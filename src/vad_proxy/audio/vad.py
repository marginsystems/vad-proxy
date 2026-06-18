"""Silero VAD via onnxruntime (no PyTorch).

A thin wrapper around the Silero v5 ONNX model that returns a speech-probability
for a fixed-size audio chunk (512 samples @ 16 kHz, 256 @ 8 kHz). The model
carries recurrent state between calls, so chunks must be fed in order.

The ONNX I/O contract (input/state/sr -> out/state) follows the upstream Silero
model and matches Pipecat's reference wrapper.
"""

from __future__ import annotations

import os
from pathlib import Path

import numpy as np

# Force single-threaded math BEFORE onnxruntime loads its native libraries.
# On some (virtualized) CPUs, OpenMP parallel reductions produce
# non-deterministic LSTM outputs across processes, which degrades VAD
# confidence and breaks endpointing. Pinning to one thread makes inference
# reproducible. Only set if the user has not chosen their own values.
for _var in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS"):
    os.environ.setdefault(_var, "1")
os.environ.setdefault("OMP_DYNAMIC", "FALSE")

import onnxruntime  # noqa: E402

_MODEL_NAME = "silero_vad.onnx"


def default_model_path() -> Path:
    """Resolve the Silero ONNX model path.

    Resolution order:
    1. ``VAD_PROXY_MODEL_PATH`` environment variable
    2. ``models/silero_vad.onnx`` relative to the current working directory
       (Docker WORKDIR ``/app``, local dev repo root)
    3. ``models/silero_vad.onnx`` relative to the source tree (editable install)
    """
    env = os.environ.get("VAD_PROXY_MODEL_PATH")
    if env:
        return Path(env)

    candidates = [
        Path.cwd() / "models" / _MODEL_NAME,
        Path(__file__).resolve().parents[3] / "models" / _MODEL_NAME,
    ]
    for path in candidates:
        if path.is_file():
            return path
    return candidates[0]


class SileroVad:
    """Stateful Silero VAD inference for streaming chunk-by-chunk processing."""

    def __init__(self, model_path: str | Path | None = None, sample_rate: int = 16000):
        if sample_rate not in (8000, 16000):
            raise ValueError(f"Silero VAD supports 8000/16000 Hz, got {sample_rate}")
        self.sample_rate = sample_rate
        self.chunk_size = 512 if sample_rate == 16000 else 256
        self._context_size = 64 if sample_rate == 16000 else 32

        path = Path(model_path) if model_path else default_model_path()
        if not path.exists():
            raise FileNotFoundError(
                f"Silero model not found at {path}. Run `python scripts/download_models.py`."
            )

        # Single-threaded, sequential execution for reproducible inference.
        # (Note: onnxruntime must be <1.20; newer CPU builds give
        # non-deterministic LSTM outputs for this model. See pyproject.toml.)
        opts = onnxruntime.SessionOptions()
        opts.inter_op_num_threads = 1
        opts.intra_op_num_threads = 1
        opts.execution_mode = onnxruntime.ExecutionMode.ORT_SEQUENTIAL
        self._session = onnxruntime.InferenceSession(
            str(path), providers=["CPUExecutionProvider"], sess_options=opts
        )
        self.reset_states()
        self._warmup()

    def _warmup(self, iterations: int = 32) -> None:
        """Run inferences on noise to settle the CPU/library FP regime.

        Without this, the first inferences in a fresh process can land in a
        degraded numerical regime on some virtualized CPUs. Warming up on a
        noisy signal (which drives the LSTM through denormal-range states)
        stabilizes subsequent confidences. State is reset afterwards so warmup
        never contaminates real audio.
        """
        rng = np.random.default_rng(0)
        for _ in range(iterations):
            noise = (rng.standard_normal(self.chunk_size).astype(np.float32)) * 0.1
            self._infer(noise)
        self.reset_states()

    def reset_states(self) -> None:
        """Clear recurrent state. Call between independent audio streams."""
        self._state = np.zeros((2, 1, 128), dtype="float32")
        self._context = np.zeros((1, self._context_size), dtype="float32")

    def _infer(self, chunk_float32: np.ndarray) -> float:
        x = np.expand_dims(chunk_float32, 0)  # (1, chunk_size)
        x = np.concatenate((self._context, x), axis=1)
        out, state = self._session.run(
            None,
            {"input": x, "state": self._state, "sr": np.array(self.sample_rate, dtype="int64")},
        )
        self._state = state
        self._context = x[..., -self._context_size :]
        return float(out[0][0])

    def confidence(self, chunk_pcm16: bytes) -> float:
        """Speech probability in [0, 1] for one fixed-size int16 PCM chunk.

        The chunk must contain exactly ``chunk_size`` samples
        (``chunk_size * 2`` bytes).
        """
        audio_int16 = np.frombuffer(chunk_pcm16, dtype=np.int16)
        audio_float32 = audio_int16.astype(np.float32) / 32768.0
        return self._infer(audio_float32)
