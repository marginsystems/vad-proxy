"""Voice API key validation on GraphQL WebSocket connect."""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest
import websockets

from vad_proxy.config import load_settings
from vad_proxy.server import _api_key_ok, _voice_connect_ok

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


async def _connection_init(
    ws_url: str,
    *,
    origin: str | None = None,
    connection_params: dict | None = None,
) -> dict:
    extra_headers = {"Origin": origin} if origin else None
    async with websockets.connect(
        ws_url,
        subprotocols=["graphql-transport-ws"],
        open_timeout=10,
        additional_headers=extra_headers,
    ) as ws:
        payload = connection_params if connection_params is not None else {}
        await ws.send(json.dumps({"type": "connection_init", "payload": payload}))
        while True:
            raw = await asyncio.wait_for(ws.recv(), timeout=10)
            msg = json.loads(raw)
            if msg.get("type") in ("connection_ack", "connection_error"):
                return msg


async def _expect_rejected(
    ws_url: str,
    *,
    origin: str | None = None,
    connection_params: dict | None = None,
) -> None:
    try:
        msg = await _connection_init(
            ws_url,
            origin=origin,
            connection_params=connection_params,
        )
        if msg.get("type") == "connection_ack":
            pytest.fail("expected connection rejection, got connection_ack")
        if msg.get("type") == "connection_error":
            return
    except websockets.exceptions.ConnectionClosed as exc:
        code = exc.rcvd.code if exc.rcvd is not None else exc.code
        assert code == 4403


def test_api_key_ok_unit():
    settings = load_settings(voice_api_key="secret")
    assert _api_key_ok(settings, {"apiKey": "secret"})
    assert not _api_key_ok(settings, {"apiKey": "wrong"})
    assert not _api_key_ok(settings, None)

    unset = load_settings(voice_api_key="")
    assert _api_key_ok(unset, None)


def test_voice_connect_ok_unit():
    settings = load_settings(
        voice_api_key="secret",
        allowed_origins="https://biosystems.dev",
    )
    assert _voice_connect_ok(settings, "http://localhost:5173", None)
    assert _voice_connect_ok(settings, "http://127.0.0.1:8080", None)
    assert _voice_connect_ok(
        settings, "https://biosystems.dev", {"apiKey": "secret"}
    )
    assert not _voice_connect_ok(settings, "https://biosystems.dev", None)
    assert not _voice_connect_ok(
        settings, "https://biosystems.dev", {"apiKey": "wrong"}
    )
    assert not _voice_connect_ok(settings, None, None)
    assert _voice_connect_ok(settings, None, {"apiKey": "secret"})

    unset = load_settings(voice_api_key="", allowed_origins="https://biosystems.dev")
    assert _voice_connect_ok(unset, None, None)


@pytest.mark.skipif(not MODEL_PATH.exists(), reason="Silero model not downloaded")
def test_graphql_ws_localhost_exempt_without_key():
    port = 18082
    env = {
        **os.environ,
        "OMP_NUM_THREADS": "1",
        "MKL_NUM_THREADS": "1",
        "OPENBLAS_NUM_THREADS": "1",
        "VAD_PROXY_PORT": str(port),
        "VAD_PROXY_STT_BACKEND": "mock",
        "VAD_PROXY_LLM_ENABLED": "false",
        "VAD_PROXY_VOICE_API_KEY": "secret",
        "VAD_PROXY_ALLOWED_ORIGINS": "https://biosystems.dev",
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
        assert health["voice_api_key_required"] is True

        ws_url = f"ws://127.0.0.1:{port}/graphql"
        msg = asyncio.run(
            _connection_init(ws_url, origin="http://127.0.0.1:5173")
        )
        assert msg.get("type") == "connection_ack"
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()


@pytest.mark.skipif(not MODEL_PATH.exists(), reason="Silero model not downloaded")
def test_graphql_ws_rejects_production_origin_without_key():
    port = 18083
    env = {
        **os.environ,
        "OMP_NUM_THREADS": "1",
        "MKL_NUM_THREADS": "1",
        "OPENBLAS_NUM_THREADS": "1",
        "VAD_PROXY_PORT": str(port),
        "VAD_PROXY_STT_BACKEND": "mock",
        "VAD_PROXY_LLM_ENABLED": "false",
        "VAD_PROXY_VOICE_API_KEY": "secret",
        "VAD_PROXY_ALLOWED_ORIGINS": "https://biosystems.dev",
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
        ws_url = f"ws://127.0.0.1:{port}/graphql"
        asyncio.run(
            _expect_rejected(ws_url, origin="https://biosystems.dev")
        )
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()


@pytest.mark.skipif(not MODEL_PATH.exists(), reason="Silero model not downloaded")
def test_graphql_ws_accepts_key_in_connection_params():
    port = 18084
    env = {
        **os.environ,
        "OMP_NUM_THREADS": "1",
        "MKL_NUM_THREADS": "1",
        "OPENBLAS_NUM_THREADS": "1",
        "VAD_PROXY_PORT": str(port),
        "VAD_PROXY_STT_BACKEND": "mock",
        "VAD_PROXY_LLM_ENABLED": "false",
        "VAD_PROXY_VOICE_API_KEY": "secret",
        "VAD_PROXY_ALLOWED_ORIGINS": "https://biosystems.dev",
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
        ws_url = f"ws://127.0.0.1:{port}/graphql"
        msg = asyncio.run(
            _connection_init(
                ws_url,
                origin="https://biosystems.dev",
                connection_params={"apiKey": "secret"},
            )
        )
        assert msg.get("type") == "connection_ack"
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()


@pytest.mark.skipif(not MODEL_PATH.exists(), reason="Silero model not downloaded")
def test_graphql_ws_rejects_script_without_key():
    port = 18085
    env = {
        **os.environ,
        "OMP_NUM_THREADS": "1",
        "MKL_NUM_THREADS": "1",
        "OPENBLAS_NUM_THREADS": "1",
        "VAD_PROXY_PORT": str(port),
        "VAD_PROXY_STT_BACKEND": "mock",
        "VAD_PROXY_LLM_ENABLED": "false",
        "VAD_PROXY_VOICE_API_KEY": "secret",
        "VAD_PROXY_ALLOWED_ORIGINS": "https://biosystems.dev",
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
        ws_url = f"ws://127.0.0.1:{port}/graphql"
        asyncio.run(_expect_rejected(ws_url, origin=None))
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
