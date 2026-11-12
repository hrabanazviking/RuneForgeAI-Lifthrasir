# Architecture Decision Record ADR-0002 — System Architecture (LIF-0002)

**Project:** Lífþrasir — The Self-Evolving Linux System
**Slice:** LIF-0002 (Phase P0)
**Status:** Accepted as the Phase P0 architecture baseline. This is a design decision record; nothing in this ADR asserts implemented capability — the system described here is not yet implemented.
**Date:** 2026-11-12
**Deciders:** Lifthrasir forge team-02, under the master roadmap (`ROADMAP-TO-COMPLETION.md`) and the project charter (`docs/CHARTER.md`).
**Sources:** `ROADMAP-TO-COMPLETION.md` sections 0, 3 and 4; `research/02-REFERENCE-ARCHITECTURE.md`; `docs/CHARTER.md`; `roadmap/07-IMPLEMENTATION-BACKLOG.md` (LIF-0002).

## Context

The backlog requires this slice to define the architecture diagram, the processes, message ownership and failure propagation, and the done criterion is an ADR with three competing design choices. The master roadmap section 0 fixes the executive decision: build first a Linux-native user-space supervisory system — an unprivileged observer, an isolated model runtime, a tiny privileged capability broker, a deterministic policy engine, and a disposable virtual-machine laboratory — and only later, after credible test evidence, kernel-facing instrumentation and upstream candidate patches. The charter fixes the design principle: separation of powers — observation produces evidence, agents produce proposals, a deterministic policy engine checks permissions, and an independently controlled broker carries out strictly scoped actions. This ADR confirms or revises the reference technology decisions of master roadmap section 4 and answers its ADR questions. Every later phase builds on this record.

## Architecture diagram

```text
                          +------------------------------+
                          | CLI / UI / API / Consent      |
                          | (unprivileged; emergency stop)|
                          +---------------+--------------+
                            read-only host observations
                                        |
                       +----------------v---------------+
                       | Heimdall: sensor / correlator   |
                       | (unprivileged observer)         |
                       +---------------+----------------+
                                      | immutable evidence events
                  +-------------------v--------------------+
                  | Mimir: local provenance + evidence     |
                  | store (SQLite + FTS, hash-linked)      |
                  +-------------------+--------------------+
                                      |
                     +----------------v---------------+
                     | Replicater: bounded subagents   |
                     | hypotheses / repro / patch / QA |
                     +-------+----------------+--------+
                       Thor  |                | Eir
                  security triage       repair proposals
                             +--------+-------+
                                      | typed immutable plan
                      +---------------v----------------+
                      | Independent Policy Engine       |
                      | grant + authorization check     |
                      +---------------+-----------------+
                                      | resource-specific token
                      +---------------v----------------+
                      | Minimal Privileged Broker       |
                      +---------+----------------+------+
                           live low-risk      lab-only high-risk
                           action                  |
                                                   v
                                      QEMU/KVM disposable lab + test CI
                           |              |
                           +-------+------+
                                  v
                      verification / rollback / journal
                                  |
                        human-reviewed dossier
                                  v
                      Upstream Forge (no auto-send; human submits)
```

Data flows downward only through the gates shown. No path runs from any agent, sensor, or retrieved document directly to the broker: the only road to execution is a typed immutable plan that the policy engine has granted and the broker has authenticated. The emergency stop is operated from the consent surface and from local controls independently of every model, and it halts the broker path without depending on the rest of the diagram being healthy. An independent watchdog process (see Processes) monitors the broker, queue sizes and resource caps from outside the agent plane.

## Processes

Process inventory, following research/02 with the plane each process belongs to. Planes separate observation, reasoning, authorization, execution, and verification; no process holds duties from two planes that the separation of powers keeps apart.

| Process | Plane | Privilege | Owns | Never does |
|---|---|---|---|---|
| `lifthrasir-ui` | Interface | Unprivileged user process | User interaction, incident timeline display, approval prompts, emergency stop control | Holds no ambient privilege; never executes actions itself |
| `lifthrasir-sensor` (Heimdall) | Observation | Unprivileged service | Host observations: service health, journal adapter, PSI, hardware inventory; emits normalized evidence events | Never takes repair action; never issues commands |
| `lifthrasir-indexer` (Mimir support) | Memory | Unprivileged service | Local keyword, exact-match and optional vector retrieval; redaction before indexing | Never treats retrieved text as commands |
| Mimir evidence store | Memory | Unprivileged service, local files | Append-only hash-linked evidence records in SQLite + FTS; provenance and retrieval | Never mutates evidence after append; never sends data off-host by default |
| `lifthrasir-replicater` | Reasoning | Unprivileged, sandboxed, bounded subagent count, time and token budgets | Hypotheses, reproducers, candidate patches, QA proposals | Never grants itself new permissions; never executes on the host |
| `lifthrasir-thor` | Reasoning (defense) | Unprivileged | Security detection and incident triage proposals | Containment is never its own act; it is a separate approved broker verb |
| `lifthrasir-eir` | Reasoning (repair) | Unprivileged | Repair workflow orchestration; builds typed RepairPlan envelopes for policy review | Never executes a plan itself; execution is broker-only |
| `lifthrasir-policy` | Authorization | Small, deterministic, independently controlled; no model in the decision path | Policy evaluation, deny-by-default; the only creator of one-time authorizations | Never authored or modified by agent prompts at runtime |
| `lifthrasir-broker` | Execution | The single minimally privileged service | Authenticated IPC, allowlisted verbs, execution of granted plans, verification hook, journal write | Exposes no arbitrary shell command endpoint; runs no unvalidated action |
| `lifthrasir-lab` | Execution (isolated) | Unprivileged host process driving QEMU/KVM guests | Build, test and fuzz coordination inside disposable VMs | Never runs unknown kernel code on the host |
| `lifthrasir-upstream` | Verification / hand-off | Unprivileged | Patch dossier assembly for human review | Never sends patches and never signs DCO on behalf of a human |
| Watchdog / recovery | Verification | Independent small process | Monitors broker, queues and resource caps; model-independent recovery and emergency stop enforcement | Depends on no model, network, embedding or federation service |

Verification and rollback are broker-adjacent duties, recorded in the journal: after execution the broker path verifies the result, writes the journal entry, and rolls back or closes the transaction (see Failure propagation).

## Message ownership

Every message type has exactly one owning producer. Consumers may read; they may not mint a message type they do not own. This is the rule that keeps a sensor event or a poisoned log line from ever becoming a command.

| Message | Sole owner (producer) | Consumers | Ownership rule |
|---|---|---|---|
| Observation / evidence event | `lifthrasir-sensor` (Heimdall) | Correlator, Mimir store | Sensor events are observations, never commands. Immutable once emitted; source-attributed with schema version, boot identifier and content hash |
| Incident record | Correlator within the observation plane | UI, Mimir, Replicater | Derived only from evidence events; carries evidence references, never authority |
| Hypothesis | Replicater (and its bounded subagents) | Mimir, Eir, Thor, UI | A claim with supporting and contradicting evidence and uncertainty; confers no permission |
| Retrieved context | Mimir / indexer | Replicater, Eir, Thor | Retrieved documents and logs are untrusted strings, never commands and never policy input with authority |
| RepairPlan envelope | Eir (repair) or Thor (containment proposal) | Policy engine | Typed and immutable once submitted: action type, exact target selector, exact diff or args, precondition hashes, privilege scope, rollback method, verification checks, expiry |
| Policy decision / authorization token | `lifthrasir-policy` — the only minter | Broker | One-time, resource-specific, bound to plan hash and nonce, time-bounded; only a policy engine authored outside agent prompts can create it |
| Execution request | Broker (translating a granted plan) | Adapters | The broker owns execution; adapters implement PREPARE, CHECK, EXECUTE, VERIFY, UNDO and return UNAVAILABLE for absent capabilities |
| Verification result / journal entry | Broker path (verification and journal) | Mimir, UI | Append-only; records outcome, rollback state and evidence links for every executed plan |
| Patch dossier | `lifthrasir-upstream` | Human reviewer | Assembly only; the human reviews, accepts responsibility and submits |
| Emergency stop signal | User via UI or local control; watchdog enforces | Broker, all planes | Model-independent; honored even when every other plane is down |

Transport: local IPC over Unix domain sockets with peer credential checks (SO_PEERCRED), authenticated typed messages, bounded sizes and timeouts, and no privilege granted through string interpolation (Decision D3).

## Failure propagation

Failures are contained at the plane where they occur and propagate only as evidence, never as authority. The governing directions are fail closed for changes and fail operational for read-only diagnosis and recovery.

- **Sensor or collector failure:** the observation plane degrades; gaps are recorded as missing evidence. No other plane may invent observations, and no repair may proceed on stale evidence without the staleness being named.
- **Model or Replicater unavailable:** deterministic checks and existing explicit recovery policies still run. Model failure cannot block recovery, inspection or emergency stop (master roadmap section 7, model dependency budget).
- **Mimir store corrupt or full:** diagnostics are capped, recovery space is reserved, and minimal incident metadata is retained. A corrupt local database is a named recovery-gate scenario (G3), not a reason to bypass the journal.
- **Policy engine down or decision absent:** deny by default. No grant means no broker action; queued plans expire rather than execute late. Expired plans are never replayed after reboot.
- **Broker down:** fail closed for changes; read-only diagnosis continues. The watchdog reports the outage and recovery proceeds without models or network.
- **Adapter returns UNAVAILABLE:** the plan is ineligible for execution on that target. Absence of a capability is reported as UNAVAILABLE, never treated as probably working; a plan without UNDO for a destructive action is never eligible for autonomous execution.
- **Execution fails mid-transaction or the broker is killed mid-transaction:** the durable transaction state and undo manifest drive rollback; verification-and-soak results are journaled either way. Power loss, disk-full and reboot cases are recovery-gate tests (G3), and the event log replays idempotently after reboot.
- **Agent disagreement:** competing hypotheses are recorded side by side; a security-critical decision is never averaged. Arbitration is evidentiary, and unresolved disagreement blocks escalation to execution.
- **Queue backpressure:** health and rollback work is prioritized over speculative experiments; bounded queues shed lab work first.
- **Malicious or poisoned input:** a fake sensor event cannot become a broker action, a malicious log line cannot alter policy, and a revoked or expired consent token cannot be replayed; these are standing validation tests inherited from research/02.
- **Emergency stop:** works without models, network, embeddings, federation or inference acceleration (safety invariant 8 in charter numbering; master roadmap invariant 8). Stop halts new executions and drives in-flight transactions to their undo path.

## Decision D1 — Process topology: separated planes versus monolith versus distributed services

**Context.** Prompt injection, accidental escalation and runaway loops are the defining risks of an agent system that can act on a host. Topology decides whether those risks are containable at all.

**Options considered.**

- **Option A — Separated multi-process planes (observation, reasoning, authorization, execution, verification as distinct processes with typed IPC).** Pros: least privilege per process; the privileged broker stays tiny and auditable; a compromised or hallucinating agent process holds no execution capability. Cons: more IPC design work; more processes to package and supervise.
- **Option B — Single monolithic agent process holding observation, reasoning and execution.** Pros: simplest to build and debug. Cons: one process holds ambient privilege, so any prompt injection or logic flaw escalates directly to host mutation; contradicts the charter separation of powers and safety invariant 1.
- **Option C — Distributed microservices with network RPC and a distributed scheduler.** Pros: scales to federation later. Cons: network attack surface and consensus complexity from day one; federation is a Phase P13 concern, and distribution before the local authority boundary is proven inverts the phase gates.

**Decision.** Option A: separated multi-process planes on a single host, exactly as drawn in the architecture diagram. Distribution is postponed until federation matures (master roadmap section 4, task graph row).

**Consequences.** Every later phase inherits the plane boundaries: P2 builds only the observation plane, P4 builds authorization and execution, and no slice may merge two planes into one process without a superseding ADR.

## Decision D2 — Core and broker language: Rust versus Go versus C

**Context.** The broker and policy engine are the trusted computing base: memory safety and typed IPC matter more there than anywhere else. Lab and AI adapter code values iteration speed instead. Master roadmap section 4 recommends Rust for core and broker and Python for the rapid lab, AI adapters and test harness.

**Options considered.**

- **Option A — Rust for core and broker; Python for lab, AI adapters and test harness.** Pros: memory-safe typed IPC and explicit permissions in the trusted base; fast iteration where change is constant. Cons: two toolchains; slower core development than Go.
- **Option B — Go for core and broker.** Pros: simple concurrency and fast builds. Cons: garbage-collector runtime in the minimal broker; weaker type-level encoding of permissions and plan binding than Rust.
- **Option C — C for core and broker.** Pros: no runtime, maximal control. Cons: memory-unsafety in precisely the component that must never have memory flaws; highest audit cost.

**Decision.** Option A, confirming master roadmap section 4: Rust for core and broker (and the policy engine), Python for the rapid lab, AI adapters and test harness. Go or C remain permitted for selected adapters only after review, as section 4 allows. The user interface is local CLI first, then a KDE/Qt front end; a webview is admissible only if local-only network security is convincing.

**Consequences.** Slice layout follows master roadmap section 3 (`crates/` or `src/` for core, `adapters/`, `agents/`, `lab/`, `tests/`). Contract stabilization is the trigger for porting any Python adapter into Rust, not developer preference.

## Decision D3 — Broker IPC and authorization binding: Unix socket with SO_PEERCRED and plan-hash nonce versus D-Bus versus local HTTP

**Context.** The broker is the only privileged door. Its channel must authenticate the caller, bind each authorization to one exact plan on one exact resource, and resist replay. Master roadmap section 4 poses this as an explicit ADR question.

**Options considered.**

- **Option A — Unix domain socket with SO_PEERCRED peer credentials, plus a one-time authorization token bound to the plan hash and a nonce, with expiry.** Pros: kernel-checked caller identity; no network surface at all; token replay is detectable and plan substitution changes the hash and fails. Cons: the token format and nonce store must be designed and tested carefully.
- **Option B — D-Bus system bus with polkit authorization.** Pros: established desktop Linux mechanism; polkit prompts exist. Cons: a broad shared bus namespace, policy spread across bus configuration, and weaker binding between a user prompt and the exact bytes of one plan.
- **Option C — Local HTTP or REST service on loopback.** Pros: familiar tooling. Cons: loopback is a network surface other local processes can reach; caller identity is weaker than peer credentials; invites TLS and token handling far beyond the need.

**Decision.** Option A. The broker listens on a Unix domain socket, checks SO_PEERCRED on every connection, and executes only a plan whose hash matches a one-time, resource-specific authorization token issued by the policy engine, with nonce and expiry checked at execution time. Approval is recorded as the plan hash, the resource, the decision and the expiry — never as secrets — so approval records can be journaled without exposing sensitive material to agents.

**Consequences.** P4 slices (LIF-0401 to LIF-0407) implement to this contract: typed action catalog, policy decisions, approval UX with signed and unique plan references, durable transaction state, kill-switch, and confinement review. Revoked or expired tokens failing closed is a release-gate test.

## Decision D4 — Evidence store: SQLite + FTS append-only hash-linked versus Postgres versus LMDB with files

**Context.** Mimir must keep provenance-grade evidence locally, offline, with source attribution and tamper-evident ordering, on machines from a desktop to a small board. Master roadmap section 4 recommends SQLite + FTS with append-only hash-linked evidence records.

**Options considered.**

- **Option A — SQLite + FTS, append-only tables, each record hash-linked to its predecessor.** Pros: embedded, zero-administration, transactional, works fully offline, single-file backup; FTS gives exact text search; hash linking makes silent evidence edits detectable. Cons: single-writer limits throughput; vector retrieval needs an optional sidecar library.
- **Option B — PostgreSQL server.** Pros: strong concurrency and rich queries. Cons: a running database server with its own attack and administration surface on every host; contradicts offline, low-overhead, uninstall-clean goals.
- **Option C — LMDB plus content-addressed blob files.** Pros: fast key-value access and simple blobs. Cons: no built-in full-text search; more hand-built indexing and migration machinery than SQLite requires.

**Decision.** Option A, confirming master roadmap section 4: SQLite + FTS with append-only hash-linked evidence records; content-addressed blob files may hold large artifacts beside it. Embeddings and vector retrieval are optional, local-only, and behind a feature flag. Migration to LMDB or Postgres is revisited only if measured deployment scale requires it — the section 4 decision trigger.

**Consequences.** P3 slices (LIF-0301 to LIF-0306) build the store, source identity and hashing, exact search first, privacy redaction and retention, causal hypothesis records, and the poisoned-document suite against this decision. The store distinguishes hypothesis, local proof, upstream acceptance and post-deployment reliability as separate evidence statuses on the master roadmap ladder.

## Confirmed reference decisions (master roadmap section 4)

Beyond the three contested decisions above (D1 restates the section 0 executive decision; D2, D3 and D4 settle the section 4 table and its first ADR questions), this ADR confirms the remaining section 4 starting points without revision:

- **Lab:** QEMU/KVM disposable laboratory with immutable golden images, via libvirt or direct QEMU. Experiments with potentially crashing kernels, drivers, modules or storage run only there or on designated sacrificial hardware. A microVM engine may replace it only after a threat and performance comparison recorded in a new ADR.
- **Inference:** a replaceable model-provider protocol with a Project A.E.S.I.R. adapter; the llama.cpp ecosystem or any compliant server may serve. No single model is required to start, stop, inspect or recover the system.
- **Task graph:** a bounded DAG queue with durable job states and cancellation; a distributed scheduler only when federation matures.
- **Isolation:** systemd unit hardening plus namespaces plus Landlock plus seccomp as the baseline layers; AppArmor or SELinux policies are added per distribution, and the VM is the isolation layer for kernel testing. Each sandbox layer must name the exact threat it mitigates (see ADR questions).
- **Build and patch QA:** Linux kselftest, KUnit, LTP, syzkaller, checkpatch and a compiler matrix; KCOV or ktest added as justified.
- **Release:** reproducible packages, versioned configuration migration, signatures and provenance; SLSA track targets chosen after threat review.
- **Upstream submissions:** b4 and git format-patch with a human-controlled send step; distribution-specific contributions follow the workflow of that distribution.
- **Rollback-capable adapters:** an adapter declares its capabilities; filesystems and adapters that cannot support verified rollback must abstain from mutation (return UNAVAILABLE) rather than approximate it.
- **Uninstall:** all AI components must be removable without leaving a broken machine or a modified boot process; no component installs into the bootloader, kernel image or firmware at any phase covered by this ADR.

## ADR questions from master roadmap section 4 — answers

- **Which components need a compiled language and why?** The broker, policy engine and core IPC (Decision D2): they form the trusted base, need memory safety and typed contracts, and must stay small enough to audit. Lab, adapters under development and AI protocol clients stay in Python until their contracts stabilize.
- **Should the broker communicate via Unix socket with SO_PEERCRED and explicit nonce and plan-hash binding?** Yes — Decision D3.
- **How is permission approval recorded without exposing sensitive secrets to agents?** As plan hash, resource identifier, decision, authorizations and expiry in the append-only journal (Decision D3). Secrets are never placed in approval records, prompts or agent-visible context.
- **Which filesystems and adapters support verified rollback, and which must abstain?** Adapters declare capabilities; snapshot-capable targets may execute reversible plans with an undo manifest, and any adapter without verified rollback abstains (UNAVAILABLE) for destructive actions.
- **What exact threat is mitigated by each sandbox layer?** Namespaces isolate mount, network and process views from a compromised agent; Landlock restricts filesystem reach to declared paths; seccomp removes unneeded syscalls from the broker and agents; systemd hardening composes these per unit; the QEMU/KVM lab contains kernel-level faults entirely.
- **How does the agent memory system distinguish hypothesis, local proof, upstream acceptance, and post-deployment reliability?** By the evidence status ladder recorded on every claim in the Mimir store (Decision D4): idea, hypothesis, reproducer, lab-verified, cross-platform-verified, human-reviewed, deployed-with-monitoring, upstream-submitted, upstream-accepted. A claim displays only the stage its artifacts prove.
- **How can all AI components be uninstalled without leaving a broken machine or a modified boot process?** All components are user-space services and local files under declared paths; none touches bootloader, kernel image, firmware or partition state, so removal is service deregistration plus file removal, restoring prior configuration and leaving user data only by explicit choice (master roadmap section 7).

## Consistency with the charter and the safety invariants

This ADR is subordinate to `docs/CHARTER.md` and to the master roadmap section 0 hard safety invariants. Where any reading of this ADR would conflict with them, the charter and the invariants govern.

- **Separation of powers (charter mission):** observation produces evidence (Heimdall), agents produce proposals (Replicater, Eir, Thor), a deterministic policy engine checks permissions, and an independently controlled broker carries out strictly scoped actions. Decision D1 makes this a process boundary, not a convention.
- **Invariant 1 — no ambient root:** no LLM or subagent gets ambient root access or an unrestricted privileged shell. Only the broker is privileged, it is not an agent, and it exposes allowlisted verbs only.
- **Invariant 2 — no autonomous mutation of protected state:** no autonomous mutation of bootloader, kernel image, firmware, partition table, encryption, home files, package trust roots, SSH access, or critical firewall or network state. Nothing in this architecture grants any plane a path to those targets.
- **Invariant 3 — every privileged action is checked:** every privileged action is schema-validated, authenticated, resource-scoped, logged, time-bounded and deterministic-policy-checked (Decisions D1 and D3).
- **Invariant 4 — evidence honesty:** unknown or untested is not verified; claims carry named scope, platform, baseline, proof artifact and limitations, and move only along the evidence ladder (Decision D4). This ADR itself claims only design status.
- **Invariant 5 — experiments only in disposable environments:** the lab plane (QEMU/KVM) is the sole home for crashing-kernel and corruption experiments.
- **Invariant 6 — local by default:** user files and private logs stay local by default; federation is opt-in with a scrubbed-payload preview, and no plane in this ADR transmits user data.
- **Invariant 7 — human upstream gate:** agents never issue human DCO Signed-off-by tags and never send kernel patches; the upstream process assembles dossiers and a human reviews and submits.
- **Invariant 8 — model-independent emergency stop:** the stop path lives in the interface and watchdog processes and is honored by the broker without models, network, embeddings, federation or inference acceleration.
- **Invariant 9 — every subsystem is bounded:** every subsystem ships with pass/fail criteria, undo behavior, resource caps, adverse-condition tests and an off switch; the process table and failure sections assign these per plane.
- **Invariant 10 — improvement must be measured:** the verification and journal path records baselines and outcomes so a machine is called self-evolving only when improvement is measurable without unacceptable regressions.

Supported and unsupported activities are exactly those of the charter: this ADR adds no supported activity and removes no prohibition.

## Issue record — LIF-0002

```yaml
id: LIF-0002
phase: P0
goal: "Define architecture diagram, processes, message ownership and failure propagation."
dependencies: []
risk_tier: L0
scope: "One architecture ADR in docs/architecture/ADR-0002-architecture.md, sourced from ROADMAP-TO-COMPLETION.md sections 0, 3 and 4, research/02-REFERENCE-ARCHITECTURE.md and docs/CHARTER.md; plus ADR content tests in tests/. Documentation and tests only; no code or system change; no README.md modification."
test_fixture: "tests/test_architecture_adr.py run against docs/architecture/ADR-0002-architecture.md in this repository checkout, together with the inherited charter tests."
expected_evidence: "Pytest log in hidden_files/ showing the full suite passes; negative-control log showing the ADR tests fail when a required element is removed from a mutated copy; artifact hashes recorded in the team CAMPAIGN_STATE.md."
negative_control: "The ADR tests fail if the ADR is missing, if any of the diagram, processes, message ownership or failure propagation sections is absent, if fewer than three competing design choices with decisions are present, or if the ADR contradicts a charter prohibition; verified against a mutated copy with the failure propagation section removed."
recovery_or_undo: "Revert the slice commit (git revert) — documentation and tests only, no system state changed."
```

## Limitations

This ADR is a Phase P0 design record at evidence status **idea/hypothesis documented and internally consistency-tested** — it is not lab-verified, because no component it describes is implemented yet. The technology confirmations inherit the master roadmap status: starting points to be validated by the P1 laboratory and P4 authority-boundary work, and revisable by later ADRs when measurements demand it.
