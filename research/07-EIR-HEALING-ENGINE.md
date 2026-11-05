# Eir: Diagnosis-to-Recovery Engineering
**Status:** proposed workflow; 2026-11-05.

## What Eir is
Eir is the repair-domain orchestrator. It does not possess permanent administrative privilege, and it cannot 'heal' arbitrary state by guessing. It accepts evidence-backed plans created by diagnosis agents, subjects them to deterministic policy, requests consent, invokes scoped execution through the broker, and measures outcome.

## Repair taxonomy
**Service health:** re-enable or restart a known unit only if it was legitimately expected to run. Do not countermand intentional user stops.

**Config mistakes:** compare with declared baseline or known package default, render exact diff, save original bytes and permissions, validate syntax with upstream tool, stage and verify.

**Dependencies:** identify missing package, version conflict, broken symlink or incompatible ABI; prefer package manager's dependency resolution and repository signatures. Never bypass package integrity just to make an install succeed.

**Disk and filesystems:** report capacity and corruption indicators; safe cleanup of owned temporary files can be separately authorized. Do not delete user files, rewrite partition table, run write-mode filesystem repair on mounted active filesystems, or assume a snapshot is a backup.

**Networking:** investigate routes, resolver, addresses and firewall changes. Network repair can disconnect a remotely administered host; require timed rollback or physical recovery.

**Kernel/driver:** propose a known-good boot entry, module parameter experiment or rollback; custom driver patch must pass VM/test-host gates and human approval.

## Candidate plan lifecycle
Eir receives a structured plan containing target, preconditions, goal, exact action, safety class, rollback and verification script. If the target changed since the plan, STOP. If the snapshot or recovery method fails, STOP. If consent expires, STOP. After execution, confirm the actual intended user-level function, not merely exit code zero.

## Example: safe user service recovery
- Observe a deliberately failed user-level unit 'lifthrasir-demo.service'.
- Confirm user expected it to be active, collect status and last errors.
- Reproduce failure in an isolated disposable test environment.
- If config syntax is wrong, propose one-line fix with expected diff and test.
- Save original config content and hash, require explicit approval.
- Apply exact previously reviewed bytes, reload user unit, start it.
- Verify process health and endpoint response, soak, close incident.
- If verification fails, restore original config and record failed attempt.

Never include an unconstrained 'run suggested command' step.

## Verification dimensions
**Functional:** does the workload work? **Regression:** did it break another dependent workload? **Integrity:** do executable/package hashes match expected provenance? **Persistence:** does repair survive restart? **Resources:** did performance, memory and I/O regress? **Human experience:** was consent respected and explanation intelligible?

## Repair knowledge
Store a successful *pattern*, not a blanket future permission. A known fix is conditional on software version, distro, hardware, configuration, and symptom. Changes in these invalidate autopromotion. A repair confirmed on one kernel build is not 'proven for Linux'.

## Distinguish Eir vs Thor
Eir's job is restoration after failure, not hostile process attribution. Thor may quarantine an identified malicious artifact under a reversible response policy, after which Eir repairs compromised configurations and validates clean operation.

## Suggested prototype
Create 10 synthetic incidents: missing user service config, corrupt key/value setting, disk-full simulator, killed worker, dependency not started, stale DNS config, broken symbolic link, package hold conflict (dry-run only), false threat alert, and sudden journal truncation. Grade Eir on abstention as rigorously as successful repair.

## References
- systemd service lifecycle: https://www.freedesktop.org/software/systemd/man/latest/systemd.service.html
- Transactional Linux updates: https://github.com/openSUSE/transactional-update
- OSTree rollback documentation: https://ostreedev.github.io/ostree/atomic-rollbacks/
