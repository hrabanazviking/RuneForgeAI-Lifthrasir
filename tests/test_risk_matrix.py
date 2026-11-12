"""LIF-0003 risk matrix and consent-mode consistency tests.

Parses the tables in docs/RISK-MATRIX.md and verifies: all six tiers
defined, consent strictness monotonic with tier, every worked example
classified consistently (consent never weaker than its tier floor),
and the section-0 prohibited actions never classified as auto-allowed.
"""
import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
DOC = REPO / "docs" / "RISK-MATRIX.md"

EXPECTED_TIER_CONSENT = {
    "L0": "none",
    "L1": "standing-opt-in",
    "L2": "session-blanket",
    "L3": "allowlist-notice",
    "L4": "per-action",
    "L5": "human-only",
}
AUTO_ALLOWED = {"none", "standing-opt-in", "session-blanket"}
PROHIBITED_KEYWORDS = [
    "bootloader", "kernel image", "partition table", "encryption",
    "ambient root", "signed-off-by", "fuzzing", "trust roots", "home files",
]

def _text():
    return DOC.read_text(encoding="utf-8")

def _rows(text, prefix):
    out = []
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("| " + prefix):
            cells = [c.strip() for c in line.strip("|").split("|")]
            out.append(cells)
    return out

def _consent_ranks():
    ranks = {}
    for line in _text().splitlines():
        m = re.match(r"\| ([a-z][a-z\-]*) \| (\d+) \|", line.strip())
        if m:
            ranks[m.group(1)] = int(m.group(2))
    return ranks

def _matrix():
    matrix = {}
    for cells in _rows(_text(), "L"):
        if re.fullmatch(r"L[0-5]", cells[0]):
            matrix[cells[0]] = cells[2]
    return matrix

def _examples():
    return _rows(_text(), "EX-")

def _prohibited():
    return _rows(_text(), "P-")

def test_doc_exists():
    assert DOC.is_file(), "docs/RISK-MATRIX.md is missing"

def test_all_six_tiers_defined():
    matrix = _matrix()
    assert sorted(matrix) == ["L0", "L1", "L2", "L3", "L4", "L5"], matrix

def test_consent_modes_defined_with_unique_ranks():
    ranks = _consent_ranks()
    for mode in list(EXPECTED_TIER_CONSENT.values()) + ["never"]:
        assert mode in ranks, f"consent mode not defined: {mode}"
    assert sorted(ranks.values()) == list(range(len(ranks))), ranks

def test_tier_consent_matches_canonical():
    assert _matrix() == EXPECTED_TIER_CONSENT

def test_consent_strictness_monotonic_with_tier():
    ranks = _consent_ranks()
    seq = [ranks[EXPECTED_TIER_CONSENT[t]] for t in ["L0", "L1", "L2", "L3", "L4", "L5"]]
    assert seq == sorted(seq) and len(set(seq)) == 6, seq
    assert ranks["never"] > ranks["human-only"]

def test_examples_cover_every_tier():
    tiers = {}
    for cells in _examples():
        tiers.setdefault(cells[1], 0)
        tiers[cells[1]] += 1
    for tier in ["L0", "L1", "L2", "L3", "L4", "L5"]:
        assert tiers.get(tier, 0) >= 2, f"tier {tier} has too few examples: {tiers}"
    assert len(_examples()) >= 18

def test_every_example_consistent_with_tier_floor():
    ranks = _consent_ranks()
    for cells in _examples():
        ex_id, tier, consent = cells[0], cells[1], cells[2]
        assert tier in EXPECTED_TIER_CONSENT, f"{ex_id}: unknown tier {tier}"
        floor = ranks[EXPECTED_TIER_CONSENT[tier]]
        assert ranks[consent] >= floor, f"{ex_id}: consent {consent} weaker than {tier} floor"
        assert consent != "never", f"{ex_id}: worked example must not be a prohibited action"

def test_prohibited_actions_present_and_never_allowed():
    rows = _prohibited()
    assert len(rows) >= 8, f"only {len(rows)} prohibited actions"
    for cells in rows:
        p_id, tier, consent = cells[0], cells[1], cells[2]
        assert tier == "L5", f"{p_id}: prohibited action not in L5"
        assert consent == "never", f"{p_id}: prohibited action consent is {consent}, not never"
        assert consent not in AUTO_ALLOWED, f"{p_id}: prohibited action is auto-allowed"

def test_prohibited_cover_section0_objects():
    blob = " ".join(cells[3].lower() for cells in _prohibited())
    for kw in PROHIBITED_KEYWORDS:
        assert kw in blob, f"prohibited table omits section-0 object: {kw}"

def test_no_example_auto_allows_a_prohibited_object():
    for cells in _examples():
        if cells[2] in AUTO_ALLOWED:
            body = cells[3].lower()
            for kw in ["bootloader", "partition table", "signed-off-by"]:
                assert kw not in body, f"{cells[0]}: auto-allowed example mentions {kw}"

def test_human_review_recorded_pending_not_claimed():
    text = _text().lower()
    assert "human review:" in text and "pending" in text
    assert "human review: complete" not in text
    assert "reviewed and approved" not in text

def test_issue_record_fields_present():
    text = _text().lower()
    for field in ["id: lif-0003", "phase: p0", "goal", "dependencies", "risk_tier", "scope", "test_fixture", "expected_evidence", "negative_control", "recovery_or_undo", "limitations"]:
        assert field in text, f"issue record missing field: {field}"
