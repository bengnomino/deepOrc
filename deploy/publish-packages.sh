#!/usr/bin/env bash
# Publish gateway-agent binary for golden image / manual copy.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib/common.sh
source "$SCRIPT_DIR/lib/common.sh"

SRC="${1:-dist}"
DEST="/var/www/deeporc-packages"
mkdir -p "$DEST"
if [[ -f "$SRC/gateway-agent" ]]; then
  install -m 0644 "$SRC/gateway-agent" "$DEST/gateway-agent"
  log "Published $DEST/gateway-agent"
else
  log "No $SRC/gateway-agent — skip publish"
fi
