"""FastAPI WebSocket server: the 24/7 listener.

Clients stream raw mono signed-16-bit PCM at the configured sample rate over a
WebSocket. Each binary message is fed into a per-connection pipeline; completed
utterances are transcribed, refined, and proxied by the configured output
adapter. A text message ``"flush"`` forces any in-progress utterance out.

GraphQL-over-WebSocket (``graphql-transport-ws``) is also exposed at ``/graphql``
for token-authenticated voice streaming with base64 PCM chunks and transcript
subscriptions.
"""

from __future__ import annotations

import hmac
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


def _parse_allowed_origins(value: str) -> list[str]:
    value = value.strip()
    if not value or value == "*":
        return ["*"]
    return [part.strip() for part in value.split(",") if part.strip()]


def _token_ok(settings: Settings, provided: str | None) -> bool:
    expected = settings.auth_token
    if not expected:
        return True
    if provided is None:
        return False
    return hmac.compare_digest(str(provided), expected)


class AuthGraphQLRouter(GraphQLRouter):
    """GraphQL router that validates ``connectionParams.token`` on WS connect."""

    def __init__(self, settings: Settings, *args: Any, **kwargs: Any) -> None:
        self._settings = settings
        super().__init__(*args, **kwargs)

    async def on_ws_connect(self, context: Context) -> Any:
        params: dict[str, Any] | None = None
        if isinstance(context, dict):
            params = context.get("connection_params")
        elif hasattr(context, "connection_params"):
            params = context.connection_params
        token = None
        if isinstance(params, dict):
            token = params.get("token")
        if not _token_ok(self._settings, token):
            raise ConnectionRejectionError({"message": "invalid token"})
        return await super().on_ws_connect(context)


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or load_settings()
    session_manager = SessionManager(settings)
    app = FastAPI(title="vad-proxy", version="0.1.0")

    origins = _parse_allowed_origins(settings.allowed_origins)
    if not settings.auth_token and "*" not in origins:
        _log.warning(
            "VAD_PROXY_AUTH_TOKEN is empty — GraphQL connections are accepted "
            "without authentication"
        )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=origins != ["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    async def graphql_context() -> dict[str, SessionManager]:
        return {"session_manager": session_manager}

    graphql_router = AuthGraphQLRouter(
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
            "graphql_auth_required": bool(settings.auth_token),
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
