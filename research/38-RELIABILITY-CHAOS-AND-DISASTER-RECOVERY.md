# Reliability Engineering, Chaos Testing and Disaster Recovery
**Status:** operational research agenda; 2026-11-05.

## Reliability objective
A self-repair service must not become a single point of failure. When all agents stop, diagnostics and recovery must remain possible. When disk or boot chain is damaged, rescue paths should not depend on the compromised runtime.

## Critical subsystems
Immutable journal, privileged broker, policy decision service, rollback engine, local CLI, evidence store, agent scheduler and optional remote connection. Assign each a failure domain. Agent crashes are expected and should degrade functionality rather than corrupt state.

## Recovery tiers
**Tier 0:** local model process crashes; deterministic health monitoring remains.  
**Tier 1:** repair daemon crashes; journal replay is idempotent, no duplicate host action.  
**Tier 2:** root FS is not writable; document read-only rescue and avoid repeated writes.  
**Tier 3:** OS fails to boot; independently prepared bootloader image and physical recovery.  
**Tier 4:** storage device fails; require independent backup or spare system, snapshot alone insufficient.

## Chaos campaigns
Kill each service before and after every durable journal boundary; disconnect network; simulate full disk and partial writes; expire authorization during operation; flip VM clock; crash during snapshot retention; inject corrupted config and failed boot; restart after model cache deletion.

## SLO examples
- No loss of ability to disable auto-actions from CLI in supported rescue states.
- No unbounded restart storms.
- No duplicated repair after crash/reboot.
- Last-good recovery reachable in specified deployment classes.
- Normal host workloads protected from experimental resource spikes.

These are goals requiring tests, not measured guarantees.

## Data recovery
Define what evidence can be safely lost and what must survive. Recovery metadata should be small and write-optimized; keep periodic verified backups to a separate failure domain for important records. A self-healing agent must not erase user-selected backups to free space.

## Postmortem process
Every unintended write or failed rollback gets a root cause analysis, full timeline, affected version, missing control, corrective test and release gate. Avoid blaming an LLM abstractly; find the specific permission, parser, test or human decision failure.

## References
- OSTree rollback: https://ostreedev.github.io/ostree/atomic-rollbacks/
- systemd watchdog: https://www.freedesktop.org/software/systemd/man/latest/systemd.service.html
- Btrfs fundamentals: https://docs.kernel.org/filesystems/btrfs.html
