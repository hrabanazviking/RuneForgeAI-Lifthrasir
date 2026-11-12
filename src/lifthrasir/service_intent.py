"""Intent classification for stopped services (LIF-0506).

SPDX-License-Identifier: GPL-2.0-only

Home justification: master roadmap section 3 lays out ``src/`` for
core code; the P4 authority pieces (policy, executor, approval)
already live in ``src/lifthrasir/``.  This classifier is the Eir
(P5) companion to those pieces: it consumes the RECORDED unit state
produced by the banked systemd collector (LIF-0202, ``lab/``) and
decides, deterministically and without any model, whether a
non-running service stopped on purpose or failed by accident.  It
therefore lives beside the policy code here, not in ``lab/``.  It
takes collector records by attribute (duck-typed), so ``src/`` does
not import ``lab/``.

The problem (P5 exit + LIF-0104 fixture F02): a service that is
``inactive`` may be

- intentionally stopped: disabled or masked by the administrator,
  cleanly stopped after a successful run, skipped because its
  condition was unmet, or static/on-demand and simply not yet
  triggered -- Eir must ABSTAIN from "repairing" it; or
- accidentally failed: it ran and ended with an error result, a
  nonzero/signal exit, or a crash/restart loop -- a genuine repair
  candidate; or
- undecidable from the recorded evidence: bare ``inactive`` with
  no file state, no result and no journal trail proves NOTHING
  about intent.  Per master roadmap section 0 invariant 4,
  unknown is not verified: the verdict is ``unknown`` and Eir must
  abstain pending more evidence.  Intent is never invented.

Inputs are recorded/fixture unit state ONLY (collector output,
``systemctl show``-style key/value data, fixture dicts in the
LIF-0104 shape).  This module never queries the live host, never
invokes systemctl, and changes no service state: it is pure data
in, verdict out.  No ambient root, no subprocess, no I/O.
"""

from __future__ import annotations

from dataclasses import dataclass, field

SCHEMA_VERSION = "0.1"

INTENTIONAL = "intentional"
ACCIDENTAL = "accidental_failure"
HEALTHY = "healthy"
UNKNOWN = "unknown"
VERDICTS = (INTENTIONAL, ACCIDENTAL, HEALTHY, UNKNOWN)

# UnitFileState values that prove deliberate non-running.
_MASKED_STATES = frozenset({"masked", "masked-runtime"})
_DISABLED_STATES = frozenset({"disabled", "disabled-runtime"})
# Static units cannot be enabled; inactive is their designed rest
# state (started on demand by sockets/timers/other units).
_DESIGN_INACTIVE_STATES = frozenset({"static", "indirect", "generated"})
# Result values (systemctl show "Result=") that mean failure.
_FAILURE_RESULTS = frozenset({
    "exit-code", "signal", "core-dump", "timeout", "watchdog",
    "resources", "start-limit-hit", "protocol", "oom-kill",
})
# Crash-loop threshold: matches the LIF-0104 F06 fixture's own
# symptom boundary (restart_count >= 5 reads as a loop, not a blip).
RESTART_LOOP_THRESHOLD = 5


@dataclass(frozen=True)
class UnitObservation:
    """One unit's recorded state.  Every field except ``unit`` may
    be None: absent recorded data stays absent, never invented."""

    unit: str
    active_state: str | None = None
    sub_state: str | None = None
    unit_file_state: str | None = None
    result: str | None = None
    exec_main_status: int | None = None
    exec_main_code: str | None = None
    n_restarts: int | None = None
    condition_result: bool | None = None
    assert_result: bool | None = None
    intentionally_disabled: bool = False
    intentionally_stopped: bool = False
    journal_kinds: tuple = ()

    @classmethod
    def from_show(cls, unit, show):
        """Build from one unit's recorded ``systemctl show`` dict
        (the shape lab.systemd_collector.parse_show returns)."""
        show = show or {}

        def _int(key):
            raw = show.get(key)
            if raw is None or raw == "":
                return None
            try:
                return int(raw)
            except (TypeError, ValueError):
                return None

        def _yesno(key):
            raw = show.get(key)
            if raw == "yes":
                return True
            if raw == "no":
                return False
            return None

        return cls(
            unit=unit or show.get("Id") or "",
            active_state=show.get("ActiveState") or None,
            sub_state=show.get("SubState") or None,
            unit_file_state=show.get("UnitFileState") or None,
            result=show.get("Result") or None,
            exec_main_status=_int("ExecMainStatus"),
            exec_main_code=show.get("ExecMainCode") or None,
            n_restarts=_int("NRestarts"),
            condition_result=_yesno("ConditionResult"),
            assert_result=_yesno("AssertResult"),
        )

    @classmethod
    def from_fixture(cls, service):
        """Build from a LIF-0104-style fixture ``service`` dict
        (name / active_state / enabled / result / restart_count /
        intentionally_disabled), e.g. lab/fixtures/F02.json."""
        service = service or {}
        enabled = service.get("enabled")
        file_state = None
        if enabled is True:
            file_state = "enabled"
        elif enabled is False:
            file_state = "disabled"
        count = service.get("restart_count")
        if not isinstance(count, int) or isinstance(count, bool):
            count = None
        return cls(
            unit=service.get("name") or "",
            active_state=service.get("active_state"),
            sub_state=service.get("sub_state"),
            unit_file_state=file_state,
            result=service.get("result"),
            n_restarts=count,
            intentionally_disabled=bool(
                service.get("intentionally_disabled")),
            intentionally_stopped=bool(
                service.get("intentionally_stopped")),
        )

    @classmethod
    def from_collector(cls, record, show=None, events=None):
        """Build from banked collector output (LIF-0202): a
        UnitRecord-like object (``unit``/``active``/``sub``
        attributes), an optional parse_show dict for this unit,
        and optional RestartEvent-like objects (``unit``/``kind``)
        from the recorded journal timeline.  Duck-typed on purpose:
        recorded data in, no lab import, no live query."""
        obs = cls.from_show(getattr(record, "unit", ""), show or {})
        kinds = tuple(
            e.kind for e in (events or [])
            if getattr(e, "unit", None) == obs.unit and getattr(
                e, "kind", None))
        base = dict(
            unit=obs.unit,
            active_state=getattr(record, "active", None)
            or obs.active_state,
            sub_state=getattr(record, "sub", None) or obs.sub_state,
            unit_file_state=obs.unit_file_state,
            result=obs.result,
            exec_main_status=obs.exec_main_status,
            exec_main_code=obs.exec_main_code,
            n_restarts=obs.n_restarts,
            condition_result=obs.condition_result,
            assert_result=obs.assert_result,
            journal_kinds=kinds,
        )
        return cls(**base)


@dataclass(frozen=True)
class Classification:
    """A verdict plus the recorded evidence that proves it.

    ``needs_repair`` is True ONLY for ACCIDENTAL.  Every other
    verdict -- including UNKNOWN -- means Eir abstains."""

    unit: str
    verdict: str
    reasons: tuple = ()
    evidence: tuple = ()
    schema_version: str = SCHEMA_VERSION

    @property
    def needs_repair(self):
        return self.verdict == ACCIDENTAL

    @property
    def abstain(self):
        return self.verdict != ACCIDENTAL


def _result_failed(obs):
    return obs.result is not None and obs.result in _FAILURE_RESULTS


def _exec_failed(obs):
    if obs.exec_main_status is None:
        return False
    if obs.exec_main_status != 0:
        return True
    return (obs.exec_main_code or "") in ("killed", "dumped")


def classify(obs):
    """Classify one recorded unit observation.

    Deterministic rule order (first match wins); failure evidence
    is checked before intent evidence so a unit that ran and failed
    is never excused by also being disabled, while intent evidence
    is checked before the clean-stop and journal heuristics:

    1. malformed (no unit / no active state)      -> UNKNOWN
    2. currently active                           -> HEALTHY
    3. failed state / failure result / bad exit /
       auto-restart sub-state / restart loop      -> ACCIDENTAL
    4. masked / disabled+inactive / explicit
       intent flag+inactive / condition unmet     -> INTENTIONAL
    5. static-family + inactive (by design)       -> INTENTIONAL
    6. inactive + recorded clean result, or a
       journal trail ending in a clean stop with
       no failure events                          -> INTENTIONAL
    7. transitional state, or anything else with
       insufficient recorded evidence             -> UNKNOWN
    """
    unit = obs.unit or ""
    if not unit or not obs.active_state:
        return Classification(unit, UNKNOWN,
                              ("malformed-observation",),
                              ())
    active = obs.active_state
    ev = []
    if obs.unit_file_state:
        ev.append("unit_file_state")
    if obs.result:
        ev.append("result")
    if obs.n_restarts is not None:
        ev.append("n_restarts")
    if obs.journal_kinds:
        ev.append("journal")
    evidence = tuple(ev)

    if active == "active":
        reasons = ["currently-active"]
        if obs.n_restarts:
            reasons.append("restart-history-noted")
        return Classification(unit, HEALTHY, tuple(reasons), evidence)

    # --- failure evidence (rule 3) ---
    if active == "failed" or obs.sub_state == "failed":
        return Classification(unit, ACCIDENTAL,
                              ("failed-state",), evidence)
    if _result_failed(obs):
        return Classification(unit, ACCIDENTAL,
                              ("failure-result:" + str(obs.result),),
                              evidence)
    if _exec_failed(obs):
        return Classification(unit, ACCIDENTAL,
                              ("failure-exit-status",), evidence)
    if obs.sub_state == "auto-restart":
        return Classification(unit, ACCIDENTAL,
                              ("auto-restart-loop",), evidence)
    if (obs.n_restarts is not None
            and obs.n_restarts >= RESTART_LOOP_THRESHOLD
            and active in ("activating", "inactive", "deactivating")):
        return Classification(unit, ACCIDENTAL,
                              ("restart-loop",), evidence)
    if obs.assert_result is False and active == "failed":
        return Classification(unit, ACCIDENTAL,
                              ("assert-failed",), evidence)

    # --- intent evidence (rules 4-5) ---
    if obs.unit_file_state in _MASKED_STATES:
        return Classification(unit, INTENTIONAL,
                              ("masked-unit",), evidence)
    if active == "inactive":
        if obs.unit_file_state in _DISABLED_STATES:
            return Classification(unit, INTENTIONAL,
                                  ("disabled-unit",), evidence)
        if obs.intentionally_disabled or obs.intentionally_stopped:
            return Classification(unit, INTENTIONAL,
                                  ("explicit-intent-flag",), evidence)
        if obs.condition_result is False:
            return Classification(unit, INTENTIONAL,
                                  ("condition-unmet",), evidence)
        if obs.unit_file_state in _DESIGN_INACTIVE_STATES:
            return Classification(unit, INTENTIONAL,
                                  ("on-demand-by-design",), evidence)

    # --- clean-stop evidence (rule 6) ---
    if active == "inactive" and obs.result == "success" and (
            obs.exec_main_status in (None, 0)):
        return Classification(unit, INTENTIONAL,
                              ("clean-stop-result-success",), evidence)
    if active == "inactive" and obs.journal_kinds:
        kinds = list(obs.journal_kinds)
        if kinds[-1] == "stopped" and "failed" not in kinds:
            return Classification(unit, INTENTIONAL,
                                  ("journal-clean-stop",), evidence)

    # --- insufficient evidence (rule 7): never guess intent ---
    if active in ("activating", "deactivating", "reloading"):
        return Classification(unit, UNKNOWN,
                              ("transitional-state",), evidence)
    return Classification(unit, UNKNOWN,
                          ("insufficient-evidence",), evidence)


def classify_many(observations):
    """Classify a sequence of observations, preserving order."""
    return [classify(o) for o in observations]


def should_abstain(classification):
    """Eir-facing helper: abstain unless the verdict is a proven
    accidental failure.  Intentional, healthy and unknown all
    abstain -- unknown means gather more evidence, not repair."""
    return classification.verdict != ACCIDENTAL
