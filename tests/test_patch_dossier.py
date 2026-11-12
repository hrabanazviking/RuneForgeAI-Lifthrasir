"""Tests for the candidate patch dossier (LIF-0904).

Fixture records only: recorded diffs, run tallies and a fixture
review. No kernel is built or booted, no patch is applied or sent,
and no DCO tag is ever produced.
"""
import ast
import copy
import json
import pathlib
import sys

REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO.joinpath(chr(115) + chr(114) + chr(99))))

import pytest

from lifthrasir import patchdossier as pd

FIX = REPO / "tests" / "fixtures" / "lif0904"


def _patch(name="candidate.patch"):
    return (FIX / name).read_text(encoding="utf-8")


def _data(**over):
    data = json.loads((FIX / "dossier.json").read_text(encoding="utf-8"))
    data["patch_diff"] = _patch()
    data["reproducer"]["script"] = (FIX / "reproducer.sh").read_text(
        encoding="utf-8")
    data.update(over)
    return data


def _review(state="pass", kind="human", reviewer="A. Human Reviewer"):
    return {
        "reviewer": reviewer, "reviewer_kind": kind,
        "items": [{"item": i, "state": state} for i in pd.REVIEW_ITEMS],
        "notes": "fixture review over recorded evidence only",
    }


def _complete():
    return pd.build_dossier(_data(review=_review()))


# --- diff accounting -------------------------------------------------

def test_diff_stats_fixture_patch():
    stats = pd.parse_unified_diff(_patch())
    assert stats.files == ("drivers/fixture/fixture_counter.c",)
    assert stats.hunks == 1 and stats.added == 1 and stats.removed == 1
    assert stats.is_minimal and stats.high_risk_paths == ()
    assert stats.digest.startswith("sha256:")


def test_diff_rejects_non_diff_and_binary():
    with pytest.raises(pd.MalformedDossierError):
        pd.parse_unified_diff("just some prose, no diff here")
    with pytest.raises(pd.MalformedDossierError):
        pd.parse_unified_diff(_patch() + "\nBinary files a/x and b/x differ\n")


def test_diff_rejects_dco_tag():
    bad = _patch() + "\nSigned-off-by: Agent <a@example.invalid>\n"
    with pytest.raises(pd.DCOViolationError):
        pd.parse_unified_diff(bad)


def test_high_risk_diff_blocks_dossier():
    d = pd.build_dossier(_data(patch_diff=_patch("high_risk.patch"),
                               review=_review()))
    assert d.diff.high_risk_paths == ("boot/efi/grub.cfg",)
    assert d.verdict == pd.VERDICT_BLOCKED


# --- differential legs -----------------------------------------------

def test_complete_dossier_verdict_and_rung():
    d = _complete()
    assert d.verdict == pd.VERDICT_COMPLETE and d.missing() == []
    assert d.reproducer.differential_ok
    assert d.evidence_status == "human-reviewed"
    assert d.to_dict()["upstream_submitted"] is False


def test_missing_reversal_leg_is_incomplete():
    data = _data(review=_review())
    data["reproducer"]["reversed_patch"] = None
    d = pd.build_dossier(data)
    assert d.verdict == pd.VERDICT_INCOMPLETE
    assert "reproducer leg: reversal-fails-again" in d.missing()
    assert d.evidence_status == "reproducer"


def test_baseline_must_fail_every_run_and_enough_runs():
    data = _data(review=_review())
    data["reproducer"]["baseline"] = {"runs": 5, "failures": 4}
    d = pd.build_dossier(data)
    assert d.reproducer.legs()["baseline-fails"] is False
    data["reproducer"]["baseline"] = {"runs": 2, "failures": 2}
    d = pd.build_dossier(data)
    assert d.reproducer.legs()["baseline-fails"] is False


def test_candidate_failure_and_control_mismatch_named():
    data = _data(review=_review())
    data["reproducer"]["candidate"] = {"runs": 5, "failures": 1}
    data["reproducer"]["control"] = {"runs": 3, "failures": 1}
    d = pd.build_dossier(data)
    legs = d.reproducer.legs()
    assert legs["candidate-passes"] is False
    assert legs["control-as-expected"] is False
    assert d.verdict == pd.VERDICT_INCOMPLETE


def test_impossible_tally_refused():
    with pytest.raises(pd.MalformedDossierError):
        pd.RunTally(runs=3, failures=4)


# --- review gates ------------------------------------------------------

def test_no_review_is_incomplete_not_reviewed():
    d = pd.build_dossier(_data())
    assert d.verdict == pd.VERDICT_INCOMPLETE
    assert "human code review missing" in d.missing()
    assert d.evidence_status == "lab-verified"


def test_agent_reviewer_refused_by_name():
    with pytest.raises(pd.AgentReviewError):
        pd.build_dossier(_data(review=_review(kind="agent")))


def test_failed_review_item_blocks():
    review = _review()
    review["items"][3] = {"item": pd.REVIEW_ITEMS[3], "state": "fail"}
    d = pd.build_dossier(_data(review=review))
    assert d.verdict == pd.VERDICT_BLOCKED


def test_partial_review_is_incomplete():
    review = _review()
    review["items"] = review["items"][:4]
    d = pd.build_dossier(_data(review=review))
    assert d.verdict == pd.VERDICT_INCOMPLETE
    assert "human code review incomplete or failed" in d.missing()


def test_na_only_for_allowed_item_with_reason():
    allowed = "compiler-and-analyzer-logs-clean-or-explained"
    review = _review()
    review["items"] = [
        {"item": e["item"],
         "state": "na" if e["item"] == allowed else "pass"}
        for e in review["items"]]
    review["na_reasons"] = [{"item": allowed,
                             "reason": "no compiler run in fixture scope"}]
    d = pd.build_dossier(_data(review=review))
    assert d.verdict == pd.VERDICT_COMPLETE
    review2 = _review()
    review2["items"][0] = {"item": pd.REVIEW_ITEMS[0], "state": "na"}
    review2["na_reasons"] = [{"item": pd.REVIEW_ITEMS[0],
                              "reason": "not applicable"}]
    d2 = pd.build_dossier(_data(review=review2))
    assert d2.verdict == pd.VERDICT_INCOMPLETE


def test_unknown_review_item_refused():
    review = _review()
    review["items"].append({"item": "looks-fine-to-me", "state": "pass"})
    with pytest.raises(pd.MalformedDossierError):
        pd.build_dossier(_data(review=review))


# --- claims, shape, minimality ----------------------------------------

def test_upstream_rungs_refused_outright():
    for rung in ("upstream-submitted", "upstream-accepted",
                 "deployed-with-monitoring"):
        with pytest.raises(pd.UpstreamClaimError):
            pd.build_dossier(_data(evidence_status=rung))


def test_floating_release_and_bad_commit_refused():
    with pytest.raises(pd.MalformedDossierError):
        pd.build_dossier(_data(kernel_release="latest"))
    with pytest.raises(pd.MalformedDossierError):
        pd.build_dossier(_data(affected_commit="main"))
    with pytest.raises(pd.MalformedDossierError):
        pd.build_dossier(_data(arch="riscv64"))


def test_oversized_diff_not_minimal():
    big = _patch() * 60  # same file, 60 hunks, 120 changed lines
    stats = pd.parse_unified_diff(big)
    assert stats.changed_lines == 120
    huge_files = "".join(
        f"diff --git a/f{i}.c b/f{i}.c\n--- a/f{i}.c\n+++ b/f{i}.c\n"
        f"@@ -1,1 +1,1 @@\n-old\n+new\n" for i in range(9))
    d = pd.build_dossier(_data(patch_diff=huge_files, review=_review()))
    assert not d.diff.is_minimal and d.verdict == pd.VERDICT_INCOMPLETE


def test_failed_matrix_row_blocks_completeness():
    data = _data(review=_review())
    data["test_matrix"][0]["outcome"] = "failed"
    d = pd.build_dossier(data)
    assert d.verdict == pd.VERDICT_INCOMPLETE
    assert "test matrix has failed/error rows" in d.missing()


def test_digest_deterministic_and_sensitive():
    a, b = _complete(), _complete()
    assert a.digest == b.digest and a.to_dict() == b.to_dict()
    data = _data(review=_review())
    data["title"] = "a different title"
    assert pd.build_dossier(data).digest != a.digest


# --- evidence record + summary ----------------------------------------

def test_evidence_record_shape():
    d = _complete()
    rec = d.evidence_fields(
        recorded_at="2026-11-12T10:00:00Z", host_local_id="purpleraider",
        evidence_id="ev-lif0904-fixture-1",
        tool_versions={"python": "3.14.8", "pytest": "9.1.1"},
        baseline_evidence_id="ev-lif0904-baseline-1")
    assert rec["schema"] == "lifthrasir.evidence.v0.1"
    assert rec["kind"] == "differential-run"
    assert rec["content_digest"] == d.digest
    assert rec["evidence_status"] == "human-reviewed"
    assert rec["source"]["component"] == "lab"
    assert rec["baseline_evidence_id"] == "ev-lif0904-baseline-1"
    with pytest.raises(pd.MalformedDossierError):
        d.evidence_fields(recorded_at="2026-11-12T10:00:00Z",
                          host_local_id="purpleraider",
                          evidence_id="ev-x-1", tool_versions={})


def test_summarize_dossiers():
    incomplete = pd.build_dossier(_data())
    s = pd.summarize_dossiers([_complete(), incomplete])
    assert s["total"] == 2
    assert s["verdicts"]["complete"] == 1
    assert s["verdicts"]["incomplete"] == 1
    assert s["complete_ids"] == ["dossier-fixture-counter-1"]


def test_module_has_no_io_machinery():
    src = (REPO / "src" / "lifthrasir" / "patchdossier.py").read_text(
        encoding="utf-8")
    tree = ast.parse(src)
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
    assert imported <= {"__future__", "hashlib", "json", "re",
                        "dataclasses", "typing"}
    for banned in ("subprocess", "socket", "os.", "open(", "Path"):
        assert banned not in src
