#!/usr/bin/env bash
# One-time setup of a fresh Ubuntu 22.04/24.04 VPS for trading-platform.
#
# Usage (as root on the server):
#   DOMAIN=example.com LETSENCRYPT_EMAIL=you@example.com \
#   DEPLOY_PUBKEY="ssh-ed25519 AAAA... github-actions" \
#   bash bootstrap.sh
#
# What it does:
#   - creates a `deploy` user (docker group, key-only SSH) used by GitHub Actions
#   - installs Docker + compose plugin, nginx, certbot, fail2ban
#   - firewall: only 22/80/443 open (compose binds everything else to 127.0.0.1)
#   - adds 2G swap (backtester + 3 Postgres can spike RAM)
#   - renders nginx config for DOMAIN + signals./backtester./logs. subdomains
#   - issues Let's Encrypt certs (DNS A-records must already point here)
#
# Safe to re-run.
set -euo pipefail

: "${DOMAIN:?set DOMAIN=your-domain.com}"
: "${LETSENCRYPT_EMAIL:?set LETSENCRYPT_EMAIL}"
: "${DEPLOY_PUBKEY:?set DEPLOY_PUBKEY to the public half of the GitHub Actions SSH key}"

APP_DIR=/opt/trading-platform
DEPLOY_USER=deploy
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

export DEBIAN_FRONTEND=noninteractive

echo "==> Packages"
apt-get update -y
apt-get upgrade -y
apt-get install -y ca-certificates curl gnupg ufw fail2ban nginx certbot python3-certbot-nginx gettext-base unattended-upgrades

echo "==> Docker"
if ! command -v docker >/dev/null; then
  curl -fsSL https://get.docker.com | sh
fi
systemctl enable --now docker

# Cap container logs so promtail/json-file never fills the disk
cat > /etc/docker/daemon.json <<'EOF'
{
  "log-driver": "json-file",
  "log-opts": { "max-size": "20m", "max-file": "5" }
}
EOF
systemctl restart docker

echo "==> Deploy user"
id "$DEPLOY_USER" >/dev/null 2>&1 || useradd -m -s /bin/bash "$DEPLOY_USER"
usermod -aG docker "$DEPLOY_USER"
install -d -m 700 -o "$DEPLOY_USER" -g "$DEPLOY_USER" "/home/$DEPLOY_USER/.ssh"
AUTH_KEYS="/home/$DEPLOY_USER/.ssh/authorized_keys"
touch "$AUTH_KEYS"
grep -qxF "$DEPLOY_PUBKEY" "$AUTH_KEYS" || echo "$DEPLOY_PUBKEY" >> "$AUTH_KEYS"
chown "$DEPLOY_USER:$DEPLOY_USER" "$AUTH_KEYS"
chmod 600 "$AUTH_KEYS"

install -d -o "$DEPLOY_USER" -g "$DEPLOY_USER" "$APP_DIR"

echo "==> SSH hardening (key-only)"
# sshd uses the FIRST value it reads, and cloud-init ships 50-cloud-init.conf
# with PasswordAuthentication yes, so our file must sort before it.
rm -f /etc/ssh/sshd_config.d/99-hardening.conf
cat > /etc/ssh/sshd_config.d/00-hardening.conf <<'EOF'
PasswordAuthentication no
KbdInteractiveAuthentication no
PermitRootLogin prohibit-password
EOF
systemctl reload ssh 2>/dev/null || systemctl reload sshd

echo "==> Firewall"
ufw allow OpenSSH
ufw allow 80/tcp
ufw allow 443/tcp
ufw --force enable
systemctl enable --now fail2ban

echo "==> Swap"
# Providers often pre-create a small /swapfile; make sure it is at least 2G
SWAP_BYTES=$(stat -c %s /swapfile 2>/dev/null || echo 0)
if [ "$SWAP_BYTES" -lt $((2 * 1024 * 1024 * 1024)) ]; then
  swapoff /swapfile 2>/dev/null || true
  rm -f /swapfile
  fallocate -l 2G /swapfile
  chmod 600 /swapfile
  mkswap /swapfile
  swapon /swapfile
  grep -q '^/swapfile ' /etc/fstab || echo '/swapfile none swap sw 0 0' >> /etc/fstab
fi

echo "==> nginx"
DOMAIN="$DOMAIN" envsubst '${DOMAIN}' \
  < "$SCRIPT_DIR/nginx/trading.conf.template" \
  > /etc/nginx/sites-available/trading.conf
ln -sf /etc/nginx/sites-available/trading.conf /etc/nginx/sites-enabled/trading.conf
rm -f /etc/nginx/sites-enabled/default
nginx -t
systemctl reload nginx

echo "==> TLS certificates"
certbot --nginx --non-interactive --agree-tos --redirect \
  -m "$LETSENCRYPT_EMAIL" \
  -d "$DOMAIN" -d "signals.$DOMAIN" -d "backtester.$DOMAIN" -d "logs.$DOMAIN"

echo
echo "Done. Next: add GitHub secrets (see deploy/README.md) and run the Deploy workflow."
