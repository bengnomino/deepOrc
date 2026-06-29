#!/usr/bin/env bash
# Quick deploy orchestrator → control plane (no sudo: SSH as root).
# Usage from repo root:
#   ./deploy/quick-cp.sh
#   CP_HOST=root@1.2.3.4 SSH_KEY=~/.ssh/id_ed25519 ./deploy/quick-cp.sh
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

CP_HOST="${CP_HOST:-root@165.227.156.103}"
SSH_KEY="${SSH_KEY:-$HOME/.ssh/deasit}"
APP_DIR="${APP_DIR:-/opt/deeporc}"

SSH=(ssh -i "$SSH_KEY" -o StrictHostKeyChecking=accept-new)
RSYNC=(rsync -avz -e "ssh -i $SSH_KEY -o StrictHostKeyChecking=accept-new")

echo "==> Sync orchestrator → ${CP_HOST}:${APP_DIR}/orchestrator/"
"${RSYNC[@]}" "$REPO_ROOT/orchestrator/" "${CP_HOST}:${APP_DIR}/orchestrator/"

echo "==> Sync alembic migrations"
"${RSYNC[@]}" "$REPO_ROOT/alembic/versions/" "${CP_HOST}:${APP_DIR}/alembic/versions/"

echo "==> Migrate + restart"
"${SSH[@]}" "$CP_HOST" bash -s <<EOF
set -euo pipefail
cd ${APP_DIR}
source .venv/bin/activate
set -a
source .env
set +a
alembic upgrade head
systemctl restart orchestrator
sleep 2
systemctl is-active orchestrator
curl -sf http://127.0.0.1:8000/orchestrator/health
echo
EOF

echo "==> Done: https://deeporc.harlock.network/orchestrator/ui"
