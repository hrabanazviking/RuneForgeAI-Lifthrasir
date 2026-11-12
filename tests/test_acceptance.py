"""LIF-1203: install/upgrade/uninstall/recovery acceptance suite.

Fixture targets only: every operation runs against an in-memory
FixtureSystem (plus one on-disk LIF-0505 journal inside tmp_path).
No package is installed, upgraded, uninstalled or recovered on
the real host, and host/non-disposable targets refuse by name.
"""
import ast
import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from lifthrasir.acceptance import (
    CASE_ORDER,
    EMPTY_DIGEST,
    PACKAGE_V1,
    PACKAGE_V2,
    AcceptanceDivergenceError,
    AlreadyInstalledError,
    ChecksumMismatchError,
    EmergencyStopError,
    FixtureSystem,
    HostTargetError,
    MalformedPackageError,
    NoRecoveryError,
    NotInstalledError,
    SimulatedInstallInterrupt,
    UnknownCaseError,
    UnpinnedPackageError,
    VersionRefusedError,
    builtin_packages,
    compare_versions,
    fixture_target,
    install,
    package_checksum,
    package_from_dict,
    recover,
    run_acceptance_suite,
    run_case,
    uninstall,
    upgrade,
    validate_target,
    verify_install,
)

FIXTURES = REPO / "tests" / "fixtures" / "lif1203" / "packages.json"


def _wire():
    return json.loads(FIXTURES.read_text(encoding="utf-8"))


def _installed_v1():
    system = FixtureSystem()
    install(system, fixture_target(), PACKAGE_V1)
    return system


# --- package pinning ---------------------------------------------------


def test_builtin_packages_are_pinned_and_valid():
    pkgs = builtin_packages()
    assert set(pkgs) == {"1.0.0", "1.1.0"}
    for pkg in pkgs.values():
        again = package_from_dict(pkg.to_dict())
        assert again.checksum == pkg.checksum


def test_fixture_file_packages_validate():
    wire = _wire()
    assert len(wire["packages"]) == 2
    versions = sorted(package_from_dict(p).version
                      for p in wire["packages"])
    assert versions == ["1.0.0", "1.1.0"]


def test_unpinned_package_refused():
    wire = _wire()
    with pytest.raises(UnpinnedPackageError):
        package_from_dict(wire["unpinned"])


def test_tampered_package_refused():
    wire = _wire()
    with pytest.raises(ChecksumMismatchError):
        package_from_dict(wire["tampered"])


def test_checksum_is_over_canonical_body():
    body = PACKAGE_V1.body()
    assert package_checksum(body) == PACKAGE_V1.checksum
    body["files"]["usr/lib/lifthrasir/core.bin"] = "core-x"
    assert package_checksum(body) != PACKAGE_V1.checksum


@pytest.mark.parametrize("bad", [
    {"name": "", "version": "1.0.0", "files": {"a": "b"},
     "checksum": "x"},
    {"name": "p", "version": "latest", "files": {"a": "b"},
     "checksum": "x"},
    {"name": "p", "version": "1.0", "files": {},
     "checksum": "x"},
    {"name": "p", "version": "1.0", "files": {"/abs/path": "b"},
     "checksum": "x"},
    {"name": "p", "version": "1.0", "files": {"../up": "b"},
     "checksum": "x"},
    {"name": "p", "version": "1.0", "files": {"a/../b": "c"},
     "checksum": "x"},
    {"name": "p", "version": "1.0", "files": {"a": 5},
     "checksum": "x"},
    "not-a-dict",
])
def test_malformed_packages_refused(bad):
    with pytest.raises(MalformedPackageError):
        package_from_dict(bad)


def test_version_comparison():
    assert compare_versions("1.0.0", "1.1.0") == -1
    assert compare_versions("1.1.0", "1.0.0") == 1
    assert compare_versions("1.1", "1.1.0") == 0
    assert compare_versions("2.0", "1.99.9") == 1
    with pytest.raises(MalformedPackageError):
        compare_versions("1.x", "1.0")


# --- target gate (section 0) -------------------------------------------


def test_fixture_target_validates():
    target = validate_target(fixture_target())
    assert target.disposable is True
    assert target.environment == "disposable-lab"


@pytest.mark.parametrize("target", [
    {"target_id": "purpleraider", "kind": "fixture-vm",
     "environment": "disposable-lab", "disposable": True},
    {"target_id": "host", "kind": "fixture-vm",
     "environment": "disposable-lab", "disposable": True},
    {"target_id": "g1", "kind": "real-machine",
     "environment": "disposable-lab", "disposable": True},
    {"target_id": "g1", "kind": "fixture-vm",
     "environment": "disposable-lab", "disposable": False},
    {"target_id": "g1", "kind": "fixture-vm",
     "environment": "production", "disposable": True},
])
def test_non_fixture_targets_refused_by_name(target):
    with pytest.raises(HostTargetError):
        validate_target(target)
    system = FixtureSystem()
    with pytest.raises(HostTargetError):
        install(system, target, PACKAGE_V1)
    assert system.digest() == EMPTY_DIGEST


# --- lifecycle ----------------------------------------------------------


def test_install_matches_handwritten_oracle():
    system = _installed_v1()
    assert system.snapshot() == {
        "installed": {"name": "lifthrasir-demo", "version": "1.0.0"},
        "files": {"usr/share/lifthrasir/demo.txt": "demo v1\n",
                  "usr/lib/lifthrasir/core.bin": "core-1",
                  "usr/share/lifthrasir/legacy.txt": "legacy\n"},
        "config": {"demo.timeout": "30", "demo.mode": "safe",
                   "demo.legacy": "on"},
        "services": {"lifthrasir-demo.service": "active"},
        "user_data": {},
    }
    assert verify_install(system, PACKAGE_V1) == []


def test_reinstall_same_version_refused_unchanged():
    system = _installed_v1()
    before = system.digest()
    with pytest.raises(AlreadyInstalledError):
        install(system, fixture_target(), PACKAGE_V1)
    assert system.digest() == before


def test_upgrade_applies_full_delta():
    system = _installed_v1()
    upgrade(system, fixture_target(), PACKAGE_V1, PACKAGE_V2)
    assert system.installed == {"name": "lifthrasir-demo",
                                "version": "1.1.0"}
    assert "usr/share/lifthrasir/legacy.txt" not in system.files
    assert system.files["usr/share/lifthrasir/new.txt"] == "new in v2\n"
    assert system.config == {"demo.timeout": "45", "demo.mode": "safe",
                             "demo.new": "yes"}
    assert verify_install(system, PACKAGE_V2) == []


def test_upgrade_preserves_user_modified_config():
    system = _installed_v1()
    system.config["demo.timeout"] = "99"
    system.config["demo.legacy"] = "off"  # user touched dropped key
    upgrade(system, fixture_target(), PACKAGE_V1, PACKAGE_V2)
    assert system.config["demo.timeout"] == "99"
    # a user-modified dropped key is NOT silently deleted
    assert system.config["demo.legacy"] == "off"


def test_downgrade_refused_and_allowed_explicitly():
    system = _installed_v1()
    upgrade(system, fixture_target(), PACKAGE_V1, PACKAGE_V2)
    before = system.digest()
    with pytest.raises(VersionRefusedError):
        upgrade(system, fixture_target(), PACKAGE_V2, PACKAGE_V1)
    assert system.digest() == before
    upgrade(system, fixture_target(), PACKAGE_V2, PACKAGE_V1,
            allow_downgrade=True)
    assert system.installed["version"] == "1.0.0"


def test_same_version_upgrade_refused():
    system = _installed_v1()
    with pytest.raises(VersionRefusedError):
        upgrade(system, fixture_target(), PACKAGE_V1, PACKAGE_V1)


def test_uninstall_clean_restores_empty_digest():
    system = _installed_v1()
    system.user_data["demo.user.notes"] = "scratch"
    uninstall(system, fixture_target(), PACKAGE_V1)
    assert system.digest() == EMPTY_DIGEST


def test_uninstall_keep_user_data():
    system = _installed_v1()
    system.user_data["demo.user.notes"] = "keep me"
    uninstall(system, fixture_target(), PACKAGE_V1,
              keep_user_data=True)
    assert system.user_data == {"demo.user.notes": "keep me"}
    assert system.files == {} and system.installed is None


def test_uninstall_not_installed_refused():
    with pytest.raises(NotInstalledError):
        uninstall(FixtureSystem(), fixture_target(), PACKAGE_V1)


def test_emergency_stop_refuses_before_mutation():
    system = FixtureSystem()
    with pytest.raises(EmergencyStopError):
        install(system, fixture_target(), PACKAGE_V1,
                emergency_stop=True)
    assert system.digest() == EMPTY_DIGEST


# --- interruption + recovery -------------------------------------------


def test_interrupted_install_recovers_to_empty():
    system = FixtureSystem()
    with pytest.raises(SimulatedInstallInterrupt):
        install(system, fixture_target(), PACKAGE_V1, interrupt_after=2)
    assert system.pending_manifest is not None
    outcome = recover(system)
    assert outcome["verified"] is True
    assert system.digest() == EMPTY_DIGEST
    assert system.pending_manifest is None


def test_interrupted_upgrade_rolls_back_to_v1():
    system = _installed_v1()
    v1_digest = system.digest()
    with pytest.raises(SimulatedInstallInterrupt):
        upgrade(system, fixture_target(), PACKAGE_V1, PACKAGE_V2,
                interrupt_after=3)
    recover(system)
    assert system.digest() == v1_digest
    assert verify_install(system, PACKAGE_V1) == []


def test_interrupted_uninstall_recovers():
    system = _installed_v1()
    v1_digest = system.digest()
    with pytest.raises(SimulatedInstallInterrupt):
        uninstall(system, fixture_target(), PACKAGE_V1,
                  interrupt_after=1)
    recover(system)
    assert system.digest() == v1_digest


def test_recover_without_pending_refused():
    with pytest.raises(NoRecoveryError):
        recover(FixtureSystem())


def test_pending_manifest_blocks_new_operations():
    system = FixtureSystem()
    with pytest.raises(SimulatedInstallInterrupt):
        install(system, fixture_target(), PACKAGE_V1, interrupt_after=1)
    with pytest.raises(Exception) as excinfo:
        install(system, fixture_target(), PACKAGE_V1)
    assert "pending recovery" in str(excinfo.value)
    recover(system)


def test_tampered_state_detected_and_repaired():
    system = _installed_v1()
    system.files["usr/lib/lifthrasir/core.bin"] = "tampered"
    assert verify_install(system, PACKAGE_V1) == [
        "file mismatch: usr/lib/lifthrasir/core.bin"]
    uninstall(system, fixture_target(), PACKAGE_V1)
    install(system, fixture_target(), PACKAGE_V1)
    assert verify_install(system, PACKAGE_V1) == []


# --- the suite itself ----------------------------------------------------


def test_suite_all_cases_pass(tmp_path):
    report = run_acceptance_suite(tmp_path)
    assert report.failed == 0
    assert report.passed == len(CASE_ORDER) == 13
    assert report.skipped == 0


def test_suite_report_is_honest_about_scope():
    report = run_acceptance_suite()
    data = report.to_dict()
    assert data["schema"] == "lifthrasir.acceptance.v0.1"
    assert "fixture" in data["evidence_status"]
    assert any("LIF-1201" in item for item in data["not_covered"])
    assert "FIXTURE level only" in data["gates"]["G9"]


def test_suite_is_deterministic(tmp_path):
    first = run_acceptance_suite(tmp_path).to_dict()
    second = run_acceptance_suite(tmp_path).to_dict()
    assert first["provenance_hash"] == second["provenance_hash"]
    assert first["results"] == second["results"]


def test_each_case_passes_individually(tmp_path):
    for case_id in CASE_ORDER:
        result = run_case(case_id, tmp_path)
        assert result.status == "passed", (case_id, result.detail)
        assert result.expected_digest == result.observed_digest \
            or "refused" in case_id or case_id in (
                "downgrade-refused", "reinstall-idempotent",
                "host-target-refused", "emergency-stop")


def test_unknown_case_refused():
    with pytest.raises(UnknownCaseError):
        run_case("no-such-case")


def test_no_real_machinery_imports():
    tree = ast.parse(
        (REPO / "src" / "lifthrasir" / "acceptance.py").read_text(
            encoding="utf-8"))
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
    banned = {"subprocess", "socket", "urllib", "shutil", "requests",
              "os"}
    assert not (imported & banned), imported & banned
