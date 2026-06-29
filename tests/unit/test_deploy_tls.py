"""Unit tests for deploy TLS / domain resolution."""

import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _bash(script: str) -> str:
    return subprocess.check_output(["bash", "-c", script], cwd=ROOT, text=True).strip()


def _load(base: str, service: str = "") -> None:
    svc = f'export SERVICE_HOST="{service}"' if service else "unset SERVICE_HOST"
    _bash(
        f"""
        export BASE_DOMAIN="{base}"
        {svc}
        unset DOMAIN
        source deploy/lib/common.sh
        resolve_host_domains
        """
    )


def test_resolve_subdomain_fqdn():
    out = _bash(
        """
        export BASE_DOMAIN=harlock.network
        export SERVICE_HOST=orchtest
        source deploy/lib/common.sh
        resolve_host_domains
        echo "$DOMAIN"
        """
    )
    assert out == "orchtest.harlock.network"


def test_derive_tls_sites_subdomain():
    assert (
        _bash(
            """
        export BASE_DOMAIN=harlock.network
        export SERVICE_HOST=orchtest
        source deploy/lib/common.sh
        resolve_host_domains
        derive_tls_sites
        """
        )
        == "orchtest.harlock.network, *.harlock.network"
    )


def test_derive_tls_sites_apex():
    assert (
        _bash(
            """
        export BASE_DOMAIN=example.com
        unset SERVICE_HOST
        source deploy/lib/common.sh
        resolve_host_domains
        derive_tls_sites
        """
        )
        == "example.com, *.example.com"
    )


def test_derive_certbot_domains_zone_and_wildcard():
    assert (
        _bash(
            """
        export BASE_DOMAIN=harlock.network
        export SERVICE_HOST=orchtest
        source deploy/lib/common.sh
        resolve_host_domains
        derive_certbot_domains
        """
        )
        == "harlock.network *.harlock.network"
    )


def test_cert_le_lineage_uses_base_domain_not_service():
    assert (
        _bash(
            """
        export BASE_DOMAIN=harlock.network
        export SERVICE_HOST=orchtest
        source deploy/lib/common.sh
        resolve_host_domains
        cert_le_lineage_dir
        """
        )
        == "/etc/letsencrypt/live/harlock.network"
    )
