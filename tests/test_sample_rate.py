"""Tests for listen(sampleRate) validation."""

from __future__ import annotations

import pytest

from vad_proxy.config import load_settings
from vad_proxy.graphql.session import SessionManager


@pytest.mark.asyncio
async def test_create_session_accepts_matching_sample_rate():
    settings = load_settings(sample_rate=16000)
    manager = SessionManager(settings)
    session = manager.create_session(16000)
    assert session.session_id in manager._sessions
    await manager.stop_session(session.session_id)


def test_create_session_rejects_mismatched_sample_rate():
    settings = load_settings(sample_rate=16000)
    manager = SessionManager(settings)
    with pytest.raises(ValueError, match="48000") as exc_info:
        manager.create_session(48000)
    assert "16000" in str(exc_info.value)
    assert manager._sessions == {}
