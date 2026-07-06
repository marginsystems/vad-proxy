"""Session cap and bounded event queue tests."""

from __future__ import annotations

import asyncio

import pytest

from vad_proxy.config import load_settings
from vad_proxy.audio.vad import get_shared_silero_vad_model
from vad_proxy.graphql.session import QueueOutputAdapter, SessionManager, VoiceEventData
from vad_proxy.output.base import FinalText, InterimChunkRecord


@pytest.mark.asyncio
async def test_create_session_rejects_at_max(model_available):
    settings = load_settings(max_sessions=2)
    vad_model = get_shared_silero_vad_model(settings.sample_rate)
    manager = SessionManager(settings, vad_model=vad_model)
    s1 = manager.create_session()
    s2 = manager.create_session()
    with pytest.raises(ValueError, match="max concurrent sessions"):
        manager.create_session()
    assert manager.active_sessions == 2
    await manager.stop_session(s1.session_id)
    await manager.stop_session(s2.session_id)
    assert manager.active_sessions == 0


@pytest.mark.asyncio
async def test_chunk_debug_skipped_when_queue_full():
    queue: asyncio.Queue[VoiceEventData] = asyncio.Queue(maxsize=2)
    adapter = QueueOutputAdapter(queue, maxsize=2)
    await queue.put(VoiceEventData(kind="transcript", text="a"))
    await queue.put(VoiceEventData(kind="transcript", text="b"))
    chunk = InterimChunkRecord(
        index=1,
        start_secs=0.0,
        end_secs=1.0,
        reason="dip",
        text="hi",
        pcm=b"\x00\x00",
        sample_rate=16000,
    )
    await adapter.send_chunk_debug([chunk])
    assert queue.qsize() == 2
    events = [queue.get_nowait(), queue.get_nowait()]
    kinds = {e.kind for e in events}
    assert "chunk_debug" not in kinds


@pytest.mark.asyncio
async def test_final_transcript_drains_one_on_full_queue():
    queue: asyncio.Queue[VoiceEventData] = asyncio.Queue(maxsize=2)
    adapter = QueueOutputAdapter(queue, maxsize=2)
    await queue.put(VoiceEventData(kind="transcript", interim=True, text="live"))
    await queue.put(VoiceEventData(kind="transcript", interim=True, text="live2"))

    final = FinalText(
        text="final transcript",
        turn_complete=True,
        end_phrase=False,
        start_secs=0.0,
        end_secs=1.0,
        stt_backend="mock",
    )

    async def send_final() -> None:
        await adapter.send(final)

    send_task = asyncio.create_task(send_final())
    await asyncio.wait_for(send_task, timeout=2.0)
    assert send_task.done()
    assert queue.qsize() == 2
    texts = []
    while not queue.empty():
        texts.append(queue.get_nowait().text)
    assert "final transcript" in texts
    assert "live" in texts or "live2" in texts
    assert len(texts) == 2
