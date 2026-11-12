# SPDX-License-Identifier: GPL-2.0-only
"""LIF-1202 tests: KDE/Qt interface, accessibility, local-only UX.

Checked five ways: (1) the canonical fixture descriptor validates
and matches its recorded expectations, deterministically;
(2) local-only guarantees fail closed -- telemetry, any network
mode but "none", remote URLs/keys anywhere, remote/unknown data
sources and a webview toolkit are each refused by name;
(3) every accessibility rule is enforced -- breaking exactly one
rule in an otherwise compliant descriptor is refused (or found by
the audit) with that rule named; (4) the interface contract --
closed view set with contract sources, no execute affordance,
approval requests only as LIF-0404-sectioned prompts in the
approval views, and a model-free/network-free emergency stop;
(5) the human document mirrors the machine contract.

Scope honesty: descriptors and fixtures only. No test launches a
GUI, imports Qt, renders a window or measures a pixel; declared
accessibility values are checked against thresholds, never
presented as rendered measurements.
"""
import copy
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from lifthrasir.desktopux import (  # noqa: E402
    A11Y_RULES, APPROVAL_SECTIONS, APPROVAL_VIEWS, DATA_SOURCES,
    DESKTOP_SCHEMA, DESIGN_TOKENS, MIN_TARGET_PX, NETWORK_MODES,
    TOOLKITS, VIEWS, VIEW_SOURCES, WIDGET_KINDS,
    AccessibilityViolationError, ApprovalBindingError,
    DesktopUXError, EmergencyStopError, LocalOnlyViolationError,
    MalformedDesktopError, UnknownViewError, UnknownWidgetError,
    audit_descriptor, check_accessibility, default_descriptor,
    descriptor_digest, desktop_evidence_record,
    summarize_descriptors, validate_desktop_descriptor)

FIXTURE = json.loads((ROOT / "tests" / "fixtures" / "lif1202" /
                      "desktop.json").read_text())
DOC = (ROOT / "docs" / "DESKTOP-UX.md").read_text()
GOOD = FIXTURE["descriptor"]


def _good():
    return copy.deepcopy(GOOD)


def _widget(desc, widget_id):
    pools = [v["widgets"] for v in desc["views"]]
    pools.append(desc.get("global_widgets", []))
    for pool in pools:
        for w in pool:
            if w["widget_id"] == widget_id:
                return w
    raise KeyError(widget_id)


def _view(desc, view_id):
    for v in desc["views"]:
        if v["view_id"] == view_id:
            return v
    raise KeyError(view_id)


# --- fixture / canonical -----------------------------------------

def test_fixture_validates_and_matches_expectations():
    desc = validate_desktop_descriptor(_good())
    exp = FIXTURE["expected"]
    assert len(desc.views) == exp["views"] == len(VIEWS)
    assert len(desc.all_widgets()) == exp["widgets"]
    assert len([w for w in desc.all_widgets() if w.interactive]) \
        == exp["interactive_widgets"]
    assert desc.network == exp["network"]
    assert desc.toolkit == exp["toolkit"]


def test_default_descriptor_is_the_fixture():
    assert default_descriptor() == GOOD


def test_digest_is_deterministic():
    assert descriptor_digest(_good()) == descriptor_digest(_good())
    desc = validate_desktop_descriptor(_good())
    assert desc.digest() == descriptor_digest(GOOD)


def test_views_cover_contract_in_order():
    desc = validate_desktop_descriptor(_good())
    assert [v.view_id for v in desc.views] == list(VIEWS)
    for v in desc.views:
        assert v.data_source == VIEW_SOURCES[v.view_id]
        assert v.data_source in DATA_SOURCES


def test_evidence_record_is_contract_level_only():
    rec = desktop_evidence_record(_good())
    assert rec["schema"] == DESKTOP_SCHEMA
    assert rec["network"] == "none"
    assert "no GUI rendered" in rec["evidence_status"]


# --- local-only guarantees ----------------------------------------

def test_network_modes_singleton_is_none():
    assert NETWORK_MODES == ("none",)
    assert TOOLKITS == ("kde-qt",)


@pytest.mark.parametrize("mode", ["online", "metered", "lan",
                                  "offline-capable"])
def test_any_other_network_mode_refused(mode):
    d = _good()
    d["network"] = mode
    with pytest.raises(LocalOnlyViolationError):
        validate_desktop_descriptor(d)


@pytest.mark.parametrize("key", ["telemetry", "analytics",
                                 "crash_reporting"])
def test_telemetry_switches_refused(key):
    d = _good()
    d[key] = True
    with pytest.raises(LocalOnlyViolationError):
        validate_desktop_descriptor(d)


@pytest.mark.parametrize("url", ["https://example.invalid/x",
                                 "http://192.0.2.1/feed",
                                 "wss://example.invalid/socket"])
def test_remote_url_anywhere_refused(url):
    d = _good()
    _view(d, "about")["widgets"][0]["accessible_name"] = url
    with pytest.raises(LocalOnlyViolationError):
        validate_desktop_descriptor(d)


def test_remote_endpoint_key_refused():
    d = _good()
    d["update_url"] = "https://example.invalid/stable"
    with pytest.raises(LocalOnlyViolationError):
        validate_desktop_descriptor(d)


@pytest.mark.parametrize("toolkit", ["webview", "electron",
                                     "web", "gtk"])
def test_non_qt_toolkit_refused(toolkit):
    d = _good()
    d["toolkit"] = toolkit
    with pytest.raises(LocalOnlyViolationError):
        validate_desktop_descriptor(d)


def test_remote_data_source_refused():
    d = _good()
    _view(d, "overview")["data_source"] = "cloud-api"
    with pytest.raises(LocalOnlyViolationError):
        validate_desktop_descriptor(d)


def test_wrong_contract_source_refused():
    d = _good()
    _view(d, "sensors")["data_source"] = "local-config"
    with pytest.raises(MalformedDesktopError):
        validate_desktop_descriptor(d)


# --- interface contract -------------------------------------------

def test_unknown_view_refused():
    d = _good()
    _view(d, "about")["view_id"] = "storefront"
    with pytest.raises(UnknownViewError):
        validate_desktop_descriptor(d)


def test_missing_view_refused():
    d = _good()
    d["views"] = [v for v in d["views"]
                  if v["view_id"] != "about"]
    with pytest.raises(MalformedDesktopError):
        validate_desktop_descriptor(d)


def test_unknown_widget_kind_refused():
    d = _good()
    _widget(d, "about-text")["kind"] = "web-frame"
    with pytest.raises(UnknownWidgetError):
        validate_desktop_descriptor(d)


def test_execute_action_refused():
    d = _good()
    _widget(d, "incidents-list")["action"] = "execute"
    with pytest.raises(ApprovalBindingError):
        validate_desktop_descriptor(d)


def test_approval_request_outside_approval_views_refused():
    d = _good()
    w = _widget(d, "incidents-list")
    w["kind"] = "approval-prompt"
    w["action"] = "request-approval"
    with pytest.raises(ApprovalBindingError):
        validate_desktop_descriptor(d)


def test_approval_prompt_in_each_approval_view():
    desc = validate_desktop_descriptor(_good())
    for vid in APPROVAL_VIEWS:
        view = [v for v in desc.views if v.view_id == vid][0]
        assert any(w.kind == "approval-prompt"
                   for w in view.widgets), vid


def test_approval_sections_exact_and_ordered():
    d = _good()
    d["approval"]["sections"] = list(
        reversed(d["approval"]["sections"]))
    with pytest.raises(ApprovalBindingError):
        validate_desktop_descriptor(d)


def test_approval_section_dropped_refused():
    d = _good()
    d["approval"]["sections"].remove("rollback")
    with pytest.raises(ApprovalBindingError):
        validate_desktop_descriptor(d)


def test_duplicate_widget_id_refused():
    d = _good()
    _widget(d, "about-text")["widget_id"] = "incidents-list"
    with pytest.raises(MalformedDesktopError):
        validate_desktop_descriptor(d)


def test_wrong_schema_refused():
    d = _good()
    d["schema"] = "lifthrasir.desktop-ux.v9"
    with pytest.raises(MalformedDesktopError):
        validate_desktop_descriptor(d)


def test_non_object_refused():
    with pytest.raises(MalformedDesktopError):
        validate_desktop_descriptor(["not", "a", "dict"])


# --- emergency stop (invariant 8) ---------------------------------

def test_emergency_stop_widget_is_global_and_bound():
    desc = validate_desktop_descriptor(_good())
    assert desc.emergency_stop["widget_id"] == "global-stop"
    assert "global-stop" in desc.widget_ids()


def test_emergency_stop_missing_widget_refused():
    d = _good()
    d["emergency_stop"]["widget_id"] = "no-such-widget"
    with pytest.raises(EmergencyStopError):
        validate_desktop_descriptor(d)


@pytest.mark.parametrize("key", ["requires_model",
                                 "requires_network"])
def test_emergency_stop_dependencies_refused(key):
    d = _good()
    d["emergency_stop"][key] = True
    with pytest.raises(EmergencyStopError):
        validate_desktop_descriptor(d)


# --- accessibility rules -------------------------------------------

def _findings_after(mutate):
    from lifthrasir.desktopux import descriptor_from_dict
    d = _good()
    mutate(d)
    return check_accessibility(descriptor_from_dict(d))


def _rules(findings):
    return {f.rule for f in findings}


def test_accessible_name_required():
    findings = _findings_after(
        lambda d: _widget(d, "incidents-list").update(
            accessible_name="  "))
    assert "accessible-name" in _rules(findings)


def test_keyboard_complete_required():
    findings = _findings_after(
        lambda d: _widget(d, "settings-form").update(
            keyboard_operable=False))
    assert "keyboard-complete" in _rules(findings)


def test_focus_order_must_cover_interactive_exactly():
    def drop(d):
        d["focus_order"].remove("settings-form")
    assert "keyboard-complete" in _rules(_findings_after(drop))

    def dup(d):
        d["focus_order"].append("settings-form")
    assert "keyboard-complete" in _rules(_findings_after(dup))


def test_visible_focus_required():
    findings = _findings_after(
        lambda d: d["theme"].update(focus_indicator="none"))
    assert "visible-focus" in _rules(findings)


def test_target_size_floor():
    assert MIN_TARGET_PX == 44
    findings = _findings_after(
        lambda d: _widget(d, "approvals-prompt").update(
            min_target_px=32))
    assert "target-size" in _rules(findings)


def test_no_color_only_status():
    findings = _findings_after(
        lambda d: _widget(d, "overview-status").update(
            redundant_channel=None))
    assert "no-color-only" in _rules(findings)


def test_status_must_be_announced():
    findings = _findings_after(
        lambda d: _widget(d, "overview-status").update(
            live_region="off"))
    assert "screen-reader-announcements" in _rules(findings)


def test_contrast_floors():
    findings = _findings_after(
        lambda d: d["theme"].update(contrast_text=3.9))
    assert "contrast" in _rules(findings)
    findings = _findings_after(
        lambda d: d["theme"].update(contrast_large=2.5))
    assert "contrast" in _rules(findings)


def test_body_text_band():
    findings = _findings_after(
        lambda d: d["theme"].update(body_text_px=11))
    assert "contrast" in _rules(findings)


def test_text_scaling_to_200_required():
    findings = _findings_after(
        lambda d: d["theme"].update(
            supports_text_scaling_to_pct=150))
    assert "text-scaling" in _rules(findings)


def test_reduced_motion_required():
    findings = _findings_after(
        lambda d: d["theme"].update(honors_reduced_motion=False))
    assert "reduced-motion" in _rules(findings)


def test_grayscale_coherence_required():
    findings = _findings_after(
        lambda d: d["theme"].update(grayscale_coherent=False))
    assert "grayscale-coherent" in _rules(findings)


def test_plain_language_approval_required():
    d = _good()
    d["approval"]["plain_language_summary"] = False
    with pytest.raises(AccessibilityViolationError):
        validate_desktop_descriptor(d)


def test_single_rule_break_fails_validation():
    d = _good()
    _widget(d, "recovery-prompt")["min_target_px"] = 20
    with pytest.raises(AccessibilityViolationError):
        validate_desktop_descriptor(d)


def test_compliant_descriptor_has_no_findings():
    from lifthrasir.desktopux import descriptor_from_dict
    assert check_accessibility(descriptor_from_dict(_good())) == []


# --- audit / summary -----------------------------------------------

def test_audit_collects_without_raising():
    d = _good()
    d["network"] = "online"
    _widget(d, "incidents-list")["min_target_px"] = 10
    report = audit_descriptor(d)
    assert not report.ok
    rules = {f.rule for f in report.findings}
    assert "local-only" in rules and "target-size" in rules


def test_audit_of_compliant_is_ok():
    assert audit_descriptor(_good()).ok


def test_summarize_counts():
    bad = _good()
    bad["telemetry"] = True
    out = summarize_descriptors([_good(), bad, {"schema": "x"}])
    assert out["total"] == 3
    assert out["compliant"] == 1
    assert out["non_compliant"] == 2


def test_errors_are_desktop_errors():
    d = _good()
    d["network"] = "online"
    with pytest.raises(DesktopUXError):
        validate_desktop_descriptor(d)


# --- document mirrors the contract ---------------------------------

def test_doc_names_schema_views_and_rules():
    assert DESKTOP_SCHEMA in DOC
    for vid in VIEWS:
        assert f"`{vid}`" in DOC, vid
    for rule in A11Y_RULES:
        assert rule in DOC, rule
    for kind in WIDGET_KINDS:
        assert kind in DOC, kind


def test_doc_names_tokens_and_sections():
    for section in APPROVAL_SECTIONS:
        assert section in DOC, section
    assert str(DESIGN_TOKENS["min_target_px"]) in DOC
    assert "200%" in DOC
    assert "4.5" in DOC


def test_doc_honest_status_no_gui_claim():
    assert "No GUI" in DOC or "no GUI" in DOC
    assert "not a running" in DOC.lower()
