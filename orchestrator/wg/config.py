"""WireGuard configuration rendering."""

from dataclasses import dataclass


@dataclass(frozen=True)
class ServerConfigParams:
    private_key: str
    listen_port: int
    address: str
    subnet: str


@dataclass(frozen=True)
class ClientConfigParams:
    private_key: str
    address: str
    dns: str
    server_public_key: str
    endpoint: str
    allowed_ips: str
    persistent_keepalive: int = 25


def render_server_config(params: ServerConfigParams) -> str:
    return f"""[Interface]
PrivateKey = {params.private_key}
Address = {params.address}/24
ListenPort = {params.listen_port}

# Peers added dynamically via gateway agent
"""


def render_client_config(params: ClientConfigParams) -> str:
    return f"""[Interface]
PrivateKey = {params.private_key}
Address = {params.address}/32
DNS = {params.dns}
MTU = 1280

[Peer]
PublicKey = {params.server_public_key}
Endpoint = {params.endpoint}
AllowedIPs = {params.allowed_ips}
PersistentKeepalive = {params.persistent_keepalive}
"""
