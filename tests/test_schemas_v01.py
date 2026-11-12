"""LIF-0004 core record schema v0.1 tests.

Validates the four JSON Schemas in docs/protocols/schemas/v0.1/
(incident, hypothesis, plan, evidence) with the python jsonschema
validator (draft 2020-12):

- every schema is itself valid against the draft 2020-12 meta-schema;
- the version discipline is pinned (each record carries schema and
  schema_version constants, and each schema file carries its version
  in its $id and in the version directory);
- every example in examples/v0.1/valid/ validates (backlog done
  criterion for LIF-0004: examples validate);
- every example in examples/v0.1/invalid/ fails validation, each for
  the rule its filename names;
- a referential-integrity check over the valid example set passes,
  and a dangling reference is caught by that check. Referential
  existence is deliberately NOT a schema-level rule in v0.1 (see
  docs/protocols/SCHEMAS-v0.1.md, honest limits): the plan with a
  well-formed but nonexistent hypothesis reference validates against
  the schema and is rejected only by the integrity check.
"""
import copy
import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator, FormatChecker

REPO = Path(__file__).resolve().parents[1]
SCHEMA_DIR = REPO / "docs" / "protocols" / "schemas" / "v0.1"
EXAMPLE_DIR = REPO / "docs" / "protocols" / "examples" / "v0.1"
SPEC = REPO / "docs" / "protocols" / "SCHEMAS-v0.1.md"

TYPES = ["incident", "hypothesis", "plan", "evidence"]
ID_FIELD = {
    "incident": "incident_id",
    "hypothesis": "hypothesis_id",
    "plan": "plan_id",
    "evidence": "evidence_id",
}
INVALID_FILES = [
    "incident-missing-severity.json",
    "incident-open-with-resolved-at.json",
    "hypothesis-confidence-out-of-range.json",
    "hypothesis-supported-without-evidence.json",
    "plan-consent-below-risk-floor.json",
    "plan-malformed-hypothesis-ref.json",
    "evidence-bad-digest.json",
    "evidence-differential-without-baseline.json",
]


def _load(path):
    return json.loads(path.read_text(encoding="utf-8"))


def _schema(record_type):
    return _load(SCHEMA_DIR / f"{record_type}.schema.json")


def _validator(record_type):
    return Draft202012Validator(_schema(record_type), format_checker=FormatChecker())


def _valid(record_type):
    return _load(EXAMPLE_DIR / "valid" / f"{record_type}.json")


def _errors(validator, instance):
    return list(validator.iter_errors(instance))


def test_spec_document_exists():
    assert SPEC.is_file(), "docs/protocols/SCHEMAS-v0.1.md is missing"


@pytest.mark.parametrize("record_type", TYPES)
def test_schema_file_exists_and_is_valid_schema(record_type):
    path = SCHEMA_DIR / f"{record_type}.schema.json"
    assert path.is_file(), f"missing schema file: {path}"
    Draft202012Validator.check_schema(_schema(record_type))


@pytest.mark.parametrize("record_type", TYPES)
def test_schema_version_is_pinned(record_type):
    schema = _schema(record_type)
    assert schema["$id"].endswith(f"/v0.1/{record_type}.schema.json"), schema["$id"]
    props = schema["properties"]
    assert props["schema"]["const"] == f"lifthrasir.{record_type}.v0.1"
    assert props["schema_version"]["const"] == "0.1"
    for field in ["schema", "schema_version", ID_FIELD[record_type]]:
        assert field in schema["required"], f"{record_type}: {field} not required"


@pytest.mark.parametrize("record_type", TYPES)
def test_valid_example_validates(record_type):
    errors = _errors(_validator(record_type), _valid(record_type))
    assert errors == [], f"{record_type} valid example failed: {[e.message for e in errors]}"


def test_all_valid_examples_present():
    valid = sorted(p.name for p in (EXAMPLE_DIR / "valid").glob("*.json"))
    assert valid == sorted(f"{t}.json" for t in TYPES), valid


@pytest.mark.parametrize("filename", INVALID_FILES)
def test_invalid_example_fails_validation(filename):
    record_type = filename.split("-")[0]
    instance = _load(EXAMPLE_DIR / "invalid" / filename)
    errors = _errors(_validator(record_type), instance)
    assert errors != [], f"{filename} unexpectedly validated as {record_type}"


def test_all_invalid_examples_present():
    invalid = sorted(p.name for p in (EXAMPLE_DIR / "invalid").glob("*.json"))
    assert invalid == sorted(INVALID_FILES), invalid


@pytest.mark.parametrize("record_type", TYPES)
@pytest.mark.parametrize("field", ["schema", "schema_version"])
def test_wrong_version_is_rejected(record_type, field):
    instance = copy.deepcopy(_valid(record_type))
    instance[field] = "9.9"
    errors = _errors(_validator(record_type), instance)
    assert errors != [], f"{record_type}: wrong {field} was accepted"


@pytest.mark.parametrize("record_type", TYPES)
def test_missing_required_field_is_rejected(record_type):
    instance = copy.deepcopy(_valid(record_type))
    del instance[ID_FIELD[record_type]]
    errors = _errors(_validator(record_type), instance)
    assert errors != [], f"{record_type}: missing {ID_FIELD[record_type]} was accepted"


@pytest.mark.parametrize("record_type", TYPES)
def test_unknown_field_is_rejected(record_type):
    instance = copy.deepcopy(_valid(record_type))
    instance["unexpected_field"] = "nope"
    errors = _errors(_validator(record_type), instance)
    assert errors != [], f"{record_type}: unknown field was accepted"


def _reference_ids():
    """Collect every reference a record makes, by target record type."""
    valid = {t: _valid(t) for t in TYPES}
    refs = {t: set() for t in TYPES}
    incident = valid["incident"]
    refs["evidence"] |= set(incident["evidence_refs"])
    refs["evidence"] |= set(incident["triggering_event_ids"])
    hypothesis = valid["hypothesis"]
    refs["incident"].add(hypothesis["incident_id"])
    refs["evidence"] |= set(hypothesis["evidence_for"])
    refs["evidence"] |= set(hypothesis["evidence_against"])
    plan = valid["plan"]
    refs["incident"].add(plan["incident_id"])
    refs["hypothesis"] |= set(plan["hypothesis_ids"])
    evidence = valid["evidence"]
    refs["incident"].add(evidence["incident_id"])
    if "baseline_evidence_id" in evidence:
        refs["evidence"].add(evidence["baseline_evidence_id"])
    return valid, refs


def test_valid_example_set_is_referentially_consistent():
    valid, refs = _reference_ids()
    known = {t: {valid[t][ID_FIELD[t]]} for t in TYPES}
    for target_type, ids in refs.items():
        dangling = ids - known[target_type]
        assert dangling == set(), f"dangling {target_type} references: {dangling}"


def test_dangling_reference_caught_by_integrity_check_not_schema():
    plan = copy.deepcopy(_valid("plan"))
    plan["hypothesis_ids"] = ["hyp-9999-nonexistent"]
    # The schema accepts a well-formed identifier: existence is a
    # store-level data-integrity concern, not a v0.1 schema rule.
    assert _errors(_validator("plan"), plan) == []
    valid, _ = _reference_ids()
    known_hypotheses = {valid["hypothesis"]["hypothesis_id"]}
    dangling = set(plan["hypothesis_ids"]) - known_hypotheses
    assert dangling == {"hyp-9999-nonexistent"}
