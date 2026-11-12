# SPDX-License-Identifier: GPL-2.0-only
"""Tests for LIF-1401: upstream patch dossier + b4 workflow support.

All inputs are fixtures: a MAINTAINERS excerpt with invented
fixture people, and recorded candidate dossiers in the LIF-0904
shape.  No kernel tree, maintainer, or network is involved, and
nothing here sends or submits anything -- the module under test
has no such surface (pinned by the AST test at the bottom).
"""
import ast
import copy
import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

import lifthrasir.upstreamforge as uf
from lifthrasir.patchdossier import (
    DCOViolationError,
    UpstreamClaimError,
    build_dossier,
)
from lifthrasir.upstreamforge import (
    FALLBACK_LIST,
    SECURITY_TEAM_ADDRESS,
    AgentSubmissionError,
    DisclosureRouteError,
    MaintainersError,
    MalformedUpstreamError,
    build_upstream_dossier,
    parse_maintainers,
    summarize_upstream,
)

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "lif1401"
MAINTAINERS_TEXT = (FIXTURES / "maintainers.txt").read_text()
FIXTURE = json.loads((FIXTURES / "upstream.json").read_text())


def record(name, **overrides):
    rec = copy.deepcopy(FIXTURE[name])
    rec["maintainers"] = MAINTAINERS_TEXT
    rec.update(overrides)
    return rec


def build(name, **overrides):
    return build_upstream_dossier(record(name, **overrides))


# --- MAINTAINERS parsing -------------------------------------------

def test_parse_sections_and_fields():
    index = parse_maintainers(MAINTAINERS_TEXT)
    assert len(index.entries) == 4
    first = index.entries[0]
    assert first.section == "FIXTURE COUNTER DRIVER"
    assert first.maintainers == ("fiona@fixture.example",)
    assert first.reviewers == ("ravi@fixture.example",)
    assert first.lists == ("fixture-counter@lists.example",)
    assert first.status == "Maintained"
    assert first.patterns == ("drivers/fixture/",)
    core = index.entries[2]
    assert core.exclusions == ("net/fixture/legacy/",)


def test_parse_tab_separated_fields():
    text = ("TAB SECTION\nM:\tTab Person <tab@fixture.example>\n"
            "F:\tdrivers/fixture/\n")
    index = parse_maintainers(text)
    assert index.entries[0].maintainers == ("tab@fixture.example",)


def test_field_before_any_header_refused():
    with pytest.raises(MaintainersError):
        parse_maintainers("M: Nobody <nobody@fixture.example>\n")


def test_address_without_email_refused():
    with pytest.raises(MaintainersError):
        parse_maintainers("SOME SECTION\nM: No Address Here\n")


def test_empty_maintainers_refused():
    with pytest.raises(MaintainersError):
        parse_maintainers("   \n")


def test_lookup_directory_prefix_pattern():
    index = parse_maintainers(MAINTAINERS_TEXT)
    hits = index.lookup("drivers/fixture/fixture_counter.c")
    assert [e.section for e in hits] == ["FIXTURE COUNTER DRIVER"]


def test_lookup_wildcard_pattern():
    index = parse_maintainers(MAINTAINERS_TEXT)
    hits = index.lookup("include/fixture/fixture_counter.h")
    assert [e.section for e in hits] == ["FIXTURE COUNTER HEADERS"]


def test_lookup_exclusion_routes_to_legacy_section():
    index = parse_maintainers(MAINTAINERS_TEXT)
    hits = index.lookup("net/fixture/legacy/old_proto.c")
    assert [e.section for e in hits] == ["FIXTURE LEGACY NETWORKING"]


def test_lookup_networking_core_not_excluded():
    index = parse_maintainers(MAINTAINERS_TEXT)
    hits = index.lookup("net/fixture/core.c")
    assert [e.section for e in hits] == ["FIXTURE NETWORKING CORE"]


def test_recipients_order_and_dedupe():
    index = parse_maintainers(MAINTAINERS_TEXT)
    rec = index.recipients_for(("drivers/fixture/fixture_counter.c",
                                "include/fixture/fixture_counter.h"))
    assert rec["to"] == ["fiona@fixture.example", "hana@fixture.example"]
    assert rec["cc"] == ["ravi@fixture.example",
                          "fixture-counter@lists.example",
                          "fixture-headers@lists.example"]
    assert rec["fallback_files"] == []


def test_recipients_fallback_flagged_never_dropped():
    index = parse_maintainers(MAINTAINERS_TEXT)
    rec = index.recipients_for(("sound/fixture/unclaimed.c",))
    assert rec["fallback_files"] == ["sound/fixture/unclaimed.c"]
    assert FALLBACK_LIST in rec["cc"]
    assert rec["per_file"][0]["fallback"] is True


# --- dossier build + readiness --------------------------------------

def test_complete_bug_awaits_human_review():
    d = build("complete_bug")
    assert d.readiness == "awaiting-human-review"
    assert d.route == "public-lists"
    assert d.recipients["to"] == ["fiona@fixture.example",
                                  "hana@fixture.example"]
    out = d.to_dict()
    assert out["submitted"] is False
    assert out["upstream_outcome"] == "not-submitted"
    assert out["agent_signed_dco"] is False


def test_digest_is_deterministic():
    a, b = build("complete_bug"), build("complete_bug")
    assert a.digest == b.digest
    assert json.dumps(a.canonical(), sort_keys=True) == \
        json.dumps(b.canonical(), sort_keys=True)


def test_candidate_digest_pin_accepted():
    pin = build_dossier(copy.deepcopy(FIXTURE["complete_bug"]["candidate"])).digest
    d = build("complete_bug", candidate_digest=pin)
    assert d.candidate_digest == pin


def test_candidate_digest_pin_mismatch_refused():
    bad = "sha256:" + "0" * 64
    with pytest.raises(MalformedUpstreamError):
        build("complete_bug", candidate_digest=bad)


def test_complete_with_submission_review_is_ready():
    d = build("complete_bug",
              submission_review=copy.deepcopy(FIXTURE["submission_review"]))
    assert d.readiness == "ready-for-human-submission"
    assert d.gaps() == []


def test_failed_submission_review_item_stays_awaiting():
    review = copy.deepcopy(FIXTURE["submission_review"])
    review["items"][0]["state"] = "fail"
    d = build("complete_bug", submission_review=review)
    assert d.readiness == "awaiting-human-review"
    assert "human-submission-review" in d.gaps()


def test_checklist_pre_review_items_ok_for_complete_candidate():
    d = build("complete_bug")
    checks = {c["item"]: c["ok"] for c in d.checklist()}
    for item, ok in checks.items():
        if item == "human-submission-review":
            assert ok is False
        else:
            assert ok is True, item


def test_incomplete_candidate_readiness_and_gaps():
    d = build("incomplete")
    assert d.readiness == "incomplete"
    gaps = d.gaps()
    assert "candidate-dossier-complete" in gaps
    assert "candidate: reproducer leg: reversal-fails-again" in gaps
    assert "candidate: human code review missing" in gaps


def test_blocked_candidate_readiness():
    d = build("blocked")
    assert d.candidate.verdict == "blocked"
    assert d.readiness == "blocked"
    checks = {c["item"]: c["ok"] for c in d.checklist()}
    assert checks["candidate-not-blocked"] is False
    # the firmware file is claimed by no fixture section: fallback
    assert d.recipients["fallback_files"] == ["drivers/firmware/fixture_fw.c"]


# --- guards: agents prepare, never send, never sign ------------------

def test_agent_submission_reviewer_refused():
    review = copy.deepcopy(FIXTURE["submission_review"])
    review["reviewer_kind"] = "agent"
    with pytest.raises(AgentSubmissionError):
        build("complete_bug", submission_review=review)


def test_agent_author_kind_refused():
    author = {"name": "Hilde Human", "email": "hilde@fixture.example",
              "kind": "agent"}
    with pytest.raises(AgentSubmissionError):
        build("complete_bug", author=author)


def test_agent_named_as_author_refused():
    author = {"name": "Lifthrasir Agent", "email": "agent@fixture.example"}
    with pytest.raises(AgentSubmissionError):
        build("complete_bug", author=author)


def test_submission_act_keys_refused():
    with pytest.raises(AgentSubmissionError):
        build("complete_bug", action="send")
    rec = record("complete_bug")
    rec["submitted"] = True
    with pytest.raises(AgentSubmissionError):
        build_upstream_dossier(rec)


def test_dco_tag_in_cover_letter_refused():
    cover = {"subject": "drivers/fixture: arm the counter",
             "body": "Body text.\n\nSigned-off-by: Hilde Human <hilde@fixture.example>"}
    with pytest.raises(DCOViolationError):
        build("complete_bug", cover_letter=cover)


def test_upstream_acceptance_claim_refused():
    with pytest.raises(UpstreamClaimError):
        build("complete_bug", evidence_status="upstream-accepted")


def test_unknown_field_refused():
    with pytest.raises(MalformedUpstreamError):
        build("complete_bug", priority="high")


def test_bad_author_email_refused():
    author = {"name": "Hilde Human", "email": "not-an-email"}
    with pytest.raises(MalformedUpstreamError):
        build("complete_bug", author=author)


# --- disclosure routing -----------------------------------------------

def test_security_route_is_private_only():
    d = build("security")
    assert d.route == "private-security"
    assert d.recipients["to"] == [SECURITY_TEAM_ADDRESS]
    assert d.recipients["cc"] == []
    assert d.readiness == "awaiting-human-review"


def test_security_with_public_route_claim_refused():
    with pytest.raises(DisclosureRouteError):
        build("security", route="public-lists")


def test_bug_with_private_route_claim_refused():
    with pytest.raises(DisclosureRouteError):
        build("complete_bug", route="private-security")


# --- b4 workflow plan (data only, never executed) ----------------------

def test_b4_plan_bug_route_shape():
    d = build("complete_bug")
    plan = d.b4_plan()
    steps = [s["step"] for s in plan]
    assert steps[0] == "identify-maintainers"
    assert steps[-1] == "submission-decision"
    by_step = {s["step"]: s for s in plan}
    assert by_step["submission-decision"]["actor"] == "human"
    assert by_step["author-signoff"]["actor"] == "human"
    assert by_step["dry-run"]["actor"] == "human"
    for s in plan:
        if s["actor"] == "agent":
            assert not (s["command"] and "send" in s["command"]), s


def test_b4_plan_security_route_has_no_public_send():
    d = build("security")
    plan = d.b4_plan()
    assert plan[-1]["step"] == "human-sends-privately"
    assert plan[-1]["actor"] == "human"
    for s in plan:
        assert not (s["command"] and "b4 send" in s["command"]), s


# --- evidence record + summary ------------------------------------------

def test_evidence_fields_shape():
    d = build("complete_bug")
    rec = d.evidence_fields(
        recorded_at="2026-11-12T00:00:00Z", host_local_id="purpleraider",
        evidence_id="ev-lif1401-fixture-1",
        tool_versions={"python": "3.14.8", "pytest": "9.1.1"})
    assert rec["schema"] == "lifthrasir.evidence.v0.1"
    assert rec["kind"] == "upstream-dossier"
    assert rec["content_digest"] == d.digest
    assert rec["evidence_status"] == d.candidate.evidence_status
    assert d.candidate.digest in rec["artifact_refs"]
    assert d.maintainers_digest in rec["artifact_refs"]
    with pytest.raises(MalformedUpstreamError):
        d.evidence_fields("2026-11-12T00:00:00Z", "purpleraider",
                          "ev-x", {})


def test_maintainers_text_is_pinned_by_digest():
    a = build("complete_bug")
    changed = MAINTAINERS_TEXT + "\nEXTRA SECTION\nM: Eve Extra <eve@fixture.example>\nF: drivers/extra/\n"
    b = build("complete_bug", maintainers=changed)
    assert a.maintainers_digest != b.maintainers_digest
    assert a.digest != b.digest


def test_summarize_upstream():
    dossiers = [build(name) for name in
                ("complete_bug", "incomplete", "blocked", "security")]
    summary = summarize_upstream(dossiers)
    assert summary["total"] == 4
    assert summary["submitted"] == 0
    assert summary["readiness"] == {
        "blocked": 1, "incomplete": 1,
        "awaiting-human-review": 2, "ready-for-human-submission": 0}
    assert summary["ready_ids"] == []


# --- no execution surface ------------------------------------------------

def test_module_has_no_execution_surface():
    source = Path(uf.__file__).read_text()
    tree = ast.parse(source)
    banned = {"subprocess", "socket", "urllib", "http", "smtplib",
              "ftplib", "os", "sys", "pathlib", "shutil", "requests"}
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                imported.add(node.module.split(".")[0])
    assert not (imported & banned), imported & banned
    assert not hasattr(uf, "send")
    assert not hasattr(uf, "submit")
