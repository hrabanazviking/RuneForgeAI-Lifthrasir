# Typed Action Catalog and Narrow Executor Interface v0.1 (LIF-0401)

**Project:** Lifþrasir — The Self-Evolving Linux System
**Slice:** LIF-0401 (Phase P4) — typed action catalog and narrow executor interface.
**Status honesty:** This slice defines a contract and ships one
non-executing implementation. The catalog is a closed vocabulary in
code (`src/lifthrasir/actions.py`) with a generated machine-readable
twin (`docs/protocols/action-catalog.v0.1.json`); the executor
interface is a typed protocol whose only shipped implementation,
`DryRunExecutor`, validates fully and executes NOTHING. No privileged
execution, no policy decisions (LIF-0402), no separate broker process
(LIF-0403), and no signed plan references (LIF-0404) exist in this
slice, and none are claimed. On the evidence ladder this is a
specification plus fixture-tested validation code: lab-verified on
this host's Python test suite only, for the contract behaviour the
tests name — nothing more.
**Date:** 2026-11-12
**Sources:** `ROADMAP-TO-COMPLETION.md` §0 (hard safety invariants)
and §5 (evidence rules); `docs/RISK-MATRIX.md` (LIF-0003, tiers and
consent floors); `docs/protocols/SCHEMAS-v0.1.md` and
`docs/protocols/schemas/v0.1/plan.schema.json` (LIF-0004);
`docs/architecture/ADR-0002-architecture.md` (broker contract);
`research/25-API-AND-EVENT-SCHEMAS.md` (unknown verbs rejected; no
generic shell strings).

## Why this slice exists

LIF-0004 recorded an honest limit: in plan schema v0.1, a step's
`action_verb` is a free string, because the typed action catalog did
not exist yet and policy evaluation was left as the authority that
rejects unknown verbs. This slice is that catalog. From here on, a
plan step is meaningful only if its verb, target type, and arguments
validate against the catalog (`validate_plan_steps` in the module is
the bridge the LIF-0004 specification promised).

## The catalog (v0.1, 16 verbs)

The code is the source of truth; this table is its human-readable
mirror, and `tests/test_action_catalog.py` fails if the JSON twin,
this table's verb set, or the code disagree.

| Verb | Tier | Consent floor | Scope | Target types | Undo |
|---|---|---|---|---|---|
| read_service_status | L0 | none | live-readonly | systemd-unit | none |
| read_system_counters | L0 | none | live-readonly | host | none |
| check_package_integrity | L0 | none | live-readonly | package | none |
| read_journal | L1 | standing-opt-in | live-readonly | systemd-unit | none |
| read_evidence_store | L1 | standing-opt-in | live-readonly | evidence-store | none |
| create_lab_guest | L2 | session-blanket | lab-guest | lab-guest | delete_lab_guest |
| delete_lab_guest | L2 | session-blanket | lab-guest | lab-guest | none |
| reset_lab_guest | L2 | session-blanket | lab-guest | lab-guest | none |
| edit_config_in_guest | L2 | session-blanket | lab-guest | config-file | reset_lab_guest |
| restart_unit_in_guest | L2 | session-blanket | lab-guest | systemd-unit | none |
| restart_unit | L3 | allowlist-notice | live-host | systemd-unit | stop_unit |
| stop_unit | L3 | allowlist-notice | live-host | systemd-unit | restart_unit |
| revert_user_config | L3 | allowlist-notice | live-host | config-file | revert_user_config |
| install_package | L4 | per-action | live-host | package | remove_package |
| remove_package | L4 | per-action | live-host | package | install_package |
| change_firewall_rule | L4 | per-action | live-host | firewall-rule | change_firewall_rule |

Design rules the table encodes:

- **Tiers come from the risk matrix, never invented here.** Each
  verb's tier is the matrix tier of its worked example class
  (observe L0/L1, lab L2, allowlisted reversible live action L3,
  per-action live change L4), and its consent floor is exactly the
  matrix floor for that tier. Consent strictness is monotone in tier.
- **L5 has no verbs.** Human-only maintenance (kernel, boot,
  partitions, encryption, keys, filesystem repair) is not executable
  through this interface at all; the prohibited classes of the risk
  matrix (consent `never`) are likewise absent, and verb spellings
  naming them are refused with a precise reason before the
  unknown-verb check.
- **Every live verb is reversible and names its undo**, which is
  itself a catalog verb or, for read-only verbs, `none` because
  nothing changed. A verb with no tested undo cannot sit in the
  catalog at L3/L4 (risk matrix classification rule 5).
- **Arguments are closed sets.** Each verb declares its arguments
  with kinds (`name`, `unit`, `path`, `string`, `integer`,
  `boolean`); unknown arguments are refused, missing required
  arguments are refused, and there is no argument — in any verb —
  that carries a command, a shell string, or an argv list.
- **Targets are singular and typed.** One request names exactly one
  target of a type the verb allows. Wildcards, shell metacharacters,
  and path traversal are refused. On the live host, critical units
  (sshd, journald, logind, dbus, NetworkManager, …), protected path
  prefixes (`/boot`, `/etc/ssh`, `/home`, firmware, trust roots, …),
  and boot/trust packages are refused by name even for a verb whose
  tier would otherwise fit.
- **Everything is time-bounded.** Each verb carries a maximum
  duration; each request and each authorization carries an expiry,
  checked against an injectable clock.

## The narrow executor interface

```text
Executor (protocol)
  execute(request: ActionRequest, authorization: Authorization,
          now: float) -> ActionResult
```

- `ActionRequest` = verb + one typed `ActionTarget` + closed args +
  the `plan_id` it belongs to + expiry. Nothing else can be asked.
- `Authorization` = the token shape of ADR-0002 decision D3:
  `plan_id`, `plan_digest` (`sha256:` + 64 hex), one-time `nonce`,
  granted `consent_mode`, `expires_at`. This slice defines and
  checks the shape, binding, consent floor, and expiry. Whether
  policy should grant it is LIF-0402; how the token is signed and
  made unique is LIF-0404; the separate limited-permission process
  that will one day execute for real is LIF-0403.
- `DryRunExecutor` is the only implementation: it runs the full
  validation chain, appends the request to an in-memory intent list,
  and returns `status="dry-run"`, `executed=False`. It touches no
  host, guest, or store state. The module contains no subprocess,
  shell, or dynamic-execution calls at all — a test scans the source
  for them.
- Deny by default: unknown verb, unknown target type, unknown
  argument, expired request or token, consent below the floor,
  unbound token, critical or protected resource — each is a named
  refusal (`UnknownVerbError`, `ProhibitedActionError`,
  `MalformedRequestError`, `ConsentError`, `ExpiredRequestError`),
  never a silent coercion.

## Consistency with v0.1 schemas (LIF-0004)

- Plan step shape is unchanged: `action_verb`, `target{type,name}`,
  `args`. The catalog constrains the VALUES, as LIF-0004 foresaw;
  no v0.1 schema file is edited by this slice.
- Both verbs in the banked valid plan example
  (`edit_config_in_guest`, `restart_unit_in_guest`) are catalog
  verbs at L2 with matching target types and argument sets, and
  `validate_plan_steps` accepts that example unchanged — the
  differential test in this slice proves it.
- Target types reuse the example's vocabulary (`systemd-unit`,
  `config-file`) plus the types the risk-matrix examples require
  (`package`, `host`, `lab-guest`, `evidence-store`,
  `firewall-rule`).
- Risk levels and consent modes are the risk matrix's own strings;
  the plan schema's consent-floor rules and this catalog's floors
  are the same table, checked against `docs/RISK-MATRIX.md` by test.

## What this slice cannot do (honest limits)

- **No execution.** Nothing here restarts a service, edits a file, or
  creates a guest. The verbs are a vocabulary and a validation
  contract; the only runner is the dry-run.
- **No policy.** Identity, allowlist membership, and precondition
  checks are LIF-0402. The validator refuses critical resources by
  its built-in lists, but it does not know any user's allowlist.
- **No authentication.** The authorization shape is checked, not
  verified: signatures, nonce consumption, and replay protection
  belong to LIF-0404 and the broker of LIF-0403 (ADR-0002 D3).
- **Home files stay protected even at L3.** The risk matrix
  places "revert a proven user-level configuration" at L3, while
  §0 invariant 2 and prohibited action P-09 bar agent mutation
  of home files. This catalog reads the two together: 
  `revert_user_config` covers managed configuration outside the
  home tree, and every path under `/home` is refused. Any
  narrower carve-out is a question for the LIF-0407 review,
  not an assumption baked in here. The banked plan example
  also shaped one detail: its `edit_config_in_guest` step names
  a setting without a value, so `value` is an optional argument
  of that verb in v0.1.
- **Lists are v0.1 judgements.** The critical-unit, protected-path,
  and protected-package lists are conservative starting points for
  the Kubuntu x86-64 target, not a distro-complete authority; the
  P4 confinement review (LIF-0407) is where they are audited per
  distro.
- **Human review pending.** Like the risk matrix it builds on, this
  catalog has not had human review; no rung above lab-verified (test
  suite, this host) is claimed for any part of it.

## Issue record — LIF-0401

```yaml
id: LIF-0401
phase: P4
goal: "Define typed action catalog and narrow executor interface."
dependencies: [LIF-0003, LIF-0004]
risk_tier: L0
scope: "Catalog and executor contract in src/lifthrasir/actions.py, generated machine-readable catalog in docs/protocols/action-catalog.v0.1.json, this specification, fixtures under tests/fixtures/lif0401/, and tests in tests/test_action_catalog.py. Contract and validation code only; the sole executor executes nothing; no system state changed; no README.md modification."
test_fixture: "tests/test_action_catalog.py plus tests/fixtures/lif0401/requests.json: catalog completeness and risk-matrix consistency, JSON-twin equality, v0.1 plan-example differential, request/authorization validation, and refusal cases (unknown, prohibited, shell, wildcard, critical, expired, under-consented)."
expected_evidence: "Full-suite pytest log in hidden_files/ showing the 226 banked tests plus the new catalog tests passing on purpleraider; negative-control log showing a mutated catalog JSON fails the equality test."
negative_control: "A request naming the unknown verb run_shell_command (and separately a catalog JSON copy with one consent floor weakened) must be refused / fail; logged in hidden_files/."
recovery_or_undo: "Revert the slice commit (git revert) — code, generated JSON, specification, fixtures and tests only, no system state changed."
```
