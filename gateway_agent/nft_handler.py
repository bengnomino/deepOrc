"""nftables suspend/resume for peer IPs."""

import subprocess

from gateway_agent.config import get_agent_settings


def _run_nft(args: list[str]) -> None:
    result = subprocess.run(["nft", *args], capture_output=True, text=True, check=False)
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "nft command failed")


def ensure_suspend_table() -> None:
    settings = get_agent_settings()
    table = settings.nft_suspend_table
    _run_nft(["add", "table", *table.split()])
    _run_nft(
        [
            "add",
            "chain",
            *table.split(),
            "forward",
            "{",
            "type",
            "filter",
            "hook",
            "forward",
            "priority",
            "filter",
            ";",
            "policy",
            "accept",
            ";",
            "}",
        ]
    )


def suspend_peer_ip(peer_ip: str) -> None:
    ensure_suspend_table()
    settings = get_agent_settings()
    table = settings.nft_suspend_table
    rule = f"ip daddr {peer_ip} drop"
    try:
        _run_nft(["add", "rule", *table.split(), "forward", rule])
    except RuntimeError:
        pass


def resume_peer_ip(peer_ip: str) -> None:
    settings = get_agent_settings()
    table = settings.nft_suspend_table
    result = subprocess.run(
        ["nft", "-a", "list", "chain", *table.split(), "forward"],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return
    for line in result.stdout.splitlines():
        if peer_ip in line and "drop" in line:
            handle = line.strip().split()[-1]
            _run_nft(["delete", "rule", *table.split(), "forward", "handle", handle])
