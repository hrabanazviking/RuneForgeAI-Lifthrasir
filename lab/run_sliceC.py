# SPDX-License-Identifier: GPL-2.0-only
"""Activation Phase 1, slice C driver: prove the guest access path.

Real boot of the pinned Kubuntu live image via direct kernel boot
(kernel/initrd extracted from the ISO with isoinfo), serial console
over a QEMU chardev socket, QGA channel wired. Polls the serial log
for a login prompt, then tries an interactive serial login as the
casper live user and runs marker commands. QGA is probed and its
result recorded honestly (the live image ships no guest agent --
see lab/guest_access.py). Writes sliceC-evidence.json on the vault;
prints SLICEC_OK (shell proven) or SLICEC_LOGIN (booted to login)
or SLICEC_INCOMPLETE as the last line. Run detached; ~5 min max.
"""
from __future__ import annotations

import hashlib
import json
import os
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from lab.guest_access import (GuestAccess, access_verdict,  # noqa: E402
                              build_qemu_argv, parse_serial_log)
from lab.real_runner import SubprocessRunner  # noqa: E402
from lab.vm_workflow import ImageReference, VMDefinition, VMWorkflow  # noqa: E402

LAB = Path("/mnt/vault/lifthrasir-lab")
ISO = LAB / "kubuntu-24.04.5-desktop-amd64.iso"
PIN = "ae59e59c54337bcd8f8e60825b4a3f58797121ae0e89855524ffc92b8075c1d6"
GOLDEN = LAB / "golden.qcow2"
DISK = LAB / "guests" / "lab-guest-1.qcow2"
EVID = LAB / "evidence"
KERNEL = LAB / "casper-vmlinuz"
INITRD = LAB / "casper-initrd"
SER_SOCK, SER_LOG = LAB / "serial-C.sock", LAB / "serial-C.log"
QGA_SOCK, QMP_SOCK = LAB / "qga-C.sock", LAB / "qmp-C.sock"
PIDFILE = LAB / "qemu-C.pid"
VARS = LAB / "OVMF_VARS.fd"
GOLDEN_SHA = "a5d8572769a1d147d2a29e2cc78de548010c2f97c6a4c40c1280f8f7061e99ac"


def sha256_stream(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 22), b""):
            h.update(chunk)
    return h.hexdigest()


def extract(member: str, dest: Path) -> int:
    if dest.exists() and dest.stat().st_size > 0:
        return 0
    with dest.open("wb") as out:
        return subprocess.run(
            ["isoinfo", "-R", "-x", member, "-i", str(ISO)],
            stdout=out, stderr=subprocess.DEVNULL).returncode


def serial_session(cmds: list[str], wait_s: float = 6.0) -> str:
    """Connect to the serial socket, run cmds, return transcript."""
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


def qga_probe() -> dict:
    try:
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.settimeout(5)
        s.connect(str(QGA_SOCK))
        s.sendall(b'{"execute":"guest-ping"}\n')
        data = s.recv(4096)
        s.close()
        return {"answered": bool(data), "reply": data.decode(errors="replace")[:200]}
    except Exception as e:
        return {"answered": False, "error": type(e).__name__}


def main() -> int:
    EVID.mkdir(parents=True, exist_ok=True)
    DISK.parent.mkdir(parents=True, exist_ok=True)
    ev: dict = {"slice": "activation-phase1-C", "lab_root": str(LAB)}
    ev["iso_sha256_ok"] = sha256_stream(ISO) == PIN
    if not ev["iso_sha256_ok"]:
        ev["error"] = "ISO sha mismatch; refusing"
        (EVID / "sliceC-evidence.json").write_text(json.dumps(ev, indent=2))
        print("SLICEC_INCOMPLETE")
        return 1
    ev["extract_kernel_rc"] = extract("/casper/vmlinuz", KERNEL)
    ev["extract_initrd_rc"] = extract("/casper/initrd", INITRD)
    ev["kernel_bytes"] = KERNEL.stat().st_size
    ev["initrd_bytes"] = INITRD.stat().st_size
    runner = SubprocessRunner(timeout_s=300)
    vm = VMDefinition(name="lab-guest-1",
                      image=ImageReference("kubuntu-24.04.5-golden", GOLDEN_SHA),
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
    # Poll the serial log up to 300 s for a login prompt.
    markers: dict = {}
    deadline = time.time() + 300
    while time.time() < deadline:
        if SER_LOG.exists():
            markers = parse_serial_log(SER_LOG.read_text(errors="replace"))
            if markers["login_prompt"]:
                break
        if not Path(f"/proc/{pid}").exists():
            break
        time.sleep(5)
    ev["boot_markers"] = markers
    ev["boot_verdict"] = access_verdict(markers)
    ev["qga_probe"] = qga_probe()
    ev["serial_login_attempted"] = False
    if markers.get("login_prompt"):
        ev["serial_login_attempted"] = True
        transcript = serial_session(
            ["", "kubuntu", "",
             "id; uname -r; echo LIFTHRASIR_GUEST_OK"], wait_s=7.0)
        ev["serial_transcript_tail"] = transcript[-1500:]
        if SER_LOG.exists():
            markers = parse_serial_log(SER_LOG.read_text(errors="replace"))
        ev["final_markers"] = markers
        ev["final_verdict"] = access_verdict(markers)
    else:
        ev["final_verdict"] = ev["boot_verdict"]
    if Path(f"/proc/{pid}").exists():
        os.kill(pid, signal.SIGTERM)
        for _ in range(20):
            if not Path(f"/proc/{pid}").exists():
                break
            time.sleep(0.5)
    ev["stopped"] = not Path(f"/proc/{pid}").exists()
    ev["serial_log_bytes"] = SER_LOG.stat().st_size if SER_LOG.exists() else 0
    wf.delete()
    ev["overlay_deleted"] = not DISK.exists()
    ev["phase1_exit_met"] = False
    ev["limitations"] = ("Live-session access only; installed-system "
                         "golden (Calamares unattended) is slice D. "
                         "QGA/SSH need the installed package set.")
    p = EVID / "sliceC-evidence.json"
    p.write_text(json.dumps(ev, indent=2))
    print(f"EVIDENCE={p}")
    v = ev["final_verdict"]
    print("SLICEC_OK" if v == "shell"
          else "SLICEC_LOGIN" if v == "booted_to_login"
          else "SLICEC_INCOMPLETE")
    return 0 if v in ("shell", "booted_to_login") else 2


if __name__ == "__main__":
    raise SystemExit(main())
