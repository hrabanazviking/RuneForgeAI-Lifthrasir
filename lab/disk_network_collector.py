# SPDX-License-Identifier: GPL-2.0-only
"""LIF-0204: disk, inode, mount and network health collectors.

Heimdall observer (Phase P2), READ-ONLY. Parses recorded fixture
text (df-style output, /proc/mounts, /proc/net/dev) into typed
health records. Collectors observe only and never mutate host
state. Missing data stays None, never invented; malformed lines
are skipped and counted, never raise.

Thresholds (documented here; no roadmap threshold exists yet, so
these are the slice's stated lab defaults, not verified limits):
filesystem or inode usage >= 90 percent -> critical alert;
>= 80 percent -> warning alert. Below 80 percent -> no alert.
Home: lab/ per the LIF-0202 collector precedent.
"""
from __future__ import annotations

from dataclasses import dataclass, field

SCHEMA_VERSION = "0.1"
WARN_PCT = 80
CRIT_PCT = 90


@dataclass(frozen=True)
class FilesystemRecord:
    filesystem: str
    size_kb: int | None
    used_kb: int | None
    avail_kb: int | None
    use_pct: int | None
    mounted_on: str


@dataclass(frozen=True)
class InodeRecord:
    filesystem: str
    inodes: int | None
    iused: int | None
    ifree: int | None
    iuse_pct: int | None
    mounted_on: str


@dataclass(frozen=True)
class MountRecord:
    device: str
    mountpoint: str
    fstype: str
    options: tuple
    dump: int | None
    passno: int | None


@dataclass(frozen=True)
class NetIfaceRecord:
    iface: str
    rx_bytes: int | None
    rx_packets: int | None
    rx_errors: int | None
    rx_drop: int | None
    tx_bytes: int | None
    tx_packets: int | None
    tx_errors: int | None
    tx_drop: int | None


@dataclass(frozen=True)
class HealthAlert:
    kind: str
    target: str
    severity: str
    use_pct: int


@dataclass
class DiskNetworkReport:
    filesystems: list = field(default_factory=list)
    inodes: list = field(default_factory=list)
    mounts: list = field(default_factory=list)
    interfaces: list = field(default_factory=list)
    alerts: list = field(default_factory=list)
    skipped: dict = field(default_factory=dict)
    schema_version: str = SCHEMA_VERSION


def _pct_alerts(kind, target, pct):
    if pct is None:
        return []
    if pct >= CRIT_PCT:
        return [HealthAlert(kind, target, "critical", pct)]
    if pct >= WARN_PCT:
        return [HealthAlert(kind, target, "warning", pct)]
    return []


def _to_int(tok):
    try:
        return int(tok)
    except (ValueError, TypeError):
        return None


def parse_df(text):
    """Parse df -P style text. Returns (records, skipped_count)."""
    records, skipped = [], 0
    if not text:
        return records, skipped
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.startswith("Filesystem"):
            continue
        parts = line.split()
        if len(parts) < 6:
            skipped += 1
            continue
        pct_tok = parts[4].rstrip("%")
        pct = _to_int(pct_tok) if pct_tok != "-" else None
        if pct is None and pct_tok != "-":
            skipped += 1
            continue
        size, used, avail = (_to_int(parts[1]), _to_int(parts[2]),
                             _to_int(parts[3]))
        if size is None or used is None or avail is None:
            skipped += 1
            continue
        records.append(FilesystemRecord(
            filesystem=parts[0], size_kb=size, used_kb=used,
            avail_kb=avail, use_pct=pct,
            mounted_on=" ".join(parts[5:]),
        ))
    return records, skipped


def parse_df_inodes(text):
    """Parse df -i style text. Returns (records, skipped_count)."""
    records, skipped = [], 0
    if not text:
        return records, skipped
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.startswith("Filesystem"):
            continue
        parts = line.split()
        if len(parts) < 6:
            skipped += 1
            continue
        pct_tok = parts[4].rstrip("%")
        pct = _to_int(pct_tok) if pct_tok != "-" else None
        if pct is None and pct_tok != "-":
            skipped += 1
            continue
        total, iused, ifree = (_to_int(parts[1]), _to_int(parts[2]),
                               _to_int(parts[3]))
        if total is None or iused is None or ifree is None:
            skipped += 1
            continue
        records.append(InodeRecord(
            filesystem=parts[0], inodes=total, iused=iused,
            ifree=ifree, iuse_pct=pct,
            mounted_on=" ".join(parts[5:]),
        ))
    return records, skipped


def _unescape(s):
    return (s.replace("\\040", " ").replace("\\011", "\t")
             .replace("\\012", "\n").replace("\\134", "\\"))


def parse_mounts(text):
    """Parse /proc/mounts text. Returns (records, skipped_count)."""
    records, skipped = [], 0
    if not text:
        return records, skipped
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        parts = line.split()
        if len(parts) < 6:
            skipped += 1
            continue
        records.append(MountRecord(
            device=_unescape(parts[0]), mountpoint=_unescape(parts[1]),
            fstype=parts[2], options=tuple(parts[3].split(",")),
            dump=_to_int(parts[4]), passno=_to_int(parts[5]),
        ))
    return records, skipped


def parse_net_dev(text):
    """Parse /proc/net/dev text. Returns (records, skipped_count)."""
    records, skipped = [], 0
    if not text:
        return records, skipped
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.startswith("Inter-") or line.startswith("face"):
            continue
        if ":" not in line:
            skipped += 1
            continue
        iface, _, rest = line.partition(":")
        nums = rest.split()
        if len(nums) < 16:
            skipped += 1
            continue
        vals = [_to_int(n) for n in nums[:16]]
        if any(v is None for v in vals):
            skipped += 1
            continue
        records.append(NetIfaceRecord(
            iface=iface.strip(), rx_bytes=vals[0], rx_packets=vals[1],
            rx_errors=vals[2], rx_drop=vals[3], tx_bytes=vals[8],
            tx_packets=vals[9], tx_errors=vals[10], tx_drop=vals[11],
        ))
    return records, skipped


def collect(df_text=None, inode_text=None, mounts_text=None,
            net_text=None):
    """Collect a report purely from recorded fixture text."""
    report = DiskNetworkReport()
    report.filesystems, s1 = parse_df(df_text or "")
    report.inodes, s2 = parse_df_inodes(inode_text or "")
    report.mounts, s3 = parse_mounts(mounts_text or "")
    report.interfaces, s4 = parse_net_dev(net_text or "")
    report.skipped = {"df": s1, "inodes": s2, "mounts": s3, "net": s4}
    for fs in report.filesystems:
        report.alerts.extend(
            _pct_alerts("filesystem", fs.mounted_on, fs.use_pct))
    for ino in report.inodes:
        report.alerts.extend(
            _pct_alerts("inode", ino.mounted_on, ino.iuse_pct))
    return report
