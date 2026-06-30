#!/usr/bin/env bash
# First-time gateway worker VPS: Incus, Tailscale, golden image, heartbeat agent.
# Usage: sudo ./deploy/bootstrap-worker-vps.sh [path/to/worker.env]
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib/common.sh
source "$SCRIPT_DIR/lib/common.sh"

require_root

ENV_FILE="${1:-${WORKER_ENV:-$SCRIPT_DIR/hosts/worker1.env}}"
load_worker_env "$ENV_FILE"
save_worker_env "$ENV_FILE"

log "Bootstrap worker ${WORKER_NAME} (${HOST_PUBLIC_IP}) → CP ${CP_DOMAIN}"

wait_for_apt
apt_install update -qq
apt_install install -y -qq \
  curl ca-certificates python3 rsync jq incus nftables
disable_exim4

PACKAGES_URL="${PACKAGES_URL:-$(packages_url_from_domain "$CP_DOMAIN")}"

if [[ ! -d "$APP_DIR/deploy" ]]; then
  if [[ -f "$SCRIPT_DIR/bootstrap-worker-vps.sh" && -d "$SCRIPT_DIR/../orchestrator" ]]; then
    log "Copying project from local checkout → ${APP_DIR}"
    mkdir -p "$(dirname "$APP_DIR")"
    rsync -a --exclude .venv --exclude .git --exclude data \
      "$SCRIPT_DIR/.." "$APP_DIR"
  elif [[ -n "${GIT_REPO:-}" ]]; then
    log "Cloning ${GIT_REPO} → ${APP_DIR}"
    git clone --branch "${GIT_REF:-main}" "$GIT_REPO" "$APP_DIR"
  else
    install_worker_bundle "$APP_DIR" "$PACKAGES_URL"
  fi
fi

export ORCH_HOST_IP
"$APP_DIR/deploy/bootstrap-incus.sh"

if [[ -z "${TAILSCALE_AUTHKEY:-}" ]]; then
  warn "TAILSCALE_AUTHKEY not set — generate on CP: ./deploy/headscale-worker-key.sh"
  warn "Then re-run: TAILSCALE_AUTHKEY=tskey-... $0 $ENV_FILE"
else
  TAILSCALE_AUTHKEY="$TAILSCALE_AUTHKEY" "$APP_DIR/deploy/setup-worker-tailscale.sh" "$ENV_FILE"
  "$APP_DIR/deploy/setup-worker-incus-https.sh" "$ENV_FILE"
fi

"$APP_DIR/deploy/firewall-worker-nft.sh" "$ENV_FILE"
"$APP_DIR/deploy/import-bundled-images.sh"

mkdir -p /etc/deeporc
install -m 600 "$ENV_FILE" /etc/deeporc/worker.env
sed -i "s|^APP_DIR=.*|APP_DIR=${APP_DIR}|" /etc/deeporc/worker.env 2>/dev/null || true

"$APP_DIR/deploy/install-worker-heartbeat.sh" "$APP_DIR"
"$APP_DIR/deploy/install-deeporc-worker-net.sh" "$APP_DIR"

save_worker_env "$ENV_FILE"
install -m 600 "$ENV_FILE" /etc/deeporc/worker.env

apt_install clean 2>/dev/null || true
rm -rf /var/lib/apt/lists/* 2>/dev/null || true
mkdir -p /var/lib/apt/lists/partial 2>/dev/null || true
if incus network show incusbr0 >/dev/null 2>&1; then
  incus network delete incusbr0 2>/dev/null || true
fi

cat <<EOF

Worker bootstrap complete: ${WORKER_NAME} (${HOST_PUBLIC_IP})

On the control plane (165.227.156.103):
  1. Apply Headscale policy (if not yet): sudo ./deploy/setup-headscale-policy.sh
  2. Ensure CP is on tailnet: sudo ./deploy/setup-cp-tailscale.sh
  3. Register worker + Incus remote:
       sudo ./deploy/register-worker-on-cp.sh ${ENV_FILE#$APP_DIR/}

Tailscale IP: $(tailscale ip -4 2>/dev/null || echo 'not connected')
Incus API:    https://$(tailscale ip -4 2>/dev/null || echo TS_IP):8443

EOF
