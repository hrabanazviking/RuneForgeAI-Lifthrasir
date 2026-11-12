"""Durable transaction state and undo manifest (LIF-0405).

SPDX-License-Identifier: GPL-2.0-only

Home justification: master roadmap section 3 places core code in
``src/``, and the P4 authority boundary already lives in
``src/lifthrasir/`` (actions LIF-0401, policy LIF-0402, executor
LIF-0403, approval LIF-0404).  Durable transaction state is that
boundary's memory: the approval ledger (LIF-0404) is explicitly
in-memory with "durable state is LIF-0405", and the event store
(LIF-0301) set the durable-store pattern this module follows
(SQLite, WAL, synchronous=FULL, versioned migrations, hash-linked
integrity).  The transaction store therefore lives beside them,
not in ``lab/``.

What this slice is, and is not (evidence-status honesty):

- It RECORDS transactions durably: a transaction is created once,
  in state ``planned``, with its full step list and, recorded
  BEFORE any execution, the undo manifest -- the inverse action
  for every step, in the form the LIF-0401 catalog names.  State
  then moves only along the explicit transition table below, and
  every transition is appended to a hash-chained history, so a
  crash or restart recovers exactly the last committed state by
  reopening the same file.  This is the durable backing the P5
  reversal tests (LIF-0505) and the kill-switch recovery
  (LIF-0406) build on.
- It EXECUTES nothing.  No step, forward or undo, is run here;
  execution belongs to the confined executor (LIF-0403) under a
  policy grant (LIF-0402) and an approval (LIF-0404).  This module
  is the record those components write to and recover from.
- Pure user-space library code: it writes only to the single
  caller-supplied file it was configured with (plus SQLite's own
  journal/WAL side files beside it).  No ambient root, no network,
  no mutation of any real system state, and nothing touching
  bootloader, kernel, firmware, partitions, encryption or trust
  roots (master roadmap section 0 invariants).  An optional
  ``allowed_root`` confines the configured file inside a tree.

Integrity: every transaction row stores the canonical payload
plus ``record_hash`` = SHA-256 over the payload and its binding
fields.  Reads recompute the hash and cross-check the duplicated
columns; a mismatch is a named refusal (CorruptTransactionError),
never a silent repair.  An unknown stored state is likewise
refused by name (UnknownStateError): corrupt or foreign state is
never coerced into a known state.  This is tamper-EVIDENCE, not
tamper-proofing -- a writer with raw file access can rewrite the
whole file; silent edits to individual rows are detectable.

Undo rules (fail closed):

- Forward verbs and undo verbs are validated against the LIF-0401
  catalog: unknown or prohibited verbs are refused, a step's
  target type must fit its verb, and an undo verb, when present,
  must be exactly the undo method the catalog names for the
  forward verb.  A catalog verb whose undo method is ``none``
  takes no undo entry.
- A step is mutating when its catalog scope is not
  ``live-readonly``.  A transaction is undoable only when every
  mutating step carries its catalog undo.  A transaction missing
  one is still recorded -- honestly, as non-undoable -- and any
  undo attempt against it is refused (NonUndoableError) naming
  the steps that lack an inverse.
- Undo may be planned only from states where something was
  actually executed (``executed``, ``verified``, ``failed``,
  ``undo_failed``).  Undoing a ``planned``/``approved``
  transaction (nothing ran; abort it instead), an ``aborted``
  one, or one still ``executing``/``undoing`` is refused, and
  undoing an already-``undone`` transaction is refused by name
  (AlreadyUndoneError): undo is never applied twice.
"""
from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .actions import ActionError, get_action

TRANSACTION_SCHEMA = "lifthrasir.transaction.v0.1"
TRANSACTION_SCHEMA_VERSION = "0.1"

GENESIS_HASH = "0" * 64

# Explicit transaction states.  A stored state outside this set is
# corrupt/foreign and is refused, never coerced.
STATES = (
    "planned", "approved", "executing", "executed", "verified",
    "failed", "aborted", "undoing", "undone", "undo_failed",
)
_STATE_SET = frozenset(STATES)

# The only legal state moves.  Terminal states map to ().
TRANSITIONS: Dict[str, Tuple[str, ...]] = {
    "planned": ("approved", "executing", "aborted"),
    "approved": ("executing", "aborted"),
    "executing": ("executed", "failed"),
    "executed": ("verified", "failed", "undoing"),
    "verified": ("undoing",),
    "failed": ("undoing",),
    "aborted": (),
    "undoing": ("undone", "undo_failed"),
    "undone": (),
    "undo_failed": ("undoing",),
}
TERMINAL_STATES = frozenset({"undone", "aborted"})
# States from which an undo may be planned (something has run).
UNDO_ENTRY_STATES = frozenset(
    {"executed", "verified", "failed", "undo_failed"})

_TX_RE = re.compile(r"^tx-[a-z0-9][a-z0-9-]*$")
_PLAN_RE = re.compile(r"^plan-[a-z0-9][a-z0-9-]*$")
_STEP_RE = re.compile(r"^step-[a-z0-9][a-z0-9-]*$")
_DIGEST_RE = re.compile(r"^sha256:[a-f0-9]{64}$")
_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.@-]*$")
_UNIT_RE = re.compile(
    r"^[A-Za-z0-9][A-Za-z0-9_.@-]*\.(service|timer|socket|mount)$")
_PATH_RE = re.compile(r"^/[A-Za-z0-9_./@+~-]+$")
_SHELL_META = (";", "|", "&", "$", "`", "<", ">", "\n", "\r", "\\")

_RECORD_FIELDS = frozenset({
    "schema", "schema_version", "transaction_id", "plan_id",
    "plan_digest", "title", "state", "created_at", "expires_at",
    "steps",
})
_STEP_FIELDS = frozenset({
    "step_id", "action_verb", "target", "args", "undo",
    "prior_digest",
})
_UNDO_FIELDS = frozenset({"action_verb", "target", "args"})
_TARGET_FIELDS = frozenset({"type", "name"})

# Ordered migration steps: (version, name, SQL).  Applied in order,
# each in its own transaction together with its version stamp.
MIGRATIONS = [
    (1, "create transactions table",
     "CREATE TABLE IF NOT EXISTS transactions ("
     " seq INTEGER PRIMARY KEY AUTOINCREMENT,"
     " transaction_id TEXT NOT NULL UNIQUE,"
     " plan_id TEXT NOT NULL,"
     " state TEXT NOT NULL,"
     " created_at TEXT NOT NULL,"
     " updated_at TEXT NOT NULL,"
     " payload_json TEXT NOT NULL,"
     " record_hash TEXT NOT NULL)"),
    (2, "transition history table and indexes",
     "CREATE TABLE IF NOT EXISTS tx_history ("
     " seq INTEGER PRIMARY KEY AUTOINCREMENT,"
     " transaction_id TEXT NOT NULL,"
     " from_state TEXT,"
     " to_state TEXT NOT NULL,"
     " at TEXT NOT NULL,"
     " detail TEXT NOT NULL,"
     " tx_hash TEXT NOT NULL,"
     " prev_hash TEXT NOT NULL,"
     " entry_hash TEXT NOT NULL);"
     " CREATE INDEX IF NOT EXISTS idx_tx_history_tx"
     " ON tx_history(transaction_id);"
     " CREATE INDEX IF NOT EXISTS idx_tx_state"
     " ON transactions(state)"),
]
CURRENT_MIGRATION_VERSION = MIGRATIONS[-1][0]


class TransactionError(Exception):
    """Base class for all named transaction-store refusals."""


class MalformedTransactionError(TransactionError):
    """Raised when a record breaks the v0.1 shape or catalog rules."""


class DuplicateTransactionError(TransactionError):
    """Raised when a transaction id is created twice."""


class UnknownTransactionError(TransactionError):
    """Raised when an operation names an unknown transaction id."""


class UnknownStateError(TransactionError):
    """Raised for a state outside the explicit STATES set, whether
    requested by a caller or found stored in the file."""


class InvalidTransitionError(TransactionError):
    """Raised when a state move is not in the transition table."""


class CorruptTransactionError(TransactionError):
    """Raised when stored bytes fail their integrity hash or the
    stored columns disagree with the stored payload."""


class NonUndoableError(TransactionError):
    """Raised when an undo is attempted on a transaction that
    cannot be undone from its state or lacks a complete manifest."""


class AlreadyUndoneError(NonUndoableError):
    """Raised when undo is attempted on an undone transaction:
    undo is never applied twice."""


class StaleTimestampError(TransactionError):
    """Raised when a transition timestamp runs backwards."""


class TransactionPathError(TransactionError):
    """Raised when the configured path is unusable or escapes root."""


class DirectMutationError(TransactionError):
    """Raised by entry points that would mutate/delete a record
    outside the transition table; those always refuse."""


def _canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False)


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_ts(value: Any, field_name: str) -> datetime:
    if not isinstance(value, str) or not value:
        raise MalformedTransactionError(
            f"{field_name} must be an RFC3339 string")
    text = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        moment = datetime.fromisoformat(text)
    except ValueError as exc:
        raise MalformedTransactionError(
            f"{field_name} {value!r} is not a valid timestamp") from exc
    if moment.tzinfo is None:
        raise MalformedTransactionError(
            f"{field_name} must carry a timezone")
    return moment.astimezone(timezone.utc)


def _record_hash(payload_json: str) -> str:
    digest = hashlib.sha256()
    digest.update(b"lifthrasir.transaction.v0.1\n")
    digest.update(payload_json.encode("utf-8"))
    return digest.hexdigest()


def _entry_hash(prev_hash: str, transaction_id: str,
                from_state: Optional[str], to_state: str, at: str,
                detail: str, tx_hash: str) -> str:
    material = _canonical_json({
        "at": at, "detail": detail, "from_state": from_state or "",
        "to_state": to_state, "transaction_id": transaction_id,
        "tx_hash": tx_hash,
    })
    digest = hashlib.sha256()
    digest.update(prev_hash.encode("utf-8"))
    digest.update(b"\n")
    digest.update(material.encode("utf-8"))
    return digest.hexdigest()


def _check_no_shell(value: Any, where: str) -> None:
    if isinstance(value, str):
        for token in _SHELL_META:
            if token in value:
                raise MalformedTransactionError(
                    f"{where} contains a shell metacharacter "
                    f"{token!r}: actions are typed values, never "
                    "shell strings")
        if "*" in value or "?" in value:
            raise MalformedTransactionError(
                f"{where} contains a wildcard: targets must name "
                "exactly one resource")


def _spec_for(verb: Any):
    try:
        return get_action(verb)
    except ActionError as exc:
        raise MalformedTransactionError(str(exc)) from exc


def _check_target(spec, target: Any, where: str) -> Dict[str, str]:
    if not isinstance(target, dict):
        raise MalformedTransactionError(f"{where} must be an object")
    extra = set(target) - _TARGET_FIELDS
    if extra:
        raise MalformedTransactionError(
            f"{where} has unknown fields {sorted(extra)}")
    ttype, name = target.get("type"), target.get("name")
    if not isinstance(ttype, str) or not isinstance(name, str) \
            or not name:
        raise MalformedTransactionError(
            f"{where} needs a target type and a non-empty name")
    if ttype not in spec.target_types:
        raise MalformedTransactionError(
            f"verb {spec.verb!r} does not act on target type "
            f"{ttype!r}; allowed: {list(spec.target_types)}")
    _check_no_shell(name, f"{where} name")
    if ttype == "systemd-unit":
        if not _UNIT_RE.match(name):
            raise MalformedTransactionError(
                f"{where} name {name!r} is not a systemd unit name")
    elif ttype == "config-file":
        if not _PATH_RE.match(name) or ".." in name:
            raise MalformedTransactionError(
                f"{where} name {name!r} must be an absolute path "
                "without traversal")
    elif not _NAME_RE.match(name):
        raise MalformedTransactionError(
            f"{where} name {name!r} must be a plain identifier")
    return {"type": ttype, "name": name}


def _check_args(args: Any, where: str) -> Dict[str, Any]:
    if args is None:
        return {}
    if not isinstance(args, dict):
        raise MalformedTransactionError(f"{where} must be an object")
    for key, value in args.items():
        if not isinstance(key, str):
            raise MalformedTransactionError(
                f"{where} keys must be strings")
        _check_no_shell(value, f"{where}[{key!r}]")
    try:
        _canonical_json(args)
    except (TypeError, ValueError) as exc:
        raise MalformedTransactionError(
            f"{where} is not JSON-serializable: {exc}") from exc
    return dict(args)


def _normalize_step(step: Any, seen: set) -> Dict[str, Any]:
    if not isinstance(step, dict):
        raise MalformedTransactionError("each step must be an object")
    extra = set(step) - _STEP_FIELDS
    if extra:
        raise MalformedTransactionError(
            f"step has unknown fields {sorted(extra)}")
    step_id = step.get("step_id")
    if not isinstance(step_id, str) or not _STEP_RE.match(step_id):
        raise MalformedTransactionError(
            f"step_id {step_id!r} is malformed (want step-<name>)")
    if step_id in seen:
        raise MalformedTransactionError(
            f"duplicate step_id {step_id!r} in one transaction")
    seen.add(step_id)
    spec = _spec_for(step.get("action_verb"))
    target = _check_target(spec, step.get("target"),
                           f"step {step_id} target")
    args = _check_args(step.get("args"), f"step {step_id} args")
    prior = step.get("prior_digest")
    if prior is not None and not (isinstance(prior, str)
                                  and _DIGEST_RE.match(prior)):
        raise MalformedTransactionError(
            f"step {step_id} prior_digest must be 'sha256:' plus "
            "64 hex characters")
    undo = step.get("undo")
    undo_norm = None
    if undo is not None:
        if not isinstance(undo, dict):
            raise MalformedTransactionError(
                f"step {step_id} undo must be an object or null")
        extra_u = set(undo) - _UNDO_FIELDS
        if extra_u:
            raise MalformedTransactionError(
                f"step {step_id} undo has unknown fields "
                f"{sorted(extra_u)}")
        if spec.undo_method == "none":
            raise MalformedTransactionError(
                f"step {step_id}: verb {spec.verb!r} has undo "
                "method 'none' in the LIF-0401 catalog and takes "
                "no undo entry")
        uspec = _spec_for(undo.get("action_verb"))
        if uspec.verb != spec.undo_method:
            raise MalformedTransactionError(
                f"step {step_id}: the catalog names "
                f"{spec.undo_method!r} as the undo for "
                f"{spec.verb!r}, got {uspec.verb!r}")
        utarget = undo.get("target")
        if utarget is None:
            utarget = target
        utarget = _check_target(uspec, utarget,
                                f"step {step_id} undo target")
        undo_norm = {
            "action_verb": uspec.verb, "target": utarget,
            "args": _check_args(undo.get("args"),
                                f"step {step_id} undo args"),
        }
    return {
        "step_id": step_id, "action_verb": spec.verb,
        "target": target, "args": args, "undo": undo_norm,
        "prior_digest": prior,
        "mutating": spec.scope != "live-readonly",
        "risk_level": spec.risk_level, "scope": spec.scope,
    }


def validate_transaction(record: Any) -> Dict[str, Any]:
    """Validate one transaction record; return its stored payload.

    The returned payload is the normalized creation payload: state
    ``planned``, ``updated_at`` equal to ``created_at``, steps in
    recorded order with catalog facts (mutating flag, risk, scope)
    pinned at creation time, and the computed ``undoable`` flag.
    The store adds nothing beyond this and certifies nothing about
    execution -- it proves the record is well-formed and durable.
    """
    if not isinstance(record, dict):
        raise MalformedTransactionError(
            f"transaction must be a JSON object, got "
            f"{type(record).__name__}")
    extra = set(record) - _RECORD_FIELDS
    if extra:
        raise MalformedTransactionError(
            f"transaction has unknown fields {sorted(extra)}")
    if record.get("schema") != TRANSACTION_SCHEMA:
        raise MalformedTransactionError(
            f"transaction schema must be {TRANSACTION_SCHEMA!r}, "
            f"got {record.get('schema')!r}")
    if record.get("schema_version") != TRANSACTION_SCHEMA_VERSION:
        raise MalformedTransactionError(
            f"transaction schema_version must be the pin "
            f"{TRANSACTION_SCHEMA_VERSION!r}, got "
            f"{record.get('schema_version')!r}")
    tx_id = record.get("transaction_id")
    if not isinstance(tx_id, str) or not _TX_RE.match(tx_id):
        raise MalformedTransactionError(
            f"transaction_id {tx_id!r} is malformed (want tx-<name>)")
    plan_id = record.get("plan_id")
    if not isinstance(plan_id, str) or not _PLAN_RE.match(plan_id):
        raise MalformedTransactionError(
            f"plan_id {plan_id!r} is malformed (want plan-<name>)")
    plan_digest = record.get("plan_digest")
    if plan_digest is not None and not (
            isinstance(plan_digest, str)
            and _DIGEST_RE.match(plan_digest)):
        raise MalformedTransactionError(
            "plan_digest must be 'sha256:' plus 64 hex characters")
    title = record.get("title")
    if not isinstance(title, str) or not title or len(title) > 512:
        raise MalformedTransactionError(
            "title must be a non-empty string of at most 512 chars")
    if record.get("state", "planned") != "planned":
        raise MalformedTransactionError(
            "a new transaction starts in state 'planned'; later "
            "states are reached only via the transition table")
    created = _parse_ts(record.get("created_at"), "created_at")
    expires_at = record.get("expires_at")
    if expires_at is not None:
        expires = _parse_ts(expires_at, "expires_at")
        if expires <= created:
            raise MalformedTransactionError(
                "expires_at must be after created_at")
    steps_in = record.get("steps")
    if not isinstance(steps_in, list) or not steps_in:
        raise MalformedTransactionError(
            "steps must be a non-empty list")
    seen: set = set()
    steps = [_normalize_step(s, seen) for s in steps_in]
    undoable = all(
        (not s["mutating"]) or s["undo"] is not None for s in steps)
    return {
        "schema": TRANSACTION_SCHEMA,
        "schema_version": TRANSACTION_SCHEMA_VERSION,
        "transaction_id": tx_id, "plan_id": plan_id,
        "plan_digest": plan_digest, "title": title,
        "state": "planned", "created_at": record["created_at"],
        "updated_at": record["created_at"],
        "expires_at": expires_at, "undoable": undoable,
        "steps": steps,
    }


@dataclass(frozen=True)
class ManifestStep:
    """One recorded step plus its recorded inverse (or None)."""
    step_id: str
    action_verb: str
    target_type: str
    target_name: str
    args: Dict[str, Any]
    undo_verb: Optional[str]
    undo_target_type: Optional[str]
    undo_target_name: Optional[str]
    undo_args: Dict[str, Any]
    prior_digest: Optional[str]
    mutating: bool
    risk_level: str
    scope: str

    def to_dict(self) -> Dict[str, Any]:
        undo = None
        if self.undo_verb is not None:
            undo = {
                "action_verb": self.undo_verb,
                "target": {"type": self.undo_target_type,
                           "name": self.undo_target_name},
                "args": dict(self.undo_args),
            }
        return {
            "step_id": self.step_id, "action_verb": self.action_verb,
            "target": {"type": self.target_type,
                       "name": self.target_name},
            "args": dict(self.args), "undo": undo,
            "prior_digest": self.prior_digest,
            "mutating": self.mutating,
            "risk_level": self.risk_level, "scope": self.scope,
        }


@dataclass(frozen=True)
class TransactionRecord:
    """One durable transaction: identity, state, manifest, hash."""
    transaction_id: str
    plan_id: str
    plan_digest: Optional[str]
    title: str
    state: str
    created_at: str
    updated_at: str
    expires_at: Optional[str]
    undoable: bool
    steps: Tuple[ManifestStep, ...]
    payload: Dict[str, Any]
    record_hash: str

    def to_dict(self) -> Dict[str, Any]:
        return json.loads(_canonical_json(self.payload))


@dataclass(frozen=True)
class UndoAction:
    """One inverse action in an undo manifest, in undo order."""
    for_step_id: str
    forward_verb: str
    action_verb: str
    target_type: str
    target_name: str
    args: Dict[str, Any]
    prior_digest: Optional[str]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "for_step_id": self.for_step_id,
            "forward_verb": self.forward_verb,
            "action_verb": self.action_verb,
            "target": {"type": self.target_type,
                       "name": self.target_name},
            "args": dict(self.args),
            "prior_digest": self.prior_digest,
        }


@dataclass(frozen=True)
class UndoManifest:
    """The recorded reversal plan for one transaction.

    ``actions`` are in strict reverse step order.  ``skipped``
    names steps that need no inverse (non-mutating).  ``missing``
    names mutating steps with no recorded inverse; a manifest with
    a non-empty ``missing`` is non-undoable and planning an undo
    from it is refused.
    """
    transaction_id: str
    plan_id: str
    state: str
    undoable: bool
    actions: Tuple[UndoAction, ...]
    skipped: Tuple[str, ...]
    missing: Tuple[str, ...]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "transaction_id": self.transaction_id,
            "plan_id": self.plan_id, "state": self.state,
            "undoable": self.undoable,
            "actions": [a.to_dict() for a in self.actions],
            "skipped": list(self.skipped),
            "missing": list(self.missing),
        }


@dataclass(frozen=True)
class HistoryEntry:
    """One hash-chained state-transition record."""
    seq: int
    transaction_id: str
    from_state: Optional[str]
    to_state: str
    at: str
    detail: str
    tx_hash: str
    entry_hash: str


def _step_from_payload(data: Dict[str, Any]) -> ManifestStep:
    undo = data.get("undo") or {}
    return ManifestStep(
        step_id=data["step_id"], action_verb=data["action_verb"],
        target_type=data["target"]["type"],
        target_name=data["target"]["name"],
        args=dict(data.get("args") or {}),
        undo_verb=undo.get("action_verb"),
        undo_target_type=(undo.get("target") or {}).get("type"),
        undo_target_name=(undo.get("target") or {}).get("name"),
        undo_args=dict(undo.get("args") or {}),
        prior_digest=data.get("prior_digest"),
        mutating=bool(data.get("mutating")),
        risk_level=data.get("risk_level", ""),
        scope=data.get("scope", ""))


class TransactionStore:
    """Durable, integrity-checked transaction store (SQLite)."""

    def __init__(self, path, allowed_root=None):
        raw = str(path)
        if raw in ("", ":memory:") or raw.startswith("file:"):
            raise TransactionPathError(
                f"store path {raw!r} is not a plain local file path")
        resolved = Path(raw).expanduser().resolve()
        if resolved.is_dir():
            raise TransactionPathError(
                f"store path {resolved} is a directory, not a file")
        if allowed_root is not None:
            root = Path(str(allowed_root)).expanduser().resolve()
            if resolved != root and root not in resolved.parents:
                raise TransactionPathError(
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

    def schema_version(self) -> int:
        """Current store schema (migration) version."""
        return self._current_version()

    @property
    def path(self) -> Path:
        return self._path

    # -- integrity ----------------------------------------------------
    def _row_to_record(self, row) -> TransactionRecord:
        (seq, tx_id, plan_id, state, created_at, updated_at,
         payload_json, record_hash) = row
        try:
            payload = json.loads(payload_json)
        except ValueError as exc:
            raise CorruptTransactionError(
                f"transaction {tx_id}: stored payload is not "
                f"valid JSON ({exc})") from exc
        stored_state = payload.get("state")
        if stored_state not in _STATE_SET:
            raise UnknownStateError(
                f"transaction {tx_id}: stored state "
                f"{stored_state!r} is not a known transaction "
                "state; refusing to coerce corrupt or foreign "
                "state into a known one")
        if _record_hash(payload_json) != record_hash:
            raise CorruptTransactionError(
                f"transaction {tx_id}: stored payload does not "
                "match its record_hash (record was modified)")
        if payload.get("transaction_id") != tx_id \
                or payload.get("plan_id") != plan_id \
                or stored_state != state \
                or payload.get("created_at") != created_at \
                or payload.get("updated_at") != updated_at:
            raise CorruptTransactionError(
                f"transaction {tx_id}: stored columns disagree "
                "with the stored payload")
        steps = tuple(_step_from_payload(s)
                      for s in payload.get("steps", []))
        return TransactionRecord(
            transaction_id=tx_id, plan_id=plan_id,
            plan_digest=payload.get("plan_digest"),
            title=payload.get("title", ""), state=stored_state,
            created_at=created_at, updated_at=updated_at,
            expires_at=payload.get("expires_at"),
            undoable=bool(payload.get("undoable")), steps=steps,
            payload=payload, record_hash=record_hash)

    _COLS = ("seq, transaction_id, plan_id, state, created_at,"
             " updated_at, payload_json, record_hash")

    def _fetch(self, where="", params=()) -> List[TransactionRecord]:
        rows = self._conn.execute(
            f"SELECT {self._COLS} FROM transactions {where}"
            " ORDER BY seq ASC", params).fetchall()
        return [self._row_to_record(r) for r in rows]

    def _append_history(self, tx_id: str, from_state: Optional[str],
                        to_state: str, at: str, detail: str,
                        tx_hash: str) -> None:
        row = self._conn.execute(
            "SELECT entry_hash FROM tx_history"
            " ORDER BY seq DESC LIMIT 1").fetchone()
        prev_hash = row[0] if row else GENESIS_HASH
        entry_hash = _entry_hash(prev_hash, tx_id, from_state,
                                 to_state, at, detail, tx_hash)
        self._conn.execute(
            "INSERT INTO tx_history (transaction_id, from_state,"
            " to_state, at, detail, tx_hash, prev_hash, entry_hash)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (tx_id, from_state, to_state, at, detail, tx_hash,
             prev_hash, entry_hash))

    # -- creation -------------------------------------------------------
    def create_transaction(self, record: Dict[str, Any]
                           ) -> TransactionRecord:
        """Create one transaction in state 'planned', durably.

        The undo manifest is part of the creation payload: it is
        recorded before any execution can be recorded, or the
        transaction is honestly marked non-undoable at creation.
        """
        payload = validate_transaction(record)
        payload_json = _canonical_json(payload)
        record_hash = _record_hash(payload_json)
        try:
            self._conn.execute("BEGIN IMMEDIATE")
            self._conn.execute(
                "INSERT INTO transactions (transaction_id, plan_id,"
                " state, created_at, updated_at, payload_json,"
                " record_hash) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (payload["transaction_id"], payload["plan_id"],
                 "planned", payload["created_at"],
                 payload["updated_at"], payload_json, record_hash))
            self._append_history(payload["transaction_id"], None,
                                 "planned", payload["created_at"],
                                 "created", record_hash)
            self._conn.commit()
        except sqlite3.IntegrityError as exc:
            self._conn.rollback()
            raise DuplicateTransactionError(
                f"transaction id {payload['transaction_id']!r} is "
                "already recorded; transaction ids are unique and "
                "records are never replaced") from exc
        except Exception:
            self._conn.rollback()
            raise
        found = self.get_transaction(payload["transaction_id"])
        assert found is not None  # just inserted above
        return found

    def delete_transaction(self, *args, **kwargs):
        raise DirectMutationError(
            "durable transaction records are never deleted: abort "
            "a planned transaction or undo an executed one")

    def update_transaction(self, *args, **kwargs):
        raise DirectMutationError(
            "transaction records change only via the transition "
            "table (transition()/approve()/begin_undo()/...)")

    # -- reads ----------------------------------------------------------
    def get_transaction(self, transaction_id: str
                        ) -> Optional[TransactionRecord]:
        found = self._fetch("WHERE transaction_id = ?",
                            (transaction_id,))
        return found[0] if found else None

    def get_by_id(self, transaction_id: str) -> Optional[Dict[str, Any]]:
        """Return the stored payload dict, or None if absent."""
        rec = self.get_transaction(transaction_id)
        return rec.to_dict() if rec else None

    def require_transaction(self, transaction_id: str
                            ) -> TransactionRecord:
        rec = self.get_transaction(transaction_id)
        if rec is None:
            raise UnknownTransactionError(
                f"unknown transaction {transaction_id!r}")
        return rec

    def list_transactions(self, state: Optional[str] = None
                          ) -> List[TransactionRecord]:
        if state is not None:
            if state not in _STATE_SET:
                raise UnknownStateError(
                    f"state filter {state!r} is not a known "
                    "transaction state")
            return self._fetch("WHERE state = ?", (state,))
        return self._fetch()

    def count(self) -> int:
        row = self._conn.execute(
            "SELECT COUNT(*) FROM transactions").fetchone()
        return int(row[0])

    def history(self, transaction_id: str) -> List[HistoryEntry]:
        self.require_transaction(transaction_id)
        rows = self._conn.execute(
            "SELECT seq, transaction_id, from_state, to_state, at,"
            " detail, tx_hash, entry_hash FROM tx_history"
            " WHERE transaction_id = ? ORDER BY seq ASC",
            (transaction_id,)).fetchall()
        return [HistoryEntry(
            seq=r[0], transaction_id=r[1], from_state=r[2],
            to_state=r[3], at=r[4], detail=r[5], tx_hash=r[6],
            entry_hash=r[7]) for r in rows]

    # -- transitions ------------------------------------------------------
    def transition(self, transaction_id: str, new_state: str, *,
                   at: Optional[str] = None, detail: str = ""
                   ) -> TransactionRecord:
        """Move one transaction along the transition table.

        Unknown target states, moves the table does not name, and
        backwards timestamps are all refused by name; a refused
        transition changes nothing.
        """
        if new_state not in _STATE_SET:
            raise UnknownStateError(
                f"state {new_state!r} is not a known transaction "
                f"state; known states are {list(STATES)}")
        rec = self.require_transaction(transaction_id)
        allowed = TRANSITIONS[rec.state]
        if new_state not in allowed:
            raise InvalidTransitionError(
                f"transaction {transaction_id}: cannot move from "
                f"{rec.state!r} to {new_state!r}; allowed moves "
                f"from {rec.state!r} are {list(allowed)}")
        stamp = at if at is not None else _now()
        moment = _parse_ts(stamp, "at")
        if moment < _parse_ts(rec.updated_at, "updated_at"):
            raise StaleTimestampError(
                f"transition timestamp {stamp!r} runs backwards "
                f"against the last update {rec.updated_at!r}")
        payload = rec.to_dict()
        payload["state"] = new_state
        payload["updated_at"] = stamp
        payload_json = _canonical_json(payload)
        record_hash = _record_hash(payload_json)
        try:
            self._conn.execute("BEGIN IMMEDIATE")
            self._conn.execute(
                "UPDATE transactions SET state = ?, updated_at = ?,"
                " payload_json = ?, record_hash = ?"
                " WHERE transaction_id = ?",
                (new_state, stamp, payload_json, record_hash,
                 transaction_id))
            self._append_history(transaction_id, rec.state,
                                 new_state, stamp, detail,
                                 record_hash)
            self._conn.commit()
        except Exception:
            self._conn.rollback()
            raise
        found = self.get_transaction(transaction_id)
        assert found is not None
        return found

    def approve(self, transaction_id: str, **kw) -> TransactionRecord:
        return self.transition(transaction_id, "approved", **kw)

    def begin_execution(self, transaction_id: str, **kw
                        ) -> TransactionRecord:
        return self.transition(transaction_id, "executing", **kw)

    def mark_executed(self, transaction_id: str, **kw
                      ) -> TransactionRecord:
        return self.transition(transaction_id, "executed", **kw)

    def mark_verified(self, transaction_id: str, **kw
                      ) -> TransactionRecord:
        return self.transition(transaction_id, "verified", **kw)

    def mark_failed(self, transaction_id: str, **kw
                    ) -> TransactionRecord:
        return self.transition(transaction_id, "failed", **kw)

    def abort(self, transaction_id: str, **kw) -> TransactionRecord:
        return self.transition(transaction_id, "aborted", **kw)

    # -- undo -------------------------------------------------------------
    def undo_manifest(self, transaction_id: str) -> UndoManifest:
        """Derive the undo manifest recorded for a transaction.

        Pure derivation: works from any state and refuses only an
        unknown, corrupt or unknown-state record.  Actions are in
        strict reverse step order.
        """
        rec = self.require_transaction(transaction_id)
        actions: List[UndoAction] = []
        skipped: List[str] = []
        missing: List[str] = []
        for step in reversed(rec.steps):
            if step.undo_verb is not None:
                actions.append(UndoAction(
                    for_step_id=step.step_id,
                    forward_verb=step.action_verb,
                    action_verb=step.undo_verb,
                    target_type=step.undo_target_type or "",
                    target_name=step.undo_target_name or "",
                    args=dict(step.undo_args),
                    prior_digest=step.prior_digest))
            elif step.mutating:
                missing.append(step.step_id)
            else:
                skipped.append(step.step_id)
        missing.reverse()
        skipped.reverse()
        return UndoManifest(
            transaction_id=rec.transaction_id, plan_id=rec.plan_id,
            state=rec.state, undoable=rec.undoable,
            actions=tuple(actions), skipped=tuple(skipped),
            missing=tuple(missing))

    def plan_undo(self, transaction_id: str) -> UndoManifest:
        """Return the undo manifest, refusing any undo that must
        not be planned (see module docstring for the full table)."""
        rec = self.require_transaction(transaction_id)
        if rec.state == "undone":
            raise AlreadyUndoneError(
                f"transaction {transaction_id} is already undone: "
                "undo is never applied twice")
        if rec.state == "aborted":
            raise NonUndoableError(
                f"transaction {transaction_id} was aborted before "
                "execution: there is nothing to undo")
        if rec.state in ("planned", "approved"):
            raise NonUndoableError(
                f"transaction {transaction_id} is in state "
                f"{rec.state!r}: nothing has executed yet, so "
                "there is nothing to undo (abort it instead)")
        if rec.state in ("executing", "undoing"):
            raise InvalidTransitionError(
                f"transaction {transaction_id} is in state "
                f"{rec.state!r}: finish or fail the current "
                "operation before planning an undo")
        manifest = self.undo_manifest(transaction_id)
        if not manifest.undoable:
            raise NonUndoableError(
                f"transaction {transaction_id} is non-undoable: "
                f"mutating steps {list(manifest.missing)} have "
                "no recorded inverse action in the undo manifest")
        return manifest

    def begin_undo(self, transaction_id: str, *,
                   at: Optional[str] = None, detail: str = ""
                   ) -> UndoManifest:
        """Plan the undo (refusing per plan_undo) and move the
        transaction to 'undoing'.  Executes nothing."""
        manifest = self.plan_undo(transaction_id)
        self.transition(transaction_id, "undoing", at=at,
                        detail=detail or "undo planned")
        return manifest

    def complete_undo(self, transaction_id: str, **kw
                      ) -> TransactionRecord:
        return self.transition(transaction_id, "undone", **kw)

    def fail_undo(self, transaction_id: str, **kw
                  ) -> TransactionRecord:
        return self.transition(transaction_id, "undo_failed", **kw)

    # -- verification -----------------------------------------------------
    def history_errors(self) -> List[str]:
        errors: List[str] = []
        rows = self._conn.execute(
            "SELECT seq, transaction_id, from_state, to_state, at,"
            " detail, tx_hash, prev_hash, entry_hash FROM tx_history"
            " ORDER BY seq ASC").fetchall()
        expected_prev = GENESIS_HASH
        expected_seq = 1
        for row in rows:
            (seq, tx_id, from_state, to_state, at, detail, tx_hash,
             prev_hash, entry_hash) = row
            if seq != expected_seq:
                errors.append(
                    f"history seq gap at stored seq {seq}: "
                    f"expected {expected_seq} (an entry was "
                    "deleted or reordered)")
            expected_seq = seq + 1
            if prev_hash != expected_prev:
                errors.append(
                    f"history entry {seq} ({tx_id}): prev_hash "
                    "does not match the previous entry_hash "
                    "(chain link broken)")
            recomputed = _entry_hash(prev_hash, tx_id, from_state,
                                     to_state, at, detail, tx_hash)
            if recomputed != entry_hash:
                errors.append(
                    f"history entry {seq} ({tx_id}): stored "
                    "fields do not match entry_hash (entry was "
                    "modified)")
            expected_prev = entry_hash
        return errors

    def verify_history(self) -> bool:
        """Recompute the whole history hash chain; True if intact."""
        return not self.history_errors()

    def verify_integrity(self) -> List[str]:
        """Check every stored transaction plus the history chain.

        Returns human-readable problems (empty = intact).  Unlike
        the read path this never raises for a single bad record:
        every problem is collected so an operator sees all damage
        at once.  Unknown stored states are reported here as
        integrity problems naming the state.
        """
        errors: List[str] = []
        rows = self._conn.execute(
            f"SELECT {self._COLS} FROM transactions"
            " ORDER BY seq ASC").fetchall()
        for row in rows:
            try:
                self._row_to_record(row)
            except TransactionError as exc:
                errors.append(str(exc))
        errors.extend(self.history_errors())
        return errors

    def close(self) -> None:
        self._conn.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        self.close()
        return False
