#!/usr/bin/env bash
# Preauth key for gateway worker host (tag:worker-host).
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib/common.sh
source "$SCRIPT_DIR/lib/common.sh"

ENV_FILE="${1:-${HOST_ENV:-$SCRIPT_DIR/hosts/host.env}}"
load_host_env "$ENV_FILE"

TAG="${HEADSCALE_WORKER_TAG:-tag:worker-host}"
EXPIRY="${HEADSCALE_PREAUTH_EXPIRY:-876000h}"

if ! headscale users list -o json 2>/dev/null | jq -e '.[] | select(.name=="workers")' >/dev/null; then
  retry 5 3 headscale users create workers
  log "Created Headscale user: workers"
fi

USER_ID=$(headscale users list -o json | jq -r '.[] | select(.name=="workers") | .id')
echo "=== Preauth key WORKER HOST (${TAG}) ==="
echo "Login server: ${HEADSCALE_URL}"
echo
echo "On worker VPS:"
echo "  TAILSCALE_AUTHKEY=<KEY> sudo ./deploy/bootstrap-worker-vps.sh deploy/hosts/worker1.env"
echo
headscale preauthkeys create -u "$USER_ID" --reusable -e "$EXPIRY" --tags "$TAG" -o json
