# SPDX-License-Identifier: GPL-2.0-only
"""Tests for lab/manual_install.py (Activation Phase 1, slice D3)."""
import sys
from pathlib import Path
import pytest
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from lab.manual_install import (apt_archive_lines, chroot_script,
    fstab_text, guest_install_script, render_chroot, sfdisk_script)

def test_sfdisk_gpt_efi_then_root():
    s = sfdisk_script()
    assert "label: gpt" in s and "type=U" in s and "type=L" in s

def test_fstab_fail_closed_and_shape():
    with pytest.raises(ValueError):
        fstab_text("", "ABCD-1234")
    t = fstab_text("root-uuid", "ABCD-1234")
    assert "UUID=root-uuid / ext4" in t
    assert "UUID=ABCD-1234 /boot/efi vfat" in t

def test_guest_script_refuses_non_virtio():
    with pytest.raises(ValueError):
        guest_install_script("/dev/sda")

def test_guest_script_steps_and_markers():
    s = guest_install_script("/dev/vdb")
    for token in ("sfdisk", "mkfs.vfat", "mkfs.ext4", "filesystem.squashfs", "cp -a /mnt/sq/.", "D3_PART_DONE", "D3_UNPACK_DONE"):
        assert token in s, token
    assert "/dev/vdb1" in s and "/dev/vdb2" in s

def test_chroot_identity_packages_grub():
    out = render_chroot("r-uuid", "EFI-UUID", apt_archive_lines())
    assert "__APT_LINES__" not in out
    for token in ("lifthrasir-lab", "useradd", "openssh-server", "qemu-guest-agent", "spice-vdagent", "grub-install", "update-grub", "systemd-machine-id-setup"):
        assert token in out, token

def test_render_chroot_refuses_empty_apt():
    with pytest.raises(ValueError):
        render_chroot("r", "e", "  ")
    assert "__APT_LINES__" in chroot_script("r", "e")

from lab.manual_install import chroot_static_script, full_install_script

def test_full_script_order_and_safety():
    s = full_install_script()
    order = [s.index(t) for t in ("sfdisk", "mkfs.ext4", "cp -a /mnt/sq/.", "fstab", "chroot", "D3_ALL_DONE")]
    assert order == sorted(order)
    assert "10.0.2.3" in s and "policy-rc.d" in s
    assert "32G" in s and "D3_NODEV" in s
    with pytest.raises(ValueError):
        chroot_static_script(" ")

def test_attempt2_kernel_and_serial_console():
    s = full_install_script()
    assert "linux-generic" in s
    assert "console=ttyS0" in s and "serial-getty@ttyS0" in s
    assert "ls -la /mnt/sq/boot" in s
