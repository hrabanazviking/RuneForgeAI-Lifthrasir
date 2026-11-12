# Release Pipeline - Lifthrasir (LIF-1201)

Slice: LIF-1201, Phase P12, queue #56 - "Package generation and
signed release pipeline". Status: fixture / record level only.
This pipeline is not a release: nothing here generates a real
package for publication, signs with a real key, or publishes or
uploads anything anywhere. Banking gate: P0-P11 - this slice was
built ahead of that gate while LIF-1102 / LIF-1103 were still
building; banking waits for the keeper.

## Package generation (plan level)

- Input is a recording: package name, MAJOR.MINOR.PATCH version,
  one plan format (`deb-plan`, `rpm-plan`, `tarball-plan` - plan
  formats only, no archive is written), a recorded source commit,
  a recorded build epoch (never wall time), the project license
  `GPL-2.0-only`, and recorded files (relative path, sha256, size,
  SPDX identifier, reviewed flag, kind, license note).
- Output is a canonical manifest (files sorted by path) and its
  sha256 digest. Rebuilding, or building from a differently
  ordered recording, yields the identical digest - the
  reproducibility differential pinned by the tests.
- Refusals: unsafe or duplicate paths, malformed version or
  format, an unreviewed SPDX identifier (LIF-0005: an assumed
  identifier is not a reviewed identifier), and artwork without
  its own license / permission note (LIF-0005 treats artwork
  licensing as unverified until noted).

## Release gates

A candidate is evaluated against: `evidence_pack_complete`
(master roadmap section 5 pack: reproducer, differential,
negative control, tool versions, artifact hashes, limitations,
undo), `full_suite_green`, `licensing_reviewed`,
`negative_control_recorded`, `cross_distro_gate_recorded`
(roadmap/08 G9, recorded honestly including blocked / not-run),
`security_review_recorded` (roadmap/08 G10, same honesty rule),
and `human_review_recorded` (pending is an honest, recorded
state). The only passing verdict is
`fixture-ready-for-human-review`; the other verdict is `blocked`.
There is no released or published verdict in this module.

## Simulated signing

- Signing is simulated with fixture keys only: the key id must
  match `fixture-<name>`, the record must carry `simulated: true`,
  and the signature is an HMAC-SHA256 over the manifest digest
  serialised under the label `SIMULATED-FIXTURE-SIGNATURE` with
  algorithm `fixture-hmac-sha256-simulation`. Tampering with the
  manifest or the signature fails verification.
- A blocked candidate receives no signature at all.
- Real key ids, key file paths, publish / upload / release
  actions, and any claimed released state are refused by name.
  This simulation proves nothing about any real key and must
  never be presented as a signed release.

## Limitations and undo

- Fixture/record level only (evidence ladder: reproducer +
  lab-verified at fixture scope, this platform). No real package
  was built, no distro package manager ran, G9 / G10 are recorded
  as not-run in the fixture, and human review is pending.
- Undo: revert the single LIF-1201 commit; no host state touched.
