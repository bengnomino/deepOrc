"""WireGuard operations via wg command."""

import subprocess
from dataclasses import dataclass
from datetime import UTC, datetime


@dataclass
class PeerInfo:
    public_key: str
    allowed_ips: str
    endpoint: str | None
    last_handshake: datetime | None
    rx_bytes: int
    tx_bytes: int


def _run_wg(args: list[str]) -> str:
    result = subprocess.run(
        ["wg", *args],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "wg command failed")
    return result.stdout


def interface_up(interface: str = "wg0") -> bool:
    try:
        _run_wg(["show", interface])
        return True
    except RuntimeError:
        return False


def add_peer(
    public_key: str,
    allowed_ips: str,
    interface: str = "wg0",
) -> None:
    _run_wg(["set", interface, "peer", public_key, "allowed-ips", allowed_ips])


def remove_peer(public_key: str, interface: str = "wg0") -> None:
    _run_wg(["set", interface, "peer", public_key, "remove"])


def list_peers(interface: str = "wg0") -> list[PeerInfo]:
    try:
        output = _run_wg(["show", interface, "dump"])
    except RuntimeError:
        return []

    peers: list[PeerInfo] = []
    for line in output.strip().splitlines()[1:]:
        parts = line.split("\t")
        if len(parts) < 8:
            continue
        pubkey = parts[0]
        endpoint = parts[2] if parts[2] != "(none)" else None
        allowed_ips = parts[3]
        latest_handshake = int(parts[4])
        rx_bytes = int(parts[5])
        tx_bytes = int(parts[6])
        last_handshake = None
        if latest_handshake > 0:
            last_handshake = datetime.fromtimestamp(latest_handshake, tz=UTC)
        peers.append(
            PeerInfo(
                public_key=pubkey,
                allowed_ips=allowed_ips,
                endpoint=endpoint,
                last_handshake=last_handshake,
                rx_bytes=rx_bytes,
                tx_bytes=tx_bytes,
            )
        )
    return peers


def get_config(interface: str = "wg0") -> str:
    return _run_wg(["showconf", interface])
