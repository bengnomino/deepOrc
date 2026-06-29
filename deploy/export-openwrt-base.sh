#!/usr/bin/env bash
# Refresh vendored OpenWrt base image (reference for golden rebuild; requires Incus + network).
# Usage: sudo ./deploy/export-openwrt-base.sh
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ASSETS="${SCRIPT_DIR}/assets/incus"
TMP="${TMPDIR:-/tmp}/deeporc-openwrt-export"
REMOTE="${OPENWRT_REMOTE_IMAGE:-images:openwrt/24.10/default}"
ALIAS="${OPENWRT_EXPORT_ALIAS:-openwrt-export-tmp}"

mkdir -p "$ASSETS" "$TMP"

if ! incus image info "$REMOTE" >/dev/null 2>&1; then
  incus launch "$REMOTE" "$ALIAS" --ephemeral || true
  incus delete -f "$ALIAS" 2>/dev/null || true
fi

FP="$(incus image info "$REMOTE" | awk '/^Fingerprint/ {print $2; exit}')"
[[ -n "$FP" ]] || { echo "Could not resolve fingerprint for ${REMOTE}" >&2; exit 1; }

incus image export "$FP" "${TMP}/openwrt-24.10-default"
if [[ -f "${TMP}/openwrt-24.10-default.tar.gz" ]]; then
  install -m 644 "${TMP}/openwrt-24.10-default.tar.gz" "${ASSETS}/openwrt-24.10-default.tar.gz"
  rm -f "${ASSETS}/openwrt-24.10-default.meta" "${ASSETS}/openwrt-24.10-default.root"
elif [[ -f "${TMP}/openwrt-24.10-default.meta" ]]; then
  install -m 644 "${TMP}/openwrt-24.10-default.meta" "${ASSETS}/openwrt-24.10-default.meta"
  install -m 644 "${TMP}/openwrt-24.10-default.root" "${ASSETS}/openwrt-24.10-default.root"
else
  install -m 644 "${TMP}/openwrt-24.10-default" "${ASSETS}/openwrt-24.10-default.meta"
  install -m 644 "${TMP}/openwrt-24.10-default.root" "${ASSETS}/openwrt-24.10-default.root"
fi

(
  cd "$ASSETS"
  {
    [[ -f gw-golden.tar.gz ]] && sha256sum gw-golden.tar.gz
    [[ -f openwrt-24.10-default.tar.gz ]] && sha256sum openwrt-24.10-default.tar.gz
    [[ -f openwrt-24.10-default.meta ]] && sha256sum openwrt-24.10-default.meta openwrt-24.10-default.root
  } >SHA256SUMS
)

ls -lh "${ASSETS}"/openwrt-24.10-default*
echo "Commit deploy/assets/incus/ and SHA256SUMS"
