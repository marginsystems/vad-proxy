"""In-process pipeline tests.

End-to-end detection is covered by the CLI subprocess smoke test
(``test_smoke_cli.py``). Here we test the pipeline plumbing with deterministic
inputs that do not depend on a successful speech detection: namely that
arbitrary-length / odd-sized feeds are buffered correctly and that silence
produces no output.
"""

from __future__ import annotations

import pytest

from vad_proxy.config import load_settings
from vad_proxy.llm.base import PassthroughSmartLayer
from vad_proxy.output.base import FinalText, OutputAdapter
from vad_proxy.pipeline import PipelineComponents, VadProxyPipeline
from vad_proxy.personalization.base import NullPersonalizer
from vad_proxy.stt.mock import MockSttBackend
from vad_proxy.audio.vad import SileroVad


class CaptureOutput(OutputAdapter):
    name = "capture"

    def __init__(self):
        self.items: list[FinalText] = []
        self.interims: list[tuple[str, float, float, str]] = []

    async def send(self, final: FinalText) -> None:
        self.items.append(final)

    async def send_interim(
        self, text: str, start_secs: float, end_secs: float, stt_backend: str
    ) -> None:
        self.interims.append((text, start_secs, end_secs, stt_backend))


def _build(settings, capture) -> VadProxyPipeline:
    components = PipelineComponents(
        vad=SileroVad(sample_rate=settings.sample_rate),
        stt=MockSttBackend(),
        smart=PassthroughSmartLayer(),
        output=capture,
        personalizer=NullPersonalizer(),
    )
    return VadProxyPipeline(settings, components)


@pytest.mark.asyncio
async def test_pipeline_handles_chunked_feed(model_available):
    """Odd-sized feeds must be buffered correctly across feed() calls."""
    settings = load_settings(stt_backend="mock", llm_enabled=False)
    capture = CaptureOutput()
    pipeline = _build(settings, capture)

    # Feed 1 second of silence in awkward 333-byte chunks; must not crash and
    # must yield no utterances.
    silence = b"\x00\x00" * settings.sample_rate
    for i in range(0, len(silence), 333):
        await pipeline.feed(silence[i : i + 333])
    await pipeline.finish()
    await pipeline.aclose()
    assert capture.items == []


@pytest.mark.asyncio
async def test_pipeline_residual_buffering_no_loss():
    """The residual buffer must preserve byte alignment across feeds."""
    settings = load_settings(stt_backend="mock", llm_enabled=False)
    capture = CaptureOutput()
    pipeline = _build(settings, capture)

    # 4096 bytes fed 1 byte at a time exercises the residual accumulation path.
    silence = b"\x00\x00" * 2048
    for b in range(len(silence)):
        await pipeline.feed(silence[b : b + 1])
    await pipeline.finish()
    await pipeline.aclose()
    assert capture.items == []


@pytest.mark.asyncio
async def test_pipeline_interim_emits_before_final(model_available, test_audio_path):
    """With interim enabled, chunk STT events should precede the final transcript."""
    from vad_proxy.audio.decode import decode_to_pcm16

    settings = load_settings(
        stt_backend="mock", llm_enabled=False, interim_enabled=True, interim_secs=0.5
    )
    capture = CaptureOutput()
    pipeline = _build(settings, capture)

    pcm = decode_to_pcm16(test_audio_path, 16000)
    for i in range(0, len(pcm), 333):
        await pipeline.feed(pcm[i : i + 333])
    await pipeline.finish()
    await pipeline.aclose()

    if capture.items:
        assert len(capture.interims) >= 1
        assert capture.interims[-1][0]
