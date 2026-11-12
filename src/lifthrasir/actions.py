"""Typed action catalog and narrow executor interface (LIF-0401).

SPDX-License-Identifier: GPL-2.0-only

Home justification: ADR-0002 fixes the authority boundary as
policy engine -> resource-specific token -> minimal privileged
broker, and master roadmap section 3 places core implementation in
``src/``. The catalog and the executor contract are that boundary's
vocabulary, so they live in the core package beside the event bus
(LIF-0201) and the evidence store (LIF-0301) -- not in ``lab/``,
which holds rapid prototypes whose contracts have not stabilised.

What this slice is, and is not (evidence-status honesty):

- It DEFINES the typed action catalog v0.1: the closed vocabulary of
  verbs a plan step may name, each with a fixed risk tier and consent
  floor (docs/RISK-MATRIX.md, LIF-0003), a fixed set of target types,
  and a closed argument specification. This closes the gap LIF-0004
  recorded honestly: in schema v0.1 a plan step's ``action_verb`` is
  a free string because the catalog did not exist yet.
- It DEFINES the narrow executor interface: an ``Executor`` protocol
  whose only entry point takes a validated ``ActionRequest`` plus an
  ``Authorization`` token shape and returns an ``ActionResult``.
  There is no shell, no argv, no free-form command anywhere in the
  interface: an action that cannot be expressed as catalog verb +
  typed target + closed args cannot be expressed at all.
- It ships exactly ONE executor implementation: ``DryRunExecutor``,
  which validates and records intent and executes NOTHING. Policy
  decisions are LIF-0402, a separate limited-permission process is
  LIF-0403, signed plan references are LIF-0404. No privileged or
  live execution exists in this slice, and none is claimed.

Safety invariants bound here (master roadmap section 0):

- No verb in the catalog mutates bootloader, kernel image, firmware,
  partition table, encryption, home files, package trust roots, SSH
  access, or critical firewall/network state. Tier L5 has NO
  executable verbs at all: it is human-only, so the catalog simply
  contains nothing at L5, and validation treats any L5 claim as a
  refusal. Consent mode ``never`` likewise names no verb.
- Unknown verbs are DENIED, never coerced (research/25: unknown
  action verbs must always be rejected). Wildcard targets, shell
  metacharacters, traversal paths and critical resources are refused
  by name with a reason code.
- Every request is time-bounded (``expires_at`` plus a per-verb
  maximum duration) and resource-scoped (exactly one typed target).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional, Protocol, Tuple

CATALOG_VERSION = "0.1"
CATALOG_SCHEMA = "lifthrasir.action-catalog.v0.1"

# Consent strictness order, verbatim from docs/RISK-MATRIX.md.
CONSENT_ORDER = (
    "none", "standing-opt-in", "session-blanket", "allowlist-notice",
    "per-action", "human-only", "never",
)
_CONSENT_RANK = {name: i for i, name in enumerate(CONSENT_ORDER)}

# Minimum consent per risk tier, verbatim from docs/RISK-MATRIX.md.
CONSENT_FLOOR = {
    "L0": "none", "L1": "standing-opt-in", "L2": "session-blanket",
    "L3": "allowlist-notice", "L4": "per-action", "L5": "human-only",
}
RISK_LEVELS = tuple(CONSENT_FLOOR.keys())

SCOPES = ("live-readonly", "lab-guest", "live-host")
TARGET_TYPES = (
    "systemd-unit", "config-file", "package", "host", "lab-guest",
    "evidence-store", "firewall-rule",
)

# Resources an agent action may never target, at any tier, in any
# scope (master roadmap section 0 invariant 2, risk matrix P-01..P-10).
CRITICAL_UNITS = frozenset({
    "sshd.service", "ssh.service", "systemd-journald.service",
    "systemd-logind.service", "dbus.service", "NetworkManager.service",
    "systemd-udevd.service", "getty@tty1.service",
})
PROTECTED_PATH_PREFIXES = (
    "/boot", "/efi", "/etc/shadow", "/etc/gshadow", "/etc/ssh",
    "/root", "/home", "/usr/lib/firmware", "/etc/pki", "/etc/ssl",
    "/var/lib/lifthrasir/trust",
)
PROTECTED_PACKAGES = frozenset({
    "linux-image", "kernel", "grub", "grub2", "shim", "firmware-linux",
    "openssl", "gnupg", "openssh-server",
})
# Verb spellings that name prohibited classes; refused even before the
# unknown-verb check so the refusal reason is precise (defence in depth:
# these verbs are also simply absent from the catalog).
PROHIBITED_VERB_PARTS = (
    "shell", "exec", "bootloader", "kernel", "firmware", "partition",
    "encrypt", "trust_root", "ssh", "dco", "sign_off", "format_disk",
    "mkfs", "dd_", "raw_write",
)

_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.@-]*$")
_UNIT_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.@-]*\.(service|timer|socket|mount)$")
_PATH_RE = re.compile(r"^/[A-Za-z0-9_./@+~-]+$")
_SHELL_META = (";", "|", "&", "$", "`", "<", ">", "\n", "\r", "\\")


class ActionError(Exception):
    """Base class for all named catalog/executor refusals."""


class UnknownVerbError(ActionError):
    """Raised when a verb is not in the catalog (deny by default)."""


class ProhibitedActionError(ActionError):
    """Raised for prohibited classes: L5, never, critical resources."""


class MalformedRequestError(ActionError):
    """Raised when a request field is missing, mistyped or unsafe."""


class ConsentError(ActionError):
    """Raised when declared consent is below the verb's floor."""


class ExpiredRequestError(ActionError):
    """Raised when a request or authorization is past its expiry."""


@dataclass(frozen=True)
class ArgSpec:
    """One closed argument: name, kind, required flag."""
    name: str
    kind: str  # "name" | "unit" | "path" | "string" | "integer" | "boolean"
    required: bool = True


@dataclass(frozen=True)
class ActionSpec:
    """One catalog entry: the complete contract for one verb."""
    verb: str
    title: str
    risk_level: str
    scope: str
    target_types: Tuple[str, ...]
    args: Tuple[ArgSpec, ...]
    reversible: bool
    undo_method: str
    max_duration_seconds: int
    description: str

    @property
    def consent_floor(self) -> str:
        return CONSENT_FLOOR[self.risk_level]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "verb": self.verb, "title": self.title,
            "risk_level": self.risk_level,
            "consent_floor": self.consent_floor, "scope": self.scope,
            "target_types": list(self.target_types),
            "args": [{"name": a.name, "kind": a.kind,
                      "required": a.required} for a in self.args],
            "reversible": self.reversible, "undo_method": self.undo_method,
            "max_duration_seconds": self.max_duration_seconds,
            "description": self.description,
        }


def _spec(verb, title, risk, scope, targets, args, reversible, undo,
          max_seconds, description):
    return ActionSpec(verb=verb, title=title, risk_level=risk, scope=scope,
                      target_types=tuple(targets),
                      args=tuple(ArgSpec(*a) if len(a) == 3 else
                                 ArgSpec(a[0], a[1]) for a in args),
                      reversible=reversible, undo_method=undo,
                      max_duration_seconds=max_seconds,
                      description=description)


# The catalog v0.1. Deliberately narrow: 16 verbs. Adding a verb is a
# catalog version change with its own review, never a runtime option.
_CATALOG_LIST = [
    _spec("read_service_status", "Read the status of one service",
          "L0", "live-readonly", ("systemd-unit",), (), True, "none", 10,
          "Observe whether one systemd unit is active or failed. No mutation."),
    _spec("read_system_counters", "Read public system counters",
          "L0", "live-readonly", ("host",), (), True, "none", 10,
          "Read public CPU, memory and pressure counters for a health report."),
    _spec("check_package_integrity", "Check package file integrity",
          "L0", "live-readonly", ("package",), (), True, "none", 60,
          "Compare installed package files against the package database, read-only."),
    _spec("read_journal", "Read journal entries for one unit",
          "L1", "live-readonly", ("systemd-unit",),
          (("max_entries", "integer", False),), True, "none", 15,
          "Read consented journal detail for one unit to build a timeline."),
    _spec("read_evidence_store", "Read the local evidence store",
          "L1", "live-readonly", ("evidence-store",),
          (("incident_id", "name", False),), True, "none", 15,
          "Read local incident evidence and sensor history; data stays local."),
    _spec("create_lab_guest", "Create a disposable lab guest",
          "L2", "lab-guest", ("lab-guest",),
          (("image_recipe", "name"),), True, "delete_lab_guest", 600,
          "Create a disposable QEMU/KVM guest from a pinned lab image recipe."),
    _spec("delete_lab_guest", "Delete a disposable lab guest",
          "L2", "lab-guest", ("lab-guest",), (), True, "none", 120,
          "Delete a disposable lab guest and everything inside it. Lab only."),
    _spec("reset_lab_guest", "Reset a disposable lab guest",
          "L2", "lab-guest", ("lab-guest",), (), True, "none", 300,
          "Reset a disposable lab guest to its pinned clean state."),
    _spec("edit_config_in_guest", "Edit a config file inside a lab guest",
          "L2", "lab-guest", ("config-file",),
          (("guest", "name"), ("setting", "name"), ("value", "string", False)),
          True, "reset_lab_guest", 60,
          "Change one named setting in one config file inside a disposable guest."),
    _spec("restart_unit_in_guest", "Restart a unit inside a lab guest",
          "L2", "lab-guest", ("systemd-unit",), (("guest", "name"),),
          True, "none", 60,
          "Restart one unit inside a disposable lab guest. No live-host effect."),
    _spec("restart_unit", "Restart an allowlisted noncritical service",
          "L3", "live-host", ("systemd-unit",), (), True, "stop_unit", 60,
          "Restart one explicitly allowlisted noncritical service under monitoring, with a tested undo. Critical units are refused by the validator."),
    _spec("revert_user_config", "Revert a user-level config file",
          "L3", "live-host", ("config-file",),
          (("prior_version_digest", "string"),), True, "revert_user_config", 60,
          "Revert one proven user-level config file to its recorded prior version. Protected paths are refused by the validator."),
    _spec("stop_unit", "Stop an allowlisted noncritical service",
          "L3", "live-host", ("systemd-unit",), (), True, "restart_unit", 60,
          "Stop one explicitly allowlisted noncritical service under monitoring. This is the tested undo for restart_unit; critical units are refused by the validator."),
    _spec("remove_package", "Remove one installed package version",
          "L4", "live-host", ("package",), (("version", "string"),),
          True, "install_package", 900,
          "Remove one exact package version after per-action approval. This is the rollback for install_package; trust-root and boot packages are refused."),
    _spec("install_package", "Install one staged package version",
          "L4", "live-host", ("package",), (("version", "string"),),
          True, "remove_package", 900,
          "Install one exact staged package version after per-action approval, with rollback staged first. Trust-root and boot packages are refused."),
    _spec("change_firewall_rule", "Change one non-critical firewall rule",
          "L4", "live-host", ("firewall-rule",),
          (("rule_id", "name"),), True, "change_firewall_rule", 120,
          "Change one named non-critical firewall rule after per-action approval, with the prior ruleset backed up. Critical network state is out of scope and refused."),
]
CATALOG: Dict[str, ActionSpec] = {s.verb: s for s in _CATALOG_LIST}


def catalog_as_dict() -> Dict[str, Any]:
    """The catalog as a JSON-ready mapping (the .json file's content)."""
    return {
        "schema": CATALOG_SCHEMA, "catalog_version": CATALOG_VERSION,
        "actions": [CATALOG[v].to_dict() for v in sorted(CATALOG)],
    }


def get_action(verb: Any) -> ActionSpec:
    """Look up one verb; unknown or prohibited verbs are refused."""
    if not isinstance(verb, str) or not verb:
        raise UnknownVerbError(f"verb must be a non-empty string, got {verb!r}")
    for part in PROHIBITED_VERB_PARTS:
        if part in verb:
            raise ProhibitedActionError(
                f"verb {verb!r} names a prohibited action class: agents "
                "never perform it at any consent level (risk matrix never)")
    try:
        return CATALOG[verb]
    except KeyError:
        raise UnknownVerbError(
            f"unknown action verb {verb!r}: the catalog is a closed "
            "vocabulary and unknown verbs are always rejected") from None


@dataclass(frozen=True)
class ActionTarget:
    """Exactly one typed, named resource (plan v0.1 target shape)."""
    type: str
    name: str


@dataclass(frozen=True)
class Authorization:
    """Token shape the executor consumes (issuance is LIF-0402/0404).

    This slice defines the shape only: plan binding by id and digest,
    a one-time nonce, the granted consent mode, and an expiry. The
    executor checks shape, binding and expiry; whether the policy
    engine SHOULD have granted it is LIF-0402's question.
    """
    plan_id: str
    plan_digest: str
    nonce: str
    consent_mode: str
    expires_at: float  # epoch seconds; injectable clock in tests


@dataclass(frozen=True)
class ActionRequest:
    """One validated request to execute one catalog action."""
    verb: str
    target: ActionTarget
    args: Mapping[str, Any] = field(default_factory=dict)
    plan_id: str = ""
    expires_at: float = 0.0


@dataclass(frozen=True)
class ActionResult:
    """Outcome of an executor call. ``executed`` is False for dry-run."""
    verb: str
    status: str  # "dry-run" in this slice; live statuses are LIF-0403+
    executed: bool
    detail: str


def _check_no_shell(value: Any, where: str) -> None:
    if isinstance(value, str):
        for token in _SHELL_META:
            if token in value:
                raise MalformedRequestError(
                    f"{where} contains a shell metacharacter {token!r}: "
                    "actions are typed values, never shell strings")
        if "*" in value or "?" in value:
            raise MalformedRequestError(
                f"{where} contains a wildcard: targets and arguments "
                "must name exactly one resource")


def _check_arg_value(spec: ArgSpec, value: Any) -> None:
    _check_no_shell(value, f"arg {spec.name!r}")
    if spec.kind == "integer":
        if not isinstance(value, int) or isinstance(value, bool) or value < 0:
            raise MalformedRequestError(
                f"arg {spec.name!r} must be a non-negative integer")
    elif spec.kind == "boolean":
        if not isinstance(value, bool):
            raise MalformedRequestError(f"arg {spec.name!r} must be a boolean")
    elif spec.kind == "unit":
        if not isinstance(value, str) or not _UNIT_RE.match(value):
            raise MalformedRequestError(
                f"arg {spec.name!r} must be a unit name like 'demo.service'")
    elif spec.kind == "path":
        if not isinstance(value, str) or not _PATH_RE.match(value) or ".." in value:
            raise MalformedRequestError(
                f"arg {spec.name!r} must be an absolute path without traversal")
    elif spec.kind == "name":
        if not isinstance(value, str) or not _NAME_RE.match(value):
            raise MalformedRequestError(
                f"arg {spec.name!r} must be a plain identifier, got {value!r}")
    elif spec.kind == "string":
        if not isinstance(value, str) or not value or len(value) > 512:
            raise MalformedRequestError(
                f"arg {spec.name!r} must be a non-empty string of at most 512 chars")
    else:  # pragma: no cover - catalog construction error
        raise AssertionError(f"unknown arg kind {spec.kind!r}")


def _check_target(spec: ActionSpec, target: ActionTarget) -> None:
    if target.type not in TARGET_TYPES:
        raise MalformedRequestError(f"unknown target type {target.type!r}")
    if target.type not in spec.target_types:
        raise MalformedRequestError(
            f"verb {spec.verb!r} does not act on target type "
            f"{target.type!r}; allowed: {list(spec.target_types)}")
    _check_no_shell(target.name, "target name")
    if target.type == "systemd-unit":
        if not _UNIT_RE.match(target.name):
            raise MalformedRequestError(
                f"target name {target.name!r} is not a systemd unit name")
        if spec.scope == "live-host" and target.name in CRITICAL_UNITS:
            raise ProhibitedActionError(
                f"unit {target.name!r} is critical infrastructure: "
                "live agent action on it is prohibited")
    elif target.type == "config-file":
        if not _PATH_RE.match(target.name) or ".." in target.name:
            raise MalformedRequestError(
                f"config target {target.name!r} must be an absolute path without traversal")
        if spec.scope == "live-host":
            for prefix in PROTECTED_PATH_PREFIXES:
                if target.name == prefix or target.name.startswith(prefix + "/"):
                    raise ProhibitedActionError(
                        f"path {target.name!r} is under protected prefix "
                        f"{prefix!r}: agent mutation there is prohibited")
    elif target.type == "package":
        if not _NAME_RE.match(target.name):
            raise MalformedRequestError(
                f"package name {target.name!r} is not a plain package name")
        if spec.scope == "live-host" and target.name in PROTECTED_PACKAGES:
            raise ProhibitedActionError(
                f"package {target.name!r} is a boot/trust package: "
                "agent installation of it is prohibited")
    elif target.type in ("host", "lab-guest", "evidence-store", "firewall-rule"):
        if not _NAME_RE.match(target.name):
            raise MalformedRequestError(
                f"target name {target.name!r} must be a plain identifier")


def validate_request(request: ActionRequest, now: float) -> ActionSpec:
    """Validate one request end to end; return its spec or refuse.

    Checks, in order: verb known and not prohibited; target typed,
    in-scope and not critical/protected; args exactly the closed set
    the spec declares (unknown args refused, missing required args
    refused, every value kind-checked and shell-free); request not
    expired. Consent is checked separately against an Authorization
    in ``validate_authorization`` because consent lives on the token.
    """
    spec = get_action(request.verb)
    if spec.risk_level == "L5":  # pragma: no cover - catalog has no L5
        raise ProhibitedActionError("L5 actions are human-only")
    _check_target(spec, request.target)
    declared = {a.name: a for a in spec.args}
    for key in request.args:
        if key not in declared:
            raise MalformedRequestError(
                f"verb {spec.verb!r} has no argument {key!r}: the "
                "argument set is closed and unknown arguments are refused")
        if key in ("command", "shell", "argv", "cmd"):
            raise MalformedRequestError("shell arguments do not exist here")
    for arg in spec.args:
        if arg.required and arg.name not in request.args:
            raise MalformedRequestError(
                f"verb {spec.verb!r} requires argument {arg.name!r}")
        if arg.name in request.args:
            _check_arg_value(arg, request.args[arg.name])
    if request.expires_at and now > request.expires_at:
        raise ExpiredRequestError("action request is past its expires_at")
    return spec


def validate_authorization(spec: ActionSpec, request: ActionRequest,
                             auth: Authorization, now: float) -> None:
    """Check an authorization token's shape, binding, consent, expiry."""
    if auth.consent_mode not in _CONSENT_RANK:
        raise ConsentError(f"unknown consent mode {auth.consent_mode!r}")
    if auth.consent_mode == "never":
        raise ProhibitedActionError("consent mode 'never' authorizes nothing")
    if _CONSENT_RANK[auth.consent_mode] < _CONSENT_RANK[spec.consent_floor]:
        raise ConsentError(
            f"verb {spec.verb!r} is {spec.risk_level} and needs consent "
            f"at or above {spec.consent_floor!r}; token grants "
            f"{auth.consent_mode!r}")
    if not auth.plan_id or auth.plan_id != request.plan_id:
        raise MalformedRequestError(
            "authorization is not bound to this request's plan_id")
    if not auth.plan_digest.startswith("sha256:") or len(auth.plan_digest) != 71:
        raise MalformedRequestError(
            "plan_digest must be 'sha256:' plus 64 hex characters")
    if not auth.nonce:
        raise MalformedRequestError("authorization nonce must be non-empty")
    if now > auth.expires_at:
        raise ExpiredRequestError("authorization token is expired")


def validate_plan_steps(plan: Mapping[str, Any]) -> List[str]:
    """Validate a v0.1 plan record's steps against the catalog.

    Returns a list of human-readable problems (empty = valid). This is
    the bridge LIF-0004 promised: the v0.1 plan schema checks step
    shape; this function checks that every ``action_verb`` exists,
    every target type fits the verb, and every step's args are within
    the verb's closed argument set.
    """
    problems: List[str] = []
    steps = plan.get("steps") if isinstance(plan, Mapping) else None
    if not isinstance(steps, list) or not steps:
        return ["plan has no steps list"]
    for step in steps:
        if not isinstance(step, Mapping):
            problems.append(f"step {step!r} is not an object")
            continue
        label = step.get("step_id", "?")
        try:
            spec = get_action(step.get("action_verb"))
        except ActionError as exc:
            problems.append(f"step {label}: {exc}")
            continue
        target = step.get("target") or {}
        try:
            _check_target(spec, ActionTarget(type=str(target.get("type", "")),
                                             name=str(target.get("name", ""))))
            declared = {a.name for a in spec.args}
            for key in (step.get("args") or {}):
                if key not in declared:
                    problems.append(
                        f"step {label}: verb {spec.verb!r} has no argument {key!r}")
            for arg in spec.args:
                if arg.required and arg.name not in (step.get("args") or {}):
                    problems.append(
                        f"step {label}: verb {spec.verb!r} requires argument {arg.name!r}")
        except ActionError as exc:
            problems.append(f"step {label}: {exc}")
    return problems


class Executor(Protocol):
    """The narrow executor interface: one method, typed in, typed out.

    Implementations receive only an already-shaped ``ActionRequest``
    and an ``Authorization``. There is deliberately no method that
    accepts a command string, a path list, or a plan document: the
    broker of LIF-0403 implements this protocol in a separate
    limited-permission process; this slice defines the contract and
    ships only the dry-run implementation below.
    """

    def execute(self, request: ActionRequest, authorization: Authorization,
                now: float) -> ActionResult:
        ...


class DryRunExecutor:
    """Validates fully, executes nothing, records intent in memory.

    The only executor in this slice. ``executed`` is always False and
    no host, guest or store state is touched: the intent log lives in
    this object's list and dies with the process.
    """

    def __init__(self) -> None:
        self.intents: List[ActionRequest] = []

    def execute(self, request: ActionRequest, authorization: Authorization,
                now: float) -> ActionResult:
        spec = validate_request(request, now)
        validate_authorization(spec, request, authorization, now)
        self.intents.append(request)
        return ActionResult(
            verb=spec.verb, status="dry-run", executed=False,
            detail=(f"validated {spec.verb} on "
                    f"{request.target.type}:{request.target.name} "
                    f"({spec.risk_level}, scope {spec.scope}); "
                    "nothing was executed"))
