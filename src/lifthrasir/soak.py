"""Verification-and-soak workflow with event logging (LIF-0504).

SPDX-License-Identifier: GPL-2.0-only

Home justification: master roadmap section 3 lays out ``src/`` for
core code and LIF-0201/LIF-0301 already placed the typed event bus
and the SQLite event store in ``src/lifthrasir/``.  Post-repair
verification is Eir's closing step on the repair path (roadmap
section 0 architecture: repair -> verification / rollback /
journal), and it consumes exactly those two banked pieces -- the
bus for live event logging and the store for durable evidence --
so it lives beside them here, not in ``lab/`` and not in ``ui/``.
This module deliberately does NOT touch
``src/lifthrasir/__init__.py`` (the LIF-0303/LIF-0402 precedent):
the banking seat unions exports; a namespace import
(``from lifthrasir import soak``) works without an ``__init__``
edit, so this slice can never conflict there.

What a soak is, here: after a repair, one passing check proves
only that the target was healthy at one instant.  A soak re-runs
the SAME verification checks for a bounded number of rounds and
judges the whole run:

- ``verified`` -- the trailing run of consecutive all-pass rounds
  reached the spec's required streak (with the default, every
  round passed).  Earlier failures stay in the report; stability
  flags still mark any check that flapped.
- ``flaky`` -- some rounds passed and some failed, and the
  required closing streak was never reached: the target is
  intermittent, which is precisely what a soak exists to catch.
- ``failed`` -- no round passed at all.
- ``aborted`` -- the duration budget ran out or the caller's
  cancellation check fired; partial rounds are retained and the
  abort reason is named.  An aborted soak is never a pass.

Event logging (the slice's second half): when the caller supplies
an event bus (LIF-0201), the workflow publishes
``verification.started``, one ``verification.round`` per round and
``verification.completed`` -- observation types only, never the
command / authorization families the bus forbids.  When the caller
supplies an event store (LIF-0301), the finished run is appended
as ONE LIF-0004 v0.1 evidence record (kind ``test-run``) whose
content digest covers the canonical report, so the soak result is
durable, hash-linked and tamper-evident like all Mimir evidence.

Bounds (master roadmap section 0 invariants 3, 8, 9): a soak is
finite by construction.  Rounds, checks, interval and total
duration are capped; a spec above any cap is refused by name
(``UnboundedSoakError``) rather than silently clamped.  Probes are
caller-supplied callables -- this module performs no host access
of its own, executes nothing, and repairs nothing: verification
observes, it never mutates.  Clock and sleeper are injectable so
tests run against fixture workloads with zero real waiting; the
production defaults are the monotonic clock and real sleep,
always inside the spec's caps.

Evidence-status honesty: a ``verified`` verdict is a lab-scope
claim about the rounds actually run, on the probes actually
supplied -- nothing here promotes it beyond ``lab-verified``.
"""
from __future__ import annotations

import hashlib
import json
import platform
import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Mapping, Optional, Tuple

SOAK_VERSION = "0.1"

# Hard caps: a soak that cannot state its own bounds is refused.
MAX_ROUNDS = 50
MAX_CHECKS = 16
MAX_INTERVAL_S = 60.0
MAX_DURATION_S = 1800.0

VERDICTS = ("verified", "flaky", "failed", "aborted")

_PLAN_RE = re.compile(r"^plan-[a-z0-9][a-z0-9-]*$")
_INC_RE = re.compile(r"^inc-[a-z0-9][a-z0-9-]*$")
_CHECK_RE = re.compile(r"^[a-z][a-z0-9-]*$")


class SoakError(Exception):
    """Base class for all named soak-workflow refusals."""


class MalformedSpecError(SoakError):
    """Raised when a soak spec breaks a field rule."""


class UnboundedSoakError(MalformedSpecError):
    """Raised when a spec exceeds a hard cap (rounds, checks,
    interval or duration): unbounded soaks are refused, never
    silently clamped."""


class UnknownCheckError(SoakError):
    """Raised when the probe map does not match the spec's checks
    exactly (missing or extra probes): a soak that silently skips
    a named check would be a false verification."""


@dataclass(frozen=True)
class SoakSpec:
    """One bounded verification-and-soak request.

    ``checks`` names the verification checks to re-run each round;
    the caller binds each name to a probe callable at run time.
    ``required_consecutive_passes`` defaults to ``rounds`` (only a
    fully clean soak verifies); a smaller value lets a soak verify
    early once the target has held for that many closing rounds.
    """

    plan_id: str
    incident_id: str
    target: str
    checks: Tuple[str, ...]
    rounds: int = 5
    interval_s: float = 0.0
    max_duration_s: float = 600.0
    required_consecutive_passes: Optional[int] = None
    fail_fast: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.plan_id, str) or not _PLAN_RE.match(self.plan_id):
            raise MalformedSpecError(
                f"plan_id {self.plan_id!r} is malformed: expected "
                "'plan-<slug>' (LIF-0004 v0.1 identifier shape)")
        if not isinstance(self.incident_id, str) or not _INC_RE.match(self.incident_id):
            raise MalformedSpecError(
                f"incident_id {self.incident_id!r} is malformed: "
                "expected 'inc-<slug>' (LIF-0004 v0.1 shape)")
        if not isinstance(self.target, str) or not self.target.strip():
            raise MalformedSpecError("target must be a non-empty string")
        checks = tuple(self.checks) if isinstance(self.checks, (list, tuple)) else None
        if not checks:
            raise MalformedSpecError(
                "checks must be a non-empty list of check names: a "
                "soak with no checks would verify nothing")
        if len(checks) > MAX_CHECKS:
            raise UnboundedSoakError(
                f"checks count {len(checks)} exceeds the cap "
                f"{MAX_CHECKS}: split the soak instead")
        for name in checks:
            if not isinstance(name, str) or not _CHECK_RE.match(name):
                raise MalformedSpecError(
                    f"check name {name!r} is malformed: expected "
                    "lowercase slug form")
        if len(set(checks)) != len(checks):
            raise MalformedSpecError(
                f"check names must be unique, got {list(checks)}")
        object.__setattr__(self, "checks", checks)
        if isinstance(self.rounds, bool) or not isinstance(self.rounds, int):
            raise MalformedSpecError("rounds must be an integer")
        if self.rounds < 1:
            raise MalformedSpecError("rounds must be at least 1")
        if self.rounds > MAX_ROUNDS:
            raise UnboundedSoakError(
                f"rounds {self.rounds} exceeds the cap {MAX_ROUNDS}")
        if not isinstance(self.interval_s, (int, float)) or isinstance(self.interval_s, bool):
            raise MalformedSpecError("interval_s must be a number")
        if self.interval_s < 0:
            raise MalformedSpecError("interval_s must not be negative")
        if self.interval_s > MAX_INTERVAL_S:
            raise UnboundedSoakError(
                f"interval_s {self.interval_s} exceeds the cap "
                f"{MAX_INTERVAL_S}")
        if not isinstance(self.max_duration_s, (int, float)) or isinstance(self.max_duration_s, bool):
            raise MalformedSpecError("max_duration_s must be a number")
        if self.max_duration_s <= 0:
            raise MalformedSpecError("max_duration_s must be positive")
        if self.max_duration_s > MAX_DURATION_S:
            raise UnboundedSoakError(
                f"max_duration_s {self.max_duration_s} exceeds "
                f"the cap {MAX_DURATION_S}")
        required = self.rounds if self.required_consecutive_passes is None \
            else self.required_consecutive_passes
        if isinstance(required, bool) or not isinstance(required, int):
            raise MalformedSpecError(
                "required_consecutive_passes must be an integer")
        if required < 1 or required > self.rounds:
            raise MalformedSpecError(
                f"required_consecutive_passes {required} must be "
                f"between 1 and rounds ({self.rounds})")
        object.__setattr__(self, "required_consecutive_passes", required)
        if not isinstance(self.fail_fast, bool):
            raise MalformedSpecError("fail_fast must be a boolean")


@dataclass(frozen=True)
class CheckOutcome:
    """One check's result inside one round."""

    name: str
    passed: bool
    detail: str = ""


@dataclass(frozen=True)
class RoundResult:
    """One soak round: every check's outcome, in spec order."""

    index: int
    passed: bool
    outcomes: Tuple[CheckOutcome, ...]
    offset_s: float


@dataclass(frozen=True)
class CheckStability:
    """Per-check totals across the whole soak.

    ``flapped`` is the soak's core signal: a check that both
    passed and failed across rounds is intermittent even when the
    closing streak later verified the run.
    """

    name: str
    passes: int
    failures: int
    transitions: int
    flapped: bool


@dataclass(frozen=True)
class SoakReport:
    """The finished (or aborted) soak, as data.

    ``evidence_id`` is set only when the run was appended to a
    caller-supplied event store; it stays ``None`` otherwise --
    an unstored run claims no durable evidence.
    """

    plan_id: str
    incident_id: str
    target: str
    verdict: str
    rounds_requested: int
    rounds_completed: int
    required_consecutive_passes: int
    trailing_streak: int
    rounds: Tuple[RoundResult, ...]
    checks: Tuple[CheckStability, ...]
    elapsed_s: float
    abort_reason: Optional[str] = None
    fail_fast_stopped: bool = False
    events_published: int = 0
    evidence_id: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "plan_id": self.plan_id,
            "incident_id": self.incident_id,
            "target": self.target,
            "verdict": self.verdict,
            "rounds_requested": self.rounds_requested,
            "rounds_completed": self.rounds_completed,
            "required_consecutive_passes": self.required_consecutive_passes,
            "trailing_streak": self.trailing_streak,
            "rounds": [
                {"index": r.index, "passed": r.passed,
                 "offset_s": r.offset_s,
                 "outcomes": [
                     {"name": o.name, "passed": o.passed,
                      "detail": o.detail} for o in r.outcomes]}
                for r in self.rounds],
            "checks": [
                {"name": c.name, "passes": c.passes,
                 "failures": c.failures,
                 "transitions": c.transitions, "flapped": c.flapped}
                for c in self.checks],
            "elapsed_s": self.elapsed_s,
            "abort_reason": self.abort_reason,
            "fail_fast_stopped": self.fail_fast_stopped,
            "events_published": self.events_published,
            "evidence_id": self.evidence_id,
        }


def sequence_probe(outcomes, detail: str = "") -> Callable[[], bool]:
    """Build a fixture probe from a scripted outcome sequence.

    Each call returns the next outcome; once the sequence is
    exhausted the LAST outcome repeats (the fixture target has
    settled into a steady state).  This is the fixture-workload
    probe the soak tests and demonstrations run against -- no
    live host is ever probed by this slice's own code.
    """
    seq = [bool(o) for o in outcomes]
    if not seq:
        raise MalformedSpecError(
            "sequence_probe needs at least one scripted outcome")
    state = {"calls": 0}

    def probe() -> bool:
        idx = min(state["calls"], len(seq) - 1)
        state["calls"] += 1
        return seq[idx]

    probe.__doc__ = detail or "scripted fixture probe"
    return probe


def _normalize_result(name: str, result: Any) -> CheckOutcome:
    if isinstance(result, CheckOutcome):
        return CheckOutcome(name=name, passed=bool(result.passed),
                            detail=str(result.detail))
    if isinstance(result, bool):
        return CheckOutcome(name=name, passed=result)
    if isinstance(result, tuple) and len(result) == 2:
        return CheckOutcome(name=name, passed=bool(result[0]),
                            detail=str(result[1]))
    if isinstance(result, dict) and "passed" in result:
        return CheckOutcome(name=name, passed=bool(result["passed"]),
                            detail=str(result.get("detail", "")))
    return CheckOutcome(
        name=name, passed=False,
        detail=f"probe returned a malformed result {result!r}: "
               "counted as a failed check, never as a pass")


def _run_probe(name: str, probe: Callable[[], Any]) -> CheckOutcome:
    try:
        return _normalize_result(name, probe())
    except Exception as exc:  # a raising probe is a failed check
        return CheckOutcome(
            name=name, passed=False,
            detail=f"probe raised {type(exc).__name__}: {exc}"[:300])


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def run_verification(spec: SoakSpec,
                     probes: Mapping[str, Callable[[], Any]],
                     *, bus=None, store=None,
                     clock: Callable[[], float] = time.monotonic,
                     sleeper: Callable[[float], None] = time.sleep,
                     wall_clock: Callable[[], str] = _utc_now_iso,
                     cancelled: Optional[Callable[[], bool]] = None,
                     host_local_id: str = "lab-guest-01") -> SoakReport:
    """Run one bounded verification-and-soak workflow.

    ``probes`` must bind exactly the spec's check names.  Every
    round runs every check once, in spec order.  The run stops
    early only when: the required closing streak is reached before
    the final round (verified), ``fail_fast`` is set and a round
    fails, the duration budget is exhausted, or ``cancelled``
    fires (the last two abort).  Events are published to ``bus``
    when given; the finished report is appended to ``store`` when
    given (see the module docstring for both contracts).
    """
    if not isinstance(spec, SoakSpec):
        raise MalformedSpecError(
            f"spec must be a SoakSpec, got {type(spec).__name__}")
    missing = [n for n in spec.checks if n not in probes]
    extra = [n for n in probes if n not in spec.checks]
    if missing or extra:
        raise UnknownCheckError(
            f"probe map does not match spec checks: missing "
            f"{missing}, extra {extra}; a soak never silently "
            "skips or invents a check")
    for name in spec.checks:
        if not callable(probes[name]):
            raise UnknownCheckError(f"probe for check {name!r} is not callable")

    published = {"count": 0}

    def emit(event_type: str, payload: Dict[str, Any]) -> None:
        if bus is None:
            return
        bus.publish(bus.make_event(event_type, "eir", payload))
        published["count"] += 1

    base = {"plan_id": spec.plan_id, "incident_id": spec.incident_id,
            "target": spec.target}
    emit("verification.started", dict(
        base, rounds_requested=spec.rounds,
        checks=list(spec.checks),
        required_consecutive_passes=spec.required_consecutive_passes))

    started = clock()
    rounds_done: List[RoundResult] = []
    abort_reason: Optional[str] = None
    fail_fast_stopped = False
    streak = 0
    for index in range(spec.rounds):
        if index > 0:
            if cancelled is not None and cancelled():
                abort_reason = "cancelled"
                break
            if clock() - started > spec.max_duration_s:
                abort_reason = "duration-budget"
                break
            if spec.interval_s:
                sleeper(float(spec.interval_s))
            if clock() - started > spec.max_duration_s:
                abort_reason = "duration-budget"
                break
        outcomes = tuple(_run_probe(n, probes[n]) for n in spec.checks)
        passed = all(o.passed for o in outcomes)
        streak = streak + 1 if passed else 0
        result = RoundResult(index=index, passed=passed,
                             outcomes=outcomes,
                             offset_s=clock() - started)
        rounds_done.append(result)
        emit("verification.round", dict(
            base, round_index=index, passed=passed,
            outcomes=[{"name": o.name, "passed": o.passed,
                       "detail": o.detail} for o in outcomes]))
        if spec.fail_fast and not passed:
            fail_fast_stopped = index < spec.rounds - 1
            break
        if passed and streak >= spec.required_consecutive_passes \
                and index < spec.rounds - 1:
            break  # verified early: the closing streak is met

    elapsed = clock() - started
    trailing = 0
    for r in reversed(rounds_done):
        if not r.passed:
            break
        trailing += 1
    if abort_reason is not None:
        verdict = "aborted"
    elif rounds_done and trailing >= spec.required_consecutive_passes:
        verdict = "verified"
    elif any(r.passed for r in rounds_done):
        verdict = "flaky"
    else:
        verdict = "failed"

    stability: List[CheckStability] = []
    for name in spec.checks:
        seq = [o.passed for r in rounds_done for o in r.outcomes
               if o.name == name]
        transitions = sum(1 for a, b in zip(seq, seq[1:]) if a != b)
        stability.append(CheckStability(
            name=name, passes=sum(1 for p in seq if p),
            failures=sum(1 for p in seq if not p),
            transitions=transitions,
            flapped=any(seq) and not all(seq)))

    report = SoakReport(
        plan_id=spec.plan_id, incident_id=spec.incident_id,
        target=spec.target, verdict=verdict,
        rounds_requested=spec.rounds,
        rounds_completed=len(rounds_done),
        required_consecutive_passes=spec.required_consecutive_passes,
        trailing_streak=trailing, rounds=tuple(rounds_done),
        checks=tuple(stability), elapsed_s=elapsed,
        abort_reason=abort_reason,
        fail_fast_stopped=fail_fast_stopped,
        events_published=published["count"])
    emit("verification.completed", dict(
        base, verdict=verdict,
        rounds_completed=len(rounds_done),
        trailing_streak=trailing, abort_reason=abort_reason))
    object.__setattr__(report, "events_published", published["count"])

    if store is not None:
        record = build_evidence_record(
            report, recorded_at=wall_clock(),
            host_local_id=host_local_id,
            boot_id=getattr(bus, "boot_id", None))
        store.append(record)
        object.__setattr__(report, "evidence_id", record["evidence_id"])
    return report


def build_evidence_record(report: SoakReport, *,
                          recorded_at: str,
                          host_local_id: str = "lab-guest-01",
                          boot_id: Optional[str] = None,
                          evidence_id: Optional[str] = None) -> Dict[str, Any]:
    """Render a finished report as a LIF-0004 v0.1 evidence record.

    The record is shaped for the LIF-0301 event store (envelope
    ``lifthrasir.evidence.v0.1``, kind ``test-run`` -- which the
    v0.1 schema requires to carry tool versions).  Its content
    digest covers the canonical report JSON with ``evidence_id``
    blanked, so the digest is stable before and after storage.
    The default evidence id is derived from that digest:
    re-running the identical soak reproduces the identical id,
    and the append-only store will refuse the duplicate -- a
    soaked-twice claim can never be silently double-counted.
    """
    canonical = dict(report.to_dict(), evidence_id=None)
    material = json.dumps(canonical, sort_keys=True,
                          separators=(",", ":"), ensure_ascii=False)
    digest = hashlib.sha256(material.encode("utf-8")).hexdigest()
    eid = evidence_id or f"ev-soak-{digest[:12]}"
    source: Dict[str, Any] = {"component": "eir",
                              "host_local_id": host_local_id}
    if boot_id:
        source["boot_id"] = boot_id
    flapped = [c.name for c in report.checks if c.flapped]
    limitations = [
        "fixture/lab scope: verdict covers only the rounds run "
        "and the probes supplied; no live host was probed by "
        "this module",
        f"verdict {report.verdict}: "
        f"{report.rounds_completed} of {report.rounds_requested} "
        "rounds completed",
    ]
    if flapped:
        limitations.append(
            f"checks that flapped during the soak: {flapped}")
    if report.abort_reason:
        limitations.append(
            f"soak aborted: {report.abort_reason}; an aborted "
            "soak is never a verification")
    return {
        "schema": "lifthrasir.evidence.v0.1",
        "schema_version": "0.1",
        "evidence_id": eid,
        "incident_id": report.incident_id,
        "plan_id": report.plan_id,
        "kind": "test-run",
        "recorded_at": recorded_at,
        "source": source,
        "summary": (
            f"Soak verification of {report.target}: verdict "
            f"{report.verdict} after {report.rounds_completed} "
            f"round(s); trailing all-pass streak "
            f"{report.trailing_streak} (required "
            f"{report.required_consecutive_passes})."),
        "content_digest": f"sha256:{digest}",
        "evidence_status": "lab-verified",
        "tool_versions": {"python": platform.python_version(),
                          "lifthrasir-soak": SOAK_VERSION},
        "limitations": limitations,
    }
