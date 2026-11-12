"""Release support, incident response, governance, continuity (LIF-1601).

SPDX-License-Identifier: GPL-2.0-only

Home justification: Book IV P16 (ecosystem completion) and Book V
(quality, release engineering and governance), closing the master
roadmap's perpetual-maintenance section (section 11): after
completion the project still needs ongoing CVE review, model and
runtime updates, distro/ABI churn support, maintainer relations,
issue triage, reproducible release signing and regression testing --
"Self-evolution never removes the need for stewardship."  P16's own
words: build maintainership and support policy, stable external
plugin APIs, a transparent security process, release engineering
stewardship, onboarding documentation, recurring audits and
contributor accessibility, so that no one developer, service or AI
provider becomes an operational single point of failure.  Its
completion test: independent maintainers can build, test, run,
secure, troubleshoot and improve the system.

What this slice builds, in those terms:

- SUPPORT POLICY AS DATA (Book V, community and sustainability):
  every release carries an honest support tier -- officially tested,
  community tested, experimental or unsupported -- and a support
  window.  An officially tiered release whose window has closed
  reports end-of-life, never "supported": the effective status is
  recomputed from the record and the date, so a stale label cannot
  outlive its window.
- MAINTAINERSHIP AND CONTINUITY: areas (broker, policy, release,
  docs, ...) name a primary maintainer and backups.  The accountable
  primary must be a HUMAN maintainer -- an agent, bot or service
  identity is refused by name (AgentActorError): agents may draft
  and propose, they cannot be the steward of record (Book V: agents
  cannot certify release safety).  continuity_risks() recomputes
  the single-point-of-failure view from the records: a critical
  area with no human backup, or any area with no backup at all, is
  flagged by name, never averaged away.
- INCIDENT RESPONSE WITH COORDINATED DISCLOSURE: incidents move
  reported -> triaged -> mitigated -> closed, by human maintainers
  only, with no skipped states.  A SECURITY incident cannot be
  disclosed publicly before mitigation is recorded
  (DisclosureBlockedError) -- security findings follow responsible
  reporting rather than automatic public disclosure (Book V; master
  roadmap section 10 lists auto-posting a discovered vulnerability
  as a disqualifying failure mode).  Disclosure itself is a human
  act recorded on the incident; this module sends nothing.
- GOVERNANCE WITH NO SELF-APPROVAL: proposals (policy change,
  broker change, release acceptance, plugin removal, other) are
  decided by a human who is NOT the proposer (SelfApprovalError;
  Book V: changes to authorization policy cannot be approved by
  the same agent that proposed them).  Release acceptance
  additionally requires the full Book V release checklist to be
  complete (ChecklistIncompleteError).
- RECURRING AUDITS AND PLUGIN API STABILITY: audits carry due
  dates and overdue audits are reported, not forgotten; a plugin
  API may be deprecated only with a migration note, and removed
  only under an approved plugin-removal governance decision that
  names it as its subject.

All wire records are digest-pinned where they cross a trust
boundary (releases, incidents, proposals): the content digest is
recomputed at import and a tampered or mislabelled record is
refused by name.  The registry is in-memory and deterministic:
listings are in registration order and every derived view (support
matrix, continuity risks, open incidents, overdue audits, the
rendered report) is recomputed from the stored records, so no
cached verdict can drift from the record.

INTERFACE ASSUMPTION (recorded plainly per keeper order): this
slice depends ONLY on banked code.  LIF-1501 (experiment selection,
team-01) is unbanked and is not imported, referenced or assumed;
a release or experiment identifier here is a validated string
carried by the record itself.  Persistence through the LIF-0301
event store, live issue-tracker import and any sending of
anything are future work, not claimed here.

Evidence-status honesty: this module's own status is
``lab-verified (fixture level, one machine)`` -- the releases,
maintainers and incidents in ``tests/fixtures/lif1601/`` are
synthetic fixture data, not a real support organisation, and no
real disclosure, decision or removal is performed by anything
here.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List, Mapping, Optional, Tuple

STEWARDSHIP_SCHEMA = "lifthrasir.stewardship.v0.1"
STEWARDSHIP_SCHEMA_VERSION = "0.1"
EVIDENCE_STATUS = "lab-verified"
TIMESTAMP_FORMAT = "%Y-%m-%dT%H:%M:%SZ"

TIER_OFFICIALLY_TESTED = "officially-tested"
TIER_COMMUNITY_TESTED = "community-tested"
TIER_EXPERIMENTAL = "experimental"
TIER_UNSUPPORTED = "unsupported"
SUPPORT_TIERS = (
    TIER_OFFICIALLY_TESTED,
    TIER_COMMUNITY_TESTED,
    TIER_EXPERIMENTAL,
    TIER_UNSUPPORTED,
)
EFFECTIVE_SUPPORTED = "supported"
EFFECTIVE_EXPERIMENTAL = "experimental"
EFFECTIVE_END_OF_LIFE = "end-of-life"
EFFECTIVE_UNSUPPORTED = "unsupported"

ACTOR_KINDS = ("human", "agent", "bot", "service")
HUMAN_KIND = "human"
CRITICALITIES = ("critical", "standard")

INCIDENT_KINDS = ("security", "operational")
INCIDENT_SEVERITIES = ("critical", "high", "medium", "low")
INCIDENT_STATES = ("reported", "triaged", "mitigated", "closed")

PROPOSAL_KINDS = (
    "policy-change",
    "broker-change",
    "release-acceptance",
    "plugin-removal",
    "other",
)
GOVERNANCE_DECISIONS = ("approved", "rejected")
PROPOSAL_STATES = ("proposed", "approved", "rejected")

RELEASE_CHECKLIST = (
    "feature-risk-scope-reviewed",
    "changes-tied-to-issue-or-adr",
    "test-matrix-and-provenance-recorded",
    "recovery-and-uninstall-documented",
    "no-unsafe-default-permissions",
    "no-critical-security-gate-failure",
    "offline-mode-verified",
    "ui-copy-and-accessibility-reviewed",
    "schema-migration-and-rollback-tested",
    "reproducible-packages-and-checksums",
    "human-reviewer-accepts-release-notes",
    "supported-distros-and-exclusions-published",
)

AUDIT_KINDS = (
    "security-review",
    "release-audit",
    "license-audit",
    "accessibility-review",
    "continuity-review",
)
PLUGIN_STABILITIES = ("stable", "experimental", "deprecated", "removed")

MAX_SUMMARY_CHARS = 2000
MAX_TITLE_CHARS = 200
MAX_NOTE_CHARS = 2000
MAX_BACKUPS_PER_AREA = 8

_ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]*$")
_EMAIL_RE = re.compile(r"^[^@\s<>]+@[^@\s<>]+\.[^@\s<>]+$")
_SHA_RE = re.compile(r"^sha256:[a-f0-9]{64}$")
_VERSION_RE = re.compile(r"^\d+\.\d+\.\d+$")


class StewardshipError(Exception):
    """Base class for every refusal raised by this module."""


class MalformedStewardError(StewardshipError):
    """A wire record is structurally invalid."""


class DigestMismatchError(StewardshipError):
    """A record's content digest or derived id does not match its pin."""


class AgentActorError(StewardshipError):
    """A non-human actor attempted an act reserved for humans."""


class SelfApprovalError(StewardshipError):
    """A proposer attempted to decide their own proposal."""


class ChecklistIncompleteError(StewardshipError):
    """Release acceptance was approved with an incomplete checklist."""


class DisclosureBlockedError(StewardshipError):
    """A security incident was disclosed before mitigation."""


class IncidentTransitionError(StewardshipError):
    """An incident state transition is not allowed from its state."""


class ProposalStateError(StewardshipError):
    """A governance proposal was decided twice or out of order."""


class DuplicateStewardshipRecordError(StewardshipError):
    """A conflicting record reuses an existing identifier."""


class UnknownStewardshipRecordError(StewardshipError):
    """A referenced record does not exist in the registry."""


class ContinuityError(StewardshipError):
    """An area assignment breaks the continuity rules."""


def _parse_ts(value: Any, field_name: str) -> datetime:
    if not isinstance(value, str):
        raise MalformedStewardError(field_name + " must be a timestamp string")
    try:
        parsed = datetime.strptime(value, TIMESTAMP_FORMAT)
    except ValueError:
        raise MalformedStewardError(field_name + " is not a valid UTC timestamp")
    if parsed.strftime(TIMESTAMP_FORMAT) != value:
        raise MalformedStewardError(field_name + " is not in canonical format")
    return parsed


def _check_id(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not _ID_RE.match(value):
        raise MalformedStewardError(field_name + " is not a valid identifier")
    return value


def _check_text(value: Any, field_name: str, max_chars: int) -> str:
    if not isinstance(value, str) or not value.strip():
        raise MalformedStewardError(field_name + " must be non-empty text")
    if len(value) > max_chars:
        raise MalformedStewardError(field_name + " exceeds its size limit")
    return value


def _exact_keys(record: Any, keys: Tuple[str, ...], what: str) -> Mapping[str, Any]:
    if not isinstance(record, Mapping):
        raise MalformedStewardError(what + " must be an object")
    if set(record.keys()) != set(keys):
        raise MalformedStewardError(what + " has missing or extra keys")
    return record


def stewardship_digest(payload: Mapping[str, Any]) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class Maintainer:
    maintainer_id: str
    name: str
    email: str
    kind: str

    @property
    def is_human(self) -> bool:
        return self.kind == HUMAN_KIND


_MAINTAINER_KEYS = ("maintainer_id", "name", "email", "kind")


def make_maintainer(maintainer_id: str, name: str, email: str, kind: str) -> Dict[str, Any]:
    wire = {
        "maintainer_id": maintainer_id,
        "name": name,
        "email": email,
        "kind": kind,
    }
    maintainer_from_dict(wire)
    return wire


def maintainer_from_dict(record: Mapping[str, Any]) -> Maintainer:
    _exact_keys(record, _MAINTAINER_KEYS, "maintainer")
    maintainer_id = _check_id(record["maintainer_id"], "maintainer_id")
    name = _check_text(record["name"], "name", MAX_TITLE_CHARS)
    email = record["email"]
    if not isinstance(email, str) or not _EMAIL_RE.match(email):
        raise MalformedStewardError("email is not a valid address")
    if record["kind"] not in ACTOR_KINDS:
        raise MalformedStewardError("kind is not a known actor kind")
    return Maintainer(maintainer_id, name, email, record["kind"])


def maintainer_to_dict(maintainer: Maintainer) -> Dict[str, Any]:
    return {
        "maintainer_id": maintainer.maintainer_id,
        "name": maintainer.name,
        "email": maintainer.email,
        "kind": maintainer.kind,
    }


@dataclass(frozen=True)
class ReleaseRecord:
    version: str
    tier: str
    released_at: str
    support_until: Optional[str]
    content_digest: str


_RELEASE_KEYS = (
    "schema", "version", "tier", "released_at", "support_until",
    "content_digest",
)


def _release_payload(version, tier, released_at, support_until):
    return {
        "schema": STEWARDSHIP_SCHEMA,
        "version": version,
        "tier": tier,
        "released_at": released_at,
        "support_until": support_until,
    }


def make_release(version: str, tier: str, released_at: str,
                 support_until: Optional[str]) -> Dict[str, Any]:
    payload = _release_payload(version, tier, released_at, support_until)
    wire = dict(payload)
    wire["content_digest"] = stewardship_digest(payload)
    release_from_dict(wire)
    return wire


def release_from_dict(record: Mapping[str, Any]) -> ReleaseRecord:
    _exact_keys(record, _RELEASE_KEYS, "release")
    if record["schema"] != STEWARDSHIP_SCHEMA:
        raise MalformedStewardError("release schema mismatch")
    version = record["version"]
    if not isinstance(version, str) or not _VERSION_RE.match(version):
        raise MalformedStewardError("version is not a valid release version")
    if record["tier"] not in SUPPORT_TIERS:
        raise MalformedStewardError("tier is not a known support tier")
    released = _parse_ts(record["released_at"], "released_at")
    until_raw = record["support_until"]
    if record["tier"] in (TIER_OFFICIALLY_TESTED, TIER_COMMUNITY_TESTED):
        if until_raw is None:
            raise MalformedStewardError(
                "a tested tier must declare a support window end")
    if until_raw is not None:
        until = _parse_ts(until_raw, "support_until")
        if until <= released:
            raise MalformedStewardError(
                "support_until must be after released_at")
    digest = record["content_digest"]
    if not isinstance(digest, str) or not _SHA_RE.match(digest):
        raise MalformedStewardError("content_digest is not a sha256 pin")
    payload = _release_payload(version, record["tier"],
                               record["released_at"], until_raw)
    if stewardship_digest(payload) != digest:
        raise DigestMismatchError("release content digest does not match")
    return ReleaseRecord(version, record["tier"], record["released_at"],
                         until_raw, digest)


def release_to_dict(release: ReleaseRecord) -> Dict[str, Any]:
    return {
        "schema": STEWARDSHIP_SCHEMA,
        "version": release.version,
        "tier": release.tier,
        "released_at": release.released_at,
        "support_until": release.support_until,
        "content_digest": release.content_digest,
    }


def support_status_for(release: ReleaseRecord, at: str) -> Dict[str, Any]:
    """Effective support status of one release at a date (recomputed)."""
    moment = _parse_ts(at, "at")
    if release.tier == TIER_UNSUPPORTED:
        effective = EFFECTIVE_UNSUPPORTED
    elif release.tier == TIER_EXPERIMENTAL:
        if release.support_until is not None and moment > _parse_ts(
                release.support_until, "support_until"):
            effective = EFFECTIVE_END_OF_LIFE
        else:
            effective = EFFECTIVE_EXPERIMENTAL
    elif release.support_until is not None and moment > _parse_ts(
            release.support_until, "support_until"):
        effective = EFFECTIVE_END_OF_LIFE
    else:
        effective = EFFECTIVE_SUPPORTED
    return {
        "version": release.version,
        "declared_tier": release.tier,
        "effective_status": effective,
        "released_at": release.released_at,
        "support_until": release.support_until,
    }


@dataclass(frozen=True)
class AreaAssignment:
    area: str
    criticality: str
    primary_id: str
    backup_ids: Tuple[str, ...]


_AREA_KEYS = ("area", "criticality", "primary_id", "backup_ids")


def make_area(area: str, criticality: str, primary_id: str,
              backup_ids: List[str]) -> Dict[str, Any]:
    wire = {
        "area": area,
        "criticality": criticality,
        "primary_id": primary_id,
        "backup_ids": list(backup_ids),
    }
    area_from_dict(wire)
    return wire


def area_from_dict(record: Mapping[str, Any]) -> AreaAssignment:
    _exact_keys(record, _AREA_KEYS, "area assignment")
    area = _check_id(record["area"], "area")
    if record["criticality"] not in CRITICALITIES:
        raise MalformedStewardError("criticality is not known")
    primary = _check_id(record["primary_id"], "primary_id")
    backups = record["backup_ids"]
    if not isinstance(backups, list):
        raise MalformedStewardError("backup_ids must be a list")
    if len(backups) > MAX_BACKUPS_PER_AREA:
        raise MalformedStewardError("too many backups for one area")
    for entry in backups:
        _check_id(entry, "backup_id")
    if len(set(backups)) != len(backups):
        raise MalformedStewardError("backup_ids contain duplicates")
    if primary in backups:
        raise MalformedStewardError("primary cannot also be a backup")
    return AreaAssignment(area, record["criticality"], primary,
                          tuple(backups))


def area_to_dict(assignment: AreaAssignment) -> Dict[str, Any]:
    return {
        "area": assignment.area,
        "criticality": assignment.criticality,
        "primary_id": assignment.primary_id,
        "backup_ids": list(assignment.backup_ids),
    }


@dataclass
class IncidentRecord:
    incident_id: str
    kind: str
    severity: str
    summary: str
    reporter_id: str
    reported_at: str
    content_digest: str
    state: str = "reported"
    mitigation_note: Optional[str] = None
    mitigated_at: Optional[str] = None
    disclosed_at: Optional[str] = None
    closed_at: Optional[str] = None


_INCIDENT_KEYS = (
    "schema", "incident_id", "kind", "severity", "summary",
    "reporter_id", "reported_at", "content_digest",
)


def _incident_payload(kind, severity, summary, reporter_id, reported_at):
    return {
        "schema": STEWARDSHIP_SCHEMA,
        "kind": kind,
        "severity": severity,
        "summary": summary,
        "reporter_id": reporter_id,
        "reported_at": reported_at,
    }


def incident_id_for(payload: Mapping[str, Any]) -> str:
    return "inc-" + stewardship_digest(payload)[7:19]


def make_incident(kind: str, severity: str, summary: str, reporter_id: str,
                  reported_at: str) -> Dict[str, Any]:
    payload = _incident_payload(kind, severity, summary, reporter_id,
                                reported_at)
    wire = dict(payload)
    wire["incident_id"] = incident_id_for(payload)
    wire["content_digest"] = stewardship_digest(payload)
    incident_from_dict(wire)
    return wire


def incident_from_dict(record: Mapping[str, Any]) -> IncidentRecord:
    _exact_keys(record, _INCIDENT_KEYS, "incident")
    if record["schema"] != STEWARDSHIP_SCHEMA:
        raise MalformedStewardError("incident schema mismatch")
    if record["kind"] not in INCIDENT_KINDS:
        raise MalformedStewardError("kind is not a known incident kind")
    if record["severity"] not in INCIDENT_SEVERITIES:
        raise MalformedStewardError("severity is not known")
    summary = _check_text(record["summary"], "summary", MAX_SUMMARY_CHARS)
    reporter = _check_id(record["reporter_id"], "reporter_id")
    _parse_ts(record["reported_at"], "reported_at")
    digest = record["content_digest"]
    if not isinstance(digest, str) or not _SHA_RE.match(digest):
        raise MalformedStewardError("content_digest is not a sha256 pin")
    payload = _incident_payload(record["kind"], record["severity"], summary,
                                reporter, record["reported_at"])
    if stewardship_digest(payload) != digest:
        raise DigestMismatchError("incident content digest does not match")
    if record["incident_id"] != incident_id_for(payload):
        raise DigestMismatchError("incident_id does not match its content")
    return IncidentRecord(record["incident_id"], record["kind"],
                          record["severity"], summary, reporter,
                          record["reported_at"], digest)


def incident_to_dict(incident: IncidentRecord) -> Dict[str, Any]:
    return {
        "schema": STEWARDSHIP_SCHEMA,
        "incident_id": incident.incident_id,
        "kind": incident.kind,
        "severity": incident.severity,
        "summary": incident.summary,
        "reporter_id": incident.reporter_id,
        "reported_at": incident.reported_at,
        "content_digest": incident.content_digest,
    }


@dataclass
class GovernanceProposal:
    proposal_id: str
    kind: str
    subject: str
    title: str
    proposer_id: str
    created_at: str
    checklist: Dict[str, bool]
    content_digest: str
    state: str = "proposed"
    decided_by: Optional[str] = None
    decided_at: Optional[str] = None


_PROPOSAL_KEYS = (
    "schema", "proposal_id", "kind", "subject", "title", "proposer_id",
    "created_at", "checklist", "content_digest",
)


def _proposal_payload(kind, subject, title, proposer_id, created_at, checklist):
    return {
        "schema": STEWARDSHIP_SCHEMA,
        "kind": kind,
        "subject": subject,
        "title": title,
        "proposer_id": proposer_id,
        "created_at": created_at,
        "checklist": checklist,
    }


def proposal_id_for(payload: Mapping[str, Any]) -> str:
    return "prop-" + stewardship_digest(payload)[7:19]


def make_proposal(kind: str, subject: str, title: str, proposer_id: str,
                  created_at: str,
                  checklist: Optional[Mapping[str, bool]] = None) -> Dict[str, Any]:
    payload = _proposal_payload(kind, subject, title, proposer_id, created_at,
                                dict(checklist) if checklist else {})
    wire = dict(payload)
    wire["proposal_id"] = proposal_id_for(payload)
    wire["content_digest"] = stewardship_digest(payload)
    proposal_from_dict(wire)
    return wire


def proposal_from_dict(record: Mapping[str, Any]) -> GovernanceProposal:
    _exact_keys(record, _PROPOSAL_KEYS, "proposal")
    if record["schema"] != STEWARDSHIP_SCHEMA:
        raise MalformedStewardError("proposal schema mismatch")
    if record["kind"] not in PROPOSAL_KINDS:
        raise MalformedStewardError("kind is not a known proposal kind")
    subject = _check_id(record["subject"], "subject")
    title = _check_text(record["title"], "title", MAX_TITLE_CHARS)
    proposer = _check_id(record["proposer_id"], "proposer_id")
    _parse_ts(record["created_at"], "created_at")
    checklist = record["checklist"]
    if not isinstance(checklist, Mapping):
        raise MalformedStewardError("checklist must be an object")
    clean_checklist: Dict[str, bool] = {}
    for key, value in checklist.items():
        if key not in RELEASE_CHECKLIST:
            raise MalformedStewardError("checklist names an unknown item")
        if not isinstance(value, bool):
            raise MalformedStewardError("checklist values must be booleans")
        clean_checklist[key] = value
    if record["kind"] == "release-acceptance":
        if set(clean_checklist.keys()) != set(RELEASE_CHECKLIST):
            raise MalformedStewardError(
                "release acceptance requires the full release checklist")
    elif clean_checklist:
        raise MalformedStewardError(
            "only release-acceptance proposals carry a checklist")
    digest = record["content_digest"]
    if not isinstance(digest, str) or not _SHA_RE.match(digest):
        raise MalformedStewardError("content_digest is not a sha256 pin")
    payload = _proposal_payload(record["kind"], subject, title, proposer,
                                record["created_at"], clean_checklist)
    if stewardship_digest(payload) != digest:
        raise DigestMismatchError("proposal content digest does not match")
    if record["proposal_id"] != proposal_id_for(payload):
        raise DigestMismatchError("proposal_id does not match its content")
    return GovernanceProposal(record["proposal_id"], record["kind"], subject,
                              title, proposer, record["created_at"],
                              clean_checklist, digest)


def proposal_to_dict(proposal: GovernanceProposal) -> Dict[str, Any]:
    return {
        "schema": STEWARDSHIP_SCHEMA,
        "proposal_id": proposal.proposal_id,
        "kind": proposal.kind,
        "subject": proposal.subject,
        "title": proposal.title,
        "proposer_id": proposal.proposer_id,
        "created_at": proposal.created_at,
        "checklist": dict(proposal.checklist),
        "content_digest": proposal.content_digest,
    }


def checklist_complete(proposal: GovernanceProposal) -> bool:
    return all(proposal.checklist.get(item, False) for item in RELEASE_CHECKLIST)


@dataclass
class AuditRecord:
    audit_id: str
    kind: str
    subject: str
    due_at: str
    completed_at: Optional[str] = None
    completed_by: Optional[str] = None


_AUDIT_KEYS = ("audit_id", "kind", "subject", "due_at")


def make_audit(audit_id: str, kind: str, subject: str, due_at: str) -> Dict[str, Any]:
    wire = {"audit_id": audit_id, "kind": kind, "subject": subject,
            "due_at": due_at}
    audit_from_dict(wire)
    return wire


def audit_from_dict(record: Mapping[str, Any]) -> AuditRecord:
    _exact_keys(record, _AUDIT_KEYS, "audit")
    audit_id = _check_id(record["audit_id"], "audit_id")
    if record["kind"] not in AUDIT_KINDS:
        raise MalformedStewardError("kind is not a known audit kind")
    subject = _check_id(record["subject"], "subject")
    _parse_ts(record["due_at"], "due_at")
    return AuditRecord(audit_id, record["kind"], subject, record["due_at"])


def audit_to_dict(audit: AuditRecord) -> Dict[str, Any]:
    return {"audit_id": audit.audit_id, "kind": audit.kind,
            "subject": audit.subject, "due_at": audit.due_at}


@dataclass(frozen=True)
class PluginApiRecord:
    api_id: str
    version: str
    stability: str
    migration_note: Optional[str]


_PLUGIN_KEYS = ("api_id", "version", "stability", "migration_note")


def make_plugin_api(api_id: str, version: str, stability: str,
                    migration_note: Optional[str] = None) -> Dict[str, Any]:
    wire = {"api_id": api_id, "version": version, "stability": stability,
            "migration_note": migration_note}
    plugin_api_from_dict(wire)
    return wire


def plugin_api_from_dict(record: Mapping[str, Any]) -> PluginApiRecord:
    _exact_keys(record, _PLUGIN_KEYS, "plugin api")
    api_id = _check_id(record["api_id"], "api_id")
    version = record["version"]
    if not isinstance(version, str) or not _VERSION_RE.match(version):
        raise MalformedStewardError("version is not a valid api version")
    if record["stability"] not in PLUGIN_STABILITIES:
        raise MalformedStewardError("stability is not known")
    note = record["migration_note"]
    if note is not None:
        _check_text(note, "migration_note", MAX_NOTE_CHARS)
    if record["stability"] in ("deprecated", "removed") and not note:
        raise MalformedStewardError(
            "a deprecated or removed api must carry a migration note")
    if record["stability"] == "removed":
        raise MalformedStewardError(
            "an api is registered live; removal goes through governance")
    return PluginApiRecord(api_id, version, record["stability"], note)


def plugin_api_to_dict(plugin: PluginApiRecord) -> Dict[str, Any]:
    return {"api_id": plugin.api_id, "version": plugin.version,
            "stability": plugin.stability,
            "migration_note": plugin.migration_note}


class StewardshipRegistry:
    """In-memory stewardship registry; every view is recomputed."""

    def __init__(self) -> None:
        self._maintainers: Dict[str, Maintainer] = {}
        self._releases: Dict[str, ReleaseRecord] = {}
        self._areas: Dict[str, AreaAssignment] = {}
        self._incidents: Dict[str, IncidentRecord] = {}
        self._proposals: Dict[str, GovernanceProposal] = {}
        self._audits: Dict[str, AuditRecord] = {}
        self._plugins: Dict[str, PluginApiRecord] = {}
        self._removed_plugins: Dict[str, PluginApiRecord] = {}

    # -- maintainers -------------------------------------------------
    def register_maintainer(self, record: Mapping[str, Any]) -> Maintainer:
        maintainer = maintainer_from_dict(record)
        existing = self._maintainers.get(maintainer.maintainer_id)
        if existing is not None:
            if existing != maintainer:
                raise DuplicateStewardshipRecordError(
                    "maintainer id already registered with other data")
            return existing
        self._maintainers[maintainer.maintainer_id] = maintainer
        return maintainer

    def maintainer(self, maintainer_id: str) -> Maintainer:
        try:
            return self._maintainers[maintainer_id]
        except KeyError:
            raise UnknownStewardshipRecordError(
                "unknown maintainer: " + str(maintainer_id))

    def maintainers(self) -> List[Maintainer]:
        return list(self._maintainers.values())

    def _require_human(self, maintainer_id: str) -> Maintainer:
        actor = self.maintainer(maintainer_id)
        if not actor.is_human:
            raise AgentActorError(
                "actor " + actor.maintainer_id + " is not human; this act "
                "is reserved for human maintainers")
        return actor

    # -- releases ----------------------------------------------------
    def register_release(self, record: Mapping[str, Any]) -> ReleaseRecord:
        release = release_from_dict(record)
        existing = self._releases.get(release.version)
        if existing is not None:
            if existing != release:
                raise DuplicateStewardshipRecordError(
                    "release version already registered with other data")
            return existing
        self._releases[release.version] = release
        return release

    def release(self, version: str) -> ReleaseRecord:
        try:
            return self._releases[version]
        except KeyError:
            raise UnknownStewardshipRecordError(
                "unknown release: " + str(version))

    def releases(self) -> List[ReleaseRecord]:
        return list(self._releases.values())

    def support_matrix(self, at: str) -> List[Dict[str, Any]]:
        return [support_status_for(r, at) for r in self._releases.values()]

    # -- areas -------------------------------------------------------
    def assign_area(self, record: Mapping[str, Any]) -> AreaAssignment:
        assignment = area_from_dict(record)
        primary = self.maintainer(assignment.primary_id)
        if not primary.is_human:
            raise AgentActorError(
                "the accountable primary of an area must be human")
        for backup_id in assignment.backup_ids:
            self.maintainer(backup_id)
        existing = self._areas.get(assignment.area)
        if existing is not None and existing != assignment:
            raise DuplicateStewardshipRecordError(
                "area already assigned differently; use handover")
        self._areas[assignment.area] = assignment
        return assignment

    def handover_area(self, area: str, new_primary_id: str, decided_by: str,
                      at: str) -> AreaAssignment:
        _parse_ts(at, "at")
        self._require_human(decided_by)
        current = self._areas.get(area)
        if current is None:
            raise UnknownStewardshipRecordError("unknown area: " + str(area))
        new_primary = self.maintainer(new_primary_id)
        if not new_primary.is_human:
            raise AgentActorError(
                "the accountable primary of an area must be human")
        if new_primary_id == current.primary_id:
            raise ContinuityError("handover to the current primary is a no-op")
        backups = [b for b in current.backup_ids if b != new_primary_id]
        updated = AreaAssignment(area, current.criticality, new_primary_id,
                                 tuple(backups))
        self._areas[area] = updated
        return updated

    def areas(self) -> List[AreaAssignment]:
        return list(self._areas.values())

    def continuity_risks(self) -> List[Dict[str, Any]]:
        risks: List[Dict[str, Any]] = []
        for assignment in self._areas.values():
            human_backups = [
                b for b in assignment.backup_ids
                if self._maintainers.get(b) is not None
                and self._maintainers[b].is_human
            ]
            if not assignment.backup_ids:
                risks.append({
                    "area": assignment.area,
                    "criticality": assignment.criticality,
                    "risk": "single-point-of-failure",
                    "detail": "no backup maintainer at all",
                })
            elif assignment.criticality == "critical" and not human_backups:
                risks.append({
                    "area": assignment.area,
                    "criticality": assignment.criticality,
                    "risk": "no-human-backup",
                    "detail": "critical area has backups but none human",
                })
        return risks

    # -- incidents ---------------------------------------------------
    def register_incident(self, record: Mapping[str, Any]) -> IncidentRecord:
        incident = incident_from_dict(record)
        self.maintainer(incident.reporter_id)
        existing = self._incidents.get(incident.incident_id)
        if existing is not None:
            return existing
        self._incidents[incident.incident_id] = incident
        return incident

    def incident(self, incident_id: str) -> IncidentRecord:
        try:
            return self._incidents[incident_id]
        except KeyError:
            raise UnknownStewardshipRecordError(
                "unknown incident: " + str(incident_id))

    def incidents(self) -> List[IncidentRecord]:
        return list(self._incidents.values())

    def open_incidents(self) -> List[IncidentRecord]:
        return [i for i in self._incidents.values() if i.state != "closed"]

    def triage_incident(self, incident_id: str, by: str, at: str) -> IncidentRecord:
        _parse_ts(at, "at")
        self._require_human(by)
        incident = self.incident(incident_id)
        if incident.state != "reported":
            raise IncidentTransitionError(
                "only a reported incident can be triaged")
        incident.state = "triaged"
        return incident

    def record_mitigation(self, incident_id: str, by: str, note: str,
                          at: str) -> IncidentRecord:
        _parse_ts(at, "at")
        self._require_human(by)
        _check_text(note, "mitigation note", MAX_NOTE_CHARS)
        incident = self.incident(incident_id)
        if incident.state != "triaged":
            raise IncidentTransitionError(
                "only a triaged incident can be mitigated")
        incident.state = "mitigated"
        incident.mitigation_note = note
        incident.mitigated_at = at
        return incident

    def disclose_incident(self, incident_id: str, by: str,
                          at: str) -> IncidentRecord:
        moment = _parse_ts(at, "at")
        self._require_human(by)
        incident = self.incident(incident_id)
        if incident.disclosed_at is not None:
            raise IncidentTransitionError("incident is already disclosed")
        if incident.state == "reported":
            raise IncidentTransitionError(
                "an untriaged incident cannot be disclosed")
        if incident.kind == "security" and incident.state not in (
                "mitigated", "closed"):
            raise DisclosureBlockedError(
                "a security incident cannot be disclosed before "
                "mitigation is recorded (coordinated disclosure)")
        if moment < _parse_ts(incident.reported_at, "reported_at"):
            raise IncidentTransitionError(
                "disclosure cannot predate the report")
        incident.disclosed_at = at
        return incident

    def close_incident(self, incident_id: str, by: str,
                       at: str) -> IncidentRecord:
        _parse_ts(at, "at")
        self._require_human(by)
        incident = self.incident(incident_id)
        if incident.state != "mitigated":
            raise IncidentTransitionError(
                "only a mitigated incident can be closed")
        incident.state = "closed"
        incident.closed_at = at
        return incident

    # -- governance --------------------------------------------------
    def register_proposal(self, record: Mapping[str, Any]) -> GovernanceProposal:
        proposal = proposal_from_dict(record)
        self.maintainer(proposal.proposer_id)
        existing = self._proposals.get(proposal.proposal_id)
        if existing is not None:
            return existing
        self._proposals[proposal.proposal_id] = proposal
        return proposal

    def proposal(self, proposal_id: str) -> GovernanceProposal:
        try:
            return self._proposals[proposal_id]
        except KeyError:
            raise UnknownStewardshipRecordError(
                "unknown proposal: " + str(proposal_id))

    def proposals(self) -> List[GovernanceProposal]:
        return list(self._proposals.values())

    def decide_proposal(self, proposal_id: str, decider_id: str,
                        decision: str, at: str) -> GovernanceProposal:
        _parse_ts(at, "at")
        if decision not in GOVERNANCE_DECISIONS:
            raise MalformedStewardError("decision is not known")
        decider = self._require_human(decider_id)
        proposal = self.proposal(proposal_id)
        if proposal.state != "proposed":
            raise ProposalStateError("proposal has already been decided")
        if decider.maintainer_id == proposal.proposer_id:
            raise SelfApprovalError(
                "a proposal cannot be decided by its own proposer")
        if decision == "approved" and proposal.kind == "release-acceptance":
            if not checklist_complete(proposal):
                raise ChecklistIncompleteError(
                    "release acceptance requires the full release "
                    "checklist to be complete")
        proposal.state = decision
        proposal.decided_by = decider.maintainer_id
        proposal.decided_at = at
        return proposal

    # -- audits ------------------------------------------------------
    def register_audit(self, record: Mapping[str, Any]) -> AuditRecord:
        audit = audit_from_dict(record)
        existing = self._audits.get(audit.audit_id)
        if existing is not None:
            if (existing.kind, existing.subject, existing.due_at) != (
                    audit.kind, audit.subject, audit.due_at):
                raise DuplicateStewardshipRecordError(
                    "audit id already registered with other data")
            return existing
        self._audits[audit.audit_id] = audit
        return audit

    def complete_audit(self, audit_id: str, by: str, at: str) -> AuditRecord:
        _parse_ts(at, "at")
        self._require_human(by)
        audit = self._audits.get(audit_id)
        if audit is None:
            raise UnknownStewardshipRecordError(
                "unknown audit: " + str(audit_id))
        if audit.completed_at is not None:
            raise ProposalStateError("audit is already completed")
        audit.completed_at = at
        audit.completed_by = by
        return audit

    def audits(self) -> List[AuditRecord]:
        return list(self._audits.values())

    def overdue_audits(self, at: str) -> List[AuditRecord]:
        moment = _parse_ts(at, "at")
        return [
            a for a in self._audits.values()
            if a.completed_at is None
            and _parse_ts(a.due_at, "due_at") < moment
        ]

    # -- plugin apis ---------------------------------------------------
    def register_plugin_api(self, record: Mapping[str, Any]) -> PluginApiRecord:
        plugin = plugin_api_from_dict(record)
        existing = self._plugins.get(plugin.api_id)
        if existing is not None:
            if existing != plugin:
                raise DuplicateStewardshipRecordError(
                    "plugin api already registered with other data")
            return existing
        self._plugins[plugin.api_id] = plugin
        return plugin

    def plugin_apis(self) -> List[PluginApiRecord]:
        return list(self._plugins.values())

    def removed_plugin_apis(self) -> List[PluginApiRecord]:
        return list(self._removed_plugins.values())

    def remove_plugin_api(self, api_id: str, proposal_id: str, by: str,
                          migration_note: str, at: str) -> PluginApiRecord:
        _parse_ts(at, "at")
        self._require_human(by)
        _check_text(migration_note, "migration_note", MAX_NOTE_CHARS)
        plugin = self._plugins.get(api_id)
        if plugin is None:
            raise UnknownStewardshipRecordError(
                "unknown plugin api: " + str(api_id))
        proposal = self.proposal(proposal_id)
        if proposal.kind != "plugin-removal" or proposal.subject != api_id:
            raise ProposalStateError(
                "removal requires a plugin-removal proposal naming "
                "this api as its subject")
        if proposal.state != "approved":
            raise ProposalStateError(
                "removal requires an approved governance decision")
        removed = PluginApiRecord(plugin.api_id, plugin.version, "removed",
                                  migration_note)
        del self._plugins[api_id]
        self._removed_plugins[api_id] = removed
        return removed

    # -- summary -------------------------------------------------------
    def stewardship_summary(self, at: str) -> Dict[str, Any]:
        matrix = self.support_matrix(at)
        return {
            "schema": STEWARDSHIP_SCHEMA,
            "at": at,
            "maintainers": len(self._maintainers),
            "human_maintainers": sum(
                1 for m in self._maintainers.values() if m.is_human),
            "releases": len(matrix),
            "supported_releases": sum(
                1 for row in matrix
                if row["effective_status"] == EFFECTIVE_SUPPORTED),
            "end_of_life_releases": sum(
                1 for row in matrix
                if row["effective_status"] == EFFECTIVE_END_OF_LIFE),
            "areas": len(self._areas),
            "continuity_risks": len(self.continuity_risks()),
            "incidents": len(self._incidents),
            "security_incidents": sum(
                1 for i in self._incidents.values() if i.kind == "security"),
            "open_incidents": len(self.open_incidents()),
            "proposals": len(self._proposals),
            "pending_proposals": sum(
                1 for p in self._proposals.values()
                if p.state == "proposed"),
            "audits": len(self._audits),
            "overdue_audits": len(self.overdue_audits(at)),
            "plugin_apis": len(self._plugins),
            "removed_plugin_apis": len(self._removed_plugins),
        }


def render_stewardship_report(registry: StewardshipRegistry, at: str) -> str:
    """Deterministic markdown stewardship report (byte-identical)."""
    summary = registry.stewardship_summary(at)
    lines = [
        "# Stewardship report",
        "",
        "Schema: " + STEWARDSHIP_SCHEMA + " at " + at,
        "",
        "## Support matrix",
        "",
    ]
    for row in registry.support_matrix(at):
        lines.append("- " + row["version"] + ": " + row["declared_tier"]
                     + " -> " + row["effective_status"]
                     + " (until " + str(row["support_until"]) + ")")
    lines += ["", "## Continuity", ""]
    risks = registry.continuity_risks()
    if risks:
        for risk in risks:
            lines.append("- " + risk["area"] + ": " + risk["risk"]
                         + " -- " + risk["detail"])
    else:
        lines.append("- no continuity risks")
    lines += ["", "## Incidents", ""]
    if registry.incidents():
        for incident in registry.incidents():
            lines.append("- " + incident.incident_id + ": "
                         + incident.kind + "/" + incident.severity
                         + " state=" + incident.state
                         + " disclosed=" + str(incident.disclosed_at))
    else:
        lines.append("- no incidents")
    lines += [
        "",
        "## Totals",
        "",
        "- maintainers: " + str(summary["maintainers"])
        + " (human " + str(summary["human_maintainers"]) + ")",
        "- open incidents: " + str(summary["open_incidents"]),
        "- pending proposals: " + str(summary["pending_proposals"]),
        "- overdue audits: " + str(summary["overdue_audits"]),
        "",
    ]
    return "\n".join(lines)


def stewardship_evidence_record(registry: StewardshipRegistry,
                                at: str) -> Dict[str, Any]:
    """Master roadmap section 5 evidence record for this slice."""
    return {
        "schema": STEWARDSHIP_SCHEMA,
        "slice": "LIF-1601",
        "evidence_status": EVIDENCE_STATUS,
        "scope": "fixture-level stewardship registry on purpleraider",
        "summary": registry.stewardship_summary(at),
        "limitations": [
            "in-memory registry only; no persistence, tracker or transport",
            "fixture maintainers, releases and incidents are synthetic",
            "disclosure and decisions are records; nothing is sent",
            "no dependence on unbanked LIF-1501; identifiers are strings",
        ],
        "undo": "revert the LIF-1601 slice commit",
    }
