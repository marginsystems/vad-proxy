"""Per-session voice pipelines for the GraphQL WebSocket API.

Each subscription gets a :class:`Session` with its own :class:`VadProxyPipeline`,
an input queue (so ``appendAudio`` stays non-blocking), and an event queue fed by
:class:`QueueOutputAdapter` whenever the pipeline emits a :class:`FinalText`.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from dataclasses import dataclass
from typing import AsyncIterator, Literal

from vad_proxy.config import Settings
from vad_proxy.output.base import FinalText, OutputAdapter
from vad_proxy.pipeline import VadProxyPipeline, build_pipeline

_log = logging.getLogger(__name__)

EventKind = Literal["session_started", "transcript"]


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


class QueueOutputAdapter(OutputAdapter):
    """Routes pipeline output into an asyncio queue for subscription consumers."""

    name = "queue"

    def __init__(self, queue: asyncio.Queue[VoiceEventData]) -> None:
        self._queue = queue

    async def send(self, final: FinalText) -> None:
        await self._queue.put(
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


class _EndUtterance:
    """Sentinel placed on the input queue to flush trailing audio."""


_END_UTTERANCE = _EndUtterance()
_STOP = object()
_EVENT_STOP = object()


def _build_session_pipeline(
    settings: Settings, event_queue: asyncio.Queue[VoiceEventData]
) -> tuple[VadProxyPipeline, OutputAdapter]:
    """Build a pipeline whose output adapter feeds ``event_queue``."""
    base = build_pipeline(settings)
    old_output = base.c.output
    base.c.output = QueueOutputAdapter(event_queue)
    return base, old_output


class Session:
    """One live voice subscription: input queue -> pipeline -> event queue."""

    def __init__(self, session_id: str, settings: Settings) -> None:
        self.session_id = session_id
        self.settings = settings
        self._input_queue: asyncio.Queue[bytes | _EndUtterance | object] = (
            asyncio.Queue(maxsize=100)
        )
        self._event_queue: asyncio.Queue[VoiceEventData | object] = asyncio.Queue()
        self._pipeline, self._original_output = _build_session_pipeline(
            settings, self._event_queue
        )
        self._stopped = False
        self._pipeline_lock = asyncio.Lock()
        self._consumer = asyncio.create_task(
            self._consume(), name=f"vad-session-{session_id}"
        )

    async def _consume(self) -> None:
        try:
            while True:
                item = await self._input_queue.get()
                if item is _STOP or self._stopped:
                    break
                if item is _END_UTTERANCE:
                    async with self._pipeline_lock:
                        await self._pipeline.finish()
                elif isinstance(item, bytes):
                    async with self._pipeline_lock:
                        await self._pipeline.feed(item)
        except asyncio.CancelledError:
            self._stopped = True
            await self._event_queue.put(_EVENT_STOP)
        except Exception:
            _log.exception("session %s consumer failed", self.session_id)
            await self._event_queue.put(_EVENT_STOP)
            self._stopped = True

    async def append_audio(self, pcm: bytes) -> None:
        await self._input_queue.put(pcm)
        if self._stopped:
            raise RuntimeError("session stopped")

    async def end_utterance(self) -> None:
        if self._stopped:
            return
        await self._input_queue.put(_END_UTTERANCE)

    async def iter_events(self) -> AsyncIterator[VoiceEventData]:
        while not self._stopped:
            event = await self._event_queue.get()
            if event is _EVENT_STOP:
                break
            yield event

    async def stop(self) -> None:
        if not self._stopped:
            self._stopped = True
            await self._input_queue.put(_STOP)
            async with self._pipeline_lock:
                await self._pipeline.finish()
            await self._event_queue.put(_EVENT_STOP)
        try:
            await self._consumer
        finally:
            await self._pipeline.aclose()
            await self._original_output.aclose()


class SessionManager:
    """Creates and tracks active GraphQL voice sessions."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._sessions: dict[str, Session] = {}

    def create_session(self, sample_rate: int | None = None) -> Session:
        if sample_rate is not None and sample_rate != self.settings.sample_rate:
            _log.warning(
                "listen(sample_rate=%s) ignored; server runs at %s",
                sample_rate,
                self.settings.sample_rate,
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
