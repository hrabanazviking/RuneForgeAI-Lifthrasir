# Cross-Platform Validation Matrix and Release Gates
**Roadmap Appendix | November 2026 | Proposed tests, not completed results**

## Testing layers
- **Schema:** unit and property tests for versioned incident, hypothesis, plan, evidence and approval contracts.
- **Observer:** fixture tests for systemd, PSI, disk and networking signals; check false alarms and cost.
- **Knowledge:** provenance, version applicability, redaction and retrieval counterexamples.
- **Agents:** frozen dataset, blinded comparison of deterministic/single-agent/multi-agent modes.
- **Permissions:** independent policy enforcement and scope checks.
- **Repair:** baseline reproduction, approved change, functional verification, regression test, undo and interrupted transaction.
- **Kernel:** KUnit, kselftest, Linux Test Project and controlled syzkaller exercises.
- **Performance:** repeated controlled benchmarks with baseline and power/thermal conditions.
- **Federation:** voluntary-node simulations, contradictory data, privacy review and cancellation.
- **Release:** clean install, upgrade, rollback, uninstall and emergency-stop tests.

## Twenty initial synthetic fixture cases
1. Service unexpectedly inactive.
2. Service intentionally disabled, requiring abstention.
3. Invalid noncritical test configuration.
4. Missing demo service dependency.
5. Simulated isolated disk quota exhaustion.
6. Temporary network route missing inside a lab guest.
7. DNS fault isolated from general connectivity.
8. Intermittent service crash and restart loop.
9. Evidence collector lacks a required permission.
10. Local AI model is offline.
11. Source documentation has obsolete version guidance.
12. Two investigators reach contradictory conclusions.
13. Normal CPU-intensive build mistaken for threat.
14. A process identifier is stale.
15. Host reboots during a staged repair.
16. Free disk becomes too low for an evidence report.
17. Sensor clock jumps or is corrected.
18. Proposed plan no longer matches target state.
19. Filesystem lacks guaranteed snapshot recovery.
20. A supposedly fixed service fails during the soak interval.

Each fixture needs an independent test oracle, exact VM image identifier, expected observation, expected authorized/denied action, expected recovery state and complete machine-readable report. A 'pass' means observed results match those independent expectations.

## Kernel laboratory matrix
- x86-64 pinned VM build and validation.
- arm64 cross-built, emulated, or designated laboratory build.
- Source commit and kernel config stored per run.
- KUnit for small internal kernel units; kselftest for externally visible interfaces.
- LTP and syzkaller only in disposable labs, with bounded resource use.
- Real hardware-specific GPU, accelerator or driver results must be validated on designated physical hardware rather than inferred from virtual emulation.
- Known failures, skipped tests and untested configurations are explicitly recorded.

## Performance experiment contract
Predeclare workload, baseline, operating system revision, compiler, CPU/GPU frequencies if available, thermal conditions, iterations, sample-size rationale, result distribution, energy, memory consumption and unacceptable regressions. Report typical and tail latency. Preserve raw evidence and include negative results. A generated optimization is not 'proven' after one fast run.

## Release gates
**G0:** Requirements, supported hardware and threat model documented.  
**G1:** Repeatable VM laboratory and evidence collection.  
**G2:** Native observer read-only tests pass.  
**G3:** Authorization policy and recovery have independent tests.  
**G4:** Eir repair and undo proven on supported fixture set.  
**G5:** Optional AI models cannot impair recovery.  
**G6:** Replicater demonstrates measured additional benefit.  
**G7:** Thor security findings meet measured precision/recall targets.  
**G8:** Kernel experiment has reproducible failure and candidate tests.  
**G9:** Cross-distro package install and uninstall validated.  
**G10:** Independent security review and operational audit.  
**G11:** Federation privacy and trust reviewed before any opt-in preview.  
**G12:** Linux patch contributions submitted only by a responsible human.

## Evidence ledger format
Every release claim should record: issue ID, build commit, test environment, commands, expected and actual outcomes, CI artifact URL, independent reviewer, risk level, known limitations, and recovery evidence. No green status without an actual record.

## References
- https://docs.kernel.org/dev-tools/testing-overview.html
- https://docs.kernel.org/dev-tools/kunit/usage.html
- https://docs.kernel.org/dev-tools/kselftest.html
- https://linux-test-project.readthedocs.io/en/latest/
- https://github.com/google/syzkaller/blob/master/docs/usage.md
- https://www.qemu.org/docs/master/system/
