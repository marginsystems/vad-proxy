"""Command-line entry point for vad-proxy.

Subcommands:
  transcribe <file>   Decode an audio file and run it through the pipeline.
  serve               Start the WebSocket listener.
"""

from __future__ import annotations

import argparse
import asyncio
import sys

from vad_proxy.config import load_settings


async def _run_transcribe(path: str, sample_rate: int) -> None:
    from vad_proxy.audio.decode import decode_to_pcm16, pcm_duration_secs
    from vad_proxy.pipeline import build_pipeline

    settings = load_settings()
    settings.sample_rate = sample_rate
    pcm = decode_to_pcm16(path, sample_rate)
    print(
        f"Decoded {path}: {pcm_duration_secs(pcm, sample_rate):.2f}s @ {sample_rate} Hz",
        file=sys.stderr,
    )

    pipeline = build_pipeline(settings)
    # Feed in ~100ms blocks to mimic a live stream.
    block = sample_rate // 10 * 2
    for i in range(0, len(pcm), block):
        await pipeline.feed(pcm[i : i + block])
    await pipeline.finish()
    await pipeline.aclose()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="vad-proxy", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    p_tr = sub.add_parser("transcribe", help="Transcribe an audio file")
    p_tr.add_argument("file", help="Path to an audio file (mp3, wav, m4a, ...)")
    p_tr.add_argument("--sample-rate", type=int, default=16000, choices=(8000, 16000))

    sub.add_parser("serve", help="Run the WebSocket listener")

    args = parser.parse_args(argv)

    if args.command == "transcribe":
        asyncio.run(_run_transcribe(args.file, args.sample_rate))
        return 0
    if args.command == "serve":
        from vad_proxy.server import main as serve_main

        serve_main()
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
