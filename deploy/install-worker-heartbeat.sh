#!/usr/bin/env bash
set -euo pipefail

APP_DIR="${1:-/opt/deeporc}"
UNIT_SRC="$APP_DIR/deploy/systemd/worker-heartbeat.service"
UNIT_DST="/etc/systemd/system/worker-heartbeat.service"

sed "s|@APP_DIR@|${APP_DIR}|g" "$UNIT_SRC" >"$UNIT_DST"
systemctl daemon-reload
systemctl enable worker-heartbeat.service
systemctl restart worker-heartbeat.service
