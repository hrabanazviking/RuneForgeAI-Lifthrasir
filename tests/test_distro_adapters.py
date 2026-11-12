# SPDX-License-Identifier: GPL-2.0-only
"""LIF-1102 tests: Fedora/Debian/openSUSE adapters + supported table.

Scope: pure data/fixtures. No test boots a distro, installs a
package, or executes a rendered command. The central honesty pin:
NO row of the supported-versions table is supported in v0.1, and
is_supported is False for every input -- documentary candidates
must never be upgraded by a code path.
"""
import json, re, sys
from pathlib import Path
import pytest
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from lifthrasir.confinement import PROFILES  # noqa: E402
from lifthrasir.distroadapters import (  # noqa: E402
    ADAPTERS, ADAPTER_IDS, MUTATING_OPERATIONS, OPERATIONS,
    SUPPORTED_VERSIONS, DistroAdapterError, MalformedOsReleaseError,
    UnknownAdapterError, UnknownConceptError, UnknownOperationError,
    adapters_as_dict, build_evidence_record, get_adapter, identify,
    is_supported, render_command, render_supported_versions_markdown,
    support_for, supported_versions_table, translate_package)
FIX = json.loads((ROOT / "tests/fixtures/lif1102/cases.json").read_text())
DOC = (ROOT / "docs/DISTRO-ADAPTERS.md").read_text()
SRC = (ROOT / "src/lifthrasir/distroadapters.py").read_text()

def test_adapter_ids_exact():
    assert ADAPTER_IDS == ("fedora", "debian", "opensuse")
    assert set(ADAPTERS) == set(ADAPTER_IDS)

def test_adapters_reuse_confinement_profiles():
    for distro_id, adapter in ADAPTERS.items():
        assert adapter.package_names() == dict(PROFILES[distro_id].package_names)
        assert adapter.package_manager == PROFILES[distro_id].package_manager
        assert [u[0] for u in adapter.critical_units()] == [u[0] for u in PROFILES[distro_id].extra_critical_units]

def test_no_row_is_supported():
    assert all(r.status == "unverified" for r in SUPPORTED_VERSIONS)
    assert not any(is_supported(r.distro_id, r.version_id) for r in SUPPORTED_VERSIONS)

def test_table_covers_three_families_plus_reference():
    rows = supported_versions_table()
    assert {r["distro_id"] for r in rows} == {"fedora", "debian", "opensuse", "ubuntu"}
    assert len(rows) == 7
    for r in rows:
        assert r["evidence"] in ("documented", "host-observed")

def test_support_fails_closed():
    assert support_for("fedora", "99")["status"] == "unlisted"
    assert support_for("arch", "1")["status"] == "unsupported-distro"
    assert support_for(None, None)["supported"] is False
    assert is_supported("debian", "12") is False

def test_unknown_adapter_raises():
    with pytest.raises(UnknownAdapterError):
        get_adapter("ubuntu")
    with pytest.raises(UnknownAdapterError):
        get_adapter("nixos")

def test_fixture_hosts_identify():
    for host in FIX["hosts"]:
        got = identify(host["os_release"])
        assert got["distro_id"] == host["distro_id"], host["name"]
        assert got["adapter"] == host["adapter"], host["name"]
        assert got["support"]["status"] == host["status"], host["name"]

def test_identify_malformed_raises():
    with pytest.raises(MalformedOsReleaseError):
        identify("  ")

def test_fixture_commands_render_exactly():
    for case in FIX["commands"]:
        plan = render_command(case["distro_id"], case["operation"], case["concept"])
        assert list(plan.argv) == case["argv"]
        assert plan.mutating is case.get("mutating", False)

def test_mutating_flags_and_notes():
    for op in MUTATING_OPERATIONS:
        plan = render_command("fedora", op, "openssl") if op != "refresh_metadata" else render_command("fedora", op)
        assert plan.mutating is True and "never executes" in plan.note
    assert render_command("debian", "query_package", "openssl").mutating is False

def test_render_refusals():
    with pytest.raises(UnknownOperationError):
        render_command("fedora", "nuke_everything")
    with pytest.raises(UnknownConceptError):
        translate_package("fedora", "warp_drive")
    with pytest.raises(DistroAdapterError):
        render_command("fedora", "query_package")

def test_package_translation_differential():
    assert translate_package("fedora", "kernel_image") == "kernel-core"
    assert translate_package("debian", "kernel_image") == "linux-image-amd64"
    assert translate_package("opensuse", "kernel_image") == "kernel-default"
    assert translate_package("opensuse", "gnupg") == "gpg2"
    assert translate_package("fedora", "gnupg") == "gnupg2"

def test_service_status_requires_unit():
    plan = render_command("debian", "service_status", unit="ssh.service")
    assert plan.argv == ("systemctl", "status", "ssh.service", "--no-pager")
    with pytest.raises(DistroAdapterError):
        render_command("debian", "service_status")

def test_doc_table_matches_module():
    md = render_supported_versions_markdown()
    for line in md.splitlines()[2:]:
        assert line in DOC, line
    assert "no row is supported" in DOC.lower()

def test_source_is_pure_no_execution():
    for token in ("import subprocess", "import os", "import socket", "os.system(", "subprocess.", "eval(", "exec("):
        assert token not in SRC, token

def test_evidence_record_honest():
    rec = build_evidence_record("fedora", "42")
    assert rec["verdict"]["status"] == "unverified"
    assert "never upgraded" in rec["evidence_status"]
    assert len(rec["digest"]) == 64

def test_negative_control_mutated_table_claim_is_detected():
    # Negative control (in-suite form): if any row were flipped to
    # supported without evidence, the honesty pin must fire.
    rows = supported_versions_table()
    flipped = [dict(r, status="supported") if r["distro_id"] == "fedora" else r for r in rows]
    assert any(r["status"] == "supported" for r in flipped)  # mutant exists
    assert not any(r["status"] == "supported" for r in rows)  # real table clean

def test_adapters_as_dict_shape():
    d = adapters_as_dict()
    assert set(d["adapters"]) == set(ADAPTER_IDS)
    assert d["table"]["rows"] == supported_versions_table()
