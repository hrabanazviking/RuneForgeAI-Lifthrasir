# Replicater: Bounded Multi-Agent Engineering
**Status:** proposed architecture; 2026-11-05.

## Motivation
Single-agent diagnosis is vulnerable to fixation and fabricated certainty. Replicater should coordinate independently generated hypotheses, assign evidence collection, reconcile contradictions, and ask a skeptical verifier to reject inadequate solutions. More agents do not automatically mean better outcomes; the design must measure benefit per joule, byte, token and minute.

## Proposed roles
- **Incident captain:** Owns one case ID, impact estimate and response budget.
- **Reproducer:** Builds a test that exhibits the symptom before any fix.
- **Causal analyst:** Separates correlation, trigger and root cause.
- **Repository archaeologist:** Examines relevant source history and known advisories.
- **Fix designer:** Produces minimal diff with explicit rationale.
- **Adversarial reviewer:** Tries to falsify the fix, find side effects and expose injection.
- **Test engineer:** Adds regression tests, runs independent harness and benchmarks.
- **Platform engineer:** Verifies distro, kernel config, hardware and architecture assumptions.
- **Upstream steward:** Prepares human-reviewable dossier and respects maintainer norms.

Each agent has independent task inputs, tool scopes and outputs; agents must not all see the same proposed answer before independent analysis if diversity is desired.

## Scheduler algorithm
At intake determine incident severity and resource budget. Start with one deterministic diagnostician; spawn a second specialized agent only if confidence is low or evidence conflicts. For high-risk fixes, independence is mandatory, but execution remains disabled. Limit active branches per host by cgroup memory and system pressure. Cancel redundant jobs when test results falsify their hypothesis.

### Job contract
Each job declares: objective, allowed tools, source revision, target host/VM, max tokens, max execution time, CPU and memory budget, network policy, artifact paths, cancellation token, result schema and evidence hashes. Job output has one of SUCCEEDED, PARTIAL, INCONCLUSIVE, FAILED, CANCELLED. 'Inconclusive' must never be coerced into a pass.

## Ranking proposals
Use an evidence matrix rather than raw model confidence:
- Reproduces symptom on clean baseline.
- Fix eliminates the symptom on same test.
- Negative and control experiments distinguish cause from coincidence.
- Changes as few dependencies/lines as practical.
- Passes static checks, regressions and cross-version tests.
- Has a clear, demonstrated rollback path.
- States known incompatibilities and uncertainty.
- Cost and side effects are quantified where feasible.

Avoid majority vote as a security boundary. Three agreeing agents can all be wrong, especially when sharing contaminated context.

## Hybrid local/cloud execution
Local inference is default. Cloud workers are optional and may never receive secrets, identifiable host logs or full filesystem snapshots without explicit user-reviewed export. Offline operation degrades gracefully: run smaller local model, narrower job tree and deterministic tools; do not suspend recovery.

## Replication experiment
Inject a known synthetic service failure into 30 clean VMs. Compare deterministic workflow, one-agent workflow and bounded 3-agent workflow. Measure correct causal diagnosis, patch precision, test coverage, time, energy, false action attempts and rollback rate. Plot gains against overhead. Require statistically meaningful improvement before adding concurrency by default.

## Operational safeguards
Deduplicate identical incidents; token and concurrency quota; no recursive agent spawning without supervisor grant; tool calls are cancellable and recorded; every remote tool response is treated as untrusted evidence; independent verifier lives in a separate process and must not depend on model agreement.

## References
- Kernel researcher guidance: https://docs.kernel.org/process/researcher-guidelines.html
- Pressure stall information: https://docs.kernel.org/accounting/psi.html
- cgroup v2: https://docs.kernel.org/admin-guide/cgroup-v2.html
