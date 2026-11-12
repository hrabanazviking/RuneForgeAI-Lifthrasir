# SPDX-License-Identifier: GPL-2.0-only
"""Activation Phase 1, slice D3: scripted manual install builders.

Road (3) adopted in keeper run 7 after Calamares unattended was
proven unusable in this lab (banked evidence, attempts 4-9). This
module is the PURE builder half: partition script, fstab, and the
in-guest install / chroot scripts as text, so they are unit-tested
before any VM boots. The lab user/hostname reuse calamares_config
values so D2 and D3 name the same disposable system. Honours the
LIF-0101 pin: same ISO, same packages.txt set; no Calamares claim.
"""
from __future__ import annotations
from lab.calamares_config import LAB_HOSTNAME, LAB_USER, PINNED_PACKAGES
EFI_MIB = 512

def sfdisk_script() -> str:
    """GPT: EFI system partition, then one ext4 root using the rest."""
    return ("label: gpt\n"
            f"size={EFI_MIB}M, type=U, name=EFI\n"
            "type=L, name=root\n")

def fstab_text(root_uuid: str, efi_uuid: str) -> str:
    if not root_uuid or not efi_uuid:
        raise ValueError("fstab needs both UUIDs (fail-closed)")
    return (f"UUID={root_uuid} / ext4 defaults 0 1\n"
            f"UUID={efi_uuid} /boot/efi vfat umask=0077 0 1\n")

def guest_install_script(dev: str) -> str:
    """Bash run INSIDE the live guest (as root via sudo) to install.

    Partitions dev, formats, unpacks the casper squashfs (the
    unpackfs equivalent), writes fstab/hostname. Chroot config is a
    separate script (chroot_script) copied into the target first.
    Each phase echoes a D3 marker the driver grades.
    """
    if not dev.startswith("/dev/vd"):
        raise ValueError(f"refusing non-virtio target: {dev}")
    lines = [
        "set -x",
        f"sfdisk --wipe always {dev} < /tmp/d3.sfdisk",
        "echo D3_PART_DONE$((1+1))",
        f"mkfs.vfat -F 32 -n EFI {dev}1",
        f"mkfs.ext4 -F -L root {dev}2",
        "echo D3_FMT_DONE$((1+1))",
        "mkdir -p /mnt/target",
        f"mount {dev}2 /mnt/target",
        "mkdir -p /mnt/target/boot/efi",
        f"mount {dev}1 /mnt/target/boot/efi",
        "mkdir -p /mnt/sq && mount -o loop,ro /cdrom/casper/filesystem.squashfs /mnt/sq",
        "cp -a /mnt/sq/. /mnt/target/",
        "echo D3_UNPACK_DONE$((1+1))",
        f"blkid -s UUID -o value {dev}2 > /tmp/d3-root.uuid",
        f"blkid -s UUID -o value {dev}1 > /tmp/d3-efi.uuid",
        "cp /tmp/d3-chroot.sh /mnt/target/tmp/d3-chroot.sh",
        "chmod +x /mnt/target/tmp/d3-chroot.sh",
        "for d in dev dev/pts proc sys run; do mount --rbind /$d /mnt/target/$d; done",
        "echo D3_PRECHROOT_DONE$((1+1))",
    ]
    return "\n".join(lines) + "\n"

def chroot_script(root_uuid: str, efi_uuid: str) -> str:
    """Bash run inside chroot /mnt/target: identity, packages, GRUB.

    apt road is decided by the D3 probe evidence at driver build
    time (ISO pool vs network archive); the driver appends the
    apt lines itself -- this script takes them as a marker line:
    the literal token __APT_LINES__ is replaced by the driver,
    and this builder refuses to emit a script still carrying it
    via render_chroot().
    """
    fstab = fstab_text(root_uuid, efi_uuid)
    lines = [
        "set -x",
        "export DEBIAN_FRONTEND=noninteractive",
        f"printf '%s' '{fstab}' > /etc/fstab",
        f"echo {LAB_HOSTNAME} > /etc/hostname",
        "printf '127.0.0.1 localhost\\n127.0.1.1 " + LAB_HOSTNAME + "\\n' > /etc/hosts",
        "echo D3_FSTAB_DONE$((1+1))",
        f"id {LAB_USER} >/dev/null 2>&1 || useradd -m -s /bin/bash -G sudo,adm {LAB_USER}",
        f"echo '{LAB_USER}:lifthrasir-lab' | chpasswd",
        "rm -f /etc/machine-id && systemd-machine-id-setup",
        "locale-gen en_US.UTF-8 || true",
        "echo D3_IDENT_DONE$((1+1))",
        "__APT_LINES__",
        "echo D3_APT_DONE$((1+1))",
        "systemctl enable ssh qemu-guest-agent || true",
        "echo 'GRUB_CMDLINE_LINUX_DEFAULT=\"console=tty0 console=ttyS0,115200n8\"' >> /etc/default/grub",
        "systemctl enable serial-getty@ttyS0 || true",
        "update-initramfs -u -k all",
        "grub-install --target=x86_64-efi --efi-directory=/boot/efi --bootloader-id=Kubuntu --recheck",
        "update-grub",
        "echo D3_GRUB_DONE$((1+1))",
    ]
    return "\n".join(lines) + "\n"

def render_chroot(root_uuid: str, efi_uuid: str, apt_lines: str) -> str:
    if not apt_lines.strip():
        raise ValueError("apt road is empty (fail-closed)")
    out = chroot_script(root_uuid, efi_uuid).replace("__APT_LINES__", apt_lines)
    if "__APT_LINES__" in out:
        raise ValueError("unrendered chroot script")
    return out

def apt_archive_lines() -> str:
    pkgs = " ".join(PINNED_PACKAGES)
    return f"apt-get update\napt-get install -y {pkgs}"

def chroot_static_script(apt_lines: str) -> str:
    """Chroot half with NO host-side values: fstab is written from
    the live side (UUIDs known only after mkfs), so this script is
    fully static and can ride the config ISO."""
    if not apt_lines.strip():
        raise ValueError("apt road is empty (fail-closed)")
    lines = [
        "set -x", "export DEBIAN_FRONTEND=noninteractive",
        f"id {LAB_USER} >/dev/null 2>&1 || useradd -m -s /bin/bash -G sudo,adm {LAB_USER}",
        f"echo '{LAB_USER}:lifthrasir-lab' | chpasswd",
        "rm -f /etc/machine-id && systemd-machine-id-setup",
        "locale-gen en_US.UTF-8 || true",
        "echo D3_IDENT_DONE$((1+1))", apt_lines, "echo D3_APT_DONE$((1+1))",
        "systemctl enable ssh qemu-guest-agent || true",
        "echo 'GRUB_CMDLINE_LINUX_DEFAULT=\"console=tty0 console=ttyS0,115200n8\"' >> /etc/default/grub",
        "systemctl enable serial-getty@ttyS0 || true",
        "update-initramfs -u -k all",
        "grub-install --target=x86_64-efi --efi-directory=/boot/efi --bootloader-id=Kubuntu --recheck",
        "update-grub", "echo D3_GRUB_DONE$((1+1))"]
    return "\n".join(lines) + "\n"

def apt_lines_with_dns() -> str:
    """Archive apt road for the chroot: QEMU user-net DNS (10.0.2.3,
    probe proved NET_OK), policy-rc.d guard, resolv.conf restored
    to the systemd-resolved symlink at the end."""
    pkgs = " ".join(PINNED_PACKAGES)
    return ("echo nameserver 10.0.2.3 > /etc/resolv.conf\n"
            "printf '#!/bin/sh\\nexit 101\\n' > /usr/sbin/policy-rc.d; chmod +x /usr/sbin/policy-rc.d\n"
            f"apt-get update && apt-get install -y {pkgs}\napt-get install -y linux-generic\n"
            "rm -f /usr/sbin/policy-rc.d\n"
            "ln -sf /run/systemd/resolve/stub-resolv.conf /etc/resolv.conf")

def full_install_script() -> str:
    """ONE script run as root in the live guest (rides config ISO).

    Target auto-detected INSIDE the guest as the 32G virtio disk
    (enumeration shifts with the config disk attached -- D2 lesson:
    config took vda, target was vdb; probe alone saw vda). Fails
    closed in-guest when no 32G disk or more than one is found.
    """
    chroot = chroot_static_script(apt_lines_with_dns())
    lines = [
        "#!/bin/bash", "set -x",
        "DEV=$(lsblk -dn -o NAME,SIZE | awk '$2==\"32G\"{print $1}')",
        "[ $(echo $DEV | wc -w) -eq 1 ] || { echo D3_NODEV; exit 3; }",
        "DEV=/dev/$DEV; echo TARGET_IS $DEV",
        "sfdisk --wipe always $DEV <<'SFDEOF'", sfdisk_script().rstrip(), "SFDEOF",
        "echo D3_PART_DONE$((1+1))",
        "mkfs.vfat -F 32 -n EFI ${DEV}1", "mkfs.ext4 -F -L root ${DEV}2",
        "echo D3_FMT_DONE$((1+1))",
        "mkdir -p /mnt/target", "mount ${DEV}2 /mnt/target",
        "mkdir -p /mnt/target/boot/efi", "mount ${DEV}1 /mnt/target/boot/efi",
        "mkdir -p /mnt/sq && mount -o loop,ro /cdrom/casper/filesystem.squashfs /mnt/sq",
        "cp -a /mnt/sq/. /mnt/target/", "sync", "ls -la /mnt/sq/boot /mnt/target/boot", "echo D3_UNPACK_DONE$((1+1))",
        "RU=$(blkid -s UUID -o value ${DEV}2); EU=$(blkid -s UUID -o value ${DEV}1)",
        "printf 'UUID=%s / ext4 defaults 0 1\\nUUID=%s /boot/efi vfat umask=0077 0 1\\n' $RU $EU > /mnt/target/etc/fstab",
        f"echo {LAB_HOSTNAME} > /mnt/target/etc/hostname",
        f"printf '127.0.0.1 localhost\\n127.0.1.1 {LAB_HOSTNAME}\\n' > /mnt/target/etc/hosts",
        "echo D3_FILES_DONE$((1+1))",
        "cat > /mnt/target/tmp/d3-chroot.sh <<'CHREOF'", chroot.rstrip(), "CHREOF",
        "chmod +x /mnt/target/tmp/d3-chroot.sh",
        "for d in dev dev/pts proc sys run; do mount --rbind /$d /mnt/target/$d; mount --make-rslave /mnt/target/$d || true; done",
        "chroot /mnt/target /bin/bash /tmp/d3-chroot.sh",
        "echo D3_CHROOT_DONE$((1+1))", "echo D3_ALL_DONE$((1+1))"]
    return "\n".join(lines) + "\n"
