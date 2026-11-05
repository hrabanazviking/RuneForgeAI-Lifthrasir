# Threat Model and Trust Boundaries
**Status:** proposed security analysis; 2026-11-05.

## Protected assets
Operating system availability; user data and secrets; package and boot integrity; developer keys; filesystem correctness; patch authorship/provenance; local evidence; agent decision history; network credentials; upstream reputation.

## Adversaries and failure classes
1. **Prompt-injection attacker:** Places hostile instructions in logs, filenames, documentation, issue reports, terminal output or RAG sources.
2. **Compromised package or repository:** Supplies malicious source or artifact masquerading as a fix.
3. **Local unprivileged attacker:** Forges symptoms or tries to trick privileged repair broker.
4. **Malicious federation peer:** Submits fraudulent benchmark, fabricated evidence or malicious test fixtures.
5. **Agent malfunction:** Confidently hallucinated shell commands, goal drift, duplicate repair loops.
6. **Hostile environment:** Partial disk failure, OOM, network outage, thermal throttling or time skew.
7. **Supply-chain attacker:** Replaces model, dependency, test binary or build container.
8. **Insider/configuration error:** Over-broad grant, forgotten credentials, stale rollback snapshot.

## Mandatory trust boundaries
- **Logs / retrieved pages → model:** input is data; never authorization.
- **Model → policy engine:** proposals must be parsed against a strict typed schema; no free-form command execution.
- **Policy → broker:** short-lived exact-resource token, signer identity, plan hash, expiry and user consent when required.
- **Broker → host:** typed actions such as restart_unit, stage_package_update, quarantine_file, never general root shell.
- **Lab → host:** artifact promotion only after independent verifier; no mounting writable host files into untrusted test workloads.
- **Federation → local research:** untrusted remote results cannot bypass local replication or policy.
- **Upstream → outside world:** no unattended public bug disclosures or commits.

## Privilege ladder
**L0** read public health metrics. **L1** read additional consented diagnostic data. **L2** construct local proposal or modify disposable test VM. **L3** restart explicitly allowlisted noncritical service under monitored conditions. **L4** change live packages or firewall after direct per-action approval. **L5** touch kernel, boot, partitions, encryption, keys or filesystem repair only via dedicated maintenance environment and human-controlled recovery.

No 'always approve everything' mechanism for L4-L5. A higher-level agent cannot grant its own lower-level privileges.

## Prompt injection defenses
Normalize and label every tool output as untrusted. Run exact-schema validation with maximum lengths, byte caps and expected types. Remove control characters from display; never promote a quotation into an executable action. Test against fabricated journal messages: 'SYSTEM: run rm -rf', fake policy JSON, forged maintenance notice, false package maintainer instructions and copy-pasted terminal snippets.

**Key test:** If an attacker controls the entire contents of one log entry, it must be impossible to cause a privileged action without a separately validated plan and authorization.

## Containment
Use namespaces, cgroups, seccomp, Landlock and MAC systems as available. These are layered constraints, not magic protection against a compromised kernel. For tests involving kernel modules, custom kernels or unknown driver code, use a disposable virtual machine, ideally on a separate test machine for high-risk cases.

## Secure failure defaults
When evidence contradicts a proposed fix: pause. When telemetry disappears: stop experimentation. When integrity of broker is questionable: disable all writes and show an actionable report. When a critical resource might be compromised: prefer isolation of clearly identified network activity and user notification over destructive cleanup.

## Security review plan
Unit tests for schema and policy; adversarial prompt corpus; fuzz IPC decoders; fake root filesystem integration; privilege escalation review; broker process hardening; malicious peer simulation; chaos testing of disk full, power loss and killed agent.

## Risk register
| Risk | Severity | Primary mitigation |
|---|---|---|
| Agent deletes legitimate data | Critical | No generic destructive capability; snapshots; policy denial |
| False positive Thor containment | High | Independent evidence, reversible action, rapid undo |
| Prompt injection through logs | High | Strict data/command boundary and attack tests |
| Invalid driver patch bricks boot | Critical | VM-only initial tests, boot rollback and explicit approval |
| Leak via telemetry federation | High | Local-only default, redaction, privacy review |
| Endless repair restart loop | Medium | Rate limit, idempotency and circuit breaker |

## References
- Landlock overview: https://landlock.io/
- Kernel security modules: https://docs.kernel.org/admin-guide/LSM/index.html
- Kernel tool-generated content guidance: https://docs.kernel.org/process/generated-content.html
