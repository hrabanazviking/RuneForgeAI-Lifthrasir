"""Local SQLite event store for Mimir memory (LIF-0301).

SPDX-License-Identifier: GPL-2.0-only

Home justification: master roadmap section 3 lays out ``src/`` for
core code, and LIF-0201 already established ``src/lifthrasir/`` as
the core package home (the typed event bus lives there).  The Mimir
evidence store is a core memory-plane component (ADR-0002 process
table: the Mimir evidence store owns append-only hash-linked
evidence records in SQLite + FTS), not a rapid-lab prototype, so it
belongs beside the bus in ``src/lifthrasir/`` rather than in
``lab/`` (the lab home ADR-0002 D2 reserves for prototypes such as
the LIF-0202 collector, whose contract had not stabilised).

Decision basis: ADR-0002 D4 confirms SQLite + FTS with append-only
hash-linked evidence records.  This slice builds the store and its
migrations; exact text search (FTS) is LIF-0303 and is NOT claimed
here.

Records: the store persists records aligned with the LIF-0004 v0.1
shapes (``docs/protocols/schemas/v0.1/`` at the banking seat, main
commit 1c1ae13): incident, hypothesis, plan and evidence records.
The full record JSON is stored verbatim in ``payload_json`` and key
fields are extracted into columns (record id, record type, schema
version, boot id, created/recorded timestamp, summary).  A record
whose ``schema_version`` is not the LIF-0004 pin ``0.1``, whose
``schema`` envelope is not a known v0.1 envelope, or that lacks its
typed identifier is refused.  The LIF-0201 event-bus envelopes are
the store's eventual producers; persisting bus envelopes directly
is future work and is not claimed here.

Tamper evidence: every row carries ``prev_hash`` (the previous
row's ``record_hash``, or the genesis constant for the first row)
and ``record_hash`` = SHA-256 over the previous hash plus the
canonical hash material (record id, type, schema version, boot id,
timestamp and the verbatim payload).  Modifying, deleting or
reordering a stored row breaks ``verify_chain()``.  This is
tamper-EVIDENCE, not tamper-proofing: a writer with raw file
access can rewrite the whole file, and the honest claim is only
that silent edits to individual rows are detectable.

Append-only: the public API offers no mutation.  ``update_record``
and ``delete_record`` exist only to refuse loudly.  There is no
generic SQL passthrough.

Local-only: the store writes only to the single file it was
configured with (plus SQLite's own journal/WAL side files beside
it).  No network, no other paths.  An optional ``allowed_root``
confines the configured file inside a directory tree.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

# LIF-0004 v0.1 pin: the only record schema version this store accepts.
RECORD_SCHEMA_VERSION = "0.1"

GENESIS_HASH = "0" * 64

# envelope value -> (record type, typed id field)
_ENVELOPES = {
    "lifthrasir.incident.v0.1": ("incident", "incident_id"),
    "lifthrasir.hypothesis.v0.1": ("hypothesis", "hypothesis_id"),
    "lifthrasir.plan.v0.1": ("plan", "plan_id"),
    "lifthrasir.evidence.v0.1": ("evidence", "evidence_id"),
}

RECORD_TYPES = frozenset(spec[0] for spec in _ENVELOPES.values())

# Ordered migration steps: (version, name, SQL).  Applied in order,
# each in its own transaction together with its version stamp.
MIGRATIONS = [
    (1, "create events table",
     "CREATE TABLE IF NOT EXISTS events ("
     " seq INTEGER PRIMARY KEY AUTOINCREMENT,"
     " record_id TEXT NOT NULL UNIQUE,"
     " record_type TEXT NOT NULL,"
     " schema_version TEXT NOT NULL,"
     " boot_id TEXT,"
     " created_at TEXT,"
     " payload_json TEXT NOT NULL,"
     " prev_hash TEXT NOT NULL,"
     " record_hash TEXT NOT NULL)"),
    (2, "events indexes and summary column",
     "ALTER TABLE events ADD COLUMN summary TEXT;"
     " CREATE INDEX IF NOT EXISTS idx_events_type"
     " ON events(record_type);"
     " CREATE INDEX IF NOT EXISTS idx_events_boot"
     " ON events(boot_id)"),
]

CURRENT_SCHEMA_VERSION = MIGRATIONS[-1][0]


class EventStoreError(Exception):
    """Base class for all named store refusals."""


class SchemaVersionError(EventStoreError):
    """Raised when a record carries a non-0.1 schema version."""


class MalformedRecordError(EventStoreError):
    """Raised when a record lacks the LIF-0004 v0.1 shape."""


class DuplicateRecordError(EventStoreError):
    """Raised when a record id is appended twice."""


class AppendOnlyError(EventStoreError):
    """Raised by the mutation entry points, which always refuse."""


class StorePathError(EventStoreError):
    """Raised when the configured path is unusable or escapes root."""


def _canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False)


def _record_hash(prev_hash: str, record_id: str, record_type: str,
                 schema_version: str, boot_id: Optional[str],
                 created_at: Optional[str], payload_json: str) -> str:
    material = _canonical_json({
        "boot_id": boot_id,
        "created_at": created_at,
        "payload_json": payload_json,
        "record_id": record_id,
        "record_type": record_type,
        "schema_version": schema_version,
    })
    digest = hashlib.sha256()
    digest.update(prev_hash.encode("utf-8"))
    digest.update(b"\n")
    digest.update(material.encode("utf-8"))
    return digest.hexdigest()


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _extract(record: Dict[str, Any]):
    """Validate a record against the LIF-0004 v0.1 envelope rules.

    Returns (record_id, record_type, boot_id, created_at, summary).
    """
    if not isinstance(record, dict):
        raise MalformedRecordError(
            f"record must be a JSON object, got {type(record).__name__}")
    version = record.get("schema_version")
    if version != RECORD_SCHEMA_VERSION:
        raise SchemaVersionError(
            f"record schema_version must be the LIF-0004 pin "
            f"{RECORD_SCHEMA_VERSION!r}, got {version!r}")
    envelope = record.get("schema")
    if envelope not in _ENVELOPES:
        raise MalformedRecordError(
            f"record schema {envelope!r} is not a known LIF-0004 "
            f"v0.1 envelope {sorted(_ENVELOPES)}")
    record_type, id_field = _ENVELOPES[envelope]
    record_id = record.get(id_field)
    if not isinstance(record_id, str) or not record_id:
        raise MalformedRecordError(
            f"{record_type} record must carry a non-empty {id_field}")
    boot_id = None
    host = record.get("host")
    if isinstance(host, dict) and isinstance(host.get("boot_id"), str):
        boot_id = host["boot_id"]
    source = record.get("source")
    if boot_id is None and isinstance(source, dict) \
            and isinstance(source.get("boot_id"), str):
        boot_id = source["boot_id"]
    if boot_id is None and isinstance(record.get("boot_id"), str):
        boot_id = record["boot_id"]
    created_at = record.get("created_at") or record.get("recorded_at")
    if not isinstance(created_at, str):
        created_at = None
    summary = record.get("summary")
    if not isinstance(summary, str):
        summary = None
    return record_id, record_type, boot_id, created_at, summary


@dataclass(frozen=True)
class StoredRecord:
    seq: int
    record_id: str
    record_type: str
    schema_version: str
    boot_id: Optional[str]
    created_at: Optional[str]
    summary: Optional[str]
    payload: Dict[str, Any]
    prev_hash: str
    record_hash: str


class EventStore:
    """Append-only, hash-linked, local SQLite record store."""

    def __init__(self, path, allowed_root=None):
        raw = str(path)
        if raw in ("", ":memory:") or raw.startswith("file:"):
            raise StorePathError(
                f"store path {raw!r} is not a plain local file path")
        resolved = Path(raw).expanduser().resolve()
        if resolved.is_dir():
            raise StorePathError(
                f"store path {resolved} is a directory, not a file")
        if allowed_root is not None:
            root = Path(str(allowed_root)).expanduser().resolve()
            if resolved != root and root not in resolved.parents:
                raise StorePathError(
                    f"store path {resolved} escapes the configured "
                    f"root {root}")
        resolved.parent.mkdir(parents=True, exist_ok=True)
        self._path = resolved
        self._conn = sqlite3.connect(str(resolved))
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=FULL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        try:
            self._migrate()
        except Exception:
            self._conn.close()
            raise

    # -- migrations -------------------------------------------------
    def _current_version(self) -> int:
        self._conn.execute(
            "CREATE TABLE IF NOT EXISTS schema_migrations ("
            " version INTEGER PRIMARY KEY,"
            " name TEXT NOT NULL,"
            " applied_at TEXT NOT NULL)")
        row = self._conn.execute(
            "SELECT COALESCE(MAX(version), 0) FROM schema_migrations"
        ).fetchone()
        return int(row[0])

    def _migrate(self) -> None:
        current = self._current_version()
        for version, name, sql in MIGRATIONS:
            if version <= current:
                continue
            try:
                self._conn.execute("BEGIN IMMEDIATE")
                for statement in sql.split(";"):
                    statement = statement.strip()
                    if statement:
                        self._conn.execute(statement)
                self._conn.execute(
                    "INSERT INTO schema_migrations"
                    " (version, name, applied_at) VALUES (?, ?, ?)",
                    (version, name, _now()))
                self._conn.commit()
            except Exception:
                self._conn.rollback()
                raise
        # Re-running open on a migrated DB is a no-op (idempotent).

    def schema_version(self) -> int:
        """Current store schema (migration) version."""
        return self._current_version()

    @property
    def path(self) -> Path:
        return self._path

    # -- writes -------------------------------------------------------
    def append(self, record: Dict[str, Any]) -> str:
        """Append one LIF-0004 v0.1 record; returns its record id."""
        record_id, record_type, boot_id, created_at, summary = \
            _extract(record)
        payload_json = _canonical_json(record)
        try:
            self._conn.execute("BEGIN IMMEDIATE")
            row = self._conn.execute(
                "SELECT record_hash FROM events"
                " ORDER BY seq DESC LIMIT 1").fetchone()
            prev_hash = row[0] if row else GENESIS_HASH
            record_hash = _record_hash(
                prev_hash, record_id, record_type,
                RECORD_SCHEMA_VERSION, boot_id, created_at,
                payload_json)
            self._conn.execute(
                "INSERT INTO events (record_id, record_type,"
                " schema_version, boot_id, created_at, payload_json,"
                " prev_hash, record_hash, summary)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (record_id, record_type, RECORD_SCHEMA_VERSION,
                 boot_id, created_at, payload_json, prev_hash,
                 record_hash, summary))
            self._conn.commit()
        except sqlite3.IntegrityError as exc:
            self._conn.rollback()
            raise DuplicateRecordError(
                f"record id {record_id!r} is already stored; the "
                f"store is append-only and ids are unique") from exc
        except Exception:
            self._conn.rollback()
            raise
        return record_id

    def update_record(self, *args, **kwargs):
        raise AppendOnlyError(
            "the Mimir event store is append-only (ADR-0002 D4): "
            "stored records are never updated; append a new record")

    def delete_record(self, *args, **kwargs):
        raise AppendOnlyError(
            "the Mimir event store is append-only (ADR-0002 D4): "
            "stored records are never deleted")

    # -- reads --------------------------------------------------------
    _COLS = ("seq, record_id, record_type, schema_version, boot_id,"
             " created_at, payload_json, record_hash, summary,"
             " prev_hash")

    def _fetch(self, where="", params=()) -> List[StoredRecord]:
        rows = self._conn.execute(
            f"SELECT {self._COLS} FROM events {where}"
            " ORDER BY seq ASC", params).fetchall()
        out = []
        for row in rows:
            out.append(StoredRecord(
                seq=row[0], record_id=row[1], record_type=row[2],
                schema_version=row[3], boot_id=row[4],
                created_at=row[5], payload=json.loads(row[6]),
                prev_hash=row[9], record_hash=row[7],
                summary=row[8]))
        return out

    def get_record(self, record_id: str) -> Optional[StoredRecord]:
        found = self._fetch("WHERE record_id = ?", (record_id,))
        return found[0] if found else None

    def get_by_id(self, record_id: str) -> Optional[Dict[str, Any]]:
        """Return the stored record payload, or None if absent."""
        stored = self.get_record(record_id)
        return stored.payload if stored else None

    def list_all(self) -> List[StoredRecord]:
        return self._fetch()

    def list_by_type(self, record_type: str) -> List[StoredRecord]:
        return self._fetch("WHERE record_type = ?", (record_type,))

    def list_by_boot(self, boot_id: str) -> List[StoredRecord]:
        return self._fetch("WHERE boot_id = ?", (boot_id,))

    def count(self) -> int:
        row = self._conn.execute(
            "SELECT COUNT(*) FROM events").fetchone()
        return int(row[0])

    # -- verification ---------------------------------------------------
    def verify_chain(self) -> bool:
        """Recompute the whole hash chain; True only if intact."""
        return not self.chain_errors()

    def chain_errors(self) -> List[str]:
        errors: List[str] = []
        rows = self._conn.execute(
            "SELECT seq, record_id, record_type, schema_version,"
            " boot_id, created_at, payload_json, prev_hash,"
            " record_hash FROM events ORDER BY seq ASC").fetchall()
        expected_prev = GENESIS_HASH
        expected_seq = 1
        for row in rows:
            (seq, record_id, record_type, schema_version, boot_id,
             created_at, payload_json, prev_hash, record_hash) = row
            if seq != expected_seq:
                errors.append(
                    f"seq gap at stored seq {seq}: expected "
                    f"{expected_seq} (a row was deleted or reordered)")
            expected_seq = seq + 1
            if prev_hash != expected_prev:
                errors.append(
                    f"record {record_id}: prev_hash does not match "
                    f"the previous record_hash (chain link broken)")
            recomputed = _record_hash(
                prev_hash, record_id, record_type, schema_version,
                boot_id, created_at, payload_json)
            if recomputed != record_hash:
                errors.append(
                    f"record {record_id}: stored payload or fields "
                    f"do not match record_hash (record was modified)")
            expected_prev = record_hash
        return errors

    def close(self) -> None:
        self._conn.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        self.close()
        return False
