#!/usr/bin/env python3
"""Print smart interim chunk boundaries for an audio file (no STT)."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from vad_proxy.audio.decode import decode_to_pcm16
from vad_proxy.audio.segmenter import SegmenterParams, collect_interim_slices, segment_pcm
from vad_proxy.audio.vad import SileroVad


def _preview(audio_path: Path, params: SegmenterParams) -> str:
    pcm = decode_to_pcm16(audio_path, 16000)
    vad = SileroVad(sample_rate=16000)
    slices = collect_interim_slices(pcm, vad, params)
    utterances = segment_pcm(pcm, vad, params)

    lines = [f"audio: {audio_path.name}", f"params: smart={params.interim_smart}"]
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
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "audio",
        type=Path,
        nargs="?",
        default=REPO_ROOT / "tests" / "data" / "chunking-speech-test.mp3",
    )
    parser.add_argument("--min-secs", type=float, default=0.5)
    parser.add_argument("--max-secs", type=float, default=2.0)
    parser.add_argument("--dip-ratio", type=float, default=0.35)
    parser.add_argument("--dip-hold-secs", type=float, default=0.04)
    parser.add_argument(
        "--fixed",
        action="store_true",
        help="Use legacy fixed-width chunking instead of smart dips",
    )
    args = parser.parse_args()

    if not args.audio.exists():
        print(f"audio not found: {args.audio}", file=sys.stderr)
        return 1

    params = SegmenterParams(
        interim_chunk_secs=args.max_secs,
        interim_min_secs=args.min_secs,
        interim_smart=not args.fixed,
        interim_dip_ratio=args.dip_ratio,
        interim_dip_hold_secs=args.dip_hold_secs,
    )
    print(_preview(args.audio, params))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
