"""Orchestrates the full voice -> text proxy flow.

A :class:`VadProxyPipeline` is fed raw mono int16 PCM chunks (any size). It runs
them through the VAD segmenter; each completed utterance is transcribed, refined
by the smart-layer, optionally logged for personalization, and handed to the
output adapter.

The pipeline is transport-agnostic: the file CLI and the WebSocket server both
just push PCM bytes into :meth:`feed` and call :meth:`finish` at the end.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

from vad_proxy.audio.segmenter import Segmenter, SegmenterParams, Utterance
from vad_proxy.audio.vad import SileroVad
from vad_proxy.config import Settings
from vad_proxy.llm.base import SmartLayer
from vad_proxy.llm.factory import build_smart_layer
from vad_proxy.output.base import FinalText, OutputAdapter
from vad_proxy.output.factory import build_output
from vad_proxy.personalization.base import Personalizer
from vad_proxy.personalization.factory import build_personalizer
from vad_proxy.stt.base import SttBackend
from vad_proxy.stt.factory import build_stt


@dataclass
class PipelineComponents:
    vad: SileroVad
    stt: SttBackend
    smart: SmartLayer
    output: OutputAdapter
    personalizer: Personalizer


def build_pipeline(settings: Settings) -> "VadProxyPipeline":
    """Construct a pipeline with all components wired from settings."""
    vad = SileroVad(sample_rate=settings.sample_rate)
    components = PipelineComponents(
        vad=vad,
        stt=build_stt(settings),
        smart=build_smart_layer(settings),
        output=build_output(settings),
        personalizer=build_personalizer(settings),
    )
    return VadProxyPipeline(settings, components)


class VadProxyPipeline:
    def __init__(self, settings: Settings, components: PipelineComponents):
        self.settings = settings
        self.c = components
        params = SegmenterParams(
            confidence=settings.vad_confidence,
            start_secs=settings.vad_start_secs,
            stop_secs=settings.vad_stop_secs,
            min_volume=settings.vad_min_volume,
            pre_speech_secs=settings.pre_speech_secs,
            max_utterance_secs=settings.max_utterance_secs,
        )
        self._segmenter = Segmenter(components.vad, params)
        self._chunk_bytes = components.vad.chunk_size * 2
        self._residual = b""

    async def feed(self, pcm: bytes) -> None:
        """Push arbitrary-length PCM; processes any complete VAD chunks."""
        buffer = self._residual + pcm
        offset = 0
        n = len(buffer)
        while n - offset >= self._chunk_bytes:
            chunk = buffer[offset : offset + self._chunk_bytes]
            offset += self._chunk_bytes
            utterance = self._segmenter.process_chunk(chunk)
            if utterance is not None:
                await self._handle_utterance(utterance)
        self._residual = buffer[offset:]

    async def finish(self) -> None:
        """Flush any in-progress utterance at end of stream."""
        tail = self._segmenter.flush()
        if tail is not None:
            await self._handle_utterance(tail)

    async def _handle_utterance(self, utterance: Utterance) -> None:
        transcript = await self.c.stt.transcribe(utterance.pcm, utterance.sample_rate)
        raw_text = self.c.personalizer.bias_vocabulary(transcript.text)
        if not raw_text.strip():
            return

        result = await self.c.smart.process(raw_text)

        final = FinalText(
            text=result.text,
            turn_complete=result.turn_complete,
            end_phrase=result.end_phrase,
            start_secs=utterance.start_secs,
            end_secs=utterance.end_secs,
            stt_backend=transcript.backend,
            refined=result.refined,
            meta={"stt_confidence": transcript.confidence},
        )

        # Personalization dataset logging (best-effort, never blocks output).
        await self.c.personalizer.record_sample(
            utterance.pcm,
            utterance.sample_rate,
            result.text,
            meta={"start_secs": utterance.start_secs, "end_secs": utterance.end_secs},
        )

        await self.c.output.send(final)

    async def aclose(self) -> None:
        await asyncio.gather(
            self.c.stt.aclose(),
            self.c.smart.aclose(),
            self.c.output.aclose(),
            return_exceptions=True,
        )
