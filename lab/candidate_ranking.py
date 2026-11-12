# SPDX-License-Identifier: GPL-2.0-only
"""LIF-1003: candidate ranking with regressions and energy tracked.

Phase P10 (optimization science). This slice is the consumer of the
LIF-1001 benchmark harness: where LIF-1001 compares ONE candidate
against a baseline under a controlled environment, this module
ranks MANY candidates against a named baseline, tracking for each
candidate (a) the primary-workload verdict, (b) regressions on
declared guard workloads, and (c) recorded energy samples -- the
three things roadmap Book III (P10, benchmark science) demands be
reported together: p50/p95, variance, energy and regressions, with
no cherry-picking. Book III's warning is a ranking rule here: a
speed improvement that increases power use may be a net regression,
so a candidate whose recorded energy regresses beyond the declared
budget is rejected however fast it is.

Master roadmap section 5 is the honesty contract: a claimed
improvement needs its comparison baseline, its repetitions and its
noise handling. Every verdict in this module is produced by the
LIF-1001 comparison rules (median shift plus 95 percent confidence
interval overlap plus a declared noise floor) applied to recorded
samples measured under one controlled fingerprint. Overlapping
intervals or a shift inside the noise floor is inconclusive, never
an improvement. Energy that was not recorded stays UNMEASURED --
never zero, never estimated, never invented -- and an unmeasured
energy track caps a candidate below the recommended status,
because the P10 gate requires improvements to be validated with
power controls.

Independence from LIF-1002: workload profiles are LIF-1002 and are
NOT required here. This module consumes plain recorded sample
lists in the LIF-1001 fixture shape (a harness spec dict plus
sample lists) and declares its workloads by id only. If LIF-1002
later names profiles for these ids, the recorded samples ranked
here remain valid inputs; no interface from unbanked LIF-1002 code
is imported or assumed.

Home justification (master roadmap section 3, following the
LIF-1001 precedent): measurement and ranking tooling for the rapid
lab lives in lab/ until its contracts stabilize. Nothing here
belongs in src/lifthrasir/ yet, so no package export union is
needed for this slice.

Scope limits, stated plainly: recorded-sample / fixture level
only. This module performs no live benchmark run, no live power
reading and no workload execution of any kind; it ranks numbers
the caller recorded elsewhere, under controls the caller declared
in the LIF-1001 spec. The provenance and measurement tool of the
energy samples are the caller's responsibility and are not
verified here. Ranking output is a deterministic lab ordering
(evidence status: reproducer / fixture-tested), not a deployment
recommendation for any host.

Offline guarantee: this module imports only standard-library
modules plus the first-party LIF-1001 harness (lab.benchmark_
harness, itself stdlib-only), reads only files it is explicitly
given, and performs no network access of any kind.
"""
from __future__ import annotations

import json
import math
from pathlib import Path

from lab.benchmark_harness import (
    DEFAULT_NOISE_FLOOR_PERCENT, BenchmarkError, compare as _bench_compare,
    spec_as_dict, spec_from_dict, summarize)

RANK_SCHEMA = "lifthrasir.ranking.v0.1"
RANK_SCHEMA_VERSION = "0.1"
UNMEASURED = "unmeasured"
CORRECTNESS_STATES = ("pass", "fail", "not-run")
STATUSES = ("recommended", "acceptable", "incomplete", "rejected")
_STATUS_ORDER = {name: i for i, name in enumerate(STATUSES)}
DEFAULT_ENERGY_NOISE_FLOOR_PERCENT = DEFAULT_NOISE_FLOOR_PERCENT
DEFAULT_MAX_ENERGY_REGRESSION_PERCENT = 5.0
MAX_CANDIDATES = 64
MAX_GUARDS = 16

_TOP_FIELDS = {"schema", "spec", "noise_floor_percent",
               "energy_noise_floor_percent",
               "max_energy_regression_percent", "baseline",
               "candidates", "guards"}
_ENTRY_FIELDS = {"candidate_id", "time_samples", "energy_samples",
                 "correctness"}
_GUARD_FIELDS = {"spec", "baseline_samples", "candidate_samples"}


class RankingError(Exception):
    """Base class for all candidate-ranking refusals."""


class MalformedRankingError(RankingError):
    """The ranking input is malformed or not comparable."""


def _fail(message):
    raise MalformedRankingError(message)


def _check_percent(value, name):
    if (isinstance(value, bool) or not isinstance(value, (int, float))
            or not math.isfinite(float(value)) or float(value) < 0):
        _fail(name + " must be a finite number >= 0")
    return float(value)


def _summarize(samples, name):
    if not isinstance(samples, list):
        _fail(name + " must be a list of recorded samples")
    try:
        return summarize(samples)
    except BenchmarkError as exc:
        raise MalformedRankingError(name + ": " + str(exc)) from exc


def _compare(spec, base_samples, cand_samples, noise_floor, name):
    try:
        return _bench_compare(spec, base_samples, spec, cand_samples,
                              noise_floor_percent=noise_floor)
    except BenchmarkError as exc:
        raise MalformedRankingError(name + ": " + str(exc)) from exc


def _entry_from_dict(data, role):
    if not isinstance(data, dict):
        _fail(role + " must be a dict")
    extra = set(data) - _ENTRY_FIELDS
    if extra:
        _fail(role + " has unknown fields: " + ", ".join(sorted(extra)))
    cid = data.get("candidate_id")
    if not isinstance(cid, str) or not cid:
        _fail(role + " candidate_id must be a non-empty string")
    correctness = data.get("correctness", "not-run")
    if correctness not in CORRECTNESS_STATES:
        _fail(role + " correctness must be one of "
              + "/".join(CORRECTNESS_STATES))
    if "time_samples" not in data:
        _fail(role + " time_samples is required")
    time_stats = _summarize(data["time_samples"], role + " time_samples")
    energy_samples = data.get("energy_samples")
    energy_stats = None
    if energy_samples is not None:
        energy_stats = _summarize(energy_samples,
                                  role + " energy_samples")
    return {"candidate_id": cid, "correctness": correctness,
            "time_samples": data["time_samples"],
            "time_stats": time_stats,
            "energy_samples": energy_samples,
            "energy_stats": energy_stats}


def _guard_from_dict(data, index, candidate_ids):
    role = "guards[%d]" % index
    if not isinstance(data, dict):
        _fail(role + " must be a dict")
    extra = set(data) - _GUARD_FIELDS
    if extra:
        _fail(role + " has unknown fields: " + ", ".join(sorted(extra)))
    if "spec" not in data or "baseline_samples" not in data:
        _fail(role + " needs spec and baseline_samples")
    try:
        spec = spec_from_dict(data["spec"])
    except BenchmarkError as exc:
        raise MalformedRankingError(role + " spec: " + str(exc)) from exc
    _summarize(data["baseline_samples"], role + " baseline_samples")
    cand_samples = data.get("candidate_samples", {})
    if not isinstance(cand_samples, dict):
        _fail(role + " candidate_samples must be a dict by candidate id")
    for cid, samples in cand_samples.items():
        if cid not in candidate_ids:
            _fail(role + " names unknown candidate: " + repr(cid))
        _summarize(samples, role + " samples for " + cid)
    return {"spec": spec, "workload_id": spec.workload_id,
            "baseline_samples": data["baseline_samples"],
            "candidate_samples": cand_samples}


def _assess(entry, baseline, spec, guards, noise_floor, energy_floor,
            energy_budget):
    cid = entry["candidate_id"]
    primary = _compare(spec, baseline["time_samples"],
                       entry["time_samples"], noise_floor,
                       cid + " primary comparison")
    regressions = []
    notes = []
    if primary["verdict"] == "regression":
        regressions.append("primary-regression")
    if entry["correctness"] == "fail":
        regressions.append("correctness-fail")
    elif entry["correctness"] == "not-run":
        notes.append("correctness-not-run")
    # Energy track: lower recorded energy is better (same verdict
    # rules as time). Unmeasured stays unmeasured, never zero.
    if entry["energy_samples"] is None:
        energy = {"status": UNMEASURED, "verdict": UNMEASURED,
                  "median_shift_percent": None,
                  "candidate_median": None, "baseline_median": None}
        notes.append("energy-unmeasured")
    else:
        eres = _compare(spec, baseline["energy_samples"],
                        entry["energy_samples"], energy_floor,
                        cid + " energy comparison")
        energy = {"status": "measured", "verdict": eres["verdict"],
                  "median_shift_percent": eres["median_shift_percent"],
                  "candidate_median": eres["candidate"]["median"],
                  "baseline_median": eres["baseline"]["median"]}
        if eres["verdict"] == "regression":
            if eres["median_shift_percent"] > energy_budget:
                regressions.append("energy-regression")
            else:
                notes.append("energy-cost-within-budget:%+.4f%%"
                             % eres["median_shift_percent"])
    guard_results = []
    guard_missing = False
    for guard in guards:
        samples = guard["candidate_samples"].get(cid)
        if samples is None:
            guard_missing = True
            guard_results.append(
                {"workload_id": guard["workload_id"],
                 "verdict": "not-measured",
                 "median_shift_percent": None})
            notes.append("guard-not-measured:" + guard["workload_id"])
            continue
        gres = _compare(guard["spec"], guard["baseline_samples"],
                        samples, noise_floor,
                        cid + " guard " + guard["workload_id"])
        guard_results.append(
            {"workload_id": guard["workload_id"],
             "verdict": gres["verdict"],
             "median_shift_percent": gres["median_shift_percent"]})
        if gres["verdict"] == "regression":
            regressions.append("guard-regression:"
                                 + guard["workload_id"])
    if regressions:
        status = "rejected"
    elif entry["correctness"] != "pass" or guard_missing:
        status = "incomplete"
    elif (primary["verdict"] == "improvement"
            and energy["status"] == "measured"):
        status = "recommended"
    else:
        status = "acceptable"
    return {
        "candidate_id": cid, "status": status,
        "correctness": entry["correctness"],
        "primary": {"verdict": primary["verdict"],
                    "median_shift_percent":
                        primary["median_shift_percent"],
                    "ci_overlap": primary["ci_overlap"],
                    "baseline_median": primary["baseline"]["median"],
                    "candidate_median": primary["candidate"]["median"],
                    "candidate_p95": primary["candidate"]["p95"],
                    "candidate_stdev": primary["candidate"]["stdev"]},
        "energy": energy, "guards": guard_results,
        "regressions": regressions, "notes": notes}


def ranking_from_dict(data):
    """Rank recorded candidates against the baseline; return report."""
    if not isinstance(data, dict):
        _fail("ranking input must be a dict")
    extra = set(data) - _TOP_FIELDS
    if extra:
        _fail("unknown ranking fields: " + ", ".join(sorted(extra)))
    if data.get("schema") != RANK_SCHEMA:
        _fail("schema must be " + RANK_SCHEMA)
    if "spec" not in data:
        _fail("spec is required (the LIF-1001 controlled environment)")
    try:
        spec = spec_from_dict(data["spec"])
    except BenchmarkError as exc:
        raise MalformedRankingError("spec: " + str(exc)) from exc
    noise_floor = _check_percent(
        data.get("noise_floor_percent", DEFAULT_NOISE_FLOOR_PERCENT),
        "noise_floor_percent")
    energy_floor = _check_percent(
        data.get("energy_noise_floor_percent",
                 DEFAULT_ENERGY_NOISE_FLOOR_PERCENT),
        "energy_noise_floor_percent")
    energy_budget = _check_percent(
        data.get("max_energy_regression_percent",
                 DEFAULT_MAX_ENERGY_REGRESSION_PERCENT),
        "max_energy_regression_percent")
    if "baseline" not in data:
        _fail("baseline is required: every claim names its baseline")
    baseline = _entry_from_dict(data["baseline"], "baseline")
    raw_candidates = data.get("candidates")
    if (not isinstance(raw_candidates, list) or not raw_candidates
            or len(raw_candidates) > MAX_CANDIDATES):
        _fail("candidates must be a list of 1..%d entries"
              % MAX_CANDIDATES)
    entries = []
    seen = {baseline["candidate_id"]}
    for i, raw in enumerate(raw_candidates):
        entry = _entry_from_dict(raw, "candidates[%d]" % i)
        if entry["candidate_id"] in seen:
            _fail("duplicate candidate_id: " + entry["candidate_id"])
        seen.add(entry["candidate_id"])
        if (baseline["energy_samples"] is None
                and entry["energy_samples"] is not None):
            _fail(entry["candidate_id"] + " has energy samples but "
                  "the baseline has none; energy is not comparable")
        entries.append(entry)
    raw_guards = data.get("guards", [])
    if not isinstance(raw_guards, list) or len(raw_guards) > MAX_GUARDS:
        _fail("guards must be a list of at most %d entries" % MAX_GUARDS)
    guards = [_guard_from_dict(g, i, seen - {baseline["candidate_id"]})
              for i, g in enumerate(raw_guards)]
    assessed = [_assess(e, baseline, spec, guards, noise_floor,
                        energy_floor, energy_budget) for e in entries]
    assessed.sort(key=lambda a: (
        _STATUS_ORDER[a["status"]],
        a["primary"]["median_shift_percent"],
        (a["energy"]["median_shift_percent"]
         if a["energy"]["median_shift_percent"] is not None
         else math.inf),
        a["candidate_id"]))
    for rank, item in enumerate(assessed, start=1):
        item["rank"] = rank
    baseline_energy = UNMEASURED
    if baseline["energy_stats"] is not None:
        baseline_energy = baseline["energy_stats"]
    return {
        "schema": RANK_SCHEMA,
        "workload_id": spec.workload_id,
        "spec": spec_as_dict(spec),
        "controlled_fingerprint": spec.controlled_fingerprint(),
        "noise_floor_percent": noise_floor,
        "energy_noise_floor_percent": energy_floor,
        "max_energy_regression_percent": energy_budget,
        "baseline": {"candidate_id": baseline["candidate_id"],
                     "correctness": baseline["correctness"],
                     "time": baseline["time_stats"],
                     "energy": baseline_energy},
        "guards": [{"workload_id": g["workload_id"],
                    "controlled_fingerprint":
                        g["spec"].controlled_fingerprint()}
                   for g in guards],
        "candidates": assessed,
        "method": ("LIF-1001 comparison rules per candidate against "
                   "the named baseline under one controlled "
                   "fingerprint; status precedence: any tracked "
                   "regression or correctness failure rejects, "
                   "missing guard data or un-run correctness is "
                   "incomplete, a primary improvement with measured "
                   "in-budget energy is recommended, everything "
                   "else is acceptable; ordering is by status, "
                   "primary median shift, energy median shift, "
                   "then candidate id."),
        "limitations": [
            "Recorded samples only: no live run or live power "
            "reading is performed or claimed by this module.",
            "Energy figures are caller-recorded samples as "
            "supplied; their measurement tool and provenance are "
            "the caller's responsibility and are not verified here.",
            "Only the primary workload and the declared guard "
            "workloads are tracked; undeclared workloads are not.",
            "This ranking is a lab ordering (fixture-tested), "
            "not a deployment recommendation for any host.",
        ],
    }


def load_ranking_fixture(path):
    """Load a recorded ranking fixture file and return its report."""
    text = Path(path).read_text(encoding="utf-8")
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise MalformedRankingError(
            "fixture is not valid JSON") from exc
    return ranking_from_dict(data)


def render_markdown(report):
    """Render a ranking report deterministically (byte-stable)."""
    base = report["baseline"]
    lines = [
        "# Candidate ranking: " + report["workload_id"],
        "",
        "- schema: " + report["schema"],
        "- controlled fingerprint: " + report["controlled_fingerprint"],
        "- baseline: " + base["candidate_id"],
        "- baseline median: %.6f" % base["time"]["median"],
        "- energy budget (max regression): %.4f%%"
        % report["max_energy_regression_percent"],
        "",
    ]
    for cand in report["candidates"]:
        energy = cand["energy"]
        if energy["status"] == "measured":
            etext = "%s (%+.4f%%)" % (
                energy["verdict"], energy["median_shift_percent"])
        else:
            etext = UNMEASURED
        lines.append(
            "- rank %d: %s -- %s (primary %s %+.4f%%; energy %s; "
            "regressions: %s)" % (
                cand["rank"], cand["candidate_id"], cand["status"],
                cand["primary"]["verdict"],
                cand["primary"]["median_shift_percent"], etext,
                ", ".join(cand["regressions"]) or "none"))
    lines += ["", "Recorded samples only; no live run is claimed.", ""]
    return "\n".join(lines)
