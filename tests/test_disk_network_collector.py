# SPDX-License-Identifier: GPL-2.0-only
"""LIF-0204 tests: disk, inode, mount and network collectors."""
import pathlib

from lab.disk_network_collector import (
    CRIT_PCT, WARN_PCT, collect, parse_df, parse_df_inodes,
    parse_mounts, parse_net_dev,
)

FIX = pathlib.Path(__file__).parent / "fixtures" / "lif0204"


def _read(name):
    return (FIX / name).read_text(encoding="utf-8")


def test_parse_df_healthy():
    records, skipped = parse_df(_read("df_healthy.txt"))
    assert skipped == 0
    assert len(records) == 3
    root = records[0]
    assert root.mounted_on == "/"
    assert root.use_pct == 21
    assert root.size_kb == 480589824


def test_full_filesystem_flagged_critical():
    report = collect(df_text=_read("df_full.txt"))
    crit = [a for a in report.alerts
            if a.kind == "filesystem" and a.severity == "critical"]
    assert len(crit) == 1
    assert crit[0].target == "/"
    assert crit[0].use_pct == 97
    assert crit[0].use_pct >= CRIT_PCT
    warn = [a for a in report.alerts if a.severity == "warning"]
    assert len(warn) == 1 and warn[0].target == "/data"
    assert warn[0].use_pct >= WARN_PCT


def test_inode_exhaustion_flagged():
    report = collect(inode_text=_read("df_inodes_exhausted.txt"))
    crit = [a for a in report.alerts if a.kind == "inode"]
    assert len(crit) == 1
    assert crit[0].severity == "critical"
    assert crit[0].use_pct == 100
    root = report.inodes[0]
    assert root.ifree == 0 and root.iused == root.inodes


def test_parse_inodes_healthy():
    records, skipped = parse_df_inodes(_read("df_inodes_healthy.txt"))
    assert skipped == 0 and len(records) == 1
    assert records[0].iuse_pct == 2


def test_healthy_yields_no_alerts():
    report = collect(df_text=_read("df_healthy.txt"),
                     inode_text=_read("df_inodes_healthy.txt"),
                     mounts_text=_read("proc_mounts.txt"),
                     net_text=_read("proc_net_dev.txt"))
    assert report.alerts == []


def test_parse_mounts():
    records, skipped = parse_mounts(_read("proc_mounts.txt"))
    assert skipped == 0 and len(records) == 4
    root = records[1]
    assert root.device == "/dev/sda2" and root.mountpoint == "/"
    assert root.fstype == "ext4" and "rw" in root.options
    assert root.passno == 1


def test_parse_net_dev():
    records, skipped = parse_net_dev(_read("proc_net_dev.txt"))
    assert skipped == 0 and len(records) == 2
    eth0 = [r for r in records if r.iface == "eth0"][0]
    assert eth0.rx_bytes == 987654321
    assert eth0.rx_errors == 12 and eth0.rx_drop == 34
    assert eth0.tx_bytes == 555444333 and eth0.tx_errors == 2


def test_malformed_input_skipped_and_counted():
    records, skipped = parse_df(_read("malformed.txt"))
    assert len(records) == 1
    assert records[0].mounted_on == "/ok"
    assert skipped == 3


def test_malformed_mounts_and_net_never_crash():
    mounts, m_skip = parse_mounts("bad line\n/dev/x /y ext4 rw 0 1\n")
    assert len(mounts) == 1 and m_skip == 1
    ifaces, n_skip = parse_net_dev("no colon here\neth9: 1 2 3\n")
    assert ifaces == [] and n_skip == 2
    assert parse_df("") == ([], 0)
    assert parse_mounts("") == ([], 0)


def test_collect_full_report_counts_skipped():
    report = collect(df_text=_read("malformed.txt"),
                     mounts_text=_read("proc_mounts.txt"),
                     net_text=_read("proc_net_dev.txt"))
    assert report.skipped["df"] == 3
    assert len(report.mounts) == 4
    assert len(report.interfaces) == 2
    assert report.schema_version == "0.1"
