"""Tests for the typed action catalog and executor interface (LIF-0401).

The catalog is checked against its three mirrors (the generated JSON
twin, the specification table, the risk matrix floors), against the
banked v0.1 plan example (differential), and against a battery of
refusals: unknown, prohibited, shell-carrying, wildcard, critical,
expired and under-consented requests must all be denied by name.
"""
import json
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from lifthrasir.actions import (  # noqa: E402
    CATALOG, CATALOG_VERSION, CONSENT_FLOOR, CONSENT_ORDER,
    ActionRequest, ActionTarget, Authorization, ConsentError,
    DryRunExecutor, ExpiredRequestError, MalformedRequestError,
    ProhibitedActionError, UnknownVerbError, catalog_as_dict,
    get_action, validate_plan_steps, validate_request,
)

NOW = 1_800_000_000.0
FIXTURES = json.loads(
    (ROOT / "tests" / "fixtures" / "lif0401" / "requests.json").read_text())


def _auth(verb, plan_id="plan-2026-001", consent=None, expires=NOW + 600):
    spec = get_action(verb)
    return Authorization(
        plan_id=plan_id, plan_digest="sha256:" + "a" * 64,
        nonce="nonce-1", consent_mode=consent or spec.consent_floor,
        expires_at=expires)


def _request(case, plan_id="plan-2026-001", expires=NOW + 600):
    return ActionRequest(
        verb=case["verb"],
        target=ActionTarget(type=case["target"]["type"],
                            name=case["target"]["name"]),
        args=case.get("args", {}), plan_id=plan_id, expires_at=expires)


def test_catalog_shape_and_version():
    assert CATALOG_VERSION == "0.1"
    assert len(CATALOG) == 16
    for verb, spec in CATALOG.items():
        assert spec.verb == verb and verb == verb.lower()
        assert spec.max_duration_seconds > 0 and spec.description


def test_json_twin_matches_code():
    on_disk = json.loads(
        (ROOT / "docs" / "protocols" / "action-catalog.v0.1.json").read_text())
    assert on_disk == catalog_as_dict()


def test_spec_table_mirrors_catalog():
    text = (ROOT / "docs" / "protocols" / "ACTION-CATALOG-v0.1.md").read_text()
    table_verbs = set(re.findall(r"^\| ([a-z][a-z0-9_]+) \|", text, re.M))
    assert table_verbs == set(CATALOG)


def test_tiers_and_consent_floors_follow_risk_matrix():
    assert CONSENT_FLOOR == {
        "L0": "none", "L1": "standing-opt-in", "L2": "session-blanket",
        "L3": "allowlist-notice", "L4": "per-action", "L5": "human-only"}
    tiers = {s.risk_level for s in CATALOG.values()}
    assert tiers == {"L0", "L1", "L2", "L3", "L4"}  # no L5 verb exists
    ranks = [CONSENT_ORDER.index(CONSENT_FLOOR[t])
             for t in ("L0", "L1", "L2", "L3", "L4", "L5")]
    assert ranks == sorted(ranks)  # consent monotone in tier
    for spec in CATALOG.values():
        assert spec.consent_floor == CONSENT_FLOOR[spec.risk_level]
        assert spec.consent_floor != "never"


def test_every_live_verb_is_reversible_with_catalog_undo():
    for spec in CATALOG.values():
        assert spec.reversible
        assert spec.undo_method == "none" or spec.undo_method in CATALOG
        if spec.scope == "live-host":
            assert spec.undo_method != "none"


def test_no_shell_shaped_arguments_anywhere():
    for spec in CATALOG.values():
        for arg in spec.args:
            assert arg.name not in ("command", "shell", "argv", "cmd")
            assert arg.kind in ("name", "unit", "path", "string",
                                "integer", "boolean")


def test_module_source_has_no_execution_primitives():
    source = (ROOT / "src" / "lifthrasir" / "actions.py").read_text()
    for token in ("subprocess", "os.system", "Popen", "eval(",
                  "__import__", "os.exec"):
        assert token not in source


def test_banked_plan_example_validates_against_catalog():
    plan = json.loads((ROOT / "docs" / "protocols" / "examples" / "v0.1"
                       / "valid" / "plan.json").read_text())
    assert validate_plan_steps(plan) == []


def test_plan_with_unknown_verb_is_reported():
    plan = json.loads((ROOT / "docs" / "protocols" / "examples" / "v0.1"
                       / "valid" / "plan.json").read_text())
    plan["steps"][0]["action_verb"] = "run_shell_command"
    problems = validate_plan_steps(plan)
    assert problems and "run_shell_command" in problems[0]


@pytest.mark.parametrize("case", FIXTURES["valid"],
                         ids=[c["verb"] for c in FIXTURES["valid"]])
def test_valid_fixture_requests_dry_run(case):
    executor = DryRunExecutor()
    result = executor.execute(_request(case), _auth(case["verb"]), NOW)
    assert result.status == "dry-run" and result.executed is False
    assert executor.intents and executor.intents[0].verb == case["verb"]


def test_unknown_verb_denied():
    with pytest.raises(UnknownVerbError):
        get_action("launch_missiles")


def test_prohibited_verb_spelling_denied_precisely():
    with pytest.raises(ProhibitedActionError):
        get_action("replace_kernel_image")


def test_shell_metacharacters_in_arg_denied():
    case = {"verb": "edit_config_in_guest",
            "target": {"type": "config-file", "name": "/etc/demo/demo.conf"},
            "args": {"guest": "lab-guest-01", "setting": "data_path",
                     "value": "/var/lib/demo; rm -rf /"}}
    with pytest.raises(MalformedRequestError):
        validate_request(_request(case), NOW)


def test_wildcard_target_denied():
    case = {"verb": "read_service_status",
            "target": {"type": "systemd-unit", "name": "*.service"}, "args": {}}
    with pytest.raises(MalformedRequestError):
        validate_request(_request(case), NOW)


def test_path_traversal_denied():
    case = {"verb": "revert_user_config",
            "target": {"type": "config-file", "name": "/home/demo/../etc/passwd"},
            "args": {"prior_version_digest": "sha256:abc123"}}
    with pytest.raises(MalformedRequestError):
        validate_request(_request(case), NOW)


def test_critical_unit_refused_on_live_host_but_not_in_guest():
    live = {"verb": "restart_unit",
            "target": {"type": "systemd-unit", "name": "sshd.service"}, "args": {}}
    with pytest.raises(ProhibitedActionError):
        validate_request(_request(live), NOW)
    guest = {"verb": "restart_unit_in_guest",
             "target": {"type": "systemd-unit", "name": "sshd.service"},
             "args": {"guest": "lab-guest-01"}}
    assert validate_request(_request(guest), NOW).verb == "restart_unit_in_guest"


def test_protected_path_and_package_refused():
    cfg = {"verb": "revert_user_config",
           "target": {"type": "config-file", "name": "/etc/ssh/sshd_config"},
           "args": {"prior_version_digest": "sha256:abc123"}}
    with pytest.raises(ProhibitedActionError):
        validate_request(_request(cfg), NOW)
    pkg = {"verb": "install_package",
           "target": {"type": "package", "name": "grub"},
           "args": {"version": "2.0"}}
    with pytest.raises(ProhibitedActionError):
        validate_request(_request(pkg), NOW)


def test_home_path_refused_even_for_user_config_revert():
    # Section 0 invariant 2 and risk matrix P-09: agent mutation of
    # home files is prohibited, so revert_user_config's "user-level
    # configuration" means managed config outside the home tree
    # (the fixture uses /etc/demo/settings.conf). A home path is
    # refused even though the verb and tier otherwise fit; any
    # narrower carve-out is LIF-0407's review question, not assumed.
    case = {"verb": "revert_user_config",
            "target": {"type": "config-file",
                       "name": "/home/demo/.config/demo/settings.conf"},
            "args": {"prior_version_digest": "sha256:abc123"}}
    with pytest.raises(ProhibitedActionError):
        validate_request(_request(case), NOW)


def test_missing_and_unknown_args_denied():
    missing = {"verb": "install_package",
               "target": {"type": "package", "name": "demo-tool"}, "args": {}}
    with pytest.raises(MalformedRequestError):
        validate_request(_request(missing), NOW)
    extra = {"verb": "read_service_status",
             "target": {"type": "systemd-unit", "name": "demo.service"},
             "args": {"force": True}}
    with pytest.raises(MalformedRequestError):
        validate_request(_request(extra), NOW)


def test_target_type_mismatch_denied():
    case = {"verb": "restart_unit",
            "target": {"type": "package", "name": "demo-tool"}, "args": {}}
    with pytest.raises(MalformedRequestError):
        validate_request(_request(case), NOW)


def test_consent_below_floor_denied_and_at_floor_allowed():
    case = [c for c in FIXTURES["valid"] if c["verb"] == "restart_unit"][0]
    executor = DryRunExecutor()
    with pytest.raises(ConsentError):
        executor.execute(_request(case),
                         _auth("restart_unit", consent="session-blanket"), NOW)
    result = executor.execute(_request(case), _auth("restart_unit"), NOW)
    assert result.executed is False


def test_expired_request_and_token_denied():
    case = FIXTURES["valid"][0]
    executor = DryRunExecutor()
    with pytest.raises(ExpiredRequestError):
        executor.execute(_request(case, expires=NOW - 1),
                         _auth(case["verb"]), NOW)
    with pytest.raises(ExpiredRequestError):
        executor.execute(_request(case),
                         _auth(case["verb"], expires=NOW - 1), NOW)


def test_unbound_token_and_bad_digest_denied():
    case = FIXTURES["valid"][0]
    executor = DryRunExecutor()
    with pytest.raises(MalformedRequestError):
        executor.execute(_request(case),
                         _auth(case["verb"], plan_id="plan-other"), NOW)
    bad = Authorization(plan_id="plan-2026-001", plan_digest="deadbeef",
                        nonce="n", consent_mode="none", expires_at=NOW + 60)
    with pytest.raises(MalformedRequestError):
        executor.execute(_request(case), bad, NOW)


def test_dry_run_executor_never_reports_execution():
    executor = DryRunExecutor()
    for case in FIXTURES["valid"]:
        result = executor.execute(_request(case), _auth(case["verb"]), NOW)
        assert result.executed is False and result.status == "dry-run"
