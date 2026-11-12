"""Tests for LIF-1601: release support, incident response, governance
and contributor continuity (stewardship registry).

SPDX-License-Identifier: GPL-2.0-only
"""
import json
import os
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from lifthrasir import stewardship as st  # noqa: E402

FIXTURE_PATH = Path(os.environ.get(
    "LIF_STEWARDSHIP_FIXTURE",
    str(Path(__file__).parent / "fixtures" / "lif1601" / "stewardship.json")))
FIXTURE = json.loads(FIXTURE_PATH.read_text())
AT = "2026-11-12T00:00:00Z"
ANNA = "anna-maintainer"
BJORN = "bjorn-maintainer"
CELIA = "celia-maintainer"
AGENT = "yrsa-agent"


def empty_registry():
    registry = st.StewardshipRegistry()
    for wire in FIXTURE["maintainers"]:
        registry.register_maintainer(wire)
    return registry


def full_registry():
    registry = empty_registry()
    for wire in FIXTURE["releases"]:
        registry.register_release(wire)
    for wire in FIXTURE["areas"]:
        registry.assign_area(wire)
    for wire in FIXTURE["incidents"]:
        registry.register_incident(wire)
    for wire in FIXTURE["proposals"]:
        registry.register_proposal(wire)
    for wire in FIXTURE["audits"]:
        registry.register_audit(wire)
    for wire in FIXTURE["plugin_apis"]:
        registry.register_plugin_api(wire)
    return registry


def own_security_incident(registry):
    wire = st.make_incident("security", "critical", "Own security case",
                            ANNA, "2026-11-11T08:00:00Z")
    return registry.register_incident(wire)


# -- maintainers -------------------------------------------------------

def test_maintainer_round_trips():
    maintainer = st.maintainer_from_dict(FIXTURE["maintainers"][0])
    assert maintainer.is_human
    assert st.maintainer_to_dict(maintainer) == FIXTURE["maintainers"][0]
    agent = st.maintainer_from_dict(FIXTURE["maintainers"][3])
    assert not agent.is_human


def test_maintainer_missing_key_refused():
    wire = dict(FIXTURE["maintainers"][0])
    del wire["email"]
    with pytest.raises(st.MalformedStewardError):
        st.maintainer_from_dict(wire)


def test_maintainer_extra_key_refused():
    wire = dict(FIXTURE["maintainers"][0])
    wire["surprise"] = "x"
    with pytest.raises(st.MalformedStewardError):
        st.maintainer_from_dict(wire)


def test_maintainer_bad_email_refused():
    wire = st.make_maintainer("x-one", "X One", "x@example.org", "human")
    wire["email"] = "not-an-address"
    with pytest.raises(st.MalformedStewardError):
        st.maintainer_from_dict(wire)


def test_maintainer_bad_kind_refused():
    wire = dict(FIXTURE["maintainers"][0])
    wire["kind"] = "superuser"
    with pytest.raises(st.MalformedStewardError):
        st.maintainer_from_dict(wire)


def test_conflicting_maintainer_reregister_refused():
    registry = empty_registry()
    wire = dict(FIXTURE["maintainers"][0])
    wire["name"] = "Different Name"
    with pytest.raises(st.DuplicateStewardshipRecordError):
        registry.register_maintainer(wire)
    assert registry.register_maintainer(FIXTURE["maintainers"][0]).name == "Anna Maintainer"


# -- releases and support policy ---------------------------------------

def test_fixture_releases_load():
    registry = full_registry()
    assert [r.version for r in registry.releases()] == [
        "2.0.0", "1.0.0", "0.9.0", "0.5.0"]


def test_release_round_trips():
    release = st.release_from_dict(FIXTURE["releases"][0])
    assert st.release_to_dict(release) == FIXTURE["releases"][0]


def test_release_tampered_digest_refused():
    wire = dict(FIXTURE["releases"][0])
    wire["tier"] = "community-tested"
    with pytest.raises(st.DigestMismatchError):
        st.release_from_dict(wire)


def test_tested_tier_requires_window():
    with pytest.raises(st.MalformedStewardError):
        st.make_release("3.0.0", "officially-tested",
                        "2026-11-01T00:00:00Z", None)
    with pytest.raises(st.MalformedStewardError):
        st.make_release("3.0.0", "community-tested",
                        "2026-11-01T00:00:00Z", None)


def test_release_window_must_follow_release():
    with pytest.raises(st.MalformedStewardError):
        st.make_release("3.0.0", "experimental", "2026-11-02T00:00:00Z",
                        "2026-11-01T00:00:00Z")


def test_release_bad_version_and_tier_refused():
    with pytest.raises(st.MalformedStewardError):
        st.make_release("v3", "experimental", "2026-11-01T00:00:00Z", None)
    with pytest.raises(st.MalformedStewardError):
        st.make_release("3.0.0", "gold", "2026-11-01T00:00:00Z", None)


def test_support_status_supported_official():
    release = st.release_from_dict(FIXTURE["releases"][0])
    row = st.support_status_for(release, AT)
    assert row["effective_status"] == "supported"
    assert row["declared_tier"] == "officially-tested"


def test_support_status_end_of_life_after_window():
    release = st.release_from_dict(FIXTURE["releases"][1])
    assert st.support_status_for(release, AT)["effective_status"] == "end-of-life"
    early = st.support_status_for(release, "2026-01-01T00:00:00Z")
    assert early["effective_status"] == "supported"


def test_support_status_experimental_and_unsupported():
    experimental = st.release_from_dict(FIXTURE["releases"][2])
    unsupported = st.release_from_dict(FIXTURE["releases"][3])
    assert st.support_status_for(experimental, AT)["effective_status"] == "experimental"
    assert st.support_status_for(unsupported, AT)["effective_status"] == "unsupported"


def test_conflicting_release_reregister_refused():
    registry = full_registry()
    wire = st.make_release("2.0.0", "community-tested",
                           "2026-11-01T00:00:00Z", "2027-05-01T00:00:00Z")
    with pytest.raises(st.DuplicateStewardshipRecordError):
        registry.register_release(wire)


# -- areas and continuity ------------------------------------------------

def test_area_assignment_loads_and_round_trips():
    registry = full_registry()
    assert [a.area for a in registry.areas()] == [
        "broker", "policy", "documentation", "release-engineering"]
    assignment = st.area_from_dict(FIXTURE["areas"][0])
    assert st.area_to_dict(assignment) == FIXTURE["areas"][0]


def test_area_agent_primary_refused():
    registry = empty_registry()
    wire = st.make_area("lab", "standard", AGENT, [])
    with pytest.raises(st.AgentActorError):
        registry.assign_area(wire)


def test_area_unknown_backup_refused():
    registry = empty_registry()
    wire = st.make_area("lab", "standard", ANNA, ["ghost-person"])
    with pytest.raises(st.UnknownStewardshipRecordError):
        registry.assign_area(wire)


def test_area_primary_cannot_be_backup():
    with pytest.raises(st.MalformedStewardError):
        st.make_area("lab", "standard", ANNA, [ANNA])


def test_continuity_risks_flags_single_point_of_failure():
    registry = full_registry()
    risks = registry.continuity_risks()
    assert len(risks) == 1
    assert risks[0]["area"] == "policy"
    assert risks[0]["risk"] == "single-point-of-failure"


def test_continuity_risks_critical_agent_only_backup():
    registry = empty_registry()
    registry.assign_area(st.make_area("kernel-lab", "critical", ANNA, [AGENT]))
    risks = registry.continuity_risks()
    assert len(risks) == 1
    assert risks[0]["risk"] == "no-human-backup"


def test_continuity_risks_none_when_covered():
    registry = empty_registry()
    registry.assign_area(st.make_area("kernel-lab", "critical", ANNA, [BJORN]))
    assert registry.continuity_risks() == []


def test_handover_area_moves_primary():
    registry = full_registry()
    updated = registry.handover_area("policy", CELIA, ANNA, AT)
    assert updated.primary_id == CELIA
    risks = registry.continuity_risks()
    assert risks[0]["area"] == "policy"


def test_handover_by_agent_refused():
    registry = full_registry()
    with pytest.raises(st.AgentActorError):
        registry.handover_area("policy", CELIA, AGENT, AT)


def test_handover_to_agent_refused():
    registry = full_registry()
    with pytest.raises(st.AgentActorError):
        registry.handover_area("policy", AGENT, ANNA, AT)


def test_handover_noop_refused():
    registry = full_registry()
    with pytest.raises(st.ContinuityError):
        registry.handover_area("policy", BJORN, ANNA, AT)


# -- incidents and disclosure --------------------------------------------

def test_incident_round_trips():
    incident = st.incident_from_dict(FIXTURE["incidents"][0])
    assert st.incident_to_dict(incident) == FIXTURE["incidents"][0]
    assert incident.state == "reported"


def test_incident_tampered_summary_refused():
    wire = dict(FIXTURE["incidents"][0])
    wire["summary"] = "Rewritten after the fact"
    with pytest.raises(st.DigestMismatchError):
        st.incident_from_dict(wire)


def test_incident_mislabelled_id_refused():
    wire = dict(FIXTURE["incidents"][0])
    wire["incident_id"] = "inc-000000000000"
    with pytest.raises(st.DigestMismatchError):
        st.incident_from_dict(wire)


def test_incident_unknown_reporter_refused():
    registry = empty_registry()
    wire = st.make_incident("operational", "low", "Ghost report",
                            "ghost-person", "2026-11-11T08:00:00Z")
    with pytest.raises(st.UnknownStewardshipRecordError):
        registry.register_incident(wire)


def test_fixture_incidents_summary():
    summary = full_registry().stewardship_summary(AT)
    assert summary["incidents"] == 2
    assert summary["security_incidents"] == 1
    assert summary["open_incidents"] == 2


def test_triage_requires_reported_state():
    registry = full_registry()
    incident = registry.incidents()[0]
    registry.triage_incident(incident.incident_id, ANNA, AT)
    with pytest.raises(st.IncidentTransitionError):
        registry.triage_incident(incident.incident_id, ANNA, AT)


def test_triage_by_agent_refused():
    registry = full_registry()
    incident = registry.incidents()[0]
    with pytest.raises(st.AgentActorError):
        registry.triage_incident(incident.incident_id, AGENT, AT)


def test_mitigation_requires_triaged_state():
    registry = full_registry()
    incident = registry.incidents()[0]
    with pytest.raises(st.IncidentTransitionError):
        registry.record_mitigation(incident.incident_id, ANNA, "Fixed", AT)


def test_security_disclosure_blocked_before_mitigation():
    registry = full_registry()
    incident = registry.incidents()[0]
    registry.triage_incident(incident.incident_id, ANNA, AT)
    with pytest.raises(st.DisclosureBlockedError):
        registry.disclose_incident(incident.incident_id, BJORN, AT)


def test_security_full_lifecycle():
    registry = empty_registry()
    incident = own_security_incident(registry)
    registry.triage_incident(incident.incident_id, BJORN, "2026-11-11T09:00:00Z")
    registry.record_mitigation(incident.incident_id, BJORN, "Rotated the leaked log",
                               "2026-11-11T10:00:00Z")
    registry.disclose_incident(incident.incident_id, ANNA, "2026-11-11T11:00:00Z")
    assert incident.disclosed_at == "2026-11-11T11:00:00Z"
    registry.close_incident(incident.incident_id, ANNA, "2026-11-11T12:00:00Z")
    assert incident.state == "closed"
    assert registry.open_incidents() == []


def test_operational_disclosure_after_triage_allowed():
    registry = empty_registry()
    wire = st.make_incident("operational", "low", "Mirror blip", BJORN,
                            "2026-11-11T08:00:00Z")
    incident = registry.register_incident(wire)
    with pytest.raises(st.IncidentTransitionError):
        registry.disclose_incident(incident.incident_id, ANNA, AT)
    registry.triage_incident(incident.incident_id, ANNA, AT)
    registry.disclose_incident(incident.incident_id, ANNA, AT)
    assert incident.disclosed_at == AT


def test_close_requires_mitigated_state():
    registry = empty_registry()
    incident = own_security_incident(registry)
    registry.triage_incident(incident.incident_id, ANNA, AT)
    with pytest.raises(st.IncidentTransitionError):
        registry.close_incident(incident.incident_id, ANNA, AT)


def test_disclose_by_agent_refused():
    registry = empty_registry()
    incident = own_security_incident(registry)
    registry.triage_incident(incident.incident_id, ANNA, AT)
    registry.record_mitigation(incident.incident_id, ANNA, "Done", AT)
    with pytest.raises(st.AgentActorError):
        registry.disclose_incident(incident.incident_id, AGENT, AT)


# -- governance ------------------------------------------------------------

def test_proposal_round_trips():
    proposal = st.proposal_from_dict(FIXTURE["proposals"][0])
    assert st.proposal_to_dict(proposal) == FIXTURE["proposals"][0]
    assert proposal.state == "proposed"


def test_release_acceptance_requires_full_checklist():
    partial = {item: True for item in st.RELEASE_CHECKLIST[:5]}
    with pytest.raises(st.MalformedStewardError):
        st.make_proposal("release-acceptance", "2.0.0", "Accept", CELIA,
                         "2026-11-11T09:00:00Z", partial)


def test_non_acceptance_proposal_checklist_refused():
    full = {item: True for item in st.RELEASE_CHECKLIST}
    with pytest.raises(st.MalformedStewardError):
        st.make_proposal("policy-change", "policy", "Nope", ANNA,
                         "2026-11-11T09:00:00Z", full)


def test_decide_by_proposer_refused():
    registry = full_registry()
    proposal = registry.proposals()[0]
    with pytest.raises(st.SelfApprovalError):
        registry.decide_proposal(proposal.proposal_id, ANNA, "approved", AT)


def test_decide_by_agent_refused():
    registry = full_registry()
    proposal = registry.proposals()[0]
    with pytest.raises(st.AgentActorError):
        registry.decide_proposal(proposal.proposal_id, AGENT, "approved", AT)


def test_decide_policy_proposal_approved():
    registry = full_registry()
    proposal = registry.proposals()[0]
    decided = registry.decide_proposal(proposal.proposal_id, BJORN, "approved", AT)
    assert decided.state == "approved"
    assert decided.decided_by == BJORN


def test_decide_twice_refused():
    registry = full_registry()
    proposal = registry.proposals()[0]
    registry.decide_proposal(proposal.proposal_id, BJORN, "rejected", AT)
    with pytest.raises(st.ProposalStateError):
        registry.decide_proposal(proposal.proposal_id, CELIA, "approved", AT)


def test_release_acceptance_incomplete_checklist_refused():
    registry = empty_registry()
    checklist = {item: True for item in st.RELEASE_CHECKLIST}
    checklist["offline-mode-verified"] = False
    wire = st.make_proposal("release-acceptance", "3.0.0", "Accept 3.0.0",
                            CELIA, "2026-11-11T09:00:00Z", checklist)
    proposal = registry.register_proposal(wire)
    with pytest.raises(st.ChecklistIncompleteError):
        registry.decide_proposal(proposal.proposal_id, ANNA, "approved", AT)
    decided = registry.decide_proposal(proposal.proposal_id, ANNA, "rejected", AT)
    assert decided.state == "rejected"


def test_release_acceptance_complete_checklist_approved():
    registry = full_registry()
    proposal = registry.proposals()[2]
    decided = registry.decide_proposal(proposal.proposal_id, ANNA, "approved", AT)
    assert decided.state == "approved"


def test_decide_bad_decision_refused():
    registry = full_registry()
    proposal = registry.proposals()[0]
    with pytest.raises(st.MalformedStewardError):
        registry.decide_proposal(proposal.proposal_id, BJORN, "maybe", AT)


# -- audits ------------------------------------------------------------------

def test_overdue_audits_at_date():
    registry = full_registry()
    overdue = registry.overdue_audits(AT)
    assert [a.audit_id for a in overdue] == ["audit-sec-2026"]
    assert registry.overdue_audits("2026-10-01T00:00:00Z") == []


def test_complete_audit_clears_overdue():
    registry = full_registry()
    audit = registry.complete_audit("audit-sec-2026", ANNA, AT)
    assert audit.completed_by == ANNA
    assert registry.overdue_audits(AT) == []


def test_complete_audit_by_agent_refused():
    registry = full_registry()
    with pytest.raises(st.AgentActorError):
        registry.complete_audit("audit-sec-2026", AGENT, AT)


def test_complete_audit_twice_refused():
    registry = full_registry()
    registry.complete_audit("audit-sec-2026", ANNA, AT)
    with pytest.raises(st.ProposalStateError):
        registry.complete_audit("audit-sec-2026", BJORN, AT)


def test_audit_bad_kind_refused():
    with pytest.raises(st.MalformedStewardError):
        st.make_audit("audit-x", "vibes-check", "broker", AT)


# -- plugin apis ---------------------------------------------------------------

def test_plugin_api_loads():
    registry = full_registry()
    assert [p.api_id for p in registry.plugin_apis()] == [
        "core-hooks", "legacy-hooks"]
    assert registry.plugin_apis()[1].stability == "deprecated"


def test_plugin_deprecated_requires_migration_note():
    with pytest.raises(st.MalformedStewardError):
        st.make_plugin_api("old-api", "0.1.0", "deprecated")


def test_plugin_removed_cannot_register_directly():
    with pytest.raises(st.MalformedStewardError):
        st.make_plugin_api("old-api", "0.1.0", "removed", "Gone.")


def test_plugin_removal_requires_approved_proposal():
    registry = full_registry()
    proposal = registry.proposals()[1]
    with pytest.raises(st.ProposalStateError):
        registry.remove_plugin_api("legacy-hooks", proposal.proposal_id,
                                   ANNA, "Use core-hooks instead.", AT)


def test_plugin_removal_wrong_subject_refused():
    registry = full_registry()
    proposal = registry.proposals()[0]
    registry.decide_proposal(proposal.proposal_id, BJORN, "approved", AT)
    with pytest.raises(st.ProposalStateError):
        registry.remove_plugin_api("legacy-hooks", proposal.proposal_id,
                                   CELIA, "Use core-hooks instead.", AT)


def test_plugin_removal_full_flow():
    registry = full_registry()
    proposal = registry.proposals()[1]
    registry.decide_proposal(proposal.proposal_id, ANNA, "approved", AT)
    removed = registry.remove_plugin_api("legacy-hooks", proposal.proposal_id,
                                         CELIA, "Use core-hooks instead.", AT)
    assert removed.stability == "removed"
    assert [p.api_id for p in registry.plugin_apis()] == ["core-hooks"]
    assert [p.api_id for p in registry.removed_plugin_apis()] == ["legacy-hooks"]


def test_plugin_removal_by_agent_refused():
    registry = full_registry()
    proposal = registry.proposals()[1]
    registry.decide_proposal(proposal.proposal_id, ANNA, "approved", AT)
    with pytest.raises(st.AgentActorError):
        registry.remove_plugin_api("legacy-hooks", proposal.proposal_id,
                                   AGENT, "Use core-hooks instead.", AT)


# -- summary, report, evidence -------------------------------------------------

def test_summary_counts():
    summary = full_registry().stewardship_summary(AT)
    assert summary["maintainers"] == 4
    assert summary["human_maintainers"] == 3
    assert summary["releases"] == 4
    assert summary["supported_releases"] == 1
    assert summary["end_of_life_releases"] == 1
    assert summary["areas"] == 4
    assert summary["continuity_risks"] == 1
    assert summary["proposals"] == 3
    assert summary["pending_proposals"] == 3
    assert summary["audits"] == 2
    assert summary["overdue_audits"] == 1
    assert summary["plugin_apis"] == 2
    assert summary["removed_plugin_apis"] == 0


def test_support_matrix_rows():
    matrix = full_registry().support_matrix(AT)
    by_version = {row["version"]: row["effective_status"] for row in matrix}
    assert by_version == {
        "2.0.0": "supported",
        "1.0.0": "end-of-life",
        "0.9.0": "experimental",
        "0.5.0": "unsupported",
    }


def test_render_report_deterministic():
    registry = full_registry()
    first = st.render_stewardship_report(registry, AT)
    second = st.render_stewardship_report(registry, AT)
    assert first == second
    assert first.encode("utf-8") == second.encode("utf-8")


def test_render_report_contents():
    report = st.render_stewardship_report(full_registry(), AT)
    assert "2.0.0: officially-tested -> supported" in report
    assert "1.0.0: officially-tested -> end-of-life" in report
    assert "policy: single-point-of-failure" in report
    assert "overdue audits: 1" in report


def test_evidence_record_honesty():
    record = st.stewardship_evidence_record(full_registry(), AT)
    assert record["slice"] == "LIF-1601"
    assert record["evidence_status"] == "lab-verified"
    assert "revert" in record["undo"]
    assert any("LIF-1501" in item for item in record["limitations"])
    assert record["summary"]["releases"] == 4
