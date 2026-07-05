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
import logging
from collections import deque
from dataclasses import dataclass

from vad_proxy.audio.segmenter import InterimSlice, Segmenter, SegmenterParams, Utterance
from vad_proxy.audio.vad import SileroVad
from vad_proxy.config import Settings
from vad_proxy.llm.base import SmartLayer
from vad_proxy.llm.factory import build_smart_layer
from vad_proxy.output.base import FinalText, InterimChunkRecord, OutputAdapter
from vad_proxy.output.factory import build_output
from vad_proxy.personalization.base import Personalizer
from vad_proxy.personalization.factory import build_personalizer
from vad_proxy.stt.base import SttBackend, Transcript
from vad_proxy.stt.factory import build_stt
from vad_proxy.stt.retry import SttUnavailable

_log = logging.getLogger(__name__)
_transcript_log = logging.getLogger("vad_proxy.transcript")

_INTERIM_STT_MAX_IN_FLIGHT = 2


@dataclass
class PipelineComponents:
    vad: SileroVad
    stt: SttBackend
    smart: SmartLayer
    output: OutputAdapter
    personalizer: Personalizer


@dataclass
class _PendingInterimSlice:
    slice: InterimSlice
    slice_index: int
    epoch: int


@dataclass
class _InterimSliceResult:
    epoch: int
    slice: InterimSlice
    text: str
    transcript: Transcript | None


def build_pipeline(
    settings: Settings, output: OutputAdapter | None = None
) -> "VadProxyPipeline":
    """Construct a pipeline with all components wired from settings."""
    vad = SileroVad(sample_rate=settings.sample_rate)
    components = PipelineComponents(
        vad=vad,
        stt=build_stt(settings),
        smart=build_smart_layer(settings),
        output=build_output(settings) if output is None else output,
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
            interim_chunk_secs=(
                settings.interim_secs if settings.interim_enabled else 0.0
            ),
            interim_min_secs=settings.interim_min_secs,
            interim_smart=settings.interim_smart if settings.interim_enabled else False,
            interim_dip_ratio=settings.interim_dip_ratio,
            interim_dip_hold_secs=settings.interim_dip_hold_secs,
        )
        self._segmenter = Segmenter(components.vad, params)
        self._chunk_bytes = components.vad.chunk_size * 2
        self._residual = b""
        self._turn_texts: list[str] = []
        self._turn_stt_backend = ""
        self._turn_stt_confidence: float | None = None
        self._turn_epoch = 0
        self._turn_debug_chunks: list[InterimChunkRecord] = []
        self._utterance_tasks: set[asyncio.Task] = set()
        self._interim_tasks: set[asyncio.Task] = set()
        self._pending_interim_slices: deque[_PendingInterimSlice] = deque()
        self._interim_results: dict[int, _InterimSliceResult] = {}
        self._interim_emit_upto = 0
        self._next_slice_index = 0
        self._interim_lock = asyncio.Lock()

    async def _schedule_utterance(self, utterance: Utterance) -> None:
        if self.settings.interim_enabled:
            await self._drain_and_schedule_interims()
            await self._await_pending_interims()
            joined_text = " ".join(self._turn_texts)
            debug_chunks = list(self._turn_debug_chunks)
            self._turn_texts.clear()
            self._turn_stt_backend = ""
            self._turn_stt_confidence = None
            self._turn_debug_chunks.clear()
            self._turn_epoch = self._segmenter.utterance_epoch
            self._reset_interim_slice_state()
        else:
            joined_text = ""
            debug_chunks: list[InterimChunkRecord] = []
        task = asyncio.create_task(
            self._handle_utterance(utterance, joined_text, debug_chunks)
        )
        self._utterance_tasks.add(task)
        task.add_done_callback(self._utterance_tasks.discard)

    async def _await_pending_utterances(self) -> None:
        if not self._utterance_tasks:
            return
        await asyncio.gather(*self._utterance_tasks, return_exceptions=True)

    async def _await_pending_interims(self) -> None:
        while self._interim_tasks or self._pending_interim_slices:
            await self._pump_interim_queue()
            if not self._interim_tasks:
                continue
            await asyncio.gather(*self._interim_tasks, return_exceptions=True)

    def _reset_interim_slice_state(self) -> None:
        self._next_slice_index = 0
        self._interim_results.clear()
        self._interim_emit_upto = 0
        self._pending_interim_slices.clear()

    def _reset_turn_if_new_utterance(self) -> None:
        epoch = self._segmenter.utterance_epoch
        if epoch != self._turn_epoch:
            self._turn_texts.clear()
            self._turn_stt_backend = ""
            self._turn_stt_confidence = None
            self._turn_debug_chunks.clear()
            self._turn_epoch = epoch
            self._reset_interim_slice_state()

    async def feed(self, pcm: bytes) -> None:
        """Push arbitrary-length PCM; processes any complete VAD chunks."""
        buffer = self._residual + pcm
        offset = 0
        n = len(buffer)
        while n - offset >= self._chunk_bytes:
            chunk = buffer[offset : offset + self._chunk_bytes]
            offset += self._chunk_bytes
            utterance = self._segmenter.process_chunk(chunk)
            if self.settings.interim_enabled:
                await self._drain_and_schedule_interims()
            if utterance is not None:
                await self._schedule_utterance(utterance)
        self._residual = buffer[offset:]

    async def finish(self) -> None:
        """Flush any in-progress utterance at end of stream."""
        tail = self._segmenter.flush()
        if tail is not None:
            if self.settings.interim_enabled:
                self._reset_turn_if_new_utterance()
                await self._drain_and_schedule_interims()
            await self._schedule_utterance(tail)
        await self._await_pending_interims()
        await self._await_pending_utterances()

    async def _drain_and_schedule_interims(self) -> None:
        self._reset_turn_if_new_utterance()
        while True:
            interim_slice = self._segmenter.drain_interim()
            if interim_slice is None:
                break
            pending = _PendingInterimSlice(
                slice=interim_slice,
                slice_index=self._next_slice_index,
                epoch=self._turn_epoch,
            )
            self._next_slice_index += 1
            self._pending_interim_slices.append(pending)
        await self._pump_interim_queue()

    async def _pump_interim_queue(self) -> None:
        while (
            self._pending_interim_slices
            and len(self._interim_tasks) < _INTERIM_STT_MAX_IN_FLIGHT
        ):
            pending = self._pending_interim_slices.popleft()
            task = asyncio.create_task(self._handle_interim_slice(pending))
            self._interim_tasks.add(task)
            task.add_done_callback(self._interim_tasks.discard)

    async def _handle_interim_slice(self, pending: _PendingInterimSlice) -> None:
        try:
            if pending.epoch != self._turn_epoch:
                return
            try:
                transcript = await self.c.stt.transcribe(
                    pending.slice.pcm, self.settings.sample_rate
                )
            except SttUnavailable as exc:
                await self.c.output.send_error(str(exc), fatal=False)
                await self._store_interim_result(
                    pending.slice_index,
                    _InterimSliceResult(
                        epoch=pending.epoch,
                        slice=pending.slice,
                        text="",
                        transcript=None,
                    ),
                )
                return
            text = transcript.text.strip()
            await self._store_interim_result(
                pending.slice_index,
                _InterimSliceResult(
                    epoch=pending.epoch,
                    slice=pending.slice,
                    text=text,
                    transcript=transcript,
                ),
            )
        finally:
            await self._pump_interim_queue()

    async def _store_interim_result(
        self, slice_index: int, result: _InterimSliceResult
    ) -> None:
        async with self._interim_lock:
            self._interim_results[slice_index] = result
            await self._flush_ordered_interims()

    async def _flush_ordered_interims(self) -> None:
        while self._interim_emit_upto in self._interim_results:
            result = self._interim_results.pop(self._interim_emit_upto)
            self._interim_emit_upto += 1
            if result.epoch != self._turn_epoch:
                continue
            interim_slice = result.slice
            text = result.text
            transcript = result.transcript
            if self.settings.debug_interim_chunks:
                self._turn_debug_chunks.append(
                    InterimChunkRecord(
                        index=len(self._turn_debug_chunks) + 1,
                        start_secs=interim_slice.start_secs,
                        end_secs=interim_slice.end_secs,
                        reason=interim_slice.reason or "unknown",
                        text=text,
                        pcm=interim_slice.pcm,
                        sample_rate=self.settings.sample_rate,
                    )
                )
            if not text:
                continue
            self._turn_texts.append(text)
            if transcript is not None:
                if not self._turn_stt_backend:
                    self._turn_stt_backend = transcript.backend
                self._turn_stt_confidence = transcript.confidence
                backend = transcript.backend
            else:
                backend = self.c.stt.name
            joined = " ".join(self._turn_texts)
            await self.c.output.send_interim(
                joined,
                interim_slice.start_secs,
                interim_slice.end_secs,
                backend,
            )

    async def _handle_utterance(
        self, utterance: Utterance, joined_text: str, debug_chunks: list[InterimChunkRecord]
    ) -> None:
        try:
            turn_confidence: float | None = None
            if self.settings.interim_enabled:
                try:
                    transcript = await self.c.stt.transcribe(
                        utterance.pcm, utterance.sample_rate
                    )
                    raw_text = self.c.personalizer.bias_vocabulary(transcript.text)
                    stt_backend = transcript.backend
                    turn_confidence = transcript.confidence
                except SttUnavailable as exc:
                    await self.c.output.send_error(str(exc), fatal=False)
                    raw_text = self.c.personalizer.bias_vocabulary(joined_text)
                    stt_backend = self.c.stt.name
                    turn_confidence = None
                if not raw_text.strip():
                    if self.settings.debug_interim_chunks and debug_chunks:
                        await self.c.output.send_chunk_debug(debug_chunks)
                    return
            else:
                try:
                    transcript = await self.c.stt.transcribe(
                        utterance.pcm, utterance.sample_rate
                    )
                except SttUnavailable as exc:
                    await self.c.output.send_error(str(exc), fatal=False)
                    return
                raw_text = self.c.personalizer.bias_vocabulary(transcript.text)
                stt_backend = transcript.backend
                if not raw_text.strip():
                    return

            result = await self.c.smart.process(raw_text)

            final = FinalText(
                text=result.text,
                turn_complete=result.turn_complete,
                end_phrase=result.end_phrase,
                start_secs=utterance.start_secs,
                end_secs=utterance.end_secs,
                stt_backend=stt_backend,
                refined=result.refined,
                meta={},
            )
            if not self.settings.interim_enabled:
                final.meta["stt_confidence"] = transcript.confidence
            elif turn_confidence is not None:
                final.meta["stt_confidence"] = turn_confidence

            await self.c.personalizer.record_sample(
                utterance.pcm,
                utterance.sample_rate,
                result.text,
                meta={"start_secs": utterance.start_secs, "end_secs": utterance.end_secs},
            )

            _transcript_log.info(
                "[%.2f-%.2f] %s%s",
                final.start_secs,
                final.end_secs,
                final.text,
                "" if final.turn_complete else " [partial]",
            )

            await self.c.output.send(final)
            if self.settings.debug_interim_chunks and debug_chunks:
                await self.c.output.send_chunk_debug(debug_chunks)
        except Exception:
            _log.exception("unhandled error processing utterance")
            await self.c.output.send_error("internal error processing utterance", fatal=True)

    async def aclose(self) -> None:
        await self._await_pending_interims()
        await self._await_pending_utterances()
        await asyncio.gather(
            self.c.stt.aclose(),
            self.c.smart.aclose(),
            self.c.output.aclose(),
            return_exceptions=True,
        )
