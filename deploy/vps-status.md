# VPS Deploy Status — deeporc.harlock.network

## Server (test)
- **Host:** `root@<VPS_IP>` (DigitalOcean, KVM)
- **SSH key:** `~/.ssh/deasit` (permessi `600`)
- **Domain:** `https://deeporc.harlock.network`

## One-shot bootstrap

```bash
git clone git@github.com:bengnomino/deeporc.git /opt/deeporc
cd /opt/deeporc
cp deploy/hosts/host.env.example deploy/hosts/host.env
# edita DOMAIN (+ CLOUDFLARE_* se usi Cloudflare)
sudo ./deploy/bootstrap-vps.sh deploy/hosts/host.env
```

Bootstrap installa lo stack (Incus, Headscale, Caddy, orchestrator) e importa **`local:gw-golden`** dal repo. Il primo gateway lo crei dalla UI.

## Servizi attivi

| Servizio | Endpoint | Note |
|----------|----------|------|
| Orchestrator API | `https://deeporc.harlock.network/orchestrator/api/v1/` | Auth: `X-API-Key` |
| Health | `https://deeporc.harlock.network/orchestrator/health` | |
| Headscale | `https://deeporc.harlock.network` | `/api/v1` = Headscale REST |
| Gateway agent wheel | `https://deeporc.harlock.network/packages/` | Legacy cloud-init path (non usato con `gw-golden`) |

## Headscale (v0.29)

**Gateway VM:** preauth key creata automaticamente dall'orchestratore.

**Exit node Android:** manuale dopo bootstrap:

```bash
sudo /opt/deeporc/deploy/headscale-keys.sh
# Sul telefono: login server https://deeporc.harlock.network
# tailscale up --advertise-exit-node --authkey <KEY>
sudo headscale routes list
sudo headscale routes enable -r <ROUTE_ID>
```

## Firewall (nftables)

Regole leggibili in `deploy/nftables/` — applicate da `deploy/firewall-nft.sh` (CP) e `deploy/firewall-worker-nft.sh` (worker).

| Porta | CP | Worker |
|-------|----|--------|
| TCP 22 | sì | sì |
| TCP 80/443 | sì | no |
| UDP 51001–52000 | sì | sì |
| TCP 8080/8000 | solo da `10.10.0.0/16` | no |

Riapplica: `sudo ./deploy/firewall-nft.sh deploy/hosts/host.env`
