"""Maintainer feedback import and human DCO review checkpoint (LIF-1402).

SPDX-License-Identifier: GPL-2.0-only

Home justification: Book IV P14 (the Upstream Forge) uses the Linux
kernel's documented contribution route -- maintainers identified via
MAINTAINERS, patches prepared with git format-patch or b4, and a
HUMAN holding the final review and submission decision.  The WAVE
PLAN safety invariant 6 states it flatly: agents never issue human
DCO Signed-off-by tags and never send kernel patches; a human
reviews and submits.  LIF-1402 is that checkpoint.  The LIF-0904
patch dossier (banked) already refuses agent-authored DCO lines
inside a dossier; this module is the receiving and gating side that
sits after a dossier exists:

- MAINTAINER FEEDBACK IMPORT: feedback about a dossier (Reviewed-by,
  Acked-by, Tested-by, change requests, NAKs, plain comments) is
  imported as validated, digest-pinned records.  Every record is
  bound to the exact dossier digest it comments on, its own content
  digest is recomputed at import (a tampered or mislabelled record
  is refused by name), re-import is idempotent, and feedback is
  DATA for the human -- importing feedback, however positive or
  negative, never changes a checkpoint's state and never counts as
  a decision.
- NO SIGNING CHANNEL: imported feedback whose body carries a
  Signed-off-by line is refused by name (FeedbackDCOError).
  Feedback relays what a maintainer said; it is not a vehicle for
  minting DCO signatures, and this module contains no code path
  that adds a Signed-off-by trailer to anything.
- THE HUMAN CHECKPOINT: a checkpoint pins one dossier digest and
  waits in state ``awaiting-human``.  The only transition out is
  ``record_decision`` with a reviewer whose declared kind is
  ``human``; an agent, bot or otherwise non-human reviewer identity
  is refused by name (AgentReviewerError) whatever decision it
  tries to record.  Approval additionally requires:
    * an explicit DCO-review attestation by that human
      (``dco_reviewed=True``) -- absent attestation, refusal;
    * when any maintainer feedback stands imported for the
      dossier, an explicit feedback-review attestation
      (``feedback_reviewed=True``);
    * the dossier digest still matching the pin -- approval of a
      stale digest is refused (StaleCheckpointError); a revised
      patch is a new checkpoint, never a mutated old one;
    * a sign-off scan of the patch text: every Signed-off-by
      trailer present must name the deciding human themselves.
      A trailer naming an agent, a bot, or any third party is a
      hard refusal (SignoffViolationError) -- the checkpoint never
      launders someone else's signature into a submission.
- NOTHING IS SENT: an approved checkpoint yields a
  ``submission_package`` RECORD (sent: False, no Signed-off-by
  added, submission channel named ``human-outside-system``).  The
  human takes that record and submits outside this system, with
  their own tools and their own signature.  This module exposes no
  network, subprocess, filesystem or send surface at all.

The board is in-memory and deterministic: listings are in import
order and every view is recomputed from the stored records, so no
cached verdict can drift from the record.  Persistence through the
LIF-0301 event store and live mailbox/forge import (the importers
that would feed these wire records) are future work, not claimed
here.  LIF-1401's dossier generator is likewise not depended on:
a dossier here is an identifier plus a SHA-256 digest pin plus the
patch text, which the banked LIF-0904 dossier already provides.

Evidence-status honesty: this module's own status is
``lab-verified (fixture level, one machine)`` -- the maintainer
feedback in ``tests/fixtures/lif1402/feedback.json`` is synthetic
fixture data, not real upstream correspondence, and no real
submission is prepared, approved or sent by anything here.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List, Mapping, Optional, Tuple

UPSTREAM_REVIEW_SCHEMA = "lifthrasir.upstreamreview.v0.1"
UPSTREAM_REVIEW_SCHEMA_VERSION = "0.1"
EVIDENCE_STATUS = "lab-verified"
TIMESTAMP_FORMAT = "%Y-%m-%dT%H:%M:%SZ"

FEEDBACK_KINDS = (
    "reviewed-by",
    "acked-by",
    "tested-by",
    "requested-changes",
    "nack",
    "comment",
)
FEEDBACK_SOURCES = ("mailing-list", "forge-review", "email", "b4", "in-person")
HUMAN_KIND = "human"
DECISION_APPROVED = "approved-for-submission"
DECISION_CHANGES = "changes-requested"
DECISION_REJECTED = "rejected"
DECISIONS = (DECISION_APPROVED, DECISION_CHANGES, DECISION_REJECTED)
STATE_AWAITING = "awaiting-human"
CHECKPOINT_STATES = (STATE_AWAITING, DECISION_APPROVED, DECISION_CHANGES, DECISION_REJECTED)
SUBMISSION_CHANNEL = "human-outside-system"

MAX_FEEDBACK_BODY_CHARS = 8000
MAX_PATCH_CHARS = 100000
MAX_FEEDBACK_PER_DOSSIER = 200
MAX_NOTE_CHARS = 2000

_SHA_RE = re.compile(r"^sha256:[a-f0-9]{64}$")
_ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]*$")
_EMAIL_RE = re.compile(r"^[^@\s<>]+@[^@\s<>]+\.[^@\s<>]+$")
_SIGNOFF_RE = re.compile(r"^\s*Signed-off-by\s*:\s*(.+?)\s*$", re.IGNORECASE | re.MULTILINE)
_IDENTITY_RE = re.compile(r"^(.*?)\s*<([^<>]+)>\s*$")


class UpstreamReviewError(Exception):
    """Base class for every refusal raised by this module."""


class MalformedFeedbackError(UpstreamReviewError):
    """A feedback wire record is structurally invalid."""


class FeedbackDigestError(UpstreamReviewError):
    """A feedback record's content digest does not match its content."""


class FeedbackDCOError(UpstreamReviewError):
    """Feedback body carries a Signed-off-by line; feedback is not a signing channel."""


class FeedbackQuotaError(UpstreamReviewError):
    """Too many feedback records already stand imported for one dossier."""


class MalformedCheckpointError(UpstreamReviewError):
    """A checkpoint or decision request is structurally invalid."""


class DossierMismatchError(UpstreamReviewError):
    """Patch text does not hash to the dossier digest it claims."""


class DuplicateCheckpointError(UpstreamReviewError):
    """A checkpoint for this dossier digest is already registered."""


class UnknownCheckpointError(UpstreamReviewError):
    """No checkpoint is registered under the given identifier or digest."""


class AgentReviewerError(UpstreamReviewError):
    """A non-human reviewer identity tried to record a decision."""


class DCOAttestationError(UpstreamReviewError):
    """Approval was attempted without the human's explicit DCO-review attestation."""


class FeedbackReviewRequiredError(UpstreamReviewError):
    """Approval was attempted without attesting review of imported maintainer feedback."""


class StaleCheckpointError(UpstreamReviewError):
    """The dossier changed after the checkpoint pinned it; approval is refused."""


class SignoffViolationError(UpstreamReviewError):
    """The patch carries a Signed-off-by trailer naming someone other than the deciding human."""


class CheckpointStateError(UpstreamReviewError):
    """The checkpoint is not in a state that allows the requested operation."""


def _canonical(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def content_digest_for(obj: Any) -> str:
    """SHA-256 digest pin (``sha256:<hex>``) over a canonical JSON form."""
    return "sha256:" + hashlib.sha256(_canonical(obj).encode("utf-8")).hexdigest()


def patch_digest(patch_text: str) -> str:
    """SHA-256 digest pin over patch text exactly as given."""
    return "sha256:" + hashlib.sha256(patch_text.encode("utf-8")).hexdigest()


def _req_text(value: Any, name: str, limit: int, error: type) -> str:
    if not isinstance(value, str) or not value.strip():
        raise error(f"{name} must be a non-empty string")
    if len(value) > limit:
        raise error(f"{name} exceeds {limit} characters")
    return value


def _check_timestamp(value: Any, name: str, error: type) -> str:
    if not isinstance(value, str):
        raise error(f"{name} must be a timestamp string")
    try:
        datetime.strptime(value, TIMESTAMP_FORMAT)
    except ValueError:
        raise error(f"{name} must match YYYY-MM-DDTHH:MM:SSZ") from None
    return value


def _check_email(value: Any, name: str, error: type) -> str:
    if not isinstance(value, str) or not _EMAIL_RE.match(value):
        raise error(f"{name} must be an email address of the form name@host.tld")
    return value


def find_signoffs(text: str) -> List[str]:
    """Return the raw identity strings of every Signed-off-by trailer in text."""
    return [m.group(1) for m in _SIGNOFF_RE.finditer(text)]


def _parse_identity(raw: str) -> Optional[Tuple[str, str]]:
    m = _IDENTITY_RE.match(raw.strip())
    if not m:
        return None
    return (m.group(1).strip(), m.group(2).strip())


@dataclass(frozen=True)
class Reviewer:
    """A reviewer identity.  Only kind == 'human' may record a decision."""

    reviewer_id: str
    name: str
    email: str
    kind: str

    def __post_init__(self) -> None:
        if not isinstance(self.reviewer_id, str) or not _ID_RE.match(self.reviewer_id):
            raise MalformedCheckpointError("reviewer_id must match [a-z0-9][a-z0-9._-]*")
        _req_text(self.name, "reviewer name", 200, MalformedCheckpointError)
        _check_email(self.email, "reviewer email", MalformedCheckpointError)
        _req_text(self.kind, "reviewer kind", 40, MalformedCheckpointError)

    @property
    def is_human(self) -> bool:
        return self.kind == HUMAN_KIND

    def as_dict(self) -> Dict[str, Any]:
        return {
            "reviewer_id": self.reviewer_id,
            "name": self.name,
            "email": self.email,
            "kind": self.kind,
        }


_FEEDBACK_KEYS = {
    "schema",
    "dossier_id",
    "dossier_digest",
    "maintainer_name",
    "maintainer_email",
    "kind",
    "source",
    "body",
    "received_at",
    "content_digest",
}


@dataclass(frozen=True)
class FeedbackRecord:
    """One imported maintainer feedback record, bound to a dossier digest."""

    feedback_id: str
    dossier_id: str
    dossier_digest: str
    maintainer_name: str
    maintainer_email: str
    kind: str
    source: str
    body: str
    received_at: str
    content_digest: str

    def as_dict(self) -> Dict[str, Any]:
        return {
            "feedback_id": self.feedback_id,
            "dossier_id": self.dossier_id,
            "dossier_digest": self.dossier_digest,
            "maintainer_name": self.maintainer_name,
            "maintainer_email": self.maintainer_email,
            "kind": self.kind,
            "source": self.source,
            "body": self.body,
            "received_at": self.received_at,
            "content_digest": self.content_digest,
        }


def feedback_from_dict(wire: Mapping[str, Any]) -> FeedbackRecord:
    """Validate a feedback wire record and return it as a FeedbackRecord.

    Refusals are by name: structural problems raise
    MalformedFeedbackError, a body carrying a Signed-off-by line
    raises FeedbackDCOError, and a content digest that does not
    recompute over the record's own content raises
    FeedbackDigestError.
    """
    if not isinstance(wire, Mapping):
        raise MalformedFeedbackError("feedback wire record must be a mapping")
    keys = set(wire.keys())
    if keys != _FEEDBACK_KEYS:
        missing = sorted(_FEEDBACK_KEYS - keys)
        extra = sorted(keys - _FEEDBACK_KEYS)
        raise MalformedFeedbackError(
            f"feedback keys mismatch (missing={missing}, extra={extra})")
    if wire["schema"] != UPSTREAM_REVIEW_SCHEMA:
        raise MalformedFeedbackError(f"schema must be {UPSTREAM_REVIEW_SCHEMA}")
    dossier_id = wire["dossier_id"]
    if not isinstance(dossier_id, str) or not _ID_RE.match(dossier_id):
        raise MalformedFeedbackError("dossier_id must match [a-z0-9][a-z0-9._-]*")
    dossier_digest = wire["dossier_digest"]
    if not isinstance(dossier_digest, str) or not _SHA_RE.match(dossier_digest):
        raise MalformedFeedbackError("dossier_digest must be a sha256:<hex> pin")
    maintainer_name = _req_text(wire["maintainer_name"], "maintainer_name", 200,
                                MalformedFeedbackError)
    maintainer_email = _check_email(wire["maintainer_email"], "maintainer_email",
                                    MalformedFeedbackError)
    kind = wire["kind"]
    if kind not in FEEDBACK_KINDS:
        raise MalformedFeedbackError(f"kind must be one of {list(FEEDBACK_KINDS)}")
    source = wire["source"]
    if source not in FEEDBACK_SOURCES:
        raise MalformedFeedbackError(f"source must be one of {list(FEEDBACK_SOURCES)}")
    body = _req_text(wire["body"], "body", MAX_FEEDBACK_BODY_CHARS, MalformedFeedbackError)
    if find_signoffs(body):
        raise FeedbackDCOError(
            "feedback body carries a Signed-off-by line; feedback is not a signing channel")
    received_at = _check_timestamp(wire["received_at"], "received_at",
                                   MalformedFeedbackError)
    claimed = wire["content_digest"]
    if not isinstance(claimed, str) or not _SHA_RE.match(claimed):
        raise MalformedFeedbackError("content_digest must be a sha256:<hex> pin")
    content = {k: wire[k] for k in sorted(_FEEDBACK_KEYS - {"content_digest"})}
    if content_digest_for(content) != claimed:
        raise FeedbackDigestError(
            "content_digest does not recompute over the record content; "
            "the record was tampered with or mislabelled")
    feedback_id = "fb-" + claimed.split(":", 1)[1][:16]
    return FeedbackRecord(
        feedback_id=feedback_id,
        dossier_id=dossier_id,
        dossier_digest=dossier_digest,
        maintainer_name=maintainer_name,
        maintainer_email=maintainer_email,
        kind=kind,
        source=source,
        body=body,
        received_at=received_at,
        content_digest=claimed,
    )


def make_feedback(dossier_id: str, dossier_digest: str, maintainer_name: str,
                  maintainer_email: str, kind: str, source: str, body: str,
                  received_at: str) -> Dict[str, Any]:
    """Build a valid feedback wire record (computes its content digest).

    This is the fixture/test constructor: it produces exactly the
    wire form ``feedback_from_dict`` validates, so any record it
    builds round-trips through import validation.
    """
    wire: Dict[str, Any] = {
        "schema": UPSTREAM_REVIEW_SCHEMA,
        "dossier_id": dossier_id,
        "dossier_digest": dossier_digest,
        "maintainer_name": maintainer_name,
        "maintainer_email": maintainer_email,
        "kind": kind,
        "source": source,
        "body": body,
        "received_at": received_at,
    }
    wire["content_digest"] = content_digest_for(wire)
    feedback_from_dict(wire)
    return wire


@dataclass
class Decision:
    """A recorded human decision on a checkpoint."""

    reviewer: Reviewer
    decision: str
    decided_at: str
    dco_reviewed: bool
    feedback_reviewed: bool
    note: str

    def as_dict(self) -> Dict[str, Any]:
        return {
            "reviewer": self.reviewer.as_dict(),
            "decision": self.decision,
            "decided_at": self.decided_at,
            "dco_reviewed": self.dco_reviewed,
            "feedback_reviewed": self.feedback_reviewed,
            "note": self.note,
        }


@dataclass
class ReviewCheckpoint:
    """One dossier digest pinned for human review.  Decisions are final."""

    checkpoint_id: str
    dossier_id: str
    dossier_digest: str
    patch_text: str
    created_at: str
    state: str = STATE_AWAITING
    decision: Optional[Decision] = None

    def as_dict(self) -> Dict[str, Any]:
        return {
            "checkpoint_id": self.checkpoint_id,
            "dossier_id": self.dossier_id,
            "dossier_digest": self.dossier_digest,
            "created_at": self.created_at,
            "state": self.state,
            "decision": self.decision.as_dict() if self.decision else None,
        }


class UpstreamReviewBoard:
    """In-memory board of review checkpoints and imported feedback.

    Feedback and decisions are separate planes: importing feedback
    never moves a checkpoint, and only ``record_decision`` with a
    human reviewer can move one, exactly once.
    """

    def __init__(self) -> None:
        self._checkpoints: Dict[str, ReviewCheckpoint] = {}
        self._by_digest: Dict[str, str] = {}
        self._feedback: Dict[str, FeedbackRecord] = {}
        self._feedback_order: List[str] = []

    # -- checkpoints -------------------------------------------------

    def register_checkpoint(self, dossier_id: str, dossier_digest: str,
                            patch_text: str, created_at: str) -> ReviewCheckpoint:
        if not isinstance(dossier_id, str) or not _ID_RE.match(dossier_id):
            raise MalformedCheckpointError("dossier_id must match [a-z0-9][a-z0-9._-]*")
        if not isinstance(dossier_digest, str) or not _SHA_RE.match(dossier_digest):
            raise MalformedCheckpointError("dossier_digest must be a sha256:<hex> pin")
        _req_text(patch_text, "patch_text", MAX_PATCH_CHARS, MalformedCheckpointError)
        _check_timestamp(created_at, "created_at", MalformedCheckpointError)
        if patch_digest(patch_text) != dossier_digest:
            raise DossierMismatchError(
                "patch_text does not hash to dossier_digest; the checkpoint "
                "would pin a dossier it cannot see")
        if dossier_digest in self._by_digest:
            raise DuplicateCheckpointError(
                f"a checkpoint already pins dossier digest {dossier_digest}")
        checkpoint_id = "ckpt-" + dossier_digest.split(":", 1)[1][:16]
        ckpt = ReviewCheckpoint(
            checkpoint_id=checkpoint_id,
            dossier_id=dossier_id,
            dossier_digest=dossier_digest,
            patch_text=patch_text,
            created_at=created_at,
        )
        self._checkpoints[checkpoint_id] = ckpt
        self._by_digest[dossier_digest] = checkpoint_id
        return ckpt

    def get_checkpoint(self, checkpoint_id: str) -> ReviewCheckpoint:
        ckpt = self._checkpoints.get(checkpoint_id)
        if ckpt is None:
            raise UnknownCheckpointError(f"no checkpoint registered as {checkpoint_id}")
        return ckpt

    def checkpoint_for_digest(self, dossier_digest: str) -> ReviewCheckpoint:
        checkpoint_id = self._by_digest.get(dossier_digest)
        if checkpoint_id is None:
            raise UnknownCheckpointError(
                f"no checkpoint pins dossier digest {dossier_digest}")
        return self._checkpoints[checkpoint_id]

    # -- feedback ----------------------------------------------------

    def import_feedback(self, wire: Mapping[str, Any]) -> FeedbackRecord:
        """Import one feedback wire record.  Idempotent per feedback_id.

        The record must name the digest of a registered checkpoint:
        feedback about a dossier nobody is reviewing is refused
        (UnknownCheckpointError) rather than filed into the void.
        Importing feedback NEVER changes any checkpoint state.
        """
        record = feedback_from_dict(wire)
        self.checkpoint_for_digest(record.dossier_digest)
        if record.feedback_id in self._feedback:
            return self._feedback[record.feedback_id]
        count = sum(1 for fid in self._feedback_order
                    if self._feedback[fid].dossier_digest == record.dossier_digest)
        if count >= MAX_FEEDBACK_PER_DOSSIER:
            raise FeedbackQuotaError(
                f"dossier already has {MAX_FEEDBACK_PER_DOSSIER} feedback records")
        self._feedback[record.feedback_id] = record
        self._feedback_order.append(record.feedback_id)
        return record

    def feedback_for(self, dossier_digest: str) -> List[FeedbackRecord]:
        """All imported feedback for one dossier digest, in import order."""
        return [self._feedback[fid] for fid in self._feedback_order
                if self._feedback[fid].dossier_digest == dossier_digest]

    def feedback_summary(self, dossier_digest: str) -> Dict[str, int]:
        """Per-kind counts of imported feedback for one dossier digest."""
        summary = {kind: 0 for kind in FEEDBACK_KINDS}
        for record in self.feedback_for(dossier_digest):
            summary[record.kind] += 1
        return summary

    # -- the human decision ------------------------------------------

    def record_decision(self, checkpoint_id: str, reviewer: Reviewer, decision: str,
                        decided_at: str, dco_reviewed: bool = False,
                        feedback_reviewed: bool = False, note: str = "",
                        current_patch_text: Optional[str] = None) -> ReviewCheckpoint:
        """Record the human decision on a checkpoint.  The only state exit.

        Refusal order is deliberate: existence, then state, then the
        reviewer's humanity, then structural validity, and only for
        an approval the DCO/feedback attestations, the freshness of
        the pinned digest, and the sign-off scan.
        """
        ckpt = self.get_checkpoint(checkpoint_id)
        if ckpt.state != STATE_AWAITING:
            raise CheckpointStateError(
                f"checkpoint is {ckpt.state}; decisions are final and a "
                "revised dossier needs a new checkpoint")
        if not isinstance(reviewer, Reviewer):
            raise MalformedCheckpointError("reviewer must be a Reviewer")
        if not reviewer.is_human:
            raise AgentReviewerError(
                f"reviewer {reviewer.reviewer_id} declares kind {reviewer.kind!r}; "
                "only a human reviewer may record a decision (invariant: "
                "agents never hold the DCO review checkpoint)")
        if decision not in DECISIONS:
            raise MalformedCheckpointError(f"decision must be one of {list(DECISIONS)}")
        _check_timestamp(decided_at, "decided_at", MalformedCheckpointError)
        if decided_at < ckpt.created_at:
            raise MalformedCheckpointError("decided_at precedes the checkpoint's created_at")
        if not isinstance(dco_reviewed, bool) or not isinstance(feedback_reviewed, bool):
            raise MalformedCheckpointError("attestations must be booleans")
        if note:
            _req_text(note, "note", MAX_NOTE_CHARS, MalformedCheckpointError)
        if decision == DECISION_APPROVED:
            if not dco_reviewed:
                raise DCOAttestationError(
                    "approval requires the human reviewer's explicit DCO-review "
                    "attestation (dco_reviewed=True)")
            if self.feedback_for(ckpt.dossier_digest) and not feedback_reviewed:
                raise FeedbackReviewRequiredError(
                    "maintainer feedback stands imported for this dossier; "
                    "approval requires feedback_reviewed=True")
            current = current_patch_text if current_patch_text is not None else ckpt.patch_text
            if patch_digest(current) != ckpt.dossier_digest:
                raise StaleCheckpointError(
                    "the dossier no longer hashes to the pinned digest; "
                    "approval of a stale digest is refused -- register a "
                    "new checkpoint for the revised patch")
            for raw in find_signoffs(current):
                identity = _parse_identity(raw)
                if identity is None:
                    raise SignoffViolationError(
                        "patch carries a Signed-off-by trailer that is not a "
                        "parseable Name <email> identity")
                name, email = identity
                if name != reviewer.name or email.lower() != reviewer.email.lower():
                    raise SignoffViolationError(
                        f"patch carries a Signed-off-by trailer naming {name} "
                        f"<{email}>, who is not the deciding human; the "
                        "checkpoint never launders another identity's signature")
        ckpt.decision = Decision(
            reviewer=reviewer,
            decision=decision,
            decided_at=decided_at,
            dco_reviewed=dco_reviewed,
            feedback_reviewed=feedback_reviewed,
            note=note,
        )
        ckpt.state = decision
        return ckpt

    # -- outputs -------------------------------------------------------

    def submission_package(self, checkpoint_id: str) -> Dict[str, Any]:
        """The submission-ready RECORD for an approved checkpoint.

        This is a record, not a transmission: ``sent`` is False, no
        Signed-off-by trailer is added or carried, and the named
        channel is the human submitting outside this system with
        their own tools and their own signature.
        """
        ckpt = self.get_checkpoint(checkpoint_id)
        if ckpt.state != DECISION_APPROVED or ckpt.decision is None:
            raise CheckpointStateError(
                f"checkpoint is {ckpt.state}; only an approved checkpoint "
                "yields a submission package")
        return {
            "schema": UPSTREAM_REVIEW_SCHEMA,
            "dossier_id": ckpt.dossier_id,
            "dossier_digest": ckpt.dossier_digest,
            "checkpoint_id": ckpt.checkpoint_id,
            "decision": ckpt.decision.as_dict(),
            "feedback_summary": self.feedback_summary(ckpt.dossier_digest),
            "signoff_added_by_system": False,
            "sent": False,
            "submission_channel": SUBMISSION_CHANNEL,
            "evidence_status": EVIDENCE_STATUS,
        }


def upstream_review_record(board: UpstreamReviewBoard,
                           checkpoint_id: str) -> Dict[str, Any]:
    """Section-5 evidence record for one checkpoint on a board."""
    ckpt = board.get_checkpoint(checkpoint_id)
    return {
        "schema": UPSTREAM_REVIEW_SCHEMA,
        "checkpoint": ckpt.as_dict(),
        "feedback": [r.as_dict() for r in board.feedback_for(ckpt.dossier_digest)],
        "feedback_summary": board.feedback_summary(ckpt.dossier_digest),
        "evidence_status": EVIDENCE_STATUS,
        "limitations": [
            "fixture level: imported feedback is synthetic wire data; no "
            "mailbox, forge or b4 importer ran",
            "the board is in-memory; nothing is persisted, sent or signed",
            "the sign-off scan reads trailers in the patch text given at "
            "registration; it cannot prove who typed them -- the human "
            "DCO attestation is the control, the scan is its guardrail",
            "approval is a record for the human to act on outside this "
            "system; it is not an upstream submission",
        ],
    }
