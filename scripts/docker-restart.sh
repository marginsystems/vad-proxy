#!/usr/bin/env bash
# Stop vad-proxy, clear bind-mounted log files, and start fresh.
set -euo pipefail
cd "$(dirname "$0")/.."

echo "Stopping container..."
docker compose down

echo "Clearing logs..."
rm -f logs/vad-proxy.log logs/vad-proxy.log.*

echo "Starting container..."
docker compose up --build -d

echo "Done. Fresh logs at logs/vad-proxy.log"
