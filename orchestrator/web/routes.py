"""Web UI routes — auth via Cloudflare Access (external)."""

import io
import json
import logging
import zipfile
from pathlib import Path
from urllib.parse import quote

from fastapi import APIRouter, BackgroundTasks, Form, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, PlainTextResponse, RedirectResponse, Response

from orchestrator.api.deps import DbSession
from orchestrator.config import get_settings
from orchestrator.headscale import HeadscaleError, list_exit_nodes
from orchestrator.models.job import JobStatus
from orchestrator.repositories.gateway_repo import GatewayRepository
from orchestrator.repositories.job_repo import JobRepository
from orchestrator.repositories.metrics_repo import MetricsRepository
from orchestrator.repositories.peer_repo import PeerRepository
from orchestrator.services.gateway_service import CreateGatewayRequest, GatewayService
from orchestrator.services.peer_service import PeerService
from orchestrator.services.worker_service import WorkerService
from orchestrator.web.views import (
    peer_is_online,
    sort_peers_by_connectivity,
    worker_host_label,
)
from orchestrator.web.templating import templates
from orchestrator.workers.provisioning import schedule_provisioning_after_request

logger = logging.getLogger(__name__)

WEB_DIR = Path(__file__).parent


def _gateway_detail_url(
    gateway_id: int,
    *,
    error: str | None = None,
    ok: str | None = None,
) -> str:
    base = f"/orchestrator/ui/gateways/{gateway_id}"
    params: list[str] = []
    if error:
        params.append(f"error={quote(error)}")
    if ok:
        params.append(f"ok={quote(ok)}")
    if not params:
        return base
    return f"{base}?{'&'.join(params)}"

router = APIRouter(tags=["webui"])

DEPLOY_DIR = Path(__file__).resolve().parents[2] / "deploy"


def _maybe_enqueue_provisioning(
    gateway_id: int,
    session: DbSession,
    background_tasks: BackgroundTasks,
) -> None:
    from orchestrator.models.gateway import GatewayStatus

    service = GatewayService(session)
    gateway = GatewayRepository(session).get_by_id(gateway_id)
    if not gateway or not service.needs_provisioning(gateway):
        return
    job = JobRepository(session).get_latest_create_job(gateway_id)
    if not job or job.status == JobStatus.FAILED or gateway.status == GatewayStatus.ERROR:
        try:
            service.prepare_provisioning(gateway_id)
        except ValueError:
            return
        job = JobRepository(session).get_pending_for_gateway(gateway_id)
    elif job.status == JobStatus.RUNNING:
        service.prepare_provisioning(gateway_id)
        job = JobRepository(session).get_pending_for_gateway(gateway_id)
    if job and job.status == JobStatus.PENDING:
        schedule_provisioning_after_request(background_tasks, gateway_id, job.id)


def _gateway_row(
    gateway,
    *,
    gs: GatewayService,
    metrics_repo: MetricsRepository,
    peers_repo: PeerRepository,
    exit_nodes_by_ip: dict,
) -> dict:
    metric = metrics_repo.latest_gateway_metric(gateway.id)
    peers = peers_repo.list_by_gateway(gateway.id)
    peer_metrics = {peer.id: metrics_repo.latest_peer_metric(peer.id) for peer in peers}
    peer_online = sum(
        1 for peer in peers if peer_is_online(peer, peer_metrics.get(peer.id))
    )
    exit_node = exit_nodes_by_ip.get(gateway.exit_node_id)
    return {
        "gateway": gateway,
        "endpoint": gs.get_endpoint(gateway),
        "tailscale_online": metric.tailscale_online if metric else None,
        "wg_online": metric.wg_online if metric else None,
        "exit_node": exit_node,
        "peer_total": len(peers),
        "peer_online": peer_online,
    }


def _dashboard_workers(session: DbSession) -> tuple[list[dict], str | None]:
    gateways = GatewayRepository(session).list_all()
    metrics_repo = MetricsRepository(session)
    peers_repo = PeerRepository(session)
    gs = GatewayService(session)
    worker_service = WorkerService(session)

    headscale_error = None
    try:
        hs_nodes = list_exit_nodes()
        exit_nodes_by_ip = {node.tailscale_ip: node for node in hs_nodes}
    except HeadscaleError as exc:
        exit_nodes_by_ip = {}
        headscale_error = f"Impossibile leggere exit node da Headscale: {exc}"

    sections = []
    for row in worker_service.dashboard_workers():
        gateway_rows = [
            _gateway_row(
                gateway,
                gs=gs,
                metrics_repo=metrics_repo,
                peers_repo=peers_repo,
                exit_nodes_by_ip=exit_nodes_by_ip,
            )
            for gateway in gateways
            if gateway.worker_id == row["worker"].id
        ]
        sections.append(
            {
                "worker": row["worker"],
                "status": row["status"],
                "gateways": gateway_rows,
            }
        )
    return sections, headscale_error


def _worker_choices(session: DbSession) -> list[dict]:
    service = WorkerService(session)
    choices = []
    for row in service.dashboard_workers():
        worker = row["worker"]
        choices.append(
            {
                "id": worker.id,
                "display_name": worker.display_name,
                "host_label": worker_host_label(worker),
                "online": row["status"].value == "online",
                "status": row["status"].value,
            }
        )
    return choices


def _pending_registrations(session: DbSession) -> list:
    return []


@router.get("", response_class=HTMLResponse)
def dashboard(request: Request, session: DbSession, error: str | None = None) -> HTMLResponse:
    workers, headscale_error = _dashboard_workers(session)
    return templates.TemplateResponse(
        request,
        "dashboard.html",
        {
            "workers": workers,
            "worker_choices": _worker_choices(session),
            "worker_choices_json": json.dumps(_worker_choices(session)),
            "headscale_error": headscale_error,
            "flash_error": error,
            "login_server": get_settings().headscale_url,
            "title": "Dashboard",
        },
    )


@router.get("/gateways/new")
def new_gateway_redirect() -> RedirectResponse:
    return RedirectResponse(url="/orchestrator/ui", status_code=303)


@router.get("/workers/stats")
def worker_stats(session: DbSession) -> JSONResponse:
    service = WorkerService(session)
    payload = []
    for row in service.dashboard_workers():
        worker = row["worker"]
        payload.append(
            {
                "id": worker.id,
                "status": row["status"].value,
                "cpu_percent": worker.cpu_percent,
                "memory_total_mb": worker.memory_total_mb,
                "memory_used_mb": worker.memory_used_mb,
                "memory_percent": worker.memory_percent,
                "network_rx_bytes_per_sec": worker.network_rx_bps,
                "network_tx_bytes_per_sec": worker.network_tx_bps,
            }
        )
    return JSONResponse(payload)


@router.get("/workers/join.sh")
def worker_join_script() -> FileResponse:
    script = DEPLOY_DIR / "join-worker.sh"
    if not script.is_file():
        raise HTTPException(status_code=404, detail="Join script not found")
    return FileResponse(script, media_type="text/x-shellscript", filename="join-worker.sh")


@router.post("/workers/enroll")
def create_worker_enrollment(session: DbSession) -> JSONResponse:
    service = WorkerService(session)
    try:
        result = service.create_enrollment()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return JSONResponse(
        {
            "name": result.name,
            "display_name": result.display_name,
            "tailscale_hostname": result.tailscale_hostname,
            "tailscale_auth_key": result.tailscale_auth_key,
            "command": result.command,
        }
    )


def _start_gateway_creation(
    session: DbSession,
    background_tasks: BackgroundTasks,
    worker_id: int,
) -> RedirectResponse:
    service = GatewayService(session)
    try:
        result = service.create_gateway(CreateGatewayRequest(worker_id=worker_id))
    except ValueError as exc:
        return RedirectResponse(
            url=f"/orchestrator/ui?error={quote(str(exc))}",
            status_code=303,
        )
    schedule_provisioning_after_request(
        background_tasks, result.gateway.id, result.job.id
    )
    return RedirectResponse(url=f"/orchestrator/ui/gateways/{result.gateway.id}", status_code=303)


@router.get("/workers/{worker_id}/create-gateway")
def create_gateway_for_worker_ui(
    worker_id: int,
    session: DbSession,
    background_tasks: BackgroundTasks,
) -> RedirectResponse:
    return _start_gateway_creation(session, background_tasks, worker_id)


@router.post("/gateways/create")
def create_gateway_ui(
    session: DbSession,
    background_tasks: BackgroundTasks,
    worker_id: int = Form(...),
) -> RedirectResponse:
    return _start_gateway_creation(session, background_tasks, worker_id)


@router.get("/gateways/{gateway_id}", response_class=HTMLResponse)
def gateway_detail(
    request: Request,
    gateway_id: int,
    session: DbSession,
    error: str | None = None,
    ok: str | None = None,
) -> HTMLResponse:
    import ipaddress

    from orchestrator.models.gateway import GatewayStatus

    repo = GatewayRepository(session)
    gateway = repo.get_by_id(gateway_id)
    if not gateway:
        return RedirectResponse(url="/orchestrator/ui", status_code=303)
    if gateway.status == GatewayStatus.READY:
        try:
            PeerService(session).ensure_backhaul_peer(gateway_id)
        except Exception:
            session.rollback()
    gs = GatewayService(session)
    headscale_error = None
    exit_node = None
    try:
        for node in list_exit_nodes():
            if node.tailscale_ip == gateway.exit_node_id or node.hostname == gateway.name:
                exit_node = node
                break
    except HeadscaleError as exc:
        headscale_error = str(exc)
    peers = PeerRepository(session).list_by_gateway(gateway_id)
    metrics_repo = MetricsRepository(session)
    peer_metrics = {peer.id: metrics_repo.latest_peer_metric(peer.id) for peer in peers}
    sorted_peers = sort_peers_by_connectivity(peers, peer_metrics)
    peers_online = [row for row in sorted_peers if row["online"]]
    peers_offline = [row for row in sorted_peers if not row["online"]]
    metrics = metrics_repo.latest_gateway_metric(gateway_id)
    wg_gateway_ip = str(ipaddress.ip_network(gateway.wg_subnet).network_address + 1)
    provision_job = JobRepository(session).get_latest_create_job(gateway_id)
    from orchestrator.workers.provisioning_stages import format_provision_progress

    provision_progress = format_provision_progress(provision_job)
    return templates.TemplateResponse(
        request,
        "gateway_detail.html",
        {
            "title": gateway.name,
            "gateway": gateway,
            "endpoint": gs.get_endpoint(gateway),
            "wg_gateway_ip": wg_gateway_ip,
            "exit_node": exit_node,
            "headscale_error": headscale_error,
            "peers_online": peers_online,
            "peers_offline": peers_offline,
            "metrics": metrics,
            "provision_progress": provision_progress,
            "flash_error": error,
            "flash_ok": ok,
        },
    )


@router.post("/gateways/{gateway_id}/retry")
def retry_gateway_ui(
    gateway_id: int,
    session: DbSession,
    background_tasks: BackgroundTasks,
) -> RedirectResponse:
    _maybe_enqueue_provisioning(gateway_id, session, background_tasks)
    return RedirectResponse(url=f"/orchestrator/ui/gateways/{gateway_id}", status_code=303)


@router.post("/gateways/{gateway_id}/delete")
def delete_gateway_ui(
    gateway_id: int,
    session: DbSession,
    background_tasks: BackgroundTasks,
) -> RedirectResponse:
    from orchestrator.workers.deletion import schedule_deletion_after_request

    try:
        job = GatewayService(session).request_delete_gateway(gateway_id)
        schedule_deletion_after_request(background_tasks, gateway_id, job.id)
    except ValueError:
        pass
    return RedirectResponse(url="/orchestrator/ui", status_code=303)


@router.post("/gateways/{gateway_id}/peers")
def create_peer_ui(
    gateway_id: int,
    session: DbSession,
    peer_name: str = Form(""),
) -> RedirectResponse:
    service = PeerService(session)
    try:
        name = peer_name.strip() or service.next_peer_name(gateway_id)
        result = service.create_peer(gateway_id, name)
        return RedirectResponse(
            url=_gateway_detail_url(gateway_id, ok=f"Peer {result.peer.name} creato"),
            status_code=303,
        )
    except ValueError as exc:
        session.rollback()
        return RedirectResponse(
            url=_gateway_detail_url(gateway_id, error=str(exc)),
            status_code=303,
        )
    except Exception as exc:
        session.rollback()
        logger.exception("Peer creation failed for gateway %s", gateway_id)
        return RedirectResponse(
            url=_gateway_detail_url(gateway_id, error=str(exc) or "Creazione peer fallita"),
            status_code=303,
        )


@router.get("/gateways/{gateway_id}/peers/config")
def download_all_peer_configs(gateway_id: int, session: DbSession) -> Response:
    gateway = GatewayRepository(session).get_by_id(gateway_id)
    if not gateway:
        return PlainTextResponse("Gateway not found", status_code=404)
    peers = PeerRepository(session).list_by_gateway(gateway_id)
    if not peers:
        return PlainTextResponse("Nessun peer", status_code=404)
    service = PeerService(session)
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as bundle:
        for peer in peers:
            bundle.writestr(f"{peer.name}.conf", service.export_config(peer.id))
    archive.seek(0)
    filename = f"{gateway.name}-peers.zip"
    return Response(
        content=archive.getvalue(),
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/peers/{peer_id}/config", response_class=PlainTextResponse)
def download_peer_config(peer_id: int, session: DbSession) -> PlainTextResponse:
    try:
        conf = PeerService(session).export_config(peer_id)
        peer = PeerRepository(session).get_by_id(peer_id)
        filename = f"{peer.name}.conf" if peer else "peer.conf"
        return PlainTextResponse(
            conf,
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
            media_type="text/plain",
        )
    except ValueError:
        return PlainTextResponse("Peer not found", status_code=404)


@router.post("/peers/{peer_id}/regenerate")
def regenerate_peer_ui(peer_id: int, session: DbSession) -> RedirectResponse:
    try:
        PeerService(session).regenerate_peer_keys(peer_id)
    except ValueError:
        pass
    return RedirectResponse(url=f"/orchestrator/ui/peers/{peer_id}/config", status_code=303)


@router.post("/peers/{peer_id}/delete")
def delete_peer_ui(peer_id: int, session: DbSession) -> RedirectResponse:
    peer = PeerRepository(session).get_by_id(peer_id)
    gateway_id = peer.gateway_id if peer else None
    try:
        if peer:
            PeerService(session).delete_peer(peer_id)
    except ValueError:
        pass
    if gateway_id:
        return RedirectResponse(url=f"/orchestrator/ui/gateways/{gateway_id}", status_code=303)
    return RedirectResponse(url="/orchestrator/ui", status_code=303)


@router.post("/peers/{peer_id}/suspend")
def suspend_peer_ui(peer_id: int, session: DbSession) -> RedirectResponse:
    peer = PeerRepository(session).get_by_id(peer_id)
    try:
        PeerService(session).suspend_peer(peer_id)
    except ValueError:
        pass
    if peer:
        return RedirectResponse(url=f"/orchestrator/ui/gateways/{peer.gateway_id}", status_code=303)
    return RedirectResponse(url="/orchestrator/ui", status_code=303)


@router.post("/peers/{peer_id}/resume")
def resume_peer_ui(peer_id: int, session: DbSession) -> RedirectResponse:
    peer = PeerRepository(session).get_by_id(peer_id)
    try:
        PeerService(session).resume_peer(peer_id)
    except ValueError:
        pass
    if peer:
        return RedirectResponse(url=f"/orchestrator/ui/gateways/{peer.gateway_id}", status_code=303)
    return RedirectResponse(url="/orchestrator/ui", status_code=303)
