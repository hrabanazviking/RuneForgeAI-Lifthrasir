# SPDX-License-Identifier: GPL-2.0-only
"""Tests for lab/calamares_config.py (Activation Phase 1, slice D).

Slice D2: assertions updated to the stock-aligned contract (stock
settings keys + stock exec order read from the live guest in the
D1 recon). The D1-era key names (dont-cancel,
disable-during-installation) and stale module names (initcpiocfg,
services-systemd) are asserted ABSENT so they cannot creep back.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lab.calamares_config import (CRITICAL, PINNED_PACKAGES,
                                  build_settings, config_iso_argv,
                                  packages_config, partition_config,
                                  render_module_conf,
                                  render_settings_conf, users_config)

# The module universe the D1 recon actually discovered in the guest.
FULL = CRITICAL | {"welcome", "locale", "keyboard", "pkgselect",
                   "summary", "finished", "fstab", "machineid",
                   "mount", "unpackfs", "localecfg",
                   "luksbootkeyfile", "displaymanager",
                   "networkcfg", "hwclock", "initramfscfg",
                   "initramfs", "grubcfg", "automirror",
                   "packages", "umount"}


def test_settings_unattended_stock_keys():
    s = build_settings(set(FULL))
    assert s["disable-cancel"] is True
    assert s["disable-cancel-during-exec"] is True
    assert s["prompt-install"] is False
    assert s["hide-back-and-next-during-exec"] is True
    assert s["quit-at-end"] is True
    assert s["dont-chroot"] is False
    assert "dont-cancel" not in s
    assert "disable-during-installation" not in s


def test_exec_is_stock_order_and_complete():
    s = build_settings(set(FULL))
    show_mods = s["sequence"][0]["show"]
    assert "partition" in show_mods and "users" in show_mods
    assert "summary" in show_mods
    exec_mods = s["sequence"][1]["exec"]
    assert set(CRITICAL) <= set(exec_mods)
    assert "packages" in exec_mods and "automirror" in exec_mods
    order = [exec_mods.index(m) for m in
             ("initramfscfg", "initramfs", "grubcfg", "bootloader")]
    assert order == sorted(order)
    for stale in ("initcpiocfg", "initcpio", "services-systemd"):
        assert stale not in exec_mods
    assert s["sequence"][2] == {"show": ["finished"]}


def test_missing_critical_refused():
    with pytest.raises(ValueError):
        build_settings(set(FULL) - {"bootloader"})


def test_render_settings_conf_stock_shape():
    text = render_settings_conf(build_settings(set(FULL)))
    assert "disable-cancel: true" in text
    assert "disable-cancel-during-exec: true" in text
    assert "prompt-install: false" in text
    assert "modules-search: [ local ]" in text
    assert "- exec:" in text and "- partition" in text
    assert "- show:" in text and "quit-at-end: true" in text
    assert "dont-cancel" not in text


def test_module_configs():
    assert partition_config()["initialPartitioningMode"] == "erase"
    u = users_config()
    assert u["user"]["name"] == "lab"
    assert u["hostname"]["template"] == "lifthrasir-lab"
    ops = packages_config()["operations"]
    install = [op["install"] for op in ops if "install" in op]
    assert install == [PINNED_PACKAGES]
    remove = [op["remove"] for op in ops if "remove" in op]
    assert remove and "calamares" in remove[0]
    pc = partition_config()
    assert pc["efiSystemPartition"] == "/boot/efi"
    assert pc["userSwapChoices"] == ["none", "file"]
    assert pc["luksGeneration"] == "luks2"


def test_render_module_conf():
    users = render_module_conf("users")
    assert "name: lab" in users and "template: lifthrasir-lab" in users
    pkgs = render_module_conf("packages")
    for pkg in PINNED_PACKAGES:
        assert pkg in pkgs
    part = render_module_conf("partition")
    assert "initialPartitioningMode: erase" in part
    with pytest.raises(ValueError):
        render_module_conf("bootloader")


def test_config_iso_argv():
    argv = config_iso_argv("/stage", "/tmp/c.iso")
    assert argv[0] == "genisoimage" and "-V" in argv
    assert argv[-1] == "/stage" and "/tmp/c.iso" in argv
