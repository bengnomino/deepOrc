"""Static asset URLs with deploy-time cache busting."""

import hashlib
import os
from functools import lru_cache
from pathlib import Path

WEB_STATIC_DIR = Path(__file__).parent / "static"


@lru_cache
def get_static_asset_version() -> str:
    override = os.environ.get("STATIC_ASSET_VERSION", "").strip()
    if override:
        return override

    digest = hashlib.sha256()
    if WEB_STATIC_DIR.is_dir():
        for path in sorted(WEB_STATIC_DIR.iterdir()):
            if path.is_file():
                digest.update(path.name.encode())
                digest.update(path.read_bytes())
    return digest.hexdigest()[:12]


def static_url(filename: str, api_root: str = "/orchestrator") -> str:
    name = filename.lstrip("/")
    prefix = api_root.rstrip("/")
    return f"{prefix}/static/{name}?v={get_static_asset_version()}"
