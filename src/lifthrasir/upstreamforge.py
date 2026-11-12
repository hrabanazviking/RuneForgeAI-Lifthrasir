# SPDX-License-Identifier: GPL-2.0-only
"""Upstream patch dossier generator and b4 workflow support (LIF-1401).

Home justification: master roadmap section 3 places core code in
``src/lifthrasir/``; this module is the Book IV P14 ("Upstream
Forge") companion to the banked LIF-0904 candidate patch dossier
(``src/lifthrasir/patchdossier.py``).  LIF-0904 turns a candidate
kernel patch into a human-reviewed evidence package; this module
takes that package and prepares the *upstream* half of the road:
who should receive it, how it would be prepared with git
format-patch or b4, which disclosure route it must take, and
whether it is ready to be put in front of a human for the
submission decision.

What this slice builds (pure functions over caller-supplied
records only -- no file, process, network or kernel access at
all, and nothing is ever sent anywhere):

- MAINTAINERS routing: a strict parser for kernel MAINTAINERS
  text (sections, M:/R:/L:/S:/F:/X: fields) and get_maintainer.pl
  style matching of the candidate diff's touched files --
  F: glob and directory-prefix patterns, X: exclusions honoured.
  Files no section claims fall back to the general kernel list
  and are flagged as fallback-routed, never silently dropped.
- UPSTREAM DOSSIER: an assembled, digest-pinned package that
  binds the LIF-0904 candidate dossier by its content digest
  (a mismatched pin is refused by name), records the declared
  HUMAN author who would submit, the cover letter, the derived
  recipients, and a derived readiness state.  Readiness is
  computed from a fixed checklist, never asserted: a blocked
  candidate stays ``blocked``, an incomplete one stays
  ``incomplete``, a complete one waits at
  ``awaiting-human-review`` until a named human records the
  submission review, and only then is it
  ``ready-for-human-submission``.  There is no ``submitted``
  state in this module at all: ``submitted`` is always False
  and the upstream outcome is always ``not-submitted``, because
  upstream acceptance is a maintainer fact that can never be
  inferred from a local test (Book IV P14 test gate).
- DCO AND SUBMISSION GUARDS (master roadmap section 0,
  invariant 7): agents prepare, never send, and never sign.
  The cover letter is scanned with the same Signed-off-by rule
  as LIF-0904 and a tag is refused with patchdossier's
  ``DCOViolationError``; a submission review from anyone but a
  named human, an author record naming the agent itself, or any
  request to send/submit/sign is refused by name
  (``AgentSubmissionError``); a claimed evidence rung above
  ``human-reviewed`` is refused with patchdossier's
  ``UpstreamClaimError``.
- DISCLOSURE ROUTING: a dossier is either a public bug report
  (route ``public-lists``: maintainers, reviewers and lists
  from MAINTAINERS) or a security disclosure (route
  ``private-security``: the kernel security team address only,
  no public list, no b4 public-send step in the plan).  A route
  claim that contradicts the disclosure kind is refused by name
  (``DisclosureRouteError``), per the kernel security-bugs
  policy.
- B4 WORKFLOW SUPPORT: an ordered preparation plan, as data --
  identify maintainers, prepare the series (git format-patch
  --cover-letter or b4 prep), checkpatch, attach the cover
  letter, then the human-only steps: the human author adds
  their own Signed-off-by, a dry run, and the terminal
  submission decision.  Commands are recorded plan strings,
  never executed; exact flags follow the operator's b4 version
  (b4.docs.kernel.org).

Evidence-status honesty: proven at fixture level only, over a
fixture MAINTAINERS excerpt and recorded candidate dossiers.
No kernel tree was consulted, no maintainer was contacted, no
human review of this slice's fixtures was performed by anyone
but the recorded fixture reviewers, and no patch was prepared
in a real tree, sent, or submitted.
"""
from __future__ import annotations

import fnmatch
import json
import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from .patchdossier import (
    EVIDENCE_LADDER,
    MAX_TEXT_CHARS,
    PatchDossier,
    UpstreamClaimError,
    build_dossier,
    sha256_of_text,
)
from .patchdossier import DCOViolationError as _PatchDCOViolationError

# Re-exported so callers can catch the one DCO refusal type for
# both dossier layers; the class itself is LIF-0904's.
DCOViolationError = _PatchDCOViolationError

UPSTREAM_SCHEMA = "lifthrasir.upstreamforge.v0.1"
UPSTREAM_SCHEMA_VERSION = "0.1"
UPSTREAM_VERSION = "1"

DISCLOSURE_BUG = "bug"
DISCLOSURE_SECURITY = "security"
DISCLOSURES = (DISCLOSURE_BUG, DISCLOSURE_SECURITY)

ROUTE_PUBLIC = "public-lists"
ROUTE_PRIVATE = "private-security"
ROUTES = (ROUTE_PUBLIC, ROUTE_PRIVATE)

SECURITY_TEAM_ADDRESS = "security@kernel.org"
FALLBACK_LIST = "linux-kernel@vger.kernel.org"

STATE_BLOCKED = "blocked"
STATE_INCOMPLETE = "incomplete"
STATE_AWAITING_HUMAN_REVIEW = "awaiting-human-review"
STATE_READY = "ready-for-human-submission"
READINESS_STATES = (STATE_BLOCKED, STATE_INCOMPLETE,
                    STATE_AWAITING_HUMAN_REVIEW, STATE_READY)

# The fixed human submission-review checklist (Book IV P14: the
# human takes the final review and submission decision).
SUBMISSION_ITEMS = (
    "candidate-dossier-complete",
    "maintainers-and-lists-identified",
    "cover-letter-reviewed",
    "disclosure-route-correct",
    "dco-stance-acknowledged",
    "verification-limits-accepted",
)
SUBMISSION_STATES = ("pass", "fail")

MAX_UPSTREAM_ID_CHARS = 128
MAX_MAINTAINERS_CHARS = 200000
MAX_SECTIONS = 512
MAX_AUTHOR_CHARS = 200
MAX_SUBJECT_CHARS = 300

_ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]*$")
_EMAIL_RE = re.compile(r"^[^@\s<>]+@[^@\s<>]+\.[^@\s<>]+$")
_FIELD_RE = re.compile(r"^([A-Z]):[ \t]+(.*)$")
_ANGLE_ADDR_RE = re.compile(r"<([^<>\s]+@[^<>\s]+)>")
_BARE_ADDR_RE = re.compile(r"^[^\s<>]+@[^\s<>]+$")
_DCO_RE = re.compile(r"^\s*Signed-off-by\s*:", re.IGNORECASE | re.MULTILINE)
_AGENT_NAME_RE = re.compile(r"lifthrasir", re.IGNORECASE)

_ALLOWED_KEYS = {
    "upstream_id", "candidate", "candidate_digest", "disclosure",
    "route", "author", "cover_letter", "maintainers",
    "submission_review", "evidence_status",
}
# Keys whose mere presence is a submission act, refused by name
# before any other validation: this tool prepares only.
_FORBIDDEN_KEYS = {
    "submitted", "submit", "send", "sent", "action",
    "signoff", "signed_off_by", "signed-off-by",
}


class UpstreamForgeError(Exception):
    """Base class for all named upstream-forge refusals."""


class MalformedUpstreamError(UpstreamForgeError):
    """An upstream dossier field breaks a shape rule."""


class MaintainersError(UpstreamForgeError):
    """MAINTAINERS text is unparsable or carries a bad address."""


class AgentSubmissionError(UpstreamForgeError):
    """An agent was asked to send, submit, sign, or pose as the
    human author/reviewer (master roadmap section 0, invariant 7)."""


class DisclosureRouteError(UpstreamForgeError):
    """The claimed route contradicts the disclosure kind: security
    disclosures never go to public lists."""


def _req_text(value: Any, name: str, limit: int = MAX_TEXT_CHARS) -> str:
    if not isinstance(value, str) or not value.strip():
        raise MalformedUpstreamError(f"{name} must be a non-empty string")
    if len(value) > limit:
        raise MalformedUpstreamError(f"{name} exceeds {limit} chars")
    return value


def _check_no_dco(text: str, where: str) -> None:
    if _DCO_RE.search(text):
        raise DCOViolationError(
            f"{where} carries a Signed-off-by tag: agents never sign "
            "DCO (master roadmap section 0, invariant 7); the human "
            "author signs at submission time, outside this tool")


def _pattern_matches(pattern: str, path: str) -> bool:
    """get_maintainer.pl style F:/X: pattern match for one path."""
    if pattern.endswith("/"):
        return path.startswith(pattern)
    if any(c in pattern for c in "*?["):
        return fnmatch.fnmatchcase(path, pattern)
    return path == pattern or path.startswith(pattern + "/")


def _address_of(value: str, where: str) -> str:
    m = _ANGLE_ADDR_RE.search(value)
    if m:
        return m.group(1)
    bare = value.strip()
    if _BARE_ADDR_RE.match(bare):
        return bare
    raise MaintainersError(
        f"{where}: no email address found in {value!r}")


@dataclass(frozen=True)
class MaintainerEntry:
    """One MAINTAINERS section: people, lists, status, patterns."""
    section: str
    maintainers: Tuple[str, ...] = ()
    reviewers: Tuple[str, ...] = ()
    lists: Tuple[str, ...] = ()
    status: str = "Unknown"
    patterns: Tuple[str, ...] = ()
    exclusions: Tuple[str, ...] = ()

    def matches(self, path: str) -> bool:
        if any(_pattern_matches(x, path) for x in self.exclusions):
            return False
        return any(_pattern_matches(p, path) for p in self.patterns)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "section": self.section,
            "maintainers": list(self.maintainers),
            "reviewers": list(self.reviewers),
            "lists": list(self.lists),
            "status": self.status,
            "patterns": list(self.patterns),
            "exclusions": list(self.exclusions),
        }


@dataclass(frozen=True)
class MaintainersIndex:
    """Parsed MAINTAINERS text; lookups are recomputed per call."""
    entries: Tuple[MaintainerEntry, ...] = ()

    def lookup(self, path: str) -> Tuple[MaintainerEntry, ...]:
        return tuple(e for e in self.entries if e.matches(path))

    def recipients_for(self, files: Tuple[str, ...]) -> Dict[str, Any]:
        """Derive To/Cc for the touched files (bug route).

        Maintainers (M:) are To, reviewers (R:) and lists (L:)
        are Cc, in first-seen order, deduplicated.  A file no
        section claims is routed to the fallback general list
        and flagged in ``fallback_files`` -- never dropped.
        """
        to: List[str] = []
        cc: List[str] = []
        per_file: List[Dict[str, Any]] = []
        fallback_files: List[str] = []
        for path in files:
            hits = self.lookup(path)
            if not hits:
                fallback_files.append(path)
                per_file.append({"file": path, "sections": [],
                                 "fallback": True})
                continue
            per_file.append({"file": path,
                             "sections": [e.section for e in hits],
                             "fallback": False})
            for entry in hits:
                for addr in entry.maintainers:
                    if addr not in to:
                        to.append(addr)
                for addr in entry.reviewers + entry.lists:
                    if addr not in cc and addr not in to:
                        cc.append(addr)
        if fallback_files and FALLBACK_LIST not in cc:
            cc.append(FALLBACK_LIST)
        return {"to": to, "cc": cc, "per_file": per_file,
                "fallback_files": fallback_files}


def _entry_from(raw: Dict[str, Any]) -> MaintainerEntry:
    section = raw["section"]
    where = f"MAINTAINERS section {section!r}"
    return MaintainerEntry(
        section=section,
        maintainers=tuple(_address_of(v, where) for v in raw["M"]),
        reviewers=tuple(_address_of(v, where) for v in raw["R"]),
        lists=tuple(_address_of(v, where) for v in raw["L"]),
        status=raw["S"][0] if raw["S"] else "Unknown",
        patterns=tuple(raw["F"]),
        exclusions=tuple(raw["X"]))


def parse_maintainers(text: Any) -> MaintainersIndex:
    """Parse kernel MAINTAINERS text into a MaintainersIndex.

    A section is a header line followed by ``X: value`` field
    lines; a blank line ends the section.  Field lines before
    any header, address fields without an address, and empty
    input are refused by name.  Indented free-text lines inside
    a section are descriptive prose and are ignored, as in the
    real file.
    """
    if not isinstance(text, str) or not text.strip():
        raise MaintainersError("MAINTAINERS text must be a non-empty string")
    if len(text) > MAX_MAINTAINERS_CHARS:
        raise MaintainersError(
            f"MAINTAINERS text exceeds {MAX_MAINTAINERS_CHARS} chars")
    entries: List[MaintainerEntry] = []
    current: Optional[Dict[str, Any]] = None

    def flush() -> None:
        nonlocal current
        if current is not None:
            entries.append(_entry_from(current))
            current = None

    for lineno, line in enumerate(text.splitlines(), 1):
        if not line.strip():
            flush()
            continue
        if line.lstrip().startswith("#"):
            continue
        m = _FIELD_RE.match(line)
        if m:
            if current is None:
                raise MaintainersError(
                    f"line {lineno}: field {m.group(1)!r} appears "
                    "before any section header")
            value = m.group(2).strip()
            if not value:
                raise MaintainersError(
                    f"line {lineno}: field {m.group(1)!r} has no value")
            letter = m.group(1)
            if letter in current:
                current[letter].append(value)
            continue
        if line[0] in " \t":
            continue
        flush()
        current = {"section": line.strip(), "M": [], "R": [],
                   "L": [], "S": [], "F": [], "X": []}
        if len(entries) + 1 > MAX_SECTIONS:
            raise MaintainersError(
                f"MAINTAINERS text exceeds {MAX_SECTIONS} sections")
    flush()
    if not entries:
        raise MaintainersError("no maintainer sections parsed")
    return MaintainersIndex(entries=tuple(entries))


@dataclass(frozen=True)
class SubmissionReview:
    """The human's final review before any submission decision."""
    reviewer: str
    reviewer_kind: str  # must be "human"
    items: Tuple[Tuple[str, str], ...]
    notes: str = ""

    @property
    def complete(self) -> bool:
        states = dict(self.items)
        return all(states.get(i) == "pass" for i in SUBMISSION_ITEMS)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "reviewer": self.reviewer,
            "reviewer_kind": self.reviewer_kind,
            "items": [{"item": k, "state": v} for k, v in self.items],
            "notes": self.notes,
            "complete": self.complete,
        }


def _submission_review_from(data: Any) -> Optional[SubmissionReview]:
    if data is None:
        return None
    if not isinstance(data, dict):
        raise MalformedUpstreamError(
            "submission_review must be an object or null")
    reviewer = _req_text(data.get("reviewer"), "submission_review.reviewer",
                         MAX_AUTHOR_CHARS)
    kind = data.get("reviewer_kind")
    if kind != "human":
        raise AgentSubmissionError(
            f"reviewer_kind must be 'human' (got {kind!r}): the "
            "submission review is the human's final decision step "
            "(Book IV P14; master roadmap section 0, invariant 7)")
    raw_items = data.get("items")
    if not isinstance(raw_items, list) or not raw_items:
        raise MalformedUpstreamError(
            "submission_review.items must be a non-empty list")
    items: List[Tuple[str, str]] = []
    seen = set()
    for entry in raw_items:
        if not isinstance(entry, dict):
            raise MalformedUpstreamError(
                "submission_review items must be objects")
        item, state = entry.get("item"), entry.get("state")
        if item not in SUBMISSION_ITEMS:
            raise MalformedUpstreamError(
                f"unknown submission review item {item!r}")
        if state not in SUBMISSION_STATES:
            raise MalformedUpstreamError(
                f"submission review item {item!r} has bad state {state!r}")
        if item in seen:
            raise MalformedUpstreamError(
                f"duplicate submission review item {item!r}")
        seen.add(item)
        items.append((item, state))
    notes = data.get("notes") or ""
    if not isinstance(notes, str) or len(notes) > MAX_TEXT_CHARS:
        raise MalformedUpstreamError("submission_review.notes is malformed")
    _check_no_dco(notes, "submission review notes")
    return SubmissionReview(reviewer=reviewer, reviewer_kind=kind,
                            items=tuple(sorted(items)), notes=notes)


@dataclass(frozen=True)
class UpstreamDossier:
    """An upstream-ready package bound to one candidate dossier.

    Everything derived (recipients, checklist, readiness, plan)
    is computed from the stored record on every call, so no
    cached verdict can drift from the record.  The candidate is
    the banked LIF-0904 ``PatchDossier`` object itself; its
    content digest pins it.
    """
    upstream_id: str
    candidate: PatchDossier
    disclosure: str
    author_name: str
    author_email: str
    cover_subject: str
    cover_body: str
    maintainers_digest: str
    recipients: Dict[str, Any]
    submission_review: Optional[SubmissionReview] = None
    claimed_status: str = "lab-verified"

    @property
    def route(self) -> str:
        return (ROUTE_PRIVATE if self.disclosure == DISCLOSURE_SECURITY
                else ROUTE_PUBLIC)

    @property
    def candidate_digest(self) -> str:
        return self.candidate.digest

    @property
    def evidence_status(self) -> str:
        # The upstream package never outranks its candidate:
        # LIF-0904 already caps the candidate at human-reviewed
        # and refuses upstream rungs outright.
        return self.candidate.evidence_status

    def checklist(self) -> List[Dict[str, Any]]:
        cand = self.candidate
        items: List[Dict[str, Any]] = []
        items.append({
            "item": "source-commit-pinned", "ok": True,
            "detail": f"affected commit {cand.affected_commit} on "
                      f"{cand.arch} / kernel {cand.kernel_release}"})
        items.append({
            "item": "candidate-dossier-complete",
            "ok": cand.verdict == "complete",
            "detail": f"candidate verdict is {cand.verdict}"})
        items.append({
            "item": "candidate-not-blocked",
            "ok": cand.verdict != "blocked",
            "detail": ("high-risk paths in diff: "
                       + ", ".join(cand.diff.high_risk_paths)
                       if cand.diff.high_risk_paths else
                       "no high-risk paths and no failed review")})
        if self.disclosure == DISCLOSURE_SECURITY:
            items.append({
                "item": "maintainers-and-lists-identified",
                "ok": True,
                "detail": "not applicable: private security route; "
                          "no public maintainers or lists"})
        else:
            matched = [pf for pf in self.recipients["per_file"]
                       if not pf["fallback"]]
            detail = (f"{len(matched)} of "
                      f"{len(self.recipients['per_file'])} files "
                      "matched a MAINTAINERS section")
            if self.recipients["fallback_files"]:
                detail += ("; fallback-routed to " + FALLBACK_LIST + ": "
                           + ", ".join(self.recipients["fallback_files"]))
            items.append({
                "item": "maintainers-and-lists-identified",
                "ok": bool(matched), "detail": detail})
        items.append({
            "item": "cover-letter-present", "ok": True,
            "detail": f"subject: {self.cover_subject}"})
        items.append({
            "item": "dco-agent-unsigned", "ok": True,
            "detail": "no Signed-off-by was added by any agent; the "
                      "human author signs at submission time, "
                      "outside this tool"})
        if self.disclosure == DISCLOSURE_SECURITY:
            route_ok = (self.recipients["to"] == [SECURITY_TEAM_ADDRESS]
                        and not self.recipients["cc"])
            route_detail = ("security disclosure addressed only to "
                            + SECURITY_TEAM_ADDRESS)
        else:
            route_ok = bool(self.recipients["to"] or self.recipients["cc"])
            route_detail = "public bug route to MAINTAINERS recipients"
        items.append({"item": "disclosure-route-correct", "ok": route_ok,
                      "detail": route_detail})
        matrix_bad = [r["name"] for r in cand.test_matrix
                      if r["outcome"] in ("failed", "error")]
        items.append({
            "item": "test-matrix-carried",
            "ok": bool(cand.test_matrix) and not matrix_bad,
            "detail": (f"{len(cand.test_matrix)} recorded rows carried "
                       "from the candidate dossier"
                       if not matrix_bad else
                       "failed/error rows: " + ", ".join(matrix_bad))})
        items.append({
            "item": "verification-limits-stated",
            "ok": bool(cand.limitations),
            "detail": f"{len(cand.limitations)} limitation(s) carried "
                      "from the candidate dossier"})
        review = self.submission_review
        items.append({
            "item": "human-submission-review",
            "ok": bool(review and review.complete),
            "detail": ("no submission review recorded" if review is None
                       else f"review by {review.reviewer}: "
                            + ("complete" if review.complete
                               else "incomplete or has failures"))})
        return items

    def gaps(self) -> List[str]:
        out = [c["item"] for c in self.checklist() if not c["ok"]]
        if self.candidate.verdict == "incomplete":
            out += [f"candidate: {m}" for m in self.candidate.missing()]
        return out

    @property
    def readiness(self) -> str:
        if self.candidate.verdict == "blocked":
            return STATE_BLOCKED
        checks = {c["item"]: c["ok"] for c in self.checklist()}
        pre = [ok for item, ok in checks.items()
               if item != "human-submission-review"]
        if not all(pre):
            return STATE_INCOMPLETE
        if not checks["human-submission-review"]:
            return STATE_AWAITING_HUMAN_REVIEW
        return STATE_READY

    def b4_plan(self) -> Tuple[Dict[str, Any], ...]:
        """The preparation plan, as data.  Never executed here.

        Agent steps are preparation only; every send-shaped step
        is human-only, and the terminal step is the human's
        submission decision.
        """
        commit = self.candidate.affected_commit
        if self.disclosure == DISCLOSURE_SECURITY:
            return (
                {"step": "classify-disclosure", "actor": "agent",
                 "command": None,
                 "detail": "disclosure kind is security: the public "
                           "route is closed for this dossier"},
                {"step": "prepare-private-report", "actor": "agent",
                 "command": None,
                 "detail": "assemble this dossier, the reproducer "
                           "and the minimal diff for a private "
                           "report; no public list is addressed"},
                {"step": "human-review", "actor": "human",
                 "command": None,
                 "detail": "a named human reviews the private "
                           "report and the disclosure decision"},
                {"step": "human-sends-privately", "actor": "human",
                 "command": None,
                 "detail": "the human sends the report to "
                           + SECURITY_TEAM_ADDRESS + " per the "
                           "kernel security-bugs policy; agents "
                           "stop before this step"},
            )
        files = " ".join(self.candidate.diff.files)
        return (
            {"step": "identify-maintainers", "actor": "agent",
             "command": f"scripts/get_maintainer.pl --no-git -f {files}",
             "detail": "recipients in this dossier were derived by "
                       "this tool's MAINTAINERS parser; re-check "
                       "with get_maintainer.pl in a kernel tree"},
            {"step": "prepare-patch-series", "actor": "agent",
             "command": f"git format-patch --cover-letter {commit} "
                        "-o upstream-out/",
             "detail": "or create a b4 prep branch from the pinned "
                       "commit and apply the candidate patch; the "
                       "series holds the candidate patch only"},
            {"step": "checkpatch", "actor": "agent",
             "command": "scripts/checkpatch.pl --strict upstream-out/*.patch",
             "detail": "style gate over the prepared series; "
                       "results are recorded, not assumed"},
            {"step": "attach-cover-letter", "actor": "agent",
             "command": None,
             "detail": "cover letter subject and body are carried "
                       "in this dossier"},
            {"step": "author-signoff", "actor": "human",
             "command": None,
             "detail": "the human author adds their own Signed-off-by "
                       "(DCO) in their editor; agents never add it "
                       "(invariant 7)"},
            {"step": "dry-run", "actor": "human",
             "command": "b4 send --dry-run",
             "detail": "verify the exact recipients and text "
                       "before any real send"},
            {"step": "submission-decision", "actor": "human",
             "command": "b4 send",
             "detail": "terminal step: a human reviews and takes "
                       "the submission decision; agents stop before "
                       "this step, and upstream acceptance is a "
                       "maintainer decision never inferred here"},
        )

    def canonical(self) -> Dict[str, Any]:
        return {
            "schema": UPSTREAM_SCHEMA,
            "schema_version": UPSTREAM_SCHEMA_VERSION,
            "upstream_id": self.upstream_id,
            "candidate": {
                "dossier_id": self.candidate.dossier_id,
                "incident_id": self.candidate.incident_id,
                "digest": self.candidate.digest,
                "affected_commit": self.candidate.affected_commit,
                "arch": self.candidate.arch,
                "kernel_release": self.candidate.kernel_release,
                "verdict": self.candidate.verdict,
                "evidence_status": self.candidate.evidence_status,
                "files": list(self.candidate.diff.files),
            },
            "disclosure": self.disclosure,
            "route": self.route,
            "author": {"name": self.author_name,
                       "email": self.author_email},
            "cover_letter": {"subject": self.cover_subject,
                             "body": self.cover_body},
            "maintainers_digest": self.maintainers_digest,
            "recipients": self.recipients,
            "submission_review": (self.submission_review.to_dict()
                                  if self.submission_review else None),
        }

    @property
    def digest(self) -> str:
        blob = json.dumps(self.canonical(), sort_keys=True,
                          separators=(",", ":"))
        return sha256_of_text(blob)

    def to_dict(self) -> Dict[str, Any]:
        out = self.canonical()
        out["readiness"] = self.readiness
        out["checklist"] = self.checklist()
        out["gaps"] = self.gaps()
        out["b4_plan"] = [dict(s) for s in self.b4_plan()]
        out["digest"] = self.digest
        out["evidence_status"] = self.evidence_status
        out["submitted"] = False
        out["upstream_outcome"] = "not-submitted"
        out["agent_signed_dco"] = False
        return out

    def evidence_fields(self, recorded_at: str, host_local_id: str,
                        evidence_id: str,
                        tool_versions: Dict[str, str],
                        baseline_evidence_id: Optional[str] = None
                        ) -> Dict[str, Any]:
        """LIF-0004 v0.1 evidence record (kind upstream-dossier)."""
        if not tool_versions:
            raise MalformedUpstreamError(
                "tool_versions are required for an evidence record "
                "(LIF-0004 v0.1)")
        limitations = list(self.candidate.limitations) + [
            "b4/git commands in the plan are recorded strings, "
            "never executed by this tool",
            "recipients derive from caller-supplied MAINTAINERS "
            "text, not from a live kernel tree",
            "nothing was sent or submitted anywhere",
        ]
        rec: Dict[str, Any] = {
            "schema": "lifthrasir.evidence.v0.1",
            "schema_version": "0.1",
            "evidence_id": evidence_id,
            "incident_id": self.candidate.incident_id,
            "kind": "upstream-dossier",
            "recorded_at": recorded_at,
            "source": {"component": "upstream-forge",
                       "host_local_id": host_local_id},
            "summary": (f"upstream dossier {self.upstream_id}: "
                        f"readiness {self.readiness}, route "
                        f"{self.route}, candidate verdict "
                        f"{self.candidate.verdict}"),
            "content_digest": self.digest,
            "evidence_status": self.evidence_status,
            "tool_versions": dict(tool_versions),
            "limitations": limitations,
            "artifact_refs": [self.candidate.digest,
                              self.maintainers_digest],
        }
        if baseline_evidence_id:
            rec["baseline_evidence_id"] = baseline_evidence_id
        return rec


def build_upstream_dossier(data: Dict[str, Any]) -> UpstreamDossier:
    """Validate an upstream dossier record and assemble it.

    The candidate half is validated by LIF-0904's own
    ``build_dossier``, so its named refusals (malformed fields,
    a DCO tag in the diff, an agent reviewer, an upstream rung
    claim) propagate unchanged.  This layer adds its own named
    refusals: a submission act requested of an agent, a route
    that contradicts the disclosure kind, a candidate digest pin
    that does not match, or a malformed upstream field.
    """
    if not isinstance(data, dict):
        raise MalformedUpstreamError("upstream dossier must be a JSON object")
    forbidden = sorted(set(data) & _FORBIDDEN_KEYS)
    if forbidden:
        raise AgentSubmissionError(
            f"field(s) {forbidden} refused: this tool prepares "
            "patches for a human to review and submit; it never "
            "sends, submits or signs (master roadmap section 0, "
            "invariant 7)")
    unknown = sorted(set(data) - _ALLOWED_KEYS)
    if unknown:
        raise MalformedUpstreamError(
            f"unknown upstream dossier field(s): {unknown}")
    claimed = data.get("evidence_status") or "lab-verified"
    if claimed not in EVIDENCE_LADDER:
        raise MalformedUpstreamError(f"unknown evidence_status {claimed!r}")
    if EVIDENCE_LADDER.index(claimed) > EVIDENCE_LADDER.index(
            "human-reviewed"):
        raise UpstreamClaimError(
            f"evidence_status {claimed!r} refused: an upstream "
            "dossier never claims submission or acceptance; the "
            "human contributor submits and maintainers decide "
            "(Book IV P14)")
    uid = data.get("upstream_id")
    if not isinstance(uid, str) or not _ID_RE.match(uid) \
            or len(uid) > MAX_UPSTREAM_ID_CHARS:
        raise MalformedUpstreamError(f"bad upstream_id {uid!r}")
    candidate = build_dossier(data.get("candidate"))
    pin = data.get("candidate_digest")
    if pin is not None and pin != candidate.digest:
        raise MalformedUpstreamError(
            f"candidate_digest pin mismatch: record pins {pin!r} "
            f"but the candidate dossier digests to "
            f"{candidate.digest!r}; a stale or tampered candidate "
            "is refused, never silently re-pinned")
    disclosure = data.get("disclosure")
    if disclosure not in DISCLOSURES:
        raise MalformedUpstreamError(
            f"disclosure must be one of {DISCLOSURES}, got {disclosure!r}")
    route = data.get("route")
    expected_route = (ROUTE_PRIVATE if disclosure == DISCLOSURE_SECURITY
                      else ROUTE_PUBLIC)
    if route is not None and route != expected_route:
        raise DisclosureRouteError(
            f"route {route!r} contradicts disclosure "
            f"{disclosure!r}: a security disclosure goes only to "
            f"{SECURITY_TEAM_ADDRESS} (kernel security-bugs "
            "policy), and a public bug report is not routed "
            "privately by this tool")
    author = data.get("author")
    if not isinstance(author, dict):
        raise MalformedUpstreamError("author must be an object")
    if "kind" in author and author.get("kind") != "human":
        raise AgentSubmissionError(
            "author.kind must be 'human': the submitting author "
            "is a named human contributor, never an agent")
    author_name = _req_text(author.get("name"), "author.name",
                            MAX_AUTHOR_CHARS)
    author_email = author.get("email")
    if not isinstance(author_email, str) \
            or not _EMAIL_RE.match(author_email):
        raise MalformedUpstreamError(
            f"author.email is not an email address: {author_email!r}")
    if _AGENT_NAME_RE.search(author_name) \
            or _AGENT_NAME_RE.search(author_email):
        raise AgentSubmissionError(
            "the recorded author names the agent itself: the "
            "submitting author must be a named human contributor "
            "(invariant 7)")
    cover = data.get("cover_letter")
    if not isinstance(cover, dict):
        raise MalformedUpstreamError("cover_letter must be an object")
    cover_subject = _req_text(cover.get("subject"),
                              "cover_letter.subject", MAX_SUBJECT_CHARS)
    cover_body = _req_text(cover.get("body"), "cover_letter.body")
    _check_no_dco(cover_subject, "cover letter subject")
    _check_no_dco(cover_body, "cover letter body")
    maintainers_text = _req_text(data.get("maintainers"), "maintainers",
                                 MAX_MAINTAINERS_CHARS)
    index = parse_maintainers(maintainers_text)
    if disclosure == DISCLOSURE_SECURITY:
        recipients: Dict[str, Any] = {
            "to": [SECURITY_TEAM_ADDRESS],
            "cc": [],
            "per_file": [{"file": f, "sections": [],
                          "fallback": False, "private": True}
                         for f in candidate.diff.files],
            "fallback_files": [],
        }
    else:
        recipients = index.recipients_for(candidate.diff.files)
    return UpstreamDossier(
        upstream_id=uid, candidate=candidate, disclosure=disclosure,
        author_name=author_name, author_email=author_email,
        cover_subject=cover_subject, cover_body=cover_body,
        maintainers_digest=sha256_of_text(maintainers_text),
        recipients=recipients,
        submission_review=_submission_review_from(
            data.get("submission_review")),
        claimed_status=claimed)


def summarize_upstream(dossiers: List[UpstreamDossier]) -> Dict[str, Any]:
    counts = {s: 0 for s in READINESS_STATES}
    for d in dossiers:
        counts[d.readiness] += 1
    return {"total": len(dossiers), "readiness": counts,
            "ready_ids": sorted(d.upstream_id for d in dossiers
                                if d.readiness == STATE_READY),
            "submitted": 0}
