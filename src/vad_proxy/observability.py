"""In-process pipeline metrics for /health (no external deps).

All mutations happen on the asyncio event loop. Counters are process-wide
aggregates suitable for a single Docker container.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any


@dataclass
class OpStats:
    count: int = 0
    errors: int = 0
    total_ms: float = 0.0
    last_ms: float = 0.0

    def record(self, ms: float) -> None:
        self.count += 1
        self.last_ms = ms
        self.total_ms += ms

    def record_error(self) -> None:
        self.errors += 1

    def to_dict(self) -> dict[str, float | int]:
        avg = self.total_ms / self.count if self.count else 0.0
        return {
            "count": self.count,
            "errors": self.errors,
            "last_ms": round(self.last_ms, 1),
            "avg_ms": round(avg, 1),
        }


@dataclass
class ServerMetrics:
    stt_final: OpStats = field(default_factory=OpStats)
    stt_interim: OpStats = field(default_factory=OpStats)
    llm: OpStats = field(default_factory=OpStats)
    utterances: int = 0
    interim_slices: int = 0
    input_queue_full: int = 0
    event_queue_dropped: int = 0
    event_queue_pressure: int = 0

    def snapshot(self, *, queue_depths: dict[str, Any] | None = None) -> dict[str, Any]:
        depths = queue_depths or {}
        return {
            "utterances": self.utterances,
            "interim_slices": self.interim_slices,
            "stt_final": self.stt_final.to_dict(),
            "stt_interim": self.stt_interim.to_dict(),
            "llm": self.llm.to_dict(),
            "backpressure": {
                "input_queue_full": self.input_queue_full,
                "event_queue_dropped": self.event_queue_dropped,
                "event_queue_pressure": self.event_queue_pressure,
                "input_queue_max_depth": depths.get("input_queue_max_depth", 0),
                "event_queue_max_depth": depths.get("event_queue_max_depth", 0),
                "sessions_with_input_pressure": depths.get(
                    "sessions_with_input_pressure", 0
                ),
            },
        }


class Timer:
    """Async context manager that records elapsed ms into an :class:`OpStats`."""

    def __init__(self, stats: OpStats) -> None:
        self._stats = stats
        self._start = 0.0
        self.elapsed_ms = 0.0

    async def __aenter__(self) -> Timer:
        self._start = time.perf_counter()
        return self

    async def __aexit__(self, exc_type: type[BaseException] | None, exc_val: BaseException | None, exc_tb: object) -> None:
        self.elapsed_ms = (time.perf_counter() - self._start) * 1000.0
        if exc_type is None:
            self._stats.record(self.elapsed_ms)


metrics = ServerMetrics()
