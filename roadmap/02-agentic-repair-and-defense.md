# Book II — Local AI, Replicater and Thor
**Implementation gates P6–P8; proposed work, November 2026.**

## P6: Optional local inference
Build a model-neutral backend interface: capability probe, inference with structured output, cancellation, deadlines, model provenance, memory and CPU/GPU quotas. Provide a deterministic mock adapter and a local inference adapter, with Project A.E.S.I.R. as a possible integration. On network loss or model failure, all observation, undo and emergency controls must continue working. Document input size, token usage, latency, memory use, context provenance, and whether the model performed inference or abstained.

### Work packages
- Define TaskEnvelope and ModelResult schemas with versioned JSON test fixtures.
- Implement three prompt templates: incident summary, rival causal hypotheses, experiment proposal.
- Add structured JSON validation, response length caps, source citations and cancellation.
- Measure token cost and correct-diagnosis rate on a frozen corpus of incidents.
- Add opt-in provider settings without automatic cloud fallback.
- Exercise 50 ambiguous cases, including false leads and expected abstentions.

**Release gate:** The system still repairs known supported faults safely when no model can load.

## P7: Replicater's bounded engineering workforce
Develop an auditable job DAG. Workers: incident captain, investigator, reproducer, source archaeologist, patch designer, independent verifier, adversarial reviewer and documentation steward. Every worker has exact tool permissions, capped resource budget, cancellation token, data sensitivity level and expected output schema.

### Work packages
- Durable queue with QUEUED/RUNNING/SUCCEEDED/INCONCLUSIVE/FAILED/CANCELLED states.
- Limited concurrency based on CPU, RAM, PSI and battery profile.
- Independent alternative hypotheses, not merely copies of a shared answer.
- Separate read-only research tools from write-capable disposable-lab tools.
- Reproducer and negative control required before declaring a technical root cause.
- Fresh verification workspace, unmodified reference branch and artifact hashes.
- Arbitration report ranks test coverage, causality, regressions and operational risk.
- Crash recovery marks uncertain outcomes, avoiding duplicate effects.

### Research trial
Compare deterministic heuristics, one-model reasoning, and 2–4 coordinated agents on an identical labeled fixture corpus. Measure correct findings per unit energy and time, not only success claims. Preserve all failed and inconclusive results.

**Release gate:** Parallel agents improve a predeclared metric while staying within resource limits and without expanding authority.

## P8: Thor, the defender
Thor provides narrowly defined endpoint threat observation, cautious triage, and human-controlled, reversible containment. Do not treat unknown activity as malicious merely because it is unusual or resource intensive.

### Work packages
- Metadata-only process and service integrity checks with user consent.
- Normal-behavior baselines for software builds, gaming, backups and AI inferencing.
- Source provenance, package ownership and corroborated event correlation.
- Explainable severity assessment with contradictory evidence and uncertainty.
- Read-only detection first, then approved temporary response with undo.
- Eir coordination to restore a system after a reviewed security incident.
- Responsible disclosure workflow for possible kernel vulnerabilities.
- False-positive, resource overhead, model-outage and user-revocation tests.

### Final validation
Use a corpus mixing harmless developer workloads and known laboratory threats. Classify with independent evidence, measure precision/recall, ensure operator override and prove reversibility for the supported response actions. Release only the detection classes that have passed independent testing.

## Cross-agent invariants
Agents never determine their own privileges, edit their success criteria, or certify patches. Their outputs are proposals subjected to deterministic checks. Each answer is traceable to evidence and software versions.

## References
- https://docs.kernel.org/process/threat-model.html
- https://docs.kernel.org/process/security-bugs.html
- https://docs.kernel.org/admin-guide/LSM/index.html
- https://docs.kernel.org/admin-guide/cgroup-v2.html
