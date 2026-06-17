"""OpenAI-compatible chat output adapter.

Proxies the final transcript as a user message to a chat completions endpoint
(e.g. DeepSeek) and prints the assistant reply. This is the "proxy my voice as
text to another API" destination.
"""

from __future__ import annotations

import sys

import httpx

from vad_proxy.output.base import FinalText, OutputAdapter


class OpenAIChatOutputAdapter(OutputAdapter):
    name = "openai_chat"

    def __init__(
        self,
        api_key: str,
        base_url: str = "https://api.deepseek.com/v1",
        model: str = "deepseek-chat",
        system_prompt: str | None = None,
        timeout: float = 60.0,
        stream=sys.stdout,
    ):
        if not api_key:
            raise ValueError("openai_chat output requires VAD_PROXY_OUTPUT_API_KEY")
        self.model = model
        self.system_prompt = system_prompt
        self._url = f"{base_url.rstrip('/')}/chat/completions"
        self._headers = {"Authorization": f"Bearer {api_key}"}
        self._client = httpx.AsyncClient(timeout=timeout)
        self._stream = stream

    async def send(self, final: FinalText) -> None:
        if not final.text:
            return
        messages = []
        if self.system_prompt:
            messages.append({"role": "system", "content": self.system_prompt})
        messages.append({"role": "user", "content": final.text})
        payload = {"model": self.model, "messages": messages}
        resp = await self._client.post(self._url, headers=self._headers, json=payload)
        resp.raise_for_status()
        reply = resp.json()["choices"][0]["message"]["content"]
        self._stream.write(f"> {final.text}\n< {reply}\n")
        self._stream.flush()

    async def aclose(self) -> None:
        await self._client.aclose()
