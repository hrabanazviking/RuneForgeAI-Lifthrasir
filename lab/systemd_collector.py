# SPDX-License-Identifier: GPL-2.0-only
"""LIF-0202: systemd service collector (Heimdall observer, read-only).

Parses recorded systemd output (fixtures) into typed records:
failed units and a restart timeline. The collector OBSERVES ONLY:
it never issues any state-changing operation against systemd.
Live reads, when explicitly requested by a caller, use only
read-only queries (list-units / show / journal export) and are
never required by the test suite.

Home justification (master roadmap section 3 + ADR-0002 D2):
collectors are rapid-prototype observation-plane code, so they
live in lab/ (Python for the rapid lab and test harness) until
their contracts stabilize; no src/ or crates/ home exists yet
and inventing one here would pre-empt that stabilization.
"""
from __future__ import annotations

import json
import re
import subprocess
from dataclasses import dataclass, field
from datetime import datetime, timezone

SCHEMA_VERSION = "0.1"

_MUTATING_VERBS = frozenset([
    "enable", "disable", "mask", "unmask", "kill", "reload",
    "daemon-reload", "isolate", "set-property",
])
# NOTE: start/stop/restart verbs are deliberately never named as
# command tokens in this module; the source-scan test enforces it.


@dataclass(frozen=True)
class UnitRecord:
    unit: str
    load: str
    active: str
    sub: str
    description: str = ""


@dataclass(frozen=True)
class FailedUnit:
    unit: str
    state: str
    since: str | None = None
    restart_count: int | None = None


@dataclass(frozen=True)
class RestartEvent:
    unit: str
    timestamp_us: int
    timestamp_iso: str
    kind: str
    message: str
    restart_counter: int | None = None


@dataclass
class CollectionReport:
    failed_units: list = field(default_factory=list)
    timeline: list = field(default_factory=list)
    warnings: list = field(default_factory=list)
    schema_version: str = SCHEMA_VERSION


_COUNTER_RE = re.compile(r"restart counter is at (\d+)")
_TS_FORMATS = ("%Y-%m-%d %H:%M:%S %Z", "%Y-%m-%d %H:%M:%S")


def _clean_line(line: str) -> str:
    line = line.strip()
    if line.startswith("●"):
        line = line[1:].strip()
    return line


def parse_systemctl_units(text: str):
    """Parse systemctl list-units style text into (records, warnings).

    Header, legend and footer lines are skipped. Lines that look
    like unit rows but cannot be split into the five columns are
    recorded as warnings, never raised.
    """
    records, warnings = [], []
    if not text:
        return records, warnings
    for raw in text.splitlines():
        line = _clean_line(raw)
        if not line:
            continue
        low = line.lower()
        if low.startswith("unit ") or low.startswith("load "):
            continue
        if "loaded units listed" in low:
            continue
        if low.startswith(("legend", "active", "sub =", "load =")):
            continue
        if "=" in line and " " not in line.split("=")[0]:
            continue
        parts = line.split(None, 4)
        if len(parts) >= 2 and parts[1] == "=":
            continue
        if len(parts) < 4 or "." not in parts[0]:
            warnings.append("skipped malformed line: " + raw.strip()[:80])
            continue
        records.append(UnitRecord(
            unit=parts[0], load=parts[1], active=parts[2], sub=parts[3],
            description=parts[4] if len(parts) > 4 else "",
        ))
    return records, warnings


def parse_show(text: str):
    """Parse systemctl show key=value blocks keyed by unit Id.

    Returns {unit: {key: value}}. Restart counts and timestamps
    come only from this recorded text; absent keys stay absent.
    """
    out, current = {}, None
    if not text:
        return out
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            current = None
            continue
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        if key == "Id":
            current = value
            out.setdefault(current, {})
        if current is not None:
            out[current][key] = value
    return out


def failed_from_units(records, show=None):
    """Build FailedUnit records; since/restart_count only when the
    recorded show data carries them, otherwise None (never invented).
    """
    show = show or {}
    failed = []
    for rec in records:
        if rec.active == "failed" or rec.sub == "failed":
            info = show.get(rec.unit, {})
            since = info.get("ActiveEnterTimestamp") or None
            raw_count = info.get("NRestarts")
            count = None
            if raw_count is not None:
                try:
                    count = int(raw_count)
                except ValueError:
                    count = None
            failed.append(FailedUnit(
                unit=rec.unit, state=rec.active,
                since=since, restart_count=count,
            ))
    return failed


def _message_text(value):
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        try:
            return bytes(value).decode("utf-8", errors="replace")
        except (ValueError, TypeError):
            return ""
    return ""


def _event_kind(message: str) -> str:
    low = message.lower()
    if "scheduled restart" in low:
        return "restart_scheduled"
    if "failed" in low:
        return "failed"
    if "stopped" in low or "stopping" in low:
        return "stopped"
    if "started" in low:
        return "started"
    return "other"


def parse_journal_json(text: str):
    """Parse journalctl -o json NDJSON into (events, warnings).

    Bad JSON lines and entries without a unit or timestamp are
    skipped with a warning; parsing never raises on bad input.
    """
    events, warnings = [], []
    if not text:
        return events, warnings
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except (ValueError, TypeError):
            warnings.append("skipped malformed json line")
            continue
        unit = obj.get("_SYSTEMD_UNIT")
        ts_raw = obj.get("__REALTIME_TIMESTAMP")
        if not unit or ts_raw is None:
            warnings.append("skipped journal entry missing unit/timestamp")
            continue
        try:
            ts_us = int(ts_raw)
        except (ValueError, TypeError):
            warnings.append("skipped journal entry with bad timestamp")
            continue
        message = _message_text(obj.get("MESSAGE", ""))
        counter = None
        m = _COUNTER_RE.search(message)
        if m:
            counter = int(m.group(1))
        iso = datetime.fromtimestamp(
            ts_us / 1_000_000, tz=timezone.utc).isoformat()
        events.append(RestartEvent(
            unit=unit, timestamp_us=ts_us, timestamp_iso=iso,
            kind=_event_kind(message), message=message,
            restart_counter=counter,
        ))
    return events, warnings


def build_restart_timeline(events):
    """Restart timeline: events sorted ascending by timestamp
    (stable for ties, so recorded order breaks ties)."""
    relevant = [e for e in events if e.kind != "other"]
    return sorted(relevant, key=lambda e: e.timestamp_us)


def max_restart_counter(events, unit: str):
    counters = [e.restart_counter for e in events
                if e.unit == unit and e.restart_counter is not None]
    return max(counters) if counters else None


def collect(failed_text=None, journal_text=None, show_text=None):
    """Collect a report purely from recorded fixture text."""
    records, w1 = parse_systemctl_units(failed_text or "")
    show = parse_show(show_text or "")
    failed = failed_from_units(records, show)
    events, w2 = parse_journal_json(journal_text or "")
    # Enrich restart counts from journal counters only when the
    # show data did not already provide a recorded count.
    enriched = []
    for fu in failed:
        count = fu.restart_count
        if count is None:
            count = max_restart_counter(events, fu.unit)
        enriched.append(FailedUnit(
            unit=fu.unit, state=fu.state, since=fu.since,
            restart_count=count,
        ))
    return CollectionReport(
        failed_units=enriched,
        timeline=build_restart_timeline(events),
        warnings=w1 + w2,
    )


def read_live_failed_text():
    """OPTIONAL live read (read-only). Never used by tests.

    Runs a single read-only unit listing with no pager. There is
    no code path in this module that changes service state.
    """
    result = subprocess.run(
        ["systemctl", "list-units", "--failed", "--no-pager",
         "--no-legend", "--plain"],
        capture_output=True, text=True, timeout=15, check=False,
    )
    return result.stdout or ""


def read_live_journal_text():
    """OPTIONAL live read (read-only journal export)."""
    result = subprocess.run(
        ["journalctl", "-o", "json", "--no-pager", "-n", "500"],
        capture_output=True, text=True, timeout=15, check=False,
    )
    return result.stdout or ""
