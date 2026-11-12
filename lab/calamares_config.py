# SPDX-License-Identifier: GPL-2.0-only
"""Activation Phase 1, slice D: Calamares unattended config builder.

Pure builder: given the module names DISCOVERED in the live guest
(slice D recon evidence -- never assumed), build the unattended
settings.conf + module configs for the installed golden. Refuses
(fail-closed) when a critical exec module is missing from the
discovered set. The lab user defined here is a throwaway account
inside a disposable, offline VM only.
"""
from __future__ import annotations

SHOW = ["welcome", "locale", "keyboard", "partition", "users",
        "summary"]
EXEC = ["partition", "mount", "unpackfs", "machineid", "fstab",
        "locale", "keyboard", "localecfg", "initcpiocfg",
        "initcpio", "users", "displaymanager", "networkcfg",
        "hwclock", "services-systemd", "grubcfg", "bootloader",
        "umount"]
FINISH = ["finished"]
CRITICAL = {"partition", "mount", "unpackfs", "users", "bootloader"}
LAB_USER = "lab"
LAB_HOSTNAME = "lifthrasir-lab"
PINNED_PACKAGES = ["openssh-server", "qemu-guest-agent",
                   "spice-vdagent"]


def build_settings(discovered: set[str]) -> dict:
    """Unattended settings intersected with discovered modules."""
    missing = CRITICAL - set(discovered)
    if missing:
        raise ValueError(
            f"critical calamares modules missing: {sorted(missing)}")
    pick = lambda seq: [m for m in seq if m in discovered]
    return {
        "modules-search": ["local", "/etc/calamares/modules"],
        "instances": [],
        "sequence": [{"show": pick(SHOW)},
                     {"exec": pick(EXEC)},
                     {"show": pick(FINISH)}],
        "branding": "kubuntu",
        "prompt-install": False,
        "dont-cancel": True,
        "oem-setup": False,
        "disable-during-installation": True,
    }


def partition_config() -> dict:
    return {"defaultFileSystemType": "ext4",
            "availableFileSystemTypes": ["ext4"],
            "drawNestedPartitions": False,
            "allowManualPartitioning": False,
            "initialPartitioningMode": "erase",
            "initialSwapChoice": "none"}


def users_config() -> dict:
    # Throwaway lab-only account in a disposable offline VM.
    return {"defaultGroups": ["sudo", "adm"],
            "doAutologin": False,
            "sudoersGroup": "sudo",
            "setRootPassword": False,
            "doReusePassword": True,
            "allowWeakPasswords": False,
            "user": {"name": LAB_USER, "fullname": "Lab User",
                     "password": "lifthrasir-lab",
                     "shell": "/bin/bash"},
            "hostname": {"location": "EtcFile",
                         "writeHostsFile": True,
                         "template": LAB_HOSTNAME}}


def packages_config() -> dict:
    return {"update_db": False, "backend": "apt",
            "operations": [{"install": list(PINNED_PACKAGES)}]}


def render_settings_conf(s: dict) -> str:
    """Render settings dict as settings.conf YAML text."""
    out = ["---"]
    out.append(f"branding: {s['branding']}")
    out.append(f"prompt-install: {str(s['prompt-install']).lower()}")
    out.append(f"dont-cancel: {str(s['dont-cancel']).lower()}")
    out.append(f"oem-setup: {str(s['oem-setup']).lower()}")
    out.append("sequence:")
    for phase in s["sequence"]:
        for key, mods in phase.items():
            out.append(f"  - {key}:")
            out += [f"    - {m}" for m in mods]
    return "\n".join(out) + "\n"


def config_iso_argv(staging: str, iso_path: str) -> list[str]:
    """genisoimage argv for the config CD (allowlist-shaped)."""
    return ["genisoimage", "-o", iso_path, "-V", "LIF_CONFIG",
            "-J", "-R", staging]
