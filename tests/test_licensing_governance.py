"""LIF-0005 repo automation: licensing policy, contributor guide,
disclosure channel, and dependency manifest."""
import json
from pathlib import Path

import jsonschema
import pytest

REPO = Path(__file__).resolve().parents[1]
LICENSING = REPO / "docs" / "LICENSING.md"
CONTRIBUTING = REPO / "docs" / "CONTRIBUTING.md"
SECURITY = REPO / "docs" / "disclosures" / "SECURITY.md"
MANIFEST = REPO / "dependencies" / "manifest.json"
SCHEMA = REPO / "dependencies" / "manifest.schema.json"


def _load_manifest():
    return json.loads(MANIFEST.read_text(encoding="utf-8"))


def _validate(data):
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    jsonschema.validate(data, schema)
    for entry in data.get("dependencies", []) + data.get("runtime_dependencies", []):
        for field in ("name", "version", "license_spdx"):
            assert entry.get(field), f"manifest entry missing {field}: {entry!r}"


def test_policy_docs_exist():
    for p in (LICENSING, CONTRIBUTING, SECURITY, MANIFEST, SCHEMA):
        assert p.is_file(), f"missing deliverable: {p.relative_to(REPO)}"


def test_licensing_states_non_negotiables():
    t = LICENSING.read_text(encoding="utf-8").lower()
    assert "gpl-2.0-only" in t
    assert "spdx" in t
    assert "per-component" in t or "per component" in t
    assert "third-party" in t or "third party" in t


def test_contributing_human_only_dco_and_evidence():
    t = CONTRIBUTING.read_text(encoding="utf-8").lower()
    assert "signed-off-by" in t
    assert "agents never" in t
    assert "only humans" in t
    assert "negative control" in t
    assert "evidence" in t
    for term in ("ambient root", "bootloader", "disposable vm"):
        assert term in t, f"contributor guide omits invariant term: {term}"


def test_disclosure_process_defined_no_invented_address():
    t = SECURITY.read_text(encoding="utf-8")
    low = t.lower()
    assert "responsib" in low or "disclos" in low
    assert "placeholder" in low, "concrete address must be marked as human-supplied placeholder"
    assert "do not open a public issue" in low
    import re
    emails = re.findall(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", t)
    assert emails == [], f"disclosure doc invents an email address: {emails}"


def test_manifest_parses_and_is_schema_valid():
    _validate(_load_manifest())


def test_manifest_is_honest_about_today():
    data = _load_manifest()
    assert data["project_license_spdx"] == "GPL-2.0-only"
    assert data["runtime_dependencies"] == []
    names = {e["name"] for e in data["dependencies"]}
    assert {"pytest", "jsonschema"} <= names
    for e in data["dependencies"]:
        assert e["kind"] == "dev-test"


def test_negative_control_fixture_is_rejected():
    bad = _load_manifest()
    bad["dependencies"] = [{"name": "ghost", "version": "0.0", "kind": "dev-test"}]
    with pytest.raises((jsonschema.ValidationError, AssertionError)):
        _validate(bad)
    malformed = _load_manifest()
    malformed["project_license_spdx"] = "Apache-2.0"
    with pytest.raises(jsonschema.ValidationError):
        _validate(malformed)
