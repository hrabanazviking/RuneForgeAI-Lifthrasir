"""User approval UX and signed/unique plan references (LIF-0404).

SPDX-License-Identifier: GPL-2.0-only

Contract/test-level implementation of the P4 approval boundary:

- A plan (v0.1 plan record, LIF-0004) is referenced by a unique,
  signed reference: plan digest + fresh nonce + issue/expiry times +
  the exact resource scope, signed with HMAC-SHA256 (ADR-0002
  Decision D3: a one-time authorization token bound to the plan hash
  and a nonce, with expiry checked at execution time).
- The approval prompt is a deterministic plain-text rendering with
  separate sections (proposal, exact scope, risk/consent, rollback,
  verification, expiry, reference) per research/34: the user never
  approves an opaque blob.
- Decisions are single-use and terminal: approve/reject once; an
  approved reference is consumed exactly once for execution, scoped
  to the named resources. Replay, tampering, expiry, wrong-resource
  and below-floor consent all fail closed.

Signing here is FIXTURE-SCALE only: keys are caller-supplied bytes
(HMAC), never stored by this module, and tests use throwaway keys.
Production key protection (research/22) is future work, stated in
docs/APPROVAL-UX.md. Agents never sign DCO; nothing here does.
No host state is touched: this module is pure data and text.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import re
import secrets
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

PLAN_ID_RE = re.compile(r"^plan-[a-z0-9][a-z0-9-]*$")
DIGEST_RE = re.compile(r"^sha256:[a-f0-9]{64}$")

CONSENT_ORDER = {
    "none": 0, "standing-opt-in": 1, "session-blanket": 2,
    "allowlist-notice": 3, "per-action": 4, "human-only": 5,
    "never": 6,
}
CONSENT_FLOOR = {
    "L0": "none", "L1": "standing-opt-in", "L2": "session-blanket",
    "L3": "allowlist-notice", "L4": "per-action", "L5": "human-only",
}
AGENT_FORBIDDEN_CONSENT = frozenset({"never"})


class ApprovalError(Exception):
    """Base class for all named approval refusals."""


class MalformedPlanError(ApprovalError):
    pass


class ConsentFloorError(ApprovalError):
    pass


class ForbiddenApprovalError(ApprovalError):
    pass


class SignatureError(ApprovalError):
    pass


class DigestMismatchError(ApprovalError):
    pass


class DuplicateReferenceError(ApprovalError):
    pass


class UnknownReferenceError(ApprovalError):
    pass


class ExpiredReferenceError(ApprovalError):
    pass


class ReplayError(ApprovalError):
    pass


class ResourceScopeError(ApprovalError):
    pass


class DecisionError(ApprovalError):
    pass


def _parse_ts(value, field_name):
    if not isinstance(value, str) or not value:
        raise MalformedPlanError(f"{field_name} must be an RFC3339 string")
    text = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        moment = datetime.fromisoformat(text)
    except ValueError as exc:
        raise MalformedPlanError(
            f"{field_name} {value!r} is not a valid timestamp") from exc
    if moment.tzinfo is None:
        raise MalformedPlanError(f"{field_name} must carry a timezone")
    return moment.astimezone(timezone.utc)


def _fmt_ts(moment):
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def canonical_plan_bytes(plan):
    """Canonical bytes of a v0.1 plan record (sorted, compact JSON)."""
    if not isinstance(plan, dict):
        raise MalformedPlanError("plan must be a JSON object (dict)")
    try:
        text = json.dumps(plan, sort_keys=True, separators=(",", ":"),
                          ensure_ascii=False)
    except (TypeError, ValueError) as exc:
        raise MalformedPlanError(f"plan is not JSON-serializable: {exc}") from exc
    return text.encode("utf-8")


def check_plan_shape(plan):
    """Structural checks this slice owns (schema validation is LIF-0004)."""
    if not isinstance(plan, dict):
        raise MalformedPlanError("plan must be a JSON object (dict)")
    plan_id = plan.get("plan_id")
    if not isinstance(plan_id, str) or not PLAN_ID_RE.match(plan_id):
        raise MalformedPlanError(f"plan_id {plan_id!r} is malformed")
    if plan.get("schema") != "lifthrasir.plan.v0.1":
        raise MalformedPlanError("plan schema must be lifthrasir.plan.v0.1")
    risk = plan.get("risk_level")
    if risk not in CONSENT_FLOOR:
        raise MalformedPlanError(f"risk_level {risk!r} is unknown")
    consent = plan.get("consent_mode")
    if consent not in CONSENT_ORDER:
        raise MalformedPlanError(f"consent_mode {consent!r} is unknown")
    if CONSENT_ORDER[consent] < CONSENT_ORDER[CONSENT_FLOOR[risk]]:
        raise ConsentFloorError(
            f"consent_mode {consent!r} is below the floor "
            f"{CONSENT_FLOOR[risk]!r} for risk_level {risk} "
            "(docs/RISK-MATRIX.md: consent is a floor, never weaker)")
    if consent in AGENT_FORBIDDEN_CONSENT:
        raise ForbiddenApprovalError(
            "consent_mode 'never' can never be approved for an agent "
            "(ROADMAP section 0 invariants; RISK-MATRIX prohibited class)")
    steps = plan.get("steps")
    if not isinstance(steps, list) or not steps:
        raise MalformedPlanError("plan steps must be a non-empty list")
    for step in steps:
        if not isinstance(step, dict) or not step.get("action_verb"):
            raise MalformedPlanError("every step needs an action_verb")
        target = step.get("target")
        if not isinstance(target, dict) or not target.get("type") or not target.get("name"):
            raise MalformedPlanError("every step needs target type+name")
    created = _parse_ts(plan.get("created_at"), "created_at")
    expires = _parse_ts(plan.get("expires_at"), "expires_at")
    if expires <= created:
        raise MalformedPlanError("plan expires_at must be after created_at")


def plan_digest(plan):
    """Content digest of the canonical plan: 'sha256:<hex>'."""
    check_plan_shape(plan)
    return "sha256:" + hashlib.sha256(canonical_plan_bytes(plan)).hexdigest()


def resource_scope(plan):
    """Exact resources a plan touches: sorted 'type:name' per step."""
    return tuple(sorted({f"{s['target']['type']}:{s['target']['name']}" for s in plan["steps"]}))


def _signing_payload(ref_fields):
    return json.dumps(ref_fields, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def _sign(key, payload):
    return "hmac-sha256:" + hmac.new(key, payload, hashlib.sha256).hexdigest()


@dataclass(frozen=True)
class PlanReference:
    """A unique, signed reference to exactly one immutable plan."""
    reference_id: str
    plan_id: str
    digest: str
    nonce: str
    scope: Tuple[str, ...]
    issued_at: str
    expires_at: str
    signature: str

    def payload_fields(self):
        return {
            "reference_id": self.reference_id, "plan_id": self.plan_id,
            "digest": self.digest, "nonce": self.nonce,
            "scope": list(self.scope), "issued_at": self.issued_at,
            "expires_at": self.expires_at,
        }

    def short_check_code(self):
        """Human-comparable short code: first 12 digest hex, grouped."""
        hexpart = self.digest.split(":", 1)[1][:12]
        return "-".join(hexpart[i:i + 4] for i in range(0, 12, 4))


def mint_plan_reference(plan, *, key, now, ttl_seconds=900, nonce=None):
    """Mint a signed, unique reference for a plan."""
    if not isinstance(key, (bytes, bytearray)) or len(key) < 16:
        raise SignatureError("signing key must be at least 16 bytes")
    if ttl_seconds < 1:
        raise MalformedPlanError("ttl_seconds must be positive")
    digest = plan_digest(plan)
    plan_expiry = _parse_ts(plan["expires_at"], "expires_at")
    issued = now.astimezone(timezone.utc)
    expires = min(issued + timedelta(seconds=ttl_seconds), plan_expiry)
    if expires <= issued:
        raise ExpiredReferenceError("plan is already expired at mint time")
    nonce = nonce or secrets.token_hex(16)
    if not re.fullmatch(r"[a-f0-9]{16,64}", nonce):
        raise MalformedPlanError("nonce must be 16-64 lowercase hex chars")
    scope = resource_scope(plan)
    reference_id = "pref-" + hashlib.sha256(f"{digest}:{nonce}".encode("utf-8")).hexdigest()[:20]
    fields = {
        "reference_id": reference_id, "plan_id": plan["plan_id"],
        "digest": digest, "nonce": nonce, "scope": list(scope),
        "issued_at": _fmt_ts(issued), "expires_at": _fmt_ts(expires),
    }
    return PlanReference(
        reference_id=reference_id, plan_id=plan["plan_id"], digest=digest,
        nonce=nonce, scope=scope, issued_at=fields["issued_at"],
        expires_at=fields["expires_at"],
        signature=_sign(bytes(key), _signing_payload(fields)))


def verify_reference_signature(ref, *, key):
    expected = _sign(bytes(key), _signing_payload(ref.payload_fields()))
    if not hmac.compare_digest(expected, ref.signature):
        raise SignatureError(f"signature on reference {ref.reference_id} does not verify")


def render_approval_prompt(plan, ref):
    """Deterministic plain-text approval prompt (the UX contract)."""
    check_plan_shape(plan)
    if ref.plan_id != plan["plan_id"] or ref.digest != plan_digest(plan):
        raise DigestMismatchError("reference does not match this plan (id or digest differs)")
    lines = [
        "LIFTHRASIR APPROVAL REQUEST",
        f"Plan: {plan['plan_id']} - {plan.get('title', '')}",
        f"Risk: {plan['risk_level']}  Consent required: {plan['consent_mode']} (floor for {plan['risk_level']}: {CONSENT_FLOOR[plan['risk_level']]})",
        "",
        "WHAT IS PROPOSED",
    ]
    for step in plan["steps"]:
        lines.append(f"- {step['action_verb']} -> {step['target']['type']}:{step['target']['name']}")
    lines += ["", "EXACT SCOPE (nothing outside this list is authorized)"]
    lines += [f"- {item}" for item in ref.scope]
    lines += ["", "PRECONDITIONS"]
    lines += [f"- {item}" for item in plan.get("preconditions", [])]
    rollback = plan.get("rollback", {})
    lines += ["", "ROLLBACK", f"- {rollback.get('method', '')}: {rollback.get('description', '')}", "", "VERIFICATION", f"- {plan.get('verification', {}).get('method', '')}", "", "REFERENCE AND EXPIRY", f"- Reference: {ref.reference_id}", f"- Plan digest: {ref.digest}", f"- Check code: {ref.short_check_code()}", f"- Issued: {ref.issued_at}  Expires: {ref.expires_at}", "- Approval is single-use, binds exactly this plan digest and scope, and cannot be replayed or transferred.", ""]
    return "\n".join(lines)


@dataclass
class ApprovalRecord:
    """Journal-shaped approval record: hash, resource, decision, expiry."""
    reference_id: str
    plan_id: str
    digest: str
    scope: Tuple[str, ...]
    decision: str
    approver: str
    decided_at: str
    expires_at: str
    consumed: bool = False


@dataclass
class ApprovalLedger:
    """In-memory reference/decision registry (durable state is LIF-0405)."""
    _refs: Dict[str, PlanReference] = field(default_factory=dict)
    _nonces: set = field(default_factory=set)
    _records: Dict[str, ApprovalRecord] = field(default_factory=dict)

    def register(self, ref, *, key):
        verify_reference_signature(ref, key=key)
        if ref.nonce in self._nonces or ref.reference_id in self._refs:
            raise DuplicateReferenceError(f"nonce/reference {ref.reference_id} was already issued: plan references are unique and never re-issued")
        self._nonces.add(ref.nonce)
        self._refs[ref.reference_id] = ref
        return ref

    def _live_ref(self, reference_id, plan, now):
        ref = self._refs.get(reference_id)
        if ref is None:
            raise UnknownReferenceError(f"unknown reference {reference_id}")
        if plan_digest(plan) != ref.digest or plan["plan_id"] != ref.plan_id:
            raise DigestMismatchError("plan presented differs from the referenced plan digest: substituted or edited plans are refused")
        if now.astimezone(timezone.utc) >= _parse_ts(ref.expires_at, "expires_at"):
            raise ExpiredReferenceError(f"reference {reference_id} expired at {ref.expires_at}")
        return ref

    def decide(self, reference_id, plan, *, decision, approver, now):
        if decision not in ("approved", "rejected"):
            raise DecisionError("decision must be 'approved' or 'rejected'")
        if not approver or not isinstance(approver, str):
            raise DecisionError("approver identity is required")
        ref = self._live_ref(reference_id, plan, now)
        if reference_id in self._records:
            raise ReplayError(f"reference {reference_id} already decided ({self._records[reference_id].decision}): decisions are single-use and terminal")
        record = ApprovalRecord(reference_id=reference_id, plan_id=ref.plan_id, digest=ref.digest, scope=ref.scope, decision=decision, approver=approver, decided_at=_fmt_ts(now), expires_at=ref.expires_at)
        self._records[reference_id] = record
        return record

    def consume_for_execution(self, reference_id, plan, *, resource, now):
        """Consume an approval exactly once, for one in-scope resource."""
        ref = self._live_ref(reference_id, plan, now)
        record = self._records.get(reference_id)
        if record is None or record.decision != "approved":
            raise DecisionError(f"reference {reference_id} has no approval to consume")
        if record.consumed:
            raise ReplayError(f"approval {reference_id} was already consumed: approvals are one-time tokens (ADR-0002 D3)")
        if resource not in ref.scope:
            raise ResourceScopeError(f"resource {resource!r} is outside the approved scope {list(ref.scope)}")
        record.consumed = True
        return record
