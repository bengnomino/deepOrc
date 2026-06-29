#!/usr/bin/env bash
# Render and apply deeporc nftables rules (replaces UFW).
set -euo pipefail

ensure_nftables() {
  apt_install install -y -qq nftables
  systemctl stop ufw 2>/dev/null || true
  systemctl disable ufw 2>/dev/null || true
  DEBIAN_FRONTEND=noninteractive apt-get remove -y -qq ufw 2>/dev/null || true
}

orch_bridge_cidr() {
  local ip="${1:-10.10.0.1}"
  local prefix="${2:-16}"
  if [[ -n "${IP_POOL_NETWORK:-}" ]]; then
    echo "$IP_POOL_NETWORK"
    return
  fi
  echo "${ip%.*}.0/${prefix}"
}

render_nft_template() {
  local template=$1
  local out=$2
  sed \
    -e "s|@ORCH_NET@|$(orch_bridge_cidr "${ORCH_HOST_IP:-10.10.0.1}")|g" \
    -e "s|@PORT_POOL_START@|${PORT_POOL_START:-51001}|g" \
    -e "s|@PORT_POOL_END@|${PORT_POOL_END:-52000}|g" \
    "$template" >"$out"
}

apply_nftables_rules() {
  local rendered=$1
  mkdir -p /etc/nftables.d
  install -m 644 "$rendered" /etc/nftables.d/10-deeporc.nft

  if [[ ! -f /etc/nftables.conf ]] || ! grep -q 'nftables.d' /etc/nftables.conf; then
    cat >/etc/nftables.conf <<'EOF'
#!/usr/sbin/nft -f
include "/etc/nftables.d/*.nft"
EOF
  fi

  nft delete table inet deeporc 2>/dev/null || true
  nft -f /etc/nftables.d/10-deeporc.nft
  systemctl enable nftables 2>/dev/null || true
  systemctl restart nftables 2>/dev/null || true
}

show_nftables_rules() {
  log "Active rules (inet deeporc):"
  nft list table inet deeporc
}
