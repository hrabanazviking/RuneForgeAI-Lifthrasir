# SPDX-License-Identifier: GPL-2.0-only
"""Activation Phase 1, slice D3 driver: scripted manual install.
Live boot (+config ISO carrying d3-install.sh) -> root install
script (partition/unpack/chroot/GRUB) -> poweroff -> UEFI boot of
installed target -> verify serial shell, QGA, sshd -> golden copy.
Evidence JSON on the vault. Detached; ~75 min max.
"""
from __future__ import annotations
import hashlib, json, os, re, shutil, signal, socket, subprocess, sys, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from lab.guest_access import GuestAccess, build_qemu_argv, parse_serial_log
from lab.manual_install import full_install_script
from lab.real_runner import SubprocessRunner
SEAT = Path.home() / "lifthrasir-forge"
LAB = Path("/mnt/vault/lifthrasir-lab")
ISO = LAB / "kubuntu-24.04.5-desktop-amd64.iso"
PIN = "ae59e59c54337bcd8f8e60825b4a3f58797121ae0e89855524ffc92b8075c1d6"
EVID = LAB / "evidence"
KERNEL, INITRD = LAB / "casper-vmlinuz", LAB / "casper-initrd"
TARGET = LAB / "install-target.qcow2"
GOLDEN_INST = LAB / "golden-installed.qcow2"
CFGISO = LAB / "config-d3.iso"
STAGE = SEAT / "lab" / "config-stage-d3"
VARS = LAB / "OVMF_VARS-D3.fd"
SER_SOCK, SER_LOG = LAB / "serial-D3.sock", LAB / "serial-D3.log"
QGA_SOCK, QMP_SOCK = LAB / "qga-D3.sock", LAB / "qmp-D3.sock"
PIDFILE = LAB / "qemu-D3.pid"
SER2_SOCK, SER2_LOG = LAB / "serial-D3b.sock", LAB / "serial-D3b.log"
QGA2_SOCK, QMP2_SOCK = LAB / "qga-D3b.sock", LAB / "qmp-D3b.sock"
PID2FILE = LAB / "qemu-D3b.pid"
SSH_FWD_PORT = 2224
INSTALL_BUDGET_S = 45 * 60
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
def wait_login(logpath, pid, timeout_s):
    markers = {}; deadline = time.time() + timeout_s
    while time.time() < deadline:
        if logpath.exists():
            markers = parse_serial_log(logpath.read_text(errors="replace"))
            if markers.get("login_prompt"): break
        if not Path(f"/proc/{pid}").exists(): break
        time.sleep(5)
    return markers
def qga_ping(sock_path):
    try:
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM); s.settimeout(5)
        s.connect(str(sock_path)); s.sendall(b'{"execute": "guest-ping"}\n')
        d = s.recv(4096); s.close(); return b"return" in d
    except OSError: return False
def stage(ev):
    if STAGE.exists(): shutil.rmtree(STAGE)
    STAGE.mkdir(parents=True)
    (STAGE / "d3-install.sh").write_text(full_install_script())
    gen = subprocess.run(["genisoimage", "-o", str(CFGISO), "-V", "LIF_CONFIG", "-J", "-R", str(STAGE)], capture_output=True, text=True, timeout=120)
    ev["genisoimage_rc"] = gen.returncode
    ev["staged_files"] = ["d3-install.sh"]
    return gen.returncode == 0
def install_phase(ev):
    runner = SubprocessRunner(timeout_s=300)
    if TARGET.exists(): runner.run(["rm", "-f", str(TARGET)])
    rc = runner.run(["qemu-img", "create", "-f", "qcow2", str(TARGET), "32G"])
    ev["target_create_rc"] = rc
    if rc != 0: ev["error"] = "qemu-img create failed"; return False
    VARS.unlink(missing_ok=True); shutil.copyfile("/usr/share/OVMF/OVMF_VARS_4M.fd", VARS)
    for p in (SER_SOCK, QGA_SOCK, QMP_SOCK, SER_LOG, PIDFILE): p.unlink(missing_ok=True)
    acc = GuestAccess(kernel=KERNEL, initrd=INITRD, iso=ISO, disk=TARGET, serial_sock=SER_SOCK, serial_log=SER_LOG, qga_sock=QGA_SOCK, qmp_sock=QMP_SOCK, pidfile=PIDFILE, vars_fd=VARS)
    argv = build_qemu_argv(acc)
    idx = argv.index("-display")
    argv[idx:idx] = ["-drive", f"file={CFGISO},format=raw,if=none,id=cd1,readonly=on", "-device", "virtio-blk-pci,drive=cd1"]
    ev["qemu_argv"] = argv
    proc = subprocess.Popen(["nice", "-n", "10", *argv], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    ev["launcher_rc"] = proc.wait(timeout=30)
    if not PIDFILE.exists(): ev["error"] = "qemu launch failed"; return False
    pid = int(PIDFILE.read_text().strip()); ev["qemu_pid"] = pid
    log(f"install boot pid={pid}; waiting for login")
    markers = wait_login(SER_LOG, pid, 300); ev["boot_markers"] = markers
    if not markers.get("login_prompt"):
        ev["error"] = "no login prompt"; ev["stopped"] = stop_vm(pid); return False
    return pid
MARKERS = ["D3_PART_DONE2", "D3_FMT_DONE2", "D3_UNPACK_DONE2", "D3_FILES_DONE2", "D3_IDENT_DONE2", "D3_APT_DONE2", "D3_GRUB_DONE2", "D3_ALL_DONE2"]
def install_serial(ev, pid):
    ser = Serial(SER_SOCK)
    try:
        ser.drain(2)
        for line in ("", "kubuntu", ""):
            ser.send(line); ser.drain(3)
        ser.send("sudo mkdir -p /mnt/cfg; sudo mount /dev/disk/by-label/LIF_CONFIG /mnt/cfg && echo LIF_D3_MOUNT_OK$((1+1)) || echo LIF_D3_MOUNT_FAIL$((1+1))")
        if not ser.wait_for("LIF_D3_MOUNT_OK2", 30):
            ev["error"] = "config mount failed"; return False
        ser.buf = ""
        ser.send("cp /mnt/cfg/d3-install.sh /tmp/d3-install.sh; chmod +x /tmp/d3-install.sh; sudo nohup bash /tmp/d3-install.sh >/tmp/d3.log 2>&1 & echo LIF_D3_LAUNCHED$((1+1))")
        ser.wait_for("LIF_D3_LAUNCHED2", 30)
        log("install script launched in guest; polling")
        deadline = time.time() + INSTALL_BUDGET_S; t0 = time.time()
        ev["poll_history"] = []; ev["stall_detected"] = False
        last_sig = None; stall = 0; done = False
        while time.time() < deadline:
            time.sleep(40); ser.buf = ""
            ser.send("grep -a -o 'D3_[A-Z_]*2' /tmp/d3.log | tail -3; wc -c /tmp/d3.log; pgrep -f d3-install >/dev/null && echo D3_RUNNING$((1+1)) || echo D3_GONE$((1+1)); echo LIF_D3_STAT_END$((1+1))")
            if not ser.wait_for("LIF_D3_STAT_END2", 25):
                log("stat poll timeout"); continue
            wm = re.findall(r"(\d+)\s+/tmp/d3\.log", ser.buf); logsz = int(wm[-1]) if wm else -1
            try: tsz = TARGET.stat().st_size
            except OSError: tsz = -1
            seen = [m for m in MARKERS if m in ser.buf]
            ev["poll_history"].append([round(time.time()-t0), logsz, tsz, seen[-1] if seen else ""])
            log(f"poll log={logsz} target={tsz} last={seen[-1] if seen else '-'}")
            if "D3_ALL_DONE2" in ser.buf: done = True; break
            if "D3_GONE2" in ser.buf and not done: break
            sig = (logsz, tsz)
            stall = stall + 1 if sig == last_sig else 0; last_sig = sig
            if stall >= 8:
                ev["stall_detected"] = True; log("stall detected"); break
        ev["install_done"] = done
        ser.buf = ""
        ser.send("tail -c 9000 /tmp/d3.log; echo LIF_D3_LOG_END$((1+1))")
        ser.wait_for("LIF_D3_LOG_END2", 60); ser.drain(3)
        tail = re.findall(r"(.*?)LIF_D3_LOG_END2", ser.buf, re.S)
        ev["install_log_tail"] = (tail[-1][-9000:] if tail else "")
        ev["markers_seen"] = [m for m in MARKERS if m in ev["install_log_tail"]] + [h[3] for h in ev["poll_history"] if h[3]]
        ser.send("sudo poweroff"); ser.drain(5)
    finally:
        ser.close()
    for _ in range(24):
        if not Path(f"/proc/{pid}").exists(): break
        time.sleep(5)
    ev["stopped"] = True if not Path(f"/proc/{pid}").exists() else stop_vm(pid)
    return bool(ev.get("install_done"))
def verify_phase(ev):
    """Boot the installed target alone (UEFI) and verify access."""
    for p in (SER2_SOCK, QGA2_SOCK, QMP2_SOCK, SER2_LOG, PID2FILE):
        p.unlink(missing_ok=True)
    argv = [
        "qemu-system-x86_64", "-name", "lifthrasir-lab-installed-d3",
        "-accel", "kvm", "-cpu", "host", "-machine", "q35",
        "-m", "4096", "-smp", "4",
        "-drive", "if=pflash,format=raw,readonly=on,file=/usr/share/OVMF/OVMF_CODE_4M.fd",
        "-drive", f"if=pflash,format=raw,file={VARS}",
        "-drive", f"file={TARGET},format=qcow2,if=virtio",
        "-chardev", f"socket,id=ser0,path={SER2_SOCK},server=on,wait=off,logfile={SER2_LOG}",
        "-serial", "chardev:ser0",
        "-chardev", f"socket,id=qga0,path={QGA2_SOCK},server=on,wait=off",
        "-device", "virtio-serial-pci,id=virtio-serial0",
        "-device", "virtserialport,chardev=qga0,name=org.qemu.guest_agent.0",
        "-netdev", f"user,id=n0,hostfwd=tcp:127.0.0.1:{SSH_FWD_PORT}-:22",
        "-device", "virtio-net-pci,netdev=n0",
        "-display", "none", "-pidfile", str(PID2FILE),
        "-qmp", f"unix:{QMP2_SOCK},server,nowait", "-daemonize"]
    ev["verify_argv"] = argv
    proc = subprocess.Popen(["nice", "-n", "10", *argv], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    ev["verify_launcher_rc"] = proc.wait(timeout=30)
    pid = int(PID2FILE.read_text().strip())
    ev["verify_pid"] = pid
    log(f"verify boot pid={pid}; waiting for login prompt")
    markers = wait_login(SER2_LOG, pid, 300)
    ev["verify_boot_markers"] = markers
    shell = False
    if markers.get("login_prompt"):
        ser = Serial(SER2_SOCK)
        try:
            ser.drain(2)
            ser.send("")
            ser.drain(2)
            ser.send("lab")
            ser.drain(3)
            ser.send("lifthrasir-lab")
            ser.drain(5)
            ser.send("id; uname -r; systemctl is-active ssh qemu-guest-agent; ss -tln | grep :22; echo LIFTHRASIR_GUEST_OK$((1+1))")
            shell = ser.wait_for("LIFTHRASIR_GUEST_OK2", 60)
            seg = ser.buf[-3000:]
            ev["verify_transcript_tail"] = seg
            ev["ssh_active"] = bool(re.search(r"(?m)^active\r?$", seg))
            ser.send("sudo poweroff")
            ser.drain(2)
            ser.send("lifthrasir-lab")
            ser.drain(3)
        finally:
            ser.close()
    ev["qga_ping"] = qga_ping(QGA2_SOCK)
    try:
        c = socket.create_connection(("127.0.0.1", SSH_FWD_PORT), timeout=5)
        banner = c.recv(64)
        c.close()
        ev["ssh_tcp_banner"] = banner.decode(errors="replace")[:64]
        ev["ssh_tcp"] = b"SSH" in banner
    except OSError:
        ev["ssh_tcp"] = False
    for _ in range(12):
        if not Path(f"/proc/{pid}").exists():
            break
        time.sleep(5)
    if Path(f"/proc/{pid}").exists():
        ev["verify_stopped"] = stop_vm(pid)
    else:
        ev["verify_stopped"] = True
    return shell

def main():
    EVID.mkdir(parents=True, exist_ok=True)
    ev = {"slice": "activation-phase1-D3"}
    ev["iso_sha256_ok"] = sha(ISO) == PIN
    if not ev["iso_sha256_ok"]:
        ev["error"] = "ISO sha mismatch; refusing"
        (EVID / "sliceD3-evidence.json").write_text(json.dumps(ev, indent=2)); print("SLICED3_INCOMPLETE"); return 1
    if not stage(ev):
        ev["error"] = "genisoimage failed"
        (EVID / "sliceD3-evidence.json").write_text(json.dumps(ev, indent=2)); print("SLICED3_INCOMPLETE"); return 1
    pid = install_phase(ev); ok_install = False
    if pid:
        try: ok_install = install_serial(ev, pid)
        except OSError as exc: ev["error"] = f"install serial failed: {exc}"
    log(f"install done={ok_install}")
    ok = False
    if ok_install:
        ok = verify_phase(ev); log(f"verify shell={ok}")
    if ok:
        shutil.copyfile(TARGET, GOLDEN_INST)
        ev["golden_installed"] = str(GOLDEN_INST); ev["golden_installed_sha256"] = sha(GOLDEN_INST)
    ev["installed_shell_proven"] = ok; ev["phase1_exit_met"] = False
    p = EVID / "sliceD3-evidence.json"; p.write_text(json.dumps(ev, indent=2))
    shutil.copyfile(p, SEAT / "lab" / "evidence" / "sliceD3-evidence.json")
    print(f"EVIDENCE={p}"); print("SLICED3_OK" if ok else "SLICED3_INCOMPLETE")
    return 0 if ok else 2
if __name__ == "__main__": raise SystemExit(main())
