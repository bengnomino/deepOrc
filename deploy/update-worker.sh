#!/usr/bin/env bash
# Refresh worker deploy files from the control plane /packages mirror.
# Usage: sudo ./deploy/update-worker.sh
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib/common.sh
source "$SCRIPT_DIR/lib/common.sh"

require_root

ENV_FILE="${WORKER_ENV_FILE:-/etc/deeporc/worker.env}"
if [[ ! -f "$ENV_FILE" ]]; then
  echo "Missing ${ENV_FILE}" >&2
  exit 1
fi
# shellcheck disable=SC1090
set -a
source "$ENV_FILE"
set +a

: "${APP_DIR:=/opt/deeporc-worker}"
: "${CP_DOMAIN:?Set CP_DOMAIN in ${ENV_FILE}}"

PACKAGES_URL="${PACKAGES_URL:-$(packages_url_from_domain "$CP_DOMAIN")}"
VERSION_URL="${PACKAGES_URL}/worker-bundle.version"

install_worker_bundle "$APP_DIR" "$PACKAGES_URL"

if curl -fsSL "$VERSION_URL" -o /etc/deeporc/worker-bundle.version 2>/dev/null; then
  log "Worker bundle version: $(cat /etc/deeporc/worker-bundle.version)"
fi

if systemctl is-enabled worker-heartbeat.service >/dev/null 2>&1; then
  systemctl restart worker-heartbeat.service
fi

log "Worker update complete"
