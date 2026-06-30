#!/usr/bin/env bash
# Repair deeper exit path for gw-015 ONLY (dio / EXIT VM).
# gw-015 uses mac_174 / 192.168.13.174 — the only slot with country on deeper.
# Run as root on dio: bash deploy/dio-repair-gw-015.sh
set -euo pipefail

PARENT_IFACE="${PARENT_IFACE:-ens18}"
LAN_GW="${LAN_GW:-192.168.13.254}"
SLOT=174
MAC="mac_${SLOT}"
LAN_IP="192.168.13.${SLOT}"
WG_IF="wg-gw015"
TABLE="${SLOT}"

echo "==> gw-015 deeper repair (${LAN_IP} / ${MAC} / ${WG_IF})"

sysctl -w net.ipv4.ip_forward=1
sysctl -w net.ipv4.conf.all.rp_filter=0
sysctl -w net.ipv4.conf.default.rp_filter=0
sysctl -w "net.ipv4.conf.${PARENT_IFACE}.rp_filter=0"

ip link del "${MAC}" 2>/dev/null || true
ip link add "${MAC}" link "${PARENT_IFACE}" type macvlan mode bridge
ip addr add "${LAN_IP}/24" dev "${MAC}"
ip link set "${MAC}" up

mkdir -p /etc/iproute2
grep -q "^${TABLE} " /etc/iproute2/rt_tables 2>/dev/null || echo "${TABLE} deeporc-${SLOT}" >> /etc/iproute2/rt_tables
ip route replace default via "${LAN_GW}" dev "${MAC}" table "${TABLE}"
ip route replace "${LAN_IP}/24" dev "${MAC}" scope link table "${TABLE}"

ip rule del from "${LAN_IP}/32" lookup "${TABLE}" 2>/dev/null || true
ip rule add pref $((32000 + SLOT)) from "${LAN_IP}/32" lookup "${TABLE}"
ip rule del iif "${WG_IF}" lookup "${TABLE}" 2>/dev/null || true
ip rule add pref 32751 iif "${WG_IF}" lookup "${TABLE}"

if [[ ! -f "/etc/wireguard/${WG_IF}.conf" ]]; then
	echo "ERROR: missing /etc/wireguard/${WG_IF}.conf — regenerate from orchestrator UI" >&2
	exit 1
fi

wg-quick down "${WG_IF}" 2>/dev/null || true
wg-quick up "${WG_IF}"
ip link set "${WG_IF}" mtu 1380

iptables -C FORWARD -i "${WG_IF}" -o "${MAC}" -j ACCEPT 2>/dev/null \
	|| iptables -A FORWARD -i "${WG_IF}" -o "${MAC}" -j ACCEPT
iptables -C FORWARD -i "${MAC}" -o "${WG_IF}" -m state --state RELATED,ESTABLISHED -j ACCEPT 2>/dev/null \
	|| iptables -A FORWARD -i "${MAC}" -o "${WG_IF}" -m state --state RELATED,ESTABLISHED -j ACCEPT
iptables -t nat -C POSTROUTING -o "${MAC}" -j MASQUERADE 2>/dev/null \
	|| iptables -t nat -A POSTROUTING -o "${MAC}" -j MASQUERADE

echo "==> verify (must egress via ${LAN_IP} country on deeper)"
wg show "${WG_IF}" | head -8
ip route get 8.8.8.8 iif "${WG_IF}" from 10.64.33.1 || true
curl -4 -m 8 -sS --interface "${MAC}" http://ifconfig.me || echo "FAIL: deeper country not working on ${LAN_IP}"
echo "Done."
