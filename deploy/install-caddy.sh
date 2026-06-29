#!/usr/bin/env bash
# Install Caddy from distro packages only.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib/common.sh
source "$SCRIPT_DIR/lib/common.sh"

require_root

if ! command -v caddy >/dev/null 2>&1; then
  apt_install install -y -qq caddy
fi
systemctl enable caddy 2>/dev/null || true
caddy version
