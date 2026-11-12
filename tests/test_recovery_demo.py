# SPDX-License-Identifier: GPL-2.0-only
"""LIF-0502 demonstration tests: one noncritical user-service recovery.

Scope: the fixture world ONLY -- an in-memory simulation of a
systemd user manager inside the disposable lab guest, observed
through the banked LIF-0202 collector. No test touches, names for
execution, or otherwise affects any real host service; the module
under test contains no mechanism that could. Baseline for the
differential: the banked suite before this slice held 372 tests.

The differential pinned here: two identical fixture worlds, one
run through the full authority chain (recovers), one run with the
emergency stop active (policy DENY, stays failed) -- the only
difference is the intervention, so the recovery is attributable
to it and not to the fixture healing itself.
"""
import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "src"))

from lab import systemd_collector as sc  # noqa: E402
from lifthrasir import approval as ap  # noqa: E402
from lifthrasir import recovery_demo as rd  # noqa: E402
from lifthrasir.actions import get_action, validate_plan_steps  # noqa: E402

FIXTURE = REPO / "tests" / "fixtures" / "lif0502" / "demo_world.json"


def fresh_world():
    data = json.loads(FIXTURE.read_text(encoding="utf-8"))
    return rd.load_demo_world(data)


def test_demo_recovers_failed_fixture_unit():
    world = fresh_world()
    report = rd.run_demo(world)
    assert report.outcome == "recovered"
    assert report.reason_codes == ("RECOVERED",)
    assert report.policy_outcome == "ALLOW"
    assert report.restart_count_before == 1
    assert report.restart_count_after == 2
    assert report.fixture_only is True
    assert report.real_host_touched is False
    assert report.evidence_status == "reproducer"
    state = world.units[rd.DEMO_UNIT]
    assert state.active == "active" and state.sub == "running"
    steps = [e.step for e in report.events]
    assert steps == ["observe", "diagnose", "plan", "policy",
                     "approval", "approval-consume", "dry-run",
                     "execute-fixture", "verify"]


def test_observation_uses_banked_collector():
    world = fresh_world()
    list_text, show_text, journal_text = world.snapshot_texts()
    report = sc.collect(failed_text=list_text, show_text=show_text,
                        journal_text=journal_text)
    failed = {f.unit: f for f in report.failed_units}
    assert set(failed) == {"lifthrasir-demo.service",
                           "lifthrasir-flaky.service"}
    assert failed["lifthrasir-demo.service"].restart_count == 1
    assert failed["lifthrasir-demo.service"].since == \
        "Thu 2026-11-12 03:59:00 UTC"


def test_plan_validates_against_catalog():
    plan = rd.build_demo_plan()
    assert validate_plan_steps(plan) == []
    spec = get_action(plan["steps"][0]["action_verb"])
    assert spec.verb == "restart_unit_in_guest"
    assert spec.risk_level == "L2" and spec.scope == "lab-guest"


def test_recipe_shape_matches_backlog_contract():
    # LIF-0501 contract (backlog): exact targets and effects. The
    # local RECIPE data carries both until LIF-0501 banks.
    assert rd.RECIPE["target"] == {"type": "systemd-unit",
                                   "name": rd.DEMO_UNIT}
    assert rd.RECIPE["verb"] == "restart_unit_in_guest"
    assert len(rd.RECIPE["effects"]) >= 2
    assert rd.RECIPE["rollback"]["method"] == "reset_lab_guest"
    assert rd.RECIPE["verification"]["method"] == \
        "collector_reobservation"


def test_abstains_on_intentionally_stopped_unit():
    world = fresh_world()
    before = world.snapshot_texts()
    report = rd.run_demo(world, "lifthrasir-paused.service")
    assert report.outcome == "abstained"
    assert report.reason_codes == ("INTENTIONALLY_STOPPED",)
    assert world.actions_taken == []
    assert world.snapshot_texts() == before


def test_abstains_on_healthy_unit():
    world = fresh_world()
    report = rd.run_demo(world, "lifthrasir-healthy.service")
    assert report.outcome == "abstained"
    assert report.reason_codes == ("NOT_FAILED",)
    assert world.actions_taken == []


def test_unknown_unit_denied():
    world = fresh_world()
    report = rd.run_demo(world, "nosuch.service")
    assert report.outcome == "denied"
    assert report.reason_codes == ("UNKNOWN_UNIT",)
    assert world.actions_taken == []


def test_critical_unit_refused():
    data = json.loads(FIXTURE.read_text(encoding="utf-8"))
    data["units"].append({
        "name": "sshd.service", "load": "loaded", "active": "failed",
        "sub": "failed", "description": "critical (fixture)",
        "n_restarts": 0, "active_enter": None, "result": "exit-code",
        "enabled": True, "intentionally_stopped": False,
        "fail_on_restart": False})
    world = rd.load_demo_world(data)
    report = rd.run_demo(world, "sshd.service")
    assert report.outcome == "denied"
    assert report.reason_codes == ("PROHIBITED_CRITICAL_UNIT",)
    assert world.actions_taken == []
    assert world.units["sshd.service"].active == "failed"


def test_differential_intervention_vs_emergency_stop():
    recovered_world = fresh_world()
    stopped_world = fresh_world()
    ok = rd.run_demo(recovered_world)
    blocked = rd.run_demo(stopped_world, emergency_stop=True)
    assert ok.outcome == "recovered"
    assert blocked.outcome == "denied"
    assert blocked.policy_outcome == "DENY"
    assert "EMERGENCY_STOP_ACTIVE" in blocked.policy_reasons
    # No intervention happened on the stopped world: still failed.
    assert stopped_world.actions_taken == []
    assert stopped_world.units[rd.DEMO_UNIT].active == "failed"


def test_consent_below_floor_requires_human_and_blocks():
    world = fresh_world()
    report = rd.run_demo(world, consent_granted="none")
    assert report.outcome == "denied"
    assert report.policy_outcome == "REQUIRE_HUMAN"
    assert "CONSENT_BELOW_FLOOR" in report.policy_reasons
    assert world.actions_taken == []
    assert world.units[rd.DEMO_UNIT].active == "failed"


def test_rejected_approval_blocks_execution():
    world = fresh_world()
    before = world.snapshot_texts()
    report = rd.run_demo(world, approve=False)
    assert report.outcome == "denied"
    assert report.reason_codes == ("APPROVAL_REJECTED",)
    assert report.approval_reference_id is not None
    assert world.actions_taken == []
    assert world.snapshot_texts() == before


def test_approval_single_use_replay_refused():
    world = fresh_world()
    ledger = ap.ApprovalLedger()
    report = rd.run_demo(world, ledger=ledger)
    assert report.outcome == "recovered"
    with pytest.raises(ap.ReplayError):
        ledger.consume_for_execution(
            report.approval_reference_id, report.plan,
            resource=f"systemd-unit:{rd.DEMO_UNIT}", now=rd.FIXED_NOW)


def test_verification_failure_not_claimed_recovered():
    world = fresh_world()
    report = rd.run_demo(world, "lifthrasir-flaky.service")
    assert report.outcome == "verification-failed"
    assert report.reason_codes == ("VERIFICATION_FAILED",)
    assert world.units["lifthrasir-flaky.service"].active == "failed"
    assert report.restart_count_before == 4
    assert report.restart_count_after == 5


def test_dry_run_executes_nothing_and_no_real_service_layer():
    world = fresh_world()
    report = rd.run_demo(world)
    assert report.dry_run_status == "dry-run"
    assert report.dry_run_executed is False
    source = (REPO / "src" / "lifthrasir" / "recovery_demo.py").read_text(
        encoding="utf-8")
    for token in ("subprocess", "Popen", "os.system", "check_output",
                  "os.popen"):
        assert token not in source, f"real-execution token present: {token}"


def test_deterministic_replay():
    first = rd.run_demo(fresh_world())
    second_world = fresh_world()
    second = rd.run_demo(second_world)
    assert first.outcome == second.outcome == "recovered"
    assert [e.step for e in first.events] == \
        [e.step for e in second.events]
    assert first.to_dict()["world_actions"] == ["restart:lifthrasir-demo.service"]
    # Stronger determinism: two fresh runs leave identical worlds.
    w1, w2 = fresh_world(), fresh_world()
    rd.run_demo(w1)
    rd.run_demo(w2)
    assert w1.snapshot_texts() == w2.snapshot_texts()
