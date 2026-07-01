#!/usr/bin/env bash
# Run on the control-plane VPS after worker bootstrap.
# Adds Incus remote, registers worker in orchestrator, configures heartbeat token.
#
# Usage:
#   sudo ./deploy/register-worker-on-cp.sh deploy/hosts/worker1.env
# Optional:
#   WORKER_SSH=root@146.190.232.35 INCUS_TRUST_TOKEN=... sudo ./deploy/register-worker-on-cp.sh ...
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib/common.sh
source "$SCRIPT_DIR/lib/common.sh"

require_root

WORKER_ENV_FILE="${1:-$SCRIPT_DIR/hosts/worker1.env}"
CP_ENV_FILE="${HOST_ENV:-$SCRIPT_DIR/hosts/host.env}"

load_host_env "$CP_ENV_FILE"
load_worker_env "$WORKER_ENV_FILE"

# Validate SSH hostname if provided
validate_ssh_hostname() {
  local ssh_host="$1"
  
  # Extract user@host format
  local host
  if [[ "$ssh_host" == *"@"* ]]; then
    host="${ssh_host#*@}"
  else
    host="$ssh_host"
  fi
  
  # Check for command injection patterns
  if echo "$host" | grep -qE '[\$\`|;&<>\n]'; then
    echo "Invalid WORKER_SSH: potential command injection detected" >&2
    return 1
  fi
  
  # Validate hostname format (IP or domain)
  if echo "$host" | grep -qE '^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$'; then
    # Valid IPv4
    return 0
  elif echo "$host" | grep -qE '^[a-zA-Z0-9]([a-zA-Z0-9.-]*[a-zA-Z0-9])?$'; then
    # Valid hostname
    return 0
  else
    echo "Invalid WORKER_SSH: invalid hostname format" >&2
    return 1
  fi
}

if [[ -n "${WORKER_SSH:-}" ]]; then
  if ! validate_ssh_hostname "$WORKER_SSH"; then
    exit 1
  fi
fi

REMOTE="${WORKER_NAME}"
DISPLAY="${WORKER_DISPLAY_NAME:-${WORKER_NAME}}"

if ! tailscale status >/dev/null 2>&1; then
  log "CP not on tailnet — running setup-cp-tailscale.sh"
  "$SCRIPT_DIR/setup-cp-tailscale.sh" "$CP_ENV_FILE"
fi

NODE_JSON=$(headscale nodes list -o json | jq -c --arg name "$TAILSCALE_HOSTNAME" \
  '[.[] | select(.name == $name or (.given_name // "" | startswith($name)))][0]')
if [[ -z "$NODE_JSON" || "$NODE_JSON" == "null" ]]; then
  echo "Worker node ${TAILSCALE_HOSTNAME} not found in Headscale — finish Tailscale on worker first" >&2
  exit 1
fi

WORKER_TS_IP=$(echo "$NODE_JSON" | jq -r '.ip_addresses[0] // empty')
[[ -n "$WORKER_TS_IP" ]] || { echo "No Tailscale IP for worker" >&2; exit 1; }

INCUS_URL="https://${WORKER_TS_IP}:8443"
log "Worker tailnet IP: ${WORKER_TS_IP}"

if [[ -z "${INCUS_TRUST_TOKEN:-}" ]]; then
  if [[ -n "${WORKER_SSH:-}" ]]; then
    log "Fetching Incus trust token via SSH ${WORKER_SSH}"
    INCUS_TRUST_TOKEN=$(ssh -o StrictHostKeyChecking=accept-new "$WORKER_SSH" \
      "incus config trust add control-plane 2>/dev/null | awk '/^eyJ/ {print; exit}'" || true)
  fi
fi
if [[ -z "${INCUS_TRUST_TOKEN:-}" ]]; then
  echo "On worker, run: incus config trust add control-plane" >&2
  echo "Then: INCUS_TRUST_TOKEN=<token> $0 $WORKER_ENV_FILE" >&2
  exit 1
fi

incus remote remove "$REMOTE" 2>/dev/null || true
incus remote add "$REMOTE" "$INCUS_URL" --token="$INCUS_TRUST_TOKEN" --accept-certificate

INCUS_CONF="${INCUS_CONF:-/root/.config/incus}"
CLIENT_CERT="${INCUS_CONF}/client.crt"
CLIENT_KEY="${INCUS_CONF}/client.key"
[[ -f "$CLIENT_CERT" && -f "$CLIENT_KEY" ]] || { echo "Missing Incus client certs in ${INCUS_CONF}" >&2; exit 1; }

CERT_DIR="${APP_DIR}/data/incus/${REMOTE}"
mkdir -p "$CERT_DIR"
install -m 600 "$CLIENT_CERT" "$CERT_DIR/client.crt"
install -m 600 "$CLIENT_KEY" "$CERT_DIR/client.key"

SERVER_CERT=""
if [[ -f "${INCUS_CONF}/servercerts/${REMOTE}.crt" ]]; then
  SERVER_CERT="${INCUS_CONF}/servercerts/${REMOTE}.crt"
elif compgen -G "${INCUS_CONF}/servercerts/*.crt" >/dev/null; then
  SERVER_CERT=$(ls -t "${INCUS_CONF}"/servercerts/*.crt | head -1)
fi
if [[ -n "$SERVER_CERT" && -f "$SERVER_CERT" ]]; then
  install -m 644 "$SERVER_CERT" "$CERT_DIR/server.crt"
  SERVER_CERT="$CERT_DIR/server.crt"
fi

PAYLOAD=$(jq -n \
  --arg name "$REMOTE" \
  --arg display "$DISPLAY" \
  --arg public_ip "$HOST_PUBLIC_IP" \
  --arg hostname "$TAILSCALE_HOSTNAME" \
  --arg remote "$REMOTE" \
  --arg url "$INCUS_URL" \
  --arg cert "$CERT_DIR/client.crt" \
  --arg key "$CERT_DIR/client.key" \
  --arg server "${SERVER_CERT:-}" \
  --argjson port_start "$PORT_POOL_START" \
  --argjson port_end "$PORT_POOL_END" \
  --arg ip_net "$IP_POOL_NETWORK" \
  --arg ip_start "$IP_POOL_START" \
  '{
    name: $name,
    display_name: $display,
    public_ip: $public_ip,
    tailscale_hostname: $hostname,
    incus_remote: $remote,
    incus_url: $url,
    incus_cert_path: $cert,
    incus_key_path: $key,
    incus_server_cert_path: (if $server == "" then null else $server end),
    port_pool_start: $port_start,
    port_pool_end: $port_end,
    ip_pool_network: $ip_net,
    ip_pool_start: $ip_start
  }')

API_LOCAL="http://127.0.0.1:8000/orchestrator/api/v1/workers/register"
RESP=$(curl -sf -X POST "$API_LOCAL" \
  -H "X-API-Key: ${API_KEY}" \
  -H "Content-Type: application/json" \
  -d "$PAYLOAD")

WORKER_ID=$(echo "$RESP" | jq -r '.id')
WORKER_TOKEN=$(echo "$RESP" | jq -r '.worker_token')
[[ -n "$WORKER_ID" && "$WORKER_ID" != null ]] || { echo "Register failed: $RESP" >&2; exit 1; }

log "Registered worker id=${WORKER_ID}"

TMP_ENV=$(mktemp)
grep -v '^WORKER_ID=' "$WORKER_ENV_FILE" 2>/dev/null | grep -v '^WORKER_TOKEN=' >"$TMP_ENV" || true
{
  cat "$TMP_ENV"
  echo "WORKER_ID=${WORKER_ID}"
  echo "WORKER_TOKEN=${WORKER_TOKEN}"
} >"$TMP_ENV"
install -m 600 "$TMP_ENV" "$WORKER_ENV_FILE"
rm -f "$TMP_ENV"

if [[ -n "${WORKER_SSH:-}" ]]; then
  log "Pushing worker env + restarting heartbeat on ${WORKER_SSH}"
  scp -o StrictHostKeyChecking=accept-new "$WORKER_ENV_FILE" "${WORKER_SSH}:/etc/deeporc/worker.env"
  ssh "$WORKER_SSH" "systemctl restart worker-heartbeat.service && systemctl is-active worker-heartbeat.service"
fi

cat <<EOF

Worker ${REMOTE} registered.

  ID:           ${WORKER_ID}
  Incus remote: ${REMOTE} → ${INCUS_URL}
  Public WG IP: ${HOST_PUBLIC_IP}

Save token (shown once): ${WORKER_TOKEN}

New gateways will prefer this worker when heartbeat is online.

EOF
