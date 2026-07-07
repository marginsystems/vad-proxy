# vad-proxy Voice Lab

Live-test **mic → VAD → STT → transcript** against a local vad-proxy server.

**[Watch the project walkthrough on YouTube](https://www.youtube.com/watch?v=v0QNBml8gkU)** — overview of architecture and Voice Lab.

## Prerequisites

1. vad-proxy running on the same machine (Docker recommended):

```bash
cd ..   # repo root
cp .env.example .env   # optional: add STT keys
docker compose up -d --build
```

2. Node.js 18+ and npm.

For interim transcripts and the **Chunk debug** panel, enable in `.env`:

```bash
VAD_PROXY_INTERIM_ENABLED=true
VAD_PROXY_DEBUG_INTERIM_CHUNKS=true
```

## Mic capture

Browser clients downsample device-rate Float32 audio to **16 kHz mono Int16**
before `appendAudio`. The resampler low-passes just below 8 kHz (output
Nyquist) before decimation to avoid aliasing sibilants — see `src/lib/resample.ts`.

```bash
npm test   # resample unit tests
```

```bash
npm install
npm run dev
```

Open **http://localhost:5173**

- **WebSocket URL** defaults to `ws://localhost:5173/graphql` — Vite proxies `/graphql` and `/health` to the backend on port 8080, so you only need the frontend port open in dev.
- Localhost origins are always permitted — no auth tokens or keys required.
- Click **Start listening**, speak, watch transcripts appear.

## Panels

| Panel | Purpose |
| --- | --- |
| **Connection** | WS URL preset (Local / Production), health, STT backend |
| **Controls** | Start listening / End utterance / Stop |
| **Transcripts** | Live italic interim + final line |
| **Chunk debug** | Per-slice WAV replay (requires `VAD_PROXY_DEBUG_INTERIM_CHUNKS=true`) |
| **Event log** | Raw GraphQL events |

## Controls

| Button | Action |
| --- | --- |
| **Local / Production** | Switch WS URL preset |
| **Refresh health** | Re-fetch `GET /health` from the server |
| **Start listening** | Open GraphQL subscription + mic stream |
| **End utterance** | Flush in-progress audio to the VAD segmenter |
| **Stop** | Flush utterance, wait for chunk debug, stop mic, close session |

## Troubleshooting

| Symptom | Fix |
| --- | --- |
| Health check failed | Run `docker compose up -d` on the server. In dev, use **Local** mode (`ws://localhost:5173/graphql`) so Vite proxies to port 8080 — you only need port 5173 forwarded, not 8080 |
| 4403 Forbidden | Your browser origin is not in `VAD_PROXY_ALLOWED_ORIGINS` (localhost always works) |
| Mic access failed (Firefox on macOS) | Browser **Allow** is not enough — also enable **Firefox** in System Settings → Privacy & Security → Microphone, then **quit and reopen Firefox**. Incognito is fine once OS access is granted |
| Mic access failed | Grant browser microphone permission (HTTPS not required on localhost) |
| No transcript | Check `VAD_PROXY_STT_BACKEND` in `.env`; mock STT still returns text for test audio patterns |
| Chunk debug empty | Enable `VAD_PROXY_INTERIM_ENABLED` and `VAD_PROXY_DEBUG_INTERIM_CHUNKS` in `.env`, rebuild Docker, then pause / End utterance / Stop to flush a turn |

## Build

```bash
npm run build    # static files in dist/
npm run preview  # serve production build locally
```

## Protocol

Uses `graphql-ws` against `/graphql`. See [../docs/INTEGRATION.md](../docs/INTEGRATION.md) for the full contract.
