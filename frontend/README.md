# vad-proxy Voice Lab

Live-test **mic → VAD → STT → transcript** against a local vad-proxy server.

## Prerequisites

1. vad-proxy running on the same machine (Docker recommended):

```bash
cd ..   # repo root
cp .env.example .env   # optional: add STT keys + VAD_PROXY_AUTH_TOKEN
docker compose up -d --build
```

2. Node.js 18+ and npm.

## Quick start

```bash
npm install
npm run dev
```

Open **http://localhost:5173**

- **WebSocket URL** defaults to `ws://127.0.0.1:8080/graphql` (matches Docker bind on localhost).
- **Auth token**: paste `VAD_PROXY_AUTH_TOKEN` from your `.env` if the server requires it.
- Click **Start listening**, speak, watch transcripts appear.

## Controls

| Button | Action |
|--------|--------|
| **Local / Production** | Switch WS URL preset |
| **Refresh health** | Re-fetch `GET /health` from the server |
| **Start listening** | Open GraphQL subscription + mic stream |
| **End utterance** | Flush in-progress audio to the VAD segmenter |
| **Stop** | Stop mic, end session, close WebSocket |

## Troubleshooting

| Symptom | Fix |
|---------|-----|
| Health check failed | Run `docker compose up -d` and confirm `curl http://127.0.0.1:8080/health` |
| 4403 Forbidden | Wrong or missing auth token |
| Mic access failed | Grant browser microphone permission (HTTPS not required on localhost) |
| No transcript | Check `VAD_PROXY_STT_BACKEND` in `.env`; mock STT still returns text for test audio patterns |

## Build

```bash
npm run build    # static files in dist/
npm run preview  # serve production build locally
```

## Protocol

Uses `graphql-ws` against `/graphql`. See [../docs/INTEGRATION.md](../docs/INTEGRATION.md) for the full contract.
