#!/usr/bin/env bash
# Install Headscale ACL policy (tag:exit auto-approvers).
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib/common.sh
source "$SCRIPT_DIR/lib/common.sh"

POLICY_SRC="${SCRIPT_DIR}/headscale-policy.hujson"
POLICY_DST="/etc/headscale/policy.hujson"
CONFIG="/etc/headscale/config.yaml"
FILES_ONLY="${HEADSCALE_POLICY_FILES_ONLY:-0}"

cp "$POLICY_SRC" "$POLICY_DST"
chmod 644 "$POLICY_DST"
chown headscale:headscale "$POLICY_DST" 2>/dev/null || true

python3 - <<'PY'
from pathlib import Path
import re

config = Path("/etc/headscale/config.yaml")
text = config.read_text()
if "path: /etc/headscale/policy.hujson" not in text:
    text = re.sub(
        r"^policy:\n  mode: file\n  path:.*\n",
        "policy:\n  mode: file\n  path: /etc/headscale/policy.hujson\n",
        text,
        flags=re.M,
    )
    if "path: /etc/headscale/policy.hujson" not in text:
        text = text.rstrip() + "\npolicy:\n  mode: file\n  path: /etc/headscale/policy.hujson\n"
    config.write_text(text)
PY

if [[ "$FILES_ONLY" == "1" ]]; then
  log "Headscale policy files installed (no service restart)"
  exit 0
fi

start_headscale 90
headscale policy check -f "$POLICY_DST"
headscale policy get
log "Headscale policy active at ${POLICY_DST}"
