"""Incus REST API client."""

from pathlib import Path
from typing import Any

import httpx

from orchestrator.config import get_settings
from orchestrator.incus.remote_setup import ensure_worker_remote_certs
from orchestrator.models.worker import Worker


class IncusClient:
    def __init__(self, worker: Worker | None = None, socket_path: str | None = None) -> None:
        settings = get_settings()
        self._worker = worker
        if worker and worker.incus_url:
            cert_path = worker.incus_cert_path
            key_path = worker.incus_key_path
            if worker.incus_remote and (
                not cert_path
                or not key_path
                or not Path(cert_path).is_file()
                or not Path(key_path).is_file()
            ):
                paths = ensure_worker_remote_certs(worker.incus_remote, settings.data_dir)
                cert_path = paths.cert_path
                key_path = paths.key_path
            if not cert_path or not key_path:
                raise ValueError(f"Worker {worker.name} missing Incus client certificate paths")
            # Server cert SAN often lacks the tailnet IP; mTLS client cert is the trust anchor.
            verify = False
            self._client = httpx.Client(
                base_url=worker.incus_url.rstrip("/"),
                cert=(cert_path, key_path),
                verify=verify,
                timeout=60.0,
            )
        else:
            socket = socket_path or settings.incus_socket
            self._client = httpx.Client(
                transport=httpx.HTTPTransport(uds=socket),
                base_url="http://localhost",
                timeout=60.0,
            )

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "IncusClient":
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()

    def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        response = self._client.request(method, f"/1.0{path}", **kwargs)
        response.raise_for_status()
        data = response.json()
        if data.get("type") == "async":
            return self._wait_operation(data["operation"])
        return data.get("metadata", data)

    def _wait_operation(self, operation_url: str) -> Any:
        op_id = operation_url.rsplit("/", 1)[-1]
        while True:
            resp = self._client.get(f"/1.0/operations/{op_id}")
            resp.raise_for_status()
            meta = resp.json().get("metadata", {})
            status = meta.get("status")
            if status == "Success":
                return meta.get("metadata")
            if status == "Failure":
                err = meta.get("err", "unknown error")
                raise RuntimeError(f"Incus operation failed: {err}")
            import time

            time.sleep(1)

    def get_instance_state(self, name: str) -> dict[str, Any]:
        return self._request("GET", f"/instances/{name}/state")

    def create_instance(self, name: str, source: dict[str, Any], config: dict[str, Any]) -> Any:
        settings = get_settings()
        payload = {
            "name": name,
            "source": source,
            "config": config,
            "type": settings.incus_instance_type,
            "profiles": ["default"],
        }
        return self._request("POST", "/instances", json=payload)

    def start_instance(self, name: str) -> Any:
        return self._request("PUT", f"/instances/{name}/state", json={"action": "start", "timeout": 60})

    def stop_instance(self, name: str) -> Any:
        return self._request("PUT", f"/instances/{name}/state", json={"action": "stop", "timeout": 60})

    def delete_instance(self, name: str) -> Any:
        return self._request("DELETE", f"/instances/{name}")

    def add_device(self, name: str, device_name: str, device_type: str, properties: dict[str, str]) -> Any:
        device = {"type": device_type, **properties}
        return self._request(
            "PATCH",
            f"/instances/{name}",
            json={"devices": {device_name: device}},
        )

    def set_instance_config(self, name: str, config: dict[str, str]) -> Any:
        return self._request("PATCH", f"/instances/{name}", json={"config": config})

    def get_instance(self, name: str) -> dict[str, Any]:
        return self._request("GET", f"/instances/{name}")
