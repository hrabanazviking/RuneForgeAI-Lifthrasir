"""Separate-process, limited-permission executor confinement (LIF-0403).

SPDX-License-Identifier: GPL-2.0-only

Home: ADR-0002 fixes the execution plane as ``lifthrasir-broker``, a
separate minimally privileged process, and master roadmap section 3
places core code under ``src/``.  The executor mechanism therefore
lives beside the other core modules in ``src/lifthrasir/``.  This
module ships WITHOUT editing ``__init__.py`` on purpose: the parallel
P4 slices (LIF-0401 team-04, LIF-0402 team-05) and earlier slices own
package export lists on their branches; importing
``lifthrasir.executor`` directly always works and can never conflict
with their merges.  The seat may add exports at banking time.

Contract alignment (design against the backlog, not against files
that do not exist yet):

* LIF-0401 (in flight) defines a typed action catalog and a narrow
  executor interface.  This slice confines whatever catalog lands:
  it accepts only actions named in the confinement profile's
  allowlist, and the verbs it can actually run here are explicit
  ``fixture.*`` verbs (echo, read/write/list inside a sandbox,
  sleep, crash, limit report).  They are mechanism proofs, NOT host
  repair verbs; a real catalog verb plugs in behind the same gate.
* LIF-0402 (in flight) makes policy decisions from user identity,
  resource, risk level and preconditions.  This slice consumes a
  decision in exactly those terms: a ``PolicyGrant`` naming the
  identity, the exact action, the exact resource (target), a risk
  level and an expiry, with decision ``allow``.  No grant, an expired
  grant, a grant for another action or resource, or a grant above
  the fixture risk ceiling is refused BEFORE any process is spawned.
  When LIF-0402 lands, its decision object only needs to be adapted
  into this shape; nothing here mints policy.

Confinement proven here (fixture / process-boundary level only):

* Separate process: work runs in a forked child process, never in
  the caller.  The result carries the child PID, which always
  differs from the caller's.  A crashing child is reported as a
  failed execution and the caller survives to execute again.
* Filesystem: every target is resolved against the profile's
  sandbox root and re-checked after resolution, so ``..`` escapes,
  absolute host paths and symlink escapes are refused by name.
* Permissions: the child runs with a scrubbed environment (only
  PATH and LANG survive), its working directory is the sandbox
  root, and kernel resource limits are applied in the child
  (RLIMIT_CPU, RLIMIT_FSIZE, RLIMIT_NOFILE, RLIMIT_CORE=0).
* Bounds: wall-clock timeout (the child is terminated on expiry),
  output-size cap, and profile ceilings a profile may not widen
  past (a profile asking for network access, a system-root
  sandbox, or limits above the ceilings is refused).

Honest limits (evidence-status honesty, roadmap section 0):

* No uid/gid change is made or claimed: dropping to another user
  needs host account configuration, which this slice is forbidden
  to touch.  Separation here is process, filesystem, environment
  and rlimit confinement at the same uid, nothing more.
* Memory is bounded indirectly (output and file caps), not by a
  kernel memory rlimit: RLIMIT_AS/RLIMIT_DATA on an already-loaded
  interpreter would measure the interpreter, not the action, so
  claiming one would be dishonest.  Named as future broker work.
* No host permission, sudoers entry or live process is changed;
  no network is used; unknown or untested is NOT verified.
"""
from __future__ import annotations

import multiprocessing as mp
import os
import resource
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, Optional

# The only verbs this fixture executor can run.  Real repair verbs
# arrive with the LIF-0401 catalog and must be added to a profile's
# allowlist explicitly; nothing unlisted can run.
KNOWN_ACTIONS = frozenset({
    "fixture.echo",
    "fixture.read_text",
    "fixture.write_text",
    "fixture.list_dir",
    "fixture.sleep",
    "fixture.crash",
    "fixture.report_limits",
})

# A confinement profile may never widen past these ceilings.
MAX_WALL_SECONDS = 60.0
MAX_CPU_SECONDS = 30
MAX_OUTPUT_BYTES = 1_048_576
MAX_FILE_BYTES = 1_048_576
ALLOWED_RISK_LEVELS = frozenset({"L0", "L1", "L2"})

# Sandbox roots that would defeat confinement outright.
_FORBIDDEN_ROOTS = frozenset({
    "/", "/etc", "/home", "/root", "/var", "/usr", "/boot", "/proc",
    "/sys", "/dev",
})


class ExecutorError(Exception):
    """Base class for all named executor refusals/failures."""


class ConfinementError(ExecutorError):
    """Raised when a profile or target breaks confinement."""


class GrantError(ExecutorError):
    """Raised when the policy grant is absent or does not cover
    the exact requested action and resource."""


class ActionRefusedError(ExecutorError):
    """Raised for an unknown or unallowlisted action."""


class ExecutionTimeoutError(ExecutorError):
    """Raised when the child exceeds the wall-clock bound."""


class ExecutionFailedError(ExecutorError):
    """Raised when the child crashes or reports an action error."""


@dataclass(frozen=True)
class ConfinementProfile:
    """The limits the executor child runs under.  Validated
    fail-closed: an over-wide profile is refused, never trimmed."""

    sandbox_root: Path
    allowed_actions: frozenset = frozenset({"fixture.echo"})
    max_wall_seconds: float = 10.0
    max_cpu_seconds: int = 5
    max_output_bytes: int = 65_536
    max_file_bytes: int = 65_536
    allow_network: bool = False

    def __post_init__(self) -> None:
        root = Path(self.sandbox_root)
        if not root.is_absolute():
            raise ConfinementError(
                f"sandbox_root {str(root)!r} must be absolute")
        resolved = str(root.resolve())
        if resolved in _FORBIDDEN_ROOTS:
            raise ConfinementError(
                f"sandbox_root {resolved!r} is a system root: "
                "refusing to confine into the host itself")
        if self.allow_network:
            raise ConfinementError(
                "allow_network must be False: the confined executor "
                "has no network permission in this slice")
        unknown = set(self.allowed_actions) - KNOWN_ACTIONS
        if unknown:
            raise ActionRefusedError(
                f"allowed_actions names unknown actions "
                f"{sorted(unknown)}: only {sorted(KNOWN_ACTIONS)} "
                "exist in the fixture catalog")
        if not self.allowed_actions:
            raise ConfinementError(
                "allowed_actions must be non-empty (deny by default "
                "means an explicit allowlist, not an empty one)")
        if not (0 < self.max_wall_seconds <= MAX_WALL_SECONDS):
            raise ConfinementError(
                f"max_wall_seconds {self.max_wall_seconds} outside "
                f"(0, {MAX_WALL_SECONDS}] ceiling")
        if not (0 < self.max_cpu_seconds <= MAX_CPU_SECONDS):
            raise ConfinementError(
                f"max_cpu_seconds {self.max_cpu_seconds} outside "
                f"(0, {MAX_CPU_SECONDS}] ceiling")
        if not (0 < self.max_output_bytes <= MAX_OUTPUT_BYTES):
            raise ConfinementError(
                f"max_output_bytes {self.max_output_bytes} outside "
                f"(0, {MAX_OUTPUT_BYTES}] ceiling")
        if not (0 < self.max_file_bytes <= MAX_FILE_BYTES):
            raise ConfinementError(
                f"max_file_bytes {self.max_file_bytes} outside "
                f"(0, {MAX_FILE_BYTES}] ceiling")


@dataclass(frozen=True)
class PolicyGrant:
    """A policy decision in LIF-0402 terms: identity, exact action,
    exact resource, risk level, expiry.  Decision defaults to deny
    semantics: anything but an explicit ``allow`` is refused."""

    identity: str
    action: str
    resource: str
    risk_level: str = "L0"
    expires_at: float = 0.0
    decision: str = "allow"


@dataclass(frozen=True)
class ActionRequest:
    """One requested action.  ``target`` is a path relative to the
    sandbox root (``.`` for actions that touch no file)."""

    action: str
    target: str = "."
    args: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ExecutionResult:
    action: str
    child_pid: int
    output: Any


def _resolve_target(profile: ConfinementProfile,
                    target: str) -> Path:
    """Resolve ``target`` inside the sandbox; refuse any escape."""
    if not isinstance(target, str) or not target:
        raise ConfinementError(
            f"target must be a non-empty string, got {target!r}")
    raw = Path(target)
    if raw.is_absolute():
        raise ConfinementError(
            f"target {target!r} is absolute: confined targets are "
            "relative to the sandbox root")
    root = Path(profile.sandbox_root).resolve()
    resolved = (root / raw).resolve()
    if resolved != root and root not in resolved.parents:
        raise ConfinementError(
            f"target {target!r} resolves outside the sandbox root")
    return resolved


def _check_grant(grant: Optional[PolicyGrant], request: ActionRequest,
                 now: float) -> None:
    if grant is None:
        raise GrantError(
            "no policy grant: the executor runs nothing without a "
            "LIF-0402 decision (deny by default)")
    if grant.decision != "allow":
        raise GrantError(
            f"policy decision is {grant.decision!r}, not 'allow'")
    if not isinstance(grant.identity, str) or not grant.identity:
        raise GrantError("grant identity must be a non-empty string")
    if grant.action != request.action:
        raise GrantError(
            f"grant covers action {grant.action!r}, not the "
            f"requested {request.action!r}")
    if grant.resource != request.target:
        raise GrantError(
            f"grant covers resource {grant.resource!r}, not the "
            f"requested target {request.target!r}")
    if grant.risk_level not in ALLOWED_RISK_LEVELS:
        raise GrantError(
            f"risk level {grant.risk_level!r} is above the fixture "
            f"executor ceiling {sorted(ALLOWED_RISK_LEVELS)}")
    if grant.expires_at <= now:
        raise GrantError(
            f"grant expired at {grant.expires_at} (now {now}): "
            "expired grants are never replayed")


def _apply_child_limits(profile: ConfinementProfile) -> None:
    resource.setrlimit(resource.RLIMIT_CPU,
                       (profile.max_cpu_seconds,
                        profile.max_cpu_seconds + 1))
    resource.setrlimit(resource.RLIMIT_FSIZE,
                       (profile.max_file_bytes, profile.max_file_bytes))
    resource.setrlimit(resource.RLIMIT_NOFILE, (64, 64))
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))


def _run_action(profile: ConfinementProfile, request: ActionRequest,
                resolved: Path) -> Any:
    action = request.action
    if action == "fixture.echo":
        return request.args.get("text", "")
    if action == "fixture.sleep":
        time.sleep(float(request.args.get("seconds", 0)))
        return "slept"
    if action == "fixture.crash":
        os._exit(3)
    if action == "fixture.write_text":
        text = str(request.args.get("text", ""))
        if len(text.encode("utf-8")) > profile.max_file_bytes:
            raise ExecutionFailedError(
                "write exceeds the profile file-size cap")
        resolved.parent.mkdir(parents=True, exist_ok=True)
        resolved.write_text(text, encoding="utf-8")
        return len(text.encode("utf-8"))
    if action == "fixture.read_text":
        return resolved.read_text(encoding="utf-8")
    if action == "fixture.list_dir":
        return sorted(p.name for p in resolved.iterdir())
    if action == "fixture.report_limits":
        cpu = resource.getrlimit(resource.RLIMIT_CPU)[0]
        fsize = resource.getrlimit(resource.RLIMIT_FSIZE)[0]
        nofile = resource.getrlimit(resource.RLIMIT_NOFILE)[0]
        core = resource.getrlimit(resource.RLIMIT_CORE)[0]
        return {
            "pid": os.getpid(),
            "cwd": os.getcwd(),
            "env_keys": sorted(os.environ.keys()),
            "rlimit_cpu": cpu,
            "rlimit_fsize": fsize,
            "rlimit_nofile": nofile,
            "rlimit_core": core,
        }
    raise ActionRefusedError(f"unknown action {action!r}")


def _child_entry(conn, profile: ConfinementProfile,
                 request: ActionRequest, resolved: Path) -> None:
    try:
        root = Path(profile.sandbox_root).resolve()
        root.mkdir(parents=True, exist_ok=True)
        os.chdir(root)
        os.environ.clear()
        os.environ["PATH"] = "/usr/bin:/bin"
        os.environ["LANG"] = "C"
        _apply_child_limits(profile)
        output = _run_action(profile, request, resolved)
        conn.send({"ok": True, "pid": os.getpid(), "output": output})
    except Exception as exc:  # reported, never hidden
        try:
            conn.send({"ok": False, "pid": os.getpid(),
                       "error": f"{type(exc).__name__}: {exc}"})
        except Exception:
            pass
    finally:
        conn.close()


def run_confined(profile: ConfinementProfile,
                 grant: Optional[PolicyGrant],
                 request: ActionRequest,
                 clock: Callable[[], float] = time.time
                 ) -> ExecutionResult:
    """Run ``request`` in a separate, confined child process.

    Refuses (before spawning anything) on an invalid grant, an
    unknown or unallowlisted action, or a target escaping the
    sandbox.  Raises ExecutionTimeoutError if the child exceeds
    the profile wall bound and ExecutionFailedError if it crashes
    or errors; the caller survives both.
    """
    if request.action not in KNOWN_ACTIONS:
        raise ActionRefusedError(
            f"unknown action {request.action!r}: the executor runs "
            f"only the typed catalog {sorted(KNOWN_ACTIONS)}")
    if request.action not in profile.allowed_actions:
        raise ActionRefusedError(
            f"action {request.action!r} is not in the confinement "
            "profile allowlist (deny by default)")
    _check_grant(grant, request, clock())
    resolved = _resolve_target(profile, request.target)
    ctx = mp.get_context("fork")
    parent_conn, child_conn = ctx.Pipe(duplex=False)
    proc = ctx.Process(target=_child_entry,
                       args=(child_conn, profile, request, resolved))
    proc.start()
    child_conn.close()
    proc.join(profile.max_wall_seconds)
    if proc.is_alive():
        proc.terminate()
        proc.join(5)
        parent_conn.close()
        raise ExecutionTimeoutError(
            f"action {request.action!r} exceeded the wall bound of "
            f"{profile.max_wall_seconds}s and the child was "
            "terminated")
    if not parent_conn.poll():
        parent_conn.close()
        raise ExecutionFailedError(
            f"action {request.action!r} child exited with code "
            f"{proc.exitcode} and no result (crash contained in "
            "the child process)")
    try:
        message = parent_conn.recv()
    except EOFError:
        parent_conn.close()
        raise ExecutionFailedError(
            f"action {request.action!r} child closed its result "
            f"pipe with exit code {proc.exitcode} (crash "
            "contained in the child process)")
    parent_conn.close()
    if not message.get("ok"):
        raise ExecutionFailedError(
            f"action {request.action!r} failed in the child: "
            f"{message.get('error')}")
    output = message["output"]
    size = len(str(output).encode("utf-8"))
    if size > profile.max_output_bytes:
        raise ExecutionFailedError(
            f"action {request.action!r} output of {size} bytes "
            f"exceeds the profile output cap of "
            f"{profile.max_output_bytes} bytes")
    return ExecutionResult(action=request.action,
                           child_pid=int(message["pid"]),
                           output=output)
