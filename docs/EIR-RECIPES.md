# Eir Health-Repair Recipes: Exact Targets and Effects (LIF-0501)

**Project:** Lífþrasir — The Self-Evolving Linux System
**Slice:** LIF-0501 (Phase P5) — health-repair recipe abstraction
with exact targets and effects.
**Status honesty:** Declarative data + validation implementation in
`src/lifthrasir/recipes.py`, proven by `tests/test_recipes.py` at
fixture scope only (evidence ladder: reproducer-level, fixture-tested
in this checkout on purpleraider). No recipe is executed against the
real host in this slice; no live recovery is implemented or claimed.
Demonstration of one noncritical user-service recovery is LIF-0502.
Human review: **pending**.

## What a recipe is

A recipe is a named, versioned, closed-shape record
(`lifthrasir.recipe.v0.1`) that binds together the banked P4
contracts without executing anything:

- **Exact targets.** Every step names one LIF-0401 catalog verb and
  exactly one typed target — a literal, or one whole-value
  `$parameter` bound at instantiation. Wildcards, shell text,
  embedded placeholders and multi-target steps do not exist here.
- **Exact effects.** Every step declares at least one effect whose
  target is *exactly* the step's target, with a named observable and
  an expected value. `expected_effects()` returns the bound list;
  verification (LIF-0504) compares observed state against it, and an
  effect that does not materialise exactly is a failed repair.
- **Catalog truth.** A step's `undo_verb` must equal the catalog's
  own `undo_method` for its verb, and the recipe rollback method
  must be the head of that undo chain. The recipe's `risk_level`
  must *equal* the maximum step risk derived from the catalog (an
  underdeclared risk is refused, as in LIF-0402), and its
  `consent_mode` must sit at or above the docs/RISK-MATRIX.md floor
  for that risk. Consent mode `never` is refused outright.
- **Preconditions and abstention.** A recipe names at least one
  precondition and at least one abstain condition.
  `check_applicability()` returns ABSTAIN unless every precondition
  is observed true and no abstain condition is observed; an
  unobserved precondition abstains as unverified (master roadmap
  §0 invariant 4). A recipe is a conditional pattern, not a blanket
  future permission (research/07).
- **Instantiation.** `instantiate()` binds parameters to exact
  values and emits a v0.1 plan record (LIF-0004 shape) that must
  pass the banked checks — `actions.validate_plan_steps`,
  `approval.check_plan_shape`, and a per-step
  `actions.validate_request` at the bound target, which refuses
  critical units, protected paths and trust-root packages bound
  through parameters exactly as it refuses them literally. Policy
  evaluation (LIF-0402) and user approval (LIF-0404) remain
  separate, later acts; instantiation grants nothing.

## Built-in recipe catalog v0.1

Four recipes, spanning L2–L4, every verb drawn from the LIF-0401
catalog. The machine-readable twin is
`docs/protocols/recipes.v0.1.json` (generated from the code;
`tests/test_recipes.py` asserts the twin matches).

| Recipe | Risk | Consent | Repair |
|---|---|---|---|
| rec-restart-failed-service | L3 | allowlist-notice | Restart one allowlisted noncritical unit that is in failed state and expected to run; abstains when the stop was intentional, the unit is critical, or a restart loop is detected. Rollback: stop_unit. |
| rec-revert-user-config | L3 | allowlist-notice | Revert one drifted user-level config file to its recorded prior version digest; abstains on intentional edits, protected paths, or a missing prior version. Rollback: revert_user_config. |
| rec-reinstall-broken-package | L4 | per-action | Reinstall one exact staged package version after an observed integrity failure; abstains on boot/trust packages, a passing integrity check, or an unstaged version. Rollback: remove_package. |
| rec-lab-guest-config-fix | L2 | session-blanket | Correct one named setting inside a disposable lab guest and restart the guest unit there; abstains when the guest is not disposable or is the live host. Rollback: reset_lab_guest. |

Adding a recipe is a catalog version change with its own review,
never a runtime option — the same closed-vocabulary rule as the
action catalog.

## Safety invariants bound here (master roadmap §0)

- No verb reachable from a recipe mutates bootloader, kernel
  image, firmware, partition table, encryption, home files,
  package trust roots, SSH access, or critical firewall/network
  state: the catalog contains no such verb, and instantiation
  re-validates every bound target through the catalog validator.
- Recipes are data. This module contains no execution primitive
  (a source-scan test pins that), no ambient root, no shell.
- Unknown recipes, unknown verbs, unknown keys and unknown
  parameters are refused by name; nothing is coerced.

## Limitations

- In-memory, single-process validation only; recipe persistence,
  signing and storage belong to later slices and are not claimed.
- Applicability is judged on caller-supplied observations; the
  sensors that produce those observations are P2/P3 slices, and
  wiring them together is future work, not claimed here.
- The P5 exit gate (10 issue fixtures including expected
  abstentions, documented recovery) spans LIF-0501…LIF-0506; this
  slice contributes the abstraction, four built-in recipes, and
  abstention semantics — not the full gate.
