"""Per-session voice pipelines for the GraphQL WebSocket API.

Each subscription gets a :class:`Session` with its own :class:`VadProxyPipeline`,
an input queue (so ``appendAudio`` stays non-blocking), and an event queue fed by
:class:`QueueOutputAdapter` whenever the pipeline emits a :class:`FinalText`.

The background consumer task is the sole owner of the pipeline: it feeds audio,
flushes on shutdown, closes resources, and signals the subscription via
``_EVENT_STOP``.
"""

from __future__ import annotations

import asyncio
import base64
import logging
import uuid
from dataclasses import dataclass, field
from typing import AsyncIterator, Literal

from vad_proxy.audio.decode import pcm16_to_wav
from vad_proxy.config import Settings
from vad_proxy.output.base import FinalText, InterimChunkRecord, OutputAdapter
from vad_proxy.pipeline import VadProxyPipeline, build_pipeline

_log = logging.getLogger(__name__)

EventKind = Literal["session_started", "transcript", "chunk_debug", "error"]

_INPUT_QUEUE_MAX = 128
_CHUNK_DEBUG_PRESSURE_RATIO = 0.75


@dataclass
class InterimChunkEvent:
    index: int
    start_secs: float
    end_secs: float
    reason: str
    text: str
    audio_base64: str


@dataclass
class VoiceEventData:
    """Internal event pushed to GraphQL subscribers."""

    kind: EventKind
    session_id: str | None = None
    text: str | None = None
    turn_complete: bool | None = None
    end_phrase: bool | None = None
    start_secs: float | None = None
    end_secs: float | None = None
    stt_backend: str | None = None
    interim: bool = False
    message: str | None = None
    fatal: bool = False
    chunks: list[InterimChunkEvent] = field(default_factory=list)


def _chunk_to_event(chunk: InterimChunkRecord) -> InterimChunkEvent:
    wav = pcm16_to_wav(chunk.pcm, chunk.sample_rate)
    return InterimChunkEvent(
        index=chunk.index,
        start_secs=chunk.start_secs,
        end_secs=chunk.end_secs,
        reason=chunk.reason,
        text=chunk.text,
        audio_base64=base64.b64encode(wav).decode("ascii"),
    )


class QueueOutputAdapter(OutputAdapter):
    """Routes pipeline output into an asyncio queue for subscription consumers."""

    name = "queue"

    def __init__(
        self, queue: asyncio.Queue[VoiceEventData], *, maxsize: int
    ) -> None:
        self._queue = queue
        self._maxsize = maxsize

    async def _put_required(self, event: VoiceEventData) -> None:
        try:
            self._queue.put_nowait(event)
        except asyncio.QueueFull:
            _log.warning(
                "required event (%s) queue full (%s/%s); draining one item to deliver",
                event.kind,
                self._queue.qsize(),
                self._maxsize,
            )
            try:
                self._queue.get_nowait()
            except asyncio.QueueEmpty:
                pass
            try:
                self._queue.put_nowait(event)
            except asyncio.QueueFull:
                pass

    def _put_best_effort(self, event: VoiceEventData) -> bool:
        try:
            self._queue.put_nowait(event)
        except asyncio.QueueFull:
            return False
        return True

    async def send(self, final: FinalText) -> None:
        await self._put_required(
            VoiceEventData(
                kind="transcript",
                text=final.text,
                turn_complete=final.turn_complete,
                end_phrase=final.end_phrase,
                start_secs=final.start_secs,
                end_secs=final.end_secs,
                stt_backend=final.stt_backend,
            )
        )

    async def send_interim(
        self, text: str, start_secs: float, end_secs: float, stt_backend: str
    ) -> None:
        if not self._put_best_effort(
            VoiceEventData(
                kind="transcript",
                interim=True,
                text=text,
                start_secs=start_secs,
                end_secs=end_secs,
                stt_backend=stt_backend,
            )
        ):
            _log.warning(
                "interim dropped: event queue full (%s/%s)",
                self._queue.qsize(),
                self._maxsize,
            )

    async def send_chunk_debug(self, chunks: list[InterimChunkRecord]) -> None:
        if not chunks:
            return
        pressure_threshold = int(self._maxsize * _CHUNK_DEBUG_PRESSURE_RATIO)
        if self._queue.qsize() >= pressure_threshold:
            _log.warning(
                "chunk_debug skipped: event queue under pressure (%s/%s)",
                self._queue.qsize(),
                self._maxsize,
            )
            if not self._put_best_effort(
                VoiceEventData(
                    kind="error",
                    message="chunk_debug skipped: event queue under pressure",
                    fatal=False,
                )
            ):
                _log.warning(
                    "error under-pressure event dropped: queue full (%s/%s)",
                    self._queue.qsize(),
                    self._maxsize,
                )
            return
        if not self._put_best_effort(
            VoiceEventData(
                kind="chunk_debug",
                start_secs=chunks[0].start_secs,
                end_secs=chunks[-1].end_secs,
                chunks=[_chunk_to_event(c) for c in chunks],
            )
        ):
            _log.warning(
                "chunk_debug skipped: event queue full (%s/%s)",
                self._queue.qsize(),
                self._maxsize,
            )
            if not self._put_best_effort(
                VoiceEventData(
                    kind="error",
                    message="chunk_debug skipped: event queue full",
                    fatal=False,
                )
            ):
                _log.warning(
                    "chunk_debug error event dropped: queue full (%s/%s)",
                    self._queue.qsize(),
                    self._maxsize,
                )

    async def send_error(self, message: str, fatal: bool = False) -> None:
        await self._put_required(
            VoiceEventData(kind="error", message=message, fatal=fatal)
        )


class _EndUtterance:
    """Sentinel placed on the input queue to flush trailing audio."""


_END_UTTERANCE = _EndUtterance()
_STOP = object()


class _EventStop(VoiceEventData):
    pass


_EVENT_STOP = _EventStop(kind="session_started")


def _build_session_pipeline(
    settings: Settings, event_queue: asyncio.Queue[VoiceEventData]
) -> VadProxyPipeline:
    """Build a pipeline whose output adapter feeds ``event_queue``."""
    return build_pipeline(
        settings,
        output=QueueOutputAdapter(event_queue, maxsize=settings.event_queue_max),
    )


class Session:
    """One live voice subscription: input queue -> pipeline -> event queue."""

    def __init__(self, session_id: str, settings: Settings) -> None:
        self.session_id = session_id
        self.settings = settings
        self._input_queue: asyncio.Queue[bytes | _EndUtterance | object] = (
            asyncio.Queue(maxsize=_INPUT_QUEUE_MAX)
        )
        self._event_queue: asyncio.Queue[VoiceEventData] = asyncio.Queue(
            maxsize=settings.event_queue_max
        )
        self._pipeline = _build_session_pipeline(settings, self._event_queue)
        self._stopped = False
        self._consumer = asyncio.create_task(
            self._consume(), name=f"vad-session-{session_id}"
        )

    async def _consume(self) -> None:
        try:
            while True:
                item = await self._input_queue.get()
                if item is _STOP:
                    break
                if item is _END_UTTERANCE:
                    await self._pipeline.finish()
                elif isinstance(item, bytes):
                    await self._pipeline.feed(item)
            await self._pipeline.finish()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            _log.exception("session %s consumer failed", self.session_id)
            await self._pipeline.output.send_error(str(exc), fatal=True)
            raise
        finally:
            try:
                await self._pipeline.aclose()
            except BaseException:
                pass
            try:
                self._event_queue.put_nowait(_EVENT_STOP)
            except asyncio.QueueFull:
                _log.warning(
                    "session %s queue full; draining one event to deliver STOP",
                    self.session_id,
                )
                try:
                    self._event_queue.get_nowait()
                except asyncio.QueueEmpty:
                    pass
                try:
                    self._event_queue.put_nowait(_EVENT_STOP)
                except asyncio.QueueFull:
                    pass

    def _enqueue(self, item: bytes | _EndUtterance) -> None:
        if self._stopped:
            raise ValueError(f"session {self.session_id} has stopped")
        try:
            self._input_queue.put_nowait(item)
        except asyncio.QueueFull as exc:
            raise ValueError(
                f"session {self.session_id} audio buffer full, retry"
            ) from exc

    async def append_audio(self, pcm: bytes) -> None:
        self._enqueue(pcm)

    async def end_utterance(self) -> None:
        self._enqueue(_END_UTTERANCE)

    async def iter_events(self) -> AsyncIterator[VoiceEventData]:
        while True:
            event = await self._event_queue.get()
            if event is _EVENT_STOP:
                break
            yield event

    async def _join_consumer(self) -> None:
        try:
            await asyncio.wait_for(self._consumer, timeout=30.0)
        except asyncio.TimeoutError:
            self._consumer.cancel()
        try:
            await self._consumer
        except asyncio.CancelledError:
            pass
        except Exception:
            pass

    async def stop(self) -> None:
        if self._stopped:
            return
        self._stopped = True
        try:
            await asyncio.wait_for(self._input_queue.put(_STOP), timeout=5.0)
        except asyncio.TimeoutError:
            self._consumer.cancel()
        await self._join_consumer()


class SessionManager:
    """Creates and tracks active GraphQL voice sessions."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._sessions: dict[str, Session] = {}

    @property
    def active_sessions(self) -> int:
        return len(self._sessions)

    def create_session(self, sample_rate: int | None = None) -> Session:
        if sample_rate is not None and sample_rate != self.settings.sample_rate:
            raise ValueError(
                f"unsupported sampleRate: {sample_rate} "
                f"(server requires {self.settings.sample_rate})"
            )
        if (
            self.settings.max_sessions
            and len(self._sessions) >= self.settings.max_sessions
        ):
            raise ValueError(
                f"max concurrent sessions ({self.settings.max_sessions}) reached"
            )
        session_id = str(uuid.uuid4())
        session = Session(session_id, self.settings)
        self._sessions[session_id] = session
        return session

    def get(self, session_id: str) -> Session | None:
        return self._sessions.get(session_id)

    async def stop_session(self, session_id: str) -> bool:
        session = self._sessions.pop(session_id, None)
        if session is None:
            return False
        await session.stop()
        return True
