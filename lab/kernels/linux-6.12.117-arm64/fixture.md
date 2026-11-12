# LIF-0901 kernel build fixture - Linux 6.12.117, arm64

Machine-readable pin: `fixture.json` beside this file, validated by
`lab/kernel_fixtures.py` (tests: `tests/test_kernel_fixtures.py`).

- Kernel: Linux 6.12.117 (longterm series 6.12; the kernel source
  tarball is architecture-neutral, so this fixture shares the x86-64
  fixture's source pin)
- Tarball: linux-6.12.117.tar.xz (148959092 bytes, HEAD-checked only -
  NOT downloaded in this slice)
- Origin: https://cdn.kernel.org/pub/linux/kernel/v6.x/linux-6.12.117.tar.xz
- SHA-256: 74e99aa5e60e242e0a165fed8cb2ea0d054bf7a401f01861d403d75733456613
  - Status: retrieved-from-official-source - from kernel.org's
    PGP-signed https://cdn.kernel.org/pub/linux/kernel/v6.x/sha256sums.asc,
    retrieved 2026-11-12.
- Git: https://git.kernel.org/pub/scm/linux/kernel/git/stable/linux.git
  tag v6.12.117, tag object 3edfb92cd34f439b2e2878c3544a1683871d29ee,
  commit d3417611a3b40b7f04a29e558cebac2bf69889d7 (official cgit tag
  page, retrieved 2026-11-12).
- Config: base defconfig (arm64) + `config.fragment` (pinned by its
  own SHA-256 in fixture.json; required options enforced).
- Toolchain expectations: GNU Make 4.4.1 lab-observed; the arm64
  cross-compiler (aarch64-linux-gnu-gcc) is UNVERIFIED - no version
  claimed, because no aarch64 cross-compiler is installed on the lab
  host (checked 2026-11-12). `assert_buildable` therefore refuses
  this fixture until a cross toolchain is installed and observed.
- Guest: qemu-system-aarch64, machine virt, disposable only.

## Safety and scope

Fixture definition + validation only. No kernel was downloaded,
cross-compiled or built in this slice; nothing touches the host
kernel, bootloader or firmware (roadmap section 0, invariants 2, 5).

## Limitations

- Not buildable as shipped (UNVERIFIED cross-compiler, by design).
- No arm64 guest was booted; emulator/machine are expectations for
  later P9 slices, not observed runs.

## Undo

Delete this fixture directory and revert the LIF-0901 commit; no host
state was changed.
