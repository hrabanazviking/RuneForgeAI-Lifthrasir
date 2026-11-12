# Sandbox and Capability Confinement Review by Distro (LIF-0407)

**Project:** Lifþrasir — The Self-Evolving Linux System
**Slice:** LIF-0407 (Phase P4) — review sandbox and capability
confinement effectiveness by distro.
**Status honesty:** This is a review: it produces findings plus
tests/fixtures, and it does not change host configuration — no
package is installed, no profile is loaded, no unit is edited, on
any distro. The machine-readable half is
`src/lifthrasir/confinement.py`; `tests/test_confinement_review.py`
fails if this document and that module disagree. On the evidence
ladder this is a documentary review with one host-observed row:
the ubuntu family row carries read-only observations from
purpleraider (Ubuntu 26.10, kernel 7.3.0-10-generic, LSM list
including landlock and apparmor, AppArmor enabled, Landlock ABI
11, cgroup v2 unified, systemd 261). The debian, fedora and
opensuse rows are **NOT verified**: they are documentary,
assembled from each family's stable public characteristics, and
no other distro was booted, installed or probed for this slice.
A review of confinement mechanisms is not proof of confinement
on any distro, tested or untested.
**Date:** 2026-11-12
**Sources:** `ROADMAP-TO-COMPLETION.md` §0 (invariants) and §5
(evidence rules); `docs/protocols/ACTION-CATALOG-v0.1.md` and
`src/lifthrasir/actions.py` (LIF-0401 — the protected lists are
v0.1 judgements, and that slice names this review as their audit);
`src/lifthrasir/executor.py` (LIF-0403 — the confinement being
rated); `research/11-AGENT-SANDBOXING.md` (the mechanism menu);
`research/13-DISTRO-INTEGRATION.md` (per-distro classes,
observation-only for unknown semantics).

## Verdict in one paragraph

The LIF-0403 executor's own layers — separate process, sandbox
path resolution with re-check, scrubbed environment, rlimits,
wall/output/file caps — are plain POSIX and therefore
**distro-portable**: they behave the same on all four families,
which is the design's real strength. But they are fixture-level
layers. None of the eight kernel/distro confinement mechanisms
below is used yet on any distro, so nothing here is broker-grade
isolation anywhere. Separately, the v0.1 catalog's protected lists
— sound in intent — are **distro-fragile in fact**, because all
three match exactly: unit names mostly survive the trip between
distros (with named exceptions), protected path prefixes have
real per-distro holes, and package names fail almost everywhere
— including the kernel package on the primary target itself.
Findings: **136** total — 19 critical-unit gaps, 47 protected-path gaps, 13 package-name mismatches, 19 unlisted trust packages, 32 unused-mechanism rows (8 mechanisms x 4 families), 3 cross-distro design limits, 3 scope exclusions. Per family, the fraction of the 11 tracked trust-package concepts whose real name the v0.1 list actually matches: ubuntu 3/11, debian 4/11, fedora 2/11, opensuse 3/11.

## Mechanism matrix (availability by distro; executor use today)

| Mechanism | Executor use | Ubuntu / Kubuntu | Debian | Fedora | openSUSE |
|---|---|---|---|---|---|
| systemd_hardening — systemd unit hardening directives | not-used | available | available | available | available |
| namespaces — mount/PID/net/user namespaces | not-used | conditional | available | available | available |
| seccomp — seccomp syscall filtering | not-used | available | available | available | available |
| landlock — Landlock filesystem sandboxing | not-used | available | available | available | available |
| capability_drop — Linux capability dropping / NoNewPrivileges | not-used | available | available | available | available |
| cgroup_v2 — cgroup v2 resource caps | not-used | default | default | default | default |
| lsm_mac — LSM mandatory access control (AppArmor/SELinux) | not-used | default | available | default | conditional |
| vm_isolation — disposable VM isolation (QEMU/KVM) | not-used | available | available | available | available |

Executor's own layers (all families, distro-portable): separate-process, sandbox-path-resolution, env-scrub, rlimits, wall-and-size-caps.

Reading notes. systemd is the default init on all four families,
so a hardened broker unit is the one native layer available
everywhere at once — it should be adopted first. Landlock is
available on every family's current kernel (host-observed ABI 11
on this host) and is LSM-independent, making it the natural
second layer. User namespaces are the one conditional row that
bites: Ubuntu mediates unprivileged user namespaces through
AppArmor policy, so a design that assumes userns is always open
will fail on exactly the first target family. openSUSE's LSM row
is conditional because both AppArmor and SELinux installs exist;
the adapter must probe, never assume (LIF-1101). SELinux on
Fedora is enforcing by default, but a broker gains from it only
with its own domain — an unconfined service under a targeted
policy is not confined in any useful sense.

## What the v0.1 lists get right (positive controls)

The audit is differential against the real lists, and it records
what holds: both SSH unit spellings are listed (`ssh.service`
for the apt families, `sshd.service` for the rpm families);
`/boot`, `/etc/ssh`, `/etc/shadow`, `/root`, `/home` and the
firmware directory are protected everywhere; `/etc/pki` covers
Fedora's TLS and RPM trust roots outright; `openssl` is the real
package name on all four families; and v0.1 `firmware-linux` /
`grub2` / `shim` are genuinely correct — on Debian and openSUSE
respectively. The findings below are the remainder, not the
whole picture.

## Findings

Severity is the review's judgement of the live-host consequence
if the corresponding verb validated against the unprotected
resource today. Every finding names its fix home: catalog v0.2
(per-distro lists owned by the LIF-1101/1102 adapters) or broker
work after P4. Nothing in this review edits the v0.1 lists;
changing them mid-phase would rewrite a banked contract other
slices validate against.

### Ubuntu / Kubuntu (first target family) — evidence: host-observed

- Host-observed on purpleraider (Ubuntu 26.10, kernel 7.3.0-10-generic): LSM list includes landlock and apparmor, AppArmor enabled, Landlock ABI 11 answered a version probe, cgroup v2 unified, systemd 261.
- User namespaces are conditional: Ubuntu mediates unprivileged user namespaces through AppArmor policy (the kernel.apparmor_restrict_unprivileged_userns sysctl exists on this host, value 0 here); a broker design must not assume userns is either always open or always closed.
- Versioned kernel packages (linux-image-7.3.0-10-generic and kin) mean even a corrected fixed name ages out every kernel update: package protection needs prefix/family matching, which is a v0.2 catalog design question.

| ID | Kind | Severity | Subject | Finding |
|---|---|---|---|---|
| CF-ubuntu-01 | critical-unit-gap | high | polkit.service | polkit.service is critical on Ubuntu / Kubuntu (first target family) (the privilege-escalation broker itself: whoever can restart or replace polkit controls authorization for the whole desktop) but is absent from the v0.1 CRITICAL_UNITS list, so restart_unit/stop_unit would validate against it on a live host. |
| CF-ubuntu-02 | critical-unit-gap | medium | systemd-resolved.service | systemd-resolved.service is critical on Ubuntu / Kubuntu (first target family) (name resolution for every lookup; a hostile resolver is a machine-wide redirect) but is absent from the v0.1 CRITICAL_UNITS list, so restart_unit/stop_unit would validate against it on a live host. |
| CF-ubuntu-03 | critical-unit-gap | high | snapd.service | snapd.service is critical on Ubuntu / Kubuntu (first target family) (snapd installs and removes software and holds its own trust chain; it is a package authority, not a user service) but is absent from the v0.1 CRITICAL_UNITS list, so restart_unit/stop_unit would validate against it on a live host. |
| CF-ubuntu-04 | critical-unit-gap | medium | ufw.service | ufw.service is critical on Ubuntu / Kubuntu (first target family) (the host firewall frontend where installed; section 0 names critical firewall state as never agent-mutated) but is absent from the v0.1 CRITICAL_UNITS list, so restart_unit/stop_unit would validate against it on a live host. |
| CF-ubuntu-05 | critical-unit-gap | medium | apparmor.service | apparmor.service is critical on Ubuntu / Kubuntu (first target family) (loads the MAC policy that confines everything else) but is absent from the v0.1 CRITICAL_UNITS list, so restart_unit/stop_unit would validate against it on a live host. |
| CF-ubuntu-06 | protected-path-gap | high | /etc/sudoers | /etc/sudoers on Ubuntu / Kubuntu (first target family): sudo policy is a trust root. It is not covered by the v0.1 PROTECTED_PATH_PREFIXES, so revert_user_config would validate against paths under it on a live host. |
| CF-ubuntu-07 | protected-path-gap | high | /etc/sudoers.d | /etc/sudoers.d on Ubuntu / Kubuntu (first target family): sudo policy drop-ins are a trust root. It is not covered by the v0.1 PROTECTED_PATH_PREFIXES, so revert_user_config would validate against paths under it on a live host. |
| CF-ubuntu-08 | protected-path-gap | high | /etc/polkit-1 | /etc/polkit-1 on Ubuntu / Kubuntu (first target family): polkit rules decide privileged actions. It is not covered by the v0.1 PROTECTED_PATH_PREFIXES, so revert_user_config would validate against paths under it on a live host. |
| CF-ubuntu-09 | protected-path-gap | high | /etc/systemd | /etc/systemd on Ubuntu / Kubuntu (first target family): unit and drop-in directory: a config revert that can write here can install a persistent privileged service. It is not covered by the v0.1 PROTECTED_PATH_PREFIXES, so revert_user_config would validate against paths under it on a live host. |
| CF-ubuntu-10 | protected-path-gap | medium | /etc/fstab | /etc/fstab on Ubuntu / Kubuntu (first target family): mount table; roadmap section 0 puts partition-adjacent state outside autonomous mutation. It is not covered by the v0.1 PROTECTED_PATH_PREFIXES, so revert_user_config would validate against paths under it on a live host. |
| CF-ubuntu-11 | protected-path-gap | high | /etc/crypttab | /etc/crypttab on Ubuntu / Kubuntu (first target family): encryption setup; section 0 invariant 2 names encryption. It is not covered by the v0.1 PROTECTED_PATH_PREFIXES, so revert_user_config would validate against paths under it on a live host. |
| CF-ubuntu-12 | protected-path-gap | medium | /etc/default/grub | /etc/default/grub on Ubuntu / Kubuntu (first target family): bootloader configuration on apt and rpm families alike; /boot alone does not cover it. It is not covered by the v0.1 PROTECTED_PATH_PREFIXES, so revert_user_config would validate against paths under it on a live host. |
| CF-ubuntu-13 | protected-path-gap | high | /etc/apparmor | /etc/apparmor on Ubuntu / Kubuntu (first target family): AppArmor policy is a trust root. It is not covered by the v0.1 PROTECTED_PATH_PREFIXES, so revert_user_config would validate against paths under it on a live host. |
| CF-ubuntu-14 | protected-path-gap | high | /etc/apparmor.d | /etc/apparmor.d on Ubuntu / Kubuntu (first target family): AppArmor profiles are a trust root. It is not covered by the v0.1 PROTECTED_PATH_PREFIXES, so revert_user_config would validate against paths under it on a live host. |
| CF-ubuntu-15 | protected-path-gap | high | /etc/apt | /etc/apt on Ubuntu / Kubuntu (first target family): apt sources and keyrings are the package trust root; the v0.1 list protects the TLS root (/etc/ssl) but not apt's. It is not covered by the v0.1 PROTECTED_PATH_PREFIXES, so revert_user_config would validate against paths under it on a live host. |
| CF-ubuntu-16 | protected-path-gap | medium | /etc/ca-certificates | /etc/ca-certificates on Ubuntu / Kubuntu (first target family): CA trust configuration. It is not covered by the v0.1 PROTECTED_PATH_PREFIXES, so revert_user_config would validate against paths under it on a live host. |
| CF-ubuntu-17 | protected-path-gap | medium | /usr/share/ca-certificates | /usr/share/ca-certificates on Ubuntu / Kubuntu (first target family): CA trust source store consumed by update-ca-certificates. It is not covered by the v0.1 PROTECTED_PATH_PREFIXES, so revert_user_config would validate against paths under it on a live host. |
| CF-ubuntu-18 | protected-path-gap | medium | /etc/grub.d | /etc/grub.d on Ubuntu / Kubuntu (first target family): grub script fragments (boot chain). It is not covered by the v0.1 PROTECTED_PATH_PREFIXES, so revert_user_config would validate against paths under it on a live host. |
| CF-ubuntu-19 | package-name-mismatch | high | linux-image-generic | On Ubuntu / Kubuntu (first target family) the kernel_image package is named 'linux-image-generic'. The v0.1 PROTECTED_PACKAGES list holds the near-name(s) ['linux-image'], but matching is EXACT (actions._check_target), so the protection does not fire for the package actually installed. |
| CF-ubuntu-20 | package-name-mismatch | high | grub-efi-amd64-signed | On Ubuntu / Kubuntu (first target family) the bootloader package is named 'grub-efi-amd64-signed'. The v0.1 PROTECTED_PACKAGES list holds the near-name(s) ['grub'], but matching is EXACT (actions._check_target), so the protection does not fire for the package actually installed. |
| CF-ubuntu-21 | package-name-mismatch | high | shim-signed | On Ubuntu / Kubuntu (first target family) the shim package is named 'shim-signed'. The v0.1 PROTECTED_PACKAGES list holds the near-name(s) ['shim'], but matching is EXACT (actions._check_target), so the protection does not fire for the package actually installed. |
| CF-ubuntu-22 | package-unlisted | high | linux-firmware | On Ubuntu / Kubuntu (first target family) the firmware package 'linux-firmware' has no entry at all in the v0.1 PROTECTED_PACKAGES list, so install_package / remove_package would validate against it. |
| CF-ubuntu-23 | package-unlisted | medium | systemd | On Ubuntu / Kubuntu (first target family) the init_system package 'systemd' has no entry at all in the v0.1 PROTECTED_PACKAGES list, so install_package / remove_package would validate against it. |
| CF-ubuntu-24 | package-unlisted | medium | polkitd | On Ubuntu / Kubuntu (first target family) the polkit_pkg package 'polkitd' has no entry at all in the v0.1 PROTECTED_PACKAGES list, so install_package / remove_package would validate against it. |
| CF-ubuntu-25 | package-unlisted | medium | sudo | On Ubuntu / Kubuntu (first target family) the sudo_pkg package 'sudo' has no entry at all in the v0.1 PROTECTED_PACKAGES list, so install_package / remove_package would validate against it. |
| CF-ubuntu-26 | package-unlisted | medium | apt | On Ubuntu / Kubuntu (first target family) the package_manager_pkg package 'apt' has no entry at all in the v0.1 PROTECTED_PACKAGES list, so install_package / remove_package would validate against it. |
| EF-ubuntu-01 | executor-layer-unused | medium | systemd_hardening | systemd unit hardening directives is available on Ubuntu / Kubuntu (first target family), but the LIF-0403 fixture executor does not use it: its confinement is process separation, sandbox path resolution, environment scrub and rlimits only. That is honest fixture-level confinement (its own docstring says so); it is not broker-grade isolation on any distro. |
| EF-ubuntu-02 | executor-layer-unused | medium | namespaces | mount/PID/net/user namespaces is conditional on Ubuntu / Kubuntu (first target family), but the LIF-0403 fixture executor does not use it: its confinement is process separation, sandbox path resolution, environment scrub and rlimits only. That is honest fixture-level confinement (its own docstring says so); it is not broker-grade isolation on any distro. |
| EF-ubuntu-03 | executor-layer-unused | medium | seccomp | seccomp syscall filtering is available on Ubuntu / Kubuntu (first target family), but the LIF-0403 fixture executor does not use it: its confinement is process separation, sandbox path resolution, environment scrub and rlimits only. That is honest fixture-level confinement (its own docstring says so); it is not broker-grade isolation on any distro. |
| EF-ubuntu-04 | executor-layer-unused | medium | landlock | Landlock filesystem sandboxing is available on Ubuntu / Kubuntu (first target family), but the LIF-0403 fixture executor does not use it: its confinement is process separation, sandbox path resolution, environment scrub and rlimits only. That is honest fixture-level confinement (its own docstring says so); it is not broker-grade isolation on any distro. |
| EF-ubuntu-05 | executor-layer-unused | medium | capability_drop | Linux capability dropping / NoNewPrivileges is available on Ubuntu / Kubuntu (first target family), but the LIF-0403 fixture executor does not use it: its confinement is process separation, sandbox path resolution, environment scrub and rlimits only. That is honest fixture-level confinement (its own docstring says so); it is not broker-grade isolation on any distro. |
| EF-ubuntu-06 | executor-layer-unused | medium | cgroup_v2 | cgroup v2 resource caps is default on Ubuntu / Kubuntu (first target family), but the LIF-0403 fixture executor does not use it: its confinement is process separation, sandbox path resolution, environment scrub and rlimits only. That is honest fixture-level confinement (its own docstring says so); it is not broker-grade isolation on any distro. |
| EF-ubuntu-07 | executor-layer-unused | medium | lsm_mac | LSM mandatory access control (AppArmor/SELinux) is default on Ubuntu / Kubuntu (first target family), but the LIF-0403 fixture executor does not use it: its confinement is process separation, sandbox path resolution, environment scrub and rlimits only. That is honest fixture-level confinement (its own docstring says so); it is not broker-grade isolation on any distro. |
| EF-ubuntu-08 | executor-layer-unused | medium | vm_isolation | disposable VM isolation (QEMU/KVM) is available on Ubuntu / Kubuntu (first target family), but the LIF-0403 fixture executor does not use it: its confinement is process separation, sandbox path resolution, environment scrub and rlimits only. That is honest fixture-level confinement (its own docstring says so); it is not broker-grade isolation on any distro. |

### Debian — evidence: documented

- AppArmor ships and is enabled by default, but with a smaller enforcing profile set than Ubuntu: LSM status is available, not the blanket default Ubuntu users assume.
- Debian is the one family where v0.1 'firmware-linux' is the real name -- the exception that proves the exact-match problem everywhere else.
- Non-systemd installs exist in the wild; the adapter must probe the init system (LIF-1101), not assume it.

| ID | Kind | Severity | Subject | Finding |
|---|---|---|---|---|
| CF-debian-01 | critical-unit-gap | high | polkit.service | polkit.service is critical on Debian (the privilege-escalation broker itself: whoever can restart or replace polkit controls authorization for the whole desktop) but is absent from the v0.1 CRITICAL_UNITS list, so restart_unit/stop_unit would validate against it on a live host. |
| CF-debian-02 | critical-unit-gap | medium | systemd-resolved.service | systemd-resolved.service is critical on Debian (name resolution for every lookup; a hostile resolver is a machine-wide redirect) but is absent from the v0.1 CRITICAL_UNITS list, so restart_unit/stop_unit would validate against it on a live host. |
| CF-debian-03 | critical-unit-gap | medium | apparmor.service | apparmor.service is critical on Debian (loads the MAC policy that confines everything else) but is absent from the v0.1 CRITICAL_UNITS list, so restart_unit/stop_unit would validate against it on a live host. |
| CF-debian-04 | protected-path-gap | high | /etc/sudoers | /etc/sudoers on Debian: sudo policy is a trust root. It is not covered by the v0.1 PROTECTED_PATH_PREFIXES, so revert_user_config would validate against paths under it on a live host. |
| CF-debian-05 | protected-path-gap | high | /etc/sudoers.d | /etc/sudoers.d on Debian: sudo policy drop-ins are a trust root. It is not covered by the v0.1 PROTECTED_PATH_PREFIXES, so revert_user_config would validate against paths under it on a live host. |
| CF-debian-06 | protected-path-gap | high | /etc/polkit-1 | /etc/polkit-1 on Debian: polkit rules decide privileged actions. It is not covered by the v0.1 PROTECTED_PATH_PREFIXES, so revert_user_config would validate against paths under it on a live host. |
| CF-debian-07 | protected-path-gap | high | /etc/systemd | /etc/systemd on Debian: unit and drop-in directory: a config revert that can write here can install a persistent privileged service. It is not covered by the v0.1 PROTECTED_PATH_PREFIXES, so revert_user_config would validate against paths under it on a live host. |
| CF-debian-08 | protected-path-gap | medium | /etc/fstab | /etc/fstab on Debian: mount table; roadmap section 0 puts partition-adjacent state outside autonomous mutation. It is not covered by the v0.1 PROTECTED_PATH_PREFIXES, so revert_user_config would validate against paths under it on a live host. |
| CF-debian-09 | protected-path-gap | high | /etc/crypttab | /etc/crypttab on Debian: encryption setup; section 0 invariant 2 names encryption. It is not covered by the v0.1 PROTECTED_PATH_PREFIXES, so revert_user_config would validate against paths under it on a live host. |
| CF-debian-10 | protected-path-gap | medium | /etc/default/grub | /etc/default/grub on Debian: bootloader configuration on apt and rpm families alike; /boot alone does not cover it. It is not covered by the v0.1 PROTECTED_PATH_PREFIXES, so revert_user_config would validate against paths under it on a live host. |
| CF-debian-11 | protected-path-gap | high | /etc/apparmor | /etc/apparmor on Debian: AppArmor policy is a trust root. It is not covered by the v0.1 PROTECTED_PATH_PREFIXES, so revert_user_config would validate against paths under it on a live host. |
| CF-debian-12 | protected-path-gap | high | /etc/apparmor.d | /etc/apparmor.d on Debian: AppArmor profiles are a trust root. It is not covered by the v0.1 PROTECTED_PATH_PREFIXES, so revert_user_config would validate against paths under it on a live host. |
| CF-debian-13 | protected-path-gap | high | /etc/apt | /etc/apt on Debian: apt sources and keyrings are the package trust root. It is not covered by the v0.1 PROTECTED_PATH_PREFIXES, so revert_user_config would validate against paths under it on a live host. |
| CF-debian-14 | protected-path-gap | medium | /etc/ca-certificates | /etc/ca-certificates on Debian: CA trust configuration. It is not covered by the v0.1 PROTECTED_PATH_PREFIXES, so revert_user_config would validate against paths under it on a live host. |
| CF-debian-15 | protected-path-gap | medium | /usr/share/ca-certificates | /usr/share/ca-certificates on Debian: CA trust source store. It is not covered by the v0.1 PROTECTED_PATH_PREFIXES, so revert_user_config would validate against paths under it on a live host. |
| CF-debian-16 | protected-path-gap | medium | /etc/grub.d | /etc/grub.d on Debian: grub script fragments (boot chain). It is not covered by the v0.1 PROTECTED_PATH_PREFIXES, so revert_user_config would validate against paths under it on a live host. |
| CF-debian-17 | package-name-mismatch | high | linux-image-amd64 | On Debian the kernel_image package is named 'linux-image-amd64'. The v0.1 PROTECTED_PACKAGES list holds the near-name(s) ['linux-image'], but matching is EXACT (actions._check_target), so the protection does not fire for the package actually installed. |
| CF-debian-18 | package-name-mismatch | high | grub-efi-amd64 | On Debian the bootloader package is named 'grub-efi-amd64'. The v0.1 PROTECTED_PACKAGES list holds the near-name(s) ['grub'], but matching is EXACT (actions._check_target), so the protection does not fire for the package actually installed. |
| CF-debian-19 | package-name-mismatch | high | shim-signed | On Debian the shim package is named 'shim-signed'. The v0.1 PROTECTED_PACKAGES list holds the near-name(s) ['shim'], but matching is EXACT (actions._check_target), so the protection does not fire for the package actually installed. |
| CF-debian-20 | package-unlisted | medium | systemd | On Debian the init_system package 'systemd' has no entry at all in the v0.1 PROTECTED_PACKAGES list, so install_package / remove_package would validate against it. |
| CF-debian-21 | package-unlisted | medium | polkitd | On Debian the polkit_pkg package 'polkitd' has no entry at all in the v0.1 PROTECTED_PACKAGES list, so install_package / remove_package would validate against it. |
| CF-debian-22 | package-unlisted | medium | sudo | On Debian the sudo_pkg package 'sudo' has no entry at all in the v0.1 PROTECTED_PACKAGES list, so install_package / remove_package would validate against it. |
| CF-debian-23 | package-unlisted | medium | apt | On Debian the package_manager_pkg package 'apt' has no entry at all in the v0.1 PROTECTED_PACKAGES list, so install_package / remove_package would validate against it. |
| EF-debian-01 | executor-layer-unused | medium | systemd_hardening | systemd unit hardening directives is available on Debian, but the LIF-0403 fixture executor does not use it: its confinement is process separation, sandbox path resolution, environment scrub and rlimits only. That is honest fixture-level confinement (its own docstring says so); it is not broker-grade isolation on any distro. |
| EF-debian-02 | executor-layer-unused | medium | namespaces | mount/PID/net/user namespaces is available on Debian, but the LIF-0403 fixture executor does not use it: its confinement is process separation, sandbox path resolution, environment scrub and rlimits only. That is honest fixture-level confinement (its own docstring says so); it is not broker-grade isolation on any distro. |
| EF-debian-03 | executor-layer-unused | medium | seccomp | seccomp syscall filtering is available on Debian, but the LIF-0403 fixture executor does not use it: its confinement is process separation, sandbox path resolution, environment scrub and rlimits only. That is honest fixture-level confinement (its own docstring says so); it is not broker-grade isolation on any distro. |
| EF-debian-04 | executor-layer-unused | medium | landlock | Landlock filesystem sandboxing is available on Debian, but the LIF-0403 fixture executor does not use it: its confinement is process separation, sandbox path resolution, environment scrub and rlimits only. That is honest fixture-level confinement (its own docstring says so); it is not broker-grade isolation on any distro. |
| EF-debian-05 | executor-layer-unused | medium | capability_drop | Linux capability dropping / NoNewPrivileges is available on Debian, but the LIF-0403 fixture executor does not use it: its confinement is process separation, sandbox path resolution, environment scrub and rlimits only. That is honest fixture-level confinement (its own docstring says so); it is not broker-grade isolation on any distro. |
| EF-debian-06 | executor-layer-unused | medium | cgroup_v2 | cgroup v2 resource caps is default on Debian, but the LIF-0403 fixture executor does not use it: its confinement is process separation, sandbox path resolution, environment scrub and rlimits only. That is honest fixture-level confinement (its own docstring says so); it is not broker-grade isolation on any distro. |
| EF-debian-07 | executor-layer-unused | medium | lsm_mac | LSM mandatory access control (AppArmor/SELinux) is available on Debian, but the LIF-0403 fixture executor does not use it: its confinement is process separation, sandbox path resolution, environment scrub and rlimits only. That is honest fixture-level confinement (its own docstring says so); it is not broker-grade isolation on any distro. |
| EF-debian-08 | executor-layer-unused | medium | vm_isolation | disposable VM isolation (QEMU/KVM) is available on Debian, but the LIF-0403 fixture executor does not use it: its confinement is process separation, sandbox path resolution, environment scrub and rlimits only. That is honest fixture-level confinement (its own docstring says so); it is not broker-grade isolation on any distro. |

### Fedora — evidence: documented

- SELinux is enforcing by default -- the strongest default MAC of the four families -- but a broker needs its own SELinux domain; running unconfined under a targeted policy gains little, so lsm_mac 'default' is an opportunity, not a property Lifthrasir inherits for free.
- v0.1 'kernel' does match Fedora's kernel metapackage -- the only kernel_image concept any family matches -- while the actually-installed kernel-core stays unlisted.
- /etc/pki IS in the v0.1 protected prefixes, so Fedora's TLS/RPM trust roots are the best-covered of any family.

| ID | Kind | Severity | Subject | Finding |
|---|---|---|---|---|
| CF-fedora-01 | critical-unit-gap | high | polkit.service | polkit.service is critical on Fedora (the privilege-escalation broker itself: whoever can restart or replace polkit controls authorization for the whole desktop) but is absent from the v0.1 CRITICAL_UNITS list, so restart_unit/stop_unit would validate against it on a live host. |
| CF-fedora-02 | critical-unit-gap | medium | systemd-resolved.service | systemd-resolved.service is critical on Fedora (name resolution for every lookup; a hostile resolver is a machine-wide redirect) but is absent from the v0.1 CRITICAL_UNITS list, so restart_unit/stop_unit would validate against it on a live host. |
| CF-fedora-03 | critical-unit-gap | high | dbus-broker.service | dbus-broker.service is critical on Fedora (Fedora's D-Bus broker runs under this unit name; the v0.1 list names only dbus.service, so on Fedora the message bus is NOT protected by the critical-unit list) but is absent from the v0.1 CRITICAL_UNITS list, so restart_unit/stop_unit would validate against it on a live host. |
| CF-fedora-04 | critical-unit-gap | high | firewalld.service | firewalld.service is critical on Fedora (the default firewall daemon; section 0 names critical firewall state as never agent-mutated) but is absent from the v0.1 CRITICAL_UNITS list, so restart_unit/stop_unit would validate against it on a live host. |
| CF-fedora-05 | critical-unit-gap | medium | auditd.service | auditd.service is critical on Fedora (the audit log is the record section 0 invariant 3 requires; stopping it blinds every other control) but is absent from the v0.1 CRITICAL_UNITS list, so restart_unit/stop_unit would validate against it on a live host. |
| CF-fedora-06 | protected-path-gap | high | /etc/sudoers | /etc/sudoers on Fedora: sudo policy is a trust root. It is not covered by the v0.1 PROTECTED_PATH_PREFIXES, so revert_user_config would validate against paths under it on a live host. |
| CF-fedora-07 | protected-path-gap | high | /etc/sudoers.d | /etc/sudoers.d on Fedora: sudo policy drop-ins are a trust root. It is not covered by the v0.1 PROTECTED_PATH_PREFIXES, so revert_user_config would validate against paths under it on a live host. |
| CF-fedora-08 | protected-path-gap | high | /etc/polkit-1 | /etc/polkit-1 on Fedora: polkit rules decide privileged actions. It is not covered by the v0.1 PROTECTED_PATH_PREFIXES, so revert_user_config would validate against paths under it on a live host. |
| CF-fedora-09 | protected-path-gap | high | /etc/systemd | /etc/systemd on Fedora: unit and drop-in directory: a config revert that can write here can install a persistent privileged service. It is not covered by the v0.1 PROTECTED_PATH_PREFIXES, so revert_user_config would validate against paths under it on a live host. |
| CF-fedora-10 | protected-path-gap | medium | /etc/fstab | /etc/fstab on Fedora: mount table; roadmap section 0 puts partition-adjacent state outside autonomous mutation. It is not covered by the v0.1 PROTECTED_PATH_PREFIXES, so revert_user_config would validate against paths under it on a live host. |
| CF-fedora-11 | protected-path-gap | high | /etc/crypttab | /etc/crypttab on Fedora: encryption setup; section 0 invariant 2 names encryption. It is not covered by the v0.1 PROTECTED_PATH_PREFIXES, so revert_user_config would validate against paths under it on a live host. |
| CF-fedora-12 | protected-path-gap | medium | /etc/default/grub | /etc/default/grub on Fedora: bootloader configuration on apt and rpm families alike; /boot alone does not cover it. It is not covered by the v0.1 PROTECTED_PATH_PREFIXES, so revert_user_config would validate against paths under it on a live host. |
| CF-fedora-13 | protected-path-gap | high | /etc/selinux | /etc/selinux on Fedora: SELinux policy is a trust root. It is not covered by the v0.1 PROTECTED_PATH_PREFIXES, so revert_user_config would validate against paths under it on a live host. |
| CF-fedora-14 | protected-path-gap | medium | /etc/dnf | /etc/dnf on Fedora: dnf configuration and repo handling. It is not covered by the v0.1 PROTECTED_PATH_PREFIXES, so revert_user_config would validate against paths under it on a live host. |
| CF-fedora-15 | protected-path-gap | medium | /etc/yum.repos.d | /etc/yum.repos.d on Fedora: repository definitions feed the package trust root. It is not covered by the v0.1 PROTECTED_PATH_PREFIXES, so revert_user_config would validate against paths under it on a live host. |
| CF-fedora-16 | package-name-mismatch | high | kernel-core | On Fedora the kernel_image package is named 'kernel-core'. The v0.1 PROTECTED_PACKAGES list holds the near-name(s) ['kernel'], but matching is EXACT (actions._check_target), so the protection does not fire for the package actually installed. |
| CF-fedora-17 | package-name-mismatch | high | grub2-efi-x64 | On Fedora the bootloader package is named 'grub2-efi-x64'. The v0.1 PROTECTED_PACKAGES list holds the near-name(s) ['grub', 'grub2'], but matching is EXACT (actions._check_target), so the protection does not fire for the package actually installed. |
| CF-fedora-18 | package-name-mismatch | high | shim-x64 | On Fedora the shim package is named 'shim-x64'. The v0.1 PROTECTED_PACKAGES list holds the near-name(s) ['shim'], but matching is EXACT (actions._check_target), so the protection does not fire for the package actually installed. |
| CF-fedora-19 | package-unlisted | high | linux-firmware | On Fedora the firmware package 'linux-firmware' has no entry at all in the v0.1 PROTECTED_PACKAGES list, so install_package / remove_package would validate against it. |
| CF-fedora-20 | package-name-mismatch | medium | gnupg2 | On Fedora the gnupg package is named 'gnupg2'. The v0.1 PROTECTED_PACKAGES list holds the near-name(s) ['gnupg'], but matching is EXACT (actions._check_target), so the protection does not fire for the package actually installed. |
| CF-fedora-21 | package-unlisted | medium | systemd | On Fedora the init_system package 'systemd' has no entry at all in the v0.1 PROTECTED_PACKAGES list, so install_package / remove_package would validate against it. |
| CF-fedora-22 | package-unlisted | medium | polkit | On Fedora the polkit_pkg package 'polkit' has no entry at all in the v0.1 PROTECTED_PACKAGES list, so install_package / remove_package would validate against it. |
| CF-fedora-23 | package-unlisted | medium | sudo | On Fedora the sudo_pkg package 'sudo' has no entry at all in the v0.1 PROTECTED_PACKAGES list, so install_package / remove_package would validate against it. |
| CF-fedora-24 | package-unlisted | medium | dnf | On Fedora the package_manager_pkg package 'dnf' has no entry at all in the v0.1 PROTECTED_PACKAGES list, so install_package / remove_package would validate against it. |
| EF-fedora-01 | executor-layer-unused | medium | systemd_hardening | systemd unit hardening directives is available on Fedora, but the LIF-0403 fixture executor does not use it: its confinement is process separation, sandbox path resolution, environment scrub and rlimits only. That is honest fixture-level confinement (its own docstring says so); it is not broker-grade isolation on any distro. |
| EF-fedora-02 | executor-layer-unused | medium | namespaces | mount/PID/net/user namespaces is available on Fedora, but the LIF-0403 fixture executor does not use it: its confinement is process separation, sandbox path resolution, environment scrub and rlimits only. That is honest fixture-level confinement (its own docstring says so); it is not broker-grade isolation on any distro. |
| EF-fedora-03 | executor-layer-unused | medium | seccomp | seccomp syscall filtering is available on Fedora, but the LIF-0403 fixture executor does not use it: its confinement is process separation, sandbox path resolution, environment scrub and rlimits only. That is honest fixture-level confinement (its own docstring says so); it is not broker-grade isolation on any distro. |
| EF-fedora-04 | executor-layer-unused | medium | landlock | Landlock filesystem sandboxing is available on Fedora, but the LIF-0403 fixture executor does not use it: its confinement is process separation, sandbox path resolution, environment scrub and rlimits only. That is honest fixture-level confinement (its own docstring says so); it is not broker-grade isolation on any distro. |
| EF-fedora-05 | executor-layer-unused | medium | capability_drop | Linux capability dropping / NoNewPrivileges is available on Fedora, but the LIF-0403 fixture executor does not use it: its confinement is process separation, sandbox path resolution, environment scrub and rlimits only. That is honest fixture-level confinement (its own docstring says so); it is not broker-grade isolation on any distro. |
| EF-fedora-06 | executor-layer-unused | medium | cgroup_v2 | cgroup v2 resource caps is default on Fedora, but the LIF-0403 fixture executor does not use it: its confinement is process separation, sandbox path resolution, environment scrub and rlimits only. That is honest fixture-level confinement (its own docstring says so); it is not broker-grade isolation on any distro. |
| EF-fedora-07 | executor-layer-unused | medium | lsm_mac | LSM mandatory access control (AppArmor/SELinux) is default on Fedora, but the LIF-0403 fixture executor does not use it: its confinement is process separation, sandbox path resolution, environment scrub and rlimits only. That is honest fixture-level confinement (its own docstring says so); it is not broker-grade isolation on any distro. |
| EF-fedora-08 | executor-layer-unused | medium | vm_isolation | disposable VM isolation (QEMU/KVM) is available on Fedora, but the LIF-0403 fixture executor does not use it: its confinement is process separation, sandbox path resolution, environment scrub and rlimits only. That is honest fixture-level confinement (its own docstring says so); it is not broker-grade isolation on any distro. |

### openSUSE (Leap / Tumbleweed) — evidence: documented

- The LSM is genuinely conditional: AppArmor is the traditional default and SELinux is offered on current releases, so neither the mechanism matrix nor the path list may hard-code one -- the adapter probes (LIF-1101).
- openSUSE is the only family where v0.1 'shim' and 'grub2' are real package names.
- Transactional variants (MicroOS) are OUT of this review's scope: live verbs abstain there (research/13).

| ID | Kind | Severity | Subject | Finding |
|---|---|---|---|---|
| CF-opensuse-01 | critical-unit-gap | high | polkit.service | polkit.service is critical on openSUSE (Leap / Tumbleweed) (the privilege-escalation broker itself: whoever can restart or replace polkit controls authorization for the whole desktop) but is absent from the v0.1 CRITICAL_UNITS list, so restart_unit/stop_unit would validate against it on a live host. |
| CF-opensuse-02 | critical-unit-gap | medium | systemd-resolved.service | systemd-resolved.service is critical on openSUSE (Leap / Tumbleweed) (name resolution for every lookup; a hostile resolver is a machine-wide redirect) but is absent from the v0.1 CRITICAL_UNITS list, so restart_unit/stop_unit would validate against it on a live host. |
| CF-opensuse-03 | critical-unit-gap | medium | wicked.service | wicked.service is critical on openSUSE (Leap / Tumbleweed) (the traditional openSUSE network stack: a host may run wicked instead of the NetworkManager the v0.1 list names) but is absent from the v0.1 CRITICAL_UNITS list, so restart_unit/stop_unit would validate against it on a live host. |
| CF-opensuse-04 | critical-unit-gap | high | firewalld.service | firewalld.service is critical on openSUSE (Leap / Tumbleweed) (the default firewall daemon; critical firewall state is never agent-mutated (section 0)) but is absent from the v0.1 CRITICAL_UNITS list, so restart_unit/stop_unit would validate against it on a live host. |
| CF-opensuse-05 | critical-unit-gap | medium | auditd.service | auditd.service is critical on openSUSE (Leap / Tumbleweed) (the audit log is the record invariant 3 requires) but is absent from the v0.1 CRITICAL_UNITS list, so restart_unit/stop_unit would validate against it on a live host. |
| CF-opensuse-06 | critical-unit-gap | medium | apparmor.service | apparmor.service is critical on openSUSE (Leap / Tumbleweed) (loads MAC policy on AppArmor-configured installs) but is absent from the v0.1 CRITICAL_UNITS list, so restart_unit/stop_unit would validate against it on a live host. |
| CF-opensuse-07 | protected-path-gap | high | /etc/sudoers | /etc/sudoers on openSUSE (Leap / Tumbleweed): sudo policy is a trust root. It is not covered by the v0.1 PROTECTED_PATH_PREFIXES, so revert_user_config would validate against paths under it on a live host. |
| CF-opensuse-08 | protected-path-gap | high | /etc/sudoers.d | /etc/sudoers.d on openSUSE (Leap / Tumbleweed): sudo policy drop-ins are a trust root. It is not covered by the v0.1 PROTECTED_PATH_PREFIXES, so revert_user_config would validate against paths under it on a live host. |
| CF-opensuse-09 | protected-path-gap | high | /etc/polkit-1 | /etc/polkit-1 on openSUSE (Leap / Tumbleweed): polkit rules decide privileged actions. It is not covered by the v0.1 PROTECTED_PATH_PREFIXES, so revert_user_config would validate against paths under it on a live host. |
| CF-opensuse-10 | protected-path-gap | high | /etc/systemd | /etc/systemd on openSUSE (Leap / Tumbleweed): unit and drop-in directory: a config revert that can write here can install a persistent privileged service. It is not covered by the v0.1 PROTECTED_PATH_PREFIXES, so revert_user_config would validate against paths under it on a live host. |
| CF-opensuse-11 | protected-path-gap | medium | /etc/fstab | /etc/fstab on openSUSE (Leap / Tumbleweed): mount table; roadmap section 0 puts partition-adjacent state outside autonomous mutation. It is not covered by the v0.1 PROTECTED_PATH_PREFIXES, so revert_user_config would validate against paths under it on a live host. |
| CF-opensuse-12 | protected-path-gap | high | /etc/crypttab | /etc/crypttab on openSUSE (Leap / Tumbleweed): encryption setup; section 0 invariant 2 names encryption. It is not covered by the v0.1 PROTECTED_PATH_PREFIXES, so revert_user_config would validate against paths under it on a live host. |
| CF-opensuse-13 | protected-path-gap | medium | /etc/default/grub | /etc/default/grub on openSUSE (Leap / Tumbleweed): bootloader configuration on apt and rpm families alike; /boot alone does not cover it. It is not covered by the v0.1 PROTECTED_PATH_PREFIXES, so revert_user_config would validate against paths under it on a live host. |
| CF-opensuse-14 | protected-path-gap | high | /etc/apparmor | /etc/apparmor on openSUSE (Leap / Tumbleweed): AppArmor policy on AppArmor-configured installs. It is not covered by the v0.1 PROTECTED_PATH_PREFIXES, so revert_user_config would validate against paths under it on a live host. |
| CF-opensuse-15 | protected-path-gap | high | /etc/apparmor.d | /etc/apparmor.d on openSUSE (Leap / Tumbleweed): AppArmor profiles. It is not covered by the v0.1 PROTECTED_PATH_PREFIXES, so revert_user_config would validate against paths under it on a live host. |
| CF-opensuse-16 | protected-path-gap | high | /etc/selinux | /etc/selinux on openSUSE (Leap / Tumbleweed): SELinux policy on SELinux-configured installs. It is not covered by the v0.1 PROTECTED_PATH_PREFIXES, so revert_user_config would validate against paths under it on a live host. |
| CF-opensuse-17 | protected-path-gap | medium | /etc/zypp | /etc/zypp on openSUSE (Leap / Tumbleweed): zypper configuration and repository handling. It is not covered by the v0.1 PROTECTED_PATH_PREFIXES, so revert_user_config would validate against paths under it on a live host. |
| CF-opensuse-18 | package-name-mismatch | high | kernel-default | On openSUSE (Leap / Tumbleweed) the kernel_image package is named 'kernel-default'. The v0.1 PROTECTED_PACKAGES list holds the near-name(s) ['kernel'], but matching is EXACT (actions._check_target), so the protection does not fire for the package actually installed. |
| CF-opensuse-19 | package-name-mismatch | high | kernel-firmware | On openSUSE (Leap / Tumbleweed) the firmware package is named 'kernel-firmware'. The v0.1 PROTECTED_PACKAGES list holds the near-name(s) ['kernel'], but matching is EXACT (actions._check_target), so the protection does not fire for the package actually installed. |
| CF-opensuse-20 | package-unlisted | medium | gpg2 | On openSUSE (Leap / Tumbleweed) the gnupg package 'gpg2' has no entry at all in the v0.1 PROTECTED_PACKAGES list, so install_package / remove_package would validate against it. |
| CF-opensuse-21 | package-name-mismatch | medium | openssh | On openSUSE (Leap / Tumbleweed) the ssh_server package is named 'openssh'. The v0.1 PROTECTED_PACKAGES list holds the near-name(s) ['openssh-server'], but matching is EXACT (actions._check_target), so the protection does not fire for the package actually installed. |
| CF-opensuse-22 | package-unlisted | medium | systemd | On openSUSE (Leap / Tumbleweed) the init_system package 'systemd' has no entry at all in the v0.1 PROTECTED_PACKAGES list, so install_package / remove_package would validate against it. |
| CF-opensuse-23 | package-unlisted | medium | polkit | On openSUSE (Leap / Tumbleweed) the polkit_pkg package 'polkit' has no entry at all in the v0.1 PROTECTED_PACKAGES list, so install_package / remove_package would validate against it. |
| CF-opensuse-24 | package-unlisted | medium | sudo | On openSUSE (Leap / Tumbleweed) the sudo_pkg package 'sudo' has no entry at all in the v0.1 PROTECTED_PACKAGES list, so install_package / remove_package would validate against it. |
| CF-opensuse-25 | package-unlisted | medium | zypper | On openSUSE (Leap / Tumbleweed) the package_manager_pkg package 'zypper' has no entry at all in the v0.1 PROTECTED_PACKAGES list, so install_package / remove_package would validate against it. |
| EF-opensuse-01 | executor-layer-unused | medium | systemd_hardening | systemd unit hardening directives is available on openSUSE (Leap / Tumbleweed), but the LIF-0403 fixture executor does not use it: its confinement is process separation, sandbox path resolution, environment scrub and rlimits only. That is honest fixture-level confinement (its own docstring says so); it is not broker-grade isolation on any distro. |
| EF-opensuse-02 | executor-layer-unused | medium | namespaces | mount/PID/net/user namespaces is available on openSUSE (Leap / Tumbleweed), but the LIF-0403 fixture executor does not use it: its confinement is process separation, sandbox path resolution, environment scrub and rlimits only. That is honest fixture-level confinement (its own docstring says so); it is not broker-grade isolation on any distro. |
| EF-opensuse-03 | executor-layer-unused | medium | seccomp | seccomp syscall filtering is available on openSUSE (Leap / Tumbleweed), but the LIF-0403 fixture executor does not use it: its confinement is process separation, sandbox path resolution, environment scrub and rlimits only. That is honest fixture-level confinement (its own docstring says so); it is not broker-grade isolation on any distro. |
| EF-opensuse-04 | executor-layer-unused | medium | landlock | Landlock filesystem sandboxing is available on openSUSE (Leap / Tumbleweed), but the LIF-0403 fixture executor does not use it: its confinement is process separation, sandbox path resolution, environment scrub and rlimits only. That is honest fixture-level confinement (its own docstring says so); it is not broker-grade isolation on any distro. |
| EF-opensuse-05 | executor-layer-unused | medium | capability_drop | Linux capability dropping / NoNewPrivileges is available on openSUSE (Leap / Tumbleweed), but the LIF-0403 fixture executor does not use it: its confinement is process separation, sandbox path resolution, environment scrub and rlimits only. That is honest fixture-level confinement (its own docstring says so); it is not broker-grade isolation on any distro. |
| EF-opensuse-06 | executor-layer-unused | medium | cgroup_v2 | cgroup v2 resource caps is default on openSUSE (Leap / Tumbleweed), but the LIF-0403 fixture executor does not use it: its confinement is process separation, sandbox path resolution, environment scrub and rlimits only. That is honest fixture-level confinement (its own docstring says so); it is not broker-grade isolation on any distro. |
| EF-opensuse-07 | executor-layer-unused | medium | lsm_mac | LSM mandatory access control (AppArmor/SELinux) is conditional on openSUSE (Leap / Tumbleweed), but the LIF-0403 fixture executor does not use it: its confinement is process separation, sandbox path resolution, environment scrub and rlimits only. That is honest fixture-level confinement (its own docstring says so); it is not broker-grade isolation on any distro. |
| EF-opensuse-08 | executor-layer-unused | medium | vm_isolation | disposable VM isolation (QEMU/KVM) is available on openSUSE (Leap / Tumbleweed), but the LIF-0403 fixture executor does not use it: its confinement is process separation, sandbox path resolution, environment scrub and rlimits only. That is honest fixture-level confinement (its own docstring says so); it is not broker-grade isolation on any distro. |


## Cross-distro design limits (rated once, apply everywhere)

| ID | Severity | Subject | Finding |
|---|---|---|---|
| DL-all-01 | medium | no-uid-drop | The executor child runs at the caller's uid on every distro; LIF-0403 names this honestly. A dedicated broker uid (systemd DynamicUser/User) is available everywhere and unused. |
| DL-all-02 | medium | no-memory-or-pid-cap | Memory and process-count are bounded only indirectly (output/file caps), because an interpreter-measuring RLIMIT_AS would be dishonest; cgroup v2 is the correct mechanism and is default/unified on all four families. |
| DL-all-03 | high | exact-match-protection | All three v0.1 protected lists match exactly. Units are the soundest (systemd names are stable across distros, with named exceptions like dbus-broker); package names are the weakest (every family names boot/trust packages differently, and versioned kernel packages defeat any fixed name). |

## Out of scope — abstention, not coverage

| ID | Subject | Finding |
|---|---|---|
| SC-all-01 | opensuse-microos | opensuse-microos is outside this review and outside the v0.1 catalog's live scope: transactional/declarative/image-based systems must be handled through their native interfaces or not at all (research/13). Any live verb reaching such a host must abstain. |
| SC-all-02 | nixos | nixos is outside this review and outside the v0.1 catalog's live scope: transactional/declarative/image-based systems must be handled through their native interfaces or not at all (research/13). Any live verb reaching such a host must abstain. |
| SC-all-03 | ostree-bootc | ostree-bootc is outside this review and outside the v0.1 catalog's live scope: transactional/declarative/image-based systems must be handled through their native interfaces or not at all (research/13). Any live verb reaching such a host must abstain. |

Transactional, declarative and image-based systems are not
"distros with different package names"; their repair routes are
different in kind. The catalog's live verbs must abstain there,
and LIF-1101's probes must detect the variant and force
observation-only mode.

## Recommendations (in order)

1. **Catalog v0.2 (with LIF-1102):** per-distro critical-unit,
   protected-path and protected-package lists owned by the
   adapters; the core keeps the union. Add family/prefix matching
   for versioned packages (kernel images above all), plus a test
   that fails when a listed name matches nothing on its distro —
   the exact-match trap that produced most findings here.
2. **Broker unit first:** systemd hardening (dedicated user,
   NoNewPrivileges, ProtectSystem, PrivateTmp, capability
   bounding set) is available on all four families and is the
   cheapest broker-grade layer to adopt uniformly.
3. **Landlock second:** kernel-supported everywhere reviewed;
   filesystem rules for the broker need no distro cooperation.
4. **cgroup v2 for memory/PID:** the honest replacement for the
   rlimit the executor deliberately does not claim.
5. **LSM last, per distro:** an AppArmor profile for the apt
   families and openSUSE-AppArmor installs, an SELinux domain
   for Fedora and openSUSE-SELinux installs — written and tested
   per distro, never assumed portable.
6. **Probe, don't presume (LIF-1101):** init system, LSM and
   its mode, userns policy, cgroup version and the transactional
   variants are runtime facts; the review's documentary rows are
   defaults to verify, not truths to bake in.

## What this review cannot do (honest limits)

- **Three of four rows are documentary.** Package and unit names
  are stable public facts of each family, but no Debian, Fedora
  or openSUSE system was run; a name that changed in a current
  release would change a finding. That is why every such row is
  labelled documented, NOT verified.
- **Mechanism availability is not mechanism effectiveness.**
  The matrix rates whether a mechanism exists and is used, from
  documentation plus one host's inventory. It does not measure
  escape resistance; that needs the disposable-VM adversarial
  suites of later phases.
- **The host observation is one machine.** purpleraider's Ubuntu
  26.10 (a development release) is not Kubuntu 24.04 LTS, the
  first target; the userns sysctl value observed here (0) is
  this host's setting, not a family promise.
- **No live validation was attempted.** By design: a review
  that restarted a protected unit to prove it was unprotected
  would violate the invariants it audits.
- **Human review pending.** No rung above lab-verified
  (documentary review + fixture tests, this host) is claimed
  for any part of this slice.

## Issue record — LIF-0407

```yaml
id: LIF-0407
phase: P4
goal: "Review sandbox and capability confinement effectiveness by distro."
dependencies: [LIF-0401, LIF-0403]
risk_tier: L0
scope: "Review only: mechanism matrix and catalog/executor audit in src/lifthrasir/confinement.py, this review document, documentary fixtures in tests/fixtures/lif0407/distros.json, and tests in tests/test_confinement_review.py. No host configuration changed on any distro; no README.md modification; the v0.1 catalog lists are audited, not edited."
test_fixture: "tests/test_confinement_review.py plus tests/fixtures/lif0407/distros.json: profile/matrix completeness, differential audit against the real v0.1 lists, named per-distro gap pins, positive controls, fail-closed unknown distros, document/module consistency."
expected_evidence: "Full-suite pytest log in hidden_files/ on purpleraider; negative-control log showing a tampered profile datum fails the suite."
negative_control: "A scratch copy of the confinement module with one documentary datum falsified (a gap declared covered) must fail the named-gap and positive-control tests; logged in hidden_files/."
recovery_or_undo: "Revert the slice commit (git revert) — review code, document, fixtures and tests only; no system state changed."
```
