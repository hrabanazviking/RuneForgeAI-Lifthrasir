# Contributor Guide - Lifthrasir (LIF-0005)

Project: Lifthrasir - The Self-Evolving Linux System.
Slice: LIF-0005, Phase P0. Sources: ROADMAP-TO-COMPLETION.md
sections 0, 5 and 6, research/21 (upstream contributions),
research/30 (licensing and dependencies), docs/CHARTER.md.

## Who may contribute, and how

- Contributions are welcome from humans. Work happens in small,
  reviewable slices: one issue or backlog slice (roadmap/07) per
  change, with the issue-template fields filled in - goal,
  dependencies, risk tier, scope, test fixture, expected evidence,
  negative control, and recovery or undo.
- Fork or branch, make the change, run the full test suite
  (python3 -m pytest tests/ -v for Python parts; cargo test for
  Rust parts when they exist), and open the change for human
  review. No change merges on its author's word alone: the
  banking seat independently checks test logs before banking.
- Code license is GPL-2.0-only (see docs/LICENSING.md). New source
  files should carry an SPDX-License-Identifier header. Contribute
  only material you have the right to contribute, with traceable
  provenance and license (research/30).

## DCO and upstream submission: humans only

- Hard rule (safety invariant 7): only humans sign DCO
  Signed-off-by and only humans submit patches upstream. Agents
  never sign DCO Signed-off-by tags and agents never send patches
  upstream. An AI agent may help draft, test, and assemble a patch
  dossier; a human reviews it, accepts responsibility, signs, and
  submits. LIF-1402 is the standing human DCO review checkpoint.
- For this repository itself, a human contributor's Signed-off-by
  line, when present, is that human's own Developer Certificate of
  Origin affirmation. Never add a Signed-off-by line for another
  person, and never add one on behalf of an agent.

## Evidence expectations (master roadmap section 5)

Every non-trivial change ships an evidence pack:

1. A reproducer or fixture demonstrating the baseline behaviour.
2. A differential run: same baseline, before and after the change.
3. A negative control that rules out a trivial alternate
   explanation (for governance slices: a deliberately broken
   fixture that the automation must reject).
4. Exact tool versions and full test logs (counts read from logs).
5. Artifact hashes (sha256) for delivered files.
6. Named scope, platform, comparison baseline, limitations, and a
   safe undo procedure (normally: revert the slice commit).
7. Evidence-status honesty: claims move only along the ladder
   idea, hypothesis, reproducer, lab-verified, cross-platform-
   verified, human-reviewed, deployed-with-monitoring, upstream-
   submitted, upstream-accepted. Unknown or untested is NOT
   verified. Never state a rung the artifacts do not prove.

## Safety invariants every contributor honours

From master roadmap section 0 - these bind every slice:

1. No ambient root: no LLM, subagent, or tool gets ambient root or
   an unrestricted privileged shell.
2. No autonomous mutation of bootloader, kernel image, firmware,
   partition table, encryption, home files, package trust roots,
   SSH access, or critical firewall or network state.
3. Experiments only in disposable VMs or designated sacrificial
   hardware - never fuzzing or corruption tests on a working
   machine.
4. Every privileged action is schema-validated, authenticated,
   resource-scoped, logged, time-bounded, and policy-checked.
5. User files and private logs stay local by default; federation
   is opt-in with a scrubbed-payload preview.
6. An emergency stop must work without models, network, or
   inference acceleration.
7. Never leave a discovered bug unfixed: fix it inside the
   slice's scope, or record it as the immediate next work.
8. Never modify README.md as part of a slice unless a human
   maintainer explicitly directs that edit; propose README changes
   in the slice record instead.

## Reporting security issues

Do not open a public issue for a suspected vulnerability. Follow
the disclosure process in docs/disclosures/SECURITY.md.
