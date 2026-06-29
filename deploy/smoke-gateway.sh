#!/usr/bin/env bash
# End-to-end check: create a gateway VM and wait until the agent reports ready.
# Usage: sudo ./deploy/smoke-gateway.sh [path/to/host.env]
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib/common.sh
source "$SCRIPT_DIR/lib/common.sh"

require_root

ENV_FILE="${1:-${HOST_ENV:-$SCRIPT_DIR/hosts/host.env}}"
load_host_env "$ENV_FILE"

: "${SMOKE_GATEWAY_TIMEOUT:=600}"
: "${SMOKE_GATEWAY_KEEP:=0}"
: "${SMOKE_GATEWAY_NAME:=smoke-gw}"

API_BASE="http://127.0.0.1:8000/orchestrator/api/v1"
POLL_INTERVAL=5

log "Smoke test: provisioning gateway ${SMOKE_GATEWAY_NAME} (timeout ${SMOKE_GATEWAY_TIMEOUT}s)"

existing_id=$(curl -sf -H "X-API-Key: ${API_KEY}" "${API_BASE}/gateways" \
  | jq -r --arg n "$SMOKE_GATEWAY_NAME" '.[] | select(.name==$n) | .id' | head -1)
if [[ -n "$existing_id" && "$existing_id" != "null" ]]; then
  log "Removing leftover smoke gateway id=${existing_id}"
  curl -sf -X DELETE -H "X-API-Key: ${API_KEY}" "${API_BASE}/gateways/${existing_id}" >/dev/null || true
  sleep 3
fi

create_payload=$(jq -nc --arg name "$SMOKE_GATEWAY_NAME" '{gateway_name: $name}')
create_resp=$(curl -sf -X POST \
  -H "X-API-Key: ${API_KEY}" \
  -H "Content-Type: application/json" \
  -d "$create_payload" \
  "${API_BASE}/gateways")

gw_id=$(echo "$create_resp" | jq -r '.gateway.id')
job_id=$(echo "$create_resp" | jq -r '.job_id')
log "Created gateway id=${gw_id} job=${job_id}"

deadline=$((SECONDS + SMOKE_GATEWAY_TIMEOUT))
status=""
error_message=""

while (( SECONDS < deadline )); do
  gw_json=$(curl -sf -H "X-API-Key: ${API_KEY}" "${API_BASE}/gateways/${gw_id}")
  status=$(echo "$gw_json" | jq -r '.status')
  error_message=$(echo "$gw_json" | jq -r '.error_message // empty')
  job_json=$(curl -sf -H "X-API-Key: ${API_KEY}" "${API_BASE}/jobs/${job_id}" || echo '{}')
  job_status=$(echo "$job_json" | jq -r '.status // empty')
  job_error=$(echo "$job_json" | jq -r '.error // empty')
  log "  gateway=${status} job=${job_status:-pending}"
  if [[ "$status" == "ready" ]]; then
    log "Smoke test passed: gateway ${SMOKE_GATEWAY_NAME} is ready"
    if [[ "$SMOKE_GATEWAY_KEEP" != "1" ]]; then
      curl -sf -X DELETE -H "X-API-Key: ${API_KEY}" "${API_BASE}/gateways/${gw_id}" >/dev/null
      log "Removed smoke gateway ${gw_id}"
    fi
    exit 0
  fi
  if [[ "$status" == "error" || "$job_status" == "failed" ]]; then
    echo "Smoke test failed for gateway ${gw_id}" >&2
    [[ -n "$error_message" ]] && echo "  gateway: ${error_message}" >&2
    [[ -n "$job_error" ]] && echo "  job: ${job_error}" >&2
    exit 1
  fi
  sleep "$POLL_INTERVAL"
done

echo "Smoke test timed out after ${SMOKE_GATEWAY_TIMEOUT}s (gateway status=${status})" >&2
exit 1
