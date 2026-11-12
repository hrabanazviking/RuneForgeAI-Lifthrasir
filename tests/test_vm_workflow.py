# SPDX-License-Identifier: GPL-2.0-only
"""LIF-0102 tests: QEMU/KVM workflow against the fake runner.

Done criterion (roadmap/07): clean VM reset after injected failure --
proven at workflow level: after FakeRunner.inject_failure(), reset
restores the guest to the clean snapshot state and the exact command
log is asserted.  No real VM is launched.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lab.vm_workflow import (FakeRunner, ImageReference, VMDefinition,
                             VMWorkflow, WorkflowRefusal)

LAB = Path("/tmp/lifthrasir-lab-fixture")
GOOD_SHA = "a" * 64


def make_vm(**over):
    kw = dict(name="lab-guest-1",
              image=ImageReference("kubuntu-pinned", GOOD_SHA),
              image_path=LAB / "images" / "kubuntu.qcow2",
              disk_path=LAB / "guests" / "lab-guest-1.qcow2",
              memory_mb=2048, cpus=2, disposable=True)
    kw.update(over)
    return VMDefinition(**kw)


def make_wf(checksum=GOOD_SHA):
    runner = FakeRunner()
    wf = VMWorkflow(LAB, runner, checksum_of=lambda p: checksum)
    return wf, runner


def test_full_lifecycle_and_command_log():
    wf, runner = make_wf()
    vm = make_vm()
    wf.create(vm)
    assert wf.state == "defined"
    wf.start()
    assert wf.state == "running" and runner.running
    wf.reset()
    assert wf.state == "defined"
    wf.delete()
    assert wf.state == "absent"
    assert [t.action for t in wf.log] == ["create", "start", "reset", "delete"]
    cmds = runner.commands
    assert cmds[0][:2] == ["qemu-img", "create"]
    assert cmds[1][0] == "qemu-system-x86_64"
    assert "-accel" in cmds[1] and "kvm" in cmds[1]
    assert cmds[2][:2] == ["qemu-img", "create"]  # reset = fresh overlay
    assert cmds[3][0] == "rm"


def test_reset_after_injected_failure_returns_clean_state():
    wf, runner = make_wf()
    wf.create(make_vm())
    wf.start()
    runner.inject_failure()
    assert runner.guest_state != FakeRunner.CLEAN
    wf.reset()
    assert runner.guest_state == FakeRunner.CLEAN
    assert wf.state == "defined"


def test_non_disposable_refused_everywhere():
    wf, _ = make_wf()
    with pytest.raises(WorkflowRefusal):
        wf.create(make_vm(disposable=False))
    wf2, _ = make_wf()
    vm = make_vm()
    wf2.create(vm)
    object.__setattr__(vm, "disposable", False) if False else None
    frozen = VMDefinition(**{**vm.__dict__, "disposable": False})
    wf2.vm = frozen
    with pytest.raises(WorkflowRefusal):
        wf2.reset()
    with pytest.raises(WorkflowRefusal):
        wf2.delete()


def test_path_escape_refused():
    wf, _ = make_wf()
    bad = make_vm(disk_path=Path("/etc/evil.qcow2"))
    with pytest.raises(WorkflowRefusal):
        wf.create(bad)
    bad2 = make_vm(image_path=Path("/tmp/outside.qcow2"))
    with pytest.raises(WorkflowRefusal):
        wf.create(bad2)


def test_checksum_mismatch_refuses_create():
    wf, runner = make_wf(checksum="b" * 64)
    with pytest.raises(WorkflowRefusal):
        wf.create(make_vm())
    assert runner.commands == []  # nothing was issued


def test_resource_caps_refused():
    wf, _ = make_wf()
    with pytest.raises(WorkflowRefusal):
        wf.create(make_vm(memory_mb=10 ** 6))
    with pytest.raises(WorkflowRefusal):
        wf.create(make_vm(cpus=64))


def test_illegal_transitions_refused():
    wf, _ = make_wf()
    with pytest.raises(WorkflowRefusal):
        wf.start()
    with pytest.raises(WorkflowRefusal):
        wf.delete()
