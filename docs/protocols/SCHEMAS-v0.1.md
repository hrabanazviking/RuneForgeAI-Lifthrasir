# Core Record Schemas v0.1 — Incident, Hypothesis, Plan, Evidence (LIF-0004)

**Project:** Lífþrasir — The Self-Evolving Linux System
**Slice:** LIF-0004 (Phase P0) — incident, hypothesis, plan and evidence schema v0.1.
**Status:** Version 0.1 contract baseline. These are data-format definitions only; nothing here asserts an implemented service, event bus, or store. The validation run in `tests/test_schemas_v01.py` is the slice evidence that the examples validate.
**Date:** 2026-11-12
**Sources:** `research/25-API-AND-EVENT-SCHEMAS.md` (design well), `docs/architecture/ADR-0002-architecture.md` (message ownership), `docs/CHARTER.md` (scope, separation of powers), `docs/RISK-MATRIX.md` (risk tiers L0–L5 and consent modes, LIF-0003), `ROADMAP-TO-COMPLETION.md` sections 0, 3 and 5.

## What this slice delivers

Machine-checkable schemas for the four core record types every later phase builds on, at version **0.1**:

| Record | Schema file | Envelope value (`schema`) | Produced by (ADR-0002 sole owner) | Consumed by |
|---|---|---|---|---|
| Incident | `schemas/v0.1/incident.schema.json` | `lifthrasir.incident.v0.1` | Correlator, within the observation plane | UI, Mimir, Replicater |
| Hypothesis | `schemas/v0.1/hypothesis.schema.json` | `lifthrasir.hypothesis.v0.1` | Replicater (and its bounded subagents) | Mimir, Eir, Thor, UI |
| Plan | `schemas/v0.1/plan.schema.json` | `lifthrasir.plan.v0.1` | Eir (repair) or Thor (containment proposal) | Policy engine |
| Evidence | `schemas/v0.1/evidence.schema.json` | `lifthrasir.evidence.v0.1` | Heimdall (`lifthrasir-sensor`) for observations; the broker path for verification and journal evidence | Mimir store, correlator, UI |

Examples live in `examples/v0.1/valid/` (one per record type, forming one cross-referentially consistent incident story) and `examples/v0.1/invalid/` (records that must fail, named for the rule they break).

Downstream slices that build on this contract: the typed event bus (LIF-0201), the local evidence store (LIF-0301), causal hypothesis records (LIF-0305), and signed plan references (LIF-0404).

## Format choice: JSON Schema, and why

The schemas are **JSON Schema, draft 2020-12**, one self-contained file per record type. Justification:

- Research/25 already fixes the wire shape: versioned JSON envelopes, strict validation of all inputs, and metadata that carries references and hashes rather than binary payloads. JSON Schema is the machine-checkable form of exactly that contract.
- It is the format the rest of the roadmap assumes: the event bus (LIF-0201) is typed and schema-versioned, and the evidence store (LIF-0301) stores these records in SQLite; both can consume the same schema files without translation.
- A maintained validator (`jsonschema`, Python) already exists on the build machine, so the contract is executable today with no new dependency and no hand-rolled checker to audit.
- Self-contained files (no cross-file references) keep each schema independently loadable, hashable, and versionable — the property the evidence pack and later migrations rely on.

## Versioning discipline

- Every record carries two version fields, both pinned by the tests: `schema` (the envelope name, ending in `.v0.1`) and `schema_version` (the constant string `0.1`). A record that claims any other version fails validation against these files.
- Schema files live under a version directory (`schemas/v0.1/`) and each carries an `$id` containing its version. A future v0.2 gets a new directory and new `$id` values; v0.1 files are never edited in place to change meaning, so stored records stay interpretable (research/25 compatibility rule: migrations preserve original audit records, hashes and causality).
- Compatibility follows research/25: additive, explicitly advertised fields may be tolerated by consumers in later versions; unknown action verbs in plans must always be rejected — in v0.1 the plan `action_verb` is a free string at the schema level because the typed action catalog is LIF-0401, and this limitation is recorded below rather than hidden.
- The tests pin the version: changing a schema file's `$id`, a record's `schema` constant, or `schema_version` without a version bump fails the suite.

## Shared conventions

- **Envelope:** every record has `schema`, `schema_version`, its own typed identifier, and `created_at` (evidence uses `recorded_at`). Timestamps are RFC 3339 date-time strings.
- **Identifiers:** typed prefixes — `inc-`, `hyp-`, `plan-`, `ev-` — followed by lowercase alphanumerics and hyphens. Cross-references between records use these identifiers.
- **Strictness:** `additionalProperties` is false at the top level of every record; unknown fields fail validation (research/25: validate all inputs strictly).
- **Evidence ladder:** `evidence_status` (hypothesis and evidence records) uses the master roadmap section 5 ladder verbatim: idea, hypothesis, reproducer, lab-verified, cross-platform-verified, human-reviewed, deployed-with-monitoring, upstream-submitted, upstream-accepted. A record displays only the rung its artifacts prove.
- **Risk and consent (plan records):** `risk_level` is one of L0–L5 and `consent_mode` one of the seven modes in `docs/RISK-MATRIX.md`. An example's consent may be stricter than its tier minimum, never weaker — the schema encodes that floor.

## Cross-field rules v0.1 can check (encoded in the schemas)

JSON Schema `if`/`then` rules, all covered by invalid examples:

1. Incident: a `resolved` or `closed` incident requires `resolved_at`; an `open` or `investigating` incident must not carry `resolved_at`.
2. Hypothesis: status `supported` requires at least one `evidence_for` reference; status `refuted` requires at least one `evidence_against` reference.
3. Plan: the declared `consent_mode` must be at or above the consent floor for the declared `risk_level` (all six tiers encoded).
4. Evidence: a `differential-run` requires a `baseline_evidence_id` and a non-empty `tool_versions`; a `test-run` or `negative-control` requires a non-empty `tool_versions` (master roadmap section 5: exact tool versions are part of a proof).

Plus per-field rules: required fields, enums, the sha256 digest pattern on evidence (`sha256:` followed by 64 lowercase hex characters), identifier patterns on every reference field, and `confidence` bounded to 0–1 on hypotheses.

## What v0.1 cannot check (honest limits)

- **Referential existence.** A JSON Schema can check that `hypothesis_ids` entries are well-formed identifiers; it cannot check that such a hypothesis exists. A plan referencing a nonexistent hypothesis is a data-integrity concern for the store and bus layers (LIF-0301, LIF-0201, LIF-0404), not for a single-record schema. The test suite demonstrates the distinction: it runs a separate referential-integrity check over the valid example set (every reference resolves within the set) and shows a dangling reference being caught by that check, while the schema alone accepts the well-formed record. This boundary is deliberate, not an oversight.
- **Time ordering.** JSON Schema cannot compare two timestamps, so `expires_at` after `created_at`, and `resolved_at` after `observed_at`, are store/bus responsibilities in v0.1.
- **Digest truth.** The schema checks the digest format only; that the digest matches the stored payload is the evidence store's job (LIF-0301, append-only hash-linked records).
- **Action vocabulary.** Plan step `action_verb` values are not enumerated until the typed action catalog exists (LIF-0401); policy evaluation (LIF-0402) remains the authority that rejects unknown verbs, per research/25.
- **Uniqueness and authorization.** Identifier uniqueness, who may produce a record (ADR-0002 sole-owner rules), and consent authenticity are runtime and policy concerns; the schema defines the shape those checks consume.

## Issue record — LIF-0004

```yaml
id: LIF-0004
phase: P0
goal: "Define incident, hypothesis, plan and evidence schema v0.1."
dependencies: []
risk_tier: L0
scope: "Four JSON Schema (draft 2020-12) files under docs/protocols/schemas/v0.1/, this specification, validating examples under docs/protocols/examples/v0.1/, and tests in tests/test_schemas_v01.py. Documentation, data-format and test work only; no code service, no system change, no README.md modification."
test_fixture: "tests/test_schemas_v01.py validates every valid example against its schema, asserts every invalid example fails, pins the version fields, checks the schemas themselves against the draft 2020-12 meta-schema, and runs a referential-integrity check over the valid example set."
expected_evidence: "Full-suite pytest log in the team worktree hidden_files/ showing the banked tests plus the new schema tests passing; artifact hashes recorded in the team CAMPAIGN_STATE.md."
negative_control: "A valid example with a required field stripped (and an invalid example relied on as if valid) must fail validation; demonstrated in tests and logged separately in hidden_files/."
recovery_or_undo: "Revert the slice commit (git revert) — schemas, examples and tests only, no system state changed."
```
