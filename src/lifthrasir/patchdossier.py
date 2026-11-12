# SPDX-License-Identifier: GPL-2.0-only
"""Candidate patch dossier with minimal reproducer and code review (LIF-0904).

Home justification: master roadmap section 3 places core code in
``src/lifthrasir/``; the kernel-lab reporting precedent (LIF-0902
kernellab, unbanked sibling read at build time) lives there too, and
this dossier is the P9 companion that turns a candidate kernel patch
into the human-reviewed evidence package of roadmap/03 (Book III,
"Patch dossier"): (a) problem and affected commit, (b) test
reproducer, (c) control outcome, (d) minimal diff, (e) compiler and
analyzer logs, (f) test and benchmark matrix, (g) limitations and
regressions, and (h) reviewer checklist.

What this slice builds (pure functions over caller-supplied records
only -- no file, process, network or kernel access at all):

- ``parse_unified_diff``: strict unified-diff accounting (files,
  hunks, added/removed lines, paths) with minimality ceilings. A
  diff carrying a ``Signed-off-by`` tag is REFUSED by name: master
  roadmap section 0 invariant 7 -- AI agents do not issue human DCO
  tags and do not send patches upstream. This dossier is a
  human-reviewed package only; nothing here submits anything.
- Reproducer differential, following the roadmap/03 reproducer
  protocol steps 1-8: the minimal reproducer must FAIL on the
  pinned baseline across recorded runs, PASS with the candidate,
  the control case must behave as expected, and the repair must be
  FALSIFIED by reversal (patch reversed -> reproducer fails again).
  A dossier missing any leg is ``incomplete`` with the missing legs
  named -- never silently read as proven.
- Code review: a fixed reviewer checklist (the eight dossier items
  plus the safety review) where every required item needs an
  explicit pass from a named HUMAN reviewer. Agent reviewers are
  refused by name. The review verdict is derived, never asserted.
- ``PatchDossier``: the assembled, validated package with a
  deterministic content digest (timestamps excluded), a derived
  completeness verdict (``complete`` / ``incomplete`` / ``blocked``),
  an evidence-status rung capped at ``lab-verified`` until a human
  review completes (then ``human-reviewed``; ``upstream-*`` rungs
  are refused outright -- no false claim of upstream acceptance,
  Book III P9 acceptance), and a LIF-0004 v0.1 evidence record.
- High-risk paths (bootloader, firmware, partition, encryption,
  kernel image) in a diff BLOCK the dossier: master roadmap section
  0 invariant 2 forbids autonomous mutation of those areas, so the
  package is flagged for human handling, never promoted.

Evidence-status honesty: proven at fixture level only, over
recorded fixture diffs and run counts. No kernel was built, booted
or patched by this slice, and no patch was sent anywhere.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

DOSSIER_SCHEMA = "lifthrasir.patchdossier.v0.1"
DOSSIER_SCHEMA_VERSION = "0.1"
DOSSIER_VERSION = "1"

EVIDENCE_LADDER = (
    "idea", "hypothesis", "reproducer", "lab-verified",
    "cross-platform-verified", "human-reviewed",
    "deployed-with-monitoring", "upstream-submitted",
    "upstream-accepted",
)
MAX_BUILDER_RUNG = "lab-verified"
MAX_DOSSIER_RUNG = "human-reviewed"

VERDICT_COMPLETE = "complete"
VERDICT_INCOMPLETE = "incomplete"
VERDICT_BLOCKED = "blocked"
VERDICTS = (VERDICT_COMPLETE, VERDICT_INCOMPLETE, VERDICT_BLOCKED)

REVIEW_PASS = "pass"
REVIEW_FAIL = "fail"
REVIEW_NA = "na"
REVIEW_STATES = (REVIEW_PASS, REVIEW_FAIL, REVIEW_NA)

# The fixed reviewer checklist: dossier items (a)-(h) of roadmap/03
# plus the safety review required by master roadmap section 0.
REVIEW_ITEMS = (
    "problem-and-affected-commit",
    "reproducer-minimal-and-pinned",
    "control-outcome-checked",
    "diff-minimal-and-scoped",
    "compiler-and-analyzer-logs-clean-or-explained",
    "test-matrix-differential-pass",
    "limitations-and-regressions-stated",
    "reversal-falsification-checked",
    "safety-invariants-respected",
)
# Items that may be marked na only with a recorded reason.
NA_ALLOWED_ITEMS = ("compiler-and-analyzer-logs-clean-or-explained",)

MAX_DIFF_FILES = 8
MAX_DIFF_CHANGED_LINES = 400
MAX_TEXT_CHARS = 20000
MAX_MATRIX_ROWS = 64
MIN_BASELINE_RUNS = 3

HIGH_RISK_PATH_PARTS = (
    "bootloader", "grub", "firmware", "efi/", "/efi",
    "partition", "cryptsetup", "luks", "vmlinuz", "initramfs",
    "secure-boot", "mok", "shim",
)

_ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]*$")
_INCIDENT_RE = re.compile(r"^inc-[a-z0-9][a-z0-9-]*$")
_COMMIT_RE = re.compile(r"^[a-f0-9]{7,64}$")
_SHA_RE = re.compile(r"^sha256:[a-f0-9]{64}$")
_DCO_RE = re.compile(r"^\s*Signed-off-by\s*:", re.IGNORECASE | re.MULTILINE)
_ARCHES = ("x86_64", "arm64")


class DossierError(Exception):
    """Base class for all named patch-dossier refusals."""


class MalformedDossierError(DossierError):
    """A dossier field, diff or run record breaks a shape rule."""


class DCOViolationError(DossierError):
    """Diff or message carries a Signed-off-by tag (invariant 7)."""


class UpstreamClaimError(DossierError):
    """A dossier claims an upstream rung it may never claim."""


class AgentReviewError(DossierError):
    """The recorded reviewer is not a named human reviewer."""


def _req_text(value: Any, name: str, limit: int = MAX_TEXT_CHARS) -> str:
    if not isinstance(value, str) or not value.strip():
        raise MalformedDossierError(f"{name} must be a non-empty string")
    if len(value) > limit:
        raise MalformedDossierError(f"{name} exceeds {limit} chars")
    return value


def _check_no_dco(text: str, where: str) -> None:
    if _DCO_RE.search(text):
        raise DCOViolationError(
            f"{where} carries a Signed-off-by tag: agents never sign "
            "DCO (master roadmap section 0, invariant 7); the human "
            "contributor signs at submission time, outside this tool")


def sha256_of_text(text: str) -> str:
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class DiffStats:
    files: Tuple[str, ...]
    hunks: int
    added: int
    removed: int
    digest: str
    high_risk_paths: Tuple[str, ...] = ()

    @property
    def changed_lines(self) -> int:
        return self.added + self.removed

    @property
    def is_minimal(self) -> bool:
        return (len(self.files) <= MAX_DIFF_FILES
                and self.changed_lines <= MAX_DIFF_CHANGED_LINES
                and self.hunks >= 1)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "files": list(self.files), "hunks": self.hunks,
            "added": self.added, "removed": self.removed,
            "changed_lines": self.changed_lines,
            "is_minimal": self.is_minimal, "digest": self.digest,
            "high_risk_paths": list(self.high_risk_paths),
        }


_DIFF_FILE_RE = re.compile(r"^\+\+\+ b/(.+)$")
_DIFF_OLD_RE = re.compile(r"^--- a/(.+)$")
_HUNK_RE = re.compile(r"^@@ -\d+(?:,\d+)? \+\d+(?:,\d+)? @@")


def parse_unified_diff(text: str) -> DiffStats:
    """Strict unified-diff accounting; refuses non-diffs by name."""
    _req_text(text, "patch diff")
    _check_no_dco(text, "patch diff")
    if "Binary files" in text or "GIT binary patch" in text:
        raise MalformedDossierError(
            "binary patches are refused: a candidate dossier diff "
            "must be reviewable text")
    files: List[str] = []
    hunks = added = removed = 0
    in_hunk = False
    for line in text.splitlines():
        m = _DIFF_FILE_RE.match(line)
        if m:
            path = m.group(1).strip()
            if path != "/dev/null" and path not in files:
                files.append(path)
            in_hunk = False
            continue
        if line.startswith("diff --git "):
            in_hunk = False
            continue
        if _HUNK_RE.match(line):
            hunks += 1
            in_hunk = True
            continue
        if in_hunk:
            if line.startswith("+") and not line.startswith("+++"):
                added += 1
            elif line.startswith("-") and not line.startswith("---"):
                removed += 1
    if not files or hunks == 0:
        raise MalformedDossierError(
            "patch diff has no file headers or no hunks: not a "
            "unified diff a reviewer can read")
    high = tuple(p for p in files
                 if any(part in p.lower() for part in HIGH_RISK_PATH_PARTS))
    return DiffStats(files=tuple(sorted(files)), hunks=hunks,
                     added=added, removed=removed,
                     digest=sha256_of_text(text),
                     high_risk_paths=tuple(sorted(high)))


@dataclass(frozen=True)
class RunTally:
    """Recorded runs of one reproducer leg (counts only, no logs)."""
    runs: int
    failures: int

    def __post_init__(self) -> None:
        if not isinstance(self.runs, int) or not isinstance(self.failures, int):
            raise MalformedDossierError("run tally counts must be integers")
        if self.runs < 1 or self.failures < 0 or self.failures > self.runs:
            raise MalformedDossierError(
                f"run tally impossible: {self.failures} failures in "
                f"{self.runs} runs")

    def to_dict(self) -> Dict[str, Any]:
        return {"runs": self.runs, "failures": self.failures}

    @classmethod
    def from_dict(cls, data: Any, name: str) -> "RunTally":
        if not isinstance(data, dict) or set(data) != {"runs", "failures"}:
            raise MalformedDossierError(
                f"{name} must be an object with runs and failures")
        return cls(runs=data["runs"], failures=data["failures"])


@dataclass(frozen=True)
class Reproducer:
    """Minimal reproducer + the four differential legs (roadmap/03)."""
    description: str
    script: str
    baseline: RunTally
    candidate: RunTally
    control: RunTally
    control_expectation: str  # "pass" or "fail"
    reversed_patch: Optional[RunTally] = None

    @property
    def script_digest(self) -> str:
        return sha256_of_text(self.script)

    def legs(self) -> Dict[str, bool]:
        base_ok = (self.baseline.runs >= MIN_BASELINE_RUNS
                   and self.baseline.failures == self.baseline.runs)
        cand_ok = self.candidate.failures == 0 and self.candidate.runs >= 1
        if self.control_expectation == "pass":
            ctrl_ok = self.control.failures == 0
        else:
            ctrl_ok = self.control.failures == self.control.runs
        rev_ok = (self.reversed_patch is not None
                  and self.reversed_patch.failures
                  == self.reversed_patch.runs
                  and self.reversed_patch.runs >= 1)
        return {"baseline-fails": base_ok, "candidate-passes": cand_ok,
                "control-as-expected": ctrl_ok,
                "reversal-fails-again": rev_ok}

    @property
    def differential_ok(self) -> bool:
        return all(self.legs().values())

    def to_dict(self) -> Dict[str, Any]:
        return {
            "description": self.description,
            "script_digest": self.script_digest,
            "baseline": self.baseline.to_dict(),
            "candidate": self.candidate.to_dict(),
            "control": self.control.to_dict(),
            "control_expectation": self.control_expectation,
            "reversed_patch": (self.reversed_patch.to_dict()
                               if self.reversed_patch else None),
            "legs": self.legs(),
            "differential_ok": self.differential_ok,
        }


def _reproducer_from(data: Any) -> Reproducer:
    if not isinstance(data, dict):
        raise MalformedDossierError("reproducer must be an object")
    desc = _req_text(data.get("description"), "reproducer.description")
    script = _req_text(data.get("script"), "reproducer.script")
    _check_no_dco(script, "reproducer script")
    exp = data.get("control_expectation")
    if exp not in ("pass", "fail"):
        raise MalformedDossierError(
            "reproducer.control_expectation must be 'pass' or 'fail'")
    rev = data.get("reversed_patch")
    return Reproducer(
        description=desc, script=script,
        baseline=RunTally.from_dict(data.get("baseline"),
                                    "reproducer.baseline"),
        candidate=RunTally.from_dict(data.get("candidate"),
                                     "reproducer.candidate"),
        control=RunTally.from_dict(data.get("control"),
                                   "reproducer.control"),
        control_expectation=exp,
        reversed_patch=(RunTally.from_dict(rev, "reproducer.reversed_patch")
                        if rev is not None else None))


@dataclass(frozen=True)
class Review:
    """One human code review over the fixed checklist."""
    reviewer: str
    reviewer_kind: str  # must be "human"
    items: Tuple[Tuple[str, str], ...]
    na_reasons: Tuple[Tuple[str, str], ...] = ()
    notes: str = ""

    @property
    def complete(self) -> bool:
        states = dict(self.items)
        reasons = dict(self.na_reasons)
        for item in REVIEW_ITEMS:
            state = states.get(item)
            if state == REVIEW_PASS:
                continue
            if state == REVIEW_NA and item in NA_ALLOWED_ITEMS \
                    and reasons.get(item):
                continue
            return False
        return True

    @property
    def any_fail(self) -> bool:
        return any(s == REVIEW_FAIL for _, s in self.items)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "reviewer": self.reviewer,
            "reviewer_kind": self.reviewer_kind,
            "items": [{"item": k, "state": v} for k, v in self.items],
            "na_reasons": [{"item": k, "reason": v}
                           for k, v in self.na_reasons],
            "notes": self.notes, "complete": self.complete,
        }


def _review_from(data: Any) -> Optional[Review]:
    if data is None:
        return None
    if not isinstance(data, dict):
        raise MalformedDossierError("review must be an object or null")
    reviewer = _req_text(data.get("reviewer"), "review.reviewer", 200)
    kind = data.get("reviewer_kind")
    if kind != "human":
        raise AgentReviewError(
            f"reviewer_kind must be 'human' (got {kind!r}): candidate "
            "dossiers are human-reviewed only (master roadmap "
            "section 0, invariant 7; section 5 rule 10)")
    raw_items = data.get("items")
    if not isinstance(raw_items, list) or not raw_items:
        raise MalformedDossierError("review.items must be a non-empty list")
    items: List[Tuple[str, str]] = []
    seen = set()
    for entry in raw_items:
        if not isinstance(entry, dict):
            raise MalformedDossierError("review items must be objects")
        item, state = entry.get("item"), entry.get("state")
        if item not in REVIEW_ITEMS:
            raise MalformedDossierError(f"unknown review item {item!r}")
        if state not in REVIEW_STATES:
            raise MalformedDossierError(
                f"review item {item!r} has bad state {state!r}")
        if item in seen:
            raise MalformedDossierError(f"duplicate review item {item!r}")
        seen.add(item)
        items.append((item, state))
    reasons: List[Tuple[str, str]] = []
    for entry in data.get("na_reasons") or []:
        if not isinstance(entry, dict) or entry.get("item") not in REVIEW_ITEMS:
            raise MalformedDossierError("na_reasons entries are malformed")
        reasons.append((entry["item"],
                        _req_text(entry.get("reason"), "na reason", 500)))
    notes = data.get("notes") or ""
    if not isinstance(notes, str) or len(notes) > MAX_TEXT_CHARS:
        raise MalformedDossierError("review.notes is malformed")
    _check_no_dco(notes, "review notes")
    return Review(reviewer=reviewer, reviewer_kind=kind,
                  items=tuple(sorted(items)),
                  na_reasons=tuple(sorted(reasons)), notes=notes)


def _matrix_from(data: Any) -> Tuple[Dict[str, Any], ...]:
    if data is None:
        return ()
    if not isinstance(data, list) or len(data) > MAX_MATRIX_ROWS:
        raise MalformedDossierError(
            f"test_matrix must be a list of at most {MAX_MATRIX_ROWS} rows")
    rows = []
    for row in data:
        if not isinstance(row, dict):
            raise MalformedDossierError("test_matrix rows must be objects")
        name = _req_text(row.get("name"), "test_matrix row name", 300)
        outcome = row.get("outcome")
        if outcome not in ("passed", "failed", "skipped", "error"):
            raise MalformedDossierError(
                f"test_matrix row {name!r} has bad outcome {outcome!r}")
        rows.append({"name": name, "outcome": outcome,
                     "detail": str(row.get("detail") or "")[:500]})
    return tuple(rows)


@dataclass(frozen=True)
class PatchDossier:
    dossier_id: str
    incident_id: str
    title: str
    problem: str
    affected_commit: str
    arch: str
    kernel_release: str
    diff: DiffStats
    reproducer: Reproducer
    test_matrix: Tuple[Dict[str, Any], ...] = ()
    analyzer_summary: str = ""
    limitations: Tuple[str, ...] = ()
    regressions: Tuple[str, ...] = ()
    review: Optional[Review] = None
    claimed_status: str = "lab-verified"

    def missing(self) -> List[str]:
        out: List[str] = []
        for leg, ok in self.reproducer.legs().items():
            if not ok:
                out.append(f"reproducer leg: {leg}")
        if not self.diff.is_minimal:
            out.append("diff exceeds minimality ceilings "
                       f"({len(self.diff.files)} files, "
                       f"{self.diff.changed_lines} changed lines)")
        if not self.test_matrix:
            out.append("test matrix is empty")
        elif any(r["outcome"] in ("failed", "error")
                 for r in self.test_matrix):
            out.append("test matrix has failed/error rows")
        if not self.limitations:
            out.append("limitations not stated")
        if self.review is None:
            out.append("human code review missing")
        elif not self.review.complete:
            out.append("human code review incomplete or failed")
        return out

    @property
    def verdict(self) -> str:
        if self.diff.high_risk_paths:
            return VERDICT_BLOCKED
        if self.review is not None and self.review.any_fail:
            return VERDICT_BLOCKED
        return VERDICT_COMPLETE if not self.missing() else VERDICT_INCOMPLETE

    @property
    def evidence_status(self) -> str:
        # Builder output is capped at lab-verified; a completed human
        # review raises the DOSSIER record to human-reviewed. Upstream
        # rungs are never produced here (see build_dossier guard).
        if self.verdict == VERDICT_COMPLETE:
            return "human-reviewed"
        if self.reproducer.differential_ok:
            return "lab-verified"
        if self.claimed_status in EVIDENCE_LADDER[:3]:
            return self.claimed_status
        return "reproducer"

    def canonical(self) -> Dict[str, Any]:
        return {
            "schema": DOSSIER_SCHEMA,
            "schema_version": DOSSIER_SCHEMA_VERSION,
            "dossier_id": self.dossier_id,
            "incident_id": self.incident_id,
            "title": self.title, "problem": self.problem,
            "affected_commit": self.affected_commit,
            "arch": self.arch, "kernel_release": self.kernel_release,
            "diff": self.diff.to_dict(),
            "reproducer": self.reproducer.to_dict(),
            "test_matrix": [dict(r) for r in self.test_matrix],
            "analyzer_summary": self.analyzer_summary,
            "limitations": list(self.limitations),
            "regressions": list(self.regressions),
            "review": self.review.to_dict() if self.review else None,
        }

    @property
    def digest(self) -> str:
        blob = json.dumps(self.canonical(), sort_keys=True,
                          separators=(",", ":"))
        return sha256_of_text(blob)

    def to_dict(self) -> Dict[str, Any]:
        out = self.canonical()
        out["verdict"] = self.verdict
        out["missing"] = self.missing()
        out["evidence_status"] = self.evidence_status
        out["digest"] = self.digest
        out["upstream_submitted"] = False
        return out

    def evidence_fields(self, recorded_at: str, host_local_id: str,
                        evidence_id: str,
                        tool_versions: Dict[str, str],
                        baseline_evidence_id: Optional[str] = None
                        ) -> Dict[str, Any]:
        """LIF-0004 v0.1 evidence record (kind differential-run)."""
        if not tool_versions:
            raise MalformedDossierError(
                "tool_versions are required for a differential-run "
                "evidence record (LIF-0004 v0.1)")
        rec: Dict[str, Any] = {
            "schema": "lifthrasir.evidence.v0.1",
            "schema_version": "0.1",
            "evidence_id": evidence_id,
            "incident_id": self.incident_id,
            "kind": "differential-run",
            "recorded_at": recorded_at,
            "source": {"component": "lab",
                       "host_local_id": host_local_id},
            "summary": (f"patch dossier {self.dossier_id}: verdict "
                        f"{self.verdict}, differential "
                        f"{'ok' if self.reproducer.differential_ok else 'incomplete'}"),
            "content_digest": self.digest,
            "evidence_status": self.evidence_status,
            "tool_versions": dict(tool_versions),
            "limitations": list(self.limitations),
            "artifact_refs": [self.diff.digest,
                              self.reproducer.script_digest],
        }
        if baseline_evidence_id:
            rec["baseline_evidence_id"] = baseline_evidence_id
        return rec


def build_dossier(data: Dict[str, Any]) -> PatchDossier:
    """Validate a dossier record and assemble the PatchDossier.

    Refusals are named: malformed fields, a DCO tag anywhere in the
    diff/messages, an agent (non-human) reviewer, or any claimed
    evidence rung above human-reviewed -- upstream-submitted and
    upstream-accepted claims are refused outright, because this
    tool never submits and acceptance is a maintainer fact.
    """
    if not isinstance(data, dict):
        raise MalformedDossierError("dossier must be a JSON object")
    claimed = data.get("evidence_status") or "lab-verified"
    if claimed not in EVIDENCE_LADDER:
        raise MalformedDossierError(f"unknown evidence_status {claimed!r}")
    if EVIDENCE_LADDER.index(claimed) > EVIDENCE_LADDER.index(MAX_DOSSIER_RUNG):
        raise UpstreamClaimError(
            f"evidence_status {claimed!r} refused: a candidate dossier "
            "never claims upstream submission or acceptance; the human "
            "contributor submits and maintainers decide (Book III P9)")
    did = data.get("dossier_id")
    if not isinstance(did, str) or not _ID_RE.match(did):
        raise MalformedDossierError(f"bad dossier_id {did!r}")
    inc = data.get("incident_id")
    if not isinstance(inc, str) or not _INCIDENT_RE.match(inc):
        raise MalformedDossierError(f"bad incident_id {inc!r}")
    commit = data.get("affected_commit")
    if not isinstance(commit, str) or not _COMMIT_RE.match(commit):
        raise MalformedDossierError(
            f"affected_commit must be a pinned hex commit id, got {commit!r}")
    arch = data.get("arch")
    if arch not in _ARCHES:
        raise MalformedDossierError(f"unsupported arch {arch!r}")
    title = _req_text(data.get("title"), "title", 300)
    _check_no_dco(title, "dossier title")
    problem = _req_text(data.get("problem"), "problem")
    _check_no_dco(problem, "problem statement")
    release = _req_text(data.get("kernel_release"), "kernel_release", 100)
    if release in ("latest", "stable", "mainline"):
        raise MalformedDossierError("kernel_release must be pinned")
    diff = parse_unified_diff(data.get("patch_diff"))
    repro = _reproducer_from(data.get("reproducer"))
    limits = data.get("limitations") or []
    if not isinstance(limits, list) or any(
            not isinstance(x, str) or not x.strip() for x in limits):
        raise MalformedDossierError("limitations must be non-empty strings")
    regs = data.get("regressions") or []
    if not isinstance(regs, list) or any(not isinstance(x, str) for x in regs):
        raise MalformedDossierError("regressions must be strings")
    analyzer = data.get("analyzer_summary") or ""
    if not isinstance(analyzer, str) or len(analyzer) > MAX_TEXT_CHARS:
        raise MalformedDossierError("analyzer_summary is malformed")
    return PatchDossier(
        dossier_id=did, incident_id=inc, title=title, problem=problem,
        affected_commit=commit, arch=arch, kernel_release=release,
        diff=diff, reproducer=repro,
        test_matrix=_matrix_from(data.get("test_matrix")),
        analyzer_summary=analyzer,
        limitations=tuple(limits), regressions=tuple(regs),
        review=_review_from(data.get("review")),
        claimed_status=claimed)


def summarize_dossiers(dossiers: List[PatchDossier]) -> Dict[str, Any]:
    counts = {v: 0 for v in VERDICTS}
    for d in dossiers:
        counts[d.verdict] += 1
    return {"total": len(dossiers), "verdicts": counts,
            "complete_ids": sorted(d.dossier_id for d in dossiers
                                   if d.verdict == VERDICT_COMPLETE)}
