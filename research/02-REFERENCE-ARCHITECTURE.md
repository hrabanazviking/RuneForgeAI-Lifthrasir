# Reference Architecture: Planes, Boundaries and Events
**Status:** design proposal; 2026-11-05.

## Plane separation
Lífþrasir must separate **observation**, **reasoning**, **authorization**, **execution**, and **verification**. Combining them in one privileged chatbot process makes it impossible to reliably defend against prompt injection, accidental escalation or runaway loops.

    ┌──────────────────── User UI / CLI / API ─────────────────────┐
    │ incident timeline, explanation, approval, emergency stop    │
    └──────────────────────────────┬───────────────────────────────┘
       observation sources → collector → normalized event bus
                                      ↓
                         incident classifier / correlator
                                      ↓
                 Mímir evidence store + Replicater planners
                                      ↓
                       candidate RepairPlan envelopes
                                      ↓
                 deterministic policy and approval engine
                                      ↓
                  scoped broker → adapter → target resource
                                      ↓
                  verification → journal → rollback/close

Independent watchdog process monitors broker, queue sizes and resource caps. The recovery subsystem must function even when the models are unavailable.

## Process inventory
- **lifthrasir-sensor:** Unprivileged service health, PSI, hardware inventory, limited journal adapter.
- **lifthrasir-indexer:** Local vector, keyword and exact-match retrieval; redacts before indexing.
- **lifthrasir-replicater:** Planning with bounded subagent count, time and token budgets.
- **lifthrasir-policy:** Small testable deterministic policy evaluator, deny-by-default.
- **lifthrasir-broker:** Privileged minimal service with authenticated IPC and allowlisted verbs. No arbitrary shell command endpoint.
- **lifthrasir-eir:** Repair workflow orchestrator using policy-approved broker verbs.
- **lifthrasir-thor:** Detection and incident triage; containment is a separate approved broker verb.
- **lifthrasir-lab:** Isolated build/test/fuzz coordinator; VM mandatory for unknown kernel code.
- **lifthrasir-upstream:** Patch dossier builder, human sign-off and sending adapter.
- **lifthrasir-ui:** CLI or local graphical console without ambient privilege.

## Trust and data direction
Sensor events are *observations*, never commands. Retrieved documents and logs are untrusted strings. Agents return proposals and explanatory confidence, not capabilities. Only a policy engine authored outside agent prompts can create a one-time authorization for an exact action on an exact resource under given preconditions.

### Proposed domain model
**Incident:** identifier, host fingerprint (locally pseudonymous), trigger, times, evidence references, data sensitivity, impact.  
**Hypothesis:** incident ID, causal claim, supporting evidence, contradicting evidence, proposed tests, uncertainty.  
**RepairPlan:** action type, target selector, exact diff/args, precondition hashes, privilege scope, rollback method, verification checks, expiry, authorizations.  
**EvidenceBundle:** immutable input manifest, tooling versions, source commits, environment manifest, logs (redacted), results, comparison baseline, signatures where available.

Each object needs schema version, creation time, content hash, provenance and a stable link to preceding state.

## Adapter design
Abstract interfaces for init (systemd first), packaging (apt/dpkg, rpm/dnf, pacman), bootloader, snapshots, network firewall, security module, kernel tracing and hardware drivers. Adapters declare capabilities. Absence of a capability returns UNAVAILABLE, not 'probably works'.

Adapters should implement PREPARE, CHECK, EXECUTE, VERIFY, UNDO where meaningful. A plan without UNDO for a destructive action is never eligible for autonomous execution.

## Failure handling
- Queue backpressure: prioritize health and rollback over speculative experiments.
- Model unavailable: run deterministic checks and existing explicit recovery policies.
- Broker down: fail closed for changes, continue read-only diagnosis.
- Agent disagreement: record competing hypotheses, do not average a security-critical decision.
- Storage full: cap diagnostics, reserve recovery space, retain minimal incident metadata.
- Reboot: replay event log idempotently; never execute expired plans.

## Implementation interfaces
Local IPC over Unix domain sockets with peer credential checks; authenticated typed messages; bounded sizes and timeouts; no privilege via string interpolation. Start with a single host and local SQLite metadata plus content-addressed blob files. Encrypt or protect sensitive records according to environment capability and user choice. Postpone distributed consensus until required.

## Validation
Test that a fake sensor event cannot become a broker action, that a malicious log line cannot alter policy, that a revoked consent token cannot be replayed, and that the system recovers after model failure mid-repair.

## References
- systemd service management: https://www.freedesktop.org/software/systemd/man/latest/systemd.service.html
- Linux cgroup v2: https://docs.kernel.org/admin-guide/cgroup-v2.html
- Kernel tracing: https://docs.kernel.org/trace/index.html
