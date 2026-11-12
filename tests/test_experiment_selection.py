"""Tests for LIF-1501: experiment selection + cross-device comparisons.

SPDX-License-Identifier: GPL-2.0-only
"""
import ast
import copy
import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from lifthrasir import experimentselection as es  # noqa: E402

FIXTURE = json.loads(
    (REPO / "tests" / "fixtures" / "lif1501" / "experiments.json").read_text())
SNAPSHOT = json.loads(
    (REPO / "tests" / "fixtures" / "lif1501" / "banked_exports_snapshot.json").read_text())

DESIRED_EXPORTS = [
    "EXPERIMENT_SCHEMA", "EXPERIMENT_SCHEMA_VERSION", "COMPARISON_SCHEMA",
    "CATEGORIES", "APPROACHES", "APPROACH_ORDER", "RISK_TIERS", "RISK_ORDER",
    "GUARD_METRICS", "COMPARISON_VERDICTS", "CORRECTNESS_STATES", "UNMEASURED",
    "MIN_REPETITIONS", "MIN_DEVICES", "MIN_HARDWARE_CLASSES", "MAX_PROPOSALS",
    "MAX_RUNS", "MAX_SAMPLES", "MAX_GUARDS", "DEFAULT_NOISE_FLOOR_PERCENT",
    "DEFAULT_MAX_RISK_TIER", "ExperimentError", "MalformedProposalError",
    "DuplicateExperimentError", "UnknownExperimentError", "IncomparableRunError",
    "ExperimentProposal", "DeviceRun", "canonical_json", "proposal_as_dict",
    "proposal_from_dict", "proposal_digest", "summarize_samples",
    "verdict_for_pair", "run_as_dict", "run_from_dict", "selection_key",
    "eligible_proposals", "selection_plan", "select_next_experiment",
    "compare_across_devices", "validate_comparison_report", "comparison_as_dict",
]
HELD_AT_SUBMODULE = [
    "EVIDENCE_STATUS", "MalformedRunError", "TIMESTAMP_FORMAT", "VERDICTS",
    "build_evidence_record", "content_digest_for",
]


def proposals():
    return [es.proposal_from_dict(p) for p in FIXTURE["proposals"]]


def proposal_by_id(exp_id):
    return next(p for p in proposals() if p.experiment_id == exp_id)


def runs_for(exp_id):
    return [es.run_from_dict(r) for r in FIXTURE["runs"][exp_id]]


def make_run(exp_id, device, hw, base, cand, guards=(), correctness="pass"):
    return es.DeviceRun(exp_id, device, hw, tuple(base), tuple(cand),
                        tuple(guards), correctness)


# -- proposals ---------------------------------------------------------

def test_fixture_proposals_round_trip():
    for wire in FIXTURE["proposals"]:
        assert es.proposal_as_dict(es.proposal_from_dict(wire)) == wire


def test_proposal_digest_deterministic():
    p = proposal_by_id("exp-sched-config")
    assert es.proposal_digest(p) == es.proposal_digest(proposal_by_id("exp-sched-config"))
    assert len(es.proposal_digest(p)) == 64


def test_proposal_missing_key_refused():
    wire = copy.deepcopy(FIXTURE["proposals"][0]); del wire["title"]
    with pytest.raises(es.MalformedProposalError):
        es.proposal_from_dict(wire)


def test_proposal_extra_key_refused():
    wire = copy.deepcopy(FIXTURE["proposals"][0]); wire["surprise"] = 1
    with pytest.raises(es.MalformedProposalError):
        es.proposal_from_dict(wire)


def test_proposal_wrong_schema_refused():
    wire = copy.deepcopy(FIXTURE["proposals"][0]); wire["schema"] = "nope"
    with pytest.raises(es.MalformedProposalError):
        es.proposal_from_dict(wire)


def test_proposal_unknown_category_refused():
    wire = copy.deepcopy(FIXTURE["proposals"][0]); wire["category"] = "quantum"
    with pytest.raises(es.MalformedProposalError):
        es.proposal_from_dict(wire)


def test_proposal_unknown_guard_refused():
    wire = copy.deepcopy(FIXTURE["proposals"][0]); wire["guard_metrics"] = ["luck"]
    with pytest.raises(es.MalformedProposalError):
        es.proposal_from_dict(wire)


def test_proposal_duplicate_guards_refused():
    wire = copy.deepcopy(FIXTURE["proposals"][0])
    wire["guard_metrics"] = ["energy", "energy"]
    with pytest.raises(es.MalformedProposalError):
        es.proposal_from_dict(wire)


def test_proposal_bad_risk_tier_refused():
    wire = copy.deepcopy(FIXTURE["proposals"][0]); wire["risk_tier"] = "L9"
    with pytest.raises(es.MalformedProposalError):
        es.proposal_from_dict(wire)


# -- selection ----------------------------------------------------------

def test_selection_plan_default_order():
    assert es.selection_plan(proposals()) == [
        "exp-sched-config", "exp-mem-config", "exp-power-algo"]


def test_select_next_is_lowest_risk_config():
    nxt = es.select_next_experiment(proposals())
    assert nxt.experiment_id == "exp-sched-config"


def test_kernel_patch_held_until_config_completes():
    assert "exp-sched-kernel" not in es.selection_plan(proposals())
    plan = es.selection_plan(proposals(), completed_ids=["exp-sched-config"])
    assert plan == ["exp-mem-config", "exp-power-algo", "exp-sched-kernel"]


def test_risk_cap_excludes_high_tiers():
    plan = es.selection_plan(proposals(), completed_ids=["exp-sched-config"],
                             max_risk_tier="L2")
    assert plan == ["exp-mem-config", "exp-power-algo"]


def test_selection_exhausted_returns_none():
    done = ["exp-sched-config", "exp-mem-config", "exp-power-algo"]
    assert es.select_next_experiment(proposals(), completed_ids=done,
                                     max_risk_tier="L2") is None


def test_duplicate_proposal_refused():
    ps = proposals(); ps.append(ps[0])
    with pytest.raises(es.DuplicateExperimentError):
        es.selection_plan(ps)


def test_unknown_completed_refused():
    with pytest.raises(es.UnknownExperimentError):
        es.selection_plan(proposals(), completed_ids=["exp-nope-1"])


def test_selection_is_deterministic_under_shuffle():
    ps = proposals(); shuffled = [ps[i] for i in (3, 0, 4, 1, 2)]
    assert es.selection_plan(shuffled) == es.selection_plan(ps)


# -- runs and statistics --------------------------------------------------

def test_fixture_runs_round_trip():
    for exp_id, wires in FIXTURE["runs"].items():
        for wire in wires:
            assert es.run_as_dict(es.run_from_dict(wire)) == wire


def test_run_too_few_repetitions_refused():
    with pytest.raises(es.MalformedRunError):
        make_run("exp-sched-config", "device-a", "x86-64-apu", [1, 2], [1, 2, 3])


def test_run_negative_sample_refused():
    with pytest.raises(es.MalformedRunError):
        make_run("exp-sched-config", "device-a", "x86-64-apu",
                 [1, 2, -3], [1, 2, 3])


def test_run_undeclared_guard_shape_refused():
    wire = copy.deepcopy(FIXTURE["runs"]["exp-sched-config"][0])
    wire["guards"]["energy"]["extra"] = 1
    with pytest.raises(es.MalformedRunError):
        es.run_from_dict(wire)


def test_verdict_pair_improvement_regression_inconclusive():
    imp = es.verdict_for_pair([100, 102, 99, 101, 100], [80, 81, 79, 80, 82])
    assert imp["verdict"] == "improvement"
    assert imp["median_shift_percent"] == pytest.approx(-20.0)
    reg = es.verdict_for_pair([100, 102, 99, 101, 100], [120, 121, 119, 120, 122])
    assert reg["verdict"] == "regression"
    inc = es.verdict_for_pair([100, 102, 99, 101, 100], [100, 101, 99, 100, 101])
    assert inc["verdict"] == "inconclusive" and inc["ci_overlap"] is True


def test_verdict_pair_zero_baseline_refused():
    with pytest.raises(es.MalformedRunError):
        es.verdict_for_pair([0, 0, 0], [1, 1, 1])


# -- cross-device comparison ----------------------------------------------

def test_replicated_improvement_across_hardware():
    report = es.compare_across_devices(proposal_by_id("exp-sched-config"),
                                       runs_for("exp-sched-config"))
    assert report["verdict"] == "replicated-improvement"
    assert report["device_count"] == 3
    assert report["hardware_classes"] == [
        "arm64-sbc", "x86-64-apu", "x86-64-desktop"]
    assert all(d["primary"]["verdict"] == "improvement"
               for d in report["devices"])
    assert report["guard_regression"] is False


def test_contradicted_devices_never_consensus():
    report = es.compare_across_devices(proposal_by_id("exp-power-algo"),
                                       runs_for("exp-power-algo"))
    assert report["verdict"] == "contradicted"


def test_single_device_caps_verdict():
    runs = runs_for("exp-sched-config")[:1]
    report = es.compare_across_devices(proposal_by_id("exp-sched-config"), runs)
    assert report["verdict"] == "single-device"


def test_same_hardware_class_is_insufficient():
    runs = runs_for("exp-sched-config")
    twin = make_run("exp-sched-config", "device-d", "x86-64-apu",
                    [100, 102, 99, 101, 100], [80, 81, 79, 80, 82],
                    guards=(("energy", (50, 51, 50, 49, 50), (48, 49, 48, 47, 48)),
                            ("latency", (10, 10, 11, 10, 10), (10, 10, 10, 11, 10))))
    report = es.compare_across_devices(proposal_by_id("exp-sched-config"),
                                       [runs[0], twin])
    assert report["verdict"] == "insufficient-replication"


def test_guard_regression_blocks_replication():
    runs = runs_for("exp-sched-config")
    hungry = make_run("exp-sched-config", "device-b", "arm64-sbc",
                      [200, 202, 198, 201, 199], [160, 162, 158, 161, 159],
                      guards=(("energy", (80, 81, 80, 79, 80), (120, 121, 119, 120, 122)),
                              ("latency", (20, 21, 20, 20, 20), (20, 20, 21, 20, 20))))
    report = es.compare_across_devices(proposal_by_id("exp-sched-config"),
                                       [runs[0], hungry, runs[2]])
    assert report["verdict"] == "guard-regression"
    assert report["guard_regression"] is True


def test_unmeasured_guard_caps_replication():
    runs = runs_for("exp-sched-config")
    bare = make_run("exp-sched-config", "device-b", "arm64-sbc",
                    [200, 202, 198, 201, 199], [160, 162, 158, 161, 159],
                    guards=(("energy", (80, 81, 80, 79, 80), (76, 77, 76, 75, 76)),))
    report = es.compare_across_devices(proposal_by_id("exp-sched-config"),
                                       [runs[0], bare, runs[2]])
    assert report["guard_unmeasured"] is True
    assert report["verdict"] == "insufficient-replication"


def test_correctness_failure_blocks_replication():
    runs = runs_for("exp-sched-config")
    bad = make_run("exp-sched-config", "device-b", "arm64-sbc",
                   [200, 202, 198, 201, 199], [160, 162, 158, 161, 159],
                   guards=(("energy", (80, 81, 80, 79, 80), (76, 77, 76, 75, 76)),
                           ("latency", (20, 21, 20, 20, 20), (20, 20, 21, 20, 20))),
                   correctness="fail")
    report = es.compare_across_devices(proposal_by_id("exp-sched-config"),
                                       [runs[0], bad, runs[2]])
    assert report["verdict"] == "correctness-failure"


def test_undeclared_guard_in_run_refused():
    runs = runs_for("exp-sched-config")
    extra = make_run("exp-sched-config", "device-b", "arm64-sbc",
                     [200, 202, 198, 201, 199], [160, 162, 158, 161, 159],
                     guards=(("safety", (1, 1, 1, 1, 1), (1, 1, 1, 1, 1)),))
    with pytest.raises(es.MalformedRunError):
        es.compare_across_devices(proposal_by_id("exp-sched-config"),
                                  [runs[0], extra])


def test_mismatched_experiment_run_refused():
    runs = runs_for("exp-power-algo")
    with pytest.raises(es.IncomparableRunError):
        es.compare_across_devices(proposal_by_id("exp-sched-config"), runs)


def test_duplicate_device_run_refused():
    runs = runs_for("exp-sched-config")
    with pytest.raises(es.DuplicateExperimentError):
        es.compare_across_devices(proposal_by_id("exp-sched-config"),
                                  [runs[0], runs[0]])


def test_inconclusive_everywhere():
    flat_a = make_run("exp-sched-config", "device-a", "x86-64-apu",
                      [100, 102, 99, 101, 100], [100, 101, 99, 100, 101],
                      guards=(("energy", (50, 51, 50, 49, 50), (50, 50, 51, 50, 50)),
                              ("latency", (10, 10, 11, 10, 10), (10, 10, 10, 10, 11))))
    flat_b = make_run("exp-sched-config", "device-b", "arm64-sbc",
                      [200, 202, 198, 201, 199], [200, 201, 199, 200, 201],
                      guards=(("energy", (80, 81, 80, 79, 80), (80, 80, 81, 80, 80)),
                              ("latency", (20, 21, 20, 20, 20), (20, 20, 20, 21, 20))))
    report = es.compare_across_devices(proposal_by_id("exp-sched-config"),
                                       [flat_a, flat_b])
    assert report["verdict"] == "inconclusive"


# -- report validation, evidence, determinism ------------------------------

def test_report_validates_and_tamper_refused():
    prop = proposal_by_id("exp-sched-config"); runs = runs_for("exp-sched-config")
    report = es.compare_across_devices(prop, runs)
    assert es.validate_comparison_report(report, prop, runs)["verdict"] == "replicated-improvement"
    tampered = copy.deepcopy(report); tampered["verdict"] = "inconclusive"
    with pytest.raises(es.MalformedRunError):
        es.validate_comparison_report(tampered, prop, runs)


def test_comparison_deterministic_digest():
    prop = proposal_by_id("exp-sched-config"); runs = runs_for("exp-sched-config")
    a = es.compare_across_devices(prop, runs)
    b = es.compare_across_devices(prop, list(reversed(runs)))
    assert a == b and a["content_digest"] == b["content_digest"]
    assert es.canonical_json(a) == es.canonical_json(b)


def test_evidence_record_validates_against_banked_schema():
    jsonschema = pytest.importorskip("jsonschema")
    schema = json.loads((REPO / "docs" / "protocols" / "schemas" / "v0.1"
                         / "evidence.schema.json").read_text())
    report = es.compare_across_devices(proposal_by_id("exp-sched-config"),
                                       runs_for("exp-sched-config"))
    record = es.build_evidence_record(report, recorded_at="2026-11-12T06:00:00Z",
                                      incident_id="inc-2026-1501")
    jsonschema.Draft202012Validator(schema).validate(record)
    assert record["evidence_status"] == "lab-verified"
    assert record["content_digest"] == "sha256:" + report["content_digest"]


def test_evidence_record_bad_incident_refused():
    report = es.compare_across_devices(proposal_by_id("exp-sched-config"),
                                       runs_for("exp-sched-config"))
    with pytest.raises(es.MalformedRunError):
        es.build_evidence_record(report, recorded_at="2026-11-12T06:00:00Z",
                                 incident_id="nope")


# -- union flag and offline surface ------------------------------------------

def test_desired_exports_do_not_collide_with_banked_package():
    banked = set(SNAPSHOT)
    assert len(banked) == 924
    for name in DESIRED_EXPORTS:
        assert hasattr(es, name), name
        assert name not in banked, name
    for name in HELD_AT_SUBMODULE:
        assert hasattr(es, name), name
        assert name in banked, name


def test_module_has_no_io_surface():
    tree = ast.parse((REPO / "src" / "lifthrasir" / "experimentselection.py").read_text())
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
    assert imported <= {"__future__", "hashlib", "json", "math", "re",
                        "dataclasses", "datetime", "typing", "platform"}
    calls = {node.func.id for node in ast.walk(tree)
             if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)}
    assert "open" not in calls and "eval" not in calls and "exec" not in calls
