#!/usr/bin/env bash
set -euo pipefail

APP_DIR="${1:-/opt/deeporc}"
chmod 755 "$APP_DIR/deploy/deeporc-worker-net-up.sh"
UNIT_SRC="$APP_DIR/deploy/systemd/deeporc-worker-net.service"
UNIT_DST="/etc/systemd/system/deeporc-worker-net.service"

sed "s|@APP_DIR@|${APP_DIR}|g" "$UNIT_SRC" >"$UNIT_DST"
systemctl daemon-reload
systemctl enable deeporc-worker-net.service
