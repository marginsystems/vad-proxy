# vad-proxy

**LLM-powered voice transcription proxy.**

**[Watch the project walkthrough on YouTube](https://www.youtube.com/watch?v=v0QNBml8gkU)** — architecture, Voice Lab demo, and why local VAD + cloud STT/LLM.

## What it does

`vad-proxy` listens to an audio stream, uses a **local Silero VAD** (~2 MB ONNX, no PyTorch) to detect when you start and stop talking, transcribes speech with a **pluggable cloud STT** backend, runs the raw transcript through a **DeepSeek smart-layer** (fix mis-transcribed words and judge whether you actually finished your turn), and delivers the final text via a **pluggable output adapter** or the GraphQL voice API.

**24/7 listening is cheap:** only local VAD runs continuously. STT fires per interim slice (optional) and/or utterance; the LLM runs **once per finished turn**.

```
audio  ->  decode/resample (16k mono)  ->  Silero VAD  ->  segmenter
       ├─ (optional) interim chunks  ->  STT  ->  live interim transcript
       └─ utterance end  ->  joined STT text  ->  DeepSeek smart-layer  ->  final transcript
                                                              |
                                                              v
                                              output adapter (stdout / webhook / openai_chat)
                                              or GraphQL events to Voice Lab
```

The DeepSeek smart-layer is **not** a chatbot in Voice Lab — it cleans up STT output and sets `turnComplete` / `endPhrase` for downstream apps.

## Features

- Local Silero VAD endpointing (no PyTorch, ~80 MB Docker idle)
- Pluggable STT: Deepgram / OpenAI / mock
- DeepSeek smart-layer: transcript correction + turn detection
- Live interim transcripts with smart word-boundary chunking
- Chunk debug replay in Voice Lab (`VAD_PROXY_DEBUG_INTERIM_CHUNKS`)
- GraphQL WebSocket API for browsers and scripts (see [docs/INTEGRATION.md](docs/INTEGRATION.md))
- Docker + Voice Lab for zero-friction local testing

## Quick start

The fastest way to try it:

```bash
cp .env.example .env          # add DEEPGRAM_API_KEY + DEEPSEEK_API_KEY as needed
docker compose up -d --build
cd frontend && npm install && npm run dev
```

Open **http://localhost:5173** → **Start listening**.

Recommended `.env` for the full Voice Lab experience:

```bash
VAD_PROXY_INTERIM_ENABLED=true
VAD_PROXY_DEBUG_INTERIM_CHUNKS=true
```

Tune chunk boundaries for your voice and mic in [docs/TUNING.md](docs/TUNING.md).

## Voice Lab

**Voice Lab** is the local React dashboard for live-testing mic → VAD → STT → transcript against your Docker container.

| Panel | Purpose |
| --- | --- |
| **Connection** | WebSocket URL (Local uses the Vite proxy), health, STT backend, sample rate |
| **Controls** | Start listening / End utterance / Stop (Stop flushes the utterance and chunk debug) |
| **Transcripts** | Live italic interim line + final transcript with `turnComplete` / `endPhrase` |
| **Chunk debug** | Per-slice WAV replay when interim + debug are enabled |
| **Event log** | Raw GraphQL events |

In dev, Vite proxies `/graphql` and `/health` to port 8080 — use `ws://localhost:5173/graphql` so you only need the frontend port open.

See [frontend/README.md](frontend/README.md) for troubleshooting (Firefox macOS mic, 4403 origins, health checks).

A zero-install HTML demo remains at [examples/browser-voice/index.html](examples/browser-voice/index.html).

## Install (from source)

```bash
pip install -e ".[all,dev]"      # or pick extras: .[deepgram] / .[openai]
python scripts/download_models.py
```

Python 3.11+. No GPU required. mp3/other formats are decoded via PyAV (bundles ffmpeg), so no system ffmpeg install is needed.

## Configure

Copy `.env.example` to `.env` and fill in what you need. With no keys at all, the core VAD path still runs using the `mock` STT and a pass-through LLM.

| Variable | Purpose |
| --- | --- |
| `VAD_PROXY_STT_BACKEND` | `mock` \| `deepgram` \| `openai` |
| `VAD_PROXY_LLM_ENABLED` | Toggle the DeepSeek smart-layer |
| `VAD_PROXY_OUTPUT` | `stdout` \| `webhook` \| `openai_chat` |
| `VAD_PROXY_INTERIM_ENABLED` | Live partial transcripts while speaking |
| `VAD_PROXY_INTERIM_SECS` / `VAD_PROXY_INTERIM_DIP_HOLD_SECS` | Chunk cap + dip sensitivity |
| `VAD_PROXY_DEBUG_INTERIM_CHUNKS` | Chunk debug events for Voice Lab |
| `VAD_PROXY_ALLOWED_ORIGINS` | Production browser origins |
| `DEEPSEEK_API_KEY` | Smart-layer (passthrough if missing) |

See `.env.example` for the full list. For VAD timing and interim chunk tuning, see [docs/TUNING.md](docs/TUNING.md).

## Usage

Transcribe a file (great for testing):

```bash
vad-proxy transcribe references/audio/test-123.mp3
```

Run the 24/7 listener (clients stream raw 16 kHz mono PCM):

```bash
vad-proxy serve
```

**GraphQL voice API** (recommended for browser clients): origin-restricted `graphql-transport-ws` at `/graphql` — subscribe to `listen`, stream base64 PCM via `appendAudio`, receive `transcript` events. Production: `wss://voice.biosystems.dev/graphql`. See [docs/INTEGRATION.md](docs/INTEGRATION.md).

## Run with Docker

The recommended way to run the 24/7 listener in production:

```bash
cp .env.example .env          # optional: add API keys
docker compose up --build -d
```

- **GraphQL WebSocket:** `ws://localhost:8080/graphql` (localhost origins always allowed)
- **Health:** `http://localhost:8080/health`
- **Logs:** `logs/vad-proxy.log` on the host (bind-mounted from `/app/logs`)
- **Data:** `data/` on the host (utterance logging, if enabled)

Logs include operational events (server startup, connections) and every finalized transcript line. They are also mirrored to `docker logs vad-proxy`.

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

Tune interim chunk boundaries against your own audio:

```bash
python scripts/preview_interim_chunks.py path/to/your-sample.mp3
```

See [docs/TUNING.md](docs/TUNING.md) for VAD and interim settings, mic effects, and suggested profiles.

The end-to-end smoke test runs the installed CLI against the bundled `tests/data/test-123.mp3` clip ("Hello this is a test, one two three") in a fresh subprocess and asserts the utterance is detected and transcribed.

> Note: on some virtualized CPUs the Silero model can be numerically unstable across process launches. The product itself is reliable when run normally; see [KNOWN_ISSUES.md](KNOWN_ISSUES.md) for details and mitigations.

## Deploy (voice.biosystems.dev)

Production deploy behind nginx + Let's Encrypt with a locked-down ufw ruleset is documented in [deploy/deploy.md](deploy/deploy.md). Run `sudo bash deploy/setup-server.sh` on the server, then `docker compose up -d --build`.

## Roadmap: personalization

v1 ships the **interfaces** for getting to know your voice over time (`enroll`, `verify`, `bias_vocabulary`, `record_sample`) plus optional utterance logging to build a personal dataset. Real speaker verification and adaptation are tracked in `src/vad_proxy/personalization/README.md`.

## License

MIT. See `LICENSE` and `NOTICE` (credits Silero VAD and Pipecat as design references).
