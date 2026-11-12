# Pinned Kubuntu image recipe - LIF-0101

## Purpose

Phase P1 (VM laboratory) needs a reproducible, disposable test
environment. This slice pins the base image recipe: the exact Kubuntu
ISO, its official origin, and its pinned SHA-256 checksum, plus the
verification step that must pass before any lab use of a downloaded
ISO. This is a RECIPE (master roadmap SS3: lab/ holds build recipes,
not large images). No ISO was downloaded and no VM image was built in
this slice; see Limitations.

## The pin

- Distro / version: Kubuntu 24.04.5 LTS (release series 24.04 LTS)
- Architecture: amd64 (x86-64, the project's initial target)
- Variant: desktop
- ISO filename: kubuntu-24.04.5-desktop-amd64.iso
- Official origin URL:
  https://cdimage.ubuntu.com/kubuntu/releases/24.04.5/release/kubuntu-24.04.5-desktop-amd64.iso
- Official checksums URL:
  https://cdimage.ubuntu.com/kubuntu/releases/24.04.5/release/SHA256SUMS
- Pinned SHA-256:
  ae59e59c54337bcd8f8e60825b4a3f58797121ae0e89855524ffc92b8075c1d6
- Checksum status: retrieved-from-official-source on 2026-11-12 from
  the checksums URL above (purpleraider, curl), and cross-checked
  against the identical entry in
  https://cdimage.ubuntu.com/kubuntu/releases/24.04/release/SHA256SUMS
  Both official listings agree byte-for-byte. The ISO origin URL was
  confirmed live with a headers-only request (HTTP 200,
  Content-Length 5457694720, Content-Type application/x-iso9660-image)
  on the same date; the ISO itself was NOT downloaded (5.46 GB; the
  recipe + verification road does not depend on it).
- Machine-readable pin: recipe.json beside this file.
- Lab package set input: packages.txt beside this file.

## Verification (must pass before any use of a downloaded ISO)

Run, from the repository root:

    python3 lab/images/verify_iso.py lab/images/kubuntu-24.04.5-amd64/recipe.json /path/to/kubuntu-24.04.5-desktop-amd64.iso

The verifier fails closed (nonzero exit) when: the recipe is malformed
or missing a pin, the origin host is not cdimage.ubuntu.com, the file
is missing, or the file's SHA-256 differs from the pinned checksum.
Only an OK result authorizes lab use of that file.

## Derived artifact and determinism (the slice Done criterion)

Backlog Done criterion: identical fixtures from two clean builds. The
derived artifact this recipe deterministically produces here is the
build manifest:

    python3 lab/images/build_manifest.py lab/images/kubuntu-24.04.5-amd64

The manifest depends only on recipe.json + packages.txt (sorted keys
and packages, fixed line endings, no timestamps, no host data). The
slice test suite proves two runs from clean state are byte-identical
and hash-equal; the run hashes are recorded in the team's
CAMPAIGN_STATE.md evidence summary. A full bootable-image build from
this ISO is future lab work (LIF-0102 onwards), not claimed here.

## Issue record - LIF-0101

    id: LIF-0101
    phase: P1
    goal: Build pinned Kubuntu image recipe and verify origin and checksum.
    dependencies: [P0 banked]
    risk_tier: L0 (documentation, recipe and unprivileged scripts only)
    scope: lab/ recipe + verifier + manifest generator + tests. No ISO
      download, no VM image, no system change, no README.md change.
    test_fixture: tests/test_lab_image_recipe.py with small fixture
      files created in pytest tmp dirs (never a real ISO).
    expected_evidence: pytest log in hidden_files/ (full suite green),
      determinism hashes, negative-control log, artifact sha256sums.
    negative_control: the verifier rejects a fixture file whose SHA-256
      does not match the recipe pin, and rejects an unofficial origin;
      both are exercised by tests and a logged manual run.
    recovery_or_undo: Revert the slice commit (git revert) - recipe,
      scripts and tests only, no system state changed.

## Limitations

- The ISO itself was not downloaded and no bootable image was built;
  checksum verification against a real downloaded ISO remains future
  lab work (it is proven here against small fixture files whose hashes
  are computed in-test, plus the negative control).
- The pinned checksum is a single-source-class pin (Ubuntu cdimage,
  cross-checked in two official listings on the same host); GPG
  signature verification of SHA256SUMS is not performed by
  verify_iso.py in this slice.
- Package versions inside the guest are resolved by apt against the
  pinned 24.04 LTS series at lab build time; this recipe pins the ISO,
  not every guest package version.
- Evidence status: reproducer (fixture-level, lab-verified on
  purpleraider for the recipe, verifier and manifest determinism).
  No claim is made about a built or booted image.
