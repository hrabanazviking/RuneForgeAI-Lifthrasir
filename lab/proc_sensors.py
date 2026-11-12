# SPDX-License-Identifier: GPL-2.0-only
"""LIF-0203: /proc and cgroup CPU, memory and PSI sensors (Heimdall
observer, read-only) with rate limiting.

Parses recorded /proc and cgroup v2 text (fixtures) into typed
readings: aggregate + per-CPU times from /proc/stat, memory figures
from /proc/meminfo, PSI pressure from /proc/pressure/{cpu,memory,io},
and cgroup v2 cpu.stat / memory.current / memory.max values.

The sensors OBSERVE ONLY: this module opens nothing for writing,
issues no commands, and mutates no system state. Tests run purely
against committed fixtures and never depend on the host's live
/proc values; read_live_texts() is an optional read-only helper
that no test calls.

Rate limiting (documented behaviour): a ProcSensor refuses to
re-read more often than its configured minimum interval. A poll
that arrives too early is SERVED THE LAST READING with
rate_limited=True on the returned report (it is not refused with
an exception, and it never re-parses the new input). The first
poll is never rate limited. Time comes from an injectable clock
so tests are deterministic.

Honesty rules: a value absent from the source stays None - the
sensor never invents numbers (a missing MemAvailable is None, not
total-minus-free; a cgroup memory.max of the literal word max
means unlimited and is recorded as None with max_is_unlimited).
Malformed lines are skipped and counted, never raised.

Home justification (master roadmap section 3 + ADR-0002, following
the LIF-0202 precedent): sensors are rapid-prototype
observation-plane code, so they live in lab/ (Python for the rapid
lab and test harness) until their contracts stabilize.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field, replace
from pathlib import Path

SCHEMA_VERSION = "0.1"


@dataclass(frozen=True)
class CpuTimes:
    label: str
    user: int
    nice: int
    system: int
    idle: int
    iowait: int = 0
    irq: int = 0
    softirq: int = 0
    steal: int = 0
    guest: int = 0
    guest_nice: int = 0

    @property
    def total(self) -> int:
        return (self.user + self.nice + self.system + self.idle
                + self.iowait + self.irq + self.softirq + self.steal
                + self.guest + self.guest_nice)

    @property
    def idle_all(self) -> int:
        return self.idle + self.iowait


def cpu_busy_percent(prev: CpuTimes, cur: CpuTimes):
    """Busy percent between two aggregate readings, or None when
    the counters did not advance (never invents a value)."""
    dt = cur.total - prev.total
    if dt <= 0:
        return None
    di = cur.idle_all - prev.idle_all
    return round(100.0 * (dt - di) / dt, 4)


@dataclass
class CpuReading:
    aggregate: object = None
    per_cpu: list = field(default_factory=list)
    skipped_lines: int = 0


def parse_proc_stat(text: str) -> CpuReading:
    reading = CpuReading()
    if not text:
        return reading
    for raw in text.splitlines():
        parts = raw.split()
        if not parts or not parts[0].startswith("cpu"):
            continue
        label = parts[0]
        if label != "cpu" and not label[3:].isdigit():
            continue
        try:
            nums = [int(p) for p in parts[1:]]
        except ValueError:
            reading.skipped_lines += 1
            continue
        if len(nums) < 4:
            reading.skipped_lines += 1
            continue
        nums = (nums + [0] * 10)[:10]
        times = CpuTimes(label, *nums)
        if label == "cpu":
            reading.aggregate = times
        else:
            reading.per_cpu.append(times)
    return reading


_MEM_KEYS = {
    "MemTotal": "mem_total_kb", "MemFree": "mem_free_kb",
    "MemAvailable": "mem_available_kb", "Buffers": "buffers_kb",
    "Cached": "cached_kb", "SwapTotal": "swap_total_kb",
    "SwapFree": "swap_free_kb", "SwapCached": "swap_cached_kb",
    "Shmem": "shmem_kb", "SReclaimable": "sreclaimable_kb",
}


@dataclass
class MemReading:
    mem_total_kb: object = None
    mem_free_kb: object = None
    mem_available_kb: object = None
    buffers_kb: object = None
    cached_kb: object = None
    swap_total_kb: object = None
    swap_free_kb: object = None
    swap_cached_kb: object = None
    shmem_kb: object = None
    sreclaimable_kb: object = None
    skipped_lines: int = 0


def parse_meminfo(text: str) -> MemReading:
    reading = MemReading()
    if not text:
        return reading
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        if ":" not in line:
            reading.skipped_lines += 1
            continue
        key, _, rest = line.partition(":")
        key = key.strip()
        if key not in _MEM_KEYS:
            continue
        tokens = rest.split()
        try:
            value = int(tokens[0])
        except (ValueError, IndexError):
            reading.skipped_lines += 1
            continue
        setattr(reading, _MEM_KEYS[key], value)
    return reading


@dataclass(frozen=True)
class PressureLine:
    avg10: float
    avg60: float
    avg300: float
    total_us: int


@dataclass
class PsiReading:
    resource: str
    some: object = None
    full: object = None
    skipped_lines: int = 0


def parse_pressure(text: str, resource: str = "") -> PsiReading:
    reading = PsiReading(resource=resource)
    if not text:
        return reading
    for raw in text.splitlines():
        parts = raw.split()
        if not parts or parts[0] not in ("some", "full"):
            if raw.strip():
                reading.skipped_lines += 1
            continue
        kv = {}
        ok = True
        for tok in parts[1:]:
            if "=" not in tok:
                ok = False
                break
            k, _, v = tok.partition("=")
            kv[k] = v
        try:
            line = PressureLine(avg10=float(kv["avg10"]),
                                avg60=float(kv["avg60"]),
                                avg300=float(kv["avg300"]),
                                total_us=int(kv["total"]))
        except (KeyError, ValueError):
            ok = False
        if not ok:
            reading.skipped_lines += 1
            continue
        if parts[0] == "some":
            reading.some = line
        else:
            reading.full = line
    return reading


@dataclass
class CgroupCpuReading:
    usage_usec: object = None
    user_usec: object = None
    system_usec: object = None
    nr_periods: object = None
    nr_throttled: object = None
    throttled_usec: object = None
    skipped_lines: int = 0


_CG_CPU_KEYS = frozenset(["usage_usec", "user_usec", "system_usec",
                          "nr_periods", "nr_throttled", "throttled_usec"])


def parse_cgroup_cpu_stat(text: str) -> CgroupCpuReading:
    reading = CgroupCpuReading()
    if not text:
        return reading
    for raw in text.splitlines():
        parts = raw.split()
        if not parts:
            continue
        if len(parts) != 2 or parts[0] not in _CG_CPU_KEYS:
            if parts[0] in _CG_CPU_KEYS or len(parts) != 2:
                reading.skipped_lines += 1
            continue
        try:
            setattr(reading, parts[0], int(parts[1]))
        except ValueError:
            reading.skipped_lines += 1
    return reading


@dataclass
class CgroupMemoryReading:
    current_bytes: object = None
    max_bytes: object = None
    max_is_unlimited: bool = False
    skipped_lines: int = 0


def parse_cgroup_memory(current_text=None, max_text=None) -> CgroupMemoryReading:
    reading = CgroupMemoryReading()
    if current_text is not None:
        tok = current_text.strip()
        try:
            reading.current_bytes = int(tok)
        except ValueError:
            if tok:
                reading.skipped_lines += 1
    if max_text is not None:
        tok = max_text.strip()
        if tok == "max":
            reading.max_is_unlimited = True
        else:
            try:
                reading.max_bytes = int(tok)
            except ValueError:
                if tok:
                    reading.skipped_lines += 1
    return reading


@dataclass
class SensorReport:
    cpu: object = None
    memory: object = None
    psi: dict = field(default_factory=dict)
    cgroup_cpu: object = None
    cgroup_memory: object = None
    rate_limited: bool = False
    schema_version: str = SCHEMA_VERSION

    @property
    def skipped_lines(self) -> int:
        total = 0
        for part in (self.cpu, self.memory, self.cgroup_cpu,
                     self.cgroup_memory):
            if part is not None:
                total += getattr(part, "skipped_lines", 0)
        for r in self.psi.values():
            total += r.skipped_lines
        return total


class RateLimiter:
    """Minimum-interval limiter with an injectable clock."""

    def __init__(self, min_interval_seconds: float, clock=None):
        if min_interval_seconds < 0:
            raise ValueError("min_interval_seconds must be >= 0")
        self.min_interval = float(min_interval_seconds)
        self._clock = clock or time.monotonic
        self._last = None

    def check(self) -> bool:
        """True when a fresh read is allowed (and records it)."""
        now = self._clock()
        if self._last is not None and (now - self._last) < self.min_interval:
            return False
        self._last = now
        return True


class ProcSensor:
    """Rate-limited fixture/live-text sensor. See module docstring
    for the documented rate-limit behaviour: too-early polls are
    served the last reading with rate_limited=True."""

    def __init__(self, min_interval_seconds: float = 1.0, clock=None):
        self.limiter = RateLimiter(min_interval_seconds, clock=clock)
        self._last_report = None

    def poll(self, stat_text=None, meminfo_text=None, pressure_texts=None,
             cgroup_cpu_text=None, cgroup_current_text=None,
             cgroup_max_text=None) -> SensorReport:
        if self._last_report is not None and not self.limiter.check():
            return replace(self._last_report, rate_limited=True)
        if self._last_report is None:
            self.limiter.check()
        psi = {}
        for resource, text in (pressure_texts or {}).items():
            psi[resource] = parse_pressure(text, resource=resource)
        report = SensorReport(
            cpu=parse_proc_stat(stat_text) if stat_text is not None else None,
            memory=(parse_meminfo(meminfo_text)
                    if meminfo_text is not None else None),
            psi=psi,
            cgroup_cpu=(parse_cgroup_cpu_stat(cgroup_cpu_text)
                        if cgroup_cpu_text is not None else None),
            cgroup_memory=(parse_cgroup_memory(cgroup_current_text,
                                               cgroup_max_text)
                           if (cgroup_current_text is not None
                               or cgroup_max_text is not None) else None),
        )
        self._last_report = report
        return report


def read_live_texts(cgroup_dir: str = "/sys/fs/cgroup"):
    """Optional READ-ONLY live helper: reads the host /proc and
    cgroup v2 files as text for ProcSensor.poll. Never called by
    tests; opens files for reading only; missing files yield None."""
    def _read(path):
        try:
            return Path(path).read_text(encoding="utf-8")
        except OSError:
            return None
    base = Path(cgroup_dir)
    return {
        "stat_text": _read("/proc/stat"),
        "meminfo_text": _read("/proc/meminfo"),
        "pressure_texts": {
            "cpu": _read("/proc/pressure/cpu"),
            "memory": _read("/proc/pressure/memory"),
            "io": _read("/proc/pressure/io"),
        },
        "cgroup_cpu_text": _read(base / "cpu.stat"),
        "cgroup_current_text": _read(base / "memory.current"),
        "cgroup_max_text": _read(base / "memory.max"),
    }
