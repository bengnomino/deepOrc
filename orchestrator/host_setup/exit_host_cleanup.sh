#!/usr/bin/env bash
# deepOrc exit host — remove all gateway plumbing (WireGuard, macvlan, policy routing).
# Discovers deepOrc artifacts on the host; no gateway list required.
# Run as root on the EXIT VM. Idempotent — safe to re-run.
#
# Usage:
#   bash exit_host_cleanup.sh
#   bash exit_host_cleanup.sh --dry-run
set -euo pipefail

DRY_RUN=0
[[ "${1:-}" == "--dry-run" ]] && DRY_RUN=1

_log() { printf '==> %s\n' "$*"; }
_run() {
	if (( DRY_RUN )); then
		printf '[dry-run] %s\n' "$*"
	else
		"$@"
	fi
}

_iptables_del_loop() {
	local table="${1:-}"
	local pattern="$2"
	local cmd=(iptables)
	[[ -n "$table" ]] && cmd+=(-t "$table")
	local line
	while IFS= read -r line; do
		[[ -z "$line" ]] && continue
		local args
		args=$(sed 's/^-A /-D /' <<<"$line")
		_run "${cmd[@]}" $args 2>/dev/null || true
	done < <("${cmd[@]}" -S 2>/dev/null | grep -E "$pattern" || true)
}

_delete_rules_for_table() {
	local table="$1"
	local rule pref
	while IFS= read -r rule; do
		[[ -z "$rule" ]] && continue
		pref=${rule%%:*}
		[[ "$pref" =~ ^[0-9]+$ ]] || continue
		_log "ip rule pref ${pref} (table ${table})"
		_run ip rule del pref "$pref" 2>/dev/null || true
	done < <(ip rule show 2>/dev/null | grep -E "lookup ${table}( |$)" || true)
}

_deeporc_wg_ifaces() {
	{
		ip -o link show type wireguard 2>/dev/null \
			| awk -F': ' '{print $2}' | cut -d@ -f1
		for conf in /etc/wireguard/wg-gw*.conf; do
			[[ -f "$conf" ]] || continue
			basename "$conf" .conf
		done
	} | sort -u
}

_deeporc_mac_ifaces() {
	ip -o link show type macvlan 2>/dev/null \
		| awk -F': ' '{print $2}' | cut -d@ -f1 \
		| grep -E '^mac_[0-9]+$' || true
}

_deeporc_table_ids() {
	if [[ -f /etc/iproute2/rt_tables ]]; then
		awk '/deeporc/ {print $1}' /etc/iproute2/rt_tables
	fi
}

_table_for_wg() {
	local wg_if="$1"
	ip rule show iif "$wg_if" 2>/dev/null \
		| awk '/lookup/ {print $NF; exit}'
}

_table_for_mac() {
	local mac="$1"
	local slot="${mac#mac_}"
	ip rule show 2>/dev/null \
		| awk -v t="$slot" '$0 ~ "lookup " t "( |$)" {print t; exit}'
}

_mac_for_wg() {
	local wg_if="$1"
	iptables -S FORWARD 2>/dev/null \
		| awk -v w="$wg_if" '$0 ~ "-i " w " -o mac_" {for (i=1;i<=NF;i++) if ($i=="-o") {print $(i+1); exit}}'
}

_cleanup_wg() {
	local wg_if="$1"
	local mac="${2:-}"
	local table="${3:-}"

	_log "WireGuard ${wg_if}"
	_run wg-quick down "$wg_if" 2>/dev/null || true
	_run ip link del "$wg_if" 2>/dev/null || true
	_run rm -f "/etc/wireguard/${wg_if}.conf"

	if [[ -n "$mac" ]]; then
		_iptables_del_loop "" "-i ${wg_if} -o ${mac}"
		_iptables_del_loop "" "-i ${mac} -o ${wg_if}"
		_iptables_del_loop nat "-o ${mac}.*MASQUERADE"
	fi
	if [[ -n "$table" ]]; then
		_delete_rules_for_table "$table"
		_run ip route flush table "$table" 2>/dev/null || true
	fi
}

_cleanup_mac() {
	local mac="$1"
	local table="${2:-}"

	_log "macvlan ${mac}"
	if [[ -z "$table" ]]; then
		table=$(_table_for_mac "$mac" || true)
	fi
	_iptables_del_loop nat "-o ${mac}.*MASQUERADE"
	if [[ -n "$table" ]]; then
		_delete_rules_for_table "$table"
		_run ip route flush table "$table" 2>/dev/null || true
	fi
	_run ip link del "$mac" 2>/dev/null || true
}

_cleanup_rt_tables() {
	local tid
	for tid in $(_deeporc_table_ids); do
		_log "rt_tables entry ${tid}"
		if (( ! DRY_RUN )); then
			sed -i "/^[[:space:]]*${tid}[[:space:]]/d" /etc/iproute2/rt_tables 2>/dev/null || true
		fi
	done
}

main() {
	_log "deepOrc exit host cleanup${DRY_RUN:+ (dry run)}"

	local wg_if mac table
	while IFS= read -r wg_if; do
		[[ -z "$wg_if" ]] && continue
		mac=$(_mac_for_wg "$wg_if" || true)
		table=$(_table_for_wg "$wg_if" || true)
		_cleanup_wg "$wg_if" "$mac" "$table"
	done < <(_deeporc_wg_ifaces)

	while IFS= read -r mac; do
		[[ -z "$mac" ]] && continue
		table=$(_table_for_mac "$mac" || true)
		_cleanup_mac "$mac" "$table"
	done < <(_deeporc_mac_ifaces)

	for table in $(_deeporc_table_ids); do
		_delete_rules_for_table "$table"
		_run ip route flush table "$table" 2>/dev/null || true
	done

	_cleanup_rt_tables

	_log "remaining deepOrc WireGuard: $(tr '\n' ' ' < <(_deeporc_wg_ifaces) || echo none)"
	_log "remaining deepOrc macvlan: $(tr '\n' ' ' < <(_deeporc_mac_ifaces) || echo none)"
	_log "Done."
}

main "$@"
