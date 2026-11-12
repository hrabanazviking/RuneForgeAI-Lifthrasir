# SPDX-License-Identifier: GPL-2.0-only
"""LIF-0403 tests: separate process + limited permissions for the
executor.

Scope: a pytest tmp_path sandbox only.  No test touches a live
system path, changes any host permission, or uses the network.
The negative control is the mutated-grant / escape battery: every
refusal below must hold, and the suite proves the unmutated path
works first so a refusal cannot be a broken-executor artefact.
"""
import os
import time
from pathlib import Path

import pytest

from lifthrasir.executor import (
    ActionRefusedError,
    ActionRequest,
    ConfinementError,
    ConfinementProfile,
    ExecutionFailedError,
    ExecutionTimeoutError,
    GrantError,
    PolicyGrant,
    run_confined,
)

ALL_FIXTURES = frozenset({
    "fixture.echo", "fixture.read_text", "fixture.write_text",
    "fixture.list_dir", "fixture.sleep", "fixture.crash",
    "fixture.report_limits",
})


def profile(tmp_path, **kw):
    kw.setdefault("allowed_actions", ALL_FIXTURES)
    return ConfinementProfile(sandbox_root=tmp_path / "sandbox", **kw)


def grant(action, target, **kw):
    kw.setdefault("identity", "user:volmarr")
    kw.setdefault("expires_at", time.time() + 600)
    return PolicyGrant(action=action, resource=target, **kw)


def test_echo_runs_in_separate_process(tmp_path):
    result = run_confined(
        profile(tmp_path),
        grant("fixture.echo", "."),
        ActionRequest("fixture.echo", ".", {"text": "hello"}))
    assert result.output == "hello"
    assert result.child_pid != os.getpid()
    assert result.child_pid > 0


def test_write_read_list_roundtrip_inside_sandbox(tmp_path):
    prof = profile(tmp_path)
    written = run_confined(
        prof, grant("fixture.write_text", "note.txt"),
        ActionRequest("fixture.write_text", "note.txt",
                      {"text": "confined"}))
    assert written.output == len("confined")
    read = run_confined(
        prof, grant("fixture.read_text", "note.txt"),
        ActionRequest("fixture.read_text", "note.txt"))
    assert read.output == "confined"
    listing = run_confined(
        prof, grant("fixture.list_dir", "."),
        ActionRequest("fixture.list_dir", "."))
    assert listing.output == ["note.txt"]
    # The file really landed inside the sandbox and nowhere else.
    assert (tmp_path / "sandbox" / "note.txt").read_text() == "confined"


def test_dotdot_escape_refused(tmp_path):
    with pytest.raises(ConfinementError):
        run_confined(
            profile(tmp_path),
            grant("fixture.read_text", "../secret.txt"),
            ActionRequest("fixture.read_text", "../secret.txt"))


def test_absolute_host_path_refused(tmp_path):
    with pytest.raises(ConfinementError):
        run_confined(
            profile(tmp_path),
            grant("fixture.read_text", "/etc/passwd"),
            ActionRequest("fixture.read_text", "/etc/passwd"))


def test_symlink_escape_refused(tmp_path):
    outside = tmp_path / "outside.txt"
    outside.write_text("host-secret", encoding="utf-8")
    sandbox = tmp_path / "sandbox"
    sandbox.mkdir()
    (sandbox / "link.txt").symlink_to(outside)
    with pytest.raises(ConfinementError):
        run_confined(
            profile(tmp_path),
            grant("fixture.read_text", "link.txt"),
            ActionRequest("fixture.read_text", "link.txt"))


def test_no_grant_refused(tmp_path):
    with pytest.raises(GrantError):
        run_confined(
            profile(tmp_path), None,
            ActionRequest("fixture.echo", ".", {"text": "x"}))


def test_expired_grant_refused(tmp_path):
    stale = PolicyGrant(identity="user:volmarr",
                        action="fixture.echo", resource=".",
                        expires_at=time.time() - 5)
    with pytest.raises(GrantError):
        run_confined(profile(tmp_path), stale,
                     ActionRequest("fixture.echo", ".",
                                   {"text": "x"}))


def test_grant_for_other_resource_refused(tmp_path):
    with pytest.raises(GrantError):
        run_confined(
            profile(tmp_path),
            grant("fixture.read_text", "other.txt"),
            ActionRequest("fixture.read_text", "note.txt"))


def test_grant_for_other_action_refused(tmp_path):
    with pytest.raises(GrantError):
        run_confined(
            profile(tmp_path),
            grant("fixture.echo", "note.txt"),
            ActionRequest("fixture.read_text", "note.txt"))


def test_high_risk_grant_refused(tmp_path):
    risky = PolicyGrant(identity="user:volmarr",
                        action="fixture.echo", resource=".",
                        risk_level="L4",
                        expires_at=time.time() + 600)
    with pytest.raises(GrantError):
        run_confined(profile(tmp_path), risky,
                     ActionRequest("fixture.echo", ".",
                                   {"text": "x"}))


def test_unknown_action_refused(tmp_path):
    with pytest.raises(ActionRefusedError):
        run_confined(
            profile(tmp_path),
            grant("shell.exec", "."),
            ActionRequest("shell.exec", ".",
                          {"text": "rm -rf /"}))


def test_action_outside_profile_allowlist_refused(tmp_path):
    narrow = ConfinementProfile(
        sandbox_root=tmp_path / "sandbox",
        allowed_actions=frozenset({"fixture.echo"}))
    with pytest.raises(ActionRefusedError):
        run_confined(
            narrow, grant("fixture.read_text", "note.txt"),
            ActionRequest("fixture.read_text", "note.txt"))


def test_timeout_terminates_child_and_caller_survives(tmp_path):
    prof = profile(tmp_path, max_wall_seconds=1.0)
    with pytest.raises(ExecutionTimeoutError):
        run_confined(
            prof, grant("fixture.sleep", "."),
            ActionRequest("fixture.sleep", ".", {"seconds": 30}))
    again = run_confined(
        prof, grant("fixture.echo", "."),
        ActionRequest("fixture.echo", ".", {"text": "alive"}))
    assert again.output == "alive"


def test_crash_is_contained_and_caller_survives(tmp_path):
    prof = profile(tmp_path)
    with pytest.raises(ExecutionFailedError):
        run_confined(
            prof, grant("fixture.crash", "."),
            ActionRequest("fixture.crash", "."))
    again = run_confined(
        prof, grant("fixture.echo", "."),
        ActionRequest("fixture.echo", ".", {"text": "alive"}))
    assert again.output == "alive"


def test_child_environment_scrubbed_and_limits_applied(tmp_path,
                                                       monkeypatch):
    monkeypatch.setenv("LIFTHRASIR_TEST_SENTINEL", "must-not-leak")
    prof = profile(tmp_path, max_cpu_seconds=7)
    result = run_confined(
        prof, grant("fixture.report_limits", "."),
        ActionRequest("fixture.report_limits", "."))
    report = result.output
    assert report["pid"] == result.child_pid != os.getpid()
    assert report["cwd"] == str((tmp_path / "sandbox").resolve())
    assert "LIFTHRASIR_TEST_SENTINEL" not in report["env_keys"]
    assert report["env_keys"] == ["LANG", "PATH"]
    assert report["rlimit_cpu"] == 7
    assert report["rlimit_core"] == 0
    assert report["rlimit_nofile"] == 64


def test_output_cap_enforced(tmp_path):
    prof = profile(tmp_path, max_output_bytes=16)
    with pytest.raises(ExecutionFailedError):
        run_confined(
            prof, grant("fixture.echo", "."),
            ActionRequest("fixture.echo", ".",
                          {"text": "x" * 500}))


def test_profile_cannot_widen_past_ceilings(tmp_path):
    with pytest.raises(ConfinementError):
        ConfinementProfile(sandbox_root=tmp_path / "s",
                           max_wall_seconds=10_000)
    with pytest.raises(ConfinementError):
        ConfinementProfile(sandbox_root=tmp_path / "s",
                           allow_network=True)
    with pytest.raises(ConfinementError):
        ConfinementProfile(sandbox_root=Path("/"))
    with pytest.raises(ActionRefusedError):
        ConfinementProfile(
            sandbox_root=tmp_path / "s",
            allowed_actions=frozenset({"fixture.echo", "shell.exec"}))
