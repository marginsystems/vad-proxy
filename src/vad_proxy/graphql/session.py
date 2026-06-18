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

    async def aclose(self) -> None:
        """Signal the event queue that output is done."""
        self._queue.put_nowait(_EVENT_STOP)


class _EndUtterance:
    """Sentinel placed on the input queue to flush trailing audio."""


_END_UTTERANCE = _EndUtterance()
class _Stop:
    pass


class _EventStop:
    pass


_STOP = _Stop()
_EVENT_STOP = _EventStop()


def _build_session_pipeline(
    settings: Settings, event_queue: asyncio.Queue[VoiceEventData]
) -> VadProxyPipeline:
    """Build a pipeline whose output adapter feeds ``event_queue``."""
    queue_output = QueueOutputAdapter(event_queue)
    return build_pipeline(settings, output=queue_output)


class Session:
    """One live voice subscription: input queue -> pipeline -> event queue."""

    def __init__(self, session_id: str, settings: Settings) -> None:
        self.session_id = session_id
        self.settings = settings
        self._input_queue: asyncio.Queue[bytes | _EndUtterance | _Stop] = asyncio.Queue(maxsize=128)
        self._event_queue: asyncio.Queue[VoiceEventData | object] = asyncio.Queue()
        self._pipeline = _build_session_pipeline(settings, self._event_queue)
        self._stopped = False
        self._pipeline_closed = False
        self._pipeline_lock = asyncio.Lock()
        self._stop_lock = asyncio.Lock()
        self._consumer = None

    async def _consume(self) -> None:
        # Lock ordering: _consume acquires _stop_lock then _pipeline_lock.
        # stop() acquires _stop_lock, releases it, awaits _consumer, then
        # re-acquires _stop_lock — no deadlock because stop() never holds
        # _stop_lock while awaiting _consumer.
        try:
            while True:
                item = await self._input_queue.get()
                if item is _STOP:
                    async with self._stop_lock:
                        self._stopped = True
                    break
                if item is _END_UTTERANCE:
                    async with self._pipeline_lock:
                        await self._pipeline.finish()
                elif isinstance(item, bytes):
                    async with self._pipeline_lock:
                        await self._pipeline.feed(item)
            # Drain any items that arrived after _STOP (TOCTOU race with
            # append_audio).
            while True:
                try:
                    item = self._input_queue.get_nowait()
                except asyncio.QueueEmpty:
                    break
                if item is _STOP:
                    continue
                async with self._stop_lock:
                    if self._pipeline_closed:
                        _log.warning(
                            "dropping item %s after pipeline closed for session %s",
                            type(item).__name__,
                            self.session_id,
                        )
                        continue
                if item is _END_UTTERANCE:
                    async with self._pipeline_lock:
                        await self._pipeline.finish()
                elif isinstance(item, bytes):
                    async with self._pipeline_lock:
                        await self._pipeline.feed(item)
            async with self._stop_lock:
                if not self._pipeline_closed:
                    async with self._pipeline_lock:
                        await self._pipeline.finish()
                    self._pipeline_closed = True
                    await self._pipeline.aclose()
            self._event_queue.put_nowait(_EVENT_STOP)
        except asyncio.CancelledError:
            async with self._stop_lock:
                self._stopped = True
                if not self._pipeline_closed:
                    self._pipeline_closed = True
                    try:
                        await self._pipeline.aclose()
                    except Exception:
                        pass
            self._event_queue.put_nowait(_EVENT_STOP)
            raise
        except Exception:
            async with self._stop_lock:
                self._stopped = True
                if not self._pipeline_closed:
                    self._pipeline_closed = True
                    try:
                        await self._pipeline.aclose()
                    except Exception:
                        pass
            _log.exception("session %s consumer failed", self.session_id)
            await self._event_queue.put(_EVENT_STOP)
            raise

    async def append_audio(self, pcm: bytes) -> bool:
        async with self._stop_lock:
            if self._stopped:
                return False
            try:
                self._input_queue.put_nowait(pcm)
            except asyncio.QueueFull:
                return False
            return True

    async def end_utterance(self) -> bool:
        async with self._stop_lock:
            if self._stopped:
                return False
            try:
                self._input_queue.put_nowait(_END_UTTERANCE)
            except asyncio.QueueFull:
                return False
            return True

    async def iter_events(self) -> AsyncIterator[VoiceEventData]:
        if self._consumer is None:
            self._consumer = asyncio.create_task(
                self._consume(), name=f"vad-session-{self.session_id}"
            )
        while True:
            event = await self._event_queue.get()
            if event is _EVENT_STOP:
                break
            yield event

    async def stop(self) -> None:
        should_send_stop = False
        async with self._stop_lock:
            if not self._stopped:
                self._stopped = True
                should_send_stop = True
        if should_send_stop:
            try:
                await asyncio.wait_for(self._input_queue.put(_STOP), timeout=5)
            except asyncio.TimeoutError:
                if self._consumer is not None:
                    self._consumer.cancel()
        if self._consumer is not None:
            try:
                await asyncio.wait_for(self._consumer, timeout=5)
            except asyncio.TimeoutError:
                self._consumer.cancel()
                try:
                    await self._consumer
                except (Exception, asyncio.CancelledError):
                    pass
            except (Exception, asyncio.CancelledError):
                _log.exception("session %s consumer failed", self.session_id)
            return
        async with self._stop_lock:
            if not self._pipeline_closed:
                self._pipeline_closed = True
                async with self._pipeline_lock:
                    await self._pipeline.finish()
                    await self._pipeline.aclose()


class SessionManager:
    """Creates and tracks active GraphQL voice sessions."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._lock = asyncio.Lock()
        self._sessions: dict[str, Session] = {}

    async def create_session(self, sample_rate: int | None = None) -> Session:
        if sample_rate is not None and sample_rate != self.settings.sample_rate:
            _log.warning(
                "listen(sample_rate=%s) ignored; server runs at %s",
                sample_rate,
                self.settings.sample_rate,
            )
        session_id = str(uuid.uuid4())
        session = Session(session_id, self.settings)
        async with self._lock:
            self._sessions[session_id] = session
        return session

    async def get(self, session_id: str) -> Session | None:
        async with self._lock:
            return self._sessions.get(session_id)

    async def stop_session(self, session_id: str) -> bool:
        async with self._lock:
            session = self._sessions.pop(session_id, None)
        if session is None:
            return False
        await session.stop()
        return True
