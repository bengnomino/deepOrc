#!/usr/bin/env bash
# Reclaim RAM/disk after bootstrap (apt/pip caches, unused daemons).
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib/common.sh
source "$SCRIPT_DIR/lib/common.sh"

require_root

ENV_FILE="${1:-${HOST_ENV:-$SCRIPT_DIR/hosts/host.env}}"
load_host_env "$ENV_FILE"

log "Post-bootstrap cleanup"

if [[ -d "${APP_DIR}/.venv" ]]; then
  "${APP_DIR}/.venv/bin/pip" cache purge >/dev/null 2>&1 || true
fi

apt_install clean
rm -rf /var/lib/apt/lists/*
mkdir -p /var/lib/apt/lists/partial

# Default Incus bridge is unused (we use orch-br0 only) — drops a dnsmasq instance.
if incus network show incusbr0 >/dev/null 2>&1; then
  if [[ "$(incus network show incusbr0 --format csv -c used_by 2>/dev/null | wc -l)" -le 1 ]]; then
    log "Removing unused Incus network incusbr0"
    incus network delete incusbr0 2>/dev/null || true
  fi
fi

if systemctl is-enabled exim4 >/dev/null 2>&1; then
  log "Disabling exim4 (not needed on orchestrator VPS)"
  disable_exim4
fi

sync
echo 3 >/proc/sys/vm/drop_caches 2>/dev/null || true

log "Cleanup done — stack RSS ~280 MiB idle (+ ~128 MiB per gateway VM)"
