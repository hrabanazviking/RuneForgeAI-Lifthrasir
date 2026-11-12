"""Sandbox and capability confinement review by distro (LIF-0407).

SPDX-License-Identifier: GPL-2.0-only

Home: the review's machine-readable half lives in the core package
beside the artifacts it audits -- the LIF-0401 action catalog
(``actions.py``: its protected lists are v0.1 judgements) and the
LIF-0403 executor confinement (``executor.py``).  The human-readable
half is ``docs/CONFINEMENT-REVIEW.md``; tests pin the two together.
This module ships WITHOUT editing ``__init__.py``: the seat unions
exports at banking, as with LIF-0402/0403/0404.

What a review is, and is not (evidence-status honesty, roadmap
section 0 invariant 4):

* It produces FINDINGS plus tests/fixtures.  It changes no host
  configuration, installs nothing, loads no LSM profile, and
  executes no confined workload on any distro.
* The ubuntu row carries read-only host observations taken on
  purpleraider 2026-11-12 (os-release, the LSM list, a Landlock
  ABI version probe, cgroup v2, systemd 261).  That is evidence
  about THIS host's kernel/userspace inventory only -- not proof
  that any Lifthrasir component is confined on Ubuntu.
* The debian, fedora and opensuse rows are DOCUMENTARY: assembled
  from each family's stable public characteristics (default LSM,
  package/unit naming, trust-root locations).  They are labelled
  ``documented`` everywhere and are NOT verified: no other distro
  was booted, installed or probed for this slice.
* Unknown distros fail closed: ``verdict_for`` returns the
  observation-only verdict, mirroring research/13 (a platform with
  unknown semantics gets observation-only mode).

Method: for each distro family, (1) a mechanism matrix rates eight
confinement mechanisms (systemd hardening, namespaces, seccomp,
Landlock, capability dropping, cgroup v2, LSM/MAC, VM isolation)
as default / available / conditional / not-default, and records
whether the LIF-0403 executor actually uses each; (2) a catalog
audit compares the v0.1 protected lists against the distro's real
unit names, package names and trust-root paths.  The v0.1 lists use
EXACT matching (``actions._check_target``), so a name that is
merely close protects nothing -- that single fact drives most
package findings.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

REVIEW_VERSION = "0.1"
REVIEW_SCHEMA = "lifthrasir.confinement-review.v0.1"

MECHANISMS = (
    "systemd_hardening", "namespaces", "seccomp", "landlock",
    "capability_drop", "cgroup_v2", "lsm_mac", "vm_isolation",
)
MECHANISM_TITLES = {
    "systemd_hardening": "systemd unit hardening directives",
    "namespaces": "mount/PID/net/user namespaces",
    "seccomp": "seccomp syscall filtering",
    "landlock": "Landlock filesystem sandboxing",
    "capability_drop": "Linux capability dropping / NoNewPrivileges",
    "cgroup_v2": "cgroup v2 resource caps",
    "lsm_mac": "LSM mandatory access control (AppArmor/SELinux)",
    "vm_isolation": "disposable VM isolation (QEMU/KVM)",
}
# Mechanism availability: "default" (on out of the box), "available"
# (shipped and usable, not automatic), "conditional" (depends on
# release/policy/configuration), "not-default".
AVAILABILITY = ("default", "available", "conditional", "not-default")
# Whether the LIF-0403 fixture executor uses the mechanism today.
EXECUTOR_USE = {
    "systemd_hardening": "not-used",
    "namespaces": "not-used",
    "seccomp": "not-used",
    "landlock": "not-used",
    "capability_drop": "not-used",
    "cgroup_v2": "not-used",
    "lsm_mac": "not-used",
    "vm_isolation": "not-used",
}
# What the executor DOES use (its own docstring's honest list):
# separate process, sandbox-root path resolution + recheck, scrubbed
# environment, RLIMIT_CPU/FSIZE/NOFILE/CORE, wall/output/file caps.
# Those layers are plain POSIX and distro-portable -- the review's
# central positive finding -- but none of the eight kernel/distro
# mechanisms above is among them.
EXECUTOR_OWN_LAYERS = (
    "separate-process", "sandbox-path-resolution", "env-scrub",
    "rlimits", "wall-and-size-caps",
)

SEVERITIES = ("high", "medium", "low", "info")


class ReviewError(Exception):
    """Base class for confinement-review refusals."""


class UnknownDistroError(ReviewError):
    """Raised when a distro id is not one of the reviewed families."""


@dataclass(frozen=True)
class DistroProfile:
    distro_id: str
    display: str
    evidence: str  # "host-observed" | "documented"
    package_manager: str
    default_lsm: str
    mechanisms: Dict[str, str]  # mechanism -> availability
    extra_critical_units: Tuple[Tuple[str, str, str], ...]  # (unit, severity, why)
    extra_protected_paths: Tuple[Tuple[str, str, str], ...]  # (prefix, severity, why)
    package_names: Dict[str, str]  # concept -> the distro's real package name
    notes: Tuple[str, ...] = ()


_COMMON_UNITS = (
    ("polkit.service", "high",
     "the privilege-escalation broker itself: whoever can restart or "
     "replace polkit controls authorization for the whole desktop"),
    ("systemd-resolved.service", "medium",
     "name resolution for every lookup; a hostile resolver is a "
     "machine-wide redirect"),
)
_COMMON_PATHS = (
    ("/etc/sudoers", "high", "sudo policy is a trust root"),
    ("/etc/sudoers.d", "high", "sudo policy drop-ins are a trust root"),
    ("/etc/polkit-1", "high", "polkit rules decide privileged actions"),
    ("/etc/systemd", "high",
     "unit and drop-in directory: a config revert that can write "
     "here can install a persistent privileged service"),
    ("/etc/fstab", "medium",
     "mount table; roadmap section 0 puts partition-adjacent state "
     "outside autonomous mutation"),
    ("/etc/crypttab", "high",
     "encryption setup; section 0 invariant 2 names encryption"),
    ("/etc/default/grub", "medium",
     "bootloader configuration on apt and rpm families alike; "
     "/boot alone does not cover it"),
)
# Package concepts the review tracks, and the v0.1 name (if any) that
# was supposed to protect the concept.
PACKAGE_CONCEPTS = (
    "kernel_image", "bootloader", "shim", "firmware", "openssl",
    "gnupg", "ssh_server", "init_system", "polkit_pkg", "sudo_pkg",
    "package_manager_pkg",
)

_UBUNTU = DistroProfile(
    distro_id="ubuntu",
    display="Ubuntu / Kubuntu (first target family)",
    evidence="host-observed",
    package_manager="apt/dpkg",
    default_lsm="apparmor",
    mechanisms={
        "systemd_hardening": "available",
        "namespaces": "conditional",
        "seccomp": "available",
        "landlock": "available",
        "capability_drop": "available",
        "cgroup_v2": "default",
        "lsm_mac": "default",
        "vm_isolation": "available",
    },
    extra_critical_units=_COMMON_UNITS + (
        ("snapd.service", "high",
         "snapd installs and removes software and holds its own "
         "trust chain; it is a package authority, not a user service"),
        ("ufw.service", "medium",
         "the host firewall frontend where installed; section 0 "
         "names critical firewall state as never agent-mutated"),
        ("apparmor.service", "medium",
         "loads the MAC policy that confines everything else"),
    ),
    extra_protected_paths=_COMMON_PATHS + (
        ("/etc/apparmor", "high", "AppArmor policy is a trust root"),
        ("/etc/apparmor.d", "high", "AppArmor profiles are a trust root"),
        ("/etc/apt", "high",
         "apt sources and keyrings are the package trust root; the "
         "v0.1 list protects the TLS root (/etc/ssl) but not apt's"),
        ("/etc/ca-certificates", "medium", "CA trust configuration"),
        ("/usr/share/ca-certificates", "medium",
         "CA trust source store consumed by update-ca-certificates"),
        ("/etc/grub.d", "medium", "grub script fragments (boot chain)"),
    ),
    package_names={
        "kernel_image": "linux-image-generic",
        "bootloader": "grub-efi-amd64-signed",
        "shim": "shim-signed",
        "firmware": "linux-firmware",
        "openssl": "openssl",
        "gnupg": "gnupg",
        "ssh_server": "openssh-server",
        "init_system": "systemd",
        "polkit_pkg": "polkitd",
        "sudo_pkg": "sudo",
        "package_manager_pkg": "apt",
    },
    notes=(
        "Host-observed on purpleraider (Ubuntu 26.10, kernel "
        "7.3.0-10-generic): LSM list includes landlock and "
        "apparmor, AppArmor enabled, Landlock ABI 11 answered a "
        "version probe, cgroup v2 unified, systemd 261.",
        "User namespaces are conditional: Ubuntu mediates "
        "unprivileged user namespaces through AppArmor policy (the "
        "kernel.apparmor_restrict_unprivileged_userns sysctl exists "
        "on this host, value 0 here); a broker design must not "
        "assume userns is either always open or always closed.",
        "Versioned kernel packages (linux-image-7.3.0-10-generic "
        "and kin) mean even a corrected fixed name ages out every "
        "kernel update: package protection needs prefix/family "
        "matching, which is a v0.2 catalog design question.",
    ),
)

_DEBIAN = DistroProfile(
    distro_id="debian",
    display="Debian",
    evidence="documented",
    package_manager="apt/dpkg",
    default_lsm="apparmor",
    mechanisms={
        "systemd_hardening": "available",
        "namespaces": "available",
        "seccomp": "available",
        "landlock": "available",
        "capability_drop": "available",
        "cgroup_v2": "default",
        "lsm_mac": "available",
        "vm_isolation": "available",
    },
    extra_critical_units=_COMMON_UNITS + (
        ("apparmor.service", "medium",
         "loads the MAC policy that confines everything else"),
    ),
    extra_protected_paths=_COMMON_PATHS + (
        ("/etc/apparmor", "high", "AppArmor policy is a trust root"),
        ("/etc/apparmor.d", "high", "AppArmor profiles are a trust root"),
        ("/etc/apt", "high",
         "apt sources and keyrings are the package trust root"),
        ("/etc/ca-certificates", "medium", "CA trust configuration"),
        ("/usr/share/ca-certificates", "medium", "CA trust source store"),
        ("/etc/grub.d", "medium", "grub script fragments (boot chain)"),
    ),
    package_names={
        "kernel_image": "linux-image-amd64",
        "bootloader": "grub-efi-amd64",
        "shim": "shim-signed",
        "firmware": "firmware-linux",
        "openssl": "openssl",
        "gnupg": "gnupg",
        "ssh_server": "openssh-server",
        "init_system": "systemd",
        "polkit_pkg": "polkitd",
        "sudo_pkg": "sudo",
        "package_manager_pkg": "apt",
    },
    notes=(
        "AppArmor ships and is enabled by default, but with a "
        "smaller enforcing profile set than Ubuntu: LSM status is "
        "available, not the blanket default Ubuntu users assume.",
        "Debian is the one family where v0.1 'firmware-linux' is "
        "the real name -- the exception that proves the exact-match "
        "problem everywhere else.",
        "Non-systemd installs exist in the wild; the adapter must "
        "probe the init system (LIF-1101), not assume it.",
    ),
)

_FEDORA = DistroProfile(
    distro_id="fedora",
    display="Fedora",
    evidence="documented",
    package_manager="dnf/rpm",
    default_lsm="selinux",
    mechanisms={
        "systemd_hardening": "available",
        "namespaces": "available",
        "seccomp": "available",
        "landlock": "available",
        "capability_drop": "available",
        "cgroup_v2": "default",
        "lsm_mac": "default",
        "vm_isolation": "available",
    },
    extra_critical_units=_COMMON_UNITS + (
        ("dbus-broker.service", "high",
         "Fedora's D-Bus broker runs under this unit name; the v0.1 "
         "list names only dbus.service, so on Fedora the message "
         "bus is NOT protected by the critical-unit list"),
        ("firewalld.service", "high",
         "the default firewall daemon; section 0 names critical "
         "firewall state as never agent-mutated"),
        ("auditd.service", "medium",
         "the audit log is the record section 0 invariant 3 "
         "requires; stopping it blinds every other control"),
    ),
    extra_protected_paths=_COMMON_PATHS + (
        ("/etc/selinux", "high", "SELinux policy is a trust root"),
        ("/etc/dnf", "medium", "dnf configuration and repo handling"),
        ("/etc/yum.repos.d", "medium",
         "repository definitions feed the package trust root"),
    ),
    package_names={
        "kernel_image": "kernel-core",
        "bootloader": "grub2-efi-x64",
        "shim": "shim-x64",
        "firmware": "linux-firmware",
        "openssl": "openssl",
        "gnupg": "gnupg2",
        "ssh_server": "openssh-server",
        "init_system": "systemd",
        "polkit_pkg": "polkit",
        "sudo_pkg": "sudo",
        "package_manager_pkg": "dnf",
    },
    notes=(
        "SELinux is enforcing by default -- the strongest default "
        "MAC of the four families -- but a broker needs its own "
        "SELinux domain; running unconfined under a targeted policy "
        "gains little, so lsm_mac 'default' is an opportunity, not "
        "a property Lifthrasir inherits for free.",
        "v0.1 'kernel' does match Fedora's kernel metapackage -- "
        "the only kernel_image concept any family matches -- while "
        "the actually-installed kernel-core stays unlisted.",
        "/etc/pki IS in the v0.1 protected prefixes, so Fedora's "
        "TLS/RPM trust roots are the best-covered of any family.",
    ),
)

_OPENSUSE = DistroProfile(
    distro_id="opensuse",
    display="openSUSE (Leap / Tumbleweed)",
    evidence="documented",
    package_manager="zypper/rpm",
    default_lsm="apparmor-or-selinux",
    mechanisms={
        "systemd_hardening": "available",
        "namespaces": "available",
        "seccomp": "available",
        "landlock": "available",
        "capability_drop": "available",
        "cgroup_v2": "default",
        "lsm_mac": "conditional",
        "vm_isolation": "available",
    },
    extra_critical_units=_COMMON_UNITS + (
        ("wicked.service", "medium",
         "the traditional openSUSE network stack: a host may run "
         "wicked instead of the NetworkManager the v0.1 list names"),
        ("firewalld.service", "high",
         "the default firewall daemon; critical firewall state is "
         "never agent-mutated (section 0)"),
        ("auditd.service", "medium",
         "the audit log is the record invariant 3 requires"),
        ("apparmor.service", "medium",
         "loads MAC policy on AppArmor-configured installs"),
    ),
    extra_protected_paths=_COMMON_PATHS + (
        ("/etc/apparmor", "high",
         "AppArmor policy on AppArmor-configured installs"),
        ("/etc/apparmor.d", "high", "AppArmor profiles"),
        ("/etc/selinux", "high",
         "SELinux policy on SELinux-configured installs"),
        ("/etc/zypp", "medium",
         "zypper configuration and repository handling"),
    ),
    package_names={
        "kernel_image": "kernel-default",
        "bootloader": "grub2",
        "shim": "shim",
        "firmware": "kernel-firmware",
        "openssl": "openssl",
        "gnupg": "gpg2",
        "ssh_server": "openssh",
        "init_system": "systemd",
        "polkit_pkg": "polkit",
        "sudo_pkg": "sudo",
        "package_manager_pkg": "zypper",
    },
    notes=(
        "The LSM is genuinely conditional: AppArmor is the "
        "traditional default and SELinux is offered on current "
        "releases, so neither the mechanism matrix nor the path "
        "list may hard-code one -- the adapter probes (LIF-1101).",
        "openSUSE is the only family where v0.1 'shim' and 'grub2' "
        "are real package names.",
        "Transactional variants (MicroOS) are OUT of this "
        "review's scope: live verbs abstain there (research/13).",
    ),
)

PROFILES: Dict[str, DistroProfile] = {
    p.distro_id: p
    for p in (_UBUNTU, _DEBIAN, _FEDORA, _OPENSUSE)
}
DISTRO_IDS = tuple(PROFILES.keys())
OUT_OF_SCOPE_VARIANTS = ("opensuse-microos", "nixos", "ostree-bootc")


@dataclass(frozen=True)
class Finding:
    finding_id: str
    distro: str  # distro id, or "all"
    kind: str  # critical-unit-gap | protected-path-gap |
    #            package-name-mismatch | package-unlisted |
    #            executor-layer-unused | executor-design-limit |
    #            scope-exclusion
    severity: str
    subject: str
    detail: str
    recommendation: str


def get_profile(distro_id: str) -> DistroProfile:
    try:
        return PROFILES[distro_id]
    except KeyError:
        raise UnknownDistroError(
            f"unknown distro {distro_id!r}: reviewed families are "
            f"{sorted(PROFILES)}; anything else is observation-only "
            "(research/13)") from None


def parse_os_release(text: str) -> Dict[str, str]:
    """Parse os-release text (fixture or host) into a plain dict."""
    out: Dict[str, str] = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        out[key.strip()] = value.strip().strip('"').strip("'")
    return out


def distro_id_for_os_release(text: str) -> Optional[str]:
    """Map an os-release ID to a reviewed family, or None.

    ID_LIKE is honoured (kubuntu -> ubuntu via ID=ubuntu in its
    os-release; derivatives naming debian in ID_LIKE map to the
    debian family).  An unmapped ID returns None: fail closed.
    """
    fields = parse_os_release(text)
    candidates = [fields.get("ID", "")] + fields.get(
        "ID_LIKE", "").split()
    for cand in candidates:
        cand = cand.strip().lower()
        if cand in PROFILES:
            return cand
        if cand in ("kubuntu", "xubuntu", "lubuntu"):
            return "ubuntu"
        if cand in ("suse", "sles", "opensuse-leap",
                    "opensuse-tumbleweed"):
            return "opensuse"
        if cand in ("rhel", "centos"):
            return "fedora"
    return None


def _v01_lists():
    from .actions import (
        CRITICAL_UNITS, PROTECTED_PACKAGES, PROTECTED_PATH_PREFIXES)
    return (set(CRITICAL_UNITS), set(PROTECTED_PACKAGES),
            tuple(PROTECTED_PATH_PREFIXES))


def _path_covered(prefix: str, protected: Tuple[str, ...]) -> bool:
    return any(prefix == p or prefix.startswith(p + "/")
               or p.startswith(prefix + "/") for p in protected)


_HIGH_PACKAGE_CONCEPTS = frozenset({
    "kernel_image", "bootloader", "shim", "firmware"})


def audit_catalog(distro_id: str) -> List[Finding]:
    """Audit the v0.1 protected lists against one distro family.

    Pure data comparison against the banked catalog lists imported
    from ``actions`` -- nothing on any host is read or changed.
    """
    profile = get_profile(distro_id)
    units, packages, paths = _v01_lists()
    findings: List[Finding] = []
    n = 0

    def add(kind, severity, subject, detail, recommendation):
        nonlocal n
        n += 1
        findings.append(Finding(
            finding_id=f"CF-{distro_id}-{n:02d}", distro=distro_id,
            kind=kind, severity=severity, subject=subject,
            detail=detail, recommendation=recommendation))

    for unit, severity, why in profile.extra_critical_units:
        if unit not in units:
            add("critical-unit-gap", severity, unit,
                f"{unit} is critical on {profile.display} ({why}) "
                "but is absent from the v0.1 CRITICAL_UNITS list, "
                "so restart_unit/stop_unit would validate against "
                "it on a live host.",
                "Add the unit to the per-distro critical set in "
                "catalog v0.2 (LIF-1101/1102 adapters own the "
                "per-distro lists; the core list stays the union).")
    for prefix, severity, why in profile.extra_protected_paths:
        if not _path_covered(prefix, paths):
            add("protected-path-gap", severity, prefix,
                f"{prefix} on {profile.display}: {why}. It is not "
                "covered by the v0.1 PROTECTED_PATH_PREFIXES, so "
                "revert_user_config would validate against paths "
                "under it on a live host.",
                "Add the prefix to the per-distro protected set "
                "in catalog v0.2.")
    for concept in PACKAGE_CONCEPTS:
        real = profile.package_names[concept]
        if real in packages:
            continue
        severity = "high" if concept in _HIGH_PACKAGE_CONCEPTS \
            else "medium"
        near = sorted(p for p in packages
                      if real.startswith(p) or p.startswith(real))
        if near:
            add("package-name-mismatch", severity, real,
                f"On {profile.display} the {concept} package is "
                f"named {real!r}. The v0.1 PROTECTED_PACKAGES list "
                f"holds the near-name(s) {near}, but matching is "
                "EXACT (actions._check_target), so the protection "
                "does not fire for the package actually installed.",
                "Move package protection to per-distro exact "
                "names plus family/prefix rules in catalog v0.2; "
                "never let a near-name imply coverage.")
        else:
            add("package-unlisted", severity, real,
                f"On {profile.display} the {concept} package "
                f"{real!r} has no entry at all in the v0.1 "
                "PROTECTED_PACKAGES list, so install_package / "
                "remove_package would validate against it.",
                "List the concept per distro in catalog v0.2 "
                "(init system, polkit, sudo and the package "
                "manager are trust roots on every family).")
    return findings


def audit_executor(distro_id: str) -> List[Finding]:
    """Rate the LIF-0403 executor's layers against one distro."""
    profile = get_profile(distro_id)
    findings: List[Finding] = []
    n = 0
    for mech in MECHANISMS:
        if EXECUTOR_USE[mech] == "not-used":
            n += 1
            findings.append(Finding(
                finding_id=f"EF-{distro_id}-{n:02d}",
                distro=distro_id, kind="executor-layer-unused",
                severity="medium", subject=mech,
                detail=(
                    f"{MECHANISM_TITLES[mech]} is "
                    f"{profile.mechanisms[mech]} on "
                    f"{profile.display}, but the LIF-0403 fixture "
                    "executor does not use it: its confinement is "
                    "process separation, sandbox path resolution, "
                    "environment scrub and rlimits only. That is "
                    "honest fixture-level confinement (its own "
                    "docstring says so); it is not broker-grade "
                    "isolation on any distro."),
                recommendation=(
                    "Broker work after P4: adopt the distro's "
                    "native layer (systemd hardening unit first -- "
                    "it is available on all four families) and "
                    "record adoption per distro in LIF-1101 "
                    "capability probes.")))
    return findings


def design_limit_findings() -> List[Finding]:
    """Executor limits that hold on every distro (rated once)."""
    rows = [
        ("no-uid-drop", "medium",
         "The executor child runs at the caller's uid on every "
         "distro; LIF-0403 names this honestly. A dedicated broker "
         "uid (systemd DynamicUser/User) is available everywhere "
         "and unused.",
         "Give the broker its own uid via its systemd unit in "
         "broker work; never claim separation the uid does not "
         "provide."),
        ("no-memory-or-pid-cap", "medium",
         "Memory and process-count are bounded only indirectly "
         "(output/file caps), because an interpreter-measuring "
         "RLIMIT_AS would be dishonest; cgroup v2 is the correct "
         "mechanism and is default/unified on all four families.",
         "Bound the broker with cgroup v2 (MemoryMax, TasksMax) "
         "through its systemd unit."),
        ("exact-match-protection", "high",
         "All three v0.1 protected lists match exactly. Units are "
         "the soundest (systemd names are stable across distros, "
         "with named exceptions like dbus-broker); package names "
         "are the weakest (every family names boot/trust packages "
         "differently, and versioned kernel packages defeat any "
         "fixed name).",
         "Catalog v0.2: per-distro lists owned by the adapters "
         "(LIF-1102), family/prefix matching for versioned "
         "packages, and a test that fails when a listed name "
         "matches nothing on its distro."),
    ]
    return [Finding(finding_id=f"DL-all-{i:02d}", distro="all",
                    kind="executor-design-limit", severity=sev,
                    subject=subj, detail=detail,
                    recommendation=rec)
            for i, (subj, sev, detail, rec) in enumerate(rows, 1)]


def scope_findings() -> List[Finding]:
    return [Finding(
        finding_id=f"SC-all-{i:02d}", distro="all",
        kind="scope-exclusion", severity="info", subject=variant,
        detail=(
            f"{variant} is outside this review and outside the "
            "v0.1 catalog's live scope: transactional/declarative/"
            "image-based systems must be handled through their "
            "native interfaces or not at all (research/13). Any "
            "live verb reaching such a host must abstain."),
        recommendation=(
            "LIF-1101 probes must detect the variant and force "
            "observation-only mode."))
        for i, variant in enumerate(OUT_OF_SCOPE_VARIANTS, 1)]


def all_findings() -> List[Finding]:
    out: List[Finding] = []
    for distro_id in DISTRO_IDS:
        out.extend(audit_catalog(distro_id))
        out.extend(audit_executor(distro_id))
    out.extend(design_limit_findings())
    out.extend(scope_findings())
    return out


def covered_package_concepts(distro_id: str) -> List[str]:
    """Concepts whose real distro name IS in the v0.1 list."""
    profile = get_profile(distro_id)
    _, packages, _ = _v01_lists()
    return [c for c in PACKAGE_CONCEPTS
            if profile.package_names[c] in packages]


def verdict_for(distro_id: Optional[str]) -> Dict[str, object]:
    """One distro's confinement verdict, fail-closed on unknown."""
    if distro_id is None or distro_id not in PROFILES:
        return {
            "distro": distro_id, "mode": "observation-only",
            "executor_layers": list(EXECUTOR_OWN_LAYERS),
            "broker_grade_layers_used": [],
            "catalog_findings": None,
            "note": "unreviewed distro: observation-only until "
                    "LIF-1101 probes and a review row exist",
        }
    profile = PROFILES[distro_id]
    return {
        "distro": distro_id, "mode": "reviewed",
        "evidence": profile.evidence,
        "executor_layers": list(EXECUTOR_OWN_LAYERS),
        "broker_grade_layers_used": [],
        "catalog_findings": len(audit_catalog(distro_id)),
        "executor_findings": len(audit_executor(distro_id)),
        "note": "fixture-level executor confinement is "
                "distro-portable (plain POSIX) but uses none of "
                "the eight kernel/distro mechanisms; the v0.1 "
                "protected lists have the per-distro gaps the "
                "findings enumerate",
    }


def review_as_dict() -> Dict[str, object]:
    """The whole review as a JSON-ready mapping (the doc's twin)."""
    return {
        "schema": REVIEW_SCHEMA, "review_version": REVIEW_VERSION,
        "mechanisms": list(MECHANISMS),
        "executor_use": dict(EXECUTOR_USE),
        "executor_own_layers": list(EXECUTOR_OWN_LAYERS),
        "distros": {
            d: {
                "display": PROFILES[d].display,
                "evidence": PROFILES[d].evidence,
                "package_manager": PROFILES[d].package_manager,
                "default_lsm": PROFILES[d].default_lsm,
                "mechanisms": dict(PROFILES[d].mechanisms),
                "package_names": dict(PROFILES[d].package_names),
                "covered_package_concepts":
                    covered_package_concepts(d),
            } for d in DISTRO_IDS},
        "findings": [
            {"finding_id": f.finding_id, "distro": f.distro,
             "kind": f.kind, "severity": f.severity,
             "subject": f.subject, "detail": f.detail,
             "recommendation": f.recommendation}
            for f in all_findings()],
        "out_of_scope_variants": list(OUT_OF_SCOPE_VARIANTS),
    }
