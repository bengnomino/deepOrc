#!/usr/bin/env bash
# Fresh Headscale identity: gateways user (policy must already be installed).
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib/common.sh
source "$SCRIPT_DIR/lib/common.sh"

if [[ ! -f /etc/headscale/policy.hujson ]]; then
  "$SCRIPT_DIR/setup-headscale-policy.sh"
else
  wait_for_headscale 90
fi

if headscale users list -o json 2>/dev/null | jq -e '.[] | select(.name=="gateways")' >/dev/null; then
  log "Headscale user exists: gateways"
else
  retry 5 3 headscale users create gateways
  log "Headscale user created: gateways"
fi

for user in workers control; do
  if headscale users list -o json 2>/dev/null | jq -e --arg u "$user" '.[] | select(.name==$u)' >/dev/null; then
    log "Headscale user exists: ${user}"
  else
    retry 5 3 headscale users create "$user"
    log "Headscale user created: ${user}"
  fi
done
