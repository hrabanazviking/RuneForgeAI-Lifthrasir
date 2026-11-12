# SPDX-License-Identifier: GPL-2.0-only
"""LIF-0903: LTP subset + syzkaller disposable-guest orchestration.

Plans, runs and records LTP-subset and syzkaller-style fuzzing
workloads that may execute ONLY inside disposable lab guests, over
the banked LIF-0102 lab VM workflow (lab/vm_workflow.py) at the
fake-runner level. NO real guest is booted, NO syzkaller binary is
executed, and NO kernel work happens on the host in this slice: the
proof level is orchestration logic plus recorded fixture runs,
exactly like LIF-0102.

Absolute invariant (master roadmap section 0): fuzzing/corruption
workloads NEVER run on the host. Any plan whose target is not a
disposable guest in the lab environment refuses by name, both at
plan time and again at run time.

Kernel fixtures are validated against the LIF-0901 fixture JSON
SHAPE only (that slice is built but unbanked at build time of this
one, so its module is deliberately not imported): a fixture dict
must carry a pinned kernel version, a supported architecture, and
a safety block asserting disposable-VM-only use.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

from lab.vm_workflow import FakeRunner, VMDefinition, VMWorkflow, ImageReference

ORCHESTRATION_SCHEMA = "lifthrasir.guest_orchestration.v0.1"
ORCHESTRATION_SCHEMA_VERSION = "0.1"
WORKLOAD_KINDS = ("ltp", "syzkaller")
LAB_ENVIRONMENT = "disposable-lab"
SUPPORTED_ARCHES = ("x86_64", "arm64")
MAX_ITERATIONS = 10000
MAX_TIMEOUT_S = 3600
MAX_LTP_TESTS = 64

LTP_SUBSET_NAME = "lifthrasir-ltp-subset-v1"
LTP_SUBSET = (
    "open01", "read01", "write01", "fork01", "execve01", "pipe01",
    "mmap01", "mprotect01", "clone01", "getpid01", "uname01", "stat01",
)
SYZKALLER_DEFAULTS = {"executor": "syz-executor", "sandbox": "namespace",
                      "cover": True, "procs": 2}


class OrchestrationError(Exception):
    """Base for all orchestration refusals."""


class MalformedPlanError(OrchestrationError):
    pass


class NonDisposableTargetError(OrchestrationError):
    """Target is not a disposable lab guest; refused by name."""


class FixtureShapeError(OrchestrationError):
    pass


class UnknownWorkloadError(OrchestrationError):
    pass


def validate_kernel_fixture_shape(fixture: object) -> dict:
    """Validate a kernel-fixture dict by shape (LIF-0901 backlog shape).

    Returns a normalized summary; raises FixtureShapeError otherwise.
    """
    if not isinstance(fixture, dict):
        raise FixtureShapeError("kernel fixture must be a JSON object")
    fid = fixture.get("fixture_id") or fixture.get("id")
    if not isinstance(fid, str) or not fid:
        raise FixtureShapeError("kernel fixture has no fixture id")
    arch = fixture.get("arch") or fixture.get("architecture")
    if arch not in SUPPORTED_ARCHES:
        raise FixtureShapeError(f"kernel fixture '{fid}': unsupported arch {arch!r}")
    source = fixture.get("source") if isinstance(fixture.get("source"), dict) else fixture
    version = source.get("version") or fixture.get("kernel_version") or fixture.get("version")
    if not isinstance(version, str) or not version or version in ("latest", "stable", "mainline"):
        raise FixtureShapeError(f"kernel fixture '{fid}': kernel version is not pinned")
    if version.count(".") < 2 or "x" in version.split(".")[-1]:
        raise FixtureShapeError(f"kernel fixture '{fid}': kernel version {version!r} is floating")
    safety = fixture.get("safety")
    if not isinstance(safety, dict) or safety.get("disposable_vm_only") is not True:
        raise FixtureShapeError(
            f"kernel fixture '{fid}': safety block must assert disposable_vm_only")
    return {"fixture_id": fid, "arch": arch, "kernel_version": version,
            "disposable_vm_only": True}


@dataclass(frozen=True)
class GuestTarget:
    name: str
    environment: str = LAB_ENVIRONMENT
    disposable: bool = False  # safe default: NOT disposable

    def to_dict(self) -> dict:
        return {"name": self.name, "environment": self.environment,
                "disposable": self.disposable}


def validate_target(target: GuestTarget) -> None:
    if target.environment != LAB_ENVIRONMENT or not target.disposable:
        raise NonDisposableTargetError(
            f"target '{target.name}' refused: workload may run only in a "
            f"disposable guest in the '{LAB_ENVIRONMENT}' environment "
            f"(got environment={target.environment!r}, disposable={target.disposable})")


@dataclass(frozen=True)
class RunPlan:
    plan_id: str
    workload: str
    target: GuestTarget
    fixture: dict
    ltp_tests: tuple = ()
    syzkaller: dict = field(default_factory=dict)
    seed: int = 0

    def to_dict(self) -> dict:
        return {"schema": ORCHESTRATION_SCHEMA, "plan_id": self.plan_id,
                "workload": self.workload, "target": self.target.to_dict(),
                "fixture": self.fixture, "ltp_tests": list(self.ltp_tests),
                "syzkaller": self.syzkaller, "seed": self.seed}


def plan_from_dict(data: object) -> RunPlan:
    if not isinstance(data, dict):
        raise MalformedPlanError("run plan must be a JSON object")
    if data.get("schema") not in (None, ORCHESTRATION_SCHEMA):
        raise MalformedPlanError(f"unsupported plan schema {data.get('schema')!r}")
    plan_id = data.get("plan_id")
    if not isinstance(plan_id, str) or not plan_id:
        raise MalformedPlanError("run plan has no plan_id")
    workload = data.get("workload")
    if workload not in WORKLOAD_KINDS:
        raise UnknownWorkloadError(f"plan '{plan_id}': unknown workload {workload!r}")
    t = data.get("target")
    if not isinstance(t, dict) or not isinstance(t.get("name"), str) or not t.get("name"):
        raise MalformedPlanError(f"plan '{plan_id}': target with a name is required")
    target = GuestTarget(name=t["name"], environment=t.get("environment", ""),
                         disposable=t.get("disposable") is True)
    validate_target(target)
    fixture = validate_kernel_fixture_shape(data.get("fixture"))
    ltp_tests: tuple = ()
    syz: dict = {}
    if workload == "ltp":
        tests = data.get("ltp_tests", list(LTP_SUBSET))
        if not isinstance(tests, list) or not tests or len(tests) > MAX_LTP_TESTS:
            raise MalformedPlanError(f"plan '{plan_id}': ltp_tests must be 1..{MAX_LTP_TESTS} names")
        unknown = [x for x in tests if x not in LTP_SUBSET]
        if unknown:
            raise MalformedPlanError(
                f"plan '{plan_id}': tests outside the pinned LTP subset: {unknown}")
        ltp_tests = tuple(tests)
    else:
        raw = data.get("syzkaller", {})
        if not isinstance(raw, dict):
            raise MalformedPlanError(f"plan '{plan_id}': syzkaller config must be an object")
        syz = {**SYZKALLER_DEFAULTS, **raw}
        it = syz.get("iterations", 100)
        to = syz.get("timeout_s", 600)
        if not isinstance(it, int) or not (1 <= it <= MAX_ITERATIONS):
            raise MalformedPlanError(f"plan '{plan_id}': iterations out of bounds: {it!r}")
        if not isinstance(to, int) or not (1 <= to <= MAX_TIMEOUT_S):
            raise MalformedPlanError(f"plan '{plan_id}': timeout_s out of bounds: {to!r}")
        syz["iterations"] = it
        syz["timeout_s"] = to
    seed = data.get("seed", 0)
    if not isinstance(seed, int):
        raise MalformedPlanError(f"plan '{plan_id}': seed must be an int")
    return RunPlan(plan_id=plan_id, workload=workload, target=target,
                   fixture=fixture, ltp_tests=ltp_tests, syzkaller=syz, seed=seed)


class GuestWorkloadRunner(Protocol):
    """Runs one workload inside an already-started disposable guest."""
    def run_workload(self, plan: RunPlan) -> dict: ...


class FakeGuestRunner:
    """Recorded fixture runner: deterministic, boots nothing.

    ``ltp_outcomes`` maps LTP test name -> outcome (default 'pass').
    ``syzkaller_crash`` optionally names a recorded crash title; when
    set, the run reports one reproducer candidate, mirroring a
    recorded syzkaller fixture run.
    """

    def __init__(self, ltp_outcomes: dict | None = None,
                 syzkaller_crash: str | None = None) -> None:
        self.ltp_outcomes = dict(ltp_outcomes or {})
        self.syzkaller_crash = syzkaller_crash
        self.calls: list[str] = []

    def run_workload(self, plan: RunPlan) -> dict:
        self.calls.append(plan.plan_id)
        if plan.workload == "ltp":
            results = {t: self.ltp_outcomes.get(t, "pass") for t in plan.ltp_tests}
            failed = [t for t, o in results.items() if o != "pass"]
            return {"kind": "ltp", "subset": LTP_SUBSET_NAME, "results": results,
                    "passed": len(results) - len(failed), "failed": len(failed),
                    "outcome": "failed" if failed else "passed"}
        crash = self.syzkaller_crash
        return {"kind": "syzkaller", "iterations": plan.syzkaller["iterations"],
                "executor": plan.syzkaller["executor"],
                "crashes": [crash] if crash else [],
                "reproducers": [crash] if crash else [],
                "outcome": "crash-found" if crash else "completed"}


@dataclass(frozen=True)
class RunRecord:
    plan: dict
    result: dict
    vm_transitions: tuple
    provenance_hash: str

    def to_dict(self) -> dict:
        return {"schema": ORCHESTRATION_SCHEMA, "plan": self.plan,
                "result": self.result,
                "vm_transitions": list(self.vm_transitions),
                "provenance_hash": self.provenance_hash}


def _provenance(plan: RunPlan, result: dict) -> str:
    blob = json.dumps({"plan": plan.to_dict(), "result": result},
                      sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(blob).hexdigest()


def orchestrate(plan_data: object, lab_root: Path,
                workload_runner: GuestWorkloadRunner | None = None,
                vm_runner=None) -> RunRecord:
    """Plan + run one workload in a disposable guest (fake-runner level).

    Drives the banked VMWorkflow lifecycle create -> start -> run ->
    reset -> delete around the workload, re-validating the target at
    run time. The guest image checksum is a placeholder pin: the
    fake runner never reads a real image, and VMWorkflow only checks
    a checksum when the image file exists.
    """
    plan = plan_from_dict(plan_data)
    validate_target(plan.target)  # re-checked at run time, not only plan time
    lab_root = Path(lab_root)
    vm = VMDefinition(
        name=plan.target.name,
        image=ImageReference(name=plan.fixture["fixture_id"], sha256="0" * 64),
        image_path=lab_root / "images" / f"{plan.fixture['fixture_id']}.qcow2",
        disk_path=lab_root / "guests" / f"{plan.target.name}.qcow2",
        disposable=True)
    workflow = VMWorkflow(lab_root=lab_root, runner=vm_runner or FakeRunner())
    runner = workload_runner or FakeGuestRunner()
    workflow.create(vm)
    workflow.start()
    result = runner.run_workload(plan)
    workflow.reset()
    workflow.delete()
    transitions = tuple(f"{t.action}:{t.from_state}->{t.to_state}" for t in workflow.log)
    return RunRecord(plan=plan.to_dict(), result=result,
                     vm_transitions=transitions,
                     provenance_hash=_provenance(plan, result))
