#!/bin/sh
# Install only tailscale + tailscaled static binaries (no apt/apk tailscale package).
set -eu

VERSION="${TAILSCALE_VERSION:-1.80.3}"
ARCH="${TAILSCALE_ARCH:-amd64}"
URL="https://pkgs.tailscale.com/stable/tailscale_${VERSION}_${ARCH}.tgz"
TMP="${TMPDIR:-/tmp}/tailscale-static"

rm -rf "$TMP"
mkdir -p "$TMP"
curl -fsSL "$URL" | tar xz -C "$TMP"

install -d /usr/local/sbin
install -m 755 "$TMP/tailscale_${VERSION}_${ARCH}/tailscale" /usr/local/sbin/tailscale
install -m 755 "$TMP/tailscale_${VERSION}_${ARCH}/tailscaled" /usr/local/sbin/tailscaled
ln -sf /usr/local/sbin/tailscale /usr/local/bin/tailscale 2>/dev/null || true

if command -v strip >/dev/null 2>&1; then
  strip /usr/local/sbin/tailscale /usr/local/sbin/tailscaled 2>/dev/null || true
fi

rm -rf "$TMP"
