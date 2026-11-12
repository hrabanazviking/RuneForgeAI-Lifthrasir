# Project Memory Map — Lifthrasir Campaign

Living map for the Lifthrasir development campaign on purpleraider.
Updated in the same session as any work it describes. (Seat:
purpleraider `~/lifthrasir-forge`.)

## The map

- **What:** Build Lífþrasir — "The Self-Evolving Linux System"
  (GitHub: hrabanazviking/RuneForgeAI-Lifthrasir): a Linux-native
  user-space supervisory system that detects failures, proposes
  evidence-based repairs, executes only authorized reversible actions,
  experiments in disposable VM labs, measures improvements against
  baselines, and prepares human-reviewed upstream patch dossiers.
  Mission (master roadmap): "Linux that heals, learns, evolves, and
  gives back."
- **Why here:** purpleraider (ROG Flow Z13) is itself the motivating
  case — a machine that fought its own Linux install for a full day
  (Wi-Fi power management, keyboard wake, speaker firmware gains,
  ethernet autosuspend traps, a broken stock PyTorch wheel). Volmarr's
  order, 2026-11-12: "this machine is the perfect reason why this
  project is needed and should be massively developed on her."
- **Design well (read before designing anything):** `README.md`
  (vision, pantheon, security boundary), `ROADMAP-TO-COMPLETION.md`
  (master: phases P0–P16, 10 hard safety invariants, reference
  architecture, evidence rules §5, security gates G0–G6, release
  cadence), `roadmap/01–05` (Books I–V), `roadmap/07` (the issue
  backlog = the campaign queue), `roadmap/08` (test matrix + release
  gates), `research/00–39` (40-document research library).
- **Architecture (reference, master roadmap §0):** CLI/UI/API + consent
  → Heimdall (sensor/correlator, read-only) → Mímir (local provenance +
  RAG evidence) → Replicater (bounded subagents: hypotheses / repro /
  patch / QA) → Thor (security triage) + Eir (repair proposals) →
  typed immutable plan → independent deterministic Policy Engine →
  resource-specific token → minimal Privileged Broker → live low-risk
  action OR QEMU/KVM lab → verification / rollback / journal →
  human-reviewed dossier → Upstream Forge (no auto-send).
- **First practical milestone (README):** in a disposable Kubuntu VM,
  detect a deliberately broken noncritical user service, explain the
  cause with evidence, propose an exact reversible fix, obtain consent,
  apply via the scoped policy broker, verify, and prove rollback —
  fully offline, and operable if the AI model stops running.
- **Completion criterion (master roadmap):** an independently audited,
  packaged, documented system meeting the §11 maturity definitions
  (MVP / 1.0 / 2.0 staged honestly; v1.0 is NOT blocked on the
  research-grade P13–P16 federation work).
- **Stack (master roadmap §4 reference decisions, ADR-confirmation is
  slice LIF-0002):** Rust core + broker; Python lab/AI adapters + test
  harness; CLI first, KDE/Qt later; SQLite + FTS, append-only
  hash-linked evidence; QEMU/KVM lab; systemd hardening + namespaces +
  Landlock + seccomp isolation. Initial target Kubuntu x86-64.
- **License:** GPL-2.0-only (repo LICENSE, 63 tracked files at base).
- **Repo baseline (2026-11-12):** main @
  e4239a098b1fde3985366a9eff4944825f8c62d9 — documentation-only tree:
  README + master roadmap + roadmap/ (Books I–V, bibliography,
  backlog, test matrix, index) + research/ (40 docs + index) + LICENSE
  + art. NO source code exists yet; the planned layout is master
  roadmap §3. Every roadmap statement is a proposal until a slice's
  evidence says otherwise.
- **Campaign seat:** purpleraider `~/lifthrasir-forge` (main) +
  `~/lifthrasir-team-01…09` (branches `yrsa/lifthrasir-team-NN`).
  9 teams × (1 lead + 6 Mythic Engineering sub-agents).
- **Keeper:** `lifthrasir-forge-keeper`, 10-minute, spec in
  `KEEPER.md` at the seat. Reports only at wave-of-9 completion,
  campaign completion, or a genuine blocker needing Volmarr's word.
- **Access:** Yrsa (@yrsafreydisdottir) is a collaborator on this repo;
  seat git operations run under the machine's own gh login
  (hrabanazviking). 2026-11-12: all pending invites accepted (3 new:
  skry-kg, skein-kg, bifrost); 0 pending; 50 collaborator repos total.

## Slice ledger

Statuses: queued · assigned · built (committed in team worktree,
awaiting banking) · banked. Evidence column names the artifact or
commit — never a bare claim. Queue order and titles per WAVE_PLAN.md.

| Slice | Phase | Status | Evidence / commit |
|---|---|---|---|
| — | — | Campaign stood up 2026-11-12 | seat stand-up commit on main (WAVE_PLAN + this map + KEEPER); ls-remote verified |
| LIF-0001 | P0 | banked | e72ad6a on main, ls-remote verified 2026-11-12; docs/CHARTER.md sha256 f24a22a5f9c3b8a16b9beccbeab70aee5bb92c8a36428d1e3b57f27d9da423d2, tests/test_charter.py sha256 9f1a50882083db7dbe20e5540ae354b5181a7ed7321a4494886914d55957eafa; suite 7 passed / 0 failed (pytest 9.1.1, Python 3.14.8, seat-verified in team worktree and at seat); negative control 1 failed / 6 passed as designed; undo = revert e72ad6a; README link proposed in team-01 CAMPAIGN_STATE.md, human to apply |
| LIF-0002 | P0 | banked | 9003355 on main, ls-remote verified 2026-11-12; docs/architecture/ADR-0002-architecture.md sha256 23b563ee0d8a1b7d91f56e95c15ef4b34a9d4e2ccd8209d8eb9dae58dc67bb85, tests/test_architecture_adr.py sha256 0f771686eaaf0c16deeae6a1374f2cdb6f059197bc8107d819545d660e023d86; suite at banking 19 passed / 0 failed (seat-verified); negative control 1 failed / 11 passed as designed; undo = revert 9003355 |
| LIF-0003 | P0 | banked | ad50632 on main (cherry-pick of team commit 37a9e37), ls-remote verified 2026-11-12; docs/RISK-MATRIX.md sha256 0bb82704975816ecf5e44f1929b6e2a196e2628d1fe28a88683e9967b3ea0f10, tests/test_risk_matrix.py sha256 ddb7ba713edb9d5030f1bee7902db7e34c7178e6a8c7e99def01b47ffd3335d6; suite at banking 31 passed / 0 failed (seat full suite); negative control 1 failed / 11 passed as designed; HUMAN REVIEW of the risk matrix remains PENDING (recorded in the doc, never claimed); undo = revert ad50632 |
| LIF-0004 | P0 | banked | 1c1ae13 on main, ls-remote verified 2026-11-12; docs/protocols v0.1 schemas (incident/hypothesis/plan/evidence, JSON Schema 2020-12, jsonschema 4.19.2) + SCHEMAS-v0.1.md + 4 valid / 8 invalid examples + tests/test_schemas_v01.py; suite at banking 72 passed / 0 failed (seat-verified); negative control PASS (severity-stripped incident rejected); honest limit recorded: schema checks identifier shape, not referenced-record existence (store/bus concern, LIF-0201/0301/0404); undo = revert 1c1ae13 |
| LIF-0005 | P0 | banked | d1ba145 on main, ls-remote verified 2026-11-12; docs/LICENSING.md + docs/CONTRIBUTING.md + docs/disclosures/SECURITY.md + dependencies/manifest.json (+schema) + tests/test_licensing_governance.py; suite at banking 79 passed / 0 failed (seat-verified); negative control PASS (license-less manifest entry rejected); limitation recorded: disclosure address is a human-supplied placeholder (repo states none), manifest SPDX values not yet machine-scanned; undo = revert d1ba145. P0 SET COMPLETE (0001-0005 banked) |
| LIF-0101 | P1 | assigned (team-06) | — |
| LIF-0102 | P1 | assigned (team-07) | — |
| LIF-0103 | P1 | assigned (team-08) | — |
| LIF-0104 | P1 | assigned (team-09) | — |
| LIF-0105 | P1 | built (team-01, awaiting banking) | commit 4b70e71 on yrsa/lifthrasir-team-01; lab/ci_runner.py + tests/test_ci_runner.py; suite 13 passed / 0 failed in team worktree; e2e trace lif-20261112T065755Z-2623f7a1743c; banking waits queue order + P0 gate |
| LIF-0201 | P2 | built (team-02, awaiting banking) | commit 10801b6 on yrsa/lifthrasir-team-02; src/lifthrasir/eventbus.py + tests/test_event_bus.py; suite 45 passed / 0 failed in team worktree; negative control PASS (wrong-version + untyped refused); banking waits queue order + P1 phase gate |
| LIF-0202 | P2 | built (team-03, awaiting banking) | commit 41ade76 on yrsa/lifthrasir-team-03; lab/systemd_collector.py + tests/test_systemd_collector.py + 6 fixtures; suite 41 passed / 0 failed in team worktree; negative control 3 failed / 7 passed as designed; fixture-based only, no live-system claim; banking waits queue order + P1 phase gate |
| LIF-0203 | P2 | built (team-04, awaiting banking) | commit b89dd48 on yrsa/lifthrasir-team-04; lab/proc_sensors.py + tests/test_proc_sensors.py + 14 fixtures; suite 84 passed / 0 failed in team worktree; negative control PASS (mutated PSI total fails exact-value test); banking waits queue order + P1 phase gate |
| LIF-0204 | P2 | queued | — |
| LIF-0205 | P2 | queued | — |
| LIF-0206 | P2 | queued | — |
| LIF-0301 | P3 | queued | — |
| LIF-0302 | P3 | queued | — |
| LIF-0303 | P3 | queued | — |
| LIF-0304 | P3 | queued | — |
| LIF-0305 | P3 | queued | — |
| LIF-0306 | P3 | queued | — |
| LIF-0401 | P4 | queued | — |
| LIF-0402 | P4 | queued | — |
| LIF-0403 | P4 | queued | — |
| LIF-0404 | P4 | queued | — |
| LIF-0405 | P4 | queued | — |
| LIF-0406 | P4 | queued | — |
| LIF-0407 | P4 | queued | — |
| LIF-0501 | P5 | queued | — |
| LIF-0502 | P5 | queued | — |
| LIF-0503 | P5 | queued | — |
| LIF-0504 | P5 | queued | — |
| LIF-0505 | P5 | queued | — |
| LIF-0506 | P5 | queued | — |
| LIF-0601 | P6 | queued | — |
| LIF-0602 | P6 | queued | — |
| LIF-0603 | P6 | queued | — |
| LIF-0701 | P7 | queued | — |
| LIF-0702 | P7 | queued | — |
| LIF-0703 | P7 | queued | — |
| LIF-0801 | P8 | queued | — |
| LIF-0802 | P8 | queued | — |
| LIF-0803 | P8 | queued | — |
| LIF-0901 | P9 | queued | — |
| LIF-0902 | P9 | queued | — |
| LIF-0903 | P9 | queued | — |
| LIF-0904 | P9 | queued | — |
| LIF-0905 | P9 | queued | — |
| LIF-1001 | P10 | queued | — |
| LIF-1002 | P10 | queued | — |
| LIF-1003 | P10 | queued | — |
| LIF-1101 | P11 | queued | — |
| LIF-1102 | P11 | queued | — |
| LIF-1103 | P11 | queued | — |
| LIF-1201 | P12 | queued | — |
| LIF-1202 | P12 | queued | — |
| LIF-1203 | P12 | queued | — |
| LIF-1301 | P13 | queued | — |
| LIF-1302 | P13 | queued | — |
| LIF-1401 | P14 | queued | — |
| LIF-1402 | P14 | queued | — |
| LIF-1501 | P15 | queued | — |
| LIF-1601 | P16 | queued | — |

## Lessons carried in (standing law for this campaign)

From the repo itself:
- Evidence is not authority; an agent's confidence grants nothing
  (README security boundary). Agents propose; the deterministic policy
  engine disposes; the broker executes only scoped, approved actions.
- Evidence-status honesty: never claim a rung of the ladder
  (idea → … → upstream-accepted) above what artifacts prove; "unknown
  or untested" is a status, not an embarrassment to hide.
- No issue closes because an agent says "done" (master roadmap §8);
  the backlog's own rule: work one bounded issue at a time, failing
  test first, independent tests, exact results attached, human review.
- Dangerous experiments (fuzzing, corruption, kernel crashes) live in
  disposable VMs or sacrificial hardware — never on the host that the
  campaign itself runs on.

From the sibling campaigns on this machine (Aesir forge discipline):
- Bank incrementally; verify the push MOVED the remote
  (`git ls-remote`), every time; never force-push; fetch + remote-diff
  before pushing.
- Trust only disk: every count from git or a test-runner log on
  purpleraider, never from memory or a worker's say-so.
- Per-worker worktrees, always; parallel writers never share a
  checkout.
- Spawn-staggering: muster 2–3 teams per keeper tick; a 429 stops
  mustering for that tick, never retry into a rate limit.
- Never leave a discovered bug unfixed — fix in scope or record it as
  the team's immediate next work.
