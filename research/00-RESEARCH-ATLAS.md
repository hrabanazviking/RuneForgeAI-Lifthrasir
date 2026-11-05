# Lífþrasir Research Atlas
> **Status:** Research and architectural proposals, not implemented features. **Reviewed:** 2026-11-05. **License:** See repository LICENSE (GPL-2.0).  
> **Premise:** Linux that heals, learns, evolves, and gives back.

## Research mission
Lífþrasir is a *distribution-aware, local-first, agentic repair and improvement framework*. It is not a new Linux kernel, not an antivirus product, and not an authority to rewrite a user's machine without permission. The first deliverable is a user-space supervisor and a reproducible VM test laboratory. Kernel modifications and cross-machine experimentation are later, opt-in areas.

Four separate verbs define the lifecycle:
1. **Observe** measurable problems, collect minimal evidence, preserve causality.
2. **Diagnose** with deterministic tools first, agent-supported hypotheses second.
3. **Repair** using constrained, reversible plans approved at the appropriate risk tier.
4. **Improve** in disposable sandboxes, publish only after independent evidence and human review.

## Navigating the library
### Foundations
- [01 Vision and boundaries](01-VISION-AND-BOUNDARIES.md)
- [02 Reference architecture](02-REFERENCE-ARCHITECTURE.md)
- [03 Threat model and trust](03-THREAT-MODEL-AND-TRUST.md)
- [04 Safe repair and rollback](04-SAFE-REPAIR-AND-ROLLBACK.md)
- [05 Replicater orchestration](05-REPLICATER-ORCHESTRATION.md)

### Platform and intelligence
- [06 Linux instrumentation](06-OBSERVABILITY-AND-DIAGNOSTICS.md)
- [07 Eir healing workflows](07-EIR-HEALING-ENGINE.md)
- [08 Thor defensive agent](08-THOR-DEFENSE.md)
- [09 Mímir memory and RAG](09-MIMIR-KNOWLEDGE-AND-RAG.md)
- [10 Local AI model runtime](10-LOCAL-AI-RUNTIME.md)
- [11 Agent sandbox and capability security](11-AGENT-SANDBOXING.md)
- [12 Kernel, drivers and hardware](12-KERNEL-DRIVER-RESEARCH.md)
- [13 Distribution compatibility](13-DISTRO-INTEGRATION.md)

### Engineering laboratory
- [14 Reproduction and regression tests](14-TESTING-AND-REPRODUCTION.md)
- [15 Fuzzing and fault injection](15-FUZZING-AND-FAULT-INJECTION.md)
- [16 Continuous optimization](16-OPTIMIZATION-RESEARCH.md)
- [17 Scheduler, memory, storage](17-RESOURCE-MANAGEMENT.md)
- [18 GPU, NPU and accelerators](18-ACCELERATOR-SUPPORT.md)
- [19 Immutable snapshots and boot recovery](19-TRANSACTIONAL-DEPLOYMENT.md)
- [20 Distributed experimental federation](20-DISTRIBUTED-FEDERATION.md)

### Contribution, operations and strategy
- [21 Upstream kernel gateway](21-UPSTREAM-CONTRIBUTIONS.md)
- [22 Supply chain and provenance](22-PROVENANCE-AND-SUPPLY-CHAIN.md)
- [23 Policy, governance and ethics](23-GOVERNANCE-AND-HUMAN-CONTROL.md)
- [24 Privacy and offline mode](24-PRIVACY-AND-OFFLINE.md)
- [25 Project APIs and contracts](25-API-AND-EVENT-SCHEMAS.md)
- [26 Quality metrics and evaluation](26-EVALUATION-AND-METRICS.md)
- [27 Roadmap and milestones](27-ROADMAP-AND-MILESTONES.md)
- [28 Prototype experiments](28-PROTOTYPE-EXPERIMENTS.md)
- [29 Security playbooks](29-INCIDENT-RESPONSE-PLAYBOOKS.md)
- [30 Licensing and dependency review](30-LICENSING-AND-DEPENDENCIES.md)
- [31 Research bibliography](31-RESEARCH-BIBLIOGRAPHY.md)

## Cross-cutting tenets
- The LLM never holds unrestricted root; deterministic executors enforce explicit scoped permissions.
- **Research hypothesis is not a proven fix.** A passing test is evidence for a specified scope, not a guarantee.
- Maintain a known-good boot path and offline access. If recovery is impossible, do not deploy.
- Networked nodes contribute voluntarily; raw system telemetry is not communal property.
- No auto-submission of patches upstream. Reviewers are scarce, and kernel DCO sign-offs are human actions.
- Every production action has an owner, reason, resource cap, reversibility classification, and audit event.

## Status conventions
**Fact** = documented external capability; **Design** = proposed interface or invariant; **Experiment** = hypothesis to evaluate; **Blocked** = depends on unknown permissions/portability. Date and verify external links before implementation.

## Initial success definition
On a disposable Kubuntu VM, detect a deliberately broken noncritical service, explain why it failed, propose one safe repair, request permission, apply it with a reversible checkpoint, verify restored health, and record a replayable signed evidence bundle. The exact same test must work without any cloud network.

## Primary references
- Linux kernel contribution process: https://docs.kernel.org/process/submitting-patches.html
- AI tool guidance: https://www.kernel.org/dochtml/latest/process/coding-assistants.html
- systemd service restart and watchdog: https://www.freedesktop.org/software/systemd/man/latest/systemd.service.html
- Kernel testing overview: https://docs.kernel.org/dev-tools/testing-overview.html
- Kernel trace guide: https://docs.kernel.org/trace/index.html
