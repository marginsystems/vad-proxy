"""Personalization interfaces (v1: interfaces + utterance logging only).

These define the contract for the "get to know my voice over time" features on
the roadmap: speaker enrollment/verification, vocabulary biasing to improve
recognition of the words you actually use, and recording samples to build a
personal dataset. v1 ships:

- The :class:`Personalizer` interface (no real adaptation yet).
- :class:`UtteranceLogger`, a concrete implementation of ``record_sample`` that
  persists PCM + transcript to disk so a personal dataset accumulates for
  future adaptation. Everything else is a documented stub.

See ``personalization/README.md`` for the full roadmap.
"""

from __future__ import annotations

import json
import time
import wave
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class SpeakerProfile:
    """A persistent profile that accumulates knowledge about one speaker."""

    speaker_id: str
    # Mean voice embedding for verification (filled in by future versions).
    embedding: list[float] | None = None
    # Custom vocabulary / corrections learned over time (term -> canonical).
    vocabulary: dict[str, str] = field(default_factory=dict)
    sample_count: int = 0
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)


@dataclass
class VerificationResult:
    """Outcome of checking whether audio matches the enrolled speaker."""

    is_match: bool
    score: float
    speaker_id: str | None = None


class Personalizer(ABC):
    """Interface for speaker-adaptive behavior. v1 implementations are stubs."""

    @abstractmethod
    async def enroll(self, speaker_id: str, pcm: bytes, sample_rate: int) -> SpeakerProfile:
        """Register/extend a speaker's profile from a sample of their voice."""

    @abstractmethod
    async def verify(self, pcm: bytes, sample_rate: int) -> VerificationResult:
        """Check whether audio is the enrolled speaker vs others/background."""

    @abstractmethod
    def bias_vocabulary(self, transcript: str) -> str:
        """Apply learned custom-vocabulary corrections to a transcript."""

    @abstractmethod
    async def record_sample(
        self, pcm: bytes, sample_rate: int, transcript: str, meta: dict[str, Any] | None = None
    ) -> None:
        """Persist an utterance to build a personal dataset for adaptation."""


class NullPersonalizer(Personalizer):
    """No-op personalizer used when personalization is disabled."""

    async def enroll(self, speaker_id, pcm, sample_rate):  # noqa: D102
        return SpeakerProfile(speaker_id=speaker_id)

    async def verify(self, pcm, sample_rate):  # noqa: D102
        return VerificationResult(is_match=True, score=1.0)

    def bias_vocabulary(self, transcript):  # noqa: D102
        return transcript

    async def record_sample(self, pcm, sample_rate, transcript, meta=None):  # noqa: D102
        return None


class UtteranceLogger(Personalizer):
    """Concrete ``record_sample`` that logs utterances to disk.

    Each utterance is written as a WAV file plus a JSONL row capturing the
    transcript and metadata. This builds the personal dataset that future
    speaker-adaptation work will train on. Enrollment/verification/biasing
    remain stubs in v1.
    """

    def __init__(self, data_dir: str | Path = "data"):
        self.root = Path(data_dir)
        self.audio_dir = self.root / "utterances"
        self.index_path = self.root / "utterances.jsonl"

    async def enroll(self, speaker_id, pcm, sample_rate):
        return SpeakerProfile(speaker_id=speaker_id)

    async def verify(self, pcm, sample_rate):
        return VerificationResult(is_match=True, score=1.0)

    def bias_vocabulary(self, transcript):
        return transcript

    async def record_sample(self, pcm, sample_rate, transcript, meta=None):
        self.audio_dir.mkdir(parents=True, exist_ok=True)
        stamp = f"{time.time():.3f}".replace(".", "_")
        wav_path = self.audio_dir / f"utt_{stamp}.wav"
        with wave.open(str(wav_path), "wb") as wav:
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(sample_rate)
            wav.writeframes(pcm)
        row = {
            "audio": str(wav_path.relative_to(self.root)),
            "transcript": transcript,
            "sample_rate": sample_rate,
            "ts": time.time(),
            "meta": meta or {},
        }
        with self.index_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
