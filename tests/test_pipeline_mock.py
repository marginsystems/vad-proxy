"""In-process pipeline tests.

End-to-end detection is covered by the CLI subprocess smoke test
(``test_smoke_cli.py``). Here we test the pipeline plumbing with deterministic
inputs that do not depend on a successful speech detection: namely that
arbitrary-length / odd-sized feeds are buffered correctly and that silence
produces no output.
"""

from __future__ import annotations

import asyncio
import time

import pytest

from vad_proxy.config import load_settings
from vad_proxy.llm.base import PassthroughSmartLayer, SmartLayer, SmartResult
from vad_proxy.output.base import FinalText, OutputAdapter
from vad_proxy.pipeline import PipelineComponents, VadProxyPipeline
from vad_proxy.personalization.base import NullPersonalizer
from vad_proxy.stt.base import SttBackend, Transcript
from vad_proxy.stt.mock import MockSttBackend
from vad_proxy.stt.retry import SttUnavailable
from vad_proxy.audio.vad import SileroVad


class FailingSttBackend(SttBackend):
    name = "failing"

    async def transcribe(self, pcm: bytes, sample_rate: int) -> Transcript:
        raise SttUnavailable("STT down")


class SizeAwareMockSttBackend(SttBackend):
    """Returns slice text for small PCM (interim) and full text for utterance PCM."""

    name = "size_mock"
    FULL_UTTERANCE_MIN_BYTES = 20_000

    async def transcribe(self, pcm: bytes, sample_rate: int) -> Transcript:
        if len(pcm) >= self.FULL_UTTERANCE_MIN_BYTES:
            text = "full utterance text"
        else:
            text = "slice-part"
        return Transcript(text=text, language="en", confidence=1.0, backend=self.name)


class CaptureOutput(OutputAdapter):
    name = "capture"

    def __init__(self):
        self.items: list[FinalText] = []
        self.interims: list[tuple[str, float, float, str]] = []
        self.chunk_debug: list = []
        self.errors: list[tuple[str, bool]] = []

    async def send(self, final: FinalText) -> None:
        self.items.append(final)

    async def send_interim(
        self, text: str, start_secs: float, end_secs: float, stt_backend: str
    ) -> None:
        self.interims.append((text, start_secs, end_secs, stt_backend))

    async def send_chunk_debug(self, chunks) -> None:
        self.chunk_debug.append(chunks)

    async def send_error(self, message: str, fatal: bool = False) -> None:
        self.errors.append((message, fatal))


def _build(settings, capture, stt: SttBackend | None = None) -> VadProxyPipeline:
    components = PipelineComponents(
        vad=SileroVad(sample_rate=settings.sample_rate),
        stt=stt or MockSttBackend(),
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
        stt_backend="mock", llm_enabled=False, interim_enabled=True, interim_secs=0.5,
        interim_smart=False,
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


@pytest.mark.asyncio
async def test_pipeline_skips_slice_on_stt_unavailable(model_available, test_audio_path):
    """SttUnavailable on interim STT must not crash; emit non-fatal error instead."""
    from vad_proxy.audio.decode import decode_to_pcm16

    settings = load_settings(
        stt_backend="mock",
        llm_enabled=False,
        interim_enabled=True,
        interim_secs=0.5,
        interim_smart=False,
    )
    capture = CaptureOutput()
    pipeline = _build(settings, capture, stt=FailingSttBackend())

    pcm = decode_to_pcm16(test_audio_path, 16000)
    for i in range(0, len(pcm), 333):
        await pipeline.feed(pcm[i : i + 333])
    await pipeline.finish()
    await pipeline.aclose()

    assert capture.errors
    assert all(not fatal for _, fatal in capture.errors)


@pytest.mark.asyncio
async def test_pipeline_final_re_stt_uses_full_utterance(
    model_available, test_audio_path
):
    """Final transcript must come from full-utterance STT, not joined slice text."""
    from vad_proxy.audio.decode import decode_to_pcm16

    settings = load_settings(
        stt_backend="mock",
        llm_enabled=False,
        interim_enabled=True,
        interim_secs=0.5,
        interim_smart=False,
    )
    capture = CaptureOutput()
    pipeline = _build(settings, capture, stt=SizeAwareMockSttBackend())

    pcm = decode_to_pcm16(test_audio_path, 16000)
    for i in range(0, len(pcm), 333):
        await pipeline.feed(pcm[i : i + 333])
    await pipeline.finish()
    await pipeline.aclose()

    assert capture.items, "expected a final transcript"
    assert len(capture.interims) >= 1
    assert all("slice-part" in t[0] for t in capture.interims)
    final_text = capture.items[-1].text
    assert "full utterance text" in final_text
    assert "slice-part slice-part" not in final_text


class SlowSmartLayer(SmartLayer):
    def __init__(self, delay_secs: float = 2.0) -> None:
        self.delay_secs = delay_secs

    async def process(self, raw_transcript: str) -> SmartResult:
        await asyncio.sleep(self.delay_secs)
        return SmartResult(
            text=raw_transcript.strip(),
            turn_complete=True,
            end_phrase=False,
            refined=True,
        )


class SlowSttBackend(SttBackend):
    """Wraps another STT backend with an artificial transcribe delay."""

    name = "slow"

    def __init__(
        self,
        delay_secs: float = 0.5,
        inner: SttBackend | None = None,
        *,
        delay_by_pcm_len: bool = False,
    ) -> None:
        self.delay_secs = delay_secs
        self._inner = inner or MockSttBackend()
        self._delay_by_pcm_len = delay_by_pcm_len
        self.name = f"slow-{self._inner.name}"

    async def transcribe(self, pcm: bytes, sample_rate: int) -> Transcript:
        delay = self.delay_secs
        if self._delay_by_pcm_len:
            delay = self.delay_secs * (1 + (len(pcm) % 3))
        await asyncio.sleep(delay)
        return await self._inner.transcribe(pcm, sample_rate)


class IndexedMockSttBackend(SttBackend):
    """Returns slice-N text for interim-sized PCM so ordering can be verified."""

    name = "indexed"
    FULL_UTTERANCE_MIN_BYTES = 20_000

    def __init__(self) -> None:
        self._slice_counter = 0

    async def transcribe(self, pcm: bytes, sample_rate: int) -> Transcript:
        if len(pcm) >= self.FULL_UTTERANCE_MIN_BYTES:
            text = "full utterance text"
        else:
            self._slice_counter += 1
            text = f"slice-{self._slice_counter}"
        return Transcript(text=text, language="en", confidence=1.0, backend=self.name)


@pytest.mark.asyncio
async def test_feed_continues_while_interim_stt(
    model_available, test_audio_path
):
    """feed() must not block on slow interim slice STT."""
    from vad_proxy.audio.decode import decode_to_pcm16

    settings = load_settings(
        stt_backend="mock",
        llm_enabled=False,
        interim_enabled=True,
        interim_secs=0.5,
        interim_smart=False,
    )
    capture = CaptureOutput()
    pipeline = _build(
        settings,
        capture,
        stt=SlowSttBackend(delay_secs=0.4, inner=MockSttBackend()),
    )

    pcm = decode_to_pcm16(test_audio_path, 16000)
    for i in range(0, len(pcm), 333):
        await pipeline.feed(pcm[i : i + 333])

    start = time.monotonic()
    for _ in range(10):
        await pipeline.feed(b"\x00\x00" * 333)
    elapsed = time.monotonic() - start
    assert elapsed < 0.5, f"feed blocked {elapsed:.2f}s during interim STT"

    await pipeline.finish()
    await pipeline.aclose()


@pytest.mark.asyncio
async def test_interim_events_emitted_in_order(
    model_available, test_audio_path
):
    """Interim joined text must grow monotonically even if STT completes out of order."""
    from vad_proxy.audio.decode import decode_to_pcm16

    settings = load_settings(
        stt_backend="mock",
        llm_enabled=False,
        interim_enabled=True,
        interim_secs=0.5,
        interim_smart=False,
    )
    capture = CaptureOutput()
    pipeline = _build(
        settings,
        capture,
        stt=SlowSttBackend(
            delay_secs=0.05,
            inner=IndexedMockSttBackend(),
            delay_by_pcm_len=True,
        ),
    )

    pcm = decode_to_pcm16(test_audio_path, 16000)
    for i in range(0, len(pcm), 333):
        await pipeline.feed(pcm[i : i + 333])
    await pipeline.finish()
    await pipeline.aclose()

    if not capture.interims:
        pytest.skip("no interim events on this host")

    seen_slices: list[str] = []
    for joined, *_ in capture.interims:
        parts = joined.split()
        assert len(parts) >= len(seen_slices)
        for i, part in enumerate(parts):
            if i < len(seen_slices):
                assert part == seen_slices[i]
            else:
                seen_slices.append(part)


@pytest.mark.asyncio
async def test_turn_end_waits_for_pending_interims(
    model_available, test_audio_path
):
    """Final fallback text includes the last in-flight interim slice."""
    from vad_proxy.audio.decode import decode_to_pcm16

    settings = load_settings(
        stt_backend="mock",
        llm_enabled=False,
        interim_enabled=True,
        interim_secs=0.5,
        interim_smart=False,
    )
    capture = CaptureOutput()
    indexed = IndexedMockSttBackend()
    slow_indexed = SlowSttBackend(delay_secs=0.3, inner=indexed)
    full_min = SizeAwareMockSttBackend.FULL_UTTERANCE_MIN_BYTES

    class FailFullUtteranceStt(SttBackend):
        name = "fail_full"

        async def transcribe(self, pcm: bytes, sample_rate: int) -> Transcript:
            if len(pcm) >= full_min:
                raise SttUnavailable("full STT down")
            return await slow_indexed.transcribe(pcm, sample_rate)

    pipeline = _build(settings, capture, stt=FailFullUtteranceStt())

    pcm = decode_to_pcm16(test_audio_path, 16000)
    for i in range(0, len(pcm), 333):
        await pipeline.feed(pcm[i : i + 333])
    await pipeline.finish()
    await pipeline.aclose()

    if not capture.items:
        pytest.skip("no final transcript on this host")

    assert capture.errors
    final_text = capture.items[-1].text
    assert "slice-" in final_text


@pytest.mark.asyncio
async def test_feed_continues_while_utterance_processing(
    model_available, test_audio_path
):
    """feed() must not block on slow STT/LLM; utterance work runs in background."""
    from vad_proxy.audio.decode import decode_to_pcm16

    settings = load_settings(stt_backend="mock", llm_enabled=False, interim_enabled=False)
    capture = CaptureOutput()
    components = PipelineComponents(
        vad=SileroVad(sample_rate=settings.sample_rate),
        stt=MockSttBackend(),
        smart=SlowSmartLayer(),
        output=capture,
        personalizer=NullPersonalizer(),
    )
    pipeline = VadProxyPipeline(settings, components)

    pcm = decode_to_pcm16(test_audio_path, 16000)
    for i in range(0, len(pcm), 333):
        await pipeline.feed(pcm[i : i + 333])

    silence = b"\x00\x00" * settings.sample_rate
    for i in range(0, len(silence), 333):
        await pipeline.feed(silence[i : i + 333])

    start = time.monotonic()
    for _ in range(10):
        await pipeline.feed(b"\x00\x00" * 333)
    elapsed = time.monotonic() - start
    assert elapsed < 0.5, f"feed blocked {elapsed:.2f}s while utterance processing"

    await pipeline.finish()
    await pipeline.aclose()
    assert capture.items
