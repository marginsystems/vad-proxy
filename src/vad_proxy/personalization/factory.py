"""Build the configured personalizer from settings."""

from __future__ import annotations

from vad_proxy.config import Settings
from vad_proxy.personalization.base import NullPersonalizer, Personalizer, UtteranceLogger


def build_personalizer(settings: Settings) -> Personalizer:
    if settings.log_utterances:
        return UtteranceLogger(data_dir=settings.data_dir)
    return NullPersonalizer()
