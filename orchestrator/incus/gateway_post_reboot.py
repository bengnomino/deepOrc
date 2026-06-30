"""Sync routing scripts and bring Tailscale back after a gateway VM reboot."""

from __future__ import annotations

import logging
import subprocess
import time
from pathlib import Path

from orchestrator.incus.setup import push_file, wait_for_instance

logger = logging.getLogger(__name__)

_REPO_ROOT = Path(__file__).resolve().parents[2]
_FRAGMENTS = _REPO_ROOT / "orchestrator" / "cloudinit" / "templates" / "_fragments"
_OPENWRT = _REPO_ROOT / "deploy" / "openwrt"


def _incus_exec(instance: str, *args: str, timeout: int = 60) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["incus", "exec", instance, "--", *args],
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )


def _tailscale_running(instance: str) -> bool:
    result = _incus_exec(
        instance,
        "/usr/sbin/tailscale",
        "status",
        "--json",
        timeout=20,
    )
    return result.returncode == 0 and '"BackendState": "Running"' in result.stdout


def _wait_for_tailscale(instance: str, *, timeout: int = 120) -> None:
    deadline = time.time() + timeout
    last_error = ""
    while time.time() < deadline:
        if _tailscale_running(instance):
            return
        log = _incus_exec(instance, "cat", "/tmp/deeporc-tailscale-up.log", timeout=10)
        last_error = (log.stdout or log.stderr or "tailscale not running").strip()
        time.sleep(3)
    raise RuntimeError(last_error or "tailscale did not come online after reboot")


def apply_gateway_post_reboot(instance_target: str, *, boot_timeout: int = 120) -> None:
    """Push latest boot scripts, login Tailscale, then apply exit routing."""
    wait_for_instance(instance_target, timeout=boot_timeout)

    push_file(
        instance_target,
        "/opt/gateway-agent/deeporc-routing.sh",
        (_FRAGMENTS / "deeporc-routing.sh").read_text(encoding="utf-8"),
    )
    push_file(
        instance_target,
        "/opt/gateway-agent/wg-up.sh",
        (_OPENWRT / "wg-up.sh").read_text(encoding="utf-8"),
    )
    push_file(
        instance_target,
        "/etc/init.d/tailscale",
        (_OPENWRT / "tailscale-up.init").read_text(encoding="utf-8"),
        mode="0755",
    )

    for i in range(1, 31):
        if _incus_exec(instance_target, "ip", "link", "show", "wg0", timeout=10).returncode == 0:
            break
        time.sleep(2)

    bootstrap = _incus_exec(
        instance_target,
        "/opt/gateway-agent/deeporc-routing.sh",
        "bootstrap",
        timeout=30,
    )
    if bootstrap.returncode != 0:
        detail = (bootstrap.stderr or bootstrap.stdout or "routing bootstrap failed").strip()
        raise RuntimeError(detail)

    _incus_exec(
        instance_target,
        "sh",
        "-c",
        "/etc/init.d/tailscale start >/tmp/deeporc-tailscale-up.log 2>&1 &",
        timeout=15,
    )
    _wait_for_tailscale(instance_target)

    result = _incus_exec(
        instance_target,
        "/opt/gateway-agent/deeporc-routing.sh",
        "apply",
        timeout=90,
    )
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "deeporc-routing apply failed").strip()
        raise RuntimeError(detail)

    logger.info("Gateway %s recovered after reboot", instance_target)
