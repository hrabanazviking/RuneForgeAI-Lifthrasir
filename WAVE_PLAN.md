# Lifthrasir Forge — Wave Plan

Campaign: Project Lifthrasir — "The Self-Evolving Linux System" — developed
on purpleraider (ASUS ROG Flow Z13, AMD Strix Halo), the machine whose own
rough install night is the living proof of why this project is needed.
Repo: https://github.com/hrabanazviking/RuneForgeAI-Lifthrasir
Ordered by Volmarr 2026-11-12; stood up the same night.

## Slice queue — provenance

The queue is the roadmap's OWN issue-level backlog:
`roadmap/07-IMPLEMENTATION-BACKLOG.md` names 64 discrete proposed issues,
**LIF-0001 … LIF-1601**, grouped by the master roadmap's phases P0–P16
(`ROADMAP-TO-COMPLETION.md` §1). Those identifiers are adopted AS the
campaign queue, in the backlog's listed order — no carving was needed or
done. Each slice carries the backlog's own "Done:" criterion plus the
required-issue-template fields (test fixture, expected evidence, negative
control, recovery/undo) from the same file.

Phases: P0 charter · P1 VM laboratory · P2 Heimdall observer · P3 Mimir
memory · P4 authority boundary (policy + broker) · P5 Eir repair MVP ·
P6 local inference · P7 Replicater workforce · P8 Thor defense ·
P9 kernel lab · P10 optimization science · P11 distro matrix ·
P12 packaging + 1.0 · P13 federation · P14 Upstream Forge ·
P15 advanced experiments · P16 stewardship.

64 slices = 8 waves of 9 (waves 1–7 full; wave 8 holds the final slice).

## Layout (all on purpleraider)

- Main checkout (banking seat): `/home/volmarr/lifthrasir-forge`
  (branch `main`)
- Team worktrees: `/home/volmarr/lifthrasir-team-01` …
  `/home/volmarr/lifthrasir-team-09`, branches `yrsa/lifthrasir-team-NN`,
  each with its own `CAMPAIGN_STATE.md` and `hidden_files/` logs. Never
  share a checkout between teams.
- Structure: 9 teams × (1 lead + 6 Mythic Engineering sub-agents) = 63
  workers. Each team works ONE slice at a time, in queue order.
- Campaign files at the seat: this plan, `PROJECT_MEMORY_MAP.md`,
  `KEEPER.md` (the 10-minute minder's spec).

## The queue (backlog order; phase entry = master roadmap §1 prerequisites)

Within a phase, slices run in the backlog's listed order. A team may BUILD
a slice before its phase-entry prerequisites are banked, but a slice BANKS
only in queue order and only when its phase prerequisites are banked —
the phase gates are dependency gates, not decoration (master roadmap §1).

| # | Slice | Phase | Title | Phase entry needs |
|---|---|---|---|---|
| 1 | LIF-0001 | P0 | Vision, success criteria, supported vs unsupported activities (charter) | repository |
| 2 | LIF-0002 | P0 | Architecture ADR: diagram, processes, message ownership, failure propagation | repository |
| 3 | LIF-0003 | P0 | Risk matrix L0–L5 and consent modes | repository |
| 4 | LIF-0004 | P0 | Incident, hypothesis, plan and evidence schema v0.1 | repository |
| 5 | LIF-0005 | P0 | Licensing policy, contributor guide, disclosure channel, dependency manifest | repository |
| 6 | LIF-0101 | P1 | Pinned Kubuntu image recipe; verify origin and checksum | P0 |
| 7 | LIF-0102 | P1 | QEMU/KVM create/start/reset/delete workflow | P0 |
| 8 | LIF-0103 | P1 | Restricted guest network profile and host filesystem isolation | P0 |
| 9 | LIF-0104 | P1 | Ten synthetic fault fixtures and independent pass/fail oracle | P0 |
| 10 | LIF-0105 | P1 | CI integration runner, log/artifact export, test trace ID | P0 |
| 11 | LIF-0201 | P2 | Typed event bus, schema version, boot identifier handling | P1 |
| 12 | LIF-0202 | P2 | systemd service collector: failed units, restart timeline | P1 |
| 13 | LIF-0203 | P2 | /proc and cgroup CPU, memory and PSI sensors with rate limiting | P1 |
| 14 | LIF-0204 | P2 | Disk, inode, mount and network health collectors | P1 |
| 15 | LIF-0205 | P2 | Read-only CLI: incident list, details, sensor permissions | P1 |
| 16 | LIF-0206 | P2 | Idle overhead and offline baseline report | P1 |
| 17 | LIF-0301 | P3 | Local SQLite event store and migration tests | P2 |
| 18 | LIF-0302 | P3 | Source identity, retrieval date and hash for referenced documentation | P2 |
| 19 | LIF-0303 | P3 | Exact text search; optional embeddings behind a feature flag | P2 |
| 20 | LIF-0304 | P3 | Privacy redactor, local retention, export preview | P2 |
| 21 | LIF-0305 | P3 | Causal hypothesis records incl. failed hypotheses and counterevidence | P2 |
| 22 | LIF-0306 | P3 | Poisoned-document test suite for model context | P2 |
| 23 | LIF-0401 | P4 | Typed action catalog and narrow executor interface | P1–P3 |
| 24 | LIF-0402 | P4 | Policy decisions: identity, resource, risk level, preconditions | P1–P3 |
| 25 | LIF-0403 | P4 | Separate process and limited permissions for executor | P1–P3 |
| 26 | LIF-0404 | P4 | User approval UX and signed/unique plan references | P1–P3 |
| 27 | LIF-0405 | P4 | Durable transaction state and undo manifest | P1–P3 |
| 28 | LIF-0406 | P4 | Kill-switch and model-independent recovery | P1–P3 |
| 29 | LIF-0407 | P4 | Sandbox and capability confinement review by distro | P1–P3 |
| 30 | LIF-0501 | P5 | Health-repair recipe abstraction: exact targets and effects | P4 |
| 31 | LIF-0502 | P5 | Demonstration: one noncritical user-service recovery | P4 |
| 32 | LIF-0503 | P5 | Configuration validation and diff preview | P4 |
| 33 | LIF-0504 | P5 | Verification-and-soak workflow with event logging | P4 |
| 34 | LIF-0505 | P5 | Reversal and interrupted-operation tests | P4 |
| 35 | LIF-0506 | P5 | Distinguish intentionally stopped services from accidental failures | P4 |
| 36 | LIF-0601 | P6 | Model-provider protocol, mock model, optional local inference adapter | P3–P5 |
| 37 | LIF-0602 | P6 | Structured explanation and hypothesis templates with citations | P3–P5 |
| 38 | LIF-0603 | P6 | Memory/CPU quotas, time limits and cancellation | P3–P5 |
| 39 | LIF-0701 | P7 | Replicater DAG executor and parallel hypothesis tests | P6 |
| 40 | LIF-0702 | P7 | Independent reproducer and verifier roles | P6 |
| 41 | LIF-0703 | P7 | Resource-aware agent scheduler and evidentiary arbitration | P6 |
| 42 | LIF-0801 | P8 | Thor read-only process and package integrity detector | P4, P7 |
| 43 | LIF-0802 | P8 | Security triage and low-false-positive baseline tests | P4, P7 |
| 44 | LIF-0803 | P8 | Permissioned, reversible response coordination with Eir | P4, P7 |
| 45 | LIF-0901 | P9 | Version-pinned Linux build fixtures for x86-64 and arm64 | P1, P4, P7 |
| 46 | LIF-0902 | P9 | KUnit and kselftest integration, machine-readable results | P1, P4, P7 |
| 47 | LIF-0903 | P9 | LTP subset and syzkaller disposable-guest orchestration | P1, P4, P7 |
| 48 | LIF-0904 | P9 | Candidate patch dossier with minimal reproducer and code review | P1, P4, P7 |
| 49 | LIF-0905 | P9 | Static-analysis and checkpatch reporting | P1, P4, P7 |
| 50 | LIF-1001 | P10 | Benchmark harness: controlled environment and repetitions | P7, P9 |
| 51 | LIF-1002 | P10 | Workload profiles: memory pressure, compilation, inference, graphics, I/O | P7, P9 |
| 52 | LIF-1003 | P10 | Candidate ranking with regressions and energy tracked | P7, P9 |
| 53 | LIF-1101 | P11 | Distro capability probes and adapter contracts | P5, P8–P10 |
| 54 | LIF-1102 | P11 | Fedora/Debian/openSUSE adapters; supported-versions table | P5, P8–P10 |
| 55 | LIF-1103 | P11 | ARM64 SBC and high-memory APU resource profiles | P5, P8–P10 |
| 56 | LIF-1201 | P12 | Package generation and signed release pipeline | P0–P11 |
| 57 | LIF-1202 | P12 | KDE/Qt interface, accessibility, local-only UX | P0–P11 |
| 58 | LIF-1203 | P12 | Install/upgrade/uninstall/recovery acceptance suite | P0–P11 |
| 59 | LIF-1301 | P13 | Opt-in node enrollment and privacy-reviewed data export | P12 |
| 60 | LIF-1302 | P13 | Peer provenance and contradictory-evidence handling | P12 |
| 61 | LIF-1401 | P14 | Upstream patch dossier generator and b4 workflow support | P9, P12 |
| 62 | LIF-1402 | P14 | Maintainer feedback import and human DCO review checkpoint | P9, P12 |
| 63 | LIF-1501 | P15 | Experiment selection and repeated cross-device comparisons | P13–P14 |
| 64 | LIF-1601 | P16 | Release support, incident response, governance, contributor continuity | P12–P15 |

## Wave 1 assignments

| Team | First slice |
|---|---|
| team-01 | LIF-0001 |
| team-02 | LIF-0002 |
| team-03 | LIF-0003 |
| team-04 | LIF-0004 |
| team-05 | LIF-0005 |
| team-06 | LIF-0101 |
| team-07 | LIF-0102 |
| team-08 | LIF-0103 |
| team-09 | LIF-0104 |

After a team's slice banks, it takes the next unbuilt slice in order.

**Banked: 5 of 64** (2026-11-12, keeper tick 01:47 EST) — P0 SET COMPLETE: LIF-0001 e72ad6a, LIF-0002 9003355, LIF-0003 ad50632, LIF-0004 1c1ae13, LIF-0005 d1ba145, all ls-remote verified; the P0 phase gate is satisfied, so P1 slices may bank in queue order as they are built. Built awaiting banking: LIF-0105 (team-01, 4b70e71), LIF-0201 (team-02, 10801b6), LIF-0202 (team-03, 41ade76), LIF-0203 (team-04, b89dd48). Building: LIF-0204 (team-01, stacked). Next assignments: team-05 flows to LIF-0205, team-02 flows to LIF-0206 (stacked on its unbanked LIF-0201 commit); teams 06+07 muster next tick for LIF-0101/LIF-0102 (the P1 gate path); teams 08/09 hold LIF-0103/LIF-0104.

**README note for LIF-0001:** the backlog's Done line says the charter is
"reviewed and linked in README". Teams NEVER modify README.md (standing
law). The charter slice delivers the charter document itself plus a
proposed one-line link, recorded in the team's CAMPAIGN_STATE.md for a
human to apply; the slice banks on the charter + its checks, not on the
README edit.

## Muster order (spawn-staggering law)

Probe with team-01 FIRST (mustered at stand-up, 2026-11-12). Then muster
2–3 additional teams per keeper tick (team-02+03, then 04+05, then 06+07,
then 08+09) — never launch all teams at once (platform rate limits,
2026-11-06 lesson). A team counts as mustered when its lead is live on
its assigned slice in its own worktree.

## Banking rules (per slice, in queue order, on purpleraider)

1. Full test suite green in the team's worktree — the suite grows from
   slice one (pytest for Python parts, `cargo test` for Rust parts, plus
   the slice's own fixture tests named in its issue-template fields).
   Counts are read back from log files, never memory. The ONLY tolerated
   skips are ones the roadmap, the backlog, or the slice ledger already
   names.
2. The slice's evidence pack is present (master roadmap §5): reproducer
   or fixture, differential run vs baseline, negative control, tool
   versions, artifact hashes, limitations, undo procedure. An agent never
   certifies its own milestone — the seat checks the logs independently
   before banking (backlog: "How to use" + master roadmap §8).
3. Merge the team branch into the main checkout (`~/lifthrasir-forge`).
   Team `CAMPAIGN_STATE.md` files are campaign bookkeeping and are
   excluded from slice merges (Aesir banking pattern).
4. `git fetch` + remote-diff before any push.
5. Push explicit refspec `HEAD:refs/heads/main` — never force-push.
6. Verify the remote moved with `git ls-remote`.
7. Append the slice entry to `PROJECT_MEMORY_MAP.md` and update this
   file (banked count + next assignments). One slice per commit,
   subject `LIF-NNNN: <title>`.

## Stack and license (the repo's own word governs)

- Reference technology decisions, master roadmap §4 (to be confirmed by
  ADR — the ADR is itself slice LIF-0002): **Rust** for core and broker
  (memory-safe typed IPC, explicit permissions); **Python** for the rapid
  lab, AI adapters and test harness; CLI first, KDE/Qt later; SQLite +
  FTS with append-only hash-linked evidence records; QEMU/KVM disposable
  lab; systemd hardening + namespaces + Landlock + seccomp.
- Proposed source layout: master roadmap §3 (`docs/`, `crates/` or
  `src/`, `adapters/`, `agents/`, `ui/`, `lab/`, `tests/`, `packaging/`).
- Initial engineering target: Kubuntu x86-64, disposable test
  environments (README). No distro/arch is announced supported until
  its adapter + tests exist (LIF-1102's table is the authority).
- License: GPL-2.0-only (repo LICENSE); SPDX identifiers reviewed per
  component (master roadmap header; research/30).

## Safety invariants carried into every slice (master roadmap §0)

1. No LLM or subagent gets ambient root or an unrestricted privileged
   shell. Experiments run in disposable VMs or designated sacrificial
   hardware — never fuzzing/corruption tests on the working machine.
2. No autonomous mutation of bootloader, kernel image, firmware,
   partition table, encryption, home files, package trust roots, SSH
   access, or critical firewall/network state.
3. Every privileged action: schema-validated, authenticated,
   resource-scoped, logged, time-bounded, deterministic-policy-checked.
4. Unknown or untested is NOT verified. Claims carry named scope,
   platform, baseline, proof artifact, limitations. Evidence status
   ladder (idea → hypothesis → reproducer → lab-verified →
   cross-platform-verified → human-reviewed → deployed-with-monitoring
   → upstream-submitted → upstream-accepted) is never overstated.
5. User files and private logs stay local by default; federation is
   opt-in with scrubbed-payload preview.
6. Agents never issue human DCO Signed-off-by tags and never send kernel
   patches; a human reviews and submits (LIF-1402 is that checkpoint).
7. Emergency stop works without models, network, embeddings, federation
   or inference acceleration.
8. Every subsystem ships with pass/fail criteria, undo behavior,
   resource caps, adverse-condition tests and an off switch.

## Shared machine (courtesy + survival)

purpleraider is shared tonight: the Aesir Z13 forge (`~/aesir-forge` +
9 team worktrees), the Tensile lab (`~/ai/tensile-lab`), and the
robustness campaign (NPU userland, memory-ceiling reboot, soak test)
finishing 2026-11-12. This campaign's stand-up stays LIGHT: no heavy
builds beyond team-01's first-slice needs while the soak runs; the
keeper checks machine load and other campaigns' activity before
scheduling heavy work, and yields when the box is saturated.

## Hard bounds

- NO Docker, ever. Native installs only.
- Never touch any README.md.
- Trust only disk: counts come from git + test-runner logs on
  purpleraider.
- Never leave a discovered bug unfixed: fix inside the slice's scope,
  or record it as the immediate next work in the team's
  CAMPAIGN_STATE.md.
- Pause only at the Forge pause-lines (data destruction, irreversible
  infrastructure, cost, public publishing beyond this repo's own
  pushes, sending as Volmarr, exposing secrets, weakening security).

## State

- Banked: **0 of 64**. Base: main @ e4239a098b1fde3985366a9eff4944825f8c62d9
  (repo as published; docs-only tree, 63 tracked files) + the campaign
  stand-up commit carrying this plan, the memory map and the keeper spec.
- Queue: first unbuilt slice is LIF-0001 (team-01, probe, mustered at
  stand-up). Next assignments per the Wave 1 table above; the keeper
  musters teams 02–09 in stagger order.
