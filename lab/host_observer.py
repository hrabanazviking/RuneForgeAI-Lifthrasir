# SPDX-License-Identifier: GPL-2.0-only
"""Phase 2 host observer (slice H): READ-ONLY host observation.

Runs unprivileged. Collects live host state using only read-only
queries (systemctl list-units --failed, journal export, df, /proc
reads) via the lab collectors, writes its findings ONLY inside its
own state dir, and drafts proposals as lifthrasir.plan.v0.1 plan
records (validated with approval.plan_digest). It NEVER executes
a plan, never calls a mutating systemctl verb, and holds no broker.

Kill-switch: if the STOP flag file exists in the state dir, or the
KillSwitch in <state>/killswitch is engaged, a cycle records the
halt and collects nothing. Stopping by hand:
  touch ~/.local/state/lifthrasir/STOP   (or systemctl --user stop)
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from systemd_collector import collect as systemd_collect, read_live_failed_text
from disk_network_collector import collect as disk_collect
from proc_sensors import parse_meminfo, parse_proc_stat

DEFAULT_STATE = Path.home() / ".local" / "state" / "lifthrasir"


def _now():
    return datetime.now(timezone.utc)


def _iso(moment):
    return moment.strftime("%Y-%m-%dT%H:%M:%SZ")

_PLAN_ID_MAX = 60


def _slugify(text):
    """Slug satisfying approval.PLAN_ID_RE: [a-z0-9] runs joined by '-'."""
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-") or "unknown"


def _obs_plan_id(prefix, raw, discriminator):
    """plan_id <= 60 chars; overlong slugs keep a hash of the full raw
    name so distinct template instances stay distinct (regression:
    drkonqi-coredump-processor@<instance> units crashed the observer
    on 2026-11-14 because '@' survived the old slug builder)."""
    slug = _slugify(raw)
    plan_id = f"{prefix}{slug}"
    if len(plan_id) > _PLAN_ID_MAX:
        digest = hashlib.sha256(discriminator.encode("utf-8")).hexdigest()[:8]
        keep = _PLAN_ID_MAX - len(prefix) - len(digest) - 1
        plan_id = f"{prefix}{slug[:keep].rstrip('-')}-{digest}"
    return plan_id



def stop_requested(state_dir):
    """True when the campaign STOP flag or the KillSwitch is engaged."""
    if (state_dir / "STOP").exists():
        return True, "flag-file"
    try:
        from lifthrasir.killswitch import KillSwitch
        ks = KillSwitch(state_dir / "killswitch")
        if ks.is_engaged():
            return True, "killswitch-engaged"
    except Exception:
        pass
    return False, ""


def build_proposals(failed_units, alerts, now):
    """Draft plan records for real observations. Records only.

    Failed unit -> an L3 restart_unit proposal (per-action consent
    is above the L3 floor of allowlist-notice). Disk alert -> an L1
    investigate-only record (verb inspect_disk_usage is a proposal
    label; the observer itself executes nothing either way).
    Every proposal is shape-validated via approval.plan_digest.
    """
    from lifthrasir.approval import plan_digest
    proposals = []
    seen_ids = set()
    created = _iso(now)
    expires = _iso(now + timedelta(days=7))
    for fu in failed_units:
        unit = fu["unit"] if isinstance(fu, dict) else fu.unit
        base = unit[:-len(".service")] if unit.endswith(".service") else unit
        plan = {
            "plan_id": _obs_plan_id("plan-obs-", base, unit),
            "schema": "lifthrasir.plan.v0.1",
            "title": f"Investigate failed unit {unit} (observer draft, not approved)",
            "risk_level": "L3",
            "consent_mode": "per-action",
            "created_at": created,
            "expires_at": expires,
            "steps": [{"action_verb": "restart_unit",
                       "target": {"type": "systemd-unit", "name": unit}}],
        }
        if plan["plan_id"] in seen_ids:
            continue
        seen_ids.add(plan["plan_id"])
        proposals.append({"kind": "failed-unit", "unit": unit,
                          "plan": plan, "digest": plan_digest(plan)})
    for alert in alerts:
        kind = alert["kind"] if isinstance(alert, dict) else alert.kind
        target = alert["target"] if isinstance(alert, dict) else alert.target
        sev = alert["severity"] if isinstance(alert, dict) else alert.severity
        plan = {
            "plan_id": _obs_plan_id("plan-obs-disk-", target.strip("/") or "root", target),
            "schema": "lifthrasir.plan.v0.1",
            "title": f"Inspect {kind} usage on {target} ({sev}, observer draft)",
            "risk_level": "L1",
            "consent_mode": "standing-opt-in",
            "created_at": created,
            "expires_at": expires,
            "steps": [{"action_verb": "inspect_disk_usage",
                       "target": {"type": "filesystem", "name": target}}],
        }
        if plan["plan_id"] in seen_ids:
            continue
        seen_ids.add(plan["plan_id"])
        proposals.append({"kind": "disk-alert", "unit": None,
                          "plan": plan, "digest": plan_digest(plan)})
    return proposals


def _run(argv, timeout=20):
    try:
        r = subprocess.run(argv, capture_output=True, text=True,
                           timeout=timeout, check=False)
        return r.stdout or ""
    except Exception:
        return ""


def gather_live():
    failed_text = read_live_failed_text()
    sys_report = systemd_collect(failed_text=failed_text)
    disk_report = disk_collect(
        df_text=_run(["df", "-P"]),
        inode_text=_run(["df", "-iP"]),
        mounts_text=Path("/proc/mounts").read_text(errors="replace"),
        net_text=Path("/proc/net/dev").read_text(errors="replace"),
    )
    mem = parse_meminfo(Path("/proc/meminfo").read_text(errors="replace"))
    cpu = parse_proc_stat(Path("/proc/stat").read_text(errors="replace"))
    failed = [{"unit": f.unit, "state": f.state, "since": f.since,
               "restart_count": f.restart_count}
              for f in sys_report.failed_units]
    # Squashfs mounts (snap packages) are read-only and 100% full BY
    # DESIGN; alerting on them would be inventing incidents. Exclude
    # any alert whose target is a squashfs mountpoint.
    squash = {m.mountpoint for m in disk_report.mounts
              if m.fstype == "squashfs"}
    alerts = [{"kind": a.kind, "target": a.target,
               "severity": a.severity, "use_pct": a.use_pct}
              for a in disk_report.alerts if a.target not in squash]
    snapshot = {
        "failed_units": failed,
        "disk_alerts": alerts,
        "filesystems": [{"mounted_on": f.mounted_on, "use_pct": f.use_pct}
                        for f in disk_report.filesystems],
        "mem_available_kb": getattr(mem, "mem_available_kb", None),
        "warnings": list(sys_report.warnings),
    }
    return snapshot


def render_digest(cycle):
    lines = ["# Lifthrasir observer digest",
             f"Cycle: {cycle['ts']}  Status: {cycle['status']}", ""]
    if cycle["status"] == "halted":
        lines.append(f"HALTED by {cycle.get('halt_reason', 'stop')} - nothing collected.")
        return "\n".join(lines) + "\n"
    snap = cycle["snapshot"]
    if not snap["failed_units"] and not snap["disk_alerts"]:
        lines.append("All observed checks are quiet: no failed units, no disk alerts.")
        lines.append("Honest log: this cycle is a non-issue; no proposals drafted.")
    for fu in snap["failed_units"]:
        lines.append(f"FAILED UNIT: {fu['unit']} (state {fu['state']}) - proposal drafted, NOT executed.")
    for a in snap["disk_alerts"]:
        lines.append(f"DISK {a['severity'].upper()}: {a['target']} at {a['use_pct']}% - proposal drafted, NOT executed.")
    lines.append("")
    lines.append(f"Proposals drafted this cycle: {len(cycle['proposals'])} (records only; Phase 2 never executes).")
    return "\n".join(lines) + "\n"


def run_cycle(state_dir, gather=gather_live):
    state_dir = Path(state_dir)
    state_dir.mkdir(parents=True, exist_ok=True)
    now = _now()
    halted, reason = stop_requested(state_dir)
    if halted:
        cycle = {"ts": _iso(now), "status": "halted", "halt_reason": reason,
                 "snapshot": None, "proposals": []}
    else:
        snapshot = gather()
        proposals = build_proposals(snapshot["failed_units"],
                                     snapshot["disk_alerts"], now)
        cycle = {"ts": _iso(now), "status": "observed",
                 "snapshot": snapshot, "proposals": proposals}
    with open(state_dir / "events.jsonl", "a", encoding="utf-8") as fh:
        fh.write(json.dumps(cycle, sort_keys=True) + "\n")
    (state_dir / "latest.json").write_text(
        json.dumps(cycle, indent=2, sort_keys=True), encoding="utf-8")
    (state_dir / "proposals.json").write_text(
        json.dumps(cycle["proposals"], indent=2, sort_keys=True), encoding="utf-8")
    (state_dir / "DIGEST.md").write_text(render_digest(cycle), encoding="utf-8")
    return cycle


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--state-dir", default=str(DEFAULT_STATE))
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--interval", type=int, default=300)
    args = ap.parse_args(argv)
    state_dir = Path(args.state_dir)
    while True:
        cycle = run_cycle(state_dir)
        print(json.dumps({"ts": cycle["ts"], "status": cycle["status"],
                          "proposals": len(cycle["proposals"])}), flush=True)
        if args.once:
            return 0
        time.sleep(max(30, args.interval))


if __name__ == "__main__":
    raise SystemExit(main())
