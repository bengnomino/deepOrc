"""Push files and run setup scripts inside Incus instances."""

import subprocess
import tempfile
from pathlib import Path


def push_file(instance: str, remote_path: str, content: str, *, mode: str = "0755") -> None:
    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", delete=False) as handle:
        handle.write(content)
        local_path = handle.name
    try:
        subprocess.run(
            ["incus", "file", "push", local_path, f"{instance}{remote_path}"],
            check=True,
            timeout=60,
            capture_output=True,
            text=True,
        )
        subprocess.run(
            ["incus", "exec", instance, "--", "chmod", mode, remote_path],
            check=True,
            timeout=30,
            capture_output=True,
            text=True,
        )
    finally:
        Path(local_path).unlink(missing_ok=True)


def push_binary(instance: str, remote_path: str, local_path: str, *, mode: str = "0755") -> None:
    subprocess.run(
        ["incus", "file", "push", local_path, f"{instance}{remote_path}"],
        check=True,
        timeout=120,
        capture_output=True,
        text=True,
    )
    subprocess.run(
        ["incus", "exec", instance, "--", "chmod", mode, remote_path],
        check=True,
        timeout=30,
        capture_output=True,
        text=True,
    )


def wait_for_instance(instance: str, timeout: int = 90) -> None:
    import time

    deadline = time.time() + timeout
    while time.time() < deadline:
        result = subprocess.run(
            ["incus", "exec", instance, "--", "ubus", "list"],
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
        if result.returncode == 0 and result.stdout.strip():
            return
        time.sleep(2)
    raise RuntimeError(f"Incus instance {instance} not ready for setup (ubus unavailable)")


def run_script(instance: str, script: str, *, remote_path: str = "/tmp/gateway-setup.sh") -> None:
    wait_for_instance(instance)
    push_file(instance, remote_path, script)
    result = subprocess.run(
        ["incus", "exec", instance, "--", "sh", remote_path],
        capture_output=True,
        text=True,
        timeout=600,
        check=False,
    )
    if result.returncode != 0:
        msg = (result.stderr or result.stdout or "setup script failed").strip()
        if len(msg) > 800:
            msg = msg[-800:].lstrip()
            if "\n" in msg:
                msg = msg.split("\n", 1)[1]
        raise RuntimeError(msg)
