# SPDX-License-Identifier: GPL-2.0-only
"""LIF-0302 source provenance tests.

Scope: fixture + tmp_path documents only; no live system path is
read, and every document is treated read-only.  The clock is injected
everywhere, so no test depends on wall time.

The mutated-document test is this slice's NEGATIVE CONTROL: a
document recorded, then changed on disk, must verify as "changed" --
detected and reported, never silently accepted.
"""
import hashlib
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from lifthrasir import provenance as pv  # noqa: E402

FIXTURE = REPO / "tests" / "fixtures" / "provenance" / "fixture-doc.txt"
FIXTURE_SHA256 = (
    "e77de0a1c3377e60f01e1372bd40be7ba8b5c4a7867b073ff0082ff582dbb443")
FIXED_MOMENT = datetime(2026, 11, 12, 3, 0, 0, tzinfo=timezone.utc)
FIXED_TS = "2026-11-12T03:00:00Z"
DIGEST_RE = re.compile(r"^sha256:[a-f0-9]{64}$")


def fixed_clock():
    return FIXED_MOMENT


def test_fixture_record_has_known_hash():
    record = pv.record_source(FIXTURE, clock=fixed_clock)
    assert hashlib.sha256(FIXTURE.read_bytes()).hexdigest() \
        == FIXTURE_SHA256
    assert record.content_hash == FIXTURE_SHA256
    assert record.content_digest == "sha256:" + FIXTURE_SHA256
    assert DIGEST_RE.match(record.content_digest)
    assert record.size_bytes == FIXTURE.stat().st_size
    assert record.source_kind == "file"


def test_identity_is_canonical_and_title_from_first_line():
    record = pv.record_source(FIXTURE, clock=fixed_clock)
    assert record.source_identity == FIXTURE.resolve().as_uri()
    assert record.title == "Lifthrasir provenance fixture document"


def test_retrieval_date_comes_from_injected_clock():
    record = pv.record_source(FIXTURE, clock=fixed_clock)
    assert record.retrieved_at == FIXED_TS
    later = pv.record_source(
        FIXTURE,
        clock=lambda: datetime(2030, 1, 2, 3, 4, 5,
                               tzinfo=timezone.utc))
    assert later.retrieved_at == "2030-01-02T03:04:05Z"


def test_verify_passes_for_unchanged_document():
    record = pv.record_source(FIXTURE, clock=fixed_clock)
    result = pv.verify_reference(record, clock=fixed_clock)
    assert result.status == "unchanged"
    assert result.ok is True
    assert result.actual_digest == record.content_digest
    assert result.verified_at == FIXED_TS


def test_verify_fails_for_mutated_document_negative_control(tmp_path):
    doc = tmp_path / "doc.txt"
    doc.write_text("original content\n", encoding="utf-8")
    record = pv.record_source(doc, clock=fixed_clock)
    doc.write_text("original content\nMUTATED\n", encoding="utf-8")
    result = pv.verify_reference(record, clock=fixed_clock)
    assert result.status == "changed"
    assert result.ok is False
    assert result.actual_digest != result.expected_digest


def test_missing_document_reported_by_name_no_invented_record():
    missing = "definitely-not-a-real-document-0302.txt"
    with pytest.raises(pv.MissingSourceError) as caught:
        pv.record_source(missing, clock=fixed_clock)
    assert missing in str(caught.value)


def test_verify_reports_missing_by_identity(tmp_path):
    doc = tmp_path / "gone.txt"
    doc.write_text("here today\n", encoding="utf-8")
    record = pv.record_source(doc, clock=fixed_clock)
    doc.unlink()
    result = pv.verify_reference(record, clock=fixed_clock)
    assert result.status == "missing"
    assert result.ok is False
    assert result.actual_digest is None
    assert record.source_identity in result.detail


def test_nonlocal_identifier_refused_by_name():
    with pytest.raises(pv.MissingSourceError) as caught:
        pv.record_source("https://example.invalid/doc.txt",
                         clock=fixed_clock)
    assert "https://example.invalid/doc.txt" in str(caught.value)


def test_duplicate_references_one_identity_consistent_hash(tmp_path):
    doc = tmp_path / "shared.txt"
    doc.write_text("shared source\n", encoding="utf-8")
    registry = pv.ProvenanceRegistry(clock=fixed_clock)
    first = registry.register(doc)
    second = registry.register(str(doc))
    third = registry.register(doc.resolve().as_uri())
    assert len(registry) == 1
    assert first is second is third
    assert second.content_hash == first.content_hash
    assert second.source_identity == first.source_identity


def test_registry_refuses_silently_changed_source(tmp_path):
    doc = tmp_path / "watched.txt"
    doc.write_text("version one\n", encoding="utf-8")
    registry = pv.ProvenanceRegistry(clock=fixed_clock)
    registry.register(doc)
    doc.write_text("version two\n", encoding="utf-8")
    with pytest.raises(pv.ChangedSourceError):
        registry.register(doc)


def test_serialization_matches_evidence_shape_and_roundtrips():
    record = pv.record_source(FIXTURE, clock=fixed_clock)
    fields = record.evidence_fields(host_local_id="purpleraider")
    assert fields["content_digest"] == record.content_digest
    assert DIGEST_RE.match(fields["content_digest"])
    assert fields["recorded_at"] == FIXED_TS
    assert fields["source"] == {"component": "mimir",
                                 "host_local_id": "purpleraider"}
    assert fields["artifact_refs"] == [record.source_identity]
    clone = pv.SourceReference.from_dict(record.to_dict())
    assert clone == record


def test_recording_and_verifying_never_modify_the_document():
    before_bytes = FIXTURE.read_bytes()
    before_mtime = FIXTURE.stat().st_mtime_ns
    record = pv.record_source(FIXTURE, clock=fixed_clock)
    pv.verify_reference(record, clock=fixed_clock)
    assert FIXTURE.read_bytes() == before_bytes
    assert FIXTURE.stat().st_mtime_ns == before_mtime
