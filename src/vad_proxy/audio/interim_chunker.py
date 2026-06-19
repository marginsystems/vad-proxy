"""Adaptive interim slicing on RMS dips (word-boundary pauses)."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from typing import Literal

ChunkReason = Literal["dip", "max"]


@dataclass
class InterimChunkParams:
    min_secs: float = 0.5
    max_secs: float = 2.0
    dip_ratio: float = 0.35
    dip_hold_secs: float = 0.04
    peak_window_secs: float = 0.25
    sample_rate: int = 16000
    chunk_size: int = 512

    @property
    def bytes_per_sec(self) -> int:
        return self.sample_rate * 2

    @property
    def chunk_bytes(self) -> int:
        return self.chunk_size * 2

    @property
    def secs_per_chunk(self) -> float:
        return self.chunk_size / self.sample_rate

    @property
    def min_bytes(self) -> int:
        return max(self.chunk_bytes, round(self.min_secs * self.bytes_per_sec))

    @property
    def max_bytes(self) -> int:
        return max(self.min_bytes, round(self.max_secs * self.bytes_per_sec))

    @property
    def dip_hold_chunks(self) -> int:
        return max(1, round(self.dip_hold_secs / self.secs_per_chunk))

    @property
    def peak_window_chunks(self) -> int:
        return max(1, round(self.peak_window_secs / self.secs_per_chunk))


class InterimChunker:
    """Detect interim slice boundaries from per-chunk RMS relative dips."""

    def __init__(self, params: InterimChunkParams) -> None:
        self.params = params
        self.last_reason: ChunkReason | None = None
        self._rms_window: deque[float] = deque(maxlen=params.peak_window_chunks)
        self._dip_start_byte: int | None = None
        self._dip_hold_count = 0

    def reset(self) -> None:
        self.last_reason = None
        self._rms_window.clear()
        self._dip_start_byte = None
        self._dip_hold_count = 0

    def _rolling_peak(self) -> float:
        if not self._rms_window:
            return 0.0
        return max(self._rms_window)

    def _after_stash(self) -> None:
        self._rms_window.clear()
        self._dip_start_byte = None
        self._dip_hold_count = 0

    def on_chunk(
        self,
        rms: float,
        chunk_start_byte: int,
        total_bytes: int,
        cursor_byte: int,
    ) -> int | None:
        """Return an end byte for a new interim slice, or None to keep buffering."""
        self.last_reason = None
        bytes_since_cursor = total_bytes - cursor_byte
        if bytes_since_cursor < self.params.min_bytes:
            self._rms_window.append(rms)
            return None

        if bytes_since_cursor >= self.params.max_bytes:
            self.last_reason = "max"
            self._after_stash()
            return total_bytes

        peak = self._rolling_peak()
        if peak > 0.0 and rms < peak * self.params.dip_ratio:
            if self._dip_start_byte is None:
                self._dip_start_byte = chunk_start_byte
            self._dip_hold_count += 1
            if (
                self._dip_hold_count >= self.params.dip_hold_chunks
                and self._dip_start_byte is not None
                and self._dip_start_byte > cursor_byte
            ):
                end_byte = self._dip_start_byte
                self.last_reason = "dip"
                self._after_stash()
                return end_byte
        else:
            self._dip_start_byte = None
            self._dip_hold_count = 0
            self._rms_window.append(rms)

        return None
