#!/bin/sh
# Run on the machine that holds the backhaul WG .conf (PC/VPS uplink).
# WireGuard must already be up (wg-quick up ./gw-XXX-link.conf).
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
exec "$SCRIPT_DIR/uplink-deeporc-nat.sh"
