# Book III — Kernel Research, Patch Science and Optimization
**Phases P9–P10 | Proposed implementation | 2026-11-05**

## P9. Establish the kernel experimentation laboratory
**Purpose:** Convert unusual Linux problems into reproducible, well-tested *candidate fixes* without endangering a person's everyday operating system.

### Kernel sources and builds
- Mirror official kernel source and pin every experiment to a full commit ID, configuration checksum and toolchain version.
- Begin with x86-64 guests; add arm64 cross-compile and emulated test guests when test infrastructure is stable.
- Build baseline and candidate from identical source and configuration except for explicit patch delta.
- Keep kernel config, command line, initramfs, firmware/driver details and architecture in machine-readable experiment manifests.
- Run warning checks and source-style tools; use kernel test systems rather than inventing substitute QA.
- Never judge a patch by whether a compiler succeeds alone.

### Reproducers
1. Describe symptom and known affected versions.
2. Construct minimum test that reliably fails on baseline.
3. Record observed failure across several clean runs, including failure frequency and timeout behavior.
4. Create a control case that should not fail.
5. Apply the proposed patch in a separate disposable workspace.
6. Run unchanged reproducer and regression tests.
7. Attempt to falsify the repair by reversing the patch and re-running.
8. Archive exact evidence and identify scope of validity.

### Kernel validation tools
| Tool | Intended use | Gate |
|---|---|---|
| KUnit | Unit tests of kernel internals | Existing and newly added relevant cases pass |
| kselftest | Kernel behavior visible through user-space interfaces | Relevant feature tests pass or known skips explained |
| Linux Test Project | Broader kernel and system reliability tests | Run exclusively on lab machines; report skips |
| syzkaller | Coverage-guided kernel fuzzing and crash minimization | Run against disposable guests, within quotas |
| KCOV | Feedback for coverage-based tests | Coverage maps attached where meaningful |
| Coccinelle, sparse, smatch | Static analysis support | New diagnostics investigated, not blindly suppressed |
| checkpatch.pl | Kernel style and common-issue checks | Justify warnings, resolve errors |
| QEMU/KVM | Isolated guest environment | Repeatable reset and independent host/guest boundary |

LTP documentation explicitly warns that certain stress suites must not be used on production systems. syzkaller supports disposable VM fuzzing and reproducible crash investigations. Those constraints are implementation requirements, not optional suggestions.

### Patch dossier
Produce an evidence package with (a) problem and affected commit, (b) test reproducer, (c) control outcome, (d) minimal diff, (e) compiler and analyzer logs, (f) test and benchmark matrix, (g) limitations and regressions, and (h) reviewer checklist. Human contributors decide whether and how to submit it upstream.

**P9 acceptance:** A manually reviewed candidate fix from a controlled kernel regression can be rebuilt and independently verified from a clean checkout; no false claim of upstream acceptance.

---

## P10. Measurable Linux self-improvement
### Candidate domains
1. CPU scheduling policy and application responsiveness.
2. Memory allocation, fragmentation, reclaim, swap/zswap and pressure behavior.
3. Process and cgroup memory limits; batch-agent scheduling.
4. Storage caching, writeback and file-system behavior.
5. Network stack latency and small-packet workload performance.
6. GPU, graphics/DRM and driver configuration compatibility.
7. NPU and accelerator-aware local inference.
8. Battery, thermal management, device sleep and power efficiency.
9. Boot speed, startup ordering and service reliability.
10. Compilation and package/build pipeline efficiency.

Optimization may be a **configuration proposal**, a better **user-space scheduling policy**, or a **kernel code candidate**. The least invasive effective alternative is preferred.

### Benchmark science
For every candidate, declare the baseline, workload, measurement tool, sample size, warming strategy, random seed, repetitions, confidence interval, thermal condition and failure threshold. Test on more than one machine where feasible. Report p50/p95, variance, energy and regressions; do not cherry-pick best result. A speed improvement that increases corruption risk, power use or latency spikes may be a net regression.

### Hardware test classes
- General-purpose x86-64 laptop with mixed desktop, compiler and local inference workloads.
- High-unified-memory APU as a separate memory pressure and accelerator target.
- ARM64 SBC with constrained RAM, CPU-only inference and removable-storage stress.
- Optional discrete GPU machine with real PCI passthrough only on an approved designated test host.
- Offline battery/thermal-limited configuration.

### Patch promotion gates
Candidate → lab verified → cross-version verified → independently reviewed → authorized test deployment → monitored rollout → upstream dossier. Use explicit `UNSUPPORTED` and `INCONCLUSIVE` states where needed. Revalidate whenever hardware, kernel release, firmware or application workload changes.

### Control experiment examples
- A proposed memory allocator improvement must beat unchanged allocator under equivalent workloads without unacceptable fragmentation, alloc latency or OOM changes.
- A scheduler change must improve selected responsiveness without starving background tasks.
- GPU tuning must demonstrate stability across sustained runs and power-state transitions, not just short benchmarks.
- Battery improvements must be measured at comparable performance and brightness, with repeatable external power conditions.

## Phase dependency
Never deploy a kernel experiment to the ordinary user's boot environment directly from an AI result. High-risk deployment needs a known-good boot entry, full recovery plan, operator authorization and documented support scope.

## Sources
- https://docs.kernel.org/dev-tools/testing-overview.html
- https://docs.kernel.org/dev-tools/kselftest.html
- https://docs.kernel.org/dev-tools/kunit/usage.html
- https://linux-test-project.readthedocs.io/en/latest/
- https://github.com/google/syzkaller/blob/master/docs/usage.md
- https://www.qemu.org/docs/master/system/
- https://docs.kernel.org/process/submitting-patches.html
