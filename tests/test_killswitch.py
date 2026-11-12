# SPDX-License-Identifier: GPL-2.0-only
"""LIF-0406 kill-switch and model-independent recovery tests.

Scope: the switch, the fixture-process guard and journal recovery in
``src/lifthrasir/killswitch.py``, exercised ONLY against this
project's own fixture processes (tests/fixtures/lif0406/sleeper.py)
and fixture journals.  No real host service or foreign process is
ever signalled: the one foreign process spawned here is deliberately
left UNREGISTERED and the test asserts it survives terminate_all()
(and then cleans it up itself).

Pinned behaviour: halt is durable across instances and fails closed
on corrupt state; the audit log is hash-chained; fixture termination
re-verifies PID identity (start-time + cmdline marker) so PID reuse
skips; recovery preserves committed transactions byte-for-byte
(never replays), rolls in-flight transactions onto their undo path,
expires prepared ones, is idempotent, and refuses corrupt journals;
recovery runs only under an engaged switch; the module is
model-independent by source scan (stdlib allowlist only).
"""
import ast
import json
import os
import subprocess
import sys
import time
import uuid
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from lifthrasir import killswitch as ks  # noqa: E402

FIXTURES = REPO / "tests" / "fixtures" / "lif0406"
SLEEPER = FIXTURES / "sleeper.py"


def marker() -> str:
    return f"lif0406-fixture-{uuid.uuid4().hex[:12]}"


def spawn_sleeper(mark: str, ignore_term: bool = False) -> subprocess.Popen:
    argv = [sys.executable, str(SLEEPER), mark]
    if ignore_term:
        argv.append("--ignore-term")
    return subprocess.Popen(argv, stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL)


def alive(pid: int) -> bool:
    return ks._proc_identity(pid) is not None


@pytest.fixture()
def switch(tmp_path):
    return ks.KillSwitch(tmp_path / "state")


# -- halt semantics ---------------------------------------------------

def test_engage_blocks_and_release_restores(switch):
    switch.require_clear("execute plan")  # clear: no raise
    rec = switch.engage("operator", "drill")
    assert switch.is_engaged()
    with pytest.raises(ks.KillSwitchEngaged):
        switch.require_clear("execute plan")
    with pytest.raises(ks.KillSwitchEngaged):
        with switch.guard("read status"):
            pass
    assert switch.release("operator", "drill over") is True
    assert not switch.is_engaged()
    switch.require_clear("execute plan")
    assert rec.nonce


def test_halt_persists_across_instances(tmp_path):
    first = ks.KillSwitch(tmp_path / "state")
    first.engage("operator", "power event")
    second = ks.KillSwitch(tmp_path / "state")  # simulated restart
    assert second.is_engaged()
    with pytest.raises(ks.KillSwitchEngaged):
        second.require_clear("anything")


def test_corrupt_halt_state_fails_closed(switch):
    switch.halt_path.write_text("{ not json", encoding="utf-8")
    assert switch.is_engaged() is True
    assert switch.status()["corrupt"] is True
    with pytest.raises(ks.KillSwitchEngaged):
        switch.require_clear("anything")
    # ...yet an operator can still deliberately clear it, audited.
    assert switch.release("operator", "clearing corrupt halt") is True
    assert not switch.is_engaged()


def test_engage_requires_actor_and_reason(switch):
    with pytest.raises(ks.KillSwitchStateError):
        switch.engage("", "x")
    with pytest.raises(ks.KillSwitchStateError):
        switch.engage("operator", "  ")


def test_audit_chain_verifies_and_detects_tamper(switch):
    switch.engage("operator", "drill")
    switch.release("operator", "done")
    assert switch.verify_audit() is True
    lines = switch.audit_path.read_text(encoding="utf-8").splitlines()
    entry = json.loads(lines[0])
    entry["detail"]["reason"] = "forged"
    lines[0] = json.dumps(entry, sort_keys=True)
    switch.audit_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    assert switch.verify_audit() is False


# -- fixture process guard ---------------------------------------------

def test_registered_fixture_is_terminated(tmp_path):
    registry = ks.FixtureRegistry(tmp_path / "state")
    mark = marker()
    pid = registry.spawn_fixture(
        [sys.executable, str(SLEEPER), mark], mark)
    assert alive(pid)
    report = registry.terminate_all()
    assert report.terminated == [pid]
    assert not alive(pid)
    assert registry.entries() == []


def test_unregistered_foreign_process_is_never_signalled(tmp_path):
    registry = ks.FixtureRegistry(tmp_path / "state")
    foreign = spawn_sleeper(marker())  # same sleeper, NEVER registered
    try:
        report = registry.terminate_all()
        assert report.terminated == [] and report.skipped == []
        assert alive(foreign.pid), "foreign process must survive"
    finally:
        foreign.terminate()
        foreign.wait(timeout=5)


def test_pid_reuse_identity_mismatch_skips(tmp_path):
    registry = ks.FixtureRegistry(tmp_path / "state")
    mark = marker()
    proc = spawn_sleeper(mark)
    try:
        registry.register(proc.pid, mark)
        rows = registry.entries()
        rows[0]["starttime"] = "1"  # stale identity, as after PID reuse
        registry._save(rows)
        report = registry.terminate_all()
        assert report.terminated == []
        assert len(report.skipped) == 1
        assert "start-time mismatch" in report.skipped[0]["why"]
        assert alive(proc.pid), "mismatched process must not be killed"
    finally:
        proc.terminate()
        proc.wait(timeout=5)


def test_registration_requires_marker_in_cmdline(tmp_path):
    registry = ks.FixtureRegistry(tmp_path / "state")
    proc = spawn_sleeper(marker())
    try:
        with pytest.raises(ks.FixtureRefusal):
            registry.register(proc.pid, "marker-not-in-argv")
    finally:
        proc.terminate()
        proc.wait(timeout=5)


def test_sigkill_escalation_for_term_ignoring_fixture(tmp_path):
    registry = ks.FixtureRegistry(tmp_path / "state")
    mark = marker()
    pid = registry.spawn_fixture(
        [sys.executable, str(SLEEPER), mark, "--ignore-term"], mark)
    time.sleep(0.5)  # let the fixture install its SIGTERM-ignoring handler
    report = registry.terminate_all(term_timeout=0.3)
    assert report.killed_after_term == [pid]
    assert not alive(pid)


def test_engage_and_stop_halts_first_then_stops_fixtures(tmp_path):
    switch = ks.KillSwitch(tmp_path / "state")
    registry = ks.FixtureRegistry(tmp_path / "state")
    mark = marker()
    pid = registry.spawn_fixture(
        [sys.executable, str(SLEEPER), mark], mark)
    record, report = ks.engage_and_stop(
        switch, registry, "operator", "runaway drill")
    assert record.nonce and switch.is_engaged()
    assert report.terminated == [pid] and not alive(pid)
    events = [e["event"] for e in switch._audit_entries()]
    assert events == ["engage", "stop_fixtures"]
    assert switch.verify_audit() is True


# -- recovery -----------------------------------------------------------

def copy_fixture(tmp_path, name: str) -> Path:
    dst = tmp_path / name
    dst.write_bytes((FIXTURES / name).read_bytes())
    return dst


def test_recovery_rolls_back_inflight_preserves_committed(tmp_path):
    journal = copy_fixture(tmp_path, "journal-interrupted.json")
    before = json.loads(journal.read_text(encoding="utf-8"))
    committed_before = before["transactions"][0]
    report = ks.recover_journal(journal, actor="test")
    assert report.changed is True
    assert report.preserved_committed == ["txn-committed-1"]
    assert report.expired_prepared == ["txn-prepared-1"]
    assert report.untouched == ["txn-aborted-1"]
    assert report.rolled_back == [{
        "txn_id": "txn-inflight-1",
        "undo_steps": ["undo-step-two", "undo-step-one"]}]
    after = json.loads(journal.read_text(encoding="utf-8"))
    by_id = {t["txn_id"]: t for t in after["transactions"]}
    # Committed preserved exactly: never replayed, never rewritten.
    assert by_id["txn-committed-1"] == committed_before
    assert by_id["txn-inflight-1"]["state"] == "aborted"
    assert by_id["txn-inflight-1"]["recovery"]["undo_steps"] == [
        "undo-step-two", "undo-step-one"]
    assert by_id["txn-prepared-1"]["state"] == "aborted"
    assert by_id["txn-prepared-1"]["recovery"]["action"] == "expire"


def test_recovery_is_idempotent(tmp_path):
    journal = copy_fixture(tmp_path, "journal-interrupted.json")
    ks.recover_journal(journal)
    once = journal.read_bytes()
    report2 = ks.recover_journal(journal)
    assert report2.changed is False
    assert report2.rolled_back == [] and report2.expired_prepared == []
    assert journal.read_bytes() == once


def test_recovery_negative_control_healthy_journal_untouched(tmp_path):
    journal = copy_fixture(tmp_path, "journal-healthy.json")
    before = journal.read_bytes()
    report = ks.recover_journal(journal)
    assert report.changed is False
    assert report.preserved_committed == ["txn-done-1"]
    assert sorted(report.untouched) == ["txn-done-2", "txn-done-3"]
    assert journal.read_bytes() == before  # byte-identical: no rewrite


def test_recovery_refuses_corrupt_and_unknown_state_journals(tmp_path):
    for name in ("journal-corrupt.json", "journal-unknown-state.json"):
        journal = copy_fixture(tmp_path, name)
        before = journal.read_bytes()
        with pytest.raises(ks.RecoveryRefused):
            ks.recover_journal(journal)
        assert journal.read_bytes() == before


def test_recovery_requires_engaged_switch(tmp_path):
    switch = ks.KillSwitch(tmp_path / "state")
    journal = copy_fixture(tmp_path, "journal-interrupted.json")
    coord = ks.RecoveryCoordinator(switch, journal)
    with pytest.raises(ks.RecoveryRefused):
        coord.recover()
    switch.engage("operator", "crash drill")
    report = coord.recover()
    assert report.changed is True
    assert switch.verify_audit() is True


# -- model independence ---------------------------------------------------

def test_model_independence_source_scan():
    tree = ast.parse(Path(ks.__file__).read_text(encoding="utf-8"))
    allowed = {"__future__", "hashlib", "json", "os", "signal",
               "subprocess", "time", "uuid", "contextlib",
               "dataclasses", "datetime", "pathlib", "typing"}
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                imported.add(node.module.split(".")[0])
    assert imported <= allowed, f"non-allowlisted imports: {imported}"
    # No name or attribute in the code (docstrings excluded by the
    # AST) may reference a network, embedding or model facility.
    used = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            used.add(node.id)
        elif isinstance(node, ast.Attribute):
            used.add(node.attr)
    for forbidden in ("socket", "urllib", "requests", "httpx",
                      "openai", "embed", "embeddings", "infer",
                      "inference", "load_model", "call_model"):
        assert forbidden not in used, forbidden
    assert not os.environ.get("LIFTHRASIR_TEST_MODEL", "")
