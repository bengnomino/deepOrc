"""Shared Jinja2 templates with static asset helpers."""

from pathlib import Path

from fastapi.templating import Jinja2Templates

from orchestrator.config import get_settings
from orchestrator.web.static_assets import static_url

WEB_DIR = Path(__file__).parent
TEMPLATES_DIR = WEB_DIR / "templates"

templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


def configure_templates() -> Jinja2Templates:
    settings = get_settings()
    templates.env.globals["static_url"] = lambda filename: static_url(
        filename, settings.api_root
    )
    return templates


configure_templates()
