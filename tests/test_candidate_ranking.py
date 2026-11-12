# SPDX-License-Identifier: GPL-2.0-only
"""LIF-1003 tests for candidate ranking (lab/candidate_ranking.py).

Covers: multi-candidate ranking against a named baseline under the
LIF-1001 comparison rules, regression tracking on the primary
workload and on declared guard workloads, recorded-energy tracking
(an energy regression beyond budget rejects a fast candidate;
unmeasured energy stays unmeasured and caps status), correctness
gating, deterministic total ordering, strict fail-closed input
validation, and byte-stable deterministic reports. Everything is
recorded-sample / fixture level: no live run, no live power
reading, nothing stresses the host.
"""
import ast
import copy
import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
MOD_PATH = REPO / "lab" / "candidate_ranking.py"
FIXTURE = REPO / "tests" / "fixtures" / "lif1003" / "ranking.json"

from lab.candidate_ranking import (  # noqa: E402
    RANK_SCHEMA, UNMEASURED, MalformedRankingError, load_ranking_fixture,
    ranking_from_dict, render_markdown)

DATA = json.loads(FIXTURE.read_text(encoding="utf-8"))


def data(**over):
    d = copy.deepcopy(DATA)
    d.update(over)
    return d


def by_id(report):
    return {c["candidate_id"]: c for c in report["candidates"]}


def test_module_file_exists():
    assert MOD_PATH.is_file(), "lab/candidate_ranking.py is missing"


def test_fixture_ranking_order_and_statuses():
    report = load_ranking_fixture(FIXTURE)
    assert report["schema"] == RANK_SCHEMA
    assert report["workload_id"] == "hash-chain"
    order = [(c["rank"], c["candidate_id"], c["status"])
             for c in report["candidates"]]
    assert order == [
        (1, "cand-fast-clean", "recommended"),
        (2, "cand-plain", "acceptable"),
        (3, "cand-fast-hungry", "rejected"),
        (4, "cand-guard-regress", "rejected"),
        (5, "cand-slow", "rejected"),
    ]


def test_hand_computed_primary_shifts():
    cands = by_id(load_ranking_fixture(FIXTURE))
    assert cands["cand-fast-clean"]["primary"]["verdict"] == "improvement"
    assert cands["cand-fast-clean"]["primary"]["median_shift_percent"] == pytest.approx(-20.0)
    assert cands["cand-slow"]["primary"]["verdict"] == "regression"
    assert cands["cand-slow"]["primary"]["median_shift_percent"] == pytest.approx(20.0)
    assert cands["cand-plain"]["primary"]["verdict"] == "inconclusive"
    assert cands["cand-plain"]["primary"]["ci_overlap"] is True


def test_energy_regression_beyond_budget_rejects_fast_candidate():
    cand = by_id(load_ranking_fixture(FIXTURE))["cand-fast-hungry"]
    assert cand["primary"]["verdict"] == "improvement"  # fastest, yet:
    assert cand["energy"]["verdict"] == "regression"
    assert cand["energy"]["median_shift_percent"] == pytest.approx(30.0)
    assert "energy-regression" in cand["regressions"]
    assert cand["status"] == "rejected"


def test_energy_cost_within_budget_is_noted_not_rejected():
    d = data()
    for cand in d["candidates"]:
        if cand["candidate_id"] == "cand-fast-hungry":
            cand["energy_samples"] = [103.0, 104.0, 102.0, 103.0, 105.0]
    cand = by_id(ranking_from_dict(d))["cand-fast-hungry"]
    assert cand["energy"]["verdict"] == "regression"  # real, but small
    assert "energy-regression" not in cand["regressions"]
    assert any(n.startswith("energy-cost-within-budget")
               for n in cand["notes"])
    assert cand["status"] == "recommended"


def test_energy_improvement_tracked():
    cand = by_id(load_ranking_fixture(FIXTURE))["cand-fast-clean"]
    assert cand["energy"]["status"] == "measured"
    assert cand["energy"]["verdict"] == "improvement"
    assert cand["energy"]["median_shift_percent"] == pytest.approx(-10.0)


def test_unmeasured_energy_stays_unmeasured_and_caps_status():
    report = load_ranking_fixture(FIXTURE)
    cand = by_id(report)["cand-plain"]
    assert cand["energy"]["status"] == UNMEASURED
    assert cand["energy"]["verdict"] == UNMEASURED
    assert cand["energy"]["median_shift_percent"] is None
    assert "energy-unmeasured" in cand["notes"]
    assert cand["status"] == "acceptable"  # never recommended
    json.dumps(report)  # report stays JSON-serializable


def test_guard_regression_rejects_primary_improvement():
    cand = by_id(load_ranking_fixture(FIXTURE))["cand-guard-regress"]
    assert cand["primary"]["verdict"] == "improvement"
    assert cand["guards"][0]["workload_id"] == "sort-fixed"
    assert cand["guards"][0]["verdict"] == "regression"
    assert "guard-regression:sort-fixed" in cand["regressions"]
    assert cand["status"] == "rejected"


def test_primary_regression_rejected():
    cand = by_id(load_ranking_fixture(FIXTURE))["cand-slow"]
    assert "primary-regression" in cand["regressions"]
    assert cand["status"] == "rejected"


def test_correctness_fail_rejected_and_not_run_incomplete():
    d = data()
    for cand in d["candidates"]:
        if cand["candidate_id"] == "cand-fast-clean":
            cand["correctness"] = "fail"
        if cand["candidate_id"] == "cand-plain":
            cand["correctness"] = "not-run"
    cands = by_id(ranking_from_dict(d))
    assert cands["cand-fast-clean"]["status"] == "rejected"
    assert "correctness-fail" in cands["cand-fast-clean"]["regressions"]
    assert cands["cand-plain"]["status"] == "incomplete"


def test_missing_guard_measurement_is_incomplete():
    d = data()
    del d["guards"][0]["candidate_samples"]["cand-fast-clean"]
    cand = by_id(ranking_from_dict(d))["cand-fast-clean"]
    assert cand["guards"][0]["verdict"] == "not-measured"
    assert cand["status"] == "incomplete"


def test_deterministic_total_order_tiebreak_by_id():
    d = data(candidates=[
        {"candidate_id": "cand-b", "correctness": "pass",
         "time_samples": [0.08, 0.081, 0.079, 0.08, 0.082],
         "energy_samples": [90.0, 91.0, 89.0, 90.0, 92.0]},
        {"candidate_id": "cand-a", "correctness": "pass",
         "time_samples": [0.08, 0.081, 0.079, 0.08, 0.082],
         "energy_samples": [90.0, 91.0, 89.0, 90.0, 92.0]},
    ], guards=[])
    report = ranking_from_dict(d)
    assert [c["candidate_id"] for c in report["candidates"]] == [
        "cand-a", "cand-b"]
    assert [c["rank"] for c in report["candidates"]] == [1, 2]


def test_report_deterministic_and_markdown_stable():
    r1 = load_ranking_fixture(FIXTURE)
    r2 = ranking_from_dict(data())
    assert r1 == r2
    md1, md2 = render_markdown(r1), render_markdown(r2)
    assert md1 == md2
    assert "cand-fast-clean" in md1 and "recommended" in md1
    assert "unmeasured" in md1


# --- strict validation ---------------------------------------------------

def test_schema_and_unknown_fields_refused():
    with pytest.raises(MalformedRankingError):
        ranking_from_dict(data(schema="lifthrasir.ranking.v9.9"))
    with pytest.raises(MalformedRankingError):
        ranking_from_dict(data(surprise=True))
    d = data()
    d["candidates"][0]["surprise"] = 1
    with pytest.raises(MalformedRankingError):
        ranking_from_dict(d)


def test_duplicate_and_baseline_id_collision_refused():
    d = data()
    d["candidates"][1]["candidate_id"] = "cand-fast-clean"
    with pytest.raises(MalformedRankingError):
        ranking_from_dict(d)
    d2 = data()
    d2["candidates"][0]["candidate_id"] = "baseline"
    with pytest.raises(MalformedRankingError):
        ranking_from_dict(d2)


def test_bad_correctness_and_empty_candidates_refused():
    d = data()
    d["candidates"][0]["correctness"] = "probably-fine"
    with pytest.raises(MalformedRankingError):
        ranking_from_dict(d)
    with pytest.raises(MalformedRankingError):
        ranking_from_dict(data(candidates=[]))


def test_too_few_samples_refused():
    d = data()
    d["candidates"][0]["time_samples"] = [0.08, 0.081]
    with pytest.raises(MalformedRankingError):
        ranking_from_dict(d)
    d2 = data()
    d2["baseline"]["energy_samples"] = [100.0]
    with pytest.raises(MalformedRankingError):
        ranking_from_dict(d2)


def test_candidate_energy_without_baseline_energy_refused():
    d = data()
    d["baseline"]["energy_samples"] = None
    with pytest.raises(MalformedRankingError):
        ranking_from_dict(d)


def test_guard_unknown_candidate_refused():
    d = data()
    d["guards"][0]["candidate_samples"]["cand-ghost"] = [
        0.2, 0.21, 0.19, 0.2, 0.2]
    with pytest.raises(MalformedRankingError):
        ranking_from_dict(d)


def test_malformed_fixture_file_refused(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text("{not json", encoding="utf-8")
    with pytest.raises(MalformedRankingError):
        load_ranking_fixture(bad)
    bad2 = tmp_path / "bad2.json"
    bad2.write_text(json.dumps({"schema": "nope"}), encoding="utf-8")
    with pytest.raises(MalformedRankingError):
        load_ranking_fixture(bad2)


# --- offline / import surface -------------------------------------------

def test_import_surface_and_no_live_measurement():
    tree = ast.parse(MOD_PATH.read_text(encoding="utf-8"))
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
    allowed = set(sys.stdlib_module_names) | {"lab"}
    assert imported <= allowed, imported - allowed
    banned = {"socket", "urllib", "http", "requests", "ftplib",
              "subprocess", "os"}
    assert not (imported & banned), imported & banned
    source = MOD_PATH.read_text(encoding="utf-8").lower()
    for token in ("powercap", "rapl", "/sys/", "/proc/"):
        assert token not in source, token
