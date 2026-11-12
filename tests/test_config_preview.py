# SPDX-License-Identifier: GPL-2.0-only
"""LIF-0503 configuration validation and diff preview tests.

Scope: pure text-in / report-out only. Every input is a fixture
copy held in this repo or an inline string; no test reads or
writes any real host configuration, and the module under test has
no file API at all.

NEGATIVE CONTROLS (standing): (1) the invalid.ini fixture -- a
duplicate key, a key before any section, a line without '=', a
repeated section -- must be rejected while current.ini passes;
hidden_files/ replays this pair. (2) identical current/proposed
texts must preview as no-change with an empty change list, ruling
out a preview that always reports changes.
"""
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from lifthrasir import configpreview as cp  # noqa: E402

FIX = REPO / "tests" / "fixtures" / "lif0503"
TARGET = "demo.service.d/unit.conf"


def fx(name):
    return (FIX / name).read_text(encoding="utf-8")


def codes(report):
    return [i.code for i in report.issues]


# ---------- validation: ini ----------

def test_valid_ini_fixture_passes():
    rep = cp.validate_config(fx("current.ini"), "ini")
    assert rep.valid and rep.errors == []
    assert rep.keys == 6
    assert rep.digest.startswith("sha256:")


def test_invalid_ini_fixture_rejected_with_named_codes():
    rep = cp.validate_config(fx("invalid.ini"), "ini")
    assert not rep.valid
    got = codes(rep)
    assert "key-outside-section" in got
    assert "duplicate-key" in got
    assert "missing-equals" in got
    assert "duplicate-section" in got


def test_ini_issue_lines_are_accurate():
    rep = cp.validate_config(fx("invalid.ini"), "ini")
    by_code = {i.code: i.line for i in rep.issues}
    assert by_code["key-outside-section"] == 1
    assert by_code["duplicate-key"] == 4
    assert by_code["missing-equals"] == 5
    assert by_code["duplicate-section"] == 6


def test_ini_bad_section_header_and_bad_key():
    rep = cp.validate_config("[Broken\nKey With Space=1\n", "ini")
    assert "bad-section-header" in codes(rep)


def test_ini_empty_value_is_warning_not_error():
    rep = cp.validate_config("[Service]\nEnvironment=\n", "ini")
    assert rep.valid
    assert [i.code for i in rep.warnings] == ["empty-value"]


def test_empty_config_is_invalid():
    rep = cp.validate_config("  \n", "ini")
    assert not rep.valid and codes(rep)[0] == "empty-config"


# ---------- validation: keyvalue ----------

def test_keyvalue_fixture_passes_and_parses():
    text = fx("current.conf")
    rep = cp.validate_config(text, "keyvalue")
    assert rep.valid and rep.keys == 3
    entries = cp.parse_config(text, "keyvalue")
    assert entries["demo.interval_seconds"] == "60"


def test_keyvalue_rejects_section_and_duplicates():
    rep = cp.validate_config("[S]\na=1\na=2\n", "keyvalue")
    assert "unexpected-section" in codes(rep)
    assert "duplicate-key" in codes(rep)


# ---------- validation: json ----------

def test_json_fixture_passes_and_flattens():
    entries = cp.parse_config(fx("current.json"), "json")
    assert entries["demo.limits.memory_mb"] == "256"
    assert entries["demo.enabled"] == "true"


def test_json_syntax_error_located():
    rep = cp.validate_config(fx("invalid.json"), "json")
    assert not rep.valid
    assert "json-syntax" in codes(rep)
    assert rep.errors[0].line >= 1


def test_json_duplicate_key_detected():
    rep = cp.validate_config('{"a": 1, "a": 2}', "json")
    assert not rep.valid and "duplicate-key" in codes(rep)


def test_json_top_level_must_be_object():
    rep = cp.validate_config("[1, 2]", "json")
    assert not rep.valid and "json-top-level" in codes(rep)


# ---------- refusals and caps ----------

def test_unknown_format_refused():
    with pytest.raises(cp.UnsupportedFormatError):
        cp.validate_config("a=1", "yaml")
    with pytest.raises(cp.UnsupportedFormatError):
        cp.preview_config_change("a=1", "a=2", "toml", TARGET)


def test_non_config_target_type_refused():
    with pytest.raises(cp.MalformedConfigError):
        cp.preview_config_change("a=1", "a=2", "keyvalue", "x",
                                 target_type="systemd-unit")


@pytest.mark.parametrize("path", [
    "/etc/ssh/sshd_config", "/boot/grub/grub.cfg",
    "/home/volmarr/.config/demo/settings.ini", "/etc/shadow",
    "/root/demo.ini",
])
def test_protected_target_paths_refused(path):
    with pytest.raises(cp.ProtectedTargetError):
        cp.preview_config_change("a=1", "a=2", "keyvalue", path)


def test_fixture_relative_target_allowed():
    p = cp.preview_config_change("a=1", "a=2", "keyvalue",
                                 "fixtures/demo/settings.conf")
    assert p.verdict == cp.VERDICT_READY


def test_oversize_and_nul_refused():
    big = "k=" + "v" * (cp.MAX_TEXT_BYTES + 1)
    with pytest.raises(cp.OversizeConfigError):
        cp.validate_config(big, "keyvalue")
    with pytest.raises(cp.MalformedConfigError):
        cp.validate_config("a=1\x00", "keyvalue")
    with pytest.raises(cp.MalformedConfigError):
        cp.validate_config(b"a=1", "keyvalue")


# ---------- preview ----------

def test_preview_ini_semantic_changes_exact():
    p = cp.preview_config_change(fx("current.ini"), fx("proposed.ini"),
                                 "ini", TARGET)
    assert p.verdict == cp.VERDICT_READY and p.applicable
    got = {(c.kind, c.key) for c in p.changes}
    assert got == {
        ("changed", "Service.Restart"),
        ("changed", "Service.MemoryMax"),
        ("added", "Service.Nice"),
    }
    by_key = {c.key: c for c in p.changes}
    assert by_key["Service.MemoryMax"].old == "256M"
    assert by_key["Service.MemoryMax"].new == "384M"
    assert p.current_digest != p.proposed_digest


def test_preview_unified_diff_shows_lines():
    p = cp.preview_config_change(fx("current.ini"), fx("proposed.ini"),
                                 "ini", TARGET)
    assert f"--- a/{TARGET}" in p.unified_diff
    assert "-Restart=on-failure" in p.unified_diff
    assert "+Restart=always" in p.unified_diff
    assert "+Nice=5" in p.unified_diff


def test_preview_identical_is_no_change_control():
    text = fx("current.ini")
    p = cp.preview_config_change(text, text, "ini", TARGET)
    assert p.verdict == cp.VERDICT_NO_CHANGE
    assert p.changes == [] and p.unified_diff == ""
    assert not p.applicable and not p.changed


def test_preview_comment_only_change_has_no_semantic_changes():
    cur = "[Service]\nRestart=on-failure\n"
    prop = "# note\n[Service]\nRestart=on-failure\n"
    p = cp.preview_config_change(cur, prop, "ini", TARGET)
    assert p.changes == [] and p.changed  # digests differ
    assert p.unified_diff != ""


def test_preview_invalid_proposed_blocked_not_applicable():
    p = cp.preview_config_change(fx("current.ini"), fx("invalid.ini"),
                                 "ini", TARGET)
    assert p.verdict == cp.VERDICT_BLOCKED_INVALID
    assert not p.applicable
    assert not p.proposed_validation.valid
    # the diff is still shown for inspection
    assert p.unified_diff != ""


def test_preview_invalid_current_blocked():
    p = cp.preview_config_change(fx("invalid.ini"), fx("current.ini"),
                                 "ini", TARGET)
    assert p.verdict == cp.VERDICT_BLOCKED_CURRENT
    assert not p.applicable


def test_preview_keyvalue_changes():
    p = cp.preview_config_change(fx("current.conf"), fx("proposed.conf"),
                                 "keyvalue", "demo/demo.conf")
    got = {(c.kind, c.key) for c in p.changes}
    assert got == {("changed", "demo.interval_seconds"),
                   ("added", "demo.retention_days")}


def test_preview_json_changes_use_flattened_keys():
    p = cp.preview_config_change(fx("current.json"), fx("proposed.json"),
                                 "json", "demo/settings.json")
    got = {(c.kind, c.key) for c in p.changes}
    assert got == {("changed", "demo.interval_seconds"),
                   ("changed", "demo.limits.memory_mb")}


def test_preview_removed_key():
    p = cp.preview_config_change("a=1\nb=2\n", "a=1\n",
                                 "keyvalue", "demo/x.conf")
    assert [(c.kind, c.key, c.old) for c in p.changes] == [
        ("removed", "b", "2")]


def test_render_preview_is_deterministic_and_complete():
    args = (fx("current.ini"), fx("proposed.ini"), "ini", TARGET)
    r1 = cp.render_preview(cp.preview_config_change(*args))
    r2 = cp.render_preview(cp.preview_config_change(*args))
    assert r1 == r2
    for needle in ("Target:", "Current digest:", "Proposed digest:",
                   "Validation (Proposed): OK", "Service.MemoryMax",
                   "256M -> 384M", "Verdict: ready"):
        assert needle in r1


def test_render_preview_shows_invalid_proposed_errors():
    p = cp.preview_config_change(fx("current.ini"), fx("invalid.ini"),
                                 "ini", TARGET)
    r = cp.render_preview(p)
    assert "Validation (Proposed): INVALID" in r
    assert "duplicate-key" in r
    assert "Verdict: blocked-invalid" in r


def test_preview_to_dict_round_trips_shape():
    p = cp.preview_config_change(fx("current.conf"), fx("proposed.conf"),
                                 "keyvalue", "demo/demo.conf")
    d = p.to_dict()
    assert d["schema"] == cp.PREVIEW_SCHEMA
    assert d["verdict"] == "ready" and d["applicable"] is True
    assert d["proposed_validation"]["valid"] is True
    assert {c["key"] for c in d["changes"]} == {
        "demo.interval_seconds", "demo.retention_days"}


def test_module_has_no_file_writing_api():
    # Design invariant of this slice: preview/validation operate on
    # in-memory copies only. There is no apply/write entry point.
    for name in ("apply", "write", "save", "commit_change", "install"):
        assert not hasattr(cp, name), name
