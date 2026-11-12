# Service Intent Classification (LIF-0506)

SPDX-License-Identifier: GPL-2.0-only

## Purpose

Eir (P5) must never "repair" a service that was stopped on purpose,
and must never ignore one that failed by accident. This slice adds
the deterministic classifier that draws that line:
`src/lifthrasir/service_intent.py` — recorded unit state in, one of
four verdicts out. No model, no live host query, no state change.

## Inputs (recorded data only)

`UnitObservation` is built three ways, all from recorded/fixture
data:

- `from_show(unit, show)` — one unit's `systemctl show`-style
  key/value dict, as returned by the banked LIF-0202 collector's
  `parse_show` (fields: ActiveState, SubState, UnitFileState,
  Result, ExecMainStatus, ExecMainCode, NRestarts, ConditionResult,
  AssertResult).
- `from_fixture(service)` — a LIF-0104-style fixture service dict
  (`name` / `active_state` / `enabled` / `result` /
  `restart_count` / `intentionally_disabled`), e.g.
  `lab/fixtures/F02.json`.
- `from_collector(record, show, events)` — banked LIF-0202
  collector output (unit record + show dict + journal timeline),
  duck-typed so `src/` never imports `lab/`.

Absent recorded fields stay `None`; nothing is invented
(master roadmap §0 invariant 4).

## Verdicts

| Verdict | Meaning | Eir action |
|---|---|---|
| `intentional` | Recorded evidence proves a deliberate stop / by-design inactive | abstain |
| `accidental_failure` | Recorded evidence proves an unintended failure | repair candidate (`needs_repair`) |
| `healthy` | Unit is currently active | abstain |
| `unknown` | Recorded evidence cannot decide intent | abstain; gather more evidence |

`needs_repair` is true ONLY for `accidental_failure`;
`should_abstain()` is its exact complement.

## Rule order (first match wins)

1. Malformed (no unit / no active state) → `unknown`.
2. Currently `active` → `healthy` (restart history is noted, not
   judged).
3. Failure evidence → `accidental_failure`: `failed` active/sub
   state; failure `Result` (exit-code, signal, core-dump, timeout,
   watchdog, resources, start-limit-hit, protocol, oom-kill);
   nonzero or killed/dumped main exit; `auto-restart` sub-state;
   restart loop (`NRestarts >= 5` while activating/inactive — the
   LIF-0104 F06 fixture's own symptom boundary). Failure evidence
   is checked BEFORE intent evidence: a disabled unit that ran and
   failed still failed.
4. Intent evidence (unit `inactive`) → `intentional`: masked /
   masked-runtime; disabled / disabled-runtime; an explicit
   recorded intent flag; `ConditionResult=no` (unit skipped by
   design).
5. Static / indirect / generated file state + `inactive` →
   `intentional` (on-demand units rest inactive by design).
6. Clean-stop evidence → `intentional`: `inactive` with
   `Result=success` and no bad exit; or a journal trail whose last
   relevant event is `stopped` with no `failed` events.
7. Anything else — bare `inactive`, transitional states, mixed
   trails → `unknown`. Bare inactive proves nothing about intent:
   stripping F02's disabled evidence flips its verdict from
   `intentional` to `unknown`, never to a guess (standing test).

## Agreement with the independent oracle (LIF-0104)

F02 (intentionally disabled) — oracle verdict `abstain`, classifier
`intentional`. F01 (failed) and F06 (restart loop) — oracle
`fault`, classifier `accidental_failure`. The oracle and the
classifier share no code; agreement is a differential check, not a
self-grade.

## Limitations

Contract/test level only (evidence ladder: reproducer +
lab-verified at recorded-data scope). The classifier judges the
recorded snapshot it is given; stale or partial recordings yield
`unknown`, by design. It does not read administrator journal notes
beyond the collector's event kinds, does not persist verdicts
(event store integration is later work), and never acts: repair
itself remains behind the P4 policy/approval boundary. Human
review pending.
