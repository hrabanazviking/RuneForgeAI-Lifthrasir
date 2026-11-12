"""Privacy redactor, local retention and export preview (LIF-0304).

SPDX-License-Identifier: GPL-2.0-only

Home justification: the Mimir memory plane lives in the core package
``src/lifthrasir/`` (LIF-0301 event store, LIF-0302 provenance,
LIF-0303 exact search; ADR-0002 process table gives the
``lifthrasir-indexer`` "redaction before indexing" and the P3
graduation gate in the master roadmap section 1 is "source
attribution, secret redaction, reproducible incident timeline").
Redaction, retention and export preview are the privacy surface of
that same memory plane (master roadmap invariant 5: user files and
private logs stay local by default; federation is opt-in and
requires a scrubbed-payload preview), so this module sits beside the
store -- not in ``lab/``, which ADR-0002 D2 reserves for prototypes
whose contracts have not stabilised.  Like LIF-0303's search module,
it deliberately does NOT touch the package ``__init__`` export list:
the banking seat unions export lists, and a submodule import
(``from lifthrasir import privacy``) works either way, so this slice
can never conflict with another slice's exports.

What this slice builds (and what it does not):

- A deterministic, rule-based REDACTOR for text and for LIF-0004
  v0.1 record mappings (the shapes the LIF-0301 store persists and
  LIF-0303 searches).  It covers a NAMED, FINITE set of categories:
  credential assignments (``password=...``, ``token: ...`` and kin),
  ``Authorization: Bearer ...`` values, known token formats (GitHub
  ``ghp_``/``github_pat_``, AWS ``AKIA...``, OpenAI-style ``sk-...``,
  JWTs), PEM private-key blocks, email addresses, IPv4/IPv6
  addresses, MAC addresses, and the username component of
  ``/home/<user>/...`` and ``/Users/<user>/...`` paths.  A second,
  field-name rule replaces the whole value of any field whose name
  is a known sensitive name (``password``, ``api_key``, ``cookie``,
  ...) regardless of the value's shape.
- A local RETENTION policy evaluation: given records and a policy
  (maximum age and/or maximum dated-record count, with an injected
  clock), it reports which records are expired and why.  It never
  mutates its input and never deletes anything: the LIF-0301 store
  is append-only by design (ADR-0002 D4), so retention here governs
  exports and derived copies and FLAGS expired store records for a
  future human-governed purge; it does not reach into the store.
  Records with no parseable timestamp are NEVER expired by either
  rule -- what cannot be dated is kept and flagged, not dropped.
- An EXPORT PREVIEW builder: the only way this module lets records
  leave the local store's context.  It applies retention, redacts
  every included record, and returns the exact payload (canonical
  JSON text plus its SHA-256) with per-category finding counts and
  warnings, for a human to inspect before anything is shared
  (research/24: "enforce preview for outgoing artifacts"; roadmap/05:
  "export controls show actual payload").  There is deliberately NO
  send/upload/transmit function in this module at all.

HONESTY (master roadmap section 5; research/24 in the repo's own
words: "Treat regex-based scrubbing as fallible"):

- This redactor catches ONLY the categories listed above, in the
  shapes its tests pin.  Secrets in novel formats, secrets split
  across fields, natural-language disclosures ("the password is
  hunter two"), hostnames, usernames outside home paths, phone
  numbers, and free-text names are NOT caught and are NOT claimed.
  The preview exists precisely because the redactor is fallible:
  a clean preview scan means "no covered pattern remains", never
  "this payload contains no sensitive information".
- Findings never carry the redacted value: a finding is a category,
  a field name and (for text) a character span into the ORIGINAL
  text, so reports and logs built from findings cannot leak the
  secret they describe.
- Redaction is idempotent: redacting already-redacted output finds
  nothing and changes nothing.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field as _dc_field
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Mapping, Optional, Tuple

__all__ = [
    "CATEGORIES",
    "SENSITIVE_FIELDS",
    "PrivacyError",
    "Finding",
    "RedactionReport",
    "Redactor",
    "redact_text",
    "redact_record",
    "RetentionPolicy",
    "RetentionDecision",
    "RetentionReport",
    "evaluate_retention",
    "ExportPreview",
    "build_export_preview",
]


class PrivacyError(Exception):
    """Base class for named privacy refusals."""


# ---------------------------------------------------------------------
# Redactor
# ---------------------------------------------------------------------

#: Redaction categories this module covers.  Anything outside these
#: categories is out of scope and is never claimed as caught.
CATEGORIES = (
    "private-key",
    "credential",
    "token",
    "email",
    "ip-address",
    "mac-address",
    "username",
)

#: Field names (compared case-insensitively, on the last path
#: component) whose whole value is always redacted.
SENSITIVE_FIELDS = frozenset({
    "password", "passwd", "pwd", "secret", "token", "api_key",
    "apikey", "api-key", "access_token", "access_key", "auth",
    "authorization", "cookie", "set_cookie", "session_id",
    "private_key", "credential", "credentials",
})

_SENSITIVE_SUFFIXES = ("_password", "_token", "_secret", "_api_key")

_PLACEHOLDER = "[REDACTED:{category}]"


def _placeholder(category: str) -> str:
    return _PLACEHOLDER.format(category=category)


@dataclass(frozen=True)
class Finding:
    """One redaction.  Never carries the redacted value itself."""

    category: str
    field: Optional[str]  # record field path, or None for bare text
    start: Optional[int]  # span into the original field text
    end: Optional[int]


@dataclass
class RedactionReport:
    findings: List[Finding] = _dc_field(default_factory=list)

    @property
    def total(self) -> int:
        return len(self.findings)

    def by_category(self) -> Dict[str, int]:
        counts: Dict[str, int] = {}
        for finding in self.findings:
            counts[finding.category] = counts.get(finding.category, 0) + 1
        return dict(sorted(counts.items()))


# Pattern table: (category, compiled regex, replacement style).
# Styles: "whole" replaces the entire match; "value" replaces group
# "val" only, keeping the matched key/label prefix intact.
_PATTERNS: List[Tuple[str, "re.Pattern[str]", str]] = [
    ("private-key", re.compile(
        r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----.*?"
        r"-----END [A-Z0-9 ]*PRIVATE KEY-----", re.DOTALL), "whole"),
    ("credential", re.compile(
        r"(?i)\bBearer\s+(?P<val>[A-Za-z0-9._~+/=-]{8,})"), "value"),
    ("credential", re.compile(
        r"(?i)\b(?:password|passwd|pwd|secret|api[_-]?key|access[_-]?token"
        r"|auth[_-]?token|session[_-]?id|cookie)\b\s*[:=]\s*"
        r"(?P<val>\"[^\"]*\"|'[^']*'|[^\s,;]+)"), "value"),
    ("token", re.compile(
        r"\bgh[pousr]_[A-Za-z0-9]{20,}\b"
        r"|\bgithub_pat_[A-Za-z0-9_]{20,}"
        r"|\bAKIA[0-9A-Z]{16}\b"
        r"|\bsk-[A-Za-z0-9]{20,}\b"
        r"|\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\b"),
     "whole"),
    ("email", re.compile(
        r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"), "whole"),
    ("ip-address", re.compile(
        r"\b(?:[0-9A-Fa-f]{1,4}:){7}[0-9A-Fa-f]{1,4}\b"
        r"|\b(?:[0-9A-Fa-f]{1,4}:){1,6}:[0-9A-Fa-f]{1,4}"
        r"(?::[0-9A-Fa-f]{1,4})*\b"
        r"|\b::1\b"
        r"|\b(?:\d{1,3}\.){3}\d{1,3}\b"), "whole"),
    ("mac-address", re.compile(
        r"\b(?:[0-9A-Fa-f]{2}[:-]){5}[0-9A-Fa-f]{2}\b"), "whole"),
    ("username", re.compile(
        r"(?<=/home/)(?P<val>[^/\s]+)|(?<=/Users/)(?P<val2>[^/\s]+)"),
     "value"),
]


def _valid_ip(candidate: str) -> bool:
    """Guard the IP patterns against lookalikes (e.g. 999.1.1.1)."""
    if ":" in candidate:  # IPv6: at least one real hex group required
        return any(ch.isdigit() or ch in "abcdefABCDEF"
                   for ch in candidate.replace(":", ""))
    parts = candidate.split(".")
    return all(p.isdigit() and 0 <= int(p) <= 255 for p in parts)


class Redactor:
    """Rule-based redactor over the named CATEGORIES set.

    ``extra_patterns`` lets a user add local rules (research/24:
    "custom user rules"): an iterable of ``(category, regex)``
    pairs whose whole matches are replaced.  Extra categories must
    be new names; redefining a built-in category is refused.
    """

    def __init__(self, extra_patterns: Iterable[Tuple[str, str]] = ()):
        self._patterns = list(_PATTERNS)
        for category, pattern in extra_patterns:
            if category in CATEGORIES:
                raise PrivacyError(
                    f"extra pattern category {category!r} redefines a "
                    f"built-in category; choose a new name")
            self._patterns.append(
                (category, re.compile(pattern), "whole"))

    # -- text ------------------------------------------------------
    def redact_text(self, text: str,
                    field: Optional[str] = None
                    ) -> Tuple[str, List[Finding]]:
        """Redact one string; returns (redacted_text, findings).

        Spans in findings index the ORIGINAL text.  Substitutions are
        applied left-to-right through the pattern table in order, and
        each later pattern sees the output of the earlier ones, so a
        span claimed by an earlier (more specific) rule is never
        re-matched inside its placeholder.
        """
        if not isinstance(text, str):
            raise PrivacyError(
                f"redact_text expects str, got {type(text).__name__}")
        findings: List[Finding] = []
        # Every pattern runs over the ORIGINAL text and the claimed
        # spans are merged in order, so finding spans always index
        # the caller's original string, never a half-redacted one.
        spans: List[Tuple[int, int, str]] = []  # (start, end, category)
        for category, pattern, style in self._patterns:
            for match in pattern.finditer(text):
                if style == "value":
                    group = "val" if match.groupdict().get(
                        "val") is not None else "val2"
                    start, end = match.span(group)
                else:
                    start, end = match.span()
                if text[start:end].startswith("[REDACTED:"):
                    continue  # already redacted: idempotence guard
                if category == "ip-address" and not _valid_ip(
                        text[start:end]):
                    continue
                if any(start < e and s < end for s, e, _ in spans):
                    continue  # already claimed by an earlier rule
                spans.append((start, end, category))
        spans.sort()
        pieces: List[str] = []
        cursor = 0
        for start, end, category in spans:
            pieces.append(text[cursor:start])
            pieces.append(_placeholder(category))
            findings.append(Finding(category, field, start, end))
            cursor = end
        pieces.append(text[cursor:])
        return "".join(pieces), findings

    # -- records ---------------------------------------------------
    def redact_record(self, record: Mapping[str, Any]
                      ) -> Tuple[Dict[str, Any], RedactionReport]:
        """Deep-redact a record mapping; the input is never mutated.

        Walks the same field shape as LIF-0303's extractor: top-level
        fields, ``field[index]`` list items and ``field.key`` nested
        mappings (recursively).  A field whose last path component is
        a SENSITIVE_FIELDS name (or carries a sensitive suffix) has
        its whole scalar value replaced, whatever its shape.
        """
        if not isinstance(record, Mapping):
            raise PrivacyError(
                f"redact_record expects a mapping, got "
                f"{type(record).__name__}")
        report = RedactionReport()
        redacted = self._walk(dict(record), "", report)
        return redacted, report

    def _walk(self, value: Any, path: str,
              report: RedactionReport) -> Any:
        if isinstance(value, Mapping):
            return {key: self._walk(item, f"{path}.{key}" if path
                                    else str(key), report)
                    for key, item in value.items()}
        if isinstance(value, (list, tuple)):
            return [self._walk(item, f"{path}[{index}]", report)
                    for index, item in enumerate(value)]
        leaf = path.rsplit(".", 1)[-1].split("[", 1)[0].lower()
        if leaf in SENSITIVE_FIELDS or leaf.endswith(
                _SENSITIVE_SUFFIXES):
            if value is None:
                return value
            if isinstance(value, str) and value.startswith("[REDACTED:"):
                return value  # already redacted: idempotence guard
            report.findings.append(
                Finding("credential", path, None, None))
            return _placeholder("credential")
        if isinstance(value, str):
            new_text, findings = self.redact_text(value, field=path)
            report.findings.extend(findings)
            return new_text
        return value


_DEFAULT_REDACTOR = Redactor()


def redact_text(text: str) -> Tuple[str, List[Finding]]:
    """Redact one string with the default rule set."""
    return _DEFAULT_REDACTOR.redact_text(text)


def redact_record(record: Mapping[str, Any]
                  ) -> Tuple[Dict[str, Any], RedactionReport]:
    """Redact one record with the default rule set."""
    return _DEFAULT_REDACTOR.redact_record(record)


# ---------------------------------------------------------------------
# Retention
# ---------------------------------------------------------------------

_TIMESTAMP_FIELDS = ("created_at", "recorded_at", "observed_at",
                     "timestamp")
_ID_FIELDS = ("evidence_id", "incident_id", "hypothesis_id",
              "plan_id", "record_id", "id")


def _record_id(record: Any) -> str:
    payload = getattr(record, "payload", record)
    if isinstance(payload, Mapping):
        for name in _ID_FIELDS:
            value = payload.get(name)
            if isinstance(value, str) and value:
                return value
    record_id = getattr(record, "record_id", None)
    return record_id if isinstance(record_id, str) else "<unknown>"


def _record_timestamp(record: Any) -> Optional[datetime]:
    payload = getattr(record, "payload", record)
    candidates: List[Any] = []
    if isinstance(payload, Mapping):
        candidates.extend(payload.get(name)
                          for name in _TIMESTAMP_FIELDS)
    created = getattr(record, "created_at", None)
    if created is not None:
        candidates.append(created)
    for raw in candidates:
        if not isinstance(raw, str) or not raw:
            continue
        text = raw.strip()
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        try:
            parsed = datetime.fromisoformat(text)
        except ValueError:
            continue
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed
    return None


@dataclass(frozen=True)
class RetentionPolicy:
    """Local retention bounds.  At least one bound is required."""

    max_age_days: Optional[float] = None
    max_records: Optional[int] = None

    def __post_init__(self) -> None:
        if self.max_age_days is None and self.max_records is None:
            raise PrivacyError(
                "a retention policy needs at least one bound "
                "(max_age_days and/or max_records)")
        if self.max_age_days is not None and self.max_age_days < 0:
            raise PrivacyError("max_age_days must be >= 0")
        if self.max_records is not None and self.max_records < 0:
            raise PrivacyError("max_records must be >= 0")


@dataclass(frozen=True)
class RetentionDecision:
    record_id: str
    expired: bool
    reason: str  # "age", "count", "kept" or "unknown-age"


@dataclass
class RetentionReport:
    decisions: List[RetentionDecision]

    @property
    def kept_ids(self) -> List[str]:
        return [d.record_id for d in self.decisions if not d.expired]

    @property
    def expired_ids(self) -> List[str]:
        return [d.record_id for d in self.decisions if d.expired]

    @property
    def unknown_age_ids(self) -> List[str]:
        return [d.record_id for d in self.decisions
                if d.reason == "unknown-age"]


def evaluate_retention(records: Iterable[Any], policy: RetentionPolicy,
                       now: Optional[datetime] = None) -> RetentionReport:
    """Evaluate ``policy`` over ``records`` without mutating anything.

    Age rule: a dated record expires when its timestamp is strictly
    older than ``now - max_age_days``.  Count rule: among DATED
    records, the newest ``max_records`` are kept and older dated
    records expire.  Undated records are always kept, flagged
    ``unknown-age``, and do not consume the count budget (stated
    limitation: an undated flood is bounded by the age of nothing).
    Decisions come back in input order.
    """
    if now is None:
        now = datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    items = list(records)
    stamps = [_record_timestamp(item) for item in items]
    expired_reasons: Dict[int, str] = {}
    if policy.max_age_days is not None:
        from datetime import timedelta
        cutoff = now - timedelta(days=policy.max_age_days)
        for index, stamp in enumerate(stamps):
            if stamp is not None and stamp < cutoff:
                expired_reasons[index] = "age"
    if policy.max_records is not None:
        dated = sorted(
            (index for index, stamp in enumerate(stamps)
             if stamp is not None),
            key=lambda index: stamps[index], reverse=True)
        for index in dated[policy.max_records:]:
            expired_reasons.setdefault(index, "count")
    decisions = []
    for index, item in enumerate(items):
        record_id = _record_id(item)
        if index in expired_reasons:
            decisions.append(RetentionDecision(
                record_id, True, expired_reasons[index]))
        elif stamps[index] is None:
            decisions.append(RetentionDecision(
                record_id, False, "unknown-age"))
        else:
            decisions.append(RetentionDecision(record_id, False, "kept"))
    return RetentionReport(decisions)


# ---------------------------------------------------------------------
# Export preview
# ---------------------------------------------------------------------

@dataclass
class ExportPreview:
    """The exact payload a human reviews before any sharing."""

    payload: List[Dict[str, Any]]
    records_in: int
    expired_excluded: List[str]
    unknown_age_included: List[str]
    findings_by_category: Dict[str, int]
    warnings: List[str]

    def to_json(self) -> str:
        """Canonical JSON of the payload (sorted keys, compact)."""
        return json.dumps(self.payload, sort_keys=True,
                          separators=(",", ":"), ensure_ascii=False)

    @property
    def payload_sha256(self) -> str:
        return hashlib.sha256(self.to_json().encode("utf-8")).hexdigest()

    @property
    def records_included(self) -> int:
        return len(self.payload)

    def verify_clean(self, redactor: Optional[Redactor] = None
                     ) -> List[Finding]:
        """Re-scan the payload text; covered patterns must be gone.

        An empty result means no COVERED pattern remains.  It is not,
        and is never presented as, proof that the payload holds no
        sensitive information (see module docstring).
        """
        scanner = redactor or _DEFAULT_REDACTOR
        _, findings = scanner.redact_text(self.to_json())
        return findings


def build_export_preview(records: Iterable[Any],
                         policy: Optional[RetentionPolicy] = None,
                         redactor: Optional[Redactor] = None,
                         now: Optional[datetime] = None
                         ) -> ExportPreview:
    """Build a redacted, retention-filtered preview; sends nothing.

    Records may be LIF-0004 mappings or LIF-0301 ``StoredRecord``
    objects (duck-typed via ``payload``).  Expired records (when a
    policy is given) are excluded BEFORE redaction, so their content
    never enters the payload at all.
    """
    worker = redactor or _DEFAULT_REDACTOR
    items = list(records)
    expired: List[str] = []
    unknown_age: List[str] = []
    kept = items
    if policy is not None:
        report = evaluate_retention(items, policy, now=now)
        expired = report.expired_ids
        unknown_age = report.unknown_age_ids
        expired_set = set(expired)
        kept = [item for item in items
                if _record_id(item) not in expired_set]
    payload: List[Dict[str, Any]] = []
    counts: Dict[str, int] = {}
    for item in kept:
        raw = getattr(item, "payload", item)
        if not isinstance(raw, Mapping):
            raise PrivacyError(
                f"export preview needs record mappings, got "
                f"{type(raw).__name__}")
        redacted, report = worker.redact_record(raw)
        payload.append(redacted)
        for category, count in report.by_category().items():
            counts[category] = counts.get(category, 0) + count
    warnings: List[str] = []
    if unknown_age:
        warnings.append(
            f"{len(unknown_age)} record(s) carry no parseable "
            f"timestamp; retention could not date them and they are "
            f"included, flagged: {', '.join(unknown_age)}")
    if not counts:
        warnings.append(
            "no covered pattern was found; this is not proof the "
            "payload is free of sensitive information -- review the "
            "payload text before sharing")
    warnings.append(
        "preview only: nothing was sent anywhere; sharing this "
        "payload is a separate human action")
    return ExportPreview(
        payload=payload,
        records_in=items.__len__(),
        expired_excluded=expired,
        unknown_age_included=unknown_age,
        findings_by_category=dict(sorted(counts.items())),
        warnings=warnings,
    )
