"""LIF-0505: reversal and interrupted-operation tests.

Fixture state only: interruptions are simulated at named points
against an in-memory store plus a durable journal in tmp_path.
No real process is killed, signalled, or interrupted, and no
host state is touched.
"""
import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from lifthrasir.reversal import (
    DELETE,
    STEP_APPLIED,
    STEP_RECORDED,
    STEP_REVERSED,
    TXN_COMMITTED,
    TXN_REVERSED,
    AlreadyReversedError,
    DivergenceError,
    FixtureState,
    IrreversibleStepError,
    Journal,
    ManifestError,
    OperationRunner,
    SimulatedInterrupt,
    Step,
    TamperedManifestError,
    TransactionStateError,
)

ORIGINAL = {
    "service.demo.state": "stopped",
    "service.demo.port": 8080,
    "config.demo.timeout": 30,
}


def _steps():
    return [
        Step("s1", "service.demo.state", "running"),
        Step("s2", "service.demo.port", 9090),
        Step("s3", "config.demo.timeout", 60),
        Step("s4", "config.demo.new-key", "added"),
        Step("s5", "service.demo.port", DELETE),
    ]


def _planned(tmp_path):
    state = FixtureState(ORIGINAL)
    runner = OperationRunner(state, tmp_path / "undo.json")
    runner.plan("txn-demo-1", _steps())
    return state, runner


def test_clean_run_and_reverse_restores_exact_state(tmp_path):
    state, runner = _planned(tmp_path)
    original_digest = state.digest()
    runner.run()
    assert state.digest() != original_digest
    assert runner.manifest.status == TXN_COMMITTED
    runner.reverse()
    assert state.snapshot() == ORIGINAL
    assert state.digest() == original_digest
    assert runner.manifest.status == TXN_REVERSED
    assert all(e["status"] == STEP_REVERSED
               for e in runner.manifest.steps)


def test_reversal_keeps_manifest_in_plan_order(tmp_path):
    state, runner = _planned(tmp_path)
    runner.run()
    runner.reverse()
    journal = Journal(tmp_path / "undo.json").read()
    assert [e["step_id"] for e in journal.steps] == [
        "s1", "s2", "s3", "s4", "s5"]
    assert journal.status == TXN_REVERSED
    assert state.snapshot() == ORIGINAL


def test_recovery_reports_reversed_steps_newest_first(tmp_path):
    state, runner = _planned(tmp_path)
    with pytest.raises(SimulatedInterrupt):
        runner.run(after_steps=3)
    report = OperationRunner.recover(state, tmp_path / "undo.json")
    assert report["reversed_steps"] == ["s3", "s2", "s1"]
    assert report["skipped_steps"] == ["s5", "s4"]
    assert report["verified"] is True
    assert state.snapshot() == ORIGINAL


def test_interrupt_before_first_step_recovers_cleanly(tmp_path):
    state, runner = _planned(tmp_path)
    with pytest.raises(SimulatedInterrupt):
        runner.run(after_steps=0)
    assert state.snapshot() == ORIGINAL
    report = OperationRunner.recover(state, tmp_path / "undo.json")
    assert report["verified"] is True
    assert state.snapshot() == ORIGINAL


def test_interrupt_between_steps_then_fresh_runner_recovers(tmp_path):
    state, runner = _planned(tmp_path)
    with pytest.raises(SimulatedInterrupt):
        runner.run(after_steps=2)
    del runner
    report = OperationRunner.recover(state, tmp_path / "undo.json")
    assert report["restored_digest"] == report["original_digest"]
    assert state.snapshot() == ORIGINAL


def test_interrupt_after_apply_before_journal_recovers(tmp_path):
    state, runner = _planned(tmp_path)
    with pytest.raises(SimulatedInterrupt):
        runner.run(after_apply_of_step="s2")
    journal = Journal(tmp_path / "undo.json").read()
    by_id = {e["step_id"]: e for e in journal.steps}
    assert by_id["s2"]["status"] == STEP_RECORDED
    assert by_id["s1"]["status"] == STEP_APPLIED
    assert state.get("service.demo.port") == 9090
    report = OperationRunner.recover(state, tmp_path / "undo.json")
    assert report["verified"] is True
    assert state.snapshot() == ORIGINAL


def test_interrupt_before_commit_recovers_all_steps(tmp_path):
    state, runner = _planned(tmp_path)
    with pytest.raises(SimulatedInterrupt):
        runner.run(before_commit=True)
    journal = Journal(tmp_path / "undo.json").read()
    assert all(e["status"] == STEP_APPLIED for e in journal.steps)
    assert journal.status != TXN_COMMITTED
    report = OperationRunner.recover(state, tmp_path / "undo.json")
    assert report["reversed_steps"] == ["s5", "s4", "s3", "s2", "s1"]
    assert state.snapshot() == ORIGINAL


def test_interrupt_during_reversal_is_itself_recoverable(tmp_path):
    state, runner = _planned(tmp_path)
    runner.run()
    with pytest.raises(SimulatedInterrupt):
        runner.reverse(after_reversals=2)
    journal = Journal(tmp_path / "undo.json").read()
    statuses = {e["step_id"]: e["status"] for e in journal.steps}
    assert statuses["s5"] == STEP_REVERSED
    assert statuses["s4"] == STEP_REVERSED
    assert statuses["s3"] == STEP_APPLIED
    report = OperationRunner.recover(state, tmp_path / "undo.json")
    assert report["reversed_steps"] == ["s3", "s2", "s1"]
    assert state.snapshot() == ORIGINAL


def test_journal_is_valid_and_complete_at_every_interrupt_point(tmp_path):
    for k in range(0, 6):
        state = FixtureState(ORIGINAL)
        path = tmp_path / f"undo-{k}.json"
        runner = OperationRunner(state, path)
        runner.plan(f"txn-{k}", _steps())
        with pytest.raises(SimulatedInterrupt):
            runner.run(after_steps=k)
        manifest = Journal(path).read()
        assert manifest.transaction_id == f"txn-{k}"
        raw = json.loads(path.read_text(encoding="utf-8"))
        assert raw["manifest_digest"].startswith("sha256:")


def test_irreversible_step_refused_at_plan_time(tmp_path):
    state = FixtureState(ORIGINAL)
    runner = OperationRunner(state, tmp_path / "undo.json")
    steps = _steps() + [Step("s6", "firmware.demo", "x",
                             reversible=False)]
    with pytest.raises(IrreversibleStepError):
        runner.plan("txn-bad", steps)
    assert state.snapshot() == ORIGINAL
    assert not (tmp_path / "undo.json").exists()


def test_double_reversal_refused_by_name(tmp_path):
    state, runner = _planned(tmp_path)
    runner.run()
    runner.reverse()
    with pytest.raises(AlreadyReversedError):
        runner.reverse()
    with pytest.raises(AlreadyReversedError):
        OperationRunner.recover(state, tmp_path / "undo.json")
    assert state.snapshot() == ORIGINAL


def test_missing_manifest_is_named_error_not_invented_recovery(tmp_path):
    state = FixtureState(ORIGINAL)
    with pytest.raises(ManifestError):
        OperationRunner.recover(state, tmp_path / "nope.json")
    assert state.snapshot() == ORIGINAL


def test_tampered_manifest_refused_by_name(tmp_path):
    state, runner = _planned(tmp_path)
    runner.run()
    raw = json.loads((tmp_path / "undo.json").read_text())
    raw["steps"][0]["before"]["value"] = "forged"
    (tmp_path / "undo.json").write_text(json.dumps(raw))
    with pytest.raises(TamperedManifestError):
        OperationRunner.recover(state, tmp_path / "undo.json")


def test_corrupt_manifest_json_refused_by_name(tmp_path):
    (tmp_path / "undo.json").write_text("{not json")
    with pytest.raises(ManifestError):
        OperationRunner.recover(FixtureState(ORIGINAL),
                                tmp_path / "undo.json")


def test_external_mutation_during_interruption_is_named_divergence(tmp_path):
    state, runner = _planned(tmp_path)
    with pytest.raises(SimulatedInterrupt):
        runner.run(after_steps=2)
    state.set("unrelated.key", "surprise")
    with pytest.raises(DivergenceError):
        OperationRunner.recover(state, tmp_path / "undo.json")


def test_recorded_step_with_foreign_value_is_named_divergence(tmp_path):
    state, runner = _planned(tmp_path)
    with pytest.raises(SimulatedInterrupt):
        runner.run(after_apply_of_step="s2")
    state.set("service.demo.port", 1234)
    with pytest.raises(DivergenceError):
        OperationRunner.recover(state, tmp_path / "undo.json")


def test_manifest_records_before_and_after_images(tmp_path):
    state, runner = _planned(tmp_path)
    planned = Journal(tmp_path / "undo.json").read()
    by_id = {e["step_id"]: e for e in planned.steps}
    # Before-images are captured at apply time, not plan time:
    # at plan time they are still None (not yet applied).
    assert by_id["s1"]["before"] is None
    assert by_id["s1"]["after"] == {"present": True,
                                    "value": "running"}
    assert by_id["s5"]["after"] == {"present": False, "value": None}
    assert planned.original_digest == FixtureState(ORIGINAL).digest()
    runner.run()
    applied = Journal(tmp_path / "undo.json").read()
    by_id = {e["step_id"]: e for e in applied.steps}
    assert by_id["s1"]["before"] == {"present": True,
                                     "value": "stopped"}
    assert by_id["s4"]["before"] == {"present": False, "value": None}
    # Chained target: s5 deletes the port AFTER s2 set it to
    # 9090, so s5's apply-time before-image is 9090, not the
    # plan-time 8080. (A plan-time image here was a real bug
    # this slice's own tests caught and fixed.)
    assert by_id["s5"]["before"] == {"present": True, "value": 9090}


def test_commit_requires_all_steps_applied(tmp_path):
    state, runner = _planned(tmp_path)
    with pytest.raises(TransactionStateError):
        runner.commit()


def test_second_plan_over_live_journal_refused(tmp_path):
    state, runner = _planned(tmp_path)
    other = OperationRunner(state, tmp_path / "undo.json")
    with pytest.raises(TransactionStateError):
        other.plan("txn-other", _steps())


def test_delete_and_recreate_roundtrip_through_reversal(tmp_path):
    state = FixtureState({"only.key": 1})
    runner = OperationRunner(state, tmp_path / "undo.json")
    runner.plan("txn-del", [Step("d1", "only.key", DELETE),
                            Step("d2", "new.key", 2)])
    runner.run()
    assert state.snapshot() == {"new.key": 2}
    runner.reverse()
    assert state.snapshot() == {"only.key": 1}
