"""Permissioned, reversible response coordination with Eir (LIF-0803).

SPDX-License-Identifier: GPL-2.0-only

Home justification: the master roadmap section 0 reference
architecture places Thor (security triage) and Eir (repair
proposals) side by side, both feeding ONE typed immutable plan into
the independent policy engine.  Coordination is therefore core
package code in ``src/lifthrasir/``, beside the components it binds
together -- the Eir recipe abstraction (LIF-0501), the policy
engine (LIF-0402), the signed-approval flow (LIF-0404) and the
durable transaction / undo manifest (LIF-0405) -- not in ``lab/``.

What this slice is, and is not (evidence-status honesty):

- It COORDINATES, at planning level only.  ``propose_response``
  takes a Thor-style security finding, resolves the Eir recipe the
  finding is answered with, instantiates that recipe into a v0.1
  plan, and then walks the full safety chain in order.  It executes
  NOTHING against the real host: the only executor it ever touches
  is the banked dry-run executor (LIF-0401), which validates fully
  and executes nothing.  Thor detection itself is LIF-0801 and
  triage is LIF-0802; findings here are fixture-shaped data in the
  closed schema below, never live sensor output.
- A proposal is marked executable ONLY when every link holds:
  (a) the recipe is a banked LIF-0501 recipe and the recipe's own
  applicability check says APPLICABLE for the observed snapshot;
  (b) the instantiated plan passes the banked LIF-0402 policy
  engine with outcome ALLOW (DENY and REQUIRE_HUMAN both abstain:
  coordination never upgrades a human gate into a grant);
  (c) the banked LIF-0404 signed-approval flow holds for EXACTLY
  this plan: the reference signature verifies, its digest and scope
  bind this plan, it is unexpired, and the ledger holds an
  unconsumed APPROVED decision for it (the approval is checked,
  never consumed here -- consumption is the executor's act);
  (d) a LIF-0405 undo manifest exists BEFORE anything is marked
  executable: either a transaction record that passes
  ``transactions.validate_transaction``, is bound to this plan id
  (and digest, when recorded), mirrors the plan's steps exactly,
  and is undoable -- or an ``UndoManifest`` derived from a durable
  store for this plan with no missing inverses.
- The default is ABSTAIN.  Any missing, malformed or unverifiable
  link -- unknown recipe, unobserved precondition, policy denial,
  absent/expired/rejected approval, missing or non-undoable undo
  manifest, a dry-run refusal -- yields an abstain proposal naming
  the broken link in its reason codes.  Unverified is never
  executable (master roadmap section 0 invariant 4; P8 exit:
  Thor actions always constrained by deterministic policy).
- The finding itself is bound to the plan: its incident id must
  equal the plan's, and its exact target must sit inside the plan's
  approved resource scope.  A finding about some other incident or
  some other resource can never ride a plan's approvals.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Mapping, Optional, Tuple

from . import approval as _approval
from . import policy as _policy
from . import recipes as _recipes
from . import transactions as _transactions
from .actions import (
    ActionRequest,
    ActionTarget,
    Authorization,
    DryRunExecutor,
)

COORDINATION_VERSION = "0.1"
COORDINATION_SCHEMA = "lifthrasir.coordination.v0.1"
FINDING_SCHEMA = "lifthrasir.finding.v0.1"

OUTCOME_EXECUTABLE = "executable"
OUTCOME_ABSTAIN = "abstain"

SEVERITIES = ("info", "low", "medium", "high", "critical")

_FINDING_ID_RE = re.compile(r"^find-[a-z0-9][a-z0-9-]*$")
_INCIDENT_ID_RE = re.compile(r"^inc-[a-z0-9][a-z0-9-]*$")
_TARGET_TYPES = frozenset({
    "systemd-unit", "config-file", "package", "host", "lab-guest",
    "evidence-store", "firewall-rule",
})
_FINDING_KEYS = frozenset({
    "schema", "finding_id", "incident_id", "detector", "category",
    "severity", "target", "observed_at", "summary", "evidence_refs",
})


class CoordinationError(Exception):
    """Base class for all named coordination refusals."""


class MalformedFindingError(CoordinationError):
    """The security finding is not well-formed closed-schema data."""


@dataclass(frozen=True)
class SecurityFinding:
    """One Thor-style security finding (fixture-shaped data)."""
    finding_id: str
    incident_id: str
    detector: str
    category: str
    severity: str
    target_type: str
    target_name: str
    observed_at: str
    summary: str
    evidence_refs: Tuple[str, ...] = ()

    def scope_key(self) -> str:
        return f"{self.target_type}:{self.target_name}"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "schema": FINDING_SCHEMA, "finding_id": self.finding_id,
            "incident_id": self.incident_id, "detector": self.detector,
            "category": self.category, "severity": self.severity,
            "target": {"type": self.target_type,
                       "name": self.target_name},
            "observed_at": self.observed_at, "summary": self.summary,
            "evidence_refs": list(self.evidence_refs),
        }


def _parse_ts(value: Any, field_name: str) -> datetime:
    if not isinstance(value, str) or not value:
        raise MalformedFindingError(
            f"{field_name} must be an RFC3339 string")
    text = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        moment = datetime.fromisoformat(text)
    except ValueError as exc:
        raise MalformedFindingError(
            f"{field_name} {value!r} is not a valid timestamp") from exc
    if moment.tzinfo is None:
        raise MalformedFindingError(
            f"{field_name} must carry a timezone")
    return moment.astimezone(timezone.utc)


def validate_finding(data: Any) -> SecurityFinding:
    """Validate one finding record; return it or refuse by name.

    The finding vocabulary is closed: unknown fields, unknown
    severities, malformed ids and untyped targets are refused, so a
    coordination decision never rests on data it cannot name.
    """
    if not isinstance(data, Mapping):
        raise MalformedFindingError("finding must be an object")
    extra = set(data) - _FINDING_KEYS
    if extra:
        raise MalformedFindingError(
            f"finding has unknown fields {sorted(extra)}")
    if data.get("schema") != FINDING_SCHEMA:
        raise MalformedFindingError(
            f"finding schema must be {FINDING_SCHEMA!r}, "
            f"got {data.get('schema')!r}")
    finding_id = data.get("finding_id")
    if not isinstance(finding_id, str) \
            or not _FINDING_ID_RE.match(finding_id):
        raise MalformedFindingError(
            f"finding_id {finding_id!r} is malformed (want find-<name>)")
    incident_id = data.get("incident_id")
    if not isinstance(incident_id, str) \
            or not _INCIDENT_ID_RE.match(incident_id):
        raise MalformedFindingError(
            f"incident_id {incident_id!r} is malformed (want inc-<name>)")
    detector = data.get("detector")
    if not isinstance(detector, str) or not detector:
        raise MalformedFindingError("detector must be a non-empty string")
    category = data.get("category", "integrity")
    if not isinstance(category, str) or not category:
        raise MalformedFindingError("category must be a non-empty string")
    severity = data.get("severity")
    if severity not in SEVERITIES:
        raise MalformedFindingError(
            f"severity {severity!r} is unknown; want one of "
            f"{list(SEVERITIES)}")
    target = data.get("target")
    if not isinstance(target, Mapping) \
            or target.get("type") not in _TARGET_TYPES \
            or not isinstance(target.get("name"), str) \
            or not target.get("name"):
        raise MalformedFindingError(
            "finding target must be a typed target with a known "
            "type and a non-empty name")
    _parse_ts(data.get("observed_at"), "observed_at")
    summary = data.get("summary")
    if not isinstance(summary, str) or not summary \
            or len(summary) > 512:
        raise MalformedFindingError(
            "summary must be a non-empty string of at most 512 chars")
    refs = data.get("evidence_refs", [])
    if not isinstance(refs, list) \
            or any(not isinstance(r, str) or not r for r in refs):
        raise MalformedFindingError(
            "evidence_refs must be a list of non-empty strings")
    return SecurityFinding(
        finding_id=finding_id, incident_id=incident_id,
        detector=detector, category=category, severity=severity,
        target_type=target["type"], target_name=target["name"],
        observed_at=data["observed_at"], summary=summary,
        evidence_refs=tuple(refs))


@dataclass(frozen=True)
class ResponseProposal:
    """The coordination verdict: data only, nothing executed.

    ``executable`` is True only when ``outcome`` is
    OUTCOME_EXECUTABLE, which requires every chain link to have
    held (see module docstring).  Even then the proposal is a plan
    plus proofs: execution remains the confined executor's act
    under a consumed approval, outside this slice.
    """
    outcome: str
    executable: bool
    finding_id: Optional[str]
    recipe_id: Optional[str]
    plan_id: Optional[str]
    reason_codes: Tuple[str, ...]
    plan: Optional[Dict[str, Any]] = None
    policy_outcome: Optional[str] = None
    policy_reasons: Tuple[str, ...] = ()
    approval_reference_id: Optional[str] = None
    undo_transaction_id: Optional[str] = None
    dry_run: Tuple[Dict[str, Any], ...] = ()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "schema": COORDINATION_SCHEMA,
            "outcome": self.outcome, "executable": self.executable,
            "finding_id": self.finding_id, "recipe_id": self.recipe_id,
            "plan_id": self.plan_id,
            "reason_codes": list(self.reason_codes),
            "plan": self.plan,
            "policy_outcome": self.policy_outcome,
            "policy_reasons": list(self.policy_reasons),
            "approval_reference_id": self.approval_reference_id,
            "undo_transaction_id": self.undo_transaction_id,
            "dry_run": [dict(d) for d in self.dry_run],
        }


def _abstain(finding_id, recipe_id, plan_id, codes, **kw):
    return ResponseProposal(
        outcome=OUTCOME_ABSTAIN, executable=False,
        finding_id=finding_id, recipe_id=recipe_id, plan_id=plan_id,
        reason_codes=tuple(codes), **kw)


def build_transaction_record(plan: Mapping[str, Any], recipe: Any, *,
                             transaction_id: str,
                             created_at: str) -> Dict[str, Any]:
    """Derive a LIF-0405 transaction record for an instantiated plan.

    The undo entry of every step is the catalog undo the recipe
    itself declares; undo arguments are the forward arguments the
    undo verb declares (the honest overlap -- e.g. remove_package
    needs the version install_package took).  The record is returned
    UNVALIDATED on purpose: ``transactions.validate_transaction``
    (called by ``propose_response`` and by the durable store) is the
    judge, and a record it refuses can never support an executable
    proposal.
    """
    parsed = _recipes._resolve(recipe)
    undo_by_step = {s.step_id: s.undo_verb for s in parsed.steps}
    steps: List[Dict[str, Any]] = []
    for step in plan["steps"]:
        undo_verb = undo_by_step.get(step["step_id"])
        undo = None
        if undo_verb and undo_verb != "none":
            from .actions import get_action
            declared = {a.name for a in get_action(undo_verb).args}
            undo = {
                "action_verb": undo_verb,
                "target": dict(step["target"]),
                "args": {k: v for k, v in (step.get("args") or {}).items()
                         if k in declared},
            }
        steps.append({
            "step_id": step["step_id"],
            "action_verb": step["action_verb"],
            "target": dict(step["target"]),
            "args": dict(step.get("args") or {}),
            "undo": undo,
        })
    return {
        "schema": _transactions.TRANSACTION_SCHEMA,
        "schema_version": _transactions.TRANSACTION_SCHEMA_VERSION,
        "transaction_id": transaction_id, "plan_id": plan["plan_id"],
        "plan_digest": None, "title": plan.get("title", ""),
        "state": "planned", "created_at": created_at,
        "expires_at": plan.get("expires_at"), "steps": steps,
    }


def propose_response(finding: Any, *, recipe_id: str,
                     bindings: Mapping[str, Any], plan_id: str,
                     hypothesis_ids: List[str], created_at: str,
                     expires_at: str,
                     observations: Mapping[str, bool],
                     identity: Any = None, context: Any = None,
                     ledger: Any = None, reference: Any = None,
                     key: Any = None, now: Any = None,
                     transaction_record: Any = None,
                     undo_manifest: Any = None) -> ResponseProposal:
    """Coordinate one finding into a response proposal, or abstain.

    Every parameter after ``observations`` is one link of the safety
    chain; omitting any of them is not an error, it is an abstain
    naming the missing link.  A malformed FINDING is the one caller
    error that raises (MalformedFindingError): coordination never
    guesses at what a finding says.
    """
    parsed_finding = validate_finding(finding)
    fid = parsed_finding.finding_id

    # (a) The recipe must be a banked LIF-0501 recipe, applicable.
    try:
        recipe = _recipes._resolve(recipe_id)
    except _recipes.RecipeError:
        return _abstain(fid, recipe_id if isinstance(recipe_id, str)
                        else None, None, ("UNKNOWN_RECIPE",))
    applicability = _recipes.check_applicability(recipe, observations)
    if applicability.outcome != "applicable":
        return _abstain(fid, recipe.recipe_id, None,
                        applicability.reason_codes)
    try:
        plan = _recipes.instantiate(
            recipe, plan_id=plan_id,
            incident_id=parsed_finding.incident_id,
            hypothesis_ids=hypothesis_ids, bindings=bindings,
            created_at=created_at, expires_at=expires_at)
    except _recipes.RecipeError as exc:
        return _abstain(fid, recipe.recipe_id, None,
                        ("RECIPE_BINDING_FAILED", type(exc).__name__))
    pid = plan["plan_id"]

    # The finding must be bound to THIS plan: same incident, and its
    # exact target inside the plan's resource scope.
    if parsed_finding.scope_key() not in _approval.resource_scope(plan):
        return _abstain(fid, recipe.recipe_id, pid,
                        ("FINDING_TARGET_OUT_OF_SCOPE",), plan=plan)

    # (b) The banked policy engine must ALLOW the plan.
    if identity is None or context is None:
        return _abstain(fid, recipe.recipe_id, pid,
                        ("POLICY_INPUT_MISSING",), plan=plan)
    decision = _policy.evaluate(_policy.PolicyRequest(
        plan=plan, identity=identity, context=context))
    if decision.outcome != _policy.ALLOW:
        return _abstain(
            fid, recipe.recipe_id, pid,
            (f"POLICY_{decision.outcome}",) + tuple(decision.reason_codes),
            plan=plan, policy_outcome=decision.outcome,
            policy_reasons=tuple(decision.reason_codes))

    # (c) The banked signed-approval flow must hold for this plan.
    if ledger is None or reference is None or key is None:
        return _abstain(fid, recipe.recipe_id, pid,
                        ("APPROVAL_MISSING",), plan=plan,
                        policy_outcome=decision.outcome,
                        policy_reasons=tuple(decision.reason_codes))
    approval_kw: Dict[str, Any] = {}
    try:
        _approval.verify_reference_signature(reference, key=key)
    except _approval.ApprovalError:
        return _abstain(fid, recipe.recipe_id, pid,
                        ("APPROVAL_SIGNATURE_INVALID",), plan=plan,
                        policy_outcome=decision.outcome,
                        policy_reasons=tuple(decision.reason_codes))
    digest = _approval.plan_digest(plan)
    if reference.plan_id != pid or reference.digest != digest:
        return _abstain(fid, recipe.recipe_id, pid,
                        ("APPROVAL_PLAN_MISMATCH",), plan=plan,
                        policy_outcome=decision.outcome,
                        policy_reasons=tuple(decision.reason_codes))
    moment = now
    if moment is None:
        try:
            moment = _parse_ts(context.evaluated_at, "evaluated_at")
        except MalformedFindingError:
            return _abstain(fid, recipe.recipe_id, pid,
                            ("APPROVAL_CLOCK_UNVERIFIED",), plan=plan,
                            policy_outcome=decision.outcome,
                            policy_reasons=tuple(decision.reason_codes))
    moment = moment.astimezone(timezone.utc)
    ref_expiry = _approval._parse_ts(reference.expires_at, "expires_at")
    if moment >= ref_expiry:
        return _abstain(fid, recipe.recipe_id, pid,
                        ("APPROVAL_EXPIRED",), plan=plan,
                        policy_outcome=decision.outcome,
                        policy_reasons=tuple(decision.reason_codes))
    refs = getattr(ledger, "_refs", None)
    records = getattr(ledger, "_records", None)
    if not isinstance(refs, dict) or not isinstance(records, dict) \
            or reference.reference_id not in refs:
        return _abstain(fid, recipe.recipe_id, pid,
                        ("APPROVAL_UNVERIFIABLE",), plan=plan,
                        policy_outcome=decision.outcome,
                        policy_reasons=tuple(decision.reason_codes))
    record = records.get(reference.reference_id)
    if record is None or record.decision != "approved":
        return _abstain(fid, recipe.recipe_id, pid,
                        ("APPROVAL_NOT_APPROVED",), plan=plan,
                        policy_outcome=decision.outcome,
                        policy_reasons=tuple(decision.reason_codes),
                        approval_reference_id=reference.reference_id)
    if record.consumed:
        return _abstain(fid, recipe.recipe_id, pid,
                        ("APPROVAL_ALREADY_CONSUMED",), plan=plan,
                        policy_outcome=decision.outcome,
                        policy_reasons=tuple(decision.reason_codes),
                        approval_reference_id=reference.reference_id)
    approval_kw = {"approval_reference_id": reference.reference_id}

    # (d) A LIF-0405 undo manifest must exist before executable.
    tx_id: Optional[str] = None
    if transaction_record is not None:
        try:
            payload = _transactions.validate_transaction(
                transaction_record)
        except _transactions.TransactionError:
            return _abstain(fid, recipe.recipe_id, pid,
                            ("UNDO_MANIFEST_INVALID",), plan=plan,
                            policy_outcome=decision.outcome,
                            policy_reasons=tuple(decision.reason_codes),
                            **approval_kw)
        if payload["plan_id"] != pid:
            return _abstain(fid, recipe.recipe_id, pid,
                            ("UNDO_PLAN_MISMATCH",), plan=plan,
                            policy_outcome=decision.outcome,
                            policy_reasons=tuple(decision.reason_codes),
                            **approval_kw)
        recorded_digest = payload.get("plan_digest")
        if recorded_digest is not None and recorded_digest != digest:
            return _abstain(fid, recipe.recipe_id, pid,
                            ("UNDO_DIGEST_MISMATCH",), plan=plan,
                            policy_outcome=decision.outcome,
                            policy_reasons=tuple(decision.reason_codes),
                            **approval_kw)
        plan_shape = [(s["step_id"], s["action_verb"],
                       s["target"]["type"], s["target"]["name"])
                      for s in plan["steps"]]
        tx_shape = [(s["step_id"], s["action_verb"],
                     s["target"]["type"], s["target"]["name"])
                    for s in payload["steps"]]
        if tx_shape != plan_shape:
            return _abstain(fid, recipe.recipe_id, pid,
                            ("UNDO_STEP_MISMATCH",), plan=plan,
                            policy_outcome=decision.outcome,
                            policy_reasons=tuple(decision.reason_codes),
                            **approval_kw)
        if not payload["undoable"]:
            return _abstain(fid, recipe.recipe_id, pid,
                            ("UNDO_MANIFEST_INCOMPLETE",), plan=plan,
                            policy_outcome=decision.outcome,
                            policy_reasons=tuple(decision.reason_codes),
                            **approval_kw)
        tx_id = payload["transaction_id"]
    elif undo_manifest is not None:
        if getattr(undo_manifest, "plan_id", None) != pid \
                or not getattr(undo_manifest, "undoable", False) \
                or getattr(undo_manifest, "missing", ()):
            return _abstain(fid, recipe.recipe_id, pid,
                            ("UNDO_MANIFEST_INCOMPLETE",), plan=plan,
                            policy_outcome=decision.outcome,
                            policy_reasons=tuple(decision.reason_codes),
                            **approval_kw)
        tx_id = getattr(undo_manifest, "transaction_id", None)
    else:
        return _abstain(fid, recipe.recipe_id, pid,
                        ("UNDO_MANIFEST_MISSING",), plan=plan,
                        policy_outcome=decision.outcome,
                        policy_reasons=tuple(decision.reason_codes),
                        **approval_kw)

    # Proof level: the banked dry-run executor validates every step
    # against the approval-bound authorization and executes nothing.
    plan_expiry = _approval._parse_ts(plan["expires_at"], "expires_at")
    auth = Authorization(
        plan_id=pid, plan_digest=digest, nonce=reference.nonce,
        consent_mode=plan["consent_mode"],
        expires_at=plan_expiry.timestamp())
    executor = DryRunExecutor()
    dry_run: List[Dict[str, Any]] = []
    for step in plan["steps"]:
        request = ActionRequest(
            verb=step["action_verb"],
            target=ActionTarget(type=step["target"]["type"],
                                name=step["target"]["name"]),
            args=dict(step.get("args") or {}), plan_id=pid,
            expires_at=plan_expiry.timestamp())
        try:
            result = executor.execute(request, auth, moment.timestamp())
        except Exception as exc:  # catalog refusal = a broken link
            return _abstain(fid, recipe.recipe_id, pid,
                            ("DRYRUN_REFUSED", type(exc).__name__),
                            plan=plan, policy_outcome=decision.outcome,
                            policy_reasons=tuple(decision.reason_codes),
                            undo_transaction_id=tx_id, **approval_kw)
        dry_run.append({"step_id": step["step_id"], "verb": result.verb,
                        "status": result.status,
                        "executed": result.executed,
                        "detail": result.detail})

    return ResponseProposal(
        outcome=OUTCOME_EXECUTABLE, executable=True, finding_id=fid,
        recipe_id=recipe.recipe_id, plan_id=pid,
        reason_codes=("ALL_CHAIN_LINKS_VERIFIED",), plan=plan,
        policy_outcome=decision.outcome,
        policy_reasons=tuple(decision.reason_codes),
        approval_reference_id=reference.reference_id,
        undo_transaction_id=tx_id, dry_run=tuple(dry_run))
