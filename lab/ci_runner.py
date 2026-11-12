# SPDX-License-Identifier: GPL-2.0-only
"""LIF-0105: local CI integration runner for Project Lifthrasir.

Runs the repository test suite in a clean, reproducible, fully offline
way, assigns every run a unique test trace ID, and exports the run's
logs plus a machine-readable result summary (JSON) to a named artifact
directory.

Home justification: master roadmap section 3 places the laboratory and
test-harness material under ``lab/`` (VM recipes and lab tooling) and
section 4 assigns the rapid lab and test harness to Python.  This
runner is lab test-harness tooling, so it lives in ``lab/``; the tests
that verify the runner itself live with the rest of the suite in
``tests/``.  There is deliberately no hosted-CI assumption: this
script is the deliverable, runnable unattended from a fresh checkout
with ``python3 lab/ci_runner.py`` (or ``python3 -m lab.ci_runner``).

No network calls are made.  No privileged operations are performed.
"""
from __future__ import annotations

import argparse
import json
import platform
import re
import subprocess
import sys
import uuid
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

SCHEMA_VERSION = "1.0"
TRACE_ID_RE = re.compile(r"^lif-\d{8}T\d{6}Z-[0-9a-f]{12}$")
REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ARTIFACT_ROOT = REPO_ROOT / "artifacts"


def generate_trace_id(now: datetime | None = None) -> str:
    """Return a unique, sortable test trace ID.

    Format: ``lif-YYYYMMDDTHHMMSSZ-<12 lowercase hex chars>`` where the
    hex suffix comes from a random UUID, so IDs stay unique even for
    runs started within the same second.
    """
    stamp = (now or datetime.now(timezone.utc)).strftime("%Y%m%dT%H%M%SZ")
    return f"lif-{stamp}-{uuid.uuid4().hex[:12]}"


def tool_versions() -> dict:
    """Exact tool versions for the evidence record (no network)."""
    versions = {
        "python": platform.python_version(),
        "platform": platform.platform(),
    }
    try:
        import pytest

        versions["pytest"] = pytest.__version__
    except Exception:  # pragma: no cover - pytest missing is itself data
        versions["pytest"] = None
    return versions


def _git_commit(cwd: Path) -> str | None:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=str(cwd), capture_output=True, text=True, timeout=15,
        )
        return out.stdout.strip() if out.returncode == 0 else None
    except Exception:
        return None


def _parse_junit(path: Path) -> tuple[list[dict], dict]:
    tests: list[dict] = []
    summary = {"total": 0, "passed": 0, "failed": 0, "errors": 0, "skipped": 0}
    if not path.is_file():
        return tests, summary
    root = ET.parse(path).getroot()
    suites = [root] if root.tag == "testsuite" else list(root.iter("testsuite"))
    for suite in suites:
        for case in suite.iter("testcase"):
            nodeid = f"{case.get('classname', '')}::{case.get('name', '')}"
            outcome = "passed"
            if case.find("failure") is not None:
                outcome = "failed"
            elif case.find("error") is not None:
                outcome = "error"
            elif case.find("skipped") is not None:
                outcome = "skipped"
            tests.append({
                "nodeid": nodeid,
                "outcome": outcome,
                "duration_s": float(case.get("time", "0") or 0),
            })
            summary["total"] += 1
            key = {"passed": "passed", "failed": "failed",
                   "error": "errors", "skipped": "skipped"}[outcome]
            summary[key] += 1
    return tests, summary


def run_suite(test_path: str | Path = "tests",
              artifact_root: str | Path | None = None,
              label: str | None = None,
              repo_root: str | Path | None = None) -> dict:
    """Run pytest once and export logs + results.json. Returns result dict.

    The result's ``exit_code`` is the pytest exit code: a failing suite
    always yields a non-zero exit code and ``status == \"failed\"`` --
    failure is never reported as success.
    """
    root = Path(repo_root) if repo_root else REPO_ROOT
    trace_id = generate_trace_id()
    artifacts = Path(artifact_root) if artifact_root else DEFAULT_ARTIFACT_ROOT
    run_dir = artifacts / trace_id
    run_dir.mkdir(parents=True, exist_ok=True)
    junit_path = run_dir / "junit.xml"
    log_path = run_dir / "run.log"
    results_path = run_dir / "results.json"

    started = datetime.now(timezone.utc)
    cmd = [sys.executable, "-m", "pytest", str(test_path), "-v",
           f"--junitxml={junit_path}"]
    proc = subprocess.run(cmd, cwd=str(root), capture_output=True, text=True)
    finished = datetime.now(timezone.utc)
    log_path.write_text(
        f"# trace_id: {trace_id}\n# command: {' '.join(cmd)}\n"
        f"# cwd: {root}\n\n{proc.stdout}\n{proc.stderr}",
        encoding="utf-8")

    tests, summary = _parse_junit(junit_path)
    status = "passed" if proc.returncode == 0 else "failed"
    result = {
        "schema_version": SCHEMA_VERSION,
        "trace_id": trace_id,
        "label": label,
        "status": status,
        "exit_code": proc.returncode,
        "command": cmd,
        "cwd": str(root),
        "started_utc": started.isoformat(),
        "finished_utc": finished.isoformat(),
        "duration_s": (finished - started).total_seconds(),
        "tool_versions": tool_versions(),
        "git_commit": _git_commit(root),
        "summary": summary,
        "tests": tests,
        "artifacts": {
            "directory": str(run_dir),
            "log": str(log_path),
            "results": str(results_path),
            "junit": str(junit_path) if junit_path.is_file() else None,
        },
    }
    results_path.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Lifthrasir local CI runner (LIF-0105): runs the test "
                    "suite, assigns a test trace ID, exports logs/artifacts.")
    parser.add_argument("--test-path", default="tests",
                        help="test path passed to pytest (default: tests)")
    parser.add_argument("--artifact-dir", default=None,
                        help="artifact root directory (default: <repo>/artifacts)")
    parser.add_argument("--label", default=None, help="optional run label")
    args = parser.parse_args(argv)
    result = run_suite(test_path=args.test_path,
                       artifact_root=args.artifact_dir, label=args.label)
    print(f"trace_id: {result['trace_id']}")
    print(f"status: {result['status']} (exit {result['exit_code']})")
    print(f"summary: {result['summary']}")
    print(f"artifacts: {result['artifacts']['directory']}")
    return result["exit_code"]


if __name__ == "__main__":
    sys.exit(main())
