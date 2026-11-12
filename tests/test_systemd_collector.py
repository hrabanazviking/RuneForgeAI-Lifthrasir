# SPDX-License-Identifier: GPL-2.0-only
"""LIF-0202 systemd collector tests (fixture-based, read-only).

Scope: recorded systemctl/journalctl-style fixture text only.
No test touches the live host systemd state; the live-read
helpers are never called here. Baseline for the differential:
the banked suite before this slice held 31 tests.
"""
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from lab import systemd_collector as sc  # noqa: E402

FIX = REPO / "tests" / "fixtures" / "lif0202"


def _read(name):
    return (FIX / name).read_text(encoding="utf-8")


def test_failed_units_fixture_parsing():
    report = sc.collect(failed_text=_read("systemctl_failed.txt"))
    units = {f.unit: f for f in report.failed_units}
    assert set(units) == {"alpha-fail.service", "beta-fail.service"}
    assert units["alpha-fail.service"].state == "failed"
    assert units["beta-fail.service"].state == "failed"


def test_no_invented_data_without_show_or_journal():
    # Negative-control style: with only the unit listing, the
    # parser must NOT invent since / restart_count values.
    report = sc.collect(failed_text=_read("systemctl_failed.txt"))
    for fu in report.failed_units:
        assert fu.since is None
        assert fu.restart_count is None


def test_show_enrichment_since_and_restart_count():
    report = sc.collect(
        failed_text=_read("systemctl_failed.txt"),
        show_text=_read("systemctl_show.txt"),
    )
    units = {f.unit: f for f in report.failed_units}
    alpha = units["alpha-fail.service"]
    assert alpha.restart_count == 3
    assert alpha.since == "Wed 2026-11-11 09:15:00 UTC"
    beta = units["beta-fail.service"]
    assert beta.since == "Wed 2026-11-11 09:20:00 UTC"
    # beta has no NRestarts in the recorded show text and no
    # journal was supplied: the count stays unknown, not zero.
    assert beta.restart_count is None


def test_restart_timeline_ordering():
    report = sc.collect(journal_text=_read("journal_restarts.json"))
    stamps = [e.timestamp_us for e in report.timeline]
    assert stamps == sorted(stamps)
    assert len(report.timeline) == 6
    assert report.timeline[0].unit == "alpha-fail.service"
    assert report.timeline[0].kind == "started"
    assert report.timeline[-1].unit == "beta-fail.service"
    assert report.timeline[-1].kind == "failed"


def test_restart_counter_from_journal():
    report = sc.collect(
        failed_text=_read("systemctl_failed.txt"),
        journal_text=_read("journal_restarts.json"),
    )
    units = {f.unit: f for f in report.failed_units}
    assert units["alpha-fail.service"].restart_count == 3
    assert units["beta-fail.service"].restart_count is None


def test_healthy_fixture_zero_failures_not_error():
    report = sc.collect(failed_text=_read("systemctl_healthy.txt"))
    assert report.failed_units == []
    assert report.timeline == []


def test_empty_fixture_zero_failures():
    report = sc.collect(failed_text=_read("systemctl_empty.txt"))
    assert report.failed_units == []
    report2 = sc.collect(failed_text="", journal_text="")
    assert report2.failed_units == []
    assert report2.timeline == []


def test_malformed_lines_do_not_crash():
    report = sc.collect(failed_text=_read("systemctl_malformed.txt"))
    units = {f.unit for f in report.failed_units}
    assert units == {"alpha-fail.service"}
    assert len(report.warnings) >= 2


def test_malformed_journal_lines_skipped():
    events, warnings = sc.parse_journal_json(
        _read("journal_restarts.json"))
    assert len(events) == 6
    assert len(warnings) == 3


def test_collector_source_has_no_mutating_commands():
    source = (REPO / "lab" / "systemd_collector.py").read_text(
        encoding="utf-8")
    # Mutating verb names may appear ONLY inside the deny-list
    # definition itself; strip that block before scanning.
    start = source.index("_MUTATING_VERBS")
    end = source.index("])", start)
    scanned = source[:start] + source[end:]
    for token in ['"start"', '"stop"', '"restart"', '"enable"',
                  '"disable"', '"kill"', '"mask"', "os.system",
                  "Popen"]:
        assert token not in scanned, f"mutating token present: {token}"
    # The only subprocess entry points are the two read-only
    # live helpers, and they use read-only verbs only.
    assert source.count("subprocess.run") == 2
    assert "list-units" in source
