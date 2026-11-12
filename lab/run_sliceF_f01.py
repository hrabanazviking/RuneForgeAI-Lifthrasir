# SPDX-License-Identifier: GPL-2.0-only
"""Activation Phase 1 slice F: F01 fault loop inside the guest.
Inject F01 (demo.service failed via faulty MODE=broken config) into a
disposable overlay of golden-installed; observe via fault oracle +
systemd collector parsing; propose via banked recipe
rec-lab-guest-config-fix; authorise via policy engine (ALLOW) +
HMAC approval ledger (mint/decide/consume, tamper+replay refused);
apply fix (MODE=ok + restart in guest); verify (oracle no_fault);
roll back in guest (MODE=broken + restart, oracle fault again).
Lab only, CPU-only, 4vCPU/4GiB, one VM. Evidence on vault + seat."""
from __future__ import annotations
import hashlib, json, os, re, shutil, signal, socket, subprocess, sys, time
from datetime import datetime, timedelta, timezone
from pathlib import Path
sys.path.insert(0, str(Path.home() / 'lifthrasir-forge'))
sys.path.insert(0, str(Path.home() / 'lifthrasir-forge' / 'src'))
from lab.guest_access import parse_serial_log
SEAT = Path.home() / 'lifthrasir-forge'
LAB = Path('/mnt/vault/lifthrasir-lab')
GOLDEN = LAB / 'golden-installed.qcow2'
GOLDEN_SHA = 'd9edd18c4d0d8406038fc180ce6a177c9d7d16a0892f12263d791331bf192c90'
EVID = LAB / 'evidence'
OVERLAY = LAB / 'overlay-F.qcow2'
VARS_SRC = LAB / 'OVMF_VARS-D3.fd'
VARS = LAB / 'OVMF_VARS-F.fd'
PORT = 2226
GUEST_NAME = 'lifthrasir-lab-F'
CONF = '/etc/demo/demo.conf'
UNIT = 'demo.service'
def log(m): print(f"[{time.strftime('%H:%M:%S')}] {m}", flush=True)
def sha(p):
    h = hashlib.sha256()
    with p.open('rb') as f:
        for c in iter(lambda: f.read(1 << 22), b''): h.update(c)
    return h.hexdigest()
def now_iso():
    return datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
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
    ser_sock = LAB / 'serial-F.sock'; ser_log = LAB / 'serial-F.log'
    qga_sock = LAB / 'qga-F.sock'; qmp_sock = LAB / 'qmp-F.sock'
    pidfile = LAB / 'qemu-F.pid'
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
def parse_state(seg):
    def last(pat):
        m = re.findall(pat, seg)
        return m[-1] if m else None
    return {'name': last(r'Id=([A-Za-z0-9_.@-]+)'), 'active_state': last(r'ActiveState=([a-z]+)'), 'sub_state': last(r'SubState=([a-z]+)'), 'unit_file_state': last(r'UnitFileState=([a-z]+)'), 'mode': last(r'MODE=([a-z]+)')}
def observed_of(st):
    return {'service': {'name': st.get('name'), 'active_state': st.get('active_state'), 'enabled': st.get('unit_file_state') == 'enabled'}}
def library_gate(observed):
    from lab.fault_fixtures import load_fixtures, validate_fixture
    from lab.fault_oracle import evaluate
    from lab.systemd_collector import parse_show
    from src.lifthrasir import recipes, policy, approval
    out = {}
    fx = [f for f in load_fixtures() if f['fault_id'] == 'F01'][0]
    out['fixture_errors'] = validate_fixture(fx)
    out['oracle_before'] = evaluate(observed, fx['expected_symptoms'], fx.get('abstain_when'))
    created = datetime.now(timezone.utc)
    plan = recipes.instantiate('rec-lab-guest-config-fix', plan_id='plan-f01-lab-fix', incident_id='inc-f01-lab', hypothesis_ids=['hyp-f01-config'], bindings={'guest': GUEST_NAME, 'config_path': CONF, 'setting': 'MODE', 'value': 'ok', 'unit': UNIT}, created_at=created.strftime('%Y-%m-%dT%H:%M:%SZ'), expires_at=(created + timedelta(minutes=30)).strftime('%Y-%m-%dT%H:%M:%SZ'))
    out['plan'] = plan
    req = {'plan': plan, 'identity': {'principal_id': 'lifthrasir-keeper', 'kind': 'agent', 'authenticated': True}, 'context': {'evaluated_at': now_iso(), 'consent_mode_granted': 'session-blanket', 'consent_granted_by_id': 'volmarr', 'consent_granted_by_kind': 'human', 'allowlist': [], 'resources': {CONF: {'scope': 'lab-guest', 'critical': False, 'sensitive': False}, UNIT: {'scope': 'lab-guest', 'critical': False, 'sensitive': False}}, 'precondition_snapshot': {p: True for p in plan['preconditions']}, 'emergency_stop_active': False}}
    dec = policy.evaluate_dict(req)
    out['policy_decision'] = dec.to_dict()
    bad = json.loads(json.dumps(plan)); bad['steps'] = [{'action_verb': 'modify_bootloader', 'target': {'type': 'config-file', 'name': CONF}}]
    req2 = json.loads(json.dumps(req)); req2['plan'] = bad
    out['policy_prohibited_outcome'] = policy.evaluate_dict(req2).outcome
    key = os.urandom(32)
    now = datetime.now(timezone.utc)
    ref = approval.mint_plan_reference(plan, key=key, now=now, ttl_seconds=900)
    ledger = approval.ApprovalLedger(); ledger.register(ref, key=key)
    out['approval_prompt'] = approval.render_approval_prompt(plan, ref)
    tampered = json.loads(json.dumps(plan)); tampered['title'] = 'tampered'
    try:
        ledger.decide(ref.reference_id, tampered, decision='approved', approver='keeper', now=now); out['tamper_refused'] = False
    except approval.ApprovalError as e: out['tamper_refused'] = type(e).__name__
    rec = ledger.decide(ref.reference_id, plan, decision='approved', approver='keeper-under-volmarr-standing-order', now=now)
    consumed = ledger.consume_for_execution(ref.reference_id, plan, resource=f'config-file:{CONF}', now=now)
    try:
        ledger.consume_for_execution(ref.reference_id, plan, resource=f'systemd-unit:{UNIT}', now=now); out['replay_refused'] = False
    except approval.ApprovalError as e: out['replay_refused'] = type(e).__name__
    out['approval'] = {'reference_id': ref.reference_id, 'digest': ref.digest, 'check_code': ref.short_check_code(), 'scope': list(ref.scope), 'decision': rec.decision, 'approver': rec.approver, 'consumed': consumed.consumed, 'key_note': 'throwaway HMAC key generated in-process, never stored (fixture-scale per APPROVAL-UX)'}
    out['gate_passed'] = bool(dec.outcome == 'ALLOW' and out['oracle_before'] == 'fault' and consumed.consumed and out['replay_refused'] and out['tamper_refused'] and out['policy_prohibited_outcome'] == 'DENY')
    return out
def main():
    EVID.mkdir(parents=True, exist_ok=True)
    ev = {'slice': 'activation-phase1-F-f01-loop', 'golden': str(GOLDEN)}
    ev['golden_sha256'] = sha(GOLDEN); ev['golden_sha_ok'] = ev['golden_sha256'] == GOLDEN_SHA
    if not ev['golden_sha_ok']: ev['error'] = 'golden sha mismatch; refusing'
    ser = None; pid = None; ok_all = False
    if ev['golden_sha_ok']:
        ser, pid, info = boot_to_shell(); ev['boot'] = info
        log(f"boot pid={pid} err={info.get('error')}")
    if ser is not None:
        try:
            inj = ['id', 'mkdir -p /etc/demo', "printf 'MODE=broken\\n' > " + CONF, "printf '%s\\n' '#!/bin/sh' '. /etc/demo/demo.conf' 'if [ \"$MODE\" = ok ]; then exec sleep 3600; fi' 'echo demo failing >&2' 'exit 1' > /usr/local/bin/lif-demo.sh", 'chmod 755 /usr/local/bin/lif-demo.sh', "printf '%s\\n' '[Unit]' 'Description=Lifthrasir lab demo F01' '' '[Service]' 'Type=simple' 'ExecStart=/usr/local/bin/lif-demo.sh' '' '[Install]' 'WantedBy=multi-user.target' > /etc/systemd/system/demo.service", 'systemctl daemon-reload', 'systemctl enable demo.service', 'systemctl reset-failed demo.service; systemctl start demo.service; sleep 2', 'echo INJ_STATE', 'systemctl show demo.service -p Id -p ActiveState -p SubState -p UnitFileState', 'cat ' + CONF, 'echo FINJ$((3+3))']
            ok1, seg1 = phase(ser, inj, 'FINJ6', 150)
            st1 = parse_state(seg1); ev['inject_ok'] = ok1; ev['state_after_inject'] = st1; ev['inject_tail'] = seg1[-2500:]
            obs1 = observed_of(st1); ev['observed_before'] = obs1
            from lab.systemd_collector import parse_show
            ev['collector_parse_show'] = parse_show(seg1)
            log(f"inject state={st1}")
            gate = library_gate(obs1); ev['gate'] = gate
            log(f"oracle_before={gate.get('oracle_before')} policy={gate.get('policy_decision', {}).get('outcome')} gate={gate.get('gate_passed')}")
            if gate.get('gate_passed'):
                fix = ["sed -i 's/^MODE=.*/MODE=ok/' " + CONF, 'systemctl restart demo.service; sleep 2', 'echo FIX_STATE', 'systemctl show demo.service -p Id -p ActiveState -p SubState -p UnitFileState', 'cat ' + CONF, 'echo FFIX$((4+4))']
                ok2, seg2 = phase(ser, fix, 'FFIX8', 120)
                st2 = parse_state(seg2); ev['fix_ok'] = ok2; ev['state_after_fix'] = st2; ev['fix_tail'] = seg2[-2000:]
                from lab.fault_oracle import evaluate
                from lab.fault_fixtures import load_fixtures
                fx = [f for f in load_fixtures() if f['fault_id'] == 'F01'][0]
                obs2 = observed_of(st2); ev['observed_after_fix'] = obs2
                ev['oracle_after_fix'] = evaluate(obs2, fx['expected_symptoms'], fx.get('abstain_when'))
                log(f"fix state={st2} oracle_after={ev['oracle_after_fix']}")
                rb = ["sed -i 's/^MODE=.*/MODE=broken/' " + CONF, 'systemctl restart demo.service; sleep 2', 'echo RB_STATE', 'systemctl show demo.service -p Id -p ActiveState -p SubState -p UnitFileState', 'cat ' + CONF, 'echo FRB$((5+5))']
                ok3, seg3 = phase(ser, rb, 'FRB10', 120)
                st3 = parse_state(seg3); ev['rollback_ok'] = ok3; ev['state_after_rollback'] = st3; ev['rollback_tail'] = seg3[-2000:]
                obs3 = observed_of(st3); ev['observed_after_rollback'] = obs3
                ev['oracle_after_rollback'] = evaluate(obs3, fx['expected_symptoms'], fx.get('abstain_when'))
                ev['rollback_note'] = 'In-guest undo: faulty setting restored + unit restarted; pre-repair failed state verified. Disposable overlay is also deleted at driver end (recipe rollback reset_lab_guest).'
                log(f"rollback state={st3} oracle_rb={ev['oracle_after_rollback']}")
                ev['qga_ping_before_poweroff'] = qga_ping(info['qga_sock'])
                ev['ssh_tcp_before_poweroff'] = ssh_probe()
                ok_all = bool(ev['oracle_after_fix'] == 'no_fault' and ev['oracle_after_rollback'] == 'fault' and st2.get('mode') == 'ok' and st3.get('mode') == 'broken' and st2.get('active_state') == 'active' and st3.get('active_state') == 'failed')
            ser.send('poweroff'); ser.drain(3)
        finally:
            ser.close()
        for _ in range(12):
            if not Path(f'/proc/{pid}').exists(): break
            time.sleep(5)
        ev['stopped'] = True if not Path(f'/proc/{pid}').exists() else stop_vm(pid)
    ev['loop_proven'] = ok_all
    ev['golden_sha_after'] = sha(GOLDEN); ev['golden_unchanged'] = ev['golden_sha_after'] == GOLDEN_SHA
    OVERLAY.unlink(missing_ok=True)
    p = EVID / 'sliceF-evidence.json'; p.write_text(json.dumps(ev, indent=2))
    shutil.copyfile(p, SEAT / 'lab' / 'evidence' / 'sliceF-evidence.json')
    print(f'EVIDENCE={p}'); print('SLICEF_OK' if ok_all and ev['golden_unchanged'] else 'SLICEF_INCOMPLETE')
    return 0 if ok_all else 2
if __name__ == '__main__': raise SystemExit(main())
