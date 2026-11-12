# SPDX-License-Identifier: GPL-2.0-only
"""LIF-0603 fixture child: this project's own quota-test worker.

Spawned ONLY by the quota tests and the negative-control script,
always through lifthrasir.quotas.run_guarded / start_guarded (or, in
the negative control, deliberately WITHOUT a memory quota to prove
the quota caused the breach verdict).  Modes:

- ``echo <text...>``     print the text and exit 0
- ``sleep <seconds> [--ignore-term]``  sleep; the flag ignores
  SIGTERM to exercise the supervisor's SIGKILL escalation
- ``spin <seconds>``     busy-loop (burns CPU) for the given wall time
- ``allocate <megabytes>``  allocate and touch the memory; a
  MemoryError is deliberately NOT caught, so an RLIMIT_AS breach
  surfaces as a real interpreter MemoryError traceback
- ``report-limits``      print this process's own rlimits as JSON
- ``spew <nbytes>``      write n bytes to stdout (output-cap tests)
- ``crash``              exit 3 immediately
"""
import json
import resource
import signal
import sys
import time


def main(argv) -> int:
    if not argv:
        print("worker: mode required", file=sys.stderr)
        return 2
    mode, rest = argv[0], argv[1:]
    if mode == "echo":
        print(" ".join(rest))
        return 0
    if mode == "sleep":
        if "--ignore-term" in rest:
            signal.signal(signal.SIGTERM, signal.SIG_IGN)
        time.sleep(float(rest[0]))
        print("slept")
        return 0
    if mode == "spin":
        end = time.monotonic() + float(rest[0])
        while time.monotonic() < end:
            pass
        print("spun")
        return 0
    if mode == "allocate":
        size = int(rest[0]) * 1024 * 1024
        buf = bytearray(size)
        for i in range(0, size, 4096):
            buf[i] = 1
        print(f"ALLOCATED {size}")
        return 0
    if mode == "report-limits":
        print(json.dumps({
            "pid": __import__("os").getpid(),
            "rlimit_as": list(resource.getrlimit(resource.RLIMIT_AS)),
            "rlimit_cpu": list(resource.getrlimit(resource.RLIMIT_CPU)),
            "rlimit_nofile": list(
                resource.getrlimit(resource.RLIMIT_NOFILE)),
            "rlimit_core": list(resource.getrlimit(resource.RLIMIT_CORE)),
        }))
        return 0
    if mode == "spew":
        sys.stdout.write("x" * int(rest[0]))
        sys.stdout.flush()
        return 0
    if mode == "crash":
        return 3
    print(f"worker: unknown mode {mode!r}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
