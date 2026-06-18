"""FastAPI WebSocket server: the 24/7 listener.

Clients stream raw mono signed-16-bit PCM at the configured sample rate over a
WebSocket. Each binary message is fed into a per-connection pipeline; completed
utterances are transcribed, refined, and proxied by the configured output
adapter. A text message ``"flush"`` forces any in-progress utterance out.

GraphQL-over-WebSocket (``graphql-transport-ws``) is also exposed at ``/graphql``
for origin-restricted voice streaming with base64 PCM chunks and transcript
subscriptions.
"""

from __future__ import annotations

import logging
from typing import Any

_log = logging.getLogger(__name__)

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from strawberry.exceptions import ConnectionRejectionError
from strawberry.fastapi import GraphQLRouter
from strawberry.http.typevars import Context

from vad_proxy.config import Settings, load_settings
from vad_proxy.graphql.schema import schema
from vad_proxy.graphql.session import SessionManager
from vad_proxy.logging_setup import configure_logging
from vad_proxy.pipeline import build_pipeline

_LOCALHOST_ORIGIN_PREFIXES = ("http://localhost", "http://127.0.0.1")


def _parse_configured_origins(value: str) -> list[str]:
    value = value.strip()
    if not value:
        return []
    return [part.strip() for part in value.split(",") if part.strip()]


def _is_localhost_origin(origin: str) -> bool:
    return origin.startswith(_LOCALHOST_ORIGIN_PREFIXES)


def _effective_origins(settings: Settings) -> list[str]:
    """Origins permitted for CORS and GraphQL WS (localhost always included)."""
    configured = _parse_configured_origins(settings.allowed_origins)
    localhost = list(_LOCALHOST_ORIGIN_PREFIXES)
    seen: set[str] = set()
    result: list[str] = []
    for origin in localhost + configured:
        if origin not in seen:
            seen.add(origin)
            result.append(origin)
    return result


def _origin_ok(settings: Settings, origin: str | None) -> bool:
    if origin is None:
        return True
    if _is_localhost_origin(origin):
        return True
    return origin in _parse_configured_origins(settings.allowed_origins)


class OriginGraphQLRouter(GraphQLRouter):
    """GraphQL router that validates the browser ``Origin`` header on WS connect."""

    def __init__(self, settings: Settings, *args: Any, **kwargs: Any) -> None:
        self._settings = settings
        super().__init__(*args, **kwargs)

    async def on_ws_connect(self, context: Context) -> Any:
        request = None
        if isinstance(context, dict):
            request = context.get("request")
        elif hasattr(context, "request"):
            request = context.request
        origin = request.headers.get("origin") if request is not None else None
        if not _origin_ok(self._settings, origin):
            raise ConnectionRejectionError({"message": "origin not allowed"})
        return await super().on_ws_connect(context)


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or load_settings()
    session_manager = SessionManager(settings)
    app = FastAPI(title="vad-proxy", version="0.1.0")

    origins = _effective_origins(settings)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    async def graphql_context() -> dict[str, SessionManager]:
        return {"session_manager": session_manager}

    graphql_router = OriginGraphQLRouter(
        settings,
        schema,
        context_getter=graphql_context,
        graphql_ide=None,
    )
    app.include_router(graphql_router, prefix="/graphql")

    @app.get("/health")
    async def health() -> dict:
        return {
            "status": "ok",
            "sample_rate": settings.sample_rate,
            "stt_backend": settings.stt_backend,
            "llm_enabled": settings.llm_enabled,
            "output": settings.output,
            "allowed_origins": _effective_origins(settings),
        }

    @app.websocket("/ws")
    async def ws(websocket: WebSocket) -> None:
        await websocket.accept()
        pipeline = build_pipeline(settings)
        try:
            while True:
                message = await websocket.receive()
                if message["type"] == "websocket.disconnect":
                    break
                if message.get("bytes") is not None:
                    await pipeline.feed(message["bytes"])
                elif message.get("text") is not None:
                    if message["text"].strip().lower() == "flush":
                        await pipeline.finish()
        except WebSocketDisconnect:
            pass
        finally:
            await pipeline.finish()
            await pipeline.aclose()

    return app


def main() -> None:
    import uvicorn

    settings = load_settings()
    configure_logging(settings)
    uvicorn.run(
        create_app(settings),
        host=settings.host,
        port=settings.port,
        log_config=None,
    )


if __name__ == "__main__":
    main()
