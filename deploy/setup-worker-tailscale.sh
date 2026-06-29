#!/usr/bin/env bash
# Join worker VPS to Headscale tailnet (tag:worker-host).
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib/common.sh
source "$SCRIPT_DIR/lib/common.sh"

ENV_FILE="${1:-${WORKER_ENV:-$SCRIPT_DIR/hosts/worker1.env}}"
load_worker_env "$ENV_FILE"

if ! command -v tailscale >/dev/null 2>&1; then
  log "Installing Tailscale client"
  curl -fsSL https://tailscale.com/install.sh | sh
fi

AUTHKEY="${TAILSCALE_AUTHKEY:-}"
if [[ -z "$AUTHKEY" ]]; then
  echo "Set TAILSCALE_AUTHKEY (run deploy/headscale-worker-key.sh on the CP)" >&2
  exit 1
fi

tailscale up \
  --login-server="${HEADSCALE_URL}" \
  --authkey="${AUTHKEY}" \
  --hostname="${TAILSCALE_HOSTNAME}" \
  --accept-routes \
  --reset

retry 30 2 tailscale status >/dev/null
TS_IP="$(tailscale ip -4)"
log "Tailscale online: ${TAILSCALE_HOSTNAME} → ${TS_IP}"
