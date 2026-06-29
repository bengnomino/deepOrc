#!/usr/bin/env bash
# Pull latest code and restart services.
# Usage: sudo ./deploy/update.sh [git-ref] [path/to/host.env]
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib/common.sh
source "$SCRIPT_DIR/lib/common.sh"

require_root

GIT_REF="${1:-main}"
ENV_FILE="${2:-${HOST_ENV:-$SCRIPT_DIR/hosts/host.env}}"
load_host_env "$ENV_FILE"

log "Updating ${APP_DIR} @ ${GIT_REF}"

cd "$APP_DIR"
if [[ -d .git ]]; then
  git fetch origin
  git checkout "$GIT_REF"
  git pull --ff-only origin "$GIT_REF" || true
else
  log "No git repo in ${APP_DIR} — sync files manually before update"
fi

HOST_ENV="$ENV_FILE" "$SCRIPT_DIR/install-app.sh" "$ENV_FILE"
render_caddyfile "$APP_DIR"
"$SCRIPT_DIR/build-worker-bundle.sh"

if [[ -f "$SCRIPT_DIR/hosts/workers.list" ]]; then
  "$SCRIPT_DIR/push-worker-bundle.sh"
fi

if [[ "${REBUILD_GOLDEN:-0}" == "1" ]]; then
  log "Rebuilding golden image"
  "$SCRIPT_DIR/build-gateway-golden-image.sh"
fi

log "Update complete"
systemctl is-active orchestrator caddy headscale || true
