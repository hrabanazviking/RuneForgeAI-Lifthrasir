# Linux Kernel, Modules, Drivers and Patch Engineering
**Status:** research design; 2026-11-05.

## Fundamental distinction
Most early Lífþrasir services belong in **user space**, not the Linux kernel. Kernel residency expands the trusted computing base, increases crash risk and creates cross-version compatibility obligations. Kernel changes are justified only after measurements show that a safer existing interface cannot satisfy the requirement.

## Kernel research domains
- **Memory management:** page reclaim, compaction, OOM, huge pages, NUMA, slab allocation and pressure accounting.
- **Scheduling:** CPU affinity, latency, fairness, priorities, energy-aware scheduling and cgroups.
- **Filesystems:** VFS, Btrfs/ext4/XFS behavior, writeback, snapshots, integrity and recovery.
- **Networking:** routing, sockets, Netfilter/nftables, BPF, TCP congestion and security hooks.
- **Device drivers:** PCI/USB identification, firmware loading, DMA/IOMMU, suspend/resume and device power.
- **Security:** LSM hooks, Landlock, seccomp, capabilities and verified boot.
- **Observability:** tracepoints, ftrace, perf, BPF and structured counters.
- **Kernel lifecycle:** release candidates, stable updates, backports, config matrices and regression tracking.

## Patch investigation pipeline
1. Identify exact bad behavior, environment and relevant source subtree.
2. Search for prior fixes in mainline, stable and relevant distro/vendor trees.
3. Develop a minimal reproducer that triggers the bug on baseline.
4. Localize root cause with tracing, sanitizer or bisection.
5. Create one logical patch per distinct change.
6. Add regression test; build and boot relevant kernel configs in test VMs.
7. Exercise across architecture/configuration matrix; measure side effects.
8. Review licensing, safety, rationale, source provenance and maintainer pathway.
9. Hold for human review and sign-off before upstream submission.

Never auto-compile and load an experimental module on the user's live system.

## Out-of-tree module risks
Kernel internal interfaces do not offer a generally stable ABI for arbitrary external modules. DKMS-like rebuild approaches may help local development but do not guarantee compatibility. The project should prefer upstream supported interfaces and portable user space; kernel module research belongs in a separate optional subsystem.

## Livepatch cautions
Live patching is a specialized kernel subsystem with constraints; it is not a generic safe way for an agent to replace arbitrary running code. A patch still needs semantic compatibility, verification, affected architecture assessment and an explicit operational plan. Start with boot-based rollback, not speculative hotpatching.

## Test matrix
At minimum: selected x86_64 distro kernel, upstream kernel in QEMU, selected arm64 kernel in QEMU, debug/sanitizer build, no-network mode, memory-constrained VM, stress+idle workload, selected relevant Kconfig variants. Keep architecture results separate; no claim that passing one config establishes upstream readiness.

## Kernel artifacts
Every patch dossier must include base tree/commit, target subsystem, reproducer, minimal diff, kernel config, compiler/toolchain, architecture, test logs and review status. Maintain a signed or content-hashed immutable record of results. The human contributor is responsible for the DCO certification.

## Research questions
When is BPF sufficient versus module changes? Can a bug be reproduced in QEMU when it depends on vendor firmware? What is a safe mapping between a distro-patched kernel and the corresponding upstream subtree? How will Lifthrasir measure regressions that appear only after weeks of uptime?

## References
- Kernel process: https://docs.kernel.org/process/submitting-patches.html
- Kernel tests: https://docs.kernel.org/dev-tools/testing-overview.html
- Linux GPU drivers: https://docs.kernel.org/gpu/drivers.html
- Kernel coding style: https://docs.kernel.org/process/coding-style.html
