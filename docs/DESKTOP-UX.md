# KDE/Qt Interface, Accessibility and Local-Only UX (LIF-1202)

Machine-readable half: `src/lifthrasir/desktopux.py`
(schema `lifthrasir.desktop-ux.v0.1`). Fixture:
`tests/fixtures/lif1202/desktop.json`. Tests:
`tests/test_desktop_ux.py` pin this document to the module.

## Honest status

This slice defines the desktop interface as contracts, rules and
guarantees at descriptor level. It is **not a running KDE
application**: no GUI is launched, no Qt library is imported, no
window is rendered and no pixel is measured. Accessibility
figures in a descriptor are *declared* values, checked against
the contract thresholds below; an implementation slice must
still prove them on screen before anyone calls the interface
accessible in fact. Evidence status: lab-verified at contract
level only (purpleraider, recorded fixtures) — not
cross-platform-verified, not human-reviewed.

## Why native KDE/Qt, and why no webview

The master roadmap (section 4) fixes the UI line: local CLI
first, then a KDE/Qt front end; a webview is admitted only if
its local-only network security is convincing. The read-only CLI
(LIF-0205, `ui/heimdall_cli.py`) is the banked first step. No
convincing local-only webview proof exists in this repo, so the
contract admits exactly one toolkit, `kde-qt`, and refuses
`webview`, `electron`, `web` and every other toolkit by name.

## Local-only guarantees

- The only network mode is `none`: the interface opens no
  socket, fetches nothing, and checks for no updates.
- `telemetry`, `analytics`, `crash_reporting` and kin must be
  absent or false — off by contract, not by preference.
- Every data source is a named local kind: `local-event-store`,
  `approval-ledger`, `transaction-store`, `local-config`,
  `static-bundle`, `fixture-dataset`. Remote or unknown sources
  are refused.
- Any remote-scheme URL (`http://`, `https://`, `ws://`,
  `wss://`, `ftp://`) anywhere in the descriptor, and any set
  remote key (`endpoint`, `url`, `webhook`, `update_url`, …),
  is refused by name.
- User files and private logs stay local by default (master
  roadmap invariant 6). Federation is opt-in P13 work with a
  scrubbed-payload preview; it is not part of this surface.

## The closed view surface

Nine views, each bound to exactly one contract source. A
descriptor missing a view, adding an unknown view, or binding a
view to another source is refused — a partial shell is not the
KDE/Qt UX.

| View | Source | Carries |
|---|---|---|
| `overview` | local-event-store | status-banner, list |
| `incidents` | local-event-store | list, status-banner |
| `incident-detail` | local-event-store | detail, text |
| `sensors` | local-event-store | sensor-table |
| `approvals` | approval-ledger | list, approval-prompt |
| `approval-detail` | approval-ledger | approval-prompt, diff-preview |
| `recovery` | transaction-store | list, approval-prompt |
| `settings` | local-config | settings-form |
| `about` | static-bundle | text |

Widget kinds: `list`, `detail`, `status-banner`,
`approval-prompt`, `diff-preview`, `sensor-table`,
`settings-form`, `emergency-stop`, `text`.

Observation views present the LIF-0205 surfaces (incident
list/details, sensor permissions at risk tiers L0/L1). As with
the CLI, the interface *reports* sensor permissions; it grants
nothing and performs no action.

## No execute affordance; approval is the only consequential path

Widget actions are a closed set: `navigate`, `observe`,
`local-setting`, `request-approval`, `emergency-stop`, `none`.
There is deliberately **no `execute` action**: execution belongs
to the policy engine and the broker (P4), never to a widget. An
`execute` action, or an approval request outside an
approval-prompt widget, is refused by name.

Approval requests live only in `approvals`, `approval-detail`
and `recovery`, and render the LIF-0404 approval UX sections in
exact order — proposal, scope, risk-consent, rollback,
verification, expiry, reference — led by a plain-language
summary. The user never approves an opaque blob.

## Emergency stop

Master roadmap invariant 8: the stop works without models,
network, embeddings or inference. The descriptor must name a
real, persistent `emergency-stop` widget (in the fixture,
`global-stop`) and declare `requires_model: false` and
`requires_network: false`. Anything else is refused.

## Accessibility rules (checked, by id)

- `keyboard-complete` — every interactive widget is
  keyboard-operable, and the declared focus order covers every
  interactive widget exactly once.
- `accessible-name` — every interactive widget carries a
  non-empty accessible name.
- `visible-focus` — a visible focus indicator is declared;
  `none` is refused.
- `contrast` — declared contrast meets the WCAG AA floors:
  4.5:1 for text, 3.0:1 for large text/UI; body text stays in
  the 14–18 px band and the corner cut in the 6–12 px band.
- `no-color-only` — every status-banner declares a redundant
  channel (`text`, `icon`, `pattern` or `shape`); colour is
  never the only status signal.
- `target-size` — interactive targets are at least 44 px.
- `text-scaling` — layout is declared to hold at 200% text
  scaling without loss.
- `reduced-motion` — the reduced-motion preference is honoured;
  ceremonial motion is rare and never mandatory.
- `screen-reader-announcements` — status changes are announced
  (live region `polite` or `assertive`, never `off`).
- `grayscale-coherent` — the theme is declared coherent in
  grayscale and with glow/art disabled (design ship gate).
- `plain-language-approval` — the approval prompt leads with a
  plain-language summary before any technical detail.

Design tokens pinned by the module (`DESIGN_TOKENS`): targets
≥ 44 px, controls 40–48 px, body text 14–18 px, corner cut
6–12 px, at most 3 frame strengths, accents 5–12% of area,
motion bands 80–140 ms / 160–220 ms, ceremonial 450–800 ms,
text scaling to 200%. These are the Cyber-Viking design numbers
carried in the campaign's standing design law, encoded as
contract constants; they do not appear in this repo's earlier
slices and are not claimed as repo-derived.

## Limitations

- Contract level only: widget behaviour, rendering, real Qt
  accessibility-tree exposure, real screen-reader behaviour and
  measured contrast all remain unproven until an implementation
  slice renders the interface and measures it.
- Declared theme values are trusted as declarations; the
  validator checks them against thresholds, it cannot detect a
  lying theme.
- The descriptor schema is v0.1 and closed: new views, widget
  kinds or actions need a schema revision, not a quiet addition.
- Settings writes are local-config only by contract; enforcing
  that in a running build is the implementation's job, policed
  by the P4 policy/broker boundary, not by this contract alone.

## Undo

Revert the LIF-1202 commit: the slice is additive (one module,
one document, one test file, one fixture) and changes no host
state.
