# SPDX-License-Identifier: GPL-2.0-only
"""LIF-0305 causal hypothesis record tests.

Scope: in-memory ledger plus the banked LIF-0004 v0.1 hypothesis
schema file. Records use the v0.1 valid-example shape. No network,
no files outside the repo, no system state touched.

The counterevidence-drop test is this slice's NEGATIVE CONTROL:
a new version that tries to erase recorded counterevidence must
be refused, and the original counterevidence must survive.
"""
import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from lifthrasir import hypotheses as hz  # noqa: E402

SCHEMA_PATH = (REPO / "docs" / "protocols" / "schemas" / "v0.1"
               / "hypothesis.schema.json")
VALID_EXAMPLE = (REPO / "docs" / "protocols" / "examples" / "v0.1"
                 / "valid" / "hypothesis.json")


def hyp(hyp_id="hyp-2026-001", incident="inc-2026-001", **over):
    record = {
        "schema": "lifthrasir.hypothesis.v0.1",
        "schema_version": "0.1",
        "hypothesis_id": hyp_id,
        "incident_id": incident,
        "claim": "demo.service fails over a missing config path.",
        "status": "proposed",
        "confidence": 0.4,
        "evidence_for": ["ev-2026-001"],
        "evidence_against": [],
        "test_plan": "Check the referenced path in the lab guest.",
        "evidence_status": "hypothesis",
        "created_at": "2026-11-05T17:05:00Z",
    }
    record.update(over)
    return record


@pytest.fixture()
def ledger():
    return hz.HypothesisLedger()


def test_banked_valid_example_validates():
    record = json.loads(VALID_EXAMPLE.read_text(encoding="utf-8"))
    assert hz.validate_hypothesis(record) == record


def test_validation_agrees_with_banked_schema():
    jsonschema = pytest.importorskip("jsonschema")
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    validator = jsonschema.Draft202012Validator(
        schema, format_checker=jsonschema.FormatChecker())
    for record in (hyp(), hyp(status="supported"),
                   hyp(status="refuted",
                       evidence_against=["ev-2026-009"])):
        assert list(validator.iter_errors(record)) == []
        assert hz.validate_hypothesis(record) == record
    bad = hyp(status="supported", evidence_for=[])
    assert list(validator.iter_errors(bad)) != []
    with pytest.raises(hz.UnsupportedStatusError):
        hz.validate_hypothesis(bad)


def test_record_and_get_roundtrip(ledger):
    assert ledger.record(hyp()) == "hyp-2026-001"
    assert ledger.get("hyp-2026-001") == hyp()
    assert len(ledger) == 1 and ledger.ids() == ["hyp-2026-001"]


def test_supported_requires_supporting_evidence():
    with pytest.raises(hz.UnsupportedStatusError):
        hz.validate_hypothesis(
            hyp(status="supported", evidence_for=[]))


def test_refuted_requires_counterevidence():
    with pytest.raises(hz.UnsupportedStatusError):
        hz.validate_hypothesis(
            hyp(status="refuted", evidence_against=[]))


def test_confidence_out_of_range_refused():
    with pytest.raises(hz.MalformedHypothesisError):
        hz.validate_hypothesis(hyp(confidence=1.5))


def test_extra_field_and_bad_ids_refused():
    with pytest.raises(hz.MalformedHypothesisError):
        hz.validate_hypothesis(hyp(caused_by="ev-2026-001"))
    with pytest.raises(hz.MalformedHypothesisError):
        hz.validate_hypothesis(hyp(hyp_id="bad-id"))
    with pytest.raises(hz.MalformedHypothesisError):
        hz.validate_hypothesis(hyp(evidence_for=["xx-1"]))


def test_same_evidence_for_and_against_refused():
    with pytest.raises(hz.MalformedHypothesisError):
        hz.validate_hypothesis(hyp(
            evidence_against=["ev-2026-001"]))


def test_duplicate_new_id_refused(ledger):
    ledger.record(hyp())
    with pytest.raises(hz.DuplicateHypothesisError):
        ledger.record(hyp())


def test_failed_hypothesis_is_retained_and_queryable(ledger):
    ledger.record(hyp(status="refuted",
                      evidence_against=["ev-2026-009"]))
    ledger.record(hyp(hyp_id="hyp-2026-002"))
    failed = ledger.list_failed()
    assert [r["hypothesis_id"] for r in failed] == ["hyp-2026-001"]
    assert failed[0]["evidence_against"] == ["ev-2026-009"]
    assert ledger.ever_failed() == ["hyp-2026-001"]
    assert ledger.get("hyp-2026-001")["status"] == "refuted"


def test_version_update_keeps_history_and_marks_stale(ledger):
    ledger.record(hyp())
    ledger.record_version(hyp(
        status="supported", confidence=0.8,
        updated_at="2026-11-05T18:00:00Z"))
    history = ledger.history("hyp-2026-001")
    assert len(history) == 2
    assert history[0]["status"] == "proposed"
    assert ledger.get("hyp-2026-001")["status"] == "supported"
    assert ledger.is_stale("hyp-2026-001", 0) is True
    assert ledger.is_stale("hyp-2026-001", 1) is False


def test_version_becoming_refuted_keeps_failure_in_history(ledger):
    ledger.record(hyp())
    ledger.record_version(hyp(
        status="refuted", evidence_against=["ev-2026-009"],
        updated_at="2026-11-05T18:00:00Z"))
    assert ledger.list_failed()[0]["hypothesis_id"] == "hyp-2026-001"
    assert ledger.counterevidence_for("hyp-2026-001") == ["ev-2026-009"]


def test_counterevidence_drop_is_refused_negative_control(ledger):
    ledger.record(hyp(evidence_against=["ev-2026-009"]))
    with pytest.raises(hz.CounterevidenceDroppedError):
        ledger.record_version(hyp(
            evidence_against=[], status="supported",
            updated_at="2026-11-05T18:00:00Z"))
    # The recorded counterevidence survives the refused rewrite.
    assert ledger.counterevidence_for("hyp-2026-001") == ["ev-2026-009"]
    assert len(ledger.history("hyp-2026-001")) == 1


def test_support_drop_also_refused(ledger):
    ledger.record(hyp())
    with pytest.raises(hz.CounterevidenceDroppedError):
        ledger.record_version(hyp(
            evidence_for=[], updated_at="2026-11-05T18:00:00Z"))


def test_version_timestamp_cannot_run_backwards(ledger):
    ledger.record(hyp())
    with pytest.raises(hz.StaleTimestampError):
        ledger.record_version(hyp(
            updated_at="2026-11-05T16:00:00Z"))


def test_version_requires_updated_at_and_same_incident(ledger):
    ledger.record(hyp())
    with pytest.raises(hz.MalformedHypothesisError):
        ledger.record_version(hyp(status="supported"))
    with pytest.raises(hz.MalformedHypothesisError):
        ledger.record_version(hyp(
            incident="inc-2026-999",
            updated_at="2026-11-05T18:00:00Z"))


def test_causal_links_same_incident_shared_and_contradiction(ledger):
    ledger.record(hyp(evidence_for=["ev-2026-001"]))
    ledger.record(hyp(
        hyp_id="hyp-2026-002",
        claim="demo.service fails over a missing binary.",
        evidence_for=["ev-2026-002"],
        evidence_against=["ev-2026-001"]))
    kinds = {(link.first_id, link.second_id, link.kind)
             for link in ledger.causal_links()}
    assert ("hyp-2026-001", "hyp-2026-002", "same-incident") in kinds
    assert ("hyp-2026-001", "hyp-2026-002", "shared-evidence") in kinds
    assert ("hyp-2026-001", "hyp-2026-002", "contradiction") in kinds


def test_no_link_invented_between_unrelated_hypotheses(ledger):
    ledger.record(hyp())
    ledger.record(hyp(hyp_id="hyp-2026-002", incident="inc-2026-777",
                      evidence_for=["ev-2026-555"]))
    assert ledger.causal_links() == []


def test_trace_for_incident_includes_failed_with_evidence(ledger):
    ledger.record(hyp())
    ledger.record(hyp(
        hyp_id="hyp-2026-002", status="refuted",
        evidence_against=["ev-2026-009"]))
    trace = ledger.trace("inc-2026-001")
    assert [t["hypothesis_id"] for t in trace] == [
        "hyp-2026-001", "hyp-2026-002"]
    assert trace[1]["failed"] is True
    assert trace[1]["evidence_against"] == ["ev-2026-009"]
    assert ledger.trace("inc-2026-unknown") == []


def test_explain_and_counterevidence_views(ledger):
    ledger.record(hyp(evidence_against=["ev-2026-009"]))
    view = ledger.explain("hyp-2026-001")
    assert view["counterevidence_ever"] == ["ev-2026-009"]
    assert view["versions"] == 1
    assert [r["hypothesis_id"]
            for r in ledger.list_with_counterevidence()] == [
                "hyp-2026-001"]
    with pytest.raises(hz.UnknownHypothesisError):
        ledger.explain("hyp-2026-404")
