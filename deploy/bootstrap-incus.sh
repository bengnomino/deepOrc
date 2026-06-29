#!/usr/bin/env bash
# One-time Incus bootstrap for gateway VMs (storage pool + default profile).
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib/common.sh
source "$SCRIPT_DIR/lib/common.sh"

: "${ORCH_HOST_IP:=10.10.0.1}"
: "${INCUS_BRIDGE:=orch-br0}"

incus_cmd() {
  timeout "${INCUS_CMD_TIMEOUT:-45}" incus "$@"
}

wait_for_incus() {
  retry 20 2 incus list >/dev/null
}

ensure_bridge() {
  local bridge=$1
  local host_ip=$2

  if incus_cmd network show "$bridge" >/dev/null 2>&1; then
    log "Incus network ${bridge} already exists"
    incus_cmd network set "$bridge" ipv4.address "${host_ip}/16" || true
    incus_cmd network set "$bridge" ipv4.nat true || true
    return 0
  fi

  if incus_cmd network show incusbr0 >/dev/null 2>&1; then
    log "Reconfiguring incusbr0 → ${bridge} (${host_ip}/16)"
    incus_cmd network set incusbr0 ipv4.address "${host_ip}/16"
    incus_cmd network set incusbr0 ipv4.nat true
    if [[ "$bridge" != "incusbr0" ]]; then
      if incus profile device get default eth0 network >/dev/null 2>&1; then
        incus profile device remove default eth0 || true
      fi
      incus_cmd network rename incusbr0 "$bridge"
    fi
    return 0
  fi

  log "Creating Incus network ${bridge} (timeout ${INCUS_CMD_TIMEOUT:-45}s)"
  if incus_cmd network create "$bridge" "ipv4.address=${host_ip}/16" ipv4.nat=true ipv4.firewall=false; then
    return 0
  fi

  warn "incus network create timed out — falling back to incus admin init --auto"
  systemctl restart incus
  wait_for_incus
  incus_cmd admin init --auto
  ensure_bridge "$bridge" "$host_ip"
}

if incus storage list --format csv | grep -q '^default,'; then
  echo "Storage pool 'default' already exists"
else
  if ! incus_cmd admin init --auto; then
    echo "incus admin init --auto failed" >&2
    exit 1
  fi
fi

if ! incus profile device get default root path >/dev/null 2>&1; then
  incus profile device add default root disk path=/ pool=default
fi

ensure_bridge "$INCUS_BRIDGE" "$ORCH_HOST_IP"

if ! incus profile device get default eth0 network >/dev/null 2>&1; then
  incus profile device add default eth0 nic "network=${INCUS_BRIDGE}" name=eth0
else
  current_net=$(incus profile device get default eth0 network 2>/dev/null || true)
  if [[ "${current_net}" != "${INCUS_BRIDGE}" ]]; then
    incus profile device set default eth0 network "$INCUS_BRIDGE"
  fi
fi

incus storage list
incus network list
incus profile show default
