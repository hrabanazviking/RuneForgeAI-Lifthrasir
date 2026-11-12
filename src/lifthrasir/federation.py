"""Opt-in federation enrollment and privacy-reviewed export (LIF-1301).

Roadmap Book IV, phase P13: a voluntary distributed research network.
Federation exists to share *sanitized evidence and reproducible
experiments*, not to grant other computers control of this host
(roadmap/04; research/20). This module is the outbound half of that
bargain:

* Enrollment is opt-in, per data category, and time-boxed. A node
  enrolls under an operator-chosen contributor identifier, for an
  explicit list of shareable categories, with an explicit expiration
  and an export quota. Consent can be withdrawn at any moment; a
  withdrawn or expired enrollment can never export again.
* Export is privacy-reviewed. A package is built only for an active
  enrollment and only for a category the node opted into. Records
  pass through the banked LIF-0304 privacy machinery (retention
  filter BEFORE redaction, then a re-scan of the exact payload); if
  the re-scan still finds a covered pattern the export is refused
  outright. The resulting package is the exact payload a human
  inspects before any sharing: canonical JSON, content hashes, no
  hidden fields.

This module sends nothing. It has no network, subprocess or
filesystem machinery: it produces an inspectable package object, and
sharing that package is a separate human action (the LIF-0304 rule).

Only the shareable categories drawn from research/20's allowed
artifact types may be enrolled. Raw logs, private files, credentials,
unique machine identifiers, packet captures and shell commands are
refused by name, and unknown categories are refused too: the
category set is closed and fails shut.

Peer provenance and contradictory-evidence handling are LIF-1302 and
are deliberately not implemented here. Nothing in this module
accepts tasks, commands or policy changes from a peer; inbound peer
artifacts stay untrusted until reproduced locally.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Iterable, List, Mapping, Optional, Tuple

from .privacy import PrivacyError, Redactor, RetentionPolicy
from .privacy import build_export_preview

__all__ = [
    "FEDERATION_SCHEMA",
    "FEDERATION_SCHEMA_VERSION",
    "ENROLLMENT_SCHEMA",
    "SHAREABLE_CATEGORIES",
    "FORBIDDEN_CATEGORIES",
    "MAX_EXPORT_RECORDS",
    "FederationError",
    "MalformedEnrollmentError",
    "UnknownCategoryError",
    "ForbiddenCategoryError",
    "DuplicateNodeError",
    "NotEnrolledError",
    "EnrollmentExpiredError",
    "EnrollmentWithdrawnError",
    "CategoryNotEnrolledError",
    "CategoryMismatchError",
    "QuotaExceededError",
    "PrivacyReviewError",
    "MalformedPackageError",
    "Enrollment",
    "EnrollmentRegistry",
    "ExportPackage",
    "enroll_node",
    "enrollment_as_dict",
    "build_federation_export",
    "package_as_dict",
    "validate_export_package",
]

FEDERATION_SCHEMA = "lifthrasir.federation-export.v0.1"
FEDERATION_SCHEMA_VERSION = "0.1"
ENROLLMENT_SCHEMA = "lifthrasir.federation-enrollment.v0.1"

# research/20 "Allowed artifact types", as export categories.
SHAREABLE_CATEGORIES = (
    "benchmark-results",
    "candidate-packages",
    "code-revisions",
    "incident-summaries",
    "test-fixtures",
)

# research/20: "not acceptable automatic federation payloads".
FORBIDDEN_CATEGORIES = (
    "credentials",
    "machine-identifiers",
    "packet-captures",
    "private-files",
    "raw-logs",
    "shell-commands",
)

MAX_EXPORT_RECORDS = 1000

_NODE_ID_RE = re.compile(r"[a-z0-9][a-z0-9._-]*[a-z0-9]")
_TS_FORMAT = "%Y-%m-%dT%H:%M:%SZ"


class FederationError(Exception):
    """Base for every refusal raised by this module."""


class MalformedEnrollmentError(FederationError, ValueError):
    """An enrollment (or a timestamp given to one) is not well-formed."""


class UnknownCategoryError(FederationError, ValueError):
    """A data category outside the closed shareable set was named."""


class ForbiddenCategoryError(FederationError, ValueError):
    """A category research/20 bars from federation payloads was named."""


class DuplicateNodeError(FederationError):
    """A node id already holds a live enrollment in the registry."""


class NotEnrolledError(FederationError):
    """No (active) enrollment exists for the node at the given time."""


class EnrollmentExpiredError(FederationError):
    """The enrollment's explicit expiration has passed."""


class EnrollmentWithdrawnError(FederationError):
    """Consent for the enrollment was withdrawn; it is terminal."""


class CategoryNotEnrolledError(FederationError):
    """The node did not opt into the requested export category."""


class CategoryMismatchError(FederationError, ValueError):
    """A record declares a category different from the export's."""


class QuotaExceededError(FederationError):
    """The export exceeds the enrollment quota or the hard cap."""


class PrivacyReviewError(FederationError):
    """The post-redaction re-scan still finds covered patterns."""


class MalformedPackageError(FederationError, ValueError):
    """An export package (or the records offered for one) is malformed."""


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _require_aware(moment: Any, field: str) -> datetime:
    if not isinstance(moment, datetime):
        raise MalformedEnrollmentError(
            f"{field} must be a datetime, got {type(moment).__name__}")
    if moment.tzinfo is None or moment.utcoffset() is None:
        raise MalformedEnrollmentError(
            f"{field} must be timezone-aware; naive datetimes refused")
    return moment


def _format_ts(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).strftime(_TS_FORMAT)


def _parse_ts(text: Any, field: str) -> datetime:
    if not isinstance(text, str):
        raise MalformedPackageError(f"{field} must be an ISO timestamp")
    try:
        return datetime.strptime(text, _TS_FORMAT).replace(
            tzinfo=timezone.utc)
    except ValueError:
        raise MalformedPackageError(
            f"{field} is not a {_TS_FORMAT} timestamp: {text!r}")


def _check_node_id(node_id: Any, error=FederationError) -> str:
    """Contributor identifiers are operator-chosen and pseudonymous.

    They are never derived from the machine (research/20 bars unique
    machine IDs from federation payloads); this check enforces only
    shape: 3-64 chars, lowercase letters, digits, dot, dash,
    underscore, starting and ending alphanumeric.
    """
    if not isinstance(node_id, str) or not (3 <= len(node_id) <= 64) \
            or _NODE_ID_RE.fullmatch(node_id) is None:
        raise error(
            f"node_id must be 3-64 chars matching "
            f"[a-z0-9][a-z0-9._-]*[a-z0-9], got {node_id!r}")
    return node_id


def _check_category(category: Any) -> str:
    if category in FORBIDDEN_CATEGORIES:
        raise ForbiddenCategoryError(
            f"category {category!r} is barred from federation payloads "
            f"by research/20 and can never be enrolled or exported")
    if category not in SHAREABLE_CATEGORIES:
        raise UnknownCategoryError(
            f"unknown data category {category!r}; the shareable set is "
            f"closed: {', '.join(SHAREABLE_CATEGORIES)}")
    return category


# ---------------------------------------------------------------------
# Enrollment
# ---------------------------------------------------------------------

@dataclass(frozen=True)
class Enrollment:
    """One node's opt-in: categories, quota and explicit expiration.

    Immutable. Withdrawal produces a new Enrollment with
    ``withdrawn_at`` set; the withdrawn state is terminal for export.
    """

    node_id: str
    categories: Tuple[str, ...]
    enrolled_at: datetime
    expires_at: datetime
    max_records_per_export: int = 100
    withdrawn_at: Optional[datetime] = None

    def __post_init__(self) -> None:
        _check_node_id(self.node_id, MalformedEnrollmentError)
        _require_aware(self.enrolled_at, "enrolled_at")
        _require_aware(self.expires_at, "expires_at")
        if self.expires_at <= self.enrolled_at:
            raise MalformedEnrollmentError(
                "expires_at must be after enrolled_at; enrollment "
                "requires an explicit, future expiration")
        if isinstance(self.categories, str) or \
                not isinstance(self.categories, Iterable):
            raise MalformedEnrollmentError(
                "categories must be an iterable of category names")
        checked = sorted({_check_category(name)
                          for name in self.categories})
        if not checked:
            raise MalformedEnrollmentError(
                "an enrollment must opt into at least one category")
        object.__setattr__(self, "categories", tuple(checked))
        if isinstance(self.max_records_per_export, bool) or \
                not isinstance(self.max_records_per_export, int) or \
                not (1 <= self.max_records_per_export
                     <= MAX_EXPORT_RECORDS):
            raise MalformedEnrollmentError(
                f"max_records_per_export must be an int in "
                f"[1, {MAX_EXPORT_RECORDS}]")
        if self.withdrawn_at is not None:
            _require_aware(self.withdrawn_at, "withdrawn_at")
            if self.withdrawn_at < self.enrolled_at:
                raise MalformedEnrollmentError(
                    "withdrawn_at cannot precede enrolled_at")

    def status_at(self, moment: datetime) -> str:
        """One of 'withdrawn', 'expired', 'pending', 'active'."""
        _require_aware(moment, "moment")
        if self.withdrawn_at is not None and self.withdrawn_at <= moment:
            return "withdrawn"
        if moment < self.enrolled_at:
            return "pending"
        if moment >= self.expires_at:
            return "expired"
        return "active"

    def is_active(self, moment: datetime) -> bool:
        return self.status_at(moment) == "active"

    def withdraw(self, moment: datetime) -> "Enrollment":
        """Return a withdrawn copy. Withdrawal is terminal."""
        _require_aware(moment, "moment")
        if self.withdrawn_at is not None:
            raise EnrollmentWithdrawnError(
                f"node {self.node_id!r} already withdrew consent at "
                f"{_format_ts(self.withdrawn_at)}")
        if moment < self.enrolled_at:
            raise MalformedEnrollmentError(
                "cannot withdraw before the enrollment begins")
        return replace(self, withdrawn_at=moment)


def enroll_node(node_id: str, categories: Iterable[str], *,
                expires_at: datetime,
                enrolled_at: Optional[datetime] = None,
                max_records_per_export: int = 100) -> Enrollment:
    """Create an opt-in enrollment. Expiration is explicit, always."""
    return Enrollment(
        node_id=node_id,
        categories=tuple(categories),
        enrolled_at=enrolled_at if enrolled_at is not None
        else _utc_now(),
        expires_at=expires_at,
        max_records_per_export=max_records_per_export,
    )


def enrollment_as_dict(enrollment: Enrollment) -> Dict[str, Any]:
    """The inspectable enrollment record (no hidden fields)."""
    return {
        "schema": ENROLLMENT_SCHEMA,
        "node_id": enrollment.node_id,
        "categories": list(enrollment.categories),
        "enrolled_at": _format_ts(enrollment.enrolled_at),
        "expires_at": _format_ts(enrollment.expires_at),
        "max_records_per_export": enrollment.max_records_per_export,
        "withdrawn_at": (_format_ts(enrollment.withdrawn_at)
                         if enrollment.withdrawn_at is not None
                         else None),
    }


class EnrollmentRegistry:
    """In-memory registry of node enrollments, keyed by node id.

    A node id holding a live (non-withdrawn) enrollment cannot be
    re-enrolled: consent changes go through withdrawal first. After
    withdrawal the node may enroll again, and the fresh enrollment
    replaces the withdrawn record.
    """

    def __init__(self) -> None:
        self._by_node: Dict[str, Enrollment] = {}

    def __len__(self) -> int:
        return len(self._by_node)

    def __contains__(self, node_id: str) -> bool:
        return node_id in self._by_node

    def enroll(self, enrollment: Enrollment) -> Enrollment:
        existing = self._by_node.get(enrollment.node_id)
        if existing is not None and existing.withdrawn_at is None:
            raise DuplicateNodeError(
                f"node {enrollment.node_id!r} already holds an "
                f"enrollment; withdraw consent before re-enrolling")
        self._by_node[enrollment.node_id] = enrollment
        return enrollment

    def get(self, node_id: str) -> Enrollment:
        try:
            return self._by_node[node_id]
        except KeyError:
            raise NotEnrolledError(
                f"node {node_id!r} holds no enrollment")

    def withdraw(self, node_id: str, moment: datetime) -> Enrollment:
        withdrawn = self.get(node_id).withdraw(moment)
        self._by_node[node_id] = withdrawn
        return withdrawn

    def enrollments(self) -> Tuple[Enrollment, ...]:
        return tuple(self._by_node[key] for key in sorted(self._by_node))

    def active_enrollments(self, moment: datetime) -> Tuple[Enrollment, ...]:
        return tuple(item for item in self.enrollments()
                     if item.is_active(moment))


# ---------------------------------------------------------------------
# Privacy-reviewed export
# ---------------------------------------------------------------------

@dataclass
class ExportPackage:
    """The exact outgoing payload, built for human inspection.

    ``payload`` is the redacted record list exactly as it would be
    shared; ``payload_sha256`` and the package digest (see
    ``package_as_dict``) let any reviewer verify byte identity.
    Building a package sends nothing.
    """

    schema: str
    node_id: str
    category: str
    created_at: str
    consent_expires_at: str
    package_expires_at: str
    records_in: int
    records_included: int
    records_declared: int
    records_undeclared: int
    expired_excluded: Tuple[str, ...]
    findings_by_category: Dict[str, int]
    warnings: Tuple[str, ...]
    payload: List[Dict[str, Any]]
    payload_sha256: str

    @property
    def package_digest(self) -> str:
        return _package_digest(package_as_dict(self, include_digest=False))


def _canonical(data: Any) -> str:
    return json.dumps(data, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False)


def _package_digest(base: Mapping[str, Any]) -> str:
    return hashlib.sha256(_canonical(dict(base)).encode("utf-8")
                          ).hexdigest()


def package_as_dict(package: ExportPackage, *,
                    include_digest: bool = True) -> Dict[str, Any]:
    """Canonical dict form of a package; digest covers all of it."""
    base: Dict[str, Any] = {
        "schema": package.schema,
        "node_id": package.node_id,
        "category": package.category,
        "created_at": package.created_at,
        "consent_expires_at": package.consent_expires_at,
        "package_expires_at": package.package_expires_at,
        "records_in": package.records_in,
        "records_included": package.records_included,
        "records_declared": package.records_declared,
        "records_undeclared": package.records_undeclared,
        "expired_excluded": list(package.expired_excluded),
        "findings_by_category": dict(package.findings_by_category),
        "warnings": list(package.warnings),
        "payload": package.payload,
        "payload_sha256": package.payload_sha256,
    }
    if include_digest:
        base["package_digest"] = _package_digest(base)
    return base


def build_federation_export(enrollment: Enrollment,
                            records: Iterable[Any],
                            category: str, *,
                            now: datetime,
                            package_ttl: Optional[timedelta] = None,
                            redactor: Optional[Redactor] = None,
                            retention_policy: Optional[RetentionPolicy]
                            = None) -> ExportPackage:
    """Build a privacy-reviewed export package, or refuse by name.

    Gate order (each refusal names its reason): category is
    shareable -> consent is active at ``now`` -> category was opted
    into -> quota -> every record's declared category matches ->
    LIF-0304 retention-then-redaction preview -> post-redaction
    re-scan is clean. Nothing is sent; the package is the exact
    payload a human reviews and chooses to share.
    """
    _require_aware(now, "now")
    _check_category(category)
    status = enrollment.status_at(now)
    if status == "withdrawn":
        raise EnrollmentWithdrawnError(
            f"node {enrollment.node_id!r} withdrew consent at "
            f"{_format_ts(enrollment.withdrawn_at)}; export refused")
    if status == "expired":
        raise EnrollmentExpiredError(
            f"enrollment for node {enrollment.node_id!r} expired at "
            f"{_format_ts(enrollment.expires_at)}; export refused")
    if status != "active":
        raise NotEnrolledError(
            f"enrollment for node {enrollment.node_id!r} is not yet "
            f"active (starts {_format_ts(enrollment.enrolled_at)})")
    if category not in enrollment.categories:
        raise CategoryNotEnrolledError(
            f"node {enrollment.node_id!r} did not opt into category "
            f"{category!r}; enrolled: "
            f"{', '.join(enrollment.categories)}")
    items = list(records)
    if not items:
        raise MalformedPackageError(
            "an export package needs at least one record")
    if len(items) > MAX_EXPORT_RECORDS:
        raise QuotaExceededError(
            f"{len(items)} records exceed the hard cap of "
            f"{MAX_EXPORT_RECORDS} records per package")
    if len(items) > enrollment.max_records_per_export:
        raise QuotaExceededError(
            f"{len(items)} records exceed node "
            f"{enrollment.node_id!r}'s quota of "
            f"{enrollment.max_records_per_export} per export")
    declared = 0
    undeclared = 0
    for item in items:
        raw = getattr(item, "payload", item)
        if isinstance(raw, Mapping) and \
                isinstance(raw.get("category"), str):
            declared += 1
            if raw["category"] != category:
                raise CategoryMismatchError(
                    f"a record declares category "
                    f"{raw['category']!r} but the export category is "
                    f"{category!r}; mixed-category packages refused")
        else:
            undeclared += 1
    try:
        preview = build_export_preview(items, policy=retention_policy,
                                       redactor=redactor, now=now)
    except PrivacyError as exc:
        raise MalformedPackageError(str(exc)) from exc
    leftovers = preview.verify_clean(redactor)
    if leftovers:
        categories = sorted({finding.category
                             for finding in leftovers})
        raise PrivacyReviewError(
            f"privacy review failed: the redacted payload still "
            f"matches covered categories {categories}; export "
            f"refused (finding values are never reported)")
    package_expires = enrollment.expires_at
    if package_ttl is not None:
        if package_ttl <= timedelta(0):
            raise MalformedPackageError(
                "package_ttl must be a positive timedelta")
        package_expires = min(package_expires, now + package_ttl)
    return ExportPackage(
        schema=FEDERATION_SCHEMA,
        node_id=enrollment.node_id,
        category=category,
        created_at=_format_ts(now),
        consent_expires_at=_format_ts(enrollment.expires_at),
        package_expires_at=_format_ts(package_expires),
        records_in=preview.records_in,
        records_included=preview.records_included,
        records_declared=declared,
        records_undeclared=undeclared,
        expired_excluded=tuple(preview.expired_excluded),
        findings_by_category=dict(preview.findings_by_category),
        warnings=tuple(preview.warnings),
        payload=preview.payload,
        payload_sha256=preview.payload_sha256,
    )


def validate_export_package(data: Any) -> bool:
    """Shape, hash and consent-window gate for a package dict.

    Raises MalformedPackageError on any defect; returns True only
    when the digest, the payload hash and the bookkeeping all agree
    with the payload bytes. A package claiming numbers its payload
    contradicts does not validate.
    """
    if not isinstance(data, Mapping):
        raise MalformedPackageError(
            f"export package must be a mapping, got "
            f"{type(data).__name__}")
    package = dict(data)
    digest = package.pop("package_digest", None)
    if not isinstance(digest, str) or not digest:
        raise MalformedPackageError("package_digest is missing")
    if _package_digest(package) != digest:
        raise MalformedPackageError(
            "package_digest does not match the package contents")
    if package.get("schema") != FEDERATION_SCHEMA:
        raise MalformedPackageError(
            f"schema must be {FEDERATION_SCHEMA!r}")
    _check_node_id(package.get("node_id"), MalformedPackageError)
    if package.get("category") not in SHAREABLE_CATEGORIES:
        raise MalformedPackageError(
            f"category {package.get('category')!r} is not shareable")
    payload = package.get("payload")
    if not isinstance(payload, list) or \
            any(not isinstance(item, Mapping) for item in payload):
        raise MalformedPackageError(
            "payload must be a list of record mappings")
    payload_hash = hashlib.sha256(
        _canonical(payload).encode("utf-8")).hexdigest()
    if package.get("payload_sha256") != payload_hash:
        raise MalformedPackageError(
            "payload_sha256 does not match the payload bytes")
    for field in ("records_in", "records_included",
                  "records_declared", "records_undeclared"):
        value = package.get(field)
        if isinstance(value, bool) or not isinstance(value, int) \
                or value < 0:
            raise MalformedPackageError(
                f"{field} must be a non-negative int")
    if package["records_included"] != len(payload):
        raise MalformedPackageError(
            "records_included contradicts the payload length")
    if package["records_in"] < package["records_included"]:
        raise MalformedPackageError(
            "records_in cannot be below records_included")
    if package["records_declared"] + package["records_undeclared"] \
            != package["records_in"]:
        raise MalformedPackageError(
            "declared + undeclared records must equal records_in")
    created = _parse_ts(package.get("created_at"), "created_at")
    consent = _parse_ts(package.get("consent_expires_at"),
                        "consent_expires_at")
    expires = _parse_ts(package.get("package_expires_at"),
                        "package_expires_at")
    if expires > consent:
        raise MalformedPackageError(
            "package_expires_at cannot outlive the consent window")
    if expires < created:
        raise MalformedPackageError(
            "package_expires_at cannot precede created_at")
    excluded = package.get("expired_excluded")
    if not isinstance(excluded, list) or \
            any(not isinstance(item, str) for item in excluded):
        raise MalformedPackageError(
            "expired_excluded must be a list of record ids")
    findings = package.get("findings_by_category")
    if not isinstance(findings, Mapping) or any(
            not isinstance(key, str) or isinstance(value, bool)
            or not isinstance(value, int) or value < 0
            for key, value in findings.items()):
        raise MalformedPackageError(
            "findings_by_category must map category -> non-negative int")
    warnings = package.get("warnings")
    if not isinstance(warnings, list) or \
            any(not isinstance(item, str) for item in warnings):
        raise MalformedPackageError("warnings must be a list of strings")
    return True
