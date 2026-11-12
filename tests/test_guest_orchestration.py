# SPDX-License-Identifier: GPL-2.0-only
"""LIF-0903 tests: disposable-guest orchestration for LTP + syzkaller."""
import ast
import json
from pathlib import Path

import pytest

from lab.guest_orchestration import (
    LAB_ENVIRONMENT, LTP_SUBSET, FakeGuestRunner, FixtureShapeError,
    MalformedPlanError, NonDisposableTargetError, UnknownWorkloadError,
    orchestrate, plan_from_dict, validate_kernel_fixture_shape)

FIX = json.loads((Path(__file__).parent / "fixtures" / "lif0903" / "plans.json").read_text())


def fx(**over):
    base = json.loads(json.dumps(FIX["fixture"]))
    base.update(over)
    return base


def plan(kind="ltp_plan", **over):
    data = json.loads(json.dumps(FIX[kind]))
    data["fixture"] = fx()
    data.update(over)
    return data


# --- fixture shape ---

def test_fixture_shape_ok():
    s = validate_kernel_fixture_shape(fx())
    assert s == {"fixture_id": "linux-6.12.117-x86_64", "arch": "x86_64",
                 "kernel_version": "6.12.117", "disposable_vm_only": True}


@pytest.mark.parametrize("bad", [
    "not-a-dict", {}, fx(arch="riscv64"), fx(source={"version": "latest"}),
    fx(source={"version": "6.12.x"}), fx(source={"version": "6.12"}),
    fx(safety={"disposable_vm_only": False}), fx(safety={}),
])
def test_fixture_shape_refusals(bad):
    with pytest.raises(FixtureShapeError):
        validate_kernel_fixture_shape(bad)


# --- plans ---

def test_ltp_plan_defaults_to_full_subset():
    data = plan()
    del data["ltp_tests"]
    p = plan_from_dict(data)
    assert p.ltp_tests == LTP_SUBSET


def test_syzkaller_plan_bounds_applied():
    p = plan_from_dict(plan("syzkaller_plan"))
    assert p.syzkaller["iterations"] == 250 and p.syzkaller["timeout_s"] == 900


@pytest.mark.parametrize("over", [
    {"workload": "stress-ng"}, {"plan_id": ""}, {"ltp_tests": []},
    {"ltp_tests": ["not-a-real-test"]}, {"seed": "x"},
])
def test_malformed_plans_refused(over):
    with pytest.raises((MalformedPlanError, UnknownWorkloadError)):
        plan_from_dict(plan(**over))


@pytest.mark.parametrize("over", [
    {"syzkaller": {"iterations": 0}}, {"syzkaller": {"iterations": 10**9}},
    {"syzkaller": {"timeout_s": 0}}, {"syzkaller": {"timeout_s": 10**9}},
])
def test_syzkaller_bounds_refused(over):
    with pytest.raises(MalformedPlanError):
        plan_from_dict(plan("syzkaller_plan", **over))


# --- the invariant: non-disposable / non-lab targets refuse by name ---

@pytest.mark.parametrize("kind,name", [("host_plan", "production-host"),
                                       ("nondisposable_plan", "persistent-vm")])
def test_non_disposable_targets_refuse_by_name(kind, name):
    data = json.loads(json.dumps(FIX[kind]))
    data["fixture"] = fx()
    with pytest.raises(NonDisposableTargetError) as exc:
        plan_from_dict(data)
    assert name in str(exc.value)


def test_wrong_environment_disposable_still_refused():
    data = plan(target={"name": "cloud-vm", "environment": "cloud", "disposable": True})
    with pytest.raises(NonDisposableTargetError) as exc:
        plan_from_dict(data)
    assert "cloud-vm" in str(exc.value)


# --- orchestration runs (fake-runner level) ---

def test_ltp_run_lifecycle_and_result(tmp_path):
    rec = orchestrate(plan(), tmp_path)
    assert rec.result["outcome"] == "passed" and rec.result["passed"] == 3
    assert rec.vm_transitions[0].startswith("create:")
    assert rec.vm_transitions[-1].endswith("->absent")
    assert len(rec.provenance_hash) == 64


def test_ltp_recorded_failure_surfaces(tmp_path):
    runner = FakeGuestRunner(ltp_outcomes={"fork01": "fail"})
    rec = orchestrate(plan(), tmp_path, workload_runner=runner)
    assert rec.result["outcome"] == "failed" and rec.result["failed"] == 1


def test_syzkaller_recorded_crash_yields_reproducer(tmp_path):
    runner = FakeGuestRunner(syzkaller_crash="KASAN: use-after-free in recorded fixture")
    rec = orchestrate(plan("syzkaller_plan"), tmp_path, workload_runner=runner)
    assert rec.result["outcome"] == "crash-found"
    assert rec.result["reproducers"] == ["KASAN: use-after-free in recorded fixture"]


def test_determinism_same_plan_same_hash(tmp_path):
    a = orchestrate(plan(), tmp_path)
    b = orchestrate(plan(), tmp_path)
    assert a.provenance_hash == b.provenance_hash and a.to_dict() == b.to_dict()


def test_orchestrate_refuses_host_target(tmp_path):
    data = json.loads(json.dumps(FIX["host_plan"]))
    data["fixture"] = fx()
    with pytest.raises(NonDisposableTargetError):
        orchestrate(data, tmp_path)


def test_module_imports_no_execution_machinery():
    tree = ast.parse(Path("lab/guest_orchestration.py").read_text())
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
    assert not (imported & {"subprocess", "socket", "os", "shutil", "urllib", "requests"})
    assert LAB_ENVIRONMENT == "disposable-lab"
