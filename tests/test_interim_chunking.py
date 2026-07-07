"""Tests and preview helpers for smart interim chunk boundaries."""

from __future__ import annotations

from pathlib import Path

import pytest

from vad_proxy.audio.decode import decode_to_pcm16
from vad_proxy.audio.segmenter import SegmenterParams, collect_interim_slices, segment_pcm
from vad_proxy.audio.vad import SileroVad

CHUNK_TOLERANCE_SECS = 0.04  # one VAD frame @ 16 kHz


def _smart_params(**overrides) -> SegmenterParams:
    defaults = {
        "interim_chunk_secs": 2.0,
        "interim_min_secs": 0.5,
        "interim_smart": True,
        "interim_dip_ratio": 0.35,
        "interim_dip_hold_secs": 0.04,
    }
    defaults.update(overrides)
    return SegmenterParams(**defaults)


def test_smart_chunks_respect_min_max_bounds(model_available, chunking_speech_test_path):
    pcm = decode_to_pcm16(chunking_speech_test_path, 16000)
    vad = SileroVad(sample_rate=16000)
    slices = collect_interim_slices(pcm, vad, _smart_params())
    if len(slices) < 2:
        pytest.skip("VAD did not detect enough speech for interim slicing on this host")

    for i, slc in enumerate(slices):
        duration = slc.end_secs - slc.start_secs
        is_tail = i == len(slices) - 1
        if not is_tail:
            assert duration >= 0.5 - CHUNK_TOLERANCE_SECS
        assert duration <= 2.0 + CHUNK_TOLERANCE_SECS


def test_smart_chunks_cut_on_dips_not_only_max(model_available, chunking_speech_test_path):
    """Default dip_hold should produce word-boundary cuts, not only max-cap slices."""
    pcm = decode_to_pcm16(chunking_speech_test_path, 16000)
    vad = SileroVad(sample_rate=16000)
    params = _smart_params(interim_chunk_secs=1.0)
    slices = collect_interim_slices(pcm, vad, params)
    if len(slices) < 2:
        pytest.skip("VAD did not detect enough speech for interim slicing on this host")

    dip_slices = [s for s in slices if s.reason == "dip"]
    assert len(dip_slices) >= 2, (
        "expected multiple dip cuts; try lowering VAD_PROXY_INTERIM_DIP_HOLD_SECS "
        "or record a sample with natural pauses"
    )


def test_smart_chunks_cover_utterance(model_available, chunking_speech_test_path):
    pcm = decode_to_pcm16(chunking_speech_test_path, 16000)
    vad = SileroVad(sample_rate=16000)
    params = _smart_params()
    slices = collect_interim_slices(pcm, vad, params)
    utterances = segment_pcm(pcm, vad, params)

    if not utterances or len(slices) < 1:
        pytest.skip("VAD did not detect speech for chunking integration on this host")

    utterance = utterances[0]
    covered = sum(s.end_secs - s.start_secs for s in slices)
    # Interim slices emitted during STOPPING include trailing silence trimmed
    # from the final utterance before paid STT.
    assert covered >= utterance.duration_secs - 0.15
    assert covered - utterance.duration_secs < params.stop_secs + CHUNK_TOLERANCE_SECS + 0.1


def test_fixed_mode_still_works(model_available, test_audio_path):
    pcm = decode_to_pcm16(test_audio_path, 16000)
    vad = SileroVad(sample_rate=16000)
    slices = collect_interim_slices(
        pcm,
        vad,
        SegmenterParams(interim_chunk_secs=0.5, interim_smart=False),
    )
    if len(slices) < 2:
        pytest.skip("VAD did not detect enough speech for fixed interim slicing on this host")

    for slc in slices[:-1]:
        duration = slc.end_secs - slc.start_secs
        assert abs(duration - 0.5) < 0.1


def test_chunking_speech_preview(
    model_available, chunking_speech_test_path, capsys
):
    """Print slice boundaries for manual tuning (visible with pytest -s)."""
    pcm = decode_to_pcm16(chunking_speech_test_path, 16000)
    vad = SileroVad(sample_rate=16000)
    params = _smart_params()
    slices = collect_interim_slices(pcm, vad, params)
    utterances = segment_pcm(pcm, vad, params)

    lines = ["Smart interim chunk preview:"]
    if not slices:
        lines.append("(no interim slices — VAD did not detect speech on this host)")
    if utterances:
        u = utterances[0]
        lines.append(f"utterance: {u.start_secs:.2f}s - {u.end_secs:.2f}s")
    for i, slc in enumerate(slices, start=1):
        duration = slc.end_secs - slc.start_secs
        reason = slc.reason or "unknown"
        lines.append(
            f"chunk {i}: {slc.start_secs:.2f}s - {slc.end_secs:.2f}s "
            f"({duration:.2f}s) reason={reason}"
        )
    report = "\n".join(lines)
    print(report)
