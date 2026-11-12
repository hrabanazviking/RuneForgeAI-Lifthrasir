# Security Triage and Low-False-Positive Baseline (LIF-0802)

SPDX-License-Identifier: GPL-2.0-only

## Purpose

A detector that pages a human for every distro update trains the
human to ignore it. This slice adds Thor's deterministic triage
layer: `src/lifthrasir/security_triage.py` — detector findings in,
a ranked, grouped queue for a human out. No model, no live host
access, no response action (response coordination is LIF-0803,
behind the P4 policy engine). P8's graduation gate names this
exact deliverable: a false-positive test suite.

## Detector finding shape (fixture interface)

LIF-0801 (the Thor detector) was still unbanked when this slice
was built, so the finding shape is defined from the BANKED
LIF-0004 v0.1 schemas, not from unbanked code:

- `finding_id` (`find-...`), `detector`, `check`,
  `target_type` / `target`, `observed` (the recorded value or
  state), optional `expected` (the value the detector compared
  against), `detail`, `recorded_at` (RFC 3339).
- `claimed_severity` uses the LIF-0004 incident severity enum:
  info / low / medium / high / critical. It is the detector's
  CLAIM, never treated as proof.
- `evidence_refs` are LIF-0004 evidence ids (`ev-...`), unique,
  at most 32; an optional `incident_id` (`inc-...`) ties the
  finding to its LIF-0004 incident record.
- Malformed findings are refused with `MalformedFindingError`;
  nothing is triaged silently.

## Scoring (deterministic, recorded factors only)

| Factor | Points |
|---|---|
| Claimed severity | info 0 · low 10 · medium 25 · high 45 · critical 70 |
| Novelty vs baseline | known-benign 0 · novel +10 · changed +15 · known-bad +20 |
| Corroboration (distinct evidence refs) | 1 ref +0 · 2 refs +8 · ≥3 refs +15 |

Two baseline rules override the arithmetic:

- Exact known-benign match — (check, target_type, target,
  observed) all equal a recorded benign baseline entry — caps
  the score at 5 (suppress), WHATEVER severity was claimed.
  This is the low-false-positive mechanism.
- Exact known-bad match floors the score at 80 (urgent).
  A baseline that records the same value as both benign and
  bad resolves to bad: triage fails toward surfacing.

Novelty labels: `known-benign` / `known-bad` (exact observed
match), `changed` (the target+check is in the baseline but this
observed value is not), `novel` (no baseline entry at all).

## Tiers

| Tier | Score | Meaning for the human |
|---|---|---|
| `urgent` | ≥ 70 | page now |
| `review` | 45–69 | queue for review |
| `watch` | 20–44 | digest; low action |
| `suppress` | < 20 | no action; kept and counted |

`review` + `urgent` are the surfaced tiers; `watch` + `suppress`
are the calm (low/no-action) tiers. Suppressed findings are never
dropped — they stay in the report with their reasons.

## Grouping

`triage()` groups by (check, target_type, target). A group's
score is its strongest member's score plus +10 when the group
holds ≥3 distinct evidence refs and +10 for ≥2 distinct
detectors — independent corroboration is the recorded reason
duplicates escalate. A group whose members are ALL exact
known-benign matches stays suppressed; a group containing a
known-bad member is floored to urgent. Groups are ordered by
descending score, then key.

## Baseline corpus — measured rates

`tests/fixtures/lif0802/corpus.json` carries 14 fixture baseline
entries and 24 labelled cases (12 ground-truth benign, 12
ground-truth bad). `evaluate_corpus()` triages per finding and
reports counts; the tests pin the counts this run produces:

| Metric | Measured |
|---|---|
| Benign calm (low/no action) | 11/12 = 91.7% |
| False positives | 1/12 = 8.3% |
| Bad surfaced (review/urgent) | 11/12 = 91.7% |
| False negatives (paging tiers) | 1/12 = 8.3% |

Stated rates for this baseline: benign calm ≥ 90%, FP ≤ 10%,
bad surfaced ≥ 90%, FN ≤ 10% — met at fixture scope.

The two misses are deliberate, documented hard cases in the
corpus itself: a novel high-claimed benign finding with
corroboration and NO baseline entry surfaces for review (the
remedy is recording the baseline entry, not weakening the
threshold), and a low-claimed novel bad finding with a single
source stays at watch — visible in the digest, not paged (the
remedy is corroboration or a known-bad signature). Standing
negative control: with an EMPTY baseline the measured benign
calm rate falls to 9/12 = 75%, proving the baseline does the
calming.

## Limitations

Contract/test level only (evidence ladder: reproducer +
lab-verified at fixture scope). The baseline entries and
findings are fixture records, not a production baseline for any
real machine; scores are a ranking heuristic with stated point
values, not probabilities. Triage consumes the finding shape
above; when LIF-0801 banks, its detector output must be adapted
to this shape (or this module extended) — no compatibility with
unbanked code is claimed. Triage never acts and proposes no
response; LIF-0803 + the P4 policy engine own that. Human
review pending.
