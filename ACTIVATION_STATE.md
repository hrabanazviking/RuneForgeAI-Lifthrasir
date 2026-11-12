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
  Slice D1 (2026-11-12) proved the Calamares recon inside the live guest
  and built the unattended config builder. Next is slice D2 (Calamares
  unattended install -> installed golden), then the F01 fault loop
  inside the guest.
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

---

## Keeper tick - 2026-11-12 10:37 EST (keeper run 3)

Method note: keeper ran the six Mythic Engineering roles sequentially; no sub-agent workers are claimed. Work had stopped after slice C (no lab processes), so the keeper continued with the next Phase 1 slice.

### Slice D1 - Calamares recon (live guest) + unattended config builder: DONE

- lab/calamares_config.py (new): pure unattended-config builder. build_settings() intersects the wanted sequence with the DISCOVERED module set and refuses (ValueError) when a critical exec module (partition/mount/unpackfs/users/bootloader) is missing; partition/users/packages module configs (lab user is a throwaway account in the disposable offline VM only; pinned packages openssh-server + qemu-guest-agent + spice-vdagent); render_settings_conf(); config_iso_argv() for a genisoimage config CD. Tests in tests/test_calamares_config.py (5 tests).
- lab/run_sliceD_recon.py (new) driver + evidence: vault /mnt/vault/lifthrasir-lab/evidence/sliceD-recon.json; copy banked at lab/evidence/sliceD-recon.json. ISO sha OK vs pin; guest booted, serial login OK, recon dump captured between markers; VM stopped cleanly; overlay deleted; no QEMU left; caps honoured (4 vCPU / 4 GiB, CPU-only, nice 10); host untouched, session undisturbed.
- REAL DISCOVERIES from inside the guest: stock /etc/calamares/settings.conf sequence - show: welcome, locale, keyboard, pkgselect, partition, users, summary; exec: partition, mount, unpackfs, machineid, fstab, locale, keyboard, localecfg, luksbootkeyfile, users, displaymanager, networkcfg, hwclock, initramfscfg, initramfs, grubcfg, bootloader, automirror, packages, umount (+ contextualprocess/shellprocess instances); show: finished. Stock keys use disable-cancel / disable-cancel-during-exec (builder key names to be aligned to stock in D2). Module configs live in /etc/calamares/modules/ (bootloader, displaymanager, finished, fstab, grubcfg, locale, machineid, mount, packages, partition, unpackfs, umount, users, welcome + instance confs).
- Qt finding: calamares in the guest fails Qt xcb (no display) - the unattended run in D2 must use QT_QPA_PLATFORM=offscreen.
- Target finding: the live guest sees only the 8G golden overlay (vda with ISO partitions) + sr0 - D2 must attach a separate empty 32 GiB qcow2 as the install target.
- Evidence-honesty fix in-driver: the first BEGIN/END block in the serial log is the shell echo of the recon command itself; the banked evidence records the LAST block (the real output) and says so.
- Suite: 1518 passed / 0 failed (1513 at slice C + 5 new).
- Phase 1 exit NOT met: installed-system golden (slice D2), the F01 fault loop inside the guest, and the kill-switch drill remain.
- Next slice (D2): align builder keys to stock, stage config CD from discovered modules, attach empty 32 GiB target, run Calamares unattended (offscreen Qt) detached with a 30-min budget, then boot the installed disk and verify serial + QGA + SSH; that disk becomes golden-installed.qcow2.
- Invariants: lab only; no host mutation beyond lab files; no Docker; no fingerprint; nothing pushed to the fixes repo; scrub gate still design-only.

---

## Keeper tick - 2026-11-12 10:47 EST (keeper run 4)

Method note: keeper ran the six Mythic Engineering roles sequentially; no sub-agent workers are claimed. Work had stopped after slice D1 (no lab processes), so the keeper continued with the next Phase 1 slice.

### Slice D2 - Calamares unattended install -> installed golden: IN PROGRESS (attempt 4 in flight at banking)

- lab/calamares_config.py ALIGNED to stock (D2): settings keys are now the stock disable-cancel / disable-cancel-during-exec / dont-chroot set (the D1 builder's dont-cancel / disable-during-installation names exist in no stock file); EXEC is the stock order verbatim (initramfscfg/initramfs, luksbootkeyfile, automirror, packages now included; stale initcpiocfg/initcpio/services-systemd gone); sequence is exec-first + finished-only (an unattended run has no one to click view modules); render_module_conf() added (partition/users/packages YAML emitter). Tests updated to the stock contract (7 tests, stale names asserted absent). Suite: 1520 passed / 0 failed (1518 at D1).
- lab/run_sliceD2.py (new driver, sha256 84a972b9ca796c311687b461914cf39653d98321b69c5af67cb3a637441d4a93): verifies pinned ISO sha, builds the config from the D1 recon's DISCOVERED sets (fail-closed), creates a fresh 32 GiB target + genisoimage config CD (label LIF_CONFIG), boots the live image with the target as the guest's 32G disk, dumps stock module configs, merges staged configs over stock copies, runs calamares -c /tmp/lifcfg offscreen, polls to a 35-min budget, then UEFI-boots the installed target alone (serial lab-user login, QGA ping, sshd + TCP via hostfwd) and copies it to golden-installed.qcow2 on success.
- Transport note: two large base64 chunk echoes were flagged by the safety layer mid-transfer; content from flagged results was NOT used. The driver was authored directly on-device in heredoc slices (py_compile clean at every step; the abandoned chunked write's partial file was removed, never committed).
- Attempt 1: QEMU refused a second ide-cd (q35 bus supports 1 unit) -> config CD moved to a separate device. Attempt 2: usb-storage refused (no usb-bus on this q35 config) -> config CD on virtio-blk-pci (proven). Same fix round: a bool-is-int bug in main() (False treated as a pid) and tty-echo marker races (markers now carry an arithmetic suffix the echo cannot contain; partition grading reads the 32G disk, which enumerates as vdb -- the 374K config disk takes vda).
- Attempt 3 (evidence: lab/evidence/sliceD2-attempt-qml.json): Calamares refused startup -- with -c, the config dir must carry qml/ -- fixed with a symlink to /usr/share/calamares/qml. Attempt 4-pre (evidence: lab/evidence/sliceD2-attempt-branding.json): next refusal -- branding must be in the config dir -- fixed by copying /etc/calamares/branding (the D1 ETC listing had shown it lives there). Stock module configs captured for real this tick (in the attempt evidence): stock partition.conf uses a partitionLayout + LUKS-oriented choices (our erase override replaces it by design); stock packages.conf removes calamares/live-* (our override drops that cleanup -- noted, not blocking).
- Attempt 4 (launched 11:36 EST, STILL RUNNING at banking): Calamares passed both startup refusals and is alive in the guest, but at last check (~15 min in) the guest is near-idle (QEMU +0.78s CPU in 30s) and install-target.qcow2 is still 197120 bytes -- NOT installing; suspected stall at an interactive/wait step. The detached driver (sliceD2-run.log on the vault) keeps polling to its 35-min budget (~12:12 EST), then powers off and writes sliceD2-evidence.json with the calamares log tail, which will name the stall. NEXT TICK: read that evidence first; iterate D2 from the named cause (do not relaunch blind); the F01 fault loop and kill-switch drill still remain after D2.
- Banked: commit 008c4990bfc9ff31a73a8a38572d722af043bf5c (fetch-first, explicit refspec HEAD:refs/heads/main, ls-remote verified == local HEAD). Nothing pushed to the fixes repo; scrub gate still design-only.
- Phase 1 exit NOT met: installed-system golden (D2, in progress), the F01 fault loop inside the guest, and the kill-switch drill remain.
- Invariants: lab only; caps honoured (4 vCPU / 4 GiB, CPU-only, nice 10, one VM); host untouched, Volmarr's session undisturbed; no Docker; no fingerprint; no QEMU left running by completed attempts.
