"""Turn a stream of audio chunks into discrete utterances.

This is a port of Pipecat's VAD endpointing state machine (QUIET / STARTING /
SPEAKING / STOPPING) driven by Silero confidence plus a simple RMS volume gate.
It buffers audio while the user speaks (with a short pre-roll so the first
phoneme is not clipped) and emits a complete :class:`Utterance` when speech
stops for ``stop_secs``.

Design references:
- pipecat/src/pipecat/audio/vad/vad_analyzer.py (state machine + VADParams)
- silero-vad VADIterator (chunk-by-chunk streaming semantics)
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from enum import Enum
from typing import Iterator

import numpy as np

from vad_proxy.audio.vad import SileroVad


class VadState(Enum):
    QUIET = 1
    STARTING = 2
    SPEAKING = 3
    STOPPING = 4


@dataclass
class SegmenterParams:
    confidence: float = 0.5
    start_secs: float = 0.2
    stop_secs: float = 0.8
    # Optional noise gate on normalized RMS (0-1). 0 disables; Silero
    # confidence is the primary speech signal.
    min_volume: float = 0.0
    pre_speech_secs: float = 0.3
    max_utterance_secs: float = 30.0
    # Sub-chunk cadence for interim STT while an utterance is in progress.
    # 0 disables interim slicing.
    interim_chunk_secs: float = 0.0


@dataclass
class Utterance:
    """A complete detected speech segment."""

    pcm: bytes
    sample_rate: int
    start_secs: float
    end_secs: float

    @property
    def duration_secs(self) -> float:
        return self.end_secs - self.start_secs


@dataclass
class InterimSlice:
    """A pending sub-chunk of the in-progress utterance for interim STT."""

    pcm: bytes
    start_secs: float
    end_secs: float


def _rms_volume(chunk_float32: np.ndarray) -> float:
    """Loudness gate roughly comparable to Pipecat's min_volume scale."""
    if chunk_float32.size == 0:
        return 0.0
    return float(np.sqrt(np.mean(chunk_float32**2)))


class Segmenter:
    """Stateful VAD endpointer that yields :class:`Utterance` objects.

    Feed fixed-size chunks via :meth:`process_chunk`; it returns an
    ``Utterance`` on the chunk that completes a segment, otherwise ``None``.
    """

    def __init__(self, vad: SileroVad, params: SegmenterParams | None = None):
        self.vad = vad
        self.params = params or SegmenterParams()
        self.sample_rate = vad.sample_rate
        self.chunk_size = vad.chunk_size
        self._secs_per_chunk = self.chunk_size / self.sample_rate

        self._state = VadState.QUIET
        self._chunk_index = 0

        # Counters (in chunks) for the STARTING / STOPPING dwell times.
        self._starting_count = 0
        self._stopping_count = 0
        self._start_chunks = max(1, round(self.params.start_secs / self._secs_per_chunk))
        self._stop_chunks = max(1, round(self.params.stop_secs / self._secs_per_chunk))
        self._max_chunks = max(1, round(self.params.max_utterance_secs / self._secs_per_chunk))

        # Pre-roll ring buffer of recent chunks while QUIET.
        pre_roll_chunks = max(1, round(self.params.pre_speech_secs / self._secs_per_chunk))
        self._preroll: deque[bytes] = deque(maxlen=pre_roll_chunks)

        self._utterance: list[bytes] = []
        self._utterance_start_chunk = 0

        if self.params.interim_chunk_secs > 0:
            interim_chunks = max(
                1, round(self.params.interim_chunk_secs / self._secs_per_chunk)
            )
            self._interim_chunk_bytes = interim_chunks * self.chunk_size * 2
        else:
            self._interim_chunk_bytes = 0
        self._interim_cursor = 0
        self._pending_interim: deque[InterimSlice] = deque()

    def _is_speech(self, chunk_pcm16: bytes) -> bool:
        confidence = self.vad.confidence(chunk_pcm16)
        audio_float32 = np.frombuffer(chunk_pcm16, dtype=np.int16).astype(np.float32) / 32768.0
        volume = _rms_volume(audio_float32)
        return confidence >= self.params.confidence and volume >= self.params.min_volume

    def process_chunk(self, chunk_pcm16: bytes) -> Utterance | None:
        """Advance the state machine by one chunk; return an utterance if done."""
        speaking = self._is_speech(chunk_pcm16)
        result: Utterance | None = None

        if self._state == VadState.QUIET:
            self._preroll.append(chunk_pcm16)
            if speaking:
                self._state = VadState.STARTING
                self._starting_count = 1

        elif self._state == VadState.STARTING:
            self._preroll.append(chunk_pcm16)
            if speaking:
                self._starting_count += 1
                if self._starting_count >= self._start_chunks:
                    self._begin_utterance()
            else:
                self._state = VadState.QUIET
                self._starting_count = 0

        elif self._state == VadState.SPEAKING:
            self._utterance.append(chunk_pcm16)
            self._maybe_stash_interim_slices()
            if not speaking:
                self._state = VadState.STOPPING
                self._stopping_count = 1
            elif len(self._utterance) >= self._max_chunks:
                result = self._end_utterance()

        elif self._state == VadState.STOPPING:
            self._utterance.append(chunk_pcm16)
            self._maybe_stash_interim_slices()
            if speaking:
                self._state = VadState.SPEAKING
                self._stopping_count = 0
            else:
                self._stopping_count += 1
                if self._stopping_count >= self._stop_chunks:
                    result = self._end_utterance()

        self._chunk_index += 1
        return result

    def _begin_utterance(self) -> None:
        self._state = VadState.SPEAKING
        # Seed with pre-roll so the leading audio is not clipped.
        self._utterance = list(self._preroll)
        self._utterance_start_chunk = self._chunk_index - len(self._preroll) + 1
        self._preroll.clear()
        self._starting_count = 0
        self._interim_cursor = 0

    def _utterance_byte_len(self) -> int:
        return sum(len(chunk) for chunk in self._utterance)

    def _slice_times(self, start_byte: int, end_byte: int) -> tuple[float, float]:
        bytes_per_sec = self.sample_rate * 2
        utterance_start_secs = max(0.0, self._utterance_start_chunk * self._secs_per_chunk)
        start = utterance_start_secs + start_byte / bytes_per_sec
        end = utterance_start_secs + end_byte / bytes_per_sec
        return start, end

    def _extract_range(self, start_byte: int, end_byte: int) -> bytes:
        parts: list[bytes] = []
        pos = 0
        for chunk in self._utterance:
            chunk_len = len(chunk)
            chunk_end = pos + chunk_len
            if chunk_end <= start_byte:
                pos = chunk_end
                continue
            if pos >= end_byte:
                break
            local_start = max(0, start_byte - pos)
            local_end = min(chunk_len, end_byte - pos)
            parts.append(chunk[local_start:local_end])
            pos = chunk_end
        return b"".join(parts)

    def _stash_slice(self, start_byte: int, end_byte: int) -> None:
        start_secs, end_secs = self._slice_times(start_byte, end_byte)
        self._pending_interim.append(
            InterimSlice(
                pcm=self._extract_range(start_byte, end_byte),
                start_secs=start_secs,
                end_secs=end_secs,
            )
        )

    def _maybe_stash_interim_slices(self) -> None:
        if self._interim_chunk_bytes <= 0:
            return
        total = self._utterance_byte_len()
        while total - self._interim_cursor >= self._interim_chunk_bytes:
            end_byte = self._interim_cursor + self._interim_chunk_bytes
            self._stash_slice(self._interim_cursor, end_byte)
            self._interim_cursor = end_byte

    def _stash_interim_tail(self) -> None:
        if self._interim_chunk_bytes <= 0:
            return
        total = self._utterance_byte_len()
        if total > self._interim_cursor:
            self._stash_slice(self._interim_cursor, total)
            self._interim_cursor = total

    def drain_interim(self) -> InterimSlice | None:
        """Return the next pending interim slice, if any."""
        if not self._pending_interim:
            return None
        return self._pending_interim.popleft()

    def _end_utterance(self) -> Utterance:
        self._stash_interim_tail()
        pcm = b"".join(self._utterance)
        start = max(0.0, self._utterance_start_chunk * self._secs_per_chunk)
        end = (self._chunk_index + 1) * self._secs_per_chunk
        utterance = Utterance(
            pcm=pcm, sample_rate=self.sample_rate, start_secs=start, end_secs=end
        )
        self._state = VadState.QUIET
        self._utterance = []
        self._interim_cursor = 0
        self._stopping_count = 0
        self._preroll.clear()
        return utterance

    def flush(self) -> Utterance | None:
        """Emit any in-progress utterance at end of stream."""
        if self._state in (VadState.SPEAKING, VadState.STOPPING) and self._utterance:
            return self._end_utterance()
        return None

    def reset(self) -> None:
        self.vad.reset_states()
        self._state = VadState.QUIET
        self._chunk_index = 0
        self._starting_count = 0
        self._stopping_count = 0
        self._utterance = []
        self._interim_cursor = 0
        self._pending_interim.clear()
        self._preroll.clear()


def iter_chunks(pcm: bytes, chunk_size: int) -> Iterator[bytes]:
    """Yield ``chunk_size``-sample (``chunk_size*2``-byte) chunks; drop remainder."""
    step = chunk_size * 2
    for i in range(0, len(pcm) - step + 1, step):
        yield pcm[i : i + step]


def segment_pcm(
    pcm: bytes, vad: SileroVad, params: SegmenterParams | None = None
) -> list[Utterance]:
    """Convenience: run the segmenter over a complete PCM buffer.

    Resets the VAD's recurrent state first so this batch helper is
    self-contained and safe to call repeatedly on a reused model.
    """
    vad.reset_states()
    seg = Segmenter(vad, params)
    utterances: list[Utterance] = []
    for chunk in iter_chunks(pcm, vad.chunk_size):
        u = seg.process_chunk(chunk)
        if u is not None:
            utterances.append(u)
    tail = seg.flush()
    if tail is not None:
        utterances.append(tail)
    return utterances
