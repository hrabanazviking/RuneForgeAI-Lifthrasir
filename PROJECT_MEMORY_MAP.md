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
| LIF-0101 | P1 | banked | 4a5cb93 on main, ls-remote verified 2026-11-12; lab/images/kubuntu-24.04.5-amd64 recipe (Kubuntu 24.04.5 LTS amd64, origin cdimage.ubuntu.com, SHA-256 ae59e59c54337bcd8f8e60825b4a3f58797121ae0e89855524ffc92b8075c1d6 RETRIEVED from the official SHA256SUMS and cross-checked) + verify_iso.py fail-closed + deterministic build manifest (two clean builds byte-identical 0b4f1b0f...); suite at banking 87 passed / 0 failed (seat-verified); negative control PASS (wrong-checksum fixture rejected); limitations: ISO NOT downloaded, no image built/booted, GPG check of SHA256SUMS not done; undo = revert 4a5cb93 |
| LIF-0102 | P1 | banked | e5a6a57 on main (cherry-pick of team commit 68bee10), ls-remote verified 2026-11-12; lab/vm_workflow.py QEMU/KVM create/start/reset/delete over a CommandRunner interface with disposable-only + lab-path + checksum refusals; suite at banking 94 passed / 0 failed (seat full suite); negative control PASS (disposable-check mutant fails the refusal test); host facts: /dev/kvm + qemu-img 11.0.3 present, qemu-system-x86_64 + virsh absent — proof at fake-runner level, NO real guest boot claimed; undo = revert e5a6a57 |
| LIF-0103 | P1 | banked | 88a556e on main, ls-remote verified 2026-11-12; lab/guest_boundary.py + 2 restricted guest network profiles + 14 tests; suite at banking 108 passed / 0 failed (seat full suite); negative controls in-test; limitation: data/profile level only, no live guest network claimed; undo = revert 88a556e |
| LIF-0104 | P1 | banked | 6697b6e on main (cherry-pick of team commit 039df72), ls-remote verified 2026-11-12; ten synthetic fault fixtures F01-F10 + independent pass/fail oracle; suite at banking 113 passed / 0 failed (seat full suite); negative control PASS; limitation: data-level only; undo = revert 6697b6e |
| LIF-0105 | P1 | banked | 89ff29b on main (cherry-pick of team commit 4b70e71; lab/__init__.py add/add convergence resolved keeping the banked LIF-0102 version, docstring-only difference), ls-remote verified 2026-11-12; lab/ci_runner.py + tests/test_ci_runner.py; suite at banking 119 passed / 0 failed (seat full suite); undo = revert 89ff29b. P1 SET COMPLETE; WAVE 1 COMPLETE (9 of 64 banked) |
| LIF-0201 | P2 | banked | 62dfd90 on main (cherry-pick of team commit 10801b6), ls-remote verified 2026-11-12; src/lifthrasir/eventbus.py typed event bus + src/lifthrasir/__init__.py package exports for the event bus + tests/test_event_bus.py; suite at banking 133 passed / 0 failed (seat full suite); undo = revert 62dfd90 |
| LIF-0202 | P2 | banked | 86765b1 on main (cherry-pick of team commit 41ade76; lab/__init__.py convergence kept the banked version), ls-remote verified 2026-11-12; lab/systemd_collector.py + tests/test_systemd_collector.py + 6 fixtures; suite at banking 143 passed / 0 failed (seat full suite); undo = revert 86765b1 |
| LIF-0203 | P2 | banked | e48c8ac on main (cherry-pick of team commit b89dd48; lab/__init__.py convergence kept the banked version), ls-remote verified 2026-11-12; lab/proc_sensors.py + tests/test_proc_sensors.py + 14 fixtures; suite at banking 155 passed / 0 failed (seat full suite); undo = revert e48c8ac |
| LIF-0204 | P2 | banked | cc987c1 on main (cherry-pick of team commit 2312b91), ls-remote verified 2026-11-12; lab/disk_network_collector.py + tests + 7 fixtures; suite at banking 165 passed / 0 failed (seat full suite); undo = revert cc987c1 |
| LIF-0205 | P2 | banked | d351358 on main (cherry-pick of team commit 5813a88), ls-remote verified 2026-11-12; ui/heimdall_cli.py read-only CLI + tests; suite at banking 172 passed / 0 failed (seat full suite); undo = revert d351358 |
| LIF-0206 | P2 | banked | 5f2b346 on main (cherry-pick of team commit 424840a; lab/__init__.py convergence kept the banked version), ls-remote verified 2026-11-12; lab/baseline_report.py + IDLE-BASELINE.md; suite at banking 185 passed / 0 failed (seat full suite); undo = revert 5f2b346. P2 SET COMPLETE |
| LIF-0301 | P3 | banked | d80dad1 on main (cherry-pick of team commit 3707766; src/lifthrasir/__init__.py UNIONED at seat: eventbus + eventstore exports; top-level SchemaVersionError is the eventbus class, the eventstore class remains at lifthrasir.eventstore.SchemaVersionError; union file sha256 3202e25b87953329a53f03bf0286794956f87561ed376bb41a64d23b6344eb8c), ls-remote verified 2026-11-12; local SQLite event store + migration tests; suite at banking 199 passed / 0 failed (seat full suite); undo = revert d80dad1 |
| LIF-0302 | P3 | banked | a19e803 on main (cherry-pick of team commit d8875c7; seat src/lifthrasir/__init__.py union extended with provenance exports, union file sha256 b50aec05d4ded855ef5999f13d7c2496c032b1f644e2263065f2604f6b6b0e29), ls-remote verified 2026-11-12; source identity, retrieval date and hash for referenced documentation; suite at banking 211 passed / 0 failed (seat full suite); undo = revert a19e803 |
| LIF-0303 | P3 | banked | e02514e on main (cherry-pick of team commit 01ec5c9), ls-remote verified 2026-11-12; exact text search; optional embeddings behind a feature flag; suite at banking 226 passed / 0 failed (seat full suite); undo = revert e02514e |
| LIF-0304 | P3 | banked | c089510 on main (FF/cherry-pick of team-01 commit 98ce3a7), ls-remote verified 2026-11-12; privacy.py redactor, local retention, export preview; suite at banking 250 passed / 0 failed (seat full suite); negative control 4 failed as designed; regex-scope limitations recorded by team; undo = revert c089510 |
| LIF-0305 | P3 | banked | 42e2b23 on main (cherry-pick of team-02 commit d9bc3d1; its in-branch __init__ hypotheses union applied cleanly), ls-remote verified 2026-11-12; causal hypothesis records incl. failed hypotheses and counterevidence; suite at banking 270 passed / 0 failed (seat full suite); undo = revert 42e2b23 |
| LIF-0306 | P3 | banked | cad0409 on main (cherry-pick of team-03 commit d2fb517 + seat union of contextguard exports into src/lifthrasir/__init__.py, amended into the slice commit), ls-remote verified 2026-11-12; poisoned-document test suite for model context; suite at banking 286 passed / 0 failed (seat full suite); undo = revert cad0409. P3 SET COMPLETE (0301-0306) |
| LIF-0401 | P4 | banked | 48f7f55 on main (cherry-pick of team-04 commit 554ff08; __init__ auto-merged union incl. actions exports, 74 __all__ entries verified), ls-remote verified 2026-11-12; typed action catalog and narrow executor interface; dry-run executor only, executes nothing; suite at banking 316 passed / 0 failed (seat full suite); undo = revert 48f7f55 |
| LIF-0402 | P4 | banked | 272d9e1 on main (cherry-pick of team-05 commit 2a05e27 + seat union of policy exports, amended into the slice commit), ls-remote verified 2026-11-12; policy decisions: identity, resource, risk level, preconditions; suite at banking 338 passed / 0 failed (seat full suite); undo = revert 272d9e1 |
| LIF-0403 | P4 | banked | 0accdd3 on main (cherry-pick of team-06 commit 8190798 + seat union of executor exports, amended into the slice commit; NOTE: executor.ActionRequest deliberately NOT exported at top level - the name stays with actions.ActionRequest banked in LIF-0401, per the SchemaVersionError precedent; the executor class remains at lifthrasir.executor.ActionRequest), ls-remote verified 2026-11-12; separate process and limited permissions for executor; suite at banking 355 passed / 0 failed (seat full suite); undo = revert 0accdd3 |
| LIF-0404 | P4 | banked | 4f352eb on main (cherry-pick of team-07 commit 782c708 + seat union of approval exports, amended into the slice commit), ls-remote verified 2026-11-12; user approval UX and signed/unique plan references; suite at banking 372 passed / 0 failed (seat full suite); undo = revert 4f352eb |
| LIF-0405 | P4 | banked | 749384a on main (FF merge of team-08 commit), ls-remote verified 2026-11-12; src/lifthrasir/transactions.py durable transaction store (SQLite WAL + synchronous=FULL, caller-supplied paths, hash-chained history, undo manifest recorded at creation, forward/undo verbs validated against the banked LIF-0401 catalog) + 49 tests + fixture; suite at banking 421 passed / 0 failed (seat full suite); undo = revert 749384a |
| LIF-0406 | P4 | banked | e2920ba on main (cherry-pick of recovered team-09 commit c1b6aa8 + seat fix amended in), ls-remote verified 2026-11-12; src/lifthrasir/killswitch.py + 17 tests + journal fixtures; NO __init__ exports (module deliberate, submodule import works); RECOVERY: the team commit was orphaned by a branch reset and recovered by the keeper (pinned as local branch yrsa/lifthrasir-lif0406-recovery); SEAT FIX: latent fork/exec race - FixtureRegistry.register()/spawn_fixture read /proc/<pid>/cmdline once, immediately after spawn, before exec landed, so registration intermittently refused the fixture's own processes under load (failed ~half of runs at the seat; the team's idle-machine run had passed 243/0); fixed in-slice at the seat - register() and spawn_fixture() now poll briefly for the marker to appear in the child's own cmdline, registration still requires observing the marker there and records starttime from the same matching read, foreign processes still refused; verified 15/15 killswitch runs + 3/3 full suites green after the fix; suite at banking 438 passed / 0 failed (seat full suite); note: killswitch.py keeps its own journal shape (lif0406-txn-journal/1) and does not consume LIF-0405's store - the two coexist, bridging is future integration work, not a defect in either slice; undo = revert e2920ba |
| LIF-0407 | P4 | banked | 221d037 on main (cherry-pick of team-01 363dbcc + seat __init__ union amended), ls-remote verified 2026-11-12; confinement review; seat unioned 24 confinement exports; confinement.Finding deliberately NOT top-level (name stays with contextguard.Finding, LIF-0306 precedent; it remains lifthrasir.confinement.Finding); suite at banking 451 passed / 0 failed (seat full suite); undo = revert 221d037. P4 SET COMPLETE (0401-0407) |
| LIF-0501 | P5 | banked | a24bce1 on main (cherry-pick of team-02 8fb60b8 + seat union of 26 recipes exports amended), ls-remote verified 2026-11-12; suite at banking 487 passed / 0 failed (seat full suite); undo = revert a24bce1 |
| LIF-0502 | P5 | banked | 07c01dc on main (cherry-pick of team-03 5b99868 + seat union of 14 recovery_demo exports amended), ls-remote verified 2026-11-12; fixture/in-memory demonstration only, no real host service touched; suite at banking 502 passed / 0 failed (seat full suite); undo = revert 07c01dc |
| LIF-0503 | P5 | banked | 3a268a5 on main (cherry-pick of team-04 8a4fa68 + seat union of 21 configpreview exports amended), ls-remote verified 2026-11-12; suite at banking 536 passed / 0 failed (seat full suite); undo = revert 3a268a5 |
| LIF-0504 | P5 | banked | 932f1a2 on main (cherry-pick of team-05 7355e49 + seat union of 17 soak exports amended), ls-remote verified 2026-11-12; soak.VERDICTS deliberately NOT top-level (name stays with configpreview.VERDICTS, LIF-0503; soak's remains lifthrasir.soak.VERDICTS); suite at banking 557 passed / 0 failed (seat full suite); undo = revert 932f1a2 |
| LIF-0505 | P5 | banked | f6cd236 on main (cherry-pick of team-06 1e9c318 + seat union of 21 reversal exports amended), ls-remote verified 2026-11-12; reversal.py is a fixture-state engine with its own durable manifest format; it re-declared the LIF-0405 contract locally and does not consume transactions.py; the two coexist, bridging is future work; suite at banking 577 passed / 0 failed (seat full suite); undo = revert f6cd236 |
| LIF-0506 | P5 | banked | a1cf23c on main (cherry-pick of team-07 c1266fc + seat union amended), ls-remote verified 2026-11-12; service_intent exports unioned with SCHEMA_VERSION aliased as SERVICE_INTENT_SCHEMA_VERSION (top-level SCHEMA_VERSION stays with the event bus, LIF-0201) and service_intent.VERDICTS held at submodule (configpreview owns the top-level name); suite at banking 587 passed / 0 failed (seat full suite); undo = revert a1cf23c. P5 SET COMPLETE (0501-0506) |
| LIF-0601 | P6 | banked | e54e702 on main (cherry-pick of team-09 38270aa + seat union of 27 modelprovider exports amended), ls-remote verified 2026-11-12; modelprovider.MalformedRequestError and modelprovider.request_from_dict deliberately NOT top-level (names stay with actions / the earlier banked module respectively; both remain at lifthrasir.modelprovider.*); no real inference claimed (protocol + deterministic mock + local-only adapter); suite at banking 638 passed / 0 failed (seat full suite); undo = revert e54e702 |
| LIF-0602 | P6 | banked | 2ed211b on main (cherry-pick of team-01 commit 37f0449 + seat union of 34 explanations exports + seat-amended collision-guard test rewritten as post-banking union-integrity test, both amended into the slice commit), ls-remote verified 2026-11-12; structured explanation + hypothesis templates with registry-resolved citations (invented citations refused); suite at banking 664 passed / 0 failed (seat full suite); negative control 8 failed / 18 passed as designed; undo = revert 2ed211b |
| LIF-0603 | P6 | banked | faf72a1 on main (cherry-pick of team-02 10bbd42 + seat union of 29 quotas exports amended; quotas.OUTCOMES stays at submodule), verified 2026-11-12; suite at banking 692 passed / 0 failed (seat full suite); negative control PASS; undo = revert faf72a1. P6 SET COMPLETE |
| LIF-0701 | P7 | banked | 6300680 on main (cherry-pick of recovered team-03 commit 6570345 + seat union of 32 dagexecutor exports amended; dagexecutor.STATUSES stays at submodule), verified 2026-11-12; RECOVERY: commit was orphaned by branch reset, recovered from reflog, pinned as yrsa/lifthrasir-lif0701-recovery; suite at banking 707 passed / 0 failed (seat full suite); negative control PASS; undo = revert 6300680 |
| LIF-0702 | P7 | banked | bf1d678 on main (cherry-pick of team-04 e14485b + seat union of 32 reproverify exports amended; reproverify EVIDENCE_SCHEMA/OUTCOMES/VERDICTS/MAX_OUTPUT_BYTES/run_verification stay at submodule, names owned by dagexecutor/modelprovider/configpreview/quotas/soak), verified 2026-11-12; suite at banking 725 passed / 0 failed (seat); negative control PASS (3 mutants); undo = revert bf1d678 |
| LIF-0703 | P7 | banked | 53d5642 on main (cherry-pick of team-05 0e0c76a + seat union of 29 scheduler exports amended; scheduler EVIDENCE_LADDER/MAX_DURATION_S stay at submodule), verified 2026-11-12; suite 745/0 (seat); negative control PASS; undo = revert 53d5642. P7 SET COMPLETE (0701-0703) |
| LIF-0801 | P8 | banked | 41abfdf on main (cherry-pick of recovered team-06 commit 876e5ea + seat union of 25 thor exports amended; thor.Finding stays at submodule, contextguard owns Finding), verified 2026-11-12; suite 763/0 (seat); negative control PASS; undo = revert 41abfdf |
| LIF-0802 | P8 | banked | 4a044f3 on main (cherry-pick of team-07 5a5379a + seat union of 36 security_triage exports amended), verified 2026-11-12; suite 777/0 (seat); negative controls PASS (empty-baseline calm drops to 75 percent; threshold mutant 7 failed as designed); undo = revert 4a044f3 |
| LIF-0803 | P8 | banked | a5ebf6d on main (cherry-pick of team-08 2014a7c + seat union of 10 coordination exports amended; coordination SEVERITIES/MalformedFindingError/validate_finding stay at submodule, security_triage owns those names), verified 2026-11-12; suite 821/0 (seat); negative control PASS; undo = revert a5ebf6d. P8 SET COMPLETE (0801-0803). FOLLOW-UPS recorded by team-08 (in its CAMPAIGN_STATE.md): policy verb-tier reconciliation with the LIF-0401 catalog, and guest-undo semantics for restart_unit_in_guest - cross-slice integration work for a future seat slice |
| LIF-0901 | P9 | banked | 28cf580 on main (cherry-pick of recovered team-09 commit 0aa9447; lab module, no package union), verified 2026-11-12; suite 866/0 (seat); negative controls PASS (32 refusal tests); undo = revert 28cf580 |
| LIF-0902 | P9 | banked | 895cef2 on main (cherry-pick of team-01 085594b + seat union of 23 kernellab exports amended; kernellab OUTCOMES/VERDICTS/build_evidence_record stay at submodule), verified 2026-11-12; suite 903/0 (seat); negative control PASS (8 failed as designed); undo = revert 895cef2 |
| LIF-0903 | P9 | banked | aacd976 on main (cherry-pick of team-09 7a5d2c7; lab module, no package union), verified 2026-11-12; suite 932/0 (seat); negative controls PASS (13 refusal tests); undo = revert aacd976 |
| LIF-0904 | P9 | banked | ceaea05 on main (cherry-pick of team-06 2e34939 + seat union of 34 patchdossier exports amended; patchdossier EVIDENCE_LADDER/VERDICTS stay at submodule), verified 2026-11-12; suite 955/0 (seat); negative control PASS; undo = revert ceaea05 |
| LIF-0905 | P9 | banked | 3990dd6 on main (cherry-pick of team-03 458fc34 + seat-amend of 18 staticanalysis exports; staticanalysis SEVERITIES stays at submodule, security_triage owns it), verified 2026-11-12; suite 981/0 (seat; the committed test file carries 26 tests - the team record said 21 from its pre-amend log; seat count governs); negative control PASS (2 failed as designed); undo = revert 3990dd6. P9 SET COMPLETE (0901-0905) |
| LIF-1001 | P10 | banked | 9f9339f on main (cherry-pick of team-02 commit 18e214a; lab module, no package union), verified 2026-11-12; benchmark harness: controlled environment + repetitions, deterministic fixture workloads only, no heavy runs; suite at banking 1006 passed / 0 failed (seat full suite); negative control PASS (mutated samples flip verdict, cross-seed comparison refused, nondeterministic checksum refused); undo = revert 9f9339f |
| LIF-1002 | P10 | banked | f4f9d4b on main (cherry-pick of team-01 commit 49852ae; lab module, no package union), verified 2026-11-12; workload profiles for all five families, declarative fixture-level only (no heavy workload ran); suite at banking 1034 passed / 0 failed (seat); negative control PASS; differential PASS; undo = revert f4f9d4b |
| LIF-1003 | P10 | banked | 95b8b03 on main (cherry-pick of team-03 commit d9e9e78; lab module, no package union), verified 2026-11-12; candidate ranking with regressions + recorded energy (unrecorded energy stays UNMEASURED, never estimated); suite at banking 1055 passed / 0 failed (seat); negative control PASS; undo = revert 95b8b03. P10 SET COMPLETE (1001-1003) |
| LIF-1101 | P11 | banked | 74a5468 on main (cherry-pick of team-04 commit 065a7b3 + seat union of 40 distroprobes exports amended; distroprobes REPORT_VERSION/build_evidence_record/summarize_reports stay at submodule), verified 2026-11-12; probes over recorded host facts only, no support claimed for any distro (authority stays LIF-1102); suite at banking 1080 passed / 0 failed (seat); negative controls PASS (4); undo = revert 74a5468 |
| LIF-1102 | P11 | banked | 965447b on main (cherry-pick of team-05 commit 18e4308 + seat union of 31 distroadapters exports amended; distroadapters.build_evidence_record stays at submodule, soak owns the name), verified 2026-11-12; adapters are data + pure rendering only; supported-versions table: all 7 rows UNVERIFIED, none supported, is_supported() False for all in v0.1; suite at banking 1098 passed / 0 failed (seat); negative control PASS; undo = revert 965447b |
| LIF-1103 | P11 | banked | 0ec8ff7 on main (cherry-pick of team-06 commit 2689bd2; lab module, no package union), verified 2026-11-12; ARM64 SBC + high-memory APU resource profiles, all basis declared-target (representative class targets, NOT probed hardware); suite at banking 1126 passed / 0 failed (seat); negative control PASS (4 mutations refused); undo = revert 0ec8ff7. P11 SET COMPLETE (1101-1103) |
| LIF-1201 | P12 | banked | b179fa1 on main (cherry-pick of team-07 commit 8b05572 + seat union of 28 releasepipeline exports amended; releasepipeline VERDICT_BLOCKED/VERDICTS/MalformedRecordError/SupportClaimError/build_evidence_record stay at submodule), verified 2026-11-12; package-plan + simulated fixture signing only - no real package, no real key, nothing published; suite at banking 1138 passed / 0 failed (seat); negative control PASS; undo = revert b179fa1 |
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
