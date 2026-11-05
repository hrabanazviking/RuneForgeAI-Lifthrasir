# Vision, Product Thesis, and Explicit Non-Goals
**Status:** proposed strategy; 2026-11-05.

## The problem
Linux administrators debug failures using logs, package managers, distribution documentation, tests and manual changes. Monitoring observes; automation restarts; package updates deliver known fixes. None guarantees that a novel symptom is understood, fixed, independently tested, or responsibly offered upstream. Generative agents add the ability to investigate and propose code, but also introduce hallucination, credential and mis-execution risks. Lífþrasir should add judgment without granting unrestricted authority.

## Product thesis
Create a local-first Linux maintenance system with cooperating special-purpose agents and a narrow privileged executor. It begins as a diagnostics assistant, advances to reversible repairs of low-risk services, and eventually produces evidence-backed candidate patches in controlled laboratory environments.

### Persona responsibilities
| Component | Symbol | Responsibilities | Explicitly forbidden |
|---|---|---|---|
| Heimdall | Watch | Collect structured health signals; explain incidents | Take repair action |
| Mímir | Know | Context retrieval, research, incident causal maps | Treat retrieved text as commands |
| Replicater | Explore | Parallel hypotheses, scoped research jobs, adjudication | Grant itself new permissions |
| Eir | Heal | Propose and execute approved reversible remediation | Edit untracked critical state |
| Thor | Defend | Evaluate security incidents and contain verified threats | Punish users or destroy arbitrary files |
| Upstream Forge | Contribute | Prepare reproducer, tests and patch evidence | Forge sign-offs or spam maintainers |

The mythology is a readable product design language, not a replacement for precise engineering terms.

## Product pillars
1. **Safety above automation:** No change to boot chain, crypto keys, firewall, kernel, driver, storage layout or critical services without explicit authorization and suitable recovery.
2. **Evidence over confidence:** A generated suggestion requires observable inputs, falsifiable hypothesis, test and negative-control result.
3. **Local-first:** Existing functionality survives disconnection; optional remote research never silently leaks logs or filenames.
4. **Distribution independence:** A portable core, adapter layer for packaging and service ecosystems, and capability probes instead of distro-name assumptions.
5. **Minimal intervention:** Restart a proven failed unit before replacing packages; prefer rollback over invasive rewriting.
6. **Human upstream stewardship:** A patch is a proposal for maintainer consideration, never a guaranteed accepted contribution.

## User modes
- **Observer:** Read-only telemetry and explanations. Default on installation.
- **Advisor:** Reproducible plans and one-click proposals, no execution.
- **Repair:** Small class of reversible actions after explicit approvals.
- **Laboratory:** Build, fuzz, benchmark and mutate only isolated workloads.
- **Federation:** Opt-in exchange of sanitized diagnostics or candidate research artifacts.
- **Contributor:** Human-reviewed preparation of patch series, never automated DCO signing.

A user may individually enable modes; do not infer permission for a higher mode from a lower one.

## Success and failure
Success is measured by repair quality, mean time to diagnose, rollback success, user trust, reproducibility, low operational burden and patches accepted on their merits. Number of generated patches, number of agent instances and amount of CPU consumed are **not** measures of success.

Failure includes a machine made unbootable, secrets transmitted off-host, speculative deletion, a feedback loop that keeps restarting a service, a 'patch' with invented benchmark results, or a contribution submitted without a responsible human understanding it.

## Design questions
- Which incident types can be diagnosed without privileged telemetry?
- What is a minimal cross-distro repair action vocabulary?
- Can candidates be tested on a different host without silently changing the target kernel?
- How can the product be useful on a 4-core SBC with no GPU?
- What evidence is enough to move a repair from 'plausible' to 'verified for this configuration'?

## Research backlog
**P0:** Build policy gate, read-only service detector, immutable incident record and VM harness. **P1:** Eir reversible repair workflow, agent comparisons, offline RAG. **P2:** kernel testing and patch packaging. **P3:** safe multi-node federation and optional auto-tuning.

## Relevant references
- Linux kernel development process: https://docs.kernel.org/process/development-process.html
- syzkaller project: https://github.com/google/syzkaller
- OpenSUSE transactional updates: https://github.com/openSUSE/transactional-update
