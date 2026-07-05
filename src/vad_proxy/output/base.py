"""Output adapter interface: proxy the final transcript somewhere."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass
class InterimChunkRecord:
    """One interim STT slice captured for debug replay."""

    index: int
    start_secs: float
    end_secs: float
    reason: str
    text: str
    pcm: bytes
    sample_rate: int = 16000


@dataclass
class FinalText:
    """The finished, corrected transcript plus metadata about its provenance."""

    text: str
    turn_complete: bool = True
    end_phrase: bool = False
    start_secs: float = 0.0
    end_secs: float = 0.0
    stt_backend: str = ""
    refined: bool = False
    meta: dict[str, Any] = field(default_factory=dict)


class OutputAdapter(ABC):
    """Receives each finished utterance and proxies it to a destination."""

    name: str = "base"

    @abstractmethod
    async def send(self, final: FinalText) -> None:
        """Deliver ``final`` to the configured destination."""

    async def send_interim(
        self, text: str, start_secs: float, end_secs: float, stt_backend: str
    ) -> None:
        """Deliver a raw interim transcript (un-polished; optional hook)."""

    async def send_chunk_debug(self, chunks: list[InterimChunkRecord]) -> None:
        """Deliver interim slice audio + metadata for debug replay (optional hook)."""

    async def send_error(self, message: str, fatal: bool = False) -> None:
        """Deliver a pipeline or session error to the client (optional hook)."""

    async def aclose(self) -> None:
        """Release any held resources."""
