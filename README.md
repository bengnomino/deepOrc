# deepOrc

Orchestrator for clustered gateways with an **inverted** architecture compared to classic VDI:

- Each **gateway is a Tailscale exit node** (Headscale)
- **One** WireGuard peer per gateway (backhaul to the cluster)
- Tailscale clients use the gateway as their Internet exit

## Architecture

```
Tailscale client ──► Gateway VM (exit node) ──► Internet
                         ▲
                    1× WG peer (backhaul)
```

Backhaul flow:

```
Cluster node ──WireGuard──► Gateway VM (Incus on worker) ──► Internet
```

The orchestrator manages:

- OpenWrt gateway provisioning on Incus (worker VPS)
- Tailscale with `--advertise-exit-node` and tag `tag:exit`
- One WireGuard backhaul peer per gateway
- nftables fail-closed (egress via WAN, not via external exit node)
- Multi-worker cluster (control plane + Incus workers)

## Initial setup (2 hosts)

| Host | IP | Role |
|------|-----|------|
| Control plane | `165.227.156.103` | Orchestrator + Headscale + UI |
| Worker 3 | `146.190.232.35` | Incus + gateway VMs |

## VPS prerequisites

### Control plane (Debian)
- Incus optional (gateways run on remote workers)
- Headscale + Caddy
- UDP port pool `51001-52000` on workers for WireGuard

### Worker
- Incus with golden image `gw-golden`
- Join Tailscale (`tag:worker-host`)
- `./deploy/join-worker.sh` from the control plane

### Headscale policy
```bash
./deploy/setup-headscale-policy.sh
```
Tag `tag:exit` owned by `gateways@` with auto-approved exit routes.

## Installation

### Local development

```bash
python3.13 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
cp deploy/orchestrator.env.example .env
alembic upgrade head
orchestrator
```

### Production (control plane)

```bash
cp deploy/hosts/host.env.example deploy/hosts/host.env
# DOMAIN, IP, SECRET_KEY, API_KEY
sudo ./deploy/bootstrap-vps.sh deploy/hosts/host.env
```

### Worker

```bash
# On worker 146.190.232.35
curl -fsSL https://<DOMAIN>/orchestrator/ui/workers/join.sh | sudo bash -s -- \
  --enroll-token <TOKEN> --cp-url https://<DOMAIN>
```

Control plane updates: `sudo ./deploy/update.sh main deploy/hosts/host.env`

Details: [deploy/README.md](deploy/README.md).

## Gateway API

```bash
curl -X POST https://<DOMAIN>/orchestrator/api/gateways \
  -H "Authorization: Bearer $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"worker_id": 1}'
```

After provisioning the gateway appears on Headscale as an exit node (`gw-NNN`). The backhaul peer `{name}-link` is created automatically.

## Differences vs orchtest

| orchtest | deepOrc |
|----------|---------|
| Gateway → external Android exit node | Gateway **is** the exit node |
| Many WG peers (VDI) | **One** WG backhaul peer |
| Exit node assignment in UI | Exit node implicit (gateway hostname) |
