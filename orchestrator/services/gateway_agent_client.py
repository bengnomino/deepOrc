"""HTTP client for gateway agent API."""

import json
import subprocess
from typing import Any, Callable
from urllib.parse import urlencode

import httpx

from orchestrator.config import get_settings


class GatewayAgentClient:
    def __init__(
        self,
        vm_ip: str,
        token: str,
        port: int | None = None,
        incus_instance: str | None = None,
    ) -> None:
        settings = get_settings()
        self._port = port or settings.agent_port
        self._token = token
        self._base = f"http://{vm_ip}:{self._port}"
        self._headers = {"Authorization": f"Bearer {token}"}
        self._incus_instance = incus_instance

    def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        if self._incus_instance:
            return self._request_via_incus(method, path, **kwargs)
        with httpx.Client(timeout=30.0) as client:
            response = client.request(
                method, f"{self._base}{path}", headers=self._headers, **kwargs
            )
            response.raise_for_status()
            if response.content:
                return response.json()
            return {}

    def _incus_http_script(self, method: str, url: str, body: dict[str, Any] | None) -> str:
        """Shell script for HTTP inside OpenWrt (busybox wget; optional curl for DELETE)."""
        auth = f"Authorization: Bearer {self._token}"
        auth_q = auth.replace("'", "'\\''")
        url_q = url.replace("'", "'\\''")
        if method == "GET":
            return (
                f"wget -qO- -T 30 --header='{auth_q}' '{url_q}'"
            )
        if method == "POST":
            payload = json.dumps(body) if body is not None else ""
            payload_q = payload.replace("'", "'\\''")
            return (
                f"wget -qO- -T 30 --header='{auth_q}' "
                f"--header='Content-Type: application/json' "
                f"--post-data='{payload_q}' '{url_q}'"
            )
        payload = json.dumps(body) if body is not None else ""
        payload_q = payload.replace("'", "'\\''")
        if body is not None:
            return (
                f"if command -v curl >/dev/null 2>&1; then "
                f"curl -sf -X {method} -H '{auth_q}' "
                f"-H 'Content-Type: application/json' "
                f"-d '{payload_q}' '{url_q}'; "
                f"else exit 127; fi"
            )
        return (
            f"if command -v curl >/dev/null 2>&1; then "
            f"curl -sf -X {method} -H '{auth_q}' '{url_q}'; "
            f"else exit 127; fi"
        )

    def _request_via_incus(self, method: str, path: str, **kwargs: Any) -> Any:
        url = f"http://127.0.0.1:{self._port}{path}"
        params = kwargs.get("params")
        if params:
            url = f"{url}?{urlencode(params)}"

        body = kwargs.get("json")
        script = self._incus_http_script(method, url, body)
        cmd = [
            "incus",
            "exec",
            self._incus_instance,
            "--",
            "sh",
            "-c",
            script,
        ]

        result = subprocess.run(cmd, capture_output=True, text=True, timeout=60, check=False)
        if result.returncode != 0:
            detail = (result.stderr or result.stdout or "incus agent request failed").strip()
            raise RuntimeError(detail)
        if result.stdout.strip():
            return json.loads(result.stdout)
        return {}

    def register(self, gateway_name: str) -> dict[str, Any]:
        return self._request("POST", "/v1/register", json={"gateway_name": gateway_name})

    def health(self) -> dict[str, Any]:
        return self._request("GET", "/v1/health")

    def tailscale_status(self) -> dict[str, Any]:
        last_err: Exception | None = None
        try:
            return self._request("GET", "/v1/tailscale/status")
        except httpx.HTTPStatusError as exc:
            last_err = exc
            if exc.response.status_code not in {404, 503} or not self._incus_instance:
                raise
        except Exception as exc:
            last_err = exc
        if self._incus_instance:
            return self._tailscale_status_via_incus()
        if last_err is not None:
            raise last_err
        return {"status": ""}

    def egress_public_ip(self) -> dict[str, Any]:
        last_err: Exception | None = None
        try:
            return self._request("GET", "/v1/egress/public-ip")
        except httpx.HTTPStatusError as exc:
            last_err = exc
            if exc.response.status_code not in {404, 503} or not self._incus_instance:
                raise
        except Exception as exc:
            last_err = exc
        if self._incus_instance:
            return self._egress_public_ip_via_incus()
        if last_err is not None:
            raise last_err
        return {"ip": ""}

    def _egress_public_ip_via_incus(self) -> dict[str, Any]:
        if not self._incus_instance:
            raise RuntimeError("incus instance required for direct egress ip lookup")
        script = (
            "for u in https://api.ipify.org https://ifconfig.me/ip; do "
            'ip=$(wget -qO- -T 10 "$u" 2>/dev/null | head -1); '
            'case "$ip" in *.*.*.*) echo "$ip"; exit 0 ;; esac; '
            "done; exit 1"
        )
        cmd = ["incus", "exec", self._incus_instance, "--", "sh", "-c", script]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=60, check=False)
        if result.returncode != 0:
            raise RuntimeError(
                result.stderr.strip() or result.stdout.strip() or "egress ip lookup failed"
            )
        ip = result.stdout.strip().splitlines()[0].strip()
        return {"ip": ip}

    def _tailscale_status_via_incus(self) -> dict[str, Any]:
        if not self._incus_instance:
            raise RuntimeError("incus instance required for direct tailscale status")
        cmd = [
            "incus",
            "exec",
            self._incus_instance,
            "--",
            "/usr/sbin/tailscale",
            "status",
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=60, check=False)
        if result.returncode != 0:
            raise RuntimeError(
                result.stderr.strip() or result.stdout.strip() or "tailscale status failed"
            )
        return {"status": result.stdout.strip()}

    def add_peer(self, public_key: str, allowed_ips: str) -> dict[str, Any]:
        return self._request("POST", "/v1/peers", json={"public_key": public_key, "allowed_ips": allowed_ips})

    def remove_peer(self, public_key: str) -> dict[str, Any]:
        return self._request("DELETE", f"/v1/peers/{public_key}")

    def suspend_peer(self, public_key: str, allowed_ip: str) -> dict[str, Any]:
        return self._request(
            "POST",
            f"/v1/peers/{public_key}/suspend",
            params={"allowed_ip": allowed_ip},
        )

    def resume_peer(self, public_key: str, allowed_ip: str) -> dict[str, Any]:
        return self._request(
            "POST",
            f"/v1/peers/{public_key}/resume",
            params={"allowed_ip": allowed_ip},
        )

    def list_peers(self) -> list[dict[str, Any]]:
        return self._request("GET", "/v1/peers")

    def advertise_exit_node(self) -> dict[str, Any]:
        last_err: Exception | None = None
        try:
            return self._request("POST", "/v1/tailscale/advertise-exit")
        except httpx.HTTPStatusError as exc:
            last_err = exc
            if exc.response.status_code != 404 or not self._incus_instance:
                raise
        except Exception as exc:
            last_err = exc
        if self._incus_instance:
            return self._advertise_exit_node_via_incus()
        if last_err is not None:
            raise last_err
        return {"status": "advertised"}

    def _advertise_exit_node_via_incus(self) -> dict[str, Any]:
        if not self._incus_instance:
            raise RuntimeError("incus instance required for direct tailscale config")
        cmd = [
            "incus",
            "exec",
            self._incus_instance,
            "--",
            "sh",
            "-c",
            "/usr/sbin/tailscale set --advertise-exit-node --accept-dns --netfilter-mode=off",
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=120, check=False)
        if result.returncode != 0:
            raise RuntimeError(
                result.stderr.strip() or result.stdout.strip() or "advertise-exit failed"
            )
        return {"status": "advertised"}

    def set_tailscale_hostname(self, hostname: str) -> dict[str, Any]:
        last_err: Exception | None = None
        try:
            return self._request(
                "POST", "/v1/tailscale/hostname", json={"hostname": hostname}
            )
        except httpx.HTTPStatusError as exc:
            last_err = exc
            if exc.response.status_code != 404 or not self._incus_instance:
                raise
        except Exception as exc:
            last_err = exc
        if self._incus_instance:
            host_q = hostname.replace("'", "'\\''")
            cmd = [
                "incus",
                "exec",
                self._incus_instance,
                "--",
                "sh",
                "-c",
                f"/usr/sbin/tailscale set --hostname='{host_q}'",
            ]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=120, check=False)
            if result.returncode != 0:
                raise RuntimeError(
                    result.stderr.strip() or result.stdout.strip() or "set hostname failed"
                )
            return {"status": "updated", "hostname": hostname}
        if last_err is not None:
            raise last_err
        return {"status": "updated", "hostname": hostname}

    def set_exit_node(self, exit_node_id: str) -> dict[str, Any]:
        """Legacy API — deepOrc gateways self-advertise as exit nodes."""
        return self.advertise_exit_node()

    def clear_exit_node(self) -> dict[str, Any]:
        return {"status": "noop"}

    def run_exit_via_wg(self) -> None:
        """Apply exit routing/DNS/firewall script inside the gateway VM."""
        if not self._incus_instance:
            return
        result = subprocess.run(
            [
                "incus",
                "exec",
                self._incus_instance,
                "--",
                "/opt/gateway-agent/exit-via-wg.sh",
            ],
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )
        if result.returncode != 0:
            msg = (result.stderr or result.stdout or "exit-via-wg failed").strip()
            raise RuntimeError(msg)

    def wait_until_healthy(
        self,
        timeout: int = 300,
        interval: int = 5,
        on_poll: Callable[[], None] | None = None,
    ) -> bool:
        import time

        deadline = time.time() + timeout
        while time.time() < deadline:
            if on_poll:
                try:
                    on_poll()
                except Exception:
                    pass
            try:
                health = self.health()
                if health.get("wg_online") and health.get("tailscale_online"):
                    return True
            except Exception:
                pass
            time.sleep(interval)
        return False
