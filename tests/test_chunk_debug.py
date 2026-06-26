"""Tests for interim chunk debug replay events."""

from __future__ import annotations

import base64
import wave
from io import BytesIO

from vad_proxy.graphql.session import InterimChunkEvent, _chunk_to_event
from vad_proxy.output.base import InterimChunkRecord


def test_chunk_to_event_wraps_pcm_as_wav():
    pcm = (b"\x00\x01" * 800)  # 800 samples
    record = InterimChunkRecord(
        index=1,
        start_secs=0.0,
        end_secs=0.05,
        reason="dip",
        text="hello",
        pcm=pcm,
        sample_rate=16000,
    )
    event = _chunk_to_event(record)
    assert isinstance(event, InterimChunkEvent)
    assert event.reason == "dip"
    assert event.text == "hello"

    raw = base64.b64decode(event.audio_base64)
    with wave.open(BytesIO(raw), "rb") as wav:
        assert wav.getnchannels() == 1
        assert wav.getsampwidth() == 2
        assert wav.getframerate() == 16000
        assert len(wav.readframes(wav.getnframes())) == len(pcm)
