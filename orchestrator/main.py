"""Orchestrator FastAPI application."""

import logging
from contextlib import asynccontextmanager

from apscheduler.schedulers.background import BackgroundScheduler
from fastapi import FastAPI, Request
from fastapi.responses import RedirectResponse, Response
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint

from orchestrator.api.routes import gateways, monitoring, peers, workers
from orchestrator.config import get_settings
from orchestrator.models.base import init_db
from orchestrator.web.register_routes import router as register_router
from orchestrator.web.routes import WEB_DIR, router as web_router
from orchestrator.web.static_files import VersionedStaticFiles
from orchestrator.web.templating import configure_templates
from orchestrator.workers.headscale_sync import sync_headscale_exit_nodes
from orchestrator.workers.metrics_collector import collect_metrics
from orchestrator.workers.provisioning import resume_incomplete_provisioning
from orchestrator.workers.deletion import resume_incomplete_deletions

logger = logging.getLogger(__name__)
scheduler = BackgroundScheduler()


def _run_metrics_collection() -> None:
    from orchestrator.models.base import get_session_factory

    session = get_session_factory()()
    try:
        count = collect_metrics(session)
        logger.debug("Collected metrics for %d gateways", count)
    except Exception:
        logger.exception("Metrics collection failed")
    finally:
        session.close()


def _run_headscale_sync() -> None:
    sync_headscale_exit_nodes()


class NoCacheHtmlMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        response = await call_next(request)
        if "text/html" in response.headers.get("content-type", ""):
            response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
            response.headers["Pragma"] = "no-cache"
            response.headers["Expires"] = "0"
        return response


def _run_provisioning_sweep() -> None:
    resume_incomplete_provisioning()
    resume_incomplete_deletions()


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    init_db()
    from orchestrator.models.base import get_session_factory
    from orchestrator.services.worker_service import WorkerService

    session = get_session_factory()()
    try:
        WorkerService(session).ensure_default_local_worker()
    finally:
        session.close()

    scheduler.add_job(
        _run_metrics_collection,
        "interval",
        seconds=settings.metrics_poll_interval_seconds,
        id="metrics_collector",
    )
    scheduler.add_job(
        _run_headscale_sync,
        "interval",
        seconds=settings.metrics_poll_interval_seconds,
        id="headscale_sync",
    )
    scheduler.add_job(
        _run_provisioning_sweep,
        "interval",
        seconds=settings.metrics_poll_interval_seconds,
        id="provisioning_sweep",
    )
    scheduler.start()
    _run_headscale_sync()
    _run_provisioning_sweep()
    logger.info("Orchestrator started")
    yield
    scheduler.shutdown(wait=False)


def create_app() -> FastAPI:
    settings = get_settings()
    configure_templates()
    api_prefix = f"{settings.api_root.rstrip('/')}/api/v1"
    ui_prefix = f"{settings.api_root.rstrip('/')}/ui"
    app = FastAPI(
        title="VDI Exit Node Orchestrator",
        version="0.2.0",
        lifespan=lifespan,
        docs_url=f"{settings.api_root.rstrip('/')}/docs",
        redoc_url=f"{settings.api_root.rstrip('/')}/redoc",
        openapi_url=f"{settings.api_root.rstrip('/')}/openapi.json",
    )
    app.add_middleware(NoCacheHtmlMiddleware)
    app.mount(
        f"{settings.api_root.rstrip('/')}/static",
        VersionedStaticFiles(directory=str(WEB_DIR / "static")),
        name="static",
    )
    app.include_router(register_router)
    app.include_router(web_router, prefix=ui_prefix)
    app.include_router(gateways.router, prefix=api_prefix)
    app.include_router(peers.router, prefix=api_prefix)
    app.include_router(monitoring.router, prefix=api_prefix)
    app.include_router(workers.router, prefix=api_prefix)

    @app.get(f"{settings.api_root.rstrip('/')}/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get(settings.api_root.rstrip("/") or "/")
    def root_redirect() -> RedirectResponse:
        return RedirectResponse(url=f"{ui_prefix}/", status_code=302)

    return app


app = create_app()


def cli() -> None:
    import uvicorn

    settings = get_settings()
    uvicorn.run(
        "orchestrator.main:app",
        host="0.0.0.0",
        port=8000,
        reload=False,
    )


if __name__ == "__main__":
    cli()
