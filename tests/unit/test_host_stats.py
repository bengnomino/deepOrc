"""Tests for VPS host stats."""

from orchestrator.services import host_stats


def test_collect_host_stats_returns_shape(monkeypatch):
    monkeypatch.setattr(host_stats, "_prev", None)
    monkeypatch.setattr(host_stats, "_prev_ts", 0.0)
    monkeypatch.setattr(host_stats, "_read_cpu_times", lambda: (1000, 800))
    monkeypatch.setattr(host_stats, "_read_mem", lambda: (4096, 1024))
    monkeypatch.setattr(host_stats, "_read_net", lambda: ("eth0", 1_000_000, 500_000))
    monkeypatch.setattr(host_stats.os, "getloadavg", lambda: (0.1, 0.2, 0.3))

    first = host_stats.collect_host_stats()
    assert first.cpu_percent == 0.0
    assert first.memory_total_mb == 4096
    assert first.memory_used_mb == 1024
    assert first.network_interface == "eth0"

    monkeypatch.setattr(host_stats, "_read_cpu_times", lambda: (1100, 840))
    monkeypatch.setattr(host_stats, "_read_net", lambda: ("eth0", 1_125_000, 550_000))
    monkeypatch.setattr(host_stats.time, "time", lambda: host_stats._prev_ts + 1.0)

    second = host_stats.collect_host_stats()
    assert second.cpu_percent == 60.0
    assert second.network_rx_bytes_per_sec == 125_000
    assert second.network_tx_bytes_per_sec == 50_000


def test_read_mem_matches_free_used_column(tmp_path, monkeypatch):
    meminfo = tmp_path / "meminfo"
    meminfo.write_text(
        "MemTotal:        4015952 kB\n"
        "MemFree:         1298208 kB\n"
        "MemAvailable:    3380108 kB\n"
        "Buffers:           94596 kB\n"
        "Cached:          2138844 kB\n"
        "SReclaimable:     114124 kB\n"
        "Active:           372664 kB\n"
        "AnonPages:        259828 kB\n"
        "Shmem:              3944 kB\n",
        encoding="utf-8",
    )
    real_open = open

    def fake_open(path, *args, **kwargs):
        if path == "/proc/meminfo":
            return real_open(meminfo, *args, **kwargs)
        return real_open(path, *args, **kwargs)

    monkeypatch.setattr("builtins.open", fake_open)

    total_mb, used_mb = host_stats._read_mem()

    assert total_mb == 3921
    # procps/free: total - free - buffers - cached - sreclaimable
    assert used_mb == 361
    assert used_mb < 622  # total - MemAvailable overstates
