"""Source provenance for referenced documentation (LIF-0302).

SPDX-License-Identifier: GPL-2.0-only

Home justification: ADR-0002 D4 makes the Mimir evidence store
(SQLite + FTS, append-only hash-linked records) the memory plane's
home, and LIF-0301 lands that store in ``src/lifthrasir/eventstore.py``
-- the store's companion belongs beside it in ``src/lifthrasir/``,
not in ``lab/``.  This module is that companion: it establishes, for
any document the store or a claim references, WHO the source is
(canonical identity), WHEN it was retrieved (an injectable clock, so
tests never depend on wall time), and WHAT its content was (a
SHA-256 content hash), and it can later verify a reference by
recomputation.  A changed document is detected and reported as
changed; it is never silently accepted.

Field alignment with the LIF-0004 v0.1 evidence shape
(``docs/protocols/schemas/v0.1/evidence.schema.json``):

- the content hash serializes as ``content_digest`` in the schema's
  own format, ``sha256:`` followed by 64 lowercase hex characters;
- the retrieval timestamp serializes as ``recorded_at`` (the evidence
  schema's timestamp field) in the same ``%Y-%m-%dT%H:%M:%SZ`` UTC
  form the store and the event bus use;
- ``evidence_fields()`` emits the ``source`` object with
  ``component: \"mimir\"`` (the schema's enum value for the memory
  plane that owns provenance) and the canonical identity in
  ``artifact_refs``.

Field alignment with LIF-0301's store: the store's tamper-evidence
columns are ``prev_hash`` / ``record_hash`` over canonical payloads;
this module's per-document digest is the payload-level hash a stored
``document`` evidence record carries in its ``content_digest``, so a
provenance record can be appended through the store unchanged.  No
field-name mismatch was found; the store names no source-identity
field of its own, so ``source_identity`` is introduced here and
recorded as this slice's naming for LIF-0303+ to reuse.

Read-only law: referenced documents are opened read-only and hashed
in a stream; hashing never modifies them.  A reference whose document
cannot be found is reported BY NAME (``MissingSourceError`` on
record, ``status=\"missing\"`` on verify) -- no record is ever
invented for a document that was not read.

Identifiers: a reference may be a local file path, a ``file://`` URI,
or a recorded source identifier that resolves to a local path
relative to an optional base directory.  A non-local URI (``http:``,
``urn:``, ...) carries no locally readable content, so recording it
refuses with ``MissingSourceError`` naming it -- retrieval of remote
documents is future work and is not claimed here.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Dict, Optional, Union

DIGEST_PREFIX = "sha256:"
_CHUNK = 65536


class ProvenanceError(Exception):
    """Base class for all named provenance refusals."""


class MissingSourceError(ProvenanceError):
    """Raised when a referenced document cannot be found or read."""


class ChangedSourceError(ProvenanceError):
    """Raised when a known identity re-registers with a new hash."""


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _format_ts(moment: datetime) -> str:
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            block = handle.read(_CHUNK)
            if not block:
                break
            digest.update(block)
    return digest.hexdigest()


def _first_line_title(path: Path) -> Optional[str]:
    try:
        with path.open("rb") as handle:
            raw = handle.readline(8192)
    except OSError:
        return None
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        return None
    title = text.strip().lstrip("#").strip()
    return title[:120] if title else None


def _resolve(source: Union[str, Path], base_dir) -> Path:
    """Resolve a reference to a local file path or refuse by name."""
    text = str(source)
    if text.startswith("file://"):
        candidate = Path(text[len("file://"):])
    elif "://" in text or text.startswith("urn:"):
        raise MissingSourceError(
            f"referenced document {text!r} is a non-local identifier "
            f"with no locally readable content; no record invented")
    else:
        candidate = Path(text)
    if not candidate.is_absolute() and base_dir is not None:
        candidate = Path(base_dir) / candidate
    resolved = candidate.expanduser().resolve()
    if not resolved.is_file():
        raise MissingSourceError(
            f"referenced document {text!r} not found "
            f"(resolved to {resolved}); no record invented")
    return resolved


@dataclass(frozen=True)
class SourceReference:
    """One provenance record for one referenced document."""

    source_identity: str
    source_kind: str
    title: Optional[str]
    retrieved_at: str
    content_hash: str
    size_bytes: int

    @property
    def content_digest(self) -> str:
        """The hash in the LIF-0004 evidence format."""
        return DIGEST_PREFIX + self.content_hash

    def to_dict(self) -> Dict:
        return {
            "source_identity": self.source_identity,
            "source_kind": self.source_kind,
            "title": self.title,
            "retrieved_at": self.retrieved_at,
            "content_hash": self.content_hash,
            "content_digest": self.content_digest,
            "size_bytes": self.size_bytes,
        }

    @classmethod
    def from_dict(cls, data: Dict) -> "SourceReference":
        return cls(
            source_identity=data["source_identity"],
            source_kind=data["source_kind"],
            title=data.get("title"),
            retrieved_at=data["retrieved_at"],
            content_hash=data["content_hash"],
            size_bytes=int(data["size_bytes"]),
        )

    def evidence_fields(self, host_local_id: str = "local") -> Dict:
        """The LIF-0004 v0.1 evidence-shape fields this record fills.

        A full evidence record also needs an evidence_id, incident_id,
        kind, summary and evidence_status, which belong to the claim
        being evidenced, not to provenance; this returns exactly the
        overlapping fields, named as the schema names them.
        """
        return {
            "content_digest": self.content_digest,
            "recorded_at": self.retrieved_at,
            "source": {"component": "mimir",
                       "host_local_id": host_local_id},
            "artifact_refs": [self.source_identity],
        }


@dataclass(frozen=True)
class VerificationResult:
    """Outcome of re-verifying one recorded reference."""

    source_identity: str
    status: str  # "unchanged" | "changed" | "missing"
    expected_digest: str
    actual_digest: Optional[str]
    verified_at: str
    detail: str

    @property
    def ok(self) -> bool:
        return self.status == "unchanged"

    def to_dict(self) -> Dict:
        return {
            "source_identity": self.source_identity,
            "status": self.status,
            "ok": self.ok,
            "expected_digest": self.expected_digest,
            "actual_digest": self.actual_digest,
            "verified_at": self.verified_at,
            "detail": self.detail,
        }


def record_source(source, clock: Callable[[], datetime] = _utc_now,
                  base_dir=None) -> SourceReference:
    """Record identity, retrieval date and hash for one document.

    ``clock`` is injectable: tests pass a fixed clock so the recorded
    retrieval date never depends on wall time.  The document is read
    read-only.  A missing document raises ``MissingSourceError``
    naming the reference; no record is invented.
    """
    resolved = _resolve(source, base_dir)
    return SourceReference(
        source_identity=resolved.as_uri(),
        source_kind="file",
        title=_first_line_title(resolved),
        retrieved_at=_format_ts(clock()),
        content_hash=_hash_file(resolved),
        size_bytes=resolved.stat().st_size,
    )


def verify_reference(reference, clock: Callable[[], datetime] = _utc_now,
                     base_dir=None) -> VerificationResult:
    """Recompute a recorded reference and compare.

    Returns status ``unchanged`` only when the recomputed hash equals
    the recorded hash; ``changed`` when the document exists but its
    hash differs (the negative control -- a mutated document is
    detected, never silently accepted); ``missing`` when it can no
    longer be found, named by its recorded identity.
    """
    if isinstance(reference, dict):
        reference = SourceReference.from_dict(reference)
    verified_at = _format_ts(clock())
    identity = reference.source_identity
    try:
        current = record_source(identity, clock=clock, base_dir=base_dir)
    except MissingSourceError:
        return VerificationResult(
            source_identity=identity, status="missing",
            expected_digest=reference.content_digest, actual_digest=None,
            verified_at=verified_at,
            detail=f"referenced document {identity!r} no longer found; "
                   f"recorded digest cannot be re-verified")
    if current.content_hash == reference.content_hash:
        return VerificationResult(
            source_identity=identity, status="unchanged",
            expected_digest=reference.content_digest,
            actual_digest=current.content_digest,
            verified_at=verified_at,
            detail="recomputed hash matches the recorded hash")
    return VerificationResult(
        source_identity=identity, status="changed",
        expected_digest=reference.content_digest,
        actual_digest=current.content_digest,
        verified_at=verified_at,
        detail="recomputed hash differs from the recorded hash; "
               "the document changed since retrieval")


class ProvenanceRegistry:
    """Deduplicating registry: one identity per canonical source.

    Registering the same source again -- under any spelling that
    resolves to the same canonical identity -- returns the existing
    record when the content hash is unchanged.  If the same identity
    now hashes differently, registration refuses with
    ``ChangedSourceError``: a changed document is surfaced, never
    silently folded into the existing identity.
    """

    def __init__(self, clock: Callable[[], datetime] = _utc_now):
        self._clock = clock
        self._records: Dict[str, SourceReference] = {}

    def register(self, source, base_dir=None) -> SourceReference:
        fresh = record_source(source, clock=self._clock,
                              base_dir=base_dir)
        existing = self._records.get(fresh.source_identity)
        if existing is None:
            self._records[fresh.source_identity] = fresh
            return fresh
        if existing.content_hash == fresh.content_hash:
            return existing
        raise ChangedSourceError(
            f"source {fresh.source_identity!r} changed since it was "
            f"recorded: was {existing.content_digest}, "
            f"now {fresh.content_digest}")

    def get(self, source_identity: str) -> Optional[SourceReference]:
        return self._records.get(source_identity)

    def __len__(self) -> int:
        return len(self._records)

    def __contains__(self, source_identity: str) -> bool:
        return source_identity in self._records
