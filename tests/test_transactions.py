# SPDX-License-Identifier: GPL-2.0-only
"""LIF-0405 durable transaction state and undo manifest tests.

Scope: temporary store files only (pytest tmp_path).  No test
touches a live system path, executes a step (forward or undo),
or reads wall time except where a default timestamp is harmless.
Fixtures live in tests/fixtures/lif0405/transactions.json.

NEGATIVE CONTROLS (standing): test_tampered_payload_refused and
test_tampered_history_detected mutate stored bytes through a raw
sqlite3 connection, bypassing the API, and integrity checking
must catch both.  hidden_files/ replays the tampered-payload
test against a mutant with the record-hash check disabled.
"""
import copy
import json
import sqlite3
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from lifthrasir import transactions as tx  # noqa: E402

FIXTURES = json.loads(
    (REPO / "tests" / "fixtures" / "lif0405" / "transactions.json")
    .read_text(encoding="utf-8"))

T1 = "2026-11-12T04:01:00Z"
T2 = "2026-11-12T04:02:00Z"
T3 = "2026-11-12T04:03:00Z"
T4 = "2026-11-12T04:04:00Z"
T5 = "2026-11-12T04:05:00Z"
T6 = "2026-11-12T04:06:00Z"
T7 = "2026-11-12T04:07:00Z"
T8 = "2026-11-12T04:08:00Z"


def undoable(**overrides):
    rec = copy.deepcopy(FIXTURES["undoable_tx"])
    rec.update(overrides)
    return rec


@pytest.fixture()
def store(tmp_path):
    with tx.TransactionStore(tmp_path / "tx.db") as s:
        yield s


def drive_to_executed(store, tx_id="tx-2026-001"):
    store.approve(tx_id, at=T1)
    store.begin_execution(tx_id, at=T2)
    store.mark_executed(tx_id, at=T3)


# -- creation and read-back ------------------------------------------

def test_create_and_read_back_equality(store):
    rec = undoable()
    created = store.create_transaction(rec)
    assert created.transaction_id == "tx-2026-001"
    assert created.state == "planned"
    assert created.undoable is True
    assert created.plan_digest == rec["plan_digest"]
    assert created.expires_at == rec["expires_at"]
    assert [s.step_id for s in created.steps] == [
        "step-1", "step-2", "step-3"]
    assert store.get_by_id("tx-2026-001") == created.to_dict()
    assert store.get_transaction("tx-missing") is None
    assert store.get_by_id("tx-missing") is None
    assert store.count() == 1
    assert store.schema_version() == tx.CURRENT_MIGRATION_VERSION


def test_fixture_transactions_all_create(store):
    for key in ("undoable_tx", "guest_config_tx", "readonly_tx"):
        store.create_transaction(copy.deepcopy(FIXTURES[key]))
    assert store.count() == 3
    assert store.get_transaction("tx-2026-001").undoable is True
    assert store.get_transaction("tx-2026-002").undoable is False
    assert store.get_transaction("tx-2026-003").undoable is True


def test_duplicate_transaction_refused(store):
    store.create_transaction(undoable())
    with pytest.raises(tx.DuplicateTransactionError):
        store.create_transaction(undoable())
    assert store.count() == 1


def test_state_survives_reopen(tmp_path):
    path = tmp_path / "tx.db"
    with tx.TransactionStore(path) as s:
        s.create_transaction(undoable())
        drive_to_executed(s)
        head = s.get_transaction("tx-2026-001").record_hash
    # Reopening the same file is the crash-recovery path: the last
    # committed state and its full history come back exactly.
    with tx.TransactionStore(path) as s:
        rec = s.get_transaction("tx-2026-001")
        assert rec.state == "executed"
        assert rec.record_hash == head
        assert [h.to_state for h in s.history("tx-2026-001")] == [
            "planned", "approved", "executing", "executed"]
        assert s.verify_integrity() == []
        assert s.verify_history() is True


def test_list_filter_by_state(store):
    store.create_transaction(undoable())
    store.create_transaction(copy.deepcopy(FIXTURES["readonly_tx"]))
    store.abort("tx-2026-003", at="2026-11-12T04:30:00Z")
    assert [r.transaction_id for r in store.list_transactions()] == [
        "tx-2026-001", "tx-2026-003"]
    assert [r.transaction_id for r in
            store.list_transactions(state="aborted")] == ["tx-2026-003"]
    with pytest.raises(tx.UnknownStateError):
        store.list_transactions(state="melted")


# -- validation refusals ----------------------------------------------

@pytest.mark.parametrize("mutate", [
    lambda r: r.update(schema="lifthrasir.plan.v0.1"),
    lambda r: r.update(schema_version="0.2"),
    lambda r: r.update(transaction_id="txn-1"),
    lambda r: r.update(plan_id="p-1"),
    lambda r: r.update(title=""),
    lambda r: r.update(plan_digest="sha256:not-hex"),
    lambda r: r.update(state="executed"),
    lambda r: r.update(expires_at="2026-11-12T03:00:00Z"),
    lambda r: r.update(created_at="not-a-time"),
    lambda r: r.update(steps=[]),
    lambda r: r.update(surprise_field=True),
    lambda r: r["steps"][0].update(surprise_field=True),
    lambda r: r["steps"].append(dict(r["steps"][0])),
    lambda r: r["steps"][1].update(prior_digest="md5:abc"),
])
def test_malformed_records_refused(store, mutate):
    rec = undoable()
    mutate(rec)
    with pytest.raises(tx.MalformedTransactionError):
        store.create_transaction(rec)
    assert store.count() == 0


def test_unknown_and_prohibited_verbs_refused(store):
    rec = undoable()
    rec["steps"][0]["action_verb"] = "teleport_unit"
    with pytest.raises(tx.MalformedTransactionError):
        store.create_transaction(rec)
    rec = undoable()
    rec["steps"][0]["action_verb"] = "kernel_patch"
    with pytest.raises(tx.MalformedTransactionError):
        store.create_transaction(rec)


def test_wrong_target_type_refused(store):
    rec = undoable()
    rec["steps"][1]["target"] = {"type": "package", "name": "demo-pkg"}
    with pytest.raises(tx.MalformedTransactionError):
        store.create_transaction(rec)


def test_catalog_undo_mismatch_refused(store):
    # restart_unit's catalog undo is stop_unit, not itself.
    rec = undoable()
    rec["steps"][1]["undo"] = {"action_verb": "restart_unit"}
    with pytest.raises(tx.MalformedTransactionError):
        store.create_transaction(rec)
    # read_service_status has catalog undo method 'none': no entry.
    rec = undoable()
    rec["steps"][0]["undo"] = {"action_verb": "read_service_status"}
    with pytest.raises(tx.MalformedTransactionError):
        store.create_transaction(rec)


def test_shell_and_wildcard_targets_refused(store):
    rec = undoable()
    rec["steps"][1]["target"]["name"] = "demo.service; rm -rf /"
    with pytest.raises(tx.MalformedTransactionError):
        store.create_transaction(rec)
    rec = undoable()
    rec["steps"][2]["target"]["name"] = "demo-*"
    with pytest.raises(tx.MalformedTransactionError):
        store.create_transaction(rec)


def test_undo_target_defaults_to_forward_target(store):
    created = store.create_transaction(undoable())
    step = created.steps[1]
    assert step.undo_verb == "stop_unit"
    assert step.undo_target_type == "systemd-unit"
    assert step.undo_target_name == "demo.service"
    assert step.prior_digest.startswith("sha256:")


# -- transitions --------------------------------------------------------

def test_happy_path_transitions(store):
    store.create_transaction(undoable())
    assert store.approve("tx-2026-001", at=T1,
                         detail="human ok").state == "approved"
    assert store.begin_execution("tx-2026-001", at=T2).state == "executing"
    assert store.mark_executed("tx-2026-001", at=T3).state == "executed"
    assert store.mark_verified("tx-2026-001", at=T4).state == "verified"
    hist = store.history("tx-2026-001")
    assert [(h.from_state, h.to_state) for h in hist] == [
        (None, "planned"), ("planned", "approved"),
        ("approved", "executing"), ("executing", "executed"),
        ("executed", "verified")]
    assert hist[1].detail == "human ok"
    assert store.verify_history() is True


@pytest.mark.parametrize("frm,to", [
    ("planned", "verified"), ("planned", "undone"),
    ("planned", "executed"), ("approved", "verified"),
    ("executing", "verified"), ("executing", "aborted"),
    ("executed", "executing"), ("verified", "executed"),
])
def test_invalid_transitions_refused(store, frm, to):
    store.create_transaction(undoable())
    path = {"approved": [("approved", T1)],
            "executing": [("approved", T1), ("executing", T2)],
            "executed": [("approved", T1), ("executing", T2),
                         ("executed", T3)],
            "verified": [("approved", T1), ("executing", T2),
                         ("executed", T3), ("verified", T4)]}
    for state, at in path.get(frm, []):
        store.transition("tx-2026-001", state, at=at)
    with pytest.raises(tx.InvalidTransitionError):
        store.transition("tx-2026-001", to, at=T8)
    assert store.get_transaction("tx-2026-001").state == frm


def test_terminal_states_have_no_moves(store):
    store.create_transaction(undoable())
    store.abort("tx-2026-001", at=T1)
    with pytest.raises(tx.InvalidTransitionError):
        store.transition("tx-2026-001", "executing", at=T2)
    assert store.get_transaction("tx-2026-001").state == "aborted"


def test_unknown_state_and_unknown_transaction_refused(store):
    store.create_transaction(undoable())
    with pytest.raises(tx.UnknownStateError):
        store.transition("tx-2026-001", "melted", at=T1)
    with pytest.raises(tx.UnknownTransactionError):
        store.transition("tx-2026-999", "approved", at=T1)
    with pytest.raises(tx.UnknownTransactionError):
        store.plan_undo("tx-2026-999")
    with pytest.raises(tx.UnknownTransactionError):
        store.history("tx-2026-999")


def test_backwards_timestamp_refused(store):
    store.create_transaction(undoable())
    store.approve("tx-2026-001", at=T3)
    with pytest.raises(tx.StaleTimestampError):
        store.begin_execution("tx-2026-001", at=T1)
    assert store.get_transaction("tx-2026-001").state == "approved"


def test_direct_mutation_entry_points_refuse(store):
    store.create_transaction(undoable())
    with pytest.raises(tx.DirectMutationError):
        store.delete_transaction("tx-2026-001")
    with pytest.raises(tx.DirectMutationError):
        store.update_transaction("tx-2026-001", {"state": "undone"})
    assert store.get_transaction("tx-2026-001").state == "planned"


# -- undo manifest --------------------------------------------------------

def test_undo_manifest_reverse_order_and_contents(store):
    store.create_transaction(undoable())
    drive_to_executed(store)
    manifest = store.plan_undo("tx-2026-001")
    assert manifest.undoable is True
    assert manifest.state == "executed"
    # Strict reverse step order: package removal before unit stop.
    assert [(a.for_step_id, a.action_verb) for a in manifest.actions] == [
        ("step-3", "remove_package"), ("step-2", "stop_unit")]
    pkg = manifest.actions[0]
    assert pkg.target_type == "package" and pkg.target_name == "demo-pkg"
    assert pkg.args == {"version": "1.2.3"}
    unit = manifest.actions[1]
    assert unit.target_name == "demo.service"
    assert unit.prior_digest.startswith("sha256:")
    assert manifest.skipped == ("step-1",)
    assert manifest.missing == ()
    assert manifest.to_dict()["actions"][0]["action_verb"] == "remove_package"


def test_readonly_transaction_manifest_is_empty_but_undoable(store):
    store.create_transaction(copy.deepcopy(FIXTURES["readonly_tx"]))
    manifest = store.undo_manifest("tx-2026-003")
    assert manifest.undoable is True
    assert manifest.actions == ()
    assert manifest.skipped == ("step-1", "step-2")
    assert manifest.missing == ()


def test_nonundoable_transaction_undo_refused(store):
    store.create_transaction(copy.deepcopy(FIXTURES["guest_config_tx"]))
    manifest = store.undo_manifest("tx-2026-002")
    assert manifest.undoable is False
    assert manifest.missing == ("step-1",)
    store.begin_execution("tx-2026-002", at="2026-11-12T04:11:00Z")
    store.mark_executed("tx-2026-002", at="2026-11-12T04:12:00Z")
    with pytest.raises(tx.NonUndoableError) as excinfo:
        store.plan_undo("tx-2026-002")
    assert "step-1" in str(excinfo.value)
    with pytest.raises(tx.NonUndoableError):
        store.begin_undo("tx-2026-002", at="2026-11-12T04:13:00Z")
    assert store.get_transaction("tx-2026-002").state == "executed"


def test_undo_refused_before_execution_and_after_abort(store):
    store.create_transaction(undoable())
    with pytest.raises(tx.NonUndoableError):
        store.plan_undo("tx-2026-001")
    store.approve("tx-2026-001", at=T1)
    with pytest.raises(tx.NonUndoableError):
        store.plan_undo("tx-2026-001")
    store.create_transaction(copy.deepcopy(FIXTURES["readonly_tx"]))
    store.abort("tx-2026-003", at="2026-11-12T04:30:00Z")
    with pytest.raises(tx.NonUndoableError):
        store.plan_undo("tx-2026-003")


def test_undo_refused_while_executing(store):
    store.create_transaction(undoable())
    store.begin_execution("tx-2026-001", at=T1)
    with pytest.raises(tx.InvalidTransitionError):
        store.plan_undo("tx-2026-001")


def test_full_undo_flow_and_already_undone_refusal(store):
    store.create_transaction(undoable())
    drive_to_executed(store)
    store.mark_verified("tx-2026-001", at=T4)
    manifest = store.begin_undo("tx-2026-001", at=T5)
    assert manifest.undoable is True
    assert store.get_transaction("tx-2026-001").state == "undoing"
    with pytest.raises(tx.InvalidTransitionError):
        store.plan_undo("tx-2026-001")
    assert store.complete_undo("tx-2026-001", at=T6).state == "undone"
    with pytest.raises(tx.AlreadyUndoneError):
        store.plan_undo("tx-2026-001")
    with pytest.raises(tx.AlreadyUndoneError):
        store.begin_undo("tx-2026-001", at=T7)
    # AlreadyUndoneError is a NonUndoableError for coarse callers.
    with pytest.raises(tx.NonUndoableError):
        store.plan_undo("tx-2026-001")


def test_undo_from_failed_and_undo_failure_retry(store):
    store.create_transaction(undoable())
    store.begin_execution("tx-2026-001", at=T1)
    store.mark_failed("tx-2026-001", at=T2, detail="step-2 failed")
    store.begin_undo("tx-2026-001", at=T3)
    assert store.fail_undo("tx-2026-001", at=T4).state == "undo_failed"
    # A failed undo may be retried from undo_failed.
    store.begin_undo("tx-2026-001", at=T5)
    assert store.complete_undo("tx-2026-001", at=T6).state == "undone"


# -- integrity: negative controls -----------------------------------------

def test_tampered_payload_refused(store, tmp_path):
    store.create_transaction(undoable())
    assert store.verify_integrity() == []
    raw = sqlite3.connect(str(tmp_path / "tx.db"))
    raw.execute(
        "UPDATE transactions SET payload_json = "
        "REPLACE(payload_json, 'Restart demo service', "
        "'Pwned demo service') WHERE transaction_id = 'tx-2026-001'")
    raw.commit()
    raw.close()
    with pytest.raises(tx.CorruptTransactionError):
        store.get_transaction("tx-2026-001")
    assert store.verify_integrity() != []


def test_tampered_state_column_refused(store, tmp_path):
    store.create_transaction(undoable())
    raw = sqlite3.connect(str(tmp_path / "tx.db"))
    raw.execute(
        "UPDATE transactions SET state = 'undone' "
        "WHERE transaction_id = 'tx-2026-001'")
    raw.commit()
    raw.close()
    with pytest.raises(tx.CorruptTransactionError):
        store.get_transaction("tx-2026-001")


def test_unknown_stored_state_refused(store, tmp_path):
    store.create_transaction(undoable())
    raw = sqlite3.connect(str(tmp_path / "tx.db"))
    raw.execute(
        "UPDATE transactions SET state = 'melted', payload_json = "
        "REPLACE(payload_json, '\"planned\"', '\"melted\"') "
        "WHERE transaction_id = 'tx-2026-001'")
    raw.commit()
    raw.close()
    with pytest.raises(tx.UnknownStateError):
        store.get_transaction("tx-2026-001")
    assert any("melted" in e for e in store.verify_integrity())


def test_tampered_history_detected(store, tmp_path):
    store.create_transaction(undoable())
    store.approve("tx-2026-001", at=T1, detail="human ok")
    assert store.verify_history() is True
    raw = sqlite3.connect(str(tmp_path / "tx.db"))
    raw.execute(
        "UPDATE tx_history SET detail = 'forged approval' "
        "WHERE to_state = 'approved'")
    raw.commit()
    raw.close()
    assert store.verify_history() is False
    assert store.history_errors() != []
    assert store.verify_integrity() != []


# -- paths ------------------------------------------------------------------

def test_path_rules(tmp_path):
    with pytest.raises(tx.TransactionPathError):
        tx.TransactionStore(":memory:")
    with pytest.raises(tx.TransactionPathError):
        tx.TransactionStore(tmp_path)
    root = tmp_path / "allowed"
    with pytest.raises(tx.TransactionPathError):
        tx.TransactionStore(tmp_path / "elsewhere" / "tx.db",
                            allowed_root=root)
    with tx.TransactionStore(root / "tx.db", allowed_root=root) as s:
        assert s.count() == 0
