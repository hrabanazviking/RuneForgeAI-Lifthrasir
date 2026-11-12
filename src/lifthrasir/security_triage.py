"""Security triage and low-false-positive baseline (LIF-0802).

SPDX-License-Identifier: GPL-2.0-only

Home justification: master roadmap section 3 lays out ``src/`` for
core code; the P4 authority pieces and the P5 Eir companion
classifier (LIF-0506, ``service_intent``) already live in
``src/lifthrasir/``.  Thor (P8) is Eir's defence sibling in the
reference architecture -- detector findings flow to a triage step
that ranks them for a human BEFORE any response is proposed
(response coordination is LIF-0803, behind the P4 policy engine).
This triage layer is that step, so it lives beside them here.

Detector interface (fixture-shaped, banked contracts only): this
slice was built while LIF-0801 (the Thor detector itself) was still
unbanked, so the finding shape is defined from the BANKED
LIF-0004 v0.1 schemas, not from any unbanked detector code:

- ``evidence_refs`` are LIF-0004 evidence ids (``ev-...``) and a
  finding may carry the ``incident_id`` (``inc-...``) of the
  LIF-0004 incident it belongs to -- the same envelope discipline
  the banked hypothesis records (LIF-0305) validate against.
- ``claimed_severity`` uses the LIF-0004 incident severity enum
  (info / low / medium / high / critical).
- A finding is a *claim by a detector*, never proof: triage ranks
  the claim, it does not certify it (master roadmap section 0
  invariant 4 -- unknown or untested is not verified).

What triage does (deterministic, no model, no I/O, no action):

- Scores each finding from three recorded factors only: the
  detector's claimed severity, NOVELTY against a recorded baseline
  (exact known-benign match, exact known-bad match, changed value
  on a known target, or a target/check the baseline has never
  seen), and CORROBORATION (how many distinct evidence records
  back the finding).
- Maps the score to one of four tiers for a human: ``urgent``
  (page now), ``review`` (queue for review), ``watch`` (digest /
  low action) and ``suppress`` (no action).  ``review`` and
  ``urgent`` are the SURFACED tiers; ``watch`` and ``suppress``
  are the CALM (low/no-action) tiers.
- Groups findings by (check, target_type, target): duplicates of
  one underlying condition corroborate each other, so a group's
  score adds a bonus for distinct evidence refs and distinct
  detectors across the group.
- The low-false-positive mechanism is the baseline, not optimism:
  a finding whose (check, target, observed) exactly matches a
  recorded known-benign baseline entry is suppressed WHATEVER
  severity the detector claimed (distro updates and sanctioned
  drift are the classic false positives).  An exact known-bad
  match is floored to urgent.  A conflicting baseline (the same
  observed value recorded both benign and bad) resolves to bad:
  triage fails toward surfacing, never toward silence.

What triage never does: it executes nothing, changes no host
state, proposes no response plan (LIF-0803 + P4 policy own that),
and never drops a finding -- suppressed findings stay in the
report, counted, with their reasons.

Baseline corpus measurement: ``evaluate_corpus`` runs a labelled
fixture corpus (known-benign / known-bad findings) through
per-finding triage and reports the measured counts and rates --
benign calm rate, false-positive rate, bad surface rate and
false-negative rate.  Rates are computed from the run, never
asserted; the corpus file states the ground-truth labels and the
tests pin the measured counts.

Evidence-status honesty: contract/test level only (ladder:
reproducer + lab-verified at fixture scope, on this platform).
No live detector, no live host and no real incident were
involved; the baseline entries in the corpus are fixture records,
not a production baseline for any real machine.  Human review
pending.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

TRIAGE_SCHEMA = "lifthrasir.security-triage.v0.1"
TRIAGE_SCHEMA_VERSION = "0.1"

SEVERITIES = ("info", "low", "medium", "high", "critical")
SEVERITY_POINTS = {
    "info": 0, "low": 10, "medium": 25, "high": 45, "critical": 70,
}

TIERS = ("suppress", "watch", "review", "urgent")
SURFACED_TIERS = ("review", "urgent")
CALM_TIERS = ("watch", "suppress")

WATCH_MIN = 20
REVIEW_MIN = 45
URGENT_MIN = 70
KNOWN_BAD_FLOOR = 80
BENIGN_SCORE_CAP = 5

NOVELTY_POINTS = {"known-benign": 0, "known-bad": 20,
                  "changed": 15, "novel": 10}
KNOWN_BENIGN = "known-benign"
KNOWN_BAD = "known-bad"
CHANGED = "changed"
NOVEL = "novel"
NOVELTIES = (KNOWN_BENIGN, KNOWN_BAD, CHANGED, NOVEL)

DISPOSITIONS = ("benign", "bad")
LABELS = ("benign", "bad")

MAX_EVIDENCE_REFS = 32
MAX_FINDINGS = 4096

_FIND_RE = re.compile(r"^find-[a-z0-9][a-z0-9-]*$")
_INC_RE = re.compile(r"^inc-[a-z0-9][a-z0-9-]*$")
_EV_RE = re.compile(r"^ev-[a-z0-9][a-z0-9-]*$")

_FINDING_REQUIRED = (
    "finding_id", "detector", "check", "target_type", "target",
    "claimed_severity", "observed", "evidence_refs", "recorded_at",
    "detail",
)
_FINDING_ALLOWED = frozenset(_FINDING_REQUIRED) | {"expected",
                                                   "incident_id"}
_ENTRY_REQUIRED = ("check", "target_type", "target", "observed",
                   "disposition")
_ENTRY_ALLOWED = frozenset(_ENTRY_REQUIRED) | {"note"}


class TriageError(Exception):
    """Base class for all named triage refusals."""


class MalformedFindingError(TriageError):
    """Raised when a detector finding breaks a field rule."""


class MalformedBaselineError(TriageError):
    """Raised when a baseline entry or corpus case is malformed."""


def _parse_ts(value: Any, field_name: str) -> datetime:
    if not isinstance(value, str) or not value:
        raise MalformedFindingError(
            f"{field_name} must be an RFC 3339 date-time string, "
            f"got {value!r}")
    text = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        raise MalformedFindingError(
            f"{field_name} {value!r} is not a valid date-time"
        ) from None


def _nonempty(value: Any, field_name: str, exc) -> str:
    if not isinstance(value, str) or not value.strip():
        raise exc(f"{field_name} must be a non-empty string, "
                  f"got {value!r}")
    return value


@dataclass(frozen=True)
class DetectorFinding:
    """One detector claim, in the banked-schema-shaped envelope.

    ``observed`` is the value/state the detector recorded;
    ``expected`` is the baseline value the detector compared
    against, when it recorded one (else None -- never invented).
    """

    finding_id: str
    detector: str
    check: str
    target_type: str
    target: str
    claimed_severity: str
    observed: str
    evidence_refs: Tuple[str, ...] = ()
    recorded_at: str = ""
    detail: str = ""
    expected: Optional[str] = None
    incident_id: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        out: Dict[str, Any] = {
            "finding_id": self.finding_id,
            "detector": self.detector,
            "check": self.check,
            "target_type": self.target_type,
            "target": self.target,
            "claimed_severity": self.claimed_severity,
            "observed": self.observed,
            "evidence_refs": list(self.evidence_refs),
            "recorded_at": self.recorded_at,
            "detail": self.detail,
        }
        if self.expected is not None:
            out["expected"] = self.expected
        if self.incident_id is not None:
            out["incident_id"] = self.incident_id
        return out


def validate_finding(record: Any) -> DetectorFinding:
    """Validate one finding dict; returns a DetectorFinding.

    Raises MalformedFindingError on any rule break.  A malformed
    finding is refused loudly, never triaged silently.
    """
    if not isinstance(record, dict):
        raise MalformedFindingError(
            f"finding must be a JSON object, got "
            f"{type(record).__name__}")
    extra = sorted(set(record) - _FINDING_ALLOWED)
    if extra:
        raise MalformedFindingError(
            f"finding carries fields the v0.1 shape forbids: "
            f"{extra}")
    missing = [f for f in _FINDING_REQUIRED if f not in record]
    if missing:
        raise MalformedFindingError(
            f"finding is missing required fields: {missing}")
    if not _FIND_RE.match(str(record["finding_id"])):
        raise MalformedFindingError(
            f"finding_id {record['finding_id']!r} is not a "
            f"well-formed finding id (find-...)")
    for name in ("detector", "check", "target_type", "target",
                 "observed", "detail"):
        _nonempty(record[name], name, MalformedFindingError)
    if record["claimed_severity"] not in SEVERITIES:
        raise MalformedFindingError(
            f"claimed_severity {record['claimed_severity']!r} is "
            f"not one of {SEVERITIES} (LIF-0004 incident enum)")
    refs = record["evidence_refs"]
    if not isinstance(refs, list):
        raise MalformedFindingError(
            f"evidence_refs must be a list of evidence ids, got "
            f"{type(refs).__name__}")
    if len(refs) > MAX_EVIDENCE_REFS:
        raise MalformedFindingError(
            f"evidence_refs carries {len(refs)} entries; the cap "
            f"is {MAX_EVIDENCE_REFS}")
    for ref in refs:
        if not isinstance(ref, str) or not _EV_RE.match(ref):
            raise MalformedFindingError(
                f"evidence_refs entry {ref!r} is not a "
                f"well-formed evidence id (ev-...)")
    if len(set(refs)) != len(refs):
        raise MalformedFindingError(
            "evidence_refs must not contain duplicates; "
            "corroboration counts DISTINCT evidence")
    _parse_ts(record["recorded_at"], "recorded_at")
    expected = record.get("expected")
    if expected is not None:
        _nonempty(expected, "expected", MalformedFindingError)
    incident_id = record.get("incident_id")
    if incident_id is not None and not _INC_RE.match(
            str(incident_id)):
        raise MalformedFindingError(
            f"incident_id {incident_id!r} is not a well-formed "
            f"incident id (inc-...)")
    return DetectorFinding(
        finding_id=record["finding_id"],
        detector=record["detector"],
        check=record["check"],
        target_type=record["target_type"],
        target=record["target"],
        claimed_severity=record["claimed_severity"],
        observed=record["observed"],
        evidence_refs=tuple(refs),
        recorded_at=record["recorded_at"],
        detail=record["detail"],
        expected=expected,
        incident_id=incident_id,
    )


def finding_from_dict(record: Any) -> DetectorFinding:
    """Alias of validate_finding (dict in, finding out)."""
    return validate_finding(record)


@dataclass(frozen=True)
class BaselineEntry:
    """One recorded baseline fact about a target.

    disposition ``benign``: this exact observed value is known
    good (e.g. a recorded distro update).  disposition ``bad``:
    this exact observed value is a known-bad signature.
    """

    check: str
    target_type: str
    target: str
    observed: str
    disposition: str
    note: str = ""

    def to_dict(self) -> Dict[str, Any]:
        out = {"check": self.check, "target_type": self.target_type,
               "target": self.target, "observed": self.observed,
               "disposition": self.disposition}
        if self.note:
            out["note"] = self.note
        return out


def validate_baseline_entry(record: Any) -> BaselineEntry:
    if not isinstance(record, dict):
        raise MalformedBaselineError(
            f"baseline entry must be a JSON object, got "
            f"{type(record).__name__}")
    extra = sorted(set(record) - _ENTRY_ALLOWED)
    if extra:
        raise MalformedBaselineError(
            f"baseline entry carries unknown fields: {extra}")
    missing = [f for f in _ENTRY_REQUIRED if f not in record]
    if missing:
        raise MalformedBaselineError(
            f"baseline entry is missing required fields: {missing}")
    for name in ("check", "target_type", "target", "observed"):
        _nonempty(record[name], name, MalformedBaselineError)
    if record["disposition"] not in DISPOSITIONS:
        raise MalformedBaselineError(
            f"disposition {record['disposition']!r} is not one "
            f"of {DISPOSITIONS}")
    note = record.get("note", "")
    if not isinstance(note, str):
        raise MalformedBaselineError("note must be a string")
    return BaselineEntry(
        check=record["check"], target_type=record["target_type"],
        target=record["target"], observed=record["observed"],
        disposition=record["disposition"], note=note)


class Baseline:
    """A recorded baseline: exact-match lookup + novelty judge.

    An empty baseline is a valid (if weak) baseline: every finding
    is then novel and nothing is calmed -- the corpus negative
    control measures exactly that degradation.
    """

    def __init__(self, entries=()):
        self._entries: Tuple[BaselineEntry, ...] = tuple(entries)
        self._exact: Dict[Tuple[str, str, str, str], str] = {}
        self._known_targets = set()
        for entry in self._entries:
            key = (entry.check, entry.target_type, entry.target,
                   entry.observed)
            # A conflicting record (same key, both dispositions)
            # resolves to bad: fail toward surfacing.
            if self._exact.get(key) != "bad":
                self._exact[key] = entry.disposition
            self._known_targets.add(
                (entry.check, entry.target_type, entry.target))

    def __len__(self) -> int:
        return len(self._entries)

    @property
    def entries(self) -> Tuple[BaselineEntry, ...]:
        return self._entries

    @classmethod
    def from_dicts(cls, records) -> "Baseline":
        if not isinstance(records, list):
            raise MalformedBaselineError(
                "baseline must be a list of entries")
        return cls(validate_baseline_entry(r) for r in records)

    def lookup(self, finding: DetectorFinding) -> Optional[str]:
        """Disposition of the exact-match entry, else None."""
        return self._exact.get((finding.check, finding.target_type,
                                finding.target, finding.observed))

    def novelty_for(self, finding: DetectorFinding) -> str:
        exact = self.lookup(finding)
        if exact == "bad":
            return KNOWN_BAD
        if exact == "benign":
            return KNOWN_BENIGN
        if (finding.check, finding.target_type,
                finding.target) in self._known_targets:
            return CHANGED
        return NOVEL


def _corroboration_points(distinct_refs: int) -> int:
    if distinct_refs >= 3:
        return 15
    if distinct_refs == 2:
        return 8
    return 0


def tier_for_score(score: int) -> str:
    if score >= URGENT_MIN:
        return "urgent"
    if score >= REVIEW_MIN:
        return "review"
    if score >= WATCH_MIN:
        return "watch"
    return "suppress"


def score_finding(finding: DetectorFinding,
                  baseline: Baseline) -> Tuple[int, str, Tuple[str, ...]]:
    """Score one finding.  Returns (score, novelty, reasons).

    Rule order: exact known-bad match floors the score to urgent;
    exact known-benign match caps it to suppress; otherwise the
    score is severity + novelty + corroboration points, capped
    at 100.  Pure arithmetic on recorded fields -- deterministic.
    """
    novelty = baseline.novelty_for(finding)
    reasons = [f"severity:{finding.claimed_severity}",
               f"novelty:{novelty}"]
    refs = len(set(finding.evidence_refs))
    if refs:
        reasons.append(f"corroboration:{refs}-evidence-refs")
    if novelty == KNOWN_BENIGN:
        reasons.append("baseline-benign-match")
        return BENIGN_SCORE_CAP, novelty, tuple(reasons)
    score = (SEVERITY_POINTS[finding.claimed_severity]
             + NOVELTY_POINTS[novelty]
             + _corroboration_points(refs))
    if novelty == KNOWN_BAD:
        reasons.append("baseline-known-bad-match")
        score = max(score, KNOWN_BAD_FLOOR)
    return min(score, 100), novelty, tuple(reasons)


@dataclass(frozen=True)
class TriagedFinding:
    finding: DetectorFinding
    score: int
    tier: str
    novelty: str
    reasons: Tuple[str, ...] = ()

    @property
    def surfaced(self) -> bool:
        return self.tier in SURFACED_TIERS

    @property
    def calm(self) -> bool:
        return self.tier in CALM_TIERS

    def to_dict(self) -> Dict[str, Any]:
        return {"finding": self.finding.to_dict(),
                "score": self.score, "tier": self.tier,
                "novelty": self.novelty,
                "reasons": list(self.reasons)}


def triage_finding(finding: DetectorFinding,
                   baseline: Baseline) -> TriagedFinding:
    score, novelty, reasons = score_finding(finding, baseline)
    return TriagedFinding(finding=finding, score=score,
                          tier=tier_for_score(score),
                          novelty=novelty, reasons=reasons)


@dataclass(frozen=True)
class TriageGroup:
    """All findings for one (check, target_type, target)."""

    check: str
    target_type: str
    target: str
    findings: Tuple[TriagedFinding, ...]
    score: int
    tier: str
    novelty: str
    evidence_refs: Tuple[str, ...] = ()
    detectors: Tuple[str, ...] = ()
    reasons: Tuple[str, ...] = ()

    @property
    def surfaced(self) -> bool:
        return self.tier in SURFACED_TIERS

    def to_dict(self) -> Dict[str, Any]:
        return {"check": self.check,
                "target_type": self.target_type,
                "target": self.target, "score": self.score,
                "tier": self.tier, "novelty": self.novelty,
                "evidence_refs": list(self.evidence_refs),
                "detectors": list(self.detectors),
                "reasons": list(self.reasons),
                "findings": [f.to_dict() for f in self.findings]}


@dataclass(frozen=True)
class TriageReport:
    groups: Tuple[TriageGroup, ...]
    schema: str = TRIAGE_SCHEMA
    schema_version: str = TRIAGE_SCHEMA_VERSION

    @property
    def total_findings(self) -> int:
        return sum(len(g.findings) for g in self.groups)

    @property
    def surfaced_groups(self) -> int:
        return sum(1 for g in self.groups if g.surfaced)

    def tier_counts(self) -> Dict[str, int]:
        counts = {tier: 0 for tier in TIERS}
        for group in self.groups:
            counts[group.tier] += 1
        return counts

    def to_dict(self) -> Dict[str, Any]:
        return {"schema": self.schema,
                "schema_version": self.schema_version,
                "tier_counts": self.tier_counts(),
                "total_findings": self.total_findings,
                "groups": [g.to_dict() for g in self.groups]}


_GROUP_NOVELTY_ORDER = (KNOWN_BAD, CHANGED, NOVEL, KNOWN_BENIGN)


def triage(findings, baseline: Baseline) -> TriageReport:
    """Triage a sequence of DetectorFinding into a ranked report.

    Groups share (check, target_type, target).  A group's score is
    its strongest member's score plus a corroboration bonus when
    the group holds >= 3 distinct evidence refs (+10) or >= 2
    distinct detectors (+10) -- independent corroboration is the
    recorded reason duplicates escalate.  A group whose members
    are ALL exact known-benign matches stays suppressed; a group
    containing a known-bad member is floored to urgent.  Groups
    are ordered by descending score, then key, deterministically.
    Nothing is dropped and nothing is acted on.
    """
    items = list(findings)
    if len(items) > MAX_FINDINGS:
        raise MalformedFindingError(
            f"triage accepts at most {MAX_FINDINGS} findings per "
            f"call, got {len(items)}")
    for item in items:
        if not isinstance(item, DetectorFinding):
            raise MalformedFindingError(
                f"triage takes DetectorFinding objects (build "
                f"them with validate_finding), got "
                f"{type(item).__name__}")
    buckets: Dict[Tuple[str, str, str], List[TriagedFinding]] = {}
    for item in items:
        key = (item.check, item.target_type, item.target)
        buckets.setdefault(key, []).append(triage_finding(item,
                                                           baseline))
    groups: List[TriageGroup] = []
    for key in sorted(buckets):
        members = sorted(buckets[key],
                         key=lambda t: t.finding.finding_id)
        refs = sorted({r for t in members
                       for r in t.finding.evidence_refs})
        detectors = sorted({t.finding.detector for t in members})
        novelty = next(n for n in _GROUP_NOVELTY_ORDER
                       if any(t.novelty == n for t in members))
        reasons = [f"group-size:{len(members)}",
                   f"novelty:{novelty}"]
        if all(t.novelty == KNOWN_BENIGN for t in members):
            score = max(t.score for t in members)
            reasons.append("baseline-benign-match")
        else:
            score = max(t.score for t in members)
            bonus = 0
            if len(refs) >= 3:
                bonus += 10
                reasons.append(
                    f"group-corroboration:{len(refs)}-evidence-refs")
            if len(detectors) >= 2:
                bonus += 10
                reasons.append(
                    f"group-corroboration:{len(detectors)}-detectors")
            score = min(score + bonus, 100)
            if novelty == KNOWN_BAD:
                score = max(score, KNOWN_BAD_FLOOR)
                reasons.append("baseline-known-bad-match")
        groups.append(TriageGroup(
            check=key[0], target_type=key[1], target=key[2],
            findings=tuple(members), score=score,
            tier=tier_for_score(score), novelty=novelty,
            evidence_refs=tuple(refs), detectors=tuple(detectors),
            reasons=tuple(reasons)))
    groups.sort(key=lambda g: (-g.score, g.check, g.target_type,
                               g.target))
    return TriageReport(groups=tuple(groups))


@dataclass(frozen=True)
class CorpusCaseResult:
    name: str
    label: str
    tier: str
    score: int
    surfaced: bool


@dataclass(frozen=True)
class CorpusReport:
    """Measured corpus outcome -- counts first, rates derived."""

    total: int
    benign_total: int
    bad_total: int
    benign_calm: int
    benign_surfaced: int
    bad_surfaced: int
    bad_missed: int
    results: Tuple[CorpusCaseResult, ...] = ()

    @property
    def benign_calm_rate(self) -> float:
        return (self.benign_calm / self.benign_total
                if self.benign_total else 0.0)

    @property
    def false_positive_rate(self) -> float:
        return (self.benign_surfaced / self.benign_total
                if self.benign_total else 0.0)

    @property
    def bad_surface_rate(self) -> float:
        return (self.bad_surfaced / self.bad_total
                if self.bad_total else 0.0)

    @property
    def false_negative_rate(self) -> float:
        return (self.bad_missed / self.bad_total
                if self.bad_total else 0.0)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "total": self.total, "benign_total": self.benign_total,
            "bad_total": self.bad_total,
            "benign_calm": self.benign_calm,
            "benign_surfaced": self.benign_surfaced,
            "bad_surfaced": self.bad_surfaced,
            "bad_missed": self.bad_missed,
            "benign_calm_rate": self.benign_calm_rate,
            "false_positive_rate": self.false_positive_rate,
            "bad_surface_rate": self.bad_surface_rate,
            "false_negative_rate": self.false_negative_rate,
            "results": [
                {"name": r.name, "label": r.label, "tier": r.tier,
                 "score": r.score, "surfaced": r.surfaced}
                for r in self.results],
        }


def evaluate_corpus(cases, baseline: Baseline) -> CorpusReport:
    """Measure triage on a labelled corpus of finding dicts.

    Each case: ``{name, label, finding}`` with label ``benign``
    (ground truth: should stay calm) or ``bad`` (ground truth:
    should surface).  Cases are triaged PER FINDING (grouping is a
    separate, separately tested behaviour).  The returned report
    carries the raw counts; rates are properties of those counts.
    """
    if not isinstance(cases, list) or not cases:
        raise MalformedBaselineError(
            "corpus must be a non-empty list of cases")
    results: List[CorpusCaseResult] = []
    benign_total = bad_total = 0
    benign_calm = benign_surfaced = 0
    bad_surfaced = bad_missed = 0
    for case in cases:
        if not isinstance(case, dict):
            raise MalformedBaselineError(
                f"corpus case must be an object, got "
                f"{type(case).__name__}")
        name = case.get("name")
        _nonempty(name, "case name", MalformedBaselineError)
        label = case.get("label")
        if label not in LABELS:
            raise MalformedBaselineError(
                f"case {name!r} label {label!r} is not one of "
                f"{LABELS}")
        if "finding" not in case:
            raise MalformedBaselineError(
                f"case {name!r} carries no finding")
        triaged = triage_finding(
            validate_finding(case["finding"]), baseline)
        results.append(CorpusCaseResult(
            name=name, label=label, tier=triaged.tier,
            score=triaged.score, surfaced=triaged.surfaced))
        if label == "benign":
            benign_total += 1
            if triaged.surfaced:
                benign_surfaced += 1
            else:
                benign_calm += 1
        else:
            bad_total += 1
            if triaged.surfaced:
                bad_surfaced += 1
            else:
                bad_missed += 1
    return CorpusReport(
        total=len(results), benign_total=benign_total,
        bad_total=bad_total, benign_calm=benign_calm,
        benign_surfaced=benign_surfaced,
        bad_surfaced=bad_surfaced, bad_missed=bad_missed,
        results=tuple(results))
