"""Causal hypothesis records for Mimir memory (LIF-0305).

SPDX-License-Identifier: GPL-2.0-only

Home justification: master roadmap section 3 lays out ``src/`` for
core code and LIF-0201/LIF-0301/LIF-0302/LIF-0303 already placed the
event bus, the event store, provenance and exact search in
``src/lifthrasir/``.  Causal hypothesis records are the Mimir
memory-plane companion to those pieces (ADR-0002: Replicater owns
hypothesis records; Mimir consumes and retains them), so they live
beside them here, not in ``lab/``.

Consistency with LIF-0004: a causal hypothesis record IS a
LIF-0004 v0.1 hypothesis record (``docs/protocols/schemas/v0.1/
hypothesis.schema.json``) -- same envelope, same fields, no extra
fields, no renamed fields.  This module validates records against
the v0.1 rules directly (required fields, identifier patterns,
confidence range, status and evidence-ladder enums, and the two
cross-field rules: ``supported`` needs at least one
``evidence_for`` entry, ``refuted`` needs at least one
``evidence_against`` entry) so a record accepted here validates
against the banked schema, and the tests prove that agreement
against the schema file itself when ``jsonschema`` is available.

What this slice adds over the bare schema:

- Retention of failure.  The ledger is append-only in spirit: a
  hypothesis is never deleted, and a ``refuted`` (failed)
  hypothesis stays queryable forever via ``list_failed()``.
  Refuted is a first-class outcome, not an error to erase.
- Counterevidence is cumulative.  A status update is a new
  VERSION of the same ``hypothesis_id``.  A new version may add
  evidence for or against, but it may never DROP an
  ``evidence_against`` entry recorded by an earlier version:
  counterevidence, once recorded, is retained (``Counterevidence-
  DroppedError``).  ``evidence_for`` is held to the same rule so
  the supporting record cannot be quietly rewritten either.
- Versioning and staleness.  ``history(id)`` returns every version
  in record order; all but the latest are stale (P3 exit: old
  versions marked stale).  ``get(id)`` returns the latest version.
  A new version must carry ``updated_at`` at or after the previous
  version's timestamp, so the causal timeline cannot run backwards.
- Causal structure.  Hypotheses are causal claims about an
  incident.  ``causal_links()`` derives the links the records
  themselves prove: two hypotheses are linked when they address
  the same incident (``same-incident``), cite the same evidence
  (``shared-evidence``), or contradict each other -- an evidence
  id cited FOR one and AGAINST another (``contradiction``).
  No link is invented beyond those three record-level facts.
- Traceability.  ``trace(incident_id)`` returns the incident's
  hypotheses in causal (record) order with their for/against
  evidence, so every summarized claim can be traced to evidence
  (P3 exit criterion).

Evidence-status honesty: this module records claims at the rung
their ``evidence_status`` field declares; it never promotes a
rung.  A ledger entry is a record, not a proof.
"""
from __future__ import annotations

import copy
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List, Optional

SCHEMA = "lifthrasir.hypothesis.v0.1"
SCHEMA_VERSION = "0.1"

STATUSES = ("proposed", "supported", "refuted", "inconclusive")
EVIDENCE_LADDER = (
    "idea", "hypothesis", "reproducer", "lab-verified",
    "cross-platform-verified", "human-reviewed",
    "deployed-with-monitoring", "upstream-submitted",
    "upstream-accepted",
)
FAILED_STATUS = "refuted"

_HYP_RE = re.compile(r"^hyp-[a-z0-9][a-z0-9-]*$")
_INC_RE = re.compile(r"^inc-[a-z0-9][a-z0-9-]*$")
_EV_RE = re.compile(r"^ev-[a-z0-9][a-z0-9-]*$")

REQUIRED = (
    "schema", "schema_version", "hypothesis_id", "incident_id",
    "claim", "status", "confidence", "evidence_for",
    "evidence_against", "test_plan", "evidence_status",
    "created_at",
)
ALLOWED = frozenset(REQUIRED) | {"updated_at"}


class HypothesisError(Exception):
    """Base class for all named hypothesis-record refusals."""


class MalformedHypothesisError(HypothesisError):
    """Raised when a record breaks a LIF-0004 v0.1 field rule."""


class UnsupportedStatusError(HypothesisError):
    """Raised when a record claims a status/evidence combination
    the v0.1 cross-field rules forbid (e.g. supported with no
    supporting evidence, refuted with no counterevidence)."""


class DuplicateHypothesisError(HypothesisError):
    """Raised when a NEW hypothesis reuses an existing id."""


class UnknownHypothesisError(HypothesisError):
    """Raised when an update or lookup names an unknown id."""


class CounterevidenceDroppedError(HypothesisError):
    """Raised when a new version drops recorded evidence."""


class StaleTimestampError(HypothesisError):
    """Raised when a new version's timestamp runs backwards."""


def _parse_ts(value: Any, field: str) -> datetime:
    if not isinstance(value, str) or not value:
        raise MalformedHypothesisError(
            f"{field} must be an RFC 3339 date-time string, "
            f"got {value!r}")
    text = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        raise MalformedHypothesisError(
            f"{field} {value!r} is not a valid date-time") from None


def _check_evidence_list(record, field):
    value = record.get(field)
    if not isinstance(value, list):
        raise MalformedHypothesisError(
            f"{field} must be a list of evidence ids, got "
            f"{type(value).__name__}")
    for item in value:
        if not isinstance(item, str) or not _EV_RE.match(item):
            raise MalformedHypothesisError(
                f"{field} entry {item!r} is not a well-formed "
                f"evidence id (ev-...)")
    if len(set(value)) != len(value):
        raise MalformedHypothesisError(
            f"{field} must not contain duplicate evidence ids")
    return list(value)


def validate_hypothesis(record: Any) -> Dict[str, Any]:
    """Validate one record against the LIF-0004 v0.1 rules.

    Returns a defensive deep copy on success; raises a named
    HypothesisError subclass on any rule break.
    """
    if not isinstance(record, dict):
        raise MalformedHypothesisError(
            f"hypothesis record must be a JSON object, got "
            f"{type(record).__name__}")
    extra = sorted(set(record) - ALLOWED)
    if extra:
        raise MalformedHypothesisError(
            f"hypothesis record carries fields the v0.1 schema "
            f"forbids (additionalProperties is false): {extra}")
    missing = [f for f in REQUIRED if f not in record]
    if missing:
        raise MalformedHypothesisError(
            f"hypothesis record is missing required fields: "
            f"{missing}")
    if record["schema"] != SCHEMA:
        raise MalformedHypothesisError(
            f"schema must be {SCHEMA!r}, got {record['schema']!r}")
    if record["schema_version"] != SCHEMA_VERSION:
        raise MalformedHypothesisError(
            f"schema_version must be the LIF-0004 pin "
            f"{SCHEMA_VERSION!r}, got {record['schema_version']!r}")
    if not _HYP_RE.match(str(record["hypothesis_id"])):
        raise MalformedHypothesisError(
            f"hypothesis_id {record['hypothesis_id']!r} is not a "
            f"well-formed hypothesis id (hyp-...)")
    if not _INC_RE.match(str(record["incident_id"])):
        raise MalformedHypothesisError(
            f"incident_id {record['incident_id']!r} is not a "
            f"well-formed incident id (inc-...)")
    for field in ("claim", "test_plan"):
        if not isinstance(record[field], str) \
                or not record[field].strip():
            raise MalformedHypothesisError(
                f"{field} must be a non-empty string")
    if record["status"] not in STATUSES:
        raise MalformedHypothesisError(
            f"status {record['status']!r} is not one of {STATUSES}")
    confidence = record["confidence"]
    if not isinstance(confidence, (int, float)) \
            or isinstance(confidence, bool) \
            or not 0 <= float(confidence) <= 1:
        raise MalformedHypothesisError(
            f"confidence must be a number in [0, 1], got "
            f"{confidence!r}")
    if record["evidence_status"] not in EVIDENCE_LADDER:
        raise MalformedHypothesisError(
            f"evidence_status {record['evidence_status']!r} is "
            f"not a rung of the section 5 evidence ladder")
    evidence_for = _check_evidence_list(record, "evidence_for")
    evidence_against = _check_evidence_list(record, "evidence_against")
    overlap = sorted(set(evidence_for) & set(evidence_against))
    if overlap:
        raise MalformedHypothesisError(
            f"evidence cited both for and against the same "
            f"hypothesis in one record: {overlap}")
    _parse_ts(record["created_at"], "created_at")
    if "updated_at" in record:
        _parse_ts(record["updated_at"], "updated_at")
    # v0.1 cross-field rules (hypothesis.schema.json allOf).
    if record["status"] == "supported" and not evidence_for:
        raise UnsupportedStatusError(
            "status 'supported' requires at least one "
            "evidence_for reference (LIF-0004 v0.1 cross-field "
            "rule); a claim with no supporting evidence cannot "
            "be recorded as supported")
    if record["status"] == "refuted" and not evidence_against:
        raise UnsupportedStatusError(
            "status 'refuted' requires at least one "
            "evidence_against reference (LIF-0004 v0.1 "
            "cross-field rule); a failed hypothesis must carry "
            "the counterevidence that failed it")
    return copy.deepcopy(record)


@dataclass(frozen=True)
class CausalLink:
    """A record-provable link between two hypotheses."""
    first_id: str
    second_id: str
    kind: str  # same-incident | shared-evidence | contradiction
    detail: str


class HypothesisLedger:
    """Append-only, versioned ledger of causal hypotheses.

    Versions of one hypothesis share its hypothesis_id; the
    ledger keeps every version ever recorded, in record order.
    Nothing is ever deleted or rewritten in place.
    """

    def __init__(self) -> None:
        self._versions: Dict[str, List[Dict[str, Any]]] = {}
        self._order: List[str] = []

    # -- writes ---------------------------------------------------
    def record(self, record: Dict[str, Any]) -> str:
        """Record a NEW hypothesis; returns its hypothesis_id."""
        checked = validate_hypothesis(record)
        hyp_id = checked["hypothesis_id"]
        if hyp_id in self._versions:
            raise DuplicateHypothesisError(
                f"hypothesis id {hyp_id!r} is already recorded; "
                f"use record_version() for a status update so the "
                f"earlier version is retained, not overwritten")
        self._versions[hyp_id] = [checked]
        self._order.append(hyp_id)
        return hyp_id

    def record_version(self, record: Dict[str, Any]) -> str:
        """Record a new version of an existing hypothesis.

        The new version must keep the same incident and claim
        identity fields' well-formedness, must not drop any
        previously recorded evidence (for or against), and must
        not carry a timestamp earlier than the previous version.
        """
        checked = validate_hypothesis(record)
        hyp_id = checked["hypothesis_id"]
        if hyp_id not in self._versions:
            raise UnknownHypothesisError(
                f"cannot version unknown hypothesis {hyp_id!r}; "
                f"use record() for a new hypothesis")
        previous = self._versions[hyp_id][-1]
        if checked["incident_id"] != previous["incident_id"]:
            raise MalformedHypothesisError(
                f"a new version of {hyp_id} cannot move it to a "
                f"different incident ({previous['incident_id']} "
                f"-> {checked['incident_id']}); record a new "
                f"hypothesis for a different incident")
        for field in ("evidence_against", "evidence_for"):
            dropped = sorted(
                set(previous[field]) - set(checked[field]))
            if dropped:
                raise CounterevidenceDroppedError(
                    f"new version of {hyp_id} drops recorded "
                    f"{field} {dropped}; evidence once recorded "
                    f"is retained -- counterevidence and support "
                    f"are cumulative in the causal record")
        prev_ts = _parse_ts(
            previous.get("updated_at", previous["created_at"]),
            "previous timestamp")
        new_ts = _parse_ts(
            checked.get("updated_at", checked["created_at"]),
            "updated_at")
        if new_ts < prev_ts:
            raise StaleTimestampError(
                f"new version of {hyp_id} is timestamped "
                f"{checked.get('updated_at', checked['created_at'])}"
                f", earlier than the previous version; the "
                f"causal timeline cannot run backwards")
        if "updated_at" not in checked:
            raise MalformedHypothesisError(
                f"a new version of {hyp_id} must carry "
                f"updated_at so the timeline is explicit")
        self._versions[hyp_id].append(checked)
        return hyp_id

    # -- reads ------------------------------------------------------
    def __len__(self) -> int:
        return len(self._order)

    def ids(self) -> List[str]:
        return list(self._order)

    def get(self, hypothesis_id: str) -> Dict[str, Any]:
        """Latest version of a hypothesis (a defensive copy)."""
        if hypothesis_id not in self._versions:
            raise UnknownHypothesisError(
                f"unknown hypothesis {hypothesis_id!r}")
        return copy.deepcopy(self._versions[hypothesis_id][-1])

    def history(self, hypothesis_id: str) -> List[Dict[str, Any]]:
        """Every version, oldest first; all retained, none lost."""
        if hypothesis_id not in self._versions:
            raise UnknownHypothesisError(
                f"unknown hypothesis {hypothesis_id!r}")
        return copy.deepcopy(self._versions[hypothesis_id])

    def is_stale(self, hypothesis_id: str, version_index: int) -> bool:
        """True for every version except the latest (P3 exit)."""
        versions = self._versions.get(hypothesis_id)
        if versions is None:
            raise UnknownHypothesisError(
                f"unknown hypothesis {hypothesis_id!r}")
        return version_index < len(versions) - 1

    def list_all(self) -> List[Dict[str, Any]]:
        """Latest version of every hypothesis, in record order."""
        return [self.get(h) for h in self._order]

    def list_for_incident(
            self, incident_id: str) -> List[Dict[str, Any]]:
        return [r for r in self.list_all()
                if r["incident_id"] == incident_id]

    def list_failed(self) -> List[Dict[str, Any]]:
        """Failed (refuted) hypotheses -- retained, queryable."""
        return [r for r in self.list_all()
                if r["status"] == FAILED_STATUS]

    def ever_failed(self) -> List[str]:
        """Ids refuted in ANY version, even if later revised."""
        return [h for h in self._order
                if any(v["status"] == FAILED_STATUS
                       for v in self._versions[h])]

    def list_with_counterevidence(self) -> List[Dict[str, Any]]:
        return [r for r in self.list_all() if r["evidence_against"]]

    def counterevidence_for(
            self, hypothesis_id: str) -> List[str]:
        """All counterevidence ever recorded against a hypothesis,
        unioned across its versions so nothing is lost."""
        if hypothesis_id not in self._versions:
            raise UnknownHypothesisError(
                f"unknown hypothesis {hypothesis_id!r}")
        seen: List[str] = []
        for version in self._versions[hypothesis_id]:
            for ev in version["evidence_against"]:
                if ev not in seen:
                    seen.append(ev)
        return seen

    # -- causal structure ------------------------------------------
    def causal_links(self) -> List[CausalLink]:
        links: List[CausalLink] = []
        latest = {h: self._versions[h][-1] for h in self._order}
        for i, first in enumerate(self._order):
            for second in self._order[i + 1:]:
                a, b = latest[first], latest[second]
                if a["incident_id"] == b["incident_id"]:
                    links.append(CausalLink(
                        first, second, "same-incident",
                        a["incident_id"]))
                shared = sorted(
                    (set(a["evidence_for"]) | set(a["evidence_against"]))
                    & (set(b["evidence_for"])
                       | set(b["evidence_against"])))
                if shared:
                    links.append(CausalLink(
                        first, second, "shared-evidence",
                        ",".join(shared)))
                contra = sorted(
                    (set(a["evidence_for"]) & set(b["evidence_against"]))
                    | (set(b["evidence_for"])
                       & set(a["evidence_against"])))
                if contra:
                    links.append(CausalLink(
                        first, second, "contradiction",
                        ",".join(contra)))
        return links

    def trace(self, incident_id: str) -> List[Dict[str, Any]]:
        """Causal timeline for one incident: every hypothesis
        (latest version) in record order, with its evidence, so a
        summarized claim can be traced to its evidence (P3 exit).
        Failed hypotheses appear in the trace, marked refuted."""
        out = []
        for record in self.list_for_incident(incident_id):
            out.append({
                "hypothesis_id": record["hypothesis_id"],
                "claim": record["claim"],
                "status": record["status"],
                "failed": record["status"] == FAILED_STATUS,
                "confidence": record["confidence"],
                "evidence_status": record["evidence_status"],
                "evidence_for": list(record["evidence_for"]),
                "evidence_against": list(record["evidence_against"]),
                "versions": len(
                    self._versions[record["hypothesis_id"]]),
            })
        return out

    def explain(self, hypothesis_id: str) -> Dict[str, Any]:
        """One hypothesis with its full causal context."""
        record = self.get(hypothesis_id)
        links = [link for link in self.causal_links()
                 if hypothesis_id in (link.first_id, link.second_id)]
        return {
            "hypothesis_id": hypothesis_id,
            "incident_id": record["incident_id"],
            "claim": record["claim"],
            "status": record["status"],
            "failed": record["status"] == FAILED_STATUS,
            "confidence": record["confidence"],
            "evidence_status": record["evidence_status"],
            "evidence_for": list(record["evidence_for"]),
            "evidence_against": list(record["evidence_against"]),
            "counterevidence_ever": self.counterevidence_for(
                hypothesis_id),
            "versions": len(self._versions[hypothesis_id]),
            "causal_links": [
                {"first_id": link.first_id,
                 "second_id": link.second_id,
                 "kind": link.kind, "detail": link.detail}
                for link in links],
        }
