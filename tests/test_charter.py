"""LIF-0001 charter consistency tests."""
import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
CHARTER = REPO / "docs" / "CHARTER.md"
PROHIBITED_IN_SUPPORTED = [
    "bootloader", "kernel image", "firmware", "partition table",
    "ambient root", "unrestricted privileged shell", "signed-off-by", "dco",
]
REQUIRED_SECTIONS = ["vision", "success criteria", "supported", "unsupported"]
ISSUE_FIELDS = ["id", "phase", "goal", "dependencies", "risk", "scope", "test_fixture", "expected_evidence", "negative_control", "recovery"]

def _text():
    return CHARTER.read_text(encoding="utf-8")

def _section(text, start_pat, end_pat=None):
    m = re.search(start_pat, text, flags=re.I)
    assert m, f"missing section matching {start_pat!r}"
    rest = text[m.end():]
    if end_pat:
        e = re.search(end_pat, rest, flags=re.I)
        if e:
            rest = rest[:e.start()]
    return rest

def test_charter_exists():
    assert CHARTER.is_file(), "docs/CHARTER.md is missing"

def test_required_sections_present():
    text = _text().lower()
    for name in REQUIRED_SECTIONS:
        assert name in text, f"charter missing required section: {name}"

def test_issue_template_fields_present():
    text = _text().lower()
    for field in ISSUE_FIELDS:
        assert field in text, f"charter missing issue field: {field}"
    assert "lif-0001" in text
    assert "l0" in text

def test_supported_does_not_contradict_invariants():
    text = _text()
    supported = _section(text, r"##\s*Supported activities", r"##\s*Unsupported activities").lower()
    for term in PROHIBITED_IN_SUPPORTED:
        assert term not in supported, f"prohibited term {term!r} appears in supported activities"

def test_unsupported_lists_invariant_prohibitions():
    text = _text()
    unsupported = _section(text, r"##\s*Unsupported activities", r"##\s*Issue record").lower()
    for term in ["bootloader", "kernel image", "firmware", "partition", "ambient root", "signed-off-by"]:
        assert term in unsupported, f"unsupported list omits invariant prohibition: {term}"

def test_status_honesty_not_yet_implemented():
    assert "not yet implemented" in _text().lower()

def test_success_criteria_tie_to_completion():
    text = _text().lower()
    assert "completion criterion" in text
    assert "mvp complete" in text
    assert "1.0 complete" in text
    assert "offline" in text
