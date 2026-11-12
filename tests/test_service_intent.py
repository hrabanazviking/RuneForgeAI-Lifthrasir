# SPDX-License-Identifier: GPL-2.0-only
"""LIF-0506 tests: distinguish intentionally stopped services from
accidental failures, on recorded/fixture unit state only.

Scope: no test queries or changes live host services.  Inputs are
the JSON case table (tests/fixtures/lif0506/cases.json), recorded
systemctl-show-style fixture text, the banked LIF-0202 collector
fed with recorded fixture text, and the banked LIF-0104 fixtures /
independent oracle.  The differential baseline is the banked suite
before this slice: 372 passed.
"""
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "src"))

from lifthrasir.service_intent import (  # noqa: E402
    ACCIDENTAL,
    HEALTHY,
    INTENTIONAL,
    UNKNOWN,
    Classification,
    UnitObservation,
    classify,
    classify_many,
    should_abstain,
)
from lab import fault_oracle  # noqa: E402
from lab import systemd_collector as sc  # noqa: E402

FIX = REPO / "tests" / "fixtures" / "lif0506"
CASES = json.loads((FIX / "cases.json").read_text(encoding="utf-8"))
LAB_FIXTURES = {
    p.stem: json.loads(p.read_text(encoding="utf-8"))
    for p in sorted((REPO / "lab" / "fixtures").glob("F*.json"))
}


def _obs_for(case):
    if "fixture" in case:
        fx = LAB_FIXTURES[case["fixture"]]
        return UnitObservation.from_fixture(
            fx["golden_observed_state"]["service"])
    return UnitObservation(**case["observation"])


def test_case_table_all_verdicts():
    assert len(CASES) >= 15
    for case in CASES:
        got = classify(_obs_for(case))
        assert got.verdict == case["expected"], (
            case["name"], got.verdict, got.reasons)
        # needs_repair is true ONLY for proven accidental failures.
        assert got.needs_repair == (case["expected"] == ACCIDENTAL)
        assert should_abstain(got) == (case["expected"] != ACCIDENTAL)


def test_f02_abstention_agrees_with_independent_oracle():
    # LIF-0104's oracle abstains on F02; the classifier must call the
    # same recorded state intentional -- two independent derivations.
    fx = LAB_FIXTURES["F02"]
    ok, verdict = fault_oracle.passes(fx["golden_observed_state"], fx)
    assert ok and verdict == "abstain"
    got = classify(_obs_for({"fixture": "F02"}))
    assert got.verdict == INTENTIONAL and got.abstain


def test_f01_and_f06_are_accidental_and_oracle_faults():
    for fid in ("F01", "F06"):
        fx = LAB_FIXTURES[fid]
        ok, verdict = fault_oracle.passes(
            fx["golden_observed_state"], fx)
        assert ok and verdict == "fault"
        got = classify(_obs_for({"fixture": fid}))
        assert got.verdict == ACCIDENTAL and got.needs_repair


def test_stripping_intent_evidence_flips_abstain_to_unknown():
    # Honesty control: F02's state WITHOUT its disabled/intent
    # evidence is bare inactive -- unknown, never "intentional".
    obs = UnitObservation(unit="opt-in.service",
                          active_state="inactive", sub_state="dead")
    got = classify(obs)
    assert got.verdict == UNKNOWN and got.abstain
    assert "insufficient-evidence" in got.reasons


def test_failure_evidence_beats_disabled():
    obs = UnitObservation(unit="both.service", active_state="failed",
                          sub_state="failed", result="exit-code",
                          unit_file_state="disabled")
    got = classify(obs)
    assert got.verdict == ACCIDENTAL and got.needs_repair


def test_from_show_recorded_text():
    show = sc.parse_show((FIX / "stopped_show.txt").read_text(
        encoding="utf-8"))
    tidy = classify(UnitObservation.from_show("tidy.service",
                                              show["tidy.service"]))
    assert tidy.verdict == INTENTIONAL
    crashed = classify(UnitObservation.from_show(
        "crashed.service", show["crashed.service"]))
    assert crashed.verdict == ACCIDENTAL


def test_collector_pipeline_on_recorded_text():
    # End-to-end on recorded text only: collector parses the unit
    # listing, the classifier judges the failed unit accidental.
    report = sc.collect(
        failed_text=(REPO / "tests" / "fixtures" / "lif0202"
                     / "systemctl_failed.txt").read_text(
                         encoding="utf-8"),
        show_text=(REPO / "tests" / "fixtures" / "lif0202"
                   / "systemctl_show.txt").read_text(encoding="utf-8"),
        journal_text=(REPO / "tests" / "fixtures" / "lif0202"
                      / "journal_restarts.json").read_text(
                          encoding="utf-8"))
    by_unit = {}
    units_text = (REPO / "tests" / "fixtures" / "lif0202"
                  / "systemctl_failed.txt").read_text(encoding="utf-8")
    records, _ = sc.parse_systemctl_units(units_text)
    show = sc.parse_show((REPO / "tests" / "fixtures" / "lif0202"
                          / "systemctl_show.txt").read_text(
                              encoding="utf-8"))
    for rec in records:
        obs = UnitObservation.from_collector(
            rec, show.get(rec.unit), report.timeline)
        by_unit[rec.unit] = classify(obs)
    assert by_unit["alpha-fail.service"].verdict == ACCIDENTAL
    assert by_unit["beta-fail.service"].verdict == ACCIDENTAL
    assert by_unit["gamma-ok.service"].verdict == HEALTHY


def test_malformed_observations_are_unknown():
    assert classify(UnitObservation(unit="")).verdict == UNKNOWN
    assert classify(UnitObservation(unit="x.service")).verdict == UNKNOWN
    odd = classify(UnitObservation(unit="x.service",
                                   active_state="frobnicate"))
    assert odd.verdict == UNKNOWN and odd.abstain


def test_classify_many_preserves_order_and_is_deterministic():
    obs = [_obs_for(c) for c in CASES]
    first = classify_many(obs)
    second = classify_many(obs)
    assert first == second
    assert [c.unit for c in first] == [o.unit for o in obs]


def test_module_is_pure_recorded_data_no_live_access():
    source = (REPO / "src" / "lifthrasir"
              / "service_intent.py").read_text(encoding="utf-8")
    for token in ("import subprocess", "subprocess.", "os.system(",
                  "Popen(", "import socket", '"systemctl"',
                  "'systemctl'"):
        assert token not in source, token
    # Classification results carry their proving evidence fields.
    got = classify(UnitObservation(
        unit="off.service", active_state="inactive",
        unit_file_state="disabled"))
    assert got.verdict == INTENTIONAL
    assert "unit_file_state" in got.evidence
    assert isinstance(got, Classification)
