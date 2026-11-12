"""LIF-0002 architecture ADR consistency tests."""
import os
import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
ADR = Path(os.environ.get("LIF_ADR_PATH", REPO / "docs" / "architecture" / "ADR-0002-architecture.md"))
CHARTER = REPO / "docs" / "CHARTER.md"

REQUIRED_SECTIONS = [
    "architecture diagram",
    "processes",
    "message ownership",
    "failure propagation",
    "consistency with the charter",
]
PLANES = ["heimdall", "mimir", "replicater", "policy", "broker", "eir", "thor"]
ISSUE_FIELDS = [
    "id", "phase", "goal", "dependencies", "risk", "scope",
    "test_fixture", "expected_evidence", "negative_control", "recovery",
]


def _text():
    return ADR.read_text(encoding="utf-8")


def _section(text, start_pat, end_pat=None):
    m = re.search(start_pat, text, flags=re.I)
    assert m, "missing section matching " + repr(start_pat)
    rest = text[m.end():]
    if end_pat:
        e = re.search(end_pat, rest, flags=re.I)
        if e:
            rest = rest[:e.start()]
    return rest


def test_adr_exists():
    assert ADR.is_file(), "docs/architecture/ADR-0002-architecture.md is missing"


def test_required_sections_present():
    text = _text().lower()
    for name in REQUIRED_SECTIONS:
        assert name in text, "ADR missing required section: " + name


def test_diagram_block_present_with_planes():
    text = _text()
    assert "```" in text, "ADR has no diagram code block"
    diagram = _section(text, r"##\s*Architecture diagram", r"##\s*Processes").lower()
    for plane in ["heimdall", "policy", "broker"]:
        assert plane in diagram, "diagram omits plane: " + plane


def test_all_planes_named_in_processes():
    text = _text()
    processes = _section(text, r"##\s*Processes", r"##\s*Message ownership").lower()
    for plane in PLANES:
        assert plane in processes, "process inventory omits: " + plane
    text_low = text.lower()
    for proc in ["lifthrasir-sensor", "lifthrasir-policy", "lifthrasir-broker", "lifthrasir-lab", "watchdog"]:
        assert proc in text_low, "ADR omits process: " + proc


def test_three_competing_choices_with_decisions():
    text = _text()
    decisions = re.findall(r"^## Decision D\d", text, flags=re.M)
    assert len(decisions) >= 3, "ADR must record at least three decisions, found " + str(len(decisions))
    for label in ["Decision D1", "Decision D2", "Decision D3"]:
        sec = _section(text, re.escape("## " + label), r"## Decision D\d|## Confirmed").lower()
        assert "options considered" in sec, label + " lacks competing options"
        assert sec.count("option a") >= 1 and "option b" in sec and "option c" in sec, label + " lacks three competing options"
        assert "decision" in sec and "consequences" in sec, label + " lacks decision or consequences"


def test_competing_alternatives_are_real():
    text = _text().lower()
    for term in ["monolith", "rust", "go", "d-bus", "unix", "so_peercred", "sqlite", "postgres"]:
        assert term in text, "ADR omits competing alternative or chosen tech: " + term


def test_message_ownership_rules():
    text = _text()
    ownership = _section(text, r"##\s*Message ownership", r"##\s*Failure propagation").lower()
    assert "never commands" in ownership, "ownership must state observations are never commands"
    assert "only" in ownership and "policy" in ownership, "ownership must reserve authorization minting to policy"
    assert "repairplan" in ownership, "ownership must cover the RepairPlan envelope"
    assert "one-time" in ownership, "authorization tokens must be one-time"


def test_failure_propagation_fail_closed():
    text = _text()
    failure = _section(text, r"##\s*Failure propagation", r"##\s*Decision D1").lower()
    for term in ["fail closed", "deny by default", "broker down", "expired", "rollback", "emergency stop"]:
        assert term in failure, "failure propagation omits: " + term


def test_section4_confirmations_present():
    text = _text().lower()
    for term in ["rust", "python", "sqlite", "qemu/kvm", "landlock", "seccomp", "kde/qt"]:
        assert term in text, "ADR omits section 4 confirmation: " + term


def test_charter_consistency_and_invariants():
    text = _text().lower()
    assert "separation of powers" in text
    for term in ["bootloader", "kernel image", "firmware", "partition", "ambient root"]:
        assert term in text, "ADR consistency section omits invariant term: " + term
    assert "signed-off-by" in text, "ADR must keep the human DCO gate"
    assert "disposable" in text, "ADR must keep experiments in disposable environments"
    assert "opt-in" in text, "ADR must keep federation opt-in"


def test_adr_does_not_claim_implementation():
    text = _text().lower()
    assert "not yet implemented" in text, "ADR must state the system is not yet implemented"
    charter = CHARTER.read_text(encoding="utf-8").lower()
    assert "not yet implemented" in charter


def test_issue_template_fields_present():
    text = _text().lower()
    for field in ISSUE_FIELDS:
        assert field in text, "ADR missing issue field: " + field
    assert "lif-0002" in text
    assert "l0" in text
