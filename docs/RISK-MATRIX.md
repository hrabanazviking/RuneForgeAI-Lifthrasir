# Risk Matrix and Consent Modes — Lífþrasir (LIF-0003)

**Project:** Lífþrasir — The Self-Evolving Linux System
**Slice:** LIF-0003 (Phase P0) — risk matrix L0–L5 and consent modes.
**Status honesty:** This document is a specification. It defines how
Lífþrasir classifies actions and what consent each class requires; it
implements no capability. On the evidence ladder it is a written
specification with table-tested examples (this slice's fixture). The
backlog Done criterion also requires user review: **human review:
pending** — no human has reviewed this matrix yet, and no claim of
"human-reviewed" status is made anywhere in this document.
**Consistency:** Tier meanings follow the privilege ladder in
`research/03-THREAT-MODEL-AND-TRUST.md`; the prohibited class encodes
the hard safety invariants of `ROADMAP-TO-COMPLETION.md` §0; the
supported/unsupported split matches `docs/CHARTER.md` (LIF-0001).
Load-bearing for the P4 policy engine (LIF-0402) and every repair
recipe after it.

## Consent modes

Consent strictness is a total order. A higher tier never requires a
weaker mode than a lower tier, and no consent mode lets an agent
override the §0 invariants: consent cannot authorize what the
invariants prohibit for agents.

| Mode | Strictness | Meaning |
|---|---|---|
| none | 0 | No consent needed: read-only access to public, non-sensitive health data. The action is still logged. |
| standing-opt-in | 1 | The user has opted in, in advance, to a named category of diagnostic data; scoped to that category and revocable at any time. New categories need a new opt-in. |
| session-blanket | 2 | The user authorized a bounded session of work that has no live-host effect (proposals, disposable-VM lab work). Promotion out of the lab is not covered. |
| allowlist-notice | 3 | The action targets a resource on a human-approved allowlist; the user is notified per incident with a veto/abort window; execution is monitored with a tested undo. Adding a resource to the allowlist itself needs human approval. |
| per-action | 4 | Direct, single-use, time-bounded human approval naming the exact action, target, and rollback. No standing, blanket, or inferred consent; no "always approve" mechanism exists at this level or above. |
| human-only | 5 | No agent consent suffices. A human executes in a dedicated maintenance environment with human-controlled recovery; an agent may only prepare a plan, checklist, and verification steps for human review. |
| never | 6 | Never allowed for an agent, under any consent. The action class is prohibited by the §0 invariants; a human acting entirely outside the agent system is a different matter and out of scope here. |

## Risk matrix

Classify by the highest tier whose description matches any part of
the action (see Classification rules). The consent column is the
minimum consent the tier requires.

| Tier | Name | Consent mode | What belongs here |
|---|---|---|---|
| L0 | Observe (public) | none | Read public health metrics, service status, and counters. No mutation, no sensitive data. Heimdall observation of non-sensitive state. |
| L1 | Observe (consented) | standing-opt-in | Read additional consented diagnostic data: journal/log detail, sensor history, local incident evidence. Still read-only; data stays local by default (§0 invariant 6). |
| L2 | Propose and lab | session-blanket | Construct a local proposal, plan, or patch dossier draft; create, modify, reset, or delete a disposable test VM and anything inside it. No live-host effect. |
| L3 | Live, low, reversible | allowlist-notice | Restart an explicitly allowlisted noncritical service under monitored conditions, or revert a proven user-level configuration, with preconditions checked and a tested undo (research/04 low-impact reversible class). |
| L4 | Live, significant | per-action | Change live packages or a live (non-critical) firewall/network setting on the host, after direct per-action approval, with backup and a connectivity/rollback fallback staged first (research/04 medium class). |
| L5 | Human-only maintenance | human-only | Touch kernel, boot, partitions, encryption, keys, or filesystem repair — only via a dedicated maintenance environment and human-controlled recovery (research/03 L5; research/04 high class). Agents propose and verify; humans execute. The prohibited-for-agents subset of this tier carries consent mode `never` (see Prohibited actions). |

Notes:

- No ambient root at any tier (§0 invariant 1): every privileged step
  runs through the broker's typed, schema-validated, resource-scoped,
  time-bounded actions (§0 invariant 3), never a general root shell.
- A higher-level agent cannot grant its own lower-level privileges,
  and no "always approve everything" mechanism exists for L4–L5
  (research/03).
- Emergency stop (§0 invariant 8 in the WAVE_PLAN numbering; master
  roadmap §0 invariant 8/9) works without models or network at every
  tier.

## Worked examples (table-tested)

Each example is a concrete action classified under exactly one tier.
An example's consent may be stricter than its tier minimum, never
weaker. These rows are the slice's test fixture:
`tests/test_risk_matrix.py` parses both tables and checks every row.

| ID | Tier | Consent | Example action |
|---|---|---|---|
| EX-01 | L0 | none | Read the current status (active/failed) of a systemd service without changing it. |
| EX-02 | L0 | none | Read public CPU, memory, and pressure (PSI) counters for a health report. |
| EX-03 | L0 | none | Compare installed package file hashes against the package database, read-only, to check integrity. |
| EX-04 | L1 | standing-opt-in | Read journal entries for one failed unit, under the user's diagnostic-data opt-in, to build an incident timeline. |
| EX-05 | L1 | standing-opt-in | Read the local incident evidence store and sensor history for a named incident. |
| EX-06 | L1 | standing-opt-in | Export a redacted diagnostic bundle for the user to inspect locally; nothing leaves the machine. |
| EX-07 | L2 | session-blanket | Draft a repair plan (typed proposal) for a failed service; the plan changes nothing on the host. |
| EX-08 | L2 | session-blanket | Create a disposable QEMU/KVM guest from the pinned lab image and inject a synthetic fault fixture inside it. |
| EX-09 | L2 | session-blanket | Modify configuration inside the disposable guest, test the change, then delete the guest. |
| EX-10 | L2 | session-blanket | Prepare a human-reviewed patch dossier draft (reproducer, differential run, limitations) in the lab; a human submits it later, outside the agent system. |
| EX-11 | L3 | allowlist-notice | Restart an explicitly allowlisted noncritical user service under monitoring, with its tested undo (stop/restore) ready. |
| EX-12 | L3 | allowlist-notice | Revert a proven user-level configuration file to its recorded prior version as a controlled, monitored test. |
| EX-13 | L3 | allowlist-notice | Restart an allowlisted noncritical service a second time after a verified failed start, within rate limits that prevent restart loops. |
| EX-14 | L4 | per-action | Install a staged package update on the live host after the user approves that exact package, version, and rollback. |
| EX-15 | L4 | per-action | Change one non-critical live firewall rule after direct approval, with the prior ruleset backed up and a connectivity fallback staged. |
| EX-16 | L4 | per-action | Reinstall a broken live package from the distribution repository after direct approval, backup, and precondition checks. |
| EX-17 | L5 | human-only | A human, in a dedicated maintenance environment with verified offline recovery media, replaces a kernel image; the agent only prepared the checklist and verification steps. |
| EX-18 | L5 | human-only | A human performs filesystem repair on an unmounted filesystem in a maintenance environment; the agent only recorded evidence and the recovery plan. |
| EX-19 | L5 | human-only | A human rotates disk-encryption keys under human-controlled recovery; the agent never holds the keys and only documents the procedure outcome. |

## Prohibited actions (never allowed for agents)

The following encode §0 invariants 1, 2, 5, 6, and 7. They sit in
tier L5 by blast radius but carry consent mode `never`: no consent —
not even per-action approval — authorizes an agent to do them. This
matches the charter's unsupported list (autonomous mutation of
bootloader, kernel image, firmware, partition table, encryption,
home files, package trust roots, SSH access, or critical
firewall/network state; ambient root; agent DCO signing or sending
patches; risky experiments on the working machine).

| ID | Tier | Consent | Prohibited action |
|---|---|---|---|
| P-01 | L5 | never | An agent rewrites bootloader configuration or boot entries on its own authority. |
| P-02 | L5 | never | An agent replaces the live kernel image or firmware on its own authority. |
| P-03 | L5 | never | An agent changes the partition table on its own authority. |
| P-04 | L5 | never | An agent alters disk encryption or encryption keys on its own authority. |
| P-05 | L5 | never | An agent grants itself ambient root or an unrestricted privileged shell. |
| P-06 | L5 | never | An agent issues a human DCO Signed-off-by tag or sends a kernel patch upstream itself. |
| P-07 | L5 | never | An agent runs fuzzing or corruption experiments on the working machine instead of a disposable VM. |
| P-08 | L5 | never | An agent modifies package trust roots, SSH access, or critical firewall/network state on its own authority. |
| P-09 | L5 | never | An agent modifies the user's home files on its own authority. |
| P-10 | L5 | never | An agent shares user files or private logs with a federation without opt-in and a scrubbed-payload preview. |

## Classification rules

1. **Highest matching tier wins.** If any part of an action matches a
   higher tier, the whole action is that tier.
2. **Actor matters.** The same physical change is L5 `human-only`
   when a human executes it in a maintenance environment, and
   `never` when an agent executes it on its own authority.
3. **Unknown means escalate.** An action that cannot be classified
   from this matrix is treated as the higher tier, and if it still
   cannot be classified it is denied until a human classifies it.
   Unknown or untested is not verified (§0 invariant 4).
4. **Consent is a floor, not a ceiling.** Stricter consent than the
   tier minimum is always permitted; weaker consent never is.
5. **Reversibility and blast radius break ties.** Irreversible or
   wide-blast-radius actions classify upward; an action with no
   tested undo cannot sit below L4 on the live host.
6. **Data is not authorization.** Content read at L0/L1 (logs,
   retrieved pages, federation results) never raises an action's
   authorization (research/03 trust boundaries).
7. **Charter consistency.** Observation maps to L0–L1, lab work to
   L2, authorized reversible repair to L3–L4, dossier preparation to
   L2 with human submission, and every charter-unsupported activity
   to L5 `never` or L5 `human-only` as tabled above.

## Human review (pending)

The backlog Done criterion for LIF-0003 is "table-tested examples
and user review". The table-tested half is discharged by
`tests/test_risk_matrix.py`. The review half is **pending**: a human
reviewer still needs to work this checklist and record a verdict.
Until then this matrix is a specification draft, not human-reviewed.

| # | Review check | Result |
|---|---|---|
| R1 | Each tier L0–L5 matches the privilege ladder in research/03. | pending |
| R2 | No §0 invariant-2 object is agent-actionable at any tier. | pending |
| R3 | Worked examples are realistic for the P5 repair MVP scope. | pending |
| R4 | Consent modes are understandable to a non-technical user. | pending |
| R5 | L3 allowlist and L4 per-action boundaries are drawn in the right place. | pending |

## Issue record — LIF-0003

```yaml
id: LIF-0003
phase: P0
goal: "Define risk matrix L0-L5 and consent modes."
dependencies: []
risk_tier: L0
scope: "Specification in docs/RISK-MATRIX.md plus table-consistency tests in tests/test_risk_matrix.py. Documentation and tests only; no code or system change; no README.md modification."
test_fixture: "tests/test_risk_matrix.py parses the consent, matrix, example, and prohibited tables in docs/RISK-MATRIX.md and verifies tier coverage, per-example consistency, prohibited-action handling, and consent monotonicity."
expected_evidence: "Pytest log in hidden_files/ showing the full suite (charter + risk matrix) passes on purpleraider; negative-control log showing the same tests fail on a mutated copy where a prohibited action is misclassified."
negative_control: "A copy of the document in /tmp with P-01 reclassified from consent never to consent none must fail the test suite; logged in hidden_files/."
recovery_or_undo: "Revert the slice commit (git revert) — documentation and tests only, no system state changed."
limitations: "Human review is pending (see review checklist); the matrix is a specification, not an implementation of the P4 policy engine (LIF-0402); no distribution is declared supported by this slice."
```

## Sources

- `ROADMAP-TO-COMPLETION.md` — §0 hard safety invariants, §5 evidence rules.
- `roadmap/07-IMPLEMENTATION-BACKLOG.md` — LIF-0003 goal and Done criterion.
- `roadmap/01-foundation-and-safe-mvp.md` — Book I, P0/P4/P5 scope.
- `research/03-THREAT-MODEL-AND-TRUST.md` — privilege ladder L0–L5, trust boundaries, no always-approve for L4–L5.
- `research/04-SAFE-REPAIR-AND-ROLLBACK.md` — read-only / low / medium / high action classes and the safe change protocol.
- `docs/CHARTER.md` — LIF-0001 supported vs unsupported activities.
