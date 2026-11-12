# SPDX-License-Identifier: GPL-2.0-only
"""Slice H tests: Phase 2 host observer (read-only, kill-switch, proposals)."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "lab"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import host_observer as obs


def _fake_gather():
    return {
        "failed_units": [{"unit": "demo.service", "state": "failed",
                          "since": None, "restart_count": 2}],
        "disk_alerts": [{"kind": "filesystem", "target": "/",
                         "severity": "warning", "use_pct": 85}],
        "filesystems": [{"mounted_on": "/", "use_pct": 85}],
        "mem_available_kb": 12345,
        "warnings": [],
    }


def test_cycle_writes_only_in_state_dir(tmp_path):
    cycle = obs.run_cycle(tmp_path, gather=_fake_gather)
    assert cycle["status"] == "observed"
    assert (tmp_path / "latest.json").exists()
    assert (tmp_path / "events.jsonl").exists()
    assert "demo.service" in (tmp_path / "DIGEST.md").read_text()


def test_proposals_are_valid_plan_records(tmp_path):
    cycle = obs.run_cycle(tmp_path, gather=_fake_gather)
    assert len(cycle["proposals"]) == 2
    for p in cycle["proposals"]:
        assert p["digest"].startswith("sha256:")
        assert p["plan"]["schema"] == "lifthrasir.plan.v0.1"


def test_stop_flag_halts_collection(tmp_path):
    (tmp_path / "STOP").write_text("stop\n")
    called = []

    def gather():
        called.append(1)
        return _fake_gather()

    cycle = obs.run_cycle(tmp_path, gather=gather)
    assert cycle["status"] == "halted"
    assert called == []
    assert "HALTED" in (tmp_path / "DIGEST.md").read_text()


def test_quiet_cycle_is_honest_non_issue(tmp_path):
    def quiet():
        return {"failed_units": [], "disk_alerts": [], "filesystems": [],
                "mem_available_kb": None, "warnings": []}

    cycle = obs.run_cycle(tmp_path, gather=quiet)
    assert cycle["proposals"] == []
    assert "non-issue" in (tmp_path / "DIGEST.md").read_text()


def test_observer_source_has_no_mutating_verbs():
    src = Path(obs.__file__).read_text()
    for verb in ('"start"', '"restart"', '"enable"', '"mask"',
                 "systemctl\", \"stop"):
        assert verb not in src
    saved = json.loads(json.dumps(_fake_gather()))
    assert saved["failed_units"][0]["unit"] == "demo.service"


def test_duplicate_alert_targets_dedupe_to_one_proposal():
    from datetime import datetime, timezone
    alerts = [
        {"kind": "filesystem", "target": "/snap/x/1",
         "severity": "critical", "use_pct": 100},
        {"kind": "inode", "target": "/snap/x/1",
         "severity": "critical", "use_pct": 100},
    ]
    # plan_id derives from target only, so the second must dedupe;
    # titles differ by kind, ids must not.
    props = obs.build_proposals([], alerts, datetime.now(timezone.utc))
    assert len(props) == 1
