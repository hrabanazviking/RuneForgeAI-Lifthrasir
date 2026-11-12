# SPDX-License-Identifier: GPL-2.0-only
"""LIF-0203 /proc + cgroup sensor tests (fixture-based, read-only).

Scope: recorded fixture text only. No test reads the host's live
/proc or cgroup values; read_live_texts is never called here.
Rate-limit behaviour (documented in lab/proc_sensors.py): a poll
inside the minimum interval is served the LAST reading with
rate_limited=True; it does not re-parse new input.
"""
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from lab import proc_sensors as ps  # noqa: E402

FIX = REPO / "tests" / "fixtures" / "lif0203"


def _read(name):
    return (FIX / name).read_text(encoding="utf-8")


class FakeClock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


def test_proc_stat_aggregate_and_per_cpu():
    r = ps.parse_proc_stat(_read("proc_stat.txt"))
    assert r.aggregate.user == 1000 and r.aggregate.idle == 8000
    assert r.aggregate.total == 9650
    assert [c.label for c in r.per_cpu] == ["cpu0", "cpu1"]
    assert r.per_cpu[1].system == 200
    assert r.skipped_lines == 0


def test_cpu_busy_percent_between_readings():
    a = ps.parse_proc_stat(_read("proc_stat.txt")).aggregate
    b = ps.parse_proc_stat(_read("proc_stat_t2.txt")).aggregate
    # dt=1000, idle delta=800 -> busy 20.0 percent exactly.
    assert ps.cpu_busy_percent(a, b) == 20.0
    assert ps.cpu_busy_percent(a, a) is None


def test_meminfo_parsing_exact_values():
    m = ps.parse_meminfo(_read("proc_meminfo.txt"))
    assert m.mem_total_kb == 16384000
    assert m.mem_available_kb == 12288000
    assert m.swap_total_kb == 4194304 and m.swap_free_kb == 4194304
    assert m.skipped_lines == 0


def test_meminfo_absent_field_stays_none_not_invented():
    m = ps.parse_meminfo("MemTotal:       16384000 kB\n")
    assert m.mem_total_kb == 16384000
    assert m.mem_available_kb is None
    assert m.mem_free_kb is None


def test_psi_values_carried_through_exactly():
    cpu = ps.parse_pressure(_read("pressure_cpu.txt"), resource="cpu")
    assert cpu.some.avg10 == 1.50 and cpu.some.total_us == 1234567
    assert cpu.full.avg10 == 0.0 and cpu.full.total_us == 0
    mem = ps.parse_pressure(_read("pressure_memory.txt"),
                            resource="memory")
    assert mem.some.avg10 == 2.25 and mem.full.total_us == 5432109
    io = ps.parse_pressure(_read("pressure_io.txt"), resource="io")
    assert io.full.avg300 == 0.01 and io.some.total_us == 987654


def test_cgroup_cpu_stat_parsing():
    c = ps.parse_cgroup_cpu_stat(_read("cgroup_cpu_stat.txt"))
    assert c.usage_usec == 5000000 and c.user_usec == 4000000
    assert c.nr_throttled == 7 and c.throttled_usec == 9999
    assert c.skipped_lines == 0


def test_cgroup_memory_numeric_and_unlimited():
    m = ps.parse_cgroup_memory(_read("cgroup_memory_current.txt"),
                               _read("cgroup_memory_max.txt"))
    assert m.current_bytes == 2147483648 and m.max_bytes == 4294967296
    assert m.max_is_unlimited is False
    u = ps.parse_cgroup_memory(_read("cgroup_memory_current.txt"),
                               _read("cgroup_memory_max_unlimited.txt"))
    assert u.max_bytes is None and u.max_is_unlimited is True


def test_malformed_lines_skipped_and_counted():
    s = ps.parse_proc_stat(_read("proc_stat_malformed.txt"))
    assert s.aggregate.user == 1000
    assert [c.label for c in s.per_cpu] == ["cpu2"]
    assert s.skipped_lines == 2
    m = ps.parse_meminfo(_read("proc_meminfo_malformed.txt"))
    assert m.mem_total_kb == 16384000 and m.mem_free_kb is None
    assert m.mem_available_kb == 12288000
    assert m.skipped_lines == 2
    p = ps.parse_pressure(_read("pressure_malformed.txt"))
    assert p.some is None and p.full.total_us == 42
    assert p.skipped_lines == 2
    c = ps.parse_cgroup_cpu_stat(_read("cgroup_cpu_stat_malformed.txt"))
    assert c.usage_usec == 5000000 and c.user_usec is None
    assert c.skipped_lines == 2


def test_empty_input_never_invents():
    assert ps.parse_proc_stat("").aggregate is None
    assert ps.parse_meminfo("").mem_total_kb is None
    assert ps.parse_pressure("").some is None
    assert ps.parse_cgroup_cpu_stat("").usage_usec is None


def test_rate_limit_serves_last_reading_flagged():
    clock = FakeClock()
    sensor = ps.ProcSensor(min_interval_seconds=5.0, clock=clock)
    first = sensor.poll(stat_text=_read("proc_stat.txt"))
    assert first.rate_limited is False
    assert first.cpu.aggregate.user == 1000
    clock.now += 1.0
    second = sensor.poll(stat_text=_read("proc_stat_t2.txt"))
    assert second.rate_limited is True
    # Served the LAST reading: t2 values must NOT appear.
    assert second.cpu.aggregate.user == 1000
    clock.now += 10.0
    third = sensor.poll(stat_text=_read("proc_stat_t2.txt"))
    assert third.rate_limited is False
    assert third.cpu.aggregate.user == 1100


def test_rate_limiter_unit():
    clock = FakeClock()
    lim = ps.RateLimiter(2.0, clock=clock)
    assert lim.check() is True
    assert lim.check() is False
    clock.now += 2.0
    assert lim.check() is True


def test_full_poll_report_and_skipped_total():
    clock = FakeClock()
    sensor = ps.ProcSensor(min_interval_seconds=0.0, clock=clock)
    rep = sensor.poll(
        stat_text=_read("proc_stat.txt"),
        meminfo_text=_read("proc_meminfo.txt"),
        pressure_texts={"cpu": _read("pressure_cpu.txt"),
                        "memory": _read("pressure_memory.txt"),
                        "io": _read("pressure_io.txt")},
        cgroup_cpu_text=_read("cgroup_cpu_stat.txt"),
        cgroup_current_text=_read("cgroup_memory_current.txt"),
        cgroup_max_text=_read("cgroup_memory_max.txt"),
    )
    assert rep.rate_limited is False and rep.schema_version == "0.1"
    assert rep.psi["memory"].full.total_us == 5432109
    assert rep.cgroup_memory.max_bytes == 4294967296
    assert rep.skipped_lines == 0
