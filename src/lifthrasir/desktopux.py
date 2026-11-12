# SPDX-License-Identifier: GPL-2.0-only
"""KDE/Qt interface contracts, accessibility rules, local-only UX (LIF-1202).

Phase P12. Master roadmap section 4 fixes the UI technology line:
"Local CLI first, then KDE/Qt front end -- Webview only if
local-only network security is convincing." The read-only CLI
(LIF-0205, ui/heimdall_cli.py) is the banked first step; this slice
is the contract layer for the KDE/Qt step that follows it.

WHAT THIS SLICE IS -- AND IS NOT:

* It is interface CONTRACTS, accessibility RULES and local-only
  GUARANTEES as tested data and code: a closed descriptor schema
  for the desktop front end, validators that refuse non-compliant
  descriptors by name, and a canonical compliant fixture.
* It is NOT a running KDE application. No GUI is launched, no Qt
  library is imported, no window is rendered, and no pixel is
  measured by this slice. Accessibility figures in a descriptor
  are DECLARED values checked against the contract thresholds;
  they are not measurements of a rendered interface. A future
  implementation slice must still prove them on screen.

The contract binds three banked surfaces:

* Observation: the views present the LIF-0205 read-only surfaces
  (incident list/details, sensor permissions L0/L1) and the local
  stores behind them. The UI grants nothing and performs no
  action: sensor permissions are reported, never granted, exactly
  as the CLI states.
* Approval: any consequential step is expressed ONLY as a
  request for approval rendered with the LIF-0404 approval UX --
  the same seven prompt sections, in the same order (proposal,
  scope, risk-consent, rollback, verification, expiry,
  reference), with a plain-language summary first. The UI has no
  "execute" affordance at all: execution belongs to the policy
  engine and broker (P4), never to a widget.
* Emergency stop: master roadmap invariant 8 -- the stop works
  without models, network, embeddings or inference. The contract
  therefore requires a persistent emergency-stop affordance whose
  descriptor declares it model-free and network-free.

LOCAL-ONLY GUARANTEES (invariant 6: user files and private logs
stay local by default; federation is opt-in and is P13, NOT this
slice): the descriptor's network mode is the single value "none";
telemetry, analytics and crash reporting must be absent or false;
every data source is one of the named local kinds; and any URL
with a remote scheme (http/https/ws/wss/ftp) anywhere in the
descriptor is refused by name. The toolkit is native KDE/Qt
only: a webview/electron/web toolkit claim is refused, because
the roadmap admits a webview only if its local-only security is
convincing, and no such proof exists in this repo.

DESIGN TOKENS: the numeric thresholds below (target size, text
sizes, corner cut, motion bands, accent budget) are the
Cyber-Viking design numbers carried in the campaign's standing
design law (body text 14-18 px, targets >= 44 px, controls
40-48 px, corner cut 6-12 px, <= 3 frame strengths, accents
5-12% of area, motion 80-140 / 160-220 ms, ceremonial
450-800 ms and rare, text scaling held at 125-200%). They are
encoded here as contract constants so an implementation can be
tested against them; they do not appear in this repo's earlier
slices and are not claimed as repo-derived. Contrast floors are
the WCAG 2.x AA values (4.5:1 text, 3:1 large text/UI).

Home: ``src/lifthrasir`` beside the other contract modules
(LIF-1101 distroprobes is the sibling pattern); the human half is
``docs/DESKTOP-UX.md`` and the tests pin the two together. This
module ships WITHOUT editing ``__init__.py``: the seat unions
exports at banking (see the union flag in the team state file).
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

DESKTOP_SCHEMA = "lifthrasir.desktop-ux.v0.1"
DESKTOP_SCHEMA_VERSION = "0.1"
DESKTOP_VERSION = "1"

TOOLKIT = "kde-qt"
TOOLKITS = ("kde-qt",)
NETWORK_MODES = ("none",)

APP_ID_RE = re.compile(r"^[a-z][a-z0-9-]*(\.[a-z][a-z0-9-]*)+$")
WIDGET_ID_RE = re.compile(r"^[a-z][a-z0-9-]*$")
REMOTE_URL_RE = re.compile(r"(?i)\b(?:https?|wss?|ftp)://")

MAX_VIEWS = 16
MAX_WIDGETS_PER_VIEW = 64
MAX_NAME_CHARS = 120
MAX_DESCRIPTOR_CHARS = 262144

# --- design tokens (see module docstring for provenance) --------
MIN_TARGET_PX = 44
CONTROL_HEIGHT_MIN_PX = 40
CONTROL_HEIGHT_MAX_PX = 48
BODY_TEXT_MIN_PX = 14
BODY_TEXT_MAX_PX = 18
CORNER_CUT_MIN_PX = 6
CORNER_CUT_MAX_PX = 12
FRAME_STRENGTHS_MAX = 3
ACCENT_AREA_MIN_PCT = 5
ACCENT_AREA_MAX_PCT = 12
TEXT_SCALE_REQUIRED_PCT = 200
MIN_CONTRAST_TEXT = 4.5
MIN_CONTRAST_LARGE = 3.0
MOTION_FAST_MS = (80, 140)
MOTION_STANDARD_MS = (160, 220)
MOTION_CEREMONIAL_MS = (450, 800)

DESIGN_TOKENS = {
    "min_target_px": MIN_TARGET_PX,
    "control_height_min_px": CONTROL_HEIGHT_MIN_PX,
    "control_height_max_px": CONTROL_HEIGHT_MAX_PX,
    "body_text_min_px": BODY_TEXT_MIN_PX,
    "body_text_max_px": BODY_TEXT_MAX_PX,
    "corner_cut_min_px": CORNER_CUT_MIN_PX,
    "corner_cut_max_px": CORNER_CUT_MAX_PX,
    "frame_strengths_max": FRAME_STRENGTHS_MAX,
    "accent_area_min_pct": ACCENT_AREA_MIN_PCT,
    "accent_area_max_pct": ACCENT_AREA_MAX_PCT,
    "text_scale_required_pct": TEXT_SCALE_REQUIRED_PCT,
    "min_contrast_text": MIN_CONTRAST_TEXT,
    "min_contrast_large": MIN_CONTRAST_LARGE,
    "motion_fast_ms": list(MOTION_FAST_MS),
    "motion_standard_ms": list(MOTION_STANDARD_MS),
    "motion_ceremonial_ms": list(MOTION_CEREMONIAL_MS),
}

# --- interface contract: views, sources, widgets, actions -------
# Each view: (data_source, may_request_approval). Observation views
# never request approval; only the approvals and recovery views
# may carry approval-prompt widgets.
VIEWS = (
    "overview", "incidents", "incident-detail", "sensors",
    "approvals", "approval-detail", "recovery", "settings",
    "about",
)
VIEW_SOURCES = {
    "overview": "local-event-store",
    "incidents": "local-event-store",
    "incident-detail": "local-event-store",
    "sensors": "local-event-store",
    "approvals": "approval-ledger",
    "approval-detail": "approval-ledger",
    "recovery": "transaction-store",
    "settings": "local-config",
    "about": "static-bundle",
}
APPROVAL_VIEWS = ("approvals", "approval-detail", "recovery")
DATA_SOURCES = (
    "local-event-store", "approval-ledger", "transaction-store",
    "local-config", "static-bundle", "fixture-dataset",
)
WIDGET_KINDS = (
    "list", "detail", "status-banner", "approval-prompt",
    "diff-preview", "sensor-table", "settings-form",
    "emergency-stop", "text",
)
# There is deliberately no "execute" action: the UI can navigate,
# observe, change a local setting, request approval, or stop.
ACTION_KINDS = (
    "navigate", "observe", "local-setting", "request-approval",
    "emergency-stop", "none",
)
INTERACTIVE_KINDS = (
    "list", "sensor-table", "approval-prompt", "settings-form",
    "emergency-stop",
)
APPROVAL_SECTIONS = (
    "proposal", "scope", "risk-consent", "rollback",
    "verification", "expiry", "reference",
)
REDUNDANT_CHANNELS = ("text", "icon", "pattern", "shape")
LIVE_REGIONS = ("polite", "assertive", "off")

A11Y_RULES = (
    "keyboard-complete", "accessible-name", "visible-focus",
    "contrast", "no-color-only", "target-size", "text-scaling",
    "reduced-motion", "screen-reader-announcements",
    "grayscale-coherent", "plain-language-approval",
)

FORBIDDEN_REMOTE_KEYS = (
    "endpoint", "url", "webhook", "feed_url", "api_base",
    "remote_url", "update_url",
)
TELEMETRY_KEYS = ("telemetry", "analytics", "crash_reporting",
                  "usage_reporting", "phone_home")


class DesktopUXError(Exception):
    """Base class for all named desktop-UX refusals."""


class MalformedDesktopError(DesktopUXError):
    pass


class UnknownViewError(DesktopUXError):
    pass


class UnknownWidgetError(DesktopUXError):
    pass


class LocalOnlyViolationError(DesktopUXError):
    pass


class AccessibilityViolationError(DesktopUXError):
    pass


class ApprovalBindingError(DesktopUXError):
    pass


class EmergencyStopError(DesktopUXError):
    pass


@dataclass(frozen=True)
class WidgetContract:
    widget_id: str
    kind: str
    action: str
    accessible_name: str
    keyboard_operable: bool
    min_target_px: int
    redundant_channel: Optional[str]
    live_region: str

    @property
    def interactive(self) -> bool:
        return self.kind in INTERACTIVE_KINDS or self.action not in (
            "none", "observe")


@dataclass(frozen=True)
class ViewContract:
    view_id: str
    data_source: str
    widgets: Tuple[WidgetContract, ...]


@dataclass(frozen=True)
class DesktopDescriptor:
    app_id: str
    toolkit: str
    network: str
    views: Tuple[ViewContract, ...]
    global_widgets: Tuple[WidgetContract, ...]
    focus_order: Tuple[str, ...]
    theme: Dict[str, Any]
    approval_sections: Tuple[str, ...]
    plain_language_summary: bool
    emergency_stop: Dict[str, Any]
    raw: Dict[str, Any]

    def all_widgets(self) -> List[WidgetContract]:
        return ([w for v in self.views for w in v.widgets]
                + list(self.global_widgets))

    def widget_ids(self) -> List[str]:
        return [w.widget_id for w in self.all_widgets()]

    def digest(self) -> str:
        return descriptor_digest(self.raw)


@dataclass(frozen=True)
class A11yFinding:
    rule: str
    where: str
    detail: str


@dataclass(frozen=True)
class AuditReport:
    app_id: str
    findings: Tuple[A11yFinding, ...]

    @property
    def ok(self) -> bool:
        return not self.findings


def _fail(exc, msg):
    raise exc(msg)


def _scan_remote(value, path):
    """Refuse any remote-scheme URL anywhere in the descriptor."""
    if isinstance(value, str):
        if REMOTE_URL_RE.search(value):
            _fail(LocalOnlyViolationError,
                  f"local-only violation: remote URL at {path}: "
                  f"{value!r} -- the desktop UX has no network "
                  "surface; federation is opt-in P13 work, not P12")
    elif isinstance(value, dict):
        for key, sub in value.items():
            if key in FORBIDDEN_REMOTE_KEYS and sub not in (
                    None, "", False):
                _fail(LocalOnlyViolationError,
                      f"local-only violation: remote key {key!r} "
                      f"set at {path}")
            _scan_remote(sub, f"{path}.{key}")
    elif isinstance(value, (list, tuple)):
        for i, sub in enumerate(value):
            _scan_remote(sub, f"{path}[{i}]")


def _parse_widget(raw, view_id):
    if not isinstance(raw, dict):
        _fail(MalformedDesktopError,
              f"widget in view {view_id!r} is not an object")
    wid = raw.get("widget_id")
    if not isinstance(wid, str) or not WIDGET_ID_RE.match(wid):
        _fail(MalformedDesktopError,
              f"widget in view {view_id!r} has a bad widget_id: "
              f"{wid!r}")
    kind = raw.get("kind")
    if kind not in WIDGET_KINDS:
        _fail(UnknownWidgetError,
              f"widget {wid!r}: unknown kind {kind!r}; known: "
              f"{', '.join(WIDGET_KINDS)}")
    action = raw.get("action", "none")
    if action not in ACTION_KINDS:
        _fail(ApprovalBindingError,
              f"widget {wid!r}: action {action!r} is not a UI "
              "action -- the UI has no execute affordance; "
              "consequential steps are request-approval only, "
              "execution belongs to policy + broker (P4)")
    if action == "request-approval" and kind != "approval-prompt":
        _fail(ApprovalBindingError,
              f"widget {wid!r}: request-approval requires an "
              "approval-prompt widget rendering the LIF-0404 "
              "sections")
    if kind == "approval-prompt" and action != "request-approval":
        _fail(ApprovalBindingError,
              f"widget {wid!r}: an approval-prompt widget must "
              "carry the request-approval action")
    if kind == "emergency-stop" and action != "emergency-stop":
        _fail(EmergencyStopError,
              f"widget {wid!r}: an emergency-stop widget must "
              "carry the emergency-stop action")
    name = raw.get("accessible_name", "")
    if not isinstance(name, str) or len(name) > MAX_NAME_CHARS:
        _fail(MalformedDesktopError,
              f"widget {wid!r}: accessible_name must be a string "
              f"of at most {MAX_NAME_CHARS} chars")
    target = raw.get("min_target_px", 0)
    if not isinstance(target, int) or isinstance(target, bool):
        _fail(MalformedDesktopError,
              f"widget {wid!r}: min_target_px must be an int")
    channel = raw.get("redundant_channel")
    if channel is not None and channel not in REDUNDANT_CHANNELS:
        _fail(MalformedDesktopError,
              f"widget {wid!r}: redundant_channel {channel!r} "
              f"not in {REDUNDANT_CHANNELS}")
    live = raw.get("live_region", "off")
    if live not in LIVE_REGIONS:
        _fail(MalformedDesktopError,
              f"widget {wid!r}: live_region {live!r} not in "
              f"{LIVE_REGIONS}")
    return WidgetContract(
        widget_id=wid, kind=kind, action=action,
        accessible_name=name,
        keyboard_operable=bool(raw.get("keyboard_operable",
                                       False)),
        min_target_px=target, redundant_channel=channel,
        live_region=live)


def descriptor_from_dict(data):
    """Structural parse only; guarantees are checked separately."""
    if not isinstance(data, dict):
        _fail(MalformedDesktopError,
              "descriptor is not an object")
    if len(json.dumps(data)) > MAX_DESCRIPTOR_CHARS:
        _fail(MalformedDesktopError,
              f"descriptor exceeds {MAX_DESCRIPTOR_CHARS} chars")
    if data.get("schema") != DESKTOP_SCHEMA:
        _fail(MalformedDesktopError,
              f"descriptor schema {data.get('schema')!r} is not "
              f"{DESKTOP_SCHEMA!r}")
    app_id = data.get("app_id")
    if not isinstance(app_id, str) or not APP_ID_RE.match(app_id):
        _fail(MalformedDesktopError,
              f"bad app_id: {app_id!r}")
    toolkit = data.get("toolkit")
    if toolkit not in TOOLKITS:
        _fail(LocalOnlyViolationError,
              f"toolkit {toolkit!r} refused: the contract admits "
              "native kde-qt only -- a webview is admitted by the "
              "roadmap only if its local-only security is "
              "convincing, and no such proof exists in this repo")
    network = data.get("network")
    views_raw = data.get("views")
    if not isinstance(views_raw, list) or not views_raw:
        _fail(MalformedDesktopError, "descriptor has no views")
    if len(views_raw) > MAX_VIEWS:
        _fail(MalformedDesktopError,
              f"too many views: {len(views_raw)} > {MAX_VIEWS}")
    views = []
    seen_views, seen_widgets = set(), set()
    for vraw in views_raw:
        if not isinstance(vraw, dict):
            _fail(MalformedDesktopError, "view is not an object")
        vid = vraw.get("view_id")
        if vid not in VIEWS:
            _fail(UnknownViewError,
                  f"unknown view {vid!r}; known: "
                  f"{', '.join(VIEWS)}")
        if vid in seen_views:
            _fail(MalformedDesktopError,
                  f"duplicate view {vid!r}")
        seen_views.add(vid)
        source = vraw.get("data_source")
        if source not in DATA_SOURCES:
            _fail(LocalOnlyViolationError,
                  f"view {vid!r}: data_source {source!r} is not "
                  "a named local source -- remote or unknown "
                  "sources are refused")
        if source != VIEW_SOURCES[vid]:
            _fail(MalformedDesktopError,
                  f"view {vid!r}: data_source must be "
                  f"{VIEW_SOURCES[vid]!r} (its contract source), "
                  f"got {source!r}")
        widgets_raw = vraw.get("widgets")
        if not isinstance(widgets_raw, list) or not widgets_raw:
            _fail(MalformedDesktopError,
                  f"view {vid!r} has no widgets")
        if len(widgets_raw) > MAX_WIDGETS_PER_VIEW:
            _fail(MalformedDesktopError,
                  f"view {vid!r} exceeds "
                  f"{MAX_WIDGETS_PER_VIEW} widgets")
        widgets = []
        for wraw in widgets_raw:
            widget = _parse_widget(wraw, vid)
            if widget.widget_id in seen_widgets:
                _fail(MalformedDesktopError,
                      f"duplicate widget_id {widget.widget_id!r}")
            seen_widgets.add(widget.widget_id)
            if (widget.action == "request-approval"
                    and vid not in APPROVAL_VIEWS):
                _fail(ApprovalBindingError,
                      f"widget {widget.widget_id!r}: approval "
                      f"requests live only in {APPROVAL_VIEWS}, "
                      f"not in observation view {vid!r}")
            widgets.append(widget)
        views.append(ViewContract(vid, source, tuple(widgets)))
    missing = [v for v in VIEWS if v not in seen_views]
    if missing:
        _fail(MalformedDesktopError,
              f"descriptor is missing required views: "
              f"{', '.join(missing)} -- the contract surface is "
              "closed; a partial shell is not the KDE/Qt UX")
    global_widgets = []
    for wraw in data.get("global_widgets", []):
        widget = _parse_widget(wraw, "global")
        if widget.widget_id in seen_widgets:
            _fail(MalformedDesktopError,
                  f"duplicate widget_id {widget.widget_id!r}")
        seen_widgets.add(widget.widget_id)
        global_widgets.append(widget)
    focus = data.get("focus_order")
    if not isinstance(focus, list) or not all(
            isinstance(x, str) for x in focus):
        _fail(MalformedDesktopError,
              "focus_order must be a list of widget ids")
    theme = data.get("theme")
    if not isinstance(theme, dict):
        _fail(MalformedDesktopError, "theme is not an object")
    approval = data.get("approval")
    if not isinstance(approval, dict):
        _fail(MalformedDesktopError, "approval is not an object")
    stop = data.get("emergency_stop")
    if not isinstance(stop, dict):
        _fail(MalformedDesktopError,
              "emergency_stop is not an object")
    return DesktopDescriptor(
        app_id=app_id, toolkit=toolkit, network=network,
        views=tuple(views),
        global_widgets=tuple(global_widgets),
        focus_order=tuple(focus),
        theme=dict(theme),
        approval_sections=tuple(approval.get("sections", [])),
        plain_language_summary=bool(
            approval.get("plain_language_summary", False)),
        emergency_stop=dict(stop), raw=data)


def check_local_only(desc: DesktopDescriptor) -> None:
    if desc.network not in NETWORK_MODES:
        _fail(LocalOnlyViolationError,
              f"network mode {desc.network!r} refused: the only "
              "mode is 'none' -- the desktop UX opens no socket, "
              "fetches nothing, and checks for no updates")
    for key in TELEMETRY_KEYS:
        if desc.raw.get(key):
            _fail(LocalOnlyViolationError,
                  f"local-only violation: {key} is enabled -- "
                  "telemetry, analytics and crash reporting are "
                  "off by contract, not by preference")
    _scan_remote(desc.raw, "$")


def check_emergency_stop(desc: DesktopDescriptor) -> None:
    stop = desc.emergency_stop
    wid = stop.get("widget_id")
    if wid not in desc.widget_ids():
        _fail(EmergencyStopError,
              f"emergency_stop widget_id {wid!r} is not a "
              "declared widget -- the stop must be a real, "
              "persistent affordance (invariant 8)")
    if stop.get("requires_model") or stop.get("requires_network"):
        _fail(EmergencyStopError,
              "emergency stop must work without models and "
              "without network (invariant 8); the descriptor "
              "declares otherwise")


def check_approval_binding(desc: DesktopDescriptor) -> None:
    if desc.approval_sections != APPROVAL_SECTIONS:
        _fail(ApprovalBindingError,
              "approval sections must be exactly the LIF-0404 "
              f"sections in order {APPROVAL_SECTIONS}, got "
              f"{desc.approval_sections} -- the user never "
              "approves an opaque blob")
    if not desc.plain_language_summary:
        _fail(AccessibilityViolationError,
              "rule plain-language-approval: the approval prompt "
              "must lead with a plain-language summary before "
              "any technical detail")
    prompts = [w for w in desc.all_widgets()
               if w.kind == "approval-prompt"]
    if not prompts:
        _fail(ApprovalBindingError,
              "no approval-prompt widget declared -- the "
              "approvals surface is part of the closed contract")


def check_accessibility(desc: DesktopDescriptor) -> List[A11yFinding]:
    """Collect accessibility findings; empty means compliant."""
    findings: List[A11yFinding] = []

    def add(rule, where, detail):
        findings.append(A11yFinding(rule, where, detail))

    interactive = [w for w in desc.all_widgets() if w.interactive]
    for w in desc.all_widgets():
        if w.interactive:
            if not w.keyboard_operable:
                add("keyboard-complete", w.widget_id,
                    "interactive widget is not keyboard-operable")
            if not w.accessible_name.strip():
                add("accessible-name", w.widget_id,
                    "interactive widget has no accessible name")
            if w.min_target_px < MIN_TARGET_PX:
                add("target-size", w.widget_id,
                    f"target {w.min_target_px}px < "
                    f"{MIN_TARGET_PX}px minimum")
        if w.kind == "status-banner":
            if w.redundant_channel is None:
                add("no-color-only", w.widget_id,
                    "status is carried by colour alone; a "
                    "redundant channel (text/icon/pattern/shape) "
                    "is required -- colour is never the only "
                    "status signal")
            if w.live_region == "off":
                add("screen-reader-announcements", w.widget_id,
                    "status changes are not announced (live "
                    "region is off)")
    focus = list(desc.focus_order)
    want = [w.widget_id for w in interactive]
    if sorted(focus) != sorted(want):
        add("keyboard-complete", "$.focus_order",
            "focus order must cover every interactive widget "
            f"exactly once; missing="
            f"{sorted(set(want) - set(focus))} extra="
            f"{sorted(set(focus) - set(want))} duplicates="
            f"{sorted({x for x in focus if focus.count(x) > 1})}")
    theme = desc.theme
    if theme.get("focus_indicator") in (None, "", "none"):
        add("visible-focus", "$.theme",
            "no visible focus indicator declared")
    body = theme.get("body_text_px")
    if not isinstance(body, (int, float)) or isinstance(
            body, bool) or not (
            BODY_TEXT_MIN_PX <= body <= BODY_TEXT_MAX_PX):
        add("contrast", "$.theme",
            f"body_text_px {body!r} outside "
            f"{BODY_TEXT_MIN_PX}-{BODY_TEXT_MAX_PX}px")
    ct = theme.get("contrast_text")
    if not isinstance(ct, (int, float)) or isinstance(
            ct, bool) or ct < MIN_CONTRAST_TEXT:
        add("contrast", "$.theme",
            f"declared text contrast {ct!r} < "
            f"{MIN_CONTRAST_TEXT}:1 (WCAG AA, declared value -- "
            "not a rendered measurement)")
    cl = theme.get("contrast_large")
    if not isinstance(cl, (int, float)) or isinstance(
            cl, bool) or cl < MIN_CONTRAST_LARGE:
        add("contrast", "$.theme",
            f"declared large-text contrast {cl!r} < "
            f"{MIN_CONTRAST_LARGE}:1 (WCAG AA)")
    cut = theme.get("corner_cut_px")
    if not isinstance(cut, (int, float)) or isinstance(
            cut, bool) or not (
            CORNER_CUT_MIN_PX <= cut <= CORNER_CUT_MAX_PX):
        add("contrast", "$.theme",
            f"corner_cut_px {cut!r} outside "
            f"{CORNER_CUT_MIN_PX}-{CORNER_CUT_MAX_PX}px "
            "(design token, checked with the theme)")
    scale = theme.get("supports_text_scaling_to_pct")
    if not isinstance(scale, (int, float)) or isinstance(
            scale, bool) or scale < TEXT_SCALE_REQUIRED_PCT:
        add("text-scaling", "$.theme",
            f"text scaling support {scale!r} < "
            f"{TEXT_SCALE_REQUIRED_PCT}% -- layout must hold "
            "at 200% without loss")
    if not theme.get("honors_reduced_motion"):
        add("reduced-motion", "$.theme",
            "reduced-motion preference is not honoured; "
            "ceremonial motion is rare and never mandatory")
    if not theme.get("grayscale_coherent"):
        add("grayscale-coherent", "$.theme",
            "theme is not declared coherent in grayscale "
            "(design ship gate: theme must survive glow/art "
            "disabled and grayscale)")
    return findings


def audit_descriptor(data) -> AuditReport:
    """Non-raising audit: structural errors still raise (a
    descriptor that cannot be parsed cannot be audited), every
    guarantee/accessibility failure is collected as a finding."""
    desc = descriptor_from_dict(data)
    findings: List[A11yFinding] = []
    for checker, rule in ((check_local_only, "local-only"),
                          (check_emergency_stop, "emergency-stop"),
                          (check_approval_binding,
                           "approval-binding")):
        try:
            checker(desc)
        except DesktopUXError as exc:
            findings.append(A11yFinding(rule, "$", str(exc)))
    findings.extend(check_accessibility(desc))
    return AuditReport(desc.app_id, tuple(findings))


def validate_desktop_descriptor(data) -> DesktopDescriptor:
    """Full contract validation; raises the named refusal."""
    desc = descriptor_from_dict(data)
    check_local_only(desc)
    check_emergency_stop(desc)
    check_approval_binding(desc)
    findings = check_accessibility(desc)
    if findings:
        first = findings[0]
        _fail(AccessibilityViolationError,
              f"rule {first.rule} at {first.where}: "
              f"{first.detail} ({len(findings)} finding(s))")
    return desc


def descriptor_digest(data) -> str:
    canonical = json.dumps(data, sort_keys=True,
                           separators=(",", ":"),
                           ensure_ascii=True)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def default_descriptor() -> Dict[str, Any]:
    """The canonical compliant descriptor (fixture mirrors it)."""
    def w(wid, kind, action="none", name="", keyboard=False,
          target=0, channel=None, live="off"):
        return {"widget_id": wid, "kind": kind, "action": action,
                "accessible_name": name,
                "keyboard_operable": keyboard,
                "min_target_px": target,
                "redundant_channel": channel, "live_region": live}
    stop = w("global-stop", "emergency-stop", "emergency-stop",
             "Emergency stop", True, 48, "text", "assertive")
    return {
        "schema": DESKTOP_SCHEMA,
        "app_id": "org.runforge.lifthrasir",
        "toolkit": TOOLKIT,
        "network": "none",
        "telemetry": False,
        "analytics": False,
        "crash_reporting": False,
        "views": [
            {"view_id": "overview", "data_source":
             "local-event-store", "widgets": [
                 w("overview-status", "status-banner", "observe",
                   "System status", False, 0, "text", "polite"),
                 w("overview-incidents", "list", "navigate",
                   "Recent incidents", True, 44)]},
            {"view_id": "incidents", "data_source":
             "local-event-store", "widgets": [
                 w("incidents-list", "list", "navigate",
                   "Incident list", True, 44),
                 w("incidents-status", "status-banner", "observe",
                   "Incident list status", False, 0, "icon",
                   "polite")]},
            {"view_id": "incident-detail", "data_source":
             "local-event-store", "widgets": [
                 w("incident-detail-body", "detail", "observe"),
                 w("incident-evidence", "text", "observe")]},
            {"view_id": "sensors", "data_source":
             "local-event-store", "widgets": [
                 w("sensors-table", "sensor-table", "observe",
                   "Sensor permissions", True, 44)]},
            {"view_id": "approvals", "data_source":
             "approval-ledger", "widgets": [
                 w("approvals-list", "list", "navigate",
                   "Pending approvals", True, 44),
                 w("approvals-prompt", "approval-prompt",
                   "request-approval", "Approval prompt", True,
                   44)]},
            {"view_id": "approval-detail", "data_source":
             "approval-ledger", "widgets": [
                 w("approval-detail-prompt", "approval-prompt",
                   "request-approval", "Approval detail", True,
                   44),
                 w("approval-diff", "diff-preview", "observe")]},
            {"view_id": "recovery", "data_source":
             "transaction-store", "widgets": [
                 w("recovery-list", "list", "navigate",
                   "Undo manifests", True, 44),
                 w("recovery-prompt", "approval-prompt",
                   "request-approval", "Recovery approval", True,
                   44)]},
            {"view_id": "settings", "data_source": "local-config",
             "widgets": [
                 w("settings-form", "settings-form",
                   "local-setting", "Local settings", True, 44)]},
            {"view_id": "about", "data_source": "static-bundle",
             "widgets": [w("about-text", "text", "observe")]},
        ],
        "global_widgets": [stop],
        "focus_order": [
            "overview-incidents", "incidents-list",
            "sensors-table", "approvals-list", "approvals-prompt",
            "approval-detail-prompt", "recovery-list",
            "recovery-prompt", "settings-form", "global-stop",
        ],
        "theme": {
            "body_text_px": 16, "contrast_text": 7.0,
            "contrast_large": 4.5, "corner_cut_px": 8,
            "focus_indicator": "2px outline + underline",
            "supports_text_scaling_to_pct": 200,
            "honors_reduced_motion": True,
            "grayscale_coherent": True,
        },
        "approval": {"sections": list(APPROVAL_SECTIONS),
                     "plain_language_summary": True},
        "emergency_stop": {"widget_id": "global-stop",
                           "requires_model": False,
                           "requires_network": False},
    }


def summarize_descriptors(descriptors) -> Dict[str, Any]:
    ok = bad = 0
    by_rule: Dict[str, int] = {}
    for data in descriptors:
        try:
            report = audit_descriptor(data)
        except DesktopUXError:
            bad += 1
            by_rule["unparseable"] = by_rule.get(
                "unparseable", 0) + 1
            continue
        if report.ok:
            ok += 1
        else:
            bad += 1
            for finding in report.findings:
                by_rule[finding.rule] = by_rule.get(
                    finding.rule, 0) + 1
    return {"total": ok + bad, "compliant": ok,
            "non_compliant": bad, "findings_by_rule": by_rule}


def desktop_evidence_record(data) -> Dict[str, Any]:
    desc = validate_desktop_descriptor(data)
    return {
        "schema": DESKTOP_SCHEMA,
        "app_id": desc.app_id,
        "digest": desc.digest(),
        "views": [v.view_id for v in desc.views],
        "widgets": len(desc.all_widgets()),
        "interactive_widgets": len(
            [w for w in desc.all_widgets() if w.interactive]),
        "network": desc.network,
        "toolkit": desc.toolkit,
        "approval_sections": list(desc.approval_sections),
        "evidence_status": "lab-verified (contract level only; "
                           "no GUI rendered or measured)",
    }
