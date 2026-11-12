# SPDX-License-Identifier: GPL-2.0-only
"""LIF-0803 response coordination tests.

Scope: coordination/planning level only.  No test touches a live
service, a real config path or a package: findings are fixture
data, the recipe binds the fixture unit demo.service, policy and
approval run in memory with a throwaway HMAC key, the transaction
store (when used) lives under pytest tmp_path, and the only
executor exercised is the banked dry-run executor, which executes
nothing.

The headline NEGATIVE CONTROLS are the missing-link tests: the
exact chain that yields an executable proposal is rebuilt with one
link removed or broken at a time -- no approval, a rejected
approval, a consumed approval, no undo manifest, a non-undoable
manifest -- and coordination MUST abstain every time.  A
coordination layer that marks a proposal executable with any link
missing has failed its whole purpose.
"""
import copy
import dataclasses
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from lifthrasir import approval as appr  # noqa: E402
from lifthrasir import policy as pol  # noqa: E402
from lifthrasir import recipes as rec  # noqa: E402
from lifthrasir import transactions as txn  # noqa: E402
from lifthrasir.coordination import (  # noqa: E402
    COORDINATION_VERSION,
    OUTCOME_ABSTAIN,
    OUTCOME_EXECUTABLE,
    MalformedFindingError,
    SecurityFinding,
    build_transaction_record,
    propose_response,
    validate_finding,
)

FIXTURES = json.loads(
    (ROOT / "tests" / "fixtures" / "lif0803" / "findings.json")
    .read_text())
FIXTURE_RECIPE = json.loads(
    (ROOT / "tests" / "fixtures" / "lif0803" / "recipes.json")
    .read_text())
CREATED = "2026-11-05T17:06:00Z"
EXPIRES = "2026-11-05T18:06:00Z"
AT = "2026-11-05T17:30:00Z"
KEY = b"lif0803-fixture-key-0123456789abcdef"
RECIPE_ID = "rec-restart-failed-service"
OBSERVATIONS = {
    "$unit is in failed state": True,
    "$unit is expected to be running": True,
    "$unit is on the human-approved allowlist": True,
}
SNAPSHOT = {
    "demo.service is in failed state": True,
    "demo.service is expected to be running": True,
    "demo.service is on the human-approved allowlist": True,
}


def _finding(**overrides):
    data = copy.deepcopy(FIXTURES["base"])
    data.update(overrides)
    return data


def _plan():
    return rec.instantiate(
        FIXTURE_RECIPE, plan_id="plan-2026-803",
        incident_id="inc-2026-803",
        hypothesis_ids=["hyp-2026-803"], bindings={"unit": "demo.service"},
        created_at=CREATED, expires_at=EXPIRES)


def _identity():
    return pol.Identity(principal_id="eir-agent", kind="agent",
                        authenticated=True)


def _context(snapshot=None, at=AT):
    return pol.AuthorizationContext(
        evaluated_at=at, consent_mode_granted="allowlist-notice",
        consent_granted_by_id="user-1", consent_granted_by_kind="human",
        allowlist=frozenset({"demo.service"}),
        resources={"demo.service": pol.ResourceInfo(
            scope="live-host", critical=False, sensitive=False)},
        precondition_snapshot=dict(SNAPSHOT if snapshot is None
                                   else snapshot),
        emergency_stop_active=False)


def _approved_ledger(plan, decision="approved", ttl_seconds=900,
                     mint_at=None):
    ledger = appr.ApprovalLedger()
    moment = mint_at or datetime(2026, 11, 5, 17, 20,
                                 tzinfo=timezone.utc)
    ref = appr.mint_plan_reference(plan, key=KEY, now=moment,
                                   ttl_seconds=ttl_seconds,
                                   nonce="a" * 32)
    ledger.register(ref, key=KEY)
    from datetime import timedelta
    ledger.decide(ref.reference_id, plan, decision=decision,
                  approver="user-1", now=moment + timedelta(seconds=30))
    return ledger, ref


def _tx_record(plan):
    return build_transaction_record(
        plan, FIXTURE_RECIPE, transaction_id="tx-2026-803",
        created_at=CREATED)


def _propose(**overrides):
    plan = _plan()
    ledger, ref = _approved_ledger(plan)
    kwargs = {
        "recipe_id": FIXTURE_RECIPE, "bindings": {"unit": "demo.service"},
        "plan_id": "plan-2026-803", "hypothesis_ids": ["hyp-2026-803"],
        "created_at": CREATED, "expires_at": EXPIRES,
        "observations": dict(OBSERVATIONS), "identity": _identity(),
        "context": _context(), "ledger": ledger, "reference": ref,
        "key": KEY, "transaction_record": _tx_record(plan),
    }
    kwargs.update(overrides)
    return propose_response(_finding(), **kwargs), ledger, ref


# -- finding validation -------------------------------------------------

def test_validate_finding_round_trip():
    finding = validate_finding(_finding())
    assert isinstance(finding, SecurityFinding)
    assert finding.finding_id == "find-2026-803"
    assert finding.scope_key() == "systemd-unit:demo.service"
    assert validate_finding(finding.to_dict()) == finding


@pytest.mark.parametrize("patch", [
    {"schema": "lifthrasir.finding.v9"},
    {"finding_id": "finding-1"},
    {"incident_id": "incident-1"},
    {"severity": "scary"},
    {"detector": ""},
    {"summary": ""},
    {"target": {"type": "kernel", "name": "vmlinuz"}},
    {"target": {"type": "systemd-unit", "name": ""}},
    {"observed_at": "yesterday"},
    {"observed_at": "2026-11-05T17:05:00"},
    {"evidence_refs": "not-a-list"},
    {"surprise_field": True},
])
def test_malformed_findings_refused_by_name(patch):
    data = _finding()
    data.update(patch)
    with pytest.raises(MalformedFindingError):
        validate_finding(data)


def test_malformed_finding_raises_from_propose():
    with pytest.raises(MalformedFindingError):
        propose_response({"schema": "nope"}, recipe_id=RECIPE_ID,
                         bindings={}, plan_id="plan-2026-803",
                         hypothesis_ids=["hyp-2026-803"],
                         created_at=CREATED, expires_at=EXPIRES,
                         observations={})


# -- transaction record derivation ---------------------------------------

def test_build_transaction_record_validates_and_is_undoable():
    plan = _plan()
    record = _tx_record(plan)
    payload = txn.validate_transaction(record)
    assert payload["undoable"] is True
    assert payload["plan_id"] == "plan-2026-803"
    verbs = [(s["action_verb"], (s["undo"] or {}).get("action_verb"))
             for s in payload["steps"]]
    assert verbs == [("restart_unit", "stop_unit")]


def test_build_transaction_record_for_package_recipe_carries_version():
    plan = rec.instantiate(
        "rec-reinstall-broken-package", plan_id="plan-2026-806",
        incident_id="inc-2026-803", hypothesis_ids=["hyp-2026-803"],
        bindings={"package": "demo-pkg", "version": "1.2.3"},
        created_at=CREATED, expires_at=EXPIRES)
    record = build_transaction_record(
        plan, "rec-reinstall-broken-package",
        transaction_id="tx-2026-806", created_at=CREATED)
    payload = txn.validate_transaction(record)
    assert payload["undoable"] is True
    undo = payload["steps"][1]["undo"]
    assert undo["action_verb"] == "remove_package"
    assert undo["args"] == {"version": "1.2.3"}


# -- the full chain --------------------------------------------------------

def test_full_chain_marks_executable_and_executes_nothing():
    proposal, ledger, ref = _propose()
    assert proposal.outcome == OUTCOME_EXECUTABLE
    assert proposal.executable is True
    assert proposal.reason_codes == ("ALL_CHAIN_LINKS_VERIFIED",)
    assert proposal.policy_outcome == pol.ALLOW
    assert proposal.approval_reference_id == ref.reference_id
    assert proposal.undo_transaction_id == "tx-2026-803"
    assert len(proposal.dry_run) == 1
    assert all(d["executed"] is False for d in proposal.dry_run)
    assert all(d["status"] == "dry-run" for d in proposal.dry_run)
    # Coordination checks the approval; it never consumes it.
    assert ledger._records[ref.reference_id].consumed is False
    assert proposal.to_dict()["executable"] is True


def test_full_chain_with_digest_bound_transaction():
    plan = _plan()
    ledger, ref = _approved_ledger(plan)
    record = _tx_record(plan)
    record["plan_digest"] = appr.plan_digest(plan)
    proposal, _, _ = _propose(ledger=ledger, reference=ref,
                              transaction_record=record)
    assert proposal.outcome == OUTCOME_EXECUTABLE


def test_full_chain_with_store_derived_undo_manifest(tmp_path):
    plan = _plan()
    ledger, ref = _approved_ledger(plan)
    store = txn.TransactionStore(str(tmp_path / "tx.sqlite3"))
    try:
        store.create_transaction(_tx_record(plan))
        manifest = store.undo_manifest("tx-2026-803")
    finally:
        store.close()
    proposal, _, _ = _propose(ledger=ledger, reference=ref,
                              transaction_record=None,
                              undo_manifest=manifest)
    assert proposal.outcome == OUTCOME_EXECUTABLE
    assert proposal.undo_transaction_id == "tx-2026-803"


# -- negative controls: one broken link at a time -------------------------

def test_unknown_recipe_abstains():
    proposal, _, _ = _propose(recipe_id="rec-does-not-exist")
    assert proposal.outcome == OUTCOME_ABSTAIN
    assert proposal.executable is False
    assert "UNKNOWN_RECIPE" in proposal.reason_codes


def test_unobserved_precondition_abstains():
    obs = dict(OBSERVATIONS)
    del obs["$unit is expected to be running"]
    proposal, _, _ = _propose(observations=obs)
    assert proposal.outcome == OUTCOME_ABSTAIN
    assert any(c.startswith("PRECONDITION_UNVERIFIED")
               for c in proposal.reason_codes)


def test_recipe_abstain_condition_abstains():
    obs = dict(OBSERVATIONS)
    obs["restart-loop-detected"] = True
    proposal, _, _ = _propose(observations=obs)
    assert proposal.outcome == OUTCOME_ABSTAIN
    assert "ABSTAIN_CONDITION:restart-loop-detected" \
        in proposal.reason_codes


def test_critical_target_binding_abstains():
    proposal = propose_response(
        _finding(), recipe_id=RECIPE_ID,
        bindings={"unit": "sshd.service"}, plan_id="plan-2026-803",
        hypothesis_ids=["hyp-2026-803"], created_at=CREATED,
        expires_at=EXPIRES, observations=dict(OBSERVATIONS))
    assert proposal.outcome == OUTCOME_ABSTAIN
    assert "RECIPE_BINDING_FAILED" in proposal.reason_codes


def test_finding_target_out_of_scope_abstains():
    plan = _plan()
    ledger, ref = _approved_ledger(plan)
    proposal = propose_response(
        copy.deepcopy(FIXTURES["other_target"]), recipe_id=RECIPE_ID,
        bindings={"unit": "demo.service"}, plan_id="plan-2026-803",
        hypothesis_ids=["hyp-2026-803"], created_at=CREATED,
        expires_at=EXPIRES, observations=dict(OBSERVATIONS),
        identity=_identity(), context=_context(), ledger=ledger,
        reference=ref, key=KEY, transaction_record=_tx_record(plan))
    assert proposal.outcome == OUTCOME_ABSTAIN
    assert "FINDING_TARGET_OUT_OF_SCOPE" in proposal.reason_codes


def test_missing_policy_input_abstains():
    proposal, _, _ = _propose(identity=None, context=None)
    assert proposal.outcome == OUTCOME_ABSTAIN
    assert "POLICY_INPUT_MISSING" in proposal.reason_codes


def test_policy_deny_abstains():
    bad = dict(SNAPSHOT)
    bad["demo.service is in failed state"] = False
    proposal, _, _ = _propose(context=_context(snapshot=bad))
    assert proposal.outcome == OUTCOME_ABSTAIN
    assert "POLICY_DENY" in proposal.reason_codes
    assert "PRECONDITION_FAILED" in proposal.reason_codes


def test_policy_require_human_abstains():
    partial = dict(SNAPSHOT)
    del partial["demo.service is expected to be running"]
    proposal, _, _ = _propose(context=_context(snapshot=partial))
    assert proposal.outcome == OUTCOME_ABSTAIN
    assert "POLICY_REQUIRE_HUMAN" in proposal.reason_codes


def test_missing_approval_abstains():
    proposal, _, _ = _propose(ledger=None, reference=None, key=None)
    assert proposal.outcome == OUTCOME_ABSTAIN
    assert "APPROVAL_MISSING" in proposal.reason_codes


def test_rejected_approval_abstains():
    plan = _plan()
    ledger, ref = _approved_ledger(plan, decision="rejected")
    proposal, _, _ = _propose(ledger=ledger, reference=ref)
    assert proposal.outcome == OUTCOME_ABSTAIN
    assert "APPROVAL_NOT_APPROVED" in proposal.reason_codes


def test_tampered_approval_signature_abstains():
    plan = _plan()
    ledger, ref = _approved_ledger(plan)
    forged = dataclasses.replace(ref, signature="hmac-sha256:" + "0" * 64)
    proposal, _, _ = _propose(ledger=ledger, reference=forged)
    assert proposal.outcome == OUTCOME_ABSTAIN
    assert "APPROVAL_SIGNATURE_INVALID" in proposal.reason_codes


def test_approval_for_other_plan_abstains():
    plan = _plan()
    other = rec.instantiate(
        RECIPE_ID, plan_id="plan-2026-807", incident_id="inc-2026-803",
        hypothesis_ids=["hyp-2026-803"], bindings={"unit": "demo.service"},
        created_at=CREATED, expires_at=EXPIRES)
    ledger, ref = _approved_ledger(other)
    proposal, _, _ = _propose(ledger=ledger, reference=ref)
    assert proposal.outcome == OUTCOME_ABSTAIN
    assert "APPROVAL_PLAN_MISMATCH" in proposal.reason_codes


def test_consumed_approval_abstains():
    plan = _plan()
    ledger, ref = _approved_ledger(plan)
    ledger.consume_for_execution(
        ref.reference_id, plan, resource="systemd-unit:demo.service",
        now=datetime(2026, 11, 5, 17, 20, tzinfo=timezone.utc))
    proposal, _, _ = _propose(ledger=ledger, reference=ref)
    assert proposal.outcome == OUTCOME_ABSTAIN
    assert "APPROVAL_ALREADY_CONSUMED" in proposal.reason_codes


def test_expired_approval_abstains():
    plan = _plan()
    ledger, ref = _approved_ledger(plan, ttl_seconds=60)
    proposal, _, _ = _propose(ledger=ledger, reference=ref)
    assert proposal.outcome == OUTCOME_ABSTAIN
    assert "APPROVAL_EXPIRED" in proposal.reason_codes


def test_missing_undo_manifest_abstains():
    proposal, _, _ = _propose(transaction_record=None)
    assert proposal.outcome == OUTCOME_ABSTAIN
    assert proposal.executable is False
    assert "UNDO_MANIFEST_MISSING" in proposal.reason_codes


def test_invalid_undo_record_abstains():
    plan = _plan()
    record = _tx_record(plan)
    record["steps"][0]["action_verb"] = "definitely_not_a_verb"
    proposal, _, _ = _propose(transaction_record=record)
    assert proposal.outcome == OUTCOME_ABSTAIN
    assert "UNDO_MANIFEST_INVALID" in proposal.reason_codes


def test_undo_record_for_other_plan_abstains():
    plan = _plan()
    record = _tx_record(plan)
    record["plan_id"] = "plan-2026-999"
    proposal, _, _ = _propose(transaction_record=record)
    assert proposal.outcome == OUTCOME_ABSTAIN
    assert "UNDO_PLAN_MISMATCH" in proposal.reason_codes


def test_undo_record_with_wrong_digest_abstains():
    plan = _plan()
    record = _tx_record(plan)
    record["plan_digest"] = "sha256:" + "1" * 64
    proposal, _, _ = _propose(transaction_record=record)
    assert proposal.outcome == OUTCOME_ABSTAIN
    assert "UNDO_DIGEST_MISMATCH" in proposal.reason_codes


def test_undo_record_with_different_steps_abstains():
    other = rec.instantiate(
        FIXTURE_RECIPE, plan_id="plan-2026-803",
        incident_id="inc-2026-803",
        hypothesis_ids=["hyp-2026-803"],
        bindings={"unit": "other.service"},
        created_at=CREATED, expires_at=EXPIRES)
    record = build_transaction_record(
        other, FIXTURE_RECIPE, transaction_id="tx-2026-803",
        created_at=CREATED)
    proposal, _, _ = _propose(transaction_record=record)
    assert proposal.outcome == OUTCOME_ABSTAIN
    assert "UNDO_STEP_MISMATCH" in proposal.reason_codes


def test_non_undoable_record_abstains():
    plan = _plan()
    record = _tx_record(plan)
    record["steps"][0]["undo"] = None
    payload = txn.validate_transaction(record)
    assert payload["undoable"] is False
    proposal, _, _ = _propose(transaction_record=record)
    assert proposal.outcome == OUTCOME_ABSTAIN
    assert "UNDO_MANIFEST_INCOMPLETE" in proposal.reason_codes


def test_non_undoable_store_manifest_abstains(tmp_path):
    plan = _plan()
    record = _tx_record(plan)
    record["steps"][0]["undo"] = None
    store = txn.TransactionStore(str(tmp_path / "tx.sqlite3"))
    try:
        store.create_transaction(record)
        manifest = store.undo_manifest("tx-2026-803")
    finally:
        store.close()
    proposal, _, _ = _propose(transaction_record=None,
                              undo_manifest=manifest)
    assert proposal.outcome == OUTCOME_ABSTAIN
    assert "UNDO_MANIFEST_INCOMPLETE" in proposal.reason_codes


# -- banked-gap honesty: coordination fails closed on known gaps ---------

def test_builtin_restart_recipe_abstains_on_policy_vocabulary_gap():
    """Banked gap, proven not hidden: the LIF-0402 policy engine's
    interim verb vocabulary (its own docstring's COORDINATION GAP)
    predates the LIF-0401 catalog and does not know the catalog verb
    read_service_status, so the built-in restart recipe's plan is
    DENIED as UNKNOWN_ACTION_VERB and coordination abstains.  The
    executable path in this slice therefore runs on a fixture recipe
    whose verbs sit in both vocabularies (the LIF-0501 fixture
    pattern); reconciling policy's vocabulary to the banked catalog
    is recorded as immediate next work in CAMPAIGN_STATE.md."""
    plan = rec.instantiate(
        RECIPE_ID, plan_id="plan-2026-803", incident_id="inc-2026-803",
        hypothesis_ids=["hyp-2026-803"], bindings={"unit": "demo.service"},
        created_at=CREATED, expires_at=EXPIRES)
    ledger, ref = _approved_ledger(plan)
    record = build_transaction_record(
        plan, RECIPE_ID, transaction_id="tx-2026-803",
        created_at=CREATED)
    assert txn.validate_transaction(record)["undoable"] is True
    proposal = propose_response(
        _finding(), recipe_id=RECIPE_ID,
        bindings={"unit": "demo.service"}, plan_id="plan-2026-803",
        hypothesis_ids=["hyp-2026-803"], created_at=CREATED,
        expires_at=EXPIRES, observations=dict(OBSERVATIONS),
        identity=_identity(), context=_context(), ledger=ledger,
        reference=ref, key=KEY, transaction_record=record)
    assert proposal.outcome == OUTCOME_ABSTAIN
    assert "POLICY_DENY" in proposal.reason_codes
    assert "UNKNOWN_ACTION_VERB" in proposal.reason_codes


def test_lab_guest_recipe_abstains_on_guest_undo_gap():
    """Banked gap, proven not hidden: the lab-guest recipe passes
    policy (its verbs ARE in the interim vocabulary), but the
    catalog names no per-step undo for restart_unit_in_guest while
    the LIF-0405 store counts lab-guest steps as mutating, so no
    undoable transaction exists for it and coordination abstains
    at the undo link instead of marking it executable."""
    plan = rec.instantiate(
        "rec-lab-guest-config-fix", plan_id="plan-2026-803",
        incident_id="inc-2026-803", hypothesis_ids=["hyp-2026-803"],
        bindings={"guest": "lab-guest-01",
                  "config_path": "/etc/demo/demo.conf",
                  "setting": "demo_setting", "value": "fixed",
                  "unit": "demo.service"},
        created_at=CREATED, expires_at=EXPIRES)
    ledger, ref = _approved_ledger(plan)
    record = build_transaction_record(
        plan, "rec-lab-guest-config-fix",
        transaction_id="tx-2026-803", created_at=CREATED)
    # build_transaction_record defaults an undo's target to the
    # forward target; reset_lab_guest acts on the guest itself, so
    # a caller records that target explicitly (documented builder
    # limitation).  Even with it, the record is non-undoable:
    # step-2 has no inverse at all.
    record["steps"][0]["undo"]["target"] = {
        "type": "lab-guest", "name": "lab-guest-01"}
    assert txn.validate_transaction(record)["undoable"] is False
    context = pol.AuthorizationContext(
        evaluated_at=AT, consent_mode_granted="session-blanket",
        consent_granted_by_id="user-1", consent_granted_by_kind="human",
        allowlist=frozenset(),
        resources={
            "/etc/demo/demo.conf": pol.ResourceInfo(
                scope="lab-guest", critical=False, sensitive=False),
            "demo.service": pol.ResourceInfo(
                scope="lab-guest", critical=False, sensitive=False)},
        precondition_snapshot={
            "lab guest lab-guest-01 is running and disposable": True,
            "/etc/demo/demo.conf inside the guest holds the "
            "faulty setting": True},
        emergency_stop_active=False)
    proposal = propose_response(
        copy.deepcopy(FIXTURES["guest_config"]),
        recipe_id="rec-lab-guest-config-fix",
        bindings={"guest": "lab-guest-01",
                  "config_path": "/etc/demo/demo.conf",
                  "setting": "demo_setting", "value": "fixed",
                  "unit": "demo.service"},
        plan_id="plan-2026-803", hypothesis_ids=["hyp-2026-803"],
        created_at=CREATED, expires_at=EXPIRES,
        observations={
            "lab guest $guest is running and disposable": True,
            "$config_path inside the guest holds the "
            "faulty setting": True},
        identity=_identity(), context=context, ledger=ledger,
        reference=ref, key=KEY, transaction_record=record)
    assert proposal.outcome == OUTCOME_ABSTAIN
    assert proposal.policy_outcome == pol.ALLOW
    assert "UNDO_MANIFEST_INCOMPLETE" in proposal.reason_codes


# -- honesty guards ---------------------------------------------------------

def test_module_source_has_no_execution_primitives():
    source = (ROOT / "src" / "lifthrasir" / "coordination.py").read_text()
    for token in ("subprocess", "os.system", "Popen", "eval(",
                  "os.exec", "socket", "urllib", "requests."):
        assert token not in source


def test_version_pin():
    assert COORDINATION_VERSION == "0.1"
