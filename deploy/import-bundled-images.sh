#!/usr/bin/env bash
# Import vendored Incus images from deploy/assets/incus/ (no remote pulls).
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib/common.sh
source "$SCRIPT_DIR/lib/common.sh"

ASSETS="${SCRIPT_DIR}/assets/incus"
GOLDEN_ALIAS="${GOLDEN_IMAGE_ALIAS:-gw-golden}"
OPENWRT_ALIAS="${OPENWRT_BASE_ALIAS:-openwrt-base}"

_import_with_alias() {
  local alias=$1
  shift
  if incus image info "local:${alias}" >/dev/null 2>&1; then
    log "Incus image local:${alias} already present"
    return 0
  fi
  log "Importing bundled image → local:${alias}"
  set +e
  import_out=$(incus image import "$@" --alias "$alias" 2>&1)
  import_rc=$?
  set -e
  if [[ "$import_rc" -eq 0 ]]; then
    incus image info "local:${alias}" | head -5 || true
    return 0
  fi
  if echo "$import_out" | grep -qiE 'fingerprint already exists|Image with same fingerprint'; then
    log "Image fingerprint already in store — ensuring alias local:${alias}"
    local fp
    fp=$(incus image list local: -f csv -c F | tail -1)
    if [[ -n "$fp" ]]; then
      incus image alias create "$fp" "$alias" 2>/dev/null || true
    fi
    return 0
  fi
  echo "$import_out" >&2
  exit 1
}

import_golden_image() {
  if [[ -f "${ASSETS}/gw-golden.tar.gz" ]]; then
    _import_with_alias "$GOLDEN_ALIAS" "${ASSETS}/gw-golden.tar.gz"
    return
  fi
  if [[ -f "${ASSETS}/gw-golden.meta" && -f "${ASSETS}/gw-golden.root" ]]; then
    _import_with_alias "$GOLDEN_ALIAS" "${ASSETS}/gw-golden.meta" "${ASSETS}/gw-golden.root"
    return
  fi
  echo "Missing bundled golden image under ${ASSETS}/" >&2
  echo "Expected gw-golden.tar.gz (Incus 6+) or gw-golden.meta + gw-golden.root" >&2
  exit 1
}

import_openwrt_base() {
  # Reference only — used when rebuilding gw-golden (see deploy/build-gateway-golden-image.sh).
  if [[ "${IMPORT_OPENWRT_BASE:-0}" != "1" ]]; then
    return 0
  fi
  if [[ -f "${ASSETS}/openwrt-24.10-default.tar.gz" ]]; then
    _import_with_alias "$OPENWRT_ALIAS" "${ASSETS}/openwrt-24.10-default.tar.gz"
    return
  fi
  if [[ -f "${ASSETS}/openwrt-24.10-default.meta" && -f "${ASSETS}/openwrt-24.10-default.root" ]]; then
    _import_with_alias "$OPENWRT_ALIAS" \
      "${ASSETS}/openwrt-24.10-default.meta" \
      "${ASSETS}/openwrt-24.10-default.root"
    return
  fi
  echo "Missing OpenWrt reference image under ${ASSETS}/" >&2
  exit 1
}

require_root
import_golden_image
import_openwrt_base
