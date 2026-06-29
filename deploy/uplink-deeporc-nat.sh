#!/bin/sh
# NAT + forward on WireGuard uplink VPS/PC. Idempotent — safe to re-run at boot (PostUp).
set -eu

WG_SUBNET="${WG_SUBNET:-10.64.6.0/24}"
WAN="${WAN:-}"
WG_IF="${WG_IF:-}"

if [ -z "$WAN" ]; then
	WAN=$(ip -4 route show default | awk '{print $5; exit}')
fi
[ -n "$WAN" ] || { echo "set WAN=eth0" >&2; exit 1; }

if [ -z "$WG_IF" ]; then
	WG_IF=$(ip -4 -o addr show | awk -v s="${WG_SUBNET%/*}" '$4 ~ "^" s "\\." {print $2; exit}')
fi
[ -n "$WG_IF" ] || WG_IF=$(wg show interfaces 2>/dev/null | head -1)
[ -n "$WG_IF" ] || { echo "set WG_IF=wg interface name" >&2; exit 1; }

sysctl -w net.ipv4.ip_forward=1
sysctl -w net.ipv4.conf.all.rp_filter=0
sysctl -w net.ipv4.conf.default.rp_filter=0

nft delete table ip deeporc_uplink 2>/dev/null || true
nft add table ip deeporc_uplink
nft add chain ip deeporc_uplink forward '{ type filter hook forward priority filter; policy accept; }'
nft add rule ip deeporc_uplink forward iifname "$WG_IF" oifname "$WAN" accept
nft add rule ip deeporc_uplink forward iifname "$WAN" oifname "$WG_IF" ct state established,related accept
nft add chain ip deeporc_uplink postrouting '{ type nat hook postrouting priority srcnat; policy accept; }'
nft add rule ip deeporc_uplink postrouting ip saddr "$WG_SUBNET" oifname "$WAN" masquerade
nft add rule ip deeporc_uplink postrouting ip saddr 100.64.0.0/10 oifname "$WAN" masquerade

echo "deeporc uplink NAT OK: $WG_SUBNET + 100.64.0.0/10 -> $WAN via $WG_IF"
