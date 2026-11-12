# SPDX-License-Identifier: GPL-2.0-only
"""LIF-1201 tests: package generation and signed release pipeline.

Fixture / record level only.  Checked: (1) the fixture candidate
plans deterministically -- same digest twice and from shuffled
input order (the reproducibility differential); (2) the gate layer
passes only to fixture-ready-for-human-review and never emits a
released / published verdict; (3) simulated signing verifies,
labels itself simulated, and tampering fails verification;
(4) refusals -- real keys and key paths, publish actions,
released-state claims, unreviewed SPDX, artwork without a
license note, unsafe / duplicate paths, malformed versions and
formats; (5) a blocked candidate (a gate input removed) gets no
signature; (6) the human doc mirrors the machine contract and
the purity scan finds no publish / signing / network machinery.
No test creates a real package, uses a real key, or publishes.
"""
import copy
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from lifthrasir.releasepipeline import (  # noqa: E402
    GATE_NAMES, PACKAGE_FORMATS, SIGNATURE_ALGORITHM, SIGNATURE_LABEL,
    VERDICT_BLOCKED, VERDICT_FIXTURE_READY, VERDICTS,
    MalformedRecordError, PublishRefusedError, RealKeyRefusedError,
    SupportClaimError, UnreviewedLicenseError, build_evidence_record,
    build_package_plan, evaluate_release_candidate, simulate_sign,
    validate_fixture_key, verify_simulated_signature)

FIXTURE = json.loads((ROOT / "tests" / "fixtures" / "lif1201" /
                      "release.json").read_text())
DOC = (ROOT / "docs" / "RELEASE-PIPELINE.md").read_text()
SRC = (ROOT / "src" / "lifthrasir" / "releasepipeline.py").read_text()


def _candidate():
    return copy.deepcopy(FIXTURE)


def _plan():
    return build_package_plan(_candidate()["package"])


def test_fixture_candidate_is_fixture_ready_not_released():
    report = evaluate_release_candidate(_candidate())
    assert report.verdict == VERDICT_FIXTURE_READY
    assert report.verdict in VERDICTS
    assert [g.gate for g in report.gates] == list(GATE_NAMES)
    assert all(g.passed for g in report.gates)
    assert report.to_dict()["release_state"] == "not-a-release"
    assert report.signature is not None


def test_plan_is_deterministic_and_order_independent():
    plan = _plan()
    assert plan.digest() == _plan().digest()
    shuffled = _candidate()["package"]
    shuffled["files"] = list(reversed(shuffled["files"]))
    assert build_package_plan(shuffled).digest() == plan.digest()
    assert [f.path for f in plan.files] == sorted(f.path for f in plan.files)
    assert plan.to_dict()["digest"].startswith("sha256:")


def test_simulated_signature_verifies_and_is_labelled():
    plan = _plan()
    key = validate_fixture_key(_candidate()["fixture_key"])
    sig = simulate_sign(plan, key).to_dict()
    assert sig["label"] == SIGNATURE_LABEL
    assert sig["algorithm"] == SIGNATURE_ALGORITHM
    assert sig["simulated"] is True
    assert verify_simulated_signature(plan, key, sig) is True


def test_tampered_manifest_fails_verification():
    plan = _plan()
    key = validate_fixture_key(_candidate()["fixture_key"])
    sig = simulate_sign(plan, key).to_dict()
    changed = _candidate()["package"]
    changed["version"] = "0.8.1"
    assert verify_simulated_signature(build_package_plan(changed), key, sig) is False
    bad = dict(sig, signature="0" * 64)
    assert verify_simulated_signature(plan, key, bad) is False
    unlabelled = dict(sig, label="REAL-SIGNATURE")
    assert verify_simulated_signature(plan, key, unlabelled) is False


def test_real_keys_and_key_paths_are_refused():
    for key_id in ("release-signing-key", "volmarr@example", "/home/user/key.pem", "prod.key"):
        raw = {"key_id": key_id, "material": "x" * 16, "simulated": True}
        with pytest.raises(RealKeyRefusedError):
            validate_fixture_key(raw)
    raw = {"key_id": "fixture-ok", "material": "x" * 16, "simulated": False}
    with pytest.raises(MalformedRecordError):
        validate_fixture_key(raw)


def test_publish_actions_and_release_claims_are_refused():
    pkg = _candidate()["package"]
    pkg["action"] = "publish"
    with pytest.raises(PublishRefusedError):
        build_package_plan(pkg)
    pkg = _candidate()["package"]
    pkg["release_state"] = "released"
    with pytest.raises(SupportClaimError):
        build_package_plan(pkg)
    assert "released" not in VERDICTS and "published" not in VERDICTS


def test_unreviewed_spdx_and_artwork_without_note_are_refused():
    pkg = _candidate()["package"]
    pkg["files"][0]["spdx_reviewed"] = False
    with pytest.raises(UnreviewedLicenseError):
        build_package_plan(pkg)
    pkg = _candidate()["package"]
    for f in pkg["files"]:
        if f["kind"] == "artwork":
            f["license_note"] = ""
    with pytest.raises(UnreviewedLicenseError):
        build_package_plan(pkg)


def test_unsafe_duplicate_and_malformed_records_are_refused():
    for bad_path in ("../escape.py", "/abs/path.py", "a//b.py", "./x.py"):
        pkg = _candidate()["package"]
        pkg["files"][0]["path"] = bad_path
        with pytest.raises(MalformedRecordError):
            build_package_plan(pkg)
    pkg = _candidate()["package"]
    pkg["files"].append(dict(pkg["files"][0]))
    with pytest.raises(MalformedRecordError):
        build_package_plan(pkg)
    pkg = _candidate()["package"]
    pkg["version"] = "1.0"
    with pytest.raises(MalformedRecordError):
        build_package_plan(pkg)
    pkg = _candidate()["package"]
    pkg["format"] = "msi"
    with pytest.raises(MalformedRecordError):
        build_package_plan(pkg)
    assert set(PACKAGE_FORMATS) == {"deb-plan", "rpm-plan", "tarball-plan"}


def test_blocked_candidate_gets_no_signature():
    cand = _candidate()
    cand["evidence"]["suite"]["failed"] = 3
    report = evaluate_release_candidate(cand)
    assert report.verdict == VERDICT_BLOCKED
    assert report.signature is None
    failed = [g.gate for g in report.gates if not g.passed]
    assert failed == ["full_suite_green"]
    cand = _candidate()
    del cand["evidence"]["undo"]
    report = evaluate_release_candidate(cand)
    assert report.verdict == VERDICT_BLOCKED and report.signature is None


def test_evidence_record_claims_no_higher_rung():
    report = evaluate_release_candidate(_candidate())
    rec = build_evidence_record(report)
    assert rec["release_state"] == "not-a-release"
    assert rec["simulated_signing"] is True
    assert "fixture" in rec["rung"]


def test_doc_mirrors_contract():
    for token in (SIGNATURE_LABEL, VERDICT_FIXTURE_READY, "GPL-2.0-only",
                  "not a release", "fixture"):
        assert token.lower() in DOC.lower(), token
    for fmt in PACKAGE_FORMATS:
        assert fmt in DOC
    for gate in GATE_NAMES:
        assert gate in DOC


def test_module_has_no_publish_or_real_signing_machinery():
    lowered = SRC.lower()
    for banned in ("import subprocess", "import socket",
                   "import urllib", "import requests", "os.system",
                   "open(", "gnupg", "cryptography"):
        assert banned not in lowered, banned
