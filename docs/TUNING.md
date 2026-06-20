# Tuning vad-proxy for your voice and mic

vad-proxy has two layers of timing: **acoustic VAD** (when a turn starts and
ends) and **interim chunking** (how live italic text is sliced while you are
still speaking). Both depend on your speech pattern, room noise, and microphone.

Defaults in `.env.example` are a reasonable starting point for conversational
English on a typical headset or laptop mic. If live interim text feels choppy,
lags behind your speech, or never updates until a full second elapses, tune with
the workflow below.

## Quick start: preview chunk boundaries

Record 15–30 seconds of yourself speaking naturally (include short pauses between
phrases), save as WAV or MP3, then run:

```bash
python scripts/preview_interim_chunks.py path/to/your-sample.mp3
```

Each line shows a slice with its duration and **reason**:

| reason | meaning |
| --- | --- |
| `dip` | Cut on a sustained RMS dip (word-boundary pause) — preferred |
| `max` | Forced at `VAD_PROXY_INTERIM_SECS` cap — no dip found in time |
| `tail` | Final slice at end of utterance |

**Healthy output:** mostly `reason=dip`, chunks between `INTERIM_MIN_SECS` and
`INTERIM_SECS`. If every chunk is `reason=max`, dips are not firing — lower
`INTERIM_DIP_HOLD_SECS` or adjust `INTERIM_DIP_RATIO`.

Match your live `.env` when previewing:

```bash
python scripts/preview_interim_chunks.py your-sample.mp3 \
  --max-secs 1.0 \
  --min-secs 0.5 \
  --dip-ratio 0.35 \
  --dip-hold-secs 0.04
```

Use `--fixed` to compare legacy fixed-width chunking (no dip detection).

## Interim chunking (live italic text)

Enabled with `VAD_PROXY_INTERIM_ENABLED=true`. Each slice is sent to STT
separately; the UI joins chunk texts until the turn ends (final text still runs
through the LLM once).

| Variable | Default | What it does |
| --- | --- | --- |
| `VAD_PROXY_INTERIM_SECS` | `2.0` | **Max** slice length. Lower (e.g. `1.0`) = faster first interim update, but shorter clips can hurt STT quality. |
| `VAD_PROXY_INTERIM_MIN_SECS` | `0.5` | Minimum buffer before a dip can cut. Prevents tiny fragments. |
| `VAD_PROXY_INTERIM_SMART` | `true` | `true` = RMS dip chunking; `false` = fixed-width slices every `INTERIM_SECS`. |
| `VAD_PROXY_INTERIM_DIP_RATIO` | `0.35` | RMS must fall below this fraction of recent peak to count as a dip. **Lower** = more sensitive (more cuts); **higher** = only deeper pauses. |
| `VAD_PROXY_INTERIM_DIP_HOLD_SECS` | `0.04` | How long the dip must last before cutting. **Shorter** = more responsive cuts; **longer** = fewer false cuts on trailing consonants. At `1.0s` max, `0.06` often never fires and every chunk hits `max`. |

### Mic and environment effects

- **Quiet mics / aggressive noise suppression** flatten RMS between words → fewer
  dips → more `reason=max`. Try lowering `DIP_HOLD_SECS` or `DIP_RATIO`.
- **Noisy rooms** add constant RMS floor → dips are harder to detect. Raise
  `DIP_RATIO` slightly or enable `VAD_PROXY_VAD_MIN_VOLUME` (see VAD section).
- **Fast, continuous speech** may not leave enough pause between words before
  `INTERIM_SECS` — expect some `max` slices; raising `INTERIM_SECS` to `1.5–2.0`
  gives the chunker more time to find a dip and improves STT per slice.
- **Soft speakers** produce smaller peak-to-dip contrast; lowering `DIP_RATIO`
  can help.

### Suggested profiles

**Low latency (Voice Lab / demos)** — fast first italic line:

```bash
VAD_PROXY_INTERIM_SECS=1.0
VAD_PROXY_INTERIM_DIP_HOLD_SECS=0.04
```

**Balanced (production)** — defaults in `.env.example`:

```bash
VAD_PROXY_INTERIM_SECS=2.0
VAD_PROXY_INTERIM_DIP_HOLD_SECS=0.04
```

**Fixed-width fallback** — if smart dips misbehave on your hardware:

```bash
VAD_PROXY_INTERIM_SMART=false
VAD_PROXY_INTERIM_SECS=1.5
```

After editing `.env`, restart Docker: `docker compose up -d --build`.

## VAD endpointing (turn start / end)

These control when a full utterance is sent to STT + LLM, independent of interim
chunking.

| Variable | Default | What it does |
| --- | --- | --- |
| `VAD_PROXY_VAD_START_SECS` | `0.2` | Speech must be present this long before a turn starts. Lower (e.g. `0.1`) = snappier onset; slight false-trigger risk in noise. |
| `VAD_PROXY_VAD_STOP_SECS` | `0.8` | Silence required to end a turn. Lower = faster turn completion; may cut off trailing words. |
| `VAD_PROXY_VAD_CONFIDENCE` | `0.5` | Silero threshold. Raise if VAD fires on background noise. |
| `VAD_PROXY_VAD_MIN_VOLUME` | `0.0` | Optional RMS gate (`0` = off, Silero only). Use if low-confidence noise triggers speech. |
| `VAD_PROXY_MAX_UTTERANCE_SECS` | `30` | Force-flush very long monologues. |

Test VAD on a file:

```bash
vad-proxy transcribe path/to/sample.mp3
```

## Automated tests

```bash
pytest tests/test_interim_chunking.py -v -s
```

`test_chunking_speech_preview` prints slice boundaries (use `-s`). The bundled
`tests/data/chunking-speech-test.mp3` fixture validates that default dip settings
produce `reason=dip` cuts, not only max-cap slices.

## Limits of tuning

Interim mode joins per-chunk STT results; it does **not** re-transcribe the full
utterance at turn end. Very short slices or noisy mics can still produce rough
interim text even with good dip settings. Final turn quality depends on STT +
LLM on the complete joined transcript.

For deeper per-user adaptation (enrollment, vocabulary bias), see
`src/vad_proxy/personalization/README.md` (roadmap).
