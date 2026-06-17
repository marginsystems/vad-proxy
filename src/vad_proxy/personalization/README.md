# Personalization roadmap

> Status: v1 ships **interfaces + utterance logging only**. No real adaptation
> is performed yet. This document tracks the plan.

The goal: the longer you use vad-proxy, the better it should get at (a)
transcribing *your* words specifically, and (b) recognizing *your* voice versus
other people and background noise.

The contract lives in [`base.py`](base.py): `Personalizer` with `enroll`,
`verify`, `bias_vocabulary`, and `record_sample`.

## What works today (v1)

- **`UtteranceLogger.record_sample`** persists every utterance (when
  `VAD_PROXY_LOG_UTTERANCES=true`) as a WAV file plus a JSONL row with the
  transcript and metadata under `VAD_PROXY_DATA_DIR`. This accumulates the
  personal dataset every later phase depends on.
- `SpeakerProfile` / `VerificationResult` dataclasses are defined and stable.
- `enroll`, `verify`, `bias_vocabulary` are no-op stubs.

## Phase 1 - Speaker verification (you vs. others/background)

- Extract speaker embeddings per utterance with a small ONNX model
  (e.g. ECAPA-TDNN / Resemblyzer-style, CPU-friendly, no torch if possible).
- `enroll`: average embeddings from your enrollment clips into
  `SpeakerProfile.embedding`.
- `verify`: cosine-similarity vs the enrolled embedding; gate the pipeline so
  only your voice is transcribed/proxied. Reject background speech and noise.
- Wire a `verify()` check into the pipeline between segmentation and STT.

## Phase 2 - Vocabulary biasing (better transcription of your words)

- Mine the logged dataset for recurring proper nouns, jargon, and the LLM
  smart-layer's repeated corrections.
- Maintain `SpeakerProfile.vocabulary` (surface form -> canonical form).
- `bias_vocabulary`: apply these corrections deterministically; additionally
  feed the vocabulary to STT backends that support hints (Deepgram keywords,
  Whisper `initial_prompt`) and to the DeepSeek prompt as context.

## Phase 3 - Acoustic adaptation

- Periodically fine-tune / adapt a recognizer on the personal dataset
  (offline job, not on the hot path). Likely a local Whisper variant.
- Track word-error-rate over time to verify the system is actually improving.

## Privacy

- Logging is **off by default** (`VAD_PROXY_LOG_UTTERANCES=false`).
- All personal data stays in the local `data/` directory (gitignored).
