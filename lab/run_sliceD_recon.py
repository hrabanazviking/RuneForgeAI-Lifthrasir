# SPDX-License-Identifier: GPL-2.0-only
"""Activation Phase 1, slice D recon driver.

Boots the pinned live guest exactly as slice C did, logs in over
the serial console, and dumps the REAL Calamares layout from inside
the guest (settings.conf, module dirs, version, block devices)
between LIF_RECON_BEGIN / LIF_RECON_END markers. The serial log is
the evidence; a summary JSON is written to the vault evidence dir.
No install is attempted. Prints SLICED_RECON_OK / _INCOMPLETE.
Run detached; ~6 min max.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from lab.guest_access import (GuestAccess, access_verdict,
                              build_qemu_argv, parse_serial_log)
from lab.real_runner import SubprocessRunner
from lab.vm_workflow import ImageReference, VMDefinition, VMWorkflow

LAB = Path("/mnt/vault/lifthrasir-lab")
ISO = LAB / "kubuntu-24.04.5-desktop-amd64.iso"
PIN = "ae59e59c54337bcd8f8e60825b4a3f58797121ae0e89855524ffc92b8075c1d6"
GOLDEN = LAB / "golden.qcow2"
DISK = LAB / "guests" / "lab-guest-1.qcow2"
EVID = LAB / "evidence"
KERNEL = LAB / "casper-vmlinuz"
INITRD = LAB / "casper-initrd"
SER_SOCK, SER_LOG = LAB / "serial-D.sock", LAB / "serial-D.log"
QGA_SOCK, QMP_SOCK = LAB / "qga-D.sock", LAB / "qmp-D.sock"
PIDFILE = LAB / "qemu-D.pid"
VARS = LAB / "OVMF_VARS.fd"
GOLDEN_SHA = "a5d8572769a1d147d2a29e2cc78de548010c2f97c6a4c40c1280f8f7061e99ac"
RECON_CMD = (
    "echo LIF_RECON_BEGIN; calamares --version 2>&1 | head -2; "
    "echo ---SETTINGS---; cat /etc/calamares/settings.conf 2>&1; "
    "echo ---ETC---; ls /etc/calamares/ 2>&1; "
    "echo ---MODDIRS---; ls /usr/lib/calamares/modules/ 2>&1; "
    "ls /usr/share/calamares/modules/ 2>&1; "
    "ls /etc/calamares/modules/ 2>&1; "
    "echo ---LSBLK---; lsblk -o NAME,SIZE,TYPE 2>&1; "
    "echo LIF_RECON_END; echo LIFTHRASIR_GUEST_OK")


def sha256_stream(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 22), b""):
            h.update(chunk)
    return h.hexdigest()


def serial_session(cmds: list[str], wait_s: float = 6.0) -> str:
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    s.settimeout(3)
    s.connect(str(SER_SOCK))
    s.setblocking(False)
    buf = b""

    def drain(dur: float) -> None:
        nonlocal buf
        end = time.time() + dur
        while time.time() < end:
            try:
                data = s.recv(65536)
                if data:
                    buf += data
            except BlockingIOError:
                time.sleep(0.2)
            except OSError:
                break
    drain(2)
    for c in cmds:
        s.sendall((c + "\n").encode())
        drain(wait_s)
    s.close()
    return buf.decode(errors="replace")


def main() -> int:
    EVID.mkdir(parents=True, exist_ok=True)
    DISK.parent.mkdir(parents=True, exist_ok=True)
    ev: dict = {"slice": "activation-phase1-D-recon"}
    ev["iso_sha256_ok"] = sha256_stream(ISO) == PIN
    if not ev["iso_sha256_ok"]:
        ev["error"] = "ISO sha mismatch; refusing"
        (EVID / "sliceD-recon.json").write_text(json.dumps(ev, indent=2))
        print("SLICED_RECON_INCOMPLETE")
        return 1
    runner = SubprocessRunner(timeout_s=300)
    vm = VMDefinition(name="lab-guest-1",
                      image=ImageReference("kubuntu-24.04.5-golden",
                                           GOLDEN_SHA),
                      image_path=GOLDEN, disk_path=DISK,
                      memory_mb=4096, cpus=4, disposable=True)
    wf = VMWorkflow(LAB, runner)
    wf.create(vm)
    for p in (SER_SOCK, QGA_SOCK, QMP_SOCK, SER_LOG, PIDFILE):
        p.unlink(missing_ok=True)
    acc = GuestAccess(kernel=KERNEL, initrd=INITRD, iso=ISO, disk=DISK,
                      serial_sock=SER_SOCK, serial_log=SER_LOG,
                      qga_sock=QGA_SOCK, qmp_sock=QMP_SOCK,
                      pidfile=PIDFILE, vars_fd=VARS)
    argv = build_qemu_argv(acc)
    ev["qemu_argv"] = argv
    proc = subprocess.Popen(["nice", "-n", "10", *argv],
                            stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL)
    ev["launcher_rc"] = proc.wait(timeout=30)
    pid = int(PIDFILE.read_text().strip())
    ev["qemu_pid"] = pid
    markers: dict = {}
    deadline = time.time() + 300
    while time.time() < deadline:
        if SER_LOG.exists():
            markers = parse_serial_log(
                SER_LOG.read_text(errors="replace"))
            if markers["login_prompt"]:
                break
        if not Path(f"/proc/{pid}").exists():
            break
        time.sleep(5)
    ev["boot_markers"] = markers
    ev["recon_done"] = False
    if markers.get("login_prompt"):
        serial_session(["", "kubuntu", "", RECON_CMD], wait_s=8.0)
        # give the dump time to flush to the serial log
        for _ in range(12):
            time.sleep(5)
            txt = SER_LOG.read_text(errors="replace")
            if "LIF_RECON_END" in txt:
                break
        txt = SER_LOG.read_text(errors="replace")
        m = re.search(r"LIF_RECON_BEGIN(.*?)LIF_RECON_END", txt, re.S)
        ev["recon_block"] = (m.group(1)[-6000:] if m else "")
        ev["recon_done"] = bool(m)
        mods = set()
        for line in ev["recon_block"].splitlines():
            w = line.strip()
            if w and re.fullmatch(r"[a-z0-9_-]+", w) and len(w) < 40:
                mods.add(w)
        ev["candidate_names"] = sorted(mods)
    if Path(f"/proc/{pid}").exists():
        os.kill(pid, signal.SIGTERM)
        for _ in range(20):
            if not Path(f"/proc/{pid}").exists():
                break
            time.sleep(0.5)
    ev["stopped"] = not Path(f"/proc/{pid}").exists()
    wf.delete()
    ev["overlay_deleted"] = not DISK.exists()
    ev["phase1_exit_met"] = False
    p = EVID / "sliceD-recon.json"
    p.write_text(json.dumps(ev, indent=2))
    print(f"EVIDENCE={p}")
    print("SLICED_RECON_OK" if ev["recon_done"]
          else "SLICED_RECON_INCOMPLETE")
    return 0 if ev["recon_done"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
