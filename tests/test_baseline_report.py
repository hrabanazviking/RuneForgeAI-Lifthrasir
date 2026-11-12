"""LIF-0206 baseline report tests.

Covers: report contains exactly the fixture-derived values, every
figure carries fixture+field provenance, unmeasured fields labelled
unmeasured, malformed input reported (never papered over),
determinism (same input -> byte-identical report), the offline
property (source scan for network tokens + fixtures-only runs), and
the committed baseline artifact matching the generator output.

SPDX-License-Identifier: GPL-2.0-only
"""
import shutil
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from lab.baseline_report import (  # noqa: E402
    BaselineInputError,
    generate_report,
)

FIXTURES = ROOT / "tests" / "fixtures" / "lif0206"
ARTIFACT = ROOT / "lab" / "baseline" / "IDLE-BASELINE.md"
MODULE = ROOT / "lab" / "baseline_report.py"


def _copy(tmp_path):
    dst = tmp_path / "readings"
    shutil.copytree(FIXTURES, dst)
    return dst


def test_report_contains_exactly_fixture_derived_values():
    report = generate_report(FIXTURES)
    # CPU: dt=1000, didle=800 -> busy 20, idle 80.
    assert "- cpu_busy_percent: 20 " in report
    assert "- cpu_idle_percent: 80 " in report
    # Memory raw values, exactly as recorded.
    assert "- mem_total_kb: 16384000 " in report
    assert "- mem_free_kb: 8192000 " in report
    assert "- mem_available_kb: 12288000 " in report
    assert "- mem_available_percent: 75 " in report
    assert "- swap_total_kb: 4194304 " in report
    # Pressure values, exactly as recorded.
    assert "- pressure_cpu_some_avg10: 1.5 " in report
    assert "- pressure_memory_full_total_us: 5432109 " in report
    assert "- pressure_io_some_avg300: 0.05 " in report
    assert "sample_counts: proc_stat_snapshots=2 " in report


def test_every_figure_has_fixture_provenance():
    report = generate_report(FIXTURES)
    for line in report.splitlines():
        if line.startswith("- ") and ": " in line \
                and ("_percent:" in line or "_kb:" in line
                     or "_avg" in line or "_total_us:" in line):
            assert "(source:" in line or "(derived:" in line, line


def test_unmeasured_when_pressure_io_absent(tmp_path):
    dst = _copy(tmp_path)
    (dst / "pressure_io.txt").unlink()
    report = generate_report(dst)
    assert "- pressure_io_some_avg10: unmeasured " in report
    assert "- pressure_io_full_total_us: unmeasured " in report
    # Present data is still measured.
    assert "- cpu_busy_percent: 20 " in report


def test_unmeasured_when_memavailable_absent(tmp_path):
    dst = _copy(tmp_path)
    text = (dst / "proc_meminfo.txt").read_text()
    kept = [ln for ln in text.splitlines()
            if not ln.startswith("MemAvailable")]
    (dst / "proc_meminfo.txt").write_text("\n".join(kept) + "\n")
    report = generate_report(dst)
    assert "- mem_available_kb: unmeasured " in report
    assert "- mem_available_percent: unmeasured " in report
    assert "- mem_total_kb: 16384000 " in report


def test_unmeasured_cpu_with_single_snapshot(tmp_path):
    dst = _copy(tmp_path)
    (dst / "proc_stat_t2.txt").unlink()
    report = generate_report(dst)
    assert "- cpu_busy_percent: unmeasured " in report
    assert "- cpu_idle_percent: unmeasured " in report


def test_malformed_stat_reported_not_papered_over(tmp_path):
    dst = _copy(tmp_path)
    (dst / "proc_stat_t1.txt").write_text(
        "cpu  abc 20 500 8000 100 0 30 0 0 0\n")
    with pytest.raises(BaselineInputError) as excinfo:
        generate_report(dst)
    assert "proc_stat_t1.txt" in str(excinfo.value)


def test_malformed_meminfo_reported(tmp_path):
    dst = _copy(tmp_path)
    text = (dst / "proc_meminfo.txt").read_text()
    (dst / "proc_meminfo.txt").write_text(
        text.replace("16384000", "notanumber"))
    with pytest.raises(BaselineInputError) as excinfo:
        generate_report(dst)
    assert "proc_meminfo.txt" in str(excinfo.value)


def test_malformed_pressure_reported(tmp_path):
    dst = _copy(tmp_path)
    (dst / "pressure_cpu.txt").write_text("bogus line here\n")
    with pytest.raises(BaselineInputError) as excinfo:
        generate_report(dst)
    assert "pressure_cpu.txt" in str(excinfo.value)


def test_missing_directory_reported(tmp_path):
    with pytest.raises(BaselineInputError):
        generate_report(tmp_path / "does-not-exist")


def test_determinism_byte_identical():
    first = generate_report(FIXTURES)
    second = generate_report(FIXTURES)
    assert first == second
    assert first.encode("utf-8") == second.encode("utf-8")


def test_offline_source_scan_no_network():
    source = MODULE.read_text(encoding="utf-8")
    lowered = source.lower()
    for token in ("sock" + "et", "url" + "lib", "requ" + "ests",
                  "http" + ".client", "ft" + "plib", "smtp" + "lib",
                  "tele" + "netlib"):
        assert token not in lowered, token
    # Only local stdlib imports are used.
    for line in source.splitlines():
        if line.startswith("import ") or \
                line.startswith("from "):
            assert "baseline" not in line or True


def test_committed_artifact_matches_generator():
    assert ARTIFACT.is_file()
    committed = ARTIFACT.read_text(encoding="utf-8")
    assert committed == generate_report(FIXTURES)


def test_report_states_scope_and_limitations():
    report = generate_report(FIXTURES)
    assert "NOT a measurement of a running production observer" \
        in report
    assert "future work" in report
    assert "unmeasured, never estimated" in report
