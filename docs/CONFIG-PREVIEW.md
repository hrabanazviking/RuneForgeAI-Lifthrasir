# Configuration validation and diff preview (LIF-0503)

SPDX-License-Identifier: GPL-2.0-only

Status: contract-level implementation in
`src/lifthrasir/configpreview.py` (preview schema
`lifthrasir.config-preview.v0.1`). Evidence status: **reproducer /
lab-verified on fixtures only** -- no live-host verification is
claimed, and no human review has happened yet.

## Purpose

Before any Eir repair recipe (LIF-0501) may propose editing a
configuration, two questions must have deterministic answers:

1. Is the proposed configuration text valid?
2. Exactly what would change, key by key and line by line?

This slice answers both, on **in-memory copies only**. The module
never reads, writes, or modifies a file; there is no apply API.
Real host configurations are never its input: callers pass fixture
copies, guest copies, or store records, and targets naming
protected paths (master roadmap section 0 invariant 2, reusing the
LIF-0401 protected-path list) are refused by name.

## Formats

| Format | Shape | Notes |
|---|---|---|
| `ini` | `[Section]` + `key=value` | systemd-unit / INI style; keys reported as `Section.key` |
| `keyvalue` | flat `key=value` | sysctl-style `.conf`; section headers are an error |
| `json` | JSON object | flattened to dotted keys (`a.b[0]`); top level must be an object |

Any other format name is refused (`UnsupportedFormatError`) --
deny by default, never a guessed parser.

## Validation rules

Every problem is a structured issue: stable `code`, 1-based `line`
(0 where no line applies, e.g. JSON duplicates), `message`, and
`severity` (`error` or `warning`). A report is `valid` iff it has
no errors; warnings never block.

- `empty-config` (error): text is empty or whitespace only.
- `missing-equals`, `bad-key`, `bad-section-header`,
  `key-outside-section`, `unexpected-section` (errors): line shape.
- `duplicate-key`, `duplicate-section` (errors): a repeated key is
  ambiguous -- the first definition wins in the parsed map and the
  repeat is an error, never a silent overwrite.
- JSON: `json-syntax` (with the decoder's line/column),
  `duplicate-key`, `json-top-level`.
- `empty-value` (warning): `key=` with nothing after it; legal in
  several real formats (e.g. resetting a systemd directive), so it
  is surfaced, not blocked.
- Resource caps: 256 KiB, 10,000 lines, 4,096 keys per text; NUL
  bytes are refused. Oversize input raises `OversizeConfigError`;
  nothing is silently truncated.

Validation is syntactic plus these structural rules. It does NOT
prove a configuration is semantically right for its daemon, safe,
or authorised -- policy (LIF-0402) and approval (LIF-0404) own
those questions.

## Preview

`preview_config_change(current, proposed, format, target)` returns:

- SHA-256 digests of both texts;
- validation reports for both texts;
- the semantic change list (`added` / `removed` / `changed` per
  flattened key, sorted by key);
- a unified diff (`a/<target>` -> `b/<target>`);
- a verdict: `no-change` (identical digests), `ready` (both valid,
  something changes -- the only `applicable=True` verdict),
  `blocked-invalid` (proposed text invalid), or
  `blocked-current-invalid` (current text invalid, so no baseline
  can be trusted). A blocked preview still shows its diff for
  inspection; it can never be applied on this module's authority.

`render_preview` renders the same content as deterministic plain
text for the approval surface: a user never approves a change they
cannot read.

Comment-only edits change the digest and the text diff but produce
an empty semantic change list; the preview says so honestly rather
than inventing key changes.

## Limits and undo

- Fixture/lab scope only; parser coverage is the three formats
  above (no YAML/TOML/XML, no include directives, no line
  continuations, no systemd specifiers expansion).
- JSON semantic values are compared by canonical JSON spelling of
  the flattened leaf, so `1` vs `1.0` reads as a change.
- Undo: this slice changes no system state; undo is reverting its
  commit (module, spec, fixtures, tests).
