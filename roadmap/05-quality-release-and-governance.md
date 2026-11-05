# Book V — Engineering Quality, Release Validation and Project Governance
**Applies to all phases | Proposed release and safety specification | November 2026**

## Quality model: four independent proof classes
1. **Functional:** tests show the feature delivers the promised outcome for the specified user and machine.
2. **Safety:** system refuses out-of-policy operations, protects user control, and preserves recovery.
3. **Scientific:** a test or optimization result is repeatable and compared against meaningful controls.
4. **Operational:** the software is installable, maintainable, measurable, reversible, debuggable and removable.

A feature cannot become production-ready if even one mandatory proof class is missing.

## Continuous integration tiers
**PR fast lane:** formatting, lint, license headers, dependency check, secrets check, unit tests, event schema validation, static analysis and documentation link tests.

**Integration lane:** version-pinned Kubuntu VM, service status fixtures, deterministic authorization tests, incident database migration, rollback and offline network emulation.

**Security lane:** policy and broker boundary tests, sandbox configuration verification, hostile tool-output regression tests, restricted execution, cross-user access tests, dependency integrity and audit review.

**Kernel laboratory lane:** source-pinned build, relevant kselftest/KUnit suites, targeted Linux Test Project cases, syzkaller experiments only in disposable VMs, then a failure/reproducer dossier.

**Release lane:** architecture and distro matrix, clean install/upgrade/uninstall, package signatures, software bill of materials, recovery smoke test, docs and manual accessibility review.

## The repair verification matrix
Each supported repair recipe needs at least:
- A passing healthy baseline case;
- A reliably failing fixture case;
- A repair that fixes the same fixture;
- A case where the proposal must abstain;
- A rejection case for invalid consent or unsupported platform;
- A rollback success case;
- An interrupted execution recovery case;
- A system reboot and offline validation case;
- A resource-pressure and insufficient-storage case;
- A regression control on a dependent workload.

Report pass count, skip count and explicitly known holes. Skipped tests do not become successes.

## Performance and reliability scorecard
Collect memory resident size, idle CPU, disk writes, battery/energy use where measurable, detection delay, false-alert rate, repair success, abstention rate, rollback success, uptime impact, model token count, agent concurrency and cost per verified diagnosis. Preserve distributions and outliers; compare test environment revisions.

**Initial acceptance targets are hypotheses until calibrated.** Do not invent universal latency, wattage or failure-rate numbers. Set per-platform envelopes after measuring a no-agent baseline.

## Data governance
- Consent to collection does not imply consent to network export.
- Private logs, precise device identifiers, paths, secrets and access tokens require careful minimization.
- Default local retention bounded by size and age; export controls show actual payload.
- All events carry origin and redaction status; imported peer data remains untrusted.
- Human users can inspect, delete and stop observation where technically possible.
- Test with synthetic private data and verify removal from exported bundles.

## Supply-chain defense
Record source revisions, dependency versions, compiler/toolchain, build recipe and artifact hashes. Create SBOM and provenance documents. Use signing and verifiable releases. Evaluate SLSA 1.2 as a framework without making compliance claims until requirements are met. Dependencies and models should have clear provenance and license checks.

## Human control and governance
- A maintained code-of-conduct and contribution guide welcome non-experts while preserving technical rigor.
- Privileged broker changes require special review and a recorded architecture decision.
- Kernel candidate changes must pass the human DCO procedure and current subsystem policies.
- Security findings follow responsible reporting rather than automatic public disclosure.
- Agents may draft summaries, patches and tests, but cannot certify release safety.
- Changes to authorization policy cannot be approved by the same agent that proposed them.

## Release checklist
- [ ] Feature and risk scope reviewed
- [ ] All changes tied to issue/ADR
- [ ] Test matrix and source provenance recorded
- [ ] Recovery and uninstall documented
- [ ] No unsafe permissions granted by default
- [ ] No known critical failure in security gate
- [ ] Offline mode verified
- [ ] UI copy and accessibility reviewed
- [ ] Versioned schema migration and rollback tested
- [ ] Reproducible packages and checksums available
- [ ] Named human reviewer accepts release notes
- [ ] Current supported distros and exclusions published

## Community and sustainability
Support tiers should be honest: officially tested, community tested, experimental and unsupported. Create a maintenance policy for old releases, security fixes, distro adapters and model updates. Provide a public test-result ledger. Record rejected patches and negative benchmark results so future agents do not repeat dead ends.

## Operating model
For each milestone create an epic with outcomes, dependencies, design review, issue breakdown, failing fixture, implementation tests and a documented pass gate. No phase gets marked complete because its Markdown plan is written or because an AI agent reports 'finished'.

## Completion test
An independent contributor must be able to use the public source and instructions to reproduce the flagship offline repair demo, its abstention cases and full recovery test, with no undocumented private service or credential.

## References
- https://docs.kernel.org/dev-tools/testing-overview.html
- https://linux-test-project.readthedocs.io/en/latest/
- https://www.freedesktop.org/software/systemd/man/latest/systemd.exec.html
- https://slsa.dev/spec/v1.2/whats-new
- https://docs.kernel.org/process/submitting-patches.html
