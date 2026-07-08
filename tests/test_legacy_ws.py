"""Legacy /ws endpoint deprecation."""

from __future__ import annotations

import asyncio
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest
import websockets

REPO_ROOT = Path(__file__).resolve().parents[1]
MODEL_PATH = REPO_ROOT / "models" / "silero_vad.onnx"


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


async def _expect_legacy_ws_deprecated(ws_url: str) -> None:
    async with websockets.connect(ws_url, open_timeout=10) as ws:
        msg = await asyncio.wait_for(ws.recv(), timeout=5)
        assert "deprecated" in msg.lower()
        assert "/graphql" in msg.lower()
        with pytest.raises(websockets.exceptions.ConnectionClosed) as exc_info:
            await asyncio.wait_for(ws.recv(), timeout=5)
        exc = exc_info.value
        code = exc.rcvd.code if exc.rcvd is not None else exc.code
        reason = exc.rcvd.reason if exc.rcvd is not None else exc.reason
        assert code == 1008
        assert "/graphql" in reason


@pytest.mark.skipif(not MODEL_PATH.exists(), reason="Silero model not downloaded")
def test_legacy_ws_closes_with_deprecation():
    port = 18086
    env = {
        **os.environ,
        "OMP_NUM_THREADS": "1",
        "MKL_NUM_THREADS": "1",
        "OPENBLAS_NUM_THREADS": "1",
        "VAD_PROXY_PORT": str(port),
        "VAD_PROXY_STT_BACKEND": "mock",
        "VAD_PROXY_LLM_ENABLED": "false",
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
        asyncio.run(_expect_legacy_ws_deprecated(f"ws://127.0.0.1:{port}/ws"))
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
