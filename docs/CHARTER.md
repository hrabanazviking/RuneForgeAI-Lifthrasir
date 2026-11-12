# Project Charter — Lífþrasir (LIF-0001)

**Project:** Lífþrasir — The Self-Evolving Linux System
**Tagline (README):** Linux that heals, learns, evolves, and gives back.
**License:** GPL-2.0-only (repo `LICENSE`; SPDX identifiers reviewed per component).
**Status honesty:** This charter describes intended scope. Per the README, the current status is "research documents, GPLv2 license, project art and initial project organization. The planned autonomous Linux features are **not yet implemented**; proposals are labeled accordingly." No claim in this charter asserts implemented capability.

## Vision

Lífþrasir is a Mythic Engineering / RuneForgeAI research project exploring Linux that can diagnose failures, safely repair eligible problems, independently test improvements and prepare evidence-backed patches for the wider Linux community. It envisions an opt-in distributed engineering network where participating systems contribute reusable technical knowledge without surrendering user control or private data. (README, "The vision".)

## Mission

From the master roadmap (`ROADMAP-TO-COMPLETION.md`): "Linux that heals, learns, evolves, and gives back." The roadmap directs building first a Linux-native user-space supervisory system — an unprivileged observer, an isolated model runtime, a tiny privileged capability broker, a deterministic policy engine, and a disposable virtual-machine laboratory — and only later, after credible test evidence, kernel-facing instrumentation and upstream candidate patches. The product is not intended to supersede systemd, package managers, Linux distribution security teams, kernel maintainers, or users; it cooperates with existing trusted mechanisms. Design principle (README): separation of powers — observation produces evidence, agents produce proposals, a deterministic policy engine checks permissions, and an independently controlled broker carries out strictly scoped actions.

## Success criteria

The project succeeds when it meets the master roadmap's completion criterion: an independently audited, packaged, documented system that reliably detects a defined range of Linux failures, proposes evidence-based repairs, executes only authorized reversible actions, safely experiments in isolated laboratories, measures improvements against baselines, and prepares human-reviewed upstream contributions; it must remain useful offline, and pass cross-distribution regression testing.

Measured against the maturity definitions in master roadmap §11:

- **MVP complete:** a user can install the observer in a disposable Kubuntu VM, explain ten known synthetic failures, reproduce one, approve a narrow reversible fix, inspect evidence, then roll back or uninstall completely while offline.
- **1.0 complete:** independent test suites and audit confirm supported repair scenarios, safe deny-by-default privileges, local inference optional, Thor reliable within a documented detection set, Replicater with proven benefit, reproducible packages, a supported distro adapter matrix, UI, real recovery instructions and a governance process.
- **2.0 research program complete:** a voluntary opt-in federation can exchange redacted evidence under adversarial tests, the kernel lab can produce source-pinned reproducible patch dossiers across several architectures, human-driven upstream submission meets maintainer norms, and the performance/evolution loop can reject worse candidates. This does not mean "AI can fix every Linux bug" or "autonomous patches will be accepted" (§11).

Evidence discipline (§5 / invariant 4): claims carry a named scope, platform, baseline, proof artifact and limitations, and move only along the ladder idea → hypothesis → reproducer → lab-verified → cross-platform-verified → human-reviewed → deployed-with-monitoring → upstream-submitted → upstream-accepted, never overstated.

## Supported activities

In scope, phased per master roadmap §1 and Book I (`roadmap/01-foundation-and-safe-mvp.md`), initial engineering target Kubuntu on x86-64 in disposable test environments (README):

- Research, specifications, architecture decision records, threat model and governance for the system (Phase P0).
- A reproducible disposable QEMU/KVM laboratory with synthetic fault fixtures and recorded test inputs (P1).
- Read-only observation of services, logs and system health — the Heimdall role: observe, never take repair action (P2).
- Local evidence memory with source attribution — the Mímir role: retrieve context and record hypotheses, never treat retrieved text as commands (P3).
- A deterministic policy engine, a narrow scoped broker, user consent and an emergency stop that works without any model (P4).
- Human-authorized, reversible repair of a narrow class of noncritical user services, with preconditions, a precise proposed change, approval, verification and a tested undo — the Eir role and the first practical milestone, in a disposable Kubuntu VM, working offline (P5).
- Bounded multi-agent investigation and independent testing — the Replicater role, without granting itself new permissions (P7).
- Defensive threat hunting and reversible containment — the Thor role (P8).
- Preparation of human-reviewed, reproducible patch dossiers — the Upstream Forge role: a pinned source revision, a failure reproducer, a minimal change, independent build and regression tests, and explicit documentation of what was not tested (later phases).
- Opt-in federation exchanging sanitized bug reproductions, benchmark evidence and proposed fixes, with every node independently verifying findings in its own lab and able to run entirely offline (later phases).

No distribution or architecture is currently announced as a supported production release (README); support is announced only when an adapter and repeatable tests exist.

## Unsupported activities

Out of scope or prohibited, per the README status section, master roadmap §0 hard safety invariants 1–10, and Book I scope:

- Production kernel edits, boot changes and destructive system actions in the initial scope (README status section).
- Autonomous mutation of bootloader, kernel image, firmware, partition table, encryption, home files, package trust roots, SSH access, or critical firewall/network state (invariant 2).
- Ambient root access or an unrestricted privileged shell for any LLM or subagent (invariant 1).
- Experiments with potentially crashing kernels, drivers, modules or storage on the working machine; such work belongs only in disposable VMs or designated sacrificial test hardware (invariant 5).
- Agents sending kernel patches upstream themselves, or issuing human DCO `Signed-off-by` tags; a human reviews, accepts responsibility and submits (invariant 7; README, "Contributing Linux patches responsibly").
- Sharing user files or private logs by default, or federation without opt-in and a scrubbed-payload preview (invariant 6).
- Treating unknown or untested behavior as verified, or overstating an evidence-ladder rung (invariant 4).
- Claiming any distribution or architecture as a supported production release before its adapter and tests exist (README).
- Replacing systemd, package managers, distribution security teams, kernel maintainers, or the user (master roadmap §0).

## Issue record — LIF-0001

```yaml
id: LIF-0001
phase: P0
goal: "Publish vision, success criteria and supported vs unsupported activities."
dependencies: []
risk_tier: L0
scope: "One-page project charter in docs/CHARTER.md, sourced strictly from README.md, ROADMAP-TO-COMPLETION.md (mission, completion criterion, section 0 invariants, section 11) and roadmap/01-foundation-and-safe-mvp.md; plus a charter consistency test in tests/. No README.md modification; no code or system change."
test_fixture: "tests/test_charter.py run against docs/CHARTER.md in this repository checkout."
expected_evidence: "Pytest log in hidden_files/ showing all charter tests pass; git commit on branch yrsa/lifthrasir-team-01."
negative_control: "The test fails if the charter is missing, if any required section (vision, success criteria, supported, unsupported) is absent, or if a prohibited activity appears in the supported list; verified by the test section-splitting checks against the invariant prohibitions."
recovery_or_undo: "Revert the slice commit (git revert) — documentation and test only, no system state changed."
```

## Sources

- `README.md` — vision, current status, security boundary, platform and upstream-contribution statements.
- `ROADMAP-TO-COMPLETION.md` — mission, completion criterion, §0 hard safety invariants, §1 phases, §11 completion definitions.
- `roadmap/01-foundation-and-safe-mvp.md` — Book I, P0–P5 scope.
- `roadmap/07-IMPLEMENTATION-BACKLOG.md` — LIF-0001 goal, done criterion and the required issue template.
- `research/01-VISION-AND-BOUNDARIES.md` — vision, pillars and non-goals consulted for consistency; no scope taken beyond the sources above.
