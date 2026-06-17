"""Smart-layer interface: refine a raw transcript and judge turn-completion."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class SmartResult:
    """Output of the smart-layer for one utterance."""

    text: str
    turn_complete: bool = True
    end_phrase: bool = False
    # True when the LLM actually ran; False if it was skipped / passthrough.
    refined: bool = False


class SmartLayer(ABC):
    @abstractmethod
    async def process(self, raw_transcript: str) -> SmartResult:
        """Return a corrected transcript plus turn-completion judgment."""

    async def aclose(self) -> None:
        """Release any held resources."""


class PassthroughSmartLayer(SmartLayer):
    """No-op layer used when the LLM is disabled or no API key is present."""

    async def process(self, raw_transcript: str) -> SmartResult:
        text = raw_transcript.strip()
        return SmartResult(text=text, turn_complete=True, end_phrase=False, refined=False)
