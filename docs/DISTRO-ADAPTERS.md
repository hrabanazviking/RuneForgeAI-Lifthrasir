# Distro Adapters and Supported Versions (LIF-1102)

SPDX-License-Identifier: GPL-2.0-only

Machine authority: `src/lifthrasir/distroadapters.py`. This document
mirrors that module; tests pin the table below to the module rows.
If this document and the module ever disagree, the module governs
and the disagreement is a bug.

## What an adapter is

An adapter is data plus pure rendering: package-manager argv
templates, package-concept translation (reusing the banked
LIF-0407 confinement profiles verbatim), critical units, protected
paths, and log sources for Fedora, Debian and openSUSE. Rendering
a command executes nothing. Mutating operations (install, remove,
metadata refresh) are rendered only as plans; executing any of
them requires policy ALLOW, human approval and the broker, under
master roadmap section 0. No adapter installs packages, mutates a
host, or probes a live distro in this slice.

## Supported-versions table (the authority)

No distro or version may be called supported unless this table
says `supported`. In table version 0.1 **no row is supported**:
the Fedora, Debian and openSUSE rows are documentary candidates
(from the LIF-0407 review, where they are labelled documented;
none was booted, installed or probed for this slice), and the
Ubuntu row is a host-observed reference with no LIF-1102 adapter.
A row moves to `supported` only with lab-verified adapter parity
evidence on that exact version (P11 graduation gate: adapter
parity with explicit unsupported behaviour). Unlisted versions
fail closed as `unlisted`; unlisted distros as
`unsupported-distro`.

| Distro | Version | Kind | Evidence | Status |
|---|---|---|---|---|
| fedora | 41 (Fedora 41) | point | documented | unverified |
| fedora | 42 (Fedora 42) | point | documented | unverified |
| debian | 12 (Debian 12 (bookworm)) | point | documented | unverified |
| debian | 13 (Debian 13 (trixie)) | point | documented | unverified |
| opensuse | 15.6 (openSUSE Leap 15.6) | point | documented | unverified |
| opensuse | tumbleweed (openSUSE Tumbleweed) | rolling | documented | unverified |
| ubuntu | 26.10 (Ubuntu 26.10 (reference host)) | point | host-observed | unverified |

## Per-distro notes

- Fedora: dnf/rpm, SELinux enforcing by default; the message-bus
  unit is `dbus-broker.service`, not `dbus.service` (LIF-0407).
- Debian: apt/dpkg, AppArmor with a smaller enforcing set than
  Ubuntu; non-systemd installs exist, so init is probed (future
  LIF-1101 contract), never assumed.
- openSUSE: zypper/rpm; the LSM is conditional (AppArmor
  traditional, SELinux offered), so neither is hard-coded.
  Transactional variants (MicroOS) are out of scope.

## Interface assumption (LIF-1101, unbanked)

LIF-1101 (capability probes and adapter contracts) is being built
in parallel and is NOT depended on. This slice assumes only that a
future probe supplies os-release text and a distro id -- the shape
`identify()` already consumes from banked LIF-0407 helpers. If
LIF-1101 banks a different contract, this module reconciles to it
at banking/integration; no unbanked code is imported here.

## Limitations and undo

Evidence rung: lab-verified (fixture level, purpleraider Ubuntu
26.10 host) for the rendering and table logic only. Distro support
itself remains unverified for every row. Undo: revert the slice
commit -- code, document, fixture and tests only; no system state
was changed and no package was installed.
