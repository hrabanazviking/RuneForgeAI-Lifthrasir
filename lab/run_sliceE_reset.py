# SPDX-License-Identifier: GPL-2.0-only
"""Activation Phase 1 slice E: reset-to-golden proof x2.
For each round: boot overlay of golden-installed, dirty it with a
marker file, poweroff, DELETE overlay, recreate fresh overlay from
golden, boot again, prove marker absent + services active.
QGA/SSH probed BEFORE poweroff (fixes D3 verify-ordering blemish).
Evidence JSON on vault + seat copy. Lab only, CPU-only, 4vCPU/4GiB.
"""
from __future__ import annotations
import hashlib, json, os, re, shutil, signal, socket, subprocess, sys, time
from pathlib import Path
sys.path.insert(0, str(Path.home() / 'lifthrasir-forge'))
from lab.guest_access import parse_serial_log
SEAT = Path.home() / 'lifthrasir-forge'
LAB = Path('/mnt/vault/lifthrasir-lab')
GOLDEN = LAB / 'golden-installed.qcow2'
GOLDEN_SHA = 'd9edd18c4d0d8406038fc180ce6a177c9d7d16a0892f12263d791331bf192c90'
EVID = LAB / 'evidence'
OVERLAY = LAB / 'overlay-E.qcow2'
VARS_SRC = LAB / 'OVMF_VARS-D3.fd'
VARS = LAB / 'OVMF_VARS-E.fd'
PORT = 2225
def log(m): print(f"[{time.strftime('%H:%M:%S')}] {m}", flush=True)
def sha(p):
    h = hashlib.sha256()
    with p.open('rb') as f:
        for c in iter(lambda: f.read(1 << 22), b''): h.update(c)
    return h.hexdigest()
class Serial:
    def __init__(self, sp):
        self.s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.s.settimeout(5); self.s.connect(str(sp)); self.s.setblocking(False); self.buf = ''
    def drain(self, dur):
        end = time.time() + dur
        while time.time() < end:
            try:
                d = self.s.recv(65536)
                if d: self.buf += d.decode(errors='replace')
            except BlockingIOError: time.sleep(0.2)
            except OSError: break
    def send(self, line): self.s.sendall((line + '\n').encode())
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
    if Path(f'/proc/{pid}').exists():
        os.kill(pid, signal.SIGTERM)
        for _ in range(30):
            if not Path(f'/proc/{pid}').exists(): break
            time.sleep(0.5)
    return not Path(f'/proc/{pid}').exists()
def wait_login(logpath, pid, timeout_s=300):
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        if logpath.exists() and parse_serial_log(logpath.read_text(errors='replace')).get('login_prompt'): break
        if not Path(f'/proc/{pid}').exists(): break
        time.sleep(5)
    return parse_serial_log(logpath.read_text(errors='replace')) if logpath.exists() else {}
def qga_ping(sp):
    try:
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM); s.settimeout(5)
        s.connect(str(sp)); s.sendall(b'{"execute": "guest-ping"}\n')
        d = s.recv(4096); s.close(); return b'return' in d
    except OSError: return False
def ssh_probe():
    try:
        c = socket.create_connection(('127.0.0.1', PORT), timeout=5)
        b = c.recv(64); c.close(); return b'SSH' in b
    except OSError: return False
def boot(tag, cmds, expect_marker):
    ser_sock = LAB / f'serial-E-{tag}.sock'; ser_log = LAB / f'serial-E-{tag}.log'
    qga_sock = LAB / f'qga-E-{tag}.sock'; qmp_sock = LAB / f'qmp-E-{tag}.sock'
    pidfile = LAB / f'qemu-E-{tag}.pid'
    for p in (ser_sock, qga_sock, qmp_sock, ser_log, pidfile): p.unlink(missing_ok=True)
    shutil.copyfile(VARS_SRC, VARS)
    argv = ['qemu-system-x86_64', '-name', f'lifthrasir-lab-E-{tag}', '-accel', 'kvm', '-cpu', 'host', '-machine', 'q35', '-m', '4096', '-smp', '4', '-drive', 'if=pflash,format=raw,readonly=on,file=/usr/share/OVMF/OVMF_CODE_4M.fd', '-drive', f'if=pflash,format=raw,file={VARS}', '-drive', f'file={OVERLAY},format=qcow2,if=virtio', '-chardev', f'socket,id=ser0,path={ser_sock},server=on,wait=off,logfile={ser_log}', '-serial', 'chardev:ser0', '-chardev', f'socket,id=qga0,path={qga_sock},server=on,wait=off', '-device', 'virtio-serial-pci,id=virtio-serial0', '-device', 'virtserialport,chardev=qga0,name=org.qemu.guest_agent.0', '-netdev', f'user,id=n0,hostfwd=tcp:127.0.0.1:{PORT}-:22', '-device', 'virtio-net-pci,netdev=n0', '-display', 'none', '-pidfile', str(pidfile), '-qmp', f'unix:{qmp_sock},server,nowait', '-daemonize']
    r = {'tag': tag, 'argv': argv}
    proc = subprocess.Popen(['nice', '-n', '10', *argv], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    r['launcher_rc'] = proc.wait(timeout=30)
    if not pidfile.exists(): r['error'] = 'no pidfile'; return r
    pid = int(pidfile.read_text().strip()); r['pid'] = pid
    markers = wait_login(ser_log, pid); r['boot_markers'] = markers
    if not markers.get('login_prompt'): r['error'] = 'no login'; r['stopped'] = stop_vm(pid); return r
    ser = Serial(ser_sock); shell = False
    try:
        ser.drain(2); ser.send(''); ser.drain(2); ser.send('lab'); ser.drain(3); ser.send('lifthrasir-lab'); ser.drain(5)
        ser.buf = ''
        ser.send(cmds)
        shell = ser.wait_for(expect_marker, 90)
        seg = ser.buf[-2500:]; r['transcript_tail'] = seg
        r['ssh_active'] = 'active' in seg
        # probe BEFORE poweroff (D3 blemish fix)
        r['qga_ping_before_poweroff'] = qga_ping(qga_sock)
        r['ssh_tcp_before_poweroff'] = ssh_probe()
        ser.send('sudo poweroff'); ser.drain(2); ser.send('lifthrasir-lab'); ser.drain(3)
    finally: ser.close()
    for _ in range(12):
        if not Path(f'/proc/{pid}').exists(): break
        time.sleep(5)
    r['stopped'] = True if not Path(f'/proc/{pid}').exists() else stop_vm(pid)
    r['shell_proven'] = shell
    return r
def fresh_overlay():
    OVERLAY.unlink(missing_ok=True)
    rc = subprocess.run(['qemu-img', 'create', '-f', 'qcow2', '-F', 'qcow2', '-b', str(GOLDEN), str(OVERLAY), '32G'], capture_output=True, text=True, timeout=120).returncode
    return rc
def main():
    EVID.mkdir(parents=True, exist_ok=True)
    ev = {'slice': 'activation-phase1-E-reset-x2', 'golden': str(GOLDEN)}
    ev['golden_sha256'] = sha(GOLDEN); ev['golden_sha_ok'] = ev['golden_sha256'] == GOLDEN_SHA
    if not ev['golden_sha_ok']: ev['error'] = 'golden sha mismatch; refusing'
    rounds = []
    ok_all = bool(ev['golden_sha_ok'])
    if ok_all:
        for n in (1, 2):
            rd = {'round': n}
            rc = fresh_overlay(); rd['overlay_create_rc_dirty'] = rc
            dirty_cmd = "echo dirty > ~/RESET_DIRTY; sync; test -f ~/RESET_DIRTY && echo RESET_DIRTY_PRESENT$((1+1)); systemctl is-active ssh qemu-guest-agent"
            d = boot(f'r{n}d', dirty_cmd, 'RESET_DIRTY_PRESENT2'); rd['dirty_boot'] = d
            log(f"round {n} dirty shell={d.get('shell_proven')} qga={d.get('qga_ping_before_poweroff')} ssh={d.get('ssh_tcp_before_poweroff')}")
            rc2 = fresh_overlay(); rd['overlay_create_rc_clean'] = rc2
            clean_cmd = "if test -f ~/RESET_DIRTY; then echo RESET_DIRTY_STILL_THERE$((1+1)); else echo RESET_CLEAN$((1+1)); fi; systemctl is-active ssh qemu-guest-agent; id"
            c = boot(f'r{n}c', clean_cmd, 'RESET_CLEAN2'); rd['clean_boot'] = c
            # dirty marker must not appear as clean verdict; check transcript
            rd['dirty_proven'] = bool(d.get('shell_proven'))
            rd['reset_proven'] = bool(c.get('shell_proven')) and 'RESET_DIRTY_STILL_THERE2' not in c.get('transcript_tail', '')
            rd['round_ok'] = rd['dirty_proven'] and rd['reset_proven'] and bool(c.get('qga_ping_before_poweroff')) and bool(c.get('ssh_tcp_before_poweroff'))
            log(f"round {n} clean reset={rd['reset_proven']} ok={rd['round_ok']}")
            rounds.append(rd); ok_all = ok_all and rd['round_ok']
    ev['rounds'] = rounds; ev['reset_x2_proven'] = ok_all
    ev['golden_sha_after'] = sha(GOLDEN); ev['golden_unchanged'] = ev['golden_sha_after'] == GOLDEN_SHA
    OVERLAY.unlink(missing_ok=True)
    p = EVID / 'sliceE-evidence.json'; p.write_text(json.dumps(ev, indent=2))
    shutil.copyfile(p, SEAT / 'lab' / 'evidence' / 'sliceE-evidence.json')
    print(f'EVIDENCE={p}'); print('SLICEE_OK' if ok_all and ev['golden_unchanged'] else 'SLICEE_INCOMPLETE')
    return 0 if ok_all else 2
if __name__ == '__main__': raise SystemExit(main())
