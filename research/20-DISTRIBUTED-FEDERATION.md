# Distributed Linux Research Federation
**Status:** long-range research concept; opt-in only; 2026-11-05.

## Vision
Many Linux systems can share *research artifacts* to reproduce bugs on different architectures and compare potential fixes, without pooling their private data or granting one host control over another. A federation is a research network, not a remote-execution botnet.

## Trust model
Every node is sovereign. Local policy governs enrollment, outbound data, remote tasks, resource quota, permitted tools and disconnect. Nodes authenticate peers but do **not** assume trusted results. Each result is independently validated and labeled with trust/provenance.

## Allowed artifact types
1. Publicly redistributable source code references and commit hashes.
2. Minimal synthetic reproducers without secrets.
3. Source/build/test manifests with machine-class metadata.
4. Redacted benchmark aggregates with version and methodology.
5. Human-reviewed candidate patch dossiers.
6. Publicly disclosed issue reports and de-identified regression records.

Raw logs, private files, credentials, unique machine IDs, network packet captures and arbitrary shell commands are not acceptable automatic federation payloads.

## Scheduler
Publish capability advertisements: architecture, kernel family, virtualization, memory class, supported toolchains, active job quota, power policy and privacy setting. The coordinator selects nodes matching a task's requirements. Tasks are immutable and content-addressed; execution is limited to isolated sandbox contexts, with signed receipts and per-node budget.

## Distributed consensus is not proof
Ten nodes accepting one patch may all reproduce the same mistake. Require implementation diversity, distinct hardware, independent regression suites and verification of artifact identity. Attach confidence to exact tested configurations. Resist fake peer identities (Sybil attacks), collusion and fabricated benchmark data.

## Protocol outline
**Discover → Negotiate → Consent → Assign immutable task → Run sandbox → Attest result → Independent replicate → Aggregate → Human review.** Each task has expiry, network policy, resource cap and complete cancellation support. Never allow remote peers to change the local host's policy.

## Peer reputation
Reputation is based on reproducible outcomes, not raw throughput or number of patches proposed. Bad results can reflect hardware differences rather than fraud; keep audit evidence and permit appeal. Do not create incentives to maximize fake patch volume.

## Governance
Public opt-in and off switch; plain-language node role; no mandatory central server; optional self-hosted coordination. Build for hostile internet conditions: stale nodes, NAT, intermittent access, replayed messages and revoked keys. Start with two user-controlled VMs before exploring public federation.

## Hardware and power
Mobile systems and laptops should default to 'no remote jobs on battery' or strict energy budgets. Never use volunteer devices for stealth computing. A node must be able to pause immediately for foreground workloads.

## Research experiments
Pair x86_64 and ARM64 VMs; share a trivial synthetic reproducer and compile/test candidate; compare manifests and verify independent result; simulate forged peer attestation, lost connectivity and stale source commit. Measure resource and privacy overhead.

## References
- SLSA specification: https://slsa.dev/spec/v1.2/
- Kernel research guidelines: https://docs.kernel.org/process/researcher-guidelines.html
- Linux test frameworks: https://docs.kernel.org/dev-tools/testing-overview.html
