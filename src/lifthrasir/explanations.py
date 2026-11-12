"""Structured explanation and hypothesis templates with citations (LIF-0602).

SPDX-License-Identifier: GPL-2.0-only

Home justification: master roadmap section 4 and roadmap/02 (P6)
fix the intelligence layer in Python (ADR-0002 D2) beside the
provider protocol it explains: roadmap/02 names this slice's
surface exactly -- "Implement three prompt templates: incident
summary, rival causal hypotheses, experiment proposal" plus
"structured JSON validation, response length caps, source
citations".  LIF-0601 banked the replaceable provider protocol
(``modelprovider.py``) whose results carry citations, and LIF-0305
banked the causal hypothesis records (``hypotheses.py``) whose
evidence ids explanations must trace to.  Like LIF-0601, this slice
deliberately does NOT touch the package ``__init__`` export list:
the banking seat unions export lists, and ``from lifthrasir import
explanations`` works either way.  Desired exports are flagged in
CAMPAIGN_STATE.md.

What this slice builds:

- ``Citation`` / ``CitationRegistry``: the evidence side of a
  citation.  A citation is only a reference: an ``ev-...`` id, a
  source kind, a locator, and an optional sha256 digest of the
  referenced evidence.  The registry is the resolution oracle for
  this layer: a citation id either resolves to a registered
  ``Citation`` or it does not exist for rendering purposes.
  Registries are built from real referenced evidence only -- from
  validated LIF-0305 hypothesis records (their evidence_for /
  evidence_against ids) or from a LIF-0601 request's context
  references -- never from free text a model emitted.
- ``TemplateSpec`` / ``SectionSpec`` and the three builtin
  templates roadmap/02 names (``tmpl-incident-summary``,
  ``tmpl-rival-hypotheses``, ``tmpl-experiment-proposal``), each
  versioned, each section declaring its placeholders and how many
  citations that section must carry.
- ``render_template``: the render-time gate.  Values must cover
  exactly the template placeholders; every citation must be
  well-formed AND resolve in the registry (an invented citation
  is refused with ``UnresolvedCitationError`` -- the template-layer
  twin of LIF-0601's provider-layer refusal); sections must meet
  their citation minimums; the whole document must cite at least
  once; and the rendered text is length-capped.  The result is a
  ``RenderedDocument`` whose digest binds template, text and
  citations together.
- ``validate_structured_explanation``: the structured-JSON gate
  for ``explanation-v0.1`` payloads, in the LIF-0004 v0.1 dict
  style -- unknown fields refused, citations must resolve.
- ``check_model_result_citations``: the bridge to LIF-0601.  A
  ``ModelResult`` (object or dict) passes only when every result
  citation -- and every citation inside its structured payload --
  resolves in the registry.  The provider layer already refuses
  citations outside the request's context references; this layer
  refuses citations that resolve to no registered evidence.
- ``hypothesis_record_from_template`` /
  ``explanation_for_hypothesis``: the bridge to LIF-0305.  The
  first builds a hypothesis record whose evidence must resolve,
  then passes the banked ``validate_hypothesis`` gate, so a
  templated hypothesis is a real v0.1 record or nothing.  The
  second renders an explanation of a recorded hypothesis only
  when every evidence id it cites resolves.

Evidence-status honesty: templates, registries and rendered
documents are proven at fixture/lab level by this slice's tests.
No real inference is claimed and none is performed here: this
module imports no model, network, socket or subprocess machinery,
and a rendered document is a structured claim with traceable
citations, not a proof of the claim itself.
"""
from __future__ import annotations

import copy
import hashlib
import json
import re
import string
from dataclasses import dataclass
from typing import Any, Dict, List, Mapping, Optional, Tuple

from .hypotheses import validate_hypothesis
from .modelprovider import ModelResult, result_from_dict

TEMPLATE_SCHEMA = "lifthrasir.templates.v0.1"
TEMPLATE_SCHEMA_VERSION = "0.1"
EXPLANATION_SCHEMA = "lifthrasir.explanation.v0.1"
EXPLANATION_SCHEMA_VERSION = "0.1"
TEMPLATE_VERSION = "1"

TEMPLATE_KINDS = ("explanation", "hypothesis")
CITATION_KINDS = (
    "sensor-reading", "log-excerpt", "hypothesis-record",
    "experiment-result", "document", "model-result", "fixture",
)

MAX_RENDER_CHARS = 16384
MAX_VALUE_CHARS = 4096
MAX_VALUES = 32
MAX_CITATIONS = 64
MAX_LOCATOR_CHARS = 256

_CITATION_RE = re.compile(r"^ev-[a-z0-9][a-z0-9-]*$")
_TEMPLATE_RE = re.compile(r"^tmpl-[a-z0-9][a-z0-9-]*$")
_SECTION_RE = re.compile(r"^[a-z][a-z0-9-]*$")
_HASH_RE = re.compile(r"^[0-9a-f]{64}$")
_FORMATTER = string.Formatter()


class TemplateError(Exception):
    """Base class for all named template/citation refusals."""


class MalformedTemplateError(TemplateError):
    """Raised when a template, value set or document breaks a rule."""


class UnknownTemplateError(TemplateError):
    """Raised when a render names a template that does not exist."""


class DuplicateCitationError(TemplateError):
    """Raised when a citation id is registered or cited twice."""


class CitationShapeError(TemplateError):
    """Raised when a citation id or record is malformed."""


class UnresolvedCitationError(TemplateError):
    """Raised when a citation resolves to no registered evidence.

    This is the invented-citation refusal at the template layer:
    a citation that names no real referenced evidence in the
    registry can never appear in a rendered document, a validated
    structured explanation, or a templated hypothesis record.
    """


class MissingValueError(TemplateError):
    """Raised when a required template placeholder has no value."""


def _canonical(obj: Any) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=True).encode("utf-8")


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def check_citation_id(value: Any) -> str:
    """Return a well-formed citation id or raise CitationShapeError."""
    if not isinstance(value, str) or not _CITATION_RE.match(value):
        raise CitationShapeError(
            f"citation id {value!r} is not a well-formed evidence "
            f"id (ev-...)")
    return value


@dataclass(frozen=True)
class Citation:
    """One reference to one piece of real evidence."""

    citation_id: str
    source_kind: str
    locator: str
    title: str = ""
    digest: Optional[str] = None

    def __post_init__(self) -> None:
        check_citation_id(self.citation_id)
        if self.source_kind not in CITATION_KINDS:
            raise CitationShapeError(
                f"source_kind {self.source_kind!r} is not one of "
                f"{list(CITATION_KINDS)}")
        if not isinstance(self.locator, str) or not self.locator \
                or len(self.locator) > MAX_LOCATOR_CHARS:
            raise CitationShapeError(
                f"locator must be a non-empty string of at most "
                f"{MAX_LOCATOR_CHARS} chars, got {self.locator!r}")
        if not isinstance(self.title, str):
            raise CitationShapeError("title must be a string")
        if self.digest is not None and not _HASH_RE.match(self.digest):
            raise CitationShapeError(
                f"digest must be a sha256 hex digest, got "
                f"{self.digest!r}")

    def to_dict(self) -> Dict[str, Any]:
        return {"citation_id": self.citation_id,
                "source_kind": self.source_kind,
                "locator": self.locator, "title": self.title,
                "digest": self.digest}

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "Citation":
        if not isinstance(data, Mapping):
            raise CitationShapeError(
                f"citation must be a mapping, got "
                f"{type(data).__name__}")
        allowed = {"citation_id", "source_kind", "locator",
                   "title", "digest"}
        unknown = sorted(set(data) - allowed)
        if unknown:
            raise CitationShapeError(
                f"unknown citation fields: {unknown}")
        for required in ("citation_id", "source_kind", "locator"):
            if required not in data:
                raise CitationShapeError(
                    f"citation is missing required field {required!r}")
        kwargs = {k: data[k] for k in allowed if k in data}
        return cls(**kwargs)


class CitationRegistry:
    """The resolution oracle: registered evidence, nothing else.

    Registration is explicit and append-only in spirit: an id maps
    to exactly one Citation for the life of the registry, and a
    second registration of the same id is refused rather than
    silently rewriting what a citation points at.
    """

    def __init__(self, citations: Any = ()) -> None:
        self._by_id: Dict[str, Citation] = {}
        self._order: List[str] = []
        for citation in citations:
            self.register(citation)

    def register(self, citation: Citation) -> str:
        if not isinstance(citation, Citation):
            raise CitationShapeError(
                f"register() needs a Citation, got "
                f"{type(citation).__name__}")
        if citation.citation_id in self._by_id:
            raise DuplicateCitationError(
                f"citation id {citation.citation_id!r} is already "
                f"registered; a citation id names one piece of "
                f"evidence and is never rewritten")
        self._by_id[citation.citation_id] = citation
        self._order.append(citation.citation_id)
        return citation.citation_id

    def register_many(self, citations: Any) -> List[str]:
        return [self.register(c) for c in citations]

    def __contains__(self, citation_id: Any) -> bool:
        return citation_id in self._by_id

    def __len__(self) -> int:
        return len(self._order)

    def ids(self) -> List[str]:
        return list(self._order)

    def resolve(self, citation_id: Any) -> Citation:
        """Return the registered Citation or refuse, by name."""
        check_citation_id(citation_id)
        try:
            return self._by_id[citation_id]
        except KeyError:
            raise UnresolvedCitationError(
                f"citation {citation_id!r} resolves to no "
                f"registered evidence; invented citations are "
                f"refused") from None

    def resolve_all(self, citation_ids: Any) -> Tuple[Citation, ...]:
        return tuple(self.resolve(c) for c in citation_ids)

    def to_dicts(self) -> List[Dict[str, Any]]:
        return [self._by_id[c].to_dict() for c in self._order]

    @classmethod
    def from_dicts(cls, data: Any) -> "CitationRegistry":
        if not isinstance(data, (list, tuple)):
            raise CitationShapeError(
                "citation registry data must be a list of citations")
        return cls(Citation.from_dict(d) for d in data)

    @classmethod
    def from_context_refs(cls, context_refs: Any,
                          source_kind: str = "document",
                          locator_prefix: str = "context"
                          ) -> "CitationRegistry":
        """Build a registry from a LIF-0601 request's context refs.

        Every reference must already be a well-formed evidence id;
        a free-form string a model invented is refused here, before
        any rendering happens.
        """
        registry = cls()
        for ref in context_refs:
            check_citation_id(ref)
            registry.register(Citation(
                citation_id=ref, source_kind=source_kind,
                locator=f"{locator_prefix}:{ref}"))
        return registry

    @classmethod
    def from_hypothesis_record(cls, record: Mapping[str, Any]
                               ) -> "CitationRegistry":
        """Build a registry from one validated LIF-0305 record.

        The record passes the banked validate_hypothesis gate
        first; its evidence_for and evidence_against ids become
        citations located at the hypothesis that cited them.
        """
        checked = validate_hypothesis(copy.deepcopy(dict(record)))
        registry = cls()
        locator = f"hypothesis:{checked['hypothesis_id']}"
        for field in ("evidence_for", "evidence_against"):
            for ev_id in checked[field]:
                if ev_id not in registry:
                    registry.register(Citation(
                        citation_id=ev_id,
                        source_kind="hypothesis-record",
                        locator=locator))
        return registry

    def add_hypothesis_record(self, record: Mapping[str, Any]) -> None:
        """Register the evidence ids of one validated record."""
        other = type(self).from_hypothesis_record(record)
        for citation_id in other.ids():
            if citation_id not in self._by_id:
                self.register(other.resolve(citation_id))


@dataclass(frozen=True)
class SectionSpec:
    """One named section of a template."""

    name: str
    heading: str
    body: str
    required_citations: int = 0

    def __post_init__(self) -> None:
        if not isinstance(self.name, str) or not _SECTION_RE.match(self.name):
            raise MalformedTemplateError(
                f"section name {self.name!r} must match "
                f"[a-z][a-z0-9-]*")
        if not isinstance(self.heading, str) or not self.heading:
            raise MalformedTemplateError(
                "section heading must be a non-empty string")
        if not isinstance(self.body, str) or not self.body.strip():
            raise MalformedTemplateError(
                f"section {self.name!r} body must be non-empty")
        if isinstance(self.required_citations, bool) or not isinstance(
                self.required_citations, int) or self.required_citations < 0:
            raise MalformedTemplateError(
                "required_citations must be a non-negative int")
        self.placeholders  # noqa: B018 - validation at construction

    @property
    def placeholders(self) -> Tuple[str, ...]:
        names: List[str] = []
        try:
            parsed = list(_FORMATTER.parse(self.body))
        except ValueError as exc:
            raise MalformedTemplateError(
                f"section {self.name!r} body is not a valid format "
                f"template: {exc}") from None
        for _, field_name, format_spec, conversion in parsed:
            if field_name is None:
                continue
            if not field_name.isidentifier() or format_spec or conversion:
                raise MalformedTemplateError(
                    f"section {self.name!r} placeholder "
                    f"{field_name!r} must be a plain identifier with "
                    f"no format spec or conversion")
            if field_name not in names:
                names.append(field_name)
        return tuple(names)


@dataclass(frozen=True)
class TemplateSpec:
    """One versioned structured template."""

    template_id: str
    kind: str
    title: str
    sections: Tuple[SectionSpec, ...]
    version: str = TEMPLATE_VERSION

    def __post_init__(self) -> None:
        if not isinstance(self.template_id, str) or not _TEMPLATE_RE.match(
                self.template_id):
            raise MalformedTemplateError(
                f"template_id {self.template_id!r} must match "
                f"tmpl-<slug>")
        if self.kind not in TEMPLATE_KINDS:
            raise MalformedTemplateError(
                f"template kind {self.kind!r} is not one of "
                f"{list(TEMPLATE_KINDS)}")
        if not isinstance(self.title, str) or not self.title:
            raise MalformedTemplateError(
                "template title must be a non-empty string")
        sections = tuple(self.sections)
        object.__setattr__(self, "sections", sections)
        if not sections:
            raise MalformedTemplateError(
                "a template needs at least one section")
        names = [s.name for s in sections]
        if len(set(names)) != len(names):
            raise MalformedTemplateError(
                f"template section names must be unique: {names}")
        for section in sections:
            if not isinstance(section, SectionSpec):
                raise MalformedTemplateError(
                    "template sections must be SectionSpec objects")

    @property
    def placeholders(self) -> Tuple[str, ...]:
        names: List[str] = []
        for section in self.sections:
            for name in section.placeholders:
                if name not in names:
                    names.append(name)
        return tuple(names)

    def section(self, name: str) -> SectionSpec:
        for section in self.sections:
            if section.name == name:
                return section
        raise MalformedTemplateError(
            f"template {self.template_id!r} has no section {name!r}")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "schema": TEMPLATE_SCHEMA,
            "schema_version": TEMPLATE_SCHEMA_VERSION,
            "template_id": self.template_id, "kind": self.kind,
            "title": self.title, "version": self.version,
            "sections": [
                {"name": s.name, "heading": s.heading, "body": s.body,
                 "required_citations": s.required_citations,
                 "placeholders": list(s.placeholders)}
                for s in self.sections],
        }


BUILTIN_TEMPLATES: Tuple[TemplateSpec, ...] = (
    TemplateSpec(
        template_id="tmpl-incident-summary", kind="explanation",
        title="Incident summary",
        sections=(
            SectionSpec(
                name="summary", heading="Summary",
                body="Incident {incident_id}: {summary}",
                required_citations=1),
            SectionSpec(
                name="evidence", heading="Evidence",
                body="{evidence_detail}", required_citations=1),
            SectionSpec(
                name="uncertainty", heading="Uncertainty",
                body="Uncertainty: {uncertainty}",
                required_citations=0),
        )),
    TemplateSpec(
        template_id="tmpl-rival-hypotheses", kind="hypothesis",
        title="Rival causal hypotheses",
        sections=(
            SectionSpec(
                name="claim", heading="Claim",
                body="Hypothesis {hypothesis_id}: {claim}",
                required_citations=1),
            SectionSpec(
                name="counterevidence", heading="Counterevidence",
                body="Counterevidence: {counterevidence}",
                required_citations=0),
            SectionSpec(
                name="test-plan", heading="Test plan",
                body="{test_plan}", required_citations=0),
        )),
    TemplateSpec(
        template_id="tmpl-experiment-proposal", kind="hypothesis",
        title="Experiment proposal",
        sections=(
            SectionSpec(
                name="proposal", heading="Proposal",
                body="Experiment {experiment_id}: {proposal}",
                required_citations=1),
            SectionSpec(
                name="method", heading="Method",
                body="{method}", required_citations=0),
            SectionSpec(
                name="expected", heading="Expected result",
                body="{expected}", required_citations=0),
        )),
)

TEMPLATES: Dict[str, TemplateSpec] = {
    t.template_id: t for t in BUILTIN_TEMPLATES}
TEMPLATE_IDS: Tuple[str, ...] = tuple(TEMPLATES)


def get_template(template_id: Any) -> TemplateSpec:
    if not isinstance(template_id, str) or template_id not in TEMPLATES:
        raise UnknownTemplateError(
            f"unknown template {template_id!r}; builtin templates "
            f"are {list(TEMPLATE_IDS)}")
    return TEMPLATES[template_id]


def list_templates() -> List[TemplateSpec]:
    return [TEMPLATES[t] for t in TEMPLATE_IDS]


def templates_as_dicts() -> List[Dict[str, Any]]:
    return [t.to_dict() for t in list_templates()]


@dataclass(frozen=True)
class RenderedDocument:
    """One rendered, citation-checked structured document."""

    template_id: str
    kind: str
    text: str
    citations: Tuple[str, ...]
    sections: Tuple[str, ...]
    digest: str = ""

    def __post_init__(self) -> None:
        template = get_template(self.template_id)
        if self.kind != template.kind:
            raise MalformedTemplateError(
                f"document kind {self.kind!r} does not match "
                f"template kind {template.kind!r}")
        if not isinstance(self.text, str) or not self.text:
            raise MalformedTemplateError("document text must be non-empty")
        if len(self.text) > MAX_RENDER_CHARS:
            raise MalformedTemplateError(
                f"document text is {len(self.text)} chars, cap is "
                f"{MAX_RENDER_CHARS}")
        citations = tuple(self.citations)
        object.__setattr__(self, "citations", citations)
        for citation_id in citations:
            check_citation_id(citation_id)
        if len(set(citations)) != len(citations):
            raise DuplicateCitationError(
                "a document must not cite the same evidence twice")
        if not citations:
            raise UnresolvedCitationError(
                "a structured document must cite at least one piece "
                "of registered evidence")
        object.__setattr__(self, "sections", tuple(self.sections))
        expected = document_digest(self.template_id, self.text, citations)
        if not self.digest:
            object.__setattr__(self, "digest", expected)
        elif self.digest != expected:
            raise MalformedTemplateError(
                "document digest does not match its template, text "
                "and citations; the document was altered after "
                "rendering")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "schema": EXPLANATION_SCHEMA,
            "schema_version": EXPLANATION_SCHEMA_VERSION,
            "template_id": self.template_id, "kind": self.kind,
            "text": self.text, "citations": list(self.citations),
            "sections": list(self.sections), "digest": self.digest,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "RenderedDocument":
        if not isinstance(data, Mapping):
            raise MalformedTemplateError(
                f"document must be a mapping, got "
                f"{type(data).__name__}")
        allowed = {"schema", "schema_version", "template_id", "kind",
                   "text", "citations", "sections", "digest"}
        unknown = sorted(set(data) - allowed)
        if unknown:
            raise MalformedTemplateError(
                f"unknown document fields: {unknown}")
        if "schema" in data and data["schema"] != EXPLANATION_SCHEMA:
            raise MalformedTemplateError(
                f"schema must be {EXPLANATION_SCHEMA!r}, got "
                f"{data['schema']!r}")
        if "schema_version" in data and data["schema_version"] != \
                EXPLANATION_SCHEMA_VERSION:
            raise MalformedTemplateError(
                f"schema_version must be "
                f"{EXPLANATION_SCHEMA_VERSION!r}, got "
                f"{data['schema_version']!r}")
        for required in ("template_id", "kind", "text", "citations",
                         "sections"):
            if required not in data:
                raise MalformedTemplateError(
                    f"document is missing required field {required!r}")
        return cls(template_id=data["template_id"], kind=data["kind"],
                   text=data["text"],
                   citations=tuple(data["citations"]),
                   sections=tuple(data["sections"]),
                   digest=data.get("digest", ""))


def document_digest(template_id: str, text: str,
                    citations: Any) -> str:
    return _sha256(_canonical({
        "template_id": template_id, "text": text,
        "citations": list(citations)}))


def _check_values(template: TemplateSpec,
                  values: Any) -> Dict[str, str]:
    if not isinstance(values, Mapping):
        raise MalformedTemplateError(
            f"values must be a mapping, got {type(values).__name__}")
    if len(values) > MAX_VALUES:
        raise MalformedTemplateError(
            f"values carries {len(values)} entries, cap is {MAX_VALUES}")
    expected = set(template.placeholders)
    supplied = set(values)
    missing = sorted(expected - supplied)
    if missing:
        raise MissingValueError(
            f"template {template.template_id!r} is missing values "
            f"for placeholders: {missing}")
    unknown = sorted(supplied - expected)
    if unknown:
        raise MalformedTemplateError(
            f"values carry placeholders the template does not "
            f"declare: {unknown}")
    checked: Dict[str, str] = {}
    for name in template.placeholders:
        value = values[name]
        if not isinstance(value, str) or not value.strip():
            raise MalformedTemplateError(
                f"value for placeholder {name!r} must be a "
                f"non-empty string")
        if len(value) > MAX_VALUE_CHARS:
            raise MalformedTemplateError(
                f"value for placeholder {name!r} is {len(value)} "
                f"chars, cap is {MAX_VALUE_CHARS}")
        checked[name] = value
    return checked


def _check_section_citations(
        template: TemplateSpec, citations_by_section: Any,
        registry: CitationRegistry) -> Dict[str, Tuple[str, ...]]:
    if citations_by_section is None:
        citations_by_section = {}
    if not isinstance(citations_by_section, Mapping):
        raise MalformedTemplateError(
            "citations_by_section must be a mapping of section "
            "name to citation id list")
    if not isinstance(registry, CitationRegistry):
        raise MalformedTemplateError(
            "rendering needs a CitationRegistry as the citation "
            "resolution oracle")
    known = {s.name for s in template.sections}
    unknown = sorted(set(citations_by_section) - known)
    if unknown:
        raise MalformedTemplateError(
            f"citations name sections the template does not "
            f"declare: {unknown}")
    checked: Dict[str, Tuple[str, ...]] = {}
    seen: List[str] = []
    for section in template.sections:
        raw = citations_by_section.get(section.name, [])
        if isinstance(raw, str) or not isinstance(raw, (list, tuple)):
            raise MalformedTemplateError(
                f"citations for section {section.name!r} must be a "
                f"list of citation ids")
        ids = tuple(raw)
        if len(ids) < section.required_citations:
            raise UnresolvedCitationError(
                f"section {section.name!r} of template "
                f"{template.template_id!r} requires at least "
                f"{section.required_citations} citation(s), got "
                f"{len(ids)}")
        for citation_id in ids:
            registry.resolve(citation_id)
            if citation_id in seen:
                raise DuplicateCitationError(
                    f"citation {citation_id!r} is cited more than "
                    f"once in one document")
            seen.append(citation_id)
        checked[section.name] = ids
    if len(seen) > MAX_CITATIONS:
        raise MalformedTemplateError(
            f"document cites {len(seen)} pieces of evidence, cap "
            f"is {MAX_CITATIONS}")
    return checked


def render_template(template: Any, values: Any,
                    citations_by_section: Any,
                    registry: CitationRegistry) -> RenderedDocument:
    """Render one template under the full citation gate.

    ``template`` is a TemplateSpec or a builtin template id.
    Every citation must resolve in ``registry``; rendering is
    deterministic -- same template, values, citations and registry
    state in, same document and digest out.
    """
    if isinstance(template, str):
        spec = get_template(template)
    elif isinstance(template, TemplateSpec):
        spec = template
    else:
        raise MalformedTemplateError(
            f"template must be a template id or TemplateSpec, got "
            f"{type(template).__name__}")
    checked_values = _check_values(spec, values)
    checked_citations = _check_section_citations(
        spec, citations_by_section, registry)
    parts: List[str] = []
    all_citations: List[str] = []
    for section in spec.sections:
        body = section.body.format(**checked_values)
        ids = checked_citations[section.name]
        all_citations.extend(ids)
        part = f"## {section.heading}\n{body}"
        if ids:
            part += "\nCitations: " + ", ".join(
                f"[{c}]" for c in ids)
        parts.append(part)
    text = "\n\n".join(parts)
    if len(text) > MAX_RENDER_CHARS:
        raise MalformedTemplateError(
            f"rendered document is {len(text)} chars, cap is "
            f"{MAX_RENDER_CHARS}")
    return RenderedDocument(
        template_id=spec.template_id, kind=spec.kind, text=text,
        citations=tuple(all_citations),
        sections=tuple(s.name for s in spec.sections))


def validate_rendered_document(data: Any,
                               registry: CitationRegistry
                               ) -> RenderedDocument:
    """Re-validate a rendered document dict against a registry."""
    document = RenderedDocument.from_dict(data)
    registry.resolve_all(document.citations)
    return document


_EXPLANATION_FIELDS = {
    "schema", "schema_version", "kind", "summary", "citations",
    "uncertainty", "hypothesis_id", "incident_id",
}


def validate_structured_explanation(data: Any,
                                    registry: CitationRegistry
                                    ) -> Dict[str, Any]:
    """Validate one explanation-v0.1 structured payload.

    Returns a defensive deep copy on success.  Unknown fields are
    refused, the summary must be non-empty, uncertainty must be in
    [0, 1] when present, and every citation must resolve in the
    registry -- a structured payload citing invented evidence is
    refused exactly like a rendered document citing it.
    """
    if not isinstance(data, Mapping):
        raise MalformedTemplateError(
            f"structured explanation must be a mapping, got "
            f"{type(data).__name__}")
    unknown = sorted(set(data) - _EXPLANATION_FIELDS)
    if unknown:
        raise MalformedTemplateError(
            f"unknown explanation fields: {unknown}")
    if data.get("schema") != EXPLANATION_SCHEMA:
        raise MalformedTemplateError(
            f"schema must be {EXPLANATION_SCHEMA!r}, got "
            f"{data.get('schema')!r}")
    if data.get("schema_version") != EXPLANATION_SCHEMA_VERSION:
        raise MalformedTemplateError(
            f"schema_version must be {EXPLANATION_SCHEMA_VERSION!r}, "
            f"got {data.get('schema_version')!r}")
    if data.get("kind") not in TEMPLATE_KINDS:
        raise MalformedTemplateError(
            f"kind {data.get('kind')!r} is not one of "
            f"{list(TEMPLATE_KINDS)}")
    summary = data.get("summary")
    if not isinstance(summary, str) or not summary.strip():
        raise MalformedTemplateError("summary must be a non-empty string")
    if len(summary) > MAX_VALUE_CHARS:
        raise MalformedTemplateError(
            f"summary is {len(summary)} chars, cap is {MAX_VALUE_CHARS}")
    citations = data.get("citations")
    if isinstance(citations, str) or not isinstance(citations, (list, tuple)) \
            or not citations:
        raise UnresolvedCitationError(
            "a structured explanation must cite at least one piece "
            "of registered evidence")
    if len(citations) > MAX_CITATIONS:
        raise MalformedTemplateError(
            f"explanation cites {len(citations)} pieces of evidence, "
            f"cap is {MAX_CITATIONS}")
    if len(set(citations)) != len(citations):
        raise DuplicateCitationError(
            "a structured explanation must not cite the same "
            "evidence twice")
    registry.resolve_all(tuple(citations))
    uncertainty = data.get("uncertainty")
    if uncertainty is not None:
        if isinstance(uncertainty, bool) or not isinstance(
                uncertainty, (int, float)) or not 0.0 <= float(
                uncertainty) <= 1.0:
            raise MalformedTemplateError(
                f"uncertainty must be in 0..1 or absent, got "
                f"{uncertainty!r}")
    return copy.deepcopy(dict(data))


def check_model_result_citations(result: Any,
                                 registry: CitationRegistry
                                 ) -> ModelResult:
    """Check a LIF-0601 ModelResult against the registry.

    Accepts a ModelResult or its dict form.  Every result citation
    must resolve, and citations inside the structured payload must
    both resolve and be among the result's own citations -- a
    payload cannot smuggle in a citation the result does not carry.
    Returns the checked ModelResult.
    """
    if isinstance(result, Mapping):
        checked = result_from_dict(result)
    elif isinstance(result, ModelResult):
        checked = result
    else:
        raise MalformedTemplateError(
            f"result must be a ModelResult or its dict form, got "
            f"{type(result).__name__}")
    registry.resolve_all(checked.citations)
    if isinstance(checked.structured, dict):
        payload_citations = checked.structured.get("citations")
        if payload_citations is not None:
            if isinstance(payload_citations, str) or not isinstance(
                    payload_citations, (list, tuple)):
                raise MalformedTemplateError(
                    "structured payload citations must be a list")
            registry.resolve_all(tuple(payload_citations))
            smuggled = sorted(
                set(payload_citations) - set(checked.citations))
            if smuggled:
                raise UnresolvedCitationError(
                    f"structured payload cites {smuggled}, which "
                    f"the result itself does not cite; payload "
                    f"citations must be a subset of result citations")
    return checked


def hypothesis_record_from_template(values: Any, registry: CitationRegistry
                                    ) -> Dict[str, Any]:
    """Build a LIF-0305 v0.1 hypothesis record from template values.

    ``values`` carries exactly the v0.1 record fields.  Every
    evidence id in evidence_for / evidence_against must resolve in
    the registry BEFORE the record is built, and the built record
    must pass the banked validate_hypothesis gate -- including its
    cross-field rules (supported needs evidence_for, refuted needs
    evidence_against).
    """
    if not isinstance(values, Mapping):
        raise MalformedTemplateError(
            f"hypothesis values must be a mapping, got "
            f"{type(values).__name__}")
    for field in ("evidence_for", "evidence_against"):
        ids = values.get(field)
        if isinstance(ids, (list, tuple)):
            registry.resolve_all(tuple(ids))
    return validate_hypothesis(copy.deepcopy(dict(values)))


def explanation_for_hypothesis(record: Any, registry: CitationRegistry
                               ) -> RenderedDocument:
    """Render a rival-hypotheses explanation of a recorded hypothesis.

    The record passes the banked validate_hypothesis gate first.
    Every evidence id it cites must resolve in the registry, and a
    record citing no evidence at all cannot be explained with
    citations -- that refusal is deliberate: an explanation with
    citations needs real referenced evidence to cite.
    """
    checked = validate_hypothesis(copy.deepcopy(dict(record)))
    evidence_for = list(checked["evidence_for"])
    evidence_against = list(checked["evidence_against"])
    if not evidence_for and not evidence_against:
        raise UnresolvedCitationError(
            f"hypothesis {checked['hypothesis_id']!r} cites no "
            f"evidence; an explanation with citations cannot be "
            f"rendered from an evidence-free claim")
    registry.resolve_all(tuple(evidence_for + evidence_against))
    values = {
        "hypothesis_id": checked["hypothesis_id"],
        "claim": checked["claim"],
        "counterevidence": (", ".join(evidence_against)
                            if evidence_against else "none recorded"),
        "test_plan": checked["test_plan"],
    }
    citations = {
        "claim": evidence_for if evidence_for else evidence_against,
        "counterevidence": evidence_against if evidence_for else [],
        "test-plan": [],
    }
    return render_template("tmpl-rival-hypotheses", values,
                           citations, registry)
