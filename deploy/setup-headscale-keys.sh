#!/usr/bin/env bash
# Generate Headscale server keys (v0.28+ CLI writes to stdout, not --output file).
set -euo pipefail

ensure_headscale_keys() {
  mkdir -p /etc/headscale /var/lib/headscale
  if [[ ! -f /etc/headscale/private.key ]]; then
    headscale generate private-key -o json | python3 -c \
      'import json,sys; print(json.load(sys.stdin)["private_key"])' \
      >/etc/headscale/private.key
    chown headscale:headscale /etc/headscale/private.key
    chmod 640 /etc/headscale/private.key
  fi
}

if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
  ensure_headscale_keys
fi
