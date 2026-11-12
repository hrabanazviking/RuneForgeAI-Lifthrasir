# SPDX-License-Identifier: GPL-2.0-only
"""LIF-0301 local SQLite event store tests.

Scope: temporary database files only (pytest tmp_path).  No test
touches a live system path.  Records use the LIF-0004 v0.1 valid
example shapes (banked on main as 1c1ae13; read from the seat
checkout because this worktree predates that banking).

The tamper test is this slice's NEGATIVE CONTROL: a stored row is
mutated through a raw sqlite3 connection, bypassing the API, and
chain verification must fail.
"""
import sqlite3
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from lifthrasir import eventstore as es  # noqa: E402


def incident(record_id="inc-2026-001", boot_id="boot-7f3a"):
    return {
        "schema": "lifthrasir.incident.v0.1",
        "schema_version": "0.1",
        "incident_id": record_id,
        "status": "investigating",
        "severity": "medium",
        "summary": "demo.service repeatedly fails to start.",
        "host": {"host_local_id": "lab-guest-01", "boot_id": boot_id},
        "observed_at": "2026-11-05T17:02:11Z",
        "created_at": "2026-11-05T17:02:15Z",
        "symptoms": ["systemd reports demo.service in failed state"],
        "evidence_refs": ["ev-2026-001"],
    }


def evidence(record_id="ev-2026-001", boot_id="boot-7f3a"):
    return {
        "schema": "lifthrasir.evidence.v0.1",
        "schema_version": "0.1",
        "evidence_id": record_id,
        "incident_id": "inc-2026-001",
        "kind": "log-excerpt",
        "recorded_at": "2026-11-05T17:02:11Z",
        "source": {"component": "heimdall",
                   "host_local_id": "lab-guest-01",
                   "boot_id": boot_id},
        "summary": "Journal excerpt showing demo.service failing.",
        "content_digest": "sha256:" + "0123456789abcdef" * 4,
        "evidence_status": "reproducer",
    }


def hypothesis(record_id="hyp-2026-001"):
    return {
        "schema": "lifthrasir.hypothesis.v0.1",
        "schema_version": "0.1",
        "hypothesis_id": record_id,
        "incident_id": "inc-2026-001",
        "claim": "demo.service fails over a missing config path.",
        "status": "proposed",
        "confidence": 0.4,
        "evidence_for": ["ev-2026-001"],
        "evidence_against": [],
        "test_plan": "Check the referenced path in the lab guest.",
        "evidence_status": "hypothesis",
        "created_at": "2026-11-05T17:05:00Z",
    }


@pytest.fixture()
def store(tmp_path):
    with es.EventStore(tmp_path / "events.db") as s:
        yield s


def test_append_and_read_back_equality(store):
    rec = incident()
    assert store.append(rec) == "inc-2026-001"
    assert store.get_by_id("inc-2026-001") == rec
    stored = store.get_record("inc-2026-001")
    assert stored.record_type == "incident"
    assert stored.boot_id == "boot-7f3a"
    assert stored.summary == rec["summary"]
    assert store.get_by_id("inc-missing") is None


def test_hash_chain_verifies(store):
    store.append(evidence())
    store.append(incident())
    store.append(hypothesis())
    rows = store.list_all()
    assert rows[0].prev_hash == es.GENESIS_HASH
    assert rows[1].prev_hash == rows[0].record_hash
    assert rows[2].prev_hash == rows[1].record_hash
    assert store.verify_chain() is True
    assert store.chain_errors() == []


def test_chain_survives_reopen(tmp_path):
    path = tmp_path / "events.db"
    with es.EventStore(path) as s:
        s.append(incident())
        head = s.list_all()[-1].record_hash
    with es.EventStore(path) as s:
        s.append(evidence())
        rows = s.list_all()
        assert rows[-1].prev_hash == head
        assert s.verify_chain() is True


def test_tamper_detection_negative_control(store, tmp_path):
    store.append(incident())
    store.append(evidence())
    assert store.verify_chain() is True
    raw = sqlite3.connect(str(tmp_path / "events.db"))
    raw.execute(
        "UPDATE events SET payload_json = ? WHERE record_id = ?",
        ('{"schema":"lifthrasir.incident.v0.1","tampered":true}',
         "inc-2026-001"))
    raw.commit()
    raw.close()
    assert store.verify_chain() is False
    assert store.chain_errors() != []


def test_tamper_deletion_breaks_chain(store, tmp_path):
    store.append(incident())
    store.append(evidence())
    store.append(hypothesis())
    raw = sqlite3.connect(str(tmp_path / "events.db"))
    raw.execute("DELETE FROM events WHERE record_id = ?",
                ("ev-2026-001",))
    raw.commit()
    raw.close()
    assert store.verify_chain() is False


def test_migration_from_scratch(tmp_path):
    path = tmp_path / "fresh.db"
    with es.EventStore(path) as s:
        assert s.schema_version() == es.CURRENT_SCHEMA_VERSION
        assert s.count() == 0
        assert s.list_all() == []
        assert s.verify_chain() is True
    raw = sqlite3.connect(str(path))
    versions = [r[0] for r in raw.execute(
        "SELECT version FROM schema_migrations ORDER BY version")]
    raw.close()
    assert versions == [v for v, _, _ in es.MIGRATIONS]


def test_migration_from_version_zero(tmp_path):
    # A v-at-0 database: the migrations table exists, no step applied,
    # no events table yet.  Opening the store must upgrade it.
    path = tmp_path / "v0.db"
    raw = sqlite3.connect(str(path))
    raw.execute(
        "CREATE TABLE schema_migrations (version INTEGER PRIMARY KEY,"
        " name TEXT NOT NULL, applied_at TEXT NOT NULL)")
    raw.commit()
    raw.close()
    with es.EventStore(path) as s:
        assert s.schema_version() == es.CURRENT_SCHEMA_VERSION
        s.append(incident())
        assert s.verify_chain() is True


def test_migration_upgrade_from_v1_preserves_rows(tmp_path):
    # Build a genuine v1 database with only the first migration
    # applied, insert a row under the v1 shape, then upgrade.
    path = tmp_path / "v1.db"
    raw = sqlite3.connect(str(path))
    raw.execute(
        "CREATE TABLE schema_migrations (version INTEGER PRIMARY KEY,"
        " name TEXT NOT NULL, applied_at TEXT NOT NULL)")
    version, name, sql = es.MIGRATIONS[0]
    raw.execute(sql)
    raw.execute(
        "INSERT INTO schema_migrations VALUES (?, ?, ?)",
        (version, name, "2026-11-12T00:00:00Z"))
    import json as _json
    payload = _json.dumps(incident(), sort_keys=True,
                          separators=(",", ":"))
    record_hash = es._record_hash(
        es.GENESIS_HASH, "inc-2026-001", "incident", "0.1",
        "boot-7f3a", "2026-11-05T17:02:15Z", payload)
    raw.execute(
        "INSERT INTO events (record_id, record_type, schema_version,"
        " boot_id, created_at, payload_json, prev_hash, record_hash)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        ("inc-2026-001", "incident", "0.1", "boot-7f3a",
         "2026-11-05T17:02:15Z", payload, es.GENESIS_HASH,
         record_hash))
    raw.commit()
    raw.close()
    with es.EventStore(path) as s:
        assert s.schema_version() == es.CURRENT_SCHEMA_VERSION
        assert s.get_by_id("inc-2026-001") == incident()
        assert s.verify_chain() is True
        # Migration is idempotent: reopening changes nothing.
    with es.EventStore(path) as s:
        assert s.count() == 1
        assert s.verify_chain() is True


def test_append_only_api_refuses_mutation(store):
    store.append(incident())
    with pytest.raises(es.AppendOnlyError):
        store.update_record("inc-2026-001", {"summary": "changed"})
    with pytest.raises(es.AppendOnlyError):
        store.delete_record("inc-2026-001")
    assert store.get_by_id("inc-2026-001") == incident()
    assert store.verify_chain() is True


def test_wrong_schema_version_refused(store):
    bad = incident()
    bad["schema_version"] = "0.2"
    with pytest.raises(es.SchemaVersionError):
        store.append(bad)
    missing = incident()
    del missing["schema_version"]
    with pytest.raises(es.SchemaVersionError):
        store.append(missing)
    assert store.count() == 0


def test_unknown_envelope_and_missing_id_refused(store):
    bad = incident()
    bad["schema"] = "lifthrasir.command.v0.1"
    with pytest.raises(es.MalformedRecordError):
        store.append(bad)
    noid = evidence()
    del noid["evidence_id"]
    with pytest.raises(es.MalformedRecordError):
        store.append(noid)
    assert store.count() == 0


def test_duplicate_id_refused(store):
    store.append(incident())
    with pytest.raises(es.DuplicateRecordError):
        store.append(incident())
    assert store.count() == 1


def test_list_by_type_and_boot(store):
    store.append(incident(boot_id="boot-a"))
    store.append(evidence(boot_id="boot-a"))
    store.append(incident("inc-2026-002", boot_id="boot-b"))
    store.append(hypothesis())
    assert [r.record_id for r in store.list_by_type("incident")] == [
        "inc-2026-001", "inc-2026-002"]
    assert [r.record_id for r in store.list_by_type("evidence")] == [
        "ev-2026-001"]
    assert [r.record_id for r in store.list_by_boot("boot-a")] == [
        "inc-2026-001", "ev-2026-001"]
    assert store.list_by_boot("boot-nope") == []
    assert store.count() == 4


def test_path_confinement(tmp_path):
    with pytest.raises(es.StorePathError):
        es.EventStore(":memory:")
    with pytest.raises(es.StorePathError):
        es.EventStore(tmp_path / "outside.db",
                      allowed_root=tmp_path / "inner")
    nested = tmp_path / "inner" / "events.db"
    with es.EventStore(nested, allowed_root=tmp_path / "inner") as s:
        s.append(incident())
        assert s.path == nested.resolve()
    assert not (tmp_path / "outside.db").exists()
