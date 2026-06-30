"""IP geolocation for exit egress display (ip-api.com, fallback ipinfo.io)."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass

import httpx

logger = logging.getLogger(__name__)

_GEO_CACHE_TTL_SECONDS = 86400
_geo_cache: dict[str, tuple[GeoResult, float]] = {}


@dataclass(frozen=True)
class GeoResult:
    ip: str
    country_code: str


def country_flag(country_code: str | None) -> str:
    if not country_code or len(country_code) != 2:
        return ""
    code = country_code.upper()
    return "".join(chr(0x1F1E6 + ord(char) - ord("A")) for char in code)


def _lookup_geo_uncached(ip: str) -> GeoResult | None:
    try:
        with httpx.Client(timeout=5.0) as client:
            response = client.get(
                f"http://ip-api.com/json/{ip}",
                params={"fields": "status,message,query,countryCode"},
            )
            response.raise_for_status()
            data = response.json()
            if data.get("status") == "success" and data.get("countryCode"):
                return GeoResult(ip=data["query"], country_code=data["countryCode"])
    except Exception as exc:
        logger.debug("ip-api lookup failed for %s: %s", ip, exc)

    try:
        with httpx.Client(timeout=5.0) as client:
            response = client.get(f"https://ipinfo.io/{ip}/json")
            response.raise_for_status()
            data = response.json()
            country = data.get("country")
            if country and not data.get("bogon"):
                return GeoResult(ip=data.get("ip", ip), country_code=country)
    except Exception as exc:
        logger.debug("ipinfo lookup failed for %s: %s", ip, exc)

    return None


def lookup_geo(ip: str) -> GeoResult | None:
    ip = ip.strip()
    if not ip:
        return None

    cached = _geo_cache.get(ip)
    now = time.time()
    if cached and now - cached[1] < _GEO_CACHE_TTL_SECONDS:
        return cached[0]

    result = _lookup_geo_uncached(ip)
    if result:
        _geo_cache[ip] = (result, now)
    return result


def clear_geo_cache() -> None:
    _geo_cache.clear()
