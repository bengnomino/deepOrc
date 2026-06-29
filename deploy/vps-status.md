# VPS Deploy Status — deeporc.harlock.network

## Server (test)
- **Host:** `root@<VPS_IP>` (DigitalOcean, KVM)
- **SSH key:** `~/.ssh/deasit` (mode `600`)
- **Domain:** `https://deeporc.harlock.network`

## One-shot bootstrap

```bash
git clone git@github.com:bengnomino/deeporc.git /opt/deeporc
cd /opt/deeporc
cp deploy/hosts/host.env.example deploy/hosts/host.env
# edit DOMAIN (+ CLOUDFLARE_* if using Cloudflare)
sudo ./deploy/bootstrap-vps.sh deploy/hosts/host.env
```

Bootstrap installs the stack (Incus, Headscale, Caddy, orchestrator) and imports **`local:gw-golden`** from the repo. Create the first gateway from the UI.

## Active services

| Service | Endpoint | Notes |
|---------|----------|-------|
| Orchestrator API | `https://deeporc.harlock.network/orchestrator/api/v1/` | Auth: `X-API-Key` |
| Health | `https://deeporc.harlock.network/orchestrator/health` | |
| Headscale | `https://deeporc.harlock.network` | `/api/v1` = Headscale REST |
| Gateway agent wheel | `https://deeporc.harlock.network/packages/` | Legacy cloud-init path (not used with `gw-golden`) |

## Headscale (v0.29)

**Gateway VM:** preauth key created automatically by the orchestrator.

**Android exit node:** manual after bootstrap:

```bash
sudo /opt/deeporc/deploy/headscale-keys.sh
# On the phone: login server https://deeporc.harlock.network
# tailscale up --advertise-exit-node --authkey <KEY>
sudo headscale routes list
sudo headscale routes enable -r <ROUTE_ID>
```

## Firewall (nftables)

Rules live in `deploy/nftables/` — applied by `deploy/firewall-nft.sh` (CP) and `deploy/firewall-worker-nft.sh` (worker).

| Port | CP | Worker |
|------|----|--------|
| TCP 22 | yes | yes |
| TCP 80/443 | yes | no |
| UDP 51001–52000 | yes | yes |
| TCP 8080/8000 | from `10.10.0.0/16` only | no |

Re-apply: `sudo ./deploy/firewall-nft.sh deploy/hosts/host.env`
