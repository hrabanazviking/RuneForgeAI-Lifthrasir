"""Configuration validation and diff preview (LIF-0503).

SPDX-License-Identifier: GPL-2.0-only

Home justification: master roadmap section 3 places core
implementation in ``src/``; Eir's repair MVP (P5) needs, before any
repair recipe (LIF-0501) may propose editing a configuration, a
deterministic way to answer two questions about a PROPOSED config
text: (1) is it valid, and (2) exactly what would change? Those two
questions are this slice: a pure validator plus a diff preview.

What this slice is, and is not (evidence-status honesty):

- It VALIDATES caller-supplied config TEXT in three stdlib-parseable
  formats (``ini`` for systemd-unit/INI style, ``keyvalue`` for flat
  ``key=value`` files, ``json``) and reports every problem as a
  structured issue with a stable code and a 1-based line number.
- It PREVIEWS a change: given the current text and the proposed
  text it returns both digests, both validation reports, a
  key-level semantic change list, a unified text diff, and a
  verdict. A proposed text that fails validation yields verdict
  ``blocked-invalid`` and ``applicable=False``: the preview may be
  inspected, never applied on the strength of this module.
- It NEVER reads, writes, or modifies any file, and never touches a
  real host configuration. Inputs are in-memory copies (fixtures,
  guest copies, store records). There is deliberately no path-based
  apply API. Targets naming protected paths (master roadmap
  section 0 invariant 2, reusing the LIF-0401 protected list) or
  non-config target types are refused by name.
- Validation is SYNTACTIC plus the structural rules stated in
  docs/CONFIG-PREVIEW.md. It does not prove a config is semantically
  correct for its daemon, safe to run, or authorised: policy is
  LIF-0402, approval is LIF-0404, execution is the broker's job.

Resource caps (section 0 invariant 9): input size, line count and
key count are bounded; oversize input is refused, never truncated
silently. All output is deterministic: same inputs, same preview,
same rendering.
"""
from __future__ import annotations

import difflib
import hashlib
import json
import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from .actions import PROTECTED_PATH_PREFIXES

PREVIEW_VERSION = "0.1"
PREVIEW_SCHEMA = "lifthrasir.config-preview.v0.1"

FORMATS = ("ini", "keyvalue", "json")

MAX_TEXT_BYTES = 262144
MAX_LINES = 10000
MAX_KEYS = 4096

# Verdicts of a preview.
VERDICT_NO_CHANGE = "no-change"
VERDICT_READY = "ready"
VERDICT_BLOCKED_INVALID = "blocked-invalid"
VERDICT_BLOCKED_CURRENT = "blocked-current-invalid"
VERDICTS = (
    VERDICT_NO_CHANGE, VERDICT_READY,
    VERDICT_BLOCKED_INVALID, VERDICT_BLOCKED_CURRENT,
)

_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.@/-]*$")
_KEY_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")
_SECTION_RE = re.compile(r"^\[([^\[\]]+)\]$")


class ConfigPreviewError(Exception):
    """Base class for all named config-preview refusals."""


class MalformedConfigError(ConfigPreviewError):
    """Raised when a request itself is malformed (bad target/format)."""


class UnsupportedFormatError(ConfigPreviewError):
    """Raised for a format outside FORMATS (deny by default)."""


class ProtectedTargetError(ConfigPreviewError):
    """Raised when the target names a protected path (roadmap s.0)."""


class OversizeConfigError(ConfigPreviewError):
    """Raised when an input exceeds a resource cap."""


@dataclass(frozen=True)
class ValidationIssue:
    code: str
    line: int
    message: str
    severity: str = "error"  # "error" or "warning"

    def to_dict(self) -> dict:
        return {"code": self.code, "line": self.line,
                "message": self.message, "severity": self.severity}


@dataclass
class ValidationReport:
    fmt: str
    digest: str
    issues: List[ValidationIssue] = field(default_factory=list)
    keys: int = 0

    @property
    def errors(self) -> List[ValidationIssue]:
        return [i for i in self.issues if i.severity == "error"]

    @property
    def warnings(self) -> List[ValidationIssue]:
        return [i for i in self.issues if i.severity == "warning"]

    @property
    def valid(self) -> bool:
        return not self.errors

    def to_dict(self) -> dict:
        return {"format": self.fmt, "digest": self.digest,
                "valid": self.valid, "keys": self.keys,
                "issues": [i.to_dict() for i in self.issues]}


@dataclass(frozen=True)
class ConfigChange:
    kind: str  # "added", "removed", "changed"
    key: str
    old: Optional[str]
    new: Optional[str]

    def to_dict(self) -> dict:
        return {"kind": self.kind, "key": self.key,
                "old": self.old, "new": self.new}


@dataclass
class DiffPreview:
    target_name: str
    fmt: str
    current_digest: str
    proposed_digest: str
    current_validation: ValidationReport
    proposed_validation: ValidationReport
    changes: List[ConfigChange]
    unified_diff: str
    verdict: str

    @property
    def applicable(self) -> bool:
        return self.verdict == VERDICT_READY

    @property
    def changed(self) -> bool:
        return bool(self.changes) or self.current_digest != self.proposed_digest

    def to_dict(self) -> dict:
        return {
            "schema": PREVIEW_SCHEMA,
            "target": self.target_name, "format": self.fmt,
            "current_digest": self.current_digest,
            "proposed_digest": self.proposed_digest,
            "current_validation": self.current_validation.to_dict(),
            "proposed_validation": self.proposed_validation.to_dict(),
            "changes": [c.to_dict() for c in self.changes],
            "verdict": self.verdict, "applicable": self.applicable,
        }


def _digest(text: str) -> str:
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()


def _check_caps(text: str, label: str) -> None:
    if not isinstance(text, str):
        raise MalformedConfigError(f"{label} config must be str text")
    if len(text.encode("utf-8")) > MAX_TEXT_BYTES:
        raise OversizeConfigError(
            f"{label} config exceeds {MAX_TEXT_BYTES} bytes")
    if text.count("\n") + 1 > MAX_LINES:
        raise OversizeConfigError(f"{label} config exceeds {MAX_LINES} lines")
    if "\x00" in text:
        raise MalformedConfigError(f"{label} config contains NUL bytes")


def _parse_ini(text: str) -> Tuple[Dict[str, str], List[ValidationIssue]]:
    entries: Dict[str, str] = {}
    first_seen: Dict[str, int] = {}
    issues: List[ValidationIssue] = []
    section: Optional[str] = None
    seen_sections = set()
    for lineno, raw in enumerate(text.splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("#") or line.startswith(";"):
            continue
        if line.startswith("["):
            m = _SECTION_RE.match(line)
            if not m or not m.group(1).strip():
                issues.append(ValidationIssue(
                    "bad-section-header", lineno,
                    f"malformed section header: {raw.strip()!r}"))
                section = None
                continue
            section = m.group(1).strip()
            if section in seen_sections:
                issues.append(ValidationIssue(
                    "duplicate-section", lineno,
                    f"section [{section}] repeated"))
            seen_sections.add(section)
            continue
        if "=" not in line:
            issues.append(ValidationIssue(
                "missing-equals", lineno,
                f"line is not a key=value assignment: {line!r}"))
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip()
        if not _KEY_RE.match(key):
            issues.append(ValidationIssue(
                "bad-key", lineno, f"invalid key name: {key!r}"))
            continue
        if section is None:
            issues.append(ValidationIssue(
                "key-outside-section", lineno,
                f"key {key!r} appears before any section header"))
            continue
        fq = f"{section}.{key}"
        if fq in entries:
            issues.append(ValidationIssue(
                "duplicate-key", lineno,
                f"key {fq!r} repeated (first defined on line "
                f"{first_seen[fq]})"))
            continue
        entries[fq] = value
        first_seen[fq] = lineno
        if value == "":
            issues.append(ValidationIssue(
                "empty-value", lineno,
                f"key {fq!r} has an empty value", severity="warning"))
    return entries, issues


def _parse_keyvalue(text: str) -> Tuple[Dict[str, str], List[ValidationIssue]]:
    entries: Dict[str, str] = {}
    first_seen: Dict[str, int] = {}
    issues: List[ValidationIssue] = []
    for lineno, raw in enumerate(text.splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("#") or line.startswith(";"):
            continue
        if line.startswith("["):
            issues.append(ValidationIssue(
                "unexpected-section", lineno,
                "section headers are not part of the keyvalue format"))
            continue
        if "=" not in line:
            issues.append(ValidationIssue(
                "missing-equals", lineno,
                f"line is not a key=value assignment: {line!r}"))
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip()
        if not _KEY_RE.match(key):
            issues.append(ValidationIssue(
                "bad-key", lineno, f"invalid key name: {key!r}"))
            continue
        if key in entries:
            issues.append(ValidationIssue(
                "duplicate-key", lineno,
                f"key {key!r} repeated (first defined on line "
                f"{first_seen[key]})"))
            continue
        entries[key] = value
        first_seen[key] = lineno
        if value == "":
            issues.append(ValidationIssue(
                "empty-value", lineno,
                f"key {key!r} has an empty value", severity="warning"))
    return entries, issues


def _flatten_json(obj, prefix: str, out: Dict[str, str]) -> None:
    if isinstance(obj, dict):
        if not obj:
            out[prefix] = "{}"
        for k in sorted(obj):
            child = f"{prefix}.{k}" if prefix else str(k)
            _flatten_json(obj[k], child, out)
    elif isinstance(obj, list):
        if not obj:
            out[prefix] = "[]"
        for i, item in enumerate(obj):
            _flatten_json(item, f"{prefix}[{i}]", out)
    else:
        out[prefix] = json.dumps(obj, sort_keys=True)


def _parse_json(text: str) -> Tuple[Dict[str, str], List[ValidationIssue]]:
    issues: List[ValidationIssue] = []
    dup_keys: List[str] = []

    def hook(pairs):
        obj = {}
        for k, v in pairs:
            if k in obj:
                dup_keys.append(k)
            obj[k] = v
        return obj

    try:
        data = json.loads(text, object_pairs_hook=hook)
    except json.JSONDecodeError as exc:
        issues.append(ValidationIssue(
            "json-syntax", exc.lineno,
            f"invalid JSON: {exc.msg} (column {exc.colno})"))
        return {}, issues
    for k in dup_keys:
        issues.append(ValidationIssue(
            "duplicate-key", 0, f"JSON object key {k!r} repeated"))
    if not isinstance(data, dict):
        issues.append(ValidationIssue(
            "json-top-level", 1,
            "top-level JSON value must be an object"))
        return {}, issues
    entries: Dict[str, str] = {}
    _flatten_json(data, "", entries)
    return entries, issues


_PARSERS = {"ini": _parse_ini, "keyvalue": _parse_keyvalue, "json": _parse_json}


def parse_config(text: str, fmt: str) -> Dict[str, str]:
    """Parse config text into a flat key->value map.

    Raises the named refusal for an unsupported format or oversize
    input. Syntax problems do NOT raise here; they are reported by
    validate_config -- parse_config returns the entries that could
    be read, so a preview can still show a diff for a broken text.
    """
    if fmt not in FORMATS:
        raise UnsupportedFormatError(f"unsupported config format: {fmt!r}")
    _check_caps(text, "config")
    entries, _ = _PARSERS[fmt](text)
    return entries


def validate_config(text: str, fmt: str) -> ValidationReport:
    """Validate config text; return a structured report (never raises
    for syntax problems -- they are the report's content). Raises only
    for unsupported format, oversize or NUL-bearing input."""
    if fmt not in FORMATS:
        raise UnsupportedFormatError(f"unsupported config format: {fmt!r}")
    _check_caps(text, "config")
    entries, issues = _PARSERS[fmt](text)
    if not text.strip():
        issues = [ValidationIssue(
            "empty-config", 1, "config text is empty")] + issues
    if len(entries) > MAX_KEYS:
        issues.append(ValidationIssue(
            "too-many-keys", 0,
            f"config defines more than {MAX_KEYS} keys"))
    issues.sort(key=lambda i: (i.line, i.code))
    return ValidationReport(fmt=fmt, digest=_digest(text),
                            issues=issues, keys=len(entries))


def _check_target(target_name, target_type) -> None:
    if target_type != "config-file":
        raise MalformedConfigError(
            f"diff preview covers config-file targets only, "
            f"got target type {target_type!r}")
    if not isinstance(target_name, str) or not target_name:
        raise MalformedConfigError("target name must be a non-empty string")
    if target_name.startswith("/"):
        for prefix in PROTECTED_PATH_PREFIXES:
            if target_name == prefix or target_name.startswith(prefix + "/"):
                raise ProtectedTargetError(
                    f"target {target_name!r} is under protected prefix "
                    f"{prefix!r} (roadmap section 0 invariant 2); "
                    f"preview a fixture/guest copy instead")
    if not _NAME_RE.match(target_name):
        raise MalformedConfigError(
            f"target name {target_name!r} has invalid characters")


def _semantic_changes(cur: Dict[str, str],
                      prop: Dict[str, str]) -> List[ConfigChange]:
    changes: List[ConfigChange] = []
    for key in sorted(set(cur) | set(prop)):
        if key not in cur:
            changes.append(ConfigChange("added", key, None, prop[key]))
        elif key not in prop:
            changes.append(ConfigChange("removed", key, cur[key], None))
        elif cur[key] != prop[key]:
            changes.append(ConfigChange("changed", key, cur[key], prop[key]))
    return changes


def preview_config_change(current_text: str, proposed_text: str, fmt: str,
                          target_name: str,
                          target_type: str = "config-file") -> DiffPreview:
    """Build the full preview: digests, both validations, semantic
    changes, unified diff, verdict. Pure: no file is read or written."""
    if fmt not in FORMATS:
        raise UnsupportedFormatError(f"unsupported config format: {fmt!r}")
    _check_target(target_name, target_type)
    _check_caps(current_text, "current")
    _check_caps(proposed_text, "proposed")
    cur_report = validate_config(current_text, fmt)
    prop_report = validate_config(proposed_text, fmt)
    cur_entries, _ = _PARSERS[fmt](current_text)
    prop_entries, _ = _PARSERS[fmt](proposed_text)
    changes = _semantic_changes(cur_entries, prop_entries)
    diff = "".join(difflib.unified_diff(
        current_text.splitlines(keepends=True),
        proposed_text.splitlines(keepends=True),
        fromfile=f"a/{target_name}", tofile=f"b/{target_name}"))
    if cur_report.digest == prop_report.digest:
        verdict = VERDICT_NO_CHANGE
    elif not prop_report.valid:
        verdict = VERDICT_BLOCKED_INVALID
    elif not cur_report.valid:
        verdict = VERDICT_BLOCKED_CURRENT
    else:
        verdict = VERDICT_READY
    return DiffPreview(
        target_name=target_name, fmt=fmt,
        current_digest=cur_report.digest,
        proposed_digest=prop_report.digest,
        current_validation=cur_report,
        proposed_validation=prop_report,
        changes=changes, unified_diff=diff, verdict=verdict)


def render_preview(preview: DiffPreview) -> str:
    """Deterministic plain-text rendering of a preview, for the
    approval surface (LIF-0404): the user never approves a change
    they cannot read. Sections: target, digests, validation,
    changes, diff, verdict."""
    lines = []
    lines.append(f"Config change preview ({PREVIEW_SCHEMA})")
    lines.append(f"Target: {preview.target_name} (format: {preview.fmt})")
    lines.append(f"Current digest:  {preview.current_digest}")
    lines.append(f"Proposed digest: {preview.proposed_digest}")
    for label, rep in (("Current", preview.current_validation),
                       ("Proposed", preview.proposed_validation)):
        if rep.valid:
            lines.append(f"Validation ({label}): OK ({rep.keys} keys)")
        else:
            lines.append(f"Validation ({label}): INVALID")
            for issue in rep.errors:
                lines.append(
                    f"  line {issue.line}: [{issue.code}] {issue.message}")
        for issue in rep.warnings:
            lines.append(
                f"  warning line {issue.line}: [{issue.code}] {issue.message}")
    if preview.changes:
        lines.append("Changes:")
        for c in preview.changes:
            if c.kind == "added":
                lines.append(f"  + {c.key} = {c.new}")
            elif c.kind == "removed":
                lines.append(f"  - {c.key} = {c.old}")
            else:
                lines.append(f"  ~ {c.key}: {c.old} -> {c.new}")
    else:
        lines.append("Changes: none")
    lines.append("Diff:")
    lines.append(preview.unified_diff.rstrip("\n") if preview.unified_diff else "(identical)")
    lines.append(f"Verdict: {preview.verdict} (applicable: {preview.applicable})")
    return "\n".join(lines) + "\n"
