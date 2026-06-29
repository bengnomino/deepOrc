# Vendored Incus images

Production deploy imports **only** the pre-built gateway golden image — no remote pulls, no on-host build.

| File | Description |
|------|-------------|
| `gw-golden.tar.gz` | Golden gateway image (Incus export, ~22 MiB) |
| `openwrt-24.10-default.*` | Upstream OpenWrt base (**reference** for rebuilding golden image) |
| `SHA256SUMS` | Checksums |

Import (automatic during bootstrap):

```bash
sudo ./deploy/import-bundled-images.sh
# → local:gw-golden
```

Rebuild golden image (maintainers only):

```bash
IMPORT_OPENWRT_BASE=1 sudo ./deploy/import-bundled-images.sh
sudo ./deploy/build-gateway-agent-go.sh
sudo ./deploy/build-gateway-golden-image.sh
sudo ./deploy/export-gateway-golden.sh
git add deploy/assets/incus/gw-golden.tar.gz
```

Refresh OpenWrt base from upstream (optional, requires network once):

```bash
sudo ./deploy/export-openwrt-base.sh
```
