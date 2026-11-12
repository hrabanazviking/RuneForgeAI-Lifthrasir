# SPDX-License-Identifier: GPL-2.0-only
"""KUnit and kselftest integration, machine-readable results (LIF-0902).

Home justification: master roadmap section 4 and roadmap/03 (P9)
fix the kernel laboratory in the Python lab/test harness beside
the evidence machinery it feeds: roadmap/03 names KUnit (unit
tests of kernel internals) and kselftest (kernel behaviour visible
through user-space interfaces) as the P9 validation tools, with
the gate that relevant cases pass or known skips are explained.
LIF-0901 (building in parallel, team-09) pins the kernel build
fixtures those runs target; this slice is the integration layer
that turns a run's TAP output into a machine-readable record
shaped to the banked LIF-0004 evidence schema
(docs/protocols/schemas/v0.1/evidence.schema.json), following the
soak module's build_evidence_record precedent and the ci_runner
machine-readable run-record precedent (lab/ci_runner.py).

What this slice builds:

- Strict TAP parsers for both frameworks: parse_kunit_tap handles
  KUnit output (TAP version 14 and KTAP version 1, indented
  "# Subtest:" suites, per-suite summary lines, final Totals);
  parse_kselftest_tap handles kselftest output (TAP version 13,
  "selftests: <target>: <test>" names, SKIP/TIMEOUT/exit=
  directives, the ksft Totals line). parse_tap dispatches on an
  explicit framework name or on detect_framework.
- Honest accounting: declared plans must match the results seen,
  declared suite/Totals counts are cross-checked against the
  parsed cases, result numbering must be sequential, and a
  truncated, plan-short, totals-mismatched, bail-out or garbage
  stream is reported as malformed (or error for Bail out!) --
  never silently read as a pass. Malformed TAP is DATA carried in
  the report's parse_issues, not an exception: the parser's job is
  to say what the stream proves and what it does not.
- RunReport / report_as_dict: the normalized machine-readable
  record (framework, verdict, completeness, flattened cases with
  suite paths, totals, declared totals, parse issues, raw-output
  sha256, deterministic run id) plus validate_report_dict, the
  shape gate for records this module emits or ingests.
- build_evidence_record: renders a report as a LIF-0004 v0.1
  evidence record (kind test-run, source component lab) whose
  content digest binds the normalized record, in the soak style.
- ingest_text / ingest_file / summarize_runs: the integration
  surface. Ingestion is over RECORDED output only.

Fixture-only scope (roadmap section 0 invariants): no kernel is
built or booted by this slice, no test binary is executed, and
nothing touches the host kernel, bootloader or firmware. Runs
against the LIF-0901 pinned fixtures happen in disposable guests
under later slices; this layer consumes their recorded TAP output
and carries the fixture identity (fixture id, architecture,
kernel release) through as metadata -- validated for shape, never
imported from team-09's unbanked fixture module. This module
imports no subprocess, socket or network machinery at all
(AST-pinned in tests).

Evidence-status honesty: parsers and records are proven at
fixture/lab level by this slice's tests on recorded TAP streams
modelled on the documented KUnit (KTAP) and kselftest (ksft)
formats. No real kernel run is claimed.
"""
from __future__ import annotations

import hashlib
import json
import platform
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

KERNELTEST_SCHEMA = "lifthrasir.kerneltest.v0.1"
KERNELTEST_SCHEMA_VERSION = "0.1"
RUN_VERSION = "1"

FRAMEWORKS = ("kunit", "kselftest")
OUTCOMES = ("passed", "failed", "skipped", "error", "xfailed", "xpassed")
VERDICTS = ("passed", "failed", "skipped", "error", "malformed")

MAX_INPUT_CHARS = 1000000
MAX_CASES = 10000
MAX_NAME_CHARS = 512
MAX_DIAGNOSTICS = 64

_FIXTURE_KEYS = ("fixture_id", "arch", "kernel_release", "source_ref")
_ARCHES = ("x86_64", "arm64")
_ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]*$")
_INCIDENT_RE = re.compile(r"^inc-[a-z0-9][a-z0-9-]*$")
_PLAN_ID_RE = re.compile(r"^plan-[a-z0-9][a-z0-9-]*$")
_HYP_ID_RE = re.compile(r"^hyp-[a-z0-9][a-z0-9-]*$")


class KernelTestError(Exception):
    """Base class for all named kernellab refusals (API misuse only).

    Malformed TAP output is never raised as one of these; it is
    reported inside the RunReport (see module docstring).
    """


class MalformedRunError(KernelTestError):
    """Raised when caller-supplied metadata or arguments break a rule."""


@dataclass(frozen=True)
class ParseIssue:
    line: Optional[int]
    message: str

    def to_dict(self) -> Dict[str, Any]:
        return {"line": self.line, "message": self.message}


@dataclass(frozen=True)
class TestCaseResult:
    name: str
    suite_path: Tuple[str, ...]
    outcome: str
    directive: Optional[str] = None
    reason: Optional[str] = None
    diagnostics: Tuple[str, ...] = ()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "suite_path": list(self.suite_path),
            "outcome": self.outcome,
            "directive": self.directive,
            "reason": self.reason,
            "diagnostics": list(self.diagnostics),
        }


@dataclass
class SuiteResult:
    name: str
    outcome: Optional[str] = None
    declared: Optional[Dict[str, int]] = None
    cases: List[TestCaseResult] = field(default_factory=list)
    suites: List["SuiteResult"] = field(default_factory=list)

    def flatten(self, prefix: Tuple[str, ...] = ()) -> List[TestCaseResult]:
        path = prefix + ((self.name,) if self.name else ())
        out: List[TestCaseResult] = []
        for case in self.cases:
            out.append(TestCaseResult(
                name=case.name, suite_path=path, outcome=case.outcome,
                directive=case.directive, reason=case.reason,
                diagnostics=case.diagnostics))
        for sub in self.suites:
            out.extend(sub.flatten(path))
        return out

    def to_dict(self, prefix: Tuple[str, ...] = ()) -> Dict[str, Any]:
        path = prefix + ((self.name,) if self.name else ())
        return {
            "name": self.name,
            "outcome": self.outcome,
            "declared": self.declared,
            "cases": [
                {
                    "name": c.name, "suite_path": list(path),
                    "outcome": c.outcome, "directive": c.directive,
                    "reason": c.reason, "diagnostics": list(c.diagnostics),
                } for c in self.cases
            ],
            "suites": [s.to_dict(path) for s in self.suites],
        }


def _validate_fixture(fixture: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Validate LIF-0901-shaped fixture metadata (shape only).

    The fixture identity is carried, never imported: LIF-0901 is a
    parallel unbanked slice, so this layer checks the shape of the
    metadata it is handed (known keys only, pinned-looking fixture
    id, known architecture) and refuses anything else by name.
    """
    if fixture is None:
        return None
    if not isinstance(fixture, dict):
        raise MalformedRunError("fixture metadata must be a dict or None")
    unknown = sorted(set(fixture) - set(_FIXTURE_KEYS))
    if unknown:
        raise MalformedRunError(f"unknown fixture keys: {unknown}")
    out: Dict[str, Any] = {}
    for key in _FIXTURE_KEYS:
        value = fixture.get(key)
        if value is None:
            out[key] = None
            continue
        if not isinstance(value, str) or not value.strip():
            raise MalformedRunError(f"fixture {key} must be a non-empty string")
        out[key] = value
    if out["fixture_id"] is not None:
        fid = out["fixture_id"]
        if not _ID_RE.match(fid) or not any(ch.isdigit() for ch in fid):
            raise MalformedRunError(
                "fixture_id must be a pinned id like linux-6.12.117-x86_64 "
                "(a floating id such as 'latest' is not a pin)")
    if out["arch"] is not None and out["arch"] not in _ARCHES:
        raise MalformedRunError(f"fixture arch must be one of {_ARCHES}")
    return out


def totals_for(cases: List[TestCaseResult]) -> Dict[str, int]:
    totals = {name: 0 for name in OUTCOMES}
    totals["total"] = 0
    for case in cases:
        totals[case.outcome] += 1
        totals["total"] += 1
    return totals


@dataclass
class RunReport:
    framework: str
    header: Optional[str]
    root: SuiteResult
    parse_issues: List[ParseIssue]
    bail_out: Optional[str]
    raw_sha256: str
    declared_totals: Optional[Dict[str, int]] = None
    fixture: Optional[Dict[str, Any]] = None
    preamble_lines: int = 0
    skip_all_reason: Optional[str] = None

    @property
    def cases(self) -> List[TestCaseResult]:
        return self.root.flatten()

    @property
    def totals(self) -> Dict[str, int]:
        return totals_for(self.cases)

    @property
    def verdict(self) -> str:
        if self.bail_out is not None:
            return "error"
        if self.parse_issues:
            return "malformed"
        totals = self.totals
        if totals["total"] == 0:
            return "skipped" if self.skip_all_reason is not None else "malformed"
        if totals["failed"] + totals["error"] > 0:
            return "failed"
        if totals["passed"] + totals["xpassed"] == 0:
            return "skipped"
        return "passed"

    @property
    def complete(self) -> bool:
        return self.bail_out is None and not self.parse_issues and (
            self.totals["total"] > 0 or self.skip_all_reason is not None)

    def to_dict(self) -> Dict[str, Any]:
        return report_as_dict(self)


def _canonical(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False)


def report_as_dict(report: RunReport) -> Dict[str, Any]:
    """Render a report as the normalized machine-readable record.

    The run id is derived from the record's own content digest
    (the soak pattern): re-ingesting identical output reproduces
    the identical record, byte for byte.
    """
    cases = report.cases
    body: Dict[str, Any] = {
        "schema": KERNELTEST_SCHEMA,
        "schema_version": KERNELTEST_SCHEMA_VERSION,
        "run_version": RUN_VERSION,
        "run_id": None,
        "framework": report.framework,
        "header": report.header,
        "verdict": report.verdict,
        "complete": report.complete,
        "fixture": report.fixture,
        "suites": [s.to_dict() for s in report.root.suites],
        "cases": [c.to_dict() for c in cases],
        "totals": report.totals,
        "declared_totals": report.declared_totals,
        "parse_issues": [i.to_dict() for i in report.parse_issues],
        "bail_out": report.bail_out,
        "skip_all_reason": report.skip_all_reason,
        "preamble_lines": report.preamble_lines,
        "raw_sha256": report.raw_sha256,
    }
    if report.root.cases:
        body["cases"] = [c.to_dict() for c in cases]
    digest = hashlib.sha256(_canonical(body).encode("utf-8")).hexdigest()
    body["run_id"] = f"kt-{digest[:12]}"
    body["content_digest"] = f"sha256:{digest}"
    return body


def run_digest(record: Dict[str, Any]) -> str:
    """Recompute a normalized record's content digest."""
    body = dict(record)
    body["run_id"] = None
    body.pop("content_digest", None)
    return hashlib.sha256(_canonical(body).encode("utf-8")).hexdigest()


def validate_report_dict(record: Any) -> Dict[str, Any]:
    """Shape gate for normalized records (emitted or ingested).

    Refuses unknown fields, wrong schema stamps, verdicts that
    disagree with the carried totals/issues, and digest/run-id
    mismatches -- a record claiming a pass its own cases contradict
    does not validate.
    """
    if not isinstance(record, dict):
        raise MalformedRunError("run record must be a dict")
    allowed = {
        "schema", "schema_version", "run_version", "run_id", "framework",
        "header", "verdict", "complete", "fixture", "suites", "cases",
        "totals", "declared_totals", "parse_issues", "bail_out",
        "skip_all_reason", "preamble_lines", "raw_sha256", "content_digest",
    }
    unknown = sorted(set(record) - allowed)
    if unknown:
        raise MalformedRunError(f"unknown run-record fields: {unknown}")
    if record.get("schema") != KERNELTEST_SCHEMA:
        raise MalformedRunError("run record schema stamp mismatch")
    if record.get("schema_version") != KERNELTEST_SCHEMA_VERSION:
        raise MalformedRunError("run record schema_version mismatch")
    if record.get("framework") not in FRAMEWORKS:
        raise MalformedRunError("run record framework must be kunit or kselftest")
    if record.get("verdict") not in VERDICTS:
        raise MalformedRunError("run record verdict is not a known verdict")
    cases = record.get("cases")
    if not isinstance(cases, list):
        raise MalformedRunError("run record cases must be a list")
    for case in cases:
        if not isinstance(case, dict) or case.get("outcome") not in OUTCOMES:
            raise MalformedRunError("run record case has an unknown outcome")
        if not isinstance(case.get("name"), str) or not case["name"]:
            raise MalformedRunError("run record case name must be non-empty")
    rebuilt = totals_for([
        TestCaseResult(name=c["name"], suite_path=tuple(c.get("suite_path") or ()),
                       outcome=c["outcome"])
        for c in cases
    ])
    if record.get("totals") != rebuilt:
        raise MalformedRunError("run record totals disagree with its cases")
    issues = record.get("parse_issues")
    if not isinstance(issues, list):
        raise MalformedRunError("run record parse_issues must be a list")
    verdict = record["verdict"]
    if record.get("bail_out") is not None and verdict != "error":
        raise MalformedRunError("a bailed-out run must carry verdict error")
    if issues and verdict not in ("malformed", "error"):
        raise MalformedRunError("a run with parse issues cannot claim a clean verdict")
    if not issues and record.get("bail_out") is None:
        if rebuilt["failed"] + rebuilt["error"] > 0:
            if verdict != "failed":
                raise MalformedRunError("a run with failures must carry verdict failed")
        elif rebuilt["total"] > 0 and rebuilt["passed"] + rebuilt["xpassed"] > 0:
            if verdict != "passed":
                raise MalformedRunError("a passing run must carry verdict passed")
        elif rebuilt["total"] > 0 and verdict != "skipped":
            raise MalformedRunError("an all-skipped run must carry verdict skipped")
    digest = run_digest(record)
    if record.get("content_digest") != f"sha256:{digest}":
        raise MalformedRunError("run record content_digest mismatch")
    if record.get("run_id") != f"kt-{digest[:12]}":
        raise MalformedRunError("run record run_id mismatch")
    _validate_fixture(record.get("fixture"))
    return record


_HEADER_RE = re.compile(r"^(KTAP|TAP) version (\d+)\s*$")
_PLAN_RE = re.compile(r"^(\d+)\.\.(\d+)(?:\s*#\s*(.*))?$")
_RESULT_RE = re.compile(r"^(not ok|ok)\s+(\d+)(?:\s+(.*))?$")
_SUBTEST_RE = re.compile(r"^#\s*Subtest:\s*(.+?)\s*$")
_TOTALS_RE = re.compile(r"^#\s*Totals:\s*(.+?)\s*$")
_SUITE_SUMMARY_RE = re.compile(
    r"^#\s*([A-Za-z0-9_.\-]+):\s*pass:(\d+)\s+fail:(\d+)"
    r"(?:\s+skip:(\d+))?\s+total:(\d+)\s*$")
_COUNTS_RE = re.compile(r"(\w+):(\d+)")
_DIRECTIVE_RE = re.compile(
    r"^(SKIP|TODO|TIMEOUT|error)\b[:\s]*(.*)$", re.IGNORECASE)
_BAIL_RE = re.compile(r"^Bail out!\s*(.*)$")

_COUNT_KEYS = {
    "pass": "passed", "fail": "failed", "skip": "skipped",
    "error": "error", "xfail": "xfailed", "xpass": "xpassed",
    "total": "total",
}


def _parse_counts(text: str) -> Optional[Dict[str, int]]:
    counts: Dict[str, int] = {}
    for key, value in _COUNTS_RE.findall(text):
        if key in _COUNT_KEYS:
            counts[_COUNT_KEYS[key]] = int(value)
    return counts or None


def _outcome_for(ok: bool, directive: Optional[str]) -> str:
    if directive == "SKIP":
        return "skipped"
    if directive == "error" and not ok:
        return "error"
    if directive == "TODO":
        return "xpassed" if ok else "xfailed"
    return "passed" if ok else "failed"


def _split_result(rest: str) -> Tuple[str, Optional[str], Optional[str], Optional[str]]:
    """Split a result tail into (name, directive, reason, note)."""
    name = rest.strip()
    if name.startswith("- "):
        name = name[2:].strip()
    elif name == "-":
        name = ""
    directive: Optional[str] = None
    reason: Optional[str] = None
    note: Optional[str] = None
    if " #" in name or name.startswith("#"):
        head, _, tail = name.partition("#")
        name = head.strip()
        if name.endswith("-"):
            name = name[:-1].strip()
        tail = tail.strip()
        match = _DIRECTIVE_RE.match(tail)
        if match:
            directive = match.group(1).upper()
            reason = match.group(2).strip() or None
        elif tail:
            note = tail
    return name[:MAX_NAME_CHARS], directive, reason, note


class _Frame:
    def __init__(self, name: str) -> None:
        self.suite = SuiteResult(name=name)
        self.plan_end: Optional[int] = None
        self.plan_directive: Optional[str] = None
        self.result_count = 0
        self.declared_summary: Optional[Dict[str, int]] = None
        self.declared_totals: Optional[Dict[str, int]] = None
        self.last_case: Optional[TestCaseResult] = None


class _Parser:
    def __init__(self, text: str, framework: str) -> None:
        self.framework = framework
        self.lines: List[Tuple[int, int, str]] = []
        for lineno, raw in enumerate(text.splitlines(), start=1):
            stripped = raw.rstrip()
            indent = len(stripped) - len(stripped.lstrip(" "))
            self.lines.append((lineno, indent, stripped.strip()))
        self.issues: List[ParseIssue] = []
        self.bail_out: Optional[str] = None
        self.header: Optional[str] = None
        self.preamble_lines = 0
        self.declared_totals: Optional[Dict[str, int]] = None
        self.skip_all_reason: Optional[str] = None
        self.case_count = 0
        self.overflow_noted = False

    def issue(self, line: Optional[int], message: str) -> None:
        self.issues.append(ParseIssue(line=line, message=message))

    def parse(self) -> SuiteResult:
        idx = 0
        total = len(self.lines)
        while idx < total:
            lineno, _indent, text = self.lines[idx]
            if not text:
                idx += 1
                continue
            match = _HEADER_RE.match(text)
            if match:
                self.header = f"{match.group(1)} version {match.group(2)}"
                if self.framework == "kunit" and match.group(1) == "TAP" \
                        and match.group(2) not in ("13", "14"):
                    self.issue(lineno, f"unexpected KUnit TAP version {match.group(2)}")
                if self.framework == "kselftest" and match.group(1) == "KTAP":
                    self.issue(lineno, "KTAP header in a kselftest stream")
                idx += 1
                break
            if _RESULT_RE.match(text) or _PLAN_RE.match(text):
                self.issue(lineno, "TAP content before any TAP/KTAP header")
                break
            self.preamble_lines += 1
            idx += 1
        if self.header is None and not any(
                i.message == "TAP content before any TAP/KTAP header"
                for i in self.issues):
            self.issue(None, "missing TAP/KTAP header: not a TAP stream")
            return SuiteResult(name="")
        if idx >= total:
            self.issue(None, "truncated stream: header present, no test plan or results")
            return SuiteResult(name="")
        base_indent = min(ind for _ln, ind, txt in self.lines[idx:] if txt)
        root, _next = self._parse_block(idx, base_indent, "")
        if self.declared_totals is not None:
            actual = totals_for(root.flatten())
            for key, want in self.declared_totals.items():
                if actual.get(key) != want:
                    self.issue(None,
                               f"declared Totals {key}:{want} disagrees with "
                               f"parsed {key}:{actual.get(key)}")
        return root

    def _parse_block(self, idx: int, base: int, name: str) -> Tuple[SuiteResult, int]:
        frame = _Frame(name)
        total = len(self.lines)
        while idx < total:
            if self.bail_out is not None:
                break
            lineno, indent, text = self.lines[idx]
            if not text:
                idx += 1
                continue
            if indent < base:
                break
            if indent > base:
                subtest_deep = _SUBTEST_RE.match(text)
                if subtest_deep:
                    deep_name = subtest_deep.group(1)[:MAX_NAME_CHARS]
                    sub, idx = self._parse_block(idx + 1, indent, deep_name)
                    idx = self._close_subtest(frame, sub, idx, base,
                                              expected_name=deep_name)
                    continue
                if _PLAN_RE.match(text):
                    sub, idx = self._parse_block(idx, indent, "")
                    idx = self._close_subtest(frame, sub, idx, base)
                    continue
                if frame.last_case is not None and text.startswith("#"):
                    self._add_diagnostic(frame, text)
                    idx += 1
                    continue
                self.issue(lineno, "unexpected indented line outside any subtest")
                idx += 1
                continue
            bail = _BAIL_RE.match(text)
            if bail:
                self.bail_out = bail.group(1).strip() or "Bail out!"
                idx += 1
                break
            subtest = _SUBTEST_RE.match(text)
            if subtest:
                sub_name = subtest.group(1)[:MAX_NAME_CHARS]
                idx += 1
                while idx < total and not self.lines[idx][2]:
                    idx += 1
                if idx < total and self.lines[idx][2] and self.lines[idx][1] > base:
                    sub, idx = self._parse_block(idx, self.lines[idx][1], sub_name)
                else:
                    sub = SuiteResult(name=sub_name)
                    self.issue(lineno, f"subtest {sub_name!r} has no body (truncated stream)")
                idx = self._close_subtest(frame, sub, idx, base,
                                          expected_name=sub_name)
                continue
            plan = _PLAN_RE.match(text)
            if plan:
                start, end = int(plan.group(1)), int(plan.group(2))
                if frame.plan_end is not None:
                    self.issue(lineno, "duplicate test plan in one suite")
                else:
                    if start != 1:
                        self.issue(lineno, f"test plan starts at {start}, not 1")
                    frame.plan_end = end
                    directive = (plan.group(3) or "").strip()
                    if end == 0:
                        frame.plan_directive = directive or None
                        if name == "" and directive.upper().startswith("SKIP"):
                            self.skip_all_reason = directive
                idx += 1
                continue
            totals = _TOTALS_RE.match(text)
            if totals:
                counts = _parse_counts(totals.group(1))
                if counts is None:
                    self.issue(lineno, "Totals line with no readable counts")
                elif name == "":
                    self.declared_totals = counts
                else:
                    frame.declared_totals = counts
                idx += 1
                continue
            summary = _SUITE_SUMMARY_RE.match(text)
            if summary:
                counts = {"passed": int(summary.group(2)),
                          "failed": int(summary.group(3)),
                          "skipped": int(summary.group(4) or 0),
                          "total": int(summary.group(5))}
                frame.declared_summary = counts
                idx += 1
                continue
            result = _RESULT_RE.match(text)
            if result:
                case = self._add_result(frame, result, lineno, is_suite_close=False)
                if case is not None:
                    if self.case_count >= MAX_CASES:
                        if not self.overflow_noted:
                            self.overflow_noted = True
                            self.issue(lineno, f"more than {MAX_CASES} cases; extra cases dropped")
                    else:
                        self.case_count += 1
                        frame.suite.cases.append(case)
                idx += 1
                continue
            if text.startswith("#"):
                self._add_diagnostic(frame, text)
                idx += 1
                continue
            self.issue(lineno, f"unrecognized line: {text[:80]!r}")
            idx += 1
        self._finalize(frame)
        return frame.suite, idx

    def _add_diagnostic(self, frame: _Frame, text: str) -> None:
        case = frame.last_case
        if case is None:
            return
        if len(case.diagnostics) >= MAX_DIAGNOSTICS:
            return
        object.__setattr__(case, "diagnostics",
                           case.diagnostics + (text[:MAX_NAME_CHARS],))

    def _add_result(self, frame: _Frame, match: "re.Match[str]",
                    lineno: int, is_suite_close: bool) -> Optional[TestCaseResult]:
        ok = match.group(1) == "ok"
        number = int(match.group(2))
        rest = match.group(3) or ""
        name, directive, reason, note = _split_result(rest)
        frame.result_count += 1
        if number != frame.result_count:
            self.issue(lineno,
                       f"result number {number} out of sequence "
                       f"(expected {frame.result_count})")
        outcome = _outcome_for(ok, directive)
        if directive == "TIMEOUT":
            outcome = "failed"
            reason = reason or "timeout"
        diagnostics: Tuple[str, ...] = ()
        if note:
            diagnostics = (f"# {note}"[:MAX_NAME_CHARS],)
            if reason is None and note.startswith("exit="):
                reason = note
        case = TestCaseResult(name=name or f"test-{number}", suite_path=(),
                              outcome=outcome, directive=directive,
                              reason=reason, diagnostics=diagnostics)
        frame.last_case = case
        return case

    def _close_subtest(self, frame: _Frame, sub: SuiteResult, idx: int,
                       base: int, expected_name: Optional[str] = None) -> int:
        total = len(self.lines)
        while idx < total and not self.lines[idx][2]:
            idx += 1
        if idx < total:
            lineno, indent, text = self.lines[idx]
            result = _RESULT_RE.match(text) if indent == base else None
            if result:
                holder = _Frame(frame.suite.name)
                holder.result_count = frame.result_count
                case = self._add_result(holder, result, lineno, is_suite_close=True)
                frame.result_count = holder.result_count
                frame.last_case = holder.last_case
                close_name = case.name if case else ""
                if expected_name is not None and close_name != expected_name:
                    self.issue(lineno,
                               f"subtest opened as {expected_name!r} closed "
                               f"as {close_name!r}")
                if not sub.name:
                    sub.name = close_name
                sub.outcome = case.outcome if case else None
                frame.suite.suites.append(sub)
                return idx + 1
        self.issue(None,
                   f"subtest {sub.name or expected_name!r} has no closing "
                   "result (truncated stream)")
        frame.suite.suites.append(sub)
        return idx

    def _finalize(self, frame: _Frame) -> None:
        if frame.plan_end is not None and frame.result_count != frame.plan_end:
            if frame.result_count < frame.plan_end:
                self.issue(None,
                           f"truncated stream: suite {frame.suite.name!r} planned "
                           f"{frame.plan_end} result(s), saw {frame.result_count}")
            else:
                self.issue(None,
                           f"suite {frame.suite.name!r} planned {frame.plan_end} "
                           f"result(s), saw {frame.result_count}")
        declared = frame.declared_summary or frame.declared_totals
        if declared is not None and frame.suite.name:
            actual = totals_for(frame.suite.flatten())
            for key, want in declared.items():
                if actual.get(key) != want:
                    self.issue(None,
                               f"suite {frame.suite.name!r} declared {key}:{want} "
                               f"disagrees with parsed {key}:{actual.get(key)}")


def detect_framework(text: str) -> Optional[str]:
    """Best-effort framework detection from a recorded TAP stream."""
    if not isinstance(text, str):
        raise MalformedRunError("detect_framework expects str input")
    for raw in text.splitlines()[:64]:
        line = raw.strip()
        if line.startswith("KTAP version"):
            return "kunit"
        if "# Subtest:" in line:
            return "kunit"
        if "selftests:" in line:
            return "kselftest"
        if line.startswith("TAP version 13"):
            return "kselftest"
        if line.startswith("TAP version 14"):
            return "kunit"
    return None


def parse_tap(text: str, framework: str = "auto",
              fixture: Optional[Dict[str, Any]] = None) -> RunReport:
    """Parse recorded TAP output into a RunReport.

    Malformed output is reported in the report (verdict malformed
    or error, parse_issues populated); it never raises and never
    reads as a pass. Only API misuse raises MalformedRunError.
    """
    if not isinstance(text, str):
        raise MalformedRunError("parse_tap expects the recorded output as str")
    clean_fixture = _validate_fixture(fixture)
    if framework == "auto":
        framework = detect_framework(text) or "kunit"
    if framework not in FRAMEWORKS:
        raise MalformedRunError(f"framework must be one of {FRAMEWORKS} or 'auto'")
    raw_sha = hashlib.sha256(text.encode("utf-8")).hexdigest()
    if len(text) > MAX_INPUT_CHARS:
        return RunReport(
            framework=framework, header=None, root=SuiteResult(name=""),
            parse_issues=[ParseIssue(
                line=None,
                message=f"input exceeds {MAX_INPUT_CHARS} chars; refused whole")],
            bail_out=None, raw_sha256=raw_sha, fixture=clean_fixture)
    parser = _Parser(text, framework)
    root = parser.parse()
    return RunReport(
        framework=framework, header=parser.header, root=root,
        parse_issues=parser.issues, bail_out=parser.bail_out,
        raw_sha256=raw_sha, declared_totals=parser.declared_totals,
        fixture=clean_fixture, preamble_lines=parser.preamble_lines,
        skip_all_reason=parser.skip_all_reason)


def parse_kunit_tap(text: str,
                    fixture: Optional[Dict[str, Any]] = None) -> RunReport:
    return parse_tap(text, framework="kunit", fixture=fixture)


def parse_kselftest_tap(text: str,
                        fixture: Optional[Dict[str, Any]] = None) -> RunReport:
    return parse_tap(text, framework="kselftest", fixture=fixture)


def ingest_text(text: str, framework: str = "auto",
                fixture: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Ingest recorded output; return the validated normalized record."""
    record = report_as_dict(parse_tap(text, framework=framework, fixture=fixture))
    return validate_report_dict(record)


def ingest_file(path: Any, framework: str = "auto",
                fixture: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Ingest a file of recorded TAP output (fixture/lab artifact)."""
    file_path = Path(path)
    try:
        text = file_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise MalformedRunError(f"cannot read recorded output {file_path}: {exc}")
    except UnicodeDecodeError as exc:
        raise MalformedRunError(f"recorded output {file_path} is not UTF-8: {exc}")
    return ingest_text(text, framework=framework, fixture=fixture)


_VERDICT_RANK = {"passed": 0, "skipped": 1, "failed": 2, "error": 3, "malformed": 4}


def summarize_runs(records: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Aggregate validated normalized records into one summary."""
    totals = {name: 0 for name in OUTCOMES}
    totals["total"] = 0
    verdict = "passed"
    summaries: List[Dict[str, Any]] = []
    for record in records:
        validate_report_dict(record)
        for key in totals:
            totals[key] += int(record["totals"].get(key, 0))
        if _VERDICT_RANK[record["verdict"]] > _VERDICT_RANK[verdict]:
            verdict = record["verdict"]
        summaries.append({
            "run_id": record["run_id"], "framework": record["framework"],
            "verdict": record["verdict"], "complete": record["complete"],
            "fixture_id": (record.get("fixture") or {}).get("fixture_id"),
        })
    if not records:
        verdict = "malformed"
    elif totals["total"] > 0 and totals["passed"] + totals["xpassed"] == 0 \
            and verdict == "passed":
        verdict = "skipped"
    return {
        "schema": KERNELTEST_SCHEMA,
        "schema_version": KERNELTEST_SCHEMA_VERSION,
        "runs": summaries,
        "run_count": len(summaries),
        "totals": totals,
        "verdict": verdict,
    }


def build_evidence_record(report: Any, *,
                          recorded_at: str,
                          incident_id: str,
                          host_local_id: str = "lab-guest-01",
                          boot_id: Optional[str] = None,
                          evidence_id: Optional[str] = None,
                          plan_id: Optional[str] = None,
                          hypothesis_id: Optional[str] = None,
                          tool_versions: Optional[Dict[str, str]] = None,
                          artifact_refs: Optional[List[str]] = None) -> Dict[str, Any]:
    """Render a report as a LIF-0004 v0.1 evidence record.

    Shaped for the banked evidence schema (kind test-run, which
    that schema requires to carry tool versions; source component
    lab). The content digest binds the normalized run record, so
    the default evidence id is reproduced by re-ingesting the
    identical output -- an identical run can never be silently
    double-counted in the append-only store.
    """
    record = report_as_dict(report) if isinstance(report, RunReport) else report
    validate_report_dict(record)
    if not _INCIDENT_RE.match(incident_id or ""):
        raise MalformedRunError("incident_id must match inc-[a-z0-9-]*")
    if plan_id is not None and not _PLAN_ID_RE.match(plan_id):
        raise MalformedRunError("plan_id must match plan-[a-z0-9-]*")
    if hypothesis_id is not None and not _HYP_ID_RE.match(hypothesis_id):
        raise MalformedRunError("hypothesis_id must match hyp-[a-z0-9-]*")
    digest = record["content_digest"].removeprefix("sha256:")
    eid = evidence_id or f"ev-kernellab-{digest[:12]}"
    source: Dict[str, Any] = {"component": "lab", "host_local_id": host_local_id}
    if boot_id:
        source["boot_id"] = boot_id
    totals = record["totals"]
    fixture = record.get("fixture") or {}
    fixture_note = fixture.get("fixture_id") or "no fixture metadata"
    limitations = [
        "fixture/lab scope: recorded TAP output only; no kernel was built "
        "or booted and no test binary was executed by this slice",
        f"verdict {record['verdict']}: {totals['passed']} passed, "
        f"{totals['failed']} failed, {totals['skipped']} skipped, "
        f"{totals['error']} error of {totals['total']} case(s)",
    ]
    if record["verdict"] == "malformed":
        limitations.append(
            "malformed output is reported as malformed; it is not a pass "
            "and not a verified kernel result")
    if record["verdict"] == "failed":
        limitations.append("a failed run is a verified failure, not a pass")
    for issue in record["parse_issues"][:8]:
        limitations.append(f"parse issue: {issue['message']}")
    versions: Dict[str, str] = {
        "python": platform.python_version(),
        "lifthrasir-kernellab": RUN_VERSION,
    }
    if tool_versions:
        versions.update({str(k): str(v) for k, v in tool_versions.items()})
    evidence: Dict[str, Any] = {
        "schema": "lifthrasir.evidence.v0.1",
        "schema_version": "0.1",
        "evidence_id": eid,
        "incident_id": incident_id,
        "kind": "test-run",
        "recorded_at": recorded_at,
        "source": source,
        "summary": (
            f"{record['framework']} run against {fixture_note}: verdict "
            f"{record['verdict']} ({totals['passed']}/{totals['total']} "
            f"passed, {totals['failed']} failed, {totals['skipped']} "
            f"skipped, run {record['run_id']})."),
        "content_digest": f"sha256:{digest}",
        "evidence_status": "lab-verified",
        "tool_versions": versions,
        "limitations": limitations,
    }
    if plan_id is not None:
        evidence["plan_id"] = plan_id
    if hypothesis_id is not None:
        evidence["hypothesis_id"] = hypothesis_id
    if artifact_refs:
        evidence["artifact_refs"] = list(artifact_refs)
    return evidence
