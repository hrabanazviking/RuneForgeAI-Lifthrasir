"""Deterministic policy decisions for the authority boundary (LIF-0402).

SPDX-License-Identifier: GPL-2.0-only

Home justification: ADR-0002 places the authorization plane in the
core package: ``lifthrasir-policy`` is a small, deterministic,
independently controlled process owning policy evaluation and the
sole minting of authorizations, and LIF-0201/LIF-0301 already
established ``src/lifthrasir/`` as the core home.  This module is
that plane's decision core, beside the event bus and the evidence
store -- not in ``lab/`` (rapid prototypes) and not in ``ui/``.

Scope of THIS slice (honest bounds): policy decisions are data plus
evaluation only.  ``evaluate()`` is a pure function: it reads a plan,
an identity, an authorization context and a precondition snapshot,
and returns a decision record.  It executes nothing, writes nothing,
opens no file or socket, and mints NO authorization token -- signed,
unique plan references are LIF-0404, the executor process is
LIF-0403, and the typed action catalog is LIF-0401.  Nothing here is
an enforcement side effect; the broker (future) is the only consumer
that may act on a decision, and only on ALLOW.

Decision contract (research/25, policy decision API): input is an
immutable plan, an authorization context, a host capability /
resource descriptor and a current exact precondition snapshot;
output is ALLOW, DENY or REQUIRE_HUMAN with a policy version and
reason codes.  The default for unknown action, resource or version
is DENY.  An agent cannot submit a policy override, and neither
prompts, logs nor retrieved documents can grant capabilities
(research/03 trust boundaries; research/33 invariants 3 and 4).

Rules encoded, each traceable to a banked source:

- Risk tiers L0-L5 and consent floors are docs/RISK-MATRIX.md
  (LIF-0003) verbatim: L0 none, L1 standing-opt-in, L2
  session-blanket, L3 allowlist-notice, L4 per-action, L5
  human-only; consent strictness ranks none 0 .. never 6.  Consent
  is a floor, never a ceiling (matrix rule 4).
- Prohibited actions (matrix P-01..P-10, master roadmap section 0
  invariants 1, 2, 5, 6, 7): bootloader, kernel image, firmware,
  partition table, encryption, package trust roots, SSH access,
  critical firewall state, user home files, ambient root / general
  shell, agent DCO signing or upstream sending, and fuzzing or
  corruption experiments on the working machine are DENY for an
  agent under ANY consent -- consent cannot authorize what the
  invariants prohibit.
- L5 is human-only maintenance: this engine never ALLOWs it for
  broker execution, whoever asks.  A human executes L5 outside the
  broker in a dedicated maintenance environment; the engine's
  answer is DENY with HUMAN_ONLY so no caller can mistake it for
  a grantable path.
- Highest matching tier wins and unknown means escalate (matrix
  rules 1 and 3): the engine computes an effective risk from the
  steps, resources and their critical/sensitive flags; a plan that
  declares LESS than the effective risk is DENY
  (RISK_UNDERDECLARED), never silently upgraded and allowed.
- Identity: an unauthenticated identity is DENY.  Consent above
  ``none`` counts only when granted by a human; an agent granting
  consent -- above all to itself -- is DENY (CONSENT_NOT_HUMAN /
  SELF_AUTHORIZATION; research/03: a higher-level agent cannot
  grant its own lower-level privileges, and no always-approve
  mechanism exists for L4-L5).
- Preconditions (research/33 dangerous-interleaving invariant):
  every plan precondition must be observed TRUE in the current
  snapshot.  Observed false is DENY (PRECONDITION_FAILED); absent
  from the snapshot is unverified, and unverified is not verified
  (invariant 4), so it escalates to REQUIRE_HUMAN
  (PRECONDITION_UNVERIFIED) instead of allowing.
- Expiry: a plan at or past its expires_at is DENY (PLAN_EXPIRED);
  expired plans are never replayed (ADR-0002 failure propagation).
- Emergency stop: while the stop is active, every state-changing
  decision (effective risk L2 or above) is DENY
  (EMERGENCY_STOP_ACTIVE); read-only observation (L0/L1) still
  evaluates normally -- fail closed for changes, fail operational
  for diagnosis (ADR-0002).
- Undo: a live mutating step (L3/L4) without a named rollback
  method is DENY (NO_UNDO_PATH; research/33 invariant 7: a verified
  undo path must exist before execute).
- Allowlist: an L3 step's target must be on the human-approved
  allowlist carried in the context, else DENY
  (RESOURCE_NOT_ALLOWLISTED).  Adding to the allowlist is itself a
  human act outside this engine.

COORDINATION GAP (recorded, not hidden): the action-verb and
resource-type vocabularies below are a conservative INTERIM set
assembled only from banked sources -- the LIF-0004 plan examples
(edit_config_in_guest, restart_unit_in_guest), research/03 broker
verbs (restart_unit, stage_package_update, quarantine_file) and the
risk-matrix worked examples.  LIF-0401 (typed action catalog,
team-04) is building in parallel on another worktree; when it banks,
its catalog becomes the authority and this interim set must be
reconciled to it.  Until then the set fails closed: any verb or
resource type outside it is DENY (UNKNOWN_ACTION_VERB /
UNKNOWN_RESOURCE_TYPE), so the gap can only over-deny, never
over-allow.

Determinism: evaluation takes its clock from the context
(``evaluated_at``); nothing here reads wall time, randomness, the
filesystem, the network or the environment, and inputs are never
mutated.  Same inputs, same decision, byte for byte.
"""
from __future__ import annotations

import copy
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, FrozenSet, Mapping, Optional, Tuple

POLICY_VERSION = "0.1"
PLAN_SCHEMA = "lifthrasir.plan.v0.1"
PLAN_SCHEMA_VERSION = "0.1"

ALLOW = "ALLOW"
DENY = "DENY"
REQUIRE_HUMAN = "REQUIRE_HUMAN"
OUTCOMES = frozenset({ALLOW, DENY, REQUIRE_HUMAN})

RISK_LEVELS = ("L0", "L1", "L2", "L3", "L4", "L5")
_RISK_RANK = {level: i for i, level in enumerate(RISK_LEVELS)}

# docs/RISK-MATRIX.md (LIF-0003): consent strictness is a total order.
CONSENT_RANKS = {
    "none": 0,
    "standing-opt-in": 1,
    "session-blanket": 2,
    "allowlist-notice": 3,
    "per-action": 4,
    "human-only": 5,
    "never": 6,
}
# Minimum consent per tier (the matrix consent column, verbatim).
TIER_CONSENT_FLOOR = {
    "L0": "none",
    "L1": "standing-opt-in",
    "L2": "session-blanket",
    "L3": "allowlist-notice",
    "L4": "per-action",
    "L5": "human-only",
}

IDENTITY_KINDS = frozenset({"human", "agent", "system"})
RESOURCE_SCOPES = frozenset({"live-host", "lab-guest", "local-store"})

# --- Interim vocabularies (see COORDINATION GAP in the docstring) ---
# verb -> base risk tier, before resource adjustments.
ACTION_VERB_TIERS = {
    "observe_status": "L0",
    "observe_metrics": "L0",
    "read_journal": "L1",
    "read_evidence": "L1",
    "edit_config_in_guest": "L2",
    "restart_unit_in_guest": "L2",
    "run_test_in_guest": "L2",
    "restart_unit": "L3",
    "revert_config": "L3",
    "quarantine_file": "L3",
    "stage_package_update": "L4",
    "install_package": "L4",
    "reinstall_package": "L4",
    "change_firewall_rule": "L4",
}
GUEST_VERBS = frozenset(
    v for v in ACTION_VERB_TIERS if v.endswith("_in_guest"))
LIVE_VERBS = frozenset({
    "restart_unit", "revert_config", "quarantine_file",
    "stage_package_update", "install_package", "reinstall_package",
    "change_firewall_rule",
})
READ_VERBS = frozenset({
    "observe_status", "observe_metrics", "read_journal", "read_evidence",
})
RESOURCE_TYPES = frozenset({
    "systemd-unit", "systemd-user-unit", "config-file", "package",
    "lab-guest", "file", "firewall-rule", "evidence-store", "service",
})
# Target types an agent may never touch (RISK-MATRIX P-01..P-10).
PROHIBITED_TARGET_TYPES = frozenset({
    "bootloader", "kernel-image", "firmware", "partition-table",
    "encryption", "package-trust-roots", "ssh-access",
    "critical-firewall", "home-directory",
})
PROHIBITED_VERBS = frozenset({
    "modify_bootloader", "replace_kernel", "replace_firmware",
    "modify_partitions", "change_encryption", "grant_root_shell",
    "run_shell", "sign_dco", "send_patch_upstream",
    "modify_trust_roots", "modify_ssh_access", "modify_home_files",
    "fuzz_host", "corrupt_host",
})

REASON_MESSAGES = {
    "ALL_CHECKS_PASSED": "every policy check passed",
    "MALFORMED_REQUEST": "request is missing or malformed in a required field",
    "UNKNOWN_SCHEMA_VERSION": "plan schema or version is not the pinned v0.1",
    "UNKNOWN_RISK_LEVEL": "declared risk level is not one of L0-L5",
    "UNKNOWN_CONSENT_MODE": "a consent mode is not one of the seven matrix modes",
    "IDENTITY_UNAUTHENTICATED": "requesting identity is not authenticated",
    "IDENTITY_UNKNOWN_KIND": "identity kind is not human, agent or system",
    "PROHIBITED_ACTION": "action is prohibited for agents under any consent (section 0)",
    "UNKNOWN_ACTION_VERB": "action verb is outside the known catalog set; default is deny",
    "UNKNOWN_RESOURCE": "a step target has no resource descriptor in the context",
    "UNKNOWN_RESOURCE_TYPE": "a step target type is outside the known resource types",
    "SCOPE_MISMATCH": "verb scope (guest/live) does not match the resource scope",
    "RISK_UNDERDECLARED": "declared risk is below the effective risk of the steps",
    "HUMAN_ONLY": "risk L5 is human-only maintenance, never broker-executed",
    "CONSENT_BELOW_FLOOR": "granted consent is weaker than the tier floor",
    "CONSENT_NOT_HUMAN": "consent above none was not granted by a human",
    "SELF_AUTHORIZATION": "an identity granted consent to itself",
    "RESOURCE_NOT_ALLOWLISTED": "an L3 target is not on the human-approved allowlist",
    "PRECONDITION_FAILED": "a precondition is observed false in the current snapshot",
    "PRECONDITION_UNVERIFIED": "a precondition has no observation in the snapshot",
    "PLAN_EXPIRED": "plan is at or past its expiry; expired plans never replay",
    "EMERGENCY_STOP_ACTIVE": "emergency stop is active; state-changing work is denied",
    "NO_UNDO_PATH": "a live mutating step has no named rollback method",
}

_PLAN_ID_RE = re.compile(r"^plan-[a-z0-9][a-z0-9-]*$")


class PolicyError(Exception):
    """Base class for named policy-engine refusals of malformed API use."""


@dataclass(frozen=True)
class Identity:
    """Who is asking.  ``kind`` is human, agent or system."""
    principal_id: str
    kind: str
    authenticated: bool = False


@dataclass(frozen=True)
class ResourceInfo:
    """Host capability / resource descriptor for one named target."""
    scope: str  # live-host | lab-guest | local-store
    critical: bool = False
    sensitive: bool = False


@dataclass(frozen=True)
class AuthorizationContext:
    """Consent, allowlist, resource descriptors and the clock."""
    evaluated_at: str  # RFC 3339, e.g. 2026-11-05T17:30:00Z
    consent_mode_granted: Optional[str] = None
    consent_granted_by_id: Optional[str] = None
    consent_granted_by_kind: Optional[str] = None
    allowlist: FrozenSet[str] = frozenset()
    resources: Mapping[str, ResourceInfo] = field(default_factory=dict)
    precondition_snapshot: Mapping[str, bool] = field(default_factory=dict)
    emergency_stop_active: bool = False


@dataclass(frozen=True)
class PolicyRequest:
    plan: Mapping[str, Any]
    identity: Identity
    context: AuthorizationContext


@dataclass(frozen=True)
class PolicyDecision:
    """The decision record: data only, no side effect."""
    outcome: str
    policy_version: str
    plan_id: Optional[str]
    declared_risk_level: Optional[str]
    effective_risk_level: Optional[str]
    required_consent_mode: Optional[str]
    reason_codes: Tuple[str, ...]
    evaluated_at: Optional[str]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "outcome": self.outcome,
            "policy_version": self.policy_version,
            "plan_id": self.plan_id,
            "declared_risk_level": self.declared_risk_level,
            "effective_risk_level": self.effective_risk_level,
            "required_consent_mode": self.required_consent_mode,
            "reason_codes": list(self.reason_codes),
            "reasons": [REASON_MESSAGES.get(c, c) for c in self.reason_codes],
            "evaluated_at": self.evaluated_at,
        }


def required_consent_for(risk_level: str) -> str:
    """Consent floor for a tier, verbatim from docs/RISK-MATRIX.md."""
    if risk_level not in TIER_CONSENT_FLOOR:
        raise PolicyError(f"unknown risk level: {risk_level!r}")
    return TIER_CONSENT_FLOOR[risk_level]


def _parse_ts(value: Any) -> Optional[datetime]:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(timezone.utc)


def _step_tier(verb: str, info: ResourceInfo) -> str:
    tier = ACTION_VERB_TIERS[verb]
    if verb in READ_VERBS and info.sensitive and tier == "L0":
        return "L1"
    if verb in LIVE_VERBS and info.critical and _RISK_RANK[tier] < 4:
        return "L4"
    return tier


def request_from_dict(data: Mapping[str, Any]) -> PolicyRequest:
    """Build a PolicyRequest from plain mappings (fixture-friendly)."""
    if not isinstance(data, Mapping):
        raise PolicyError("request must be a mapping")
    ident = data.get("identity") or {}
    ctx = data.get("context") or {}
    resources = {}
    for name, spec in (ctx.get("resources") or {}).items():
        spec = spec or {}
        resources[name] = ResourceInfo(
            scope=spec.get("scope", ""),
            critical=bool(spec.get("critical", False)),
            sensitive=bool(spec.get("sensitive", False)),
        )
    return PolicyRequest(
        plan=data.get("plan") or {},
        identity=Identity(
            principal_id=ident.get("principal_id", ""),
            kind=ident.get("kind", ""),
            authenticated=bool(ident.get("authenticated", False)),
        ),
        context=AuthorizationContext(
            evaluated_at=ctx.get("evaluated_at", ""),
            consent_mode_granted=ctx.get("consent_mode_granted"),
            consent_granted_by_id=ctx.get("consent_granted_by_id"),
            consent_granted_by_kind=ctx.get("consent_granted_by_kind"),
            allowlist=frozenset(ctx.get("allowlist") or []),
            resources=resources,
            precondition_snapshot=dict(ctx.get("precondition_snapshot") or {}),
            emergency_stop_active=bool(ctx.get("emergency_stop_active", False)),
        ),
    )


def evaluate(request: PolicyRequest) -> PolicyDecision:
    """Evaluate one request deterministically.  Pure: no side effects."""
    plan = copy.deepcopy(dict(request.plan))  # never mutate caller data
    ident = request.identity
    ctx = request.context
    plan_id = plan.get("plan_id") if isinstance(plan.get("plan_id"), str) else None
    declared = plan.get("risk_level") if isinstance(plan.get("risk_level"), str) else None

    def deny_now(codes):
        return PolicyDecision(
            outcome=DENY, policy_version=POLICY_VERSION, plan_id=plan_id,
            declared_risk_level=declared, effective_risk_level=None,
            required_consent_mode=None, reason_codes=tuple(codes),
            evaluated_at=ctx.evaluated_at or None)

    # --- Phase A: structural validation (fail closed, immediately) ---
    structural = []
    if not isinstance(ident.principal_id, str) or not ident.principal_id:
        structural.append("MALFORMED_REQUEST")
    if plan.get("schema") != PLAN_SCHEMA or plan.get("schema_version") != PLAN_SCHEMA_VERSION:
        structural.append("UNKNOWN_SCHEMA_VERSION")
    if plan_id is None or not _PLAN_ID_RE.match(plan_id):
        structural.append("MALFORMED_REQUEST")
    if declared not in _RISK_RANK:
        structural.append("UNKNOWN_RISK_LEVEL")
    declared_consent = plan.get("consent_mode")
    if declared_consent not in CONSENT_RANKS:
        structural.append("UNKNOWN_CONSENT_MODE")
    if ctx.consent_mode_granted is not None and ctx.consent_mode_granted not in CONSENT_RANKS:
        structural.append("UNKNOWN_CONSENT_MODE")
    steps = plan.get("steps")
    if not isinstance(steps, list) or not steps:
        structural.append("MALFORMED_REQUEST")
        steps = []
    for step in steps:
        if not isinstance(step, Mapping) or not isinstance(step.get("action_verb"), str) \
                or not step.get("action_verb"):
            structural.append("MALFORMED_REQUEST")
            break
        target = step.get("target")
        if not isinstance(target, Mapping) or not target.get("type") or not target.get("name"):
            structural.append("MALFORMED_REQUEST")
            break
    evaluated_at = _parse_ts(ctx.evaluated_at)
    created_at = _parse_ts(plan.get("created_at"))
    expires_at = _parse_ts(plan.get("expires_at"))
    if evaluated_at is None or created_at is None or expires_at is None \
            or expires_at <= created_at:
        structural.append("MALFORMED_REQUEST")
    if structural:
        return deny_now(list(dict.fromkeys(structural)))
    # --- Phase B: semantic checks (deny reasons + human reasons) ---
    deny = []
    human = []

    def add(bucket, code):
        if code not in bucket:
            bucket.append(code)

    # Identity.
    if ident.kind not in IDENTITY_KINDS:
        add(deny, "IDENTITY_UNKNOWN_KIND")
    if not ident.authenticated:
        add(deny, "IDENTITY_UNAUTHENTICATED")

    # Per-step checks; effective risk = highest matching tier.
    effective_rank = 0
    saw_live_mutation = False
    for step in steps:
        verb = step["action_verb"]
        target = step["target"]
        ttype, tname = target["type"], target["name"]
        if verb in PROHIBITED_VERBS or ttype in PROHIBITED_TARGET_TYPES \
                or "shell" in verb:
            add(deny, "PROHIBITED_ACTION")
            continue
        if verb not in ACTION_VERB_TIERS:
            add(deny, "UNKNOWN_ACTION_VERB")
            continue
        if ttype not in RESOURCE_TYPES:
            add(deny, "UNKNOWN_RESOURCE_TYPE")
            continue
        info = ctx.resources.get(tname)
        if info is None:
            add(deny, "UNKNOWN_RESOURCE")
            continue
        if info.scope not in RESOURCE_SCOPES:
            add(deny, "UNKNOWN_RESOURCE")
            continue
        if verb in GUEST_VERBS and info.scope != "lab-guest":
            add(deny, "SCOPE_MISMATCH")
        if verb in LIVE_VERBS and info.scope != "live-host":
            add(deny, "SCOPE_MISMATCH")
        tier = _step_tier(verb, info)
        effective_rank = max(effective_rank, _RISK_RANK[tier])
        if verb in LIVE_VERBS:
            saw_live_mutation = True
            if tier == "L3" and tname not in ctx.allowlist:
                add(deny, "RESOURCE_NOT_ALLOWLISTED")
    effective = RISK_LEVELS[effective_rank]
    governing = RISK_LEVELS[max(_RISK_RANK[declared], effective_rank)]
    required_consent = TIER_CONSENT_FLOOR[governing]

    if _RISK_RANK[declared] < effective_rank:
        add(deny, "RISK_UNDERDECLARED")
    if governing == "L5":
        add(deny, "HUMAN_ONLY")

    # Consent: floor from the governing tier; human-granted only.
    granted = ctx.consent_mode_granted
    if granted == "never":
        add(deny, "CONSENT_BELOW_FLOOR")
    elif granted is not None and CONSENT_RANKS[granted] >= 1 \
            and ctx.consent_granted_by_kind != "human":
        add(deny, "CONSENT_NOT_HUMAN")
    if granted is not None and ctx.consent_granted_by_id is not None \
            and ctx.consent_granted_by_id == ident.principal_id \
            and ident.kind != "human":
        add(deny, "SELF_AUTHORIZATION")
    granted_rank = CONSENT_RANKS[granted] if granted in CONSENT_RANKS else -1
    if "CONSENT_NOT_HUMAN" not in deny and "SELF_AUTHORIZATION" not in deny:
        if granted_rank < CONSENT_RANKS[required_consent]:
            if governing != "L5":
                add(human, "CONSENT_BELOW_FLOOR")
    # Preconditions: observed true, or the plan does not proceed.
    for text in plan.get("preconditions") or []:
        observed = ctx.precondition_snapshot.get(text)
        if observed is False:
            add(deny, "PRECONDITION_FAILED")
        elif observed is not True:
            add(human, "PRECONDITION_UNVERIFIED")

    # Expiry and emergency stop.
    if evaluated_at >= expires_at:
        add(deny, "PLAN_EXPIRED")
    if ctx.emergency_stop_active and effective_rank >= 2:
        add(deny, "EMERGENCY_STOP_ACTIVE")

    # Undo path for live mutation.
    if saw_live_mutation:
        rollback = plan.get("rollback")
        method = rollback.get("method") if isinstance(rollback, Mapping) else None
        if not isinstance(method, str) or not method.strip():
            add(deny, "NO_UNDO_PATH")

    if deny:
        outcome, codes = DENY, deny + [c for c in human if c not in deny]
    elif human:
        outcome, codes = REQUIRE_HUMAN, human
    else:
        outcome, codes = ALLOW, ["ALL_CHECKS_PASSED"]
    return PolicyDecision(
        outcome=outcome, policy_version=POLICY_VERSION, plan_id=plan_id,
        declared_risk_level=declared, effective_risk_level=effective,
        required_consent_mode=required_consent, reason_codes=tuple(codes),
        evaluated_at=ctx.evaluated_at)


def evaluate_dict(data: Mapping[str, Any]) -> PolicyDecision:
    """Evaluate a plain-mapping request (see request_from_dict)."""
    return evaluate(request_from_dict(data))
