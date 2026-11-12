# SPDX-License-Identifier: GPL-2.0-only
"""Static-analysis and checkpatch reporting (LIF-0905).

The reporting layer for the P9 kernel lab: it ingests RECORDED
static-analysis and checkpatch-style outputs (fixture texts in the
real tools' formats) and normalizes them into one machine-readable,
evidence-shaped report.  It runs NO analyzer, executes nothing, and
modifies no code under analysis -- recorded outputs only.

Home justification: master roadmap section 4 and roadmap/03 (P9)
fix the kernel laboratory in the Python lab/test harness beside the
evidence machinery it feeds; the sibling LIF-0902 slice
(``lifthrasir.kernellab``) set the precedent of a ``src/lifthrasir``
module for P9 run-output normalization, and this slice follows it,
including the soak/kernellab ``build_evidence_record`` pattern
shaped to the banked LIF-0004 evidence schema
(docs/protocols/schemas/v0.1/evidence.schema.json).

Supported recorded formats (the tool name selects the grammar; the
grammar is never guessed silently):

- ``checkpatch``: Linux scripts/checkpatch.pl text output.
  A finding is a severity line (``ERROR:`` / ``WARNING:`` /
  ``CHECK:`` / ``NOTE:`` + message), followed by a location line
  (``#<patch-line>: FILE: <path>:<line>:``) and one context line of
  the flagged source.  The run ends with a declared summary
  (``total: X errors, Y warnings, Z checks, N lines checked``),
  which is cross-checked against the parsed findings.
- ``sparse``: sparse diagnostics, gcc-shaped
  (``<path>:<line>:<col>: warning: <message>``; severities
  warning / error / note).  Sparse carries no rule name, so the
  finding's rule is honestly None.
- ``coccinelle``: coccicheck report lines
  (``<path>:<line>:<col>-<endcol>: <SEVERITY>: <message>``).
  Coccicheck carries no rule name in this format either.
- ``clang-tidy``: clang-tidy diagnostics
  (``<path>:<line>:<col>: warning: <message> [<check-name>]``);
  the bracketed check name is the rule.  A bracketed ``-W...``
  compiler flag is likewise kept as the rule.

Honest accounting (the point of the slice):

- Malformed input is reported AS malformed (``parse_status``),
  never as zero findings.  Empty or whitespace-only input is
  malformed for every format: as recorded evidence it cannot
  distinguish "ran clean" from "never ran".  A legitimate zero
  exists only where the format carries positive proof of a clean
  run (a checkpatch summary declaring zero of everything).
- Unrecognized non-empty lines in the line-diagnostic formats are
  counted and carried as parse issues; if NO line parses, the
  report is malformed.  Checkpatch context lines never invent
  findings: only a severity line opens a finding.
- Checkpatch's declared totals are cross-checked against the
  deduplicated-by-occurrence parsed counts; any disagreement is a
  parse issue and marks the report malformed.
- Findings are deduplicated on the full tuple (tool, file, line,
  column, rule, severity, message); a collapsed finding keeps its
  occurrence count, so dedup never hides how often a finding was
  reported.  Findings differing in any tuple field -- including
  line -- never collapse.
- Severity is normalized by an explicit table and never silently
  defaulted: checkpatch ``CHECK`` stays ``check`` (it is not a
  compiler warning); an unrecognized severity word simply does not
  parse as a finding and surfaces as a parse issue instead.
- Paths or line numbers the recorded output does not carry stay
  None; nothing is inferred from a neighbouring finding.

Evidence-status honesty: the parsers are proven at fixture level
by this slice's tests on recorded outputs modelled on the
documented formats of the real tools.  No analyzer was run, no
finding was adjudicated a true positive, and no code was fixed.
"""

from __future__ import annotations

import hashlib
import json
import platform
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

ANALYSIS_SCHEMA = "lifthrasir.staticanalysis.v0.1"
ANALYSIS_SCHEMA_VERSION = "0.1"
REPORT_VERSION = "1"

TOOLS = ("checkpatch", "sparse", "coccinelle", "clang-tidy")
PARSE_STATUSES = ("ok", "malformed")
SEVERITIES = ("error", "warning", "check", "note", "unknown")

MAX_INPUT_CHARS = 1000000
MAX_FINDINGS = 10000
MAX_ISSUES = 64
MAX_MESSAGE_CHARS = 512

_INCIDENT_RE = re.compile(r"^inc-[a-z0-9][a-z0-9-]*$")
_ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")

# checkpatch grammar -------------------------------------------------
_CP_SEVERITY_RE = re.compile(
    r"^(ERROR|WARNING|CHECK|NOTE):\s+(.*)$")
_CP_LOCATION_RE = re.compile(
    r"^#(\d+): FILE:\s+(.*?):(\d+):\s*$")
_CP_TOTAL_RE = re.compile(
    r"^total:\s+(\d+) errors?,\s+(\d+) warnings?,"
    r"(?:\s+(\d+) checks?,)?\s+(\d+) (lines|files) checked\s*$")
_CP_TRAILER_PREFIX = "If any of the errors are false positives"

# line-diagnostic grammars ------------------------------------------
# The location is matched by one anchored regex per tool, severity
# only at its fixed slot -- never searched for inside the message,
# and never split positionally on ':' (paths may contain colons).
_LINE_DIAG_RE = re.compile(
    r"^(.*?):(\d+)(?::(\d+))?:\s+(fatal error|warning|error|note):"
    r"\s+(.*)$")
_COCCI_BARE_RE = re.compile(
    r"^(.*?):(\d+):(\d+)(?:-(\d+))?:\s+(.*)$")
_SKIP_LINE_RE = re.compile(
    r"^(In file included from |\d+ (warnings?|errors?) generated\.|"
    r"Suppressed \d+ warnings?|Use -header-filter=)")
_COCCI_RE = re.compile(
    r"^(.*?):(\d+):(\d+)(?:-(\d+))?:\s+(WARNING|ERROR|CHECK|NOTE):"
    r"\s+(.*)$")
_RULE_TAIL_RE = re.compile(r"^(.*?)\s*\[([^\[\]\s]+)\]\s*$")

_SEVERITY_MAP = {
    "ERROR": "error", "WARNING": "warning", "CHECK": "check",
    "NOTE": "note", "error": "error", "warning": "warning",
    "note": "note", "fatal error": "error",
}


class StaticAnalysisError(Exception):
    """Base class for static-analysis reporting errors."""


class UnknownToolError(StaticAnalysisError):
    """Raised when a caller names a tool this slice does not parse.

    An unknown tool is a programmer error, not data: it raises,
    while malformed recorded output is carried in the report.
    """


class OversizeInputError(StaticAnalysisError):
    """Raised when a recorded output exceeds MAX_INPUT_CHARS."""


@dataclass
class AnalysisFinding:
    """One normalized finding from a recorded analyzer output."""

    tool: str
    file: Optional[str]
    line: Optional[int]
    column: Optional[int]
    rule: Optional[str]
    severity: str
    message: str
    occurrences: int = 1

    def key(self) -> Tuple[Any, ...]:
        return (self.tool, self.file, self.line, self.column,
                self.rule, self.severity, self.message)

    def sort_key(self) -> Tuple[Any, ...]:
        return (self.file or "", self.line or 0, self.column or 0,
                self.tool or "", self.rule or "", self.severity,
                self.message)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "tool": self.tool, "file": self.file,
            "line": self.line, "column": self.column,
            "rule": self.rule, "severity": self.severity,
            "message": self.message, "occurrences": self.occurrences,
        }


@dataclass
class AnalysisParseIssue:
    """A way the recorded output failed to prove what it claims."""

    kind: str
    detail: str
    line_number: Optional[int] = None

    def to_dict(self) -> Dict[str, Any]:
        return {"kind": self.kind, "detail": self.detail,
                "line_number": self.line_number}


@dataclass
class AnalysisReport:
    """The normalized, evidence-shaped report for one recorded run."""

    tool: str
    parse_status: str
    findings: List[AnalysisFinding] = field(default_factory=list)
    parse_issues: List[AnalysisParseIssue] = field(default_factory=list)
    declared_totals: Optional[Dict[str, int]] = None
    duplicates_removed: int = 0
    total_occurrences: int = 0
    unparsed_lines: int = 0
    input_digest: str = ""
    source_name: Optional[str] = None

    @property
    def report_id(self) -> str:
        return f"sa-{self.input_digest[:12]}"

    def counts_by_severity(self) -> Dict[str, int]:
        counts: Dict[str, int] = {}
        for finding in self.findings:
            counts[finding.severity] = (
                counts.get(finding.severity, 0) + finding.occurrences)
        return counts

    def to_dict(self) -> Dict[str, Any]:
        return {
            "schema": ANALYSIS_SCHEMA,
            "schema_version": ANALYSIS_SCHEMA_VERSION,
            "report_version": REPORT_VERSION,
            "report_id": self.report_id,
            "tool": self.tool,
            "parse_status": self.parse_status,
            "source_name": self.source_name,
            "input_digest": f"sha256:{self.input_digest}",
            "findings": [f.to_dict() for f in self.findings],
            "findings_count": len(self.findings),
            "total_occurrences": self.total_occurrences,
            "duplicates_removed": self.duplicates_removed,
            "counts_by_severity": self.counts_by_severity(),
            "declared_totals": self.declared_totals,
            "unparsed_lines": self.unparsed_lines,
            "parse_issues": [i.to_dict() for i in self.parse_issues],
        }


_ANSI_RE = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")


def _clean(text: str) -> str:
    """Normalize recorded text: BOM, ANSI colour escapes (recorded
    output may retain them from a --color capture), CRLF and stray
    CR are removed before any grammar is applied."""
    if text.startswith("\ufeff"):
        text = text[1:]
    text = _ANSI_RE.sub("", text)
    return text.replace("\r\n", "\n").replace("\r", "\n")


def _issue(report: AnalysisReport, kind: str, detail: str,
           line_number: Optional[int] = None) -> None:
    if len(report.parse_issues) < MAX_ISSUES:
        report.parse_issues.append(
            AnalysisParseIssue(kind, detail, line_number))


def _finish(report: AnalysisReport,
            raw: List[AnalysisFinding]) -> AnalysisReport:
    """Deduplicate, sort deterministically, and total a report."""
    by_key: Dict[Tuple[Any, ...], AnalysisFinding] = {}
    for finding in raw:
        existing = by_key.get(finding.key())
        if existing is None:
            by_key[finding.key()] = finding
        else:
            existing.occurrences += 1
    report.findings = sorted(by_key.values(),
                             key=lambda f: f.sort_key())
    report.total_occurrences = len(raw)
    report.duplicates_removed = len(raw) - len(report.findings)
    if report.parse_issues:
        report.parse_status = "malformed"
    return report


def _base_report(tool: str, text: str,
                 source_name: Optional[str]) -> AnalysisReport:
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    return AnalysisReport(tool=tool, parse_status="ok",
                          input_digest=digest, source_name=source_name)


def parse_checkpatch(text: str,
                     source_name: Optional[str] = None
                     ) -> AnalysisReport:
    """Parse recorded checkpatch.pl output into a report."""
    report = _base_report("checkpatch", text, source_name)
    raw: List[AnalysisFinding] = []
    pending: Optional[Tuple[str, str, int]] = None  # sev, msg, lineno
    totals: Optional[Dict[str, int]] = None
    segment_start = 0  # raw index where the current total segment began
    for lineno, line in enumerate(text.split("\n"), start=1):
        sev = _CP_SEVERITY_RE.match(line)
        if sev:
            message = sev.group(2).strip()
            if message.startswith(_CP_TRAILER_PREFIX):
                continue  # the false-positives trailer is not a finding
            if pending is not None:
                # A severity line with no FILE: location is a real
                # checkpatch shape (commit-log findings); file and
                # line stay honestly null, never inferred.
                raw.append(AnalysisFinding(
                    "checkpatch", None, None, None, None,
                    pending[0], pending[1]))
            pending = (_SEVERITY_MAP[sev.group(1)],
                       message[:MAX_MESSAGE_CHARS], lineno)
            continue
        loc = _CP_LOCATION_RE.match(line)
        if loc:
            if pending is None:
                _issue(report, "orphan-location",
                       "FILE: location line without a preceding "
                       "severity line", lineno)
            else:
                raw.append(AnalysisFinding(
                    "checkpatch", loc.group(2), int(loc.group(3)),
                    None, None, pending[0], pending[1]))
                pending = None
            continue
        tot = _CP_TOTAL_RE.match(line)
        if tot:
            if pending is not None:
                raw.append(AnalysisFinding(
                    "checkpatch", None, None, None, None,
                    pending[0], pending[1]))
                pending = None
            declared = {"errors": int(tot.group(1)),
                        "warnings": int(tot.group(2)),
                        "checks": int(tot.group(3) or 0)}
            bucket = {"error": "errors", "warning": "warnings",
                      "check": "checks"}
            parsed = {"errors": 0, "warnings": 0, "checks": 0}
            for finding in raw[segment_start:]:
                key = bucket.get(finding.severity)
                if key:
                    parsed[key] += 1
            for key in ("errors", "warnings", "checks"):
                if declared[key] != parsed[key]:
                    _issue(report, "totals-mismatch",
                           f"declared total says {declared[key]} "
                           f"{key} but {parsed[key]} were parsed "
                           "in this segment; neither figure is "
                           "silently trusted", lineno)
            if totals is None:
                totals = dict(declared)
            else:
                for key in declared:
                    totals[key] += declared[key]
            unit_key = ("lines_checked" if tot.group(5) == "lines"
                        else "files_checked")
            totals[unit_key] = (totals.get(unit_key, 0)
                                + int(tot.group(4)))
            segment_start = len(raw)
            continue
        # Anything else (context source lines, the "has style
        # problems" / "ready for submission" trailers, blank lines)
        # is not a finding and never becomes one.
    if pending is not None:
        raw.append(AnalysisFinding(
            "checkpatch", None, None, None, None, pending[0],
            pending[1]))
    report.declared_totals = totals
    if totals is None:
        _issue(report, "missing-total",
               "no 'total:' summary line: the recorded output is "
               "truncated or is not checkpatch output; parsed "
               "findings are not a complete result")
    return _finish(report, raw)


def _parse_line_diagnostics(text: str, tool: str,
                            source_name: Optional[str]
                            ) -> AnalysisReport:
    """Parse sparse / coccicheck / clang-tidy recorded lines."""
    report = _base_report(tool, text, source_name)
    raw: List[AnalysisFinding] = []
    pattern = _COCCI_RE if tool == "coccinelle" else _LINE_DIAG_RE
    for lineno, line in enumerate(text.split("\n"), start=1):
        if not line.strip():
            continue
        if line[0] in " \t":
            continue  # indented continuation / excerpt / caret line
        if _SKIP_LINE_RE.match(line):
            continue  # include-stack prologue or run footer
        match = pattern.match(line)
        bare = False
        if match is None and tool == "coccinelle":
            match = _COCCI_BARE_RE.match(line)
            bare = match is not None
        if match is None:
            report.unparsed_lines += 1
            _issue(report, "unparsed-line",
                   f"line does not match the {tool} diagnostic "
                   f"grammar: {line.strip()[:120]!r}", lineno)
            continue
        if tool == "coccinelle":
            if bare:
                path, line_no, col, _endcol, message = match.groups()
                sev_norm = "unknown"  # never invented, never dropped
            else:
                path, line_no, col, _endcol, sev, message = \
                    match.groups()
                sev_norm = _SEVERITY_MAP[sev]
            rule = None
        else:
            path, line_no, col, sev, message = match.groups()
            sev_norm = _SEVERITY_MAP[sev]
            rule = None
            if tool == "clang-tidy":
                tail = _RULE_TAIL_RE.match(message.strip())
                if tail:
                    message, rule = tail.group(1), tail.group(2)
        raw.append(AnalysisFinding(
            tool, path, int(line_no),
            int(col) if col is not None else None, rule,
            sev_norm, message.strip()[:MAX_MESSAGE_CHARS]))
    if not raw and report.unparsed_lines == 0:
        _issue(report, "no-diagnostics",
               "no diagnostic lines at all: a line-format run that "
               "found nothing leaves no positive proof in its "
               "output, so this is not evidence of zero findings")
    return _finish(report, raw)


def parse_analysis_output(text: str, tool: str,
                          source_name: Optional[str] = None
                          ) -> AnalysisReport:
    """Parse one recorded analyzer output for a named tool.

    Malformed recorded output is DATA carried in the returned
    report (``parse_status == \"malformed\"``), never an exception
    and never a silent zero.  An unknown tool name or an oversize
    input is a caller error and raises.
    """
    if tool not in TOOLS:
        raise UnknownToolError(
            f"unknown tool {tool!r}; supported: {', '.join(TOOLS)}")
    if not isinstance(text, str):
        raise StaticAnalysisError("recorded output must be text")
    if len(text) > MAX_INPUT_CHARS:
        raise OversizeInputError(
            f"recorded output of {len(text)} chars exceeds the "
            f"{MAX_INPUT_CHARS}-char bound")
    cleaned = _clean(text)
    if not cleaned.strip():
        report = _base_report(tool, cleaned, source_name)
        _issue(report, "empty-input",
               "empty recorded output is not evidence of zero "
               "findings: it cannot distinguish a clean run from "
               "a run that never happened")
        return _finish(report, [])
    if tool == "checkpatch":
        return parse_checkpatch(cleaned, source_name)
    return _parse_line_diagnostics(cleaned, tool, source_name)


def ingest_text(text: str, tool: str,
                source_name: Optional[str] = None) -> AnalysisReport:
    """Ingest recorded output text (alias of parse_analysis_output)."""
    return parse_analysis_output(text, tool, source_name)


def ingest_file(path: str | Path, tool: str) -> AnalysisReport:
    """Ingest a recorded output file; undecodable bytes are replaced,
    never allowed to lose the whole file's findings."""
    file_path = Path(path)
    text = file_path.read_text(encoding="utf-8", errors="replace")
    return parse_analysis_output(text, tool, file_path.name)


def dedupe_findings(findings: Iterable[AnalysisFinding]
                    ) -> List[AnalysisFinding]:
    """Collapse exact duplicates, keeping occurrence counts."""
    by_key: Dict[Tuple[Any, ...], AnalysisFinding] = {}
    for finding in findings:
        existing = by_key.get(finding.key())
        if existing is None:
            by_key[finding.key()] = AnalysisFinding(
                finding.tool, finding.file, finding.line,
                finding.column, finding.rule, finding.severity,
                finding.message, finding.occurrences)
        else:
            existing.occurrences += finding.occurrences
    return sorted(by_key.values(), key=lambda f: f.sort_key())


def report_as_dict(report: AnalysisReport) -> Dict[str, Any]:
    return report.to_dict()


def validate_report_dict(data: Any) -> List[str]:
    """Shape gate for report dicts this module emits or ingests.

    Returns a list of problems (empty = the dict is well-shaped).
    """
    problems: List[str] = []
    if not isinstance(data, dict):
        return ["report is not an object"]
    if data.get("schema") != ANALYSIS_SCHEMA:
        problems.append("schema is not the static-analysis v0.1 schema")
    if data.get("tool") not in TOOLS:
        problems.append(f"unknown tool {data.get('tool')!r}")
    if data.get("parse_status") not in PARSE_STATUSES:
        problems.append("parse_status missing or unknown")
    findings = data.get("findings")
    if not isinstance(findings, list):
        problems.append("findings is not a list")
        return problems
    for idx, finding in enumerate(findings):
        if not isinstance(finding, dict):
            problems.append(f"finding {idx} is not an object")
            continue
        if finding.get("severity") not in SEVERITIES:
            problems.append(f"finding {idx} has unknown severity")
        if not isinstance(finding.get("message"), str) \
                or not finding["message"]:
            problems.append(f"finding {idx} has no message")
        line = finding.get("line")
        if line is not None and (not isinstance(line, int) or line < 1):
            problems.append(f"finding {idx} has an invalid line")
    if data.get("findings_count") != len(findings):
        problems.append("findings_count disagrees with findings list")
    if data.get("parse_status") == "malformed" \
            and not data.get("parse_issues"):
        problems.append("malformed report carries no parse issues")
    return problems


def summarize_reports(reports: Iterable[AnalysisReport]
                      ) -> Dict[str, Any]:
    """Combine per-tool reports into one deterministic summary.

    Findings are NOT deduplicated across tools: the same defect
    reported by two tools is corroboration, not a duplicate.
    """
    per_tool: Dict[str, Any] = {}
    total_findings = 0
    malformed: List[str] = []
    for report in sorted(reports, key=lambda r: (r.tool,
                                                 r.report_id)):
        per_tool[report.tool] = {
            "report_id": report.report_id,
            "parse_status": report.parse_status,
            "findings_count": len(report.findings),
            "total_occurrences": report.total_occurrences,
            "counts_by_severity": report.counts_by_severity(),
        }
        total_findings += len(report.findings)
        if report.parse_status == "malformed":
            malformed.append(report.tool)
    return {
        "schema": ANALYSIS_SCHEMA,
        "tools": per_tool,
        "total_findings": total_findings,
        "malformed_tools": malformed,
        "any_malformed": bool(malformed),
    }


def build_evidence_record(report: AnalysisReport, *,
                          recorded_at: str,
                          incident_id: str,
                          host_local_id: str = "lab-guest-01",
                          boot_id: Optional[str] = None,
                          evidence_id: Optional[str] = None
                          ) -> Dict[str, Any]:
    """Render a report as a LIF-0004 v0.1 evidence record.

    Kind ``test-run`` (the v0.1 schema requires tool versions for
    it), source component ``lab``.  The content digest covers the
    canonical report dict, so re-ingesting identical recorded
    output reproduces the identical record id.  The evidence
    status is ``reproducer``: fixture-level proof only -- no real
    analyzer run is claimed by construction.
    """
    if not _INCIDENT_RE.match(incident_id or ""):
        raise StaticAnalysisError(
            f"incident_id {incident_id!r} is not a v0.1 incident id")
    canonical = report.to_dict()
    material = json.dumps(canonical, sort_keys=True,
                          separators=(",", ":"),
                          ensure_ascii=False)
    digest = hashlib.sha256(material.encode("utf-8")).hexdigest()
    eid = evidence_id or f"ev-staticanalysis-{digest[:12]}"
    if not _ID_RE.match(eid.removeprefix("ev-")):
        raise StaticAnalysisError(
            f"evidence_id {eid!r} is not a v0.1 evidence id")
    source: Dict[str, Any] = {"component": "lab",
                              "host_local_id": host_local_id}
    if boot_id:
        source["boot_id"] = boot_id
    counts = report.counts_by_severity()
    counts_text = ", ".join(
        f"{sev}={counts[sev]}" for sev in sorted(counts)) or "none"
    limitations = [
        "recorded fixture output only: no analyzer was run by "
        "this module and no code under analysis was modified",
        "severities and messages are the recorded tool's claims; "
        "no finding was adjudicated a true or false positive",
        f"parse status {report.parse_status}: a malformed report "
        "is evidence about the recording, not about the code",
    ]
    if report.declared_totals is None and report.tool == "checkpatch":
        limitations.append(
            "no declared checkpatch totals were present to "
            "cross-check the parsed findings against")
    return {
        "schema": "lifthrasir.evidence.v0.1",
        "schema_version": "0.1",
        "evidence_id": eid,
        "incident_id": incident_id,
        "kind": "test-run",
        "recorded_at": recorded_at,
        "source": source,
        "summary": (
            f"Static-analysis report for {report.tool}: "
            f"{len(report.findings)} distinct findings "
            f"({report.total_occurrences} occurrences, "
            f"{report.duplicates_removed} duplicates removed; "
            f"by severity: {counts_text}); parse status "
            f"{report.parse_status}."),
        "content_digest": f"sha256:{digest}",
        "evidence_status": "reproducer",
        "tool_versions": {
            "python": platform.python_version(),
            "lifthrasir-staticanalysis": REPORT_VERSION,
            f"recorded-{report.tool}": "fixture (not run)",
        },
        "limitations": limitations,
        "artifact_refs": [f"sha256:{report.input_digest}"],
    }
