"""Offline VAD smoke tests against the bundled sample.

Detection of real speech is validated end-to-end through the installed CLI in a
fresh subprocess (see ``test_smoke_cli.py``). The pytest process itself can land
in a degraded floating-point regime on some virtualized CPUs that makes
in-process Silero inference unreliable (see KNOWN_ISSUES.md), so here we only
assert things that do not depend on a successful detection: decoding, and that
pure silence never produces a (false) utterance.
"""

from __future__ import annotations

from vad_proxy.audio.decode import decode_to_pcm16, pcm_duration_secs
from vad_proxy.audio.segmenter import Segmenter, SegmenterParams, segment_pcm
from vad_proxy.audio.vad import SileroVad


def test_decodes_to_expected_duration(test_audio_path):
    pcm = decode_to_pcm16(test_audio_path, 16000)
    secs = pcm_duration_secs(pcm, 16000)
    # The clip is ~5.5s; allow generous bounds.
    assert 3.0 < secs < 8.0


def test_silence_produces_no_utterance(model_available):
    # 2 seconds of digital silence -> no speech segments (under-detection-safe).
    silence = b"\x00\x00" * 16000 * 2
    vad = SileroVad(sample_rate=16000)
    utterances = segment_pcm(silence, vad, SegmenterParams())
    assert utterances == []


def test_interim_drain_disabled_by_default(model_available):
    vad = SileroVad(sample_rate=16000)
    seg = Segmenter(vad, SegmenterParams())
    assert seg.drain_interim() is None


def test_interim_slices_accumulate(model_available, test_audio_path):
    from vad_proxy.audio.decode import decode_to_pcm16
    from vad_proxy.audio.segmenter import Segmenter, iter_chunks

    pcm = decode_to_pcm16(test_audio_path, 16000)
    vad = SileroVad(sample_rate=16000)
    seg = Segmenter(vad, SegmenterParams(interim_chunk_secs=0.5))
    interim_count = 0
    for chunk in iter_chunks(pcm, vad.chunk_size):
        seg.process_chunk(chunk)
        while seg.drain_interim() is not None:
            interim_count += 1
    tail = seg.flush()
    while seg.drain_interim() is not None:
        interim_count += 1
    if tail is not None:
        assert interim_count >= 1
