"""Health-repair recipe abstraction: exact targets and effects (LIF-0501).

SPDX-License-Identifier: GPL-2.0-only

Home justification: Eir is the repair domain of the core package
(master roadmap section 0 reference architecture; research/07).
Recipes are Eir's vocabulary, beside the action catalog (LIF-0401),
the policy engine (LIF-0402) and the approval contracts (LIF-0404)
whose contracts they bind together -- core implementation in
``src/`` per master roadmap section 3, not ``lab/`` prototypes.

What this slice is, and is not (evidence-status honesty):

- A recipe is DECLARATIVE DATA: a named, versioned template that
  names the exact catalog verbs it uses, the exact typed target of
  every step (a literal, or one whole-value ``$parameter`` bound at
  instantiation), the exact observable effect every step must
  produce, the preconditions that must be observed true, the
  conditions under which the recipe must ABSTAIN, a rollback method
  and a verification method. Validation is pure: it reads data and
  returns data. Nothing in this module executes a repair, touches
  host state, opens a file or a network connection, or mints an authorization.
  Demonstration of one live recovery is LIF-0502; configuration
  diff preview is LIF-0503; soak is LIF-0504.
- Exactness is enforced, never assumed. Every verb must exist in
  the LIF-0401 catalog; every step's undo verb must equal the
  catalog's own ``undo_method`` for that verb; the recipe's risk
  level must EQUAL the maximum step risk (an underdeclared risk is
  refused, as in LIF-0402) and its consent mode must sit at or
  above the risk-matrix floor for that risk; every step declares at
  least one effect whose target is EXACTLY the step's target;
  wildcards, shell text, embedded placeholders and undeclared or
  unused parameters are all refused by name.
- Instantiation binds parameters to exact values and emits a v0.1
  plan record (LIF-0004 shape) that must pass the banked checks:
  ``actions.validate_plan_steps``, ``approval.check_plan_shape``
  and a per-step ``actions.validate_request`` (which refuses
  critical units, protected paths and trust-root packages bound
  through parameters, exactly as it refuses them literally).
- A recipe is a conditional pattern, not a blanket permission
  (research/07 repair knowledge): ``check_applicability`` returns
  ABSTAIN unless every precondition is observed true and no
  abstain condition is observed. Unobserved is unverified, and
  unverified abstains (master roadmap section 0 invariant 4).
"""
from __future__ import annotations

import copy
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Mapping, Optional, Tuple

from .actions import (
    CONSENT_FLOOR,
    ActionRequest,
    ActionTarget,
    get_action,
    validate_plan_steps,
    validate_request,
)
from .approval import ApprovalError, check_plan_shape

RECIPE_SCHEMA = "lifthrasir.recipe.v0.1"
RECIPE_VERSION = "0.1"

_RISK_ORDER = ("L0", "L1", "L2", "L3", "L4", "L5")
_RISK_RANK = {name: i for i, name in enumerate(_RISK_ORDER)}
_CONSENT_ORDER = (
    "none", "standing-opt-in", "session-blanket", "allowlist-notice",
    "per-action", "human-only", "never",
)
_CONSENT_RANK = {name: i for i, name in enumerate(_CONSENT_ORDER)}
PARAM_KINDS = ("name", "unit", "path", "string", "integer", "boolean")

_RECIPE_ID_RE = re.compile(r"^rec-[a-z0-9][a-z0-9-]*$")
_PARAM_NAME_RE = re.compile(r"^[a-z][a-z0-9_]*$")
_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.@-]*$")
_CONDITION_ID_RE = re.compile(r"^[a-z][a-z0-9-]*$")
_PLAN_ID_RE = re.compile(r"^plan-[a-z0-9][a-z0-9-]*$")
_INCIDENT_ID_RE = re.compile(r"^inc-[a-z0-9][a-z0-9-]*$")
_HYPOTHESIS_ID_RE = re.compile(r"^hyp-[a-z0-9][a-z0-9-]*$")
_PLACEHOLDER_RE = re.compile(r"^\$([a-z][a-z0-9_]*)$")
_TOKEN_RE = re.compile(r"\$([A-Za-z][A-Za-z0-9_]*)")
_SHELL_META = (";", "|", "&", "`", "<", ">", "\n", "\r", "\\")

# Sample binding per parameter kind / target type, used ONLY to run
# the banked catalog validator over a recipe at definition time:
# placeholders are replaced by inert samples so literal targets,
# argument kinds and closed argument sets are checked by the same
# code that checks real requests; samples never leave this module.
_KIND_SAMPLES = {
    "name": "demo-name", "unit": "demo.service",
    "path": "/etc/demo/demo.conf", "string": "demo-value",
    "integer": 1, "boolean": True,
}
_TARGET_SAMPLES = {
    "systemd-unit": "demo.service", "config-file": "/etc/demo/demo.conf",
    "package": "demo-pkg", "host": "demo-host",
    "lab-guest": "lab-guest-01", "evidence-store": "evidence-store",
    "firewall-rule": "rule-1",
}
# Parameter kind a whole-value target placeholder must declare.
_TARGET_PARAM_KIND = {
    "systemd-unit": "unit", "config-file": "path", "package": "name",
    "host": "name", "lab-guest": "name", "evidence-store": "name",
    "firewall-rule": "name",
}

_RECIPE_KEYS = frozenset({
    "schema", "schema_version", "recipe_id", "title", "health_issue",
    "parameters", "preconditions", "abstain_when", "steps",
    "risk_level", "consent_mode", "rollback", "verification",
    "expected_outcome",
})
_PARAM_KEYS = frozenset({"name", "kind", "required", "description"})
_STEP_KEYS = frozenset({
    "step_id", "action_verb", "target", "args", "effects", "undo_verb",
})
_TARGET_KEYS = frozenset({"type", "name"})
_EFFECT_KEYS = frozenset({"target", "observable", "expected"})
_ABSTAIN_KEYS = frozenset({"condition_id", "description"})
_ROLLBACK_KEYS = frozenset({"method", "description"})
_VERIFICATION_KEYS = frozenset({"method", "timeout_seconds"})


class RecipeError(Exception):
    """Base class for all named recipe refusals."""


class MalformedRecipeError(RecipeError):
    """The recipe data is missing, mistyped, open or unsafe."""


class UnknownRecipeError(RecipeError):
    """The named recipe is not in the built-in catalog."""


class RiskMismatchError(RecipeError):
    """Declared risk differs from the derived maximum step risk."""


class RecipeConsentError(RecipeError):
    """Declared consent is unknown, prohibited or below the floor."""


class EffectError(RecipeError):
    """A step's declared effects are missing or not exact."""


class UndoMismatchError(RecipeError):
    """A step undo or the rollback method disagrees with the catalog."""


class ParameterError(RecipeError):
    """A parameter is undeclared, unused, or a placeholder is embedded."""


class BindingError(RecipeError):
    """Instantiation bindings are missing, mistyped or unsafe."""


@dataclass(frozen=True)
class RecipeParameter:
    name: str
    kind: str
    required: bool
    description: str


@dataclass(frozen=True)
class Effect:
    target_type: str
    target_name: str
    observable: str
    expected: Any


@dataclass(frozen=True)
class RecipeStep:
    step_id: str
    verb: str
    target_type: str
    target_name: str
    args: Tuple[Tuple[str, Any], ...]
    effects: Tuple[Effect, ...]
    undo_verb: str

    def args_dict(self) -> Dict[str, Any]:
        return dict(self.args)


@dataclass(frozen=True)
class AbstainCondition:
    condition_id: str
    description: str


@dataclass(frozen=True)
class Recipe:
    recipe_id: str
    title: str
    health_issue: str
    parameters: Tuple[RecipeParameter, ...]
    preconditions: Tuple[str, ...]
    abstain_when: Tuple[AbstainCondition, ...]
    steps: Tuple[RecipeStep, ...]
    risk_level: str
    consent_mode: str
    rollback_method: str
    rollback_description: str
    verification_method: str
    verification_timeout_seconds: int
    expected_outcome: str

    @property
    def consent_floor(self) -> str:
        return CONSENT_FLOOR[self.risk_level]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "schema": RECIPE_SCHEMA, "schema_version": RECIPE_VERSION,
            "recipe_id": self.recipe_id, "title": self.title,
            "health_issue": self.health_issue,
            "parameters": [
                {"name": p.name, "kind": p.kind, "required": p.required,
                 "description": p.description} for p in self.parameters],
            "preconditions": list(self.preconditions),
            "abstain_when": [
                {"condition_id": c.condition_id,
                 "description": c.description} for c in self.abstain_when],
            "steps": [{
                "step_id": s.step_id, "action_verb": s.verb,
                "target": {"type": s.target_type, "name": s.target_name},
                "args": s.args_dict(),
                "effects": [{
                    "target": {"type": e.target_type,
                               "name": e.target_name},
                    "observable": e.observable, "expected": e.expected,
                } for e in s.effects],
                "undo_verb": s.undo_verb,
            } for s in self.steps],
            "risk_level": self.risk_level,
            "consent_mode": self.consent_mode,
            "rollback": {"method": self.rollback_method,
                         "description": self.rollback_description},
            "verification": {
                "method": self.verification_method,
                "timeout_seconds": self.verification_timeout_seconds},
            "expected_outcome": self.expected_outcome,
        }


@dataclass(frozen=True)
class ApplicabilityDecision:
    recipe_id: str
    outcome: str  # "applicable" | "abstain"
    reason_codes: Tuple[str, ...]


def _fail(message: str) -> None:
    raise MalformedRecipeError(message)


def _text(value: Any, where: str) -> str:
    if not isinstance(value, str) or not value or len(value) > 512:
        _fail(f"{where} must be a non-empty string of at most 512 chars")
    return value


def _check_closed(obj: Any, keys: frozenset, where: str) -> Mapping:
    if not isinstance(obj, Mapping):
        _fail(f"{where} must be an object")
    extra = set(obj) - set(keys)
    missing = set(keys) - set(obj)
    if extra:
        _fail(f"{where} has unknown keys {sorted(extra)}: "
              "the recipe shape is closed")
    if missing:
        _fail(f"{where} is missing keys {sorted(missing)}")
    return obj


def _placeholder(value: Any) -> Optional[str]:
    """Param name if value is exactly one whole-value placeholder."""
    if isinstance(value, str):
        match = _PLACEHOLDER_RE.match(value)
        if match:
            return match.group(1)
        if "$" in value:
            raise ParameterError(
                f"value {value!r} embeds a placeholder inside other "
                "text: targets, arguments and effects bind whole "
                "values only, so the bound value stays exact")
    return None


def _tokens(text: str) -> List[str]:
    return _TOKEN_RE.findall(text)


def validate_recipe(data: Any) -> Recipe:
    """Validate one recipe record end to end; return it parsed.

    Refusals are named RecipeError subclasses. Checks, in order:
    closed shape and pins; parameter table; per-step catalog truth
    (verb exists, target fits, closed args, catalog undo, exact
    effects) proven by running the banked catalog validator over a
    sample-bound request; derived risk and consent floor; rollback
    equals the catalog undo chain; parameter usage is exact.
    """
    _check_closed(data, _RECIPE_KEYS, "recipe")
    if data["schema"] != RECIPE_SCHEMA:
        _fail(f"schema must be {RECIPE_SCHEMA!r}")
    if data["schema_version"] != RECIPE_VERSION:
        _fail(f"schema_version must be {RECIPE_VERSION!r}")
    recipe_id = data["recipe_id"]
    if not isinstance(recipe_id, str) or not _RECIPE_ID_RE.match(recipe_id):
        _fail(f"recipe_id {recipe_id!r} is malformed (want rec-...)")
    title = _text(data["title"], "title")
    health_issue = _text(data["health_issue"], "health_issue")
    expected_outcome = _text(data["expected_outcome"], "expected_outcome")

    raw_params = data["parameters"]
    if not isinstance(raw_params, list):
        _fail("parameters must be a list")
    params: Dict[str, RecipeParameter] = {}
    for raw in raw_params:
        _check_closed(raw, _PARAM_KEYS, "parameter")
        name = raw["name"]
        if not isinstance(name, str) or not _PARAM_NAME_RE.match(name):
            raise ParameterError(f"parameter name {name!r} is malformed")
        if name in params:
            raise ParameterError(f"parameter {name!r} is declared twice")
        if raw["kind"] not in PARAM_KINDS:
            raise ParameterError(
                f"parameter {name!r} kind {raw['kind']!r} is not one "
                f"of {list(PARAM_KINDS)}")
        if not isinstance(raw["required"], bool):
            raise ParameterError(
                f"parameter {name!r} required must be a boolean")
        params[name] = RecipeParameter(
            name=name, kind=raw["kind"], required=raw["required"],
            description=_text(raw["description"],
                              f"parameter {name!r} description"))
    used: set = set()

    def note_placeholder(value: Any, param_kind: str, where: str) -> None:
        pname = _placeholder(value)
        if pname is None:
            return
        if pname not in params:
            raise ParameterError(
                f"{where} references undeclared parameter ${pname}")
        if params[pname].kind != param_kind:
            raise ParameterError(
                f"{where} binds ${pname} (kind "
                f"{params[pname].kind!r}) where kind {param_kind!r} "
                "is required")
        used.add(pname)

    preconditions = data["preconditions"]
    if not isinstance(preconditions, list) or not preconditions:
        _fail("a repair recipe names at least one precondition: "
              "repair without observed preconditions is guessing "
              "(research/07 plan lifecycle)")
    for text in preconditions:
        _text(text, "precondition")
        for token in _tokens(text):
            if token not in params:
                raise ParameterError(
                    f"precondition references undeclared parameter "
                    f"${token}")
            used.add(token)

    raw_abstain = data["abstain_when"]
    if not isinstance(raw_abstain, list) or not raw_abstain:
        _fail("a repair recipe names at least one abstain condition: "
              "abstention is graded as rigorously as repair (P5 exit)")
    abstain: List[AbstainCondition] = []
    seen_conditions: set = set()
    for raw in raw_abstain:
        _check_closed(raw, _ABSTAIN_KEYS, "abstain condition")
        cid = raw["condition_id"]
        if not isinstance(cid, str) or not _CONDITION_ID_RE.match(cid):
            _fail(f"abstain condition_id {cid!r} is malformed")
        if cid in seen_conditions:
            _fail(f"abstain condition {cid!r} is listed twice")
        seen_conditions.add(cid)
        abstain.append(AbstainCondition(
            condition_id=cid,
            description=_text(raw["description"],
                              "abstain condition description")))

    raw_steps = data["steps"]
    if not isinstance(raw_steps, list) or not raw_steps:
        _fail("steps must be a non-empty list")
    steps: List[RecipeStep] = []
    seen_steps: set = set()
    derived_rank = -1
    mutating = 0
    for raw in raw_steps:
        _check_closed(raw, _STEP_KEYS, "step")
        step_id = raw["step_id"]
        if not isinstance(step_id, str) or not step_id:
            _fail("step_id must be a non-empty string")
        if step_id in seen_steps:
            _fail(f"step_id {step_id!r} is used twice")
        seen_steps.add(step_id)
        try:
            spec = get_action(raw["action_verb"])
        except Exception as exc:  # catalog refusal, re-named here
            raise MalformedRecipeError(
                f"step {step_id}: {exc}") from exc
        _check_closed(raw["target"], _TARGET_KEYS, "step target")
        ttype, tname = raw["target"]["type"], raw["target"]["name"]
        if ttype not in spec.target_types:
            _fail(f"step {step_id}: verb {spec.verb!r} does not act "
                  f"on target type {ttype!r}")
        pname = _placeholder(tname)
        if pname is not None:
            note_placeholder(tname, _TARGET_PARAM_KIND[ttype],
                             f"step {step_id} target")
            sample_target = _TARGET_SAMPLES[ttype]
        else:
            _text(tname, f"step {step_id} target name")
            sample_target = tname
        if not isinstance(raw["args"], Mapping):
            _fail(f"step {step_id}: args must be an object")
        declared = {a.name: a for a in spec.args}
        sample_args: Dict[str, Any] = {}
        args_pairs: List[Tuple[str, Any]] = []
        for key, value in raw["args"].items():
            if key not in declared:
                _fail(f"step {step_id}: verb {spec.verb!r} has no "
                      f"argument {key!r}: the argument set is closed")
            arg_pname = _placeholder(value)
            if arg_pname is not None:
                note_placeholder(value, declared[key].kind,
                                 f"step {step_id} arg {key!r}")
                sample_args[key] = _KIND_SAMPLES[declared[key].kind]
            else:
                sample_args[key] = value
            args_pairs.append((key, value))
        for arg in spec.args:
            if arg.required and arg.name not in raw["args"]:
                _fail(f"step {step_id}: verb {spec.verb!r} requires "
                      f"argument {arg.name!r}")
        # Definition-time proof via the banked catalog validator.
        try:
            validate_request(ActionRequest(
                verb=spec.verb,
                target=ActionTarget(type=ttype, name=sample_target),
                args=sample_args), now=0.0)
        except Exception as exc:
            raise MalformedRecipeError(
                f"step {step_id}: {exc}") from exc
        if raw["undo_verb"] != spec.undo_method:
            raise UndoMismatchError(
                f"step {step_id}: undo_verb {raw['undo_verb']!r} "
                f"disagrees with the catalog undo "
                f"{spec.undo_method!r} for verb {spec.verb!r}")
        raw_effects = raw["effects"]
        if not isinstance(raw_effects, list) or not raw_effects:
            raise EffectError(
                f"step {step_id} declares no effect: every step "
                "names its exact observable effect (slice title)")
        effects: List[Effect] = []
        for raw_effect in raw_effects:
            _check_closed(raw_effect, _EFFECT_KEYS, "effect")
            _check_closed(raw_effect["target"], _TARGET_KEYS,
                          "effect target")
            etype = raw_effect["target"]["type"]
            ename = raw_effect["target"]["name"]
            if etype != ttype or ename != tname:
                raise EffectError(
                    f"step {step_id}: effect target "
                    f"{etype}:{ename} is not exactly the step target "
                    f"{ttype}:{tname}: effects are exact, never "
                    "approximate or side-effecting elsewhere")
            observable = raw_effect["observable"]
            if not isinstance(observable, str) or \
                    not _NAME_RE.match(observable):
                raise EffectError(
                    f"step {step_id}: observable {observable!r} must "
                    "be a plain identifier")
            expected = raw_effect["expected"]
            exp_pname = _placeholder(expected)
            if exp_pname is not None:
                if exp_pname not in params:
                    raise ParameterError(
                        f"step {step_id} effect references "
                        f"undeclared parameter ${exp_pname}")
                used.add(exp_pname)
            elif not isinstance(expected, str) or not expected:
                raise EffectError(
                    f"step {step_id}: effect expected must be a "
                    "non-empty string or one $parameter")
            effects.append(Effect(target_type=etype, target_name=ename,
                                  observable=observable,
                                  expected=expected))
        derived_rank = max(derived_rank, _RISK_RANK[spec.risk_level])
        if spec.scope in ("live-host", "lab-guest"):
            mutating += 1
        steps.append(RecipeStep(
            step_id=step_id, verb=spec.verb, target_type=ttype,
            target_name=tname, args=tuple(args_pairs),
            effects=tuple(effects), undo_verb=raw["undo_verb"]))
    if mutating == 0:
        _fail("an observation-only recipe is not a health-repair "
              "recipe: at least one step must act in the lab guest "
              "or on the live host")
    derived_risk = _RISK_ORDER[derived_rank]
    if data["risk_level"] != derived_risk:
        raise RiskMismatchError(
            f"declared risk_level {data['risk_level']!r} differs "
            f"from the derived maximum step risk {derived_risk!r}: "
            "risk is derived from the catalog, never understated")
    consent = data["consent_mode"]
    if consent not in _CONSENT_RANK:
        raise RecipeConsentError(f"consent_mode {consent!r} is unknown")
    if consent == "never":
        raise RecipeConsentError(
            "consent_mode 'never' names the prohibited class: no "
            "recipe may carry it (risk matrix P-01..P-10)")
    floor = CONSENT_FLOOR[derived_risk]
    if _CONSENT_RANK[consent] < _CONSENT_RANK[floor]:
        raise RecipeConsentError(
            f"consent_mode {consent!r} is below the floor {floor!r} "
            f"for risk {derived_risk} (docs/RISK-MATRIX.md)")

    _check_closed(data["rollback"], _ROLLBACK_KEYS, "rollback")
    rollback_method = data["rollback"]["method"]
    rollback_description = _text(data["rollback"]["description"],
                                 "rollback description")
    expected_rollback = None
    for step in reversed(steps):
        if step.undo_verb != "none":
            expected_rollback = step.undo_verb
            break
    if expected_rollback is None:
        raise UndoMismatchError(
            "no step carries a catalog undo: a repair recipe "
            "without a tested undo cannot be declared")
    if rollback_method != expected_rollback:
        raise UndoMismatchError(
            f"rollback method {rollback_method!r} is not the "
            f"catalog undo chain's head {expected_rollback!r}")

    _check_closed(data["verification"], _VERIFICATION_KEYS,
                  "verification")
    vmethod = data["verification"]["method"]
    if not isinstance(vmethod, str) or not _NAME_RE.match(vmethod):
        _fail(f"verification method {vmethod!r} must be a plain "
              "identifier")
    timeout = data["verification"]["timeout_seconds"]
    if not isinstance(timeout, int) or isinstance(timeout, bool) \
            or not 1 <= timeout <= 3600:
        _fail("verification timeout_seconds must be an integer "
              "in 1..3600")

    unused = set(params) - used
    if unused:
        raise ParameterError(
            f"parameters {sorted(unused)} are declared but never "
            "used: a recipe binds exactly what it declares")
    return Recipe(
        recipe_id=recipe_id, title=title, health_issue=health_issue,
        parameters=tuple(params[name] for name in params),
        preconditions=tuple(preconditions), abstain_when=tuple(abstain),
        steps=tuple(steps), risk_level=derived_risk,
        consent_mode=consent, rollback_method=rollback_method,
        rollback_description=rollback_description,
        verification_method=vmethod,
        verification_timeout_seconds=timeout,
        expected_outcome=expected_outcome)


def _param(name, kind, description, required=True):
    return {"name": name, "kind": kind, "required": required,
            "description": description}


def _step(step_id, verb, ttype, tname, args, observable, expected,
          undo_verb):
    return {
        "step_id": step_id, "action_verb": verb,
        "target": {"type": ttype, "name": tname}, "args": args,
        "effects": [{"target": {"type": ttype, "name": tname},
                     "observable": observable, "expected": expected}],
        "undo_verb": undo_verb,
    }


def _recipe(recipe_id, title, health_issue, parameters, preconditions,
            abstain_when, steps, risk_level, consent_mode,
            rollback_method, rollback_description, verification_method,
            timeout_seconds, expected_outcome):
    return {
        "schema": RECIPE_SCHEMA, "schema_version": RECIPE_VERSION,
        "recipe_id": recipe_id, "title": title,
        "health_issue": health_issue, "parameters": parameters,
        "preconditions": preconditions,
        "abstain_when": [
            {"condition_id": cid, "description": desc}
            for cid, desc in abstain_when],
        "steps": steps, "risk_level": risk_level,
        "consent_mode": consent_mode,
        "rollback": {"method": rollback_method,
                     "description": rollback_description},
        "verification": {"method": verification_method,
                         "timeout_seconds": timeout_seconds},
        "expected_outcome": expected_outcome,
    }


# The built-in recipe catalog v0.1. Deliberately small: four recipes
# spanning L2-L4, every verb drawn from the LIF-0401 catalog. Adding
# a recipe is a catalog version change with its own review.
_RECIPE_LIST = [
    _recipe(
        "rec-restart-failed-service",
        "Restart a failed noncritical service",
        "An allowlisted noncritical systemd unit is in failed "
        "state although it is expected to be running.",
        [_param("unit", "unit",
                "Exact systemd unit name to restart")],
        ["$unit is in failed state",
         "$unit is expected to be running",
         "$unit is on the human-approved allowlist"],
        [("unit-intentionally-stopped",
          "The user intentionally stopped this unit; Eir never "
          "countermands an intentional stop (research/07)"),
         ("unit-is-critical-infrastructure",
          "The unit is critical infrastructure; live agent action "
          "on it is prohibited by the catalog"),
         ("restart-loop-detected",
          "The unit has restarted repeatedly in the window; a "
          "further restart would feed a restart loop")],
        [_step("step-1", "read_service_status", "systemd-unit",
               "$unit", {}, "service_state", "failed", "none"),
         _step("step-2", "restart_unit", "systemd-unit", "$unit",
               {}, "service_state", "active", "stop_unit")],
        "L3", "allowlist-notice", "stop_unit",
        "Stop the restarted unit, restoring its pre-repair state.",
        "unit_healthy", 60,
        "The named unit is active and passes its health check."),
    _recipe(
        "rec-revert-user-config",
        "Revert a drifted user-level configuration file",
        "A managed user-level configuration file differs from its "
        "recorded prior version and the service misbehaves.",
        [_param("config_path", "path",
                "Exact absolute path of the configuration file"),
         _param("prior_version_digest", "string",
                "Digest of the recorded prior version to restore")],
        ["$config_path differs from its recorded prior version",
         "the recorded prior version digest is available locally",
         "the configuration owner expects the prior version"],
        [("config-intentionally-changed",
          "The drift is an intentional user edit, not a fault"),
         ("config-target-protected",
          "The path sits under a protected prefix; agent mutation "
          "there is prohibited by the catalog"),
         ("prior-version-missing",
          "No recorded prior version exists to revert to")],
        [_step("step-1", "revert_user_config", "config-file",
               "$config_path",
               {"prior_version_digest": "$prior_version_digest"},
               "config_digest", "$prior_version_digest",
               "revert_user_config")],
        "L3", "allowlist-notice", "revert_user_config",
        "Revert the file again to the version recorded before "
        "this repair ran.",
        "config_valid", 60,
        "The file matches its recorded prior version and "
        "validates."),
    _recipe(
        "rec-reinstall-broken-package",
        "Reinstall a package that fails integrity checks",
        "An installed package's files no longer match the package "
        "database and the exact staged version is available.",
        [_param("package", "name", "Exact package name"),
         _param("version", "string",
                "Exact staged package version to install")],
        ["package $package fails its integrity check",
         "exact version $version is staged from the "
         "distribution repository",
         "a removal rollback is staged before install"],
        [("package-is-boot-or-trust",
          "The package is a boot or trust-root package; agent "
          "installation of it is prohibited by the catalog"),
         ("integrity-check-passes",
          "The package verifies clean; there is nothing to repair"),
         ("version-not-staged",
          "The exact version is not staged locally; installing "
          "would require an unreviewed fetch")],
        [_step("step-1", "check_package_integrity", "package",
               "$package", {}, "package_integrity", "failed",
               "none"),
         _step("step-2", "install_package", "package", "$package",
               {"version": "$version"}, "package_version",
               "$version", "remove_package")],
        "L4", "per-action", "remove_package",
        "Remove the installed package version, restoring the "
        "pre-repair package state.",
        "package_integrity", 120,
        "The exact staged version is installed and its files "
        "verify against the package database."),
    _recipe(
        "rec-lab-guest-config-fix",
        "Fix a faulty setting inside a disposable lab guest",
        "A configuration setting inside a disposable lab guest is "
        "wrong and the guest's unit fails with it.",
        [_param("guest", "name", "Exact disposable lab guest name"),
         _param("config_path", "path",
                "Exact config path inside the guest"),
         _param("setting", "name", "Exact setting name to change"),
         _param("value", "string", "Exact value to set"),
         _param("unit", "unit",
                "Exact unit inside the guest to restart")],
        ["lab guest $guest is running and disposable",
         "$config_path inside the guest holds the faulty setting"],
        [("guest-not-disposable",
          "The guest is not marked disposable; lab verbs must "
          "never reach a persistent system"),
         ("guest-is-live-host",
          "The named target is the live host, not a lab guest"),
         ("setting-already-correct",
          "The setting already holds the proposed value; there "
          "is nothing to repair")],
        [_step("step-1", "edit_config_in_guest", "config-file",
               "$config_path",
               {"guest": "$guest", "setting": "$setting",
                "value": "$value"},
               "config_setting", "$value", "reset_lab_guest"),
         _step("step-2", "restart_unit_in_guest", "systemd-unit",
               "$unit", {"guest": "$guest"}, "service_state",
               "active", "none")],
        "L2", "session-blanket", "reset_lab_guest",
        "Reset the disposable guest to its pinned clean state.",
        "unit_healthy_in_guest", 30,
        "The guest unit is active with the corrected setting."),
]

RECIPES: Tuple[Recipe, ...] = tuple(
    validate_recipe(data) for data in _RECIPE_LIST)
RECIPE_CATALOG: Dict[str, Recipe] = {r.recipe_id: r for r in RECIPES}


def recipes_catalog_as_dict() -> Dict[str, Any]:
    """The built-in catalog as a JSON-ready mapping (twin file)."""
    return {
        "schema": "lifthrasir.recipes.v0.1",
        "recipe_version": RECIPE_VERSION,
        "recipes": [r.to_dict() for r in RECIPES],
    }


def get_recipe(recipe_id: Any) -> Recipe:
    if not isinstance(recipe_id, str) or recipe_id not in RECIPE_CATALOG:
        raise UnknownRecipeError(
            f"unknown recipe {recipe_id!r}: the recipe catalog is "
            "a closed vocabulary and unknown recipes are refused")
    return RECIPE_CATALOG[recipe_id]


def _resolve(recipe: Any) -> Recipe:
    if isinstance(recipe, Recipe):
        return recipe
    if isinstance(recipe, str):
        return get_recipe(recipe)
    return validate_recipe(recipe)


def _parse_ts(value: Any, field_name: str) -> datetime:
    if not isinstance(value, str) or not value:
        raise BindingError(f"{field_name} must be an RFC3339 string")
    text = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        moment = datetime.fromisoformat(text)
    except ValueError as exc:
        raise BindingError(
            f"{field_name} {value!r} is not a valid timestamp") from exc
    if moment.tzinfo is None:
        raise BindingError(f"{field_name} must carry a timezone")
    return moment.astimezone(timezone.utc)


def _fmt_ts(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).strftime(
        "%Y-%m-%dT%H:%M:%SZ")


def _substitute(value: Any, bindings: Mapping[str, Any]) -> Any:
    pname = _PLACEHOLDER_RE.match(value) \
        if isinstance(value, str) else None
    if pname:
        return bindings[pname.group(1)]
    return value


def _substitute_text(text: str, bindings: Mapping[str, Any]) -> str:
    def replace(match: "re.Match") -> str:
        return str(bindings[match.group(1)])
    return _TOKEN_RE.sub(replace, text)


def instantiate(recipe: Any, *, plan_id: str, incident_id: str,
                hypothesis_ids: List[str],
                bindings: Mapping[str, Any], created_at: str,
                expires_at: str) -> Dict[str, Any]:
    """Bind a recipe to exact values; return a v0.1 plan record.

    The emitted plan is data only. It must pass the banked plan
    checks (catalog plan-step validation and the LIF-0404 shape
    check) and a per-step catalog request validation at the bound
    targets, or BindingError is raised and no plan is returned.
    Policy evaluation (LIF-0402) and approval (LIF-0404) remain
    separate, later acts; instantiation grants nothing.
    """
    parsed = _resolve(recipe)
    if not isinstance(plan_id, str) or not _PLAN_ID_RE.match(plan_id):
        raise BindingError(f"plan_id {plan_id!r} is malformed")
    if not isinstance(incident_id, str) \
            or not _INCIDENT_ID_RE.match(incident_id):
        raise BindingError(f"incident_id {incident_id!r} is malformed")
    if not isinstance(hypothesis_ids, list) or not hypothesis_ids \
            or any(not isinstance(h, str)
                   or not _HYPOTHESIS_ID_RE.match(h)
                   for h in hypothesis_ids):
        raise BindingError(
            "hypothesis_ids must be a non-empty list of hyp- ids")
    created = _parse_ts(created_at, "created_at")
    expires = _parse_ts(expires_at, "expires_at")
    if expires <= created:
        raise BindingError("expires_at must be after created_at")
    if not isinstance(bindings, Mapping):
        raise BindingError("bindings must be an object")
    declared = {p.name: p for p in parsed.parameters}
    for key in bindings:
        if key not in declared:
            raise BindingError(
                f"binding {key!r} names no declared parameter: "
                "bindings are exact, never open")
    for param in parsed.parameters:
        if param.required and param.name not in bindings:
            raise BindingError(
                f"required parameter ${param.name} has no binding")
    now = created.timestamp()
    steps: List[Dict[str, Any]] = []
    for step in parsed.steps:
        target_name = _substitute(step.target_name, bindings)
        args = {key: _substitute(value, bindings)
                for key, value in step.args}
        request = ActionRequest(
            verb=step.verb,
            target=ActionTarget(type=step.target_type,
                                name=target_name),
            args=args, plan_id=plan_id, expires_at=expires.timestamp())
        try:
            validate_request(request, now)
        except Exception as exc:
            raise BindingError(
                f"step {step.step_id} at its bound target: "
                f"{exc}") from exc
        steps.append({
            "step_id": step.step_id, "action_verb": step.verb,
            "target": {"type": step.target_type, "name": target_name},
            "args": args,
        })
    plan = {
        "schema": "lifthrasir.plan.v0.1", "schema_version": "0.1",
        "plan_id": plan_id, "incident_id": incident_id,
        "hypothesis_ids": list(hypothesis_ids),
        "title": parsed.title, "status": "draft",
        "risk_level": parsed.risk_level,
        "consent_mode": parsed.consent_mode,
        "steps": steps,
        "preconditions": [
            _substitute_text(text, bindings)
            for text in parsed.preconditions],
        "rollback": {"method": parsed.rollback_method,
                     "description": parsed.rollback_description},
        "verification": {
            "method": parsed.verification_method,
            "timeout_seconds": parsed.verification_timeout_seconds},
        "created_at": _fmt_ts(created), "expires_at": _fmt_ts(expires),
    }
    problems = validate_plan_steps(plan)
    if problems:
        raise BindingError(
            "instantiated plan fails catalog validation: "
            + "; ".join(problems))
    try:
        check_plan_shape(plan)
    except ApprovalError as exc:
        raise BindingError(
            f"instantiated plan fails the approval shape check: "
            f"{exc}") from exc
    return plan


def expected_effects(recipe: Any, *,
                     bindings: Mapping[str, Any]) -> List[Dict[str, Any]]:
    """The exact effects a bound recipe must produce, per step.

    Verification (LIF-0504) compares observed state against this
    list; an effect that does not materialise exactly is a failed
    repair, never a partial success to narrate over.
    """
    parsed = _resolve(recipe)
    out: List[Dict[str, Any]] = []
    for step in parsed.steps:
        for effect in step.effects:
            out.append({
                "step_id": step.step_id,
                "target": {
                    "type": effect.target_type,
                    "name": _substitute(effect.target_name, bindings)},
                "observable": effect.observable,
                "expected": _substitute(effect.expected, bindings),
            })
    return out


def check_applicability(recipe: Any,
                        observations: Mapping[str, bool]
                        ) -> ApplicabilityDecision:
    """Decide APPLICABLE vs ABSTAIN from an observation snapshot.

    Keys are the recipe's precondition texts (verbatim, parameters
    unsubstituted: applicability is judged before binding) and its
    abstain condition ids. Any abstain condition observed true, any
    precondition observed false, and any precondition with NO
    observation each force ABSTAIN with named reason codes.
    """
    parsed = _resolve(recipe)
    if not isinstance(observations, Mapping):
        raise MalformedRecipeError("observations must be an object")
    reasons: List[str] = []
    for condition in parsed.abstain_when:
        if observations.get(condition.condition_id) is True:
            reasons.append(
                f"ABSTAIN_CONDITION:{condition.condition_id}")
    for text in parsed.preconditions:
        observed = observations.get(text)
        if observed is False:
            reasons.append(f"PRECONDITION_FAILED:{text}")
        elif observed is not True:
            reasons.append(f"PRECONDITION_UNVERIFIED:{text}")
    if reasons:
        return ApplicabilityDecision(
            recipe_id=parsed.recipe_id, outcome="abstain",
            reason_codes=tuple(reasons))
    return ApplicabilityDecision(
        recipe_id=parsed.recipe_id, outcome="applicable",
        reason_codes=("ALL_PRECONDITIONS_OBSERVED",))


# Re-exported for callers that deep-copy built-in records to mutate.
def builtin_recipe_dicts() -> List[Dict[str, Any]]:
    """Deep copies of the built-in recipe records (fixture use)."""
    return copy.deepcopy(_RECIPE_LIST)
