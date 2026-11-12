# SPDX-License-Identifier: GPL-2.0-only
"""LIF-0105 tests for the local CI integration runner (lab/ci_runner.py).

Covers: trace ID format + uniqueness, log/artifact export contents, and
failure propagation (a failing suite must make the runner report
failure, never success). All fixtures are tiny synthetic suites written
into pytest tmp dirs; everything runs locally and offline.
"""
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
RUNNER_PATH = REPO / "lab" / "ci_runner.py"

spec = importlib.util.spec_from_file_location("ci_runner", RUNNER_PATH)
ci_runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ci_runner)

PASS_SUITE = "def test_ok():\n    assert 1 + 1 == 2\n"
FAIL_SUITE = "def test_bad():\n    assert 1 + 1 == 3, 'deliberate failure'\n"


def _write_suite(tmp_path: Path, body: str) -> Path:
    suite = tmp_path / "fixture_suite"
    suite.mkdir(exist_ok=True)
    (suite / "test_fixture.py").write_text(body, encoding="utf-8")
    return suite


def test_runner_file_exists():
    assert RUNNER_PATH.is_file(), "lab/ci_runner.py is missing"


def test_trace_id_format():
    tid = ci_runner.generate_trace_id()
    assert ci_runner.TRACE_ID_RE.match(tid), f"bad trace ID format: {tid}"


def test_trace_id_unique():
    ids = {ci_runner.generate_trace_id() for _ in range(200)}
    assert len(ids) == 200, "trace IDs must be unique across rapid calls"


def test_export_passing_suite(tmp_path):
    suite = _write_suite(tmp_path, PASS_SUITE)
    artifacts = tmp_path / "artifacts"
    result = ci_runner.run_suite(test_path=str(suite), artifact_root=artifacts,
                                 label="unit-pass", repo_root=REPO)
    assert result["status"] == "passed"
    assert result["exit_code"] == 0
    assert ci_runner.TRACE_ID_RE.match(result["trace_id"])
    run_dir = artifacts / result["trace_id"]
    results_file = run_dir / "results.json"
    log_file = run_dir / "run.log"
    assert results_file.is_file(), "results.json was not exported"
    assert log_file.is_file(), "run.log was not exported"
    exported = json.loads(results_file.read_text(encoding="utf-8"))
    assert exported["trace_id"] == result["trace_id"]
    assert exported["status"] == "passed"
    assert exported["tool_versions"]["python"]
    assert exported["tool_versions"]["pytest"]
    assert exported["summary"]["total"] == 1
    assert exported["summary"]["passed"] == 1
    assert exported["tests"][0]["outcome"] == "passed"
    assert "test_ok" in exported["tests"][0]["nodeid"]
    assert result["trace_id"] in log_file.read_text(encoding="utf-8")


def test_failure_propagation(tmp_path):
    suite = _write_suite(tmp_path, FAIL_SUITE)
    artifacts = tmp_path / "artifacts"
    result = ci_runner.run_suite(test_path=str(suite), artifact_root=artifacts,
                                 label="unit-fail", repo_root=REPO)
    assert result["status"] == "failed", "failing suite reported as success"
    assert result["exit_code"] != 0
    exported = json.loads(
        (artifacts / result["trace_id"] / "results.json").read_text(encoding="utf-8"))
    assert exported["status"] == "failed"
    assert exported["summary"]["failed"] == 1
    assert exported["tests"][0]["outcome"] == "failed"


def test_cli_exit_codes(tmp_path):
    suite = _write_suite(tmp_path, FAIL_SUITE)
    artifacts = tmp_path / "cli-artifacts"
    proc = subprocess.run(
        [sys.executable, str(RUNNER_PATH), "--test-path", str(suite),
         "--artifact-dir", str(artifacts), "--label", "cli-fail"],
        cwd=str(REPO), capture_output=True, text=True)
    assert proc.returncode != 0, "CLI must exit non-zero on a failing suite"
    assert "trace_id:" in proc.stdout
    assert "status: failed" in proc.stdout
