#!/usr/bin/env bash
# Shared helpers for deploy scripts.
set -euo pipefail

log() {
  printf '==> %s\n' "$*"
}

warn() {
  printf '!! %s\n' "$*" >&2
}

validate_url() {
  local url="$1"
  local name="$2"
  
  # Check if URL starts with http:// or https://
  if ! echo "$url" | grep -qE '^https?://'; then
    echo "Invalid $name: must start with http:// or https://" >&2
    return 1
  fi
  
  # Extract hostname from URL
  local host
  host=$(echo "$url" | sed -E 's|^https?://||' | sed -E 's|/.*||' | sed -E 's|:[0-9]+$||')
  
  # Validate hostname format (no commands, special chars except - and .)
  if ! echo "$host" | grep -qE '^[a-zA-Z0-9]([a-zA-Z0-9.-]*[a-zA-Z0-9])?$'; then
    echo "Invalid $name: invalid hostname format" >&2
    return 1
  fi
  
  # Check for command injection patterns
  if echo "$url" | grep -qE '[\$\`|;&<>]'; then
    echo "Invalid $name: potential command injection detected" >&2
    return 1
  fi
  
  return 0
}

validate_domain() {
  local domain="$1"
  local name="$2"
  
  # Validate domain format
  if ! echo "$domain" | grep -qE '^[a-zA-Z0-9]([a-zA-Z0-9.-]*[a-zA-Z0-9])?$'; then
    echo "Invalid $name: invalid domain format" >&2
    return 1
  fi
  
  # Check for command injection patterns
  if echo "$domain" | grep -qE '[\$\`|;&<>]'; then
    echo "Invalid $name: potential command injection detected" >&2
    return 1
  fi
  
  return 0
}

validate_port() {
  local port="$1"
  local name="$2"
  
  # Validate port is a number
  if ! echo "$port" | grep -qE '^[0-9]+$'; then
    echo "Invalid $name: must be a number" >&2
    return 1
  fi
  
  # Validate port range
  if [ "$port" -lt 1 ] || [ "$port" -gt 65535 ]; then
    echo "Invalid $name: must be between 1 and 65535" >&2
    return 1
  fi
  
  return 0
}

validate_ip_or_domain() {
  local value="$1"
  local name="$2"
  
  # Check if it's an IP address
  if echo "$value" | grep -qE '^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$'; then
    # Validate each octet
    local IFS='.'
    set -- $value
    if [ $# -ne 4 ]; then
      echo "Invalid $name: invalid IP address format" >&2
      return 1
    fi
    for octet in "$1" "$2" "$3" "$4"; do
      if [ "$octet" -lt 0 ] || [ "$octet" -gt 255 ] 2>/dev/null; then
        echo "Invalid $name: IP octet must be 0-255" >&2
        return 1
      fi
    done
    return 0
  fi
  
  # Otherwise validate as domain
  validate_domain "$value" "$name"
}

validate_path() {
  local path="$1"
  local name="$2"
  
  # Check for command injection patterns
  if echo "$path" | grep -qE '[\$\`|;&<>]'; then
    echo "Invalid $name: potential command injection detected" >&2
    return 1
  fi
  
  # Check for relative path traversal
  if echo "$path" | grep -qE '\.\./|\.\.'; then
    echo "Invalid $name: relative path traversal detected" >&2
    return 1
  fi
  
  return 0
}

validate_hostname() {
  local hostname="$1"
  local name="$2"
  
  # Validate hostname format (RFC 1123)
  if ! echo "$hostname" | grep -qE '^[a-zA-Z0-9]([a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?(\.[a-zA-Z0-9]([a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?)*$'; then
    echo "Invalid $name: invalid hostname format" >&2
    return 1
  fi
  
  # Check for command injection
  if echo "$hostname" | grep -qE '[\$\`|;&<>]'; then
    echo "Invalid $name: potential command injection detected" >&2
    return 1
  fi
  
  # Length check
  if [ ${#hostname} -gt 253 ]; then
    echo "Invalid $name: hostname too long (max 253 chars)" >&2
    return 1
  fi
  
  return 0
}

validate_environment_vars() {
  local env_file="$1"
  
  # Source the environment file
  # shellcheck disable=SC1090
  set -a
  # shellcheck disable=SC1091
  source "$env_file"
  set +a
  
  local errors=0
  
  # Validate URLs
  if [ -n "${HEADSCALE_URL:-}" ]; then
    if ! validate_url "$HEADSCALE_URL" "HEADSCALE_URL"; then
      errors=$((errors + 1))
    fi
  fi
  
  if [ -n "${CP_BASE_URL:-}" ]; then
    if ! validate_url "$CP_BASE_URL" "CP_BASE_URL"; then
      errors=$((errors + 1))
    fi
  fi
  
  if [ -n "${CP_DOMAIN:-}" ]; then
    if ! validate_domain "$CP_DOMAIN" "CP_DOMAIN"; then
      errors=$((errors + 1))
    fi
  fi
  
  if [ -n "${DOMAIN:-}" ]; then
    if ! validate_domain "$DOMAIN" "DOMAIN"; then
      errors=$((errors + 1))
    fi
  fi
  
  if [ -n "${BASE_DOMAIN:-}" ]; then
    if ! validate_domain "$BASE_DOMAIN" "BASE_DOMAIN"; then
      errors=$((errors + 1))
    fi
  fi
  
  if [ -n "${SERVICE_HOST:-}" ]; then
    if ! validate_hostname "$SERVICE_HOST" "SERVICE_HOST"; then
      errors=$((errors + 1))
    fi
  fi
  
  # Validate ports
  if [ -n "${PORT_POOL_START:-}" ]; then
    if ! validate_port "$PORT_POOL_START" "PORT_POOL_START"; then
      errors=$((errors + 1))
    fi
  fi
  
  if [ -n "${PORT_POOL_END:-}" ]; then
    if ! validate_port "$PORT_POOL_END" "PORT_POOL_END"; then
      errors=$((errors + 1))
    fi
  fi
  
  # Validate IPs
  if [ -n "${HOST_PUBLIC_IP:-}" ]; then
    if ! validate_ip_or_domain "$HOST_PUBLIC_IP" "HOST_PUBLIC_IP"; then
      errors=$((errors + 1))
    fi
  fi
  
  if [ -n "${ORCH_HOST_IP:-}" ]; then
    if ! validate_ip_or_domain "$ORCH_HOST_IP" "ORCH_HOST_IP"; then
      errors=$((errors + 1))
    fi
  fi
  
  if [ "$errors" -gt 0 ]; then
    echo "Validation failed with $errors error(s)" >&2
    return 1
  fi
  
  return 0
}

validate_worker_env_vars() {
  local env_file="$1"
  
  # Source the environment file
  # shellcheck disable=SC1090
  set -a
  # shellcheck disable=SC1091
  source "$env_file"
  set +a
  
  local errors=0
  
  # Validate URLs
  if [ -n "${HEADSCALE_URL:-}" ]; then
    if ! validate_url "$HEADSCALE_URL" "HEADSCALE_URL"; then
      errors=$((errors + 1))
    fi
  fi
  
  if [ -n "${CP_DOMAIN:-}" ]; then
    if ! validate_domain "$CP_DOMAIN" "CP_DOMAIN"; then
      errors=$((errors + 1))
    fi
  fi
  
  if [ -n "${CP_API_URL:-}" ]; then
    if ! validate_url "$CP_API_URL" "CP_API_URL"; then
      errors=$((errors + 1))
    fi
  fi
  
  # Validate ports
  if [ -n "${PORT_POOL_START:-}" ]; then
    if ! validate_port "$PORT_POOL_START" "PORT_POOL_START"; then
      errors=$((errors + 1))
    fi
  fi
  
  if [ -n "${PORT_POOL_END:-}" ]; then
    if ! validate_port "$PORT_POOL_END" "PORT_POOL_END"; then
      errors=$((errors + 1))
    fi
  fi
  
  # Validate IPs
  if [ -n "${HOST_PUBLIC_IP:-}" ]; then
    if ! validate_ip_or_domain "$HOST_PUBLIC_IP" "HOST_PUBLIC_IP"; then
      errors=$((errors + 1))
    fi
  fi
  
  if [ -n "${ORCH_HOST_IP:-}" ]; then
    if ! validate_ip_or_domain "$ORCH_HOST_IP" "ORCH_HOST_IP"; then
      errors=$((errors + 1))
    fi
  fi
  
  # Validate hostname formats
  if [ -n "${TAILSCALE_HOSTNAME:-}" ]; then
    if ! validate_hostname "$TAILSCALE_HOSTNAME" "TAILSCALE_HOSTNAME"; then
      errors=$((errors + 1))
    fi
  fi
  
  # Validate path formats for repos
  if [ -n "${GIT_REPO:-}" ]; then
    # Check for command injection
    if echo "$GIT_REPO" | grep -qE '[\$\`|;&<>]'; then
      echo "Invalid GIT_REPO: potential command injection detected" >&2
      errors=$((errors + 1))
    fi
    # Allow git URLs (git@, https://, http://)
    if ! echo "$GIT_REPO" | grep -qE '^(git@|https://|http://|file://)'; then
      echo "Invalid GIT_REPO: must be a valid git URL" >&2
      errors=$((errors + 1))
    fi
  fi
  
  if [ -n "${GIT_REF:-}" ]; then
    if echo "$GIT_REF" | grep -qE '[\$\`|;&<>]'; then
      echo "Invalid GIT_REF: potential command injection detected" >&2
      errors=$((errors + 1))
    fi
  fi
  
  if [ "$errors" -gt 0 ]; then
    echo "Worker validation failed with $errors error(s)" >&2
    return 1
  fi
  
  return 0
}

wait_for_apt() {
  local timeout="${1:-600}"
  local elapsed=0
  while fuser /var/lib/dpkg/lock-frontend >/dev/null 2>&1 \
    || fuser /var/lib/apt/lists/lock >/dev/null 2>&1 \
    || fuser /var/cache/apt/archives/lock >/dev/null 2>&1; do
    if (( elapsed >= timeout )); then
      echo "Timed out waiting for apt/dpkg lock after ${timeout}s" >&2
      fuser -v /var/lib/dpkg/lock-frontend 2>/dev/null || true
      exit 1
    fi
    log "Waiting for apt/dpkg lock (${elapsed}s)..."
    sleep 5
    elapsed=$((elapsed + 5))
  done
  DEBIAN_FRONTEND=noninteractive dpkg --configure -a 2>/dev/null || true
}

apt_install() {
  wait_for_apt
  DEBIAN_FRONTEND=noninteractive apt-get "$@"
}

retry() {
  local attempts=$1
  shift
  local delay="${1:-3}"
  if [[ "$delay" =~ ^[0-9]+$ ]]; then
    shift
  else
    delay=3
  fi
  local n=1
  while true; do
    if "$@"; then
      return 0
    fi
    if (( n >= attempts )); then
      return 1
    fi
    warn "Retry $n/$attempts failed: $*"
    sleep "$delay"
    n=$((n + 1))
  done
}

wait_for_systemd() {
  local unit=$1
  local timeout="${2:-120}"
  local elapsed=0
  while ! systemctl is-active --quiet "$unit"; do
    if (( elapsed >= timeout )); then
      journalctl -u "$unit" -n 20 --no-pager >&2 || true
      echo "Timed out waiting for ${unit} to become active" >&2
      return 1
    fi
    sleep 2
    elapsed=$((elapsed + 2))
  done
}

wait_for_headscale() {
  local timeout="${1:-90}"
  wait_for_systemd headscale "$timeout"
  retry 15 3 headscale users list >/dev/null
}

wait_for_http() {
  local url=$1
  local timeout="${2:-120}"
  local elapsed=0
  while ! curl -sf --max-time 5 "$url" >/dev/null; do
    if (( elapsed >= timeout )); then
      echo "Timed out waiting for HTTP ${url}" >&2
      return 1
    fi
    sleep 2
    elapsed=$((elapsed + 2))
  done
}

stop_headscale_until_configured() {
  systemctl stop headscale 2>/dev/null || true
  systemctl disable headscale 2>/dev/null || true
}

start_headscale() {
  systemctl enable headscale
  systemctl restart headscale
  wait_for_headscale "${1:-90}"
}

require_root() {
  if [[ "${EUID}" -ne 0 ]]; then
    echo "Run as root (or with sudo)." >&2
    exit 1
  fi
}

detect_public_ip() {
  curl -sf --max-time 5 https://api.ipify.org \
    || curl -sf --max-time 5 https://ifconfig.me/ip \
    || true
}

derive_parent_zone() {
  local domain=$1
  echo "$domain" | rev | cut -d. -f1-2 | rev
}

# BASE_DOMAIN + optional SERVICE_HOST → DOMAIN (public HTTPS / Headscale URL).
resolve_host_domains() {
  if [[ -n "${BASE_DOMAIN:-}" ]]; then
    BASE_DOMAIN="${BASE_DOMAIN%.}"
    if [[ -n "${SERVICE_HOST:-}" ]]; then
      SERVICE_HOST="${SERVICE_HOST%.}"
      SERVICE_HOST="${SERVICE_HOST%.${BASE_DOMAIN}}"
      DOMAIN="${SERVICE_HOST}.${BASE_DOMAIN}"
    else
      DOMAIN="${BASE_DOMAIN}"
    fi
  elif [[ -n "${DOMAIN:-}" ]]; then
    warn "Set BASE_DOMAIN + SERVICE_HOST in host.env (DOMAIN-only is deprecated)"
    BASE_DOMAIN="$(derive_parent_zone "$DOMAIN")"
    if [[ "$DOMAIN" == "$BASE_DOMAIN" ]]; then
      SERVICE_HOST=""
    else
      SERVICE_HOST="${DOMAIN%%.${BASE_DOMAIN}}"
    fi
  else
    echo "Set BASE_DOMAIN (DNS zone apex) and SERVICE_HOST (subdomain label) in host.env" >&2
    exit 1
  fi

  if [[ ! "$BASE_DOMAIN" == *.* ]]; then
    echo "BASE_DOMAIN must be the DNS zone apex (e.g. harlock.network)" >&2
    exit 1
  fi
  if [[ -n "${SERVICE_HOST:-}" && "$SERVICE_HOST" == *.* ]]; then
    echo "SERVICE_HOST must be a single label (e.g. deeporc), not a FQDN" >&2
    exit 1
  fi
}

# Caddy site block: service FQDN + wildcard on the zone apex.
derive_tls_sites() {
  echo "${DOMAIN}, *.${BASE_DOMAIN}"
}

# Certbot DNS-01: zone apex + wildcard only (never the service subdomain as cert name).
derive_certbot_domains() {
  echo "${BASE_DOMAIN} *.${BASE_DOMAIN}"
}

cert_le_lineage_dir() {
  echo "/etc/letsencrypt/live/${BASE_DOMAIN}"
}

origin_tls_installed() {
  [[ -f /etc/caddy/ssl/fullchain.pem && -f /etc/caddy/ssl/privkey.pem ]]
}

cert_le_lineage_present() {
  local dir
  dir="$(cert_le_lineage_dir)"
  [[ -f "${dir}/fullchain.pem" && -f "${dir}/privkey.pem" ]]
}

generate_secret() {
  python3 -c 'import secrets; print(secrets.token_urlsafe(32))'
}

generate_api_key() {
  python3 -c 'import secrets; print(secrets.token_urlsafe(24))'
}

load_host_env() {
  local env_file="$1"
  if [[ ! -f "$env_file" ]]; then
    echo "Missing host env: $env_file" >&2
    echo "Copy deploy/hosts/host.env.example to deploy/hosts/host.env and set BASE_DOMAIN." >&2
    exit 1
  fi
  # shellcheck disable=SC1090
  set -a
  source "$env_file"
  set +a

  # Validate environment variables for security
  if ! validate_environment_vars "$env_file"; then
    echo "Environment variable validation failed" >&2
    exit 1
  fi

  : "${APP_DIR:=/opt/deeporc}"
  resolve_host_domains

  if [[ -z "${HOST_PUBLIC_IP:-}" ]]; then
    HOST_PUBLIC_IP="$(detect_public_ip)"
    if [[ -z "$HOST_PUBLIC_IP" ]]; then
      echo "HOST_PUBLIC_IP not set and auto-detect failed" >&2
      exit 1
    fi
    log "Auto-detected HOST_PUBLIC_IP=${HOST_PUBLIC_IP}"
  fi

  : "${ORCH_HOST_IP:=10.10.0.1}"
  : "${HEADSCALE_BASE_DOMAIN:=ts.${BASE_DOMAIN}}"
  : "${HEADSCALE_URL:=https://${DOMAIN}}"
  : "${WG_PUBLIC_HOST:=${HOST_PUBLIC_IP}}"
  : "${PORT_POOL_START:=51001}"
  : "${PORT_POOL_END:=52000}"
  : "${HEADSCALE_VERSION:=0.29.1}"
  : "${CLOUDFLARE_DNS_PROXIED:=true}"
  if [[ -n "${CLOUDFLARE_API_TOKEN:-}" ]]; then
    : "${ORIGIN_TLS:=letsencrypt}"
  else
    : "${ORIGIN_TLS:=internal}"
  fi

  if [[ -z "${SECRET_KEY:-}" || "${SECRET_KEY}" == change-me* ]]; then
    if [[ -f "${APP_DIR}/.env" ]]; then
      # shellcheck disable=SC1091
      SECRET_KEY=$(grep -m1 '^SECRET_KEY=' "${APP_DIR}/.env" | cut -d= -f2- || true)
    fi
  fi
  if [[ -z "${SECRET_KEY:-}" || "${SECRET_KEY}" == change-me* ]]; then
    SECRET_KEY="$(generate_secret)"
    log "Generated SECRET_KEY"
  fi
  if [[ -z "${API_KEY:-}" || "${API_KEY}" == change-me* || "${API_KEY}" == dev-api-key ]]; then
    if [[ -f "${APP_DIR}/.env" ]]; then
      API_KEY=$(grep -m1 '^API_KEY=' "${APP_DIR}/.env" | cut -d= -f2- || true)
    fi
  fi
  if [[ -z "${API_KEY:-}" || "${API_KEY}" == change-me* || "${API_KEY}" == dev-api-key ]]; then
    API_KEY="$(generate_api_key)"
    log "Generated API_KEY=${API_KEY}"
  fi

  export APP_DIR BASE_DOMAIN SERVICE_HOST DOMAIN HOST_PUBLIC_IP ORCH_HOST_IP HEADSCALE_BASE_DOMAIN
  export HEADSCALE_URL WG_PUBLIC_HOST PORT_POOL_START PORT_POOL_END
  export SECRET_KEY API_KEY HEADSCALE_VERSION
  export CLOUDFLARE_API_TOKEN CLOUDFLARE_ZONE_ID CLOUDFLARE_ZONE_NAME
  export CLOUDFLARE_ACCOUNT_ID CLOUDFLARE_ACCESS_EMAIL CLOUDFLARE_ACCESS_SKIP CLOUDFLARE_SKIP_DNS CLOUDFLARE_DNS_PROXIED
  export ORIGIN_TLS GIT_REPO GIT_REF
}

ensure_python_venv() {
  local app_dir="$1"
  if [[ ! -d "$app_dir/.venv" ]]; then
    python3 -m venv "$app_dir/.venv"
  fi
  # shellcheck disable=SC1091
  source "$app_dir/.venv/bin/activate"
  pip install -q --upgrade pip
  pip install -q --no-cache-dir -e "$app_dir[postgres]"
}

install_orchestrator_unit() {
  local app_dir="$1"
  local unit_src="$app_dir/deploy/systemd/orchestrator.service"
  sed "s|@APP_DIR@|${app_dir}|g" "$unit_src" >/etc/systemd/system/orchestrator.service
  systemctl daemon-reload
  systemctl enable orchestrator.service
}

install_caddy_tls_material() {
  local cert_dir=$1
  local dest="/etc/caddy/ssl"
  mkdir -p "$dest"
  install -m 644 -o caddy -g caddy "$cert_dir/fullchain.pem" "$dest/fullchain.pem"
  install -m 640 -o caddy -g caddy "$cert_dir/privkey.pem" "$dest/privkey.pem"
}

render_caddyfile() {
  local app_dir="$1"
  local template="$app_dir/deploy/Caddyfile.template"
  local out="/etc/caddy/Caddyfile"
  local tls_sites site cert_dir caddy_ssl="/etc/caddy/ssl/fullchain.pem"
  tls_sites="$(derive_tls_sites)"
  cert_dir="$(cert_le_lineage_dir)"
  site="$(sed "s/@TLS_SITES@/${tls_sites}/g" "$template")"
  mkdir -p /etc/caddy
  if [[ -f "$caddy_ssl" ]]; then
    site="$(printf '%s\n' "$site" | sed "0,/ {/s| {| {\n    tls /etc/caddy/ssl/fullchain.pem /etc/caddy/ssl/privkey.pem|")"
  elif [[ -f "${cert_dir}/fullchain.pem" ]]; then
    install_caddy_tls_material "$cert_dir"
    site="$(printf '%s\n' "$site" | sed "0,/ {/s| {| {\n    tls /etc/caddy/ssl/fullchain.pem /etc/caddy/ssl/privkey.pem|")"
  elif [[ "${ORIGIN_TLS:-internal}" == "letsencrypt" ]]; then
    site="$(printf '%s\n' "$site" | sed "0,/ {/s/ {/ {\n    tls internal/")"
  else
    site="$(printf '%s\n' "$site" | sed "0,/ {/s/ {/ {\n    tls internal/")"
  fi
  printf '%s\n' "$site" >"$out"
  systemctl enable caddy 2>/dev/null || true
  systemctl restart caddy 2>/dev/null || true
}

render_headscale_config() {
  local app_dir="$1"
  local template="$app_dir/deploy/headscale-config.yaml.template"
  local out="/etc/headscale/config.yaml"
  mkdir -p /etc/headscale /var/lib/headscale
  sed \
    -e "s|@DOMAIN@|${DOMAIN}|g" \
    -e "s|@HEADSCALE_BASE_DOMAIN@|${HEADSCALE_BASE_DOMAIN}|g" \
    -e "s|@ORCH_HOST_IP@|${ORCH_HOST_IP}|g" \
    "$template" >"$out"
  chmod 640 "$out"
  chown headscale:headscale "$out" 2>/dev/null || true
}

install_headscale_package() {
  local ver="${HEADSCALE_VERSION}"
  local deb="/tmp/headscale_${ver}_linux_amd64.deb"
  local need_install=1
  if command -v headscale >/dev/null 2>&1; then
    if headscale version 2>/dev/null | grep -q "v${ver}"; then
      need_install=0
    else
      log "Upgrading Headscale to v${ver}"
    fi
  else
    log "Installing Headscale v${ver}"
  fi
  if [[ "$need_install" == "1" ]]; then
    wait_for_apt
    curl -fsSL -o "$deb" \
      "https://github.com/juanfont/headscale/releases/download/v${ver}/headscale_${ver}_linux_amd64.deb"
    DEBIAN_FRONTEND=noninteractive dpkg --force-confold -i "$deb" \
      || DEBIAN_FRONTEND=noninteractive apt-get install -f -y -qq
  fi
  stop_headscale_until_configured
}

write_app_env() {
  local app_dir="$1"
  local example="$app_dir/deploy/orchestrator.env.example"
  local out="$app_dir/.env"
  sed \
    -e "s|@HOST_PUBLIC_IP@|${HOST_PUBLIC_IP}|g" \
    -e "s|@ORCH_HOST_IP@|${ORCH_HOST_IP}|g" \
    -e "s|@DOMAIN@|${DOMAIN}|g" \
    -e "s|@HEADSCALE_URL@|${HEADSCALE_URL}|g" \
    -e "s|@HEADSCALE_BASE_DOMAIN@|${HEADSCALE_BASE_DOMAIN}|g" \
    -e "s|@SECRET_KEY@|${SECRET_KEY}|g" \
    -e "s|@API_KEY@|${API_KEY}|g" \
    -e "s|@WG_PUBLIC_HOST@|${WG_PUBLIC_HOST}|g" \
    -e "s|@PORT_POOL_START@|${PORT_POOL_START}|g" \
    -e "s|@PORT_POOL_END@|${PORT_POOL_END}|g" \
    "$example" >"$out"
  chmod 600 "$out"
}

save_host_env() {
  local env_file="$1"
  local tmp
  tmp="$(mktemp)"
  {
    echo "# Written by bootstrap — $(date -Iseconds)"
    echo "APP_DIR=${APP_DIR}"
    echo "BASE_DOMAIN=${BASE_DOMAIN}"
    [[ -n "${SERVICE_HOST:-}" ]] && echo "SERVICE_HOST=${SERVICE_HOST}"
    echo "DOMAIN=${DOMAIN}"
    echo "HOST_PUBLIC_IP=${HOST_PUBLIC_IP}"
    echo "ORCH_HOST_IP=${ORCH_HOST_IP}"
    echo "HEADSCALE_BASE_DOMAIN=${HEADSCALE_BASE_DOMAIN}"
    echo "HEADSCALE_URL=${HEADSCALE_URL}"
    echo "WG_PUBLIC_HOST=${WG_PUBLIC_HOST}"
    echo "SECRET_KEY=${SECRET_KEY}"
    echo "API_KEY=${API_KEY}"
    echo "PORT_POOL_START=${PORT_POOL_START}"
    echo "PORT_POOL_END=${PORT_POOL_END}"
    echo "HEADSCALE_VERSION=${HEADSCALE_VERSION}"
    [[ -n "${GIT_REPO:-}" ]] && echo "GIT_REPO=${GIT_REPO}"
    [[ -n "${GIT_REF:-}" ]] && echo "GIT_REF=${GIT_REF}"
    [[ -n "${CLOUDFLARE_API_TOKEN:-}" ]] && echo "CLOUDFLARE_API_TOKEN=${CLOUDFLARE_API_TOKEN}"
    [[ -n "${CLOUDFLARE_ZONE_ID:-}" ]] && echo "CLOUDFLARE_ZONE_ID=${CLOUDFLARE_ZONE_ID}"
    [[ -n "${CLOUDFLARE_ACCESS_EMAIL:-}" ]] && echo "CLOUDFLARE_ACCESS_EMAIL=${CLOUDFLARE_ACCESS_EMAIL}"
    [[ -n "${CLOUDFLARE_ACCESS_SKIP:-}" ]] && echo "CLOUDFLARE_ACCESS_SKIP=${CLOUDFLARE_ACCESS_SKIP}"
    [[ -n "${CLOUDFLARE_DNS_PROXIED:-}" ]] && echo "CLOUDFLARE_DNS_PROXIED=${CLOUDFLARE_DNS_PROXIED}"
    [[ -n "${ORIGIN_TLS:-}" ]] && echo "ORIGIN_TLS=${ORIGIN_TLS}"
  } >"$tmp"
  install -m 600 "$tmp" "$env_file"
  rm -f "$tmp"
}

load_worker_env() {
  local env_file="$1"
  if [[ ! -f "$env_file" ]]; then
    echo "Missing worker env: $env_file" >&2
    echo "Copy deploy/hosts/worker.env.example to deploy/hosts/worker1.env" >&2
    exit 1
  fi
  # shellcheck disable=SC1090
  set -a
  source "$env_file"
  set +a

  # Validate environment variables for security
  if ! validate_worker_env_vars "$env_file"; then
    echo "Environment variable validation failed" >&2
    exit 1
  fi

  : "${WORKER_NAME:?Set WORKER_NAME in worker env}"
  : "${APP_DIR:=/opt/deeporc-worker}"
  : "${GIT_REPO:=}"
  : "${GIT_REF:=main}"
  : "${ORCH_HOST_IP:=10.10.0.1}"
  : "${PORT_POOL_START:=51001}"
  : "${PORT_POOL_END:=52000}"
  : "${IP_POOL_NETWORK:=10.10.0.0/16}"
  : "${IP_POOL_START:=10.10.1.10}"
  : "${TAILSCALE_HOSTNAME:=${WORKER_NAME}}"
  : "${HEADSCALE_WORKER_TAG:=tag:worker-host}"

  if [[ -z "${HOST_PUBLIC_IP:-}" ]]; then
    HOST_PUBLIC_IP="$(detect_public_ip)"
    [[ -n "$HOST_PUBLIC_IP" ]] || { echo "HOST_PUBLIC_IP not set" >&2; exit 1; }
    log "Auto-detected HOST_PUBLIC_IP=${HOST_PUBLIC_IP}"
  fi

  if [[ -z "${CP_DOMAIN:-}" && -n "${BASE_DOMAIN:-}" && -n "${SERVICE_HOST:-}" ]]; then
    CP_DOMAIN="${SERVICE_HOST}.${BASE_DOMAIN}"
  fi
  : "${CP_DOMAIN:?Set CP_DOMAIN (e.g. deeporc.harlock.network)}"
  : "${HEADSCALE_URL:=https://${CP_DOMAIN}}"
  : "${CP_API_URL:=https://${CP_DOMAIN}/orchestrator/api/v1}"

  export WORKER_NAME WORKER_DISPLAY_NAME HOST_PUBLIC_IP APP_DIR ORCH_HOST_IP
  export PORT_POOL_START PORT_POOL_END IP_POOL_NETWORK IP_POOL_START
  export TAILSCALE_HOSTNAME HEADSCALE_URL HEADSCALE_WORKER_TAG CP_DOMAIN CP_API_URL
  export WORKER_ID WORKER_TOKEN CP_API_KEY GIT_REPO GIT_REF
}

packages_url_from_domain() {
  local domain="${1#https://}"
  domain="${domain#http://}"
  domain="${domain%%/*}"
  echo "https://${domain}/packages"
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

  log "Extracting archive…"
  if command -v pv >/dev/null 2>&1; then
    pv "$archive" | tar -xzf - -C "$dest"
  else
    tar -xzf "$archive" -C "$dest"
  fi
  log "Extracting archive — done"
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

install_worker_bundle() {
  local app_dir=$1
  local packages_url=$2
  local version tarball tmp parent

  version="$(curl -fsSL "${packages_url}/worker-bundle.version" 2>/dev/null || date -Iseconds)"
  version="${version//$'\n'/}"
  version="${version// /%20}"
  tarball="${packages_url}/worker-bundle.tar.gz?v=${version}"
  tmp="$(mktemp)"
  if ! download_with_progress "$tarball" "$tmp" "Downloading worker bundle"; then
    rm -f "$tmp"
    echo "Failed to download ${tarball} from control plane" >&2
    echo "Ensure the CP published packages: sudo ${app_dir}/deploy/build-worker-bundle.sh" >&2
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

save_worker_env() {
  local env_file="$1"
  local tmp
  tmp="$(mktemp)"
  {
    echo "# Written by worker bootstrap — $(date -Iseconds)"
    printf 'WORKER_NAME=%q\n' "$WORKER_NAME"
    [[ -n "${WORKER_DISPLAY_NAME:-}" ]] && printf 'WORKER_DISPLAY_NAME=%q\n' "$WORKER_DISPLAY_NAME"
    printf 'HOST_PUBLIC_IP=%q\n' "$HOST_PUBLIC_IP"
    printf 'TAILSCALE_HOSTNAME=%q\n' "$TAILSCALE_HOSTNAME"
    printf 'CP_DOMAIN=%q\n' "${CP_DOMAIN:-}"
    printf 'HEADSCALE_URL=%q\n' "${HEADSCALE_URL:-}"
    printf 'CP_API_URL=%q\n' "${CP_API_URL:-}"
    printf 'APP_DIR=%q\n' "$APP_DIR"
    printf 'ORCH_HOST_IP=%q\n' "$ORCH_HOST_IP"
    printf 'PORT_POOL_START=%q\n' "$PORT_POOL_START"
    printf 'PORT_POOL_END=%q\n' "$PORT_POOL_END"
    printf 'IP_POOL_NETWORK=%q\n' "$IP_POOL_NETWORK"
    printf 'IP_POOL_START=%q\n' "$IP_POOL_START"
    if [[ -n "${WORKER_ID:-}" ]]; then printf 'WORKER_ID=%q\n' "$WORKER_ID"; fi
    if [[ -n "${WORKER_TOKEN:-}" ]]; then printf 'WORKER_TOKEN=%q\n' "$WORKER_TOKEN"; fi
  } >"$tmp"
  install -m 600 "$tmp" "$env_file"
  rm -f "$tmp"
}
