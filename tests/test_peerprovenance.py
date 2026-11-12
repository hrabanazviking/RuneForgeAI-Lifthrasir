"""LIF-1302: peer provenance and contradictory-evidence handling.

Book IV P13 at fixture level: a simulated 20-node network
(tests/fixtures/lif1302/peers.json) whose reports are ingested,
provenance-checked, duplicate-grouped and contradiction-tracked
by the in-memory registry.  No network, no transport, no host
state: every report is inert data, and nothing here can make a
peer artifact cause an action.
"""
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from lifthrasir.peerprovenance import (
    DECLARED_STATUSES,
    EVIDENCE_STATUS,
    MAX_PEER_DECLARED_STATUS,
    PEER_SCHEMA,
    SUBJECT_STATUSES,
    TRUST_STATES,
    ConsentWithdrawnError,
    DigestMismatchError,
    ExpiredReportError,
    MalformedReportError,
    PayloadTooLargeError,
    PeerEvidenceRegistry,
    QuotaExceededError,
    ReproductionMismatchError,
    SensitivePayloadError,
    UnknownReportError,
    UnsafePayloadError,
    content_digest_for,
    make_report,
    peer_evidence_record,
    report_from_dict,
    report_to_dict,
)

FIXTURE = Path(os.environ.get(
    "LIF_PEER_FIXTURE",
    REPO / "tests" / "fixtures" / "lif1302" / "peers.json"))
ISSUED = "2026-11-12T00:00:00Z"
EXPIRES = "2027-11-12T00:00:00Z"
SUBJECT_A = "benchmark:kernel-compile@config-pinned-a"
SUBJECT_B = "incident:oom-kill@host-class-b"
SUBJECT_C = "fixture:ltp-subset@2026.11"
PAYLOAD_A = {"config": "config-pinned-a", "duration_seconds": 182,
             "unit": "seconds", "workload": "kernel-compile"}


def _moment(text):
    return datetime.strptime(text, "%Y-%m-%dT%H:%M:%SZ").replace(
        tzinfo=timezone.utc)


class Clock:
    """Mutable injectable clock: tests advance time explicitly."""

    def __init__(self, text="2026-11-12T12:00:00Z"):
        self.moment = _moment(text)

    def __call__(self):
        return self.moment

    def advance_to(self, text):
        self.moment = _moment(text)


def load_fixture_reports():
    data = json.loads(FIXTURE.read_text(encoding="utf-8"))
    assert data["network"] == "simulated-20-node"
    return data["reports"]


def fresh_registry(**kwargs):
    return PeerEvidenceRegistry(clock=Clock(), **kwargs)


def one_report(contributor="node-01", subject=SUBJECT_A,
               claim="duration_seconds=182", payload=None, **kw):
    return make_report(contributor, subject, claim,
                       PAYLOAD_A if payload is None else payload,
                       kw.get("issued_at", ISSUED),
                       kw.get("expires_at", EXPIRES),
                       kw.get("declared_status", "hypothesis"))


# ----------------------------------------------------------------
# Report shape and provenance pins
# ----------------------------------------------------------------

class TestReportValidation:

    def test_round_trip_preserves_every_field(self):
        report = one_report(declared_status="reproducer")
        clone = report_from_dict(report_to_dict(report))
        assert clone == report

    def test_digest_and_id_are_content_pins(self):
        report = one_report()
        assert report.content_digest == content_digest_for(
            SUBJECT_A, "duration_seconds=182", PAYLOAD_A)
        assert report.content_digest.startswith("sha256:")
        assert report.report_id.startswith("pr-")
        # Same content, different contributor: same WHAT, new WHO.
        other = one_report(contributor="node-02")
        assert other.content_digest == report.content_digest
        assert other.report_id != report.report_id

    def test_missing_digest_is_refused(self):
        wire = report_to_dict(one_report())
        del wire["content_digest"]
        with pytest.raises(MalformedReportError):
            report_from_dict(wire)

    def test_tampered_payload_is_refused_by_name(self):
        wire = report_to_dict(one_report())
        wire["payload"] = dict(PAYLOAD_A, duration_seconds=999)
        with pytest.raises(DigestMismatchError):
            report_from_dict(wire)

    def test_tampered_claim_is_refused_by_name(self):
        wire = report_to_dict(one_report())
        wire["claim"] = "duration_seconds=1"
        with pytest.raises(DigestMismatchError):
            report_from_dict(wire)

    def test_mislabelled_report_id_is_refused(self):
        wire = report_to_dict(one_report())
        wire["report_id"] = "pr-0000000000000000"
        with pytest.raises(DigestMismatchError):
            report_from_dict(wire)

    @pytest.mark.parametrize("field", ["contributor_id", "subject",
                                       "claim", "issued_at",
                                       "expires_at"])
    def test_missing_or_blank_fields_are_refused(self, field):
        wire = report_to_dict(one_report())
        wire[field] = "  "
        with pytest.raises(MalformedReportError):
            report_from_dict(wire)

    def test_non_mapping_report_and_payload_are_refused(self):
        with pytest.raises(MalformedReportError):
            report_from_dict(["not", "a", "mapping"])
        with pytest.raises(MalformedReportError):
            one_report(payload="not-a-mapping")

    def test_bad_timestamp_and_inverted_window_are_refused(self):
        with pytest.raises(MalformedReportError):
            one_report(issued_at="yesterday-ish")
        with pytest.raises(MalformedReportError):
            one_report(issued_at=EXPIRES, expires_at=ISSUED)

    def test_declared_status_must_be_on_the_ladder(self):
        with pytest.raises(MalformedReportError):
            one_report(declared_status="totally-proven")
        for status in DECLARED_STATUSES:
            if DECLARED_STATUSES.index(status) <= DECLARED_STATUSES.index(
                    MAX_PEER_DECLARED_STATUS):
                assert one_report(declared_status=status).declared_status \
                    == status

    @pytest.mark.parametrize("status", ["cross-platform-verified",
                                        "human-reviewed",
                                        "upstream-accepted"])
    def test_peer_cannot_declare_a_local_rung(self, status):
        # Higher rungs name local human/process acts; a remote
        # artifact asserting them is refused, not believed.
        with pytest.raises(MalformedReportError):
            one_report(declared_status=status)

    @pytest.mark.parametrize("key", ["command", "action", "shell",
                                     "exec", "sudo"])
    def test_command_like_payload_keys_are_refused(self, key):
        # Federation shares evidence, not control: a payload that
        # names an action is not evidence and never gets stored.
        with pytest.raises(UnsafePayloadError):
            one_report(payload={key: "rm -rf /", "outcome": "x"})

    @pytest.mark.parametrize("key", ["password", "api_key", "token"])
    def test_sensitive_payload_keys_are_refused(self, key):
        # Data minimization: payloads must be scrubbed pre-exchange.
        with pytest.raises(SensitivePayloadError):
            one_report(payload={key: "hunter2", "outcome": "x"})

    def test_oversized_payload_is_refused(self):
        big = {"blob": "x" * 20000}
        with pytest.raises(PayloadTooLargeError):
            one_report(payload=big)
        with pytest.raises(PayloadTooLargeError):
            fresh_registry(max_payload_bytes=64).ingest(
                report_to_dict(one_report()))


# ----------------------------------------------------------------
# Ingest: untrusted by default, idempotent, quota- and time-bound
# ----------------------------------------------------------------

class TestIngest:

    def test_every_report_enters_untrusted(self):
        # Even a maximally-declared peer report starts untrusted:
        # trust is earned locally, never asserted remotely.
        registry = fresh_registry()
        result = registry.ingest(report_to_dict(
            one_report(declared_status="lab-verified")))
        assert result.duplicate is False
        assert result.record.trust_state == "untrusted"
        assert result.record.trust_state in TRUST_STATES

    def test_duplicate_resend_is_idempotent_and_counted(self):
        registry = fresh_registry()
        wire = report_to_dict(one_report())
        first = registry.ingest(wire)
        second = registry.ingest(wire)
        assert second.duplicate is True
        assert second.record is first.record
        assert len(registry) == 1
        assert first.record.duplicate_ingests == 1

    def test_expired_at_arrival_is_refused_and_not_stored(self):
        registry = fresh_registry()
        stale = one_report(issued_at="2026-01-01T00:00:00Z",
                           expires_at="2026-06-01T00:00:00Z")
        with pytest.raises(ExpiredReportError):
            registry.ingest(report_to_dict(stale))
        assert len(registry) == 0

    def test_per_contributor_quota_is_enforced(self):
        registry = fresh_registry(max_reports_per_contributor=2)
        registry.ingest(report_to_dict(one_report(subject="s:1")))
        registry.ingest(report_to_dict(one_report(subject="s:2")))
        with pytest.raises(QuotaExceededError):
            registry.ingest(report_to_dict(one_report(subject="s:3")))
        assert len(registry) == 2
        # Another contributor is unaffected by node-01's quota.
        registry.ingest(report_to_dict(
            one_report(contributor="node-02", subject="s:3")))
        assert len(registry) == 3

    def test_unknown_report_id_is_refused_by_name(self):
        with pytest.raises(UnknownReportError):
            fresh_registry().get("pr-0000000000000000")


# ----------------------------------------------------------------
# Duplicates: detected and grouped, never double-counted
# ----------------------------------------------------------------

class TestDuplicates:

    def test_identical_content_groups_across_contributors(self):
        registry = fresh_registry()
        registry.ingest(report_to_dict(one_report()))
        result = registry.ingest(report_to_dict(
            one_report(contributor="node-02")))
        assert result.content_shared_with != ()
        groups = registry.duplicates()
        assert len(groups) == 1
        assert groups[0].contributor_ids == ("node-01", "node-02")
        assert len(groups[0].report_ids) == 2
        # Grouping is not merging: both records still exist.
        assert len(registry) == 2

    def test_distinct_content_is_not_grouped(self):
        registry = fresh_registry()
        registry.ingest(report_to_dict(one_report()))
        registry.ingest(report_to_dict(one_report(
            contributor="node-02", claim="duration_seconds=240",
            payload=dict(PAYLOAD_A, duration_seconds=240))))
        assert registry.duplicates() == []


# ----------------------------------------------------------------
# Contradictions: preserved, never voted into a false consensus
# ----------------------------------------------------------------

class TestContradictions:

    def _registry_with_dissent(self, agreeing=17, dissenting=1):
        registry = fresh_registry()
        for i in range(1, agreeing + 1):
            registry.ingest(report_to_dict(
                one_report(contributor=f"node-{i:02d}")))
        for j in range(dissenting):
            registry.ingest(report_to_dict(one_report(
                contributor=f"node-{90 + j}",
                claim="duration_seconds=240",
                payload=dict(PAYLOAD_A, duration_seconds=240))))
        return registry

    def test_majority_does_not_dissolve_a_dispute(self):
        # THE Book IV P13 rule: 17 agreeing peers and 1 dissenting
        # peer is a disputed subject, full stop -- agreement is
        # counted inside the dispute, never used to outvote it.
        registry = self._registry_with_dissent()
        assert registry.subject_status(SUBJECT_A) == "disputed"
        assert registry.subject_status(SUBJECT_A) in SUBJECT_STATUSES
        disputes = registry.disputes()
        assert len(disputes) == 1
        dispute = disputes[0]
        assert dispute.subject == SUBJECT_A
        assert len(dispute.claims["duration_seconds=182"]) == 17
        assert len(dispute.claims["duration_seconds=240"]) == 1
        assert "node-90" in dispute.contributor_ids
        assert len(dispute.report_ids) == 18

    def test_claim_counts_are_facts_not_verdicts(self):
        registry = self._registry_with_dissent(agreeing=2, dissenting=1)
        assert registry.claim_counts(SUBJECT_A) == {
            "duration_seconds=182": 2, "duration_seconds=240": 1}
        assert registry.subject_status(SUBJECT_A) == "disputed"

    def test_corroborated_needs_two_distinct_contributors(self):
        registry = fresh_registry()
        registry.ingest(report_to_dict(one_report()))
        assert registry.subject_status(SUBJECT_A) == "uncontested"
        registry.ingest(report_to_dict(one_report()))  # resend
        assert registry.subject_status(SUBJECT_A) == "uncontested"
        registry.ingest(report_to_dict(
            one_report(contributor="node-02")))
        assert registry.subject_status(SUBJECT_A) == "corroborated"

    def test_unknown_subject(self):
        registry = self._registry_with_dissent(agreeing=1, dissenting=0)
        assert registry.subject_status("subject:never-reported") == \
            "unknown"
        assert registry.claim_counts("subject:never-reported") == {}


# ----------------------------------------------------------------
# Trust: local reproduction is the only road up
# ----------------------------------------------------------------

class TestReproduction:

    def test_matching_local_reproduction_promotes(self):
        registry = fresh_registry()
        report = one_report()
        registry.ingest(report_to_dict(report))
        record = registry.mark_reproduced(
            report.report_id, report.subject, report.claim,
            report.payload)
        assert record.trust_state == "locally-reproduced"

    def test_mismatched_reproduction_fails_and_is_recorded(self):
        registry = fresh_registry()
        report = one_report()
        registry.ingest(report_to_dict(report))
        with pytest.raises(ReproductionMismatchError):
            registry.mark_reproduced(
                report.report_id, report.subject, report.claim,
                dict(PAYLOAD_A, duration_seconds=181))
        record = registry.get(report.report_id)
        assert record.trust_state == "untrusted"
        assert record.reproduction_failures == 1
        # A later honest reproduction still succeeds.
        registry.mark_reproduced(report.report_id, report.subject,
                                 report.claim, report.payload)
        assert record.trust_state == "locally-reproduced"
        assert record.reproduction_failures == 1

    def test_reproduction_must_match_the_whole_triple(self):
        registry = fresh_registry()
        report = one_report()
        registry.ingest(report_to_dict(report))
        with pytest.raises(ReproductionMismatchError):
            registry.mark_reproduced(
                report.report_id, "benchmark:other@config", report.claim,
                report.payload)

    def test_withdrawn_report_cannot_be_reproduced_into_trust(self):
        registry = fresh_registry()
        report = one_report()
        registry.ingest(report_to_dict(report))
        registry.withdraw_report(report.report_id)
        with pytest.raises(ConsentWithdrawnError):
            registry.mark_reproduced(report.report_id, report.subject,
                                     report.claim, report.payload)

    def test_expired_report_cannot_be_promoted(self):
        clock = Clock()
        registry = PeerEvidenceRegistry(clock=clock)
        report = one_report(expires_at="2026-12-01T00:00:00Z")
        registry.ingest(report_to_dict(report))
        clock.advance_to("2026-12-02T00:00:00Z")
        with pytest.raises(ExpiredReportError):
            registry.mark_reproduced(report.report_id, report.subject,
                                     report.claim, report.payload)
        assert registry.get(report.report_id).trust_state == "expired"


# ----------------------------------------------------------------
# Consent withdrawal and expiration (the outage half of the gate)
# ----------------------------------------------------------------

class TestConsentAndExpiry:

    def test_withdrawal_excludes_from_usable_views_but_retains(self):
        registry = fresh_registry()
        report = one_report()
        registry.ingest(report_to_dict(report))
        registry.withdraw_report(report.report_id)
        registry.withdraw_report(report.report_id)  # idempotent
        assert registry.reports(usable_only=True) == []
        assert len(registry.reports()) == 1  # retained for audit
        assert registry.subject_status(SUBJECT_A) == "unknown"

    def test_contributor_withdrawal_ends_a_dispute_by_consent(self):
        # The dissent disappears because its owner withdrew consent
        # -- the ONLY way a dispute ends without local evidence.
        registry = fresh_registry()
        registry.ingest(report_to_dict(one_report()))
        registry.ingest(report_to_dict(one_report(
            contributor="node-02")))
        registry.ingest(report_to_dict(one_report(
            contributor="node-03", claim="duration_seconds=240",
            payload=dict(PAYLOAD_A, duration_seconds=240))))
        assert registry.subject_status(SUBJECT_A) == "disputed"
        assert registry.withdraw_contributor("node-03") == 1
        assert registry.disputes() == []
        assert registry.subject_status(SUBJECT_A) == "corroborated"

    def test_sweep_expires_live_records_only(self):
        clock = Clock()
        registry = PeerEvidenceRegistry(clock=clock)
        short = one_report(contributor="node-01", subject="s:short",
                           expires_at="2026-11-20T00:00:00Z")
        long = one_report(contributor="node-02", subject="s:long")
        gone = one_report(contributor="node-03", subject="s:gone",
                          expires_at="2026-11-20T00:00:00Z")
        for report in (short, long, gone):
            registry.ingest(report_to_dict(report))
        registry.withdraw_report(gone.report_id)
        clock.advance_to("2026-11-21T00:00:00Z")
        assert registry.sweep_expired() == 1
        assert registry.get(short.report_id).trust_state == "expired"
        assert registry.get(long.report_id).trust_state == "untrusted"
        # Withdrawn is governed by consent, not by the clock.
        assert registry.get(gone.report_id).trust_state == "withdrawn"
        assert registry.sweep_expired() == 0


# ----------------------------------------------------------------
# The Book IV P13 test gate: a simulated network of 20 nodes
# ----------------------------------------------------------------

class TestSimulatedNetworkGate:

    def test_twenty_node_network_endures_the_gate(self):
        clock = Clock()
        registry = PeerEvidenceRegistry(clock=clock)
        wires = load_fixture_reports()
        assert len(wires) == 20
        for wire in wires:
            result = registry.ingest(wire)
            assert result.record.trust_state == "untrusted"
        assert len(registry) == 20
        summary = registry.summary()
        assert summary["contributors"] == 20
        assert summary["subjects"] == 3
        # Contradictory evidence: 17 carriers of one claim, 1
        # dissenter -- disputed, never voted into consensus.
        assert registry.subject_status(SUBJECT_A) == "disputed"
        assert registry.claim_counts(SUBJECT_A) == {
            "duration_seconds=182": 17, "duration_seconds=240": 1}
        # Duplicated reports: one artifact, seventeen carriers.
        groups = registry.duplicates()
        assert len(groups) == 1
        assert len(groups[0].report_ids) == 17
        assert len(groups[0].contributor_ids) == 17
        # Uncontested single-node subjects stay modest claims.
        assert registry.subject_status(SUBJECT_B) == "uncontested"
        assert registry.subject_status(SUBJECT_C) == "uncontested"
        # Withdrawn consent: node-18 leaves; the dispute ends by
        # consent and the subject is corroborated by the 17.
        assert registry.withdraw_contributor("node-18") == 1
        assert registry.disputes() == []
        assert registry.subject_status(SUBJECT_A) == "corroborated"
        # Outage by time: every report expires; the registry still
        # answers and claims nothing usable remains.
        clock.advance_to("2027-11-13T00:00:00Z")
        assert registry.sweep_expired() == 19
        assert registry.subject_status(SUBJECT_A) == "unknown"
        assert registry.reports(usable_only=True) == []
        assert len(registry) == 20  # audit trail survives

    def test_no_peer_report_ever_bypasses_local_trust(self):
        # Ingesting the whole network grants NO trust by itself:
        # zero locally-reproduced until a local reproduction runs.
        registry = fresh_registry()
        for wire in load_fixture_reports():
            registry.ingest(wire)
        states = registry.summary()["by_trust_state"]
        assert states["untrusted"] == 20
        assert states["locally-reproduced"] == 0


# ----------------------------------------------------------------
# Evidence record
# ----------------------------------------------------------------

class TestEvidenceRecord:

    def test_record_shape_and_honesty(self):
        registry = fresh_registry()
        for wire in load_fixture_reports():
            registry.ingest(wire)
        record = peer_evidence_record(registry)
        assert record["schema"] == PEER_SCHEMA
        assert record["evidence_status"] == EVIDENCE_STATUS
        assert record["reports"] == 20
        assert record["disputes"] == 1
        assert record["disputed_subjects"] == [SUBJECT_A]
        assert record["duplicate_groups"] == 1
        assert any("not a live federation" in limit
                   for limit in record["limitations"])
        assert "reverting the LIF-1302 commit" in record["undo"]
