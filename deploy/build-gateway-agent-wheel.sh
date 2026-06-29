#!/usr/bin/env bash
# Build a minimal gateway-agent-only wheel (no orchestrator bloat).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUT="${1:-$ROOT/dist}"
STAGE="$(mktemp -d)"
trap 'rm -rf "$STAGE"' EXIT

mkdir -p "$OUT" "$STAGE/gateway_agent"
cp "$ROOT/gateway_agent"/*.py "$STAGE/gateway_agent/"

cat >"$STAGE/pyproject.toml" <<'EOF'
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[project]
name = "gateway-agent"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = [
  "fastapi>=0.115.0",
  "uvicorn[standard]>=0.32.0",
  "pydantic-settings>=2.6.0",
]

[tool.hatch.build.targets.wheel]
packages = ["gateway_agent"]
EOF

python3 -m pip wheel "$STAGE" -w "$OUT" --no-deps -q
echo "Built: $OUT/$(ls "$OUT"/gateway_agent-*.whl | xargs basename)"
