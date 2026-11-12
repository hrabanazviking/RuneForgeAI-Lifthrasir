# SPDX-License-Identifier: GPL-2.0-only
"""Activation Phase 1, slice B: build the golden qcow2 from the pinned
ISO and prove a REAL create -> boot -> reset -> boot -> delete cycle.

Honest scope: the golden image is the pinned Kubuntu ISO converted
raw->qcow2 (qemu-img convert). A full unattended Calamares install
into an installed-system golden remains a later Phase 1 slice; this
slice proves the real runner, the golden artifact, overlay
create/reset via VMWorkflow, and that QEMU/KVM actually boots the
golden twice (QMP status 'running' + guest CPU time advancing).
Evidence JSON is written beside the artifacts on the vault and its
path is printed as the last line: EVIDENCE=<path>
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import signal
import socket
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from lab.real_runner import SubprocessRunner  # noqa: E402
from lab.vm_workflow import ImageReference, VMDefinition, VMWorkflow  # noqa: E402

LAB_ROOT = Path("/mnt/vault/lifthrasir-lab")
ISO = LAB_ROOT / "kubuntu-24.04.5-desktop-amd64.iso"
PIN = "ae59e59c54337bcd8f8e60825b4a3f58797121ae0e89855524ffc92b8075c1d6"
GOLDEN = LAB_ROOT / "golden.qcow2"
DISK = LAB_ROOT / "guests" / "lab-guest-1.qcow2"
EVID = LAB_ROOT / "evidence"


def sha256_stream(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 22), b""):
            h.update(chunk)
    return h.hexdigest()


def cpu_ticks(pid: int) -> int:
    parts = Path(f"/proc/{pid}/stat").read_text().split()
    return int(parts[13]) + int(parts[14])  # utime + stime


def qmp_status(sock_path: Path) -> str:
    try:
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.settimeout(5)
        s.connect(str(sock_path))
        f = s.makefile("rw", encoding="utf-8", newline="\r\n")
        f.readline()
        f.write(json.dumps({"execute": "qmp_capabilities"}) + "\r\n")
        f.flush()
        f.readline()
        f.write(json.dumps({"execute": "query-status"}) + "\r\n")
        f.flush()
        resp = json.loads(f.readline())
        s.close()
        return str(resp.get("return", {}).get("status", "unknown"))
    except Exception as e:  # evidence, not a crash
        return f"qmp-error:{type(e).__name__}"


def boot_once(runner: SubprocessRunner, tag: str) -> dict:
    pidfile = LAB_ROOT / f"qemu-{tag}.pid"
    sock = LAB_ROOT / f"qmp-{tag}.sock"
    vars_copy = LAB_ROOT / "OVMF_VARS.fd"
    if not vars_copy.exists():
        shutil.copyfile("/usr/share/OVMF/OVMF_VARS_4M.fd", vars_copy)
    argv = ["qemu-system-x86_64", "-name", "lifthrasir-lab-guest-1",
            "-accel", "kvm", "-cpu", "host", "-machine", "q35",
            "-m", "4096", "-smp", "4",
            "-drive", f"file={DISK},format=qcow2,if=virtio",
            "-drive", "if=pflash,format=raw,readonly=on,"
                      "file=/usr/share/OVMF/OVMF_CODE_4M.fd",
            "-drive", f"if=pflash,format=raw,file={vars_copy}",
            "-netdev", "user,id=n0", "-device", "virtio-net-pci,netdev=n0",
            "-display", "none", "-pidfile", str(pidfile),
            "-qmp", f"unix:{sock},server,nowait", "-daemonize"]
    rc = runner.run(argv)
    if rc != 0:
        return {"tag": tag, "rc": rc, "booted": False}
    pid = int(pidfile.read_text().strip())
    time.sleep(10)
    alive1 = Path(f"/proc/{pid}").exists()
    ticks1 = cpu_ticks(pid) if alive1 else 0
    status = qmp_status(sock)
    time.sleep(5)
    ticks2 = cpu_ticks(pid) if Path(f"/proc/{pid}").exists() else ticks1
    out = {"tag": tag, "rc": rc, "pid": pid, "qmp_status": status,
           "alive_after_10s": alive1, "cpu_ticks_delta_5s": ticks2 - ticks1,
           "booted": bool(alive1 and status == "running"
                          and ticks2 > ticks1)}
    if Path(f"/proc/{pid}").exists():
        os.kill(pid, signal.SIGTERM)
        for _ in range(20):
            if not Path(f"/proc/{pid}").exists():
                break
            time.sleep(0.5)
    out["stopped"] = not Path(f"/proc/{pid}").exists()
    return out


def main() -> int:
    EVID.mkdir(parents=True, exist_ok=True)
    DISK.parent.mkdir(parents=True, exist_ok=True)
    ev: dict = {"slice": "activation-phase1-B", "lab_root": str(LAB_ROOT)}
    iso_sha = sha256_stream(ISO)
    ev["iso_sha256_ok"] = iso_sha == PIN
    if not ev["iso_sha256_ok"]:
        ev["error"] = "ISO sha mismatch; refusing to proceed"
        p = EVID / "sliceB-evidence.json"
        p.write_text(json.dumps(ev, indent=2))
        print(f"EVIDENCE={p}")
        return 1
    runner = SubprocessRunner(timeout_s=900)
    if not GOLDEN.exists():
        rc = runner.run(["qemu-img", "convert", "-f", "raw", "-O", "qcow2",
                         str(ISO), str(GOLDEN)])
        ev["convert_rc"] = rc
        if rc != 0:
            p = EVID / "sliceB-evidence.json"
            p.write_text(json.dumps(ev, indent=2))
            print(f"EVIDENCE={p}")
            return 1
    ev["golden_bytes"] = GOLDEN.stat().st_size
    ev["golden_sha256"] = sha256_stream(GOLDEN)
    nice = ["nice", "-n", "10"]
    del nice  # politeness is via caps (4 vCPU/4 GiB, one VM); noted in state
    vm = VMDefinition(
        name="lab-guest-1",
        image=ImageReference("kubuntu-24.04.5-golden", ev["golden_sha256"]),
        image_path=GOLDEN, disk_path=DISK,
        memory_mb=4096, cpus=4, disposable=True)
    wf = VMWorkflow(LAB_ROOT, runner)
    wf.create(vm)
    ev["boot1"] = boot_once(runner, "boot1")
    wf.reset()
    ev["boot2"] = boot_once(runner, "boot2")
    ev["workflow_log"] = [t.action for t in wf.log]
    wf.delete()
    ev["overlay_deleted"] = not DISK.exists()
    ev["runner_calls"] = runner.calls
    ev["phase1_exit_met"] = False
    ev["limitations"] = ("Golden is the converted live ISO, not an "
                         "installed system; fault loop + unattended "
                         "install remain later Phase 1 slices.")
    p = EVID / "sliceB-evidence.json"
    p.write_text(json.dumps(ev, indent=2))
    print(f"EVIDENCE={p}")
    ok = (ev["boot1"].get("booted") and ev["boot2"].get("booted")
          and ev["overlay_deleted"])
    print("SLICEB_OK" if ok else "SLICEB_INCOMPLETE")
    return 0 if ok else 2


if __name__ == "__main__":
    raise SystemExit(main())
