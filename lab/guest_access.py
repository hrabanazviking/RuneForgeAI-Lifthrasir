# SPDX-License-Identifier: GPL-2.0-only
"""Activation Phase 1, slice C: guest access path for the lab.

Slice B proved the golden (converted live ISO) boots under QEMU/KVM
but offered NO way to talk to the guest: the workflow builder has no
console, no agent channel, no network service. This module defines
the access path used from slice C on:

* DIRECT kernel boot (-kernel/-initrd/-append extracted from the
  pinned ISO) so the kernel command line is ours: casper live boot
  plus ``console=ttyS0`` -- systemd's getty generator then spawns
  serial-getty@ttyS0 in the guest, giving a login prompt on the
  serial line without touching the ISO.
* Serial console as a QEMU chardev SOCKET (server, wait=off) with a
  logfile: the driver can connect, log in, and run commands, while
  the logfile captures the full boot transcript as evidence even if
  no client is attached.
* QEMU guest-agent channel (virtio-serial, org.qemu.guest_agent.0)
  wired the same way. HONEST FACT from the ISO manifest (checked
  2026-11-12): the live image ships calamares + openssh-CLIENT only
  -- no qemu-guest-agent, no openssh-server -- so QGA/SSH cannot
  answer in the live session. Both packages ARE the pinned lab
  package set (lab/images/.../packages.txt) for the installed
  golden; the channel is built now so it lights up there.

Everything here is pure argv construction + log parsing; the real
boot lives in lab/run_sliceC.py and its evidence pack.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

APPEND = ("boot=casper console=ttyS0,115200n8 console=tty0 "
          "net.ifnames=0 ---")


@dataclass(frozen=True)
class GuestAccess:
    kernel: Path
    initrd: Path
    iso: Path
    disk: Path
    serial_sock: Path
    serial_log: Path
    qga_sock: Path
    qmp_sock: Path
    pidfile: Path
    vars_fd: Path
    memory_mb: int = 4096
    cpus: int = 4


def build_qemu_argv(a: GuestAccess) -> list[str]:
    """Exact QEMU argv for a direct-kernel live boot with access."""
    if not (1 <= a.cpus <= 8):
        raise ValueError(f"cpu cap exceeded: {a.cpus}")
    if not (128 <= a.memory_mb <= 16384):
        raise ValueError(f"memory cap exceeded: {a.memory_mb}")
    return [
        "qemu-system-x86_64", "-name", "lifthrasir-lab-guest-1",
        "-accel", "kvm", "-cpu", "host", "-machine", "q35",
        "-m", str(a.memory_mb), "-smp", str(a.cpus),
        "-kernel", str(a.kernel), "-initrd", str(a.initrd),
        "-append", APPEND,
        "-drive", f"file={a.iso},format=raw,if=none,id=cd0,readonly=on",
        "-device", "ide-cd,drive=cd0",
        "-drive", f"file={a.disk},format=qcow2,if=virtio",
        "-drive", "if=pflash,format=raw,readonly=on,"
                  "file=/usr/share/OVMF/OVMF_CODE_4M.fd",
        "-drive", f"if=pflash,format=raw,file={a.vars_fd}",
        "-chardev", f"socket,id=ser0,path={a.serial_sock},"
                    f"server=on,wait=off,logfile={a.serial_log}",
        "-serial", "chardev:ser0",
        "-chardev", f"socket,id=qga0,path={a.qga_sock},server=on,wait=off",
        "-device", "virtio-serial-pci,id=virtio-serial0",
        "-device", "virtserialport,chardev=qga0,"
                   "name=org.qemu.guest_agent.0",
        "-netdev", "user,id=n0", "-device", "virtio-net-pci,netdev=n0",
        "-display", "none", "-pidfile", str(a.pidfile),
        "-qmp", f"unix:{a.qmp_sock},server,nowait", "-daemonize"]


def parse_serial_log(text: str) -> dict:
    """Grade a serial boot transcript (pure; unit-tested)."""
    low = text.lower()
    return {
        "kernel_started": "linux version" in low,
        "casper_live": "casper" in low,
        "systemd_reached": ("systemd" in low
                            and ("reached target" in low
                                 or "starting" in low)),
        "login_prompt": "login:" in low,
        "shell_proven": "lifthrasir_guest_ok" in low,
    }


def access_verdict(markers: dict) -> str:
    """booted_to_login | shell | partial | none -- honest grading."""
    if markers.get("shell_proven"):
        return "shell"
    if markers.get("login_prompt") and markers.get("kernel_started"):
        return "booted_to_login"
    if markers.get("kernel_started"):
        return "partial"
    return "none"
