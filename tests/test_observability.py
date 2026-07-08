"""Unit + health integration tests for in-process observability."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest

from vad_proxy.observability import OpStats, ServerMetrics, Timer

REPO_ROOT = Path(__file__).resolve().parents[1]
MODEL_PATH = REPO_ROOT / "models" / "silero_vad.onnx"


def test_op_stats_avg_and_errors():
    stats = OpStats()
    stats.record(100.0)
    stats.record(200.0)
    stats.record_error()
    d = stats.to_dict()
    assert d["count"] == 2
    assert d["errors"] == 1
    assert d["last_ms"] == 200.0
    assert d["avg_ms"] == 150.0


def test_server_metrics_snapshot_shape():
    m = ServerMetrics()
    m.utterances = 3
    m.interim_slices = 10
    m.stt_final.record(50.0)
    m.input_queue_full = 1
    snap = m.snapshot(
        queue_depths={
            "input_queue_max_depth": 40,
            "event_queue_max_depth": 5,
            "sessions_with_input_pressure": 0,
        }
    )
    assert snap["utterances"] == 3
    assert snap["interim_slices"] == 10
    assert snap["stt_final"]["count"] == 1
    assert snap["stt_final"]["avg_ms"] == 50.0
    assert snap["stt_interim"]["count"] == 0
    assert snap["llm"]["count"] == 0
    bp = snap["backpressure"]
    assert bp["input_queue_full"] == 1
    assert bp["input_queue_max_depth"] == 40
    assert bp["event_queue_max_depth"] == 5
    assert bp["sessions_with_input_pressure"] == 0


@pytest.mark.asyncio
async def test_timer_records_on_success():
    stats = OpStats()
    async with Timer(stats) as t:
        await __import__("asyncio").sleep(0.01)
    assert stats.count == 1
    assert t.elapsed_ms >= 5.0
    assert stats.last_ms == t.elapsed_ms


@pytest.mark.asyncio
async def test_timer_skips_record_on_error():
    stats = OpStats()
    with pytest.raises(RuntimeError):
        async with Timer(stats):
            raise RuntimeError("boom")
    assert stats.count == 0


def _wait_for_health(port: int, timeout: float = 30.0) -> None:
    deadline = time.time() + timeout
    url = f"http://127.0.0.1:{port}/health"
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=2) as resp:
                if resp.status == 200:
                    return
        except (urllib.error.URLError, TimeoutError):
            time.sleep(0.25)
    raise RuntimeError(f"server did not become healthy at {url}")


@pytest.mark.skipif(not MODEL_PATH.exists(), reason="Silero model not downloaded")
def test_health_includes_metrics_block():
    port = 18097
    env = {
        **os.environ,
        "OMP_NUM_THREADS": "1",
        "MKL_NUM_THREADS": "1",
        "OPENBLAS_NUM_THREADS": "1",
        "VAD_PROXY_PORT": str(port),
        "VAD_PROXY_STT_BACKEND": "mock",
        "VAD_PROXY_LLM_ENABLED": "false",
        "PYTHONPATH": str(REPO_ROOT / "src"),
    }
    proc = subprocess.Popen(
        [sys.executable, "-m", "vad_proxy.server"],
        cwd=str(REPO_ROOT),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        _wait_for_health(port)
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/health") as resp:
            health = json.loads(resp.read().decode())
        assert health["status"] == "ok"
        metrics = health["metrics"]
        assert "utterances" in metrics
        assert "interim_slices" in metrics
        for key in ("stt_final", "stt_interim", "llm"):
            assert set(metrics[key]) >= {"count", "errors", "last_ms", "avg_ms"}
            assert metrics[key]["count"] == 0
        bp = metrics["backpressure"]
        assert bp["input_queue_full"] == 0
        assert bp["event_queue_dropped"] == 0
        assert bp["event_queue_pressure"] == 0
        assert "input_queue_max_depth" in bp
        assert "event_queue_max_depth" in bp
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
