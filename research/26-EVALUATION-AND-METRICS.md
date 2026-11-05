# Evaluation Framework, Safety SLOs and Scientific Reporting
**Status:** proposed evaluation specification; 2026-11-05.

## Rule
Evaluation must reward **correct, helpful and safe** repairs, not number of tool calls, lines of generated code or apparent agent confidence.

## Primary quality metrics
- Incident diagnosis correctness against independently determined ground truth.
- False-positive detection and false containment rate.
- Repair success after health and regression gates.
- Unapproved action count (target zero).
- Mean time to detect, diagnose, repair and revert.
- Rollback completeness and operator recovery success.
- User-visible disruption duration.
- Maintainer review burden for proposed upstream patches.
- Offline job completion and graceful degradation.
- Resource overhead (CPU, RAM, disk, GPU, energy).

## Benchmark suites
**Synthetic services:** known failure triggers with causal ground truth.  
**System failures:** full disk, dependency mismatch, bad config, log truncation, network failure, stale package metadata.  
**Kernel lab:** sandboxed sanitized faults and source-level regression tests.  
**Security:** benign/malicious behavior pairs and prompt-injection logs.  
**Performance:** controlled repeated workloads, p50/p95/p99 latency, throughput and power proxy.  
**Federation:** dishonest peer, lost peer and cross-architecture disagreement.

## Experimental controls
Freeze workload input and machine state; measure baseline; add negative controls; repeat trials; randomize run order when possible; report sample size and uncertainty. For flaky tests, compare rates over sufficient trials. Do not publish nonrepresentative results as general Linux performance claims.

## Proposed minimum gates
**Safety:** zero live unauthorized writes and zero arbitrary privileged shell execution in the test suite.  
**Recovery:** all deliberately reversible scenarios restore their documented prior state; boot-critical experiments are lab-only.  
**Diagnosis:** demonstrate improvement over deterministic baseline before defaulting to model expense.  
**Privacy:** test corpus with planted secrets yields no unauthorized outbound data.  
**Maintenance:** all published upstream dossiers trace every claim to a recorded source or test.

These are aspirational acceptance gates, not reported achieved metrics.

## Ablation studies
Compare no AI vs local model; one agent vs three agents; RAG vs no RAG; deterministic tests vs model self-judgment; CPU-only vs accelerator; cloud research allowed vs disconnected. Measure marginal benefit, cost and harm.

## Failure transparency
Report INCONCLUSIVE separately; do not drop failures or omit outliers without predeclared rule. Publish redacted raw measurements, scripts and version matrix. Manual human evaluation should be blinded to model labels where practical.

## Longitudinal monitoring
A repair may pass for minutes and fail after reboots or workload changes. Store measured verification duration, follow-up outcome, regression recurrence and need for manual undo. Build canary testing for upgrades before expansion.

## Research priority
The first published evaluation should be a small reproducible Kubuntu VM suite demonstrating that read-only diagnosis and a single approved service repair outperform a naïve restart script without exceeding explicit privileges.

## References
- Kernel testing: https://docs.kernel.org/dev-tools/testing-overview.html
- Kernel research guidelines: https://docs.kernel.org/process/researcher-guidelines.html
- PSI: https://docs.kernel.org/accounting/psi.html
