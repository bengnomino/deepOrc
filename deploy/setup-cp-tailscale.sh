#!/usr/bin/env bash
# Join control-plane VPS to its own Headscale (tag:control-plane) for Incus remote access.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib/common.sh
source "$SCRIPT_DIR/lib/common.sh"

require_root

ENV_FILE="${1:-${HOST_ENV:-$SCRIPT_DIR/hosts/host.env}}"
load_host_env "$ENV_FILE"

TAG="${HEADSCALE_CP_TAG:-tag:control-plane}"
HOSTNAME="${TAILSCALE_CP_HOSTNAME:-control-plane}"

if ! command -v tailscale >/dev/null 2>&1; then
  log "Installing Tailscale client on CP"
  curl -fsSL https://tailscale.com/install.sh | sh
fi

if tailscale status >/dev/null 2>&1; then
  log "Tailscale already running on CP ($(tailscale ip -4 2>/dev/null || true))"
  exit 0
fi

if ! headscale users list -o json 2>/dev/null | jq -e '.[] | select(.name=="control")' >/dev/null; then
  retry 5 3 headscale users create control
  log "Created Headscale user: control"
fi

USER_ID=$(headscale users list -o json | jq -r '.[] | select(.name=="control") | .id')
EXPIRY="${HEADSCALE_PREAUTH_EXPIRY:-876000h}"
AUTHKEY=$(headscale preauthkeys create -u "$USER_ID" --reusable -e "$EXPIRY" --tags "$TAG" -o json | jq -r '.key')

tailscale up \
  --login-server="${HEADSCALE_URL}" \
  --authkey="${AUTHKEY}" \
  --hostname="${HOSTNAME}" \
  --accept-routes \
  --reset

retry 30 2 tailscale status >/dev/null
log "Control plane on tailnet: ${HOSTNAME} → $(tailscale ip -4)"
