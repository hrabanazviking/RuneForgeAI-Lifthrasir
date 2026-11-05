# Book VI — Verified References, Research Ledger and Decision Questions
**Reviewed against official sources November 5, 2026.** Links may change; pin source version and retrieval date when implementing.

## 1. Linux contribution policy
**Primary:** [Linux patch submission](https://docs.kernel.org/process/submitting-patches.html). Establishes logical patch separation, checkpatch, recipients, DCO, reproducibility and maintainer process.

**AI-specific:** [AI coding assistants](https://docs.kernel.org/next/process/coding-assistants.html). Describes AI-assisted contribution requirements, human DCO responsibility, tests, attribution and avoiding automatic sending.

**Generated material:** [Kernel generated-content guidance](https://docs.kernel.org/process/generated-content.html). Review original text before applying a specific metadata convention; guidance can evolve by kernel tree version.

**Security reports:** [Security bugs](https://docs.kernel.org/process/security-bugs.html), [Threat model](https://docs.kernel.org/process/threat-model.html). Used to distinguish regular kernel bugs from qualifying vulnerabilities and to direct responsible reports.

**b4:** [Contributor workflow](https://b4.docs.kernel.org/en/latest/contributor/overview.html). Supports preparing and sending email-based patch series with maintainer-facing review.

### Engineering decisions
- Upstream Forge must not generate human `Signed-off-by` certifications or independently transmit patches.
- Human reviewer decides whether attribution and disclosures satisfy target subsystem expectations.
- Track `prepared`, `submitted`, `reviewed`, and `merged` separately. Never claim GitHub stars/contributions as proof of kernel acceptance.

## 2. Kernel testing and reproducing failures
[Kernel Testing Guide](https://docs.kernel.org/dev-tools/testing-overview.html) distinguishes in-kernel KUnit and externally exercised kselftest.  
[KUnit tests](https://docs.kernel.org/dev-tools/kunit/usage.html) apply to internal units.  
[kselftest documentation](https://docs.kernel.org/dev-tools/kselftest.html) covers feature/system behavior.  
[Linux Test Project](https://linux-test-project.readthedocs.io/en/latest/) provides broader reliability tests and cautions against running stress suites on production systems.  
[syzkaller usage](https://github.com/google/syzkaller/blob/master/docs/usage.md) describes virtual-machine kernel fuzzing and reproducer minimization.  
[syzkaller setup](https://github.com/google/syzkaller/blob/master/docs/linux/setup.md) covers kernel coverage and VM requirements.  
[QEMU system docs](https://www.qemu.org/docs/master/system/) cover system emulation, accelerators, storage and test guests.

### Decision
The first kernel research milestone must ship reproducer tooling and source-pinned lab manifests before claiming a self-generated patch is verified.

## 3. Linux observation and resource control
[Pressure Stall Information](https://docs.kernel.org/accounting/psi.html) provides pressure signals for CPU, memory and I/O.  
[Linux cgroup v2](https://docs.kernel.org/admin-guide/cgroup-v2.html) provides controller and group-level accounting.  
[Kernel tracing](https://docs.kernel.org/trace/index.html) describes deeper instrumentation.  
[systemd service reference](https://www.freedesktop.org/software/systemd/man/latest/systemd.service.html) documents units, restarts and watchdog behavior.

### Decision
Observe cheap counters first, escalate to more costly tracing on demand, and always account for observer overhead in benchmarks.

## 4. Security boundaries
[Landlock](https://docs.kernel.org/userspace-api/landlock.html) is an unprivileged mechanism for reducing accessible resources.  
[Linux Security Modules](https://docs.kernel.org/admin-guide/LSM/index.html) documents pluggable access-control infrastructure.  
[systemd execution and sandboxing](https://www.freedesktop.org/software/systemd/man/latest/systemd.exec.html) documents unit isolation and hardening.

### Decision
No single security feature is enough. Combine independent permission policy, typed broker, layered process isolation, version-aware capability probing and executable tests.

## 5. Deployment and rollback
[OSTree atomic upgrades](https://ostreedev.github.io/ostree/atomic-upgrades/) documents deployment-oriented update behavior.  
[openSUSE transactional-update](https://github.com/openSUSE/transactional-update) provides a separate transactional update approach.  
[QEMU VM snapshots](https://www.qemu.org/docs/master/system/) are appropriate for disposable lab state.

### Decision
Rollback is not universal across all Linux filesystems or packages. Every adapter must report actual capabilities and test a real recovery before promising reversibility.

## 6. Artifact trust and provenance
[SLSA 1.2](https://slsa.dev/spec/v1.2/whats-new) includes guidance on source and build provenance. Treat it as a model for requirements, not a certification automatically conferred by using GitHub Actions.

### Decision
Include a verifiable source version, build provenance, artifacts manifest, test logs and tool versions with every release and patch candidate.

---

## Research ledger template
Record each important technology decision as:
```yaml
id: RESEARCH-0001
question: What repair classes can be reversible on stock Kubuntu?
source_urls: []
source_versions: []
verified_on: 2026-11-05
status: research-needed
hypothesis: null
counterevidence: []
experiment_plan: []
result_artifacts: []
risk: medium
proposed_decision: null
human_reviewed: false
```

## High-priority unresolved research questions
1. Which kernel release and Kubuntu LTS image should be the first reference build?
2. Which boot and filesystem variants permit actually tested restoration?
3. Which least-privilege IPC implementation is easiest to audit?
4. Can AppArmor, seccomp, namespaces and Landlock rules be combined portably?
5. What exact sensor sampling budgets maintain desktop responsiveness on low-memory ARM?
6. Which local inference engine has the best diagnosis quality at equal resource and energy budgets?
7. How should TaskEnvelope and RepairPlan evolve while preserving old evidence?
8. Can the first Replicater experiments produce meaningful gains over simple deterministic heuristics?
9. Which security-detector classes have reliably low false-positive rates?
10. What subset of kernel testing can run economically on user-owned hardware?
11. What is the minimum trusted build/provenance implementation for public releases?
12. What are the privacy and legal consequences of voluntary cross-node benchmark sharing?
13. How do version-specific Linux kernel policies affect attribution of assisted changes?
14. What is the best independent review process for privileged broker changes?
15. How can an independent operator reproduce the full offline repair and recovery demo?

## Source hygiene
Do not assume a search snippet is the entire specification. Before code depends on a rule: read the complete relevant source, pin version, check whether it applies to a distribution kernel or mainline, record compatibility, write a test and log reviewer acceptance.

## Completion evidence ledger
Maintain a table of each release gate: **not started**, **in progress**, **failed**, **inconclusive**, **passed with evidence**, **externally audited**. Only link actual existing test artifacts. A roadmap chapter is not itself completion evidence.
