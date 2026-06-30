#!/usr/bin/env bash
# Run deepOrc exit-host cleanup from the repo checkout.
# Usage on EXIT VM (after copying script):
#   bash exit-host-cleanup.sh
#   bash exit-host-cleanup.sh --dry-run
#
# Copy to exit VM:
#   scp deploy/exit-host-cleanup.sh root@EXIT:/root/
#   ssh root@EXIT 'bash /root/exit-host-cleanup.sh --dry-run'
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
exec bash "$REPO_ROOT/orchestrator/host_setup/exit_host_cleanup.sh" "$@"
