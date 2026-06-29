"""Public /register/* — codice a 6 cifre, approvazione solo da admin UI."""

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, JSONResponse

from orchestrator.api.deps import DbSession
from orchestrator.headscale.client import is_valid_registration_key, normalize_registration_key
from orchestrator.models.registration_request import RegistrationRequestStatus
from orchestrator.repositories.registration_request_repo import RegistrationRequestRepository
from orchestrator.web.templating import templates

router = APIRouter(tags=["register"])


@router.get("/register/{registration_key}", response_class=HTMLResponse)
def register_page(
    request: Request,
    registration_key: str,
    session: DbSession,
) -> HTMLResponse:
    key = normalize_registration_key(registration_key)
    if not is_valid_registration_key(key):
        return templates.TemplateResponse(
            request,
            "register_pending.html",
            {"error": "Richiesta non valida", "display_code": None, "registration_key": None},
            status_code=400,
        )
    row = RegistrationRequestRepository(session).touch_pending(key)
    session.commit()
    return templates.TemplateResponse(
        request,
        "register_pending.html",
        {
            "display_code": row.display_code,
            "registration_key": key,
            "status": row.status.value,
        },
    )


@router.get("/register/{registration_key}/status")
def register_status(registration_key: str, session: DbSession) -> JSONResponse:
    row = RegistrationRequestRepository(session).get_by_key(registration_key.strip())
    if not row:
        return JSONResponse({"status": "unknown"}, status_code=404)
    return JSONResponse(
        {
            "status": row.status.value,
            "display_code": row.display_code,
            "tailscale_ip": row.tailscale_ip,
        }
    )
