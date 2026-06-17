"""Generic HTTP webhook output adapter. POSTs the final text as JSON."""

from __future__ import annotations

import httpx

from vad_proxy.output.base import FinalText, OutputAdapter


class WebhookOutputAdapter(OutputAdapter):
    name = "webhook"

    def __init__(self, url: str, timeout: float = 15.0):
        if not url:
            raise ValueError("Webhook output requires VAD_PROXY_WEBHOOK_URL")
        self.url = url
        self._client = httpx.AsyncClient(timeout=timeout)

    async def send(self, final: FinalText) -> None:
        payload = {
            "text": final.text,
            "turn_complete": final.turn_complete,
            "end_phrase": final.end_phrase,
            "start_secs": final.start_secs,
            "end_secs": final.end_secs,
            "stt_backend": final.stt_backend,
            "refined": final.refined,
            "meta": final.meta,
        }
        resp = await self._client.post(self.url, json=payload)
        resp.raise_for_status()

    async def aclose(self) -> None:
        await self._client.aclose()
