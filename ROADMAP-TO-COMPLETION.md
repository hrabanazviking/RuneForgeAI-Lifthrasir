# ᛚᛁᚠᚦᚱᚨᛊᛁᚱ — Lífþrasir: Master Roadmap to Completion
## Self-Evolving Linux • Long-Horizon Engineering Program • 2026-11-05

> **Mission:** Linux that heals, learns, evolves, and gives back.
>
> **Status:** A research-driven implementation program, **not a statement that any functionality is already implemented**. Scope extends from a first safe local prototype to a mature multi-distribution, community-auditable, opt-in distributed improvement framework.
>
> **Repository:** https://github.com/hrabanazviking/RuneForgeAI-Lifthrasir • **License in repository:** GPL v2 (review SPDX identifiers for each component).  
> **Owner vision:** Mythic Engineering agents, Replicater, Thor, Eir, Mímir, and Upstream Forge working together without removing human control or jeopardizing host integrity.
>
> **Completion criterion:** An independently audited, packaged, documented system that reliably detects a defined range of Linux failures, proposes evidence-based repairs, executes only authorized reversible actions, safely experiments in isolated laboratories, measures improvements against baselines, and prepares human-reviewed upstream contributions; it must remain useful offline, and pass cross-distribution regression testing.

---

## 0. Executive Decision: What to Build First
A self-changing Linux *kernel* is not the right first product. Build a **Linux-native user-space supervisory system** with an unprivileged observer, an isolated model runtime, a tiny privileged capability broker, a deterministic policy engine, and a disposable virtual-machine laboratory. Later, after credible test evidence, add kernel-facing instrumentation and upstream candidate patches. This maximizes useful outcomes and minimizes the probability that a malfunctioning AI breaks the machine it is supposed to heal.

The product is **not** intended to supersede systemd, package managers, Linux distribution security teams, kernel maintainers, or users. It should cooperate with existing trusted mechanisms.

### Hard safety invariants (apply in every phase)
1. No LLM or subagent gets ambient root access or an unrestricted privileged shell.
2. No autonomous mutations of bootloader, kernel image, firmware, partition table, encryption, home files, package trust roots, SSH access, or critical firewall/network state.
3. Every privileged action is schema-validated, authenticated, resource-scoped, logged, bounded in time, and subject to a local deterministic authorization policy.
4. *Unknown or untested* is not *verified*. A 'successful test' has a named scope, platform version, comparison baseline, proof artifact, and limitations.
5. All experiments with potentially crashing kernels, drivers, modules or storage must take place in disposable VMs or designated sacrificial test hardware.
6. User-owned files and private logs stay local by default. Federation is opt-in and requires scrubbed payload preview.
7. AI agents do not issue human DCO `Signed-off-by` tags or send kernel patches themselves; the human contributor reviews and submits.
8. Emergency stop works without models, network, embeddings, federation, or inference acceleration.
9. Every added subsystem must have meaningful pass/fail criteria, undo behavior, resource caps, adverse-condition tests, and off switches.
10. A single machine cannot be considered 'self-evolving' merely because agents rewrite code; it must *measurably improve* without unacceptable regressions.

### Reference architecture
```text
                          ┌──────────────────────────────┐
                          │ CLI / UI / API / Consent      │
                          └──────────────┬───────────────┘
                            read-only host observations
                                        │
                       ┌────────────────▼───────────────┐
                       │ Heimdall: sensor/correlator     │
                       └──────────────┬─────────────────┘
                                      │ immutable evidence
                  ┌───────────────────▼────────────────────┐
                  │ Mímir: local provenance + RAG          │
                  └───────────────────┬────────────────────┘
                                      │
                     ┌────────────────▼───────────────┐
                     │ Replicater: bounded subagents  │
                     │ hypotheses / repro / patch / QA│
                     └───────┬──────────┬─────────────┘
                       Thor  │          │ Eir
                  security triage       repair proposals
                             └─────┬────┘
                                   │ typed immutable plan
                      ┌────────────▼───────────────┐
                      │ Independent Policy Engine  │
                      │ grant + authorization check│
                      └────────────┬───────────────┘
                                   │ resource-specific token
                      ┌────────────▼───────────────┐
                      │ Minimal Privileged Broker   │
                      └─────────┬─────────┬────────┘
                           live low-risk  │ lab-only high-risk
                           action         ▼
                                      QEMU/KVM + test CI
                           │              │
                           └──────┬───────┘
                                  ▼
                      verification / rollback / journal
                                  │
                        human-reviewed dossier
                                  ▼
                      Upstream Forge (no auto-send)
```

## 1. Phases and Dependency Gates
Stages are dependency-driven, not deadline promises. Some streams can run concurrently only *after* the security foundation is stable.

| Phase | Deliverable | Entry prerequisite | Graduation gate |
|---|---|---|---|
| **P0** | Project charter, ADRs, threat model, research corpus | Repository | Reviewed specifications, threat register, SPDX plan |
| **P1** | Reproducible dev/test lab | P0 | Disposable VM reset, deterministic fault fixtures, signed test provenance |
| **P2** | Read-only Heimdall observer | P1 | Service/pressure/storage/network health without host mutation |
| **P3** | Mímir local memory/evidence graph | P2 | Source attribution, secret redaction, reproducible incident timeline |
| **P4** | Policy engine, broker, consent and emergency stop | P1–P3 | Deny by default, verified isolation and failed escalation suite |
| **P5** | Eir safe repair MVP | P4 | At least 10 synthetic issues, strict reversibility and recovery drills |
| **P6** | Local inference and model adapters | P3–P5 | Model failure cannot block recovery; offline proof |
| **P7** | Replicater subagent workforce | P6 | Bounded concurrency, tests outperform baseline in predeclared metrics |
| **P8** | Thor defensive detection and containment | P4, P7 | False-positive, attack and reversible-response test suite passes |
| **P9** | Kernel lab and kernel patch drafting | P1, P4, P7 | Kernel builds, reproducers, KUnit/kselftest, static analysis |
| **P10** | Performance optimizer and A.E.S.I.R. integration | P7, P9 | Statistically validated improvements with power/thermal controls |
| **P11** | Second distro and second architecture | P5, P8–P10 | Adapter parity with explicit 'unsupported' behavior |
| **P12** | Package hardening, GUI and 1.0 release | P0–P11 | External audit, installation/uninstall/rollback and offline QA |
| **P13** | Opt-in distributed federation | P12 | Byzantine-ish peer resilience, privacy and replay tests |
| **P14** | Upstream Forge and contributor process | P9, P12 | Human review gate; a real maintainable patch dossier |
| **P15** | Advanced evolutionary experiments | P13–P14 | Novel algorithms validated across diverse hardware |
| **P16** | 2.0 ecosystem completeness and stewardship | P12–P15 | Maintenance ownership, multi-cycle stability, community contribution |

**Do not block an excellent v1.0 on research-grade P13–P16**. The commercially and socially useful core is local, safe, offline system diagnosis and recoverability. The global evolution network is a higher-risk, opt-in 2.x vision.

## 2. The Seven Workstreams
**A. Kernel and platform:** systemd/journald, procfs/sysfs, PSI, cgroups, package managers, snapshots, hardware and driver adapters.  
**B. Security and correctness:** policy DSL, broker, permissions, sandbox, threat model, replay protection, audit, emergency stop.  
**C. Agent infrastructure:** Replicater DAGs, model backends, task schemas, costs, cancellation, tool provenance.  
**D. Repair and defense:** Eir repair catalog and Thor security incident containment.  
**E. Science and validation:** VM farms, seeded failures, KUnit, kselftest, LTP, syzkaller, fuzzing, property-based tests, benchmarks, negative controls.  
**F. Product and operations:** CLI, GUI, setup, notices, accessibility, language, offline docs, packaged upgrades/uninstall.  
**G. Federation and community:** evidence exchanges, incentives, disclosure, review, mailing-list patch workflow, maintainership.

Every feature must have a workstream owner, an interface specification, deterministic test, documented configuration, threat review and rollback story.

## 3. Planned Repository Layout
```text
README.md                       # User onboarding and current honest status
ROADMAP-TO-COMPLETION.md        # This master
research/                       # Existing thematic research and new additions
roadmap/
  01-foundation-and-safe-mvp.md
  02-agentic-repair-and-defense.md
  03-kernel-evolution-and-optimization.md
  04-distribution-federation-and-upstream.md
  05-quality-release-and-governance.md
docs/
  architecture/                 # Architecture decision records (ADRs)
  operator-guide/               # Backup, installing, recovery, uninstall
  developer-guide/              # API, adapters, build, tests, design rules
  threat-model/                 # Assets, attacker paths, mitigations
  benchmarks/                   # Metrics, frozen workloads, baselines
  protocols/                    # Schemas, authorization tokens, agent jobs
  disclosures/                  # Security policy, responsible reporting
crates/ or src/                 # Core implementation (language ADR pending)
adapters/                       # systemd, apt, dnf, pacman, snapshots
agents/                         # Thor, Eir, Mímir, Replicater prompts + code
ui/                             # CLI and desktop
lab/                            # VM images (build recipes, not large images)
tests/                          # Unit, integration, adversarial, chaos, fuzz
packaging/                      # Deb/RPM/Arch/Flatpak where appropriate
.github/                        # CI, Dependabot / security workflows
```
The source tree above is **proposed**, not currently present. Avoid committing secrets or huge VM images. Ship reproducible image *recipes* and checksums.

## 4. Reference Technology Decisions (to confirm by ADR)
| Domain | Recommended starting point | Alternatives / decision trigger |
|---|---|---|
| Core and broker | Rust for memory-safe typed IPC and explicit permissions | Go/C for selected adapters after review |
| Rapid lab and AI adapters | Python for research/test harness and model protocol clients | Rust after stabilizing contracts |
| UI | Local CLI first, then KDE/Qt front end | Webview only if local-only network security is convincing |
| Metadata and incidents | SQLite + FTS, append-only hash-linked evidence records | LMDB/Postgres if deployment scale requires |
| Vector retrieval | Optional local library, no online prerequisite | Per-hardware/index benchmarking |
| Local inference | Replaceable provider protocol, Project A.E.S.I.R. adapter | llama.cpp ecosystem, any compliant server |
| Task graph | Bounded DAG queue with durable job states and cancellation | Distributed scheduler only when federation matures |
| Isolation | systemd unit hardening + namespaces + Landlock + seccomp | AppArmor/SELinux distro policies; VM for kernel testing |
| VM lab | QEMU/KVM + libvirt or direct QEMU, immutable golden images | MicroVM engine after threat/performance comparison |
| Build/patch QA | Linux kselftest, KUnit, LTP, syzkaller, checkpatch and compiler matrix | Add KCOV/ktest as justified |
| Release | Reproducible packages, versioned config migration, signatures, provenance | Choose SLSA track targets after threat review |
| Upstream submissions | b4/git format-patch with a HUMAN-controlled send step | Distro-specific contributions via their workflow |

### Architectural decision record (ADR) questions
- Which components need a compiled language and why?
- Should broker communicate via Unix socket with SO_PEERCRED and explicit nonce/plan-hash binding?
- How is permission approval recorded without exposing sensitive secrets to agents?
- Which filesystems/adapters support verified rollback, and which MUST abstain?
- What exact threat is mitigated by each sandbox layer?
- How does the agent memory system distinguish hypothesis, local proof, upstream acceptance, and post-deployment reliability?
- How can all AI components be uninstalled without leaving a broken machine or modified boot process?

## 5. Evidence-Based Engineering Rules
A 'proven patch' must include:
1. Reproducer (test demonstrates failure on baseline with pinned source and configuration).
2. Differential run on the same baseline plus candidate patch.
3. Control test that rules out an alternate trivial explanation.
4. Compiler/test logs, warnings, stdout/stderr and exact tool versions.
5. Functional, regression and security results; code coverage where meaningful.
6. Hardware/VM details, kernel config, distro, firmware if relevant, workload and seed.
7. Performance distribution not cherry-picked: repeated runs and confidence intervals when benchmarking.
8. Artifacts with cryptographic hashes and source/provenance links.
9. Risk and limitations, and a safe undo procedure.
10. Independent human review before host deployment or upstream release.

Evidence statuses: **idea → hypothesis → reproducer → lab-verified → cross-platform-verified → human-reviewed → deployed-with-monitoring → upstream-submitted → upstream-accepted**. Only the relevant stage is displayed; never imply acceptance before it happens.

## 6. Security Review Gates
- **G0 Specification:** full threat model, privileged interface contract and user-consent design.
- **G1 Static:** formatting, lint, dependency review, SBOM, secrets scan, checkable licenses.
- **G2 Isolation:** path traversal, symlink races, PID reuse, revoked consent, expired plan, model prompt injection and log poisoning.
- **G3 Recovery:** kill agent/broker during transaction, power-loss simulation, disk-full conditions, offline operation, OS reboot, corrupt local database.
- **G4 Policy:** attempt kernel mutation without human authorization; attempt noncritical restart on wrong resource; attempts MUST fail with useful logs.
- **G5 Release:** independent security assessment, reproducible build and recovery audit, clear public limitations.
- **G6 Community:** voluntary federation opt-in, authenticity, privacy, reputation and complaint/abuse pathway.

Failure of any safety gate blocks promotion even if a feature's demo looks impressive.

## 7. Non-Functional Budgets and Targets
These are **initial proposed acceptance targets**, not empirical results. Freeze actual thresholds with maintainers before testing.

| Metric | Proposed initial objective |
|---|---|
| Idle resource overhead | Keep measured CPU and RAM modest; set numeric budget from target Kubuntu hardware baseline |
| Service watch accuracy | Detect all 10 intentionally seeded service failures in test suite; minimize false alerts in benign controls |
| Reversible action completion | 100% of tested low-risk actions have audited rollback path |
| Unauthorized privileged mutation | 0 accepted in adversarial integration battery |
| Offline diagnostic function | Every supported MVP workflow executes with network disabled |
| Rollback after interrupted repair | Demonstrate recovery for every supported reversible repair fixture |
| Model dependency | No single model is needed to start, stop, inspect or recover system |
| Upstream false claims | 0 untested or auto-signed patches presented as 'verified' |
| Uninstall cleanliness | Restore service registration and configuration; leave user data only by explicit choice |
| Reliability | Predeclare workload and failure-injection SLOs; report p50/p95 and failures, not averages alone |

## 8. Project Management: Epics and Critical Path
**Critical path:** architecture safety → fixture VM → deterministic sensor → policy/broker → Eir reversibility → offline AI → Replicater → Thor/Kernel lab → packaging and 1.0 → federation and upstream advanced capabilities.

Parallel from P1 onward: official documentation indexing, isolated unit/contract tests, release engineering scaffolding, license audits and clean-room design rules. Parallel after P4: Qt mockups, Thor *detection only*, package adapters in isolated fixtures.

Suggested issue labels: `phase:P0`–`phase:P16`, `area:broker`, `area:security`, `area:lab`, `risk:L0`–`risk:L5`, `type:research`, `type:implementation`, `type:test`, `type:documentation`, `gate:blocker`.

Each issue includes purpose, exact scope, dependencies, proposed test, rollback impact, owner, acceptance checkbox, cited research, estimated difficulty and evidence artifact. No issue closes because an agent merely says 'done.'

## 9. Release Cadence (Illustrative, Not a Promise)
- **0.0.x design builds:** specifications, read-only sensors, lab and no host modification.
- **0.1 MVP:** local diagnosis of service problems with all mutations disabled.
- **0.2:** consented narrow Eir repair in test VMs and explicit lab mode.
- **0.3:** offline Mímir and first optional local model adapter.
- **0.4:** Replicater with bounded task DAGs, comparison against non-agent baseline.
- **0.5:** Thor detection and careful reversible containment, gated in isolated tests.
- **0.6:** kernel build/reproducer and patch dossier generation in VM.
- **0.7:** more distribution adapters, hardware/memory/power profiles.
- **0.8:** complete CLI, starter GUI, multilingual docs, packaging, public beta testing.
- **0.9:** release-candidate security audit, migration/restore, 30-day soak.
- **1.0:** production-ready *defined local subset* of features with audited boundaries.
- **1.1–1.x:** wider distribution matrix and refinements; no policy regression.
- **2.0:** opt-in federation, reproducible cross-node scientific experiments, mature upstream contribution workflow.

A small independent team could need multiple years to reach the complete 2.x vision. A solo developer with AI collaborators can accelerate code drafting but not eliminate validation, hardware matrix testing, security audits or maintainer review. Keep **exit criteria**, rather than optimistic calendar dates, as the release authority.

## 10. Main Disqualifying Failure Modes
- Self-referential agent changes policy code or its own evaluation criteria to manufacture passes.
- Broker accepts arbitrary shell arguments, wildcard paths, non-atomic write plans or stale approval tokens.
- A running kernel is upgraded without a known-good boot strategy.
- Experimental fuzzing or filesystem corruption tests run on the user's real personal workstation.
- Performance improvement is based on one benchmark without controls for DVFS, thermal state, cache and workload.
- Thor kills a user's local AI inference process as an assumed miner.
- Privacy-sensitive logs enter the federation or public patch reports without review.
- A 'discovered vulnerability' is auto-posted to a public forum before coordinated disclosure.
- Upstream patch volume is optimized at expense of maintainers.
- New features depend on proprietary cloud access with no fallback.
- 'Complete' is defined by number of agents rather than demonstrated reliability.

## 11. Completion Definition by Maturity
### MVP complete
A user can install the observer in a disposable Kubuntu VM, explain ten known synthetic failures, reproduce one, approve a narrow reversible fix, inspect evidence, then roll back or uninstall completely while offline.

### 1.0 complete
Independent test suites and audit confirm supported repair scenarios, safe deny-by-default privileges, local inference optional, Thor reliable *within a documented detection set*, Replicater with proven benefit, reproducible packages, supported distro adapter matrix, UI, real recovery instructions and a governance process.

### 2.0 research program complete
A voluntary opt-in federation can exchange redacted evidence under adversarial tests, kernel lab can produce source-pinned reproducible patch dossiers across several architectures, human-driven upstream submission meets maintainer norms, and the performance/evolution loop can reject worse candidates. This does **not** mean 'AI can fix every Linux bug' or 'autonomous patches will be accepted'.

### Perpetual maintenance
After 'completion', the project still needs ongoing CVE review, model and runtime updates, distro/ABI churn support, maintainer relations, issue triage, reproducible release signing, and regression testing. Self-evolution never removes the need for stewardship.

## 12. Detailed Chapter Index
- [Book I: Foundations, P0–P5](roadmap/01-foundation-and-safe-mvp.md)
- [Book II: Replicater, Eir, Thor, P6–P8](roadmap/02-agentic-repair-and-defense.md)
- [Book III: Kernel and Performance Laboratory, P9–P10](roadmap/03-kernel-evolution-and-optimization.md)
- [Book IV: Cross-Distribution, Federation, Upstream, P11–P16](roadmap/04-distribution-federation-and-upstream.md)
- [Book V: Quality, Safety, Release Engineering and Governance](roadmap/05-quality-release-and-governance.md)
- [Reference bibliography and verification ledger](roadmap/06-bibliography-and-research-ledger.md)
- [Research atlas](research/00-RESEARCH-ATLAS.md)

## 13. Authoritative Source Anchors
- Kernel patch submission and DCO: https://docs.kernel.org/process/submitting-patches.html
- AI coding assistant kernel process (version-dependent wording): https://docs.kernel.org/next/process/coding-assistants.html
- Kernel generated-content guidance: https://docs.kernel.org/process/generated-content.html
- Kernel testing guide: https://docs.kernel.org/dev-tools/testing-overview.html
- KUnit: https://docs.kernel.org/dev-tools/kunit/usage.html
- kselftest: https://docs.kernel.org/dev-tools/kselftest.html
- LTP: https://linux-test-project.readthedocs.io/en/latest/
- syzkaller: https://github.com/google/syzkaller/blob/master/docs/linux/setup.md
- QEMU: https://www.qemu.org/docs/master/system/
- systemd sandboxing: https://www.freedesktop.org/software/systemd/man/latest/systemd.exec.html
- Landlock: https://docs.kernel.org/userspace-api/landlock.html
- Linux cgroups: https://docs.kernel.org/admin-guide/cgroup-v2.html
- OSTree deployment: https://ostreedev.github.io/ostree/atomic-upgrades/
- B4 contributor workflow: https://b4.docs.kernel.org/en/latest/contributor/overview.html
- SLSA: https://slsa.dev/spec/v1.2/whats-new

Read each document in full and pin versions when implementing; document URLs may describe different kernel releases or evolving policy. Assertions here are about project *design*, except explicitly sourced capabilities.
