#!/usr/bin/env bash
# Build static gateway-agent binary for Linux amd64 (OpenWrt/Alpine containers).
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUT="${1:-$ROOT/dist}"
mkdir -p "$OUT"
CGO_ENABLED=0 GOOS=linux GOARCH=amd64 go build -C "$ROOT/cmd/gateway-agent" -ldflags='-s -w' -o "$OUT/gateway-agent" .
ls -lh "$OUT/gateway-agent"
