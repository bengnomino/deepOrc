"""Gateway agent FastAPI application."""

from contextlib import asynccontextmanager
from typing import Annotated

from fastapi import Depends, FastAPI, Header, HTTPException, status
from pydantic import BaseModel, Field

from gateway_agent.config import AgentSettings, get_agent_settings
from gateway_agent.health import collect_health, fetch_egress_public_ip, tailscale_status_text
from gateway_agent.nft_handler import resume_peer_ip, suspend_peer_ip
from gateway_agent.tailscale_handler import advertise_exit_node, restore_exit_node_routing, set_tailscale_hostname
from gateway_agent.wg_handler import add_peer, get_config, list_peers, remove_peer


class PeerCreate(BaseModel):
    public_key: str
    allowed_ips: str


class PeerResponse(BaseModel):
    public_key: str
    allowed_ips: str
    endpoint: str | None = None
    last_handshake: str | None = None
    rx_bytes: int = 0
    tx_bytes: int = 0


class HealthResponse(BaseModel):
    wg_online: bool
    tailscale_online: bool
    nft_running: bool
    exit_node_configured: bool


class EgressPublicIpResponse(BaseModel):
    ip: str


class TailscaleStatusResponse(BaseModel):
    status: str


class RegisterRequest(BaseModel):
    gateway_name: str = Field(min_length=1, max_length=128)


class TailscaleHostnameUpdate(BaseModel):
    hostname: str = Field(min_length=1, max_length=128)


class ExitNodeUpdate(BaseModel):
    exit_node_id: str = ""


_registered = False


def verify_token(
    authorization: Annotated[str | None, Header()] = None,
    settings: AgentSettings = Depends(get_agent_settings),
) -> None:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing token")
    token = authorization.removeprefix("Bearer ").strip()
    if token != settings.agent_token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")


@asynccontextmanager
async def lifespan(app: FastAPI):
    restore_exit_node_routing()
    yield


def create_app() -> FastAPI:
    settings = get_agent_settings()
    app = FastAPI(title="Gateway Agent", version="0.1.0", lifespan=lifespan)

    @app.post("/v1/register")
    def register(body: RegisterRequest, _: None = Depends(verify_token)) -> dict[str, str]:
        global _registered
        _registered = True
        return {"status": "registered", "gateway_name": body.gateway_name}

    @app.get("/v1/health", response_model=HealthResponse)
    def health(_: None = Depends(verify_token)) -> HealthResponse:
        h = collect_health(settings.wg_interface)
        return HealthResponse(
            wg_online=h.wg_online,
            tailscale_online=h.tailscale_online,
            nft_running=h.nft_running,
            exit_node_configured=h.exit_node_configured,
        )

    @app.post("/v1/peers")
    def create_peer(body: PeerCreate, _: None = Depends(verify_token)) -> dict[str, str]:
        add_peer(body.public_key, body.allowed_ips, settings.wg_interface)
        return {"status": "created", "public_key": body.public_key}

    @app.delete("/v1/peers/{public_key}")
    def delete_peer(public_key: str, _: None = Depends(verify_token)) -> dict[str, str]:
        remove_peer(public_key, settings.wg_interface)
        return {"status": "deleted", "public_key": public_key}

    @app.post("/v1/peers/{public_key}/suspend")
    def suspend(public_key: str, allowed_ip: str, _: None = Depends(verify_token)) -> dict[str, str]:
        ip = allowed_ip.split("/")[0]
        suspend_peer_ip(ip)
        return {"status": "suspended", "public_key": public_key}

    @app.post("/v1/peers/{public_key}/resume")
    def resume(public_key: str, allowed_ip: str, _: None = Depends(verify_token)) -> dict[str, str]:
        ip = allowed_ip.split("/")[0]
        resume_peer_ip(ip)
        return {"status": "resumed", "public_key": public_key}

    @app.get("/v1/peers", response_model=list[PeerResponse])
    def get_peers(_: None = Depends(verify_token)) -> list[PeerResponse]:
        return [
            PeerResponse(
                public_key=p.public_key,
                allowed_ips=p.allowed_ips,
                endpoint=p.endpoint,
                last_handshake=p.last_handshake.isoformat() if p.last_handshake else None,
                rx_bytes=p.rx_bytes,
                tx_bytes=p.tx_bytes,
            )
            for p in list_peers(settings.wg_interface)
        ]

    @app.get("/v1/wg/config")
    def wg_config(_: None = Depends(verify_token)) -> dict[str, str]:
        return {"config": get_config(settings.wg_interface)}

    @app.get("/v1/egress/public-ip", response_model=EgressPublicIpResponse)
    def egress_public_ip(_: None = Depends(verify_token)) -> EgressPublicIpResponse:
        try:
            return EgressPublicIpResponse(ip=fetch_egress_public_ip())
        except RuntimeError as exc:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=str(exc),
            ) from exc

    @app.get("/v1/tailscale/status", response_model=TailscaleStatusResponse)
    def tailscale_status(_: None = Depends(verify_token)) -> TailscaleStatusResponse:
        try:
            return TailscaleStatusResponse(status=tailscale_status_text())
        except RuntimeError as exc:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=str(exc),
            ) from exc

    @app.post("/v1/tailscale/hostname")
    def update_tailscale_hostname(
        body: TailscaleHostnameUpdate, _: None = Depends(verify_token)
    ) -> dict[str, str]:
        set_tailscale_hostname(body.hostname.strip().lower())
        return {"status": "updated", "hostname": body.hostname.strip().lower()}

    @app.post("/v1/tailscale/advertise-exit")
    def advertise_exit(_: None = Depends(verify_token)) -> dict[str, str]:
        advertise_exit_node()
        return {"status": "advertised"}

    @app.post("/v1/tailscale/exit-node")
    def update_exit_node(body: ExitNodeUpdate, _: None = Depends(verify_token)) -> dict[str, str]:
        if body.exit_node_id.strip():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="deepOrc gateways advertise their own exit node; external assignment is disabled",
            )
        advertise_exit_node()
        return {"status": "advertised"}

    return app


app = create_app()


def cli() -> None:
    import uvicorn

    settings = get_agent_settings()
    uvicorn.run(
        "gateway_agent.main:app",
        host=settings.listen_host,
        port=settings.listen_port,
        reload=False,
    )


if __name__ == "__main__":
    cli()
