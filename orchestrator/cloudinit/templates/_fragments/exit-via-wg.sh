#!/bin/sh
# deepOrc: Tailscale mesh/control via host (eth0). Only forwarded exit traffic -> wg0 -> uplink.
set -eu

[ -f /opt/gateway-agent/exit.env ] && . /opt/gateway-agent/exit.env

WG_SUBNET="${WG_SUBNET:-10.64.5.0/24}"
WG_GW="${WG_GW:-10.64.5.1}"
VM_IP="${VM_IP:-10.10.2.10}"

# OpenWrt dnsmasq binds :53 on tailscale0 and rejects tailnet clients (SERVFAIL on exit DNS).
if [ -x /etc/init.d/dnsmasq ]; then
	/etc/init.d/dnsmasq stop 2>/dev/null || true
	/etc/init.d/dnsmasq disable 2>/dev/null || true
fi

ip link set eth0 up 2>/dev/null || true
ip addr show dev eth0 | grep -q "$VM_IP" || ip addr add "$VM_IP/16" dev eth0 2>/dev/null || true
ip route replace default via 10.10.0.1 dev eth0 2>/dev/null || true

if ip link show wg0 >/dev/null 2>&1; then
	if [ -n "${UPLINK_PEER:-}" ] && ! wg show wg0 peers 2>/dev/null | grep -q .; then
		wg set wg0 peer "$UPLINK_PEER" allowed-ips 0.0.0.0/0,::/0 persistent-keepalive 25
	fi
	for peer in $(wg show wg0 peers 2>/dev/null); do
		wg set wg0 peer "$peer" allowed-ips 0.0.0.0/0,::/0 persistent-keepalive 25
	done
	# Exit-node DNS upstream must follow the same uplink as web traffic (not worker eth0 / AMS).
	ip route replace 1.1.1.1/32 dev wg0 2>/dev/null || true
	ip route replace 1.0.0.1/32 dev wg0 2>/dev/null || true
fi

ip rule del pref 35 2>/dev/null || true
ip rule add pref 35 to "$WG_SUBNET" lookup main
ip rule del pref 40 2>/dev/null || true
ip rule add pref 40 from "$WG_GW/32" lookup main
ip rule del pref 50 2>/dev/null || true
ip rule add pref 50 from "$VM_IP/32" lookup main
TS_IP=$(ip -4 -o addr show dev tailscale0 2>/dev/null | awk '{print $4}' | cut -d/ -f1)
if [ -n "$TS_IP" ]; then
	ip rule del pref 45 2>/dev/null || true
	ip rule add pref 45 from "$TS_IP/32" lookup main
fi
for pref in 54 55 60; do ip rule del pref "$pref" 2>/dev/null || true; done

grep -q '^200 backhaul' /etc/iproute2/rt_tables || echo '200 backhaul' >> /etc/iproute2/rt_tables
ip route replace default dev wg0 table backhaul
ip rule del pref 58 2>/dev/null || true
ip rule add pref 58 iif tailscale0 lookup backhaul

# Do not use tailscale up --reset here — it drops mesh state on every re-run.
# --accept-dns: exit node must accept control-plane DNS so it can proxy client queries (no leak to ISP).
tailscale set --advertise-exit-node --accept-dns --advertise-routes= 2>/dev/null || true
# Tailscale must own resolv.conf (100.100.100.100). Plain 1.1.1.1 breaks exit-node DNS for clients.
if ! grep -q '100.100.100.100' /etc/resolv.conf 2>/dev/null; then
	/etc/init.d/tailscale restart
	sleep 2
	tailscale set --advertise-exit-node --accept-dns --advertise-routes= 2>/dev/null || true
fi
while nft -a list chain ip nat ts-postrouting 2>/dev/null | grep -q masquerade; do
	h=$(nft -a list chain ip nat ts-postrouting 2>/dev/null | grep masquerade | head -1 | awk '{print $NF}')
	case "$h" in ''|*[!0-9]*) break;; esac
	nft delete rule ip nat ts-postrouting handle "$h" 2>/dev/null || break
done

nft delete table inet gw_filter 2>/dev/null || true
nft delete table ip gw_nat 2>/dev/null || true
nft delete table ip deeporc_exit 2>/dev/null || true

# OpenWrt fw4 forward policy is drop; without tailscale ts-forward, exit traffic dies here.
if nft list chain inet fw4 forward >/dev/null 2>&1; then
	nft list chain inet fw4 forward 2>/dev/null | grep -q 'deeporc-ts-fwd' || \
		nft insert rule inet fw4 forward iifname tailscale0 accept comment "deeporc-ts-fwd"
	nft list chain inet fw4 forward 2>/dev/null | grep -q 'deeporc-wg-fwd' || \
		nft insert rule inet fw4 forward iifname wg0 oifname tailscale0 accept comment "deeporc-wg-fwd"
	nft list chain inet fw4 forward 2>/dev/null | grep -q 'deeporc-exit-fwd' || \
		nft insert rule inet fw4 forward iifname tailscale0 oifname wg0 accept comment "deeporc-exit-fwd"
fi

if [ -f /etc/nftables.d/gateway.nft ]; then
	nft -f /etc/nftables.d/gateway.nft
else
	nft add table ip gw_nat
	nft add chain ip gw_nat postrouting '{ type nat hook postrouting priority srcnat; policy accept; }'
	nft add rule ip gw_nat postrouting ip saddr 100.64.0.0/10 oifname wg0 masquerade
	nft add table ip deeporc_exit
	nft add chain ip deeporc_exit forward '{ type filter hook forward priority filter; policy accept; }'
	nft add rule ip deeporc_exit forward iifname tailscale0 oifname wg0 accept
	nft add rule ip deeporc_exit forward iifname wg0 oifname tailscale0 accept
fi

sysctl -w net.ipv4.ip_forward=1 >/dev/null
sysctl -w net.ipv4.conf.all.rp_filter=0 >/dev/null
sysctl -w net.netfilter.nf_conntrack_helper=1 2>/dev/null || true

echo "exit-via-wg: OK"
