#!/usr/bin/env bash
# Join a fresh VPS to the orchestrator as a gateway worker.
# Env (set by the control-plane enrollment snippet):
#   CP_BASE_URL, ENROLL_TOKEN, TAILSCALE_AUTHKEY,
#   WORKER_NAME, WORKER_DISPLAY_NAME, TAILSCALE_HOSTNAME
set -euo pipefail

require_env() {
  local name=$1
  if [[ -z "${!name:-}" ]]; then
    echo "Missing required env: ${name}" >&2
    exit 1
  fi
}

for var in CP_BASE_URL ENROLL_TOKEN TAILSCALE_AUTHKEY WORKER_NAME WORKER_DISPLAY_NAME TAILSCALE_HOSTNAME; do
  require_env "$var"
done

# Validate URL format and prevent command injection
validate_url() {
  local url="$1"
  local name="$2"
  
  # Check for command injection patterns
  if echo "$url" | grep -qE '[\$\`|;&<>\n]'; then
    echo "Invalid $name: potential command injection detected" >&2
    exit 1
  fi
  
  # Check if URL starts with http:// or https://
  if ! echo "$url" | grep -qE '^https?://'; then
    echo "Invalid $name: must start with http:// or https://" >&2
    exit 1
  fi
  
  # Extract hostname from URL
  local host
  host=$(echo "$url" | sed -E 's|^https?://||' | sed -E 's|/.*||' | sed -E 's|:[0-9]+$||')
  
  # Validate hostname format (no command injection, proper hostname)
  if ! echo "$host" | grep -qE '^[a-zA-Z0-9]([a-zA-Z0-9.-]*[a-zA-Z0-9])?$'; then
    echo "Invalid $name: invalid hostname format" >&2
    exit 1
  fi
  
  return 0
}

# Validate URLs before using them
validate_url "$CP_BASE_URL" "CP_BASE_URL"

if [[ "${EUID}" -ne 0 ]]; then
  echo "Run as root (the enrollment command wraps this script with sudo)." >&2
  exit 1
fi

log() { printf '==> %s\n' "$*"; }

detect_public_ip() {
  curl -sf --max-time 5 https://api.ipify.org \
    || curl -sf --max-time 5 https://ifconfig.me/ip \
    || true
}

packages_url_from_cp_base() {
  local base="${1%/}"
  base="${base%/orchestrator}"
  echo "${base}/packages"
}

_http_content_length() {
  curl -fsI "$1" 2>/dev/null | awk 'tolower($1) == "content-length:" { print $2 }' | tr -d '\r'
}

download_with_progress() {
  local url=$1 dest=$2
  local label=${3:-Downloading}

  log "${label}"
  if command -v pv >/dev/null 2>&1; then
    local size
    size="$(_http_content_length "$url" || true)"
    if [[ -n "${size:-}" && "${size:-0}" -gt 0 ]]; then
      curl -fsL "$url" | pv -pte -s "$size" >"$dest" || return 1
    else
      curl -fsL "$url" | pv -pte >"$dest" || return 1
    fi
  else
    curl -fL --progress-bar "$url" -o "$dest" || return 1
    printf '\n'
  fi
  log "${label} — done ($(du -h "$dest" | awk '{print $1}'))"
}

extract_tarball_with_progress() {
  local archive=$1 dest=$2

  log "Extracting worker bundle…"
  if command -v pv >/dev/null 2>&1; then
    pv "$archive" | tar -xzf - -C "$dest"
  else
    tar -xzf "$archive" -C "$dest"
  fi
  log "Extracting worker bundle — done"
}

disable_exim4() {
  if ! dpkg-query -W -f='${Status}' exim4 2>/dev/null | grep -q 'install ok installed'; then
    return 0
  fi
  log "Removing exim4 (not needed on worker VPS)"
  systemctl disable --now exim4 2>/dev/null || true
  DEBIAN_FRONTEND=noninteractive apt-get remove -y -qq exim4 2>/dev/null \
    || DEBIAN_FRONTEND=noninteractive apt-get purge -y -qq exim4 2>/dev/null \
    || true
}

fetch_worker_bundle() {
  local app_dir=$1 packages_url=$2
  local version tarball tmp parent

  version="$(curl -fsSL "${packages_url}/worker-bundle.version" 2>/dev/null || date -Iseconds)"
  version="${version//$'\n'/}"
  version="${version// /%20}"
  tarball="${packages_url}/worker-bundle.tar.gz?v=${version}"
  tmp="$(mktemp)"
  if ! download_with_progress "$tarball" "$tmp" "Downloading worker bundle from control plane"; then
    rm -f "$tmp"
    echo "Failed to download ${tarball}" >&2
    exit 1
  fi

  parent="$(dirname "$app_dir")"
  rm -rf "$app_dir"
  mkdir -p "$parent"
  extract_tarball_with_progress "$tmp" "$parent"
  rm -f "$tmp"

  if [[ ! -d "${app_dir}/deploy" ]]; then
    echo "Invalid worker bundle — missing ${app_dir}/deploy" >&2
    exit 1
  fi
}

APP_DIR="${APP_DIR:-/opt/deeporc-worker}"
HEADSCALE_URL="${HEADSCALE_URL:-${CP_BASE_URL%/orchestrator}}"
HEADSCALE_URL="${HEADSCALE_URL%/}"
CP_DOMAIN="${CP_DOMAIN:-${HEADSCALE_URL#https://}}"
CP_DOMAIN="${CP_DOMAIN#http://}"
CP_DOMAIN="${CP_DOMAIN%%/*}"
CP_API_URL="${CP_BASE_URL%/}/api/v1"
PACKAGES_URL="${PACKAGES_URL:-$(packages_url_from_cp_base "$CP_BASE_URL")}"
HOST_PUBLIC_IP="$(detect_public_ip)"
if [[ -z "${HOST_PUBLIC_IP}" ]]; then
  echo "Could not detect public IP on this VPS" >&2
  exit 1
fi

write_worker_env() {
  local path=$1
  {
    printf 'WORKER_NAME=%q\n' "$WORKER_NAME"
    printf 'WORKER_DISPLAY_NAME=%q\n' "$WORKER_DISPLAY_NAME"
    printf 'HOST_PUBLIC_IP=%q\n' "$HOST_PUBLIC_IP"
    printf 'TAILSCALE_HOSTNAME=%q\n' "$TAILSCALE_HOSTNAME"
    printf 'CP_DOMAIN=%q\n' "$CP_DOMAIN"
    printf 'HEADSCALE_URL=%q\n' "$HEADSCALE_URL"
    printf 'CP_API_URL=%q\n' "$CP_API_URL"
    printf 'APP_DIR=%q\n' "$APP_DIR"
    if [[ -n "${WORKER_ID:-}" ]]; then printf 'WORKER_ID=%q\n' "$WORKER_ID"; fi
    if [[ -n "${WORKER_TOKEN:-}" ]]; then printf 'WORKER_TOKEN=%q\n' "$WORKER_TOKEN"; fi
  } >"$path"
}

log "Join worker ${WORKER_NAME} (${HOST_PUBLIC_IP}) → ${CP_BASE_URL}"

export DEBIAN_FRONTEND=noninteractive
log "Updating package lists…"
apt-get update
log "Installing base packages (curl, python3, pv…)…"
apt-get install -y curl ca-certificates python3 rsync jq pv
disable_exim4
log "Installing Incus and nftables (large download, may take several minutes)…"
apt-get install -y incus nftables

mkdir -p /etc/deeporc
write_worker_env /etc/deeporc/worker.env
chmod 600 /etc/deeporc/worker.env

if [[ -d "${APP_DIR}/deploy" && "${WORKER_SKIP_BUNDLE_DOWNLOAD:-0}" == "1" ]]; then
  log "Using existing ${APP_DIR}"
else
  fetch_worker_bundle "${APP_DIR}" "${PACKAGES_URL}"
fi

# shellcheck source=lib/common.sh
source "${APP_DIR}/deploy/lib/common.sh"

export ORCH_HOST_IP="${ORCH_HOST_IP:-10.10.0.1}"
log "Configuring Incus bridge and storage…"
"${APP_DIR}/deploy/bootstrap-incus.sh"

if ! command -v tailscale >/dev/null 2>&1; then
  log "Installing Tailscale client…"
  curl -fsSL https://tailscale.com/install.sh | sh
fi

log "Connecting worker to Headscale tailnet…"
TAILSCALE_AUTHKEY="${TAILSCALE_AUTHKEY}" \
  "${APP_DIR}/deploy/setup-worker-tailscale.sh" /etc/deeporc/worker.env
log "Enabling Incus HTTPS API on tailnet…"
"${APP_DIR}/deploy/setup-worker-incus-https.sh" /etc/deeporc/worker.env
log "Applying worker firewall rules…"
"${APP_DIR}/deploy/firewall-worker-nft.sh" /etc/deeporc/worker.env
log "Importing bundled gateway golden image…"
"${APP_DIR}/deploy/import-bundled-images.sh"

TS_IP="$(tailscale ip -4)"
log "Tailscale IP: ${TS_IP}"

log "Creating Incus trust token for control plane…"
TRUST_TOKEN="$(incus config trust add control-plane 2>/dev/null | awk '/^eyJ/ {print; exit}')"
if [[ -z "${TRUST_TOKEN}" ]]; then
  echo "Failed to obtain Incus trust token" >&2
  exit 1
fi

log "Registering worker with control plane…"
PAYLOAD=$(jq -n \
  --arg hostname "${TAILSCALE_HOSTNAME}" \
  --arg ip "${TS_IP}" \
  --arg token "${TRUST_TOKEN}" \
  --arg public_ip "${HOST_PUBLIC_IP}" \
  '{tailscale_hostname: $hostname, tailscale_ip: $ip, incus_trust_token: $token, public_ip: $public_ip}')

RESP=$(curl -sf -X POST "${CP_API_URL}/workers/enroll/complete" \
  -H "Content-Type: application/json" \
  -H "X-Enroll-Token: ${ENROLL_TOKEN}" \
  -d "${PAYLOAD}")

WORKER_ID=$(echo "${RESP}" | jq -r '.id')
WORKER_TOKEN=$(echo "${RESP}" | jq -r '.worker_token')
if [[ -z "${WORKER_ID}" || "${WORKER_ID}" == "null" || -z "${WORKER_TOKEN}" || "${WORKER_TOKEN}" == "null" ]]; then
  echo "Enrollment failed: ${RESP}" >&2
  exit 1
fi

write_worker_env /etc/deeporc/worker.env
chmod 600 /etc/deeporc/worker.env

log "Starting worker heartbeat service…"
"${APP_DIR}/deploy/install-worker-heartbeat.sh" "${APP_DIR}"

log "Worker ${WORKER_NAME} enrolled (id=${WORKER_ID}, public_ip=${HOST_PUBLIC_IP})"
