# Unattended installed golden — research note (Activation Phase 1, slice C)

Question: how does the pinned Kubuntu 24.04.5 image become an
INSTALLED-system golden (not the live ISO), unattended, in the lab?

## Evidence from the pinned ISO itself (read 2026-11-12, purpleraider)

- Installer present in the live filesystem manifest
  (`/casper/filesystem.manifest` on the ISO): **Calamares 3.3.5**
  (`calamares 3.3.5-0ubuntu4`, `calamares-settings-kubuntu
  1:24.04.40`, `calamares-settings-ubuntu-common 1:24.04.40`).
  There is no Ubuntu autoinstall / subiquity path on this image and
  no `autoinstall.yaml` consumer; the GRUB menu offers only
  try/install, safe graphics, and an OEM entry
  (`oem-config/enable=true`).
- The live image ships **openssh-client only** and **no
  qemu-guest-agent** (manifest grep). The pinned lab package set
  (`lab/images/kubuntu-24.04.5-amd64/packages.txt`) already names
  exactly what the installed golden must add: `openssh-server`,
  `qemu-guest-agent`, `spice-vdagent`.
- Boot is casper: `/casper/vmlinuz`, `/casper/initrd`,
  `filesystem.squashfs`. Slice C boots those directly with
  `console=ttyS0` for serial guest access.

## The road for slice D (design, not yet proven)

Calamares supports unattended operation: a `settings.conf` whose
module sequence runs without user interaction (dontCancel /
disable-during-installation + pre-seeded `partition`, `mount`,
`users` (one lab user), `packages` (the pinned set above),
`bootloader` modules), launched in the live session over the
serial console slice C proved (`sudo -E calamares` with the lab
config placed under `/etc/calamares/` inside the live guest via a
small config ISO attached as a second CD-ROM — casper reads no
config from the boot ISO itself).

Steps: (1) attach empty 32 GiB qcow2 target + config CD; (2) serial
login, stage config, run Calamares unattended; (3) shut down,
detach the ISO, boot the installed disk; (4) verify serial login +
QGA ping + SSH all answer (the installed package set is why);
(5) that disk becomes `golden-installed.qcow2`; snapshot/reset
proof repeats slice B's cycle against it.

Risks / unknowns to retire in slice D: Calamares 3.3.5 Kubuntu
module names may differ from upstream docs (read them from the
live guest's `/usr/share/calamares` / `/etc/calamares` at runtime,
never assume); EFI boot variables in the lab OVMF_VARS copy must
survive the install (use a per-golden VARS copy); install time on
4 vCPU is unmeasured (budget 30 min, detached).

No claim is made that unattended install works yet — this note is
the research slice C owed; slice D is the proof.
