#!/usr/bin/env bash
# Origin Let's Encrypt via DNS-01 — runs certbot at most once per BASE_DOMAIN.
# Usage: sudo ./deploy/obtain-tls-cert.sh [path/to/host.env]
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib/common.sh
source "$SCRIPT_DIR/lib/common.sh"

ENV_FILE="${1:-${HOST_ENV:-$SCRIPT_DIR/hosts/host.env}}"
load_host_env "$ENV_FILE"

if [[ "${ORIGIN_TLS:-internal}" != "letsencrypt" ]]; then
  log "ORIGIN_TLS=${ORIGIN_TLS:-internal} — skip certbot"
  exit 0
fi

if [[ -z "${CLOUDFLARE_API_TOKEN:-}" ]]; then
  echo "ORIGIN_TLS=letsencrypt requires CLOUDFLARE_API_TOKEN (DNS-01)" >&2
  exit 1
fi

CERT_NAME="${BASE_DOMAIN}"
CERT_DIR="$(cert_le_lineage_dir)"
CADDY_SSL="/etc/caddy/ssl/fullchain.pem"
CF_INI="/etc/letsencrypt/cloudflare.ini"
RENEWAL_CONF="/etc/letsencrypt/renewal/${BASE_DOMAIN}.conf"

if origin_tls_installed; then
  log "Origin TLS already installed for Caddy: ${CADDY_SSL}"
  exit 0
fi

if cert_le_lineage_present; then
  log "Let's Encrypt lineage ${CERT_NAME} present — installing for Caddy (no certbot run)"
  install_caddy_tls_material "$CERT_DIR"
  exit 0
fi

if [[ -f "$RENEWAL_CONF" ]]; then
  log "Certbot renewal config ${RENEWAL_CONF} exists — installing existing lineage (no certbot run)"
  install_caddy_tls_material "$CERT_DIR"
  exit 0
fi

# Legacy deploys stored the lineage under the service FQDN — reuse, never re-issue.
if [[ "$DOMAIN" != "$BASE_DOMAIN" ]]; then
  legacy_dir="/etc/letsencrypt/live/${DOMAIN}"
  if [[ -f "${legacy_dir}/fullchain.pem" && -f "${legacy_dir}/privkey.pem" ]]; then
    warn "Using legacy cert lineage at ${legacy_dir} — install to Caddy without new certbot run"
    install_caddy_tls_material "$legacy_dir"
    exit 0
  fi
fi

log "Obtaining Let's Encrypt cert once (DNS-01): ${BASE_DOMAIN} + *.${BASE_DOMAIN}"
apt_install install -y -qq certbot python3-certbot-dns-cloudflare

install -m 600 /dev/null "$CF_INI"
cat >"$CF_INI" <<EOF
dns_cloudflare_api_token = ${CLOUDFLARE_API_TOKEN}
EOF

certbot certonly --non-interactive --agree-tos --register-unsafely-without-email \
  --cert-name "$CERT_NAME" \
  --dns-cloudflare \
  --dns-cloudflare-credentials "$CF_INI" \
  --dns-cloudflare-propagation-seconds 30 \
  -d "$BASE_DOMAIN" \
  -d "*.${BASE_DOMAIN}"

if [[ ! -f /etc/letsencrypt/renewal-hooks/deploy/reload-caddy.sh ]]; then
  mkdir -p /etc/letsencrypt/renewal-hooks/deploy
  cat >/etc/letsencrypt/renewal-hooks/deploy/reload-caddy.sh <<'EOF'
#!/bin/sh
set -eu
CERT_DIR="$(dirname "$(readlink -f "$RENEWED_LINEAGE/fullchain.pem")")"
# shellcheck source=lib/common.sh
. /opt/deeporc/deploy/lib/common.sh
install_caddy_tls_material "$CERT_DIR"
systemctl restart caddy
EOF
  chmod 755 /etc/letsencrypt/renewal-hooks/deploy/reload-caddy.sh
fi

install_caddy_tls_material "$CERT_DIR"
log "Origin TLS ready (${CERT_NAME} → /etc/caddy/ssl/)"
