#!/usr/bin/env python3
"""Stream an audio file to a running vad-proxy WebSocket server.

Mimics a live microphone client: decodes the file to 16 kHz mono PCM and sends
it in ~20 ms binary frames, then sends a final "flush" so any trailing
utterance is emitted.

Usage:
    python examples/stream_file_ws.py path/to/audio.mp3 --url ws://localhost:8080/ws
"""

from __future__ import annotations

import argparse
import asyncio

import websockets

from vad_proxy.audio.decode import decode_to_pcm16


async def stream(path: str, url: str, sample_rate: int) -> None:
    pcm = decode_to_pcm16(path, sample_rate)
    frame = sample_rate // 50 * 2  # 20 ms of int16 mono
    async with websockets.connect(url, max_size=None) as ws:
        for i in range(0, len(pcm), frame):
            await ws.send(pcm[i : i + frame])
            await asyncio.sleep(0.02)  # pace like real time
        await ws.send("flush")
        await asyncio.sleep(0.5)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("file")
    parser.add_argument("--url", default="ws://localhost:8080/ws")
    parser.add_argument("--sample-rate", type=int, default=16000, choices=(8000, 16000))
    args = parser.parse_args()
    asyncio.run(stream(args.file, args.url, args.sample_rate))


if __name__ == "__main__":
    main()
