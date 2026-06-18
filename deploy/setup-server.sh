#!/usr/bin/env bash
# Install nginx + certbot, configure voice.biosystems.dev, enable ufw.
# Re-runnable: skips steps that are already done.
set -euo pipefail

DOMAIN="voice.biosystems.dev"
EMAIL="${CERTBOT_EMAIL:-admin@biosystems.dev}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
NGINX_SITE="voice.biosystems.dev.conf"

if [[ "${EUID}" -ne 0 ]]; then
  echo "Run as root: sudo bash deploy/setup-server.sh" >&2
  exit 1
fi

export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq nginx certbot python3-certbot-nginx ufw curl

mkdir -p /var/www/certbot
install -m 0644 "${SCRIPT_DIR}/nginx/${NGINX_SITE}" \
  "/etc/nginx/sites-available/${NGINX_SITE}"
ln -sf "/etc/nginx/sites-available/${NGINX_SITE}" \
  "/etc/nginx/sites-enabled/${NGINX_SITE}"
rm -f /etc/nginx/sites-enabled/default

# If certs are missing, use a temporary HTTP-only bootstrap so nginx -t passes.
if [[ ! -f "/etc/letsencrypt/live/${DOMAIN}/fullchain.pem" ]]; then
  cat > "/etc/nginx/sites-available/${NGINX_SITE}.bootstrap" <<'BOOT'
server {
    listen 80;
    listen [::]:80;
    server_name voice.biosystems.dev;
    location /.well-known/acme-challenge/ { root /var/www/certbot; }
    location / {
        proxy_pass http://127.0.0.1:8080;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
    }
}
BOOT
  ln -sf "/etc/nginx/sites-available/${NGINX_SITE}.bootstrap" \
    "/etc/nginx/sites-enabled/${NGINX_SITE}"
fi

nginx -t
systemctl enable nginx
systemctl reload nginx

if [[ ! -f "/etc/letsencrypt/live/${DOMAIN}/fullchain.pem" ]]; then
  certbot certonly --webroot -w /var/www/certbot \
    -d "${DOMAIN}" --non-interactive --agree-tos -m "${EMAIL}" \
    || certbot --nginx -d "${DOMAIN}" --non-interactive --agree-tos -m "${EMAIL}"
  ln -sf "/etc/nginx/sites-available/${NGINX_SITE}" \
    "/etc/nginx/sites-enabled/${NGINX_SITE}"
  nginx -t
  systemctl reload nginx
fi

# --- ufw: preserve SSH, allow 80/443 only ---------------------------------
SSH_PORT="$(ss -tlnp 2>/dev/null | awk '/sshd/ && /LISTEN/ {split($4,a,":"); print a[length(a)]; exit}')"
if [[ -z "${SSH_PORT}" ]]; then
  SSH_PORT="$(grep -E '^Port[[:space:]]+' /etc/ssh/sshd_config 2>/dev/null | awk '{print $2}' | tail -1)"
fi
SSH_PORT="${SSH_PORT:-22}"

ufw --force reset
ufw default deny incoming
ufw default allow outgoing
ufw allow "${SSH_PORT}/tcp" comment 'SSH'
ufw allow 80/tcp comment 'HTTP ACME + redirect'
ufw allow 443/tcp comment 'HTTPS / WSS'
ufw --force enable
ufw status verbose

echo ""
echo "Setup complete. From ${REPO_ROOT}:"
echo "  docker compose up -d --build"
echo "  curl -s https://${DOMAIN}/health"
