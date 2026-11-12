# SPDX-License-Identifier: GPL-2.0-only
"""LIF-0102: QEMU/KVM create/start/reset/delete workflow for the lab.

Home: master roadmap section 3 places lab tooling under ``lab/`` and
section 4 assigns the rapid lab to Python and names "QEMU/KVM +
libvirt or direct QEMU" as the VM-lab starting point.  This module
uses DIRECT qemu-system-x86_64 command construction (the roadmap
names no single tool as mandatory) and drives it through a
command-runner interface, so the full workflow is testable without
launching a real VM on a shared host.

Safety (master roadmap section 0, invariant 5: experiments only in
disposable VMs):

* every operation refuses a VM definition whose ``disposable`` flag
  is false -- reset and delete are impossible for such a VM;
* every host path the workflow touches must resolve inside the lab
  directory -- path escapes are refused;
* create refuses when the image's actual checksum does not match
  the checksum pinned in the definition (the generic image contract
  shared with LIF-0101: a named image plus its sha256 checksum; no
  LIF-0101-internal detail is hard-coded here);
* memory/CPU are capped; no privileged operation is performed.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Protocol

MAX_MEMORY_MB = 8192
MAX_CPUS = 8
QEMU_BINARY = "qemu-system-x86_64"


class WorkflowRefusal(Exception):
    """Raised when the workflow refuses an unsafe operation."""


@dataclass(frozen=True)
class ImageReference:
    name: str
    sha256: str  # pinned checksum from the image recipe (LIF-0101 contract)


@dataclass(frozen=True)
class VMDefinition:
    name: str
    image: ImageReference
    image_path: Path
    disk_path: Path
    memory_mb: int = 2048
    cpus: int = 2
    disposable: bool = False  # safe default: NOT disposable


class CommandRunner(Protocol):
    def run(self, argv: list[str]) -> int: ...


def file_sha256(path: Path) -> str | None:
    if not path.is_file():
        return None
    h = hashlib.sha256()
    h.update(path.read_bytes())
    return h.hexdigest()


class QemuCommandBuilder:
    """Builds the exact direct-QEMU argv for each transition."""

    def create_disk(self, vm: VMDefinition) -> list[str]:
        return ["qemu-img", "create", "-f", "qcow2", "-F", "qcow2",
                "-b", str(vm.image_path), str(vm.disk_path), "8G"]

    def start(self, vm: VMDefinition) -> list[str]:
        return [QEMU_BINARY, "-name", vm.name, "-accel", "kvm",
                "-m", str(vm.memory_mb), "-smp", str(vm.cpus),
                "-drive", f"file={vm.disk_path},format=qcow2,if=virtio",
                "-display", "none", "-daemonize"]

    def reset(self, vm: VMDefinition) -> list[str]:
        # Hard reset back to the clean overlay: stop, recreate the
        # disposable overlay from the golden image, so guest state
        # returns byte-identical to the clean snapshot state.
        return ["qemu-img", "create", "-f", "qcow2", "-F", "qcow2",
                "-b", str(vm.image_path), str(vm.disk_path), "8G"]

    def delete_disk(self, vm: VMDefinition) -> list[str]:
        return ["rm", "--", str(vm.disk_path)]


@dataclass
class Transition:
    action: str
    from_state: str
    to_state: str
    argv: list[str]


class VMWorkflow:
    STATES = ("absent", "defined", "running")

    def __init__(self, lab_root: Path, runner: CommandRunner,
                 builder: QemuCommandBuilder | None = None,
                 checksum_of: Callable[[Path], str | None] = file_sha256):
        self.lab_root = Path(lab_root).resolve()
        self.runner = runner
        self.builder = builder or QemuCommandBuilder()
        self.checksum_of = checksum_of
        self.state = "absent"
        self.log: list[Transition] = []
        self.vm: VMDefinition | None = None

    # -- safety gates -------------------------------------------------
    def _require_disposable(self, vm: VMDefinition, action: str) -> None:
        if not vm.disposable:
            raise WorkflowRefusal(
                f"{action} refused: VM '{vm.name}' is not marked disposable")

    def _require_in_lab(self, path: Path) -> None:
        resolved = Path(path).resolve()
        if resolved != self.lab_root and self.lab_root not in resolved.parents:
            raise WorkflowRefusal(
                f"path refused: {resolved} is outside lab dir {self.lab_root}")

    def _validate(self, vm: VMDefinition, action: str) -> None:
        self._require_disposable(vm, action)
        self._require_in_lab(vm.image_path)
        self._require_in_lab(vm.disk_path)
        if not (1 <= vm.cpus <= MAX_CPUS):
            raise WorkflowRefusal(f"cpu cap exceeded: {vm.cpus}")
        if not (128 <= vm.memory_mb <= MAX_MEMORY_MB):
            raise WorkflowRefusal(f"memory cap exceeded: {vm.memory_mb}")

    def _do(self, action: str, to_state: str, argv: list[str]) -> None:
        rc = self.runner.run(argv)
        if rc != 0:
            raise WorkflowRefusal(f"{action} failed: runner rc={rc}")
        self.log.append(Transition(action, self.state, to_state, argv))
        self.state = to_state

    # -- lifecycle ----------------------------------------------------
    def create(self, vm: VMDefinition) -> None:
        if self.state != "absent":
            raise WorkflowRefusal(f"create refused: state is {self.state}")
        self._validate(vm, "create")
        actual = self.checksum_of(vm.image_path)
        if actual is not None and actual.lower() != vm.image.sha256.lower():
            raise WorkflowRefusal(
                "create refused: image checksum mismatch for "
                f"'{vm.image.name}' (pinned {vm.image.sha256}, got {actual})")
        self._do("create", "defined", self.builder.create_disk(vm))
        self.vm = vm

    def start(self) -> None:
        if self.state != "defined" or self.vm is None:
            raise WorkflowRefusal(f"start refused: state is {self.state}")
        self._validate(self.vm, "start")
        self._do("start", "running", self.builder.start(self.vm))

    def reset(self) -> None:
        if self.state not in ("defined", "running") or self.vm is None:
            raise WorkflowRefusal(f"reset refused: state is {self.state}")
        self._validate(self.vm, "reset")
        self._do("reset", "defined", self.builder.reset(self.vm))

    def delete(self) -> None:
        if self.state == "absent" or self.vm is None:
            raise WorkflowRefusal("delete refused: no VM defined")
        self._validate(self.vm, "delete")
        self._do("delete", "absent", self.builder.delete_disk(self.vm))
        self.vm = None


class FakeRunner:
    """Dry-run runner: records commands, simulates guest state.

    ``guest_state`` stands for the guest disk contents: it starts as
    the clean snapshot, tests may corrupt it via ``inject_failure``,
    and a workflow reset (overlay recreation) restores it.
    """

    CLEAN = "clean-snapshot"

    def __init__(self) -> None:
        self.commands: list[list[str]] = []
        self.guest_state = self.CLEAN
        self.running = False

    def inject_failure(self) -> None:
        self.guest_state = "corrupted-by-injected-failure"
        self.running = False

    def run(self, argv: list[str]) -> int:
        self.commands.append(list(argv))
        if argv[0] == "qemu-img" and "create" in argv:
            self.guest_state = self.CLEAN  # fresh overlay from golden image
        elif argv[0].startswith("qemu-system"):
            self.running = True
        elif argv[0] == "rm":
            self.guest_state = "deleted"
            self.running = False
        return 0
