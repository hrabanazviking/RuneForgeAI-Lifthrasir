# Fuzzing, Sanitizers, Chaos Engineering and Fault Injection
**Status:** lab research; 2026-11-05.

## Goals
Discover safety and correctness failures before they reach actual users, and test whether Lífþrasir survives unexpected failures of its own components. Fuzzing is for controlled test environments and properly scoped code, not live attack traffic against third-party systems.

## Candidate fuzz targets
**Lífþrasir itself:** broker IPC decoder, agent event schema, config diff parser, signed evidence loader, package metadata, URL parser, archive extraction, event replay and federation protocol.  
**Linux components:** user-space parsers and well-defined kernel interfaces in isolated VMs with authorized test code.  
**Recovery:** combinations of sudden termination, incomplete writes, corrupted journal records, missing snapshots and clock changes.

## Kernel fuzzing
Syzkaller is an established coverage-guided kernel fuzzer; fuzz workers require carefully provisioned kernels and virtual machines. The project can integrate existing fuzzers rather than invent an unproven one. KCOV and sanitizers can help locate failing paths. Use isolated VM images, quotas and dedicated test hardware where needed; a kernel crash is an expected *test event*, not a reason to crash a production workstation.

## Sanitizer selection
KASAN for memory-safety classes, KCSAN for concurrency/data races, UBSAN for undefined behavior, KFENCE for low-overhead detection in suitable circumstances, KMSAN where tooling supports it. Each finds only certain bug classes and requires configuration support. Do not confuse sanitizer silence with correctness.

## Fault injection framework
Inject disk-full, EIO, ENOSPC, EAGAIN, DNS failure, packet loss, stalled IPC, killed subagent, expired consent, high memory pressure, repeated service restart, corrupted snapshot manifest and reboot during staged rollout. Fault injection must be bounded and isolated; never randomly corrupt production filesystems.

## Reduction and triage
A fuzz crash is a lead. Deduplicate by call stack, kernel commit, exact config, input and fault type. Minimize the reproducer. Check for already known upstream issue and fixed commits; classify severity only after evidence. Store raw crash inputs under access controls because they can be dangerous test artifacts.

## Multi-agent repair experiments
Replicater could assign independent workers to (1) minimize failing input, (2) find first-bad commit using bisection, (3) inspect relevant code, (4) propose test, and (5) challenge candidate fix. Independent verification must rerun original reproducer and broader regression suite.

## Metrics
Unique reproducible defects per CPU hour; percentage valid/nonduplicate; time-to-minimize; crash reproduction rate; fraction with regression test; downstream repair precision; false positives; accepted upstream fixes per *reviewed* work hour. Avoid reporting total raw crashes as if they were distinct vulnerabilities.

## Security disclosure
Do not automatically publish an unpatched exploitable defect, payload or exploit details. Follow upstream security procedures with a responsible human; security research artifacts may need confidential handling.

## References
- syzkaller documentation: https://github.com/google/syzkaller
- syzkaller setup: https://github.com/google/syzkaller/blob/master/docs/linux/setup.md
- Kernel testing overview: https://docs.kernel.org/dev-tools/testing-overview.html
- Kernel research guidance: https://docs.kernel.org/process/researcher-guidelines.html
