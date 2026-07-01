#!/usr/bin/env bash
# Push the published worker bundle to all worker VPS hosts (run on control plane).
# Usage: sudo ./deploy/push-worker-bundle.sh [path/to/workers.list]
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib/common.sh
source "$SCRIPT_DIR/lib/common.sh"

require_root

CP_APP_DIR="${APP_DIR:-/opt/deeporc}"
DEFAULT_WORKER_APP_DIR="${WORKER_APP_DIR:-/opt/deeporc-worker}"

WORKERS_FILE="${1:-$SCRIPT_DIR/hosts/workers.list}"
if [[ ! -f "$WORKERS_FILE" ]]; then
  log "No ${WORKERS_FILE} — skip worker bundle push (see workers.list.example)"
  exit 0
fi

SSH_OPTS=(-o StrictHostKeyChecking=accept-new -o ConnectTimeout=15)
if [[ -n "${WORKER_SSH_IDENTITY:-}" ]]; then
  SSH_OPTS+=(-i "$WORKER_SSH_IDENTITY")
fi

updated=0
failed=0
while IFS= read -r line || [[ -n "$line" ]]; do
  line="${line%%#*}"
  # Parse line for APP_DIR (format: root@host APP_DIR=path) before space removal.
  worker_app_dir="$DEFAULT_WORKER_APP_DIR"
  if [[ "$line" == *" APP_DIR="* ]]; then
    worker_app_dir="${line##* APP_DIR=}"
    line="${line%% APP_DIR=*}"
  fi
  # Remove remaining spaces
  line="${line// /}"
  [[ -z "$line" ]] && continue

  log "Updating worker at ${line}"
  printf -v remote_app_dir '%q' "$worker_app_dir"
  if ssh -n "${SSH_OPTS[@]}" "$line" "APP_DIR=${remote_app_dir}; test -x \"\$APP_DIR/deploy/update-worker.sh\" && \"\$APP_DIR/deploy/update-worker.sh\""; then
    if [[ -f "${CP_APP_DIR}/orchestrator/services/host_stats.py" ]]; then
      scp -q "${SSH_OPTS[@]}" \
        "${CP_APP_DIR}/orchestrator/services/host_stats.py" \
        "${line}:${worker_app_dir}/orchestrator/services/host_stats.py" 2>/dev/null || true
      ssh -n "${SSH_OPTS[@]}" "$line" "systemctl restart worker-heartbeat.service" 2>/dev/null || true
    fi
    updated=$((updated + 1))
  else
    warn "Worker update failed for ${line}"
    failed=$((failed + 1))
  fi
done <"$WORKERS_FILE"

log "Worker bundle push done (${updated} ok, ${failed} failed)"
[[ "$failed" -eq 0 ]]
