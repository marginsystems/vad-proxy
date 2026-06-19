"""Unit tests for InterimChunker (no VAD / no audio files)."""

from __future__ import annotations

from vad_proxy.audio.interim_chunker import InterimChunkParams, InterimChunker


def _chunker(**overrides) -> InterimChunker:
    params = InterimChunkParams(**overrides)
    return InterimChunker(params)


def _feed_constant(
    chunker: InterimChunker,
    *,
    rms: float,
    count: int,
    cursor: int,
    chunk_bytes: int,
) -> int | None:
    end: int | None = None
    total = cursor
    for _ in range(count):
        start = total
        total += chunk_bytes
        end = chunker.on_chunk(rms, start, total, cursor)
        if end is not None:
            return end
    return None


def test_waits_until_min_bytes_before_cutting():
    chunker = _chunker()
    chunk_bytes = chunker.params.chunk_bytes
    min_chunks = chunker.params.min_bytes // chunk_bytes
    end = _feed_constant(
        chunker, rms=0.2, count=min_chunks - 1, cursor=0, chunk_bytes=chunk_bytes
    )
    assert end is None


def test_force_cut_at_max_bytes():
    chunker = _chunker()
    chunk_bytes = chunker.params.chunk_bytes
    chunks_needed = (chunker.params.max_bytes + chunk_bytes - 1) // chunk_bytes
    end = _feed_constant(
        chunker, rms=0.2, count=chunks_needed, cursor=0, chunk_bytes=chunk_bytes
    )
    assert end is not None
    assert end >= chunker.params.max_bytes
    assert chunker.last_reason == "max"


def test_dip_cut_after_sustained_quiet():
    chunker = _chunker()
    chunk_bytes = chunker.params.chunk_bytes
    min_chunks = chunker.params.min_bytes // chunk_bytes
    hold_chunks = chunker.params.dip_hold_chunks
    cursor = 0
    total = 0

    for _ in range(min_chunks):
        start = total
        total += chunk_bytes
        assert chunker.on_chunk(0.2, start, total, cursor) is None

    dip_start = total
    for _ in range(hold_chunks):
        start = total
        total += chunk_bytes
        end = chunker.on_chunk(0.02, start, total, cursor)

    assert end == dip_start
    assert chunker.last_reason == "dip"
