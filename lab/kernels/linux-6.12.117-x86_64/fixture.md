# LIF-0901 kernel build fixture - Linux 6.12.117, x86-64

Machine-readable pin: `fixture.json` beside this file, validated by
`lab/kernel_fixtures.py` (tests: `tests/test_kernel_fixtures.py`).

- Kernel: Linux 6.12.117 (longterm series 6.12, per kernel.org
  releases.json, retrieved 2026-11-12)
- Tarball: linux-6.12.117.tar.xz (148959092 bytes, HEAD-checked only -
  NOT downloaded in this slice)
- Origin: https://cdn.kernel.org/pub/linux/kernel/v6.x/linux-6.12.117.tar.xz
- SHA-256: 74e99aa5e60e242e0a165fed8cb2ea0d054bf7a401f01861d403d75733456613
  - Status: retrieved-from-official-source - from kernel.org's
    PGP-signed https://cdn.kernel.org/pub/linux/kernel/v6.x/sha256sums.asc,
    retrieved 2026-11-12 from purpleraider.
- Git: https://git.kernel.org/pub/scm/linux/kernel/git/stable/linux.git
  tag v6.12.117, tag object 3edfb92cd34f439b2e2878c3544a1683871d29ee,
  commit d3417611a3b40b7f04a29e558cebac2bf69889d7 (official cgit tag
  page, retrieved 2026-11-12; git ls-remote exceeded the device
  invoke time limit, so the cgit page on the same official host is
  the recorded retrieval path).
- Config: base x86_64_defconfig + `config.fragment` (pinned by its
  own SHA-256 in fixture.json; required options enforced).
- Toolchain expectations (lab-observed on purpleraider 2026-11-12,
  not upstream minimums): gcc 15.3.0, GNU ld 2.47, GNU Make 4.4.1.
- Guest: qemu-system-x86_64, machine q35, disposable only.

## Safety and scope

Fixture definition + validation only. No kernel was downloaded or
built in this slice; nothing touches the host kernel, bootloader or
firmware (master roadmap section 0, invariants 2 and 5). Builds that
consume this fixture run only in disposable VMs (later P9 slices).

## Limitations

- The tarball bytes themselves were not hashed in this slice (HEAD
  only, to keep the slice light); the pin is verified against any
  bytes a future build hands to `verify_source_file`.
- Toolchain versions are the lab host's observed versions at pin
  time; a different build host must re-observe and re-pin.

## Undo

Delete this fixture directory and revert the LIF-0901 commit; no host
state was changed.
