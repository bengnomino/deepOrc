#!/usr/bin/env bash
# First-time VPS setup: Incus, Headscale, Caddy, orchestrator (fresh DB, no migration).
# Usage: sudo ./deploy/bootstrap-vps.sh [path/to/host.env]
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib/common.sh
source "$SCRIPT_DIR/lib/common.sh"

require_root

ENV_FILE="${1:-${HOST_ENV:-$SCRIPT_DIR/hosts/host.env}}"
load_host_env "$ENV_FILE"
save_host_env "$ENV_FILE"

log "Bootstrap VPS for ${DOMAIN} (zone ${BASE_DOMAIN}, ${HOST_PUBLIC_IP})"
log "Headscale MagicDNS base: ${HEADSCALE_BASE_DOMAIN}"

wait_for_apt
apt_install update -qq
apt_install install -y -qq \
  git curl ca-certificates python3 python3-venv python3-pip rsync jq \
  incus caddy nftables

HOST_ENV="$ENV_FILE" "$SCRIPT_DIR/install-caddy.sh"

if [[ -n "${GIT_REPO:-}" ]] && [[ ! -d "$APP_DIR/.git" ]]; then
  log "Cloning ${GIT_REPO} → ${APP_DIR}"
  git clone --branch "${GIT_REF:-main}" "$GIT_REPO" "$APP_DIR"
elif [[ ! -d "$APP_DIR/deploy" ]]; then
  log "Copying project to ${APP_DIR}"
  mkdir -p "$(dirname "$APP_DIR")"
  rsync -a --exclude .venv --exclude .git --exclude data \
    "$SCRIPT_DIR/.." "$APP_DIR"
fi

install_headscale_package

export ORCH_HOST_IP
"$SCRIPT_DIR/bootstrap-incus.sh"

log "Fresh Headscale database and keys"
stop_headscale_until_configured
rm -f /var/lib/headscale/db.sqlite /var/lib/headscale/db.sqlite-shm /var/lib/headscale/db.sqlite-wal
rm -f /etc/headscale/private.key /var/lib/headscale/noise_private.key

render_headscale_config "$APP_DIR"
HEADSCALE_POLICY_FILES_ONLY=1 "$SCRIPT_DIR/setup-headscale-policy.sh"
"$SCRIPT_DIR/setup-headscale-keys.sh"
start_headscale 90
"$SCRIPT_DIR/setup-headscale-identity.sh"
headscale policy check -f /etc/headscale/policy.hujson

"$SCRIPT_DIR/firewall-nft.sh" "$ENV_FILE"

if [[ -n "${CLOUDFLARE_API_TOKEN:-}" ]]; then
  retry 3 5 "$SCRIPT_DIR/cloudflare-setup.sh" "$ENV_FILE" \
    || warn "Cloudflare setup failed — fix token/zone and re-run deploy/cloudflare-setup.sh"
else
  log "No CLOUDFLARE_API_TOKEN — set DNS manually: ${DOMAIN} → ${HOST_PUBLIC_IP} (proxied recommended)"
fi

if [[ "${ORIGIN_TLS:-internal}" == "letsencrypt" ]]; then
  "$SCRIPT_DIR/obtain-tls-cert.sh" "$ENV_FILE"
fi

HOST_ENV="$ENV_FILE" FRESH_INSTALL=1 "$SCRIPT_DIR/install-app.sh" "$ENV_FILE"
render_caddyfile "$APP_DIR"
save_host_env "$ENV_FILE"

"$SCRIPT_DIR/import-bundled-images.sh"

log "Verifying stack"
wait_for_http "http://127.0.0.1:8000/orchestrator/health" 120

if [[ "${SKIP_SMOKE_GATEWAY:-0}" != "1" ]]; then
  log "Running gateway smoke test (set SKIP_SMOKE_GATEWAY=1 to skip)"
  SMOKE_GATEWAY_NAME="${SMOKE_GATEWAY_NAME:-smoke-gw}" \
  SMOKE_GATEWAY_KEEP="${SMOKE_GATEWAY_KEEP:-0}" \
  bash "$SCRIPT_DIR/smoke-gateway.sh" "$ENV_FILE"
else
  warn "SKIP_SMOKE_GATEWAY=1 — bootstrap will not verify gateway provisioning"
fi

if [[ -n "${CLOUDFLARE_API_TOKEN:-}" && "${CLOUDFLARE_DNS_PROXIED:-true}" != "false" ]]; then
  cf_code=$(curl -sS -o /dev/null -w '%{http_code}' --max-time 20 "https://${DOMAIN}/orchestrator/health" || echo 000)
  if [[ "$cf_code" == "526" ]]; then
    echo "Cloudflare 526 — origin TLS invalid (check ORIGIN_TLS=letsencrypt and /etc/caddy/ssl/ from ${BASE_DOMAIN})" >&2
    exit 1
  fi
  log "Public HTTPS check: HTTP ${cf_code} (302 Access login is OK)"
fi
API_CHECK=$(curl -sf -H "X-Api-Key: ${API_KEY}" "http://127.0.0.1:8000/orchestrator/api/v1/monitoring/gateways" || true)
HS_USER=$(headscale users list -o json 2>/dev/null | jq -r '.[] | select(.name=="gateways") | .name' || true)
HS_POLICY=$(headscale policy check -f /etc/headscale/policy.hujson 2>&1 && echo ok || true)
GOLDEN=$(incus image list local: -f csv -c L | grep -x gw-golden || true)
[[ -n "$API_CHECK" ]] || { warn "Orchestrator API check failed"; exit 1; }
[[ "$HS_USER" == "gateways" ]] || { warn "Headscale user gateways missing"; exit 1; }
[[ "$HS_POLICY" == *ok* ]] || { warn "Headscale policy check failed"; exit 1; }
[[ -n "$GOLDEN" ]] || { warn "Golden image missing"; exit 1; }
headscale version | head -1

"$SCRIPT_DIR/bootstrap-cleanup.sh" "$ENV_FILE"

cat <<EOF

Bootstrap complete (fresh install).

  Domain:     https://${DOMAIN}
  API key:    ${API_KEY}
  UI:         https://${DOMAIN}/orchestrator/ui/
  Headscale:  https://${DOMAIN}  (MagicDNS: *.${HEADSCALE_BASE_DOMAIN})

Next:
  1. Register exit node Android (UI → Auth key, or deploy/headscale-keys.sh)
  2. Create gateways from the dashboard (smoke test already verified provisioning)

Updates:
  cd ${APP_DIR} && sudo ./deploy/update.sh

EOF
