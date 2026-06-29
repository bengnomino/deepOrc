#!/usr/bin/env bash
# Build and publish a minimal OpenWrt container golden image (~50MB rootfs, Glinet-style).
set -euo pipefail

BUILD_NAME="${BUILD_NAME:-gw-golden-build}"
IMAGE_ALIAS="${IMAGE_ALIAS:-gw-golden}"
BASE_IMAGE="${BASE_IMAGE:-local:openwrt-base}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
AGENT_BIN="${GATEWAY_AGENT_BIN:-$ROOT/dist/gateway-agent}"
BUNDLED_WG="${SCRIPT_DIR}/openwrt/bin/wg"

incus_exec() { timeout 180 incus exec "$BUILD_NAME" -- "$@"; }
incus_push() { incus file push "$1" "$BUILD_NAME$2"; }

if [ ! -x "$AGENT_BIN" ]; then
  echo "Missing $AGENT_BIN — run deploy/build-gateway-agent-go.sh first" >&2
  exit 1
fi

_launch_instance() {
  local name=$1
  local image=$2
  local alias="${image#local:}"
  if [[ "$image" != local:* ]]; then
    echo "BASE_IMAGE must be a local alias (e.g. local:openwrt-base). Run deploy/import-bundled-images.sh" >&2
    exit 1
  fi
  if ! incus image info "local:${alias}" >/dev/null 2>&1; then
    echo "Missing Incus image local:${alias} — run deploy/import-bundled-images.sh" >&2
    exit 1
  fi
  local payload
  payload=$(python3 -c 'import json,sys; print(json.dumps({"name":sys.argv[1],"type":"container","source":{"type":"image","alias":sys.argv[2]},"profiles":["default"],"config":{"limits.memory":"512MiB","limits.cpu":"2","security.privileged":"true"}}))' "$name" "$alias")
  incus query -X POST -d "$payload" --wait /1.0/instances >/dev/null
  incus start "$name"
}

_install_wg() {
  if incus_exec sh -c 'command -v wg >/dev/null 2>&1'; then
    return 0
  fi
  if [[ -x "$BUNDLED_WG" ]]; then
    echo "==> Installing bundled wg binary"
    incus_exec mkdir -p /usr/bin
    incus_push "$BUNDLED_WG" /usr/bin/wg
    incus_exec chmod 755 /usr/bin/wg
    return 0
  fi
  echo "wireguard-tools/wg not installed and no bundled binary at $BUNDLED_WG" >&2
  return 1
}

echo "==> Removing previous build instance/image (if any)"
incus delete -f "$BUILD_NAME" 2>/dev/null || true
if incus image info "$IMAGE_ALIAS" >/dev/null 2>&1; then
  incus image delete "$IMAGE_ALIAS"
fi

echo "==> Launching builder from $BASE_IMAGE"
_launch_instance "$BUILD_NAME" "$BASE_IMAGE"

echo "==> Installing OpenWrt packages (tailscale, wireguard, curl)"
incus_exec sh -c '
  set -eu
  for i in 1 2 3 4 5; do
    opkg update && break
    sleep 3
  done
  for pkg in "zlib libopenssl3 ca-bundle curl" "ca-bundle curl" "curl"; do
    if opkg install $pkg; then
      break
    fi
  done
  opkg install tailscale kmod-wireguard 2>/dev/null || opkg install tailscale
  opkg install wireguard-tools 2>/dev/null || true
  command -v curl
  wget -qO /dev/null http://127.0.0.1/ 2>/dev/null || command -v wget
'
_install_wg

echo "==> Installing gateway-agent and init scripts"
incus_exec mkdir -p /opt/gateway-agent /etc/wireguard /etc/nftables.d
incus_push "$AGENT_BIN" /opt/gateway-agent/gateway-agent
incus_push "$SCRIPT_DIR/openwrt/wg-up.sh" /opt/gateway-agent/wg-up.sh
incus_push "$SCRIPT_DIR/openwrt/gateway-agent.init" /etc/init.d/gateway-agent
incus_push "$SCRIPT_DIR/openwrt/gateway-wg.init" /etc/init.d/gateway-wg
incus_push "$SCRIPT_DIR/openwrt/tailscale-up.init" /etc/init.d/tailscale-up
incus_exec chmod 755 /opt/gateway-agent/gateway-agent /opt/gateway-agent/wg-up.sh
incus_exec chmod 755 /etc/init.d/gateway-agent /etc/init.d/gateway-wg /etc/init.d/tailscale-up

echo "==> Verifying baked stack"
incus_exec test -x /opt/gateway-agent/gateway-agent
incus_exec test -x /usr/sbin/tailscaled
incus_exec test -x /usr/bin/wg
incus_exec sh -c 'command -v curl'
incus_exec /opt/gateway-agent/gateway-agent --help 2>/dev/null || incus_exec test -s /opt/gateway-agent/gateway-agent
incus_exec sh -c 'ls -lh /opt/gateway-agent/gateway-agent /usr/bin/wg /usr/sbin/tailscaled; du -sh / 2>/dev/null | tail -1'

echo "==> Minimizing footprint"
incus_exec sh -c '
  set -eu
  /etc/init.d/gateway-agent stop 2>/dev/null || true
  /etc/init.d/tailscale stop 2>/dev/null || true
  opkg remove --force-depends wget uhttpd-mod-ubus 2>/dev/null || true
  rm -rf /tmp/* /var/opkg-lists/*
'

echo "==> Publishing image as local:$IMAGE_ALIAS"
incus stop "$BUILD_NAME" --force
incus publish "$BUILD_NAME" --alias "$IMAGE_ALIAS" \
  description="Minimal OpenWrt gateway (bundled base, static Go agent)"
incus delete "$BUILD_NAME"

echo "==> Done. Golden image: local:${IMAGE_ALIAS}"
echo "    Publish to repo: sudo ./deploy/export-gateway-golden.sh"
echo "    Rebuild requires: IMPORT_OPENWRT_BASE=1 ./deploy/import-bundled-images.sh"
incus image list | grep -E "ALIAS|$IMAGE_ALIAS"
