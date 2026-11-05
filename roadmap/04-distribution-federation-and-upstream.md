# Book IV — Multi-Distro Linux, Shared Evolution and the Upstream Forge
**Roadmap gates P11–P16 | November 2026 | Proposed features**

## P11: Portability and hardware support
Create an explicit capabilities adapter interface for each distro: service manager, package manager, boot mechanism, snapshot strategy, MAC policy, network stack and hardware interfaces. Probe support instead of assuming features exist. Start with pinned Kubuntu, expand to Debian, Fedora/RPM, openSUSE and Arch, each with documented differences. Add arm64 SBC and x86-64 desktop matrix; treat more architectures as research until validated.

**Test gate:** supported install, observer, permitted repair, offline mode, recovery and uninstall pass on two genuinely distinct distros and two hardware classes. Unsupported functionality always reports it is unsupported.

## P12: Packaging, user experience and 1.0
Implement CLI status, incidents, explanation, plan inspection, approval, undo, stop and privacy settings. Follow with optional KDE/Qt UI, keyboard navigation, understandable incident timeline, evidence citations, task budgets and patch review.

Deliver reproducible packages, signed release artifacts, versioned config migration, local-only default, operator documentation, developer documentation and uninstall/recovery procedures. Maintain a security review checklist and supported-version policy.

**1.0 boundary:** Focus on audited local monitoring and selected safe repair actions. No claim that experimental kernel rewriting or federation is production-ready.

**Test gate:** independent operators can install, use, upgrade, recover and remove the tool on all advertised platforms, with no model or network connection.

## P13: Voluntary distributed research network
Federation exists to share *sanitized evidence and reproducible experiments*, not to grant other computers control of host systems. Users opt in per data category and can inspect exact outgoing payloads. Nodes exchange versioned incident summaries, test fixtures, benchmark results, code revisions and candidate research packages.

Every remote artifact is untrusted until reproduced locally. Use content hashes, contributor identifiers, quotas, explicit expiration and data minimization. Detect duplicated reports and contradictory measurements without voting disputed results into a false consensus.

**Test gate:** simulated network of 20 nodes survives outages, contradictory evidence and withdrawn consent. No incoming peer can bypass local authorization or cause an uncontrolled production action.

## P14: Upstream Forge
The agent workforce may prepare, never unilaterally send, Linux kernel patches. A patch dossier should include source commit ID, reproducer, minimal diff, architecture/kernel configuration, compiler and static analysis logs, relevant KUnit/kselftest results, performance/regression checks and limits of verification.

Use the Linux kernel's documented contribution route: identify maintainers with MAINTAINERS and get_maintainer.pl, prepare with git format-patch or b4, and give a human the final review and submission decision. AI agents must not add human DCO Signed-off-by signatures. Distinguish bug reports from security disclosures and follow current kernel policy.

**Test gate:** a source-pinned patch candidate passes its required test matrix and receives genuine human review. Upstream acceptance is not guaranteed and can never be inferred from a local test.

## P15: Advanced self-evolving experiments
Explore novel scheduler policies, memory/resource tuning, storage behavior, hardware inference acceleration, power optimizations and research task allocation. Each proposed improvement must beat an unchanged baseline in replicated measurements; track regressions and side effects. Try a smaller reversible configuration optimization before a riskier kernel patch.

**Test gate:** at least one improvement is independently reproducible across distinct hardware and is no worse under predeclared safety, fairness, energy and latency metrics.

## P16: Ecosystem completion
Build maintainership and support policy, stable external plugin APIs, a transparent security process, release engineering stewardship, onboarding documentation, recurring audits and contributor accessibility. No one developer, service or AI provider should become an operational single point of failure.

**Completion:** independent maintainers can build, test, run, secure, troubleshoot and improve Lífþrasir; offline local behavior continues even without federation.

## Sources
- https://docs.kernel.org/process/submitting-patches.html
- https://docs.kernel.org/next/process/coding-assistants.html
- https://docs.kernel.org/process/security-bugs.html
- https://b4.docs.kernel.org/en/latest/contributor/overview.html
- https://ostreedev.github.io/ostree/atomic-upgrades/
- https://slsa.dev/spec/v1.2/whats-new
