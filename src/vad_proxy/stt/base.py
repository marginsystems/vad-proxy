"""Speech-to-text backend interface and shared types."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class Transcript:
    """Result of transcribing one utterance."""

    text: str
    language: str | None = None
    confidence: float | None = None
    backend: str = ""


class SttBackend(ABC):
    """Transcribe a single complete utterance of mono int16 PCM."""

    name: str = "base"

    @abstractmethod
    async def transcribe(self, pcm: bytes, sample_rate: int) -> Transcript:
        """Transcribe ``pcm`` (mono signed-16-bit) at ``sample_rate``."""

    async def aclose(self) -> None:
        """Release any held resources (HTTP clients, sessions)."""
