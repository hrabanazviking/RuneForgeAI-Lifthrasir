"""Independent reproducer and verifier roles (LIF-0702).

SPDX-License-Identifier: GPL-2.0-only

Home justification: master roadmap section 3 places core code in
``src/lifthrasir/`` beside the Replicater companions (LIF-0701 DAG
executor, LIF-0305 hypotheses, LIF-0601 model provider).  The
Replicater's separation-of-duties rule -- the agent that reproduces
a claim never grades its own reproduction -- is core code in the
same sense, so it lives here, not in ``lab/``.  Like LIF-0701, this
slice deliberately does NOT touch the package ``__init__`` export
list: the banking seat unions export lists, and
``from lifthrasir import reproverify`` works either way.  Desired
exports are flagged in CAMPAIGN_STATE.md.

What this slice builds:

- Two named roles, one task.  A ``ReproductionTask`` names exactly
  one reproducer actor and one verifier actor, a fixture ``spec``
  (the steps/payload both roles run), and the claim under test,
  optionally bound to a banked LIF-0305 hypothesis record
  (validated with ``validate_hypothesis`` before anything runs).
  The two actors MUST differ: a task whose reproducer and verifier
  are the same actor is refused with ``SeparationViolationError``
  before any work runs.  There is no API to reassign a role after
  validation, and neither role runner is ever invoked by the other
  role's code path.
- Sealed reproducer output.  ``run_reproduction`` runs the
  reproducer callable exactly once on the task spec and returns a
  ``ReproductionReport`` whose ``seal`` is a SHA-256 over the
  canonical task core plus the observed outcome and output.  Any
  later edit to the report's outcome, output, task or actor breaks
  the seal and verification refuses with ``TamperedReportError``
  before the verifier callable runs.
- Blinded verification.  ``blinded_view(task)`` is the ONLY task
  view handed to a verifier before it commits: it carries the
  spec and the claim, and it carries neither the reproducer's
  identity, nor its outcome, nor its output.  ``run_verification``
  runs the verifier callable on that blinded spec alone, and only
  AFTER the verifier outcome exists does it unseal and compare.
  Agreement is mechanical: equal outcomes ``confirmed``, differing
  deterministic outcomes ``contradicted``, a verifier error or an
  explicit inconclusive outcome ``inconclusive``.  Confidence is
  never compared; there is no confidence field anywhere here.
- Independent check assembly.  ``run_independent_check`` runs both
  roles in order (reproduce, seal, blind, verify, compare) and
  returns an ``IndependentCheck`` whose final status is one of
  ``corroborated`` (both reproduced), ``refuted`` (both agreed the
  claim does not reproduce), ``disputed`` (roles disagree) or
  ``inconclusive``.  ``evidence_records()`` emits one LIF-0305-style
  record per role outcome plus one for the comparison, with
  deterministic ``ev-...`` ids; a corroborated check is recorded
  as an outcome, never promoted to a ``supported`` hypothesis
  status -- status changes stay with the hypothesis ledger.

Fixture workloads only: runners are in-process callables handed in
by the caller.  This module imports no process, network or HTTP
machinery, runs no real system check by itself, and mutates no
host state.  A runner that raises is recorded ``error``; it never
propagates out of the role that ran it.

Evidence-status honesty: proven at fixture level only by this
slice's tests (in-process doubles).  No real reproducer fleet,
host service, or live system was involved, and no evidence-ladder
rung above ``reproducer`` is claimed for any artifact here.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple

from .hypotheses import validate_hypothesis

REPRO_SCHEMA = "lifthrasir.reproverify.v0.1"
REPRO_SCHEMA_VERSION = "0.1"
EVIDENCE_SCHEMA = "lifthrasir.reproevidence.v0.1"

ROLE_REPRODUCER = "reproducer"
ROLE_VERIFIER = "verifier"
ROLES = (ROLE_REPRODUCER, ROLE_VERIFIER)

OUTCOME_REPRODUCED = "reproduced"
OUTCOME_NOT_REPRODUCED = "not-reproduced"
OUTCOME_INCONCLUSIVE = "inconclusive"
OUTCOME_ERROR = "error"
OUTCOMES = (OUTCOME_REPRODUCED, OUTCOME_NOT_REPRODUCED,
            OUTCOME_INCONCLUSIVE, OUTCOME_ERROR)
DETERMINISTIC_OUTCOMES = (OUTCOME_REPRODUCED, OUTCOME_NOT_REPRODUCED)

VERDICT_CONFIRMED = "confirmed"
VERDICT_CONTRADICTED = "contradicted"
VERDICT_INCONCLUSIVE = "inconclusive"
VERDICTS = (VERDICT_CONFIRMED, VERDICT_CONTRADICTED,
            VERDICT_INCONCLUSIVE)

CHECK_CORROBORATED = "corroborated"
CHECK_REFUTED = "refuted"
CHECK_DISPUTED = "disputed"
CHECK_INCONCLUSIVE = "inconclusive"
CHECK_STATUSES = (CHECK_CORROBORATED, CHECK_REFUTED, CHECK_DISPUTED,
                  CHECK_INCONCLUSIVE)

MAX_SPEC_BYTES = 65536
MAX_CLAIM_CHARS = 4096
MAX_OUTPUT_BYTES = 65536

_TASK_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")
_ACTOR_RE = re.compile(r"^[a-z0-9][a-z0-9._-]*$")
_HYP_RE = re.compile(r"^hyp-[a-z0-9][a-z0-9-]*$")
_INC_RE = re.compile(r"^inc-[a-z0-9][a-z0-9-]*$")


class ReproVerifyError(Exception):
    """Base class for all named reproducer/verifier refusals."""


class MalformedTaskError(ReproVerifyError):
    """Raised when a task or report breaks a structural rule."""


class SeparationViolationError(ReproVerifyError):
    """Raised when one actor would hold both roles on a task."""


class TamperedReportError(ReproVerifyError):
    """Raised when a sealed report no longer matches its seal."""


class UnboundedTaskError(ReproVerifyError):
    """Raised when a size bound exceeds its hard ceiling."""


def _canonical(obj: Any) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=True).encode("utf-8")


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _check_id(value: Any, pattern: Any, what: str) -> str:
    if not isinstance(value, str) or not pattern.match(value):
        raise MalformedTaskError(f"{what} {value!r} is not well-formed")
    return value


@dataclass(frozen=True)
class ReproductionTask:
    """One claim, one fixture spec, two distinct role actors.

    ``spec`` is the JSON-serialisable fixture both roles run; it is
    the only work input either role receives.  ``hypothesis`` is an
    optional LIF-0305 record dict, validated before anything runs;
    when present, ``hypothesis_id`` must match its record.
    """

    task_id: str
    claim: str
    spec: Any
    reproducer_actor: str
    verifier_actor: str
    hypothesis_id: Optional[str] = None
    incident_id: Optional[str] = None
    hypothesis: Optional[Dict[str, Any]] = field(default=None, repr=False)

    def core(self) -> Dict[str, Any]:
        return {
            "task_id": self.task_id, "claim": self.claim,
            "spec": self.spec,
            "reproducer_actor": self.reproducer_actor,
            "verifier_actor": self.verifier_actor,
            "hypothesis_id": self.hypothesis_id,
            "incident_id": self.incident_id,
        }

    def digest(self) -> str:
        return _sha256(_canonical(self.core()))


def validate_task(task: Any) -> ReproductionTask:
    """Validate a task; refuse same-actor roles before any run."""
    if not isinstance(task, ReproductionTask):
        raise MalformedTaskError(
            f"task must be ReproductionTask, got {type(task).__name__}")
    _check_id(task.task_id, _TASK_RE, "task_id")
    _check_id(task.reproducer_actor, _ACTOR_RE, "reproducer_actor")
    _check_id(task.verifier_actor, _ACTOR_RE, "verifier_actor")
    if task.reproducer_actor == task.verifier_actor:
        raise SeparationViolationError(
            f"actor {task.reproducer_actor!r} cannot hold both the "
            f"reproducer and verifier roles on task {task.task_id!r}")
    if not isinstance(task.claim, str) or not task.claim.strip():
        raise MalformedTaskError("claim must be a non-empty string")
    if len(task.claim) > MAX_CLAIM_CHARS:
        raise UnboundedTaskError(
            f"claim of {len(task.claim)} chars exceeds ceiling "
            f"{MAX_CLAIM_CHARS}")
    try:
        spec_bytes = _canonical(task.spec)
    except (TypeError, ValueError):
        raise MalformedTaskError("spec is not JSON-serialisable") from None
    if len(spec_bytes) > MAX_SPEC_BYTES:
        raise UnboundedTaskError(
            f"spec of {len(spec_bytes)} bytes exceeds ceiling "
            f"{MAX_SPEC_BYTES}")
    if task.hypothesis_id is not None:
        _check_id(task.hypothesis_id, _HYP_RE, "hypothesis_id")
    if task.incident_id is not None:
        _check_id(task.incident_id, _INC_RE, "incident_id")
    if task.hypothesis is not None:
        if not isinstance(task.hypothesis, dict):
            raise MalformedTaskError("hypothesis must be a record dict")
        record = validate_hypothesis(task.hypothesis)
        if task.hypothesis_id != record["hypothesis_id"]:
            raise MalformedTaskError(
                "hypothesis_id does not match its record")
        if task.incident_id is not None and \
                task.incident_id != record["incident_id"]:
            raise MalformedTaskError(
                "incident_id does not match its hypothesis record")
    return task


def blinded_view(task: ReproductionTask) -> Dict[str, Any]:
    """The only pre-commit view a verifier may see.

    Carries the claim and the spec -- everything needed to run the
    fixture independently -- and nothing else: no reproducer
    identity, no reproducer outcome, no reproducer output, and no
    verifier identity either (a verifier grades a fixture, not a
    colleague).  The task digest is included so the verifier's run
    can later be bound to exactly this task.
    """
    validate_task(task)
    return {
        "schema": REPRO_SCHEMA,
        "task_id": task.task_id,
        "task_digest": task.digest(),
        "claim": task.claim,
        "spec": task.spec,
        "hypothesis_id": task.hypothesis_id,
        "incident_id": task.incident_id,
    }


def _normalise_result(raw: Any, role: str) -> Tuple[str, Any, Optional[str]]:
    """Normalise one runner return to (outcome, output, error).

    A runner returns either an outcome string, a bool (True means
    reproduced), or a dict with ``outcome`` and optional ``output``
    keys.  Anything else is an ``error`` outcome for that role --
    recorded, never raised -- so one malformed role result cannot
    crash the comparison.
    """
    if isinstance(raw, bool):
        return (OUTCOME_REPRODUCED if raw else OUTCOME_NOT_REPRODUCED,
                raw, None)
    if isinstance(raw, str) and raw in OUTCOMES and raw != OUTCOME_ERROR:
        return raw, None, None
    if isinstance(raw, dict):
        outcome = raw.get("outcome")
        if outcome in OUTCOMES and outcome != OUTCOME_ERROR:
            output = raw.get("output")
            try:
                blob = _canonical(output)
            except (TypeError, ValueError):
                return OUTCOME_ERROR, None, (
                    f"{role} output is not JSON-serialisable")
            if len(blob) > MAX_OUTPUT_BYTES:
                return OUTCOME_ERROR, None, (
                    f"{role} output exceeds {MAX_OUTPUT_BYTES} bytes")
            return outcome, output, None
    return OUTCOME_ERROR, None, (
        f"{role} returned an unrecognised result: {raw!r:.120}")


def _run_role(fn: Any, view: Dict[str, Any], role: str) -> Tuple[str, Any, Optional[str]]:
    if not callable(fn):
        return OUTCOME_ERROR, None, f"{role} runner is not callable"
    try:
        raw = fn(view)
    except Exception as exc:  # failure-isolation boundary per role
        return OUTCOME_ERROR, None, f"{type(exc).__name__}: {exc}"
    return _normalise_result(raw, role)


@dataclass(frozen=True)
class ReproductionReport:
    schema: str
    task_id: str
    task_digest: str
    actor: str
    outcome: str
    output: Any
    error: Optional[str]
    seal: str

    def as_dict(self) -> Dict[str, Any]:
        return {
            "schema": self.schema, "task_id": self.task_id,
            "task_digest": self.task_digest, "actor": self.actor,
            "outcome": self.outcome, "output": self.output,
            "error": self.error, "seal": self.seal,
        }


def _seal(task_digest: str, actor: str, outcome: str, output: Any,
          error: Optional[str]) -> str:
    return _sha256(_canonical({
        "task_digest": task_digest, "actor": actor,
        "outcome": outcome, "output": output, "error": error,
    }))


def run_reproduction(task: ReproductionTask,
                     runner: Callable[..., Any]) -> ReproductionReport:
    """Run the reproducer role once and seal its report.

    The runner receives the full task core (the reproducer knows
    its own assignment).  Its result is normalised, bounded, and
    sealed; a raising runner is recorded ``error``, never raised.
    """
    validate_task(task)
    view = dict(task.core())
    view["role"] = ROLE_REPRODUCER
    outcome, output, error = _run_role(runner, view, ROLE_REPRODUCER)
    digest = task.digest()
    return ReproductionReport(
        schema=REPRO_SCHEMA, task_id=task.task_id, task_digest=digest,
        actor=task.reproducer_actor, outcome=outcome, output=output,
        error=error,
        seal=_seal(digest, task.reproducer_actor, outcome, output, error))


def verify_seal(task: ReproductionTask, report: Any) -> ReproductionReport:
    """Check a report belongs to this task, this reproducer, intact.

    Refuses a foreign task, a wrong actor (including the verifier
    presenting its own work as the reproduction), or any edit made
    after sealing -- all before any verifier callable runs.
    """
    validate_task(task)
    if not isinstance(report, ReproductionReport):
        raise MalformedTaskError(
            f"report must be ReproductionReport, got "
            f"{type(report).__name__}")
    if report.task_id != task.task_id or \
            report.task_digest != task.digest():
        raise TamperedReportError(
            f"report is bound to a different task than {task.task_id!r}")
    if report.actor != task.reproducer_actor:
        raise SeparationViolationError(
            f"report actor {report.actor!r} is not the assigned "
            f"reproducer {task.reproducer_actor!r}")
    if report.outcome not in OUTCOMES:
        raise MalformedTaskError(
            f"report outcome {report.outcome!r} not in {OUTCOMES}")
    expected = _seal(report.task_digest, report.actor, report.outcome,
                     report.output, report.error)
    if report.seal != expected:
        raise TamperedReportError(
            "report seal mismatch: outcome, output or actor was "
            "edited after sealing")
    return report


@dataclass(frozen=True)
class VerificationReport:
    schema: str
    task_id: str
    task_digest: str
    actor: str
    verifier_outcome: str
    verifier_output: Any
    verifier_error: Optional[str]
    reproducer_outcome: str
    verdict: str
    digest: str

    def as_dict(self) -> Dict[str, Any]:
        return {
            "schema": self.schema, "task_id": self.task_id,
            "task_digest": self.task_digest, "actor": self.actor,
            "verifier_outcome": self.verifier_outcome,
            "verifier_output": self.verifier_output,
            "verifier_error": self.verifier_error,
            "reproducer_outcome": self.reproducer_outcome,
            "verdict": self.verdict, "digest": self.digest,
        }


def compare_outcomes(reproducer_outcome: str,
                       verifier_outcome: str) -> str:
    """Mechanical agreement rule; no judgement, no confidence."""
    for outcome in (reproducer_outcome, verifier_outcome):
        if outcome not in OUTCOMES:
            raise MalformedTaskError(
                f"outcome {outcome!r} not in {OUTCOMES}")
    if verifier_outcome in (OUTCOME_ERROR, OUTCOME_INCONCLUSIVE):
        return VERDICT_INCONCLUSIVE
    if reproducer_outcome in (OUTCOME_ERROR, OUTCOME_INCONCLUSIVE):
        return VERDICT_INCONCLUSIVE
    if reproducer_outcome == verifier_outcome:
        return VERDICT_CONFIRMED
    return VERDICT_CONTRADICTED


def run_verification(task: ReproductionTask, report: ReproductionReport,
                       runner: Callable[..., Any]) -> VerificationReport:
    """Run the verifier role blind, then unseal and compare.

    Order is the guarantee: the seal is checked first (a tampered
    report runs no verifier at all), the verifier callable receives
    ONLY ``blinded_view(task)`` plus its role name, and the sealed
    outcome is read only after the verifier outcome exists.
    """
    verify_seal(task, report)
    view = blinded_view(task)
    view["role"] = ROLE_VERIFIER
    outcome, output, error = _run_role(runner, view, ROLE_VERIFIER)
    verdict = compare_outcomes(report.outcome, outcome)
    digest = _sha256(_canonical({
        "task_digest": task.digest(), "report_seal": report.seal,
        "verifier_actor": task.verifier_actor,
        "verifier_outcome": outcome, "verdict": verdict,
    }))
    return VerificationReport(
        schema=REPRO_SCHEMA, task_id=task.task_id,
        task_digest=task.digest(), actor=task.verifier_actor,
        verifier_outcome=outcome, verifier_output=output,
        verifier_error=error, reproducer_outcome=report.outcome,
        verdict=verdict, digest=digest)


@dataclass(frozen=True)
class IndependentCheck:
    schema: str
    task_id: str
    status: str
    reproduction: ReproductionReport
    verification: VerificationReport
    digest: str
    hypothesis_id: Optional[str] = None

    @property
    def ok(self) -> bool:
        return self.status in (CHECK_CORROBORATED, CHECK_REFUTED)

    def as_dict(self) -> Dict[str, Any]:
        return {
            "schema": self.schema, "task_id": self.task_id,
            "status": self.status,
            "hypothesis_id": self.hypothesis_id,
            "reproduction": self.reproduction.as_dict(),
            "verification": self.verification.as_dict(),
            "digest": self.digest,
        }

    def evidence_records(self) -> List[Dict[str, Any]]:
        """One LIF-0305-style record per role outcome + comparison.

        Bearings: a ``reproduced`` outcome bears ``for`` the claim,
        ``not-reproduced`` bears ``against``, anything else bears
        ``neither``.  The comparison record bears ``for`` only when
        corroborated and ``against`` only when refuted; disputed
        and inconclusive comparisons bear ``neither`` -- a dispute
        is evidence of disagreement, not of the claim.  Ids are
        deterministic over task digest + role + outcome.  No record
        promotes a hypothesis status or an evidence-ladder rung.
        """
        def bearing(outcome: str) -> str:
            return ("for" if outcome == OUTCOME_REPRODUCED else
                    "against" if outcome == OUTCOME_NOT_REPRODUCED
                    else "neither")
        rows = [
            (ROLE_REPRODUCER, self.reproduction.actor,
             self.reproduction.outcome, bearing(self.reproduction.outcome)),
            (ROLE_VERIFIER, self.verification.actor,
             self.verification.verifier_outcome,
             bearing(self.verification.verifier_outcome)),
        ]
        cmp_bearing = ("for" if self.status == CHECK_CORROBORATED else
                       "against" if self.status == CHECK_REFUTED
                       else "neither")
        rows.append(("comparison", None, self.status, cmp_bearing))
        out: List[Dict[str, Any]] = []
        for role, actor, outcome, bear in rows:
            seed = _canonical([self.task_id, self.digest, role, outcome])
            out.append({
                "schema": EVIDENCE_SCHEMA,
                "evidence_id": "ev-" + _sha256(seed)[:16],
                "task_id": self.task_id,
                "hypothesis_id": self.hypothesis_id,
                "role": role, "actor": actor,
                "outcome": outcome, "bearing": bear,
            })
        return out


def check_status(reproduction: ReproductionReport,
                   verification: VerificationReport) -> str:
    """Final status from a sealed pair of role reports."""
    if verification.verdict == VERDICT_INCONCLUSIVE:
        return CHECK_INCONCLUSIVE
    if verification.verdict == VERDICT_CONTRADICTED:
        return CHECK_DISPUTED
    if reproduction.outcome == OUTCOME_REPRODUCED:
        return CHECK_CORROBORATED
    return CHECK_REFUTED


def run_independent_check(task: ReproductionTask,
                          reproducer_runner: Callable[..., Any],
                          verifier_runner: Callable[..., Any]) -> IndependentCheck:
    """Reproduce, seal, blind-verify and compare, in that order."""
    validate_task(task)
    reproduction = run_reproduction(task, reproducer_runner)
    verification = run_verification(task, reproduction, verifier_runner)
    status = check_status(reproduction, verification)
    digest = _sha256(_canonical({
        "task_digest": task.digest(), "report_seal": reproduction.seal,
        "verification_digest": verification.digest, "status": status,
    }))
    return IndependentCheck(
        schema=REPRO_SCHEMA, task_id=task.task_id, status=status,
        reproduction=reproduction, verification=verification,
        digest=digest, hypothesis_id=task.hypothesis_id)
