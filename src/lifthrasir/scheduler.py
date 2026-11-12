"""Resource-aware agent scheduler and evidentiary arbitration (LIF-0703).

SPDX-License-Identifier: GPL-2.0-only

Home justification: master roadmap section 3 lays out ``src/`` for
core code and LIF-0201/LIF-0301/LIF-0305/LIF-0601 already placed the
event bus, the event store, causal hypotheses and the model-provider
protocol in ``src/lifthrasir/``.  Scheduling and arbitration are the
Replicater workforce plane (roadmap section 0 architecture:
"Replicater: bounded subagents -- hypotheses / repro / patch / QA";
workstream C: "task schemas, costs, cancellation"), so they live
beside those pieces here, not in ``lab/`` and not in ``ui/``.  This
module deliberately does NOT touch ``src/lifthrasir/__init__.py``
(the LIF-0303/LIF-0402/LIF-0601 precedent): the banking seat unions
exports; a namespace import (``from lifthrasir import scheduler``)
works without an ``__init__`` edit, so this slice can never conflict
there.  Desired exports are flagged in CAMPAIGN_STATE.md.

Design against banked contracts only: the evidence-status ladder is
imported verbatim from LIF-0305 (``hypotheses.EVIDENCE_LADDER``) --
this module defines no second ladder.  LIF-0701 (DAG executor) and
LIF-0702 (reproducer/verifier roles) are unbanked at build time and
nothing here depends on their code; work items and claims are plain
fixture-shaped records in the LIF-0004 dict style.

What this slice builds:

- Scheduling.  A ``WorkItem`` declares its cost up front (CPU in
  milli-cores, memory in MiB, run duration) and a ``ResourceBudget``
  declares the envelope (total CPU, total memory, concurrency
  ``slots``, and a ``time_window_s`` no single admitted run may
  exceed).  ``schedule_work(items, budget)`` is a pure, deterministic
  function: items are evaluated in a fixed order (priority
  descending, then submission ``sequence``, then ``work_id``), each
  item is ADMITTED only if it fits in the capacity the already
  admitted items leave, and every other item is DEFERRED with a
  typed ``AdmissionDecision`` naming every binding constraint, the
  primary (first, in the fixed cpu/memory/slots/time order) binding
  constraint, the numbers behind the refusal, and whether the item
  could ever fit this budget alone (``fits_alone``).  Nothing is
  silently dropped and nothing is over-admitted: the admitted set
  never exceeds the budget in any dimension, and every input item
  appears exactly once in the plan, admitted or deferred.
  ``Scheduler`` is the stateful twin for a live queue: ``submit``
  admits or queues, ``complete`` frees the finished item's capacity
  and re-evaluates the queue in the same deterministic order,
  promoting whatever now fits.
- Evidentiary arbitration.  An ``EvidenceClaim`` is one work item's
  evidence-backed verdict on a subject: a verdict string, the
  banked ladder rung (``evidence_status``) its evidence has
  reached, the evidence ids behind it, and a ``confidence`` number
  that is recorded but NEVER decisive on its own.  ``arbitrate_claims``
  rules on two claims about the same subject: agreeing verdicts need
  no ruling (``agree``); conflicting verdicts are decided FIRST by
  ladder rung -- a higher rung wins however confident the lower
  claim is -- and, only at the same rung, by evidence breadth (more
  distinct evidence ids).  If rung and breadth both tie, the ruling
  is ``unresolved`` and names human review: confidence is
  explicitly not a tie-break, because a confident guess must never
  outrank equally-ranked evidence.  The typed ``ArbitrationRuling``
  preserves BOTH claims verbatim and lists the losing claim's
  evidence separately (``losing_evidence``): losing evidence is
  preserved, never deleted (the LIF-0305 retention rule applied to
  arbitration).

Bounds (master roadmap section 0 invariants 3 and 9): budgets and
items are finite by construction -- hard caps refuse absurd values
by name (``UnboundedBudgetError``) rather than silently clamping
them.  This module performs no host access, starts no process, and
runs no work: it decides admission and rules on evidence, purely
over the records it is handed.

Evidence-status honesty: scheduling decisions and arbitration
rulings are proven at fixture/lab level by this slice's tests, on
purpleraider only.  No rung is promoted by an arbitration win: the
ruling records which claim prevailed and why, at the rungs the
claims themselves declared.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from .hypotheses import EVIDENCE_LADDER

SCHEDULER_SCHEMA = "lifthrasir.scheduler.v0.1"
SCHEDULER_VERSION = "0.1"

WORK_KINDS = (
    "reproducer", "verifier", "hypothesis", "repair", "analysis",
    "generic",
)
DECISIONS = ("admitted", "deferred")
CONSTRAINTS = ("cpu", "memory", "slots", "time")
RULING_OUTCOMES = ("agree", "upheld-first", "upheld-second", "unresolved")

# Hard caps: a budget or item that cannot state finite bounds is
# refused, never silently clamped (roadmap section 0 invariants).
MAX_CPU_MILLI = 64000
MAX_MEMORY_MB = 1048576
MAX_SLOTS = 64
MAX_TIME_WINDOW_S = 86400.0
MAX_DURATION_S = 86400.0
MAX_ITEMS = 4096

_WORK_RE = re.compile(r"^work-[a-z0-9][a-z0-9-]*$")
_CLAIM_RE = re.compile(r"^claim-[a-z0-9][a-z0-9-]*$")
_EV_RE = re.compile(r"^ev-[a-z0-9][a-z0-9-]*$")


class SchedulerError(Exception):
    """Base class for all named scheduler/arbitration refusals."""


class MalformedBudgetError(SchedulerError):
    """Raised when a ResourceBudget breaks a field rule."""


class UnboundedBudgetError(MalformedBudgetError):
    """Raised when a budget or item exceeds a hard cap."""


class MalformedWorkItemError(SchedulerError):
    """Raised when a WorkItem breaks a field rule."""


class DuplicateWorkItemError(SchedulerError):
    """Raised when one plan/queue names the same work_id twice."""


class UnknownWorkItemError(SchedulerError):
    """Raised when complete() names an item that is not admitted."""


class MalformedClaimError(SchedulerError):
    """Raised when an EvidenceClaim breaks a field rule."""


class ArbitrationError(SchedulerError):
    """Raised when two claims cannot be arbitrated at all."""


def evidence_rank(evidence_status: str) -> int:
    """Ladder rank of a banked evidence status (higher is stronger).

    The ladder itself is LIF-0305's ``EVIDENCE_LADDER``, imported
    verbatim; an unknown status is refused, never ranked as zero.
    """
    if evidence_status not in EVIDENCE_LADDER:
        raise MalformedClaimError(
            f"evidence_status {evidence_status!r} is not a rung of "
            f"the banked evidence ladder {EVIDENCE_LADDER}")
    return EVIDENCE_LADDER.index(evidence_status)


def _check_int(value: Any, field_name: str, err: type) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise err(f"{field_name} must be an int, got "
                  f"{type(value).__name__}")
    return value


def _check_number(value: Any, field_name: str, err: type) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise err(f"{field_name} must be a number, got "
                  f"{type(value).__name__}")
    return float(value)


@dataclass(frozen=True)
class ResourceBudget:
    """The declared envelope work is admitted against."""

    cpu_milli: int
    memory_mb: int
    slots: int
    time_window_s: float

    def __post_init__(self) -> None:
        for name in ("cpu_milli", "memory_mb", "slots"):
            value = _check_int(getattr(self, name), name,
                               MalformedBudgetError)
            if value < 1:
                raise MalformedBudgetError(
                    f"{name} must be at least 1, got {value}")
        if self.cpu_milli > MAX_CPU_MILLI:
            raise UnboundedBudgetError(
                f"cpu_milli {self.cpu_milli} exceeds the hard cap "
                f"{MAX_CPU_MILLI}")
        if self.memory_mb > MAX_MEMORY_MB:
            raise UnboundedBudgetError(
                f"memory_mb {self.memory_mb} exceeds the hard cap "
                f"{MAX_MEMORY_MB}")
        if self.slots > MAX_SLOTS:
            raise UnboundedBudgetError(
                f"slots {self.slots} exceeds the hard cap {MAX_SLOTS}")
        window = _check_number(self.time_window_s, "time_window_s",
                               MalformedBudgetError)
        if window <= 0:
            raise MalformedBudgetError(
                f"time_window_s must be positive, got {window}")
        if window > MAX_TIME_WINDOW_S:
            raise UnboundedBudgetError(
                f"time_window_s {window} exceeds the hard cap "
                f"{MAX_TIME_WINDOW_S}")
        object.__setattr__(self, "time_window_s", window)


@dataclass(frozen=True)
class WorkItem:
    """One unit of agent work with its cost declared up front."""

    work_id: str
    kind: str
    cpu_milli: int
    memory_mb: int
    duration_s: float
    priority: int = 50
    sequence: int = 0
    subject: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.work_id, str) \
                or not _WORK_RE.match(self.work_id):
            raise MalformedWorkItemError(
                f"work_id {self.work_id!r} is not a well-formed "
                f"work id (work-...)")
        if self.kind not in WORK_KINDS:
            raise MalformedWorkItemError(
                f"kind {self.kind!r} is not one of {WORK_KINDS}")
        for name in ("cpu_milli", "memory_mb"):
            value = _check_int(getattr(self, name), name,
                               MalformedWorkItemError)
            if value < 1:
                raise MalformedWorkItemError(
                    f"{name} must be at least 1, got {value}")
        if self.cpu_milli > MAX_CPU_MILLI:
            raise UnboundedBudgetError(
                f"item cpu_milli {self.cpu_milli} exceeds the hard "
                f"cap {MAX_CPU_MILLI}")
        if self.memory_mb > MAX_MEMORY_MB:
            raise UnboundedBudgetError(
                f"item memory_mb {self.memory_mb} exceeds the hard "
                f"cap {MAX_MEMORY_MB}")
        duration = _check_number(self.duration_s, "duration_s",
                                 MalformedWorkItemError)
        if duration <= 0:
            raise MalformedWorkItemError(
                f"duration_s must be positive, got {duration}")
        if duration > MAX_DURATION_S:
            raise UnboundedBudgetError(
                f"duration_s {duration} exceeds the hard cap "
                f"{MAX_DURATION_S}")
        object.__setattr__(self, "duration_s", duration)
        priority = _check_int(self.priority, "priority",
                              MalformedWorkItemError)
        if not 0 <= priority <= 100:
            raise MalformedWorkItemError(
                f"priority must be in 0..100, got {priority}")
        sequence = _check_int(self.sequence, "sequence",
                              MalformedWorkItemError)
        if sequence < 0:
            raise MalformedWorkItemError(
                f"sequence must be at least 0, got {sequence}")
        if not isinstance(self.subject, str):
            raise MalformedWorkItemError("subject must be a string")

    def fits_alone(self, budget: ResourceBudget) -> bool:
        """True when this item could ever fit the budget by itself."""
        return (self.cpu_milli <= budget.cpu_milli
                and self.memory_mb <= budget.memory_mb
                and budget.slots >= 1
                and self.duration_s <= budget.time_window_s)


@dataclass(frozen=True)
class AdmissionDecision:
    """One scheduler decision: admitted, or deferred with reasons."""

    work_id: str
    decision: str  # admitted | deferred
    binding_constraints: Tuple[str, ...]
    primary_constraint: Optional[str]
    fits_alone: bool
    explanation: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "work_id": self.work_id,
            "decision": self.decision,
            "binding_constraints": list(self.binding_constraints),
            "primary_constraint": self.primary_constraint,
            "fits_alone": self.fits_alone,
            "explanation": self.explanation,
        }


@dataclass(frozen=True)
class SchedulePlan:
    """The full, deterministic outcome of one schedule_work call."""

    budget: ResourceBudget
    decisions: Tuple[AdmissionDecision, ...]
    admitted_ids: Tuple[str, ...]
    deferred_ids: Tuple[str, ...]
    used_cpu_milli: int
    used_memory_mb: int
    used_slots: int

    def decision_for(self, work_id: str) -> AdmissionDecision:
        for decision in self.decisions:
            if decision.work_id == work_id:
                return decision
        raise UnknownWorkItemError(
            f"no decision for {work_id!r} in this plan")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "schema": SCHEDULER_SCHEMA,
            "budget": {
                "cpu_milli": self.budget.cpu_milli,
                "memory_mb": self.budget.memory_mb,
                "slots": self.budget.slots,
                "time_window_s": self.budget.time_window_s,
            },
            "decisions": [d.to_dict() for d in self.decisions],
            "admitted_ids": list(self.admitted_ids),
            "deferred_ids": list(self.deferred_ids),
            "used": {"cpu_milli": self.used_cpu_milli,
                     "memory_mb": self.used_memory_mb,
                     "slots": self.used_slots},
        }


def _evaluation_order(items: List[WorkItem]) -> List[WorkItem]:
    """The one deterministic order: priority desc, sequence, id."""
    return sorted(items,
                  key=lambda it: (-it.priority, it.sequence, it.work_id))


def _binding_constraints(item: WorkItem, budget: ResourceBudget,
                         used_cpu: int, used_mem: int,
                         used_slots: int) -> Tuple[str, ...]:
    """Every constraint the item breaks against remaining capacity,
    in the fixed cpu/memory/slots/time order."""
    binding = []
    if used_cpu + item.cpu_milli > budget.cpu_milli:
        binding.append("cpu")
    if used_mem + item.memory_mb > budget.memory_mb:
        binding.append("memory")
    if used_slots + 1 > budget.slots:
        binding.append("slots")
    if item.duration_s > budget.time_window_s:
        binding.append("time")
    return tuple(binding)


def _explain(item: WorkItem, budget: ResourceBudget, binding,
             used_cpu: int, used_mem: int, used_slots: int) -> str:
    parts = []
    if "cpu" in binding:
        parts.append(
            f"cpu needs {item.cpu_milli} milli with "
            f"{budget.cpu_milli - used_cpu} of {budget.cpu_milli} free")
    if "memory" in binding:
        parts.append(
            f"memory needs {item.memory_mb} MiB with "
            f"{budget.memory_mb - used_mem} of {budget.memory_mb} free")
    if "slots" in binding:
        parts.append(
            f"slots needs 1 with {budget.slots - used_slots} of "
            f"{budget.slots} free")
    if "time" in binding:
        parts.append(
            f"time needs {item.duration_s}s beyond the "
            f"{budget.time_window_s}s window")
    return "; ".join(parts)


def schedule_work(items: List[WorkItem],
                  budget: ResourceBudget) -> SchedulePlan:
    """Admit work against a budget, deterministically and openly.

    Pure function: same items and budget always give the same plan.
    Every item is decided exactly once; a deferred item names its
    binding constraint(s) and is never dropped from the plan.
    """
    if not isinstance(budget, ResourceBudget):
        raise MalformedBudgetError(
            f"budget must be a ResourceBudget, got "
            f"{type(budget).__name__}")
    items = list(items)
    if len(items) > MAX_ITEMS:
        raise UnboundedBudgetError(
            f"{len(items)} items exceeds the hard cap {MAX_ITEMS}")
    seen = set()
    for item in items:
        if not isinstance(item, WorkItem):
            raise MalformedWorkItemError(
                f"items must be WorkItem records, got "
                f"{type(item).__name__}")
        if item.work_id in seen:
            raise DuplicateWorkItemError(
                f"work_id {item.work_id!r} appears twice; one id "
                f"names one unit of work")
        seen.add(item.work_id)
    used_cpu = used_mem = used_slots = 0
    decisions: List[AdmissionDecision] = []
    admitted: List[str] = []
    deferred: List[str] = []
    for item in _evaluation_order(items):
        binding = _binding_constraints(item, budget, used_cpu,
                                       used_mem, used_slots)
        if not binding:
            used_cpu += item.cpu_milli
            used_mem += item.memory_mb
            used_slots += 1
            admitted.append(item.work_id)
            decisions.append(AdmissionDecision(
                work_id=item.work_id, decision="admitted",
                binding_constraints=(), primary_constraint=None,
                fits_alone=True,
                explanation=(
                    f"admitted: fits with {budget.cpu_milli - used_cpu} "
                    f"cpu milli, {budget.memory_mb - used_mem} MiB and "
                    f"{budget.slots - used_slots} slots to spare")))
        else:
            deferred.append(item.work_id)
            fits = item.fits_alone(budget)
            decisions.append(AdmissionDecision(
                work_id=item.work_id, decision="deferred",
                binding_constraints=binding,
                primary_constraint=binding[0], fits_alone=fits,
                explanation=(
                    "deferred: " + _explain(item, budget, binding,
                                            used_cpu, used_mem,
                                            used_slots)
                    + ("; fits this budget alone, so it is queued "
                       "behind admitted work" if fits else
                       "; cannot fit this budget even alone"))))
    return SchedulePlan(
        budget=budget, decisions=tuple(decisions),
        admitted_ids=tuple(admitted), deferred_ids=tuple(deferred),
        used_cpu_milli=used_cpu, used_memory_mb=used_mem,
        used_slots=used_slots)


class Scheduler:
    """Stateful queue over schedule_work's rules for live work.

    ``submit`` admits an item if it fits alongside the currently
    admitted set, else queues it (deferred, never dropped).
    ``complete`` frees a finished item and re-evaluates the queue in
    deterministic order, returning the decisions it promoted.
    """

    def __init__(self, budget: ResourceBudget) -> None:
        if not isinstance(budget, ResourceBudget):
            raise MalformedBudgetError(
                f"budget must be a ResourceBudget, got "
                f"{type(budget).__name__}")
        self._budget = budget
        self._admitted: Dict[str, WorkItem] = {}
        self._queue: List[WorkItem] = []

    @property
    def budget(self) -> ResourceBudget:
        return self._budget

    def admitted_ids(self) -> Tuple[str, ...]:
        return tuple(sorted(self._admitted))

    def queued_ids(self) -> Tuple[str, ...]:
        return tuple(it.work_id
                     for it in _evaluation_order(self._queue))

    def _usage(self) -> Tuple[int, int, int]:
        return (sum(it.cpu_milli for it in self._admitted.values()),
                sum(it.memory_mb for it in self._admitted.values()),
                len(self._admitted))

    def _decide(self, item: WorkItem, used_cpu: int, used_mem: int,
                used_slots: int) -> AdmissionDecision:
        binding = _binding_constraints(item, self._budget, used_cpu,
                                       used_mem, used_slots)
        if not binding:
            return AdmissionDecision(
                work_id=item.work_id, decision="admitted",
                binding_constraints=(), primary_constraint=None,
                fits_alone=True,
                explanation=(
                    f"admitted: fits with "
                    f"{self._budget.cpu_milli - used_cpu - item.cpu_milli} "
                    f"cpu milli, "
                    f"{self._budget.memory_mb - used_mem - item.memory_mb} "
                    f"MiB and {self._budget.slots - used_slots - 1} "
                    f"slots to spare"))
        fits = item.fits_alone(self._budget)
        return AdmissionDecision(
            work_id=item.work_id, decision="deferred",
            binding_constraints=binding, primary_constraint=binding[0],
            fits_alone=fits,
            explanation=(
                "deferred: " + _explain(item, self._budget, binding,
                                        used_cpu, used_mem, used_slots)
                + ("; fits this budget alone, so it is queued "
                   "behind admitted work" if fits else
                   "; cannot fit this budget even alone")))

    def submit(self, item: WorkItem) -> AdmissionDecision:
        """Admit against CURRENT seats only: an admitted item is
        never displaced by a later, higher-priority arrival -- the
        arrival queues instead.  No over-admission is possible."""
        if not isinstance(item, WorkItem):
            raise MalformedWorkItemError(
                f"item must be a WorkItem, got "
                f"{type(item).__name__}")
        if item.work_id in self._admitted or any(
                q.work_id == item.work_id for q in self._queue):
            raise DuplicateWorkItemError(
                f"work_id {item.work_id!r} is already admitted or "
                f"queued")
        decision = self._decide(item, *self._usage())
        if decision.decision == "admitted":
            self._admitted[item.work_id] = item
        else:
            self._queue.append(item)
        return decision

    def complete(self, work_id: str) -> Tuple[AdmissionDecision, ...]:
        if work_id not in self._admitted:
            raise UnknownWorkItemError(
                f"cannot complete {work_id!r}: it is not admitted "
                f"(unknown or still queued)")
        del self._admitted[work_id]
        used_cpu, used_mem, used_slots = self._usage()
        promoted: List[AdmissionDecision] = []
        still_queued: List[WorkItem] = []
        for item in _evaluation_order(self._queue):
            decision = self._decide(item, used_cpu, used_mem,
                                    used_slots)
            if decision.decision == "admitted":
                self._admitted[item.work_id] = item
                used_cpu += item.cpu_milli
                used_mem += item.memory_mb
                used_slots += 1
                promoted.append(decision)
            else:
                still_queued.append(item)
        self._queue = still_queued
        return tuple(promoted)


@dataclass(frozen=True)
class EvidenceClaim:
    """One work item's evidence-backed verdict on a subject."""

    claim_id: str
    work_id: str
    subject: str
    verdict: str
    evidence_status: str
    evidence_ids: Tuple[str, ...]
    confidence: float = 0.0

    def __post_init__(self) -> None:
        if not isinstance(self.claim_id, str) \
                or not _CLAIM_RE.match(self.claim_id):
            raise MalformedClaimError(
                f"claim_id {self.claim_id!r} is not a well-formed "
                f"claim id (claim-...)")
        if not isinstance(self.work_id, str) \
                or not _WORK_RE.match(self.work_id):
            raise MalformedClaimError(
                f"work_id {self.work_id!r} is not a well-formed "
                f"work id (work-...)")
        if not isinstance(self.subject, str) or not self.subject:
            raise MalformedClaimError("subject must be non-empty")
        if not isinstance(self.verdict, str) \
                or not self.verdict.strip():
            raise MalformedClaimError("verdict must be non-empty")
        object.__setattr__(self, "verdict",
                           self.verdict.strip().lower())
        evidence_rank(self.evidence_status)
        if isinstance(self.evidence_ids, str) or not isinstance(
                self.evidence_ids, (list, tuple)):
            raise MalformedClaimError(
                "evidence_ids must be a list of evidence ids")
        ids = tuple(self.evidence_ids)
        if not ids:
            raise MalformedClaimError(
                "an evidence-backed claim needs at least one "
                "evidence id; a verdict with no evidence behind it "
                "cannot enter arbitration")
        for ev in ids:
            if not isinstance(ev, str) or not _EV_RE.match(ev):
                raise MalformedClaimError(
                    f"evidence id {ev!r} is not well-formed (ev-...)")
        if len(set(ids)) != len(ids):
            raise MalformedClaimError(
                "evidence_ids must not contain duplicates")
        object.__setattr__(self, "evidence_ids", ids)
        confidence = _check_number(self.confidence, "confidence",
                                   MalformedClaimError)
        if not 0.0 <= confidence <= 1.0:
            raise MalformedClaimError(
                f"confidence must be in [0, 1], got {confidence}")
        object.__setattr__(self, "confidence", confidence)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "claim_id": self.claim_id, "work_id": self.work_id,
            "subject": self.subject, "verdict": self.verdict,
            "evidence_status": self.evidence_status,
            "evidence_ids": list(self.evidence_ids),
            "confidence": self.confidence,
        }


@dataclass(frozen=True)
class ArbitrationRuling:
    """A typed ruling: winner (if any), reasons, preserved evidence."""

    outcome: str  # agree | upheld-first | upheld-second | unresolved
    subject: str
    first: EvidenceClaim
    second: EvidenceClaim
    winner_work_id: Optional[str]
    loser_work_id: Optional[str]
    reason: str
    first_rank: int
    second_rank: int
    losing_evidence: Tuple[str, ...]
    preserved_evidence: Tuple[str, ...]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "schema": SCHEDULER_SCHEMA, "outcome": self.outcome,
            "subject": self.subject,
            "first": self.first.to_dict(),
            "second": self.second.to_dict(),
            "winner_work_id": self.winner_work_id,
            "loser_work_id": self.loser_work_id,
            "reason": self.reason,
            "first_rank": self.first_rank,
            "second_rank": self.second_rank,
            "losing_evidence": list(self.losing_evidence),
            "preserved_evidence": list(self.preserved_evidence),
        }


def arbitrate_claims(first: EvidenceClaim,
                     second: EvidenceClaim) -> ArbitrationRuling:
    """Rule on two claims about the same subject.

    Order of weighing (never confidence first): (1) agreement needs
    no ruling; (2) the higher banked evidence-ladder rung wins;
    (3) at the same rung, more distinct evidence ids win; (4) a
    full tie is unresolved and goes to a human -- confidence is
    recorded on the claims and named in the reason when ignored,
    but it never decides a ruling on its own.
    """
    for claim in (first, second):
        if not isinstance(claim, EvidenceClaim):
            raise MalformedClaimError(
                f"claims must be EvidenceClaim records, got "
                f"{type(claim).__name__}")
    if first.subject != second.subject:
        raise ArbitrationError(
            f"cannot arbitrate claims about different subjects "
            f"({first.subject!r} vs {second.subject!r})")
    if first.claim_id == second.claim_id:
        raise ArbitrationError(
            f"claim {first.claim_id!r} cannot arbitrate against "
            f"itself")
    rank_first = evidence_rank(first.evidence_status)
    rank_second = evidence_rank(second.evidence_status)
    preserved = tuple(dict.fromkeys(
        list(first.evidence_ids) + list(second.evidence_ids)))
    if first.verdict == second.verdict:
        return ArbitrationRuling(
            outcome="agree", subject=first.subject, first=first,
            second=second, winner_work_id=None, loser_work_id=None,
            reason=(
                f"both claims return verdict {first.verdict!r}; "
                f"there is no conflict to arbitrate"),
            first_rank=rank_first, second_rank=rank_second,
            losing_evidence=(), preserved_evidence=preserved)
    winner: Optional[EvidenceClaim] = None
    loser: Optional[EvidenceClaim] = None
    outcome = "unresolved"
    if rank_first != rank_second:
        if rank_first > rank_second:
            winner, loser, outcome = first, second, "upheld-first"
        else:
            winner, loser, outcome = second, first, "upheld-second"
        reason = (
            f"conflicting verdicts {first.verdict!r} vs "
            f"{second.verdict!r}: {winner.evidence_status!r} "
            f"(ladder rank {max(rank_first, rank_second)}) outranks "
            f"{loser.evidence_status!r} (rank "
            f"{min(rank_first, rank_second)}); confidence "
            f"({first.confidence} vs {second.confidence}) was not "
            f"used -- the ladder decides before confidence is read")
    elif len(first.evidence_ids) != len(second.evidence_ids):
        if len(first.evidence_ids) > len(second.evidence_ids):
            winner, loser, outcome = first, second, "upheld-first"
        else:
            winner, loser, outcome = second, first, "upheld-second"
        reason = (
            f"conflicting verdicts at the same ladder rung "
            f"{first.evidence_status!r} (rank {rank_first}): the "
            f"claim backed by more distinct evidence prevails "
            f"({len(first.evidence_ids)} vs "
            f"{len(second.evidence_ids)} evidence ids); confidence "
            f"was not used as the deciding weight")
    else:
        reason = (
            f"conflicting verdicts {first.verdict!r} vs "
            f"{second.verdict!r} tie on the ladder "
            f"({first.evidence_status!r}, rank {rank_first}) and on "
            f"evidence breadth ({len(first.evidence_ids)} ids each); "
            f"confidence ({first.confidence} vs {second.confidence}) "
            f"never decides a ruling on its own, so this conflict is "
            f"unresolved and needs human review; both claims and "
            f"all their evidence are preserved in this ruling")
    return ArbitrationRuling(
        outcome=outcome, subject=first.subject, first=first,
        second=second,
        winner_work_id=winner.work_id if winner else None,
        loser_work_id=loser.work_id if loser else None,
        reason=reason, first_rank=rank_first,
        second_rank=rank_second,
        losing_evidence=tuple(loser.evidence_ids) if loser else (),
        preserved_evidence=preserved)
