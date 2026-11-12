# SPDX-License-Identifier: GPL-2.0-only
"""LIF-0703 resource-aware scheduler + evidentiary arbitration tests.

Scope: fixture work items and claims only
(tests/fixtures/lif0703/cases.json plus in-code records).  No live
host is scheduled, no process runs, no real work executes.

Pinned behaviour: admission never exceeds the budget in any
dimension; every item is decided exactly once; a deferred item
names its binding constraint(s) and whether it could ever fit
alone; evaluation order is deterministic (priority, sequence, id)
so input order cannot change the admitted set; the stateful
Scheduler never displaces an admitted seat and promotes queued
work on completion; arbitration weighs the banked LIF-0305 ladder
first and evidence breadth second, and NEVER decides by confidence
alone -- a full tie is unresolved with all evidence preserved.

The mutated-ruling test is this slice's NEGATIVE CONTROL: the
exact claim pair the ladder decides for the low-confidence claim
is re-run with the winner's evidence_status forged down to
``idea`` and its confidence raised to 1.0, and the ruling must
flip/unresolve -- an arbitrator that still upholds it is reading
confidence, not evidence.
"""
import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from lifthrasir import scheduler  # noqa: E402
from lifthrasir.hypotheses import EVIDENCE_LADDER  # noqa: E402

FIXTURE = REPO / "tests" / "fixtures" / "lif0703" / "cases.json"


def fixture():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def budget():
    return scheduler.ResourceBudget(**fixture()["budget"])


def items_of(scenario):
    return [scheduler.WorkItem(**row)
            for row in fixture()["scheduling"][scenario]["items"]]


def claim_of(row):
    return scheduler.EvidenceClaim(
        claim_id=row["claim_id"], work_id=row["work_id"],
        subject=row["subject"], verdict=row["verdict"],
        evidence_status=row["evidence_status"],
        evidence_ids=tuple(row["evidence_ids"]),
        confidence=row["confidence"])


# -- scheduling: fixture scenarios ------------------------------------

def test_mixed_load_fixture_admits_and_defers_as_declared():
    data = fixture()["scheduling"]["mixed-load"]
    plan = scheduler.schedule_work(items_of("mixed-load"), budget())
    assert sorted(plan.admitted_ids) == sorted(data["expected_admitted"])
    assert set(plan.deferred_ids) == set(data["expected_deferred"])
    for work_id, want in data["expected_deferred"].items():
        decision = plan.decision_for(work_id)
        assert decision.decision == "deferred"
        assert decision.primary_constraint == want["primary"]
        assert decision.fits_alone is want["fits_alone"]
        assert decision.primary_constraint in decision.binding_constraints
        assert decision.explanation  # every deferral explains itself
    assert plan.used_cpu_milli <= plan.budget.cpu_milli
    assert plan.used_memory_mb <= plan.budget.memory_mb
    assert plan.used_slots <= plan.budget.slots


def test_all_fit_fixture_admits_everything():
    plan = scheduler.schedule_work(items_of("all-fit"), budget())
    assert sorted(plan.admitted_ids) == ["work-one", "work-two"]
    assert plan.deferred_ids == ()


def test_memory_bound_fixture_names_memory():
    plan = scheduler.schedule_work(items_of("memory-bound"), budget())
    decision = plan.decision_for("work-fat-b")
    assert decision.primary_constraint == "memory"
    assert decision.fits_alone is True


def test_every_item_decided_exactly_once_and_never_over_admitted():
    items = items_of("mixed-load")
    plan = scheduler.schedule_work(items, budget())
    decided = [d.work_id for d in plan.decisions]
    assert sorted(decided) == sorted(i.work_id for i in items)
    assert len(decided) == len(set(decided))
    admitted = [i for i in items if i.work_id in plan.admitted_ids]
    assert sum(i.cpu_milli for i in admitted) == plan.used_cpu_milli
    assert sum(i.memory_mb for i in admitted) == plan.used_memory_mb


def test_evaluation_is_deterministic_under_input_shuffle():
    items = items_of("mixed-load")
    forward = scheduler.schedule_work(items, budget())
    backward = scheduler.schedule_work(list(reversed(items)), budget())
    assert forward.admitted_ids == backward.admitted_ids
    assert forward.deferred_ids == backward.deferred_ids
    again = scheduler.schedule_work(items_of("mixed-load"), budget())
    assert again.to_dict() == forward.to_dict()


def test_priority_then_sequence_then_id_order():
    tight = scheduler.ResourceBudget(cpu_milli=1000, memory_mb=1024,
                                     slots=1, time_window_s=60)
    low = scheduler.WorkItem("work-aaa", "generic", 500, 100, 10,
                             priority=10, sequence=0)
    high = scheduler.WorkItem("work-zzz", "generic", 500, 100, 10,
                              priority=90, sequence=9)
    plan = scheduler.schedule_work([low, high], tight)
    assert plan.admitted_ids == ("work-zzz",)
    assert plan.decision_for("work-aaa").primary_constraint == "slots"


def test_never_fitting_item_is_deferred_not_dropped():
    plan = scheduler.schedule_work(items_of("mixed-load"), budget())
    huge = plan.decision_for("work-huge")
    assert huge.decision == "deferred" and huge.fits_alone is False
    assert "cpu" in huge.binding_constraints


def test_duplicate_work_ids_refused():
    item = items_of("all-fit")[0]
    with pytest.raises(scheduler.DuplicateWorkItemError):
        scheduler.schedule_work([item, item], budget())


def test_malformed_items_and_budgets_refused_by_name():
    with pytest.raises(scheduler.MalformedWorkItemError):
        scheduler.WorkItem("nope", "generic", 100, 100, 10)
    with pytest.raises(scheduler.MalformedWorkItemError):
        scheduler.WorkItem("work-x", "bogus-kind", 100, 100, 10)
    with pytest.raises(scheduler.MalformedWorkItemError):
        scheduler.WorkItem("work-x", "generic", 0, 100, 10)
    with pytest.raises(scheduler.MalformedBudgetError):
        scheduler.ResourceBudget(0, 1024, 1, 60)
    with pytest.raises(scheduler.UnboundedBudgetError):
        scheduler.ResourceBudget(scheduler.MAX_CPU_MILLI + 1, 1024, 1, 60)
    with pytest.raises(scheduler.UnboundedBudgetError):
        scheduler.WorkItem("work-x", "generic", 100, 100,
                           scheduler.MAX_DURATION_S + 1)


# -- scheduling: stateful Scheduler -----------------------------------

def test_scheduler_queues_then_promotes_on_complete():
    sched = scheduler.Scheduler(budget())
    first = scheduler.WorkItem("work-first", "reproducer", 2000, 1024,
                               60, priority=80, sequence=0)
    second = scheduler.WorkItem("work-second", "verifier", 2000, 1024,
                                60, priority=70, sequence=1)
    assert sched.submit(first).decision == "admitted"
    deferred = sched.submit(second)
    assert deferred.decision == "deferred"
    assert deferred.primary_constraint == "cpu"
    assert sched.queued_ids() == ("work-second",)
    promoted = sched.complete("work-first")
    assert [d.work_id for d in promoted] == ["work-second"]
    assert sched.admitted_ids() == ("work-second",)
    assert sched.queued_ids() == ()


def test_scheduler_never_displaces_an_admitted_seat():
    sched = scheduler.Scheduler(budget())
    seated = scheduler.WorkItem("work-seated", "generic", 2000, 4096,
                                60, priority=10, sequence=0)
    bully = scheduler.WorkItem("work-bully", "generic", 2000, 4096,
                               60, priority=99, sequence=1)
    assert sched.submit(seated).decision == "admitted"
    assert sched.submit(bully).decision == "deferred"
    assert sched.admitted_ids() == ("work-seated",)


def test_scheduler_complete_unknown_or_queued_refused():
    sched = scheduler.Scheduler(budget())
    with pytest.raises(scheduler.UnknownWorkItemError):
        sched.complete("work-ghost")
    big = scheduler.WorkItem("work-stuck", "generic", 9999, 100, 10)
    assert sched.submit(big).decision == "deferred"
    with pytest.raises(scheduler.UnknownWorkItemError):
        sched.complete("work-stuck")  # queued is not admitted
    with pytest.raises(scheduler.DuplicateWorkItemError):
        sched.submit(big)


# -- arbitration -------------------------------------------------------

def test_ladder_beats_confidence_fixture():
    data = fixture()["arbitration"]["ladder-beats-confidence"]
    ruling = scheduler.arbitrate_claims(claim_of(data["first"]),
                                        claim_of(data["second"]))
    assert ruling.outcome == data["expected_outcome"]
    assert ruling.winner_work_id == data["expected_winner"]
    assert ruling.loser_work_id == data["expected_loser"]
    # The loser was MORE confident (0.99 vs 0.4) and still lost:
    # the ladder, not confidence, decided.
    assert ruling.second.confidence > ruling.first.confidence
    assert "confidence" in ruling.reason


def test_same_rung_decided_by_evidence_breadth_fixture():
    data = fixture()["arbitration"]["same-rung-breadth"]
    ruling = scheduler.arbitrate_claims(claim_of(data["first"]),
                                        claim_of(data["second"]))
    assert ruling.outcome == "upheld-second"
    assert ruling.winner_work_id == "work-verify-a"


def test_full_tie_is_unresolved_despite_confidence_gap():
    data = fixture()["arbitration"]["full-tie-unresolved"]
    ruling = scheduler.arbitrate_claims(claim_of(data["first"]),
                                        claim_of(data["second"]))
    assert ruling.outcome == "unresolved"
    assert ruling.winner_work_id is None
    assert ruling.first.confidence == 0.95  # gap recorded, not used
    assert "human review" in ruling.reason


def test_agreeing_verdicts_need_no_ruling():
    data = fixture()["arbitration"]["agreeing-verdicts"]
    ruling = scheduler.arbitrate_claims(claim_of(data["first"]),
                                        claim_of(data["second"]))
    assert ruling.outcome == "agree"
    assert ruling.losing_evidence == ()
    assert set(ruling.preserved_evidence) == {"ev-note-1", "ev-run-1"}


def test_losing_evidence_is_preserved_never_deleted():
    data = fixture()["arbitration"]["ladder-beats-confidence"]
    ruling = scheduler.arbitrate_claims(claim_of(data["first"]),
                                        claim_of(data["second"]))
    assert ruling.losing_evidence == ("ev-note-1", "ev-note-2")
    for ev in ("ev-run-1", "ev-note-1", "ev-note-2"):
        assert ev in ruling.preserved_evidence
    assert ruling.second.to_dict()["evidence_ids"] == ["ev-note-1",
                                                       "ev-note-2"]
    assert ruling.to_dict()["losing_evidence"] == ["ev-note-1",
                                                   "ev-note-2"]


def test_arbitration_refusals_are_named():
    data = fixture()["arbitration"]["ladder-beats-confidence"]
    first = claim_of(data["first"])
    other_subject = scheduler.EvidenceClaim(
        "claim-other", "work-x", "hyp-other", "supported",
        "reproducer", ("ev-a",))
    with pytest.raises(scheduler.ArbitrationError):
        scheduler.arbitrate_claims(first, other_subject)
    with pytest.raises(scheduler.ArbitrationError):
        scheduler.arbitrate_claims(first, first)
    with pytest.raises(scheduler.MalformedClaimError):
        scheduler.EvidenceClaim("claim-bad", "work-x", "s", "v",
                                "not-a-rung", ("ev-a",))
    with pytest.raises(scheduler.MalformedClaimError):
        scheduler.EvidenceClaim("claim-bad", "work-x", "s", "v",
                                "reproducer", ())
    with pytest.raises(scheduler.MalformedClaimError):
        scheduler.EvidenceClaim("claim-bad", "work-x", "s", "v",
                                "reproducer", ("ev-a",), confidence=2.0)


def test_evidence_rank_uses_the_banked_ladder_verbatim():
    assert scheduler.EVIDENCE_LADDER is EVIDENCE_LADDER
    assert scheduler.evidence_rank("idea") == 0
    assert scheduler.evidence_rank("upstream-accepted") == \
        len(EVIDENCE_LADDER) - 1
    with pytest.raises(scheduler.MalformedClaimError):
        scheduler.evidence_rank("verified-ish")


def test_negative_control_forged_status_must_not_uphold():
    """NEGATIVE CONTROL: same pair as ladder-beats-confidence, but
    the winner's rung is forged down to ``idea`` and its confidence
    raised to 1.0.  The ruling must NOT still uphold it."""
    data = fixture()["arbitration"]["ladder-beats-confidence"]
    forged = scheduler.EvidenceClaim(
        "claim-repro", "work-repro-a", "hyp-alpha", "supported",
        "idea", ("ev-run-1",), confidence=1.0)
    ruling = scheduler.arbitrate_claims(forged,
                                        claim_of(data["second"]))
    assert ruling.outcome != "upheld-first"
    assert ruling.winner_work_id != "work-repro-a"
