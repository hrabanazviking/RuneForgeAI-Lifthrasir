# Licensing Policy - Lifthrasir (LIF-0005)

Project: Lifthrasir - The Self-Evolving Linux System.
Slice: LIF-0005, Phase P0. Sources: repo LICENSE file, research/30
(licensing and dependencies), ROADMAP-TO-COMPLETION.md header and
section 5, docs/CHARTER.md. This policy is project governance, not
legal advice.

## Project license: GPL-2.0-only

- All project code in this repository is licensed GPL-2.0-only.
  The canonical license text is the repo LICENSE file (GNU General
  Public License, version 2, June 1991). No later-version option is
  granted by this project: the SPDX identifier is GPL-2.0-only.
- New source files SHOULD carry an SPDX-License-Identifier header
  naming GPL-2.0-only, following the kernel SPDX convention cited
  in research/30.
- Documentation and artwork are not automatically covered by the
  code license. Each such asset needs its own explicit license or
  permission note before redistribution in packages (research/30
  flags the Viking Tux artwork as needing owner and permission
  documentation). Until that note exists, treat artwork licensing
  as unverified, not as free to redistribute.

## Per-component SPDX review rule

- Every component, file set, or vendored item carries a reviewed
  SPDX identifier. Review means: a human or a recorded automation
  check confirms the identifier matches the component's own license
  text or upstream declaration. An assumed identifier is not a
  reviewed identifier.
- The dependency manifest (dependencies/manifest.json) records the
  SPDX identifier or license string for every dependency; an entry
  without a license field fails repo automation (LIF-0005 tests).
- Mixed-license components, if ever accepted, live in a LICENSES/
  directory with one file per license, per the research/30 action
  list, and are named in THIRD_PARTY_NOTICES when shipped.
- Kernel-facing code follows Linux kernel licensing rules:
  GPL-2.0-only with the kernel's per-file exceptions and dual-
  licensed components handled case by case. Never assume a license
  marketed as open source is compatible with GPL-2.0-only kernel
  code (research/30).

## Third-party material

- Third-party code, data, model weights, firmware, and artwork are
  handled individually: name, version or pinned commit, upstream
  source, license SPDX, and provenance are recorded in the
  dependency manifest before use. Material without traceable
  provenance and license is rejected.
- Preserve all third-party copyright and license notices when
  redistributing. Do not bundle proprietary or license-incompatible
  kernel components. Optional connectors with different terms are
  installed only under documented user control (research/30).
- Open weights does not mean open source: model licenses may impose
  use, attribution, or commercial restrictions. Record the actual
  terms; warn on an unverified license rather than silently
  downloading (research/30).
- Copied code without traceable provenance is refused. Patches
  derived from external proprietary code follow a clean-room policy
  (research/30); plagiarism is refused.

## Distribution obligations

- When binaries are distributed, the corresponding GPL-covered
  source, build instructions, and license texts travel with them,
  per the GPL-2.0 terms in LICENSE.
- Before significant binary distribution, produce an SBOM in a
  standard format generated from the dependency manifest
  (research/30).

## Issue record - LIF-0005 (licensing part)

    id: LIF-0005
    phase: P0
    goal: Establish licensing policy, contributor guide, disclosure channel and dependency manifest.
    dependencies: []
    risk_tier: L0
    scope: Governance docs plus structured dependency manifest plus repo automation tests. No code behaviour change; no README.md modification.
    test_fixture: tests/test_licensing_governance.py run in this checkout.
    expected_evidence: Full pytest log in hidden_files/ with all tests passing.
    negative_control: A manifest copy with a license-less entry must fail validation; logged in hidden_files/.
    recovery_or_undo: Revert the slice commit (git revert) - docs, manifest and tests only.
