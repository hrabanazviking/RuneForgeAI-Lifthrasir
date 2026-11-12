# SPDX-License-Identifier: GPL-2.0-only
"""LIF-1002 tests for workload profiles (lab/workload_profiles.py).

Covers: the five backlog families (memory pressure, compilation,
inference, graphics, I/O) present in the built-in catalog, strict
fail-closed profile validation (unknown categories, operations
outside the allowlist, fixture size caps, process-subverting pins),
canonical dict round-trips, fingerprint stability and sensitivity,
the LIF-1001 harness binding (every built-in profile renders a spec
the banked harness accepts, with an equal controlled fingerprint),
the deterministic synthetic executor (same profile, same checksum;
any edit moves the checksum; lab-vm profiles refused on a host),
catalog strictness (duplicates, unknown fields, schema), fixture
loading, byte-stable catalog reports, and the offline import
surface. Everything is fixture-scale: no test stresses the host.
"""
import ast
import importlib.util
import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
MOD_PATH = REPO / "lab" / "workload_profiles.py"
HARNESS_PATH = REPO / "lab" / "benchmark_harness.py"
FIXTURE = REPO / "tests" / "fixtures" / "lif1002" / "profiles.json"

spec = importlib.util.spec_from_file_location("workload_profiles", MOD_PATH)
wp = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = wp
spec.loader.exec_module(wp)

hspec = importlib.util.spec_from_file_location("benchmark_harness", HARNESS_PATH)
bench = importlib.util.module_from_spec(hspec)
sys.modules[hspec.name] = bench
hspec.loader.exec_module(bench)


def _profile(**kw):
    base = {"profile_id": "test-fixture.v1", "category": "io",
            "title": "Test profile",
            "operations": (wp.Operation("buffer-copy", 1024),)}
    base.update(kw)
    return wp.WorkloadProfile(**base)


# --- built-in catalog -------------------------------------------------

def test_module_file_exists():
    assert MOD_PATH.is_file(), "lab/workload_profiles.py is missing"


def test_builtin_catalog_covers_all_five_backlog_categories():
    assert wp.missing_categories(wp.BUILTIN_PROFILES) == ()
    assert {p.category for p in wp.BUILTIN_PROFILES} == set(wp.CATEGORIES)
    assert set(wp.CATEGORIES) == {"memory-pressure", "compilation",
                                  "inference", "graphics", "io"}


def test_builtin_profiles_are_all_fixture_class():
    for p in wp.BUILTIN_PROFILES:
        assert p.safety_class == "fixture"
        assert wp.execute_profile(p)["ops_completed"] == len(p.operations)


def test_get_profile_and_unknown_refused():
    assert wp.get_profile("io-fixture.v1").category == "io"
    with pytest.raises(wp.MalformedProfileError):
        wp.get_profile("nope.v1")


def test_fixture_file_matches_builtin_catalog():
    loaded = wp.load_catalog(FIXTURE)
    assert wp.catalog_as_dict(loaded) == wp.catalog_as_dict(wp.BUILTIN_PROFILES)


# --- validation: fail-closed ------------------------------------------

def test_unknown_category_refused():
    with pytest.raises(wp.UnknownCategoryError):
        _profile(category="network")


def test_operation_outside_allowlist_refused():
    with pytest.raises(wp.UnsafeProfileError):
        wp.Operation("fork-bomb", 10)
    with pytest.raises(wp.UnsafeProfileError):
        wp.Operation("dd-write", 10)


def test_operation_size_caps_refused():
    with pytest.raises(wp.MalformedProfileError):
        wp.Operation("hash-chain", 0)
    with pytest.raises(wp.MalformedProfileError):
        wp.Operation("hash-chain", wp.MAX_OP_SIZE + 1)
    many = tuple(wp.Operation("hash-chain", wp.MAX_OP_SIZE)
                 for _ in range(5))
    with pytest.raises(wp.UnsafeProfileError):
        _profile(operations=many)  # total exceeds MAX_TOTAL_SIZE
    with pytest.raises(wp.UnsafeProfileError):
        _profile(operations=tuple(wp.Operation("hash-chain", 10)
                                  for _ in range(wp.MAX_OPERATIONS + 1)))


def test_envelope_bounds_refused():
    with pytest.raises(wp.MalformedProfileError):
        _profile(repetitions=wp.MIN_REPETITIONS - 1)
    with pytest.raises(wp.MalformedProfileError):
        _profile(memory_cap_mb=0)
    with pytest.raises(wp.MalformedProfileError):
        _profile(memory_cap_mb=wp.MAX_MEMORY_CAP_MB + 1)
    with pytest.raises(wp.MalformedProfileError):
        _profile(threads=0)
    with pytest.raises(wp.MalformedProfileError):
        _profile(timeout_s=99999.0)


def test_forbidden_and_malformed_pins_refused():
    for key in ("LD_PRELOAD", "PYTHONPATH", "NODE_OPTIONS"):
        with pytest.raises(wp.UnsafeProfileError):
            _profile(pinned_env={key: "x"})
    for key in ("lower_case", "HAS SPACE", "9LEADING", ""):
        with pytest.raises(wp.UnsafeProfileError):
            _profile(pinned_env={key: "x"})
    with pytest.raises(wp.MalformedProfileError):
        _profile(pinned_env={"GOOD_KEY": 3})


def test_metrics_rules():
    with pytest.raises(wp.MalformedProfileError):
        _profile(metrics=("wall_time_s",))  # checksum is mandatory
    with pytest.raises(wp.MalformedProfileError):
        _profile(metrics=("checksum", "telepathy"))
    with pytest.raises(wp.MalformedProfileError):
        _profile(metrics=("checksum", "checksum"))


def test_profile_id_rules():
    for bad in ("NoCaps.v1", "has space.v1", "nodigit", "-lead.v1", ""):
        with pytest.raises(wp.MalformedProfileError):
            _profile(profile_id=bad)
    assert _profile(profile_id="ok-id_2.v3").profile_id == "ok-id_2.v3"


def test_unknown_safety_class_and_harness_workload_refused():
    with pytest.raises(wp.MalformedProfileError):
        _profile(safety_class="host")
    with pytest.raises(wp.MalformedProfileError):
        _profile(harness_workload="stress-ng")


# --- dict forms, fingerprints, harness binding -------------------------

def test_profile_dict_roundtrip_and_strictness():
    for original in wp.BUILTIN_PROFILES:
        clone = wp.profile_from_dict(wp.profile_as_dict(original))
        assert clone == original
    bad = wp.profile_as_dict(_profile())
    bad["surprise"] = True
    with pytest.raises(wp.MalformedProfileError):
        wp.profile_from_dict(bad)
    bad2 = wp.profile_as_dict(_profile())
    bad2["schema"] = "lifthrasir.workload-profile.v9.9"
    with pytest.raises(wp.MalformedProfileError):
        wp.profile_from_dict(bad2)
    bad3 = wp.profile_as_dict(_profile())
    del bad3["category"]
    with pytest.raises(wp.MalformedProfileError):
        wp.profile_from_dict(bad3)


def test_fingerprint_stable_and_sensitive():
    a = wp.get_profile("mem-pressure-fixture.v1")
    assert a.fingerprint() == wp.profile_from_dict(
        wp.profile_as_dict(a)).fingerprint()
    base = a.fingerprint()
    changed = wp.profile_from_dict({**wp.profile_as_dict(a), "seed": 99})
    assert changed.fingerprint() != base
    changed2 = wp.profile_from_dict(
        {**wp.profile_as_dict(a), "memory_cap_mb": 128})
    assert changed2.fingerprint() != base


def test_harness_binding_accepted_by_banked_harness():
    for p in wp.BUILTIN_PROFILES:
        rendered = wp.environment_spec_dict(p)
        env_spec = bench.spec_from_dict(rendered)
        assert env_spec.workload_id == p.harness_workload
        assert env_spec.seed == p.seed
        assert bench.spec_as_dict(env_spec) == rendered


def test_harness_runs_bound_workload_deterministically():
    p = wp.get_profile("compile-fixture.v1")
    measurement = bench.run_builtin(bench.spec_from_dict(
        wp.environment_spec_dict(p)))
    assert measurement.checksum
    assert len(measurement.samples) == p.repetitions


# --- synthetic executor --------------------------------------------------

def test_execute_is_deterministic():
    for p in wp.BUILTIN_PROFILES:
        first = wp.execute_profile(p)
        second = wp.execute_profile(p)
        assert first == second
        assert first["fingerprint"] == p.fingerprint()


def test_execute_checksum_moves_with_any_edit():
    a = wp.get_profile("io-fixture.v1")
    base = wp.execute_profile(a)["checksum"]
    other_seed = wp.profile_from_dict({**wp.profile_as_dict(a), "seed": 16})
    assert wp.execute_profile(other_seed)["checksum"] != base
    other_ops = wp.profile_from_dict(
        {**wp.profile_as_dict(a),
         "operations": [{"kind": "buffer-copy", "size": 32767},
                        {"kind": "hash-chain", "size": 8000}]})
    assert wp.execute_profile(other_ops)["checksum"] != base


def test_execute_distinct_profiles_distinct_checksums():
    checksums = {wp.execute_profile(p)["checksum"]
                 for p in wp.BUILTIN_PROFILES}
    assert len(checksums) == len(wp.BUILTIN_PROFILES)


def test_execute_refuses_lab_vm_profiles_on_host():
    vm_profile = _profile(safety_class="lab-vm")
    with pytest.raises(wp.UnsafeProfileError):
        wp.execute_profile(vm_profile)


def test_execute_bytes_touched_hand_computed():
    result = wp.execute_profile(wp.get_profile("io-fixture.v1"))
    # buffer-copy 32768 touches 2*32768 bytes; hash-chain touches 0.
    assert result["bytes_touched"] == 65536
    assert result["ops_completed"] == 2


# --- catalogs and reports -----------------------------------------------

def test_catalog_duplicate_ids_refused():
    a = wp.get_profile("io-fixture.v1")
    with pytest.raises(wp.DuplicateProfileError):
        wp.validate_catalog([a, a])
    data = wp.catalog_as_dict([a])
    data["profiles"].append(data["profiles"][0])
    with pytest.raises(wp.DuplicateProfileError):
        wp.catalog_from_dict(data)


def test_catalog_strictness():
    data = wp.catalog_as_dict(wp.BUILTIN_PROFILES)
    bad = dict(data, surprise=True)
    with pytest.raises(wp.MalformedProfileError):
        wp.catalog_from_dict(bad)
    bad2 = dict(data, schema="lifthrasir.workload-catalog.v9.9")
    with pytest.raises(wp.MalformedProfileError):
        wp.catalog_from_dict(bad2)
    with pytest.raises(wp.MalformedProfileError):
        wp.catalog_from_dict({"schema": wp.CATALOG_SCHEMA,
                              "profiles": "nope"})


def test_missing_categories_partial_catalog():
    only_io = [wp.get_profile("io-fixture.v1")]
    assert wp.missing_categories(only_io) == (
        "memory-pressure", "compilation", "inference", "graphics")


def test_render_markdown_byte_stable_and_complete():
    first = wp.render_markdown(wp.BUILTIN_PROFILES)
    second = wp.render_markdown(list(reversed(wp.BUILTIN_PROFILES)))
    assert first == second  # input order cannot change the report
    for p in wp.BUILTIN_PROFILES:
        assert p.profile_id in first
        assert p.fingerprint() in first
    assert "categories covered: 5 of 5" in first


def test_fixture_json_is_canonical_catalog():
    data = json.loads(FIXTURE.read_text(encoding="utf-8"))
    assert data["schema"] == wp.CATALOG_SCHEMA
    assert len(data["profiles"]) == 5


# --- offline surface ------------------------------------------------------

def test_import_surface_is_stdlib_offline_only():
    tree = ast.parse(MOD_PATH.read_text(encoding="utf-8"))
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
    assert imported <= {"__future__", "hashlib", "json", "re",
                        "dataclasses", "pathlib"}
    called = {node.func.attr if isinstance(node.func, ast.Attribute)
              else getattr(node.func, "id", "")
              for node in ast.walk(tree) if isinstance(node, ast.Call)}
    assert not (called & {"system", "popen", "exec", "eval", "__import__"})
