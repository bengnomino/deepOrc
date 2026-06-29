"""Add Incus remotes for gateway workers on the control plane."""

import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path


class IncusRemoteError(RuntimeError):
    pass


@dataclass(frozen=True)
class IncusRemotePaths:
    cert_path: str
    key_path: str
    server_cert_path: str | None


def _incus_conf_dir() -> Path:
    return Path(os.environ.get("HOME", "/root")) / ".config" / "incus"


def _copy_remote_certs(remote_name: str, data_dir: Path) -> IncusRemotePaths:
    cert_dir = data_dir / "incus" / remote_name
    cert_dir.mkdir(parents=True, exist_ok=True)

    incus_conf = _incus_conf_dir()
    client_cert = incus_conf / "client.crt"
    client_key = incus_conf / "client.key"
    if not client_cert.is_file() or not client_key.is_file():
        raise IncusRemoteError(f"Missing Incus client certs in {incus_conf}")

    dest_cert = cert_dir / "client.crt"
    dest_key = cert_dir / "client.key"
    shutil.copy2(client_cert, dest_cert)
    shutil.copy2(client_key, dest_key)
    dest_cert.chmod(0o600)
    dest_key.chmod(0o600)

    server_cert_path: str | None = None
    named_server = incus_conf / "servercerts" / f"{remote_name}.crt"
    if named_server.is_file():
        dest_server = cert_dir / "server.crt"
        shutil.copy2(named_server, dest_server)
        dest_server.chmod(0o644)
        server_cert_path = str(dest_server)
    else:
        server_dir = incus_conf / "servercerts"
        if server_dir.is_dir():
            candidates = sorted(
                server_dir.glob("*.crt"),
                key=lambda path: path.stat().st_mtime,
                reverse=True,
            )
            if candidates:
                dest_server = cert_dir / "server.crt"
                shutil.copy2(candidates[0], dest_server)
                dest_server.chmod(0o644)
                server_cert_path = str(dest_server)

    return IncusRemotePaths(
        cert_path=str(dest_cert),
        key_path=str(dest_key),
        server_cert_path=server_cert_path,
    )


def ensure_worker_remote_certs(remote_name: str, data_dir: Path) -> IncusRemotePaths:
    """Re-copy Incus mTLS certs into data_dir when missing (e.g. after manual data cleanup)."""
    cert_dir = data_dir / "incus" / remote_name
    dest_cert = cert_dir / "client.crt"
    dest_key = cert_dir / "client.key"
    if dest_cert.is_file() and dest_key.is_file():
        server_cert_path: str | None = None
        dest_server = cert_dir / "server.crt"
        if dest_server.is_file():
            server_cert_path = str(dest_server)
        return IncusRemotePaths(
            cert_path=str(dest_cert),
            key_path=str(dest_key),
            server_cert_path=server_cert_path,
        )
    return _copy_remote_certs(remote_name, data_dir)


def add_worker_remote(
    remote_name: str,
    incus_url: str,
    trust_token: str,
    data_dir: Path,
) -> IncusRemotePaths:
    cert_dir = data_dir / "incus" / remote_name
    cert_dir.mkdir(parents=True, exist_ok=True)

    subprocess.run(
        ["incus", "remote", "remove", remote_name],
        capture_output=True,
        text=True,
        check=False,
    )
    result = subprocess.run(
        [
            "incus",
            "remote",
            "add",
            remote_name,
            incus_url,
            f"--token={trust_token}",
            "--accept-certificate",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip() or "incus remote add failed"
        raise IncusRemoteError(detail)

    return _copy_remote_certs(remote_name, data_dir)
