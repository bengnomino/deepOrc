# deepOrc

Orchestratore per gateway clusterizzati con architettura **invertita** rispetto al modello VDI classico:

- Ogni **gateway è un exit node Tailscale** (Headscale)
- Un **solo peer WireGuard** per gateway (backhaul verso il cluster)
- I client Tailscale usano il gateway come uscita Internet

## Architettura

```
Client Tailscale ──► Gateway VM (exit node) ──► Internet
                         ▲
                    1× peer WG (backhaul)
```

Flusso backhaul:

```
Nodo cluster ──WireGuard──► Gateway VM (Incus su worker) ──► Internet
```

L'orchestratore gestisce:

- Provisioning gateway OpenWrt su Incus (worker VPS)
- Tailscale con `--advertise-exit-node` e tag `tag:exit`
- Un peer WireGuard backhaul per gateway
- nftables fail-closed (egress via WAN, non via exit node esterno)
- Cluster multi-worker (control plane + worker Incus)

## Setup iniziale (2 host)

| Host | IP | Ruolo |
|------|-----|--------|
| Control plane | `165.227.156.103` | Orchestrator + Headscale + UI |
| Worker 3 | `146.190.232.35` | Incus + gateway VM |

## Prerequisiti VPS

### Control plane (Debian)
- Incus opzionale (gateway su worker remoti)
- Headscale + Caddy
- Pool porte UDP `51001-52000` sul worker per WireGuard

### Worker
- Incus con golden image `gw-golden`
- Join Tailscale (`tag:worker-host`)
- `./deploy/join-worker.sh` dal control plane

### Headscale policy
```bash
./deploy/setup-headscale-policy.sh
```
Tag `tag:exit` owned by `gateways@` con auto-approvazione route exit.

## Installazione

### Sviluppo locale

```bash
python3.13 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
cp deploy/orchestrator.env.example .env
alembic upgrade head
orchestrator
```

### Produzione (control plane)

```bash
cp deploy/hosts/host.env.example deploy/hosts/host.env
# DOMAIN, IP, SECRET_KEY, API_KEY
sudo ./deploy/bootstrap-vps.sh deploy/hosts/host.env
```

### Worker

```bash
# Sul worker 146.190.232.35
curl -fsSL https://<DOMAIN>/orchestrator/ui/workers/join.sh | sudo bash -s -- \
  --enroll-token <TOKEN> --cp-url https://<DOMAIN>
```

Aggiornamenti CP: `sudo ./deploy/update.sh main deploy/hosts/host.env`

Dettagli: [deploy/README.md](deploy/README.md).

## API gateway

```bash
curl -X POST https://<DOMAIN>/orchestrator/api/gateways \
  -H "Authorization: Bearer $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"worker_id": 1}'
```

Dopo il provisioning il gateway compare su Headscale come exit node (`gw-NNN`). Il peer backhaul `{name}-link` viene creato automaticamente.

## Differenze vs orchtest

| orchtest | deepOrc |
|----------|---------|
| Gateway → exit node Android esterno | Gateway **è** l'exit node |
| Molti peer WG (VDI) | **Un** peer WG backhaul |
| Assegnazione exit node in UI | Exit node implicito (hostname gateway) |
