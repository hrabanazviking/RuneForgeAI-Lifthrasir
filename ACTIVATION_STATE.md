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

- **Phase 1 — Lab MVP loop in a disposable VM: COMPLETE (2026-11-12, keeper run 11).** Entry
  criteria MET 2026-11-12 (see slice A log). Slice B (2026-11-12) wired
  the real runner, built the golden qcow2 from the pinned ISO, and
  proved real boot/reset/boot. Slice C (2026-11-12) proved the guest access path: serial-console login + a working shell inside the live guest.
  Slice D1 (2026-11-12) proved the Calamares recon inside the live guest
  and built the unattended config builder. Next is slice D2 (Calamares
  unattended install -> installed golden), then the F01 fault loop
  inside the guest. Slice D3 (2026-11-12, keeper run 8) COMPLETED the
  installed golden via the scripted manual road: golden-installed.qcow2
  (9.2G, sha256 d9edd18c...) boots UEFI, serial lab login + ssh +
  qemu-guest-agent all active inside the guest. Slice E (2026-11-12,
  keeper run 9) PROVED reset-to-golden twice against the installed
  golden (dirty marker -> overlay deleted/recreated -> marker absent,
  services active; golden sha unchanged) and fixed the D3 verify-
  ordering blemish in its driver (QGA/SSH probed BEFORE poweroff).
  Slice F (2026-11-12, keeper run 10) PROVED the F01 fault loop
  inside the guest end-to-end (detect -> propose -> approve -> fix ->
  verify -> rollback, evidence pack banked). Slice G (2026-11-12,
  keeper run 11) PROVED the kill-switch drill at fixture level AND
  against the live lab loop (see run 11 entry). **Phase 1 COMPLETE
  2026-11-12**: every exit item is banked with its evidence pack --
  F01 fault loop inside the VM (slice F), reset-to-golden proven
  twice (slice E), kill-switch halts the loop mid-run (slice G),
  host untouched throughout (lab-only work, all slices).
- **Phase 2 — Host observe + propose: IN PROGRESS (started
  2026-11-12, keeper run 12, slice H).** Observer design checked
  against docs/CONFINEMENT-REVIEW.md (docs/OBSERVER-DESIGN.md);
  lifthrasir-observer.service user unit ACTIVE on purpleraider
  (read-only, hardened, quotas in force), writing cycles to
  ~/.local/state/lifthrasir/. Phase 2 exit needs 7 days of observer
  operation with zero host mutations — the clock started
  2026-11-12 14:11 EST at the first unit run. NEXT: daily digest
  review + continued operation; Phase 3 stays blocked on Phase 2
  exit + Volmarr seeing the broker design.
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

---

## Keeper tick - 2026-11-12 11:47 EST (keeper run 5)

Method note: keeper ran the six Mythic Engineering roles sequentially; no sub-agent workers claimed. Work had NOT stopped: slice D2 attempt 4 driver (pid 920324) and QEMU (pid 920339) were both alive, so no new slice was launched and no second VM was started (one-VM law).

- Verified at 11:47-11:48 EST: driver log last line remains [11:37:22] calamares launched; polling until it exits or budget ends. Serial log shows repeated CALA_RUNNING polls.
- Stall evidence strengthened: install-target.qcow2 still 193K (unchanged from launch); QEMU CPU time static at 00:00:54 over a 5s probe (guest near-idle). Calamares is running in guest but not installing.
- Driver source check: branding staging line in lab/run_sliceD2.py is correct (/tmp/lifcfg/branding); no new code defect claimed from the serial echo rendering.
- Action taken: NONE against the running attempt - do not relaunch blind, per run-4 instruction. The driver keeps polling to its 35-min budget (~12:12 EST), then should power off and write sliceD2-evidence.json with the calamares log tail naming the stall cause.
- NEXT TICK: read sliceD2-evidence.json / sliceD2-run.log FIRST; iterate D2 from the named cause in the calamares log. F01 fault loop and kill-switch drill still remain after D2.
- Phase 1 exit NOT met. Invariants: lab only, caps honoured, host/session untouched, no Docker, no fingerprint, nothing pushed to fixes repo.

---

## Keeper tick - 2026-11-12 11:49-12:35 EST (keeper run 6)

Method note: keeper ran the six Mythic Engineering roles sequentially; no sub-agent workers claimed. Run 5's state entry was found appended but UNBANKED; this tick banks it with its own.

### Slice D2 attempts 4-6: stall root-caused; attempt 7 in flight

- Attempt 4 rode out its 35-min budget untouched (one-VM law; driver pid 920324, QEMU 920339). At 12:12:22 EST the budget expired; the driver collected its log, powered off, wrote evidence, exited clean (no QEMU left). Verdict: calamares_exited=False, target_partitioned=False, SLICED2_INCOMPLETE. Attempt-4 cala.log tail held ONLY three Qt XDG_RUNTIME_DIR warnings - Calamares hung right after Qt init with zero module logging (evidence: lab/evidence/sliceD2-attempt4-evidence.json, banked this tick).
- Driver hardened for attempt 5 (run_sliceD2.py sha 78a4f5ae): calamares launched with -d debug + XDG_RUNTIME_DIR=/tmp/runtime-root (dir staged as root, mode 700); polls now record cala.log size + host-side target size every cycle and declare a stall after 4 unchanged polls (~3.5 min instead of 35); collection tail widened to 6000. Suite still 1520 passed / 0 failed.
- Attempt 5 (12:17-12:24 EST): cala.log reached 11219 bytes in the first poll (debug logging works), then froze; stall detector broke at 12:21:58 and collected. BUT the collection markers had no arithmetic suffix, so the tty echo of the collection command satisfied wait_for before the real output arrived - evidence captured only the echo. That marker-race (the same class fixed in attempt 3) is a proven driver bug, fixed for attempt 6 (suffixed LOG_END2/POST_END2 markers + extra drain; sha c6440559). Evidence: lab/evidence/sliceD2-attempt5-evidence.json (poll_history + stall_detected=true are its real content).
- Attempt 6 (12:26-12:32 EST): same stall signature (cala.log 11153 bytes, frozen from poll 1; target 197120 throughout), and the fixed collection captured the full log tail. ROOT CAUSE NAMED from the guest debug log (lab/evidence/sliceD2-attempt6-evidence.json): Calamares loads its modules, reports 9 view steps loaded, runs the requirements checker, then sits in the offscreen GUI on the partition ChoicePage - calculateNextEnabled: No partitioning choice has been made yet; applyActionChoice InstallChoice NoChoice none - followed by a GeoIP lookup from a view step, then silence. It is waiting for an interactive partitioning choice that no one will ever make: the unattended exec sequence never auto-started the install.
- Attempt 7 (launched 12:34 EST, IN FLIGHT at banking): collection tail widened 6000 -> 12000 (the whole ~11 KB log) so the next evidence includes the log HEAD - which settings file and sequence Calamares actually parsed - to decide the fix (candidate roads for next tick, in order: (1) if our settings.conf was not the one parsed, fix delivery of it; (2) restore the stock show sequence with prompt-install false + pre-seeded partition choice via the partition view module config (initialPartitioningMode/initialSwapChoice already set - check why the ChoicePage still defaults to NoChoice; the staged partition.conf may need the full stock key set, e.g. defaultPartitionType / efi keys, to yield a choice); (3) only if Calamares proves unusable unattended, fall back to a scripted manual install road (partition + unpack by hand inside the guest) and record the deviation against the LIF-0101 recipe explicitly).
- Phase 1 exit NOT met: installed golden (D2), F01 fault loop, kill-switch drill remain. Invariants: lab only; caps honoured (4 vCPU / 4 GiB, CPU-only, nice 10, one VM at a time); host and Volmarr session untouched; no Docker; no fingerprint; nothing pushed to the fixes repo; scrub gate still design-only.

---

## Keeper tick - 2026-11-12 12:36-12:57 EST (keeper run 7)

Method note: keeper ran the six Mythic Engineering roles sequentially; no sub-agent workers claimed. Work had NOT stopped at tick start: slice D2 attempt 7 (driver pid 942595, QEMU 942622, launched 12:34 by run 6) was in flight, so no second VM was started (one-VM law). The keeper monitored attempt 7 to completion, analysed its evidence, then continued with attempts 8-9.

### Slice D2 attempt 7: DONE (stall, full-log capture worked)

- Stall detector fired 12:38:40 (cala.log frozen 11219, target 197120, 5 polls); collection + poweroff completed clean 12:40:59, SLICED2_INCOMPLETE, no QEMU left. Evidence banked: lab/evidence/sliceD2-attempt7-evidence.json (20858 B, whole 11219 B log captured).
- LOG HEAD VERDICT (the question attempt 7 was launched to answer): Calamares DID parse our settings file ("Using Calamares settings file at /tmp/lifcfg/settings.conf"), ruling out candidate road (1) (settings delivery). It also flagged two missing required keys: hide-back-and-next-during-exec and quit-at-end. The stall signature was identical: requirements checked, ChoicePage applyActionChoice NoChoice, GeoIP, silence.

### Slice D2 attempt 8: ABORTED PRE-BOOT (driver bug, fixed) + attempt 9: DONE (stall, new signature)

- Builder changes for attempt 8 (lab/calamares_config.py sha 6dde8d36): sequence restored to the documented Calamares semantics (show -> exec -> show finished; the official settings.conf documentation states an exec phase enqueues jobs only from viewmodules in the IMMEDIATELY PRECEDING show phase, so the D2 exec-first sequence could never enqueue partition/users jobs - root cause of attempts 4-7, now named from documentation, not just observation); settings gained hide-back-and-next-during-exec + quit-at-end; partition.conf is now a full stock-merged file (efiSystemPartition, luksGeneration luks2, userSwapChoices [none, file], defaultPartitionTableType gpt; LUKS layout dropped, erase/no-encryption); users.conf gained stock passwordRequirements; packages.conf restored the stock remove ops (live-* / calamares / etc) plus the pinned install set. Tests updated to the new contract; suite 1520 passed / 0 failed.
- Attempt 8 launch ABORTED at config staging, no VM booted: stage_config hardcoded sequence[0]["exec"], which the sequence change broke (KeyError 'exec'; evidence written with that error). Bug fixed in lab/run_sliceD2.py (sha df612b42; exec phase located generically), staging re-proven, suite still 1520/0. The relaunched run is attempt 9.
- Attempt 9 (12:49-12:55 EST): cala.log grew to 13414 (full show sequence loads), then froze; stall detector fired 12:53:15; clean collection/poweroff 12:55:33, SLICED2_INCOMPLETE, no QEMU left. Evidence: lab/evidence/sliceD2-attempt9-evidence.json (21112 B). Log verdict: requirements now gathered from welcome (5) + partition (1), all mandatory satisfied - and the wizard then sits at the START of its show phase awaiting Next navigation. In offscreen serial-only operation no navigation can occur, stock Calamares 3.3.5 has no auto-advance, AND the partition pre-seed still constructs as NoChoice during page setup in both sequence shapes.

### Calamares unattended: PROVEN UNUSABLE in this lab configuration - road (3) taken

- Two independent blockers, each evidence-backed: (a) exec-first sequences never enqueue viewmodule jobs (official sequence semantics + attempts 4-7); (b) show-first sequences park the wizard on its first page with no auto-advance and a NoChoice partition pre-seed (attempt 9). Six booted attempts (4-7, 9, plus the qml/branding pre-attempts) is enough: per run 6's candidate list, road (3) is adopted.
- Deviation recorded precisely: LIF-0101 pins only the ISO (sha-verified) + the guest package set (packages.txt); it does not mandate Calamares. The Calamares assumption lived in lab/UNATTENDED_INSTALL.md (slice C research, explicitly unproven there) - that note now carries the disproof. The manual road still derives the golden from the pinned ISO and must land exactly the pinned package set, so the LIF-0101 pin is honoured in full.
- NEXT SLICE (D3, next tick): scripted manual install driver (lab/run_sliceD3.py), all inside the disposable guest via the proven serial path: GPT partition the 32 GiB target (EFI FAT32 /boot/efi + ext4 /), mount, unpack /cdrom/casper/filesystem.squashfs to the target (the unpackfs equivalent), chroot-configure (fstab by UUID, machine-id, locale/keyboard, lab user + hostname per calamares_config.py values, apt-install the pinned set openssh-server + qemu-guest-agent + spice-vdagent, update-initramfs, grub-install --efi + grub-mkconfig), poweroff, then the existing verify phase (UEFI boot, serial lab login, QGA ping, sshd banner) and golden-installed.qcow2 copy. Each step marker-checked over serial with an evidence pack, stall/timeout guards like D2. Then F01 fault loop + kill-switch drill remain for Phase 1 exit.
- Phase 1 exit NOT met: installed golden (now D3), F01 fault loop, kill-switch drill remain. Invariants: lab only; caps honoured (4 vCPU / 4 GiB, CPU-only, nice 10, one VM at a time); host and Volmarr session untouched; no Docker; no fingerprint; nothing pushed to the fixes repo; scrub gate still design-only.

---

## Keeper tick - 2026-11-12 12:57-13:35 EST (keeper run 8)

Method note: keeper ran the six Mythic Engineering roles sequentially; no sub-agent workers claimed. Work had stopped after run 7 (no lab processes), so the keeper continued with slice D3 (road 3, adopted run 7).

### Slice D3 probe: DONE

- lab/run_sliceD3_probe.py + evidence lab/evidence/sliceD3-probe.json (D3P_OK): live guest inventory -- sudo -n root OK; sfdisk/parted/mkfs.vfat/mkfs.ext4/unsquashfs/rsync/grub-install/update-grub/update-initramfs/chroot/apt-get all present (sgdisk missing, not needed); squashfs 4.3G at /cdrom/casper/filesystem.squashfs; NO pool debs for the pinned set on the ISO; apt sources name archive.ubuntu.com and a TCP probe to it returned NET_OK via QEMU user NAT -- the archive apt road is the install road. Target enumerates as vda alone, vdb with the config disk attached (D2 lesson) -- the install script auto-detects the unique 32G virtio disk in-guest, fail-closed (D3_NODEV).

### Slice D3 builders: DONE

- lab/manual_install.py (new): sfdisk GPT script (512M EFI + ext4 root), fstab builder (fail-closed on missing UUID), guest install script, chroot scripts, apt roads. full_install_script() = ONE root script riding a genisoimage config ISO (proven D2 transport): partition/format/mount/unpack (cp -a of the mounted squashfs), fstab+hostname from the live side, bind mounts, chroot (lab user, machine-id, locale, pinned apt set, GRUB EFI). Tests tests/test_manual_install.py: 8 tests.
- lab/run_sliceD3.py (new driver): fresh 32G target + fresh OVMF VARS (shared by install and verify boots so the GRUB NVRAM entry survives), stall detector, verify phase inherited from D2. Suite: 1528 passed / 0 failed (1520 + 8 new).

### Slice D3 attempt 1: install OK, verify FAIL (kernel-less golden) -- root-caused

- Install ran clean in ~2 min: ALL markers, apt installed openssh-server + qemu-guest-agent from the archive (policy-rc.d guard worked, services enabled), grub-install "No error reported". Evidence preserved as lab/evidence/sliceD3-attempt1-evidence.json.
- Verify FAILED (SLICED3_INCOMPLETE): OVMF loaded Boot0002 Ubuntu -> shimx64.efi, then nothing -- no serial login, QGA/SSH silent after 300 s. Root cause from the attempt-1 install log tail: update-grub found ONLY memtest86+ -- no linux image. The casper squashfs carries no kernel in /boot (the live kernel lives on the ISO outside the squashfs), so the unpacked target was kernel-less and GRUB had nothing to boot. Attempt 1 also had no serial console in the installed GRUB cmdline, which would have hidden a boot anyway.

### Slice D3 attempt 2: DONE -- installed golden PROVEN

- Fixes: apt installs linux-generic after the pinned set (kernel 6.8.0-149-generic; update-grub: "Found linux image: /boot/vmlinuz-6.8.0-149-generic" + initrd); GRUB_CMDLINE_LINUX_DEFAULT gains console=tty0 console=ttyS0,115200n8 (appended in chroot, later assignment wins); serial-getty@ttyS0 enabled; install script now logs ls of /mnt/sq/boot + target /boot after unpack. A first rendering of the GRUB fix as an unquoted sed was caught by bash -n / tests BEFORE launch and replaced -- no bad script ever ran in a guest.
- Evidence (lab/evidence/sliceD3-evidence.json, SLICED3_OK): install_done=True, all markers; verify boot reached serial login; login as lab succeeded; inside the INSTALLED guest: id uid=1000(lab), uname 6.8.0-149-generic, systemctl is-active ssh = active, qemu-guest-agent = active, ss LISTEN 0.0.0.0:22 + [::]:22; verify shell proven in 43 s. Golden copied: /mnt/vault/lifthrasir-lab/golden-installed.qcow2, 9.2G, sha256 d9edd18c4d0d8406038fc180ce6a177c9d7d16a0892f12263d791331bf192c90. No QEMU left; both boots stopped cleanly; caps honoured (4 vCPU / 4 GiB, CPU-only, nice 10, one VM at a time).
- Honest blemish: evidence fields qga_ping=False / ssh_tcp=False are a VERIFY-ORDERING BUG inherited from D2 (both are probed AFTER the serial poweroff is sent, so the guest is already going down). The in-guest service proof above supersedes them; the ordering fix (probe before poweroff) is owed in the next slice that touches the verify phase -- recorded here, not hidden.
- Phase 1 exit NOT met: snapshot/reset proof against the installed golden (twice), the F01 fault loop inside the guest, and the kill-switch drill remain. NEXT SLICE: reset-to-golden proof x2 against golden-installed.qcow2, then F01 fault loop (detect -> propose -> approve -> fix -> verify -> rollback inside the guest, evidence pack).
- Invariants: lab only; host and Volmarr session untouched; no Docker; no fingerprint; nothing pushed to the fixes repo; scrub gate still design-only.

---

## Keeper tick - 2026-11-12 13:27-13:42 EST (keeper run 9)

Method note: keeper ran the six Mythic Engineering roles sequentially; no sub-agent workers claimed. Work had stopped after run 8 (no lab processes), so the keeper continued with slice E (reset-to-golden proof x2, the next Phase 1 item named by run 8).

### Slice E - reset-to-golden proof x2: DONE

- lab/run_sliceE_reset.py (new driver): per round, fresh qcow2 overlay backed by golden-installed.qcow2 (sha verified d9edd18c... before and after), UEFI boot, serial lab login, dirty the guest (~/RESET_DIRTY marker + sync), poweroff, DELETE overlay, recreate fresh overlay from the golden, boot again, prove marker absent + ssh/qemu-guest-agent active. Caps honoured (4 vCPU / 4 GiB, CPU-only, nice 10, one VM at a time).
- D3 blemish FIXED in this driver: QGA ping + SSH banner are probed BEFORE poweroff is sent. In all four boots both probes returned True before poweroff (D3 evidence had them False purely from ordering).
- Attempt 1 (evidence preserved as lab/evidence/sliceE-attempt1-evidence.json): all four boots actually passed (clean transcripts show RESET_CLEAN2, services active, qga/ssh True) but the driver graded reset_proven=False - a grading bug of the known tty-echo class: the check searched the transcript tail for the plain marker name, which appears in the ECHO of the shell command itself. Fixed to the arithmetic-suffixed output form (RESET_DIRTY_STILL_THERE2), which the echo can never contain; attempt 2 re-ran the full proof.
- Attempt 2 (lab/evidence/sliceE-evidence.json, SLICEE_OK): round 1 dirty=True clean reset=True; round 2 dirty=True clean reset=True; reset_x2_proven=True; golden sha unchanged after; overlay deleted; no QEMU left. Suite: 1528 passed / 0 failed (unchanged - the driver is lab tooling, no new unit tests claimed).
- Phase 1 exit NOT met: the F01 fault loop inside the guest (detect -> propose -> approve -> fix -> verify -> rollback, evidence pack) and the kill-switch drill remain. NEXT SLICE (F): F01 loop in the guest - F01 fixture is a failed demo.service; inject inside the disposable guest only, observe via lab collectors/oracle, authorise one narrow reversible fix through policy+approval library path, apply, verify, roll back, evidence pack.
- Invariants: lab only; host and Volmarr session untouched; no Docker; no fingerprint; nothing pushed to the fixes repo; scrub gate still design-only.

---

## Keeper tick - 2026-11-12 13:43-13:52 EST (keeper run 10)

Method note: keeper ran the six Mythic Engineering roles sequentially; no sub-agent workers claimed. Work had stopped after run 9 (no lab processes), so the keeper continued with slice F (the F01 fault loop, named next by run 9).

### Slice F - F01 fault loop inside the guest: DONE

- lab/run_sliceF_f01.py (new driver): one disposable overlay boot of golden-installed.qcow2 (sha verified d9edd18c... before and after, unchanged); all fault work inside the guest only, via the proven serial root shell. Caps honoured (4 vCPU / 4 GiB, CPU-only, nice 10, one VM); QGA + SSH both True BEFORE poweroff; VM stopped cleanly; overlay deleted; no QEMU left.
- INJECT (F01 per lab/fixtures/F01.json): /etc/demo/demo.conf with MODE=broken, /usr/local/bin/lif-demo.sh (exits 1 unless MODE=ok), demo.service enabled + started. Observed in guest: Id=demo.service, ActiveState=failed, SubState=failed, UnitFileState=enabled, MODE=broken. Fixture validation: no errors. Independent oracle (lab/fault_oracle.py) verdict on the observed state: fault.
- PROPOSE: banked recipe rec-lab-guest-config-fix instantiated (recipes.instantiate) with bindings guest=lifthrasir-lab-F, config_path=/etc/demo/demo.conf, setting=MODE, value=ok, unit=demo.service -> plan-f01-lab-fix (L2, session-blanket; steps edit_config_in_guest + restart_unit_in_guest), catalog-validated at binding time.
- APPROVE (library path, host-side, before any fix was applied): policy engine (policy.evaluate_dict) returned ALLOW / ALL_CHECKS_PASSED (effective L2, consent session-blanket granted by human). Negative controls all refused as designed: a modify_bootloader plan -> policy DENY; a tampered plan (title edited) -> approval DigestMismatchError; a second consume of the approval -> ReplayError. Approval itself: HMAC plan reference minted (throwaway in-process key, never stored - fixture-scale per APPROVAL-UX, recorded honestly), registered, decided approved by keeper-under-volmarr-standing-order, consumed exactly once for config-file:/etc/demo/demo.conf with the full plan scope recorded.
- FIX + VERIFY: MODE=ok applied in guest + demo.service restarted -> ActiveState=active, SubState=running, MODE=ok; oracle verdict: no_fault.
- ROLLBACK: faulty setting restored in guest (MODE=broken) + restart -> ActiveState=failed again; oracle verdict: fault. The recipe rollback names reset_lab_guest; the in-guest inverse edit is the step-level undo and restores the exact pre-repair state, and the disposable overlay was additionally deleted at driver end - both recorded in the evidence pack, not conflated.
- Evidence: lab/evidence/sliceF-evidence.json (SLICEF_OK, loop_proven=True): full plan, policy decision, approval prompt + reference/digest/scope, per-phase guest states and transcript tails. The gate logic was smoke-proven host-side before the VM boot (same verdicts), so the single guest run was not a blind attempt.
- Honest blemish: the systemd-collector parse_show capture in the evidence carries ANSI escape suffixes (serial tty colour codes) on its values; the oracle grading used regex-extracted clean fields from the same transcript. The collector parse is supplementary evidence only.
- Suite: 1528 passed / 0 failed (unchanged - the driver is lab tooling, no new unit tests claimed, as with slice E).
- Phase 1 exit NOT met: only the kill-switch drill remains (halting the loop mid-run, per the Phase 1 exit evidence in ACTIVATION_PLAN.md). NEXT SLICE (G): kill-switch drill against the lab loop (killswitch.py machinery + campaign flag: engage mid-run, prove the loop halts and state is consistent, release, evidence pack). Phase 2 stays blocked on Phase 1 exit, by design.
- Invariants: lab only; host and Volmarr session untouched; no Docker; no fingerprint; nothing pushed to the fixes repo; scrub gate still design-only.

---

## Keeper tick - 2026-11-12 13:47-14:05 EST (keeper run 11)

Method note: keeper ran the six Mythic Engineering roles sequentially; no sub-agent workers claimed. Work had stopped after run 10 (no lab processes, no QEMU, no tmux), so the keeper continued with slice G (the kill-switch drill, named next by run 10). Machine idle at tick start (load 0.22); no sibling banking observed.

### Slice G - kill-switch drill: DONE -- Phase 1 exit COMPLETE

- lab/run_sliceG_killswitch.py (new driver, 252 lines): two-part drill, caps honoured (4 vCPU / 4 GiB, CPU-only, nice 10, one VM); golden sha256 d9edd18c... verified before and after, unchanged; evidence lab/evidence/sliceG-evidence.json (SLICEG_OK, drill_proven=True).
- Part 1 (host, fixture level, killswitch.py machinery): a worker loop thread ran under require_clear; engage_and_stop (actor keeper-sliceG) halted it at iteration 6 (KillSwitchEngaged). The registered sleeper fixture was terminated (report terminated=[pid], no SIGKILL escalation needed) and verified dead; an UNREGISTERED foreign sleeper was never signalled and stayed alive through the engage (cleaned up afterwards by its owner, this driver). A fresh KillSwitch instance over the same state dir still saw the halt (durable across restart); require_clear refused while engaged; hash-chained audit verified True before and after release. Journal recovery via RecoveryCoordinator while engaged: committed txn-committed-1 preserved byte-for-byte, in-flight txn-inflight-1 rolled back (undo steps in reverse order), prepared txn-prepared-1 expired, aborted txn untouched; second recovery changed nothing (idempotent). Release returned True and require_clear passed again.
- Part 2 (live lab loop): disposable overlay boot of golden-installed; guest heartbeat loop started (counter in /root/hb.txt advancing 3 -> 5 across probes); QGA ping + SSH banner both True BEFORE the halt. Campaign stop engaged mid-run (flag file /mnt/vault/lifthrasir-lab/STOP-G.flag + KillSwitch.engage on its own state dir); the driver loop saw the engage at cycle 0 and halted the loop: serial poweroff, VM stopped cleanly, overlay deleted. After VM down the halt was STILL engaged (durable) with audit chain True; then released and the flag file removed -- both verified absent/complete in the evidence pack.
- Host-untouched note (Phase 1 exit item): Part 1 touched only the lab state dirs on the vault plus this project's own fixture processes by design; Part 2 touched only the disposable guest overlay. No host config, journal, service, or session state was changed by this drill; Volmarr's seat0 session undisturbed; no Docker; no fingerprint; nothing pushed to the fixes repo; scrub gate still design-only (Phase 4).
- Suite: 1528 passed / 0 failed (unchanged -- the driver is lab tooling, no new unit tests claimed, as with slices E/F).
- PHASE 1 EXIT MET (all items, each with a banked evidence pack): F01 fault detect -> propose -> approve -> fix -> verify -> rollback inside the VM (slice F); reset-to-golden proven twice (slice E); kill-switch halts the loop mid-run (slice G); host untouched throughout Phase 1 (slices A-G, lab-only). Phase tracker updated: Phase 1 COMPLETE.
- NEXT SLICE (H, Phase 2 entry): observer design checked against docs/CONFINEMENT-REVIEW.md, then the first unprivileged systemd user-unit observer run (read-only host collectors -> ~/.local/state/lifthrasir/, proposals drafted as plan records only, NEVER executes; quotas bound it; kill-switch flag + documented command stops it; daily plain-language digest for Volmarr). Phase 2 exit needs 7 days of observer operation, so its clock starts when the unit first runs.

---

## Keeper tick - 2026-11-12 13:57-14:15 EST (keeper run 12)

Method note: keeper ran the six Mythic Engineering roles sequentially; no sub-agent workers claimed. Work had stopped after run 11 (Phase 1 complete, no observer, no lab processes), so the keeper continued with slice H, the Phase 2 entry named by run 11.

### Slice H - observer design + first unprivileged user-unit run: DONE -- Phase 2 STARTED

- docs/OBSERVER-DESIGN.md (new): design checked against docs/CONFINEMENT-REVIEW.md in its own recommendation order -- systemd hardening first (adopted, adapted to a user unit), cgroup v2 caps (adopted), probe-dont-presume (adopted: NO user-namespace assumption, the Ubuntu/AppArmor conditional row), Landlock second and LSM last honestly NOT claimed. Catalog v0.2 recorded as Phase 3 preparation.
- lab/host_observer.py (new): read-only live collectors (systemctl list-units --failed, df, /proc) via the LIF-0202/0203/0204 lab modules; writes ONLY inside ~/.local/state/lifthrasir/ (events.jsonl, latest.json, proposals.json, DIGEST.md); proposals are lifthrasir.plan.v0.1 records validated by approval.plan_digest, records only, never executed; STOP flag file or engaged KillSwitch halts a cycle before collecting. Tests tests/test_host_observer.py: 6 tests.
- units/lifthrasir-observer.service (new, banked template) installed to ~/.config/systemd/user/ and ENABLED + ACTIVE (pid 995441 at check): NoNewPrivileges yes, PrivateTmp, ProtectSystem strict, ProtectHome read-only with ReadWritePaths for exactly the state dir, CPUQuota 25pct, MemoryMax 512M, TasksMax 64, Nice 10, 300 s cycle. Its first confined cycle wrote cleanly. systemd-analyze verify on the template: no findings for this unit.
- BUG FOUND AND FIXED IN-SLICE: the first manual cycle drafted 20 critical proposals for snap squashfs mounts, which are read-only and 100pct full BY DESIGN (false incidents), with duplicate plan_ids across filesystem/inode alerts. Fix: alerts on squashfs mountpoints excluded in gather_live; build_proposals dedupes by plan_id (new test). The false cycle stays in events.jsonl as honest history. After the fix: manual cycle = observed, 0 proposals, honest non-issue (no failed units; root 9pct, vault 1pct).
- Kill-switch drill (scratch state dir): STOP flag -> cycle halted, nothing collected; flag removed -> observed. (The Phase 1 KillSwitch machinery drill remains slice G.)
- Evidence: lab/evidence/sliceH-evidence.json (SLICEH_OK). Suite: 1534 passed / 0 failed (1528 + 6 new).
- Phase 2 exit NOT met and not claimed: 7 days of observer operation with zero host mutations are required; the clock started 2026-11-12 14:11 EST. Host mutations this slice: none outside the observer state dir and the user-unit install itself; no broker; no root; Volmarr seat0 undisturbed; no Docker; no fingerprint; nothing pushed to the fixes repo.
- NEXT: keeper verifies the observer is still cycling each tick, reviews the digest, and logs any real proposal; Phase 3 remains blocked on Phase 2 exit evidence + Volmarr seeing the broker design.
