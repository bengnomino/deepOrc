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
from orchestrator.headscale import (
    HeadscaleError,
    approve_registration_request,
    create_exit_node_preauth_key,
    exit_node_registration_command,
    list_exit_nodes,
)
from orchestrator.repositories.registration_request_repo import RegistrationRequestRepository
from orchestrator.models.job import JobStatus
from orchestrator.repositories.gateway_repo import GatewayRepository
from orchestrator.repositories.job_repo import JobRepository
from orchestrator.repositories.metrics_repo import MetricsRepository
from orchestrator.repositories.peer_repo import PeerRepository
from orchestrator.services.exit_host_script_service import ExitHostScriptService
from orchestrator.services.gateway_service import CreateGatewayRequest, GatewayService
from orchestrator.services.peer_group_service import CreatePeerGroupRequest, PeerGroupService
from orchestrator.services.ip_geo import country_flag
from orchestrator.services.peer_service import PeerService
from orchestrator.services.worker_service import WorkerService
from orchestrator.web.views import (
    gateway_headscale_display_name,
    match_gateway_exit_node,
    partition_exit_nodes,
    peer_is_online,
    sort_peers_by_connectivity,
    worker_host_label,
)
from orchestrator.web.templating import templates
from orchestrator.lan.ipam import remaining_lan_capacity
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
    exit_nodes_by_hostname: dict,
) -> dict:
    import ipaddress

    metric = metrics_repo.latest_gateway_metric(gateway.id)
    peers = peers_repo.list_by_gateway(gateway.id)
    peer_metrics = {peer.id: metrics_repo.latest_peer_metric(peer.id) for peer in peers}
    peer_online = sum(
        1 for peer in peers if peer_is_online(peer, peer_metrics.get(peer.id))
    )
    exit_node = match_gateway_exit_node(gateway, exit_nodes_by_ip, exit_nodes_by_hostname)
    wg_gateway_ip = None
    if gateway.wg_subnet and gateway.wg_subnet != "pending":
        try:
            wg_gateway_ip = str(ipaddress.ip_network(gateway.wg_subnet).network_address + 1)
        except ValueError:
            wg_gateway_ip = None
    egress_public_ip = metric.egress_public_ip if metric else None
    egress_country_code = metric.egress_country_code if metric else None
    return {
        "gateway": gateway,
        "display_name": gateway_headscale_display_name(gateway, exit_node),
        "endpoint": gs.get_endpoint(gateway),
        "wg_gateway_ip": wg_gateway_ip,
        "tailscale_online": metric.tailscale_online if metric else None,
        "wg_online": metric.wg_online if metric else None,
        "exit_node": exit_node,
        "peer_total": len(peers),
        "peer_online": peer_online,
        "egress_public_ip": egress_public_ip,
        "egress_country_code": egress_country_code,
        "egress_flag": country_flag(egress_country_code),
    }


def _dashboard_workers(session: DbSession) -> tuple[list[dict], list, str | None]:
    gateways = GatewayRepository(session).list_all()
    metrics_repo = MetricsRepository(session)
    peers_repo = PeerRepository(session)
    gs = GatewayService(session)
    worker_service = WorkerService(session)

    headscale_error = None
    try:
        hs_nodes = list_exit_nodes()
        exit_nodes_by_ip = {node.tailscale_ip: node for node in hs_nodes}
        exit_nodes_by_hostname = {node.hostname: node for node in hs_nodes}
        unassigned, _ = partition_exit_nodes(hs_nodes, gateways)
    except HeadscaleError as exc:
        exit_nodes_by_ip = {}
        exit_nodes_by_hostname = {}
        unassigned = []
        headscale_error = f"Could not read exit nodes from Headscale: {exc}"

    groups_by_worker: dict[int, list] = {}
    for group in PeerGroupService(session).list_groups():
        groups_by_worker.setdefault(group.worker_id, []).append(group)

    sections = []
    for row in worker_service.dashboard_workers():
        gateway_rows_by_group: dict[int, list] = {}
        orphan_gateway_rows: list = []
        for gateway in gateways:
            if gateway.worker_id != row["worker"].id:
                continue
            gateway_row = _gateway_row(
                gateway,
                gs=gs,
                metrics_repo=metrics_repo,
                peers_repo=peers_repo,
                exit_nodes_by_ip=exit_nodes_by_ip,
                exit_nodes_by_hostname=exit_nodes_by_hostname,
            )
            if gateway.peer_group_id:
                gateway_rows_by_group.setdefault(gateway.peer_group_id, []).append(gateway_row)
            else:
                orphan_gateway_rows.append(gateway_row)

        worker_groups = groups_by_worker.get(row["worker"].id, [])
        peer_group_sections = [
            {
                "group": group,
                "gateways": gateway_rows_by_group.get(group.id, []),
            }
            for group in worker_groups
        ]
        sections.append(
            {
                "worker": row["worker"],
                "status": row["status"],
                "peer_group_sections": peer_group_sections,
                "orphan_gateways": orphan_gateway_rows,
            }
        )
    return sections, unassigned, headscale_error


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
    return RegistrationRequestRepository(session).list_pending()


@router.get("", response_class=HTMLResponse)
def dashboard(request: Request, session: DbSession, error: str | None = None) -> HTMLResponse:
    workers, unassigned, headscale_error = _dashboard_workers(session)
    pending_regs = _pending_registrations(session)
    settings = get_settings()
    return templates.TemplateResponse(
        request,
        "dashboard.html",
        {
            "workers": workers,
            "worker_choices": _worker_choices(session),
            "worker_choices_json": json.dumps(_worker_choices(session)),
            "unassigned_exit_nodes": unassigned,
            "pending_registrations": pending_regs,
            "headscale_error": headscale_error,
            "flash_error": error,
            "exit_node_tag": settings.headscale_exit_node_tag,
            "login_server": settings.headscale_url,
            "title": "Dashboard",
        },
    )


@router.post("/exit-nodes/authkey")
def create_exit_node_authkey() -> JSONResponse:
    settings = get_settings()
    try:
        preauth = create_exit_node_preauth_key()
    except HeadscaleError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return JSONResponse(
        {
            "key": preauth.key,
            "tag": "",
            "login_server": settings.headscale_url,
            "command": exit_node_registration_command(preauth.key),
        }
    )


@router.get("/registrations/pending")
def list_pending_registrations(session: DbSession) -> JSONResponse:
    rows = RegistrationRequestRepository(session).list_pending()
    return JSONResponse(
        [
            {
                "registration_key": row.registration_key,
                "display_code": row.display_code,
                "created_at": row.created_at.isoformat(),
            }
            for row in rows
        ]
    )


@router.post("/registrations/{registration_key}/approve")
def approve_registration_ui(registration_key: str, session: DbSession) -> RedirectResponse:
    key = registration_key.strip()
    repo = RegistrationRequestRepository(session)
    try:
        node = approve_registration_request(key)
        repo.mark_approved(key, node.node_id, node.tailscale_ip)
        session.commit()
    except HeadscaleError:
        session.rollback()
    return RedirectResponse(url="/orchestrator/ui", status_code=303)


@router.post("/registrations/{registration_key}/reject")
def reject_registration_ui(registration_key: str, session: DbSession) -> RedirectResponse:
    RegistrationRequestRepository(session).mark_rejected(registration_key.strip())
    session.commit()
    return RedirectResponse(url="/orchestrator/ui", status_code=303)


@router.post("/peer-groups/create")
def create_peer_group_ui(
    session: DbSession,
    name: str = Form(...),
    worker_id: int = Form(...),
    lan_start_ip: str = Form(...),
    parent_iface: str = Form(""),
) -> RedirectResponse:
    service = PeerGroupService(session)
    try:
        group = service.create_group(
            CreatePeerGroupRequest(
                name=name.strip(),
                worker_id=worker_id,
                lan_start_ip=lan_start_ip.strip(),
                parent_iface=parent_iface.strip() or None,
            )
        )
        return RedirectResponse(url=f"/orchestrator/ui/peer-groups/{group.id}", status_code=303)
    except ValueError as exc:
        return RedirectResponse(
            url=f"/orchestrator/ui?error={quote(str(exc))}",
            status_code=303,
        )


@router.get("/peer-groups/{group_id}", response_class=HTMLResponse)
def peer_group_detail(
    request: Request,
    group_id: int,
    session: DbSession,
    error: str | None = None,
    ok: str | None = None,
) -> HTMLResponse:
    group = PeerGroupService(session).get_group(group_id)
    if not group:
        return RedirectResponse(url="/orchestrator/ui", status_code=303)
    gateways = [g for g in GatewayRepository(session).list_all() if g.peer_group_id == group_id]
    gs = GatewayService(session)
    metrics_repo = MetricsRepository(session)
    peers_repo = PeerRepository(session)
    exit_nodes_by_ip: dict = {}
    exit_nodes_by_hostname: dict = {}
    try:
        hs_nodes = list_exit_nodes()
        exit_nodes_by_ip = {node.tailscale_ip: node for node in hs_nodes}
        exit_nodes_by_hostname = {node.hostname: node for node in hs_nodes}
    except HeadscaleError:
        pass
    gateway_rows = [
        _gateway_row(
            gateway,
            gs=gs,
            metrics_repo=metrics_repo,
            peers_repo=peers_repo,
            exit_nodes_by_ip=exit_nodes_by_ip,
            exit_nodes_by_hostname=exit_nodes_by_hostname,
        )
        for gateway in gateways
    ]
    try:
        _, host_setup_script = ExitHostScriptService(session).build_setup_script(group_id)
    except ValueError:
        host_setup_script = ""
    return templates.TemplateResponse(
        request,
        "peer_group_detail.html",
        {
            "title": group.name,
            "group": group,
            "gateway_rows": gateway_rows,
            "lan_remaining": remaining_lan_capacity(session, group),
            "host_setup_script": host_setup_script,
            "flash_error": error,
            "flash_ok": ok,
        },
    )


@router.get("/peer-groups/{group_id}/host-setup.sh", response_class=PlainTextResponse)
def download_peer_group_host_setup(group_id: int, session: DbSession) -> PlainTextResponse:
    try:
        group, script = ExitHostScriptService(session).build_setup_script(group_id)
    except ValueError as exc:
        return PlainTextResponse(str(exc), status_code=404)
    filename = f"{group.name}-host-setup.sh"
    return PlainTextResponse(
        script,
        media_type="text/x-shellscript",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/exit-host-cleanup.sh", response_class=PlainTextResponse)
def download_exit_host_cleanup() -> PlainTextResponse:
    from orchestrator.host_setup.script import render_exit_host_auto_cleanup_script

    return PlainTextResponse(
        render_exit_host_auto_cleanup_script(),
        media_type="text/x-shellscript",
        headers={"Content-Disposition": 'attachment; filename="exit-host-cleanup.sh"'},
    )


@router.post("/peer-groups/{group_id}/gateways")
def create_group_gateways_ui(
    group_id: int,
    session: DbSession,
    background_tasks: BackgroundTasks,
    count: int = Form(...),
) -> RedirectResponse:
    service = PeerGroupService(session)
    try:
        result = service.create_gateways(group_id, count)
        for item in result.gateways:
            schedule_provisioning_after_request(
                background_tasks, item.gateway.id, item.job.id
            )
        return RedirectResponse(
            url=f"/orchestrator/ui/peer-groups/{group_id}?ok={quote(f'Created {len(result.gateways)} gateway(s)')}",
            status_code=303,
        )
    except ValueError as exc:
        return RedirectResponse(
            url=f"/orchestrator/ui/peer-groups/{group_id}?error={quote(str(exc))}",
            status_code=303,
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
        hs_nodes = list_exit_nodes()
        exit_nodes_by_ip = {node.tailscale_ip: node for node in hs_nodes}
        exit_nodes_by_hostname = {node.hostname: node for node in hs_nodes}
        exit_node = match_gateway_exit_node(gateway, exit_nodes_by_ip, exit_nodes_by_hostname)
    except HeadscaleError as exc:
        headscale_error = str(exc)
    display_name = gateway_headscale_display_name(gateway, exit_node)
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
    tailscale_status = None
    if gateway.status == GatewayStatus.READY:
        tailscale_status = gs.fetch_tailscale_status(gateway)
    return templates.TemplateResponse(
        request,
        "gateway_detail.html",
        {
            "title": display_name,
            "gateway": gateway,
            "display_name": display_name,
            "endpoint": gs.get_endpoint(gateway),
            "wg_gateway_ip": wg_gateway_ip,
            "exit_node": exit_node,
            "headscale_error": headscale_error,
            "peers_online": peers_online,
            "peers_offline": peers_offline,
            "metrics": metrics,
            "provision_progress": provision_progress,
            "peer_group": gateway.peer_group,
            "tailscale_status": tailscale_status,
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


@router.post("/gateways/{gateway_id}/tailscale-name")
def rename_gateway_tailscale_ui(
    gateway_id: int,
    session: DbSession,
    tailscale_hostname: str = Form(...),
) -> RedirectResponse:
    service = GatewayService(session)
    try:
        service.rename_tailscale_display_name(gateway_id, tailscale_hostname.strip())
        return RedirectResponse(
            url=_gateway_detail_url(gateway_id, ok="Headscale name updated"),
            status_code=303,
        )
    except ValueError as exc:
        session.rollback()
        return RedirectResponse(
            url=_gateway_detail_url(gateway_id, error=str(exc)),
            status_code=303,
        )


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
            url=_gateway_detail_url(gateway_id, ok=f"Peer {result.peer.name} created"),
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
            url=_gateway_detail_url(gateway_id, error=str(exc) or "Peer creation failed"),
            status_code=303,
        )


@router.get("/gateways/{gateway_id}/peers/config")
def download_all_peer_configs(gateway_id: int, session: DbSession) -> Response:
    gateway = GatewayRepository(session).get_by_id(gateway_id)
    if not gateway:
        return PlainTextResponse("Gateway not found", status_code=404)
    peers = PeerRepository(session).list_by_gateway(gateway_id)
    if not peers:
        return PlainTextResponse("No peers", status_code=404)
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
