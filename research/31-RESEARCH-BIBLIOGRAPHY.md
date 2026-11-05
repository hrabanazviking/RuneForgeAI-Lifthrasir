# Research Bibliography and Verification Register
**Status:** curated official references consulted for this initial research corpus; 2026-11-05.

## Source verification method
Prefer kernel.org, docs.kernel.org, original upstream project manuals and vendor compatibility tables. URLs point to live docs and may change. A repository document should cite the exact source relevant to its claim. For evolving details (especially AI submission policy, hardware matrices and licensing), re-check before implementation or publication.

## Kernel development, contribution and security
1. Linux kernel development process — https://docs.kernel.org/process/development-process.html — community contribution lifecycle.
2. Submitting patches — https://docs.kernel.org/process/submitting-patches.html — maintainer routing, patch format, human DCO, review.
3. Submission checklist — https://docs.kernel.org/process/submit-checklist.html — style, build and test expectations.
4. AI Coding Assistants — https://www.kernel.org/dochtml/latest/process/coding-assistants.html — humans sign, model/tool attribution.
5. Kernel Guidelines for Tool-Generated Content — https://docs.kernel.org/process/generated-content.html — transparency and maintainer bandwidth.
6. Researcher guidelines — https://docs.kernel.org/process/researcher-guidelines.html — reproducer and research evidence.
7. Licensing rules — https://docs.kernel.org/process/license-rules.html — SPDX and compatibility.
8. Security bugs — https://docs.kernel.org/process/security-bugs.html — responsible reporting.
9. b4 workflow — https://b4.docs.kernel.org/en/latest/ — patch series management.

## Linux internals, testing and instrumentation
10. Kernel tracing guide — https://docs.kernel.org/trace/index.html — ftrace and tracepoints.
11. Kernel testing overview — https://docs.kernel.org/dev-tools/testing-overview.html — KUnit and kselftest.
12. Kernel selftests — https://docs.kernel.org/dev-tools/kselftest.html — in-tree selftest discipline.
13. Syzkaller — https://github.com/google/syzkaller — coverage-guided kernel fuzzer.
14. Syzkaller setup — https://github.com/google/syzkaller/blob/master/docs/linux/setup.md — VM fuzz workers.
15. Cgroup v2 — https://docs.kernel.org/admin-guide/cgroup-v2.html — resource controls.
16. PSI — https://docs.kernel.org/accounting/psi.html — resource stall monitoring.
17. GPU driver guide — https://docs.kernel.org/gpu/ — DRM driver internals.
18. AMDGPU — https://docs.kernel.org/gpu/amdgpu/index.html — graphics/compute driver structure.
19. Landlock — https://landlock.io/ — unprivileged sandboxing.
20. LSM — https://docs.kernel.org/admin-guide/LSM/index.html — kernel security modules.

## Transactional systems and services
21. systemd.service — https://www.freedesktop.org/software/systemd/man/latest/systemd.service.html — restart and watchdog mechanics.
22. systemd.exec — https://www.freedesktop.org/software/systemd/man/latest/systemd.exec.html — service hardening and process environment.
23. OSTree atomic upgrades — https://ostreedev.github.io/ostree/atomic-upgrades/ — deployment changes.
24. OSTree rollback — https://ostreedev.github.io/ostree/atomic-rollbacks/ — recovery paths.
25. openSUSE transactional-update — https://github.com/openSUSE/transactional-update — distro atomic update framework.
26. NixOS manual — https://nixos.org/manual/nixos/stable/ — declarative configuration and generations.

## Accelerators and supply chain
27. AMD ROCm Radeon/Ryzen compatibility — https://rocm.docs.amd.com/projects/radeon-ryzen/en/latest/docs/compatibility.html — versioned vendor matrix.
28. SLSA specification 1.2 — https://slsa.dev/spec/v1.2/ — supply chain requirements.
29. SLSA provenance — https://slsa.dev/spec/v1.2/provenance — tracking artifact production.
30. SPDX — https://spdx.org/licenses/ — standardized license identifiers.

## Evidence quality annotations
- **Normative:** published process or specification. Applicable only where in scope.
- **Descriptive:** tool's documented features. Does not verify Lifthrasir implementation.
- **Vendor-conditional:** exact support matrix; changes by release.
- **Proposed design:** a project choice or untested hypothesis, explicitly labeled.
- **Experimental finding:** only after reproducible results are deposited with data and hash.

## Research gaps requiring fresh work
Formal verification of policy broker, measured security overhead of kernel telemetry, cross-version deployment rollback reliability, NPU operator compatibility by hardware, model benchmarking under actual workloads, federated poisoning mitigation, long-horizon repair regression data, maintainer interviews and accessibility testing.

## Update policy
On implementation milestones, attach exact retrieved source revision/date to decisions and keep a CHANGELOG. Never silently convert 'planned' into 'implemented' or 'observed' into 'verified'. Cite real benchmarks and include negative outcomes.
