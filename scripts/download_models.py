#!/usr/bin/env python3
"""Fetch the Silero VAD ONNX model into ``models/silero_vad.onnx``.

Resolution order:
  1. ``VAD_PROXY_MODEL_PATH`` env var (used directly if it exists).
  2. An installed ``silero_vad`` package's bundled model.
  3. An installed ``pipecat`` package's bundled model.
  4. Local clones under ``references/`` (silero-vad or pipecat).
  5. Download from the official Silero GitHub raw URL.
"""

from __future__ import annotations

import os
import shutil
import sys
import urllib.request
from pathlib import Path

MODEL_NAME = "silero_vad.onnx"
RAW_URL = (
    "https://github.com/snakers4/silero-vad/raw/master/src/silero_vad/data/silero_vad.onnx"
)

REPO_ROOT = Path(__file__).resolve().parents[1]
DEST = REPO_ROOT / "models" / MODEL_NAME


def _from_installed_package() -> Path | None:
    from importlib import resources

    for pkg in ("silero_vad.data", "pipecat.audio.vad.data"):
        try:
            candidate = resources.files(pkg).joinpath(MODEL_NAME)
            if candidate.is_file():
                return Path(str(candidate))
        except (ModuleNotFoundError, FileNotFoundError, AttributeError):
            continue
    return None


def _from_local_clones() -> Path | None:
    candidates = [
        REPO_ROOT.parent / "references/silero-vad/src/silero_vad/data" / MODEL_NAME,
        REPO_ROOT.parent / "references/pipecat/src/pipecat/audio/vad/data" / MODEL_NAME,
        Path("/root/references/silero-vad/src/silero_vad/data") / MODEL_NAME,
        Path("/root/references/pipecat/src/pipecat/audio/vad/data") / MODEL_NAME,
    ]
    for c in candidates:
        if c.is_file():
            return c
    return None


def main() -> int:
    env_path = os.environ.get("VAD_PROXY_MODEL_PATH")
    if env_path and Path(env_path).is_file():
        print(f"Using model from VAD_PROXY_MODEL_PATH: {env_path}")
        return 0

    if DEST.is_file() and DEST.stat().st_size > 0:
        print(f"Model already present: {DEST}")
        return 0

    DEST.parent.mkdir(parents=True, exist_ok=True)

    source = _from_installed_package() or _from_local_clones()
    if source is not None:
        shutil.copyfile(source, DEST)
        print(f"Copied model from {source} -> {DEST}")
        return 0

    print(f"Downloading model from {RAW_URL} ...")
    try:
        urllib.request.urlretrieve(RAW_URL, DEST)  # noqa: S310 (trusted URL)
    except Exception as e:  # pragma: no cover - network dependent
        print(f"Download failed: {e}", file=sys.stderr)
        return 1
    print(f"Saved model -> {DEST}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
