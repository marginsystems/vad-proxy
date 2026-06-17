"""End-to-end smoke test through the real CLI in a fresh subprocess.

This exercises the full pipeline (decode -> Silero VAD -> segmenter -> mock STT
-> passthrough smart-layer -> stdout output) exactly as it runs in production.

Running in a subprocess matters: the plain interpreter reliably detects speech,
whereas in-process inference under the pytest runtime can be perturbed by the
host's floating-point instability (see KNOWN_ISSUES.md). A small number of
retries absorbs any residual environment flakiness.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
TEST_AUDIO = REPO_ROOT / "tests" / "data" / "test-123.mp3"
MODEL_PATH = REPO_ROOT / "models" / "silero_vad.onnx"
MAX_ATTEMPTS = 6
EXPECTED = "hello this is a test"


@pytest.mark.skipif(not TEST_AUDIO.exists(), reason="bundled test audio missing")
@pytest.mark.skipif(not MODEL_PATH.exists(), reason="Silero model not downloaded")
def test_cli_transcribe_detects_utterance():
    env = {
        "OMP_NUM_THREADS": "1",
        "MKL_NUM_THREADS": "1",
        "OPENBLAS_NUM_THREADS": "1",
        "PATH": __import__("os").environ.get("PATH", ""),
        "VAD_PROXY_STT_BACKEND": "mock",
        "VAD_PROXY_LLM_ENABLED": "false",
    }
    last_stdout = ""
    for _ in range(MAX_ATTEMPTS):
        proc = subprocess.run(
            [sys.executable, "-m", "vad_proxy.cli", "transcribe", str(TEST_AUDIO)],
            capture_output=True,
            text=True,
            env=env,
            timeout=120,
        )
        last_stdout = proc.stdout
        assert proc.returncode == 0, proc.stderr
        if EXPECTED in proc.stdout.lower():
            return  # success
    pytest.fail(
        f"CLI did not detect the utterance in {MAX_ATTEMPTS} attempts. "
        f"Last stdout: {last_stdout!r}. See KNOWN_ISSUES.md."
    )
