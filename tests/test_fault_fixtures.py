# SPDX-License-Identifier: GPL-2.0-only
"""LIF-0104 tests: fixtures well-formed/distinct, oracle matches golden,
negative control, oracle independence, reproducibility (twice, identical)."""
import hashlib, json, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from lab.fault_fixtures import load_fixtures, validate_fixture
from lab import fault_oracle

FX = load_fixtures()
HEALTHY = {"service": {"name": "demo.service", "active_state": "active", "enabled": True},
           "filesystem": {"mount": "/var", "use_percent": 20, "free_bytes": 999999},
           "config": {"valid": True}, "clock": {"offset_ms": 5, "synchronized": True}}

def test_ten_fixtures_wellformed_and_distinct():
    assert len(FX) == 10
    assert len({f["fault_id"] for f in FX}) == 10
    assert len({f["roadmap_case"] for f in FX}) == 10
    for f in FX:
        assert validate_fixture(f) == [], f["fault_id"]

def test_oracle_matches_golden_all_ten():
    for f in FX:
        ok, verdict = fault_oracle.passes(f["golden_observed_state"], f)
        assert ok, (f["fault_id"], verdict)

def test_negative_control_healthy_state_never_passes_as_fault():
    for f in FX:
        if f["golden_verdict"] == "fault":
            ok, verdict = fault_oracle.passes(HEALTHY, f)
            assert not ok and verdict == "no_fault", f["fault_id"]

def test_oracle_independence_source_scan():
    src = Path(fault_oracle.__file__).read_text()
    # structural: oracle imports only stdlib __future__
    imports = [l for l in src.splitlines() if l.startswith(("import ", "from "))]
    assert all("__future__" in l for l in imports), imports

def _summary():
    rows = []
    for f in FX:
        ok, verdict = fault_oracle.passes(f["golden_observed_state"], f)
        rows.append(f"{f['fault_id']}:{verdict}:{ok}")
    return hashlib.sha256("\n".join(rows).encode()).hexdigest(), rows

def test_reproducibility_twice_byte_identical():
    h1, r1 = _summary(); h2, r2 = _summary()
    assert h1 == h2 and r1 == r2
    assert all(":True" in r for r in r1)
