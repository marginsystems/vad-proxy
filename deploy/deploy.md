# Deploying vad-proxy at voice.biosystems.dev

Production layout:

```
Internet ──► nginx (443/80, TLS) ──► 127.0.0.1:8080 (Docker vad-proxy)
```

The app container binds only to **localhost**; nginx terminates TLS and proxies
WebSocket upgrades for `/graphql` and `/health`.

## Prerequisites

- DNS `voice.biosystems.dev` → server public IP (grey-cloud / DNS-only for
  HTTP-01).
- `.env` on the server with API keys and `VAD_PROXY_AUTH_TOKEN`.
- Docker and docker compose.

## Quick start

```bash
cd /path/to/vad-proxy
cp .env.example .env   # edit secrets
sudo bash deploy/setup-server.sh
docker compose up -d --build
```

`setup-server.sh` installs nginx + certbot, copies the site config, obtains a
Let's Encrypt certificate, enables a TCP-only ufw ruleset (SSH + 80/443), and
reloads nginx.

## Manual steps

### 1. Bind Docker to localhost

`docker-compose.yml` maps `127.0.0.1:8080:8080` so the app is not reachable
directly from the internet.

### 2. nginx

```bash
sudo cp deploy/nginx/voice.biosystems.dev.conf /etc/nginx/sites-available/
sudo ln -sf /etc/nginx/sites-available/voice.biosystems.dev.conf /etc/nginx/sites-enabled/
sudo nginx -t && sudo systemctl reload nginx
```

### 3. TLS (Let's Encrypt)

```bash
sudo certbot --nginx -d voice.biosystems.dev --non-interactive --agree-tos -m admin@biosystems.dev
```

Certbot installs a systemd timer for renewal.

### 4. Firewall (ufw)

```bash
# Detect SSH port first — do not lock yourself out
SSH_PORT=$(ss -tlnp | awk '/sshd/ && /LISTEN/ {split($4,a,":"); print a[length(a)]; exit}')
sudo ufw default deny incoming
sudo ufw default allow outgoing
sudo ufw allow "${SSH_PORT}/tcp"
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp
sudo ufw --force enable
```

No UDP ports are opened. Port 8080 stays closed (localhost only).

## Verification

```bash
curl -s https://voice.biosystems.dev/health | jq .
```

GraphQL WebSocket (with token):

```bash
# Use examples/browser-voice/index.html or the integration test against wss://voice.biosystems.dev/graphql
```

## Logs

- App: `./logs/vad-proxy.log` (bind-mounted from the container)
- nginx: `/var/log/nginx/access.log`, `error.log`

## Updating

```bash
git pull
docker compose up -d --build
sudo nginx -t && sudo systemctl reload nginx
```
