# Safe Repair, Transaction Semantics and Rollback
**Status:** architecture and experiment plan; 2026-11-05.

## Non-negotiable invariant
A successful model response does **not** imply a successful repair. Every host modification must be bounded, attributable, observable and, for eligible automated actions, reversible. The rollback engine is independent of the agent runtime.

## Five-stage state machine
**DETECTED → PROPOSED → AUTHORIZED → STAGED → VERIFIED** or **ROLLED_BACK / FAILED / MANUAL_RECOVERY**.
Record transitions durably with idempotency keys, exact resource identity, precondition hashes and timestamps. Prevent executing the same proposal twice after a crash.

### Risk and action classes
- **Read-only:** inspect service status, query counters, compare package integrity.
- **Low-impact reversible:** restart a specified noncritical service, revert a proven user-level config in a controlled test.
- **Medium:** stage a package reinstall or network config edit; requires direct approval, backup and connectivity fallback.
- **High:** change kernel, initramfs, bootloader, disk partitions, encryption, filesystem repair, driver firmware; require human-managed maintenance plan and verified offline recovery. Never autonomous in early versions.

## Two rollback strategies
**Filesystem snapshot or image:** Btrfs/ZFS/LVM-thin snapshots when available, plus application-aware data handling. A snapshot is not a substitute for a real backup; it may share failure domain with the damaged disk. Test snapshot restore before trusting it.

**Transactional OS deployment:** OSTree, transactional-update or distro-specific atomic update facilities stage a separate bootable deployment. The new deployment can be activated with health checks and reverted if startup fails. Not every traditional Linux installation has these capabilities; distro adapters must probe them.

For Kubuntu/ext4 early prototypes, begin with deliberately low-risk service changes in disposable VMs. Do not pretend generic 'rollback' can restore the entire OS if no whole-system snapshot or known-good image exists.

## Safe change protocol
1. Freeze target identity and config/package versions; reject if they change before execution.
2. Measure free disk space, battery/power and whether the user is on a remote session.
3. Evaluate whether rollback is feasible: data backup, snapshot, boot fallback, OOB console access.
4. Render a human-understandable proposed diff and exact consequences.
5. Require authorization appropriate to risk tier.
6. Apply via typed broker verb; never via agent-composed privileged shell.
7. Verify positive health, absence of regressions and user-visible task outcome.
8. Observe a soak interval; revert or escalate on failure.
9. Persist before/after manifest and audit trail.

## Watchdog and boot semantics
Use systemd Restart/WatchdogSec for supervised services where appropriate, but enforce start limits to avoid restart storms. A kernel panic or bootloader failure requires earlier-in-boot recovery independent of normal user-space agents. Research boot counting, fallback entries and measured boot; test actual power interruptions in disposable hardware.

## Chaos tests
- Kill Eir between snapshot and action.
- Pull network during package transaction.
- Exhaust disk while writing repair journal.
- Crash policy broker after authorization but before commit.
- Simulate wrong disk UUID and stale package hash.
- Force reboot after staging, before verification.
- Ensure a user can revert without AI access.

**Pass criteria:** no unauthorized host mutation, no silently lost transaction state, a documented manual recovery route, and bounded resource use.

## References
- OSTree atomic upgrades: https://ostreedev.github.io/ostree/atomic-upgrades/
- OSTree rollbacks: https://ostreedev.github.io/ostree/atomic-rollbacks/
- openSUSE transactional-update: https://github.com/openSUSE/transactional-update
- systemd watchdog: https://www.freedesktop.org/software/systemd/man/latest/systemd.service.html
