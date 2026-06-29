#!/usr/bin/env bash
# Export local:gw-golden into deploy/assets/incus/ for vendoring in git.
# Prerequisites: incus image local:gw-golden (build with deploy/build-gateway-golden-image.sh).
# Usage: sudo ./deploy/export-gateway-golden.sh
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ASSETS="${SCRIPT_DIR}/assets/incus"
TMP="${TMPDIR:-/tmp}/deeporc-gw-golden-export"
ALIAS="${GOLDEN_EXPORT_ALIAS:-gw-golden}"
OUT="${ASSETS}/gw-golden.tar.gz"

mkdir -p "$ASSETS" "$TMP"

if ! incus image info "local:${ALIAS}" >/dev/null 2>&1; then
  echo "Missing Incus image local:${ALIAS} — run deploy/build-gateway-golden-image.sh first" >&2
  exit 1
fi

FP="$(incus image info "local:${ALIAS}" | awk '/^Fingerprint/ {print $2; exit}')"
[[ -n "$FP" ]] || { echo "Could not resolve fingerprint for local:${ALIAS}" >&2; exit 1; }

incus image export "$FP" "${TMP}/gw-golden"
if [[ -f "${TMP}/gw-golden.tar.gz" ]]; then
  install -m 644 "${TMP}/gw-golden.tar.gz" "$OUT"
elif [[ -f "${TMP}/gw-golden.meta" && -f "${TMP}/gw-golden.root" ]]; then
  install -m 644 "${TMP}/gw-golden.meta" "${ASSETS}/gw-golden.meta"
  install -m 644 "${TMP}/gw-golden.root" "${ASSETS}/gw-golden.root"
  rm -f "$OUT"
else
  echo "Unexpected export layout under ${TMP}/" >&2
  ls -la "$TMP" >&2
  exit 1
fi

(
  cd "$ASSETS"
  {
    [[ -f gw-golden.tar.gz ]] && sha256sum gw-golden.tar.gz
    [[ -f gw-golden.meta ]] && sha256sum gw-golden.meta gw-golden.root
    [[ -f openwrt-24.10-default.meta ]] && sha256sum openwrt-24.10-default.meta openwrt-24.10-default.root
  } >SHA256SUMS
)

ls -lh "${ASSETS}"/gw-golden*
echo "Commit deploy/assets/incus/gw-golden* and SHA256SUMS"
