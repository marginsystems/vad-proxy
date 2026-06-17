# Known issues

## VAD floating-point instability on some virtualized CPUs

**Symptom.** On certain virtualized/cloud CPUs, a freshly started process can
occasionally land in a degraded floating-point regime where the Silero VAD LSTM
under-detects speech (e.g. the confidence for clearly-spoken audio collapses).
When this happens, an utterance may be missed or split.

**Scope.** This is an *environment* issue, not a bug in vad-proxy. It was
reproduced on the same machine with:

- onnxruntime (multiple versions), and
- the official Silero TorchScript (JIT) model run via PyTorch.

Because two independent runtimes produce the same non-determinism on identical,
bit-for-bit-identical input audio, the root cause is the CPU/hypervisor's
floating-point behavior (most likely inconsistent SIMD kernel dispatch and/or
parallel-reduction order across process launches), which the application cannot
fully control.

**Mitigations already applied.**

- `onnxruntime` is pinned `<1.20`; newer CPU builds made the problem far worse.
- Math libraries are forced single-threaded (`OMP_NUM_THREADS=1` etc., set in
  `vad_proxy/__init__.py`) and onnxruntime runs sequentially with one thread.
- The VAD model performs a short warmup on construction.
- The default VAD confidence threshold is Silero's recommended `0.5`.

These reduce the frequency markedly but do not eliminate it on a defective host.

**Recommended actions for reliable operation.**

- Prefer a bare-metal or known-good CPU instance. If you must run on a shared
  cloud VM, pin the instance to a specific CPU model where possible.
- Export the threading limits in the environment *before* the process starts
  (so they apply before any native thread pool initializes):

  ```bash
  export OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1
  ```

**Effect on tests.** The test suite includes a session health-gate
(`vad_model` fixture). If the current process is in a degraded regime, the
inference-dependent tests are **skipped** with a clear message rather than
failing intermittently. On a healthy process they run and pass deterministically.
