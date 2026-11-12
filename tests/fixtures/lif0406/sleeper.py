# SPDX-License-Identifier: GPL-2.0-only
"""LIF-0406 fixture process: this project's own killable sleeper.

Spawned ONLY by the kill-switch tests, carrying a unique marker in
its argv so the fixture registry can re-verify identity before any
signal.  ``--ignore-term`` installs a SIGTERM handler that ignores
the signal, to exercise the guard's SIGKILL escalation path.
"""
import signal
import sys
import time


def main() -> None:
    if "--ignore-term" in sys.argv:
        signal.signal(signal.SIGTERM, signal.SIG_IGN)
    deadline = time.time() + 120
    while time.time() < deadline:
        time.sleep(0.05)


if __name__ == "__main__":
    main()
