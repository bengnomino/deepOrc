#!/usr/bin/env bash
# nftables rules for gateway worker VPS.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib/common.sh
source "$SCRIPT_DIR/lib/common.sh"
# shellcheck source=lib/nftables.sh
source "$SCRIPT_DIR/lib/nftables.sh"

require_root

ENV_FILE="${1:-${WORKER_ENV:-$SCRIPT_DIR/hosts/worker1.env}}"
load_worker_env "$ENV_FILE"

TMP=$(mktemp)
trap 'rm -f "$TMP"' EXIT

ensure_nftables
render_nft_template "$SCRIPT_DIR/nftables/worker.nft" "$TMP"
apply_nftables_rules "$TMP"
show_nftables_rules
