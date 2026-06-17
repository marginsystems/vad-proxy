"""Deepgram pre-recorded STT backend (via the REST API over httpx)."""

from __future__ import annotations

import httpx

from vad_proxy.audio.decode import pcm16_to_wav
from vad_proxy.stt.base import SttBackend, Transcript

_DEEPGRAM_URL = "https://api.deepgram.com/v1/listen"


class DeepgramSttBackend(SttBackend):
    name = "deepgram"

    def __init__(
        self,
        api_key: str,
        model: str = "nova-2",
        language: str = "en",
        timeout: float = 30.0,
    ):
        if not api_key:
            raise ValueError("Deepgram backend requires DEEPGRAM_API_KEY")
        self.api_key = api_key
        self.model = model
        self.language = language
        self._client = httpx.AsyncClient(timeout=timeout)

    async def transcribe(self, pcm: bytes, sample_rate: int) -> Transcript:
        wav = pcm16_to_wav(pcm, sample_rate)
        params = {"model": self.model, "smart_format": "true", "language": self.language}
        headers = {"Authorization": f"Token {self.api_key}", "Content-Type": "audio/wav"}
        resp = await self._client.post(
            _DEEPGRAM_URL, params=params, headers=headers, content=wav
        )
        resp.raise_for_status()
        data = resp.json()
        alt = data["results"]["channels"][0]["alternatives"][0]
        return Transcript(
            text=alt.get("transcript", "").strip(),
            language=self.language,
            confidence=alt.get("confidence"),
            backend=self.name,
        )

    async def aclose(self) -> None:
        await self._client.aclose()
