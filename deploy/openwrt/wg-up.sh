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
[ -f /opt/gateway-agent/exit.env ] && . /opt/gateway-agent/exit.env
ip link set wg0 mtu "${EXIT_MTU:-1420}"

peer_pub=$(sed -n '/^\[Peer\]/,$ s/^PublicKey = //p' "$CONF" | head -1 | tr -d ' \r\n')
allowed=$(sed -n '/^\[Peer\]/,$ s/^AllowedIPs = //p' "$CONF" | head -1 | tr -d ' \r\n')
[ -n "$peer_pub" ] || exit 0
[ -n "$allowed" ] || allowed="0.0.0.0/0,::/0"
wg set wg0 peer "$peer_pub" allowed-ips "$allowed" persistent-keepalive 25

[ -x /opt/gateway-agent/deeporc-routing.sh ] \
	&& /opt/gateway-agent/deeporc-routing.sh apply
