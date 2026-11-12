"""Reversal and interrupted-operation tests (LIF-0505).

SPDX-License-Identifier: GPL-2.0-only

Contract/test-level implementation of the P5 Eir reversal drill:

- A repair operation is a sequence of steps against FIXTURE state
  only (an in-memory key/value store standing in for configuration
  targets). No host file, service, or process is ever touched, and
  interruptions are simulated by raising ``SimulatedInterrupt`` at
  named points -- never by killing or signalling any real process.
- Before any step mutates the fixture state, its undo entry
  (target, before-image, after-image) is written ahead into a
  durable undo manifest on disk (atomic replace + fsync). The
  manifest shape follows the LIF-0405 contract named in the
  backlog -- durable transaction state plus an undo manifest --
  re-declared here because LIF-0405 is not banked on this base;
  this module depends on no unbanked file.
- Reversal applies the before-images in exact reverse order.
  Reversal progress is itself journaled after every step, so an
  interruption DURING reversal leaves a manifest from which a
  fresh runner can finish the reversal.
- Recovery is manifest-driven and model-independent in the
  LIF-0406 sense: a brand-new runner, given only the journal
  file and the fixture state, restores the exact original state
  digest or refuses with a named divergence -- it never claims a
  recovery it did not verify.
- A step that declares itself irreversible is refused when the
  transaction is planned, before anything is applied (the
  policy engine's NO_UNDO_PATH rule, LIF-0402, applied here).
- A tampered manifest (digest mismatch, malformed JSON, unknown
  version) is refused by name; a missing manifest is a named
  error, never an invented recovery.

Evidence status: reproducer / fixture-level, lab-verified on
purpleraider only. Nothing here proves reversal of any real
host mutation; that is future Eir work behind the P4 gates.
"""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

MANIFEST_VERSION = 1

STEP_RECORDED = "recorded"
STEP_APPLIED = "applied"
STEP_REVERSED = "reversed"
TXN_OPEN = "open"
TXN_COMMITTED = "committed"
TXN_REVERSED = "reversed"


class ReversalError(Exception):
    """Base class for all named reversal refusals."""


class IrreversibleStepError(ReversalError):
    """A step with no undo path was offered; refused at plan time."""


class ManifestError(ReversalError):
    """The undo manifest is missing, malformed, or inconsistent."""


class TamperedManifestError(ManifestError):
    """The manifest digest does not match its contents."""


class DivergenceError(ReversalError):
    """Recovered state does not match the recorded original."""


class AlreadyReversedError(ReversalError):
    """The transaction is already fully reversed; terminal."""


class TransactionStateError(ReversalError):
    """The operation is invalid for the transaction's status."""


class SimulatedInterrupt(Exception):
    """Simulated crash/power-loss at a named point (fixture only).

    Deliberately NOT a ReversalError: a real interruption is not a
    refusal, and the runner must not catch or soften it. The test
    (or drill) catches it, discards the runner, and recovers from
    the journal alone -- exactly as after a real process death.
    """


class _Delete:
    """Sentinel: the step removes its target key."""

    def __repr__(self) -> str:
        return "DELETE"


DELETE = _Delete()


def _canonical(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=True)


def _digest(obj: Any) -> str:
    return "sha256:" + hashlib.sha256(
        _canonical(obj).encode("utf-8")).hexdigest()


def _image(value: Any) -> Dict[str, Any]:
    """JSON image of a possibly-absent fixture value."""
    if value is DELETE:
        return {"present": False, "value": None}
    return {"present": True, "value": value}


class FixtureState:
    """In-memory fixture state: JSON-valued keys, digestible.

    Stands in for the exact targets a repair recipe would touch.
    Values must be JSON-serializable; anything else is refused so
    the manifest can always record a faithful before-image.
    """

    def __init__(self, initial: Optional[Dict[str, Any]] = None):
        self._data: Dict[str, Any] = {}
        for key, value in (initial or {}).items():
            self.set(key, value)

    def get(self, key: str, default: Any = None) -> Any:
        return self._data.get(key, default)

    def has(self, key: str) -> bool:
        return key in self._data

    def set(self, key: str, value: Any) -> None:
        try:
            _canonical(value)
        except (TypeError, ValueError) as exc:
            raise ReversalError(
                f"fixture value for {key!r} is not JSON-serializable: "
                f"{exc}") from exc
        self._data[key] = value

    def delete(self, key: str) -> None:
        self._data.pop(key, None)

    def snapshot(self) -> Dict[str, Any]:
        return json.loads(_canonical(self._data))

    def digest(self) -> str:
        return _digest(self._data)


@dataclass
class Step:
    """One reversible fixture mutation.

    ``value`` is the after-image (or DELETE to remove the key).
    ``reversible=False`` marks a step with no undo path; planning
    refuses it by name before anything is applied.
    """

    step_id: str
    target: str
    value: Any = None
    reversible: bool = True


@dataclass
class Manifest:
    """Durable transaction state + undo manifest (LIF-0405 shape)."""

    transaction_id: str
    original_digest: str
    status: str = TXN_OPEN
    steps: List[Dict[str, Any]] = field(default_factory=list)
    version: int = MANIFEST_VERSION

    def to_dict(self) -> Dict[str, Any]:
        body = {
            "version": self.version,
            "transaction_id": self.transaction_id,
            "status": self.status,
            "original_digest": self.original_digest,
            "steps": self.steps,
        }
        body["manifest_digest"] = _digest(body)
        return body

    @classmethod
    def from_dict(cls, data: Any) -> "Manifest":
        if not isinstance(data, dict):
            raise ManifestError("manifest is not a JSON object")
        claimed = data.get("manifest_digest")
        body = {k: v for k, v in data.items() if k != "manifest_digest"}
        if not isinstance(claimed, str) or _digest(body) != claimed:
            raise TamperedManifestError(
                "manifest digest mismatch: contents were altered "
                "after journaling; refusing to recover from it")
        if body.get("version") != MANIFEST_VERSION:
            raise ManifestError(
                f"unsupported manifest version: {body.get('version')!r}")
        for key in ("transaction_id", "status", "original_digest",
                    "steps"):
            if key not in body:
                raise ManifestError(f"manifest missing field: {key}")
        if not isinstance(body["steps"], list):
            raise ManifestError("manifest steps is not a list")
        return cls(transaction_id=body["transaction_id"],
                   original_digest=body["original_digest"],
                   status=body["status"], steps=body["steps"],
                   version=body["version"])


class Journal:
    """Atomic, fsynced manifest file (write tmp, rename, fsync)."""

    def __init__(self, path: Any):
        self.path = Path(path)

    def write(self, manifest: Manifest) -> None:
        payload = _canonical(manifest.to_dict())
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=str(self.path.parent),
                                   prefix=self.path.name + ".",
                                   suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                fh.write(payload)
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(tmp, self.path)
        except BaseException:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise

    def read(self) -> Manifest:
        if not self.path.exists():
            raise ManifestError(
                f"no undo manifest at {self.path}: nothing to "
                "recover; no recovery will be invented")
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (ValueError, UnicodeDecodeError) as exc:
            raise ManifestError(
                f"undo manifest at {self.path} is not valid JSON: "
                f"{exc}") from exc
        return Manifest.from_dict(data)

    def exists(self) -> bool:
        return self.path.exists()


class OperationRunner:
    """Plans, applies, reverses, and recovers one transaction.

    Interruption points for ``run``/``reverse`` (all simulated,
    fixture state only): ``after_steps=k`` raises after k steps
    have been applied and journaled; ``after_apply_of_step=id``
    raises after that step's mutation but BEFORE its applied
    status is journaled (the write-ahead entry is already
    durable, so recovery can still decide by comparing images);
    ``before_commit=True`` raises with every step applied but
    the transaction uncommitted.
    """

    def __init__(self, state: FixtureState, journal_path: Any):
        self.state = state
        self.journal = Journal(journal_path)
        self.manifest: Optional[Manifest] = None

    def plan(self, transaction_id: str, steps: List[Step]) -> Manifest:
        if self.journal.exists():
            raise TransactionStateError(
                f"journal {self.journal.path} already holds a "
                "transaction; recover or reverse it before planning "
                "a new one")
        if not steps:
            raise ReversalError("a transaction needs at least one step")
        seen = set()
        for step in steps:
            if step.step_id in seen:
                raise ReversalError(
                    f"duplicate step_id in plan: {step.step_id!r}")
            seen.add(step.step_id)
            if not step.reversible:
                raise IrreversibleStepError(
                    f"step {step.step_id!r} declares no undo path; "
                    "refused at plan time (NO_UNDO_PATH): nothing "
                    "was applied and no manifest was written")
        entries = []
        for step in steps:
            entries.append({
                "step_id": step.step_id,
                "target": step.target,
                # The before-image is captured at apply time,
                # write-ahead per step (see run): a plan-time
                # image goes stale when two steps touch one
                # target. None means "not yet applied".
                "before": None,
                "after": _image(step.value),
                "status": STEP_RECORDED,
            })
        self.manifest = Manifest(
            transaction_id=transaction_id,
            original_digest=self.state.digest(),
            status=TXN_OPEN, steps=entries)
        self.journal.write(self.manifest)
        return self.manifest

    def _apply_entry(self, entry: Dict[str, Any]) -> None:
        after = entry["after"]
        if after["present"]:
            self.state.set(entry["target"], after["value"])
        else:
            self.state.delete(entry["target"])

    def _restore_entry(self, entry: Dict[str, Any]) -> None:
        before = entry["before"]
        if before["present"]:
            self.state.set(entry["target"], before["value"])
        else:
            self.state.delete(entry["target"])

    def run(self, *, after_steps: Optional[int] = None,
            after_apply_of_step: Optional[str] = None,
            before_commit: bool = False) -> Manifest:
        manifest = self._require_manifest()
        if manifest.status != TXN_OPEN:
            raise TransactionStateError(
                f"cannot run a transaction in status "
                f"{manifest.status!r}")
        applied = 0
        if after_steps is not None and after_steps <= 0:
            raise SimulatedInterrupt(
                "simulated interruption before the first step")
        for entry in manifest.steps:
            if entry["status"] == STEP_APPLIED:
                applied += 1
                continue
            if entry["status"] != STEP_RECORDED:
                raise TransactionStateError(
                    f"step {entry['step_id']!r} in unexpected "
                    f"status {entry['status']!r} during run")
            live = (self.state.get(entry["target"])
                    if self.state.has(entry["target"]) else DELETE)
            entry["before"] = _image(live)
            self.journal.write(manifest)
            self._apply_entry(entry)
            if after_apply_of_step == entry["step_id"]:
                raise SimulatedInterrupt(
                    f"simulated interruption after applying step "
                    f"{entry['step_id']!r}, before its applied "
                    "status was journaled")
            entry["status"] = STEP_APPLIED
            self.journal.write(manifest)
            applied += 1
            if after_steps is not None and applied >= after_steps:
                raise SimulatedInterrupt(
                    f"simulated interruption after {applied} "
                    "applied step(s)")
        if before_commit:
            raise SimulatedInterrupt(
                "simulated interruption after the final step, "
                "before commit")
        manifest.status = TXN_COMMITTED
        self.journal.write(manifest)
        return manifest

    def commit(self) -> Manifest:
        manifest = self._require_manifest()
        if manifest.status != TXN_OPEN:
            raise TransactionStateError(
                f"cannot commit a transaction in status "
                f"{manifest.status!r}")
        pending = [e["step_id"] for e in manifest.steps
                   if e["status"] != STEP_APPLIED]
        if pending:
            raise TransactionStateError(
                f"cannot commit: step(s) not applied: {pending}")
        manifest.status = TXN_COMMITTED
        self.journal.write(manifest)
        return manifest

    def reverse(self, *,
                after_reversals: Optional[int] = None) -> Manifest:
        manifest = self._require_manifest()
        if manifest.status == TXN_REVERSED:
            raise AlreadyReversedError(
                f"transaction {manifest.transaction_id!r} is "
                "already fully reversed; reversal is terminal")
        if manifest.status not in (TXN_OPEN, TXN_COMMITTED):
            raise TransactionStateError(
                f"cannot reverse a transaction in status "
                f"{manifest.status!r}")
        self._reverse_remaining(manifest,
                                after_reversals=after_reversals)
        return manifest

    def _reverse_remaining(self, manifest: Manifest, *,
                           after_reversals: Optional[int] = None
                           ) -> tuple:
        """Reverse every not-yet-reversed step, newest first.

        A step still in RECORDED status may or may not have been
        applied (the crash window in ``run``): it is reversed
        only when the live value equals its after-image; when it
        equals its before-image it was never applied and is
        marked reversed without a mutation; anything else is a
        named divergence. Progress is journaled per step, so an
        interruption mid-reversal is itself recoverable.
        """
        reversed_ids: List[str] = []
        skipped_ids: List[str] = []
        count = 0
        for entry in reversed(manifest.steps):
            if entry["status"] == STEP_REVERSED:
                continue
            if entry["status"] == STEP_RECORDED:
                if entry["before"] is None:
                    skipped_ids.append(entry["step_id"])
                else:
                    live = (self.state.get(entry["target"])
                            if self.state.has(entry["target"])
                            else DELETE)
                    if _image(live) == entry["after"]:
                        self._restore_entry(entry)
                    elif _image(live) == entry["before"]:
                        skipped_ids.append(entry["step_id"])
                    else:
                        raise DivergenceError(
                            f"step {entry['step_id']!r}: live value of "
                            f"{entry['target']!r} matches neither its "
                            "before-image nor its after-image; refusing "
                            "to guess a recovery")
            elif entry["status"] == STEP_APPLIED:
                self._restore_entry(entry)
            else:
                raise ManifestError(
                    f"step {entry['step_id']!r} has unknown status "
                    f"{entry['status']!r}")
            entry["status"] = STEP_REVERSED
            self.journal.write(manifest)
            if entry["step_id"] not in skipped_ids:
                reversed_ids.append(entry["step_id"])
            count += 1
            if after_reversals is not None and count >= after_reversals:
                raise SimulatedInterrupt(
                    f"simulated interruption during reversal after "
                    f"{count} reversed step(s)")
        manifest.status = TXN_REVERSED
        self.journal.write(manifest)
        return reversed_ids, skipped_ids

    @classmethod
    def recover(cls, state: FixtureState,
                journal_path: Any) -> Dict[str, Any]:
        """Model-independent recovery from the journal alone.

        A fresh runner loads the durable manifest, reverses every
        step that was applied (or left in the crash window), and
        verifies the restored digest against the recorded
        original. Any mismatch is a named DivergenceError -- a
        recovery is never claimed on faith.
        """
        runner = cls(state, journal_path)
        manifest = runner.journal.read()
        runner.manifest = manifest
        if manifest.status == TXN_REVERSED:
            raise AlreadyReversedError(
                f"transaction {manifest.transaction_id!r} is "
                "already fully reversed; nothing to recover")
        reversed_ids, skipped_ids = runner._reverse_remaining(manifest)
        restored = state.digest()
        if restored != manifest.original_digest:
            raise DivergenceError(
                f"recovery of transaction "
                f"{manifest.transaction_id!r} did not restore the "
                f"original state: expected digest "
                f"{manifest.original_digest}, got {restored}; "
                f"reversed steps: {reversed_ids}; state keys now: "
                f"{sorted(state.snapshot())}")
        return {
            "transaction_id": manifest.transaction_id,
            "reversed_steps": reversed_ids,
            "skipped_steps": skipped_ids,
            "restored_digest": restored,
            "original_digest": manifest.original_digest,
            "verified": True,
        }

    def _require_manifest(self) -> Manifest:
        if self.manifest is None:
            if self.journal.exists():
                self.manifest = self.journal.read()
            else:
                raise TransactionStateError(
                    "no transaction planned in this runner and no "
                    f"manifest at {self.journal.path}")
        return self.manifest

    def load(self) -> Manifest:
        """(Re)load this runner's manifest from the journal."""
        self.manifest = self.journal.read()
        return self.manifest
