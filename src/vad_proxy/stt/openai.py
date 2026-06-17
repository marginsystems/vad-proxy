"""OpenAI (Whisper) STT backend via the audio/transcriptions REST endpoint."""

from __future__ import annotations

import httpx

from vad_proxy.audio.decode import pcm16_to_wav
from vad_proxy.stt.base import SttBackend, Transcript

_OPENAI_URL = "https://api.openai.com/v1/audio/transcriptions"


class OpenAISttBackend(SttBackend):
    name = "openai"

    def __init__(
        self,
        api_key: str,
        model: str = "whisper-1",
        language: str = "en",
        base_url: str = "https://api.openai.com/v1",
        timeout: float = 60.0,
    ):
        if not api_key:
            raise ValueError("OpenAI STT backend requires OPENAI_API_KEY")
        self.api_key = api_key
        self.model = model
        self.language = language
        self._url = f"{base_url.rstrip('/')}/audio/transcriptions"
        self._client = httpx.AsyncClient(timeout=timeout)

    async def transcribe(self, pcm: bytes, sample_rate: int) -> Transcript:
        wav = pcm16_to_wav(pcm, sample_rate)
        files = {"file": ("utterance.wav", wav, "audio/wav")}
        data = {"model": self.model, "language": self.language}
        headers = {"Authorization": f"Bearer {self.api_key}"}
        resp = await self._client.post(self._url, headers=headers, data=data, files=files)
        resp.raise_for_status()
        body = resp.json()
        return Transcript(
            text=body.get("text", "").strip(), language=self.language, backend=self.name
        )

    async def aclose(self) -> None:
        await self._client.aclose()
