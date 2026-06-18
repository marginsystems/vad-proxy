"""GraphQL-over-WebSocket integration test (subprocess + graphql-transport-ws).

Exercises token auth, the ``listen`` subscription, and ``appendAudio`` mutations
by streaming PCM from the bundled test MP3 through the live server.
"""

from __future__ import annotations

import asyncio
import base64
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

REPO_ROOT = Path(__file__).resolve().parents[1]
TEST_AUDIO = REPO_ROOT / "tests" / "data" / "test-123.mp3"
MODEL_PATH = REPO_ROOT / "models" / "silero_vad.onnx"
MAX_ATTEMPTS = 6
AUTH_TOKEN = "test-graphql-token"
EXPECTED = "hello this is a test"

LISTEN_QUERY = """
subscription Listen {
  listen(sampleRate: 16000) {
    kind
    sessionId
    text
    turnComplete
  }
}
"""

APPEND_MUTATION = """
mutation Append($sessionId: ID!, $audio: String!) {
  appendAudio(sessionId: $sessionId, audioBase64: $audio)
}
"""

END_MUTATION = """
mutation End($sessionId: ID!) {
  endUtterance(sessionId: $sessionId)
}
"""


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


def _pcm_chunks(path: Path, chunk_samples: int = 8000) -> list[str]:
    from vad_proxy.audio.decode import decode_to_pcm16

    pcm = decode_to_pcm16(path, sample_rate=16000)
    chunks: list[str] = []
    step = chunk_samples * 2
    for offset in range(0, len(pcm), step):
        chunks.append(base64.b64encode(pcm[offset : offset + step]).decode("ascii"))
    return chunks


async def _graphql_ws_round_trip(
    ws_url: str,
    token: str | None,
    audio_chunks: list[str],
    *,
    wait_for_transcript: bool = True,
) -> list[dict]:
    """Run listen + appendAudio over graphql-transport-ws; return transcript events."""
    subprotocol = "graphql-transport-ws"
    events: list[dict] = []
    session_id: str | None = None

    async with websockets.connect(
        ws_url,
        subprotocols=[subprotocol],
        open_timeout=10,
    ) as ws:
        await ws.send(
            json.dumps(
                {
                    "type": "connection_init",
                    "payload": {"token": token} if token else {},
                }
            )
        )
        while True:
            raw = await asyncio.wait_for(ws.recv(), timeout=10)
            msg = json.loads(raw)
            if msg.get("type") == "connection_ack":
                break
            if msg.get("type") == "connection_error":
                raise RuntimeError(msg)

        sub_id = "sub-1"
        await ws.send(
            json.dumps(
                {
                    "id": sub_id,
                    "type": "subscribe",
                    "payload": {"query": LISTEN_QUERY},
                }
            )
        )

        async def _send_mutation(query: str, variables: dict, mid: str) -> None:
            await ws.send(
                json.dumps(
                    {
                        "id": mid,
                        "type": "subscribe",
                        "payload": {"query": query, "variables": variables},
                    }
                )
            )

        mut_idx = 0
        audio_sent = False
        end_sent = False

        while True:
            raw = await asyncio.wait_for(ws.recv(), timeout=120)
            msg = json.loads(raw)
            mtype = msg.get("type")
            mid = msg.get("id")

            if mtype == "next" and mid == sub_id:
                data = msg.get("payload", {}).get("data", {}).get("listen")
                if data:
                    events.append(data)
                    if data.get("kind") == "session_started":
                        session_id = data.get("sessionId")
                        if session_id and not audio_sent:
                            for chunk in audio_chunks:
                                mut_idx += 1
                                await _send_mutation(
                                    APPEND_MUTATION,
                                    {
                                        "sessionId": session_id,
                                        "audio": chunk,
                                    },
                                    f"mut-{mut_idx}",
                                )
                            mut_idx += 1
                            await _send_mutation(
                                END_MUTATION,
                                {"sessionId": session_id},
                                f"mut-{mut_idx}",
                            )
                            audio_sent = True
                            end_sent = True
                            if not wait_for_transcript:
                                return events
                    if data.get("kind") == "transcript":
                        return events
            elif mtype in ("complete", "error"):
                if mid == sub_id and not end_sent and session_id:
                    end_sent = True
                    mut_idx += 1
                    await _send_mutation(
                        END_MUTATION,
                        {"sessionId": session_id},
                        f"mut-{mut_idx}",
                    )

    return events


async def _expect_rejected(ws_url: str, token: str) -> None:
    try:
        async with websockets.connect(
            ws_url,
            subprotocols=["graphql-transport-ws"],
            open_timeout=10,
        ) as ws:
            while True:
                raw = await asyncio.wait_for(ws.recv(), timeout=10)
                if raw:
                    msg = json.loads(raw)
                    if msg.get("type") == "connection_ack":
                        pytest.fail("expected connection rejection, got connection_ack")
    except websockets.exceptions.ConnectionClosed as exc:
        if exc.code != 4403:
            pytest.fail(f"expected close code 4403, got {exc.code}")


@pytest.mark.skipif(not TEST_AUDIO.exists(), reason="bundled test audio missing")
@pytest.mark.skipif(not MODEL_PATH.exists(), reason="Silero model not downloaded")
def test_graphql_ws_transcript_and_auth():
    port = 18080
    env = {
        **os.environ,
        "OMP_NUM_THREADS": "1",
        "MKL_NUM_THREADS": "1",
        "OPENBLAS_NUM_THREADS": "1",
        "VAD_PROXY_PORT": str(port),
        "VAD_PROXY_STT_BACKEND": "mock",
        "VAD_PROXY_LLM_ENABLED": "false",
        "VAD_PROXY_AUTH_TOKEN": AUTH_TOKEN,
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
        chunks = _pcm_chunks(TEST_AUDIO)

        # Bad token should be rejected.
        asyncio.run(_expect_rejected(ws_url, "wrong-token"))

        last_events: list[dict] = []
        for _ in range(MAX_ATTEMPTS):
            last_events = asyncio.run(
                _graphql_ws_round_trip(ws_url, AUTH_TOKEN, chunks)
            )
            transcripts = [
                e.get("text", "").lower()
                for e in last_events
                if e.get("kind") == "transcript"
            ]
            if any(EXPECTED in t for t in transcripts):
                return
        pytest.fail(
            f"No transcript matched {EXPECTED!r} in {MAX_ATTEMPTS} attempts. "
            f"Events: {last_events!r}"
        )
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()


@pytest.mark.skipif(not TEST_AUDIO.exists(), reason="bundled test audio missing")
@pytest.mark.skipif(not MODEL_PATH.exists(), reason="Silero model not downloaded")
def test_graphql_ws_no_auth_when_token_unset():
    port = 18081
    env = {
        **os.environ,
        "OMP_NUM_THREADS": "1",
        "MKL_NUM_THREADS": "1",
        "OPENBLAS_NUM_THREADS": "1",
        "VAD_PROXY_PORT": str(port),
        "VAD_PROXY_STT_BACKEND": "mock",
        "VAD_PROXY_LLM_ENABLED": "false",
        "VAD_PROXY_AUTH_TOKEN": "",
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
        events = asyncio.run(
            _graphql_ws_round_trip(
                f"ws://127.0.0.1:{port}/graphql",
                token=None,
                audio_chunks=_pcm_chunks(TEST_AUDIO)[:1],
                wait_for_transcript=False,
            )
        )
        assert any(e.get("kind") == "session_started" for e in events)
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
