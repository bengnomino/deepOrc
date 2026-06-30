#!/usr/bin/env bash
# Bring worker Tailscale online and bind Incus HTTPS to the tailnet IP.
set -euo pipefail

ENV_FILE="${WORKER_ENV_FILE:-/etc/deeporc/worker.env}"
if [[ -f "$ENV_FILE" ]]; then
  # shellcheck disable=SC1090
  source "$ENV_FILE"
fi

HEADSCALE_URL="${HEADSCALE_URL:-https://deeporc.harlock.network}"
TAILSCALE_HOSTNAME="${TAILSCALE_HOSTNAME:-$(hostname -s)}"

if ! command -v tailscale >/dev/null 2>&1; then
  echo "tailscale not installed" >&2
  exit 1
fi

tailscale up \
  --login-server="${HEADSCALE_URL}" \
  --hostname="${TAILSCALE_HOSTNAME}" \
  --accept-routes

TS_IP="$(tailscale ip -4)"
[[ -n "$TS_IP" ]] || { echo "tailscale has no IPv4 address" >&2; exit 1; }

if command -v incus >/dev/null 2>&1; then
  incus config set core.https_address "[${TS_IP}]:8443"
  systemctl restart incus
fi
