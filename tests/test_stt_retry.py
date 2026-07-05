"""Tests for RetryingSttBackend transient-failure handling."""

from __future__ import annotations

import pytest
import httpx

from vad_proxy.stt.base import SttBackend, Transcript
from vad_proxy.stt.retry import RetryingSttBackend, SttUnavailable


class _FlakyBackend(SttBackend):
    name = "flaky"

    def __init__(self, failures_before_success: int = 0, always_fail: bool = False):
        self._failures_before_success = failures_before_success
        self._always_fail = always_fail
        self._calls = 0

    async def transcribe(self, pcm: bytes, sample_rate: int) -> Transcript:
        self._calls += 1
        if self._always_fail or self._calls <= self._failures_before_success:
            request = httpx.Request("POST", "https://example.test/listen")
            response = httpx.Response(503, request=request)
            raise httpx.HTTPStatusError("service unavailable", request=request, response=response)
        return Transcript(text="ok", backend=self.name)


class _AuthFailBackend(SttBackend):
    name = "auth_fail"

    async def transcribe(self, pcm: bytes, sample_rate: int) -> Transcript:
        request = httpx.Request("POST", "https://example.test/listen")
        response = httpx.Response(401, request=request)
        raise httpx.HTTPStatusError("unauthorized", request=request, response=response)


@pytest.mark.asyncio
async def test_retry_succeeds_after_transient_failure():
    inner = _FlakyBackend(failures_before_success=1)
    backend = RetryingSttBackend(inner, max_retries=2, base_delay=0.0)
    result = await backend.transcribe(b"\x00\x00", 16000)
    assert result.text == "ok"
    assert inner._calls == 2


@pytest.mark.asyncio
async def test_retry_exhausted_raises_stt_unavailable():
    inner = _FlakyBackend(always_fail=True)
    backend = RetryingSttBackend(inner, max_retries=1, base_delay=0.0)
    with pytest.raises(SttUnavailable):
        await backend.transcribe(b"\x00\x00", 16000)
    assert inner._calls == 2


@pytest.mark.asyncio
async def test_non_retryable_error_raises_immediately():
    inner = _AuthFailBackend()
    backend = RetryingSttBackend(inner, max_retries=3, base_delay=0.0)
    with pytest.raises(SttUnavailable):
        await backend.transcribe(b"\x00\x00", 16000)
