#!/usr/bin/env bash
# Bind Incus HTTPS API to the worker Tailscale IP (CP connects over tailnet).
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib/common.sh
source "$SCRIPT_DIR/lib/common.sh"

require_root

ENV_FILE="${1:-${WORKER_ENV:-$SCRIPT_DIR/hosts/worker1.env}}"
load_worker_env "$ENV_FILE"

TS_IP="$(tailscale ip -4)"
[[ -n "$TS_IP" ]] || { echo "Tailscale not up — run setup-worker-tailscale.sh first" >&2; exit 1; }

incus config set core.https_address "[${TS_IP}]:8443"
systemctl restart incus
retry 20 2 incus list >/dev/null

log "Incus HTTPS on ${TS_IP}:8443"

if [[ "${PRINT_INCUS_TRUST_TOKEN:-0}" == "1" ]]; then
  log "Incus trust token (one-time, for CP incus remote add):"
  incus config trust add control-plane
fi
