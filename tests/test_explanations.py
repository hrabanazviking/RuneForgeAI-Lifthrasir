# SPDX-License-Identifier: GPL-2.0-only
"""LIF-0602 structured explanation/hypothesis templates with citations.

Scope: the citation registry, the three builtin templates, the
render-time citation gate, structured-explanation validation, and
the bridges to the banked LIF-0601 model provider and LIF-0305
hypothesis records, all over the committed fixture corpus
(tests/fixtures/lif0602/).  No network, no model, no real
inference: the mock provider is the only provider exercised.
"""
import ast
import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from lifthrasir import explanations as ex  # noqa: E402
from lifthrasir import modelprovider as mp  # noqa: E402

FIXTURES = REPO / "tests" / "fixtures" / "lif0602"


@pytest.fixture(scope="module")
def cases():
    return json.loads((FIXTURES / "cases.json").read_text(encoding="utf-8"))


@pytest.fixture()
def registry(cases):
    return ex.CitationRegistry.from_dicts(cases["citations"])


def render_summary(cases, registry, **overrides):
    case = cases["incident_summary"]
    kwargs = dict(values=dict(case["values"]),
                  citations_by_section={
                      k: list(v) for k, v in
                      case["citations_by_section"].items()},
                  registry=registry)
    kwargs.update(overrides)
    return ex.render_template(case["template_id"], **kwargs)


# --- citation registry -----------------------------------------------------

def test_registry_registers_and_resolves_fixture_citations(registry):
    assert len(registry) == 3
    assert registry.ids() == ["ev-2026-201", "ev-2026-202", "ev-2026-203"]
    citation = registry.resolve("ev-2026-201")
    assert citation.source_kind == "log-excerpt"
    assert ex.Citation.from_dict(citation.to_dict()) == citation
    assert ex.CitationRegistry.from_dicts(registry.to_dicts()).ids() == registry.ids()


def test_registry_refuses_invented_and_malformed_citations(registry, cases):
    with pytest.raises(ex.UnresolvedCitationError):
        registry.resolve(cases["invented_citation"])
    with pytest.raises(ex.CitationShapeError):
        registry.resolve("not-an-evidence-id")
    with pytest.raises(ex.CitationShapeError):
        ex.Citation(citation_id="ev-2026-201", source_kind="rumour",
                    locator="somewhere")
    with pytest.raises(ex.CitationShapeError):
        ex.Citation(citation_id="ev-2026-201", source_kind="document",
                    locator="x", digest="not-a-hash")


def test_registry_refuses_duplicate_registration(registry, cases):
    with pytest.raises(ex.DuplicateCitationError):
        registry.register(ex.Citation.from_dict(cases["citations"][0]))


def test_registry_from_context_refs_and_bad_ref_refused():
    registry = ex.CitationRegistry.from_context_refs(
        ("ev-2026-201", "ev-2026-202"))
    assert registry.ids() == ["ev-2026-201", "ev-2026-202"]
    with pytest.raises(ex.CitationShapeError):
        ex.CitationRegistry.from_context_refs(("a free-form claim",))


def test_registry_from_hypothesis_record(registry, cases):
    built = ex.CitationRegistry.from_hypothesis_record(
        cases["hypothesis_record"])
    assert built.ids() == ["ev-2026-201", "ev-2026-202", "ev-2026-203"]
    assert built.resolve("ev-2026-203").source_kind == "hypothesis-record"
    registry.add_hypothesis_record(cases["hypothesis_record"])
    assert len(registry) == 3  # already present: no duplicate, no rewrite


# --- template catalog ------------------------------------------------------

def test_builtin_templates_are_the_three_roadmap_templates():
    assert ex.TEMPLATE_IDS == (
        "tmpl-incident-summary", "tmpl-rival-hypotheses",
        "tmpl-experiment-proposal")
    kinds = {t.template_id: t.kind for t in ex.list_templates()}
    assert kinds["tmpl-incident-summary"] == "explanation"
    assert kinds["tmpl-rival-hypotheses"] == "hypothesis"
    assert kinds["tmpl-experiment-proposal"] == "hypothesis"
    for template in ex.list_templates():
        assert template.version == ex.TEMPLATE_VERSION
        assert template.placeholders  # every template takes values
        assert template.to_dict()["schema"] == ex.TEMPLATE_SCHEMA
    with pytest.raises(ex.UnknownTemplateError):
        ex.get_template("tmpl-does-not-exist")


def test_template_spec_validation_refuses_bad_shapes():
    with pytest.raises(ex.MalformedTemplateError):
        ex.SectionSpec(name="Bad Name", heading="H", body="{x}")
    with pytest.raises(ex.MalformedTemplateError):
        ex.SectionSpec(name="ok", heading="H", body="{x:>10}")
    with pytest.raises(ex.MalformedTemplateError):
        ex.TemplateSpec(template_id="tmpl-x", kind="essay", title="T",
                        sections=(ex.SectionSpec(
                            name="a", heading="A", body="{v}"),))


# --- rendering -------------------------------------------------------------

def test_render_incident_summary_is_deterministic(cases, registry):
    first = render_summary(cases, registry)
    second = render_summary(cases, registry)
    assert first == second and first.digest == second.digest
    assert first.kind == "explanation"
    assert first.citations == ("ev-2026-201", "ev-2026-202")
    assert "[ev-2026-201]" in first.text and "[ev-2026-202]" in first.text
    assert "disk filled" in first.text
    assert ex.RenderedDocument.from_dict(first.to_dict()) == first
    assert ex.validate_rendered_document(first.to_dict(), registry) == first


def test_render_refuses_invented_citation(cases, registry):
    bad = {k: list(v) for k, v in
           cases["incident_summary"]["citations_by_section"].items()}
    bad["evidence"] = [cases["invented_citation"]]
    with pytest.raises(ex.UnresolvedCitationError):
        render_summary(cases, registry, citations_by_section=bad)


def test_render_refuses_malformed_citation_shape(cases, registry):
    bad = {k: list(v) for k, v in
           cases["incident_summary"]["citations_by_section"].items()}
    bad["summary"] = ["a made-up source"]
    with pytest.raises(ex.CitationShapeError):
        render_summary(cases, registry, citations_by_section=bad)


def test_render_refuses_missing_required_citations(cases, registry):
    bad = {k: list(v) for k, v in
           cases["incident_summary"]["citations_by_section"].items()}
    bad["evidence"] = []
    with pytest.raises(ex.UnresolvedCitationError):
        render_summary(cases, registry, citations_by_section=bad)


def test_render_refuses_missing_unknown_and_duplicate_inputs(cases, registry):
    case = cases["incident_summary"]
    values = dict(case["values"])
    del values["summary"]
    with pytest.raises(ex.MissingValueError):
        render_summary(cases, registry, values=values)
    values = dict(case["values"], extra="nope")
    with pytest.raises(ex.MalformedTemplateError):
        render_summary(cases, registry, values=values)
    bad = {k: list(v) for k, v in case["citations_by_section"].items()}
    bad["uncertainty"] = ["ev-2026-201"]
    with pytest.raises(ex.DuplicateCitationError):
        render_summary(cases, registry, citations_by_section=bad)
    bad_sections = dict(case["citations_by_section"], nope=["ev-2026-201"])
    with pytest.raises(ex.MalformedTemplateError):
        render_summary(cases, registry, citations_by_section=bad_sections)


def test_render_length_caps_are_enforced(cases, registry):
    values = dict(cases["incident_summary"]["values"],
                  summary="x" * (ex.MAX_VALUE_CHARS + 1))
    with pytest.raises(ex.MalformedTemplateError):
        render_summary(cases, registry, values=values)


def test_rendered_document_digest_detects_tampering(cases, registry):
    document = render_summary(cases, registry)
    data = document.to_dict()
    data["text"] = data["text"] + " Altered."
    with pytest.raises(ex.MalformedTemplateError):
        ex.RenderedDocument.from_dict(data)
    with pytest.raises(ex.UnresolvedCitationError):
        ex.validate_rendered_document(document.to_dict(),
                                      ex.CitationRegistry())


# --- structured explanations ----------------------------------------------

def test_structured_explanation_validates_and_copies(cases, registry):
    payload = cases["structured_explanation"]
    checked = ex.validate_structured_explanation(payload, registry)
    assert checked == payload and checked is not payload


def test_structured_explanation_refuses_invented_citation(cases, registry):
    payload = dict(cases["structured_explanation"],
                   citations=[cases["invented_citation"]])
    with pytest.raises(ex.UnresolvedCitationError):
        ex.validate_structured_explanation(payload, registry)
    payload = dict(cases["structured_explanation"], citations=[])
    with pytest.raises(ex.UnresolvedCitationError):
        ex.validate_structured_explanation(payload, registry)


def test_structured_explanation_refuses_bad_shape(cases, registry):
    payload = dict(cases["structured_explanation"], verdict="surely")
    with pytest.raises(ex.MalformedTemplateError):
        ex.validate_structured_explanation(payload, registry)
    payload = dict(cases["structured_explanation"], uncertainty=1.5)
    with pytest.raises(ex.MalformedTemplateError):
        ex.validate_structured_explanation(payload, registry)
    payload = dict(cases["structured_explanation"],
                   citations=["ev-2026-201", "ev-2026-201"])
    with pytest.raises(ex.DuplicateCitationError):
        ex.validate_structured_explanation(payload, registry)


# --- LIF-0601 model-result bridge ------------------------------------------

def test_model_result_citations_must_resolve(cases):
    provider = mp.MockModelProvider(clock=lambda: 0.0)
    request = mp.ModelRequest(
        task_id="task-fixture", prompt="Explain the failure.",
        context_refs=("ev-2026-201", "ev-2026-202"),
        output_schema="explanation-v0.1")
    result = provider.generate(request)
    registry = ex.CitationRegistry.from_context_refs(request.context_refs)
    assert ex.check_model_result_citations(result, registry) == result
    assert ex.check_model_result_citations(result.to_dict(), registry) == result
    with pytest.raises(ex.UnresolvedCitationError):
        ex.check_model_result_citations(result, ex.CitationRegistry())


def test_model_result_with_invented_citation_is_refused(cases):
    result = mp.ModelResult(
        task_id="task-fixture", provider_name="mock", model_id="mock-1",
        model_revision="mock-rev-1", outcome="completed", text="claim",
        citations=(cases["invented_citation"],), performed_inference=True)
    registry = ex.CitationRegistry.from_dicts(cases["citations"])
    with pytest.raises(ex.UnresolvedCitationError):
        ex.check_model_result_citations(result, registry)


def test_model_result_payload_cannot_smuggle_citations(cases, registry):
    result = mp.ModelResult(
        task_id="task-fixture", provider_name="mock", model_id="mock-1",
        model_revision="mock-rev-1", outcome="completed", text="claim",
        structured={"citations": ["ev-2026-203"]},
        citations=("ev-2026-201",), performed_inference=True)
    with pytest.raises(ex.UnresolvedCitationError):
        ex.check_model_result_citations(result, registry)


# --- LIF-0305 hypothesis bridge --------------------------------------------

def test_hypothesis_record_from_template_is_a_real_record(cases, registry):
    record = ex.hypothesis_record_from_template(
        cases["hypothesis_record"], registry)
    assert record["hypothesis_id"] == "hyp-fixture-disk"
    assert record["status"] == "supported"


def test_hypothesis_record_from_template_refuses_invented_evidence(
        cases, registry):
    record = dict(cases["hypothesis_record"],
                  evidence_for=[cases["invented_citation"]])
    with pytest.raises(ex.UnresolvedCitationError):
        ex.hypothesis_record_from_template(record, registry)
    record = dict(cases["hypothesis_record"], evidence_for=[])
    with pytest.raises(Exception) as excinfo:
        ex.hypothesis_record_from_template(record, registry)
    assert excinfo.value.__class__.__name__ == "UnsupportedStatusError"


def test_explanation_for_hypothesis_renders_with_citations(cases, registry):
    document = ex.explanation_for_hypothesis(
        cases["hypothesis_record"], registry)
    assert document.template_id == "tmpl-rival-hypotheses"
    assert document.citations == (
        "ev-2026-201", "ev-2026-202", "ev-2026-203")
    assert "hyp-fixture-disk" in document.text


def test_explanation_for_hypothesis_refuses_unregistered_evidence(cases):
    with pytest.raises(ex.UnresolvedCitationError):
        ex.explanation_for_hypothesis(
            cases["hypothesis_record"], ex.CitationRegistry())
    record = dict(cases["hypothesis_record"], status="proposed",
                  evidence_for=[], evidence_against=[])
    with pytest.raises(ex.UnresolvedCitationError):
        ex.explanation_for_hypothesis(
            record, ex.CitationRegistry.from_dicts(cases["citations"]))


# --- house rules -------------------------------------------------------------

def test_module_performs_no_network_or_process_calls():
    tree = ast.parse(
        (REPO / "src" / "lifthrasir" / "explanations.py").read_text(
            encoding="utf-8"))
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
    assert not (imported & {"socket", "urllib", "http", "subprocess",
                            "requests", "os"})


def test_desired_exports_banked_in_package_union():
    # Seat-amended at LIF-0602 banking: the team's original test
    # asserted these names were ABSENT from the banked package (a
    # pre-banking collision guard; it passed in the team worktree).
    # The banking union is the step that adds them, so the guard is
    # rewritten to assert the union's integrity instead: every
    # desired name is exported and IS the explanations module's own
    # object, and __all__ carries no duplicates.
    import lifthrasir
    desired = [
        "TEMPLATE_SCHEMA", "TEMPLATE_SCHEMA_VERSION", "EXPLANATION_SCHEMA",
        "EXPLANATION_SCHEMA_VERSION", "TEMPLATE_VERSION", "TEMPLATE_KINDS",
        "CITATION_KINDS", "MAX_RENDER_CHARS", "TemplateError",
        "MalformedTemplateError", "UnknownTemplateError",
        "DuplicateCitationError", "CitationShapeError",
        "UnresolvedCitationError", "MissingValueError", "Citation",
        "CitationRegistry", "SectionSpec", "TemplateSpec",
        "RenderedDocument", "BUILTIN_TEMPLATES", "TEMPLATES",
        "TEMPLATE_IDS", "get_template", "list_templates",
        "templates_as_dicts", "check_citation_id", "document_digest",
        "render_template", "validate_rendered_document",
        "validate_structured_explanation", "check_model_result_citations",
        "hypothesis_record_from_template", "explanation_for_hypothesis",
    ]
    from lifthrasir import explanations
    missing = [name for name in desired if name not in lifthrasir.__all__]
    assert missing == []
    for name in desired:
        assert getattr(lifthrasir, name) is getattr(explanations, name)
    assert len(lifthrasir.__all__) == len(set(lifthrasir.__all__))
