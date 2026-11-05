# Transactional Deployments, Immutable Systems and Boot Recovery
**Status:** comparative recovery research; 2026-11-05.

## Problem
A host patch that builds correctly can still break boot, initramfs, disk unlock, network configuration or graphical startup. User-space 'undo' tools cannot help if the OS never reaches the agent. Any eventual self-evolving Linux requires recovery below the ordinary agent runtime.

## Technology families
**Btrfs snapshot strategies:** cheap copy-on-write snapshots for compatible subvolume layouts. Limitations: not a separate disk backup, may not include boot/ESP or databases consistently; snapshot rollback mechanics vary by distro.

**LVM thin snapshots:** snapshot-capable storage layouts with pool space risks and administration complexity. Never assume a machine uses LVM.

**OSTree deployment:** atomically stages a new bootable filesystem and retains deployment history; rollback is via bootable deployments.

**openSUSE transactional-update:** integrates snapshots and distro update semantics; supported rollback must use native tooling and health policy.

**NixOS:** declarative configuration builds a new generation; old generations may be selectable at boot. It is not correct to rewrite random generated files as an autonomous 'repair'.

**A/B images / bootc:** build a separate candidate boot target, health-check and commit it after successful start. Details depend on boot stack and platform; inspect capabilities.

## Recovery guarantees
For any kernel or early-boot change, identify:
- Snapshot or independent known-good boot entry.
- Availability of older kernel/initramfs and all required driver modules.
- Whether disk unlock, Secure Boot, firmware and bootloader are compatible.
- Boot count/health timeout and fallback trigger.
- Console route if networking never initializes.
- Ability to restore user data if a filesystem operation goes wrong.

No boot fallback means NO auto-application of high-risk changes.

## Candidate deployment protocol
1. Create and verify known-good recovery state.
2. Build signed/hashed candidate artifact in lab.
3. Verify dependency and platform matrix.
4. Stage separate candidate deployment, do not replace live boot files ad hoc.
5. Prompt human with exact target and failure consequences.
6. Activate once; watchdog/boot health gate determines success.
7. Confirm critical services and intended workload before commit.
8. Keep previous deployment until deliberate cleanup, with retention safeguards.

## Special cases
Encrypted root, snapshots of swap files, TPM-bound boot secrets, out-of-tree modules, dual-boot and network-root environments complicate recovery. Treat these as separate explicit support profiles. A no-console remote host cannot be risked by a speculative kernel deployment.

## Tests
Simulate power loss before commit, torn journal write, invalid initramfs, missing network driver, failing graphics module, failing disk decrypt and watchdog timeout in disposable VMs. Verify fallback actually returns to the known-good state, not just that bootloader entries appear in configuration.

## References
- OSTree atomic upgrades: https://ostreedev.github.io/ostree/atomic-upgrades/
- OSTree rollbacks: https://ostreedev.github.io/ostree/atomic-rollbacks/
- openSUSE transactional-update: https://github.com/openSUSE/transactional-update
- NixOS manual: https://nixos.org/manual/nixos/stable/
