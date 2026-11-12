# SPDX-License-Identifier: GPL-2.0-only
"""LIF-1001 tests for the benchmark harness (lab/benchmark_harness.py).

Covers: controlled-environment validation (fail-closed pins, bounds),
child-environment construction (allowlist inheritance only), the
controlled fingerprint as comparability key, distribution statistics
as pure functions with hand-computed values, warmup/repetition
semantics on tiny deterministic workloads, the determinism gate
(a workload whose checksum moves under a fixed seed is refused, not
averaged), command workloads under the built environment, the
differential verdict rules (improvement / regression / inconclusive /
incomparable), and byte-stable deterministic reports from recorded
fixture samples. Everything is fixture-scale: the built-in workloads
are bounded integer loops; no test stresses the host.
"""
import ast
import importlib.util
import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
MOD_PATH = REPO / "lab" / "benchmark_harness.py"
FIXTURE = REPO / "tests" / "fixtures" / "lif1001" / "samples.json"

spec = importlib.util.spec_from_file_location("benchmark_harness", MOD_PATH)
bench = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = bench
spec.loader.exec_module(bench)


def _spec(**kw):
    base = {"workload_id": "hash-chain"}
    base.update(kw)
    return bench.EnvironmentSpec(**base)


# --- spec validation -------------------------------------------------

def test_module_file_exists():
    assert MOD_PATH.is_file(), "lab/benchmark_harness.py is missing"


def test_spec_defaults_and_fingerprint_stable():
    a, b = _spec(), _spec()
    assert a.controlled_fingerprint() == b.controlled_fingerprint()
    assert a.total_runs == a.warmup + a.repetitions


def test_fingerprint_changes_with_any_control():
    base = _spec().controlled_fingerprint()
    for kw in ({"seed": 2}, {"repetitions": 6}, {"warmup": 0},
               {"workload_id": "sort-fixed"},
               {"pinned_env": {"OMP_NUM_THREADS": "1"}}):
        assert _spec(**kw).controlled_fingerprint() != base, kw


def test_repetitions_below_minimum_refused():
    with pytest.raises(bench.MalformedSpecError):
        _spec(repetitions=bench.MIN_REPETITIONS - 1)
    with pytest.raises(bench.MalformedSpecError):
        _spec(repetitions=bench.MAX_REPETITIONS + 1)


def test_timeout_bounds_refused():
    with pytest.raises(bench.MalformedSpecError):
        _spec(timeout_s=0.01)
    with pytest.raises(bench.MalformedSpecError):
        _spec(timeout_s=bench.MAX_TIMEOUT_S + 1)


def test_forbidden_pin_keys_refused():
    for key in ("LD_PRELOAD", "PYTHONPATH", "NODE_OPTIONS"):
        with pytest.raises(bench.BenchEnvironmentError):
            _spec(pinned_env={key: "x"})


def test_malformed_pin_keys_refused():
    for key in ("lower_case", "HAS SPACE", "9LEADING", ""):
        with pytest.raises(bench.BenchEnvironmentError):
            _spec(pinned_env={key: "x"})
    with pytest.raises(bench.MalformedSpecError):
        _spec(pinned_env={"GOOD_KEY": 3})


def test_spec_dict_roundtrip_and_strictness():
    original = _spec(seed=7, pinned_env={"OMP_NUM_THREADS": "1"})
    clone = bench.spec_from_dict(bench.spec_as_dict(original))
    assert clone == original
    bad = bench.spec_as_dict(original)
    bad["surprise"] = True
    with pytest.raises(bench.MalformedSpecError):
        bench.spec_from_dict(bad)
    bad2 = bench.spec_as_dict(original)
    bad2["schema"] = "lifthrasir.benchmark.v9.9"
    with pytest.raises(bench.MalformedSpecError):
        bench.spec_from_dict(bad2)


# --- child environment ------------------------------------------------

def test_child_env_allowlist_and_pins():
    spec = _spec(seed=42, pinned_env={"OMP_NUM_THREADS": "1"})
    base = {"PATH": "/usr/bin", "HOME": "/home/x",
            "SECRET_LEAK": "must-not-pass", "OMP_NUM_THREADS": "99"}
    env = bench.build_child_env(spec, base_env=base)
    assert env["PATH"] == "/usr/bin"
    assert "SECRET_LEAK" not in env
    assert env["OMP_NUM_THREADS"] == "1"  # pin wins over ambient
    assert env["LIFTHRASIR_BENCH_SEED"] == "42"
    assert env["LIFTHRASIR_BENCH_WORKLOAD"] == "hash-chain"


# --- statistics ---------------------------------------------------------

def test_summarize_hand_computed():
    stats = bench.summarize([1.0, 2.0, 3.0, 4.0, 5.0])
    assert stats["n"] == 5
    assert stats["min"] == 1.0 and stats["max"] == 5.0
    assert stats["mean"] == 3.0 and stats["median"] == 3.0
    assert abs(stats["stdev"] - 1.5811388300841898) < 1e-12
    assert stats["p95"] == 5.0
    assert stats["ci95_low"] < 3.0 < stats["ci95_high"]


def test_summarize_refuses_too_few_or_bad_samples():
    with pytest.raises(bench.MalformedSpecError):
        bench.summarize([1.0, 2.0])
    with pytest.raises(bench.MalformedSpecError):
        bench.summarize([1.0, -1.0, 2.0])
    with pytest.raises(bench.MalformedSpecError):
        bench.summarize([1.0, float("inf"), 2.0])


# --- live measurement (tiny, deterministic) ----------------------------

def test_run_builtin_repetitions_and_warmup():
    spec = _spec(repetitions=4, warmup=2)
    m = bench.run_builtin(spec)
    assert len(m.samples) == 4  # warmup runs are not measured samples
    assert m.stats["n"] == 4
    assert len(m.checksum) == 16
    again = bench.run_builtin(spec)
    assert again.checksum == m.checksum  # same seed, same result


def test_run_builtin_seed_changes_checksum():
    a = bench.run_builtin(_spec(seed=1))
    b = bench.run_builtin(_spec(seed=2))
    assert a.checksum != b.checksum


def test_run_builtin_unknown_workload_refused():
    with pytest.raises(bench.WorkloadError):
        bench.run_builtin(_spec(workload_id="no-such-workload"))


def test_nondeterministic_workload_refused_not_averaged():
    calls = {"n": 0}

    def flaky(seed):
        calls["n"] += 1
        return "checksum-%d" % calls["n"]

    with pytest.raises(bench.NondeterminismError):
        bench.run_callable(_spec(repetitions=3, warmup=0), flaky)


def test_run_command_controlled_env():
    argv = [sys.executable, "-c",
            "import os; print(os.environ['LIFTHRASIR_BENCH_SEED'])"]
    m = bench.run_command(_spec(seed=9, repetitions=3, warmup=1), argv)
    assert len(m.samples) == 3
    assert m.checksum  # identical stdout hash across all runs


def test_run_command_failure_refused():
    argv = [sys.executable, "-c", "import sys; sys.exit(3)"]
    with pytest.raises(bench.WorkloadError):
        bench.run_command(_spec(repetitions=3, warmup=0), argv)
    with pytest.raises(bench.WorkloadError):
        bench.run_command(_spec(), [])


# --- comparison ---------------------------------------------------------

BASE = [0.100, 0.102, 0.098, 0.101, 0.099]
FASTER = [0.080, 0.081, 0.079, 0.080, 0.082]
SLOWER = [0.120, 0.121, 0.119, 0.120, 0.122]
NOISY_OVERLAP = [0.100, 0.115, 0.085, 0.110, 0.090]


def test_compare_improvement_and_regression():
    spec = _spec()
    fast = bench.compare(spec, BASE, spec, FASTER)
    assert fast["verdict"] == "improvement"
    assert fast["median_shift_percent"] < -15
    slow = bench.compare(spec, BASE, spec, SLOWER)
    assert slow["verdict"] == "regression"
    assert slow["median_shift_percent"] > 15


def test_compare_overlap_is_inconclusive():
    spec = _spec()
    result = bench.compare(spec, BASE, spec, NOISY_OVERLAP)
    assert result["ci_overlap"] is True
    assert result["verdict"] == "inconclusive"


def test_compare_noise_floor_is_inconclusive():
    spec = _spec()
    tiny = [0.0995, 0.0996, 0.0994, 0.0995, 0.0996]
    result = bench.compare(spec, BASE, spec, tiny)
    assert result["verdict"] == "inconclusive"  # shift inside 1% floor


def test_compare_different_controls_refused():
    with pytest.raises(bench.ComparisonError):
        bench.compare(_spec(seed=1), BASE, _spec(seed=2), FASTER)
    with pytest.raises(bench.ComparisonError):
        bench.compare(_spec(), BASE,
                      _spec(pinned_env={"OMP_NUM_THREADS": "1"}), FASTER)


# --- recorded fixture + deterministic report -----------------------------

def test_fixture_report_deterministic_and_verdict():
    spec, base, cand = bench.load_sample_fixture(FIXTURE)
    report = bench.report_from_samples(spec, base, cand)
    assert report["comparison"]["verdict"] == "improvement"
    md1 = bench.render_markdown(report)
    md2 = bench.render_markdown(
        bench.report_from_samples(spec, base, cand))
    assert md1 == md2  # byte-identical for identical recorded input
    assert "improvement" in md1
    json.dumps(report)  # report is JSON-serializable


def test_fixture_malformed_refused(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({"schema": "nope"}), encoding="utf-8")
    with pytest.raises(bench.MalformedSpecError):
        bench.load_sample_fixture(bad)
    short = json.loads(FIXTURE.read_text(encoding="utf-8"))
    short["baseline_samples"] = [0.1, 0.2]
    bad2 = tmp_path / "short.json"
    bad2.write_text(json.dumps(short), encoding="utf-8")
    with pytest.raises(bench.MalformedSpecError):
        bench.load_sample_fixture(bad2)


def test_measurement_as_dict_shape():
    m = bench.run_builtin(_spec(repetitions=3, warmup=0))
    d = bench.measurement_as_dict(m)
    assert d["schema"] == bench.BENCH_SCHEMA
    assert d["checksum"] == m.checksum
    assert d["observed_fingerprint"]["cpu_count"] >= 1
    json.dumps(d)


# --- offline / import surface -------------------------------------------

def test_import_surface_is_local_stdlib_only():
    tree = ast.parse(MOD_PATH.read_text(encoding="utf-8"))
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
    allowed = set(sys.stdlib_module_names)
    assert imported <= allowed, imported - allowed
    banned = {"socket", "urllib", "http", "requests", "ftplib"}
    assert not (imported & banned), imported & banned
