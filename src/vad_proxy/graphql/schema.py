"""Strawberry GraphQL schema for voice streaming over graphql-transport-ws."""

from __future__ import annotations

import asyncio
import base64
from typing import AsyncGenerator

import strawberry

from vad_proxy.graphql.session import SessionManager, VoiceEventData


@strawberry.type
class InterimChunk:
    index: int
    start_secs: float
    end_secs: float
    reason: str
    text: str
    audio_base64: str


def _to_voice_event(data: VoiceEventData) -> "VoiceEvent":
    return VoiceEvent(
        kind=data.kind,
        session_id=data.session_id,
        text=data.text,
        turn_complete=data.turn_complete,
        end_phrase=data.end_phrase,
        start_secs=data.start_secs,
        end_secs=data.end_secs,
        stt_backend=data.stt_backend,
        interim=data.interim,
        message=data.message,
        fatal=data.fatal,
        chunks=[
            InterimChunk(
                index=c.index,
                start_secs=c.start_secs,
                end_secs=c.end_secs,
                reason=c.reason,
                text=c.text,
                audio_base64=c.audio_base64,
            )
            for c in data.chunks
        ],
    )


@strawberry.type
class VoiceEvent:
    kind: str
    session_id: strawberry.ID | None = None
    text: str | None = None
    turn_complete: bool | None = None
    end_phrase: bool | None = None
    start_secs: float | None = None
    end_secs: float | None = None
    stt_backend: str | None = None
    interim: bool = False
    message: str | None = None
    fatal: bool = False
    chunks: list[InterimChunk] | None = None


@strawberry.type
class Query:
    @strawberry.field
    def voice_api_ready(self) -> bool:
        return True


@strawberry.type
class Mutation:
    @strawberry.mutation
    async def append_audio(
        self,
        info: strawberry.Info,
        session_id: strawberry.ID,
        audio_base64: str,
    ) -> bool:
        manager: SessionManager = info.context["session_manager"]
        session = manager.get(str(session_id))
        if session is None:
            raise ValueError(f"unknown session: {session_id}")

        if len(audio_base64) * 3 // 4 > 1024 * 1024:
            raise ValueError("audio payload too large")
        try:
            pcm = base64.b64decode(audio_base64, validate=True)
        except Exception as exc:
            raise ValueError("invalid base64 audio payload") from exc
        if not pcm:
            return True
        await session.append_audio(pcm)
        return True

    @strawberry.mutation
    async def end_utterance(
        self, info: strawberry.Info, session_id: strawberry.ID
    ) -> bool:
        manager: SessionManager = info.context["session_manager"]
        session = manager.get(str(session_id))
        if session is None:
            raise ValueError(f"unknown session: {session_id}")
        await session.end_utterance()
        return True

    @strawberry.mutation
    async def stop_session(
        self, info: strawberry.Info, session_id: strawberry.ID
    ) -> bool:
        manager: SessionManager = info.context["session_manager"]
        return await manager.stop_session(str(session_id))


@strawberry.type
class Subscription:
    @strawberry.subscription
    async def listen(
        self, info: strawberry.Info, sample_rate: int = 16000
    ) -> AsyncGenerator[VoiceEvent, None]:
        manager: SessionManager = info.context["session_manager"]
        session = None
        try:
            session = manager.create_session(sample_rate)
            yield VoiceEvent(
                kind="session_started",
                session_id=strawberry.ID(session.session_id),
            )
            async for event in session.iter_events():
                event.session_id = session.session_id
                yield _to_voice_event(event)
        finally:
            if session is not None:
                await asyncio.shield(manager.stop_session(session.session_id))


schema = strawberry.Schema(
    query=Query,
    mutation=Mutation,
    subscription=Subscription,
)
