"""Tests for the health-repair recipe abstraction (LIF-0501).

Scope: declarative data + validation only. No test touches a live
service, a real config path or a package: recipes bind fixture
targets (demo.service, /etc/demo/...) and instantiation emits plan
records that are checked by the banked catalog and approval
contracts, never executed.

The mutated-binding test is this slice's NEGATIVE CONTROL: the
exact bindings that instantiate the restart recipe cleanly are
mutated to name the critical sshd.service, and instantiation must
refuse -- a recipe layer that lets a parameter smuggle a critical
target past the catalog has failed its whole purpose.
"""
import copy
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from lifthrasir.actions import validate_plan_steps  # noqa: E402
from lifthrasir.approval import check_plan_shape  # noqa: E402
from lifthrasir.recipes import (  # noqa: E402
    RECIPE_CATALOG, RECIPE_VERSION, RECIPES, BindingError,
    EffectError, MalformedRecipeError, ParameterError,
    RecipeConsentError, RiskMismatchError, UndoMismatchError,
    UnknownRecipeError, builtin_recipe_dicts, check_applicability,
    expected_effects, get_recipe, instantiate, recipes_catalog_as_dict,
    validate_recipe,
)

FIXTURES = json.loads(
    (ROOT / "tests" / "fixtures" / "lif0501" / "recipes.json").read_text())
CREATED = "2026-11-05T17:06:00Z"
EXPIRES = "2026-11-05T18:06:00Z"
ERRORS = {
    "MalformedRecipeError": MalformedRecipeError,
    "RiskMismatchError": RiskMismatchError,
    "RecipeConsentError": RecipeConsentError,
    "EffectError": EffectError,
    "UndoMismatchError": UndoMismatchError,
    "ParameterError": ParameterError,
}


def _base():
    return copy.deepcopy(
        [r for r in builtin_recipe_dicts()
         if r["recipe_id"] == "rec-restart-failed-service"][0])


def _instantiate(recipe_id="rec-restart-failed-service", **overrides):
    kwargs = {
        "plan_id": "plan-2026-501", "incident_id": "inc-2026-501",
        "hypothesis_ids": ["hyp-2026-501"],
        "bindings": {"unit": "demo.service"},
        "created_at": CREATED, "expires_at": EXPIRES,
    }
    kwargs.update(overrides)
    return instantiate(recipe_id, **kwargs)


def test_catalog_shape_and_version():
    assert RECIPE_VERSION == "0.1"
    assert len(RECIPES) == 4
    assert set(RECIPE_CATALOG) == {
        "rec-restart-failed-service", "rec-revert-user-config",
        "rec-reinstall-broken-package", "rec-lab-guest-config-fix"}
    tiers = {r.risk_level for r in RECIPES}
    assert tiers == {"L2", "L3", "L4"}


def test_every_builtin_recipe_validates_and_round_trips():
    for data in builtin_recipe_dicts():
        recipe = validate_recipe(data)
        assert recipe.to_dict() == data


def test_json_twin_matches_code():
    on_disk = json.loads(
        (ROOT / "docs" / "protocols" / "recipes.v0.1.json").read_text())
    assert on_disk == recipes_catalog_as_dict()


def test_doc_table_mirrors_catalog():
    text = (ROOT / "docs" / "EIR-RECIPES.md").read_text()
    for recipe_id in RECIPE_CATALOG:
        assert recipe_id in text


def test_risk_and_consent_are_derived_from_catalog():
    for recipe in RECIPES:
        assert recipe.consent_floor == {
            "L2": "session-blanket", "L3": "allowlist-notice",
            "L4": "per-action"}[recipe.risk_level]
        for step in recipe.steps:
            assert step.undo_verb  # every step names its undo


def test_module_source_has_no_execution_primitives():
    source = (ROOT / "src" / "lifthrasir" / "recipes.py").read_text()
    for token in ("subprocess", "os.system", "Popen", "eval(",
                  "os.exec", "socket", "urllib", "requests."):
        assert token not in source


def test_fixture_valid_recipe_validates():
    recipe = validate_recipe(copy.deepcopy(FIXTURES["base"]))
    assert recipe.recipe_id == "rec-stop-runaway-service"
    assert recipe.risk_level == "L3"


@pytest.mark.parametrize(
    "mutation", FIXTURES["mutations"], ids=[m["name"] for m in FIXTURES["mutations"]])
def test_fixture_mutations_are_refused_by_name(mutation):
    data = copy.deepcopy(FIXTURES["base"])
    node = data
    for key in mutation["path"][:-1]:
        node = node[key]
    if mutation.get("delete"):
        del node[mutation["path"][-1]]
    else:
        node[mutation["path"][-1]] = mutation["value"]
    with pytest.raises(ERRORS[mutation["error"]]):
        validate_recipe(data)


def test_unknown_recipe_refused():
    with pytest.raises(UnknownRecipeError):
        get_recipe("rec-fix-everything")


def test_unknown_key_and_wrong_schema_refused():
    data = _base()
    data["shell_command"] = "systemctl restart demo"
    with pytest.raises(MalformedRecipeError):
        validate_recipe(data)
    data = _base()
    data["schema"] = "lifthrasir.recipe.v9"
    with pytest.raises(MalformedRecipeError):
        validate_recipe(data)


def test_observation_only_recipe_refused():
    data = _base()
    data["steps"] = [data["steps"][0]]  # read_service_status only
    data["risk_level"] = "L0"
    data["consent_mode"] = "none"
    data["rollback"] = {"method": "stop_unit", "description": "x"}
    with pytest.raises((MalformedRecipeError, UndoMismatchError)):
        validate_recipe(data)


def test_instantiated_plan_passes_banked_checks():
    plan = _instantiate()
    assert validate_plan_steps(plan) == []
    check_plan_shape(plan)  # must not raise
    assert plan["risk_level"] == "L3"
    assert plan["consent_mode"] == "allowlist-notice"
    assert plan["steps"][1]["target"]["name"] == "demo.service"
    assert plan["preconditions"][0] == "demo.service is in failed state"
    assert plan["rollback"]["method"] == "stop_unit"


def test_instantiate_is_deterministic():
    assert _instantiate() == _instantiate()


def test_negative_control_critical_unit_binding_refused():
    good = _instantiate()
    assert good["steps"][1]["target"]["name"] == "demo.service"
    with pytest.raises(BindingError):
        _instantiate(bindings={"unit": "sshd.service"})


def test_protected_path_binding_refused():
    with pytest.raises(BindingError):
        instantiate(
            "rec-revert-user-config", plan_id="plan-2026-502",
            incident_id="inc-2026-501",
            hypothesis_ids=["hyp-2026-501"],
            bindings={"config_path": "/etc/ssh/sshd_config",
                      "prior_version_digest": "sha256:abc123"},
            created_at=CREATED, expires_at=EXPIRES)


def test_lab_guest_recipe_instantiates():
    plan = instantiate(
        "rec-lab-guest-config-fix", plan_id="plan-2026-503",
        incident_id="inc-2026-501", hypothesis_ids=["hyp-2026-501"],
        bindings={"guest": "lab-guest-01",
                  "config_path": "/etc/demo/demo.conf",
                  "setting": "data_path", "value": "/var/lib/demo",
                  "unit": "demo.service"},
        created_at=CREATED, expires_at=EXPIRES)
    assert validate_plan_steps(plan) == []
    assert plan["risk_level"] == "L2"
    assert plan["steps"][0]["args"]["setting"] == "data_path"


def test_package_recipe_instantiates_at_l4():
    plan = instantiate(
        "rec-reinstall-broken-package", plan_id="plan-2026-504",
        incident_id="inc-2026-501", hypothesis_ids=["hyp-2026-501"],
        bindings={"package": "demo-tool", "version": "1.2.3"},
        created_at=CREATED, expires_at=EXPIRES)
    assert plan["risk_level"] == "L4"
    assert plan["consent_mode"] == "per-action"
    assert plan["rollback"]["method"] == "remove_package"


def test_missing_and_extra_bindings_refused():
    with pytest.raises(BindingError):
        _instantiate(bindings={})
    with pytest.raises(BindingError):
        _instantiate(bindings={"unit": "demo.service",
                               "surprise": "x"})
    with pytest.raises(BindingError):
        _instantiate(bindings={"unit": "*.service"})
    with pytest.raises(BindingError):
        _instantiate(bindings={"unit": "demo.service; rm -rf /"})


def test_expired_window_and_bad_ids_refused():
    with pytest.raises(BindingError):
        _instantiate(expires_at=CREATED)
    with pytest.raises(BindingError):
        _instantiate(plan_id="not-a-plan")
    with pytest.raises(BindingError):
        _instantiate(hypothesis_ids=[])


def test_expected_effects_are_exact_and_bound():
    effects = expected_effects(
        "rec-restart-failed-service", bindings={"unit": "demo.service"})
    assert effects == [
        {"step_id": "step-1",
         "target": {"type": "systemd-unit", "name": "demo.service"},
         "observable": "service_state", "expected": "failed"},
        {"step_id": "step-2",
         "target": {"type": "systemd-unit", "name": "demo.service"},
         "observable": "service_state", "expected": "active"},
    ]
    pkg = expected_effects(
        "rec-reinstall-broken-package",
        bindings={"package": "demo-tool", "version": "1.2.3"})
    assert pkg[1]["expected"] == "1.2.3"


def _observations(recipe_id="rec-restart-failed-service", **overrides):
    recipe = get_recipe(recipe_id)
    snapshot = {text: True for text in recipe.preconditions}
    snapshot.update(overrides)
    return snapshot


def test_applicability_applicable_only_when_all_observed():
    decision = check_applicability(
        "rec-restart-failed-service", _observations())
    assert decision.outcome == "applicable"
    assert decision.reason_codes == ("ALL_PRECONDITIONS_OBSERVED",)


def test_applicability_abstains_on_failed_precondition():
    recipe = get_recipe("rec-restart-failed-service")
    snapshot = _observations()
    snapshot[recipe.preconditions[0]] = False
    decision = check_applicability("rec-restart-failed-service",
                                   snapshot)
    assert decision.outcome == "abstain"
    assert any(code.startswith("PRECONDITION_FAILED:")
               for code in decision.reason_codes)


def test_applicability_abstains_on_unverified_precondition():
    snapshot = _observations()
    snapshot.popitem()
    decision = check_applicability("rec-restart-failed-service",
                                   snapshot)
    assert decision.outcome == "abstain"
    assert any(code.startswith("PRECONDITION_UNVERIFIED:")
               for code in decision.reason_codes)


def test_applicability_abstains_on_abstain_condition():
    snapshot = _observations(**{"unit-intentionally-stopped": True})
    decision = check_applicability("rec-restart-failed-service",
                                   snapshot)
    assert decision.outcome == "abstain"
    assert "ABSTAIN_CONDITION:unit-intentionally-stopped" \
        in decision.reason_codes
