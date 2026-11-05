# Engineering Backlog: Concrete Work Packages and Dependency Map
**Appendix to the [Master Roadmap](../ROADMAP-TO-COMPLETION.md) • 2026-11-05**

Every task below is a **proposed GitHub issue**, not evidence of a finished implementation. Assign an owner, code reviewer, risk level, test fixture, affected packages, acceptance artifact and actual source links before moving it into development.

## The minimum dependency graph
```
P0 specs ──► P1 VM lab ──► P2 sensors ──► P3 memory ──► P4 permissions ──► P5 Eir
                   │                              │                  │
                   └──► kernel lab prework         │                  └──► P6 model adapter
                                                  └──────────────────────► P7 Replicater
                                                                       ├─► P8 Thor
                                                                       └─► P9 kernel lab
P5 + adapters + release work ──► P11 distro matrix ──► P12 stable 1.0
P9 + P12 ──► P14 upstream package
P12 ──► P13 federation ──► P15 optimization science ──► P16 stewardship
```

## Proposed issues P0: engineering charter
- **LIF-0001:** Publish vision, success criteria and supported vs unsupported activities. Done: one-page charter reviewed and linked in README.
- **LIF-0002:** Define architecture diagram, processes, message ownership and failure propagation. Done: ADR with three competing design choices.
- **LIF-0003:** Define risk matrix L0–L5 and consent modes. Done: table-tested examples and user review.
- **LIF-0004:** Define incident, hypothesis, plan and evidence schema v0.1. Done: examples validate.
- **LIF-0005:** Establish licensing policy, contributor guide, disclosure channel and dependency manifest. Done: repo automation tests.

## Proposed issues P1: laboratory
- **LIF-0101:** Build pinned Kubuntu image recipe and verify origin and checksum. Done: identical fixtures from two clean builds.
- **LIF-0102:** QEMU/KVM create/start/reset/delete workflow. Done: clean VM reset after injected failure.
- **LIF-0103:** Restricted guest network profile and host filesystem isolation. Done: boundary tests pass.
- **LIF-0104:** Ten synthetic fault fixtures and independent pass/fail oracle. Done: golden failures reliably reproduce.
- **LIF-0105:** CI integration runner, log/artifact export and test trace ID. Done: at least one unattended test from fresh checkout.

## Proposed issues P2: observer
- **LIF-0201:** Typed event bus, schema version and boot identifier handling.
- **LIF-0202:** systemd service collector with failed-unit and restart timeline.
- **LIF-0203:** /proc and cgroup CPU, memory and PSI sensors with rate limiting.
- **LIF-0204:** Disk, inode, mount and network health collectors.
- **LIF-0205:** Read-only CLI incident list, details and sensor permissions.
- **LIF-0206:** Idle overhead and offline baseline report.
**P2 exit:** sensor events are immutable, source-attributed and do not cause state changes.

## Proposed issues P3: Mímir
- **LIF-0301:** Local SQLite event store and migration tests.
- **LIF-0302:** Source identity, retrieval date and hash for referenced documentation.
- **LIF-0303:** Exact text search and optional embeddings behind a feature flag.
- **LIF-0304:** Privacy redactor, local retention and export preview.
- **LIF-0305:** Causal hypothesis records including failed hypotheses and counterevidence.
- **LIF-0306:** Poisoned-document test suite for model context.
**P3 exit:** all summarized claims can be traced to evidence and old versions marked stale.

## Proposed issues P4: authority boundary
- **LIF-0401:** Define typed action catalog and narrow executor interface.
- **LIF-0402:** Policy decisions from user identity, resource, risk level and preconditions.
- **LIF-0403:** Separate process and limited permissions for executor.
- **LIF-0404:** User approval UX and signed/unique plan references.
- **LIF-0405:** Durable transaction state and undo manifest.
- **LIF-0406:** Kill-switch and model-independent recovery.
- **LIF-0407:** Review sandbox and capability confinement effectiveness by distro.
**P4 exit:** independent policy and recovery tests pass before any live repair is enabled.

## Proposed issues P5: Eir
- **LIF-0501:** Health-repair recipe abstraction with exact targets and effects.
- **LIF-0502:** Demonstration of one noncritical user-service recovery.
- **LIF-0503:** Configuration validation and diff preview.
- **LIF-0504:** Verification-and-soak workflow with event logging.
- **LIF-0505:** Reversal and interrupted-operation tests.
- **LIF-0506:** Distinguish intentionally stopped services from accidental failures.
**P5 exit:** 10 issue fixtures, including expected abstentions, documented recovery.

## Proposed issues P6–P8: intelligence and defense
- **LIF-0601:** Model-provider protocol, mock model, optional local inference adapter.
- **LIF-0602:** Structured explanation and hypothesis templates with citations.
- **LIF-0603:** Memory/CPU quotas, time limits and cancellation.
- **LIF-0701:** Replicater DAG executor and parallel hypothesis tests.
- **LIF-0702:** Independent reproducer and verifier roles.
- **LIF-0703:** Resource-aware agent scheduler and evidentiary arbitration.
- **LIF-0801:** Thor read-only process and package integrity detector.
- **LIF-0802:** Security triage and low-false-positive baseline tests.
- **LIF-0803:** Permissioned, reversible response coordination with Eir.
**Exit:** model failure cannot affect recovery; Thor actions always constrained by deterministic policy.

## Proposed issues P9–P10: kernel lab and evolution
- **LIF-0901:** Version-pinned Linux build fixtures for x86-64 and arm64.
- **LIF-0902:** KUnit and kselftest integration with machine-readable results.
- **LIF-0903:** LTP subset and syzkaller disposable guest orchestration.
- **LIF-0904:** Candidate patch dossier with minimal reproducer and code review.
- **LIF-0905:** Static-analysis and checkpatch reporting.
- **LIF-1001:** Benchmark harness with controlled environment and repetitions.
- **LIF-1002:** Workload profiles: memory pressure, compilation, inference, graphics, I/O.
- **LIF-1003:** Candidate ranking with regressions and energy tracked.
**Exit:** one minimal lab change has a independently repeatable failure-to-fix result.

## Proposed issues P11–P16: ecosystem
- **LIF-1101:** Distro capability probes and adapter contracts.
- **LIF-1102:** Fedora/Debian/openSUSE adapters; published supported-versions table.
- **LIF-1103:** ARM64 SBC and high-memory APU resource profiles.
- **LIF-1201:** Package generation and signed release pipeline.
- **LIF-1202:** KDE/Qt interface, accessibility and local-only UX.
- **LIF-1203:** Install/upgrade/uninstall/recovery acceptance suite.
- **LIF-1301:** Opt-in node enrollment, privacy-reviewed data export.
- **LIF-1302:** Peer provenance and contradictory-evidence handling.
- **LIF-1401:** Upstream patch dossier generator and b4 workflow support.
- **LIF-1402:** Maintainer feedback import and human DCO review checkpoint.
- **LIF-1501:** Experiment selection and repeated cross-device comparisons.
- **LIF-1601:** Release support, incident response, governance and contributor continuity.

## Required issue template
```yaml
id: LIF-xxxx
status: proposed
phase: P0
goal: ""
dependencies: []
risk_tier: L0
scope: ""
architecture_decisions: []
test_fixture: ""
expected_evidence: ""
negative_control: ""
recovery_or_undo: ""
owner: unassigned
reviewer: unassigned
results: not-run
```

## How to use with Yrsa or another engineering coordinator
Request work on *one bounded issue or coherent dependency group* at a time. Have the agent create an implementation branch, reproduce or create a failing test, design a minimal change, run independent tests, attach exact results and request review. Never let a summarization agent mark its own milestone complete. Link real tests and commits into the issue rather than replacing the evidence ledger with chat summaries.

## Source context
See [Book VI](06-bibliography-and-research-ledger.md) and kernel official docs at https://docs.kernel.org/.
