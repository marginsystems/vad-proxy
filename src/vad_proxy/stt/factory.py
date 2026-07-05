"""Build the configured STT backend from settings."""

from __future__ import annotations

from vad_proxy.config import Settings
from vad_proxy.stt.base import SttBackend
from vad_proxy.stt.retry import RetryingSttBackend


def _wrap_cloud(backend: SttBackend, settings: Settings) -> SttBackend:
    return RetryingSttBackend(
        backend,
        max_retries=settings.stt_max_retries,
        base_delay=settings.stt_retry_base_delay,
    )


def build_stt(settings: Settings) -> SttBackend:
    backend = settings.stt_backend
    if backend == "mock":
        from vad_proxy.stt.mock import MockSttBackend

        return MockSttBackend()
    if backend == "deepgram":
        from vad_proxy.stt.deepgram import DeepgramSttBackend

        return _wrap_cloud(
            DeepgramSttBackend(
                api_key=settings.deepgram_api_key,
                model=settings.deepgram_model,
                language=settings.language,
            ),
            settings,
        )
    if backend == "openai":
        from vad_proxy.stt.openai import OpenAISttBackend

        return _wrap_cloud(
            OpenAISttBackend(
                api_key=settings.openai_api_key,
                model=settings.openai_stt_model,
                language=settings.language,
            ),
            settings,
        )
    raise ValueError(f"Unknown STT backend: {backend}")
