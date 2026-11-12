# SPDX-License-Identifier: GPL-2.0-only
"""LIF-0205: read-only CLI - incident list, details, sensor permissions.

Heimdall observer front end (Phase P2). This CLI OBSERVES ONLY: it
reads a local fixture dataset and prints it. It has no mutating
command, no action verb, and no code path that alters any file,
service, or system state. Sensor permissions are reported, never
granted: every sensor entry is observation-only, classified with
the risk-matrix tiers (docs/RISK-MATRIX.md, LIF-0003): L0 (consent
mode none) for public health data, L1 (standing-opt-in) for
consented diagnostic detail. Nothing here performs or authorizes
an action at any tier.

DATA HONESTY: the dataset is a small committed fixture standing in
for the future event store. The live local event store is
LIF-0301's deliverable (Phase P3), NOT this slice's. Fixture
incidents follow the LIF-0004 incident schema v0.1 field shape.

Home justification (master roadmap section 3 + ADR-0002 D2):
section 3 names ui/ for the user interface and the ADR fixes the
interface as local CLI first, KDE/Qt later; the event-bus slice
(LIF-0201) put core Python in src/, but a CLI is interface code,
so it lives in ui/heimdall_cli.py.

Exit codes: 0 success; 2 named user/data error (unknown incident
id, corrupted record, unreadable dataset) - reported on stderr,
never a traceback, never invented data.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

SCHEMA_VERSION = "0.1"
DEFAULT_FIXTURE = (
    Path(__file__).resolve().parent.parent
    / "tests" / "fixtures" / "lif0205" / "fixture.json"
)
REQUIRED_INCIDENT_FIELDS = (
    "incident_id", "status", "severity", "summary",
    "observed_at", "symptoms", "evidence_refs",
)
REQUIRED_SENSOR_FIELDS = (
    "sensor_id", "name", "reads", "risk_tier", "consent_mode",
)


class DataError(Exception):
    """A named, user-facing dataset problem (never a crash)."""


def load_dataset(path):
    """Load and validate the fixture dataset. Read-only."""
    try:
        text = Path(path).read_text(encoding="utf-8")
    except OSError as exc:
        raise DataError(f"dataset unreadable: {path}: {exc}") from exc
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise DataError(f"dataset corrupted: invalid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise DataError("dataset corrupted: top level is not an object")
    for key in ("incidents", "sensors"):
        if not isinstance(data.get(key), list):
            raise DataError(f"dataset corrupted: missing list '{key}'")
    for rec in data["incidents"]:
        if not isinstance(rec, dict):
            raise DataError("dataset corrupted: incident is not an object")
        for field in REQUIRED_INCIDENT_FIELDS:
            if field not in rec:
                raise DataError(
                    "dataset corrupted: incident "
                    f"{rec.get('incident_id', '<no-id>')} missing "
                    f"required field '{field}'")
    for rec in data["sensors"]:
        if not isinstance(rec, dict):
            raise DataError("dataset corrupted: sensor is not an object")
        for field in REQUIRED_SENSOR_FIELDS:
            if field not in rec:
                raise DataError(
                    "dataset corrupted: sensor "
                    f"{rec.get('sensor_id', '<no-id>')} missing "
                    f"required field '{field}'")
        if rec["risk_tier"] not in ("L0", "L1"):
            raise DataError(
                "dataset corrupted: sensor "
                f"{rec['sensor_id']} risk_tier "
                f"{rec['risk_tier']!r} is not an observation tier "
                "(L0/L1); observation only, nothing above L1 may "
                "be listed as a sensor permission")
    return data


def cmd_incidents_list(data, out):
    out.write("incident_id\tstatus\tseverity\tsummary\n")
    for rec in data["incidents"]:
        out.write(
            f"{rec['incident_id']}\t{rec['status']}\t"
            f"{rec['severity']}\t{rec['summary']}\n")
    out.write(f"total: {len(data['incidents'])} incident(s)\n")
    return 0


def cmd_incidents_show(data, incident_id, out):
    for rec in data["incidents"]:
        if rec["incident_id"] == incident_id:
            out.write(json.dumps(rec, indent=2, sort_keys=True) + "\n")
            return 0
    raise DataError(f"unknown incident id: {incident_id}")


def cmd_sensors_permissions(data, out):
    out.write("sensor_id\tname\trisk_tier\tconsent_mode\treads\n")
    for rec in data["sensors"]:
        out.write(
            f"{rec['sensor_id']}\t{rec['name']}\t{rec['risk_tier']}\t"
            f"{rec['consent_mode']}\t{', '.join(rec['reads'])}\n")
    out.write(
        "note: observation only - these permissions describe what "
        "each sensor may READ. They grant nothing and perform no "
        "action (risk matrix L0/L1).\n")
    return 0


def build_parser():
    parser = argparse.ArgumentParser(
        prog="heimdall",
        description="Lifthrasir Heimdall read-only CLI (LIF-0205).")
    parser.add_argument(
        "--data", default=str(DEFAULT_FIXTURE),
        help="path to the incident/sensor dataset (fixture JSON)")
    sub = parser.add_subparsers(dest="group", required=True)
    inc = sub.add_parser("incidents", help="incident queries")
    inc_sub = inc.add_subparsers(dest="verb", required=True)
    inc_sub.add_parser("list", help="list incidents")
    show = inc_sub.add_parser("show", help="show one incident")
    show.add_argument("incident_id")
    sen = sub.add_parser("sensors", help="sensor queries")
    sen_sub = sen.add_subparsers(dest="verb", required=True)
    sen_sub.add_parser("permissions", help="show sensor permissions")
    return parser


def main(argv=None, out=None, err=None):
    out = out if out is not None else sys.stdout
    err = err if err is not None else sys.stderr
    args = build_parser().parse_args(argv)
    try:
        data = load_dataset(args.data)
        if args.group == "incidents" and args.verb == "list":
            return cmd_incidents_list(data, out)
        if args.group == "incidents" and args.verb == "show":
            return cmd_incidents_show(data, args.incident_id, out)
        if args.group == "sensors" and args.verb == "permissions":
            return cmd_sensors_permissions(data, out)
    except DataError as exc:
        err.write(f"error: {exc}\n")
        return 2
    err.write("error: unknown command\n")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
