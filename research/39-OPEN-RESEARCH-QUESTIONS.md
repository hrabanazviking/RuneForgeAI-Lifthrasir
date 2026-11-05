# Long-Horizon Open Research Questions
**Status:** unsolved problems and falsifiable hypotheses; 2026-11-05.

## 1. Can a Linux agent reliably distinguish root cause from correlated symptom?
Research paired incident corpora with visually similar logs but different hidden triggers. Evaluate whether independent hypotheses and chosen tests improve causal accuracy relative to static rules.

## 2. Does agent replication justify its computational overhead?
Compare 1, 2, 4 and 8 agents under equal total compute budget, including verifier diversity and repeated tool use. Check whether extra agents create false consensus from common model biases.

## 3. How can we measure an actual 'proven good patch'?
Possible definition: reproducer fails before/passes after; relevant regression tests pass; no detectable guardrail regression; independently verified on declared platforms; accountable human review. Study how many tests and how long a soak period are sufficient for each risk tier.

## 4. Can a policy engine be proven resistant to model prompt injection?
Attempt to prove narrow invariants for typed broker verbs and non-replayable authorizations. Test logs, package metadata and malicious peer payloads for unauthorized cross-boundary influence.

## 5. Can self-repair be valuable entirely offline on small ARM boards?
Benchmark deterministic monitors and small local model assistance with strict RAM/power budgets. Investigate reduced context, cached docs and selective invocation.

## 6. Can a research federation be privacy-preserving and Sybil-resistant?
Compare opt-in trust chains and reputation grounded in independent reproduction rather than votes. Measure leak risk from seemingly anonymized hardware profiles.

## 7. How can patches be presented so maintainers welcome them?
Study reviewer time, completeness of evidence, duplicate submissions and AI-generated explanation quality. Confirm with real maintainers instead of assuming volume is beneficial.

## 8. When is automatic tuning truly safe?
Compare static profiles versus adaptive trials under varying workloads and battery/thermal states. Require reversible settings, no data-loss potential and measured user benefit.

## 9. Can one recovery architecture span mutable and immutable Linux?
Model the semantic differences among apt/dpkg, Nix generations, Btrfs snapshots and OSTree deployments. Identify a minimal abstraction that does not pretend all platforms provide atomic undo.

## 10. What is the correct boundary for kernel intelligence?
Investigate user-space agents using existing kernel APIs versus adding any in-kernel component. Measure reliability/security debt versus utility. Default to user space until evidence justifies otherwise.

## 11. How to prevent long-term knowledge contamination?
Incident memory can accumulate false hypotheses, poisoned documents and stale hardware applicability. Evaluate source-weighted retrieval, contradiction detection and mandatory reproducibility.

## 12. How can self-improvement preserve a small trusted core?
Model separate build/test/release and rescue installations so an agent never rewrites the only code able to recover it. Design independent fallback before enabling software to upgrade itself.

## Research publication standard
Each answered question should produce a public report with scope, hypotheses, methods, raw redacted data, uncertainty, limitations, sources, artifacts and replication instructions. Claims without such evidence remain proposals.

## References
- Kernel testing guidance: https://docs.kernel.org/dev-tools/testing-overview.html
- Kernel generated-content expectations: https://docs.kernel.org/process/generated-content.html
- SLSA: https://slsa.dev/spec/v1.2/
