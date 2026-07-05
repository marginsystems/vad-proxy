"""Retry wrapper for cloud STT backends.

Transient HTTP failures (429, 5xx, timeouts) are retried with exponential
backoff. Persistent or non-retryable failures raise :class:`SttUnavailable`
so the pipeline can skip a slice instead of crashing the session.
"""

from __future__ import annotations

import asyncio

import httpx

from vad_proxy.stt.base import SttBackend, Transcript

_RETRYABLE_STATUS = frozenset({429, 500, 502, 503, 504})


class SttUnavailable(Exception):
    """STT could not transcribe after retries or due to a non-retryable error."""


def _is_retryable(exc: BaseException) -> bool:
    if isinstance(exc, httpx.TimeoutException | httpx.TransportError):
        return True
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code in _RETRYABLE_STATUS
    return False


class RetryingSttBackend(SttBackend):
    """Wrap an STT backend with retry-on-transient-failure semantics."""

    def __init__(
        self,
        inner: SttBackend,
        *,
        max_retries: int = 2,
        base_delay: float = 0.2,
    ):
        self._inner = inner
        self._max_retries = max(0, max_retries)
        self._base_delay = base_delay

    @property
    def name(self) -> str:
        return self._inner.name

    async def transcribe(self, pcm: bytes, sample_rate: int) -> Transcript:
        attempts = self._max_retries + 1
        last_exc: BaseException | None = None
        for attempt in range(attempts):
            try:
                return await self._inner.transcribe(pcm, sample_rate)
            except Exception as exc:
                last_exc = exc
                if not _is_retryable(exc) or attempt >= attempts - 1:
                    break
                await asyncio.sleep(self._base_delay * (2**attempt))
        msg = f"STT unavailable ({self.name})"
        if last_exc is not None:
            msg = f"{msg}: {last_exc}"
        raise SttUnavailable(msg) from last_exc

    async def aclose(self) -> None:
        await self._inner.aclose()
