# Lifthrasir Activation Plan — purpleraider (2026-11-12)

**Order (Volmarr, by voice, 2026-11-12):** (1) put Lifthrasir into action on
purpleraider — deployed live, doing its work, improving the machine; (2) set it
so the improvements it makes are sent up to the Z13 fixes repo
(hrabanazviking/RuneForgeAI-ASUS-z13-Linux-Fixes) PROVIDED they carry no
self-identifying information.

**Seat:** ~/lifthrasir-forge (hrabanazviking/RuneForgeAI-Lifthrasir, main
ff6e956, roadmap 64/64 banked, seat suite 1505 passed / 0 failed).

**Method note (honest):** Activation slice A was executed by the campaign
coordinator running the six Mythic Engineering roles sequentially
(census / architecture / gatekeeping / build / verification / record). No
sub-agent workers are claimed. Later slices muster under
`lifthrasir-activation-keeper` (10-minute keeper law: it CONTINUES stopped
work slice by slice, never merely watches).

**Starting truth:** the 64-slice roadmap built Lifthrasir at spec/fixture
level. Its own README, CHARTER and acceptance docs say so plainly: install /
acceptance slices were fixture-level, host targets refused by name, nothing
was ever installed or run live on a real host. Activation is a deployment
campaign, not a switch-flip. This plan phases the deployment so every step
leans on the project's own hard safety invariants (ROADMAP §0) and Volmarr's
standing laws.

---

## 1. Capability census (on-device evidence, 2026-11-12)

**Verdict in one line:** a complete deterministic core exists as real,
tested Python — but it is fixture-fed library code with exactly one
read-only entry point, no daemon, no broker process, no systemd units, and
no live host data path. ~28,800 lines of Python in `src/lifthrasir/`
(44 modules); the seat suite passed 1505 / 0 at banking.

### Genuinely runnable today (real logic, fixture-fed)

| Component | Evidence | Live status |
|---|---|---|
| Policy engine (deny-by-default) | `src/lifthrasir/policy.py` (508 lines) | Library only; decides on plan records, executes nothing |
| Action catalog + protected-path list | `src/lifthrasir/actions.py` (532) | Data + validation logic; the invariant-2 refusal list lives here |
| Approval flow | `src/lifthrasir/approval.py` (335) + `docs/APPROVAL-UX.md` | HMAC-signed unique plan references, one-time consume, expiry; keys are caller-supplied test stand-ins; no live UX surface |
| Transactions + undo | `src/lifthrasir/transactions.py` (1073), `reversal.py` (516) | Durable transaction state + undo manifests as library code |
| Quotas / limits | `src/lifthrasir/quotas.py` (727) | Real `subprocess.Popen` supervision of its OWN child processes, with caps — the only real process control in `src/` |
| Kill-switch | `src/lifthrasir/killswitch.py` (557) | Real stop machinery (Popen-based), proven against fixture processes only |
| Config preview | `src/lifthrasir/configpreview.py` (481) + `docs/CONFIG-PREVIEW.md` | Validates + diffs IN MEMORY; deliberately has NO apply API |
| Eir repair recipes | `src/lifthrasir/recipes.py` (964) + `docs/EIR-RECIPES.md` | Recipe logic/data; never executed against a host |
| Repro / hypotheses / explanations | `reproverify.py`, `hypotheses.py`, `explanations.py` | Record-level reasoning pipeline |
| Thor + security triage | `thor.py` (459), `security_triage.py` (711) | Detection logic over records; no live sensors wired |
| Patch dossier / upstream forge | `patchdossier.py`, `upstreamforge.py` (836), `upstreamreview.py` | Assembles human-review dossiers; NO send surface (by design, invariant 7) |
| Privacy / federation / provenance | `privacy.py` (565), `peerprovenance.py`, `federation.py` | Scrub + provenance logic; the module "sends nothing" (its own docstring) |
| Acceptance suite | `src/lifthrasir/acceptance.py` (1239) | Runs against an in-memory fixture system; host targets refused BY NAME |
| Kernel lab logic | `src/lifthrasir/kernellab.py` (903) | Orchestration logic; imports no subprocess at all |
| Model provider | `src/lifthrasir/modelprovider.py` (982) | Mock + local-adapter CONTRACT (LIF-0601); no real inference claimed |
| Heimdall CLI | `ui/heimdall_cli.py` — the ONLY entry point in the repo | Read-only; reads `tests/fixtures/lif0205/fixture.json`, NOT a live event store (its own docstring says so) |
| Lab harness | `lab/vm_workflow.py`, `lab/fault_fixtures.py`, `lab/fault_oracle.py`, `lab/*_collector.py` | Real code: builds direct-QEMU argv (create/start/reset/delete) behind an injectable runner — tests drive a RECORDING FAKE; fault fixtures F01–F10 + oracle exist as JSON/logic |

### Fixture-only / not present (this is the activation work)

- **No observer daemon.** There is no Heimdall observer module in `src/`;
  nothing collects live /proc, journald or systemd state into the event
  store. `eventstore.py` is library code the CLI does not use.
- **No broker process.** No scoped privileged executor exists as a daemon;
  `executor.py` has no real host runner.
- **No systemd units anywhere in the repo; no packaging or installer for a
  real host.** Nothing is installed on purpleraider today.
- **No VM has ever booted.** `lab/images/kubuntu-24.04.5-amd64/` holds only
  the pinned recipe (`recipe.json` / `recipe.md` / `packages.txt`): Kubuntu
  24.04.5 ISO, sha256 `ae59e59c54337bcd8f8e60825b4a3f58797121ae0e89855524ffc92b8075c1d6`,
  5,457,694,720 bytes — the recipe states the ISO was NOT downloaded.
  `lab/kernels/` holds config fragments + fixtures, no kernel binaries.
- **Desktop UX is descriptor contracts only** (`docs/DESKTOP-UX.md`: "not a
  running KDE application"). **Confinement review** (`docs/CONFINEMENT-REVIEW.md`,
  LIF-0407) is an evidence review — the Ubuntu/Kubuntu row is host-observed —
  not an applied sandbox.

### Host readiness (purpleraider, measured 2026-11-12)

- `/dev/kvm` present, AMD SVM, 32 threads, ~118 GiB RAM available, 1.6 TB
  free on the root SSD, 3.8 TB on `/mnt/vault`. Python 3.14.8.
- **Gap found by the census:** `qemu-img` is installed but
  **`qemu-system-x86_64` is NOT** (apt candidate 1:11.0.3+ds-2ubuntu2).
  Phase 1 step 1 closes this with a native apt install (no Docker, ever).
- Sibling load: Aesir Z13 + MimirAlloc Z13 campaigns run on this machine;
  Volmarr is live in seat0. The lab must be a polite neighbour (see §4).

---

## 2. Phased activation

### Phase 1 — Lab MVP loop, end-to-end, in a disposable VM

*Leans on: invariant 5 (experiments only in disposable VMs / sacrificial
hardware), invariant 3 (privileged action is schema-validated, scoped,
logged), invariant 9 (every subsystem has pass/fail, undo, caps, off switch).*

- **Entry:** qemu-system-x86 installed natively; ISO downloaded to
  `/mnt/vault/lifthrasir-lab/` (storage law: bulk on the vault) and
  sha256-verified against the pinned recipe BEFORE any boot.
- **Work:** (a) wire `lab/vm_workflow.py` to a real runner implementation,
  kept clearly separate from the fixture fakes; (b) build a golden qcow2
  from the pinned ISO (unattended install per the LIF-0101 recipe +
  `packages.txt`); (c) prove snapshot/reset; (d) inject synthetic faults
  F01–F10 one at a time; the lab collectors observe; policy + approval
  authorise ONE narrow reversible Eir fix inside the GUEST; the executor
  path applies it; verification runs; undo executes; (e) an evidence pack
  (digests, logs, before/after) is written at the seat for every run;
  (f) the §11 MVP bar is the phase target: explain ten known synthetic
  failures, reproduce one, approve a narrow reversible fix, inspect
  evidence, roll back — all inside the VM, offline.
- **Exit evidence:** at least one fault taken detect → propose → approve →
  fix → verify → rollback entirely inside the VM with its evidence pack
  archived; reset-to-golden proven twice; kill-switch halts the loop
  mid-run; the HOST is untouched (no lifthrasir-caused change in the host
  journal/config).

### Phase 2 — Host observe + propose (purpleraider, read-only)

*Leans on: invariant 1 (no ambient root), invariant 2 (no autonomous
mutation — this phase has no mutation path at all), invariant 8
(emergency stop works without any model).*

- **Entry:** Phase 1 exit evidence banked; observer design checked against
  the CONFINEMENT-REVIEW recommendations for Ubuntu/Kubuntu.
- **Work:** an UNPRIVILEGED systemd **user** unit runs the observer:
  lab collectors adapted to read the real host (systemd state, journal,
  /proc pressure, disk) into a local event store under
  `~/.local/state/lifthrasir/`. It drafts proposals as plan records
  (approval.py references) — and NEVER executes on the host. There is no
  broker in this phase. Quotas (LIF-0603) bound its CPU/RAM; the
  kill-switch (a flag file + documented command, no model involved) stops
  it. A daily plain-language digest is written for Volmarr.
- **Exit evidence:** 7 days of observer operation with zero host mutations
  (the observer holds no write path outside its own state dir — argued by
  construction and sampled by audit); every real observation either became
  a well-formed proposal or was honestly logged as a non-issue (no
  invented incidents); Volmarr can read the digest unaided.

### Phase 3 — Approval-gated repair classes on the host

*Leans on: invariant 1 (an LLM never holds unrestricted root — actions go
through the deterministic policy engine + scoped broker), invariant 2
(protected classes refused by name, hard-coded), invariant 3, invariant 8,
invariant 9.*

- **Entry:** Phase 2 exit evidence banked; Volmarr has seen the Phase 2
  digest and the broker design.
- **Work:** the ONE privileged piece is built: a root systemd service (the
  broker) exposing ONLY the banked action-catalog verbs, each call
  schema-validated, authenticated by a consumed one-time approval token
  (`approval.consume_for_execution`), resource-scoped, time-bounded,
  journaled, and paired with a precondition check + tested undo manifest
  (transactions.py). Repair classes are admitted ONE AT A TIME, in order
  of increasing reach: (a) user-scope services and $HOME-adjacent config
  with undo; (b) noncritical system service config with tested undo;
  (c) package-adjacent repairs only through existing distro mechanisms —
  never trust roots, never bootloader/kernel/firmware/partition/
  encryption/home/SSH/firewall-critical state (invariant 2, refused by
  name). Each class first proves itself in the Phase 1 lab against a
  host-mirror fixture, then runs ONCE live under Volmarr's per-action
  approval, then — only if he grants it — under standing approval for
  that class.
- **Exit evidence (per class):** at least one live repair AND one live
  rollback on the host, with the full journal archived (plan digest,
  approval record, before/after digests, verification result); a
  tampered-digest plan refused on the host; a live kill-switch drill.

### Phase 4 — Upstream pipeline live

*Leans on: invariant 4 (evidence ladder — claims carry scope, baseline,
proof artifact, limitations), invariant 6 (private data stays local;
scrubbed payload only), invariant 7 (no agent sends as the human; dossiers
are human-reviewed), plus the fixes repo's standing law (applied + proven
only, scrubbed to grep-ZERO, README hand-edit only, never force-push,
ls-remote verified).*

- **Entry:** at least one real improvement proven — on the host via
  Phase 3, or lab-verified against a named host baseline (the dossier
  states which, honestly).
- **Work:** the §3 pipeline runs per improvement. The FIRST dossier goes
  to Volmarr for explicit review before pushing (proof the pipeline is
  honest); subsequent dossiers flow under his standing order, each one
  reported.
- **Exit evidence (campaign stop condition):** the first dossier round is
  published in the fixes repo with its scrub-gate report showing ZERO
  findings and a complete proof ladder; the activation loop
  (observe → propose → approve → repair → verify → dossier) is live.
  The keeper then reports activation complete and awaits orders.

---

## 3. Upstream pipeline design (built as code during Phases 1–2, live in Phase 4)

### Dossier format

One directory per improvement round inside the fixes repo:
`rounds/lifthrasir-<YYYYMMDD>-<slug>/` containing:

- `DOSSIER.md` — the improvement in plain language; the baseline it was
  measured against (machine class + OS/package versions — never hostname,
  serials or UUIDs); the evidence-ladder rung reached; before/after
  measurements; what was NOT tested; applicability (which Z13 / Kubuntu
  versions it applies to).
- `evidence/` — logs and digests, scrubbed AT CAPTURE TIME: collectors
  write generic labels only; home paths are rendered `$HOME`; no journal
  line enters evidence until it has passed the same pattern scan.
- `fix/` — the change itself (patch or script) plus its undo, byte-identical
  to what was proven.
- `SCRUB-REPORT.txt` — the gate's own output for this exact payload:
  patterns scanned, payload tree hash, finding count (must be ZERO).

### Scrub gate (fail-closed, two layers)

1. **At capture:** the dossier builder refuses to assemble any payload
   whose source text matches an identifier pattern. Refusal is the
   default; there is no override flag.
2. **Pre-push gate:** a script (`scrub_gate.sh`, kept at the seat and run
   against the exact staged payload — the round directory / `git diff
   --cached`) scans for: `purpleraider`; `volmarr` (case-insensitive —
   the sole permitted occurrence anywhere in that repo is his own LICENSE
   copyright line, which is never part of a round payload); `PurpleWizard`;
   `192.168.`; tailnet CGNAT space (regex `100\.(6[4-9]|[7-9][0-9]|1[01][0-9]|12[0-7])\.`);
   UUID patterns; MAC-address patterns; email-address patterns; serial
   numbers / fields; and Volmarr's resume/swap UUID — which is stored at
   the seat ONLY as a SHA-256 hash, so the gate can compare candidate
   strings without the value ever being printed or written anywhere.
   **Any hit aborts the push.** The dossier stays local; the keeper
   reports the hit CLASS (never the matched string) to Volmarr.

### Target + push mechanics

- Repo: `hrabanazviking/RuneForgeAI-ASUS-z13-Linux-Fixes`, rounds under
  `rounds/` (if the repo's layout at Phase 4 entry suggests a better home,
  follow the repo — never restructure it unasked).
- Push with the established gh identity (hrabanazviking): fetch first,
  diff remote vs local, commit the round, push an explicit refspec
  (`HEAD:refs/heads/main`), verify with `git ls-remote`. Never force-push.
  README.md is never overwritten; a round-index line, if needed, is a
  hand-edit only. Nothing is ever sent as Volmarr, and no dossier ever
  claims an upstream-accepted rung it has not reached (invariant 4 + 7).

---

## 4. Coordination and safety on this host

- Volmarr's live session (seat0, active since 01:55) is never disturbed:
  no reboots, no display-manager restarts, no session work.
- Lab politeness while the Aesir Z13 and MimirAlloc Z13 campaigns run:
  one lab VM at a time, capped at 8 vCPU / 16 GiB RAM, low scheduling
  priority; the lab is CPU-only — it never touches the GPU; lab work
  pauses while a sibling keeper is banking.
- The kill-switch (LIF-0406 machinery + a campaign-level stop: flag file,
  VM shutdown, unit stop) is armed from Phase 1 and drilled every phase.
- State: `ACTIVATION_STATE.md` at the seat is appended as work lands;
  plan + state bank to RuneForgeAI-Lifthrasir on main with explicit
  refspecs and ls-remote verification, incrementally, per slice.
