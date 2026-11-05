# Phased Engineering Roadmap for Lífþrasir
**Status:** proposed milestones; 2026-11-05.

## Phase 0: Foundations and guardrails
**Goal:** Demonstrate a safe read-only foundation.
- Define project governance, code ownership, GPLv2 compliance and contributor guide.
- Version event schemas, capability declarations and policy engine.
- Implement host inventory, systemd read-only health sensor and local incident store.
- Add sanitization, logging caps, offline operation and emergency stop.
- Build hermetic/disposable Kubuntu VM harness.
**Exit:** product runs without cloud or root; policy fuzz suite cannot cause writes.

## Phase 1: Eir minimal closed loop
**Goal:** Repair one deliberately broken noncritical user-level service.
- Implement one scoped broker action with approvals.
- Prepare immutable RepairPlan and journal.
- Record config backup or snapshot when required.
- Execute only after exact preconditions, verify and undo on failure.
- Build CLI explaining reasoning and uncertainty.
**Exit:** deterministic tests show reproducible safe repair, undo and no arbitrary commands.

## Phase 2: Mímir + Replicater
**Goal:** Evidence-supported diagnoses improve over deterministic rules.
- Import curated official man pages and local source docs.
- Add local model adapter and schema-constrained outputs.
- Implement bounded two/three-agent challenge workflow.
- Publish ablation study and resource costs.
**Exit:** improved diagnostic quality without privilege regression or unacceptable overhead.

## Phase 3: Thor defensive containment
**Goal:** Detect and assess synthetic malicious behaviors with low false-positive harm.
- Read-only integrity and process lineage investigation.
- Independent evidence and policy gates.
- Reversible containment of selected lab processes only.
- False-positive adversarial benchmark.
**Exit:** demonstrate containment + prompt-injection resistance and reliable undo in lab.

## Phase 4: Kernel and distro research forge
**Goal:** Generate a complete *reviewable* patch dossier, not auto-submit it.
- Source checkout, minimal reproducer, KUnit/kselftest and static analysis integration.
- Run selected kernels in QEMU with optional sanitizers.
- Support first cross-architecture x86_64/arm64 test matrix.
- Record machine-readable test provenance.
**Exit:** one synthetic or known public bug receives test-backed candidate diff for human review.

## Phase 5: Transactional system repair
**Goal:** Boot-level safe canary upgrade on supported deployment class.
- Choose one known rollback-capable platform.
- Stage alternate deployment; simulate boot failure; verify fallback.
- Human-approved promotion and documented rescue steps.
**Exit:** physical or VM test shows credible recovery after a deliberately bad image.

## Phase 6: Optional research federation
**Goal:** Two mutually authenticated voluntary nodes replicate a test artifact.
- Explicit permissions, signed task manifests, no raw logs, strict quotas.
- Treat peers as untrusted and verify results independently.
- Test disconnect, malicious peer and cancellation.
**Exit:** cross-node test result reproduced without remote root or privacy leaks.

## Backlog prioritization
Rank tasks by safety necessity, measurable user impact, reproducibility, ability to test in disposable VMs and compatibility with existing Linux conventions. Defer fancy graphical visuals, kernel injection, remote worker networks and autopatching until the trust foundations exist.

## Suggested repository layout
    research/       architecture studies and citations
    rfcs/           decisions and alternative designs
    schemas/        versioned event definitions
    crates/ or src/ unprivileged services and broker
    adapters/       init, package, snapshot integrations
    labs/           VM provisioning and fault scenarios
    tests/          unit/integration/fuzz/regression
    policy/         machine-checkable default-deny rules
    docs/           guides and recovery runbooks

The actual code language is a later decision; a memory-safe language is strongly preferred for privileged IPC and parsing.

## Definition of done
A milestone needs test evidence, threat-model update, reproducible instructions, license audit, rollback consideration, resource footprint and user-facing explanation. Mark speculative designs explicitly until implemented.

## References
- Linux development process: https://docs.kernel.org/process/development-process.html
- Kselftest: https://docs.kernel.org/dev-tools/kselftest.html
