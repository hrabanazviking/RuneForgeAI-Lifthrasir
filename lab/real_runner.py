# SPDX-License-Identifier: GPL-2.0-only
"""Real command runner for the lab (Activation Phase 1, slice B).

Kept clearly separate from ``FakeRunner`` in ``lab/vm_workflow.py``:
the fake records commands and simulates guest state for tests; this
runner actually executes argv on the host via ``subprocess`` with NO
shell. Safety rails (invariants 1, 3, 5):

* argv[0] must be in an allowlist (default: qemu-img,
  qemu-system-x86_64, rm) -- resolved to an absolute path;
* no shell, ever; empty argv and NUL bytes are refused;
* every call is bounded by a timeout and its argv + rc are recorded
  in ``self.calls`` for the evidence pack;
* this runner is for the disposable lab only: callers (VMWorkflow)
  already enforce disposable flags, lab-path confinement and caps.
"""
from __future__ import annotations

import shutil
import subprocess

DEFAULT_ALLOWED = ("qemu-img", "qemu-system-x86_64", "rm")


class RunnerRefusal(Exception):
    """Raised when the real runner refuses an unsafe invocation."""


class SubprocessRunner:
    def __init__(self, allowed=DEFAULT_ALLOWED, timeout_s: int = 900):
        self.allowed = tuple(allowed)
        self.timeout_s = int(timeout_s)
        self.calls: list[dict] = []

    def run(self, argv: list[str]) -> int:
        if not argv or not all(isinstance(a, str) and "\x00" not in a
                                for a in argv):
            raise RunnerRefusal("refused: empty or invalid argv")
        prog = argv[0]
        if prog not in self.allowed:
            raise RunnerRefusal(f"refused: program not allowlisted: {prog}")
        resolved = shutil.which(prog)
        if resolved is None:
            raise RunnerRefusal(f"refused: program not found: {prog}")
        full = [resolved, *argv[1:]]
        try:
            proc = subprocess.run(full, shell=False, timeout=self.timeout_s,
                                  stdout=subprocess.DEVNULL,
                                  stderr=subprocess.DEVNULL)
            rc = int(proc.returncode)
        except subprocess.TimeoutExpired:
            rc = 124
        self.calls.append({"argv": list(argv), "rc": rc})
        return rc
