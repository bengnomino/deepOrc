# Deploy su VPS (production-ready, fresh install)

Installazione completa su Debian 13+: Incus, Headscale (ACL + utente `gateways`), Caddy, orchestrator.

**Non migrare** database da altre VPS: ogni host parte pulito.

## Configurazione minima

```bash
cp deploy/hosts/host.env.example deploy/hosts/host.env
```

Modifica:

| Variabile | Obbligatoria | Descrizione |
|-----------|--------------|-------------|
| `BASE_DOMAIN` | sì | zona DNS apex (es. `harlock.network`) — cert LE: `BASE_DOMAIN` + `*.BASE_DOMAIN` |
| `SERVICE_HOST` | sì* | label sottodominio (es. `deeporc`) → URL `deeporc.harlock.network` |
| `CLOUDFLARE_API_TOKEN` | no | DNS A record + Zero Trust Access |
| `CLOUDFLARE_ACCESS_EMAIL` | sì (con token) | email ammessa da Cloudflare Access |
| `CLOUDFLARE_ACCESS_SKIP` | no | `1` solo se Access è già sul dashboard CF |

\* ometti `SERVICE_HOST` se il servizio è sull'apex (`BASE_DOMAIN` = URL pubblico)

Tutto il resto è automatico:
- `DOMAIN` — `${SERVICE_HOST}.${BASE_DOMAIN}` (derivato, non impostarlo a mano)
- `HOST_PUBLIC_IP` — rilevato via ipify
- `WG_PUBLIC_HOST` — uguale a `HOST_PUBLIC_IP` (WireGuard non passa da Cloudflare)
- `HEADSCALE_BASE_DOMAIN` — `ts.${BASE_DOMAIN}` (solo MagicDNS tailnet)
- `SECRET_KEY`, `API_KEY` — generati al bootstrap
- Headscale **0.29.1** (fresh): policy ACL + utente `gateways` (no migrazione DB)

### Headscale 0.29

- Minimo client Tailscale: **v1.80.0**
- ACL `*` = solo tailnet (non Internet); la nostra policy resta valida
- `randomizeClientPort` va nel file policy (già incluso)
- Registrazione mobile usa `headscale auth register` (fallback su `nodes register`)

## Primo deploy

```bash
# sulla VPS (root)
git clone git@github.com:bengnomino/deeporc.git /opt/deeporc
cd /opt/deeporc
cp deploy/hosts/host.env.example deploy/hosts/host.env
# edita DOMAIN (+ Cloudflare se usi CF)
sudo ./deploy/bootstrap-vps.sh deploy/hosts/host.env
```

Al termine lo script:
- stampa **API key** e URL UI
- aggiorna `host.env` con i segreti generati
- importa l'immagine **`local:gw-golden`** vendored in repo (nessun build on-host)
- esegue **smoke test gateway** (crea, attende `ready`, elimina)

Per saltare lo smoke test: `SKIP_SMOKE_GATEWAY=1 sudo ./deploy/bootstrap-vps.sh ...`

Se vedi `Smoke test passed: gateway smoke-gw is ready` → deploy one-shot OK.

### Cloudflare

Con token configurato, lo script:
1. Crea/aggiorna record **A** per `DOMAIN` con **proxy Cloudflare attivo** (`proxied=true`, default)
2. Se `CLOUDFLARE_ACCESS_EMAIL` è impostata, crea app Zero Trust su `/orchestrator/*` e `/register/*`

`HEADSCALE_BASE_DOMAIN` (es. `ts.harlock.network`) è solo MagicDNS tailnet — **nessun record DNS pubblico**.

**WireGuard:** i client usano `HOST_PUBLIC_IP` e la porta UDP dal pool (`51001–52000`), non il dominio.

nftables apre **8080/8000** solo da `10.10.0.0/16` (gateway → Headscale/orchestrator sul host). Regole in `deploy/nftables/control-plane.nft`.

**RAM attesa (VPS idle, nessun gateway):** ~280–320 MiB RSS (Incus ~80, orchestrator ~100, Headscale ~55, Caddy ~45). I ~650 MiB che vedi subito dopo bootstrap erano soprattutto **cache apt/pip** (~500 MiB) — `bootstrap-cleanup.sh` le libera a fine install. Ogni gateway OpenWrt aggiunge ~128 MiB (limite Incus configurabile con `INCUS_VM_MEMORY`).

Per disabilitare il proxy: `CLOUDFLARE_DNS_PROXIED=false` in `host.env`.

Permessi token consigliati: **Zone → DNS → Edit**, **Account → Access → Apps and Policies → Edit**.

SSL origine: con **Cloudflare proxied + Full (strict)** serve certificato valido sulla VPS. Con token CF, bootstrap esegue **certbot una sola volta** per `BASE_DOMAIN` + `*.BASE_DOMAIN` (es. `harlock.network` + `*.harlock.network`) → `/etc/caddy/ssl/`. Il certificato **non** viene richiesto per il sottodominio del servizio. Imposta `ORIGIN_TLS=internal` solo se CF è **Full** (non Strict).

```bash
cd /opt/deeporc
sudo ./deploy/update.sh main deploy/hosts/host.env
```

## File

| File | Ruolo |
|------|--------|
| `deploy/hosts/host.env` | Config host (non committare) |
| `deploy/bootstrap-vps.sh` | Primo install + smoke test gateway |
| `deploy/smoke-gateway.sh` | Verifica end-to-end creazione gateway (richiamabile da solo) |
| `deploy/import-bundled-images.sh` | Import golden image vendored → `local:gw-golden` |
| `deploy/export-gateway-golden.sh` | Esporta `local:gw-golden` in repo (maintainers) |
| `deploy/assets/incus/` | Golden image + OpenWrt base di riferimento |
| `deploy/update.sh` | git pull + restart |
| `deploy/cloudflare-setup.sh` | DNS + Access (richiamabile da solo) |
| `deploy/setup-headscale-identity.sh` | ACL + utenti gateways/workers/control |
| `deploy/obtain-tls-cert.sh` | Opzionale: LE DNS-01 una volta se `ORIGIN_TLS=letsencrypt` |

## Gateway worker VPS (Incus remoto)

Il control plane resta su `165.227.156.103`. I gateway possono girare su VPS worker separate (solo Incus + Tailscale).

```bash
cp deploy/hosts/worker.env.example deploy/hosts/worker1.env
# HOST_PUBLIC_IP, WORKER_NAME, CP_DOMAIN
```

### 1. Sul CP (una tantum)

```bash
cd /opt/deeporc
sudo ./deploy/setup-headscale-policy.sh      # tag worker-host + control-plane
sudo ./deploy/setup-headscale-identity.sh    # utenti workers + control
sudo ./deploy/setup-cp-tailscale.sh          # CP sulla tailnet
sudo ./deploy/headscale-worker-key.sh        # copia auth key
# alembic upgrade head  (migration workers)
sudo ./deploy/update.sh
```

### 2. Sulla worker VPS (`146.190.232.35`)

```bash
git clone git@github.com:bengnomino/deeporc-worker.git /opt/deeporc-worker
cd /opt/deeporc-worker
cp deploy/hosts/worker.env.example deploy/hosts/worker1.env
# verifica HOST_PUBLIC_IP

TAILSCALE_AUTHKEY=tskey-auth-… \
  sudo ./deploy/bootstrap-worker-vps.sh deploy/hosts/worker1.env
```

Repo worker: https://github.com/bengnomino/deeporc-worker

### 3. Registra worker dal CP

```bash
# opzionale SSH per token Incus + heartbeat automatico
WORKER_SSH=root@146.190.232.35 \
  sudo ./deploy/register-worker-on-cp.sh deploy/hosts/worker1.env
```

Senza SSH: genera token Incus sulla worker (`incus config trust add control-plane --name control-plane`), poi:

```bash
INCUS_TRUST_TOKEN=… sudo ./deploy/register-worker-on-cp.sh deploy/hosts/worker1.env
```

| File | Ruolo |
|------|--------|
| `deploy/hosts/worker1.env` | Config worker (non committare) |
| `deploy/bootstrap-worker-vps.sh` | Primo install worker |
| `deploy/register-worker-on-cp.sh` | Incus remote + API register |
| `deploy/worker-heartbeat.py` | Stats VPS → CP |
| `deploy/update-worker.sh` | Pull bundle da `/packages` (sulla worker) |
| `deploy/push-worker-bundle.sh` | Dal CP: aggiorna tutte le worker in `hosts/workers.list` |
| `deploy/hosts/workers.list.example` | Template SSH target worker (`workers.list` gitignored) |

`update.sh` sul CP rigenera il bundle (`host_stats.py`, heartbeat, ecc.) e, se esiste `deploy/hosts/workers.list`, lo pusha via SSH su ogni worker. Il CP deve avere la propria chiave SSH in `authorized_keys` sulle worker.
