#!/usr/bin/env bash
# Preauth keys: mobile client (tag:client) and optional gateway exit nodes.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib/common.sh
source "$SCRIPT_DIR/lib/common.sh"

ENV_FILE="${1:-${HOST_ENV:-$SCRIPT_DIR/hosts/host.env}}"
if [[ -f "$ENV_FILE" ]]; then
  load_host_env "$ENV_FILE"
fi

LOGIN_SERVER="${HEADSCALE_URL:-https://deeporc.harlock.network}"
EXPIRY="${HEADSCALE_PREAUTH_EXPIRY:-876000h}"
CLIENT_USER="${HEADSCALE_MOBILE_USER:-gateways}"
CLIENT_TAG="${HEADSCALE_CLIENT_TAG:-tag:client}"

USER_ID=$(headscale users list -o json | python3 -c "import sys,json; u=json.load(sys.stdin); print(next(x['id'] for x in u if x['name']=='${CLIENT_USER}'))")

echo "Mobile client auth key (user=${CLIENT_USER}, tag=${CLIENT_TAG}):"
CLIENT_KEY=$(headscale preauthkeys create -u "$USER_ID" --reusable -e "$EXPIRY" --tags "$CLIENT_TAG" -o json | python3 -c "import sys,json; print(json.load(sys.stdin).get('key',''))")
echo "$CLIENT_KEY"

echo ""
echo "Tailscale app:"
echo "  Login server: ${LOGIN_SERVER}"
echo "  Auth key: ${CLIENT_KEY}"
