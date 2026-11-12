# SPDX-License-Identifier: GPL-2.0-only
"""LIF-0407 tests: sandbox/capability confinement review by distro.

The review is checked four ways: (1) the mechanism matrix and
distro profiles are complete and honest (every mechanism rated for
every family; only ubuntu claims host observation, because only
this host was probed); (2) the catalog audit is differential -- it
runs against the REAL banked v0.1 lists in lifthrasir.actions, so
if a future catalog fixes a gap the finding must disappear and if
a name regresses a finding must appear; (3) known per-distro gaps
are pinned by name (fedora dbus-broker, versioned kernel package
names, /etc/apt, /etc/selinux, ...); (4) the human review document
mirrors the machine review (every finding id appears in the doc).

Scope: pure data and fixtures. No test boots a distro, changes a
host setting, or claims confinement on an untested system.
"""
import json
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from lifthrasir.actions import (  # noqa: E402
    CRITICAL_UNITS, PROTECTED_PACKAGES, PROTECTED_PATH_PREFIXES)
from lifthrasir.confinement import (  # noqa: E402
    DISTRO_IDS, EXECUTOR_OWN_LAYERS, EXECUTOR_USE, MECHANISMS,
    PROFILES, UnknownDistroError, all_findings, audit_catalog,
    audit_executor, covered_package_concepts, distro_id_for_os_release,
    get_profile, parse_os_release, review_as_dict, verdict_for)

FIXTURES = json.loads((ROOT / "tests" / "fixtures" / "lif0407" /
                       "distros.json").read_text())
DOC = (ROOT / "docs" / "CONFINEMENT-REVIEW.md").read_text()


def test_fixture_families_match_profiles():
    ids = {d["id"] for d in FIXTURES["distros"]}
    assert ids == set(DISTRO_IDS) == {"ubuntu", "debian", "fedora",
                                      "opensuse"}
    for row in FIXTURES["distros"]:
        profile = PROFILES[row["id"]]
        assert profile.default_lsm == row["default_lsm"]
        assert profile.package_manager == row["package_manager"]
        assert profile.evidence == row["evidence"]


def test_only_ubuntu_claims_host_observation():
    assert PROFILES["ubuntu"].evidence == "host-observed"
    for distro in ("debian", "fedora", "opensuse"):
        assert PROFILES[distro].evidence == "documented"
    host = [d for d in FIXTURES["distros"]
            if d["id"] == "ubuntu"][0]["host_observation"]
    assert host["landlock_abi"] >= 1
    assert "landlock" in host["lsm_list"]
    assert "apparmor" in host["lsm_list"]


def test_mechanism_matrix_is_complete_and_honest():
    for profile in PROFILES.values():
        assert set(profile.mechanisms) == set(MECHANISMS)
        assert all(v in ("default", "available", "conditional",
                         "not-default")
                   for v in profile.mechanisms.values())
    # The default LSM differs by family -- the whole point of a
    # per-distro review.
    assert PROFILES["ubuntu"].default_lsm == "apparmor"
    assert PROFILES["fedora"].default_lsm == "selinux"
    assert PROFILES["opensuse"].default_lsm == "apparmor-or-selinux"
    assert PROFILES["opensuse"].mechanisms["lsm_mac"] == "conditional"
    assert PROFILES["ubuntu"].mechanisms["namespaces"] == "conditional"


def test_executor_uses_no_broker_grade_mechanism_yet():
    assert set(EXECUTOR_USE) == set(MECHANISMS)
    assert all(v == "not-used" for v in EXECUTOR_USE.values())
    assert "separate-process" in EXECUTOR_OWN_LAYERS
    for distro in DISTRO_IDS:
        findings = audit_executor(distro)
        assert len(findings) == len(MECHANISMS)
        assert all(f.kind == "executor-layer-unused"
                   for f in findings)


def test_unknown_distro_fails_closed():
    with pytest.raises(UnknownDistroError):
        get_profile("arch")
    with pytest.raises(UnknownDistroError):
        audit_catalog("nixos")
    verdict = verdict_for("arch")
    assert verdict["mode"] == "observation-only"
    assert verdict["catalog_findings"] is None
    assert verdict_for(None)["mode"] == "observation-only"


def test_os_release_mapping():
    assert distro_id_for_os_release(
        'ID=ubuntu\nID_LIKE=debian\n') == "ubuntu"
    assert distro_id_for_os_release('ID=kubuntu\n') == "ubuntu"
    assert distro_id_for_os_release('ID=debian\n') == "debian"
    assert distro_id_for_os_release(
        'ID="opensuse-tumbleweed"\n') == "opensuse"
    assert distro_id_for_os_release('ID=fedora\n') == "fedora"
    assert distro_id_for_os_release('ID=arch\n') is None
    assert parse_os_release('A=1\n# comment\nB="x y"\n') == {
        "A": "1", "B": "x y"}


def test_positive_controls_v01_lists_do_cover_these():
    # The audit must not cry wolf: these v0.1 judgements DO hold.
    assert "sshd.service" in CRITICAL_UNITS  # fedora/opensuse name
    assert "ssh.service" in CRITICAL_UNITS  # debian/ubuntu name
    assert "/boot" in PROTECTED_PATH_PREFIXES
    assert "/etc/ssh" in PROTECTED_PATH_PREFIXES
    assert "/home" in PROTECTED_PATH_PREFIXES
    for distro in DISTRO_IDS:
        subjects = {f.subject for f in audit_catalog(distro)}
        assert "openssl" not in subjects
        assert "/etc/ssh" not in subjects


def test_headline_gap_exact_match_kernel_names():
    # v0.1 holds 'linux-image' and 'kernel'; the packages actually
    # installed are named differently on every family.
    for distro in DISTRO_IDS:
        findings = {f.subject: f for f in audit_catalog(distro)}
        real = PROFILES[distro].package_names["kernel_image"]
        assert real not in PROTECTED_PACKAGES
        assert real in findings
        assert findings[real].kind in (
            "package-name-mismatch", "package-unlisted")
    covered = {d: covered_package_concepts(d) for d in DISTRO_IDS}
    assert covered["debian"] == ["firmware", "openssl", "gnupg",
                                 "ssh_server"]
    assert covered["opensuse"] == ["bootloader", "shim", "openssl"]
    assert "kernel_image" not in covered["fedora"]  # kernel-core


def test_named_unit_and_path_gaps_per_distro():
    fedora = {f.subject for f in audit_catalog("fedora")}
    assert "dbus-broker.service" in fedora  # v0.1 names dbus.service
    assert "firewalld.service" in fedora
    assert "/etc/selinux" in fedora
    ubuntu = {f.subject for f in audit_catalog("ubuntu")}
    assert "snapd.service" in ubuntu
    assert "/etc/apt" in ubuntu
    assert "/etc/apparmor.d" in ubuntu
    opensuse = {f.subject for f in audit_catalog("opensuse")}
    assert "wicked.service" in opensuse
    assert "/etc/zypp" in opensuse
    for distro in DISTRO_IDS:
        subjects = {f.subject for f in audit_catalog(distro)}
        assert "polkit.service" in subjects  # missing everywhere
        assert "/etc/sudoers" in subjects
        assert "/etc/systemd" in subjects
        assert "/etc/crypttab" in subjects


def test_findings_are_well_formed_and_unique():
    findings = all_findings()
    ids = [f.finding_id for f in findings]
    assert len(ids) == len(set(ids))
    for f in findings:
        assert f.severity in ("high", "medium", "low", "info")
        assert f.distro in DISTRO_IDS + ("all",)
        assert f.detail and f.recommendation
    kinds = {f.kind for f in findings}
    assert {"critical-unit-gap", "protected-path-gap",
            "package-name-mismatch", "package-unlisted",
            "executor-layer-unused", "executor-design-limit",
            "scope-exclusion"} <= kinds


def test_scope_exclusions_named():
    subjects = {f.subject for f in all_findings()
                if f.kind == "scope-exclusion"}
    assert subjects == {"opensuse-microos", "nixos", "ostree-bootc"}
    assert {v["id"] for v in FIXTURES["out_of_scope_variants"]} == subjects


def test_document_mirrors_machine_review():
    for f in all_findings():
        assert f.finding_id in DOC, f.finding_id
    for distro in DISTRO_IDS:
        assert PROFILES[distro].display.split("(")[0].strip() in DOC
    for mech in MECHANISMS:
        assert mech in DOC
    # Honesty lines the doc must never lose in an edit.
    assert "NOT verified" in DOC
    assert "does not change host configuration" in DOC


def test_review_module_changes_no_host_state():
    source = (ROOT / "src" / "lifthrasir" /
              "confinement.py").read_text()
    for banned in ("subprocess", "os.system", "os.chmod",
                   "os.chown", "socket", "urllib", "requests"):
        assert banned not in source, banned
    as_dict = review_as_dict()
    assert as_dict["schema"] == "lifthrasir.confinement-review.v0.1"
    assert len(as_dict["findings"]) == len(all_findings())
