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
  criteria MET 2026-11-12 (see slice A log). The loop itself has not run
  yet: next slice wires `lab/vm_workflow.py` to a real runner, builds the
  golden qcow2 (unattended install from the pinned ISO), and proves
  snapshot/reset.
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
