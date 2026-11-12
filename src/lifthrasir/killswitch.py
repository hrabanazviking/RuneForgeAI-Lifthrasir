"""Kill-switch and model-independent recovery (LIF-0406).

SPDX-License-Identifier: GPL-2.0-only

Home justification: master roadmap section 3 places core code under
``src/``; ADR-0002 seats emergency-stop enforcement in the interface
and watchdog/recovery processes, beside the broker path -- core
safety machinery, not a lab prototype, so this module lives in the
core package ``src/lifthrasir/`` beside the event bus and the Mimir
store.  Following the LIF-0303 precedent, this slice ships WITHOUT
editing the package ``__init__`` export lists: the P4 slices
LIF-0401..LIF-0405 are building in parallel on their own branches and
several of them own ``__init__`` changes; a submodule import
(``from lifthrasir import killswitch``) works before and after they
bank, so this slice can never conflict with or overwrite their
exports.  Coordination gaps are recorded in CAMPAIGN_STATE.md.

Contract (master roadmap section 0 invariants 8 and 9; ADR-0002
failure propagation; research/33 property 6):

- The emergency stop works WITHOUT models, network, embeddings,
  federation or inference acceleration.  This module therefore
  imports nothing outside a small stdlib allowlist, imports no other
  ``lifthrasir`` module, opens no sockets and calls no model.  A
  source-scan test pins that property.
- Engaging the switch is durable (an atomically written, fsynced
  halt record inside one state directory) and survives process
  restart: a fresh instance over the same directory sees the halt.
- While engaged, ``require_clear`` refuses every new execution.
  A corrupt halt record FAILS CLOSED: unreadable halt state is
  treated as engaged, never as clear.
- Engaging drives in-flight work down: the fixture-process guard
  terminates ONLY processes this project registered itself, after
  re-verifying identity (PID + /proc start-time + cmdline marker),
  so PID reuse can never redirect a signal onto a foreign process.
  Unregistered processes are never signalled -- there is no API
  that signals an arbitrary PID.
- Recovery is deterministic and model-free: it reads a durable
  transaction journal (the shape LIF-0405's undo manifest is being
  built against -- see the coordination note in CAMPAIGN_STATE.md),
  preserves committed transactions byte-for-byte (a committed action
  is NEVER replayed), drives in-flight transactions onto their undo
  path (state ``aborted`` plus the undo steps in reverse order) and
  expires prepared transactions instead of executing them late.
  Recovery is idempotent: a second run changes nothing.  A corrupt
  journal or an unknown transaction state refuses loudly and leaves
  the journal untouched.
- Every engage / release / termination / recovery is appended to a
  hash-chained audit log inside the state directory.

Scope honesty: the kill path is exercised ONLY against this
project's own fixture processes and fixture journals (the task's
hard bound).  No real host service, campaign process or system
process is ever stopped, signalled or inspected beyond the fixture
registry's own identity check.  Live broker/watchdog integration is
future work once LIF-0401..LIF-0405 bank; it is NOT claimed here.
Evidence status: reproducer + lab-verified (fixture level) only.
"""
from __future__ import annotations

import hashlib
import json
import os
import signal
import subprocess
import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional

HALT_FILENAME = "HALT.json"
AUDIT_FILENAME = "audit.jsonl"
REGISTRY_FILENAME = "fixtures.json"
GENESIS_HASH = "0" * 64

JOURNAL_SCHEMA = "lif0406-txn-journal/1"
TXN_STATES = frozenset(
    {"prepared", "in_flight", "committed", "aborted", "undone"})


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _canonical(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"))


def _fsync_dir(path: Path) -> None:
    try:
        fd = os.open(str(path), os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(fd)
    except OSError:
        pass
    finally:
        os.close(fd)


def _atomic_write(path: Path, text: str) -> None:
    tmp = path.with_name(path.name + f".tmp-{uuid.uuid4().hex[:8]}")
    tmp.write_text(text, encoding="utf-8")
    with open(tmp, "r+b") as fh:
        os.fsync(fh.fileno())
    os.replace(tmp, path)
    _fsync_dir(path.parent)


class KillSwitchError(Exception):
    """Base class for all named kill-switch refusals."""


class KillSwitchEngaged(KillSwitchError):
    """Raised when work is attempted while the switch is engaged."""


class KillSwitchStateError(KillSwitchError):
    """Raised for malformed operator input or state operations."""


class FixtureRefusal(KillSwitchError):
    """Raised when a fixture registration is refused."""


class RecoveryRefused(KillSwitchError):
    """Raised when recovery cannot proceed safely."""


@dataclass(frozen=True)
class HaltRecord:
    actor: str
    reason: str
    engaged_at: str
    nonce: str

    def to_dict(self) -> Dict[str, Any]:
        return {"actor": self.actor, "reason": self.reason,
                "engaged_at": self.engaged_at, "nonce": self.nonce}


class KillSwitch:
    """Durable, model-independent emergency stop over one state dir."""

    def __init__(self, state_dir: Path):
        self.state_dir = Path(state_dir)
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.halt_path = self.state_dir / HALT_FILENAME
        self.audit_path = self.state_dir / AUDIT_FILENAME

    # -- audit (append-only, hash-chained) --------------------------
    def _audit_entries(self) -> List[Dict[str, Any]]:
        if not self.audit_path.is_file():
            return []
        entries = []
        for line in self.audit_path.read_text(
                encoding="utf-8").splitlines():
            if line.strip():
                entries.append(json.loads(line))
        return entries

    def _audit(self, event: str, actor: str,
               detail: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        entries = self._audit_entries()
        prev = entries[-1]["hash"] if entries else GENESIS_HASH
        entry: Dict[str, Any] = {
            "seq": len(entries) + 1, "ts": _now(), "event": event,
            "actor": actor, "detail": detail or {}, "prev_hash": prev}
        entry["hash"] = hashlib.sha256(
            (prev + _canonical(
                {k: entry[k] for k in
                 ("seq", "ts", "event", "actor", "detail")})
             ).encode("utf-8")).hexdigest()
        with open(self.audit_path, "a", encoding="utf-8") as fh:
            fh.write(_canonical(entry) + "\n")
            fh.flush()
            os.fsync(fh.fileno())
        return entry

    def verify_audit(self) -> bool:
        """True iff the audit chain is intact (tamper-evident)."""
        prev = GENESIS_HASH
        for i, entry in enumerate(self._audit_entries(), start=1):
            if entry.get("seq") != i or entry.get("prev_hash") != prev:
                return False
            expect = hashlib.sha256(
                (prev + _canonical(
                    {k: entry.get(k) for k in
                     ("seq", "ts", "event", "actor", "detail")})
                 ).encode("utf-8")).hexdigest()
            if entry.get("hash") != expect:
                return False
            prev = entry["hash"]
        return True

    # -- halt state ---------------------------------------------------
    def _read_halt(self) -> tuple[str, Optional[HaltRecord]]:
        """Return (kind, record): kind in clear/engaged/corrupt."""
        if not self.halt_path.is_file():
            return ("clear", None)
        try:
            data = json.loads(
                self.halt_path.read_text(encoding="utf-8"))
            record = HaltRecord(
                actor=str(data["actor"]), reason=str(data["reason"]),
                engaged_at=str(data["engaged_at"]),
                nonce=str(data["nonce"]))
            if not record.actor or not record.nonce:
                raise ValueError("incomplete halt record")
            return ("engaged", record)
        except (ValueError, KeyError, TypeError, OSError):
            return ("corrupt", None)

    def status(self) -> Dict[str, Any]:
        kind, record = self._read_halt()
        return {"engaged": kind != "clear", "corrupt": kind == "corrupt",
                "record": record.to_dict() if record else None}

    def is_engaged(self) -> bool:
        # Fail closed: corrupt halt state counts as engaged.
        return self._read_halt()[0] != "clear"

    def engage(self, actor: str, reason: str) -> HaltRecord:
        if not isinstance(actor, str) or not actor.strip():
            raise KillSwitchStateError("engage requires a named actor")
        if not isinstance(reason, str) or not reason.strip():
            raise KillSwitchStateError("engage requires a reason")
        kind, existing = self._read_halt()
        if kind == "engaged" and existing is not None:
            self._audit("engage_redundant", actor,
                        {"reason": reason,
                         "original_nonce": existing.nonce})
            return existing
        record = HaltRecord(actor=actor, reason=reason,
                            engaged_at=_now(),
                            nonce=uuid.uuid4().hex)
        _atomic_write(self.halt_path,
                      json.dumps(record.to_dict(), indent=2) + "\n")
        self._audit("engage", actor,
                    {"reason": reason, "nonce": record.nonce,
                     "replaced_corrupt": kind == "corrupt"})
        return record

    def release(self, actor: str, reason: str) -> bool:
        if not isinstance(actor, str) or not actor.strip():
            raise KillSwitchStateError("release requires a named actor")
        if not isinstance(reason, str) or not reason.strip():
            raise KillSwitchStateError("release requires a reason")
        kind, record = self._read_halt()
        if kind == "clear":
            return False
        self.halt_path.unlink()
        _fsync_dir(self.state_dir)
        self._audit("release", actor,
                    {"reason": reason, "was_corrupt": kind == "corrupt",
                     "halt_nonce": record.nonce if record else None})
        return True

    def require_clear(self, action: str = "") -> None:
        kind, record = self._read_halt()
        if kind == "clear":
            return
        if kind == "corrupt":
            raise KillSwitchEngaged(
                "kill-switch halt state is corrupt; failing closed "
                f"(action {action!r} refused)")
        assert record is not None
        raise KillSwitchEngaged(
            f"kill-switch engaged by {record.actor!r} "
            f"({record.reason!r}); action {action!r} refused")

    @contextmanager
    def guard(self, action: str = "") -> Iterator[None]:
        self.require_clear(action)
        yield


# --------------------------------------------------------------------
# Fixture process guard: the ONLY signalling surface, fixtures only.
# --------------------------------------------------------------------

def _proc_identity(pid: int) -> Optional[tuple[str, str]]:
    """Return (starttime, cmdline) for pid, or None if it is gone."""
    try:
        stat = Path(f"/proc/{pid}/stat").read_text(encoding="utf-8")
        # comm may contain spaces/parens; fields after the final ')':
        # index 0 is state, field 22 overall is starttime -> index 19.
        rest = stat.rsplit(")", 1)[1].split()
        if rest[0] == "Z":
            return None  # zombie: dead, awaiting reap; counts as gone
        starttime = rest[19]
        cmdline = Path(f"/proc/{pid}/cmdline").read_bytes().replace(
            b"\x00", b" ").decode("utf-8", "replace").strip()
        return (starttime, cmdline)
    except (OSError, IndexError):
        return None


@dataclass
class TerminationReport:
    terminated: List[int] = field(default_factory=list)
    killed_after_term: List[int] = field(default_factory=list)
    already_dead: List[int] = field(default_factory=list)
    skipped: List[Dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {"terminated": self.terminated,
                "killed_after_term": self.killed_after_term,
                "already_dead": self.already_dead,
                "skipped": self.skipped}


class FixtureRegistry:
    """Registry of THIS project's own fixture processes.

    A process can only ever be signalled through this registry, and
    only after its live identity (start-time + cmdline marker) is
    re-verified against the registration -- PID reuse therefore
    skips instead of killing a foreign successor process.
    """

    def __init__(self, state_dir: Path):
        self.state_dir = Path(state_dir)
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.path = self.state_dir / REGISTRY_FILENAME

    def _load(self) -> List[Dict[str, Any]]:
        if not self.path.is_file():
            return []
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            return list(data.get("fixtures", []))
        except (ValueError, AttributeError, OSError):
            return []

    def _save(self, rows: List[Dict[str, Any]]) -> None:
        _atomic_write(self.path, json.dumps(
            {"fixtures": rows}, indent=2) + "\n")

    def entries(self) -> List[Dict[str, Any]]:
        return self._load()

    def register(self, pid: int, marker: str) -> Dict[str, Any]:
        if not isinstance(marker, str) or not marker:
            raise FixtureRefusal("registration requires a marker")
        # A just-spawned fixture may not have exec'd yet: its /proc
        # cmdline is briefly still the parent's. Poll briefly for the
        # marker to appear in the pid's own cmdline. Registration still
        # requires observing the marker there, and the recorded
        # starttime comes from the same matching read - a process whose
        # cmdline never carries the marker is refused exactly as before.
        ident = None
        for _ in range(50):
            ident = _proc_identity(int(pid))
            if ident is not None and marker in ident[1]:
                break
            time.sleep(0.02)
        if ident is None:
            raise FixtureRefusal(f"pid {pid} is not a live process")
        starttime, cmdline = ident
        if marker not in cmdline:
            raise FixtureRefusal(
                f"marker {marker!r} not in cmdline of pid {pid}: "
                "only this project's own fixture processes register")
        rows = [r for r in self._load() if r["pid"] != int(pid)]
        row = {"pid": int(pid), "marker": marker,
               "starttime": starttime, "registered_at": _now()}
        rows.append(row)
        self._save(rows)
        return row

    def spawn_fixture(self, argv: List[str], marker: str,
                      cwd: Optional[Path] = None) -> int:
        if marker not in " ".join(argv):
            raise FixtureRefusal(
                "fixture argv must carry its marker so identity can "
                "be re-verified before any signal")
        proc = subprocess.Popen(
            argv, cwd=str(cwd) if cwd else None,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            start_new_session=True)
        # Wait for exec to land: right after fork the child's /proc
        # cmdline is still the parent's, so poll until the marker is
        # visible in the child's own cmdline (register() re-verifies
        # strictly before anything is recorded or signalled).
        for _ in range(50):
            ident = _proc_identity(proc.pid)
            if ident is not None and marker in ident[1]:
                break
            time.sleep(0.02)
        if proc.poll() is not None:
            raise FixtureRefusal(
                f"fixture {argv!r} exited immediately "
                f"(rc={proc.returncode})")
        self.register(proc.pid, marker)
        return proc.pid

    def terminate_all(self, term_timeout: float = 2.0) -> TerminationReport:
        report = TerminationReport()
        remaining = []
        for row in self._load():
            pid, marker = int(row["pid"]), row["marker"]
            ident = _proc_identity(pid)
            if ident is None:
                report.already_dead.append(pid)
                continue
            starttime, cmdline = ident
            if starttime != row["starttime"]:
                report.skipped.append(
                    {"pid": pid, "why": "start-time mismatch "
                                        "(PID reuse); not signalled"})
                remaining.append(row)
                continue
            if marker not in cmdline:
                report.skipped.append(
                    {"pid": pid, "why": "cmdline marker mismatch; "
                                        "not signalled"})
                remaining.append(row)
                continue
            os.kill(pid, signal.SIGTERM)
            deadline = time.time() + term_timeout
            while time.time() < deadline and _proc_identity(pid):
                time.sleep(0.02)
            if _proc_identity(pid) is None:
                report.terminated.append(pid)
            else:
                os.kill(pid, signal.SIGKILL)
                deadline = time.time() + term_timeout
                while time.time() < deadline and _proc_identity(pid):
                    time.sleep(0.02)
                if _proc_identity(pid) is None:
                    report.killed_after_term.append(pid)
                else:
                    report.skipped.append(
                        {"pid": pid, "why": "survived SIGKILL window"})
                    remaining.append(row)
        self._save(remaining)
        return report


def engage_and_stop(switch: KillSwitch, registry: FixtureRegistry,
                    actor: str, reason: str,
                    term_timeout: float = 2.0):
    """The kill-switch act: halt FIRST, then stop fixture processes.

    Order matters: the durable halt lands before any signal is sent,
    so no new work can start while fixtures are being stopped.
    """
    record = switch.engage(actor, reason)
    report = registry.terminate_all(term_timeout=term_timeout)
    switch._audit("stop_fixtures", actor, report.to_dict())
    return record, report


# --------------------------------------------------------------------
# Model-independent recovery over a durable transaction journal.
# --------------------------------------------------------------------

@dataclass
class RecoveryReport:
    preserved_committed: List[str] = field(default_factory=list)
    rolled_back: List[Dict[str, Any]] = field(default_factory=list)
    expired_prepared: List[str] = field(default_factory=list)
    untouched: List[str] = field(default_factory=list)
    changed: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {"preserved_committed": self.preserved_committed,
                "rolled_back": self.rolled_back,
                "expired_prepared": self.expired_prepared,
                "untouched": self.untouched, "changed": self.changed}


def load_journal(path: Path) -> Dict[str, Any]:
    path = Path(path)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, OSError) as exc:
        raise RecoveryRefused(f"journal {path} unreadable: {exc}")
    if not isinstance(data, dict) or data.get("schema") != JOURNAL_SCHEMA:
        raise RecoveryRefused(
            f"journal {path}: schema is not {JOURNAL_SCHEMA!r}")
    txns = data.get("transactions")
    if not isinstance(txns, list):
        raise RecoveryRefused(f"journal {path}: transactions not a list")
    for txn in txns:
        if not isinstance(txn, dict) or not txn.get("txn_id"):
            raise RecoveryRefused(f"journal {path}: txn without txn_id")
        if txn.get("state") not in TXN_STATES:
            raise RecoveryRefused(
                f"journal {path}: txn {txn.get('txn_id')!r} has "
                f"unknown state {txn.get('state')!r}; refusing to guess")
        if not isinstance(txn.get("undo", []), list):
            raise RecoveryRefused(
                f"journal {path}: txn {txn['txn_id']!r} undo not a list")
    return data


def recover_journal(path: Path, actor: str = "recovery") -> RecoveryReport:
    """Drive a journal to a safe state. Deterministic; no model.

    Committed transactions are preserved exactly (never replayed);
    in-flight transactions move to ``aborted`` with their undo steps
    recorded in reverse order; prepared transactions expire to
    ``aborted`` rather than executing late.  Idempotent: when no
    transaction needs action the file is not rewritten at all.
    """
    path = Path(path)
    data = load_journal(path)
    report = RecoveryReport()
    stamp = _now()
    for txn in data["transactions"]:
        state = txn["state"]
        if state == "committed":
            report.preserved_committed.append(txn["txn_id"])
        elif state == "in_flight":
            undo_steps = list(reversed(txn.get("undo", [])))
            txn["state"] = "aborted"
            txn["recovery"] = {"action": "rollback",
                               "by": actor, "at": stamp,
                               "undo_steps": undo_steps}
            report.rolled_back.append(
                {"txn_id": txn["txn_id"], "undo_steps": undo_steps})
            report.changed = True
        elif state == "prepared":
            txn["state"] = "aborted"
            txn["recovery"] = {"action": "expire", "by": actor,
                               "at": stamp, "undo_steps": []}
            report.expired_prepared.append(txn["txn_id"])
            report.changed = True
        else:  # aborted / undone: already safe terminal states
            report.untouched.append(txn["txn_id"])
    if report.changed:
        _atomic_write(path, json.dumps(data, indent=2) + "\n")
    return report


class RecoveryCoordinator:
    """Recovery under halt: the ADR-0002 emergency-stop sequence."""

    def __init__(self, switch: KillSwitch, journal_path: Path):
        self.switch = switch
        self.journal_path = Path(journal_path)

    def recover(self, actor: str = "recovery") -> RecoveryReport:
        if not self.switch.is_engaged():
            raise RecoveryRefused(
                "recovery runs only under an engaged kill-switch: "
                "halt new work first, then drive in-flight work to "
                "its undo path")
        report = recover_journal(self.journal_path, actor=actor)
        self.switch._audit("recovery", actor, report.to_dict())
        return report
