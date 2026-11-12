# SPDX-License-Identifier: GPL-2.0-only
"""Slice D3 probe: boot live guest, inventory install tools/apt road."""
from __future__ import annotations
import hashlib, json, os, re, shutil, signal, socket, subprocess, sys, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from lab.guest_access import GuestAccess, build_qemu_argv, parse_serial_log
SEAT = Path.home() / "lifthrasir-forge"
LAB = Path("/mnt/vault/lifthrasir-lab")
ISO = LAB / "kubuntu-24.04.5-desktop-amd64.iso"
PIN = "ae59e59c54337bcd8f8e60825b4a3f58797121ae0e89855524ffc92b8075c1d6"
EVID = LAB / "evidence"
KERNEL, INITRD = LAB / "casper-vmlinuz", LAB / "casper-initrd"
TARGET = LAB / "install-target.qcow2"
VARS = LAB / "OVMF_VARS-D3P.fd"
SER_SOCK, SER_LOG = LAB / "serial-D3P.sock", LAB / "serial-D3P.log"
QGA_SOCK, QMP_SOCK = LAB / "qga-D3P.sock", LAB / "qmp-D3P.sock"
PIDFILE = LAB / "qemu-D3P.pid"
def log(m): print(f"[{time.strftime('%H:%M:%S')}] {m}", flush=True)
def sha(p):
    h = hashlib.sha256()
    with p.open("rb") as f:
        for c in iter(lambda: f.read(1 << 22), b""): h.update(c)
    return h.hexdigest()
class Serial:
    def __init__(self, sp):
        self.s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.s.settimeout(5); self.s.connect(str(sp)); self.s.setblocking(False); self.buf = ""
    def drain(self, dur):
        end = time.time() + dur
        while time.time() < end:
            try:
                d = self.s.recv(65536)
                if d: self.buf += d.decode(errors="replace")
            except BlockingIOError: time.sleep(0.2)
            except OSError: break
    def send(self, line): self.s.sendall((line + "\n").encode())
    def wait_for(self, marker, timeout_s):
        end = time.time() + timeout_s
        while time.time() < end:
            if marker in self.buf: return True
            self.drain(2)
        return marker in self.buf
    def close(self):
        try: self.s.close()
        except OSError: pass
def stop_vm(pid):
    if Path(f"/proc/{pid}").exists():
        os.kill(pid, signal.SIGTERM)
        for _ in range(30):
            if not Path(f"/proc/{pid}").exists(): break
            time.sleep(0.5)
    return not Path(f"/proc/{pid}").exists()
PROBE = (
 "echo D3P_BEGIN$((1+1)); id; sudo -n id; "
 "for t in sfdisk parted sgdisk mkfs.vfat mkfs.ext4 unsquashfs rsync grub-install grub-mkconfig update-grub update-initramfs chroot apt-get systemctl useradd locale-gen systemd-machine-id-setup; do printf %s= $t; command -v $t || echo MISSING; done; "
 "ls -lh /cdrom/casper/filesystem.squashfs; ls /cdrom/pool/main/o/openssh/ 2>&1; ls /cdrom/pool/main/q/qemu/ 2>&1 | head; ls /cdrom/pool/main/s/spice-vdagent/ 2>&1; "
 "grep -R . /etc/apt/sources.list /etc/apt/sources.list.d/ 2>/dev/null | head -n 30; "
 "timeout 6 bash -c 'echo >/dev/tcp/archive.ubuntu.com/80' 2>/dev/null && echo NET_OK || echo NET_FAIL; "
 "lsblk -o NAME,SIZE,TYPE; df -h / /cdrom 2>/dev/null; echo D3P_END$((1+1))")
def main():
    EVID.mkdir(parents=True, exist_ok=True)
    ev = {"slice": "activation-phase1-D3-probe"}
    ev["iso_sha256_ok"] = sha(ISO) == PIN
    if not ev["iso_sha256_ok"]:
        ev["error"] = "ISO sha mismatch"; print("D3P_INCOMPLETE"); return 1
    VARS.unlink(missing_ok=True); shutil.copyfile("/usr/share/OVMF/OVMF_VARS_4M.fd", VARS)
    for p in (SER_SOCK, QGA_SOCK, QMP_SOCK, SER_LOG, PIDFILE): p.unlink(missing_ok=True)
    acc = GuestAccess(kernel=KERNEL, initrd=INITRD, iso=ISO, disk=TARGET, serial_sock=SER_SOCK, serial_log=SER_LOG, qga_sock=QGA_SOCK, qmp_sock=QMP_SOCK, pidfile=PIDFILE, vars_fd=VARS)
    argv = build_qemu_argv(acc); ev["qemu_argv"] = argv
    proc = subprocess.Popen(["nice", "-n", "10", *argv], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    ev["launcher_rc"] = proc.wait(timeout=30); pid = int(PIDFILE.read_text().strip()); ev["qemu_pid"] = pid
    log(f"probe boot pid={pid}")
    deadline = time.time() + 300; markers = {}
    while time.time() < deadline:
        if SER_LOG.exists():
            markers = parse_serial_log(SER_LOG.read_text(errors="replace"))
            if markers.get("login_prompt"): break
        time.sleep(5)
    ev["boot_markers"] = markers
    if not markers.get("login_prompt"):
        ev["error"] = "no login prompt"; ev["stopped"] = stop_vm(pid)
        (EVID / "sliceD3-probe.json").write_text(json.dumps(ev, indent=2)); print("D3P_INCOMPLETE"); return 2
    ser = Serial(SER_SOCK)
    try:
        ser.drain(2)
        for line in ("", "kubuntu", ""):
            ser.send(line); ser.drain(3)
        ser.send(PROBE)
        ok = ser.wait_for("D3P_END2", 180)
        ser.drain(3)
        blocks = re.findall(r"D3P_BEGIN2(.*?)D3P_END2", ser.buf, re.S)
        ev["probe_block"] = (blocks[-1][-9000:] if blocks else ser.buf[-9000:])
        ev["probe_complete"] = bool(blocks) and ok
        ser.send("sudo poweroff"); ser.drain(3)
    finally:
        ser.close()
    for _ in range(24):
        if not Path(f"/proc/{pid}").exists(): break
        time.sleep(5)
    ev["stopped"] = True if not Path(f"/proc/{pid}").exists() else stop_vm(pid)
    p = EVID / "sliceD3-probe.json"; p.write_text(json.dumps(ev, indent=2))
    shutil.copyfile(p, SEAT / "lab" / "evidence" / "sliceD3-probe.json")
    print(f"EVIDENCE={p}"); print("D3P_OK" if ev.get("probe_complete") else "D3P_INCOMPLETE")
    return 0 if ev.get("probe_complete") else 2
if __name__ == "__main__": raise SystemExit(main())
