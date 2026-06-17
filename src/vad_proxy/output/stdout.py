"""Stdout output adapter. Prints each finished utterance as it arrives."""

from __future__ import annotations

import sys

from vad_proxy.output.base import FinalText, OutputAdapter


class StdoutOutputAdapter(OutputAdapter):
    name = "stdout"

    def __init__(self, stream=sys.stdout):
        self._stream = stream

    async def send(self, final: FinalText) -> None:
        flag = "" if final.turn_complete else "  [partial turn]"
        ts = f"[{final.start_secs:6.2f}-{final.end_secs:6.2f}s]"
        self._stream.write(f"{ts} {final.text}{flag}\n")
        self._stream.flush()
