# SPDX-License-Identifier: GPL-2.0-only
"""LIF-1501: experiment selection and repeated cross-device comparisons.

Phase P15 (advanced self-evolving experiments, roadmap Book IV).
Book IV states the P15 contract plainly: explore novel scheduler
policies, memory/resource tuning, storage behavior, hardware
inference acceleration, power optimizations and research task
allocation; each proposed improvement must beat an unchanged
baseline in replicated measurements; regressions and side effects
are tracked; a smaller reversible configuration optimization is
tried before a riskier kernel patch. The P15 test gate: at least
one improvement is independently reproducible across distinct
hardware and is no worse under predeclared safety, fairness,
energy and latency metrics.

This module is the fixture-level machinery for that contract:

- SELECTION: experiment proposals are validated data (closed
  category and approach sets, risk tier L0-L5, reversibility,
  named unchanged baseline, predeclared guard metrics). Eligible
  proposals are ordered deterministically: approach order first
  (config-optimization, then algorithm, then kernel-patch), then
  risk tier, then reversible before irreversible, then id. A
  kernel-patch proposal is not eligible until a config-optimization
  experiment in the same category has completed (the Book IV
  smaller-first rule), and nothing above the caller's risk cap is
  eligible. Selection never mutates anything; it names the next
  experiment to run in the lab.
- REPEATED CROSS-DEVICE COMPARISON: a device run is recorded
  samples only (baseline vs candidate under one experiment, on one
  device of one declared hardware class, with per-guard baseline
  and candidate penalty samples and a correctness state). Per-device
  verdicts use the P10 comparison discipline (median shift plus
  95 percent confidence-interval separation plus a declared noise
  floor; overlapping intervals or a shift inside the noise floor
  is inconclusive, never an improvement). The aggregate verdict
  follows the P13 no-false-consensus rule: improvement on one
  device and regression on another is CONTRADICTED, never averaged
  into a win; replicated-improvement requires improvement on at
  least two devices spanning at least two distinct hardware
  classes, no regression anywhere, and no guard regression on any
  device. A guard regression on any device blocks replication
  however fast the candidate is. Correctness failure on any device
  blocks replication too.
- Guard samples are penalty values where lower is better for all
  four predeclared metrics (safety incidents, fairness deviation,
  energy, latency), so "no worse" is one uniform rule. A declared
  guard with no recorded samples is UNMEASURED, never zero, and
  caps the aggregate below replicated (the P10 energy lesson).

Scope limits, stated plainly: recorded-sample / fixture level
only. This module runs no experiment, executes no workload, reads
no sensor and touches no device; it selects among proposals and
judges numbers the caller recorded elsewhere. A replicated
verdict here is a lab ordering over recorded fixtures (evidence
status: reproducer / fixture-tested), not proof on real hardware.

Offline guarantee: this module imports only standard-library
modules, reads no files, and performs no network, subprocess or
filesystem access of any kind (AST-pinned in the tests).
"""
from __future__ import annotations

import hashlib
import json
import platform
import math
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

EXPERIMENT_SCHEMA = "lifthrasir.experimentselection.v0.1"
EXPERIMENT_SCHEMA_VERSION = "0.1"
COMPARISON_SCHEMA = "lifthrasir.crossdevice.v0.1"
EVIDENCE_STATUS = "lab-verified"
TIMESTAMP_FORMAT = "%Y-%m-%dT%H:%M:%SZ"

CATEGORIES = ("scheduler-policy", "memory-tuning", "storage-behavior",
              "inference-acceleration", "power-optimization",
              "task-allocation")
APPROACHES = ("config-optimization", "algorithm", "kernel-patch")
APPROACH_ORDER = {name: i for i, name in enumerate(APPROACHES)}
RISK_TIERS = ("L0", "L1", "L2", "L3", "L4", "L5")
RISK_ORDER = {name: i for i, name in enumerate(RISK_TIERS)}
GUARD_METRICS = ("safety", "fairness", "energy", "latency")
VERDICTS = ("improvement", "regression", "inconclusive")
COMPARISON_VERDICTS = ("replicated-improvement", "replicated-regression",
                       "contradicted", "guard-regression",
                       "correctness-failure", "single-device",
                       "insufficient-replication", "inconclusive")
CORRECTNESS_STATES = ("pass", "fail", "not-run")
UNMEASURED = "unmeasured"
MIN_REPETITIONS = 3
MIN_DEVICES = 2
MIN_HARDWARE_CLASSES = 2
MAX_PROPOSALS = 64
MAX_RUNS = 128
MAX_SAMPLES = 1000
MAX_GUARDS = 4
DEFAULT_NOISE_FLOOR_PERCENT = 1.0
DEFAULT_MAX_RISK_TIER = "L3"

_ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{2,63}$")
_DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")
_INCIDENT_RE = re.compile(r"^inc-[a-z0-9-]+$")

_PROPOSAL_FIELDS = {"schema", "experiment_id", "title", "category",
                    "approach", "risk_tier", "reversible", "baseline_id",
                    "workload_id", "guard_metrics", "hypothesis"}
_RUN_FIELDS = {"schema", "experiment_id", "device_id", "hardware_class",
               "baseline_samples", "candidate_samples", "guards",
               "correctness"}
_GUARD_FIELDS = {"baseline", "candidate"}


class ExperimentError(Exception):
    """Base class for all experiment-selection refusals."""


class MalformedProposalError(ExperimentError):
    """An experiment proposal is malformed."""


class MalformedRunError(ExperimentError):
    """A device run or comparison input is malformed."""


class DuplicateExperimentError(ExperimentError):
    """Two proposals or two runs claim the same identity."""


class UnknownExperimentError(ExperimentError):
    """A run or lookup names an experiment that was not proposed."""


class IncomparableRunError(ExperimentError):
    """Runs cannot be compared (mismatched experiment or device)."""


def _is_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _check_id(value: Any, name: str, exc: type) -> str:
    if not isinstance(value, str) or not _ID_RE.match(value):
        raise exc(f"{name} must match [a-z0-9][a-z0-9._-]{{2,63}}")
    return value


def _check_text(value: Any, name: str, exc: type, max_len: int = 512) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > max_len:
        raise exc(f"{name} must be a non-empty string of at most {max_len} chars")
    return value


def _check_timestamp(value: Any, name: str, exc: type) -> str:
    if not isinstance(value, str):
        raise exc(f"{name} must be a timestamp string")
    try:
        datetime.strptime(value, TIMESTAMP_FORMAT)
    except ValueError:
        raise exc(f"{name} must match {TIMESTAMP_FORMAT}") from None
    return value


def _check_samples(value: Any, name: str, exc: type) -> Tuple[float, ...]:
    if not isinstance(value, (list, tuple)) or not value:
        raise exc(f"{name} must be a non-empty list of numbers")
    if len(value) > MAX_SAMPLES:
        raise exc(f"{name} exceeds MAX_SAMPLES={MAX_SAMPLES}")
    out: List[float] = []
    for item in value:
        if isinstance(item, bool) or not isinstance(item, (int, float)):
            raise exc(f"{name} samples must be numbers")
        number = float(item)
        if not math.isfinite(number) or number < 0:
            raise exc(f"{name} samples must be finite and >= 0")
        out.append(number)
    return tuple(out)


def _check_percent(value: Any, name: str, exc: type) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise exc(f"{name} must be a number")
    number = float(value)
    if not math.isfinite(number) or number < 0 or number > 100:
        raise exc(f"{name} must be finite and within 0..100")
    return number


def canonical_json(payload: Any) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=True)


def content_digest_for(payload: Any) -> str:
    return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()


# ---------------------------------------------------------------- proposals

@dataclass(frozen=True)
class ExperimentProposal:
    experiment_id: str
    title: str
    category: str
    approach: str
    risk_tier: str
    reversible: bool
    baseline_id: str
    workload_id: str
    guard_metrics: Tuple[str, ...]
    hypothesis: str

    def __post_init__(self) -> None:
        exc = MalformedProposalError
        _check_id(self.experiment_id, "experiment_id", exc)
        _check_text(self.title, "title", exc, 256)
        if self.category not in CATEGORIES:
            raise exc(f"category must be one of {CATEGORIES}")
        if self.approach not in APPROACHES:
            raise exc(f"approach must be one of {APPROACHES}")
        if self.risk_tier not in RISK_TIERS:
            raise exc(f"risk_tier must be one of {RISK_TIERS}")
        if not isinstance(self.reversible, bool):
            raise exc("reversible must be a bool")
        _check_id(self.baseline_id, "baseline_id", exc)
        _check_id(self.workload_id, "workload_id", exc)
        guards = tuple(self.guard_metrics)
        if len(guards) > MAX_GUARDS or len(set(guards)) != len(guards):
            raise exc("guard_metrics must be unique and at most MAX_GUARDS")
        for metric in guards:
            if metric not in GUARD_METRICS:
                raise exc(f"guard metric must be one of {GUARD_METRICS}")
        object.__setattr__(self, "guard_metrics", guards)
        _check_text(self.hypothesis, "hypothesis", exc)


def proposal_as_dict(proposal: ExperimentProposal) -> Dict[str, Any]:
    if not isinstance(proposal, ExperimentProposal):
        raise MalformedProposalError("proposal must be an ExperimentProposal")
    return {"schema": EXPERIMENT_SCHEMA,
            "experiment_id": proposal.experiment_id,
            "title": proposal.title, "category": proposal.category,
            "approach": proposal.approach, "risk_tier": proposal.risk_tier,
            "reversible": proposal.reversible,
            "baseline_id": proposal.baseline_id,
            "workload_id": proposal.workload_id,
            "guard_metrics": list(proposal.guard_metrics),
            "hypothesis": proposal.hypothesis}


def proposal_from_dict(payload: Any) -> ExperimentProposal:
    exc = MalformedProposalError
    if not isinstance(payload, Mapping):
        raise exc("proposal must be an object")
    if set(payload) != _PROPOSAL_FIELDS:
        raise exc(f"proposal fields must be exactly {sorted(_PROPOSAL_FIELDS)}")
    if payload["schema"] != EXPERIMENT_SCHEMA:
        raise exc(f"schema must be {EXPERIMENT_SCHEMA}")
    if not isinstance(payload["guard_metrics"], list):
        raise exc("guard_metrics must be a list")
    return ExperimentProposal(
        experiment_id=payload["experiment_id"], title=payload["title"],
        category=payload["category"], approach=payload["approach"],
        risk_tier=payload["risk_tier"], reversible=payload["reversible"],
        baseline_id=payload["baseline_id"], workload_id=payload["workload_id"],
        guard_metrics=tuple(payload["guard_metrics"]),
        hypothesis=payload["hypothesis"])


def proposal_digest(proposal: ExperimentProposal) -> str:
    return content_digest_for(proposal_as_dict(proposal))


# ---------------------------------------------------------------- statistics

def summarize_samples(samples: Sequence[float]) -> Dict[str, Any]:
    values = sorted(float(v) for v in samples)
    n = len(values)
    mean = sum(values) / n
    mid = n // 2
    median = values[mid] if n % 2 else (values[mid - 1] + values[mid]) / 2.0
    if n > 1:
        variance = sum((v - mean) ** 2 for v in values) / (n - 1)
        sd = math.sqrt(variance)
    else:
        sd = 0.0
    half = 1.96 * sd / math.sqrt(n) if n else 0.0
    return {"n": n, "min": values[0], "max": values[-1], "mean": mean,
            "median": median, "sd": sd,
            "ci95_low": mean - half, "ci95_high": mean + half}


def verdict_for_pair(baseline: Sequence[float], candidate: Sequence[float],
                     noise_floor_percent: float = DEFAULT_NOISE_FLOOR_PERCENT
                     ) -> Dict[str, Any]:
    """P10 discipline: median shift + CI separation + noise floor."""
    noise = _check_percent(noise_floor_percent, "noise_floor_percent",
                           MalformedRunError)
    base = summarize_samples(baseline)
    cand = summarize_samples(candidate)
    if base["median"] <= 0:
        raise MalformedRunError("baseline median must be > 0 to compare")
    shift = (cand["median"] - base["median"]) / base["median"] * 100.0
    overlap = not (cand["ci95_high"] < base["ci95_low"]
                   or base["ci95_high"] < cand["ci95_low"])
    if shift < -noise and not overlap and cand["ci95_high"] < base["ci95_low"]:
        verdict = "improvement"
    elif shift > noise and not overlap and base["ci95_high"] < cand["ci95_low"]:
        verdict = "regression"
    else:
        verdict = "inconclusive"
    return {"verdict": verdict, "median_shift_percent": shift,
            "ci_overlap": overlap, "noise_floor_percent": noise,
            "baseline": base, "candidate": cand}


# ---------------------------------------------------------------- device runs

@dataclass(frozen=True)
class DeviceRun:
    experiment_id: str
    device_id: str
    hardware_class: str
    baseline_samples: Tuple[float, ...]
    candidate_samples: Tuple[float, ...]
    guards: Tuple[Tuple[str, Tuple[float, ...], Tuple[float, ...]], ...]
    correctness: str

    def __post_init__(self) -> None:
        exc = MalformedRunError
        _check_id(self.experiment_id, "experiment_id", exc)
        _check_id(self.device_id, "device_id", exc)
        _check_id(self.hardware_class, "hardware_class", exc)
        base = _check_samples(self.baseline_samples, "baseline_samples", exc)
        cand = _check_samples(self.candidate_samples, "candidate_samples", exc)
        if len(base) < MIN_REPETITIONS or len(cand) < MIN_REPETITIONS:
            raise exc(f"runs need at least {MIN_REPETITIONS} repetitions per side")
        object.__setattr__(self, "baseline_samples", base)
        object.__setattr__(self, "candidate_samples", cand)
        seen = set()
        normalized = []
        for entry in self.guards:
            if not isinstance(entry, (list, tuple)) or len(entry) != 3:
                raise exc("guards entries must be (metric, baseline, candidate)")
            metric, gbase, gcand = entry
            if metric not in GUARD_METRICS:
                raise exc(f"guard metric must be one of {GUARD_METRICS}")
            if metric in seen:
                raise exc(f"duplicate guard metric {metric}")
            seen.add(metric)
            normalized.append((metric,
                               _check_samples(gbase, f"guards.{metric}.baseline", exc),
                               _check_samples(gcand, f"guards.{metric}.candidate", exc)))
        object.__setattr__(self, "guards", tuple(normalized))
        if self.correctness not in CORRECTNESS_STATES:
            raise exc(f"correctness must be one of {CORRECTNESS_STATES}")

    def guard_map(self) -> Dict[str, Tuple[Tuple[float, ...], Tuple[float, ...]]]:
        return {m: (b, c) for m, b, c in self.guards}


def run_as_dict(run: DeviceRun) -> Dict[str, Any]:
    if not isinstance(run, DeviceRun):
        raise MalformedRunError("run must be a DeviceRun")
    return {"schema": EXPERIMENT_SCHEMA, "experiment_id": run.experiment_id,
            "device_id": run.device_id, "hardware_class": run.hardware_class,
            "baseline_samples": list(run.baseline_samples),
            "candidate_samples": list(run.candidate_samples),
            "guards": {m: {"baseline": list(b), "candidate": list(c)}
                       for m, b, c in run.guards},
            "correctness": run.correctness}


def run_from_dict(payload: Any) -> DeviceRun:
    exc = MalformedRunError
    if not isinstance(payload, Mapping):
        raise exc("run must be an object")
    if set(payload) != _RUN_FIELDS:
        raise exc(f"run fields must be exactly {sorted(_RUN_FIELDS)}")
    if payload["schema"] != EXPERIMENT_SCHEMA:
        raise exc(f"schema must be {EXPERIMENT_SCHEMA}")
    guards_payload = payload["guards"]
    if not isinstance(guards_payload, Mapping):
        raise exc("guards must be an object")
    guards = []
    for metric in sorted(guards_payload):
        entry = guards_payload[metric]
        if not isinstance(entry, Mapping) or set(entry) != _GUARD_FIELDS:
            raise exc(f"guards.{metric} fields must be exactly baseline/candidate")
        guards.append((metric, entry["baseline"], entry["candidate"]))
    return DeviceRun(experiment_id=payload["experiment_id"],
                     device_id=payload["device_id"],
                     hardware_class=payload["hardware_class"],
                     baseline_samples=payload["baseline_samples"],
                     candidate_samples=payload["candidate_samples"],
                     guards=tuple(guards), correctness=payload["correctness"])


# ---------------------------------------------------------------- selection

def _index_proposals(proposals: Sequence[ExperimentProposal]
                     ) -> Dict[str, ExperimentProposal]:
    if len(proposals) > MAX_PROPOSALS:
        raise MalformedProposalError(f"at most {MAX_PROPOSALS} proposals")
    indexed: Dict[str, ExperimentProposal] = {}
    for proposal in proposals:
        if not isinstance(proposal, ExperimentProposal):
            raise MalformedProposalError("proposals must be ExperimentProposal")
        if proposal.experiment_id in indexed:
            raise DuplicateExperimentError(
                f"duplicate experiment_id {proposal.experiment_id}")
        indexed[proposal.experiment_id] = proposal
    return indexed


def selection_key(proposal: ExperimentProposal) -> Tuple[int, int, int, str]:
    return (APPROACH_ORDER[proposal.approach], RISK_ORDER[proposal.risk_tier],
            0 if proposal.reversible else 1, proposal.experiment_id)


def eligible_proposals(proposals: Sequence[ExperimentProposal],
                       completed_ids: Sequence[str] = (),
                       max_risk_tier: str = DEFAULT_MAX_RISK_TIER
                       ) -> List[ExperimentProposal]:
    """Deterministic Book IV order over the eligible subset.

    Kernel-patch proposals are held back until a config-optimization
    experiment in the same category has completed (smaller first).
    """
    if max_risk_tier not in RISK_TIERS:
        raise MalformedProposalError(f"max_risk_tier must be one of {RISK_TIERS}")
    indexed = _index_proposals(proposals)
    completed = set(completed_ids)
    for done in completed:
        if done not in indexed:
            raise UnknownExperimentError(f"completed id {done} was not proposed")
    config_done = {indexed[d].category for d in completed
                   if indexed[d].approach == "config-optimization"}
    cap = RISK_ORDER[max_risk_tier]
    eligible = []
    for proposal in indexed.values():
        if proposal.experiment_id in completed:
            continue
        if RISK_ORDER[proposal.risk_tier] > cap:
            continue
        if (proposal.approach == "kernel-patch"
                and proposal.category not in config_done):
            continue
        eligible.append(proposal)
    return sorted(eligible, key=selection_key)


def selection_plan(proposals: Sequence[ExperimentProposal],
                   completed_ids: Sequence[str] = (),
                   max_risk_tier: str = DEFAULT_MAX_RISK_TIER) -> List[str]:
    return [p.experiment_id for p in eligible_proposals(
        proposals, completed_ids, max_risk_tier)]


def select_next_experiment(proposals: Sequence[ExperimentProposal],
                           completed_ids: Sequence[str] = (),
                           max_risk_tier: str = DEFAULT_MAX_RISK_TIER
                           ) -> Optional[ExperimentProposal]:
    plan = eligible_proposals(proposals, completed_ids, max_risk_tier)
    return plan[0] if plan else None


# ---------------------------------------------------------------- comparison

def compare_across_devices(proposal: ExperimentProposal,
                           runs: Sequence[DeviceRun],
                           noise_floor_percent: float = DEFAULT_NOISE_FLOOR_PERCENT
                           ) -> Dict[str, Any]:
    if not isinstance(proposal, ExperimentProposal):
        raise MalformedProposalError("proposal must be an ExperimentProposal")
    noise = _check_percent(noise_floor_percent, "noise_floor_percent",
                           MalformedRunError)
    if not runs:
        raise MalformedRunError("at least one device run is required")
    if len(runs) > MAX_RUNS:
        raise MalformedRunError(f"at most {MAX_RUNS} runs")
    devices: Dict[str, DeviceRun] = {}
    for run in runs:
        if not isinstance(run, DeviceRun):
            raise MalformedRunError("runs must be DeviceRun")
        if run.experiment_id != proposal.experiment_id:
            raise IncomparableRunError(
                f"run on {run.device_id} names {run.experiment_id}, "
                f"not {proposal.experiment_id}")
        if run.device_id in devices:
            raise DuplicateExperimentError(
                f"duplicate run for device {run.device_id}")
        devices[run.device_id] = run
    per_device: List[Dict[str, Any]] = []
    for device_id in sorted(devices):
        run = devices[device_id]
        primary = verdict_for_pair(run.baseline_samples, run.candidate_samples,
                                   noise)
        guard_map = run.guard_map()
        guard_results: Dict[str, Any] = {}
        for metric in proposal.guard_metrics:
            if metric not in guard_map:
                guard_results[metric] = {"verdict": UNMEASURED}
            else:
                gbase, gcand = guard_map[metric]
                guard_results[metric] = verdict_for_pair(gbase, gcand, noise)
        for metric in guard_map:
            if metric not in guard_results:
                raise MalformedRunError(
                    f"run on {device_id} records undeclared guard {metric}")
        per_device.append({
            "device_id": device_id, "hardware_class": run.hardware_class,
            "correctness": run.correctness, "primary": primary,
            "guards": guard_results,
            "repetitions": len(run.baseline_samples)})
    verdicts = [d["primary"]["verdict"] for d in per_device]
    hardware = sorted({d["hardware_class"] for d in per_device})
    guard_regressed = any(g.get("verdict") == "regression"
                          for d in per_device for g in d["guards"].values())
    guard_unmeasured = any(g.get("verdict") == UNMEASURED
                           for d in per_device for g in d["guards"].values())
    correctness_failed = any(d["correctness"] != "pass" for d in per_device)
    improvements = verdicts.count("improvement")
    regressions = verdicts.count("regression")
    if correctness_failed:
        verdict = "correctness-failure"
    elif improvements and regressions:
        verdict = "contradicted"
    elif guard_regressed:
        verdict = "guard-regression"
    elif improvements >= MIN_DEVICES and len(hardware) >= MIN_HARDWARE_CLASSES \
            and not guard_unmeasured:
        verdict = "replicated-improvement"
    elif regressions >= MIN_DEVICES and len(hardware) >= MIN_HARDWARE_CLASSES:
        verdict = "replicated-regression"
    elif len(per_device) < MIN_DEVICES:
        verdict = "single-device"
    elif improvements or regressions:
        verdict = "insufficient-replication"
    else:
        verdict = "inconclusive"
    report: Dict[str, Any] = {
        "schema": COMPARISON_SCHEMA,
        "experiment_id": proposal.experiment_id,
        "baseline_id": proposal.baseline_id,
        "workload_id": proposal.workload_id,
        "proposal_digest": proposal_digest(proposal),
        "noise_floor_percent": noise,
        "device_count": len(per_device),
        "hardware_classes": hardware,
        "devices": per_device,
        "guard_regression": guard_regressed,
        "guard_unmeasured": guard_unmeasured,
        "verdict": verdict}
    report["content_digest"] = content_digest_for(report)
    return report


_REPORT_FIELDS = {"schema", "experiment_id", "baseline_id", "workload_id",
                  "proposal_digest", "noise_floor_percent", "device_count",
                  "hardware_classes", "devices", "guard_regression",
                  "guard_unmeasured", "verdict", "content_digest"}


def validate_comparison_report(report: Any, proposal: ExperimentProposal,
                               runs: Sequence[DeviceRun]) -> Dict[str, Any]:
    if not isinstance(report, Mapping):
        raise MalformedRunError("report must be an object")
    if set(report) != _REPORT_FIELDS:
        raise MalformedRunError(f"report fields must be exactly {sorted(_REPORT_FIELDS)}")
    if report["schema"] != COMPARISON_SCHEMA:
        raise MalformedRunError(f"schema must be {COMPARISON_SCHEMA}")
    if report["verdict"] not in COMPARISON_VERDICTS:
        raise MalformedRunError("verdict is not a comparison verdict")
    digest = report["content_digest"]
    if not isinstance(digest, str) or not _DIGEST_RE.match(digest):
        raise MalformedRunError("content_digest must be a sha256 hex digest")
    body = {k: v for k, v in report.items() if k != "content_digest"}
    if content_digest_for(body) != digest:
        raise MalformedRunError("content_digest does not match report body")
    recomputed = compare_across_devices(proposal, runs,
                                        report["noise_floor_percent"])
    if recomputed != dict(report):
        raise MalformedRunError("report does not match recomputation from runs")
    return dict(report)


def comparison_as_dict(report: Mapping[str, Any]) -> Dict[str, Any]:
    return json.loads(canonical_json(dict(report)))


# ---------------------------------------------------------------- evidence

def build_evidence_record(report: Mapping[str, Any], *,
                          recorded_at: str, incident_id: str,
                          host_local_id: str = "lab-guest-01"
                          ) -> Dict[str, Any]:
    """Render a comparison report as a LIF-0004 v0.1 evidence record."""
    _check_timestamp(recorded_at, "recorded_at", MalformedRunError)
    if not isinstance(incident_id, str) or not _INCIDENT_RE.match(incident_id):
        raise MalformedRunError("incident_id must match inc-[a-z0-9-]+")
    if not isinstance(report, Mapping) or "content_digest" not in report:
        raise MalformedRunError("report must be a comparison report")
    digest = str(report["content_digest"])
    return {"schema": "lifthrasir.evidence.v0.1",
            "schema_version": EXPERIMENT_SCHEMA_VERSION,
            "evidence_id": f"ev-expselect-{digest[:12]}",
            "incident_id": incident_id,
            "kind": "test-run",
            "recorded_at": recorded_at,
            "source": {"component": "lab", "host_local_id": host_local_id},
            "summary": (f"cross-device comparison {report['experiment_id']}: "
                        f"verdict {report['verdict']} over "
                        f"{report['device_count']} device(s), hardware "
                        f"{', '.join(report['hardware_classes'])}"),
            "content_digest": f"sha256:{digest}",
            "evidence_status": EVIDENCE_STATUS,
            "tool_versions": {"python": platform.python_version(),
                               "lifthrasir-experimentselection": EXPERIMENT_SCHEMA_VERSION},
            "limitations": [
                "fixture/lab scope: recorded samples only; no experiment "
                "was executed and no device was touched by this slice",
                "evidence status lab-verified (fixture level, one "
                "machine); not cross-platform-verified, not human-reviewed"],
            "artifact_refs": []}
