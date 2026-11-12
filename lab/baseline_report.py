# SPDX-License-Identifier: GPL-2.0-only
"""LIF-0206: idle overhead and offline baseline report generator.

Heimdall observer, read-only, offline. Takes RECORDED sensor and
collector readings (fixture files in the style of LIF-0203: /proc/stat
snapshots, /proc/meminfo, /proc/pressure/*) and produces a baseline
report in which every figure carries its exact provenance (fixture
file plus field) and every value absent from the input stays
'unmeasured' -- never estimated, never invented. That honesty rule
is the whole point of this slice (campaign evidence-honesty law).

Scope, stated plainly: this is baseline-report TOOLING plus a
methodology-honest baseline measured on purpleraider fixtures /
recorded data. It is NOT a claim about a running production
observer; no production observer exists yet. A live idle
measurement of a real observer is future work and is not claimed.

Home justification (master roadmap section 3, following the
LIF-0202 / LIF-0203 precedent): measurement tooling for the rapid
lab lives in lab/ (Python for the rapid lab and test harness)
until its contracts stabilize.

Offline guarantee: this module imports only local-file and text
standard-library helpers, opens only files under the readings
directory it is given, and performs pure local file processing.
The test suite proves the offline property by source scan (no
network-related tokens) and by running only against fixtures.

Method:
- CPU: two /proc/stat aggregate snapshots (t1, t2). Busy percent is
  100 * (dtotal - didle_all) / dtotal over the interval; idle
  percent is 100 - busy. With fewer than two snapshots, or with
  counters that do not advance, both stay unmeasured.
- Memory: single /proc/meminfo snapshot. Raw kB figures are
  reported as recorded; mem_available_percent is a labelled
  derived value, 100 * MemAvailable / MemTotal, only when both
  fields are present.
- Pressure: PSI some/full avg10/avg60/avg300 and totals from each
  pressure file present; absent files or fields stay unmeasured.
Output is deterministic: fixed field order, sorted provenance,
no timestamps and no host-dependent values, so the same input
always yields a byte-identical report.
"""
from __future__ import annotations

import hashlib
from pathlib import Path

REPORT_VERSION = "0.1"
UNMEASURED = "unmeasured"

STAT_T1 = "proc_stat_t1.txt"
STAT_T2 = "proc_stat_t2.txt"
MEMINFO = "proc_meminfo.txt"
PRESSURE_FILES = ("pressure_cpu.txt", "pressure_memory.txt",
                  "pressure_io.txt")


class BaselineInputError(Exception):
    """Raised when a present input file is malformed.

    Malformed input is reported, never papered over: the error
    names the file and the offending content.
    """


def _read(path):
    try:
        return path.read_text(encoding="utf-8")
    except OSError as exc:
        raise BaselineInputError(
            "cannot read " + path.name + ": " + str(exc)) from exc


def _sha256_text(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def parse_proc_stat(text, fname):
    """Return (aggregate dict or None, sample line count)."""
    agg = None
    for raw in text.splitlines():
        parts = raw.split()
        if not parts or parts[0] != "cpu":
            continue
        try:
            nums = [int(p) for p in parts[1:]]
        except ValueError:
            raise BaselineInputError(
                fname + ": malformed cpu line (non-integer "
                "counter): " + raw.strip())
        if len(nums) < 4:
            raise BaselineInputError(
                fname + ": malformed cpu line (fewer than 4 "
                "counters): " + raw.strip())
        nums = (nums + [0] * 10)[:10]
        keys = ("user", "nice", "system", "idle", "iowait", "irq",
                "softirq", "steal", "guest", "guest_nice")
        agg = dict(zip(keys, nums))
    return agg


_MEM_KEYS = ("MemTotal", "MemFree", "MemAvailable", "Buffers",
             "Cached", "SwapTotal", "SwapFree")


def parse_meminfo(text, fname):
    out = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        if ":" not in line:
            raise BaselineInputError(
                fname + ": malformed meminfo line (no colon): "
                + line)
        key, _, rest = line.partition(":")
        key = key.strip()
        if key not in _MEM_KEYS:
            continue
        tokens = rest.split()
        try:
            out[key] = int(tokens[0])
        except (ValueError, IndexError):
            raise BaselineInputError(
                fname + ": malformed meminfo value for " + key
                + ": " + line)
    return out


def parse_pressure(text, fname):
    out = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        parts = line.split()
        kind = parts[0]
        if kind not in ("some", "full"):
            raise BaselineInputError(
                fname + ": malformed pressure line (expected "
                "some/full): " + line)
        vals = {}
        for tok in parts[1:]:
            if "=" not in tok:
                raise BaselineInputError(
                    fname + ": malformed pressure token: " + tok)
            k, _, v = tok.partition("=")
            try:
                vals[k] = (int(v) if k == "total" else float(v))
            except ValueError:
                raise BaselineInputError(
                    fname + ": malformed pressure value: " + tok)
        for need in ("avg10", "avg60", "avg300", "total"):
            if need not in vals:
                raise BaselineInputError(
                    fname + ": pressure line missing " + need
                    + ": " + line)
        out[kind] = vals
    return out


def load_readings(readings_dir):
    """Load every reading present; absent files stay absent."""
    d = Path(readings_dir)
    if not d.is_dir():
        raise BaselineInputError(
            "readings directory does not exist: " + str(d))
    data = {"files": {}, "hashes": {}}
    for name in (STAT_T1, STAT_T2, MEMINFO) + PRESSURE_FILES:
        p = d / name
        if p.is_file():
            text = _read(p)
            data["files"][name] = text
            data["hashes"][name] = _sha256_text(text)
    if STAT_T1 in data["files"]:
        data["stat_t1"] = parse_proc_stat(data["files"][STAT_T1],
                                          STAT_T1)
    if STAT_T2 in data["files"]:
        data["stat_t2"] = parse_proc_stat(data["files"][STAT_T2],
                                          STAT_T2)
    if MEMINFO in data["files"]:
        data["meminfo"] = parse_meminfo(data["files"][MEMINFO],
                                        MEMINFO)
    data["pressure"] = {}
    for name in PRESSURE_FILES:
        if name in data["files"]:
            resource = name[len("pressure_"):-len(".txt")]
            data["pressure"][resource] = parse_pressure(
                data["files"][name], name)
    return data


def _fmt(value):
    if isinstance(value, float):
        text = "%.4f" % value
        return text.rstrip("0").rstrip(".") if "." in text else text
    return str(value)


def generate_report(readings_dir):
    """Return the deterministic baseline report text."""
    data = load_readings(readings_dir)
    lines = []
    lines.append("# Lifthrasir idle baseline report v" +
                 REPORT_VERSION + " (LIF-0206)")
    lines.append("")
    lines.append("Scope: fixture/recorded-data baseline produced "
                 "offline by lab/baseline_report.py. This is NOT a "
                 "measurement of a running production observer; no "
                 "production observer exists yet.")
    lines.append("Method: CPU busy/idle from two /proc/stat "
                 "aggregate snapshots; memory from one "
                 "/proc/meminfo snapshot; pressure from PSI "
                 "some/full lines. Any value absent from the input "
                 "is reported as unmeasured, never estimated.")
    lines.append("")
    lines.append("## Inputs (provenance)")
    present = sorted(data["files"])
    if present:
        for name in present:
            lines.append("- input_file: " + name + " sha256=" +
                         data["hashes"][name])
    else:
        lines.append("- input_file: none")
    lines.append("- sample_counts: proc_stat_snapshots=" +
                 str(int(STAT_T1 in data["files"]) +
                     int(STAT_T2 in data["files"])) +
                 " meminfo_snapshots=" +
                 str(int(MEMINFO in data["files"])) +
                 " pressure_files=" +
                 str(len(data["pressure"])))
    lines.append("")
    lines.append("## CPU (idle overhead)")
    t1 = data.get("stat_t1")
    t2 = data.get("stat_t2")
    busy = None
    if t1 and t2:
        tot1 = sum(t1.values())
        tot2 = sum(t2.values())
        idle1 = t1["idle"] + t1["iowait"]
        idle2 = t2["idle"] + t2["iowait"]
        dt = tot2 - tot1
        di = idle2 - idle1
        if dt > 0:
            busy = round(100.0 * (dt - di) / dt, 4)
    if busy is None:
        lines.append("- cpu_busy_percent: " + UNMEASURED +
                     " (source: " + STAT_T1 + ":cpu + " +
                     STAT_T2 + ":cpu; reason: fewer than two "
                     "advancing snapshots in input)")
        lines.append("- cpu_idle_percent: " + UNMEASURED +
                     " (source: " + STAT_T1 + ":cpu + " +
                     STAT_T2 + ":cpu; reason: fewer than two "
                     "advancing snapshots in input)")
    else:
        lines.append("- cpu_busy_percent: " + _fmt(busy) +
                     " (derived: " + STAT_T1 + ":cpu + " +
                     STAT_T2 + ":cpu; formula: 100*(dtotal-"
                     "didle_all)/dtotal)")
        lines.append("- cpu_idle_percent: " + _fmt(round(
            100.0 - busy, 4)) + " (derived: 100 - "
            "cpu_busy_percent)")
    lines.append("")
    lines.append("## Memory")
    mem = data.get("meminfo") or {}
    label = {"MemTotal": "mem_total_kb", "MemFree": "mem_free_kb",
             "MemAvailable": "mem_available_kb",
             "Buffers": "buffers_kb", "Cached": "cached_kb",
             "SwapTotal": "swap_total_kb",
             "SwapFree": "swap_free_kb"}
    for key in _MEM_KEYS:
        if key in mem:
            lines.append("- " + label[key] + ": " + str(mem[key]) +
                         " (source: " + MEMINFO + ":" + key + ")")
        else:
            lines.append("- " + label[key] + ": " + UNMEASURED +
                         " (source: " + MEMINFO + ":" + key +
                         "; reason: field absent from input)")
    if "MemAvailable" in mem and "MemTotal" in mem \
            and mem["MemTotal"] > 0:
        pct = round(100.0 * mem["MemAvailable"] / mem["MemTotal"],
                    4)
        lines.append("- mem_available_percent: " + _fmt(pct) +
                     " (derived: " + MEMINFO + ":MemAvailable / " +
                     MEMINFO + ":MemTotal * 100)")
    else:
        lines.append("- mem_available_percent: " + UNMEASURED +
                     " (source: " + MEMINFO +
                     ":MemAvailable,MemTotal; reason: field absent "
                     "from input)")
    lines.append("")
    lines.append("## Pressure (PSI)")
    for resource in ("cpu", "memory", "io"):
        fname = "pressure_" + resource + ".txt"
        pres = data["pressure"].get(resource)
        for kind in ("some", "full"):
            key = "pressure_" + resource + "_" + kind
            if pres and kind in pres:
                v = pres[kind]
                lines.append(
                    "- " + key + "_avg10: " + _fmt(v["avg10"]) +
                    " (source: " + fname + ":" + kind + " avg10)")
                lines.append(
                    "- " + key + "_avg60: " + _fmt(v["avg60"]) +
                    " (source: " + fname + ":" + kind + " avg60)")
                lines.append(
                    "- " + key + "_avg300: " + _fmt(v["avg300"]) +
                    " (source: " + fname + ":" + kind + " avg300)")
                lines.append(
                    "- " + key + "_total_us: " + str(v["total"]) +
                    " (source: " + fname + ":" + kind + " total)")
            else:
                for suffix in ("avg10", "avg60", "avg300",
                               "total_us"):
                    lines.append(
                        "- " + key + "_" + suffix + ": " +
                        UNMEASURED + " (source: " + fname + ":" +
                        kind + "; reason: absent from input)")
    lines.append("")
    lines.append("## Limitations")
    lines.append("- Fixture-based baseline only; a live idle "
                 "measurement of a real observer is future work "
                 "and is NOT claimed here.")
    lines.append("- Evidence status: reproducer-level, "
                 "fixture-tested offline on purpleraider only. "
                 "Not lab-verified, cross-platform-verified or "
                 "human-reviewed.")
    lines.append("")
    return "\n".join(lines)


def main(argv=None):
    import sys
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) not in (1, 2):
        print("usage: baseline_report.py READINGS_DIR [OUTPUT]")
        return 2
    try:
        report = generate_report(args[0])
    except BaselineInputError as exc:
        print("error: " + str(exc))
        return 1
    if len(args) == 2:
        Path(args[1]).write_text(report, encoding="utf-8")
    else:
        print(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
