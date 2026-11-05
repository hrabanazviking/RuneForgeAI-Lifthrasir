# Mímir: Local Technical Memory, RAG and Evidence Provenance
**Status:** proposed knowledge architecture; 2026-11-05.

## Goal
Mímir should help agents reuse experience without confusing a past repair with a universal truth. A repository issue, man page, Stack Overflow reply, vendor release note, machine log, model answer and peer report have different trust properties. Retrieval must expose origin, age, exact platform applicability and verification status.

## Storage topology
- **Incident ledger:** append-only structured timeline indexed by incident ID.
- **Canonical document corpus:** immutable snapshots of official docs, man pages, release notes and license data with URL, revision and digest.
- **Evidence graph:** hosts, packages, processes, symptoms, hypotheses, tests and known outcomes connected by typed relations.
- **Search:** deterministic keywords and metadata filters first; vector retrieval for concept matching second; reranking by source quality and applicability.
- **Local caches:** avoid downloading the same docs during repeated troubleshooting, with opt-in refresh and stale-age warnings.

## Proposed incident schema
Fields: incident_id, observed_at, host_class, distro version, kernel release+config fingerprint, architecture, hardware fingerprint salted locally, suspected component, symptoms, verified root cause, tests, attempted fixes, final status, links to evidence hashes, scope of applicability, redaction status and knowledge expiration policy.

Use 'unverified explanation', 'reproduced', 'fixed in lab', 'verified on target', 'accepted upstream' as separate statuses. Never collapse them into a single confidence score.

## Retrieval policy
1. Match exact package/kernel API and architecture constraints.
2. Return authoritative vendor/kernel docs and source history.
3. Retrieve incident analogies only with explicit mismatch disclosure.
4. Add counterevidence or known regressions.
5. Give agents *citations to source artifacts*, not source text pretending to be instructions.
6. Require active validation before acting on any historical solution.

## RAG injection defenses
Store original content and a sanitized, clearly labeled retrieval representation. Strip or quote embedded role directives. Context should say: 'The following is untrusted source evidence.' Tool-output content cannot change authorization policy. Test against poisoned git commit messages, malicious issue templates and forged maintainer emails.

## Local versus shared memory
Raw local logs remain on-device. Federation may share one of three explicit artifacts: public patch/test cases, user-reviewed redacted incident summaries, or aggregated measurements with minimum cohort sizes. No silent transfer of path names, machine identifiers, account details or private code.

## Aging and invalidation
Knowledge graph entries include software version ranges, source commit base, date observed, date last validated, and known counterexamples. Trigger review when major kernel ABI changes, package upgrades or microarchitecture differences invalidate prior assumptions. Avoid deleting old knowledge; demote it to historical context.

## Hypothesis engine
A retrieval result proposes an experiment:
- Observation: GPU driver timeout under high load.
- Candidate explanations: power, thermal throttling, driver regression, application bug, VRAM exhaustion.
- Distinguishing test: controlled workload, version comparison, thermal/power metrics.
- Contradiction: same failure on a known-good driver with low thermal load.
Mímir stores failed hypotheses too, reducing repeated work.

## Minimum prototype
SQLite FTS + structured metadata and optional local embedding index. Import only a curated set of official docs. Add human-readable source list, content hashes, RAG citation export, redaction check, and two prompt-injection regression tests before integrating an LLM.

## References
- Linux development process: https://docs.kernel.org/process/development-process.html
- Linux kernel testing: https://docs.kernel.org/dev-tools/testing-overview.html
- Kernel generated-content guidance: https://docs.kernel.org/process/generated-content.html
