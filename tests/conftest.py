"""Shared test fixtures and helpers."""

from __future__ import annotations

# Pin math-library threads before anything imports numpy / onnxruntime. Under
# some virtualized CPUs this is required for reproducible Silero inference;
# conftest is imported early by pytest, before the test modules.
import os as _os

for _var in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS"):
    _os.environ.setdefault(_var, "1")
_os.environ.setdefault("OMP_DYNAMIC", "FALSE")

from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
TEST_AUDIO = REPO_ROOT / "tests" / "data" / "test-123.mp3"
MODEL_PATH = REPO_ROOT / "models" / "silero_vad.onnx"


@pytest.fixture(scope="session")
def test_audio_path() -> Path:
    if not TEST_AUDIO.exists():
        pytest.skip(f"Test audio missing: {TEST_AUDIO}")
    return TEST_AUDIO


@pytest.fixture(scope="session")
def model_available() -> bool:
    if not MODEL_PATH.exists():
        pytest.skip(
            f"Silero model missing: {MODEL_PATH}. Run `python scripts/download_models.py`."
        )
    return True
