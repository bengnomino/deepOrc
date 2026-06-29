#!/usr/bin/env bash
# Build worker deploy bundle for /packages (no git on worker VPS).
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
# shellcheck source=lib/common.sh
source "$SCRIPT_DIR/lib/common.sh"

DEST="${1:-/var/www/deeporc-packages}"
STAGE="$(mktemp -d)"
trap 'rm -rf "$STAGE"' EXIT

ROOT="$STAGE/deeporc-worker"
mkdir -p "$ROOT/orchestrator/services"

rsync -a \
  --exclude 'hosts/host.env' \
  --exclude 'hosts/worker1.env' \
  --exclude 'hosts/*.env' \
  "$SCRIPT_DIR/" "$ROOT/deploy/"

install -m 644 "$REPO_ROOT/orchestrator/__init__.py" "$ROOT/orchestrator/"
install -m 644 "$REPO_ROOT/orchestrator/services/__init__.py" "$ROOT/orchestrator/services/"
install -m 644 "$REPO_ROOT/orchestrator/services/host_stats.py" "$ROOT/orchestrator/services/"

VERSION="$(git -C "$REPO_ROOT" rev-parse --short HEAD 2>/dev/null || date -Iseconds)"
echo "$VERSION" >"$ROOT/VERSION"

mkdir -p "$DEST"
tar -C "$STAGE" -czf "$DEST/worker-bundle.tar.gz" deeporc-worker
echo "$VERSION" >"$DEST/worker-bundle.version"
chmod 644 "$DEST/worker-bundle.tar.gz" "$DEST/worker-bundle.version"
log "Published ${DEST}/worker-bundle.tar.gz (${VERSION})"
