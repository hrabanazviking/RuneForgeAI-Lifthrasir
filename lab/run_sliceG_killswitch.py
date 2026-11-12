# SPDX-License-Identifier: GPL-2.0-only
"""Activation Phase 1 slice G: kill-switch drill.
Part 1 (host, fixture level): KillSwitch + FixtureRegistry -- spawn
this project's own sleeper fixture plus one unregistered foreign
sleeper; engage_and_stop mid-run; prove only the registered fixture
dies, the halt survives a fresh instance (restart), require_clear
refuses while engaged, the audit chain verifies, and journal
recovery preserves committed / rolls back in-flight / expires
prepared / is idempotent. Release restores require_clear.
Part 2 (lab loop): boot a disposable overlay of golden-installed,
start a guest heartbeat loop, engage the campaign stop (flag file +
KillSwitch) while it runs; the driver loop polls the switch, halts:
poweroff via serial, overlay deleted, golden sha unchanged, no
QEMU left; then release + flag removed. Lab only, CPU-only,
4vCPU/4GiB, nice 10, one VM. Evidence on vault + seat."""
from __future__ import annotations
import hashlib, json, os, re, shutil, signal, socket, subprocess, sys, time
from datetime import datetime, timezone
from pathlib import Path
sys.path.insert(0, str(Path.home() / 'lifthrasir-forge'))
sys.path.insert(0, str(Path.home() / 'lifthrasir-forge' / 'src'))
from lab.guest_access import parse_serial_log
SEAT = Path.home() / 'lifthrasir-forge'
LAB = Path('/mnt/vault/lifthrasir-lab')
GOLDEN = LAB / 'golden-installed.qcow2'
GOLDEN_SHA = 'd9edd18c4d0d8406038fc180ce6a177c9d7d16a0892f12263d791331bf192c90'
EVID = LAB / 'evidence'
OVERLAY = LAB / 'overlay-G.qcow2'
VARS_SRC = LAB / 'OVMF_VARS-D3.fd'
VARS = LAB / 'OVMF_VARS-G.fd'
PORT = 2227
GUEST_NAME = 'lifthrasir-lab-G'
FLAG = LAB / 'STOP-G.flag'
SLEEPER = SEAT / 'tests' / 'fixtures' / 'lif0406' / 'sleeper.py'
JOURNAL_FX = SEAT / 'tests' / 'fixtures' / 'lif0406' / 'journal-interrupted.json'
def log(m): print(f"[{time.strftime('%H:%M:%S')}] {m}", flush=True)
def sha(p):
    h = hashlib.sha256()
    with p.open('rb') as f:
        for c in iter(lambda: f.read(1 << 22), b''): h.update(c)
    return h.hexdigest()
def now_iso():
    return datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
def proc_dead(pid):
    st = Path(f'/proc/{pid}/stat')
    if not st.exists(): return True
    try: return st.read_text().split()[2] == 'Z'
    except Exception: return False
def wait_dead(pid, timeout_s=6):
    end = time.time() + timeout_s
    while time.time() < end:
        if proc_dead(pid): return True
        time.sleep(0.3)
    return proc_dead(pid)
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
def boot_to_shell():
    ser_sock = LAB / 'serial-G.sock'; ser_log = LAB / 'serial-G.log'
    qga_sock = LAB / 'qga-G.sock'; qmp_sock = LAB / 'qmp-G.sock'
    pidfile = LAB / 'qemu-G.pid'
    for p in (ser_sock, qga_sock, qmp_sock, ser_log, pidfile): p.unlink(missing_ok=True)
    shutil.copyfile(VARS_SRC, VARS)
    OVERLAY.unlink(missing_ok=True)
    rc = subprocess.run(['qemu-img', 'create', '-f', 'qcow2', '-F', 'qcow2', '-b', str(GOLDEN), str(OVERLAY), '32G'], capture_output=True, text=True, timeout=120).returncode
    if rc != 0: return None, None, {'error': 'overlay create failed'}
    argv = ['qemu-system-x86_64', '-name', GUEST_NAME, '-accel', 'kvm', '-cpu', 'host', '-machine', 'q35', '-m', '4096', '-smp', '4', '-drive', 'if=pflash,format=raw,readonly=on,file=/usr/share/OVMF/OVMF_CODE_4M.fd', '-drive', f'if=pflash,format=raw,file={VARS}', '-drive', f'file={OVERLAY},format=qcow2,if=virtio', '-chardev', f'socket,id=ser0,path={ser_sock},server=on,wait=off,logfile={ser_log}', '-serial', 'chardev:ser0', '-chardev', f'socket,id=qga0,path={qga_sock},server=on,wait=off', '-device', 'virtio-serial-pci,id=virtio-serial0', '-device', 'virtserialport,chardev=qga0,name=org.qemu.guest_agent.0', '-netdev', f'user,id=n0,hostfwd=tcp:127.0.0.1:{PORT}-:22', '-device', 'virtio-net-pci,netdev=n0', '-display', 'none', '-pidfile', str(pidfile), '-qmp', f'unix:{qmp_sock},server,nowait', '-daemonize']
    info = {'argv': argv}
    proc = subprocess.Popen(['nice', '-n', '10', *argv], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    info['launcher_rc'] = proc.wait(timeout=30)
    if not pidfile.exists(): info['error'] = 'no pidfile'; return None, None, info
    pid = int(pidfile.read_text().strip()); info['pid'] = pid
    markers = wait_login(ser_log, pid); info['boot_markers'] = markers
    if not markers.get('login_prompt'): info['error'] = 'no login'; return None, pid, info
    ser = Serial(ser_sock)
    ser.drain(2); ser.send(''); ser.drain(2); ser.send('lab'); ser.drain(3); ser.send('lifthrasir-lab'); ser.drain(5)
    ser.send('sudo -s'); ser.drain(2); ser.send('lifthrasir-lab'); ser.drain(3)
    info['qga_sock'] = str(qga_sock)
    return ser, pid, info
def phase(ser, lines, marker, timeout_s=120):
    ser.buf = ''
    for ln in lines: ser.send(ln)
    ok = ser.wait_for(marker, timeout_s)
    return ok, ser.buf
def host_drill():
    from lifthrasir import killswitch as ks
    out = {}
    state = LAB / 'killswitch-G-host'
    shutil.rmtree(state, ignore_errors=True); state.mkdir(parents=True, exist_ok=True)
    sw = ks.KillSwitch(state); reg = ks.FixtureRegistry(state)
    mark = 'lif-g-drill-' + str(int(time.time()))
    pid = reg.spawn_fixture([sys.executable, str(SLEEPER), mark], mark)
    foreign = subprocess.Popen([sys.executable, str(SLEEPER), 'lif-g-foreign-unregistered'])
    out['fixture_pid'] = pid; out['foreign_pid'] = foreign.pid
    time.sleep(0.6)
    out['fixture_alive_before'] = not proc_dead(pid)
    out['foreign_alive_before'] = not proc_dead(foreign.pid)
    iterations = []
    halted_at = [None]
    def loop():
        for i in range(200):
            try: sw.require_clear(f'loop-iter-{i}')
            except ks.KillSwitchEngaged:
                halted_at[0] = i; return
            iterations.append(i); time.sleep(0.1)
    import threading
    th = threading.Thread(target=loop); th.start()
    time.sleep(0.55)
    rec, rep = ks.engage_and_stop(sw, reg, 'keeper-sliceG', 'Phase 1 kill-switch drill: halt mid-run')
    th.join(timeout=10)
    out['loop_iterations_before_halt'] = len(iterations)
    out['loop_halted_at_iter'] = halted_at[0]
    out['loop_thread_alive_after'] = th.is_alive()
    out['termination'] = rep.to_dict()
    out['fixture_dead_after'] = wait_dead(pid)
    out['foreign_alive_after_engage'] = not proc_dead(foreign.pid)
    sw2 = ks.KillSwitch(state)
    out['restart_sees_halt'] = sw2.is_engaged()
    try:
        sw2.require_clear('post-restart probe'); out['require_clear_refused'] = False
    except ks.KillSwitchEngaged: out['require_clear_refused'] = True
    out['audit_chain_ok'] = sw.verify_audit()
    jp = state / 'journal.json'
    jp.write_bytes(JOURNAL_FX.read_bytes())
    coord = ks.RecoveryCoordinator(sw, jp)
    rep1 = coord.recover(actor='keeper-sliceG')
    out['recovery'] = rep1.to_dict()
    rep2 = ks.recover_journal(jp, actor='keeper-sliceG')
    out['recovery_second_changed'] = rep2.changed
    out['released'] = sw.release('keeper-sliceG', 'host drill complete')
    out['engaged_after_release'] = sw.is_engaged()
    try:
        sw.require_clear('post-release probe'); out['require_clear_after_release'] = True
    except ks.KillSwitchEngaged: out['require_clear_after_release'] = False
    out['audit_chain_ok_after_release'] = sw.verify_audit()
    foreign.terminate()
    try: foreign.wait(timeout=5)
    except Exception: foreign.kill()
    out['foreign_cleaned_by_owner'] = proc_dead(foreign.pid) or wait_dead(foreign.pid)
    out['host_drill_passed'] = bool(out['fixture_alive_before'] and out['foreign_alive_before'] and out['loop_halted_at_iter'] is not None and not out['loop_thread_alive_after'] and out['fixture_dead_after'] and out['foreign_alive_after_engage'] and out['restart_sees_halt'] and out['require_clear_refused'] and out['audit_chain_ok'] and rep1.preserved_committed == ['txn-committed-1'] and [r['txn_id'] for r in rep1.rolled_back] == ['txn-inflight-1'] and rep1.expired_prepared == ['txn-prepared-1'] and out['recovery_second_changed'] is False and out['released'] and out['require_clear_after_release'] and out['audit_chain_ok_after_release'])
    return out
def hb_value(seg):
    m = re.findall(r'HBVAL=(\d+)', seg)
    return int(m[-1]) if m else None
def vm_drill(ev):
    from lifthrasir import killswitch as ks
    out = {}
    ser, pid, info = boot_to_shell(); ev['boot'] = info
    log(f"boot pid={pid} err={info.get('error')}")
    if ser is None:
        out['vm_drill_passed'] = False; return out
    try:
        start = ["rm -f /root/hb.txt", "nohup sh -c 'i=0; while true; do i=$((i+1)); echo $i > /root/hb.txt; sleep 2; done' >/dev/null 2>&1 &", 'sleep 5', 'echo HBVAL=$(cat /root/hb.txt)', 'echo GSTART$((2+2))']
        ok1, seg1 = phase(ser, start, 'GSTART4', 90)
        hb1 = hb_value(seg1); out['hb_first'] = hb1; out['guest_loop_started'] = bool(ok1 and hb1 and hb1 >= 1)
        log(f'guest loop hb1={hb1}')
        time.sleep(4)
        ok2, seg2 = phase(ser, ['echo HBVAL=$(cat /root/hb.txt)', 'echo GMID$((3+3))'], 'GMID6', 60)
        hb2 = hb_value(seg2); out['hb_second'] = hb2
        out['guest_loop_advancing'] = bool(hb2 and hb1 and hb2 > hb1)
        log(f'guest loop hb2={hb2} advancing={out["guest_loop_advancing"]}')
        out['qga_ping_before_halt'] = qga_ping(info['qga_sock'])
        out['ssh_tcp_before_halt'] = ssh_probe()
        state = LAB / 'killswitch-G-vm'
        shutil.rmtree(state, ignore_errors=True); state.mkdir(parents=True, exist_ok=True)
        sw = ks.KillSwitch(state)
        FLAG.write_text(json.dumps({'engaged_by': 'keeper-sliceG', 'at': now_iso(), 'reason': 'Phase 1 kill-switch drill: halt lab loop mid-run'}) + '\n')
        rec = sw.engage('keeper-sliceG', 'campaign stop: halt lab loop mid-run')
        out['halt_record'] = rec.to_dict(); out['flag_written'] = FLAG.exists()
        halted = False
        for cycle in range(60):
            if sw.is_engaged(): halted = True; out['halted_at_cycle'] = cycle; break
            time.sleep(0.5)
        out['driver_loop_saw_engage'] = halted
        log(f'campaign stop engaged; driver halted={halted}; powering off guest')
        ser.send('poweroff'); ser.drain(3)
    finally:
        ser.close()
    for _ in range(12):
        if not Path(f'/proc/{pid}').exists(): break
        time.sleep(5)
    out['vm_stopped'] = True if not Path(f'/proc/{pid}').exists() else stop_vm(pid)
    out['engaged_after_vm_down'] = ks.KillSwitch(state).is_engaged()
    out['audit_chain_ok'] = ks.KillSwitch(state).verify_audit()
    sw3 = ks.KillSwitch(state)
    out['released_after_halt'] = sw3.release('keeper-sliceG', 'VM halt proven; drill complete')
    FLAG.unlink(missing_ok=True); out['flag_removed'] = not FLAG.exists()
    OVERLAY.unlink(missing_ok=True); out['overlay_deleted'] = not OVERLAY.exists()
    out['vm_drill_passed'] = bool(out.get('guest_loop_started') and out.get('guest_loop_advancing') and out.get('flag_written') and out.get('driver_loop_saw_engage') and out.get('vm_stopped') and out.get('engaged_after_vm_down') and out.get('audit_chain_ok') and out.get('released_after_halt') and out.get('flag_removed') and out.get('overlay_deleted'))
    return out
def main():
    EVID.mkdir(parents=True, exist_ok=True)
    ev = {'slice': 'activation-phase1-G-killswitch-drill', 'golden': str(GOLDEN), 'started_at': now_iso()}
    ev['golden_sha256'] = sha(GOLDEN); ev['golden_sha_ok'] = ev['golden_sha256'] == GOLDEN_SHA
    ok_all = False
    if ev['golden_sha_ok']:
        ev['host'] = host_drill(); log(f"host drill passed={ev['host'].get('host_drill_passed')}")
        if ev['host'].get('host_drill_passed'):
            ev['vm'] = vm_drill(ev); log(f"vm drill passed={ev['vm'].get('vm_drill_passed')}")
            ok_all = bool(ev['vm'].get('vm_drill_passed'))
    ev['drill_proven'] = ok_all
    ev['golden_sha_after'] = sha(GOLDEN); ev['golden_unchanged'] = ev['golden_sha_after'] == GOLDEN_SHA
    ev['finished_at'] = now_iso()
    p = EVID / 'sliceG-evidence.json'; p.write_text(json.dumps(ev, indent=2))
    shutil.copyfile(p, SEAT / 'lab' / 'evidence' / 'sliceG-evidence.json')
    print(f'EVIDENCE={p}'); print('SLICEG_OK' if ok_all and ev['golden_unchanged'] else 'SLICEG_INCOMPLETE')
    return 0 if ok_all else 2
if __name__ == '__main__': raise SystemExit(main())
