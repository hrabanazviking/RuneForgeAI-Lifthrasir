# SPDX-License-Identifier: GPL-2.0-only
"""LIF-0901 tests: version-pinned Linux build fixtures (x86-64, arm64).

The shipped fixtures must load, be fully pinned to kernel.org
retrieved values, and hash-verify their config fragments; unpinned,
floating, mismatched, unofficial-origin and UNVERIFIED-claiming
mutants must REFUSE - those mutants are the negative controls.
Fixture/validator level only: no kernel is downloaded or built here.
"""
import ast
import copy
import hashlib
import json
import re
import shutil
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lab.kernel_fixtures import (ARCH_DEFCONFIG, KERNEL_FIXTURE_SCHEMA,
                                 ChecksumMismatchError, FragmentMismatchError,
                                 KernelFixtureError, MalformedFixtureError,
                                 UnofficialOriginError, UnpinnedFixtureError,
                                 UnsupportedArchitectureError,
                                 UnverifiedPinError, assert_buildable,
                                 build_kernel_manifest, builtin_fixture_ids,
                                 load_builtin_fixture, load_fixture,
                                 validate_fixture, verify_source_bytes,
                                 verify_source_file)

ROOT = Path(__file__).resolve().parents[1]
KDIR = ROOT / "lab" / "kernels"
X86 = "linux-6.12.117-x86_64"
ARM = "linux-6.12.117-arm64"
PIN_SHA = "74e99aa5e60e242e0a165fed8cb2ea0d054bf7a401f01861d403d75733456613"
PIN_COMMIT = "d3417611a3b40b7f04a29e558cebac2bf69889d7"


def _raw(fid):
    return json.loads((KDIR / fid / "fixture.json").read_text(encoding="utf-8"))


def test_both_architectures_shipped():
    assert builtin_fixture_ids() == [ARM, X86]
    arches = {load_builtin_fixture(i).architecture for i in builtin_fixture_ids()}
    assert arches == {"x86_64", "arm64"}


@pytest.mark.parametrize("fid", [X86, ARM])
def test_shipped_fixture_pins_wellformed(fid):
    f = load_builtin_fixture(fid)
    assert f.schema == KERNEL_FIXTURE_SCHEMA
    assert f.slice == "LIF-0901"
    assert f.source.version == "6.12.117"
    assert f.source.release_kind == "longterm"
    assert f.source.tarball == "linux-6.12.117.tar.xz"
    assert f.source.checksum_sha256 == PIN_SHA
    assert f.source.checksum_status == "retrieved-from-official-source"
    assert f.source.checksum_retrieved == "2026-11-12"
    assert f.source.git_commit == PIN_COMMIT
    assert f.source.git_tag == "v6.12.117"
    assert f.defconfig == ARCH_DEFCONFIG[f.architecture]
    assert f.safety.disposable_vm_only is True
    assert f.guest.disposable is True


@pytest.mark.parametrize("fid", [X86, ARM])
def test_fixture_doc_matches_json_pin(fid):
    doc = (KDIR / fid / "fixture.md").read_text(encoding="utf-8")
    raw = _raw(fid)
    assert raw["source"]["checksum_sha256"] in doc
    assert raw["source"]["origin_url"] in doc
    assert raw["source"]["git_commit"] in doc
    assert "LIF-0901" in doc


def test_no_large_binaries_committed_in_fixtures():
    for p in KDIR.rglob("*"):
        if p.is_file():
            assert p.suffix.lower() not in (".iso", ".img", ".qcow2", ".xz", ".gz")
            assert p.stat().st_size < 65536


def test_x86_64_fixture_is_buildable():
    assert_buildable(load_builtin_fixture(X86))


def test_arm64_fixture_valid_but_not_buildable_unverified_toolchain():
    f = load_builtin_fixture(ARM)
    with pytest.raises(UnverifiedPinError) as exc:
        assert_buildable(f)
    assert "aarch64-linux-gnu-gcc" in str(exc.value)


@pytest.mark.parametrize("fid", [X86, ARM])
def test_to_dict_round_trip(fid):
    f = load_builtin_fixture(fid)
    assert validate_fixture(f.to_dict()) == f


def test_verify_source_bytes_accepts_matching_payload():
    payload = b"lifthrasir LIF-0901 fake tarball payload\n"
    raw = _raw(X86)
    raw["source"]["checksum_sha256"] = hashlib.sha256(payload).hexdigest()
    f = validate_fixture(raw)
    assert verify_source_bytes(f, payload) == hashlib.sha256(payload).hexdigest()


def test_verify_source_bytes_rejects_mismatched_payload():
    f = load_builtin_fixture(X86)
    with pytest.raises(ChecksumMismatchError):
        verify_source_bytes(f, b"not the pinned kernel tarball\n")


def test_verify_source_file_rejects_mismatched_file(tmp_path):
    target = tmp_path / "linux-6.12.117.tar.xz"
    target.write_bytes(b"tampered tarball contents\n")
    with pytest.raises(ChecksumMismatchError):
        verify_source_file(load_builtin_fixture(X86), target)


def test_verify_refuses_unverified_source():
    raw = _raw(X86)
    raw["source"]["checksum_status"] = "UNVERIFIED"
    raw["source"]["checksum_sha256"] = None
    raw["source"]["checksum_retrieved"] = None
    f = validate_fixture(raw)
    with pytest.raises(UnverifiedPinError):
        verify_source_bytes(f, b"anything")
    with pytest.raises(UnverifiedPinError):
        assert_buildable(f)


def _mutant(fid=X86):
    return copy.deepcopy(_raw(fid))


@pytest.mark.parametrize("version", ["latest", "6.12", "6.12.x", "6.12.117-rc1", ""])
def test_unpinned_or_floating_version_refused(version):
    raw = _mutant()
    raw["source"]["version"] = version
    with pytest.raises(KernelFixtureError):
        validate_fixture(raw)


def test_missing_checksum_refused():
    raw = _mutant()
    raw["source"]["checksum_sha256"] = None
    with pytest.raises(UnpinnedFixtureError):
        validate_fixture(raw)


def test_uppercase_checksum_refused():
    raw = _mutant()
    raw["source"]["checksum_sha256"] = PIN_SHA.upper()
    with pytest.raises(UnpinnedFixtureError):
        validate_fixture(raw)


def test_unverified_status_claiming_a_checksum_refused():
    raw = _mutant()
    raw["source"]["checksum_status"] = "UNVERIFIED"
    with pytest.raises(MalformedFixtureError):
        validate_fixture(raw)


def test_verified_checksum_without_retrieval_date_refused():
    raw = _mutant()
    raw["source"]["checksum_retrieved"] = None
    with pytest.raises(UnpinnedFixtureError):
        validate_fixture(raw)


@pytest.mark.parametrize("url", [
    "https://example.invalid/linux-6.12.117.tar.xz",
    "http://cdn.kernel.org/pub/linux/kernel/v6.x/linux-6.12.117.tar.xz",
    "https://kernel.org.evil.example/linux-6.12.117.tar.xz"])
def test_unofficial_origin_refused(url):
    raw = _mutant()
    raw["source"]["origin_url"] = url
    with pytest.raises(UnofficialOriginError):
        validate_fixture(raw)


def test_unsupported_architecture_refused():
    raw = _mutant()
    raw["architecture"] = "riscv64"
    with pytest.raises(UnsupportedArchitectureError):
        validate_fixture(raw)


def test_make_arch_mismatch_refused():
    raw = _mutant()
    raw["make_arch"] = "arm64"
    with pytest.raises(MalformedFixtureError):
        validate_fixture(raw)


def test_defconfig_mismatch_refused():
    raw = _mutant(ARM)
    raw["defconfig"] = "x86_64_defconfig"
    with pytest.raises(MalformedFixtureError):
        validate_fixture(raw)


def test_emulator_mismatch_refused():
    raw = _mutant()
    raw["guest"]["emulator"] = "qemu-system-aarch64"
    with pytest.raises(MalformedFixtureError):
        validate_fixture(raw)


def test_fixture_id_mismatch_refused():
    raw = _mutant()
    raw["fixture_id"] = "linux-6.12.117"
    with pytest.raises(MalformedFixtureError):
        validate_fixture(raw)


def test_git_tag_mismatch_refused():
    raw = _mutant()
    raw["source"]["git_tag"] = "v6.12.116"
    with pytest.raises(MalformedFixtureError):
        validate_fixture(raw)


def test_unverified_toolchain_claiming_version_refused():
    raw = _mutant(ARM)
    raw["toolchain"][0]["expected_version"] = "13.3.0"
    with pytest.raises(MalformedFixtureError):
        validate_fixture(raw)


def test_observed_toolchain_without_version_refused():
    raw = _mutant()
    raw["toolchain"][0]["expected_version"] = None
    with pytest.raises(UnpinnedFixtureError):
        validate_fixture(raw)


def test_empty_toolchain_refused():
    raw = _mutant()
    raw["toolchain"] = []
    with pytest.raises(UnpinnedFixtureError):
        validate_fixture(raw)


def test_non_disposable_guest_refused():
    raw = _mutant()
    raw["guest"]["disposable"] = False
    with pytest.raises(MalformedFixtureError):
        validate_fixture(raw)


def test_host_touching_safety_refused():
    raw = _mutant()
    raw["safety"]["host_kernel_touched"] = True
    with pytest.raises(MalformedFixtureError):
        validate_fixture(raw)


def test_fragment_path_traversal_refused():
    raw = _mutant()
    raw["config_fragments"][0]["file"] = "../config.fragment"
    with pytest.raises(MalformedFixtureError):
        validate_fixture(raw)


def _copy_fixture(tmp_path, fid=X86):
    dst = tmp_path / fid
    shutil.copytree(KDIR / fid, dst)
    return dst


def test_tampered_fragment_file_refused(tmp_path):
    d = _copy_fixture(tmp_path)
    frag = d / "config.fragment"
    frag.write_text(frag.read_text(encoding="utf-8") + "CONFIG_TAMPERED=y\n", encoding="utf-8")
    with pytest.raises(FragmentMismatchError):
        load_fixture(d / "fixture.json")


def test_fragment_missing_required_option_refused(tmp_path):
    d = _copy_fixture(tmp_path)
    frag = d / "config.fragment"
    kept = [ln for ln in frag.read_text(encoding="utf-8").splitlines()
            if not ln.startswith("CONFIG_EXT4_FS=")]
    frag.write_text("\n".join(kept) + "\n", encoding="utf-8")
    raw = json.loads((d / "fixture.json").read_text(encoding="utf-8"))
    raw["config_fragments"][0]["sha256"] = hashlib.sha256(frag.read_bytes()).hexdigest()
    (d / "fixture.json").write_text(json.dumps(raw), encoding="utf-8")
    with pytest.raises(FragmentMismatchError):
        load_fixture(d / "fixture.json")


def test_fragment_wrong_pinned_hash_refused(tmp_path):
    d = _copy_fixture(tmp_path)
    raw = json.loads((d / "fixture.json").read_text(encoding="utf-8"))
    raw["config_fragments"][0]["sha256"] = "0" * 64
    (d / "fixture.json").write_text(json.dumps(raw), encoding="utf-8")
    with pytest.raises(FragmentMismatchError):
        load_fixture(d / "fixture.json")


@pytest.mark.parametrize("fid", [X86, ARM])
def test_manifest_deterministic_and_pinned(fid):
    m1 = build_kernel_manifest(KDIR / fid)
    m2 = build_kernel_manifest(KDIR / fid)
    assert m1 == m2
    assert PIN_SHA in m1 and PIN_COMMIT in m1
    digest = m1.rsplit("manifest_sha256=", 1)[1].strip()
    body = m1.rsplit("manifest_sha256=", 1)[0]
    assert hashlib.sha256(body.encode()).hexdigest() == digest


def test_arm64_manifest_marks_unverified_toolchain():
    assert "UNVERIFIED" in build_kernel_manifest(KDIR / ARM)


def test_module_has_no_network_or_process_machinery():
    tree = ast.parse((ROOT / "lab" / "kernel_fixtures.py").read_text(encoding="utf-8"))
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
    assert not (imported & {"socket", "subprocess", "os", "sys"})
    assert imported <= {"__future__", "hashlib", "json", "re", "dataclasses", "pathlib", "urllib"}
