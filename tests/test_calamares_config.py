# SPDX-License-Identifier: GPL-2.0-only
"""Tests for lab/calamares_config.py (Activation Phase 1, slice D)."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lab.calamares_config import (CRITICAL, PINNED_PACKAGES,
                                  build_settings, config_iso_argv,
                                  packages_config, partition_config,
                                  render_settings_conf, users_config)

FULL = CRITICAL | {"welcome", "locale", "keyboard", "summary",
                   "fstab", "machineid", "finished", "umount",
                   "mount", "grubcfg", "hwclock"}


def test_settings_intersect_discovered_and_unattended():
    s = build_settings(set(FULL))
    assert s["dont-cancel"] is True
    assert s["prompt-install"] is False
    exec_mods = s["sequence"][1]["exec"]
    assert set(CRITICAL) <= set(exec_mods)
    assert "nonexistent-module" not in exec_mods


def test_missing_critical_refused():
    with pytest.raises(ValueError):
        build_settings(set(FULL) - {"bootloader"})


def test_render_is_parseable_shape():
    text = render_settings_conf(build_settings(set(FULL)))
    assert "dont-cancel: true" in text
    assert "- exec:" in text and "- partition" in text


def test_module_configs():
    assert partition_config()["initialPartitioningMode"] == "erase"
    u = users_config()
    assert u["user"]["name"] == "lab"
    assert u["hostname"]["template"] == "lifthrasir-lab"
    ops = packages_config()["operations"][0]["install"]
    assert ops == PINNED_PACKAGES


def test_config_iso_argv():
    argv = config_iso_argv("/stage", "/tmp/c.iso")
    assert argv[0] == "genisoimage" and "-V" in argv
    assert argv[-1] == "/stage" and "/tmp/c.iso" in argv
