"""Host CPU/RAM/network stats from /proc (Linux VPS)."""

from __future__ import annotations

import os
import time
from dataclasses import asdict, dataclass

_prev: dict[str, int] | None = None
_prev_ts: float = 0.0


@dataclass(frozen=True)
class HostStats:
    cpu_percent: float
    memory_total_mb: int
    memory_used_mb: int
    memory_percent: float
    network_interface: str
    network_rx_bytes_per_sec: float
    network_tx_bytes_per_sec: float
    load_avg: list[float]

    def to_dict(self) -> dict:
        return asdict(self)


def _read_cpu_times() -> tuple[int, int]:
    with open("/proc/stat", encoding="utf-8") as handle:
        line = handle.readline()
    parts = line.split()
    vals = [int(x) for x in parts[1:]]
    idle = vals[3] + (vals[4] if len(vals) > 4 else 0)
    return sum(vals), idle


def _read_mem() -> tuple[int, int]:
    data: dict[str, int] = {}
    with open("/proc/meminfo", encoding="utf-8") as handle:
        for line in handle:
            key, rest = line.split(":", 1)
            data[key] = int(rest.split()[0])
    total_kb = data["MemTotal"]
    total_mb = total_kb // 1024

    # Match `free` used memory (and htop Mem bar on most setups):
    # total - free - buffers - cached - sreclaimable
    if "MemFree" in data and "Cached" in data:
        used_kb = (
            total_kb
            - data.get("MemFree", 0)
            - data.get("Buffers", 0)
            - data.get("Cached", 0)
            - data.get("SReclaimable", 0)
        )
    elif "AnonPages" in data:
        used_kb = data["AnonPages"] + data.get("Shmem", 0)
    else:
        avail_kb = data.get("MemAvailable", data.get("MemFree", 0))
        used_kb = total_kb - avail_kb

    used_mb = max(0, min(used_kb // 1024, total_mb))
    return total_mb, used_mb


def _read_net() -> tuple[str, int, int]:
    iface = "eth0"
    rx = tx = 0
    best_total = -1
    with open("/proc/net/dev", encoding="utf-8") as handle:
        for line in handle.readlines()[2:]:
            if ":" not in line:
                continue
            name, rest = line.split(":", 1)
            name = name.strip()
            if name == "lo":
                continue
            cols = rest.split()
            cur_rx, cur_tx = int(cols[0]), int(cols[8])
            total = cur_rx + cur_tx
            if total >= best_total:
                best_total = total
                iface, rx, tx = name, cur_rx, cur_tx
    return iface, rx, tx


def collect_host_stats() -> HostStats:
    global _prev, _prev_ts

    now = time.time()
    cpu_total, cpu_idle = _read_cpu_times()
    mem_total_mb, mem_used_mb = _read_mem()
    iface, rx, tx = _read_net()
    load_avg = list(os.getloadavg())

    cpu_percent = 0.0
    rx_bps = 0.0
    tx_bps = 0.0
    if _prev is not None and now > _prev_ts:
        dt = now - _prev_ts
        dtotal = cpu_total - _prev["cpu_total"]
        didle = cpu_idle - _prev["cpu_idle"]
        if dtotal > 0:
            cpu_percent = max(0.0, min(100.0, (1 - didle / dtotal) * 100))
        rx_bps = max(0.0, (rx - _prev["rx"]) / dt)
        tx_bps = max(0.0, (tx - _prev["tx"]) / dt)

    _prev = {"cpu_total": cpu_total, "cpu_idle": cpu_idle, "rx": rx, "tx": tx}
    _prev_ts = now

    mem_percent = (mem_used_mb / mem_total_mb * 100) if mem_total_mb else 0.0
    return HostStats(
        cpu_percent=round(cpu_percent, 1),
        memory_total_mb=mem_total_mb,
        memory_used_mb=mem_used_mb,
        memory_percent=round(mem_percent, 1),
        network_interface=iface,
        network_rx_bytes_per_sec=round(rx_bps, 0),
        network_tx_bytes_per_sec=round(tx_bps, 0),
        load_avg=[round(x, 2) for x in load_avg],
    )
