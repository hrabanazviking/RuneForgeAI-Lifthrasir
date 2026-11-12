# Lifthrasir Activation — Campaign State (living file)

**Order:** Volmarr, by voice, 2026-11-12 — put Lifthrasir into action on
purpleraider (deployed live, improving the machine); improvements flow to
hrabanazviking/RuneForgeAI-ASUS-z13-Linux-Fixes ONLY with zero
self-identifying information (fail-closed scrub gate).

**Seat:** ~/lifthrasir-forge (RuneForgeAI-Lifthrasir). **Plan:**
ACTIVATION_PLAN.md (sha256 3ac37f01b143061390193ab1ceebf6bf84baf91135e152a33b23ac7b58aaa468).
**Keeper:** `lifthrasir-activation-keeper` — 10-minute interval, created
2026-11-12 ~10:07 EST, first run 10:17:58 EST, 3600 s budget. Keeper law:
it CONTINUES stopped work slice by slice; it is not a watcher.

**Method note:** slice A was executed by the activation coordinator
running the six Mythic Engineering roles sequentially. No sub-agent
workers are claimed for slice A.

---

## Phase tracker

- **Phase 1 — Lab MVP loop in a disposable VM: IN PROGRESS.** Entry
  criteria MET 2026-11-12 (see slice A log). Slice B (2026-11-12) wired
  the real runner, built the golden qcow2 from the pinned ISO, and
  proved real boot/reset/boot. Slice C (2026-11-12) proved the guest access path: serial-console login + a working shell inside the live guest.
  Next is slice D (Calamares unattended install -> installed golden), then
  the F01 fault loop inside the guest.
- **Phase 2 — Host observe + propose: NOT STARTED.** Blocked on Phase 1
  exit evidence, by design.
- **Phase 3 — Approval-gated repair classes: NOT STARTED.** Blocked on
  Phase 2 exit evidence + Volmarr seeing the broker design.
- **Phase 4 — Upstream pipeline live: NOT STARTED.** Design is written
  (ACTIVATION_PLAN.md §3). Stop condition for the whole campaign: loop
  live + first scrubbed dossier round published with a ZERO-finding
  scrub report; then the keeper reports completion and awaits orders.

---

## Slice A log — 2026-11-12 (coordinator)

1. **Capability census: DONE.** Verdict: complete deterministic core as
   real tested Python (~28,800 LOC, 44 modules, suite 1505/0 at banking)
   but fixture-fed library code — one read-only entry point
   (`ui/heimdall_cli.py`, reads a fixture JSON), no observer daemon, no
   broker process, no systemd units, no host installer, no VM ever
   booted. Full evidence table: ACTIVATION_PLAN.md §1.
2. **Activation plan: DONE.** ACTIVATION_PLAN.md — 4 phases with
   entry/exit evidence + the invariant each leans on; upstream pipeline
   design (dossier format, two-layer fail-closed scrub gate, fixes-repo
   target at `rounds/lifthrasir-<date>-<slug>/`, push mechanics).
3. **Keeper: CREATED** (see header). Checked first: no existing
   lifthrasir-activation keeper existed.
4. **Phase 1 setup: DONE + VERIFIED** (detached job, log
   PHASE1_SETUP.log, finished 2026-11-12 10:08:07 EST):
   - `qemu-system-x86` + `qemu-utils` + `ovmf` installed natively via apt
     (exit 0). QEMU 11.0.3 at /usr/bin/qemu-system-x86_64. (The census
     gap — qemu-img present, qemu-system absent — is closed.)
   - Kubuntu 24.04.5 ISO downloaded to
     /mnt/vault/lifthrasir-lab/kubuntu-24.04.5-desktop-amd64.iso
     (5,457,694,720 bytes) and **sha256-verified against the pinned
     recipe: OK** (ae59e59c…c1d6). Bulk on the vault per the storage law.
   - KVM smoke test PASSED: a test VM ran under `-accel kvm` until the
     5 s timeout stopped it; no KVM initialisation errors. /dev/kvm +
     AMD SVM confirmed; host has 32 threads / ~118 GiB RAM free.
   - Host untouched otherwise; Volmarr's session undisturbed; no GPU
     use; no reboots.

## Invariants watch (standing)

- No autonomous bootloader/kernel/firmware/partition/encryption/home/
  package-trust/SSH/firewall mutation — none attempted, none planned.
- Experiments in the disposable VM only; no Docker (none used); no
  fingerprint anything (none).
- Kill-switch armed from Phase 1 (drilled per phase); quotas in force
  for any live component; lab capped at 8 vCPU / 16 GiB, CPU-only,
  one VM at a time, pauses while sibling keepers bank.
- Upstream: nothing has been pushed to the fixes repo by this campaign
  yet; the scrub gate is design-complete, implementation is a Phase 1–2
  build slice, and the first dossier will go to Volmarr for review.

---

## Keeper tick - 2026-11-12 10:17 EST (keeper run 1)

Method note: keeper ran the six Mythic Engineering roles sequentially; no sub-agent workers are claimed. Work had stopped after slice A (no lab processes), so the keeper continued with the next Phase 1 slice.

### Slice B - real runner + golden qcow2 + real boot/reset cycle: DONE

- lab/real_runner.py (new): SubprocessRunner, the real counterpart to FakeRunner, in its own module. No shell; argv0 allowlist (qemu-img, qemu-system-x86_64, rm); empty/NUL argv refused; per-call timeout; every call recorded for evidence. Tests in tests/test_real_runner.py (4 tests).
- lab/build_golden.py (new): verifies pinned ISO sha256 (streaming), converts raw to qcow2 golden on the vault, drives VMWorkflow + real runner through create, boot, reset, boot, delete, writes evidence pack.
- Evidence: vault /mnt/vault/lifthrasir-lab/evidence/sliceB-evidence.json; copy banked at lab/evidence/sliceB-evidence.json. ISO sha OK vs pin; golden.qcow2 5457575936 bytes, sha256 a5d8572769a1d147d2a29e2cc78de548010c2f97c6a4c40c1280f8f7061e99ac; boot1 and boot2 both QMP running, alive after 10s, guest CPU +499 ticks in 5s each, stopped cleanly; workflow log create/reset, delete proven by recorded rm rc=0 and overlay_deleted true; caps honoured (4 vCPU / 4 GiB, one VM, CPU-only); host untouched, session undisturbed, no QEMU left running.
- Suite: 1509 passed / 0 failed (1505 at slice A + 4 new).
- Honest limitation: golden is the converted LIVE ISO, not an installed system. Phase 1 exit NOT met: fault loop inside the guest, installed-system golden, and kill-switch drill remain later Phase 1 slices.
- Next slice (C): guest access path (serial/SSH into live guest or Calamares unattended-install research), then the F01 fault loop inside the guest.
- Invariants: no host mutation beyond lab files; no Docker; no fingerprint; nothing pushed to the fixes repo; scrub gate still design-only.

---

## Keeper tick - 2026-11-12 10:27 EST (keeper run 2)

Method note: keeper ran the six Mythic Engineering roles sequentially; no sub-agent workers are claimed. Work had stopped after slice B (no lab processes), so the keeper continued with the next Phase 1 slice.

### Slice C - guest access path (serial console) + unattended-install research: DONE

- lab/guest_access.py (new): direct-kernel boot argv (kernel/initrd extracted from the pinned ISO), console=ttyS0 serial console over a QEMU chardev socket with logfile capture, QGA virtio-serial channel wired, caps enforced (<=8 vCPU / <=16 GiB); parse_serial_log + access_verdict grading. Tests in tests/test_guest_access.py (4 tests).
- lab/run_sliceC.py (new) driver + evidence: vault /mnt/vault/lifthrasir-lab/evidence/sliceC-evidence.json; copy banked at lab/evidence/sliceC-evidence.json. ISO sha OK vs pin; kernel 16992648 B / initrd 90599405 B extracted via isoinfo.
- REAL PROOF: the guest booted to a serial login prompt; interactive login as the casper live user kubuntu (empty password) succeeded; commands ran INSIDE the guest: id -> uid=1000(kubuntu), uname -r -> 7.0.0-31-generic, marker LIFTHRASIR_GUEST_OK printed (serial log + transcript tail in the evidence pack). Final verdict: shell. VM stopped cleanly; overlay deleted; no QEMU left running; caps honoured (4 vCPU / 4 GiB, CPU-only, nice 10); host untouched, session undisturbed.
- QGA probe: answered=false (TimeoutError) - HONEST result: the live image ships no qemu-guest-agent and no openssh-server (ISO manifest grep: calamares 3.3.5 + openssh-client only). QGA/SSH light up only on the installed golden, whose pinned package set (packages.txt) already names qemu-guest-agent + openssh-server.
- Grading note: boot markers kernel_started/casper/systemd_reached read false because this boot passed `quiet`; login + shell are the operative proof. APPEND no longer passes `quiet` from this banking on, so future transcripts grade fully; the evidence pack preserves the exact argv actually used in this run.
- lab/UNATTENDED_INSTALL.md (new): Calamares unattended road for slice D (config CD + settings.conf design; module names to be read from the live guest at runtime, never assumed; risks). No unattended-install claim is made yet.
- Suite: 1513 passed / 0 failed (1509 at slice B + 4 new).
- Phase 1 exit NOT met: installed-system golden (slice D), the F01 fault loop inside the guest, and the kill-switch drill remain.
- Next slice (D): Calamares unattended install -> golden-installed.qcow2; boot it; verify serial + QGA + SSH; snapshot/reset proof; then the F01 fault loop.
- Invariants: lab only; no host mutation beyond lab files; no Docker; no fingerprint; nothing pushed to the fixes repo; scrub gate still design-only.
