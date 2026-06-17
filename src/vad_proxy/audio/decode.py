"""Decode arbitrary audio files into 16 kHz (or 8 kHz) mono int16 PCM.

Uses PyAV, which bundles its own ffmpeg, so mp3/m4a/ogg/etc. decode without any
system ffmpeg install. The output format (mono, signed 16-bit, target rate) is
exactly what Silero VAD and the cloud STT backends expect.
"""

from __future__ import annotations

import io
import wave
from pathlib import Path

import av
import numpy as np


def decode_to_pcm16(path: str | Path, sample_rate: int = 16000) -> bytes:
    """Decode an audio file to mono signed-16-bit little-endian PCM.

    Args:
        path: Path to any container/codec PyAV can read (mp3, wav, m4a, ...).
        sample_rate: Target sample rate in Hz (16000 or 8000 for Silero).

    Returns:
        Raw PCM bytes, mono int16, at ``sample_rate``.
    """
    path = str(path)
    resampler = av.AudioResampler(format="s16", layout="mono", rate=sample_rate)

    chunks: list[bytes] = []
    with av.open(path) as container:
        stream = container.streams.audio[0]
        for frame in container.decode(stream):
            for resampled in resampler.resample(frame):
                chunks.append(bytes(resampled.planes[0]))
        # Flush any buffered samples held by the resampler.
        for resampled in resampler.resample(None):
            chunks.append(bytes(resampled.planes[0]))

    return b"".join(chunks)


def pcm16_to_float32(pcm: bytes) -> np.ndarray:
    """Convert mono int16 PCM bytes to a float32 array in [-1, 1)."""
    return np.frombuffer(pcm, dtype=np.int16).astype(np.float32) / 32768.0


def pcm_duration_secs(pcm: bytes, sample_rate: int) -> float:
    """Duration in seconds of mono int16 PCM (2 bytes per sample)."""
    return len(pcm) / 2 / sample_rate


def pcm16_to_wav(pcm: bytes, sample_rate: int) -> bytes:
    """Wrap mono int16 PCM in a WAV container (for STT APIs needing a file)."""
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(sample_rate)
        wav.writeframes(pcm)
    return buf.getvalue()
