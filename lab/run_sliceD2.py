# SPDX-License-Identifier: GPL-2.0-only
"""Activation Phase 1, slice D2 driver: Calamares unattended install.
Live boot (target = only virtio disk) -> calamares -c merged config
-> poweroff -> UEFI boot of installed target -> verify serial shell,
QGA ping, sshd. Evidence JSON on the vault. Detached; ~50 min max.
"""
from __future__ import annotations
import hashlib, json, os, re, shutil, signal, socket, subprocess, sys, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from lab.calamares_config import build_settings, config_iso_argv, render_module_conf, render_settings_conf
from lab.guest_access import GuestAccess, build_qemu_argv, parse_serial_log
from lab.real_runner import SubprocessRunner
SEAT = Path.home() / "lifthrasir-forge"
LAB = Path("/mnt/vault/lifthrasir-lab")
ISO = LAB / "kubuntu-24.04.5-desktop-amd64.iso"
PIN = "ae59e59c54337bcd8f8e60825b4a3f58797121ae0e89855524ffc92b8075c1d6"
RECON = SEAT / "lab" / "evidence" / "sliceD-recon.json"
EVID = LAB / "evidence"
KERNEL, INITRD = LAB / "casper-vmlinuz", LAB / "casper-initrd"
TARGET = LAB / "install-target.qcow2"
GOLDEN_INST = LAB / "golden-installed.qcow2"
CFGISO = LAB / "config.iso"
STAGE = SEAT / "lab" / "config-stage"
VARS2 = LAB / "OVMF_VARS-D2.fd"
SER_SOCK, SER_LOG = LAB / "serial-D2.sock", LAB / "serial-D2.log"
QGA_SOCK, QMP_SOCK = LAB / "qga-D2.sock", LAB / "qmp-D2.sock"
PIDFILE = LAB / "qemu-D2.pid"
SER2_SOCK, SER2_LOG = LAB / "serial-D2b.sock", LAB / "serial-D2b.log"
QGA2_SOCK, QMP2_SOCK = LAB / "qga-D2b.sock", LAB / "qmp-D2b.sock"
PID2FILE = LAB / "qemu-D2b.pid"
SSH_FWD_PORT = 2223
INSTALL_BUDGET_S = 35 * 60

def log(m):
    print(f"[{time.strftime('%H:%M:%S')}] {m}", flush=True)

def sha256_stream(p):
    h = hashlib.sha256()
    with p.open("rb") as f:
        for c in iter(lambda: f.read(1 << 22), b""):
            h.update(c)
    return h.hexdigest()

class Serial:
    """One persistent serial-console connection with a text buffer."""
    def __init__(self, sock_path):
        self.s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.s.settimeout(5)
        self.s.connect(str(sock_path))
        self.s.setblocking(False)
        self.buf = ""
    def drain(self, dur):
        end = time.time() + dur
        while time.time() < end:
            try:
                data = self.s.recv(65536)
                if data:
                    self.buf += data.decode(errors="replace")
            except BlockingIOError:
                time.sleep(0.2)
            except OSError:
                break
    def send(self, line):
        self.s.sendall((line + "\n").encode())
    def wait_for(self, marker, timeout_s):
        end = time.time() + timeout_s
        while time.time() < end:
            if marker in self.buf:
                return True
            self.drain(2)
        return marker in self.buf
    def close(self):
        try:
            self.s.close()
        except OSError:
            pass

def wait_login(logpath, pid, timeout_s):
    markers = {}
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        if logpath.exists():
            markers = parse_serial_log(logpath.read_text(errors="replace"))
            if markers.get("login_prompt"):
                break
        if not Path(f"/proc/{pid}").exists():
            break
        time.sleep(5)
    return markers

def stop_vm(pid):
    if Path(f"/proc/{pid}").exists():
        os.kill(pid, signal.SIGTERM)
        for _ in range(30):
            if not Path(f"/proc/{pid}").exists():
                break
            time.sleep(0.5)
    return not Path(f"/proc/{pid}").exists()

def qga_ping(sock_path):
    try:
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.settimeout(5)
        s.connect(str(sock_path))
        s.sendall(b'{"execute": "guest-ping"}\n')
        data = s.recv(4096)
        s.close()
        return b"return" in data
    except OSError:
        return False

def stage_config(ev):
    """Build the config CD staging tree from recon evidence."""
    recon = json.loads(RECON.read_text())
    discovered = set(recon["discovered_exec"]) | set(recon["discovered_show"])
    ev["discovered_count"] = len(discovered)
    settings = build_settings(discovered)
    if STAGE.exists():
        shutil.rmtree(STAGE)
    (STAGE / "modules").mkdir(parents=True)
    (STAGE / "settings.conf").write_text(render_settings_conf(settings))
    for kind in ("partition", "users", "packages"):
        (STAGE / "modules" / f"{kind}.conf").write_text(render_module_conf(kind))
    ev["staged_files"] = sorted(str(p.relative_to(STAGE)) for p in STAGE.rglob("*") if p.is_file())
    ev["exec_sequence"] = next(ph["exec"] for ph in settings["sequence"] if "exec" in ph)

def install_phase(ev):
    """Boot live image, run Calamares unattended; True if target partitioned."""
    runner = SubprocessRunner(timeout_s=300)
    if TARGET.exists():
        runner.run(["rm", "-f", str(TARGET)])
    rc = runner.run(["qemu-img", "create", "-f", "qcow2", str(TARGET), "32G"])
    ev["target_create_rc"] = rc
    if rc != 0:
        ev["error"] = "qemu-img create failed"
        return False
    gen = subprocess.run(config_iso_argv(str(STAGE), str(CFGISO)), capture_output=True, text=True, timeout=120)
    ev["genisoimage_rc"] = gen.returncode
    if gen.returncode != 0:
        ev["error"] = "genisoimage failed: " + gen.stderr[-300:]
        return False
    VARS2.unlink(missing_ok=True)
    shutil.copyfile("/usr/share/OVMF/OVMF_VARS_4M.fd", VARS2)
    for p in (SER_SOCK, QGA_SOCK, QMP_SOCK, SER_LOG, PIDFILE):
        p.unlink(missing_ok=True)
    acc = GuestAccess(kernel=KERNEL, initrd=INITRD, iso=ISO, disk=TARGET, serial_sock=SER_SOCK, serial_log=SER_LOG, qga_sock=QGA_SOCK, qmp_sock=QMP_SOCK, pidfile=PIDFILE, vars_fd=VARS2)
    argv = build_qemu_argv(acc)
    idx = argv.index("-display")
    argv[idx:idx] = ["-drive", f"file={CFGISO},format=raw,if=none,id=cd1,readonly=on", "-device", "virtio-blk-pci,drive=cd1"]
    ev["qemu_argv"] = argv
    proc = subprocess.Popen(["nice", "-n", "10", *argv], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    ev["launcher_rc"] = proc.wait(timeout=30)
    if not PIDFILE.exists():
        ev["error"] = "qemu launch failed, rc=" + str(ev["launcher_rc"])
        return False
    pid = int(PIDFILE.read_text().strip())
    ev["qemu_pid"] = pid
    log(f"install boot pid={pid}; waiting for login prompt")
    markers = wait_login(SER_LOG, pid, 300)
    ev["boot_markers"] = markers
    if not markers.get("login_prompt"):
        ev["error"] = "live guest never reached a login prompt"
        ev["stopped"] = stop_vm(pid)
        return False
    return pid

def install_serial(ev, pid):
    """Serial work in the live guest: stock dump, stage, install, poll."""
    ser = Serial(SER_SOCK)
    try:
        ser.drain(2)
        for line in ("", "kubuntu", ""):
            ser.send(line)
            ser.drain(3)
        log("logged in; dumping stock module configs")
        ser.send("echo LIF_D2_STOCK_BEGIN; for f in partition users packages mount bootloader; do echo ===$f===; cat /etc/calamares/modules/$f.conf 2>&1; done; lsblk -o NAME,SIZE,TYPE; blkid; echo LIF_D2_STOCK_END")
        deadline = time.time() + 90
        while time.time() < deadline and ser.buf.count("LIF_D2_STOCK_END") < 2:
            ser.drain(2)
        m = re.findall(r"LIF_D2_STOCK_BEGIN(.*?)LIF_D2_STOCK_END", ser.buf, re.S)
        ev["stock_block"] = (m[-1][-7000:] if m else "")
        ev["stock_dump_ok"] = bool(m)
        ser.buf = ""
        ser.send("sudo mkdir -p /mnt/cfg; sudo mount /dev/disk/by-label/LIF_CONFIG /mnt/cfg && echo LIF_D2_MOUNT_OK$((1+1)) || echo LIF_D2_MOUNT_FAIL$((1+1))")
        mok = ser.wait_for("LIF_D2_MOUNT_OK2", 30) or ser.wait_for("LIF_D2_MOUNT_FAIL2", 3)
        if not (mok or "LIF_D2_MOUNT_FAIL2" in ser.buf):
            ev["error"] = "config CD mount produced no marker"
            return False
        ev["config_mounted"] = "LIF_D2_MOUNT_OK2" in ser.buf
        if not ev["config_mounted"]:
            ev["error"] = "config CD mount failed"
            return False
        ser.buf = ""
        log("config mounted; merging over stock module configs")
        ser.send("rm -rf /tmp/lifcfg; mkdir -p /tmp/lifcfg/modules; cp /etc/calamares/modules/*.conf /tmp/lifcfg/modules/; cp /mnt/cfg/settings.conf /tmp/lifcfg/; cp /mnt/cfg/modules/*.conf /tmp/lifcfg/modules/; ln -s /usr/share/calamares/qml /tmp/lifcfg/qml; cp -r /etc/calamares/branding /tmp/lifcfg/branding; sudo mkdir -p /tmp/runtime-root; sudo chmod 700 /tmp/runtime-root; echo LIF_D2_STAGED$((1+1))")
        if not ser.wait_for("LIF_D2_STAGED2", 30):
            ev["error"] = "config merge produced no marker"
            return False
        ser.buf = ""
        ser.send("sudo env QT_QPA_PLATFORM=offscreen XDG_RUNTIME_DIR=/tmp/runtime-root nohup calamares -d -c /tmp/lifcfg >/tmp/cala.log 2>&1 & echo LIF_D2_CALA_LAUNCHED")
        ser.wait_for("LIF_D2_CALA_LAUNCHED", 30)
        log("calamares launched; polling until it exits or budget ends")
        deadline = time.time() + INSTALL_BUDGET_S
        gone = False
        ev["poll_history"] = []
        ev["stall_detected"] = False
        last_sig = None
        stall_polls = 0
        t0 = time.time()
        while time.time() < deadline:
            time.sleep(40)
            ser.buf = ""
            ser.send("echo LIF_D2_STAT; pgrep -x calamares >/dev/null && echo CALA_RUNNING$((1+1)) || echo CALA_GONE$((1+1)); wc -c /tmp/cala.log; echo LIF_D2_STAT_END$((1+1))")
            if not ser.wait_for("LIF_D2_STAT_END2", 25):
                log("stat poll timed out (guest busy?)")
                continue
            if "CALA_GONE2" in ser.buf:
                gone = True
                break
            wm = re.findall(r"(\d+)\s+/tmp/cala\.log", ser.buf)
            logsz = int(wm[-1]) if wm else -1
            try:
                tsz = TARGET.stat().st_size
            except OSError:
                tsz = -1
            ev["poll_history"].append([round(time.time() - t0), logsz, tsz])
            log(f"poll: cala.log={logsz} target={tsz}")
            sig = (logsz, tsz)
            if sig == last_sig:
                stall_polls += 1
            else:
                stall_polls = 0
                last_sig = sig
            if stall_polls >= 4:
                ev["stall_detected"] = True
                log("stall detected: no log or target growth for 4 polls")
                break
        ev["calamares_exited"] = gone
        log(f"calamares exited={gone}; collecting log + post state")
        ser.buf = ""
        ser.send("tail -c 12000 /tmp/cala.log; echo LIF_D2_LOG_END$((1+1)); lsblk -o NAME,SIZE,TYPE; ps aux | grep -i cala | grep -v grep; cat /proc/$(pgrep -x calamares | head -1)/status 2>/dev/null | head -n 12; echo LIF_D2_POST_END$((1+1))")
        ser.wait_for("LIF_D2_POST_END2", 60)
        ser.drain(3)
        tail = re.findall(r"(.*?)LIF_D2_LOG_END2", ser.buf, re.S)
        ev["cala_log_tail"] = (tail[-1][-12000:] if tail else "")
        post = re.findall(r"LIF_D2_LOG_END2(.*?)LIF_D2_POST_END2", ser.buf, re.S)
        ev["post_lsblk"] = (post[-1].strip() if post else "")
        tm = re.search(r"(vd[ab])\s+32G", ev["post_lsblk"])
        ev["target_disk"] = tm.group(1) if tm else None
        ev["target_partitioned"] = bool(tm and re.search(tm.group(1) + r"[0-9]", ev["post_lsblk"]))
        ser.send("sudo poweroff")
        ser.drain(5)
    finally:
        ser.close()
    for _ in range(24):
        if not Path(f"/proc/{pid}").exists():
            break
        time.sleep(5)
    if Path(f"/proc/{pid}").exists():
        ev["stopped"] = stop_vm(pid)
    else:
        ev["stopped"] = True
    return bool(ev.get("target_partitioned"))

def verify_phase(ev):
    """Boot the installed target alone (UEFI) and verify access."""
    for p in (SER2_SOCK, QGA2_SOCK, QMP2_SOCK, SER2_LOG, PID2FILE):
        p.unlink(missing_ok=True)
    argv = [
        "qemu-system-x86_64", "-name", "lifthrasir-lab-installed",
        "-accel", "kvm", "-cpu", "host", "-machine", "q35",
        "-m", "4096", "-smp", "4",
        "-drive", "if=pflash,format=raw,readonly=on,file=/usr/share/OVMF/OVMF_CODE_4M.fd",
        "-drive", f"if=pflash,format=raw,file={VARS2}",
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
    ev = {"slice": "activation-phase1-D2"}
    ev["iso_sha256_ok"] = sha256_stream(ISO) == PIN
    if not ev["iso_sha256_ok"]:
        ev["error"] = "ISO sha mismatch; refusing"
        (EVID / "sliceD2-evidence.json").write_text(json.dumps(ev, indent=2))
        print("SLICED2_INCOMPLETE")
        return 1
    try:
        stage_config(ev)
    except (ValueError, KeyError, FileNotFoundError) as exc:
        ev["error"] = f"config staging refused: {exc}"
        (EVID / "sliceD2-evidence.json").write_text(json.dumps(ev, indent=2))
        print("SLICED2_INCOMPLETE")
        return 1
    log(f"config staged: {ev['staged_files']}")
    pid = install_phase(ev)
    partitioned = False
    if pid:
        try:
            partitioned = install_serial(ev, pid)
        except OSError as exc:
            ev["error"] = f"install serial failed: {exc}"
    log(f"install phase done; partitioned={partitioned}")
    ok = False
    if partitioned:
        ok = verify_phase(ev)
        log(f"verify phase done; shell={ok}")
    if ok:
        shutil.copyfile(TARGET, GOLDEN_INST)
        ev["golden_installed"] = str(GOLDEN_INST)
        ev["golden_installed_sha256"] = sha256_stream(GOLDEN_INST)
    ev["installed_shell_proven"] = ok
    ev["phase1_exit_met"] = False
    p = EVID / "sliceD2-evidence.json"
    p.write_text(json.dumps(ev, indent=2))
    print(f"EVIDENCE={p}")
    print("SLICED2_OK" if ok else "SLICED2_INCOMPLETE")
    return 0 if ok else 2

if __name__ == "__main__":
    raise SystemExit(main())
