#!/usr/bin/env bash
# Optional: Cloudflare DNS (A records) + Zero Trust Access for /orchestrator/* and /register/*
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib/common.sh
source "$SCRIPT_DIR/lib/common.sh"

ENV_FILE="${1:-${HOST_ENV:-$SCRIPT_DIR/hosts/host.env}}"
load_host_env "$ENV_FILE"

if [[ -z "${CLOUDFLARE_API_TOKEN:-}" ]]; then
  log "CLOUDFLARE_API_TOKEN not set — skip Cloudflare (configure DNS manually)"
  exit 0
fi

cf_api() {
  curl -sf -H "Authorization: Bearer ${CLOUDFLARE_API_TOKEN}" \
    -H "Content-Type: application/json" "$@"
}

log "Cloudflare: verifying API token"
if ! cf_api "https://api.cloudflare.com/client/v4/user/tokens/verify" | jq -e '.success' >/dev/null; then
  echo "Cloudflare API token invalid" >&2
  exit 1
fi

ZONE_NAME="${CLOUDFLARE_ZONE_NAME:-${BASE_DOMAIN}}"
log "Cloudflare: resolving zone ${ZONE_NAME}"
ZONE_ID="${CLOUDFLARE_ZONE_ID:-}"
if [[ -z "$ZONE_ID" ]]; then
  ZONE_ID=$(cf_api "https://api.cloudflare.com/client/v4/zones?name=${ZONE_NAME}" \
    | jq -r '.result[0].id // empty')
fi
if [[ -z "$ZONE_ID" || "$ZONE_ID" == "null" ]]; then
  echo "Cloudflare zone not found for ${ZONE_NAME} — set CLOUDFLARE_ZONE_ID" >&2
  exit 1
fi

upsert_a_record() {
  local host=$1
  local ip=$2
  local proxied_flag=${3:-true}
  local name
  if [[ "$host" == "$ZONE_NAME" ]]; then
    name="$ZONE_NAME"
  else
    name="${host%%.${ZONE_NAME}}.${ZONE_NAME}"
    [[ "$name" == ".${ZONE_NAME}" ]] && name="$ZONE_NAME"
  fi
  local existing
  existing=$(cf_api "https://api.cloudflare.com/client/v4/zones/${ZONE_ID}/dns_records?type=A&name=${host}" \
    | jq -r '.result[0].id // empty')
  local payload
  payload=$(jq -n --arg name "$host" --arg ip "$ip" --argjson proxied "$proxied_flag" \
    '{type:"A",name:$name,content:$ip,ttl:120,proxied:$proxied}')
  if [[ -n "$existing" && "$existing" != "null" ]]; then
    if [[ "$proxied_flag" == "true" ]]; then
      log "Cloudflare DNS: update A ${host} → ${ip} (proxied)"
    else
      log "Cloudflare DNS: update A ${host} → ${ip} (DNS only)"
    fi
    cf_api -X PUT "https://api.cloudflare.com/client/v4/zones/${ZONE_ID}/dns_records/${existing}" \
      -d "$payload" >/dev/null
  else
    if [[ "$proxied_flag" == "true" ]]; then
      log "Cloudflare DNS: create A ${host} → ${ip} (proxied)"
    else
      log "Cloudflare DNS: create A ${host} → ${ip} (DNS only)"
    fi
    cf_api -X POST "https://api.cloudflare.com/client/v4/zones/${ZONE_ID}/dns_records" \
      -d "$payload" >/dev/null
  fi
}

: "${CLOUDFLARE_DNS_PROXIED:=true}"
if [[ "${CLOUDFLARE_SKIP_DNS:-0}" == "1" || "${CLOUDFLARE_SKIP_DNS:-false}" == "true" ]]; then
  log "CLOUDFLARE_SKIP_DNS set — skip A record sync (using existing DNS)"
else
  upsert_a_record "$DOMAIN" "$HOST_PUBLIC_IP" "$CLOUDFLARE_DNS_PROXIED"
fi
log "WireGuard endpoints use VPS IP (${HOST_PUBLIC_IP}), not ${DOMAIN}"

if [[ -z "${CLOUDFLARE_ACCESS_EMAIL:-}" ]]; then
  if [[ "${CLOUDFLARE_ACCESS_SKIP:-0}" == "1" || "${CLOUDFLARE_ACCESS_SKIP:-false}" == "true" ]]; then
    log "CLOUDFLARE_ACCESS_SKIP set — skip Zero Trust Access (ensure dashboard policy allows your login)"
    exit 0
  fi
  echo "CLOUDFLARE_API_TOKEN set but CLOUDFLARE_ACCESS_EMAIL missing." >&2
  echo "Set CLOUDFLARE_ACCESS_EMAIL in host.env, or CLOUDFLARE_ACCESS_SKIP=1 if Access is managed manually." >&2
  exit 1
fi

ACCOUNT_ID="${CLOUDFLARE_ACCOUNT_ID:-}"
if [[ -z "$ACCOUNT_ID" ]]; then
  ACCOUNT_ID=$(cf_api "https://api.cloudflare.com/client/v4/accounts" | jq -r '.result[0].id // empty')
fi
if [[ -z "$ACCOUNT_ID" || "$ACCOUNT_ID" == "null" ]]; then
  echo "Cloudflare account id not found — set CLOUDFLARE_ACCOUNT_ID" >&2
  exit 1
fi

APP_NAME="Orchtest ${DOMAIN}"
existing_app=$(cf_api "https://api.cloudflare.com/client/v4/accounts/${ACCOUNT_ID}/access/apps?domain=${DOMAIN}" \
  | jq -r --arg n "$APP_NAME" '.result[] | select(.name==$n) | .id' | head -1)

app_payload=$(jq -n \
  --arg name "$APP_NAME" \
  --arg domain "$DOMAIN" \
  '{
    name: $name,
    type: "self_hosted",
    domain: $domain,
    session_duration: "24h",
    auto_redirect_to_identity: true,
    destinations: [
      {type: "public", uri: ($domain + "/orchestrator/*")},
      {type: "public", uri: ($domain + "/register/*")}
    ]
  }')

if [[ -n "$existing_app" ]]; then
  log "Cloudflare Access: update app ${APP_NAME}"
  cf_api -X PUT "https://api.cloudflare.com/client/v4/accounts/${ACCOUNT_ID}/access/apps/${existing_app}" \
    -d "$app_payload" >/dev/null
  APP_ID="$existing_app"
else
  log "Cloudflare Access: create app ${APP_NAME}"
  APP_ID=$(cf_api -X POST "https://api.cloudflare.com/client/v4/accounts/${ACCOUNT_ID}/access/apps" \
    -d "$app_payload" | jq -r '.result.id')
fi

policy_payload=$(jq -n \
  --arg name "Allow ${CLOUDFLARE_ACCESS_EMAIL}" \
  --arg email "$CLOUDFLARE_ACCESS_EMAIL" \
  --arg app "$APP_ID" \
  '{
    name: $name,
    decision: "allow",
    include: [{email: {email: $email}}],
    applications: [$app]
  }')

existing_policy=$(cf_api "https://api.cloudflare.com/client/v4/accounts/${ACCOUNT_ID}/access/policies" \
  | jq -r --arg app "$APP_ID" '.result[] | select(.application_id==$app) | .id' | head -1)

if [[ -n "$existing_policy" ]]; then
  cf_api -X PUT "https://api.cloudflare.com/client/v4/accounts/${ACCOUNT_ID}/access/policies/${existing_policy}" \
    -d "$policy_payload" >/dev/null
else
  cf_api -X POST "https://api.cloudflare.com/client/v4/accounts/${ACCOUNT_ID}/access/policies" \
    -d "$policy_payload" >/dev/null
fi

log "Cloudflare Access: allow ${CLOUDFLARE_ACCESS_EMAIL} on /orchestrator/* and /register/*"
