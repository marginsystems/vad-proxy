"""DeepSeek smart-layer over an OpenAI-compatible chat completions API.

Sends the raw transcript with a structured prompt and parses a small JSON
response containing the corrected text plus a turn-completion judgment. Any
failure degrades gracefully to a passthrough result so the pipeline never
breaks on an LLM hiccup.
"""

from __future__ import annotations

import json

import httpx

from vad_proxy.llm.base import SmartLayer, SmartResult
from vad_proxy.llm.prompts import SYSTEM_PROMPT, build_user_prompt


class DeepSeekSmartLayer(SmartLayer):
    def __init__(
        self,
        api_key: str,
        base_url: str = "https://api.deepseek.com/v1",
        model: str = "deepseek-chat",
        timeout: float = 30.0,
    ):
        if not api_key:
            raise ValueError("DeepSeek smart-layer requires DEEPSEEK_API_KEY")
        self.model = model
        self._url = f"{base_url.rstrip('/')}/chat/completions"
        self._headers = {"Authorization": f"Bearer {api_key}"}
        self._client = httpx.AsyncClient(timeout=timeout)

    async def process(self, raw_transcript: str) -> SmartResult:
        raw = raw_transcript.strip()
        if not raw:
            return SmartResult(text="", turn_complete=False, refined=False)

        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": build_user_prompt(raw)},
            ],
            "temperature": 0.0,
            "response_format": {"type": "json_object"},
        }
        try:
            resp = await self._client.post(self._url, headers=self._headers, json=payload)
            resp.raise_for_status()
            content = resp.json()["choices"][0]["message"]["content"]
            data = json.loads(content)
            return SmartResult(
                text=str(data.get("text", raw)).strip() or raw,
                turn_complete=bool(data.get("turn_complete", True)),
                end_phrase=bool(data.get("end_phrase", False)),
                refined=True,
            )
        except (httpx.HTTPError, KeyError, ValueError, json.JSONDecodeError):
            # Degrade to passthrough rather than dropping the utterance.
            return SmartResult(text=raw, turn_complete=True, refined=False)

    async def aclose(self) -> None:
        await self._client.aclose()
