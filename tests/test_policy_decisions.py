# SPDX-License-Identifier: GPL-2.0-only
"""LIF-0402 policy decision tests.

Scope: pure in-memory evaluation only.  No test touches a live
system path, the network, or any real service: plans, identities,
resources and precondition snapshots are all in-code or fixture
data, and the clock is a fixed context value everywhere.

Documented behaviour pinned here (docs/RISK-MATRIX.md LIF-0003,
research/25 policy decision API, research/33 invariants): outcomes
are ALLOW / DENY / REQUIRE_HUMAN with a policy version and reason
codes; unknown verb, resource or version denies; consent is a
floor granted only by a human; prohibited section-0 actions deny
under any consent; preconditions must be observed true; expired
plans never replay; L5 is human-only and never broker-allowed.

The mutated-request test is this slice's NEGATIVE CONTROL: the
exact request that ALLOWs an allowlisted L3 restart is mutated
(precondition flipped to false) and must DENY -- a policy engine
that still allows it has failed its whole purpose.
"""
import copy
import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from lifthrasir import policy as pol  # noqa: E402

FIXTURE = REPO / "tests" / "fixtures" / "lif0402" / "cases.json"
AT = "2026-11-05T17:30:00Z"
PRE = "demo.service is in failed state"


def plan(verb="restart_unit", ttype="systemd-unit", tname="demo.service",
         risk="L3", consent="allowlist-notice", preconditions=(PRE,),
         rollback_method="stop_unit", plan_id="plan-2026-201"):
    return {
        "schema": "lifthrasir.plan.v0.1", "schema_version": "0.1",
        "plan_id": plan_id, "incident_id": "inc-2026-001",
        "hypothesis_ids": ["hyp-2026-001"], "title": "test plan",
        "status": "submitted", "risk_level": risk, "consent_mode": consent,
        "steps": [{"step_id": "step-1", "action_verb": verb,
                   "target": {"type": ttype, "name": tname}, "args": {}}],
        "preconditions": list(preconditions),
        "rollback": {"method": rollback_method, "description": "undo it"},
        "verification": {"method": "unit_healthy", "timeout_seconds": 20},
        "created_at": "2026-11-05T17:06:00Z",
        "expires_at": "2026-11-05T18:06:00Z",
    }


def request(p=None, kind="agent", principal="eir-agent", auth=True,
            granted="allowlist-notice", by_kind="human", by_id="user-1",
            allowlist=("demo.service",), scope="live-host", critical=False,
            sensitive=False, snapshot=None, stop=False, at=AT, resources=None):
    p = p if p is not None else plan()
    if resources is None:
        name = p["steps"][0]["target"]["name"]
        resources = {name: pol.ResourceInfo(scope=scope, critical=critical,
                                            sensitive=sensitive)}
    if snapshot is None:
        snapshot = {t: True for t in p["preconditions"]}
    return pol.PolicyRequest(
        plan=p,
        identity=pol.Identity(principal_id=principal, kind=kind,
                              authenticated=auth),
        context=pol.AuthorizationContext(
            evaluated_at=at, consent_mode_granted=granted,
            consent_granted_by_id=by_id, consent_granted_by_kind=by_kind,
            allowlist=frozenset(allowlist), resources=resources,
            precondition_snapshot=snapshot, emergency_stop_active=stop))


def test_allow_allowlisted_l3_restart():
    d = pol.evaluate(request())
    assert d.outcome == pol.ALLOW
    assert d.reason_codes == ("ALL_CHECKS_PASSED",)
    assert d.policy_version == pol.POLICY_VERSION
    assert d.effective_risk_level == "L3"
    assert d.required_consent_mode == "allowlist-notice"
    assert d.to_dict()["outcome"] == "ALLOW"


def test_negative_control_mutated_precondition_denies():
    good = request()
    assert pol.evaluate(good).outcome == pol.ALLOW
    bad = request(snapshot={PRE: False})
    d = pol.evaluate(bad)
    assert d.outcome == pol.DENY
    assert "PRECONDITION_FAILED" in d.reason_codes


def test_fixture_cases_table():
    data = json.loads(FIXTURE.read_text(encoding="utf-8"))
    assert len(data["cases"]) >= 12
    for case in data["cases"]:
        d = pol.evaluate_dict(case["request"])
        assert d.outcome == case["expected_outcome"], case["name"]
        for code in case["expected_reasons"]:
            assert code in d.reason_codes, (case["name"], d.reason_codes)
        assert d.policy_version == pol.POLICY_VERSION, case["name"]


def test_require_human_when_l4_consent_below_floor():
    p = plan(verb="stage_package_update", ttype="package", tname="demo-pkg",
             risk="L4", consent="per-action", preconditions=())
    d = pol.evaluate(request(p=p, granted="session-blanket"))
    assert d.outcome == pol.REQUIRE_HUMAN
    assert "CONSENT_BELOW_FLOOR" in d.reason_codes
    assert d.required_consent_mode == "per-action"


def test_allow_l4_with_human_per_action_consent():
    p = plan(verb="stage_package_update", ttype="package", tname="demo-pkg",
             risk="L4", consent="per-action", preconditions=())
    d = pol.evaluate(request(p=p, granted="per-action"))
    assert d.outcome == pol.ALLOW


def test_prohibited_denied_under_any_consent():
    for consent, granted in (("human-only", "human-only"),
                             ("per-action", "per-action")):
        p = plan(verb="replace_kernel", ttype="kernel-image", tname="vmlinuz",
                 risk="L5", consent=consent, preconditions=())
        d = pol.evaluate(request(p=p, kind="human", principal="user-1",
                                 granted=granted))
        assert d.outcome == pol.DENY
        assert "PROHIBITED_ACTION" in d.reason_codes


def test_prohibited_target_type_denied_with_innocent_verb():
    p = plan(verb="revert_config", ttype="bootloader", tname="grub",
             risk="L4", consent="per-action", preconditions=())
    d = pol.evaluate(request(p=p, granted="per-action"))
    assert d.outcome == pol.DENY
    assert "PROHIBITED_ACTION" in d.reason_codes


def test_l5_human_only_never_allowed():
    p = plan(verb="restart_unit", risk="L5", consent="human-only")
    d = pol.evaluate(request(p=p, kind="human", principal="user-1",
                             granted="human-only"))
    assert d.outcome == pol.DENY
    assert "HUMAN_ONLY" in d.reason_codes


def test_unknown_verb_resource_and_version_all_deny():
    d = pol.evaluate(request(p=plan(verb="teleport_unit")))
    assert d.outcome == pol.DENY and "UNKNOWN_ACTION_VERB" in d.reason_codes
    d = pol.evaluate(request(p=plan(ttype="warp-drive")))
    assert d.outcome == pol.DENY and "UNKNOWN_RESOURCE_TYPE" in d.reason_codes
    d = pol.evaluate(request(resources={}))
    assert d.outcome == pol.DENY and "UNKNOWN_RESOURCE" in d.reason_codes
    p = plan(); p["schema_version"] = "9.9"
    d = pol.evaluate(request(p=p))
    assert d.outcome == pol.DENY and "UNKNOWN_SCHEMA_VERSION" in d.reason_codes
    p = plan(); p["risk_level"] = "L9"
    d = pol.evaluate(request(p=p))
    assert d.outcome == pol.DENY and "UNKNOWN_RISK_LEVEL" in d.reason_codes


def test_unauthenticated_and_unknown_identity_deny():
    d = pol.evaluate(request(auth=False))
    assert d.outcome == pol.DENY and "IDENTITY_UNAUTHENTICATED" in d.reason_codes
    d = pol.evaluate(request(kind="ghost"))
    assert d.outcome == pol.DENY and "IDENTITY_UNKNOWN_KIND" in d.reason_codes


def test_agent_cannot_grant_consent_to_itself():
    p = plan(verb="stage_package_update", ttype="package", tname="demo-pkg",
             risk="L4", consent="per-action", preconditions=())
    d = pol.evaluate(request(p=p, granted="per-action", by_kind="agent",
                             by_id="eir-agent"))
    assert d.outcome == pol.DENY
    assert "CONSENT_NOT_HUMAN" in d.reason_codes
    assert "SELF_AUTHORIZATION" in d.reason_codes


def test_unverified_precondition_requires_human_not_allow():
    d = pol.evaluate(request(snapshot={}))
    assert d.outcome == pol.REQUIRE_HUMAN
    assert "PRECONDITION_UNVERIFIED" in d.reason_codes


def test_expired_plan_denied_at_expiry_instant():
    d = pol.evaluate(request(at="2026-11-05T18:06:00Z"))
    assert d.outcome == pol.DENY and "PLAN_EXPIRED" in d.reason_codes


def test_emergency_stop_blocks_mutation_but_not_observation():
    d = pol.evaluate(request(stop=True))
    assert d.outcome == pol.DENY and "EMERGENCY_STOP_ACTIVE" in d.reason_codes
    p = plan(verb="observe_status", risk="L0", consent="none", preconditions=())
    d = pol.evaluate(request(p=p, granted="none", stop=True))
    assert d.outcome == pol.ALLOW


def test_scope_mismatch_guest_verb_on_live_resource_denies():
    p = plan(verb="edit_config_in_guest", ttype="config-file",
             tname="/etc/demo/demo.conf", risk="L2",
             consent="session-blanket", preconditions=())
    d = pol.evaluate(request(p=p, granted="session-blanket", scope="live-host"))
    assert d.outcome == pol.DENY and "SCOPE_MISMATCH" in d.reason_codes


def test_risk_underdeclared_for_critical_unit_denies():
    d = pol.evaluate(request(critical=True))
    assert d.outcome == pol.DENY and "RISK_UNDERDECLARED" in d.reason_codes
    assert d.effective_risk_level == "L4"


def test_sensitive_read_escalates_l0_to_l1():
    p = plan(verb="observe_status", risk="L0", consent="none", preconditions=())
    d = pol.evaluate(request(p=p, granted="none", sensitive=True))
    assert d.outcome == pol.DENY
    assert "RISK_UNDERDECLARED" in d.reason_codes
    assert d.effective_risk_level == "L1"
    assert d.required_consent_mode == "standing-opt-in"


def test_l3_target_not_allowlisted_denies():
    d = pol.evaluate(request(allowlist=()))
    assert d.outcome == pol.DENY and "RESOURCE_NOT_ALLOWLISTED" in d.reason_codes


def test_live_mutation_without_undo_denies():
    d = pol.evaluate(request(p=plan(rollback_method="")))
    assert d.outcome == pol.DENY and "NO_UNDO_PATH" in d.reason_codes


def test_required_consent_table_matches_risk_matrix():
    assert pol.required_consent_for("L0") == "none"
    assert pol.required_consent_for("L1") == "standing-opt-in"
    assert pol.required_consent_for("L2") == "session-blanket"
    assert pol.required_consent_for("L3") == "allowlist-notice"
    assert pol.required_consent_for("L4") == "per-action"
    assert pol.required_consent_for("L5") == "human-only"
    with pytest.raises(pol.PolicyError):
        pol.required_consent_for("L9")


def test_evaluation_is_deterministic_and_does_not_mutate_input():
    req = request()
    snapshot_before = copy.deepcopy(req.plan)
    first = pol.evaluate(req)
    second = pol.evaluate(req)
    assert first == second
    assert req.plan == snapshot_before


def test_policy_module_has_no_side_effect_surface():
    src = (REPO / "src" / "lifthrasir" / "policy.py").read_text(encoding="utf-8")
    for token in ("import subprocess", "import socket", "import os",
                  "import urllib", "os.system", "Popen", "open(", ".write("):
        assert token not in src, f"policy module must stay pure, found {token}"
