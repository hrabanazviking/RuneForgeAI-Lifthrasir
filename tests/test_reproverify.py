"""Tests for independent reproducer and verifier roles (LIF-0702).

Fixture workloads only: in-process callables.  No real reproducer
fleet, host service, model, or network is used.
"""
import dataclasses
import json
import pathlib
import sys

REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

import pytest

from lifthrasir import reproverify as rv

CASES = json.loads((REPO / "tests" / "fixtures" / "lif0702" / "cases.json").read_text())


def _task(**kw):
    base = dict(task_id="task-0702-1", claim="fixture fails on baseline",
                spec={"fixture": "synthetic-failure", "seed": 7},
                reproducer_actor="agent-repro", verifier_actor="agent-verify")
    base.update(kw)
    return rv.ReproductionTask(**base)


def _record(hid="hyp-0702-1"):
    return {
        "schema": "lifthrasir.hypothesis.v0.1", "schema_version": "0.1",
        "hypothesis_id": hid, "incident_id": "inc-0702-1",
        "claim": "the fixture service fails under load",
        "status": "proposed", "confidence": 0.5,
        "evidence_for": [], "evidence_against": [],
        "test_plan": "run the fixture reproducer",
        "evidence_status": "hypothesis",
        "created_at": "2026-11-12T00:00:00Z",
    }


def test_same_actor_both_roles_refused_before_any_run():
    ran = []
    task = _task(verifier_actor="agent-repro")
    with pytest.raises(rv.SeparationViolationError):
        rv.run_independent_check(task, lambda v: ran.append(1), lambda v: ran.append(1))
    assert ran == []


def test_malformed_ids_and_empty_claim_refused():
    with pytest.raises(rv.MalformedTaskError):
        rv.validate_task(_task(task_id="Task Bad"))
    with pytest.raises(rv.MalformedTaskError):
        rv.validate_task(_task(reproducer_actor="Bad Actor"))
    with pytest.raises(rv.MalformedTaskError):
        rv.validate_task(_task(claim="  "))
    with pytest.raises(rv.MalformedTaskError):
        rv.validate_task(_task(spec={"x": object()}))
    with pytest.raises(rv.MalformedTaskError):
        rv.validate_task("not-a-task")


def test_unbounded_claim_and_spec_refused():
    with pytest.raises(rv.UnboundedTaskError):
        rv.validate_task(_task(claim="x" * (rv.MAX_CLAIM_CHARS + 1)))
    with pytest.raises(rv.UnboundedTaskError):
        rv.validate_task(_task(spec={"blob": "y" * rv.MAX_SPEC_BYTES}))


def test_hypothesis_binding_validated_and_mismatch_refused():
    task = _task(hypothesis_id="hyp-0702-1", incident_id="inc-0702-1", hypothesis=_record())
    assert rv.validate_task(task) is task
    bad = _task(hypothesis_id="hyp-other-9", hypothesis=_record())
    with pytest.raises(rv.MalformedTaskError):
        rv.validate_task(bad)


def test_corroborated_and_refuted_paths():
    check = rv.run_independent_check(_task(), lambda v: True, lambda v: True)
    assert check.status == "corroborated" and check.ok
    assert check.verification.verdict == "confirmed"
    check2 = rv.run_independent_check(_task(), lambda v: False, lambda v: False)
    assert check2.status == "refuted" and check2.ok


def test_disagreement_is_disputed_never_confirmed():
    check = rv.run_independent_check(_task(), lambda v: True, lambda v: False)
    assert check.status == "disputed" and not check.ok
    assert check.verification.verdict == "contradicted"


def test_fixture_case_matrix():
    for case in CASES["cases"]:
        check = rv.run_independent_check(
            _task(), lambda v, r=case["repro"]: r, lambda v, r=case["verify"]: r)
        assert check.verification.verdict == case["verdict"], case["name"]
        assert check.status == case["status"], case["name"]


def test_verifier_is_blinded_no_actor_no_outcome_no_output():
    seen = {}
    def verifier(view):
        seen.update(view)
        return True
    rv.run_independent_check(_task(), lambda v: {"outcome": "reproduced", "output": {"secret": 1}}, verifier)
    assert "reproducer_actor" not in seen and "verifier_actor" not in seen
    assert "outcome" not in seen and "output" not in seen and "actor" not in seen
    assert seen["spec"] == {"fixture": "synthetic-failure", "seed": 7}
    assert seen["role"] == "verifier"


def test_blinded_view_shape_directly():
    view = rv.blinded_view(_task())
    assert set(view) == {"schema", "task_id", "task_digest", "claim", "spec", "hypothesis_id", "incident_id"}
    assert view["task_digest"] == _task().digest()


def test_seal_tamper_refused_and_verifier_never_runs():
    report = rv.run_reproduction(_task(), lambda v: True)
    tampered = dataclasses.replace(report, outcome="not-reproduced")
    ran = []
    with pytest.raises(rv.TamperedReportError):
        rv.run_verification(_task(), tampered, lambda v: ran.append(1))
    assert ran == []


def test_foreign_task_and_wrong_actor_reports_refused():
    report = rv.run_reproduction(_task(), lambda v: True)
    with pytest.raises(rv.TamperedReportError):
        rv.verify_seal(_task(task_id="task-0702-2"), report)
    forged = dataclasses.replace(report, actor="agent-verify")
    with pytest.raises(rv.SeparationViolationError):
        rv.verify_seal(_task(), forged)


def test_runner_exception_recorded_as_error_not_raised():
    def boom(view):
        raise RuntimeError("fixture explosion")
    check = rv.run_independent_check(_task(), boom, lambda v: True)
    assert check.reproduction.outcome == "error"
    assert "fixture explosion" in check.reproduction.error
    assert check.status == "inconclusive"
    check2 = rv.run_independent_check(_task(), lambda v: True, boom)
    assert check2.verification.verifier_outcome == "error"
    assert check2.status == "inconclusive"


def test_unrecognised_and_oversize_runner_results_become_error():
    check = rv.run_independent_check(_task(), lambda v: 42, lambda v: True)
    assert check.reproduction.outcome == "error"
    big = {"outcome": "reproduced", "output": {"blob": "z" * rv.MAX_OUTPUT_BYTES}}
    check2 = rv.run_independent_check(_task(), lambda v: big, lambda v: True)
    assert check2.reproduction.outcome == "error"


def test_dict_and_bool_and_string_results_normalised():
    check = rv.run_independent_check(
        _task(), lambda v: {"outcome": "reproduced", "output": {"rc": 1}},
        lambda v: "reproduced")
    assert check.status == "corroborated"
    assert check.reproduction.output == {"rc": 1}


def test_digests_deterministic_across_runs():
    a = rv.run_independent_check(_task(), lambda v: True, lambda v: True)
    b = rv.run_independent_check(_task(), lambda v: True, lambda v: True)
    assert a.digest == b.digest and a.reproduction.seal == b.reproduction.seal
    c = rv.run_independent_check(_task(), lambda v: True, lambda v: False)
    assert c.digest != a.digest


def test_evidence_records_shape_bearings_and_hypothesis_binding():
    task = _task(hypothesis_id="hyp-0702-1", incident_id="inc-0702-1", hypothesis=_record())
    check = rv.run_independent_check(task, lambda v: True, lambda v: True)
    records = check.evidence_records()
    assert len(records) == 3
    assert [r["role"] for r in records] == ["reproducer", "verifier", "comparison"]
    assert all(r["hypothesis_id"] == "hyp-0702-1" for r in records)
    assert all(r["evidence_id"].startswith("ev-") for r in records)
    assert [r["bearing"] for r in records] == ["for", "for", "for"]
    disputed = rv.run_independent_check(_task(), lambda v: True, lambda v: False)
    assert disputed.evidence_records()[2]["bearing"] == "neither"


def test_compare_outcomes_rejects_unknown_outcome():
    with pytest.raises(rv.MalformedTaskError):
        rv.compare_outcomes("maybe", "reproduced")


def test_non_callable_runner_recorded_error():
    check = rv.run_independent_check(_task(), None, lambda v: True)
    assert check.reproduction.outcome == "error"
