# SPDX-License-Identifier: GPL-2.0-only
"""LIF-1001: benchmark harness with controlled environment and repetitions.

Phase P10 (performance optimizer) foundation slice. Master roadmap
section 5 rule 7 is the contract this harness exists to enforce:
performance claims need a distribution, not a cherry-picked number --
repeated runs and confidence intervals when benchmarking. This module
is the tooling that produces such distributions under a declared,
controlled environment, and refuses to produce or compare numbers
when the controls are missing or the two sides were not measured
under the same controls.

Home justification (master roadmap section 3, following the
LIF-0105 CI runner and LIF-0206 baseline report precedent):
measurement tooling for the rapid lab lives in lab/ (Python for the
rapid lab and test harness) until its contracts stabilize. Workload
profiles themselves are LIF-1002 and candidate ranking is LIF-1003;
neither is claimed here.

Design:

- EnvironmentSpec is the controlled environment, declared as data:
  a fixed seed, a repetition count, a warmup count, a per-run wall
  timeout, and pinned environment variables. Validation is
  fail-closed: fewer than MIN_REPETITIONS measured repetitions,
  a warmup count that leaves no measured run, an out-of-bounds
  timeout, a malformed pin name, or a pin that would subvert the
  measured process (dynamic-loader or interpreter-path injection
  keys) are all refused, never trimmed or silently repaired.
- build_child_env constructs the child environment from nothing but
  a small allowlist of inherited variables plus the declared pins,
  so an ambient variable on the host cannot leak into a measured
  run unnoticed. The controlled fingerprint is a hash of the
  declared controls only (workload id, seed, repetitions, warmup,
  pins); two runs are comparable only when their controlled
  fingerprints are equal. Observed host facts (interpreter version,
  platform, CPU count) are recorded separately as the observed
  fingerprint and never decide comparability: they are provenance,
  in the LIF-0206 style.
- Repetitions: every measured run of a workload must report the
  same result checksum. A workload whose own output changes from
  run to run under a fixed seed is nondeterministic under these
  controls and the whole measurement is refused with
  NondeterminismError rather than averaged over -- averaging over
  a moving target would manufacture a distribution for a result
  that does not exist.
- Statistics are pure functions of the sample list: n, min, max,
  mean, median, sample standard deviation, p95, coefficient of
  variation, and a normal-approximation 95 percent confidence
  interval for the mean. Given the same samples they always return
  the same numbers.
- Comparison (the section 5 differential): baseline and candidate
  sample sets measured under the same controlled fingerprint are
  compared by median shift in percent and by whether the two
  confidence intervals overlap. The verdict is improvement,
  regression, or inconclusive; a median shift inside the declared
  noise floor is inconclusive even when the intervals separate,
  and overlapping intervals are always inconclusive. Comparing
  across different controls raises ComparisonError.
- Reports: report_from_samples builds a JSON-serializable report
  from recorded sample sets, and render_markdown renders it
  deterministically (fixed field order, no timestamps, no host
  values), so the same recorded input yields a byte-identical
  report -- the fixture-level differential this slice is tested
  at, exactly like the LIF-0206 baseline report.

Live measurement is deliberately tiny: the two built-in workloads
are bounded deterministic integer workloads, and command workloads
run a caller-supplied argv under the built child environment with
the declared timeout. No workload in this slice stresses the host;
heavy or long benchmarking on a shared machine is out of scope.

Offline guarantee: this module imports only standard-library
modules for local computation and local subprocess measurement,
reads only files it is explicitly given, and performs no network
access of any kind. The test suite proves the import surface by
scanning this module's import statements.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import platform
import statistics
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

BENCH_SCHEMA = "lifthrasir.benchmark.v0.1"
BENCH_SCHEMA_VERSION = "0.1"

MIN_REPETITIONS = 3
MAX_REPETITIONS = 1000
MAX_WARMUP = 100
MIN_TIMEOUT_S = 0.05
MAX_TIMEOUT_S = 600.0
DEFAULT_NOISE_FLOOR_PERCENT = 1.0

# Variables a measured child may inherit from the host environment.
# Everything else in the ambient environment is excluded by default:
# an unlisted variable is an uncontrolled variable.
INHERITABLE_ENV_KEYS = ("PATH", "HOME", "LANG", "LC_ALL", "TZ",
                        "TMPDIR", "USER")

# Pin keys that would let a spec subvert the measured process itself
# (loader/interpreter injection) or smuggle an uncontrolled search
# path into it. Refused at spec validation, never honoured.
FORBIDDEN_PIN_KEYS = frozenset({
    "LD_PRELOAD", "LD_LIBRARY_PATH", "LD_AUDIT", "LD_DEBUG",
    "PYTHONPATH", "PYTHONSTARTUP", "PYTHONHOME", "PERL5OPT",
    "RUBYOPT", "NODE_OPTIONS",
})

_ENV_KEY_CHARS = frozenset(
    "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_")


class BenchmarkError(Exception):
    """Base class for all benchmark harness refusals."""


class MalformedSpecError(BenchmarkError):
    """The environment spec or sample data is malformed."""


class BenchEnvironmentError(BenchmarkError):
    """A pin or inherited variable violates the controlled env."""


class NondeterminismError(BenchmarkError):
    """A workload changed its own result under a fixed seed."""


class ComparisonError(BenchmarkError):
    """Two sample sets are not comparable under the controls."""


class WorkloadError(BenchmarkError):
    """A measured run failed, timed out, or returned no checksum."""


def _check_env_key(key):
    if not isinstance(key, str) or not key:
        raise BenchEnvironmentError("env key must be a non-empty string")
    if key[0].isdigit() or any(c not in _ENV_KEY_CHARS for c in key):
        raise BenchEnvironmentError("malformed env key: " + repr(key))
    if key != key.upper():
        raise BenchEnvironmentError(
            "env key must be uppercase: " + repr(key))
    return key


@dataclass(frozen=True)
class EnvironmentSpec:
    """Declared controlled environment for a benchmark measurement."""

    workload_id: str
    seed: int = 1
    repetitions: int = 5
    warmup: int = 1
    timeout_s: float = 30.0
    pinned_env: dict = field(default_factory=dict)

    def __post_init__(self):
        if not isinstance(self.workload_id, str) or not self.workload_id:
            raise MalformedSpecError("workload_id must be non-empty")
        if isinstance(self.seed, bool) or not isinstance(self.seed, int):
            raise MalformedSpecError("seed must be an int")
        if (isinstance(self.repetitions, bool)
                or not isinstance(self.repetitions, int)
                or not MIN_REPETITIONS <= self.repetitions <= MAX_REPETITIONS):
            raise MalformedSpecError(
                "repetitions must be an int in [%d, %d]"
                % (MIN_REPETITIONS, MAX_REPETITIONS))
        if (isinstance(self.warmup, bool)
                or not isinstance(self.warmup, int)
                or not 0 <= self.warmup <= MAX_WARMUP):
            raise MalformedSpecError("warmup out of bounds")
        if (isinstance(self.timeout_s, bool)
                or not isinstance(self.timeout_s, (int, float))
                or not MIN_TIMEOUT_S <= float(self.timeout_s) <= MAX_TIMEOUT_S):
            raise MalformedSpecError(
                "timeout_s must be in [%s, %s]"
                % (MIN_TIMEOUT_S, MAX_TIMEOUT_S))
        if not isinstance(self.pinned_env, dict):
            raise MalformedSpecError("pinned_env must be a dict")
        for key, value in self.pinned_env.items():
            _check_env_key(key)
            if key in FORBIDDEN_PIN_KEYS:
                raise BenchEnvironmentError(
                    "pin refused (process-subverting key): " + key)
            if not isinstance(value, str):
                raise MalformedSpecError(
                    "pinned env value must be a string: " + key)

    @property
    def total_runs(self):
        return self.warmup + self.repetitions

    def controlled_fingerprint(self):
        """Hash of the declared controls only (comparability key)."""
        payload = {
            "schema": BENCH_SCHEMA,
            "workload_id": self.workload_id,
            "seed": self.seed,
            "repetitions": self.repetitions,
            "warmup": self.warmup,
            "pinned_env": dict(sorted(self.pinned_env.items())),
        }
        blob = json.dumps(payload, sort_keys=True).encode("utf-8")
        return hashlib.sha256(blob).hexdigest()


def spec_from_dict(data):
    """Build an EnvironmentSpec from its strict dict form."""
    if not isinstance(data, dict):
        raise MalformedSpecError("spec must be a dict")
    allowed = {"schema", "workload_id", "seed", "repetitions",
               "warmup", "timeout_s", "pinned_env"}
    extra = set(data) - allowed
    if extra:
        raise MalformedSpecError(
            "unknown spec fields: " + ", ".join(sorted(extra)))
    if data.get("schema", BENCH_SCHEMA) != BENCH_SCHEMA:
        raise MalformedSpecError("schema mismatch")
    if "workload_id" not in data:
        raise MalformedSpecError("workload_id is required")
    return EnvironmentSpec(
        workload_id=data["workload_id"],
        seed=data.get("seed", 1),
        repetitions=data.get("repetitions", 5),
        warmup=data.get("warmup", 1),
        timeout_s=data.get("timeout_s", 30.0),
        pinned_env=data.get("pinned_env", {}),
    )


def spec_as_dict(spec):
    return {
        "schema": BENCH_SCHEMA,
        "workload_id": spec.workload_id,
        "seed": spec.seed,
        "repetitions": spec.repetitions,
        "warmup": spec.warmup,
        "timeout_s": float(spec.timeout_s),
        "pinned_env": dict(sorted(spec.pinned_env.items())),
    }


def build_child_env(spec, base_env=None):
    """Controlled child env: allowlisted inheritance + declared pins."""
    source = dict(os.environ) if base_env is None else dict(base_env)
    env = {}
    for key in INHERITABLE_ENV_KEYS:
        if key in source:
            env[key] = source[key]
    for key, value in sorted(spec.pinned_env.items()):
        env[key] = value
    env["LIFTHRASIR_BENCH_SEED"] = str(spec.seed)
    env["LIFTHRASIR_BENCH_WORKLOAD"] = spec.workload_id
    return env


def observed_fingerprint():
    """Host facts recorded as provenance; never a comparability key."""
    return {
        "python": platform.python_version(),
        "platform": platform.platform(),
        "cpu_count": os.cpu_count(),
    }


def summarize(samples):
    """Distribution summary of a sample list (pure, deterministic)."""
    vals = [float(s) for s in samples]
    if len(vals) < MIN_REPETITIONS:
        raise MalformedSpecError(
            "need at least %d samples, got %d"
            % (MIN_REPETITIONS, len(vals)))
    if any((not math.isfinite(v)) or v < 0 for v in vals):
        raise MalformedSpecError("samples must be finite and >= 0")
    n = len(vals)
    mean = statistics.fmean(vals)
    median = statistics.median(vals)
    stdev = statistics.stdev(vals) if n > 1 else 0.0
    ordered = sorted(vals)
    p95 = ordered[min(n - 1, math.ceil(0.95 * n) - 1)]
    sem = stdev / math.sqrt(n) if n > 1 else 0.0
    half = 1.96 * sem
    cv = (stdev / mean) if mean > 0 else 0.0
    return {
        "n": n,
        "min": ordered[0],
        "max": ordered[-1],
        "mean": mean,
        "median": median,
        "stdev": stdev,
        "p95": p95,
        "cv": cv,
        "ci95_low": mean - half,
        "ci95_high": mean + half,
    }


def _workload_hash_chain(seed, iterations=20000):
    """Bounded deterministic integer workload; returns a checksum."""
    state = (seed * 2654435761) & 0xFFFFFFFFFFFFFFFF
    for i in range(iterations):
        state ^= (state << 13) & 0xFFFFFFFFFFFFFFFF
        state ^= state >> 7
        state ^= (state << 17) & 0xFFFFFFFFFFFFFFFF
        state = (state + i) & 0xFFFFFFFFFFFFFFFF
    return "%016x" % state


def _workload_sort_fixed(seed, size=4000):
    """Sort a fixed pseudo-random list derived from the seed."""
    values = []
    state = seed & 0x7FFFFFFF
    for _ in range(size):
        state = (state * 1103515245 + 12345) & 0x7FFFFFFF
        values.append(state)
    values.sort()
    digest = hashlib.sha256(
        ",".join(str(v) for v in values[::257]).encode("utf-8"))
    return digest.hexdigest()[:16]


BUILTIN_WORKLOADS = {
    "hash-chain": _workload_hash_chain,
    "sort-fixed": _workload_sort_fixed,
}


@dataclass(frozen=True)
class Measurement:
    spec: EnvironmentSpec
    samples: tuple
    checksum: str
    stats: dict
    observed: dict


def _run_measured(fn, spec):
    """Run fn(seed) warmup+repetitions times; enforce one checksum."""
    checksums = []
    samples = []
    for run in range(spec.total_runs):
        start = time.perf_counter()
        checksum = fn(spec.seed)
        elapsed = time.perf_counter() - start
        if elapsed > float(spec.timeout_s):
            raise WorkloadError(
                "run %d exceeded timeout_s=%s" % (run, spec.timeout_s))
        checksums.append(checksum)
        if run >= spec.warmup:
            samples.append(elapsed)
    if len(set(checksums)) != 1:
        raise NondeterminismError(
            "workload %s produced %d distinct checksums under seed %d"
            % (spec.workload_id, len(set(checksums)), spec.seed))
    return Measurement(spec=spec, samples=tuple(samples),
                       checksum=checksums[0],
                       stats=summarize(samples),
                       observed=observed_fingerprint())


def run_builtin(spec):
    """Measure one built-in workload under the declared controls."""
    fn = BUILTIN_WORKLOADS.get(spec.workload_id)
    if fn is None:
        raise WorkloadError("unknown built-in workload: "
                            + spec.workload_id)
    return _run_measured(fn, spec)


def run_callable(spec, fn):
    """Measure a caller callable fn(seed) -> checksum string."""
    if not callable(fn):
        raise WorkloadError("fn is not callable")
    return _run_measured(fn, spec)


def run_command(spec, argv):
    """Measure an argv workload under the built child environment.

    The workload checksum is the hash of the child's stdout, which
    must be identical on every run (warmup included). The child
    runs with the controlled environment and the declared timeout;
    a non-zero exit or a timeout refuses the whole measurement.
    """
    if (not isinstance(argv, (list, tuple)) or not argv
            or not all(isinstance(a, str) and a for a in argv)):
        raise WorkloadError("argv must be a non-empty list of strings")
    env = build_child_env(spec)

    def once(seed):
        try:
            proc = subprocess.run(
                list(argv), env=env, capture_output=True, text=True,
                timeout=float(spec.timeout_s))
        except subprocess.TimeoutExpired as exc:
            raise WorkloadError(
                "command timed out after %ss" % spec.timeout_s) from exc
        if proc.returncode != 0:
            raise WorkloadError(
                "command exited %d" % proc.returncode)
        return hashlib.sha256(proc.stdout.encode("utf-8")).hexdigest()

    return _run_measured(once, spec)


def compare(spec_a, samples_a, spec_b, samples_b,
            noise_floor_percent=DEFAULT_NOISE_FLOOR_PERCENT):
    """Differential verdict for two sample sets under equal controls."""
    if spec_a.controlled_fingerprint() != spec_b.controlled_fingerprint():
        raise ComparisonError(
            "controlled environments differ; samples are not comparable")
    if (isinstance(noise_floor_percent, bool)
            or not isinstance(noise_floor_percent, (int, float))
            or noise_floor_percent < 0):
        raise MalformedSpecError("noise_floor_percent must be >= 0")
    base = summarize(samples_a)
    cand = summarize(samples_b)
    if base["median"] <= 0:
        raise ComparisonError("baseline median must be > 0")
    shift = 100.0 * (cand["median"] - base["median"]) / base["median"]
    overlap = not (cand["ci95_high"] < base["ci95_low"]
                   or base["ci95_high"] < cand["ci95_low"])
    if overlap or abs(shift) <= float(noise_floor_percent):
        verdict = "inconclusive"
    elif shift < 0:
        verdict = "improvement"
    else:
        verdict = "regression"
    return {
        "schema": BENCH_SCHEMA,
        "workload_id": spec_a.workload_id,
        "controlled_fingerprint": spec_a.controlled_fingerprint(),
        "baseline": base,
        "candidate": cand,
        "median_shift_percent": shift,
        "ci_overlap": overlap,
        "noise_floor_percent": float(noise_floor_percent),
        "verdict": verdict,
    }


def report_from_samples(spec, baseline_samples, candidate_samples,
                        noise_floor_percent=DEFAULT_NOISE_FLOOR_PERCENT):
    """Deterministic report dict from recorded sample sets."""
    result = compare(spec, baseline_samples, spec, candidate_samples,
                     noise_floor_percent=noise_floor_percent)
    return {
        "schema": BENCH_SCHEMA,
        "workload_id": spec.workload_id,
        "spec": spec_as_dict(spec),
        "controlled_fingerprint": spec.controlled_fingerprint(),
        "baseline_samples": [float(s) for s in baseline_samples],
        "candidate_samples": [float(s) for s in candidate_samples],
        "comparison": result,
    }


def render_markdown(report):
    """Render a report dict deterministically (byte-stable output)."""
    comp = report["comparison"]
    base, cand = comp["baseline"], comp["candidate"]
    lines = [
        "# Benchmark report: " + report["workload_id"],
        "",
        "- schema: " + report["schema"],
        "- controlled fingerprint: " + report["controlled_fingerprint"],
        "- repetitions per side: %d" % base["n"],
        "- baseline median: %.6f" % base["median"],
        "- candidate median: %.6f" % cand["median"],
        "- baseline mean 95 percent CI: [%.6f, %.6f]"
        % (base["ci95_low"], base["ci95_high"]),
        "- candidate mean 95 percent CI: [%.6f, %.6f]"
        % (cand["ci95_low"], cand["ci95_high"]),
        "- median shift: %+.4f%%" % comp["median_shift_percent"],
        "- verdict: " + comp["verdict"],
        "",
        "Recorded samples only; no live run is claimed by this report.",
        "",
    ]
    return "\n".join(lines)


def load_sample_fixture(path):
    """Load and validate a recorded-samples fixture file.

    Fixture shape: {"schema": ..., "spec": {...},
    "baseline_samples": [...], "candidate_samples": [...]}.
    """
    text = Path(path).read_text(encoding="utf-8")
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise MalformedSpecError("fixture is not valid JSON") from exc
    if not isinstance(data, dict) or data.get("schema") != BENCH_SCHEMA:
        raise MalformedSpecError("fixture schema mismatch")
    spec = spec_from_dict(data.get("spec"))
    for name in ("baseline_samples", "candidate_samples"):
        vals = data.get(name)
        if not isinstance(vals, list):
            raise MalformedSpecError(name + " must be a list")
        summarize(vals)  # validates count, finiteness, sign
    return spec, data["baseline_samples"], data["candidate_samples"]


def measurement_as_dict(measurement):
    return {
        "schema": BENCH_SCHEMA,
        "spec": spec_as_dict(measurement.spec),
        "controlled_fingerprint":
            measurement.spec.controlled_fingerprint(),
        "observed_fingerprint": measurement.observed,
        "checksum": measurement.checksum,
        "samples": list(measurement.samples),
        "stats": measurement.stats,
    }
