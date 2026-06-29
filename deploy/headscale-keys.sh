#!/bin/bash
# Preauth key Headscale per exit node Android (tag:exit, auto-approvazione route).
# Preferire il pulsante "+ Exit node" nella WebUI.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TAG="${HEADSCALE_EXIT_NODE_TAG:-tag:exit}"

USER_ID=$(headscale users list -o json | python3 -c "import sys,json; u=json.load(sys.stdin); print(next(x['id'] for x in u if x['name']=='gateways'))")
EXPIRY="876000h"
LOGIN_SERVER="${HEADSCALE_URL:-https://deeporc.harlock.network}"

echo "=== Preauth key EXIT NODE (${TAG}) ==="
echo "Login server: ${LOGIN_SERVER}"
echo "Sul telefono: tailscale up --login-server=${LOGIN_SERVER} --advertise-exit-node --authkey <KEY>"
echo
headscale preauthkeys create -u "$USER_ID" --reusable -e "$EXPIRY" --tags "$TAG" -o json
