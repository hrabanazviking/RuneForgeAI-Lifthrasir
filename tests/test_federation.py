# SPDX-License-Identifier: GPL-2.0-only
"""LIF-1301 opt-in node enrollment and privacy-reviewed export tests.

Scope: the enrollment/consent gate and the export package builder in
src/lifthrasir/federation.py, exercised against committed fixtures
only: a 20-node roster (tests/fixtures/lif1301/nodes.json) and
incident-summary records carrying SYNTHETIC planted secrets
(tests/fixtures/lif1301/records.json). No network, no real
credentials, no real machine identity anywhere in this file.

Honesty pinned here: consent is per category and time-boxed;
withdrawn or expired consent can never export; forbidden categories
from research/20 are refused by name; the exported payload is the
exact byte content its hashes cover; and when the redaction layer is
broken (negative control), the privacy review refuses the export
instead of shipping a dirty payload.
"""
import ast
import copy
import hashlib
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from lifthrasir import federation as fed  # noqa: E402
from lifthrasir.privacy import Redactor, RetentionPolicy  # noqa: E402

FIXTURES = REPO / "tests" / "fixtures" / "lif1301"
T0 = datetime(2026, 11, 12, tzinfo=timezone.utc)
SECRETS = [
    "bob@example.org",
    "carol@example.net",
    "ghp_0123456789abcdefghij0123456789abcd",
    "192.168.1.20",
    "10.0.0.8",
    "/home/bob",
]
HELD_NAMES = {"DuplicateNodeError", "MalformedPackageError"}


def load_fixture(name):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def make_enrollment(**overrides):
    kwargs = {
        "node_id": "node-alpha",
        "categories": ["incident-summaries", "test-fixtures"],
        "enrolled_at": T0,
        "expires_at": T0 + timedelta(days=30),
    }
    kwargs.update(overrides)
    return fed.enroll_node(**kwargs)


def oracle_digest(base):
    """Independent canonical-JSON sha256 (the test-side oracle)."""
    return hashlib.sha256(
        json.dumps(base, sort_keys=True, separators=(",", ":"),
                   ensure_ascii=False).encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------
# Category law (research/20)
# ---------------------------------------------------------------------

def test_category_sets_are_closed_and_disjoint():
    assert not set(fed.SHAREABLE_CATEGORIES) & set(
        fed.FORBIDDEN_CATEGORIES)
    assert len(fed.SHAREABLE_CATEGORIES) == 5
    assert len(fed.FORBIDDEN_CATEGORIES) == 6


def test_enroll_refuses_every_forbidden_category():
    for category in fed.FORBIDDEN_CATEGORIES:
        with pytest.raises(fed.ForbiddenCategoryError):
            make_enrollment(categories=[category])


def test_enroll_refuses_unknown_category():
    with pytest.raises(fed.UnknownCategoryError):
        make_enrollment(categories=["telemetry"])


def test_enroll_refuses_empty_categories():
    with pytest.raises(fed.MalformedEnrollmentError):
        make_enrollment(categories=[])


# ---------------------------------------------------------------------
# Enrollment shape
# ---------------------------------------------------------------------

def test_enroll_normalizes_categories_sorted_and_deduped():
    enrollment = make_enrollment(
        categories=["test-fixtures", "incident-summaries",
                    "test-fixtures"])
    assert enrollment.categories == (
        "incident-summaries", "test-fixtures")
    assert enrollment.status_at(T0) == "active"
    assert enrollment.is_active(T0 + timedelta(days=29))


def test_enroll_refuses_bad_node_ids():
    for bad in ("", "ab", "Node-01", "-node", "node id", "n" * 65):
        with pytest.raises(fed.MalformedEnrollmentError):
            make_enrollment(node_id=bad)


def test_enroll_refuses_naive_datetimes():
    naive = datetime(2026, 11, 12)
    with pytest.raises(fed.MalformedEnrollmentError):
        make_enrollment(enrolled_at=naive)
    with pytest.raises(fed.MalformedEnrollmentError):
        make_enrollment(expires_at=naive)


def test_enroll_refuses_non_future_expiration():
    with pytest.raises(fed.MalformedEnrollmentError):
        make_enrollment(expires_at=T0)
    with pytest.raises(fed.MalformedEnrollmentError):
        make_enrollment(expires_at=T0 - timedelta(days=1))


def test_enroll_refuses_quota_out_of_bounds():
    with pytest.raises(fed.MalformedEnrollmentError):
        make_enrollment(max_records_per_export=0)
    with pytest.raises(fed.MalformedEnrollmentError):
        make_enrollment(
            max_records_per_export=fed.MAX_EXPORT_RECORDS + 1)


def test_enrollment_as_dict_is_exact_and_inspectable():
    record = fed.enrollment_as_dict(make_enrollment())
    assert record["schema"] == fed.ENROLLMENT_SCHEMA
    assert record["node_id"] == "node-alpha"
    assert record["categories"] == [
        "incident-summaries", "test-fixtures"]
    assert record["enrolled_at"] == "2026-11-12T00:00:00Z"
    assert record["expires_at"] == "2026-12-12T00:00:00Z"
    assert record["max_records_per_export"] == 100
    assert record["withdrawn_at"] is None


# ---------------------------------------------------------------------
# Consent lifecycle
# ---------------------------------------------------------------------

def test_status_transitions_pending_active_expired():
    enrollment = make_enrollment(
        enrolled_at=T0 + timedelta(days=1),
        expires_at=T0 + timedelta(days=31))
    assert enrollment.status_at(T0) == "pending"
    assert enrollment.status_at(T0 + timedelta(days=1)) == "active"
    assert enrollment.status_at(T0 + timedelta(days=31)) == "expired"


def test_withdrawal_is_terminal_and_outranks_expiry():
    enrollment = make_enrollment()
    withdrawn = enrollment.withdraw(T0 + timedelta(days=2))
    assert withdrawn.status_at(T0 + timedelta(days=2)) == "withdrawn"
    assert withdrawn.status_at(T0 + timedelta(days=90)) == "withdrawn"
    with pytest.raises(fed.EnrollmentWithdrawnError):
        withdrawn.withdraw(T0 + timedelta(days=3))
    assert enrollment.status_at(T0 + timedelta(days=2)) == "active"


def test_withdraw_before_enrollment_start_refused():
    enrollment = make_enrollment(
        enrolled_at=T0 + timedelta(days=1),
        expires_at=T0 + timedelta(days=31))
    with pytest.raises(fed.MalformedEnrollmentError):
        enrollment.withdraw(T0)


def test_registry_duplicate_withdraw_and_reenroll():
    registry = fed.EnrollmentRegistry()
    registry.enroll(make_enrollment())
    assert len(registry) == 1
    assert "node-alpha" in registry
    with pytest.raises(fed.DuplicateNodeError):
        registry.enroll(make_enrollment())
    with pytest.raises(fed.NotEnrolledError):
        registry.get("node-ghost")
    with pytest.raises(fed.NotEnrolledError):
        registry.withdraw("node-ghost", T0)
    registry.withdraw("node-alpha", T0 + timedelta(days=1))
    assert registry.get("node-alpha").withdrawn_at is not None
    registry.enroll(make_enrollment(categories=["test-fixtures"]))
    assert len(registry) == 1
    assert registry.get("node-alpha").categories == ("test-fixtures",)


# ---------------------------------------------------------------------
# Simulated network: 20 nodes, withdrawals and expirations (roadmap/04
# P13 gate, enrollment half; contradiction handling is LIF-1302)
# ---------------------------------------------------------------------

def build_roster_registry():
    registry = fed.EnrollmentRegistry()
    for entry in load_fixture("nodes.json"):
        registry.enroll(fed.enroll_node(
            entry["node_id"], entry["categories"],
            enrolled_at=T0,
            expires_at=T0 + timedelta(days=entry["expires_in_days"]),
            max_records_per_export=entry["max_records_per_export"]))
    return registry


def test_twenty_node_roster_survives_withdrawal_and_expiry():
    registry = build_roster_registry()
    assert len(registry) == 20
    for node_id in ("node-02", "node-04", "node-06", "node-08",
                    "node-10"):
        registry.withdraw(node_id, T0 + timedelta(hours=12))
    now = T0 + timedelta(days=2)
    active = {item.node_id for item in registry.active_enrollments(now)}
    assert active == {
        "node-01", "node-03", "node-05", "node-07", "node-09",
        "node-11", "node-12", "node-13", "node-14", "node-15"}
    records = load_fixture("records.json")
    package = fed.build_federation_export(
        registry.get("node-01"), records, "incident-summaries",
        now=now)
    assert package.records_included == 3
    with pytest.raises(fed.EnrollmentWithdrawnError):
        fed.build_federation_export(
            registry.get("node-02"), records, "incident-summaries",
            now=now)
    with pytest.raises(fed.EnrollmentExpiredError):
        fed.build_federation_export(
            registry.get("node-16"), records, "incident-summaries",
            now=now)


# ---------------------------------------------------------------------
# Export gates
# ---------------------------------------------------------------------

def test_export_happy_path_is_redacted_hashed_and_valid():
    now = T0 + timedelta(hours=13)
    package = fed.build_federation_export(
        make_enrollment(), load_fixture("records.json"),
        "incident-summaries", now=now)
    assert package.schema == fed.FEDERATION_SCHEMA
    assert package.node_id == "node-alpha"
    assert package.records_in == 3
    assert package.records_included == 3
    assert package.records_declared == 2
    assert package.records_undeclared == 1
    assert package.findings_by_category.get("token") == 1
    assert package.findings_by_category.get("email", 0) >= 2
    blob = json.dumps(fed.package_as_dict(package), sort_keys=True)
    for secret in SECRETS:
        assert secret not in blob
    assert "[REDACTED:" in blob
    assert package.payload_sha256 == oracle_digest(package.payload)
    assert fed.package_as_dict(package)["package_digest"] == \
        package.package_digest
    assert fed.validate_export_package(fed.package_as_dict(package))


def test_export_package_expiry_never_outlives_consent():
    now = T0 + timedelta(hours=1)
    long_ttl = fed.build_federation_export(
        make_enrollment(), [{"summary": "clean"}],
        "incident-summaries", now=now, package_ttl=timedelta(days=365))
    assert long_ttl.package_expires_at == long_ttl.consent_expires_at
    short_ttl = fed.build_federation_export(
        make_enrollment(), [{"summary": "clean"}],
        "incident-summaries", now=now, package_ttl=timedelta(hours=6))
    assert short_ttl.package_expires_at == "2026-11-12T07:00:00Z"


def test_export_refuses_category_not_enrolled():
    with pytest.raises(fed.CategoryNotEnrolledError):
        fed.build_federation_export(
            make_enrollment(), [{"summary": "x"}],
            "benchmark-results", now=T0)


def test_export_refuses_forbidden_and_unknown_categories():
    with pytest.raises(fed.ForbiddenCategoryError):
        fed.build_federation_export(
            make_enrollment(), [{"summary": "x"}], "raw-logs", now=T0)
    with pytest.raises(fed.UnknownCategoryError):
        fed.build_federation_export(
            make_enrollment(), [{"summary": "x"}], "telemetry", now=T0)


def test_export_refuses_expired_and_pending_consent():
    expired = make_enrollment(expires_at=T0 + timedelta(days=1))
    with pytest.raises(fed.EnrollmentExpiredError):
        fed.build_federation_export(
            expired, [{"summary": "x"}], "incident-summaries",
            now=T0 + timedelta(days=2))
    pending = make_enrollment(
        enrolled_at=T0 + timedelta(days=1),
        expires_at=T0 + timedelta(days=31))
    with pytest.raises(fed.NotEnrolledError):
        fed.build_federation_export(
            pending, [{"summary": "x"}], "incident-summaries", now=T0)


def test_export_refuses_quota_breach_and_empty_batch():
    small = make_enrollment(max_records_per_export=2)
    with pytest.raises(fed.QuotaExceededError):
        fed.build_federation_export(
            small, load_fixture("records.json"), "incident-summaries",
            now=T0)
    big = make_enrollment(
        max_records_per_export=fed.MAX_EXPORT_RECORDS)
    with pytest.raises(fed.QuotaExceededError):
        fed.build_federation_export(
            big, [{"n": i} for i in range(fed.MAX_EXPORT_RECORDS + 1)],
            "incident-summaries", now=T0)
    with pytest.raises(fed.MalformedPackageError):
        fed.build_federation_export(
            make_enrollment(), [], "incident-summaries", now=T0)


def test_export_refuses_declared_category_mismatch():
    records = [{"category": "benchmark-results", "summary": "x"}]
    with pytest.raises(fed.CategoryMismatchError):
        fed.build_federation_export(
            make_enrollment(), records, "incident-summaries", now=T0)


def test_export_refuses_non_mapping_records():
    with pytest.raises(fed.MalformedPackageError):
        fed.build_federation_export(
            make_enrollment(), [42], "incident-summaries", now=T0)


def test_export_retention_excludes_expired_before_redaction():
    now = T0 + timedelta(hours=13)
    package = fed.build_federation_export(
        make_enrollment(), load_fixture("records.json"),
        "incident-summaries", now=now,
        retention_policy=RetentionPolicy(max_age_days=30))
    assert package.expired_excluded == ("inc-2026-003",)
    assert package.records_in == 3
    assert package.records_included == 2
    blob = json.dumps(fed.package_as_dict(package), sort_keys=True)
    assert "carol@example.net" not in blob
    assert "10.0.0.8" not in blob


# ---------------------------------------------------------------------
# Negative control: a broken redactor must stop the export
# ---------------------------------------------------------------------

class _SilentRedactor(Redactor):
    """Record redaction silently does nothing; text scan still works."""

    def redact_record(self, record):
        _, empty_report = Redactor().redact_record({})
        return dict(record), empty_report


def test_privacy_review_refuses_when_redaction_is_broken():
    with pytest.raises(fed.PrivacyReviewError) as excinfo:
        fed.build_federation_export(
            make_enrollment(), load_fixture("records.json"),
            "incident-summaries", now=T0 + timedelta(hours=13),
            redactor=_SilentRedactor())
    for secret in SECRETS:
        assert secret not in str(excinfo.value)


# ---------------------------------------------------------------------
# Package validation: tampering is detected
# ---------------------------------------------------------------------

def test_validate_detects_tampered_payload_with_recomputed_digest():
    package = fed.build_federation_export(
        make_enrollment(), load_fixture("records.json"),
        "incident-summaries", now=T0 + timedelta(hours=13))
    data = fed.package_as_dict(package)
    forged = copy.deepcopy(data)
    forged["payload"][0]["summary"] = "tampered after the fact"
    forged["package_digest"] = oracle_digest(
        {key: value for key, value in forged.items()
         if key != "package_digest"})
    with pytest.raises(fed.MalformedPackageError) as excinfo:
        fed.validate_export_package(forged)
    assert "payload_sha256" in str(excinfo.value)
    with pytest.raises(fed.MalformedPackageError):
        fed.validate_export_package(dict(data, node_id="node-beta"))
    with pytest.raises(fed.MalformedPackageError):
        fed.validate_export_package({"schema": fed.FEDERATION_SCHEMA})
    with pytest.raises(fed.MalformedPackageError):
        fed.validate_export_package(["not", "a", "mapping"])


# ---------------------------------------------------------------------
# Offline surface and export-name collisions
# ---------------------------------------------------------------------

def test_module_has_no_network_or_send_surface():
    source = (REPO / "src" / "lifthrasir" / "federation.py").read_text(
        encoding="utf-8")
    tree = ast.parse(source)
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0]
                            for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                assert node.module == "privacy"
            else:
                imported.add(node.module.split(".")[0])
    assert imported <= {
        "__future__", "hashlib", "json", "re", "dataclasses",
        "datetime", "typing"}
    for banned in ("socket", "subprocess", "urllib", "requests",
                   "os", "sys"):
        assert banned not in imported
    functions = {node.name for node in tree.body
                 if isinstance(node, ast.FunctionDef)}
    for banned in ("send", "transmit", "publish", "upload", "post"):
        assert banned not in functions


def test_desired_exports_do_not_collide_with_banked_package():
    snapshot = set(load_fixture("banked_exports_snapshot.json"))
    collisions = set(fed.__all__) & snapshot
    # Precedent: the earlier-banked module owns the top-level name;
    # federation's copies stay at lifthrasir.federation.<name>.
    assert collisions == HELD_NAMES
    assert HELD_NAMES <= snapshot
    assert fed.DuplicateNodeError is not None
    assert fed.MalformedPackageError is not None
