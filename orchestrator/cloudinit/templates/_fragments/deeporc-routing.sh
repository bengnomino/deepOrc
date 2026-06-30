#!/bin/sh
# deepOrc OpenWrt routing: default Internet -> wg0; tailscaled/control -> eth0 (wan table).
# Exit-node forwarded traffic (iif tailscale0) uses main -> wg0.
set -eu

WAN_TABLE=100
WAN_TABLE_NAME=wan
TAILNET=100.64.0.0/10
MAGICDNS=100.100.100.100
HOST_IF=eth0
UPLINK_IF=wg0
TS_IF=tailscale0

PUBLIC_DNS="8.8.8.8 8.8.4.4 1.1.1.1 1.0.0.1"
DOH_HOSTS="cloudflare-dns.com dns.google"
RULE_WG_PEER=35
RULE_WG_GW=40
RULE_TS_SRC=45
RULE_TAILNET=48
RULE_VM_SRC=50
RULE_EXIT_FWD=49
RULE_DNS_BASE=52
RULE_MAGICDNS=57
RULE_WG_INGRESS=59

[ -f /opt/gateway-agent/exit.env ] && . /opt/gateway-agent/exit.env
[ -f /opt/gateway-agent/tailscale.env ] && . /opt/gateway-agent/tailscale.env

WG_SUBNET="${WG_SUBNET:-10.64.5.0/24}"
WG_GW="${WG_GW:-10.64.5.1}"
VM_IP="${VM_IP:-10.10.2.10}"
# tailscale0 defaults to 1280; exit-via-wg needs both legs high enough for TLS backhaul.
EXIT_MTU="${EXIT_MTU:-1420}"

_log() { logger -t deeporc-routing "$*" 2>/dev/null || echo "deeporc-routing: $*"; }

_host_ipv4() {
	host="$1"
	case "$host" in
		*[!0-9.]*)
			getent ahostsv4 "$host" 2>/dev/null | awk '{print $1}' | sort -u
			;;
		*) echo "$host" ;;
	esac
}

_wan_gw() {
	gw=$(ip -4 route show default dev "$HOST_IF" 2>/dev/null | awk '/default/ {print $3; exit}')
	if [ -n "$gw" ]; then
		echo "$gw"
		return
	fi
	gw=$(ip -4 route show table "$WAN_TABLE" default 2>/dev/null | awk '/default via/ {print $3; exit}')
	if [ -n "$gw" ]; then
		echo "$gw"
		return
	fi
	case "$VM_IP" in
		10.10.*) echo "10.10.0.1" ;;
	esac
}

_ensure_rt_table() {
	id="$1"
	name="$2"
	grep -q "^${id} ${name}\$" /etc/iproute2/rt_tables 2>/dev/null \
		|| echo "${id} ${name}" >>/etc/iproute2/rt_tables
}

_rule_scrub_pref() {
	pref="$1"
	while ip rule del pref "$pref" 2>/dev/null; do :; done
}

_rule_add() {
	pref="$1"
	shift
	_rule_scrub_pref "$pref"
	ip rule add pref "$pref" "$@"
}

_fw4_del_by_comment() {
	chain="$1"
	comment="$2"
	while nft -a list chain inet fw4 "$chain" 2>/dev/null | grep -q "$comment"; do
		h=$(nft -a list chain inet fw4 "$chain" 2>/dev/null | grep "$comment" | head -1 | awk '{print $NF}')
		case "$h" in ''|*[!0-9]*) break ;; esac
		nft delete rule inet fw4 "$chain" handle "$h" 2>/dev/null || break
	done
}

_fw4_insert() {
	chain="$1"
	comment="$2"
	shift 2
	_fw4_del_by_comment "$chain" "$comment"
	nft insert rule inet fw4 "$chain" "$@" comment "$comment"
}

_cleanup_stale() {
	for pref in 52 53 54 55 58 60 100; do
		_rule_scrub_pref "$pref"
	done
	while ip rule del iif "$TS_IF" lookup 200 2>/dev/null; do :; done
	ts_ip="$(_ts_ip)"
	if [ -n "$ts_ip" ]; then
		while ip rule del from "${ts_ip}/32" lookup main 2>/dev/null; do :; done
	fi
	ip route flush table 200 2>/dev/null || true
}

_ts_ip() {
	ip -4 -o addr show dev "$TS_IF" 2>/dev/null | awk '{print $4}' | cut -d/ -f1 | head -1
}

_strip_wg_pollution() {
	ip -4 route show table main dev "$UPLINK_IF" 2>/dev/null | while read -r line; do
		dst=$(echo "$line" | awk '{print $1}')
		case "$dst" in
			default|"$WG_SUBNET") continue ;;
		esac
		ip route del "$dst" dev "$UPLINK_IF" 2>/dev/null || true
	done
}

_apply_mtu() {
	ip link show "$UPLINK_IF" >/dev/null 2>&1 \
		&& ip link set "$UPLINK_IF" mtu "$EXIT_MTU" 2>/dev/null || true
	ip link show "$TS_IF" >/dev/null 2>&1 \
		&& ip link set "$TS_IF" mtu "$EXIT_MTU" 2>/dev/null || true
}

_apply_wg_peer() {
	[ -f /etc/wireguard/wg0.conf ] || return 0
	ip link show "$UPLINK_IF" >/dev/null 2>&1 || return 0
	if [ -n "${UPLINK_PEER:-}" ] && ! wg show "$UPLINK_IF" peers 2>/dev/null | grep -q .; then
		wg set "$UPLINK_IF" peer "$UPLINK_PEER" allowed-ips 0.0.0.0/0,::/0 persistent-keepalive 25
	fi
	for peer in $(wg show "$UPLINK_IF" peers 2>/dev/null); do
		wg set "$UPLINK_IF" peer "$peer" allowed-ips 0.0.0.0/0,::/0 persistent-keepalive 25
	done
}

_apply_dnsmasq_off() {
	if [ -x /etc/init.d/dnsmasq ]; then
		/etc/init.d/dnsmasq stop 2>/dev/null || true
		/etc/init.d/dnsmasq disable 2>/dev/null || true
	fi
}

_apply_host_link() {
	ip link set "$HOST_IF" up 2>/dev/null || true
	ip addr show dev "$HOST_IF" | grep -q "$VM_IP" \
		|| ip addr add "$VM_IP/16" dev "$HOST_IF" 2>/dev/null || true
}

_apply_wan_table() {
	gw="$(_wan_gw)"
	[ -n "$gw" ] || return 0
	_ensure_rt_table "$WAN_TABLE" "$WAN_TABLE_NAME"
	ip route replace default via "$gw" dev "$HOST_IF" table "$WAN_TABLE"
	ip route replace "$TAILNET" dev "$TS_IF" table "$WAN_TABLE" 2>/dev/null || true
	ip route replace "$MAGICDNS" dev "$TS_IF" scope link table "$WAN_TABLE" 2>/dev/null || true
	if [ -n "${HEADSCALE_URL:-}" ]; then
		url="${HEADSCALE_URL#*://}"
		host="${url%%/*}"
		host="${host%%:*}"
		for ip in $(_host_ipv4 "$host"); do
			ip route replace "$ip/32" via "$gw" dev "$HOST_IF" table "$WAN_TABLE" 2>/dev/null || true
		done
	fi
	for dns in $PUBLIC_DNS; do
		ip route replace "$dns/32" via "$gw" dev "$HOST_IF" table "$WAN_TABLE" 2>/dev/null || true
	done
	for host in $DOH_HOSTS; do
		for ip in $(_host_ipv4 "$host"); do
			ip route replace "$ip/32" via "$gw" dev "$HOST_IF" table "$WAN_TABLE" 2>/dev/null || true
		done
	done
}

_apply_main_table() {
	gw="$(_wan_gw)"
	ip link show "$UPLINK_IF" >/dev/null 2>&1 || return 0
	_strip_wg_pollution
	ip route replace default dev "$UPLINK_IF" table main
	ip route replace "$WG_SUBNET" dev "$UPLINK_IF" table main 2>/dev/null || true
	ip route replace "$TAILNET" dev "$TS_IF" table main 2>/dev/null || true
	ip route replace "$MAGICDNS" dev "$TS_IF" scope link table main 2>/dev/null || true
	# Control plane + DNS bypass wg0 default in main (tailscale login before TS policy rules exist).
	if [ -n "$gw" ]; then
		for dns in $PUBLIC_DNS; do
			ip route replace "$dns/32" via "$gw" dev "$HOST_IF" table main 2>/dev/null || true
		done
		if [ -n "${HEADSCALE_URL:-}" ]; then
			url="${HEADSCALE_URL#*://}"
			host="${url%%/*}"
			host="${host%%:*}"
			for ip in $(_host_ipv4 "$host"); do
				ip route replace "$ip/32" via "$gw" dev "$HOST_IF" table main 2>/dev/null || true
			done
		fi
	fi
}

_apply_policy_rules() {
	ts_ip="$(_ts_ip)"
	_rule_add "$RULE_WG_PEER" to "$WG_SUBNET" lookup main
	_rule_add "$RULE_WG_GW" from "${WG_GW}/32" lookup main
	if [ -n "$ts_ip" ]; then
		_rule_add "$RULE_TS_SRC" from "${ts_ip}/32" lookup "$WAN_TABLE"
	fi
	_rule_add "$RULE_TAILNET" to "$TAILNET" lookup main
	_rule_add "$RULE_VM_SRC" from "${VM_IP}/32" lookup "$WAN_TABLE"
	_rule_add "$RULE_EXIT_FWD" iif "$TS_IF" lookup main
	_rule_add "$RULE_MAGICDNS" to "$MAGICDNS" lookup main
	_rule_add "$RULE_WG_INGRESS" iif "$UPLINK_IF" lookup main
}

_apply_nft() {
	while nft -a list chain ip nat ts-postrouting 2>/dev/null | grep -q masquerade; do
		h=$(nft -a list chain ip nat ts-postrouting 2>/dev/null | grep masquerade | head -1 | awk '{print $NF}')
		case "$h" in ''|*[!0-9]*) break ;; esac
		nft delete rule ip nat ts-postrouting handle "$h" 2>/dev/null || break
	done
	nft delete table ip gw_nat 2>/dev/null || true
	nft delete table ip deeporc_exit 2>/dev/null || true
	nft delete table ip deeporc_mangle 2>/dev/null || true
	if [ -f /etc/nftables.d/gateway.nft ]; then
		nft -f /etc/nftables.d/gateway.nft
	else
		nft add table ip gw_nat
		nft add chain ip gw_nat postrouting '{ type nat hook postrouting priority srcnat; policy accept; }'
		nft add rule ip gw_nat postrouting ip saddr 100.64.0.0/10 oifname wg0 masquerade
		nft add rule ip gw_nat postrouting ip saddr 100.64.0.0/10 oifname eth0 udp dport 53 masquerade
		nft add rule ip gw_nat postrouting ip saddr 100.64.0.0/10 oifname eth0 tcp dport 53 masquerade
		nft add table ip deeporc_exit
		nft add chain ip deeporc_exit forward '{ type filter hook forward priority filter; policy accept; }'
		nft add rule ip deeporc_exit forward iifname tailscale0 oifname wg0 accept
		nft add rule ip deeporc_exit forward iifname wg0 oifname tailscale0 accept
	fi
	if nft list chain inet fw4 forward >/dev/null 2>&1; then
		_fw4_insert forward deeporc-exit-fwd iifname tailscale0 oifname wg0 accept
		_fw4_insert forward deeporc-wg-fwd iifname wg0 oifname tailscale0 accept
		_fw4_insert forward deeporc-ts-fwd iifname tailscale0 accept
	fi
	if nft list chain inet fw4 input_wan >/dev/null 2>&1 \
		&& [ -f /etc/wireguard/wg0.conf ]; then
		wg_port=$(grep -m1 '^ListenPort' /etc/wireguard/wg0.conf | cut -d= -f2 | tr -d ' ')
		if [ -n "$wg_port" ]; then
			_fw4_insert input_wan deeporc-wg meta nfproto ipv4 udp dport "$wg_port" accept
		fi
	fi
}

_apply_ethtool() {
	command -v ethtool >/dev/null 2>&1 || return 0
	for iface in "$HOST_IF" "$TS_IF" "$UPLINK_IF"; do
		ip link show "$iface" >/dev/null 2>&1 || continue
		ethtool -K "$iface" rx-udp-gro-forwarding on rx-gro-list off 2>/dev/null || true
	done
}

_apply_tailscale() {
	tailscale set --advertise-exit-node --accept-dns --advertise-routes= 2>/dev/null || true
}

_apply_sysctl() {
	sysctl -w net.ipv4.ip_forward=1 >/dev/null
	sysctl -w net.ipv4.conf.all.rp_filter=0 >/dev/null
	sysctl -w net.ipv4.conf."$UPLINK_IF".rp_filter=0 >/dev/null 2>&1 || true
	sysctl -w net.ipv4.conf."$TS_IF".rp_filter=0 >/dev/null 2>&1 || true
	sysctl -w net.netfilter.nf_conntrack_helper=1 2>/dev/null || true
	sysctl -w net.ipv4.tcp_mtu_probing=1 >/dev/null 2>&1 || true
	sysctl -w net.ipv4.conf."$HOST_IF".forwarding=1 >/dev/null 2>&1 || true
	sysctl -w net.ipv4.conf."$TS_IF".forwarding=1 >/dev/null 2>&1 || true
}

apply() {
	_cleanup_stale
	_apply_dnsmasq_off
	_apply_host_link
	_apply_wg_peer
	_apply_mtu
	_apply_wan_table
	_apply_main_table
	_apply_policy_rules
	_apply_nft
	_apply_tailscale
	_apply_sysctl
	_apply_ethtool
	_log "apply OK"
}

stop_rules() {
	_cleanup_stale
	for pref in "$RULE_WG_PEER" "$RULE_WG_GW" "$RULE_TS_SRC" "$RULE_TAILNET" "$RULE_VM_SRC" \
		"$RULE_EXIT_FWD" "$RULE_MAGICDNS" "$RULE_WG_INGRESS"; do
		_rule_scrub_pref "$pref"
	done
}

daemon() {
	_log "daemon start"
	while true; do
		apply || _log "apply failed"
		sleep 60
	done
}

case "${1:-apply}" in
	apply) apply ;;
	start) apply; daemon ;;
	stop) stop_rules ;;
	reload) apply ;;
	daemon) daemon ;;
	*) echo "usage: $0 {apply|start|stop|reload|daemon}" >&2; exit 1 ;;
esac
