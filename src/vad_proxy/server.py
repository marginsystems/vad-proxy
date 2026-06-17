"""FastAPI WebSocket server: the 24/7 listener.

Clients stream raw mono signed-16-bit PCM at the configured sample rate over a
WebSocket. Each binary message is fed into a per-connection pipeline; completed
utterances are transcribed, refined, and proxied by the configured output
adapter. A text message ``"flush"`` forces any in-progress utterance out.
"""

from __future__ import annotations

from fastapi import FastAPI, WebSocket, WebSocketDisconnect

from vad_proxy.config import Settings, load_settings
from vad_proxy.pipeline import build_pipeline


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or load_settings()
    app = FastAPI(title="vad-proxy", version="0.1.0")

    @app.get("/health")
    async def health() -> dict:
        return {
            "status": "ok",
            "sample_rate": settings.sample_rate,
            "stt_backend": settings.stt_backend,
            "llm_enabled": settings.llm_enabled,
            "output": settings.output,
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
    uvicorn.run(create_app(settings), host=settings.host, port=settings.port)


if __name__ == "__main__":
    main()
