"""Memory/CPU quotas, hard time limits and cancellation (LIF-0603).

SPDX-License-Identifier: GPL-2.0-only

Home justification: master roadmap section 3 places core code under
``src/``; roadmap/02 (P6) names this slice's surface exactly --
"memory and CPU/GPU quotas", "cancellation, deadlines" for the model
runtime -- and research/17 makes resource caps a correctness
constraint.  LIF-0601 built the PROTOCOL layer (token caps, a
cooperative deadline, ``CancellationToken`` polling) and said so
honestly: it enforces nothing at OS level.  LIF-0403 built executor
confinement (a forked child, scrubbed environment, RLIMIT_CPU /
RLIMIT_FSIZE / RLIMIT_NOFILE / RLIMIT_CORE, a wall bound) for the
fixture action catalog.  This slice is the missing OS-level
enforcement layer that sits under both: one validated quota object,
one supervised-child runner, and one provider wrapper.

What this slice builds:

- ``ResourceQuota``: the validated quota (memory bytes, total CPU
  seconds, wall seconds, CPU bandwidth fraction, pid cap, output
  cap, model-token cap, termination grace).  Validation is
  fail-closed in the LIF-0403 style: a quota outside the module
  ceilings is REFUSED, never silently trimmed.
- ``run_guarded`` / ``GuardedProcess``: run one argv in a child
  process this module spawned itself, in its own session, with
  kernel rlimits applied in the child before exec
  (``RLIMIT_AS`` for memory, ``RLIMIT_CPU`` soft/hard for total CPU,
  ``RLIMIT_FSIZE`` / ``RLIMIT_NOFILE`` / ``RLIMIT_CORE=0`` following
  LIF-0403).  A supervisor loop enforces the HARD wall limit and
  cancellation: on expiry or on the LIF-0601 ``CancellationToken``
  firing, it terminates ONLY its own child's process group
  (SIGTERM, then SIGKILL after the grace window).  There is no API
  that signals an arbitrary PID: a ``GuardedProcess`` can only ever
  signal the process it spawned, whose identity is the live
  ``Popen`` handle it holds.  Outcomes are named honestly --
  ``completed`` / ``failed`` / ``quota_exceeded`` / ``timed_out`` /
  ``cancelled`` -- with the exit code or signal, wall time, and a
  ``RUSAGE_CHILDREN`` usage delta attached.
- ``check_model_request`` / ``run_model_with_quotas``: the bridge to
  the banked LIF-0601 protocol.  A request whose deadline or token
  budget exceeds the quota is refused BEFORE the provider is
  called.  Otherwise the provider runs through ``run_request``
  under a hard wall of ``min(request deadline, quota wall)``: if
  the wall expires, the shared ``CancellationToken`` is cancelled
  and a cooperative provider's cancelled result is returned; an
  uncooperative provider is abandoned (daemon thread) and an
  honest failure result is returned instead.  Model failure still
  cannot block recovery: quota events come back as results or as
  the one named pre-flight refusal, never as a hang.
- The cgroup v2 ADAPTER INTERFACE (``CgroupAdapter`` protocol):
  ``UnavailableCgroupAdapter`` is the default -- it reports itself
  unavailable and refuses to apply anything, so the default path
  writes nothing anywhere.  ``FixtureCgroupAdapter`` implements
  the interface against a FIXTURE directory tree that mimics the
  cgroup v2 file layout (``memory.max``, ``cpu.max``,
  ``pids.max``) so the translation from quota to cgroup values is
  fixture-tested.  It refuses any root that is, or sits under, a
  real system cgroup/sysfs/proc tree.

Honest limits (evidence-status honesty, roadmap section 0):

- Enforcement proven here is RLIMIT-level, on this module's OWN
  fixture child processes only (the LIF-0406 sleeper-fixture
  pattern), on purpleraider only.  ``RLIMIT_AS`` bounds virtual
  address space, which is an honest over-approximation of resident
  memory, not an exact RSS cap; Python children surface AS
  exhaustion as ``MemoryError`` and the runner classifies that as
  a memory quota breach only while a memory quota is in force.
- Real cgroup v2 enforcement (writing ``memory.max`` / ``cpu.max``
  under ``/sys/fs/cgroup``, delegation, privileges) is NOT claimed
  and NOT attempted: no host configuration is changed, no real
  cgroup is written, and no ambient root is used.  The adapter
  interface plus the fixture adapter are the provable level; a
  privileged broker slice is future work.
- CPU bandwidth fraction and the pid cap exist ONLY at the cgroup
  interface level in this slice (``RLIMIT_CPU`` bounds total CPU
  time; there is no unprivileged per-child bandwidth rlimit), and
  no GPU quota is claimed (roadmap/02 lists CPU/GPU quotas; no GPU
  enforcement mechanism is exercised here).
- The provider hard wall cannot kill an uncooperative in-process
  provider thread (Python threads are unkillable); it cancels the
  token, waits one grace window, and then returns without it.
  Process-level hard enforcement applies to child processes.
- Like LIF-0601/LIF-0403, this slice deliberately does NOT touch
  the package ``__init__`` export list: the banking seat unions
  export lists.  Desired exports are flagged in CAMPAIGN_STATE.md.
"""
from __future__ import annotations

import json
import os
import resource
import signal
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Protocol, Tuple

from . import modelprovider as _mp

QUOTA_SCHEMA = "lifthrasir.quota.v0.1"
QUOTA_SCHEMA_VERSION = "0.1"

# Module ceilings: a quota may never widen past these (fail closed).
MIN_MEMORY_BYTES = 32 * 1024 * 1024          # a Python child needs this
MAX_MEMORY_BYTES = 8 * 1024 * 1024 * 1024
MAX_CPU_SECONDS = 300
MAX_WALL_SECONDS = 600.0
MAX_OUTPUT_BYTES = 16 * 1024 * 1024
MAX_PIDS = 4096
MAX_TOTAL_TOKENS = 1_048_576
MAX_GRACE_SECONDS = 10.0

OUTCOMES = frozenset(
    {"completed", "failed", "quota_exceeded", "timed_out", "cancelled"})

# Real system trees the fixture cgroup adapter must never touch.
_FORBIDDEN_CGROUP_ROOTS = ("/sys", "/proc", "/dev", "/run")


class QuotaError(Exception):
    """Base class for all named quota refusals."""


class MalformedQuotaError(QuotaError):
    """Raised when a ResourceQuota or its dict form breaks a rule."""


class QuotaRefusalError(QuotaError):
    """Raised when work is refused BEFORE it starts (pre-flight)."""


class CgroupError(QuotaError):
    """Base class for cgroup adapter refusals."""


class CgroupUnavailableError(CgroupError):
    """Raised when an adapter cannot apply cgroup controls."""


class CgroupPathError(CgroupError):
    """Raised when a cgroup root is a real system tree, not a fixture."""


def _check_int(value: Any, name: str, lo: int, hi: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise MalformedQuotaError(
            f"{name} must be an int, got {type(value).__name__}")
    if not lo <= value <= hi:
        raise MalformedQuotaError(
            f"{name}={value} outside [{lo}, {hi}] ceiling")
    return value


def _check_float(value: Any, name: str, lo: float, hi: float,
                 lo_exclusive: bool = False) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise MalformedQuotaError(
            f"{name} must be a number, got {type(value).__name__}")
    v = float(value)
    if lo_exclusive:
        ok = lo < v <= hi
        rng = f"({lo}, {hi}]"
    else:
        ok = lo <= v <= hi
        rng = f"[{lo}, {hi}]"
    if not ok:
        raise MalformedQuotaError(f"{name}={value} outside {rng} ceiling")
    return v


@dataclass(frozen=True)
class ResourceQuota:
    """One bounded resource budget.  Validated fail-closed."""

    memory_bytes: Optional[int] = None
    cpu_seconds: Optional[int] = None
    wall_seconds: float = 30.0
    cpu_fraction: Optional[float] = None
    max_pids: Optional[int] = None
    max_output_bytes: int = 65_536
    max_total_tokens: Optional[int] = None
    term_grace_s: float = 1.0

    def __post_init__(self) -> None:
        if self.memory_bytes is not None:
            _check_int(self.memory_bytes, "memory_bytes",
                       MIN_MEMORY_BYTES, MAX_MEMORY_BYTES)
        if self.cpu_seconds is not None:
            _check_int(self.cpu_seconds, "cpu_seconds",
                       1, MAX_CPU_SECONDS)
        object.__setattr__(
            self, "wall_seconds",
            _check_float(self.wall_seconds, "wall_seconds",
                         0.0, MAX_WALL_SECONDS, lo_exclusive=True))
        if self.cpu_fraction is not None:
            object.__setattr__(
                self, "cpu_fraction",
                _check_float(self.cpu_fraction, "cpu_fraction",
                             0.0, 1.0, lo_exclusive=True))
        if self.max_pids is not None:
            _check_int(self.max_pids, "max_pids", 1, MAX_PIDS)
        _check_int(self.max_output_bytes, "max_output_bytes",
                   1024, MAX_OUTPUT_BYTES)
        if self.max_total_tokens is not None:
            _check_int(self.max_total_tokens, "max_total_tokens",
                       1, MAX_TOTAL_TOKENS)
        object.__setattr__(
            self, "term_grace_s",
            _check_float(self.term_grace_s, "term_grace_s",
                         0.0, MAX_GRACE_SECONDS))

    def to_dict(self) -> Dict[str, Any]:
        return {
            "schema": QUOTA_SCHEMA,
            "schema_version": QUOTA_SCHEMA_VERSION,
            "memory_bytes": self.memory_bytes,
            "cpu_seconds": self.cpu_seconds,
            "wall_seconds": float(self.wall_seconds),
            "cpu_fraction": self.cpu_fraction,
            "max_pids": self.max_pids,
            "max_output_bytes": self.max_output_bytes,
            "max_total_tokens": self.max_total_tokens,
            "term_grace_s": float(self.term_grace_s),
        }

    @classmethod
    def from_dict(cls, data: Any) -> "ResourceQuota":
        if not isinstance(data, dict):
            raise MalformedQuotaError(
                f"quota must be a mapping, got {type(data).__name__}")
        allowed = {"schema", "schema_version", "memory_bytes",
                   "cpu_seconds", "wall_seconds", "cpu_fraction",
                   "max_pids", "max_output_bytes", "max_total_tokens",
                   "term_grace_s"}
        unknown = sorted(set(data) - allowed)
        if unknown:
            raise MalformedQuotaError(f"unknown quota fields: {unknown}")
        if "schema" in data and data["schema"] != QUOTA_SCHEMA:
            raise MalformedQuotaError(
                f"schema must be {QUOTA_SCHEMA!r}, got {data['schema']!r}")
        if "schema_version" in data and \
                data["schema_version"] != QUOTA_SCHEMA_VERSION:
            raise MalformedQuotaError(
                f"schema_version must be {QUOTA_SCHEMA_VERSION!r}, "
                f"got {data['schema_version']!r}")
        kwargs = {k: data[k] for k in allowed - {"schema", "schema_version"}
                  if k in data}
        return cls(**kwargs)


def quota_from_dict(data: Any) -> ResourceQuota:
    return ResourceQuota.from_dict(data)


# --------------------------------------------------------------------
# Supervised child processes: rlimits + hard wall + cancellation.
# The ONLY signalling surface in this module is GuardedProcess, and
# it can only signal the process group it spawned itself.
# --------------------------------------------------------------------

def _apply_rlimits(quota: ResourceQuota) -> None:
    """preexec_fn: apply kernel limits in the child before exec."""
    if quota.memory_bytes is not None:
        resource.setrlimit(resource.RLIMIT_AS,
                           (quota.memory_bytes, quota.memory_bytes))
    if quota.cpu_seconds is not None:
        resource.setrlimit(resource.RLIMIT_CPU,
                           (quota.cpu_seconds, quota.cpu_seconds + 1))
    resource.setrlimit(resource.RLIMIT_FSIZE,
                       (quota.max_output_bytes * 16,
                        quota.max_output_bytes * 16))
    resource.setrlimit(resource.RLIMIT_NOFILE, (64, 64))
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))


def _rusage_children() -> Tuple[float, int]:
    ru = resource.getrusage(resource.RUSAGE_CHILDREN)
    return (float(ru.ru_utime + ru.ru_stime), int(ru.ru_maxrss))


@dataclass
class GuardedResult:
    outcome: str
    child_pid: int
    exit_code: Optional[int]
    signal_number: Optional[int]
    stdout: str
    stderr: str
    output_truncated: bool
    wall_s: float
    cpu_s: float
    peak_rss_kb: int
    escalated_to_kill: bool
    detail: str
    quota: ResourceQuota

    def to_dict(self) -> Dict[str, Any]:
        return {
            "outcome": self.outcome,
            "child_pid": self.child_pid,
            "exit_code": self.exit_code,
            "signal_number": self.signal_number,
            "stdout": self.stdout,
            "stderr": self.stderr,
            "output_truncated": self.output_truncated,
            "wall_s": round(self.wall_s, 4),
            "cpu_s": round(self.cpu_s, 4),
            "peak_rss_kb": self.peak_rss_kb,
            "escalated_to_kill": self.escalated_to_kill,
            "detail": self.detail,
            "quota": self.quota.to_dict(),
        }


class _Drain:
    """Bounded pipe drainer: keeps the cap, discards the rest."""

    def __init__(self, stream: Any, cap: int) -> None:
        self._stream = stream
        self._cap = cap
        self.buf = bytearray()
        self.truncated = False
        self._thread = threading.Thread(target=self._run, daemon=True)

    def start(self) -> None:
        self._thread.start()

    def _run(self) -> None:
        try:
            while True:
                chunk = self._stream.read(8192)
                if not chunk:
                    break
                room = self._cap - len(self.buf)
                if room > 0:
                    self.buf.extend(chunk[:room])
                    if len(chunk) > room:
                        self.truncated = True
                else:
                    self.truncated = True
        except (OSError, ValueError):
            pass

    def finish(self, timeout: float = 2.0) -> None:
        self._thread.join(timeout)

    def text(self) -> str:
        return bytes(self.buf).decode("utf-8", "replace")


def _validate_argv(argv: Any) -> List[str]:
    if isinstance(argv, (str, bytes)) or \
            not isinstance(argv, (list, tuple)) or not argv:
        raise QuotaRefusalError(
            "argv must be a non-empty list of strings (no shell strings)")
    out = []
    for item in argv:
        if not isinstance(item, str) or not item or "\x00" in item:
            raise QuotaRefusalError(
                f"argv entries must be non-empty strings, got {item!r}")
        out.append(item)
    return out


class GuardedProcess:
    """One supervised child, spawned by this module and no one else.

    Cancellation terminates this process's own group only: the
    child was started in a new session, so its process-group id is
    its own pid, held in the live ``Popen`` handle.  There is no
    way to aim this object at a process it did not spawn.
    """

    def __init__(self, argv: List[str], quota: ResourceQuota,
                 cancel_token: Optional[Any] = None,
                 cwd: Optional[str] = None) -> None:
        self.argv = _validate_argv(argv)
        self.quota = quota
        self._token = cancel_token
        self._cpu_before, _ = _rusage_children()
        self._started = time.monotonic()
        env = {"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8"}
        self._proc = subprocess.Popen(
            self.argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            env=env, cwd=cwd, start_new_session=True,
            preexec_fn=lambda: _apply_rlimits(quota))
        cap = quota.max_output_bytes
        self._out = _Drain(self._proc.stdout, cap)
        self._err = _Drain(self._proc.stderr, cap)
        self._out.start()
        self._err.start()
        self._stop_reason: Optional[str] = None
        self._escalated = False
        self._result: Optional[GuardedResult] = None

    @property
    def pid(self) -> int:
        return int(self._proc.pid)

    def poll(self) -> Optional[int]:
        return self._proc.poll()

    def cancel(self, reason: str = "cancelled by caller") -> bool:
        """Terminate ONLY this object's own child process group."""
        if self._proc.poll() is not None:
            return False
        if self._stop_reason is None:
            self._stop_reason = reason
        self._terminate()
        return True

    def _terminate(self) -> None:
        if self._proc.poll() is not None:
            return
        try:
            os.killpg(self._proc.pid, signal.SIGTERM)
        except (ProcessLookupError, PermissionError):
            return
        deadline = time.monotonic() + self.quota.term_grace_s
        while time.monotonic() < deadline:
            if self._proc.poll() is not None:
                return
            time.sleep(0.01)
        if self._proc.poll() is None:
            self._escalated = True
            try:
                os.killpg(self._proc.pid, signal.SIGKILL)
            except (ProcessLookupError, PermissionError):
                pass

    def wait(self) -> GuardedResult:
        if self._result is not None:
            return self._result
        deadline = self._started + self.quota.wall_seconds
        while True:
            rc = self._proc.poll()
            if rc is not None:
                break
            if self._token is not None and \
                    getattr(self._token, "cancelled", False):
                self._stop_reason = "cancelled via CancellationToken"
                self._terminate()
                break
            if time.monotonic() >= deadline:
                self._stop_reason = "wall time limit exceeded"
                self._terminate()
                break
            time.sleep(0.01)
        rc = self._proc.wait()
        self._out.finish()
        self._err.finish()
        wall = time.monotonic() - self._started
        cpu_after, peak_kb = _rusage_children()
        cpu_s = max(0.0, cpu_after - self._cpu_before)
        stdout = self._out.text()
        stderr = self._err.text()
        sig = -rc if rc is not None and rc < 0 else None
        outcome, detail = self._classify(rc, sig, stderr)
        self._result = GuardedResult(
            outcome=outcome, child_pid=int(self._proc.pid),
            exit_code=rc if sig is None else None, signal_number=sig,
            stdout=stdout, stderr=stderr,
            output_truncated=bool(self._out.truncated or
                                   self._err.truncated),
            wall_s=wall, cpu_s=cpu_s, peak_rss_kb=peak_kb,
            escalated_to_kill=self._escalated, detail=detail,
            quota=self.quota)
        return self._result

    def _classify(self, rc: Optional[int], sig: Optional[int],
                  stderr: str) -> Tuple[str, str]:
        if self._stop_reason is not None:
            if "wall" in self._stop_reason:
                return ("timed_out",
                        f"{self._stop_reason}: terminated after "
                        f"{self.quota.wall_seconds}s wall limit")
            return ("cancelled", self._stop_reason)
        if sig is not None and sig == int(signal.SIGXCPU):
            return ("quota_exceeded",
                    f"cpu quota: child killed by SIGXCPU at "
                    f"{self.quota.cpu_seconds}s CPU limit (RLIMIT_CPU)")
        if sig is not None and sig == int(signal.SIGKILL) and \
                self.quota.cpu_seconds is not None:
            return ("quota_exceeded",
                    "cpu quota: child killed by SIGKILL on the "
                    "RLIMIT_CPU hard limit")
        if rc not in (0, None) and self.quota.memory_bytes is not None \
                and "MemoryError" in stderr:
            return ("quota_exceeded",
                    f"memory quota: child hit MemoryError under the "
                    f"{self.quota.memory_bytes}-byte RLIMIT_AS limit")
        if rc == 0:
            return ("completed", "child exited 0 within quota")
        return ("failed",
                f"child exited rc={rc} signal={sig} within quota; "
                f"failure is the child's own, not a quota event")


def start_guarded(argv: List[str], quota: ResourceQuota,
                  cancel_token: Optional[Any] = None,
                  cwd: Optional[str] = None) -> GuardedProcess:
    """Spawn a supervised child; the caller drives cancel/wait."""
    if not isinstance(quota, ResourceQuota):
        raise QuotaRefusalError(
            f"quota must be a ResourceQuota, got {type(quota).__name__}")
    return GuardedProcess(argv, quota, cancel_token=cancel_token,
                          cwd=cwd)


def run_guarded(argv: List[str], quota: ResourceQuota,
                cancel_token: Optional[Any] = None,
                cwd: Optional[str] = None) -> GuardedResult:
    """Spawn, supervise and reap one child under ``quota``."""
    proc = start_guarded(argv, quota, cancel_token=cancel_token,
                         cwd=cwd)
    return proc.wait()


# --------------------------------------------------------------------
# Cgroup v2 adapter interface: fixture level only (see module docs).
# --------------------------------------------------------------------

@dataclass(frozen=True)
class CgroupReceipt:
    adapter: str
    group: str
    values: Dict[str, str]

    def to_dict(self) -> Dict[str, Any]:
        return {"adapter": self.adapter, "group": self.group,
                "values": dict(self.values)}


class CgroupAdapter(Protocol):
    """The cgroup v2 control interface a privileged broker would fill."""

    name: str

    def available(self) -> bool:
        ...

    def apply(self, group: str, quota: ResourceQuota) -> CgroupReceipt:
        ...


def cgroup_values(quota: ResourceQuota) -> Dict[str, str]:
    """Translate a quota into cgroup v2 file values (pure function)."""
    values = {
        "memory.max": (str(quota.memory_bytes)
                       if quota.memory_bytes is not None else "max"),
        "cpu.max": ("max 100000" if quota.cpu_fraction is None else
                    f"{max(1000, round(quota.cpu_fraction * 100000))}"
                    " 100000"),
        "pids.max": (str(quota.max_pids)
                     if quota.max_pids is not None else "max"),
    }
    return values


class UnavailableCgroupAdapter:
    """Default adapter: no cgroup access claimed, nothing written."""

    name = "unavailable"

    def available(self) -> bool:
        return False

    def apply(self, group: str, quota: ResourceQuota) -> CgroupReceipt:
        raise CgroupUnavailableError(
            "no cgroup adapter is configured in this slice: real "
            "cgroup v2 enforcement needs a privileged broker and is "
            "not claimed (see module limitations)")


class FixtureCgroupAdapter:
    """Cgroup interface exercised against a fixture directory tree.

    ``root`` mimics a cgroupfs mount: apply() creates
    ``<root>/<group>/`` and writes the v2 control files there.
    Any root that is or sits under a real system tree is refused,
    so this adapter can never write a real cgroup.
    """

    name = "fixture"

    def __init__(self, root: Any) -> None:
        resolved = str(Path(root).resolve())
        if resolved == "/":
            raise CgroupPathError(
                "cgroup fixture root '/' is the filesystem root: "
                "refusing; real cgroup writes are out of scope for "
                "this slice")
        for forbidden in _FORBIDDEN_CGROUP_ROOTS:
            if resolved == forbidden or \
                    resolved.startswith(forbidden + "/"):
                raise CgroupPathError(
                    f"cgroup fixture root {resolved!r} is a real "
                    f"system tree ({forbidden}): refusing; real "
                    f"cgroup writes are out of scope for this slice")
        self.root = Path(root)

    def available(self) -> bool:
        return True

    def apply(self, group: str, quota: ResourceQuota) -> CgroupReceipt:
        if not isinstance(group, str) or not group or \
                "/" in group or group in (".", "..") or "\x00" in group:
            raise CgroupPathError(
                f"group must be one plain name, got {group!r}")
        if not isinstance(quota, ResourceQuota):
            raise CgroupError(
                f"quota must be a ResourceQuota, got "
                f"{type(quota).__name__}")
        values = cgroup_values(quota)
        target = self.root / group
        target.mkdir(parents=True, exist_ok=True)
        for filename, value in values.items():
            (target / filename).write_text(value + "\n",
                                           encoding="utf-8")
        readback = {fn: (target / fn).read_text(
            encoding="utf-8").strip() for fn in values}
        if readback != values:
            raise CgroupError(
                f"fixture cgroup write readback mismatch: {readback!r} "
                f"!= {values!r}")
        return CgroupReceipt(adapter=self.name, group=group,
                             values=readback)


# --------------------------------------------------------------------
# Bridge to the banked LIF-0601 model-provider protocol.
# --------------------------------------------------------------------

def check_model_request(request: Any, quota: ResourceQuota) -> None:
    """Refuse a model request that exceeds the quota, pre-flight.

    Raises QuotaRefusalError BEFORE any provider is called when the
    request deadline exceeds the quota wall, or when its declared
    token budget exceeds the quota token cap.  A malformed request
    raises the provider layer's own MalformedRequestError.
    """
    if not isinstance(request, _mp.ModelRequest):
        raise _mp.MalformedRequestError(
            f"request must be a ModelRequest, got "
            f"{type(request).__name__}")
    if not isinstance(quota, ResourceQuota):
        raise QuotaRefusalError(
            f"quota must be a ResourceQuota, got {type(quota).__name__}")
    if float(request.deadline_s) > float(quota.wall_seconds):
        raise QuotaRefusalError(
            f"request deadline {request.deadline_s}s exceeds the "
            f"quota wall of {quota.wall_seconds}s")
    if quota.max_total_tokens is not None:
        total = int(request.max_input_tokens) + \
            int(request.max_output_tokens)
        if total > quota.max_total_tokens:
            raise QuotaRefusalError(
                f"request token budget {total} (input "
                f"{request.max_input_tokens} + output "
                f"{request.max_output_tokens}) exceeds the quota "
                f"token cap of {quota.max_total_tokens}")


def run_model_with_quotas(provider: Any, request: Any,
                          quota: ResourceQuota,
                          cancel_token: Optional[Any] = None) -> Any:
    """Run one provider request under a hard quota wall.

    Pre-flight refusals raise QuotaRefusalError (no provider call).
    Every provider-side event returns an mp.ModelResult via
    run_request; if the hard wall expires first, the token is
    cancelled and a cooperative provider's cancelled result is
    returned, while an uncooperative provider is abandoned after
    one grace window and reported as an honest failure result.
    """
    check_model_request(request, quota)
    token = cancel_token if cancel_token is not None \
        else _mp.CancellationToken()
    wall = min(float(request.deadline_s), float(quota.wall_seconds))
    box: Dict[str, Any] = {}

    def _target() -> None:
        box["result"] = _mp.run_request(provider, request, token)

    thread = threading.Thread(target=_target, daemon=True)
    thread.start()
    thread.join(wall)
    if not thread.is_alive():
        return box["result"]
    token.cancel()
    thread.join(max(0.5, float(quota.term_grace_s)))
    if not thread.is_alive() and "result" in box:
        return box["result"]
    provider_name = getattr(provider, "name", None) or "unknown"
    if not isinstance(provider_name, str):
        provider_name = "unknown"
    return _mp.ModelResult(
        task_id=request.task_id, provider_name=provider_name,
        model_id=request.model_id,
        model_revision=request.model_revision, outcome="failed",
        input_tokens=request.input_tokens,
        error=(f"quota wall of {wall}s expired and the provider "
               f"did not honour cancellation within the grace "
               f"window; the in-process provider thread was "
               f"abandoned (threads cannot be killed) -- process-"
               f"level enforcement is run_guarded"),
        performed_inference=False, provenance_hash="")


__all__ = [
    "QUOTA_SCHEMA", "QUOTA_SCHEMA_VERSION",
    "MIN_MEMORY_BYTES", "MAX_MEMORY_BYTES", "MAX_CPU_SECONDS",
    "MAX_WALL_SECONDS", "MAX_OUTPUT_BYTES", "MAX_PIDS",
    "MAX_TOTAL_TOKENS", "MAX_GRACE_SECONDS", "OUTCOMES",
    "QuotaError", "MalformedQuotaError", "QuotaRefusalError",
    "CgroupError", "CgroupUnavailableError", "CgroupPathError",
    "ResourceQuota", "quota_from_dict",
    "GuardedResult", "GuardedProcess", "start_guarded", "run_guarded",
    "CgroupReceipt", "CgroupAdapter", "cgroup_values",
    "UnavailableCgroupAdapter", "FixtureCgroupAdapter",
    "check_model_request", "run_model_with_quotas",
]
