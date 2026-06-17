"""Offline mock STT backend for development and tests.

Returns a canned transcript (optionally derived from utterance duration) so the
full pipeline can be exercised with no API keys or network.
"""

from __future__ import annotations

from vad_proxy.audio.decode import pcm_duration_secs
from vad_proxy.stt.base import SttBackend, Transcript


class MockSttBackend(SttBackend):
    name = "mock"

    def __init__(self, canned_text: str = "hello this is a test one two three"):
        self.canned_text = canned_text

    async def transcribe(self, pcm: bytes, sample_rate: int) -> Transcript:
        # Touch the audio so the mock behaves like a real backend (and so empty
        # audio yields an empty transcript).
        if pcm_duration_secs(pcm, sample_rate) <= 0:
            return Transcript(text="", language="en", backend=self.name)
        return Transcript(
            text=self.canned_text, language="en", confidence=1.0, backend=self.name
        )
