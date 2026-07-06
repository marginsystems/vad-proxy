"""Tests for process-wide shared Silero VAD model."""

from __future__ import annotations

import numpy as np
import pytest

from vad_proxy.audio.vad import (
    SharedSileroVadModel,
    SileroVad,
    get_shared_silero_vad_model,
)
from vad_proxy.config import load_settings
from vad_proxy.graphql.session import SessionManager


def test_get_shared_silero_vad_model_is_singleton(model_available):
    first = get_shared_silero_vad_model(16000)
    second = get_shared_silero_vad_model(16000)
    assert first is second


def test_shared_model_single_onnx_session(model_available):
    model = SharedSileroVadModel(sample_rate=16000)
    stream_a = model.create_stream()
    stream_b = model.create_stream()
    assert stream_a._session is stream_b._session
    assert stream_a is not stream_b


def test_streams_have_independent_state(model_available):
    model = get_shared_silero_vad_model(16000)
    stream_a = model.create_stream()
    stream_b = model.create_stream()

    silence = b"\x00\x00" * 512
    rng = np.random.default_rng(42)
    for _ in range(12):
        noise = (rng.standard_normal(512) * 5000).astype(np.int16).tobytes()
        stream_a.confidence(noise)

    stream_a.reset_states()
    fresh = model.create_stream()
    conf_fresh = fresh.confidence(silence)
    assert stream_a.confidence(silence) == pytest.approx(conf_fresh, abs=1e-5)
    assert stream_b.confidence(silence) == pytest.approx(conf_fresh, abs=1e-5)


@pytest.mark.asyncio
async def test_session_manager_uses_shared_model(model_available):
    settings = load_settings(sample_rate=16000, max_sessions=10)
    vad_model = get_shared_silero_vad_model(settings.sample_rate)
    manager = SessionManager(settings, vad_model=vad_model)

    s1 = manager.create_session()
    s2 = manager.create_session()
    try:
        assert s1._pipeline.c.vad._session is s2._pipeline.c.vad._session
        assert s1._pipeline.c.vad is not s2._pipeline.c.vad
        assert s1._pipeline.c.vad._session is vad_model.session
    finally:
        await manager.stop_session(s1.session_id)
        await manager.stop_session(s2.session_id)


def test_standalone_silero_vad_still_works(model_available):
    """Scripts and unit tests can still construct SileroVad directly."""
    vad = SileroVad(sample_rate=16000)
    conf = vad.confidence(b"\x00\x00" * 512)
    assert 0.0 <= conf <= 1.0
