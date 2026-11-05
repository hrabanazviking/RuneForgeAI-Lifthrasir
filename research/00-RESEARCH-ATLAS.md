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

## Execution roadmap

See the [Master Roadmap to Completion](../ROADMAP-TO-COMPLETION.md) and [implementation phase books](../roadmap/INDEX.md). Entries labeled *planned* below are not yet written.

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
- 12 Kernel, drivers and hardware *(planned research file)*
- 13 Distribution compatibility *(planned research file)*

### Engineering laboratory
- 14 Reproduction and regression tests *(planned research file)*
- 15 Fuzzing and fault injection *(planned research file)*
- 16 Continuous optimization *(planned research file)*
- 17 Scheduler, memory, storage *(planned research file)*
- 18 GPU, NPU and accelerators *(planned research file)*
- 19 Immutable snapshots and boot recovery *(planned research file)*
- 20 Distributed experimental federation *(planned research file)*

### Contribution, operations and strategy
- 21 Upstream kernel gateway *(planned research file)*
- 22 Supply chain and provenance *(planned research file)*
- 23 Policy, governance and ethics *(planned research file)*
- 24 Privacy and offline mode *(planned research file)*
- 25 Project APIs and contracts *(planned research file)*
- 26 Quality metrics and evaluation *(planned research file)*
- 27 Roadmap and milestones *(planned research file)*
- 28 Prototype experiments *(planned research file)*
- 29 Security playbooks *(planned research file)*
- 30 Licensing and dependency review *(planned research file)*
- 31 Research bibliography *(planned research file)*

### Advanced research
- [32 AUTONOMOUS PATCH LIFECYCLE](32-AUTONOMOUS-PATCH-LIFECYCLE.md)
- [33 FORMAL POLICY VERIFICATION](33-FORMAL-POLICY-VERIFICATION.md)
- [34 CLI DESKTOP AND ACCESSIBILITY](34-CLI-DESKTOP-AND-ACCESSIBILITY.md)
- [35 POWER THERMALS AND MOBILITY](35-POWER-THERMALS-AND-MOBILITY.md)
- [36 BUG LOCALIZATION AND STATIC ANALYSIS](36-BUG-LOCALIZATION-AND-STATIC-ANALYSIS.md)
- [37 MYTHIC ECOSYSTEM INTEGRATION](37-MYTHIC-ECOSYSTEM-INTEGRATION.md)
- [38 RELIABILITY CHAOS AND DISASTER RECOVERY](38-RELIABILITY-CHAOS-AND-DISASTER-RECOVERY.md)
- [39 OPEN RESEARCH QUESTIONS](39-OPEN-RESEARCH-QUESTIONS.md)

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
