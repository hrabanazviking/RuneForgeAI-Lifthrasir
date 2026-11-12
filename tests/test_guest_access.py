# SPDX-License-Identifier: GPL-2.0-only
"""Tests for lab/guest_access.py (Activation Phase 1, slice C)."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lab.guest_access import (GuestAccess, access_verdict,
                              build_qemu_argv, parse_serial_log)


def _acc(**kw):
    base = dict(kernel=Path("/lab/vmlinuz"), initrd=Path("/lab/initrd"),
                iso=Path("/lab/iso"), disk=Path("/lab/d.qcow2"),
                serial_sock=Path("/lab/ser.sock"),
                serial_log=Path("/lab/ser.log"),
                qga_sock=Path("/lab/qga.sock"),
                qmp_sock=Path("/lab/qmp.sock"),
                pidfile=Path("/lab/qemu.pid"),
                vars_fd=Path("/lab/VARS.fd"))
    base.update(kw)
    return GuestAccess(**base)


def test_argv_has_serial_qga_and_direct_kernel():
    argv = build_qemu_argv(_acc())
    joined = " ".join(argv)
    assert "-kernel" in argv and "-initrd" in argv
    assert "console=ttyS0,115200n8" in joined
    assert "boot=casper" in joined
    assert "org.qemu.guest_agent.0" in joined
    assert "logfile=/lab/ser.log" in joined
    assert "-display" in argv


def test_caps_refused():
    with pytest.raises(ValueError):
        build_qemu_argv(_acc(cpus=99))
    with pytest.raises(ValueError):
        build_qemu_argv(_acc(memory_mb=999999))


def test_parse_full_transcript_is_shell():
    text = ("[0.0] Linux version 6.8.0-87-generic casper\n"
            "systemd[1]: Reached target multi-user.target\n"
            "kubuntu login: kubuntu\nLIFTHRASIR_GUEST_OK\n")
    m = parse_serial_log(text)
    assert m["kernel_started"] and m["login_prompt"]
    assert access_verdict(m) == "shell"


def test_parse_login_only_and_empty():
    m = parse_serial_log("Linux version 6.8\nfoo login: ")
    assert access_verdict(m) == "booted_to_login"
    assert access_verdict(parse_serial_log("")) == "none"
    assert access_verdict(parse_serial_log("Linux version x")) == "partial"
