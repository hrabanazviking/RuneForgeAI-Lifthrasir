"""Peer provenance and contradictory-evidence handling (LIF-1302).

SPDX-License-Identifier: GPL-2.0-only

Home justification: Book IV P13 (the voluntary distributed research
network) shares *sanitized evidence and reproducible experiments*
between nodes; it never grants another computer control of a host.
The memory plane already owns local provenance for referenced
documents (LIF-0302, ``src/lifthrasir/provenance.py``); this module
is its federation-facing companion and sits beside it in
``src/lifthrasir/`` -- not in ``lab/``, which ADR-0002 D2 reserves
for prototypes whose contracts have not stabilised.  Node
enrollment and the opt-in export path are LIF-1301's slice; this
module deliberately does not depend on them: a contributor here is
a validated identifier string carried by the report itself, and
nothing in this module sends, uploads or transmits anything.

What this slice builds, in Book IV P13's own terms:

- PROVENANCE for every incoming peer artifact: WHO sent it
  (``contributor_id``), WHAT it is (a SHA-256 ``content_digest``
  over the canonical subject + claim + payload, recomputed and
  verified at ingest -- a tampered or mislabelled artifact is
  refused by name, never silently accepted), and WHEN it is valid
  (``issued_at`` / ``expires_at``; explicit expiration is enforced
  at ingest and by sweep).
- UNTRUSTED BY DEFAULT: every remote artifact is untrusted until
  reproduced locally (Book IV P13).  A report enters the registry
  in trust state ``untrusted`` whatever status it declares; the
  only road up is ``mark_reproduced`` with a locally recomputed
  digest that matches.  A declared evidence status above
  ``lab-verified`` is refused at the door: a peer cannot assert a
  rung (human-reviewed, deployed, upstream-accepted) that only
  local process can grant (master roadmap section 5).
- DUPLICATES detected, not double-counted: re-ingesting the same
  report is idempotent and flagged; identical content arriving
  from several contributors is grouped as one artifact with many
  carriers (``duplicates()``).
- CONTRADICTIONS preserved, never voted away: reports about the
  same subject with different claims put the subject in state
  ``disputed`` (``disputes()``), and it stays disputed while ANY
  usable contradictory report stands -- 19 agreeing peers do not
  outvote 1 dissenting peer into a false consensus (Book IV P13:
  "without voting disputed results into a false consensus").
  Withdrawing consent removes that contributor's reports from the
  usable set (they are retained, marked ``withdrawn``, for audit);
  expiration does the same by time.  Neither is a vote.
- NO CONTROL PATH: a peer payload is data, never a command.
  Payloads carrying command-like keys are refused by name
  (``UnsafePayloadError``), payloads carrying known sensitive
  field names are refused (``SensitivePayloadError``; data
  minimization -- payloads must be scrubbed before exchange, see
  the LIF-0304 export preview), and payload size and per-
  contributor volume are quota-capped (``PayloadTooLargeError`` /
  ``QuotaExceededError``).  No incoming peer artifact can bypass
  local authorization or cause an action: this module exposes no
  execution surface at all.

The registry is in-memory and deterministic: the clock is
injectable, all listings are in ingest order, and every derived
view (duplicates, disputes, subject status, summary) is recomputed
from the stored records, so no cached verdict can drift from the
record.  Persistence through the LIF-0301 event store is future
work and is not claimed here.

Evidence-status honesty: this module's own status is
``lab-verified (fixture level, one machine)`` -- the simulated
20-node network in ``tests/fixtures/lif1302/peers.json`` is a
fixture, not a live federation.  Records are claims with
provenance, not proofs.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Mapping, Optional, Tuple

from .privacy import SENSITIVE_FIELDS

PEER_SCHEMA = "lifthrasir.peer-provenance.v0.1"
PEER_SCHEMA_VERSION = "0.1"
EVIDENCE_STATUS = "lab-verified (fixture level, one machine)"
DIGEST_PREFIX = "sha256:"
TIMESTAMP_FORMAT = "%Y-%m-%dT%H:%M:%SZ"

# Trust states a stored record can be in.  ``untrusted`` is the only
# entry state; ``locally-reproduced`` is earned by a matching local
# reproduction; ``withdrawn`` and ``expired`` remove a report from
# the usable set without erasing it.
TRUST_STATES = ("untrusted", "locally-reproduced", "withdrawn", "expired")

# Derived per-subject states.  There is deliberately no "true" or
# "accepted" state: the strongest statement this module makes about
# a claim is that several distinct peers reported it and no usable
# report contradicts it (``corroborated``).
SUBJECT_STATUSES = ("unknown", "uncontested", "corroborated", "disputed")

# The master roadmap section 5 evidence ladder.  A peer report may
# DECLARE a rung, but only up to MAX_PEER_DECLARED_STATUS: the
# higher rungs name local human/process acts no remote artifact can
# perform on this node's behalf.
DECLARED_STATUSES = (
    "idea",
    "hypothesis",
    "reproducer",
    "lab-verified",
    "cross-platform-verified",
    "human-reviewed",
    "deployed-with-monitoring",
    "upstream-submitted",
    "upstream-accepted",
)
MAX_PEER_DECLARED_STATUS = "lab-verified"

# Payload keys that would make a "report" a command in disguise.
# Book IV P13: federation shares evidence, not control, so any of
# these at the top level of a payload refuses the whole report.
FORBIDDEN_PAYLOAD_KEYS = frozenset({
    "action", "actions", "command", "commands", "exec", "execute",
    "run", "script", "shell", "sudo", "system",
})

DEFAULT_MAX_PAYLOAD_BYTES = 16384
DEFAULT_MAX_REPORTS_PER_CONTRIBUTOR = 256

_REPORT_ID_HEX = 16


class PeerProvenanceError(Exception):
    """Base class for all named peer-provenance refusals."""


class MalformedReportError(PeerProvenanceError):
    """Raised when a peer report is structurally invalid."""


class DigestMismatchError(PeerProvenanceError):
    """Raised when a report's pinned digest != its content digest."""


class ExpiredReportError(PeerProvenanceError):
    """Raised when an expired report is ingested or relied on."""


class PayloadTooLargeError(PeerProvenanceError):
    """Raised when a payload exceeds the size quota."""


class UnsafePayloadError(PeerProvenanceError):
    """Raised when a payload carries command-like keys."""


class SensitivePayloadError(PeerProvenanceError):
    """Raised when a payload carries known sensitive field names."""


class QuotaExceededError(PeerProvenanceError):
    """Raised when a contributor exceeds the per-node report quota."""


class UnknownReportError(PeerProvenanceError):
    """Raised when a report id names no stored record."""


class ConsentWithdrawnError(PeerProvenanceError):
    """Raised when an operation relies on a withdrawn report."""


class ReproductionMismatchError(PeerProvenanceError):
    """Raised when a local reproduction's digest != the report's."""


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _format_ts(moment: datetime) -> str:
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc).strftime(TIMESTAMP_FORMAT)


def _parse_ts(text: Any, field_name: str) -> datetime:
    if not isinstance(text, str):
        raise MalformedReportError(
            f"{field_name} must be a timestamp string in "
            f"{TIMESTAMP_FORMAT} form, got {type(text).__name__}")
    try:
        parsed = datetime.strptime(text, TIMESTAMP_FORMAT)
    except ValueError:
        raise MalformedReportError(
            f"{field_name} {text!r} is not in {TIMESTAMP_FORMAT} "
            f"UTC form") from None
    return parsed.replace(tzinfo=timezone.utc)


def _canonical(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False)


def content_digest_for(subject: str, claim: str,
                       payload: Mapping[str, Any]) -> str:
    """The content hash that pins WHAT a report says (not who sent it).

    Two contributors sending the same subject + claim + payload
    produce the same content digest; that sameness is what duplicate
    detection groups on.  Provenance (who) is bound separately in
    the report id, so identical content from many peers is neither
    merged into one report nor mistaken for independent content.
    """
    body = _canonical({"claim": claim, "payload": payload,
                       "subject": subject})
    return DIGEST_PREFIX + hashlib.sha256(body.encode("utf-8")).hexdigest()


def report_id_for(contributor_id: str, content_digest: str) -> str:
    body = f"{contributor_id}|{content_digest}".encode("utf-8")
    return "pr-" + hashlib.sha256(body).hexdigest()[:_REPORT_ID_HEX]


def payload_size_bytes(payload: Mapping[str, Any]) -> int:
    return len(_canonical(payload).encode("utf-8"))


def _require_text(data: Mapping[str, Any], key: str) -> str:
    value = data.get(key)
    if not isinstance(value, str) or not value.strip():
        raise MalformedReportError(
            f"peer report field {key!r} must be a non-empty string, "
            f"got {value!r}")
    return value


def _check_payload(payload: Any, max_payload_bytes: int) -> Dict[str, Any]:
    """Validate a payload as inert evidence data, or refuse by name."""
    if not isinstance(payload, Mapping):
        raise MalformedReportError(
            f"peer report payload must be a mapping, got "
            f"{type(payload).__name__}")
    keys = {str(key) for key in payload.keys()}
    unsafe = sorted(keys & FORBIDDEN_PAYLOAD_KEYS)
    if unsafe:
        raise UnsafePayloadError(
            f"peer payload carries command-like key(s) {unsafe}; "
            f"federation shares evidence, not control -- a payload "
            f"is data and can never name an action")
    sensitive = sorted(keys & SENSITIVE_FIELDS)
    if sensitive:
        raise SensitivePayloadError(
            f"peer payload carries sensitive field name(s) "
            f"{sensitive}; data minimization requires payloads to "
            f"be scrubbed before exchange (LIF-0304 export preview)")
    size = payload_size_bytes(payload)
    if size > max_payload_bytes:
        raise PayloadTooLargeError(
            f"peer payload is {size} bytes, over the "
            f"{max_payload_bytes}-byte quota")
    return dict(payload)


@dataclass(frozen=True)
class PeerReport:
    """One incoming peer evidence artifact, provenance-pinned.

    ``content_digest`` covers subject + claim + payload only;
    ``report_id`` additionally binds the contributor, so the pair
    (who, what) is the report's identity.  Instances are normally
    built through :func:`make_report` (which computes the pins) or
    :func:`report_from_dict` (which verifies them).
    """

    report_id: str
    contributor_id: str
    subject: str
    claim: str
    payload: Dict[str, Any]
    content_digest: str
    issued_at: str
    expires_at: str
    declared_status: str = "hypothesis"


def make_report(contributor_id: str, subject: str, claim: str,
                payload: Mapping[str, Any], issued_at: str,
                expires_at: str,
                declared_status: str = "hypothesis",
                max_payload_bytes: int = DEFAULT_MAX_PAYLOAD_BYTES
                ) -> PeerReport:
    """Build a report with its provenance pins computed, validated
    exactly as :func:`report_from_dict` validates wire input."""
    data = {
        "contributor_id": contributor_id,
        "subject": subject,
        "claim": claim,
        "payload": payload,
        "issued_at": issued_at,
        "expires_at": expires_at,
        "declared_status": declared_status,
        "content_digest": content_digest_for(subject, claim, payload)
        if isinstance(payload, Mapping) else "",
    }
    return report_from_dict(data, max_payload_bytes=max_payload_bytes)


def report_from_dict(data: Any,
                     max_payload_bytes: int = DEFAULT_MAX_PAYLOAD_BYTES
                     ) -> PeerReport:
    """Validate wire input into a :class:`PeerReport`, or refuse by
    name.  The pinned digest is REQUIRED on the wire: provenance
    means the sender committed to the content hash, and a report
    whose recomputed digest differs is tampered or mislabelled."""
    if not isinstance(data, Mapping):
        raise MalformedReportError(
            f"peer report must be a mapping, got "
            f"{type(data).__name__}")
    contributor_id = _require_text(data, "contributor_id")
    subject = _require_text(data, "subject")
    claim = _require_text(data, "claim")
    issued_at = _require_text(data, "issued_at")
    expires_at = _require_text(data, "expires_at")
    issued = _parse_ts(issued_at, "issued_at")
    expires = _parse_ts(expires_at, "expires_at")
    if expires <= issued:
        raise MalformedReportError(
            f"peer report expires_at {expires_at!r} is not after "
            f"issued_at {issued_at!r}; explicit expiration must "
            f"bound a positive validity window")
    declared_status = data.get("declared_status", "hypothesis")
    if declared_status not in DECLARED_STATUSES:
        raise MalformedReportError(
            f"declared_status {declared_status!r} is not on the "
            f"evidence ladder {list(DECLARED_STATUSES)}")
    if DECLARED_STATUSES.index(declared_status) > DECLARED_STATUSES.index(
            MAX_PEER_DECLARED_STATUS):
        raise MalformedReportError(
            f"declared_status {declared_status!r} is above "
            f"{MAX_PEER_DECLARED_STATUS!r}, the highest rung a peer "
            f"report may declare; higher rungs are local acts, not "
            f"remote assertions")
    payload = _check_payload(data.get("payload"), max_payload_bytes)
    pinned = data.get("content_digest")
    if not isinstance(pinned, str) or not pinned:
        raise MalformedReportError(
            "peer report carries no content_digest; provenance "
            "requires the sender to pin the content hash")
    computed = content_digest_for(subject, claim, payload)
    if pinned != computed:
        raise DigestMismatchError(
            f"peer report pins content_digest {pinned!r} but its "
            f"subject + claim + payload hash to {computed!r}; the "
            f"artifact is tampered or mislabelled and is refused")
    report_id = report_id_for(contributor_id, computed)
    claimed_id = data.get("report_id")
    if claimed_id is not None and claimed_id != report_id:
        raise DigestMismatchError(
            f"peer report claims report_id {claimed_id!r} but "
            f"contributor + content pin {report_id!r}; the "
            f"artifact is mislabelled and is refused")
    return PeerReport(
        report_id=report_id,
        contributor_id=contributor_id,
        subject=subject,
        claim=claim,
        payload=payload,
        content_digest=computed,
        issued_at=issued_at,
        expires_at=expires_at,
        declared_status=declared_status,
    )


def report_to_dict(report: PeerReport) -> Dict[str, Any]:
    """Serialize a report to its wire mapping (round-trippable)."""
    return {
        "report_id": report.report_id,
        "contributor_id": report.contributor_id,
        "subject": report.subject,
        "claim": report.claim,
        "payload": dict(report.payload),
        "content_digest": report.content_digest,
        "issued_at": report.issued_at,
        "expires_at": report.expires_at,
        "declared_status": report.declared_status,
    }


@dataclass
class PeerRecord:
    """A stored report plus its local trust bookkeeping.

    The report itself is immutable; everything this node LEARNS
    about it (trust state, failed reproductions, duplicate resends)
    lives here, so the artifact and the local verdict never blur.
    """

    report: PeerReport
    trust_state: str = "untrusted"
    ingested_at: str = ""
    reproduction_failures: int = 0
    duplicate_ingests: int = 0


@dataclass(frozen=True)
class IngestResult:
    """Outcome of one ingest: the stored record, whether this
    ingest was a duplicate resend of an already-stored report, and
    the ids of OTHER stored reports carrying identical content."""

    record: PeerRecord
    duplicate: bool
    content_shared_with: Tuple[str, ...] = ()


@dataclass(frozen=True)
class DuplicateGroup:
    """One content digest carried by more than one stored report."""

    content_digest: str
    report_ids: Tuple[str, ...]
    contributor_ids: Tuple[str, ...]


@dataclass(frozen=True)
class Dispute:
    """One subject with two or more competing usable claims.

    A dispute is a RECORD, not a verdict: it names the subject,
    every competing claim, and which reports carry each claim, so a
    human or a local reproduction can engage the actual conflict.
    Nothing in this module picks a winner.
    """

    subject: str
    claims: Dict[str, Tuple[str, ...]]
    contributor_ids: Tuple[str, ...]

    @property
    def report_ids(self) -> Tuple[str, ...]:
        ids: List[str] = []
        for claim in sorted(self.claims):
            ids.extend(self.claims[claim])
        return tuple(ids)


class PeerEvidenceRegistry:
    """In-memory registry of peer evidence reports.

    Deterministic: an injectable clock, ingest-ordered listings,
    and derived views recomputed from the stored records on every
    call.  The registry grants nothing and executes nothing; it
    records provenance, tracks trust, detects duplicates and
    contradictions, and answers factual questions about them.
    """

    def __init__(self,
                 clock: Optional[Callable[[], datetime]] = None,
                 max_payload_bytes: int = DEFAULT_MAX_PAYLOAD_BYTES,
                 max_reports_per_contributor: int =
                 DEFAULT_MAX_REPORTS_PER_CONTRIBUTOR) -> None:
        self._clock = clock or _utc_now
        self._max_payload_bytes = max_payload_bytes
        self._max_reports_per_contributor = max_reports_per_contributor
        self._records: Dict[str, PeerRecord] = {}
        self._order: List[str] = []

    # -- internal helpers -------------------------------------------

    def _now(self) -> datetime:
        moment = self._clock()
        if moment.tzinfo is None:
            moment = moment.replace(tzinfo=timezone.utc)
        return moment.astimezone(timezone.utc)

    def _shared_content_ids(self, record: PeerRecord) -> Tuple[str, ...]:
        return tuple(
            other.report.report_id for other in self._ordered_records()
            if other.report.report_id != record.report.report_id
            and other.report.content_digest == record.report.content_digest)

    def _ordered_records(self) -> List[PeerRecord]:
        return [self._records[rid] for rid in self._order]

    # -- ingest ------------------------------------------------------

    def ingest(self, data: Any) -> IngestResult:
        """Take in one peer report (wire mapping or PeerReport).

        Refusals, all by name: malformed shape, digest mismatch,
        unsafe or sensitive payload, oversized payload, expired at
        arrival, per-contributor quota.  Re-ingesting an identical
        report is NOT an error: it returns the stored record with
        ``duplicate=True`` and bumps its resend counter, so a peer
        retrying after an outage never double-counts its evidence.
        """
        if isinstance(data, PeerReport):
            report = data
            _check_payload(report.payload, self._max_payload_bytes)
        else:
            report = report_from_dict(
                data, max_payload_bytes=self._max_payload_bytes)
        now = self._now()
        existing = self._records.get(report.report_id)
        if existing is not None:
            existing.duplicate_ingests += 1
            return IngestResult(record=existing, duplicate=True,
                                content_shared_with=
                                self._shared_content_ids(existing))
        if _parse_ts(report.expires_at, "expires_at") <= now:
            raise ExpiredReportError(
                f"peer report {report.report_id} from "
                f"{report.contributor_id} expired at "
                f"{report.expires_at}; explicit expiration is "
                f"enforced at ingest and nothing is stored")
        held = sum(1 for rec in self._ordered_records()
                   if rec.report.contributor_id == report.contributor_id)
        if held >= self._max_reports_per_contributor:
            raise QuotaExceededError(
                f"contributor {report.contributor_id} already holds "
                f"{held} reports, the per-contributor quota of "
                f"{self._max_reports_per_contributor}; the new "
                f"report is refused, stored reports are untouched")
        record = PeerRecord(report=report, trust_state="untrusted",
                            ingested_at=_format_ts(now))
        self._records[report.report_id] = record
        self._order.append(report.report_id)
        return IngestResult(record=record, duplicate=False,
                            content_shared_with=
                            self._shared_content_ids(record))

    # -- lookups ------------------------------------------------------

    def get(self, report_id: str) -> PeerRecord:
        record = self._records.get(report_id)
        if record is None:
            raise UnknownReportError(
                f"no stored peer report with id {report_id!r}")
        return record

    def reports(self, contributor_id: Optional[str] = None,
                subject: Optional[str] = None,
                usable_only: bool = False) -> List[PeerRecord]:
        """Stored records in ingest order, optionally filtered.

        ``usable_only`` excludes withdrawn and expired records --
        the set derived views (duplicates excepted) reason over.
        """
        out = []
        for record in self._ordered_records():
            if contributor_id is not None and \
                    record.report.contributor_id != contributor_id:
                continue
            if subject is not None and record.report.subject != subject:
                continue
            if usable_only and record.trust_state in ("withdrawn",
                                                      "expired"):
                continue
            out.append(record)
        return out

    def __len__(self) -> int:
        return len(self._order)

    # -- trust transitions -------------------------------------------

    def mark_reproduced(self, report_id: str, local_subject: str,
                        local_claim: str,
                        local_payload: Mapping[str, Any]) -> PeerRecord:
        """Promote a report to ``locally-reproduced`` -- the only
        promotion this registry grants, and only when a LOCAL
        reproduction of the same subject + claim + payload hashes
        to the report's pinned content digest.

        A mismatch is itself evidence: the failure is counted on
        the record and raised by name, and the report stays
        untrusted.  Withdrawn reports refuse (consent governs use),
        expired reports refuse (reproduce the claim fresh instead).
        """
        record = self.get(report_id)
        if record.trust_state == "withdrawn":
            raise ConsentWithdrawnError(
                f"peer report {report_id} was withdrawn by "
                f"{record.report.contributor_id}; withdrawn consent "
                f"governs use, so it cannot be reproduced into trust")
        self.sweep_expired()
        if record.trust_state == "expired":
            raise ExpiredReportError(
                f"peer report {report_id} expired at "
                f"{record.report.expires_at}; it can no longer be "
                f"promoted -- a fresh report is required")
        local_digest = content_digest_for(local_subject, local_claim,
                                          local_payload)
        if local_digest != record.report.content_digest:
            record.reproduction_failures += 1
            raise ReproductionMismatchError(
                f"local reproduction of report {report_id} hashed "
                f"to {local_digest!r}, not the pinned "
                f"{record.report.content_digest!r}; the report "
                f"stays untrusted and the failure is recorded "
                f"(failure #{record.reproduction_failures})")
        record.trust_state = "locally-reproduced"
        return record

    def withdraw_report(self, report_id: str) -> PeerRecord:
        """Withdraw one report: retained for audit, removed from
        every usable view.  Idempotent."""
        record = self.get(report_id)
        record.trust_state = "withdrawn"
        return record

    def withdraw_contributor(self, contributor_id: str) -> int:
        """Withdraw ALL of a contributor's reports (consent
        withdrawn at the node level, Book IV P13 test gate).
        Returns how many records changed state."""
        changed = 0
        for record in self._ordered_records():
            if record.report.contributor_id == contributor_id and \
                    record.trust_state != "withdrawn":
                record.trust_state = "withdrawn"
                changed += 1
        return changed

    def sweep_expired(self) -> int:
        """Move every live record past its expiration to
        ``expired``.  Withdrawn records keep their state (consent,
        not time, governs them).  Returns how many changed."""
        now = self._now()
        changed = 0
        for record in self._ordered_records():
            if record.trust_state in ("withdrawn", "expired"):
                continue
            if _parse_ts(record.report.expires_at, "expires_at") <= now:
                record.trust_state = "expired"
                changed += 1
        return changed

    # -- derived views -------------------------------------------------

    def duplicates(self) -> List[DuplicateGroup]:
        """Content digests carried by more than one stored report,
        in first-ingest order.  Withdrawn and expired carriers are
        included: duplication is a fact about what ARRIVED, and the
        audit trail must show it even after consent or time removes
        a carrier from the usable set."""
        groups: Dict[str, List[PeerRecord]] = {}
        for record in self._ordered_records():
            groups.setdefault(record.report.content_digest,
                              []).append(record)
        out = []
        for digest, records in groups.items():
            if len(records) < 2:
                continue
            out.append(DuplicateGroup(
                content_digest=digest,
                report_ids=tuple(r.report.report_id for r in records),
                contributor_ids=tuple(sorted(
                    {r.report.contributor_id for r in records})),
            ))
        return out

    def disputes(self) -> List[Dispute]:
        """Subjects whose USABLE reports disagree, in first-ingest
        subject order.  A subject appears here while ANY usable
        pair contradicts -- agreement counts are reported inside
        the dispute, never used to dissolve it."""
        by_subject: Dict[str, Dict[str, List[PeerRecord]]] = {}
        subject_order: List[str] = []
        for record in self.reports(usable_only=True):
            if record.report.subject not in by_subject:
                by_subject[record.report.subject] = {}
                subject_order.append(record.report.subject)
            by_subject[record.report.subject].setdefault(
                record.report.claim, []).append(record)
        out = []
        for subject in subject_order:
            claims = by_subject[subject]
            if len(claims) < 2:
                continue
            contributors = sorted({
                rec.report.contributor_id
                for recs in claims.values() for rec in recs})
            out.append(Dispute(
                subject=subject,
                claims={claim: tuple(r.report.report_id for r in recs)
                        for claim, recs in sorted(claims.items())},
                contributor_ids=tuple(contributors),
            ))
        return out

    def claim_counts(self, subject: str) -> Dict[str, int]:
        """Factual count of usable reports per claim on a subject.
        Counts are information, not verdicts: see subject_status."""
        counts: Dict[str, int] = {}
        for record in self.reports(subject=subject, usable_only=True):
            counts[record.report.claim] = \
                counts.get(record.report.claim, 0) + 1
        return counts

    def subject_status(self, subject: str) -> str:
        """One of SUBJECT_STATUSES for a subject.

        ``disputed`` wins over every agreement count, by design:
        a single usable contradictory report keeps the subject
        disputed, so disputed results are never voted into a false
        consensus.  ``corroborated`` requires one claim carried by
        at least two DISTINCT contributors; ``uncontested`` is one
        claim from one contributor; ``unknown`` is no usable
        reports at all.
        """
        usable = self.reports(subject=subject, usable_only=True)
        if not usable:
            return "unknown"
        claims = {record.report.claim for record in usable}
        if len(claims) > 1:
            return "disputed"
        contributors = {record.report.contributor_id for record in usable}
        return "corroborated" if len(contributors) >= 2 else "uncontested"

    def summary(self) -> Dict[str, Any]:
        """Factual registry summary (see peer_evidence_record)."""
        by_state: Dict[str, int] = {state: 0 for state in TRUST_STATES}
        subjects = set()
        contributors = set()
        for record in self._ordered_records():
            by_state[record.trust_state] += 1
            subjects.add(record.report.subject)
            contributors.add(record.report.contributor_id)
        return {
            "schema": PEER_SCHEMA,
            "schema_version": PEER_SCHEMA_VERSION,
            "evidence_status": EVIDENCE_STATUS,
            "reports": len(self._order),
            "contributors": len(contributors),
            "subjects": len(subjects),
            "by_trust_state": by_state,
            "duplicate_groups": len(self.duplicates()),
            "disputes": len(self.disputes()),
            "disputed_subjects": [d.subject for d in self.disputes()],
        }


def peer_evidence_record(registry: PeerEvidenceRegistry) -> Dict[str, Any]:
    """The LIF-1302 evidence record for a registry: what arrived,
    what is trusted and why, what is disputed, and the limits of
    every one of those statements (master roadmap section 5)."""
    record = registry.summary()
    record["limitations"] = [
        "fixture level: the 20-node network is a pinned fixture, "
        "not a live federation; no network transport exists here",
        "locally-reproduced means a local digest recomputation "
        "matched the pinned content hash; it is not human review",
        "corroborated is a count of distinct contributors, not a "
        "truth verdict; disputed subjects are never voted away",
        "in-memory registry: persistence via the LIF-0301 event "
        "store is future work and is not claimed",
    ]
    record["undo"] = (
        "the registry is in-memory and holds no host state; "
        "discarding it undoes everything it recorded.  At banking, "
        "reverting the LIF-1302 commit removes the module, its "
        "tests and its fixture.")
    return record
