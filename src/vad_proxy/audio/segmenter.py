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
from dataclasses import dataclass
from enum import Enum
from typing import Iterator

import numpy as np

from vad_proxy.audio.interim_chunker import InterimChunkParams, InterimChunker
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
    # When > 0, interim slicing is enabled. In smart mode this is the max cap.
    interim_chunk_secs: float = 0.0
    interim_min_secs: float = 0.5
    interim_smart: bool = True
    interim_dip_ratio: float = 0.35
    interim_dip_hold_secs: float = 0.04


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
    reason: str | None = None


def _rms_volume(chunk_float32: np.ndarray) -> float:
    """Loudness gate roughly comparable to Pipecat's min_volume scale."""
    if chunk_float32.size == 0:
        return 0.0
    return float(np.sqrt(np.mean(chunk_float32**2)))


_MAX_SPLIT_LOOKBACK_SECS = 2.0
_MIN_SPLIT_PART_SECS = 1.0


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
        self._utterance_speech: list[bool] = []
        self._utterance_rms: list[float] = []
        self._utterance_start_chunk = 0

        self._interim_enabled = self.params.interim_chunk_secs > 0
        self._interim_cursor = 0
        self._pending_interim: deque[InterimSlice] = deque()
        self._utterance_epoch = 0
        self._interim_chunker: InterimChunker | None = None
        self._interim_chunk_bytes = 0

        if self._interim_enabled:
            if self.params.interim_smart:
                self._interim_chunker = InterimChunker(
                    InterimChunkParams(
                        min_secs=self.params.interim_min_secs,
                        max_secs=self.params.interim_chunk_secs,
                        dip_ratio=self.params.interim_dip_ratio,
                        dip_hold_secs=self.params.interim_dip_hold_secs,
                        sample_rate=self.sample_rate,
                        chunk_size=self.chunk_size,
                    )
                )
            else:
                interim_chunks = max(
                    1, round(self.params.interim_chunk_secs / self._secs_per_chunk)
                )
                self._interim_chunk_bytes = interim_chunks * self.chunk_size * 2

    @property
    def utterance_epoch(self) -> int:
        """Increments each time a new in-progress utterance begins."""
        return self._utterance_epoch

    def _chunk_rms(self, chunk_pcm16: bytes) -> float:
        audio_float32 = np.frombuffer(chunk_pcm16, dtype=np.int16).astype(np.float32) / 32768.0
        return _rms_volume(audio_float32)

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
            chunk_rms = self._chunk_rms(chunk_pcm16)
            self._utterance.append(chunk_pcm16)
            self._utterance_speech.append(speaking)
            self._utterance_rms.append(chunk_rms)
            self._maybe_stash_interim_slices(chunk_pcm16)
            if not speaking:
                self._state = VadState.STOPPING
                self._stopping_count = 1
            elif len(self._utterance) >= self._max_chunks:
                split_at = self._find_soft_max_split()
                min_part = max(1, round(_MIN_SPLIT_PART_SECS / self._secs_per_chunk))
                min_part = min(min_part, max(1, self._max_chunks // 3))
                if min_part <= split_at < len(self._utterance):
                    result = self._emit_prefix_utterance(split_at)
                else:
                    result = self._end_utterance()

        elif self._state == VadState.STOPPING:
            self._utterance.append(chunk_pcm16)
            self._utterance_speech.append(speaking)
            self._utterance_rms.append(self._chunk_rms(chunk_pcm16))
            self._maybe_stash_interim_slices(chunk_pcm16)
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
        self._utterance_epoch += 1
        self._state = VadState.SPEAKING
        # Seed with pre-roll so the leading audio is not clipped.
        self._utterance = list(self._preroll)
        self._utterance_speech = [False] * len(self._utterance)
        self._utterance_rms = [self._chunk_rms(chunk) for chunk in self._utterance]
        self._utterance_start_chunk = self._chunk_index - len(self._preroll) + 1
        self._preroll.clear()
        self._starting_count = 0
        self._interim_cursor = 0
        self._pending_interim.clear()
        if self._interim_chunker is not None:
            self._interim_chunker.reset()

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

    def _stash_slice(self, start_byte: int, end_byte: int, reason: str | None = None) -> None:
        start_secs, end_secs = self._slice_times(start_byte, end_byte)
        self._pending_interim.append(
            InterimSlice(
                pcm=self._extract_range(start_byte, end_byte),
                start_secs=start_secs,
                end_secs=end_secs,
                reason=reason,
            )
        )

    def _maybe_stash_interim_slices(self, chunk_pcm16: bytes) -> None:
        if not self._interim_enabled:
            return
        total = self._utterance_byte_len()
        if self._interim_chunker is not None:
            audio_float32 = (
                np.frombuffer(chunk_pcm16, dtype=np.int16).astype(np.float32) / 32768.0
            )
            rms = _rms_volume(audio_float32)
            chunk_bytes = len(chunk_pcm16)
            end_byte = self._interim_chunker.on_chunk(
                rms,
                total - chunk_bytes,
                total,
                self._interim_cursor,
            )
            if end_byte is not None and end_byte > self._interim_cursor:
                self._stash_slice(
                    self._interim_cursor,
                    end_byte,
                    reason=self._interim_chunker.last_reason,
                )
                self._interim_cursor = end_byte
            return

        while total - self._interim_cursor >= self._interim_chunk_bytes:
            end_byte = self._interim_cursor + self._interim_chunk_bytes
            self._stash_slice(self._interim_cursor, end_byte, reason="fixed")
            self._interim_cursor = end_byte

    def _stash_interim_tail(self) -> None:
        if not self._interim_enabled:
            return
        total = self._utterance_byte_len()
        cursor = min(self._interim_cursor, total)
        if total > cursor:
            self._stash_slice(cursor, total, reason="tail")
            self._interim_cursor = total

    def drain_interim(self) -> InterimSlice | None:
        """Return the next pending interim slice, if any."""
        if not self._pending_interim:
            return None
        return self._pending_interim.popleft()

    def _trim_trailing_silence(self) -> None:
        while len(self._utterance) > 1 and not self._utterance_speech[-1]:
            self._utterance.pop()
            self._utterance_speech.pop()
            self._utterance_rms.pop()

    def _find_soft_max_split(self) -> int:
        """Return exclusive end index for a prefix when max_utterance_secs is hit."""
        n = len(self._utterance)
        min_part = max(1, round(_MIN_SPLIT_PART_SECS / self._secs_per_chunk))
        min_part = min(min_part, max(1, self._max_chunks // 3))
        lookback = max(1, round(_MAX_SPLIT_LOOKBACK_SECS / self._secs_per_chunk))
        search_start = max(min_part, n - lookback)
        fallback = n - min_part
        if fallback <= min_part:
            return max(min_part, n // 2)

        for i in range(n - min_part, search_start - 1, -1):
            if i > 0 and not self._utterance_speech[i - 1]:
                return i

        window = self._utterance_rms[search_start:fallback]
        if window:
            peak = max(window)
            if peak > 0.0:
                ratio = self.params.interim_dip_ratio
                best_i = fallback
                best_rms = float("inf")
                for i in range(search_start + 1, fallback + 1):
                    rms = self._utterance_rms[i - 1]
                    if rms < peak * ratio and rms < best_rms:
                        best_rms = rms
                        best_i = i
                if best_i < fallback:
                    return best_i
                for i in range(search_start + 1, fallback + 1):
                    rms = self._utterance_rms[i - 1]
                    if rms < best_rms:
                        best_rms = rms
                        best_i = i
                if best_i < fallback:
                    return best_i

        return fallback

    def _build_current_utterance(self) -> Utterance:
        self._trim_trailing_silence()
        self._stash_interim_tail()
        pcm = b"".join(self._utterance)
        start = max(0.0, self._utterance_start_chunk * self._secs_per_chunk)
        end = (self._utterance_start_chunk + len(self._utterance)) * self._secs_per_chunk
        return Utterance(
            pcm=pcm, sample_rate=self.sample_rate, start_secs=start, end_secs=end
        )

    def _emit_prefix_utterance(self, split_at: int) -> Utterance:
        suffix_utterance = self._utterance[split_at:]
        suffix_speech = self._utterance_speech[split_at:]
        suffix_rms = self._utterance_rms[split_at:]
        suffix_start_chunk = self._utterance_start_chunk + split_at

        self._utterance = self._utterance[:split_at]
        self._utterance_speech = self._utterance_speech[:split_at]
        self._utterance_rms = self._utterance_rms[:split_at]
        utterance = self._build_current_utterance()

        self._utterance_epoch += 1
        self._state = VadState.SPEAKING
        self._utterance = suffix_utterance
        self._utterance_speech = suffix_speech
        self._utterance_rms = suffix_rms
        self._utterance_start_chunk = suffix_start_chunk
        self._interim_cursor = 0
        if self._interim_chunker is not None:
            self._interim_chunker.reset()
        self._stopping_count = 0
        return utterance

    def _end_utterance(self) -> Utterance:
        utterance = self._build_current_utterance()
        self._state = VadState.QUIET
        self._utterance = []
        self._utterance_speech = []
        self._utterance_rms = []
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
        self._utterance_speech = []
        self._utterance_rms = []
        self._interim_cursor = 0
        self._pending_interim.clear()
        self._preroll.clear()
        if self._interim_chunker is not None:
            self._interim_chunker.reset()


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


def collect_interim_slices(
    pcm: bytes, vad: SileroVad, params: SegmenterParams | None = None
) -> list[InterimSlice]:
    """Run the segmenter and return all interim slice boundaries (no STT)."""
    vad.reset_states()
    seg = Segmenter(vad, params)
    slices: list[InterimSlice] = []

    def _drain() -> None:
        while True:
            interim = seg.drain_interim()
            if interim is None:
                break
            slices.append(interim)

    for chunk in iter_chunks(pcm, vad.chunk_size):
        seg.process_chunk(chunk)
        _drain()
    seg.flush()
    _drain()
    return slices
