# SPDX-License-Identifier: GPL-2.0-only
"""Activation Phase 1, slice D: Calamares unattended config builder.

Pure builder: given the module names DISCOVERED in the live guest
(slice D recon evidence -- never assumed), build the unattended
settings.conf + module configs for the installed golden. Refuses
(fail-closed) when a critical exec module is missing from the
discovered set. The lab user defined here is a throwaway account
inside a disposable, offline VM only.

Slice D2 alignment (2026-11-12): settings keys and the exec sequence
now match the STOCK Kubuntu layout read from the live guest in the
D1 recon (evidence: lab/evidence/sliceD-recon.json):

* stock keys are ``disable-cancel`` / ``disable-cancel-during-exec``
  (the D1 builder's ``dont-cancel`` / ``disable-during-installation``
  names exist in no stock file and are gone);
* the exec sequence is the stock order verbatim (initramfscfg /
  initramfs -- not the D1 builder's stale initcpiocfg / initcpio /
  services-systemd names, none of which the guest ships);
* the sequence is exec-first with only the ``finished`` show step:
  an unattended run has no one to click through view modules.
"""
from __future__ import annotations

SHOW = ["welcome", "locale", "keyboard", "pkgselect", "partition",
        "users", "summary"]
EXEC = ["partition", "mount", "unpackfs", "machineid", "fstab",
        "locale", "keyboard", "localecfg", "luksbootkeyfile",
        "users", "displaymanager", "networkcfg", "hwclock",
        "initramfscfg", "initramfs", "grubcfg", "bootloader",
        "automirror", "packages", "umount"]
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
        "modules-search": ["local"],
        "instances": [],
        "sequence": [{"show": pick(SHOW)},
                     {"exec": pick(EXEC)},
                     {"show": pick(FINISH)}],
        "branding": "kubuntu",
        "prompt-install": False,
        "dont-chroot": False,
        "oem-setup": False,
        "disable-cancel": True,
        "disable-cancel-during-exec": True,
        "hide-back-and-next-during-exec": True,
        "quit-at-end": True,
    }


def partition_config() -> dict:
    # Full-file replacement in the guest, so this must carry the
    # stock keys the D2 attempts proved Calamares needs (attempts
    # 5-7 warnings: luksGeneration, userSwapChoices, EFI partition).
    # LUKS layout dropped: erase mode, no encryption, GPT, ext4.
    return {"efiSystemPartition": "/boot/efi",
            "enableLuksAutomatedPartitioning": False,
            "luksGeneration": "luks2",
            "userSwapChoices": ["none", "file"],
            "initialSwapChoice": "none",
            "defaultPartitionTableType": "gpt",
            "defaultFileSystemType": "ext4",
            "availableFileSystemTypes": ["ext4"],
            "drawNestedPartitions": False,
            "allowManualPartitioning": False,
            "initialPartitioningMode": "erase"}


def users_config() -> dict:
    # Throwaway lab-only account in a disposable offline VM.
    return {"defaultGroups": ["sudo", "adm"],
            "doAutologin": False,
            "sudoersGroup": "sudo",
            "setRootPassword": False,
            "doReusePassword": True,
            "allowWeakPasswords": False,
            "passwordRequirements": {"minLength": 1,
                                     "maxLength": -1},
            "user": {"name": LAB_USER, "fullname": "Lab User",
                     "password": "lifthrasir-lab",
                     "shell": "/bin/bash"},
            "hostname": {"location": "EtcFile",
                         "writeHostsFile": True,
                         "template": LAB_HOSTNAME}}


def packages_config() -> dict:
    # Stock remove ops kept (attempt-7 stock dump): the installed
    # system should shed the live installer, as a real install does.
    return {"update_db": True, "backend": "apt",
            "operations": [
                {"remove": ["^live-*", "calamares-settings-kubuntu",
                            "calamares", "cifs-utils",
                            "kubuntu-installer-prompt"]},
                {"install": list(PINNED_PACKAGES)}]}


def _yaml_scalar(v) -> str:
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return str(v)
    s = str(v)
    needs_quote = (
        s == "" or s != s.strip()
        or s[0] in "-?:,[]{}#&*!|>'\"%@`"
        or ": " in s or " #" in s or s.endswith(":")
        or s.lower() in ("true", "false", "null", "yes", "no",
                         "on", "off", "~"))
    if needs_quote:
        return '"' + s.replace('"', '\\"') + '"'
    return s


def _emit(obj, indent: int) -> list[str]:
    pad = "  " * indent
    out: list[str] = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            if isinstance(v, (dict, list)) and v:
                out.append(f"{pad}{k}:")
                out += _emit(v, indent + 1)
            elif isinstance(v, list):
                out.append(f"{pad}{k}: []")
            elif isinstance(v, dict):
                out.append(f"{pad}{k}: {{}}")
            else:
                out.append(f"{pad}{k}: {_yaml_scalar(v)}")
    elif isinstance(obj, list):
        for item in obj:
            if isinstance(item, dict):
                first = True
                for k, v in item.items():
                    pfx = f"{pad}- " if first else f"{pad}  "
                    first = False
                    if isinstance(v, (dict, list)) and v:
                        out.append(f"{pfx}{k}:")
                        out += _emit(v, indent + 2)
                    elif isinstance(v, list):
                        out.append(f"{pfx}{k}: []")
                    else:
                        out.append(f"{pfx}{k}: {_yaml_scalar(v)}")
            else:
                out.append(f"{pad}- {_yaml_scalar(item)}")
    return out


def render_module_conf(kind: str) -> str:
    """Render one module config (partition|users|packages) as YAML."""
    builders = {"partition": partition_config, "users": users_config,
                "packages": packages_config}
    if kind not in builders:
        raise ValueError(f"unknown module config kind: {kind}")
    return "---\n" + "\n".join(_emit(builders[kind](), 0)) + "\n"


def render_settings_conf(s: dict) -> str:
    """Render settings dict as settings.conf YAML text."""
    yn = lambda b: "true" if b else "false"
    out = ["---"]
    ms = ", ".join(s["modules-search"])
    out.append(f"modules-search: [ {ms} ]")
    out.append("instances: []")
    out.append("sequence:")
    for phase in s["sequence"]:
        for key, mods in phase.items():
            out.append(f"  - {key}:")
            out += [f"    - {m}" for m in mods]
    out.append(f"branding: {s['branding']}")
    out.append(f"prompt-install: {yn(s['prompt-install'])}")
    out.append(f"dont-chroot: {yn(s['dont-chroot'])}")
    out.append(f"oem-setup: {yn(s['oem-setup'])}")
    out.append(f"disable-cancel: {yn(s['disable-cancel'])}")
    out.append("disable-cancel-during-exec: "
               f"{yn(s['disable-cancel-during-exec'])}")
    out.append("hide-back-and-next-during-exec: "
               f"{yn(s['hide-back-and-next-during-exec'])}")
    out.append(f"quit-at-end: {yn(s['quit-at-end'])}")
    return "\n".join(out) + "\n"


def config_iso_argv(staging: str, iso_path: str) -> list[str]:
    """genisoimage argv for the config CD (allowlist-shaped)."""
    return ["genisoimage", "-o", iso_path, "-V", "LIF_CONFIG",
            "-J", "-R", staging]
