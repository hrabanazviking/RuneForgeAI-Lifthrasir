# SPDX-License-Identifier: GPL-2.0-only
"""LIF-1103 tests for resource profiles (lab/resource_profiles.py).

Covers: both P11 device classes (ARM64 SBC, high-memory APU)
present in the built-in catalog with the banked LIF-0901 kernel
fixture per architecture, strict fail-closed validation (unknown
class, class/architecture mismatch, budget above device total,
budget above the banked LIF-0603 quota ceiling, unknown kernel
fixture, unknown sensor source, unknown workload id, invented
probed-hardware basis), canonical dict round-trips, fingerprint
stability and sensitivity, the fit rule judged against the REAL
banked LIF-1002 workload envelopes (every claimed workload fits;
an envelope edit that breaks the fit is caught), catalog
strictness, fixture loading, byte-stable reports, the quota-ceiling
mirror against the banked quotas module, and the offline import
surface. No test probes hardware or stresses the host.
"""
import ast
import importlib.util
import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
MOD_PATH = REPO / "lab" / "resource_profiles.py"
WP_PATH = REPO / "lab" / "workload_profiles.py"
FIXTURE = REPO / "tests" / "fixtures" / "lif1103" / "resource_profiles.json"


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


rp = _load("resource_profiles", MOD_PATH)
wp = _load("workload_profiles", WP_PATH)
sys.path.insert(0, str(REPO / "src"))
import lifthrasir.quotas as quotas  # noqa: E402  (banked LIF-0603)


def _profile(**kw):
    base = {"profile_id": "test-sbc.v1", "device_class": "arm64-sbc",
            "title": "Test SBC", "architecture": "arm64",
            "cpu_cores": 4, "memory_total_mb": 4096,
            "memory_budget_mb": 1024,
            "kernel_fixture_id": "linux-6.12.117-arm64",
            "sensor_sources": ("proc-stat",),
            "workload_profile_ids": ("io-fixture.v1",)}
    base.update(kw)
    return rp.ResourceProfile(**base)


def _envelopes():
    return {p.profile_id: (p.memory_cap_mb, p.threads)
            for p in wp.BUILTIN_PROFILES}


# --- built-in catalog -------------------------------------------------

def test_module_file_exists():
    assert MOD_PATH.is_file(), "lab/resource_profiles.py is missing"


def test_builtin_catalog_covers_both_p11_classes():
    assert rp.missing_classes(rp.BUILTIN_PROFILES) == ()
    assert {p.device_class for p in rp.BUILTIN_PROFILES} == {
        "arm64-sbc", "high-memory-apu"}


def test_builtin_profiles_use_banked_kernel_fixtures():
    for p in rp.BUILTIN_PROFILES:
        assert p.kernel_fixture_id == rp.KERNEL_FIXTURES[p.architecture]
        assert p.architecture == rp.CLASS_ARCH[p.device_class]


def test_builtin_profiles_are_declared_targets_only():
    for p in rp.BUILTIN_PROFILES:
        assert p.basis == "declared-target"


def test_get_profile_and_unknown_refused():
    assert rp.get_profile("arm64-sbc-4gb.v1").device_class == "arm64-sbc"
    with pytest.raises(rp.MalformedProfileError):
        rp.get_profile("nope.v1")


def test_fixture_file_matches_builtin_catalog():
    loaded = rp.load_catalog(FIXTURE)
    assert rp.catalog_as_dict(loaded) == rp.catalog_as_dict(
        rp.BUILTIN_PROFILES)


def test_quota_ceiling_mirror_matches_banked_quotas():
    assert rp.QUOTA_CEILING_MB * 1024 * 1024 == quotas.MAX_MEMORY_BYTES


def test_workload_id_mirror_matches_banked_catalog():
    assert set(rp.WORKLOAD_PROFILE_IDS) == {
        p.profile_id for p in wp.BUILTIN_PROFILES}


# --- validation: fail-closed ------------------------------------------

def test_unknown_class_refused():
    with pytest.raises(rp.UnknownClassError):
        _profile(device_class=" risc-v-sbc".strip())


def test_class_architecture_mismatch_refused():
    with pytest.raises(rp.UnsafeProfileError):
        _profile(architecture="x86_64",
                 kernel_fixture_id="linux-6.12.117-x86_64")
    with pytest.raises(rp.UnsafeProfileError):
        _profile(device_class="high-memory-apu", architecture="arm64")


def test_budget_above_total_refused():
    with pytest.raises(rp.UnsafeProfileError):
        _profile(memory_budget_mb=8192)


def test_budget_above_quota_ceiling_refused():
    with pytest.raises(rp.UnsafeProfileError):
        _profile(device_class="high-memory-apu", architecture="x86_64",
                 kernel_fixture_id="linux-6.12.117-x86_64",
                 cpu_cores=16, memory_total_mb=131072,
                 memory_budget_mb=16384)


def test_unknown_kernel_fixture_refused():
    with pytest.raises(rp.UnsafeProfileError):
        _profile(kernel_fixture_id="linux-9.9.9-arm64")
    with pytest.raises(rp.UnsafeProfileError):
        _profile(kernel_fixture_id="linux-6.12.117-x86_64")


def test_unknown_sensor_source_refused():
    with pytest.raises(rp.MalformedProfileError):
        _profile(sensor_sources=("proc-stat", "hwmon-fans"))


def test_unknown_workload_id_refused():
    with pytest.raises(rp.MalformedProfileError):
        _profile(workload_profile_ids=("crypto-mining.v1",))


def test_probed_basis_refused():
    with pytest.raises(rp.MalformedProfileError):
        _profile(basis="probed-hardware")
    with pytest.raises(rp.MalformedProfileError):
        _profile(basis="lab-verified")


def test_unknown_thermal_class_refused():
    with pytest.raises(rp.MalformedProfileError):
        _profile(thermal_class="liquid-nitrogen")


# --- dict form, fingerprint, catalog -----------------------------------

def test_dict_round_trip():
    for p in rp.BUILTIN_PROFILES:
        assert rp.profile_from_dict(rp.profile_as_dict(p)) == p
        blob = json.loads(json.dumps(rp.profile_as_dict(p)))
        assert rp.profile_from_dict(blob) == p


def test_unknown_dict_field_refused():
    data = rp.profile_as_dict(rp.BUILTIN_PROFILES[0])
    data["measured_on_host"] = "purpleraider"
    with pytest.raises(rp.MalformedProfileError):
        rp.profile_from_dict(data)


def test_fingerprint_stable_and_sensitive():
    p = rp.BUILTIN_PROFILES[0]
    assert p.fingerprint() == rp.profile_from_dict(
        rp.profile_as_dict(p)).fingerprint()
    data = rp.profile_as_dict(p)
    data["memory_budget_mb"] = 512
    assert rp.profile_from_dict(data).fingerprint() != p.fingerprint()


def test_catalog_duplicate_refused():
    p = rp.BUILTIN_PROFILES[0]
    with pytest.raises(rp.DuplicateProfileError):
        rp.validate_catalog((p, p))


def test_catalog_schema_and_unknown_field_refused():
    data = rp.catalog_as_dict(rp.BUILTIN_PROFILES)
    data["schema"] = "lifthrasir.bogus.v9"
    with pytest.raises(rp.MalformedProfileError):
        rp.catalog_from_dict(data)
    data = rp.catalog_as_dict(rp.BUILTIN_PROFILES)
    data["probed_hosts"] = []
    with pytest.raises(rp.MalformedProfileError):
        rp.catalog_from_dict(data)


def test_render_markdown_byte_stable():
    first = rp.render_markdown(rp.BUILTIN_PROFILES)
    second = rp.render_markdown(tuple(reversed(rp.BUILTIN_PROFILES)))
    assert first == second
    assert "no probed hardware is claimed" in first


# --- fit rule against the real banked LIF-1002 envelopes ----------------

def test_every_claimed_workload_fits_its_profile():
    envelopes = _envelopes()
    for p in rp.BUILTIN_PROFILES:
        assert rp.unhostable(p, envelopes) == ()


def test_fit_rule_boundaries():
    p = rp.get_profile("arm64-sbc-4gb.v1")
    assert rp.fits_workload(p, p.memory_budget_mb, p.cpu_cores)
    assert not rp.fits_workload(p, p.memory_budget_mb + 1, 1)
    assert not rp.fits_workload(p, 1, p.cpu_cores + 1)


def test_inference_unclaimed_on_small_sbc_and_caught_when_forced():
    small = rp.get_profile("arm64-sbc-4gb.v1")
    assert "inference-fixture.v1" not in small.workload_profile_ids
    envelopes = _envelopes()
    cap, threads = envelopes["inference-fixture.v1"]
    assert cap <= small.memory_budget_mb  # memory alone would pass
    forced = rp.profile_from_dict({
        **rp.profile_as_dict(small),
        "workload_profile_ids": list(small.workload_profile_ids)
        + ["inference-fixture.v1"]})
    # the claim validates as data, and the fit check is what judges it:
    # inference declares 512 MB / 2 threads, which fits this budget, so
    # unhostable stays empty -- the SBC catalog simply does not claim
    # it. A heavier edited envelope IS caught:
    assert rp.unhostable(forced, envelopes) == ()
    heavier = dict(envelopes)
    heavier["inference-fixture.v1"] = (small.memory_budget_mb + 1, threads)
    assert rp.unhostable(forced, heavier) == ("inference-fixture.v1",)


def test_unverifiable_claim_reported_unhostable():
    p = rp.get_profile("highmem-apu-32gb.v1")
    envelopes = _envelopes()
    del envelopes["io-fixture.v1"]
    assert rp.unhostable(p, envelopes) == ("io-fixture.v1",)


# --- offline surface -----------------------------------------------------

def test_import_surface_is_stdlib_only():
    tree = ast.parse(MOD_PATH.read_text(encoding="utf-8"))
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
    assert imported <= set(sys.stdlib_module_names)
    assert not imported & {"subprocess", "socket", "urllib", "os"}
