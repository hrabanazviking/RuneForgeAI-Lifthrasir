# SPDX-License-Identifier: GPL-2.0-only
"""Tests for lab/real_runner.py (Activation Phase 1, slice B).

Uses only harmless allowlisted test programs (true/false); no VM is
launched here -- real-VM proof lives in lab/build_golden.py evidence.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lab.real_runner import RunnerRefusal, SubprocessRunner


def test_true_and_false_rc_recorded():
    r = SubprocessRunner(allowed=("true", "false"), timeout_s=10)
    assert r.run(["true"]) == 0
    assert r.run(["false"]) == 1
    assert [c["rc"] for c in r.calls] == [0, 1]
    assert r.calls[0]["argv"] == ["true"]


def test_non_allowlisted_refused_and_not_run():
    r = SubprocessRunner(allowed=("true",), timeout_s=10)
    with pytest.raises(RunnerRefusal):
        r.run(["rm", "-rf", "/"])
    with pytest.raises(RunnerRefusal):
        r.run(["sudo", "true"])
    assert r.calls == []


def test_empty_and_nul_argv_refused():
    r = SubprocessRunner(allowed=("true",), timeout_s=10)
    with pytest.raises(RunnerRefusal):
        r.run([])
    with pytest.raises(RunnerRefusal):
        r.run(["true", "a\x00b"])
    assert r.calls == []


def test_missing_program_refused():
    r = SubprocessRunner(allowed=("no-such-prog-xyz",), timeout_s=10)
    with pytest.raises(RunnerRefusal):
        r.run(["no-such-prog-xyz"])
