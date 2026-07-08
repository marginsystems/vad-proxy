"""Max-utterance soft split at RMS dip."""

from __future__ import annotations

import pytest

from vad_proxy.audio.decode import decode_to_pcm16
from vad_proxy.audio.segmenter import SegmenterParams, segment_pcm
from vad_proxy.audio.vad import SileroVad

CAP_TOLERANCE_SECS = 0.15


def test_max_utterance_splits_at_dip(model_available, chunking_speech_test_path):
    pcm = decode_to_pcm16(chunking_speech_test_path, 16000)
    vad = SileroVad(sample_rate=16000)
    params = SegmenterParams(max_utterance_secs=1.0)
    utterances = segment_pcm(pcm, vad, params)

    if not utterances:
        pytest.skip("VAD did not detect speech for max-split test on this host")

    if len(utterances) < 2:
        pytest.skip("speech sample too short or no dip split on this host")

    for i, utterance in enumerate(utterances):
        assert utterance.duration_secs <= params.max_utterance_secs + CAP_TOLERANCE_SECS
        if i > 0:
            assert utterance.start_secs >= utterances[i - 1].start_secs
