# SPDX-License-Identifier: GPL-2.0-only
"""LIF-0802 tests: security triage + low-false-positive baseline.

Scope: fixture data only.  Inputs are the labelled corpus
(tests/fixtures/lif0802/corpus.json -- baseline entries + detector-
shaped findings in the banked LIF-0004 v0.1 discipline) and
in-test findings.  No live detector, no live host, no response
action: triage ranks and groups, it never acts.  The differential
baseline is the banked suite before this slice: 638 passed.

Measured corpus rates are pinned to the counts this run produces:
24 cases (12 benign / 12 bad) -> benign calm 11/12, false
positives 1/12, bad surfaced 11/12, false negatives 1/12.  The
two misses are the corpus's own documented hard cases (a novel
high-claimed benign with no baseline entry; a low-claimed novel
bad with a single source), named in the corpus file itself.
"""
import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "src"))

from lifthrasir.security_triage import (  # noqa: E402
    CALM_TIERS,
    CHANGED,
    KNOWN_BAD,
    KNOWN_BENIGN,
    NOVEL,
    SURFACED_TIERS,
    Baseline,
    DetectorFinding,
    MalformedBaselineError,
    MalformedFindingError,
    evaluate_corpus,
    finding_from_dict,
    score_finding,
    tier_for_score,
    triage,
    triage_finding,
    validate_finding,
)

FIX = REPO / "tests" / "fixtures" / "lif0802"
CORPUS = json.loads((FIX / "corpus.json").read_text(encoding="utf-8"))
BASELINE = Baseline.from_dicts(CORPUS["baseline"])
REPORT = evaluate_corpus(CORPUS["cases"], BASELINE)
BY_NAME = {r.name: r for r in REPORT.results}
CASES = {c["name"]: c for c in CORPUS["cases"]}


def _finding(name):
    return validate_finding(CASES[name]["finding"])


def test_corpus_shape_and_measured_rates():
    assert CORPUS["schema"] == "lifthrasir.security-triage-corpus.v0.1"
    assert REPORT.total == 24
    assert REPORT.benign_total == 12 and REPORT.bad_total == 12
    # Measured counts, read from the corpus run itself.
    assert REPORT.benign_calm == 11 and REPORT.benign_surfaced == 1
    assert REPORT.bad_surfaced == 11 and REPORT.bad_missed == 1
    # Stated rates for this baseline: calm >= 90%, FP <= 10%,
    # bad surfaced >= 90%, FN <= 10%.
    assert REPORT.benign_calm_rate >= 0.90
    assert REPORT.false_positive_rate <= 0.10
    assert REPORT.bad_surface_rate >= 0.90
    assert REPORT.false_negative_rate <= 0.10
    # The two misses are exactly the documented hard cases.
    assert BY_NAME["benign-novel-high-admin-service"].surfaced
    assert not BY_NAME["bad-low-stealth-single-ref"].surfaced
    assert BY_NAME["bad-low-stealth-single-ref"].tier == "watch"


def test_baseline_benign_suppresses_even_critical_claims():
    got = triage_finding(
        _finding("benign-critical-claim-baseline-match"), BASELINE)
    assert got.novelty == KNOWN_BENIGN and got.tier == "suppress"
    assert "baseline-benign-match" in got.reasons
    for name in ("benign-baseline-package-update",
                 "benign-baseline-config-drift",
                 "benign-baseline-cron-update",
                 "benign-baseline-permission"):
        calm = triage_finding(_finding(name), BASELINE)
        assert calm.tier in CALM_TIERS and calm.score <= 5, name


def test_known_bad_floor_surfaces_even_medium_claims():
    got = triage_finding(_finding("bad-known-bad-package"), BASELINE)
    assert got.novelty == KNOWN_BAD and got.tier == "urgent"
    assert got.score >= 80
    assert "baseline-known-bad-match" in got.reasons


def test_empty_baseline_control_degrades_calm_rate():
    # Standing negative control: with NO baseline, the baseline-
    # matched benign findings lose their calming evidence and the
    # measured calm rate collapses below the stated 90% -- proof
    # the baseline, not the thresholds alone, does the calming.
    degraded = evaluate_corpus(CORPUS["cases"],
                               Baseline.from_dicts([]))
    assert degraded.benign_calm == 9
    assert degraded.benign_calm_rate < 0.90
    assert degraded.benign_calm_rate < REPORT.benign_calm_rate


def test_conflicting_baseline_resolves_to_bad():
    entries = [
        {"check": "binary-modified", "target_type": "file",
         "target": "/x", "observed": "sha256:same",
         "disposition": "benign"},
        {"check": "binary-modified", "target_type": "file",
         "target": "/x", "observed": "sha256:same",
         "disposition": "bad"},
    ]
    baseline = Baseline.from_dicts(entries)
    finding = validate_finding({
        "finding_id": "find-conflict", "detector": "thor-integrity",
        "check": "binary-modified", "target_type": "file",
        "target": "/x", "claimed_severity": "low",
        "observed": "sha256:same", "evidence_refs": ["ev-c1"],
        "recorded_at": "2026-11-05T12:00:00Z",
        "detail": "conflicting baseline records"})
    got = triage_finding(finding, baseline)
    assert got.novelty == KNOWN_BAD and got.tier == "urgent"


def test_novelty_labels_changed_vs_novel():
    changed = triage_finding(
        _finding("bad-high-changed-shadow-perms"), BASELINE)
    assert changed.novelty == CHANGED
    novel = triage_finding(_finding("bad-high-novel-single-ref"),
                           BASELINE)
    assert novel.novelty == NOVEL


def test_grouping_corroboration_lifts_tier():
    # Two medium novel findings on ONE target, from two detectors:
    # alone they score watch (35 with 1 ref, 43 with 2 refs);
    # grouped, the corroboration bonus (3 distinct refs across the
    # group, 2 distinct detectors) lifts the group to review (63).
    raw = CASES["benign-medium-novel-single-ref"]["finding"]
    first = dict(raw)
    second = dict(raw)
    second.update({
        "finding_id": "find-group-b", "detector": "thor-packages",
        "evidence_refs": ["ev-g2a", "ev-g2b"]})
    solo = triage_finding(validate_finding(first), BASELINE)
    assert solo.tier == "watch" and solo.score == 35
    solo2 = triage_finding(validate_finding(second), BASELINE)
    assert solo2.tier == "watch" and solo2.score == 43
    report = triage([validate_finding(first),
                     validate_finding(second)], BASELINE)
    assert len(report.groups) == 1
    group = report.groups[0]
    assert len(group.findings) == 2
    assert group.detectors == ("thor-integrity", "thor-packages")
    assert len(group.evidence_refs) == 3
    assert group.score == 63 and group.tier == "review"
    assert group.surfaced


def test_grouping_keeps_all_benign_group_suppressed():
    raw = CASES["benign-baseline-package-update"]["finding"]
    dupe = dict(raw)
    dupe["finding_id"] = "find-dupe-b01"
    report = triage([validate_finding(raw), validate_finding(dupe)],
                    BASELINE)
    assert len(report.groups) == 1
    assert report.groups[0].tier == "suppress"
    assert report.total_findings == 2  # nothing is ever dropped


def test_report_ordering_counts_and_determinism():
    findings = [validate_finding(c["finding"])
                for c in CORPUS["cases"]]
    first = triage(findings, BASELINE)
    second = triage(list(reversed(findings)), BASELINE)
    assert first == second
    counts = first.tier_counts()
    assert sum(counts.values()) == len(first.groups)
    assert first.total_findings == 24
    scores = [g.score for g in first.groups]
    assert scores == sorted(scores, reverse=True)
    assert first.groups[0].tier == "urgent"


def test_malformed_findings_and_baseline_are_refused():
    good = dict(CASES["bad-high-novel-single-ref"]["finding"])
    for break_it in (
            lambda d: d.update(claimed_severity="severe"),
            lambda d: d.update(evidence_refs=["not-an-ev-id"]),
            lambda d: d.update(evidence_refs=["ev-x", "ev-x"]),
            lambda d: d.update(finding_id="finding-1"),
            lambda d: d.update(incident_id="incident-1"),
            lambda d: d.update(recorded_at="yesterday"),
            lambda d: d.update(target=""),
            lambda d: d.update(surprise_field="x"),
            lambda d: d.pop("observed"),
    ):
        broken = dict(good)
        break_it(broken)
        with pytest.raises(MalformedFindingError):
            validate_finding(broken)
    with pytest.raises(MalformedBaselineError):
        Baseline.from_dicts([{"check": "c", "target_type": "file",
                              "target": "/x", "observed": "v",
                              "disposition": "shrug"}])
    with pytest.raises(MalformedBaselineError):
        evaluate_corpus([{"name": "n", "label": "maybe",
                          "finding": good}], BASELINE)


def test_severity_and_corroboration_are_monotonic():
    base = dict(CASES["bad-high-novel-single-ref"]["finding"])
    scores = []
    for severity in ("info", "low", "medium", "high", "critical"):
        variant = dict(base)
        variant["claimed_severity"] = severity
        scores.append(score_finding(validate_finding(variant),
                                    BASELINE)[0])
    assert scores == sorted(scores)
    one = dict(base)
    three = dict(base)
    three["evidence_refs"] = ["ev-m1", "ev-m2", "ev-m3"]
    assert (score_finding(validate_finding(three), BASELINE)[0]
            > score_finding(validate_finding(one), BASELINE)[0])


def test_tier_boundaries():
    assert tier_for_score(0) == "suppress"
    assert tier_for_score(19) == "suppress"
    assert tier_for_score(20) == "watch"
    assert tier_for_score(44) == "watch"
    assert tier_for_score(45) == "review"
    assert tier_for_score(69) == "review"
    assert tier_for_score(70) == "urgent"
    assert tier_for_score(100) == "urgent"
    assert set(SURFACED_TIERS) | set(CALM_TIERS) == {
        "suppress", "watch", "review", "urgent"}


def test_finding_round_trip_and_types():
    for case in CORPUS["cases"]:
        finding = validate_finding(case["finding"])
        assert isinstance(finding, DetectorFinding)
        assert finding_from_dict(finding.to_dict()) == finding
    with pytest.raises(MalformedFindingError):
        triage([{"not": "a finding"}], BASELINE)


def test_module_is_pure_no_action_no_live_access():
    source = (REPO / "src" / "lifthrasir"
              / "security_triage.py").read_text(encoding="utf-8")
    for token in ("import subprocess", "subprocess.", "os.system(",
                  "Popen(", "import socket", "import os",
                  "\"systemctl\"", "'systemctl'", "open("):
        assert token not in source, token
    # Triage output is a ranking for a human: it carries tiers and
    # reasons, never an action, plan or execution field.
    report = triage([_finding("bad-critical-novel-process")],
                    BASELINE)
    blob = json.dumps(report.to_dict())
    for token in ("\"action\"", "\"plan\"", "\"execute\"",
                  "\"rollback\""):
        assert token not in blob, token
