#!/usr/bin/env bash
# Install or refresh orchestrator application (venv, migrations, systemd, packages).
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib/common.sh
source "$SCRIPT_DIR/lib/common.sh"

ENV_FILE="${1:-${HOST_ENV:-$SCRIPT_DIR/hosts/host.env}}"
load_host_env "$ENV_FILE"

log "Installing orchestrator in ${APP_DIR}"
mkdir -p "$APP_DIR/data" /var/www/deeporc-packages

if [[ "${FRESH_INSTALL:-0}" == "1" ]] && [[ -f "$APP_DIR/data/orchestrator.db" ]]; then
  log "FRESH_INSTALL: removing existing orchestrator.db"
  rm -f "$APP_DIR/data/orchestrator.db" "$APP_DIR/data/orchestrator.db-"*
fi

ensure_python_venv "$APP_DIR"
write_app_env "$APP_DIR"

cd "$APP_DIR"
# shellcheck disable=SC1091
source "$APP_DIR/.venv/bin/activate"
set -a
# shellcheck disable=SC1091
source "$APP_DIR/.env"
set +a
alembic upgrade head

"$SCRIPT_DIR/build-worker-bundle.sh"

install_orchestrator_unit "$APP_DIR"
retry 5 3 systemctl restart orchestrator.service
wait_for_http "http://127.0.0.1:8000/orchestrator/health" 120

log "Orchestrator ready: systemctl status orchestrator"
