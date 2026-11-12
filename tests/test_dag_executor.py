"""Tests for the Replicater DAG executor (LIF-0701).

Fixture workloads only: in-process functions and the LIF-0601
mock provider.  No real model, host service, or network is used.
"""
import pathlib
import sys
import time

REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO.joinpath(chr(115)+chr(114)+chr(99))))

import pytest

from lifthrasir import dagexecutor as dag
from lifthrasir import modelprovider as mp

ROOT = pathlib.Path(__file__).resolve().parents[1]


def _record(hid="hyp-dag-1", status="proposed"):
    return {
        "schema": "lifthrasir.hypothesis.v0.1",
        "schema_version": "0.1",
        "hypothesis_id": hid,
        "incident_id": "inc-dag-1",
        "claim": "the fixture service fails under load",
        "status": status,
        "confidence": 0.5,
        "evidence_for": [],
        "evidence_against": [],
        "test_plan": "run the fixture reproducer",
        "evidence_status": "hypothesis",
        "created_at": "2026-11-12T00:00:00Z",
    }


def _add(payload, deps):
    return (payload or 0) + sum(deps.values())


def test_linear_chain_runs_in_dependency_order():
    nodes = [
        dag.callable_node("c", _add, depends_on=("b",), payload=1),
        dag.callable_node("a", lambda p, d: 1),
        dag.callable_node("b", _add, depends_on=("a",), payload=10),
    ]
    report = dag.run_dag(nodes)
    assert report.ok
    assert report.result("b").value == 11
    assert report.result("c").value == 12
    assert report.counts() == {"succeeded": 3, "failed": 0,
                               "timed-out": 0, "skipped": 0}


def test_diamond_and_parallel_independents():
    nodes = [
        dag.callable_node("root", lambda p, d: 2),
        dag.callable_node("left", _add, depends_on=("root",), payload=3),
        dag.callable_node("right", _add, depends_on=("root",), payload=5),
        dag.callable_node("join", _add, depends_on=("left", "right")),
    ]
    report = dag.run_dag(nodes)
    assert report.ok and report.result("join").value == 12


def test_failure_isolates_siblings_and_skips_dependents_explicitly():
    def boom(payload, deps):
        raise RuntimeError("fixture explosion")

    nodes = [
        dag.callable_node("bad", boom),
        dag.callable_node("child", _add, depends_on=("bad",)),
        dag.callable_node("grandchild", _add, depends_on=("child",)),
        dag.callable_node("sibling", lambda p, d: "untouched"),
    ]
    report = dag.run_dag(nodes)
    assert report.result("bad").status == "failed"
    assert "fixture explosion" in report.result("bad").error
    assert report.result("sibling").status == "succeeded"
    assert report.result("sibling").value == "untouched"
    child = report.result("child")
    assert child.status == "skipped" and child.skipped_due_to == ("bad",)
    grandchild = report.result("grandchild")
    assert grandchild.status == "skipped"
    assert grandchild.skipped_due_to == ("child",)
    assert report.counts() == {"succeeded": 1, "failed": 1,
                                "timed-out": 0, "skipped": 2}


def test_timeout_is_isolated_and_sibling_still_runs():
    def slow(payload, deps):
        time.sleep(1.0)
        return "late"

    nodes = [
        dag.callable_node("slow", slow, timeout_s=0.1),
        dag.callable_node("fast", lambda p, d: "quick"),
        dag.callable_node("after-slow", _add, depends_on=("slow",)),
    ]
    report = dag.run_dag(nodes)
    assert report.result("slow").status == "timed-out"
    assert report.result("fast").status == "succeeded"
    assert report.result("after-slow").status == "skipped"


def test_cycle_and_self_dependency_refused_before_any_run():
    ran = []
    nodes = [
        dag.callable_node("a", lambda p, d: ran.append(1),
                          depends_on=("b",)),
        dag.callable_node("b", lambda p, d: ran.append(1),
                          depends_on=("a",)),
    ]
    with pytest.raises(dag.CycleError):
        dag.run_dag(nodes)
    assert ran == []
    with pytest.raises(dag.CycleError):
        dag.run_dag([dag.callable_node("x", _add, depends_on=("x",))])


def test_unknown_dependency_and_duplicate_ids_refused():
    with pytest.raises(dag.UnknownDependencyError):
        dag.run_dag([dag.callable_node("a", _add, depends_on=("ghost",))])
    with pytest.raises(dag.DuplicateNodeError):
        dag.run_dag([dag.callable_node("a", _add),
                     dag.callable_node("a", _add)])
    with pytest.raises(dag.MalformedDagError):
        dag.run_dag([])


def test_bounds_are_enforced():
    with pytest.raises(dag.UnboundedDagError):
        dag.run_dag([dag.callable_node("a", _add, timeout_s=999.0)])
    with pytest.raises(dag.UnboundedDagError):
        dag.DagExecutor(max_workers=dag.MAX_WORKERS + 1)
    with pytest.raises(dag.UnboundedDagError):
        dag.run_dag([dag.callable_node("a", _add, resource_units=8)],
                    resource_budget=4)
    many = [dag.callable_node(f"n{i:02d}", _add)
            for i in range(dag.MAX_NODES + 1)]
    with pytest.raises(dag.UnboundedDagError):
        dag.run_dag(many)


def test_deterministic_digest_across_runs_with_jitter():
    def jitter(payload, deps):
        time.sleep(0.01 * (payload % 3))
        return payload * 2

    def build():
        return [dag.callable_node(f"n{i}", jitter, payload=i)
                for i in range(6)]

    first = dag.run_dag(build())
    second = dag.run_dag(build())
    assert first.digest == second.digest
    assert first.graph_digest == second.graph_digest
    assert [r.node_id for r in first.results] == sorted(
        r.node_id for r in first.results)
    assert first.as_dict()["results"] == second.as_dict()["results"]


def test_non_serialisable_result_fails_in_isolation():
    nodes = [
        dag.callable_node("weird", lambda p, d: object()),
        dag.callable_node("fine", lambda p, d: 7),
    ]
    report = dag.run_dag(nodes)
    assert report.result("weird").status == "failed"
    assert report.result("fine").value == 7


def test_hypothesis_node_validates_record_and_emits_evidence():
    nodes = [
        dag.hypothesis_node("t1", _record(), lambda p, d: {"ran": True}),
        dag.hypothesis_node("t2", _record("hyp-dag-2"),
                            lambda p, d: 1 / 0),
    ]
    report = dag.run_dag(nodes)
    records = report.evidence_records()
    assert len(records) == 2
    by_node = {r["node_id"]: r for r in records}
    assert by_node["t1"]["bearing"] == "for"
    assert by_node["t1"]["hypothesis_id"] == "hyp-dag-1"
    assert by_node["t2"]["bearing"] == "against"
    for rec in records:
        assert rec["evidence_id"].startswith("ev-")
        assert len(rec["evidence_id"]) == 19
        assert rec["schema"] == dag.EVIDENCE_SCHEMA
    # Deterministic: same graph, same evidence ids.
    again = dag.run_dag(nodes)
    assert [r["evidence_id"] for r in again.evidence_records()] == \
        [r["evidence_id"] for r in records]


def test_hypothesis_node_refuses_malformed_record():
    bad = _record()
    bad["status"] = "supported"  # supported with no evidence_for
    with pytest.raises(Exception):
        dag.run_dag([dag.hypothesis_node("t", bad, lambda p, d: 1)])


def test_skipped_hypothesis_node_is_evidence_of_nothing():
    nodes = [
        dag.callable_node("gate", lambda p, d: 1 / 0),
        dag.hypothesis_node("t", _record(), lambda p, d: 1,
                            depends_on=("gate",)),
    ]
    report = dag.run_dag(nodes)
    (rec,) = report.evidence_records()
    assert rec["outcome"] == "skipped" and rec["bearing"] == "neither"


def test_provider_node_uses_mock_and_failure_is_isolated():
    ok_req = mp.ModelRequest(task_id="task-dag-ok", prompt="hello fixture")
    abstain_req = mp.ModelRequest(task_id="task-dag-no",
                                  prompt="please [[abstain]]")
    nodes = [
        dag.provider_node("model-ok", ok_req),
        dag.provider_node("model-no", abstain_req),
        dag.callable_node("plain", lambda p, d: "still ran"),
    ]
    report = dag.run_dag(nodes, provider=mp.MockModelProvider())
    assert report.result("model-ok").status == "succeeded"
    assert report.result("model-ok").value["outcome"] == "completed"
    assert report.result("model-no").status == "failed"
    assert "abstained" in report.result("model-no").error
    assert report.result("plain").value == "still ran"


def test_provider_node_without_provider_fails_in_isolation():
    nodes = [
        dag.provider_node("model", mp.ModelRequest(
            task_id="task-dag-x", prompt="hi")),
        dag.callable_node("plain", lambda p, d: 1),
    ]
    report = dag.run_dag(nodes)
    assert report.result("model").status == "failed"
    assert report.result("plain").status == "succeeded"


def test_module_has_no_host_or_network_machinery():
    text = (ROOT / "src" / "lifthrasir" / "dagexecutor.py").read_text()
    for token in ("subprocess", "socket", "os.system", "urllib",
                  "requests", "shutil", "Popen"):
        assert token not in text, token
