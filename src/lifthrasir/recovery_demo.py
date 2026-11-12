"""Demonstration: one noncritical user-service recovery (LIF-0502).

SPDX-License-Identifier: GPL-2.0-only

Home justification: ADR-0002 names ``lifthrasir-eir`` the repair
workflow orchestrator (it builds typed plan envelopes for policy
review and never executes a plan itself; execution is broker-only),
and master roadmap section 3 places core implementation in ``src/``.
This demonstration is Eir's first end-to-end workflow proof, so it
lives in the core package beside the catalog (LIF-0401), the policy
engine (LIF-0402) and the approval ledger (LIF-0404) it composes --
not in ``lab/``, whose collectors it consumes as a client.

WHAT THE DEMONSTRATION ACTUALLY EXERCISES (evidence-status honesty,
master roadmap sections 0 and 5 -- read this before citing it):

- The target is ``lifthrasir-demo.service``, the deliberately failed
  user-level unit named in research/07's example recovery. It exists
  ONLY inside this slice's fixture world: an in-memory simulation of
  a systemd user manager inside the disposable lab guest
  ``lab-guest-01`` (the LIF-0102 lab world). NO real host service --
  user or system -- is restarted, stopped, started or otherwise
  touched by this module or its tests, and no code path in this
  module can reach one: the fixture world is plain data, the only
  "effect" is a state transition inside that data, and observation
  of the world goes through the banked read-only collector
  (``lab.systemd_collector``, LIF-0202) fed with recorded-style text
  the world renders from its own state.
- The authority chain around the fixture effect is the REAL banked
  chain, exercised at its contract level: the plan validates
  against the LIF-0401 typed catalog (verb ``restart_unit_in_guest``,
  L2, lab-guest scope), the LIF-0402 policy engine must ALLOW it
  (identity, consent floor, preconditions observed from the actual
  fixture observation, emergency-stop gate), and a LIF-0404 signed,
  single-use plan reference must be approved by a human and consumed
  for exactly the plan's resource scope before anything happens.
- Execution is proven at the interface level only: the catalog's
  ``DryRunExecutor`` validates the request and executes NOTHING
  (``executed`` is False), and the fixture world's restart
  transition stands in for the future broker effect. Claiming a
  live recovery from this slice would be false; the honest status
  is reproducer / fixture-demonstrated, not lab-verified on a live
  system and not human-reviewed.
- Abstention is part of the demonstration (P5 grades abstention as
  rigorously as repair, research/07): a unit that is intentionally
  stopped, or is not failed at all, is NOT restarted. Critical units
  (the catalog's CRITICAL_UNITS) are refused outright, in any scope.

COORDINATION WITH LIF-0501 (building in parallel on team-02): the
health-repair recipe abstraction is not banked yet, so this slice
depends on NO LIF-0501 file. The single recovery recipe is carried
here as explicit local data (``RECIPE``: exact target, verb,
preconditions, rollback, verification) shaped after the backlog
contract for LIF-0501 ("exact targets and effects"); when LIF-0501
banks, the seat should reconcile ``RECIPE`` / ``build_demo_plan``
onto its abstraction. Flagged in the team's CAMPAIGN_STATE.md.

Safety invariants bound here (master roadmap section 0): no ambient
root (nothing here runs privileged, or runs anything external at
all); no mutation of any real host state; every step is bounded,
logged in the report's event trail, and reversible by construction
(the fixture guest is disposable; the named rollback is a guest
reset). Verification is immediate re-observation through the
collector, twice; a timed soak workflow is LIF-0504, not this slice.
"""
from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Tuple

from . import actions as _actions
from . import approval as _approval
from . import policy as _policy

DEMO_UNIT = "lifthrasir-demo.service"
DEMO_GUEST = "lab-guest-01"
DEMO_PLAN_ID = "plan-2026-502"
FIXTURE_KEY = b"lif-0502-fixture-key-throwaway-00"
FIXED_NOW = datetime(2026, 11, 12, 4, 5, 0, tzinfo=timezone.utc)
PLAN_CREATED_AT = "2026-11-12T04:00:00Z"
PLAN_EXPIRES_AT = "2026-11-12T05:00:00Z"
EVALUATED_AT = "2026-11-12T04:05:00Z"
REFERENCE_NONCE = "0502" * 8  # deterministic fixture nonce (hex)
EVIDENCE_STATUS = "reproducer"

# The one recovery recipe, as data (see the LIF-0501 coordination
# note in the module docstring): exact target, exact verb, exact
# effects, named preconditions, rollback and verification.
RECIPE: Dict[str, Any] = {
    "recipe_id": "restart-failed-user-service",
    "title": "Restart one failed noncritical user service in the lab guest",
    "target": {"type": "systemd-unit", "name": DEMO_UNIT},
    "guest": DEMO_GUEST,
    "verb": "restart_unit_in_guest",
    "risk_level": "L2",
    "consent_mode": "session-blanket",
    "effects": [
        "the fixture unit's active state changes failed -> active",
        "the fixture unit's restart counter increases by one",
        "two journal entries are appended to the fixture journal "
        "(restart scheduled, then started)",
    ],
    "rollback": {
        "method": "reset_lab_guest",
        "description": "The lab guest is disposable: reset it to its "
                       "pinned clean state. No live-host state exists "
                       "to restore.",
    },
    "verification": {
        "method": "collector_reobservation",
        "description": "Re-observe the fixture world through the "
                       "LIF-0202 collector: the unit must be absent "
                       "from the failed list and a started event "
                       "must appear in the restart timeline.",
    },
}


def _preconditions(unit: str, guest: str) -> List[str]:
    return [
        f"{unit} is in failed state in lab guest {guest}",
        f"lab guest {guest} is disposable",
        f"{unit} is not intentionally stopped",
    ]


class DemoError(Exception):
    """Base class for named demonstration refusals."""


class DemoRefusal(DemoError):
    """Raised when the fixture world itself refuses an operation."""


@dataclass
class UnitState:
    """One fixture unit inside the simulated guest user manager."""
    name: str
    active: str = "inactive"
    sub: str = "dead"
    load: str = "loaded"
    description: str = ""
    n_restarts: Optional[int] = None
    active_enter: Optional[str] = None
    result: Optional[str] = None
    enabled: bool = True
    intentionally_stopped: bool = False
    fail_on_restart: bool = False


@dataclass
class FixtureServiceWorld:
    """In-memory fixture world: a simulated systemd user manager
    inside one disposable lab guest.

    The world is plain data. It renders recorded-style collector
    input (unit listing, show blocks, journal NDJSON) from its
    state, so the demonstration observes it exclusively through
    the banked LIF-0202 collector, and its single mutating method
    ``apply_restart`` performs the fixture stand-in for a broker
    restart. Nothing here names, opens or signals any real unit,
    process or file.
    """
    guest: str = DEMO_GUEST
    disposable: bool = True
    units: Dict[str, UnitState] = field(default_factory=dict)
    journal: List[Dict[str, Any]] = field(default_factory=list)
    actions_taken: List[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "FixtureServiceWorld":
        if not isinstance(data, Mapping) or not data.get("guest"):
            raise DemoError("world data must name its guest")
        units: Dict[str, UnitState] = {}
        for raw in data.get("units") or []:
            state = UnitState(
                name=raw["name"], active=raw.get("active", "inactive"),
                sub=raw.get("sub", "dead"), load=raw.get("load", "loaded"),
                description=raw.get("description", ""),
                n_restarts=raw.get("n_restarts"),
                active_enter=raw.get("active_enter"),
                result=raw.get("result"),
                enabled=bool(raw.get("enabled", True)),
                intentionally_stopped=bool(
                    raw.get("intentionally_stopped", False)),
                fail_on_restart=bool(raw.get("fail_on_restart", False)),
            )
            units[state.name] = state
        journal = [dict(entry) for entry in data.get("journal") or []]
        return cls(guest=str(data["guest"]),
                   disposable=bool(data.get("disposable", True)),
                   units=units, journal=journal)

    # -- observation rendering (collector input, recorded style) --
    def snapshot_texts(self) -> Tuple[str, str, str]:
        """Render (list-units text, show text, journal NDJSON)."""
        lines = ["  UNIT                LOAD   ACTIVE SUB    DESCRIPTION"]
        for state in self.units.values():
            marker = "● " if state.active == "failed" else "  "
            lines.append(
                f"{marker}{state.name}  {state.load} {state.active} "
                f"{state.sub} {state.description}")
        lines.append("")
        lines.append(f"{len(self.units)} loaded units listed.")
        list_text = "\n".join(lines) + "\n"

        blocks = []
        for state in self.units.values():
            block = [f"Id={state.name}",
                     f"ActiveState={state.active}",
                     f"SubState={state.sub}"]
            if state.n_restarts is not None:
                block.append(f"NRestarts={state.n_restarts}")
            if state.active_enter is not None:
                block.append(f"ActiveEnterTimestamp={state.active_enter}")
            if state.result is not None:
                block.append(f"Result={state.result}")
            blocks.append("\n".join(block))
        show_text = "\n\n".join(blocks) + ("\n" if blocks else "")

        journal_text = "".join(
            json.dumps({
                "__REALTIME_TIMESTAMP": str(entry["timestamp_us"]),
                "_SYSTEMD_UNIT": entry["unit"],
                "MESSAGE": entry["message"],
                "PRIORITY": "6",
                "_BOOT_ID": "fixtureboot0502",
            }) + "\n" for entry in self.journal)
        return list_text, show_text, journal_text

    # -- the one fixture effect -----------------------------------
    def _next_ts(self) -> int:
        last = max((int(e["timestamp_us"]) for e in self.journal),
                   default=0)
        return last + 60_000_000

    def apply_restart(self, unit: str) -> None:
        """Fixture stand-in for a broker restart of one unit.

        Transitions failed -> active (or records a fresh failure
        for a unit whose fixture data says it fails on restart)
        and appends the journal entries a real restart would
        leave. Refuses unknown and critical units by name.
        """
        state = self.units.get(unit)
        if state is None:
            raise DemoRefusal(f"unknown fixture unit {unit!r}")
        if unit in _actions.CRITICAL_UNITS:
            raise DemoRefusal(
                f"unit {unit!r} is critical infrastructure: the "
                "demonstration never restarts it, in any scope")
        self.actions_taken.append(f"restart:{unit}")
        state.n_restarts = (state.n_restarts or 0) + 1
        self.journal.append({
            "timestamp_us": self._next_ts(), "unit": unit,
            "message": f"{unit}: Scheduled restart job, restart "
                       f"counter is at {state.n_restarts}."})
        if state.fail_on_restart:
            state.active, state.sub, state.result = (
                "failed", "failed", "exit-code")
            self.journal.append({
                "timestamp_us": self._next_ts(), "unit": unit,
                "message": f"{unit}: Failed with result exit-code."})
        else:
            state.active, state.sub, state.result = (
                "active", "running", "success")
            self.journal.append({
                "timestamp_us": self._next_ts(), "unit": unit,
                "message": f"Started {state.description or unit}."})


def load_demo_world(data: Mapping[str, Any]) -> FixtureServiceWorld:
    """Build a fixture world from recorded JSON-shaped data."""
    return FixtureServiceWorld.from_dict(data)


def build_demo_plan(unit: str = DEMO_UNIT,
                    guest: str = DEMO_GUEST) -> Dict[str, Any]:
    """The v0.1 plan for the one demonstration recovery (RECIPE)."""
    return {
        "schema": "lifthrasir.plan.v0.1",
        "schema_version": "0.1",
        "plan_id": DEMO_PLAN_ID,
        "incident_id": "inc-2026-502",
        "hypothesis_ids": ["hyp-2026-502"],
        "title": RECIPE["title"],
        "status": "submitted",
        "risk_level": RECIPE["risk_level"],
        "consent_mode": RECIPE["consent_mode"],
        "steps": [{
            "step_id": "step-1",
            "action_verb": RECIPE["verb"],
            "target": {"type": "systemd-unit", "name": unit},
            "args": {"guest": guest},
        }],
        "preconditions": _preconditions(unit, guest),
        "rollback": dict(RECIPE["rollback"]),
        "verification": {"method": "unit_healthy_in_guest",
                         "timeout_seconds": 30},
        "created_at": PLAN_CREATED_AT,
        "expires_at": PLAN_EXPIRES_AT,
    }


@dataclass(frozen=True)
class DemoEvent:
    step: str
    detail: str


@dataclass
class DemoReport:
    unit: str
    guest: str
    outcome: str  # recovered | abstained | denied | verification-failed
    reason_codes: Tuple[str, ...] = ()
    policy_outcome: Optional[str] = None
    policy_reasons: Tuple[str, ...] = ()
    approval_reference_id: Optional[str] = None
    dry_run_status: Optional[str] = None
    dry_run_executed: bool = False
    real_host_touched: bool = False
    fixture_only: bool = True
    evidence_status: str = EVIDENCE_STATUS
    restart_count_before: Optional[int] = None
    restart_count_after: Optional[int] = None
    plan: Optional[Dict[str, Any]] = None
    events: Tuple[DemoEvent, ...] = ()
    world_actions: Tuple[str, ...] = ()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "unit": self.unit, "guest": self.guest,
            "outcome": self.outcome,
            "reason_codes": list(self.reason_codes),
            "policy_outcome": self.policy_outcome,
            "policy_reasons": list(self.policy_reasons),
            "approval_reference_id": self.approval_reference_id,
            "dry_run_status": self.dry_run_status,
            "dry_run_executed": self.dry_run_executed,
            "real_host_touched": self.real_host_touched,
            "fixture_only": self.fixture_only,
            "evidence_status": self.evidence_status,
            "restart_count_before": self.restart_count_before,
            "restart_count_after": self.restart_count_after,
            "events": [{"step": e.step, "detail": e.detail}
                       for e in self.events],
            "world_actions": list(self.world_actions),
        }


def _load_collector():
    """Import the banked LIF-0202 collector (lab/ prototype home).

    The collector lives in ``lab/`` per ADR-0002 D2 while this
    orchestrator lives in ``src/``; the import is lazy and falls
    back to the repository root derived from this file, so the
    module imports cleanly in either layout.
    """
    try:
        from lab import systemd_collector
        return systemd_collector
    except ImportError:
        root = Path(__file__).resolve().parents[2]
        if str(root) not in sys.path:
            sys.path.insert(0, str(root))
        from lab import systemd_collector
        return systemd_collector


def _observe(world: FixtureServiceWorld):
    collector = _load_collector()
    list_text, show_text, journal_text = world.snapshot_texts()
    return collector.collect(failed_text=list_text,
                             show_text=show_text,
                             journal_text=journal_text)


def run_demo(world: FixtureServiceWorld, unit: str = DEMO_UNIT, *,
             approve: bool = True, emergency_stop: bool = False,
             consent_granted: str = "session-blanket",
             ledger: Optional[_approval.ApprovalLedger] = None,
             key: bytes = FIXTURE_KEY,
             now: datetime = FIXED_NOW) -> DemoReport:
    """Run the one demonstration recovery against a fixture world.

    Steps, in order: observe (banked collector) -> diagnose /
    abstain -> plan (catalog-validated) -> policy (LIF-0402 must
    ALLOW) -> approval (LIF-0404 signed reference, human decision,
    single-use consumption for the exact resource) -> dry-run
    validation (executes nothing) -> fixture restart transition ->
    verification by collector re-observation, twice.

    ``approve=False`` simulates the human rejecting the approval
    prompt. Approval-layer refusals (duplicate reference, replay,
    tampering) propagate as their named LIF-0404 errors: they are
    refusals, not outcomes. The world is mutated ONLY on the
    recovered / verification-failed paths (the fixture restart);
    denied and abstained runs leave it byte-identical.
    """
    events: List[DemoEvent] = []
    guest = world.guest

    def finish(outcome: str, reasons: Tuple[str, ...], **kw) -> DemoReport:
        return DemoReport(
            unit=unit, guest=guest, outcome=outcome,
            reason_codes=tuple(reasons),
            events=tuple(events),
            world_actions=tuple(world.actions_taken), **kw)

    # 1. Observe through the banked collector -- never by reading
    #    the world's internals for the failure verdict.
    pre = _observe(world)
    pre_failed = {f.unit: f for f in pre.failed_units}
    pre_max_ts = max((e.timestamp_us for e in pre.timeline), default=0)
    events.append(DemoEvent(
        "observe",
        f"collector reports {len(pre_failed)} failed fixture "
        f"unit(s): {sorted(pre_failed)}"))
    before = pre_failed.get(unit)
    count_before = before.restart_count if before else None

    # 2. Diagnose / abstain.
    state = world.units.get(unit)
    if state is None:
        events.append(DemoEvent("diagnose", "unit not in fixture world"))
        return finish("denied", ("UNKNOWN_UNIT",),
                      restart_count_before=None)
    if unit in _actions.CRITICAL_UNITS:
        events.append(DemoEvent(
            "diagnose", "critical unit: demonstration refuses it"))
        return finish("denied", ("PROHIBITED_CRITICAL_UNIT",),
                      restart_count_before=count_before)
    if state.intentionally_stopped:
        events.append(DemoEvent(
            "diagnose",
            "unit is intentionally stopped: Eir does not countermand "
            "an intentional stop (research/07)"))
        return finish("abstained", ("INTENTIONALLY_STOPPED",),
                      restart_count_before=count_before)
    if unit not in pre_failed:
        events.append(DemoEvent(
            "diagnose", "unit is not failed: nothing to recover"))
        return finish("abstained", ("NOT_FAILED",),
                      restart_count_before=count_before)
    events.append(DemoEvent(
        "diagnose",
        f"{unit} is failed (restart_count={count_before}); it is a "
        "noncritical fixture user service expected to run"))

    # 3. Plan, validated against the typed catalog.
    plan = build_demo_plan(unit, guest)
    problems = _actions.validate_plan_steps(plan)
    if problems:  # pragma: no cover - plan is built from the catalog
        return finish("denied", ("PLAN_INVALID",), plan=plan,
                      restart_count_before=count_before)
    events.append(DemoEvent(
        "plan", f"plan {plan['plan_id']}: {RECIPE['verb']} -> "
                f"systemd-unit:{unit} in guest {guest} "
                f"({plan['risk_level']}, {plan['consent_mode']})"))

    # 4. Policy: preconditions are OBSERVED values, not constants --
    #    the failed-state value comes from the collector report,
    #    disposability and intent from the fixture world's record.
    preconditions = _preconditions(unit, guest)
    snapshot = {
        preconditions[0]: unit in pre_failed,
        preconditions[1]: bool(world.disposable),
        preconditions[2]: not state.intentionally_stopped,
    }
    decision = _policy.evaluate(_policy.PolicyRequest(
        plan=plan,
        identity=_policy.Identity(
            principal_id="eir-demo-agent", kind="agent",
            authenticated=True),
        context=_policy.AuthorizationContext(
            evaluated_at=EVALUATED_AT,
            consent_mode_granted=consent_granted,
            consent_granted_by_id="user-1",
            consent_granted_by_kind="human",
            allowlist=frozenset(),
            resources={unit: _policy.ResourceInfo(
                scope="lab-guest", critical=False, sensitive=False)},
            precondition_snapshot=snapshot,
            emergency_stop_active=emergency_stop)))
    events.append(DemoEvent(
        "policy", f"{decision.outcome} "
                  f"({', '.join(decision.reason_codes)})"))
    if decision.outcome != _policy.ALLOW:
        return finish(
            "denied", tuple(decision.reason_codes), plan=plan,
            policy_outcome=decision.outcome,
            policy_reasons=tuple(decision.reason_codes),
            restart_count_before=count_before)

    # 5. Approval: signed unique reference, human decision, and
    #    single-use consumption for exactly the approved resource.
    ledger = ledger if ledger is not None else _approval.ApprovalLedger()
    ref = _approval.mint_plan_reference(
        plan, key=key, now=now, ttl_seconds=900,
        nonce=REFERENCE_NONCE)
    ledger.register(ref, key=key)
    record = ledger.decide(
        ref.reference_id, plan,
        decision="approved" if approve else "rejected",
        approver="user-1", now=now)
    events.append(DemoEvent(
        "approval", f"reference {ref.reference_id} "
                    f"{record.decision} by {record.approver}"))
    if record.decision != "approved":
        return finish(
            "denied", ("APPROVAL_REJECTED",), plan=plan,
            policy_outcome=decision.outcome,
            policy_reasons=tuple(decision.reason_codes),
            approval_reference_id=ref.reference_id,
            restart_count_before=count_before)
    ledger.consume_for_execution(
        ref.reference_id, plan,
        resource=f"systemd-unit:{unit}", now=now)
    events.append(DemoEvent(
        "approval-consume",
        f"approval consumed once for systemd-unit:{unit}"))

    # 6. Dry-run validation of the exact catalog request. The
    #    DryRunExecutor executes nothing; the fixture transition
    #    below is the demonstration's stand-in for a broker effect.
    digest = _approval.plan_digest(plan)
    dry = _actions.DryRunExecutor().execute(
        _actions.ActionRequest(
            verb=RECIPE["verb"],
            target=_actions.ActionTarget(
                type="systemd-unit", name=unit),
            args={"guest": guest}, plan_id=plan["plan_id"],
            expires_at=now.timestamp() + 600),
        _actions.Authorization(
            plan_id=plan["plan_id"], plan_digest=digest,
            nonce="demo-auth-nonce", consent_mode="session-blanket",
            expires_at=now.timestamp() + 600),
        now.timestamp())
    events.append(DemoEvent(
        "dry-run", f"{dry.status}: {dry.detail}"))

    # 7. The fixture effect (the ONLY mutation in this slice).
    world.apply_restart(unit)
    events.append(DemoEvent(
        "execute-fixture",
        f"fixture world applied restart:{unit} (in-memory only; "
        "no real service was touched)"))

    # 8. Verify by collector re-observation, twice (an immediate
    #    double check -- a timed soak is LIF-0504, not claimed here).
    post = _observe(world)
    post_again = _observe(world)
    post_failed = {f.unit for f in post.failed_units}
    started = [e for e in post.timeline
               if e.unit == unit and e.kind == "started"
               and e.timestamp_us > pre_max_ts]
    count_after = world.units[unit].n_restarts
    verified = (unit not in post_failed
                and {f.unit for f in post_again.failed_units}
                == post_failed
                and bool(started))
    events.append(DemoEvent(
        "verify",
        f"re-observation: unit {'still failed' if unit in post_failed else 'no longer failed'}; "
        f"{len(started)} new started event(s); "
        f"restart_count {count_before} -> {count_after}"))
    if verified:
        return finish(
            "recovered", ("RECOVERED",), plan=plan,
            policy_outcome=decision.outcome,
            policy_reasons=tuple(decision.reason_codes),
            approval_reference_id=ref.reference_id,
            dry_run_status=dry.status, dry_run_executed=dry.executed,
            restart_count_before=count_before,
            restart_count_after=count_after)
    return finish(
        "verification-failed", ("VERIFICATION_FAILED",), plan=plan,
        policy_outcome=decision.outcome,
        policy_reasons=tuple(decision.reason_codes),
        approval_reference_id=ref.reference_id,
        dry_run_status=dry.status, dry_run_executed=dry.executed,
        restart_count_before=count_before,
        restart_count_after=count_after)
