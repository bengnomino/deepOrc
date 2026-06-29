# VPS deploy (production-ready, fresh install)

Full install on Debian 13+: Incus, Headscale (ACL + `gateways` user), Caddy, orchestrator.

**Do not migrate** databases from other VPS hosts — each host starts clean.

## Minimal configuration

```bash
cp deploy/hosts/host.env.example deploy/hosts/host.env
```

Edit:

| Variable | Required | Description |
|----------|----------|-------------|
| `BASE_DOMAIN` | yes | DNS apex zone (e.g. `harlock.network`) — LE cert: `BASE_DOMAIN` + `*.BASE_DOMAIN` |
| `SERVICE_HOST` | yes* | subdomain label (e.g. `deeporc`) → URL `deeporc.harlock.network` |
| `CLOUDFLARE_API_TOKEN` | no | DNS A record + Zero Trust Access |
| `CLOUDFLARE_ACCESS_EMAIL` | yes (with token) | email allowed by Cloudflare Access |
| `CLOUDFLARE_ACCESS_SKIP` | no | `1` only if Access is already configured in the CF dashboard |

\* omit `SERVICE_HOST` if the service is on the apex (`BASE_DOMAIN` = public URL)

Everything else is automatic:
- `DOMAIN` — `${SERVICE_HOST}.${BASE_DOMAIN}` (derived; do not set manually)
- `HOST_PUBLIC_IP` — detected via ipify
- `WG_PUBLIC_HOST` — same as `HOST_PUBLIC_IP` (WireGuard does not go through Cloudflare)
- `HEADSCALE_BASE_DOMAIN` — `ts.${BASE_DOMAIN}` (tailnet MagicDNS only)
- `SECRET_KEY`, `API_KEY` — generated at bootstrap
- Headscale **0.29.1** (fresh): ACL policy + `gateways` user (no DB migration)

### Headscale 0.29

- Minimum Tailscale client: **v1.80.0**
- ACL `*` = tailnet only (not Internet); our policy remains valid
- `randomizeClientPort` belongs in the policy file (already included)
- Mobile registration uses `headscale auth register` (fallback to `nodes register`)

## First deploy

```bash
# on the VPS (root)
git clone git@github.com:bengnomino/deeporc.git /opt/deeporc
cd /opt/deeporc
cp deploy/hosts/host.env.example deploy/hosts/host.env
# edit DOMAIN (+ Cloudflare if used)
sudo ./deploy/bootstrap-vps.sh deploy/hosts/host.env
```

When finished the script:
- prints **API key** and UI URL
- updates `host.env` with generated secrets
- imports the vendored **`local:gw-golden`** image from the repo (no on-host build)
- runs the **gateway smoke test** (create, wait for `ready`, delete)

To skip the smoke test: `SKIP_SMOKE_GATEWAY=1 sudo ./deploy/bootstrap-vps.sh ...`

If you see `Smoke test passed: gateway smoke-gw is ready` → one-shot deploy OK.

### Cloudflare

With a configured token, the script:
1. Creates/updates **A** records for `DOMAIN` with **Cloudflare proxy enabled** (`proxied=true`, default)
2. If `CLOUDFLARE_ACCESS_EMAIL` is set, creates a Zero Trust app on `/orchestrator/*` and `/register/*`

`HEADSCALE_BASE_DOMAIN` (e.g. `ts.harlock.network`) is tailnet MagicDNS only — **no public DNS record**.

**WireGuard:** clients use `HOST_PUBLIC_IP` and the UDP port from the pool (`51001–52000`), not the domain name.

nftables opens **8080/8000** only from `10.10.0.0/16` (gateway → Headscale/orchestrator on the host). Rules in `deploy/nftables/control-plane.nft`.

**Expected RAM (idle VPS, no gateways):** ~280–320 MiB RSS (Incus ~80, orchestrator ~100, Headscale ~55, Caddy ~45). The ~650 MiB seen right after bootstrap was mostly **apt/pip cache** (~500 MiB) — `bootstrap-cleanup.sh` frees it at end of install. Each OpenWrt gateway adds ~128 MiB (Incus limit configurable with `INCUS_VM_MEMORY`).

To disable the proxy: `CLOUDFLARE_DNS_PROXIED=false` in `host.env`.

Recommended token permissions: **Zone → DNS → Edit**, **Account → Access → Apps and Policies → Edit**.

Origin SSL: with **Cloudflare proxied + Full (strict)** you need a valid certificate on the VPS. With a CF token, bootstrap runs **certbot once** for `BASE_DOMAIN` + `*.BASE_DOMAIN` (e.g. `harlock.network` + `*.harlock.network`) → `/etc/caddy/ssl/`. The certificate is **not** requested for the service subdomain. Set `ORIGIN_TLS=internal` only if CF is **Full** (not Strict).

```bash
cd /opt/deeporc
sudo ./deploy/update.sh main deploy/hosts/host.env
```

## Files

| File | Role |
|------|------|
| `deploy/hosts/host.env` | Host config (do not commit) |
| `deploy/bootstrap-vps.sh` | First install + gateway smoke test |
| `deploy/smoke-gateway.sh` | End-to-end gateway creation check (callable standalone) |
| `deploy/import-bundled-images.sh` | Import vendored golden image → `local:gw-golden` |
| `deploy/export-gateway-golden.sh` | Export `local:gw-golden` into repo (maintainers) |
| `deploy/assets/incus/` | Golden image + reference OpenWrt base |
| `deploy/update.sh` | git pull + restart |
| `deploy/cloudflare-setup.sh` | DNS + Access (callable standalone) |
| `deploy/setup-headscale-identity.sh` | ACL + gateways/workers/control users |
| `deploy/obtain-tls-cert.sh` | Optional: LE DNS-01 once if `ORIGIN_TLS=letsencrypt` |

## Gateway worker VPS (remote Incus)

The control plane stays on `165.227.156.103`. Gateways can run on separate worker VPS hosts (Incus + Tailscale only).

```bash
cp deploy/hosts/worker.env.example deploy/hosts/worker1.env
# HOST_PUBLIC_IP, WORKER_NAME, CP_DOMAIN
```

### 1. On the CP (one-time)

```bash
cd /opt/deeporc
sudo ./deploy/setup-headscale-policy.sh      # tag worker-host + control-plane
sudo ./deploy/setup-headscale-identity.sh    # workers + control users
sudo ./deploy/setup-cp-tailscale.sh          # CP on the tailnet
sudo ./deploy/headscale-worker-key.sh        # copy auth key
# alembic upgrade head  (workers migration)
sudo ./deploy/update.sh
```

### 2. On the worker VPS (`146.190.232.35`)

```bash
git clone git@github.com:bengnomino/deeporc-worker.git /opt/deeporc-worker
cd /opt/deeporc-worker
cp deploy/hosts/worker.env.example deploy/hosts/worker1.env
# verify HOST_PUBLIC_IP

TAILSCALE_AUTHKEY=tskey-auth-… \
  sudo ./deploy/bootstrap-worker-vps.sh deploy/hosts/worker1.env
```

Worker repo: https://github.com/bengnomino/deeporc-worker

### 3. Register worker from the CP

```bash
# optional SSH for Incus token + automatic heartbeat
WORKER_SSH=root@146.190.232.35 \
  sudo ./deploy/register-worker-on-cp.sh deploy/hosts/worker1.env
```

Without SSH: generate an Incus token on the worker (`incus config trust add control-plane --name control-plane`), then:

```bash
INCUS_TRUST_TOKEN=… sudo ./deploy/register-worker-on-cp.sh deploy/hosts/worker1.env
```

| File | Role |
|------|------|
| `deploy/hosts/worker1.env` | Worker config (do not commit) |
| `deploy/bootstrap-worker-vps.sh` | First worker install |
| `deploy/register-worker-on-cp.sh` | Incus remote + API register |
| `deploy/worker-heartbeat.py` | VPS stats → CP |
| `deploy/update-worker.sh` | Pull bundle from `/packages` (on the worker) |
| `deploy/push-worker-bundle.sh` | From CP: update all workers in `hosts/workers.list` |
| `deploy/hosts/workers.list.example` | SSH target template (`workers.list` gitignored) |

`update.sh` on the CP regenerates the bundle (`host_stats.py`, heartbeat, etc.) and, if `deploy/hosts/workers.list` exists, pushes it via SSH to each worker. The CP must have its SSH key in `authorized_keys` on the workers.
