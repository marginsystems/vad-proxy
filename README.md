# vad-proxy

**LLM-powered voice transcription proxy.**

`vad-proxy` listens to an audio stream, uses a **local Silero VAD** to detect
when you start and stop talking, transcribes each utterance with a **pluggable
cloud STT** backend, runs the raw transcript through a **DeepSeek smart-layer**
(decide whether you actually finished your turn, and fix mis-transcribed words),
and proxies the final clean text to a **pluggable output destination**.

It is designed to be lean: VAD runs locally for free via `onnxruntime` (no
PyTorch), so the only paid hops are the STT and LLM calls you opt into.

```
audio  ->  decode/resample (16k mono)  ->  Silero VAD  ->  segmenter
       ->  STT (Deepgram / OpenAI / mock)
       ->  DeepSeek smart-layer (turn-complete? + correction)
       ->  output adapter (DeepSeek chat / webhook / stdout)
```

## Why

- **Smart endpointing.** Acoustic VAD finds silence boundaries; the LLM layer
  confirms semantically that you are done (e.g. catches "okay, your turn").
- **Cheap to keep listening.** The 24/7 listening loop is local VAD only; STT
  and LLM only fire once a complete utterance is detected.
- **Pluggable everywhere.** STT, LLM, and output are all interfaces with
  built-in implementations and a mock for offline development.

## Install

```bash
pip install -e ".[all,dev]"      # or pick extras: .[deepgram] / .[openai]
python scripts/download_models.py
```

Python 3.11+. No GPU required. mp3/other formats are decoded via PyAV
(bundles ffmpeg), so no system ffmpeg install is needed.

## Configure

Copy `.env.example` to `.env` and fill in what you need. With no keys at all,
the core VAD path still runs using the `mock` STT and a pass-through LLM.

| Variable | Purpose |
| --- | --- |
| `VAD_PROXY_STT_BACKEND` | `mock` \| `deepgram` \| `openai` |
| `VAD_PROXY_LLM_ENABLED` | toggle the DeepSeek smart-layer |
| `VAD_PROXY_OUTPUT` | `stdout` \| `webhook` \| `openai_chat` |

See `.env.example` for the full list.

## Usage

Transcribe a file (great for testing):

```bash
vad-proxy transcribe references/audio/test-123.mp3
```

Run the 24/7 WebSocket listener (clients stream raw 16 kHz mono PCM):

```bash
vad-proxy serve
```

**GraphQL voice API** (recommended for browser clients): token-authenticated
`graphql-transport-ws` at `/graphql` — subscribe to `listen`, stream base64 PCM via
`appendAudio`, receive `transcript` events. See [docs/INTEGRATION.md](docs/INTEGRATION.md)
and the runnable demo at [examples/browser-voice/index.html](examples/browser-voice/index.html).

## Run with Docker

The recommended way to run the 24/7 listener in production:

```bash
cp .env.example .env          # optional: add API keys
docker compose up --build -d
```

- **WebSocket (legacy):** `ws://localhost:8080/ws`
- **GraphQL WebSocket:** `ws://localhost:8080/graphql` (`connectionParams.token` when `VAD_PROXY_AUTH_TOKEN` is set)
- **Health:** `http://localhost:8080/health`
- **Logs:** `logs/vad-proxy.log` on the host (bind-mounted from `/app/logs`)
- **Data:** `data/` on the host (utterance logging, if enabled)

Logs include operational events (server startup, connections) and every
finalized transcript line. They are also mirrored to `docker logs vad-proxy`.

Stop the container:

```bash
docker compose down
```

Full restart with a clean log file (drops old errors/transcripts from prior runs):

```bash
./scripts/docker-restart.sh
```

## Testing

```bash
pytest                 # offline tests + end-to-end CLI smoke test
```

The end-to-end smoke test runs the installed CLI against the bundled
`tests/data/test-123.mp3` clip ("Hello this is a test, one two three") in a
fresh subprocess and asserts the utterance is detected and transcribed.

> Note: on some virtualized CPUs the Silero model can be numerically unstable
> across process launches. The product itself is reliable when run normally;
> see [KNOWN_ISSUES.md](KNOWN_ISSUES.md) for details and mitigations.

## Deploy (voice.biosystems.dev)

Production deploy behind nginx + Let's Encrypt with a locked-down ufw ruleset is
documented in [deploy/deploy.md](deploy/deploy.md). Run `sudo bash deploy/setup-server.sh`
on the server, then `docker compose up -d --build`.

## Roadmap: personalization

v1 ships the **interfaces** for getting to know your voice over time
(`enroll`, `verify`, `bias_vocabulary`, `record_sample`) plus optional
utterance logging to build a personal dataset. Real speaker verification and
adaptation are tracked in `src/vad_proxy/personalization/README.md`.

## License

MIT. See `LICENSE` and `NOTICE` (credits Silero VAD and Pipecat as design
references).
