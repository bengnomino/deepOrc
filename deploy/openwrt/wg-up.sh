#!/bin/sh
# Bring up wg0 from /etc/wireguard/wg0.conf (OpenWrt wg expects key file paths).
set -eu
CONF=/etc/wireguard/wg0.conf
[ -f "$CONF" ] || exit 1

port=$(grep -m1 '^ListenPort' "$CONF" | cut -d= -f2 | tr -d ' ')
addr=$(grep -m1 '^Address' "$CONF" | cut -d= -f2 | tr -d ' ')
keyfile=$(mktemp)
umask 077
sed -n 's/^PrivateKey = //p' "$CONF" | head -1 | tr -d '\r\n' >"$keyfile"

ip link del dev wg0 2>/dev/null || true
ip link add dev wg0 type wireguard
wg set wg0 private-key "$keyfile" listen-port "$port"
rm -f "$keyfile"
ip -4 addr add "$addr" dev wg0
ip link set wg0 up
ip link set wg0 mtu 1280
