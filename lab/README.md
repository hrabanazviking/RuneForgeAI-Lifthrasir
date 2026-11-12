# lab/ - VM laboratory (recipes, not images)

Per the master roadmap (ROADMAP-TO-COMPLETION.md SS3), lab/ holds VM
image BUILD RECIPES, not large images: reproducible recipes and
checksums only. No VM image, ISO, or other large binary is ever
committed to this repository.

Layout:

- images/<image-name>/recipe.json - the machine-readable pin (distro,
  version, architecture, ISO filename, official origin URL, pinned
  SHA-256 and where/when that checksum was retrieved from).
- images/<image-name>/recipe.md - the human-readable recipe: purpose,
  verification steps, determinism proof scope, limitations, undo.
- images/<image-name>/packages.txt - the pinned lab package set input.
- images/verify_iso.py - fail-closed verifier: given a recipe and a
  downloaded file, it checks the origin is the official host and the
  file's SHA-256 equals the pinned checksum before any use.
- images/build_manifest.py - deterministic derived-artifact generator:
  emits the build manifest for a recipe directory. Its output depends
  only on recipe.json + packages.txt (sorted, no timestamps), so two
  runs from clean state are byte-identical.

First recipe: LIF-0101, Kubuntu 24.04.5 LTS desktop, amd64 (the
project's initial engineering target: Kubuntu x86-64, README and
master roadmap SS1/P1).
