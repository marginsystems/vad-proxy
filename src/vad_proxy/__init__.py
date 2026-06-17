"""vad-proxy: LLM-powered voice transcription proxy.

Local Silero VAD for endpointing -> pluggable cloud STT -> DeepSeek smart-layer
(turn detection + correction) -> pluggable output adapter.
"""

import os as _os

# Pin math libraries to a single thread BEFORE numpy / onnxruntime initialize
# their native (OpenMP/BLAS) thread pools. On some virtualized CPUs, parallel
# reductions yield non-deterministic LSTM outputs across processes, which
# degrades VAD confidence and breaks endpointing. Importing the vad_proxy
# package first (as all entry points do) makes this effective. Users can
# override by exporting these variables themselves.
for _var in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS"):
    _os.environ.setdefault(_var, "1")
_os.environ.setdefault("OMP_DYNAMIC", "FALSE")

__version__ = "0.1.0"
