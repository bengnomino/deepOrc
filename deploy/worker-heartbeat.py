#!/usr/bin/env python3
"""Send host stats heartbeat to the control plane (runs on worker VPS)."""

from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ENV_PATH = Path(os.environ.get("WORKER_ENV_FILE", "/etc/deeporc/worker.env"))
INTERVAL = int(os.environ.get("WORKER_HEARTBEAT_INTERVAL", "30"))


def load_env(path: Path) -> dict[str, str]:
    data: dict[str, str] = {}
    if not path.is_file():
        return data
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        data[key.strip()] = value.strip()
    return data


def collect_stats() -> dict:
    app_dir = os.environ.get("APP_DIR", "/opt/deeporc")
    if Path(app_dir, "orchestrator").is_dir():
        sys.path.insert(0, app_dir)
        from orchestrator.services.host_stats import collect_host_stats

        stats = collect_host_stats()
        return {
            "cpu_percent": stats.cpu_percent,
            "memory_total_mb": stats.memory_total_mb,
            "memory_used_mb": stats.memory_used_mb,
            "memory_percent": stats.memory_percent,
            "network_rx_bytes_per_sec": stats.network_rx_bytes_per_sec,
            "network_tx_bytes_per_sec": stats.network_tx_bytes_per_sec,
        }
    raise RuntimeError("APP_DIR orchestrator not found — copy repo to /opt/deeporc")


def post_heartbeat(api_url: str, worker_id: str, token: str, payload: dict) -> None:
    url = f"{api_url.rstrip('/')}/workers/{worker_id}/heartbeat"
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {token}",
        },
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        if resp.status not in (200, 204):
            raise RuntimeError(f"heartbeat HTTP {resp.status}")


def main() -> int:
    env = {**load_env(ENV_PATH), **os.environ}
    worker_id = env.get("WORKER_ID", "")
    token = env.get("WORKER_TOKEN", "")
    api_url = env.get("CP_API_URL", "")
    if not worker_id or not token or not api_url:
        print("WORKER_ID, WORKER_TOKEN, CP_API_URL required in worker env", file=sys.stderr)
        return 1

    while True:
        try:
            payload = collect_stats()
            post_heartbeat(api_url, worker_id, token, payload)
        except (urllib.error.URLError, OSError, RuntimeError) as exc:
            print(f"heartbeat failed: {exc}", file=sys.stderr)
        time.sleep(INTERVAL)


if __name__ == "__main__":
    raise SystemExit(main())
