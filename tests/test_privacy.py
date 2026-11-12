# SPDX-License-Identifier: GPL-2.0-only
"""LIF-0304 privacy redactor, local retention and export preview tests.

Scope: the committed fixture corpus (tests/fixtures/lif0304/
records.json) with SYNTHETIC planted secrets only (research/24's own
test line: "Fake a credential in journal metadata and confirm it
never leaves host in a research artifact"), plus inline strings.
No network, no real credentials anywhere in this file.

Honesty pinned here: the redactor covers ONLY its named categories;
the suite asserts a natural-language disclosure is NOT caught (the
limitation is tested, not hidden), findings never contain the
redacted values, retention never expires an undated record, and the
export preview is the exact payload whose hash is reported.
"""
import copy
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from lifthrasir import privacy as pv  # noqa: E402

NOW = datetime(2026, 11, 12, tzinfo=timezone.utc)
SECRETS = [
    "hunter2", "alice@example.org", "192.168.1.20",
    "2001:db8:85a3::8a2e:370:7334", "aa:bb:cc:dd:ee:ff",
    "/home/alice/", "abcdefgh12345678", "carol@example.net",
    "10.0.0.5", "bob.smith+lab@example.co.uk",
    "ghp_0123456789abcdefghij0123456789abcd",
    "not-a-pattern-shaped-secret", "MIIBfake",
]


@pytest.fixture(scope="module")
def records():
    path = REPO / "tests" / "fixtures" / "lif0304" / "records.json"
    return json.loads(path.read_text(encoding="utf-8"))


# -- text redaction ---------------------------------------------------

def test_credential_assignment_value_redacted_key_kept():
    out, findings = pv.redact_text("login password=hunter2 ok")
    assert out == "login password=[REDACTED:credential] ok"
    assert [f.category for f in findings] == ["credential"]
    assert "hunter2" not in out


def test_bearer_token_redacted():
    out, _ = pv.redact_text("Authorization: Bearer abcdefgh12345678 x")
    assert "abcdefgh12345678" not in out
    assert "[REDACTED:credential]" in out


def test_known_token_formats_redacted():
    text = ("gh ghp_0123456789abcdefghij0123456789abcd "
            "aws AKIAIOSFODNN7EXAMPLE jwt "
            "eyJhbGciOiJIUzI1NiIs.eyJzdWIiOiIxMjM0NTY3ODkwIn0."
            "SflKxwRJSMeKKF2QT4fwpMeJf36POk6yJVadQssw5c")
    out, findings = pv.redact_text(text)
    assert "ghp_0123" not in out and "AKIAIOSFODNN7EXAMPLE" not in out
    assert "eyJhbGciOiJIUzI1NiIs" not in out
    assert all(f.category == "token" for f in findings)
    assert len(findings) == 3


def test_email_ip_mac_path_redacted_times_untouched():
    text = ("alice@example.org from 192.168.1.20 via "
            "2001:db8:85a3::8a2e:370:7334 nic aa:bb:cc:dd:ee:ff "
            "cfg /home/alice/app.toml at 17:02:11 daily")
    out, findings = pv.redact_text(text)
    for secret in ("alice@example.org", "192.168.1.20",
                   "2001:db8:85a3::8a2e:370:7334", "aa:bb:cc:dd:ee:ff",
                   "/home/alice/"):
        assert secret not in out
    assert "/home/[REDACTED:username]/app.toml" in out
    assert "17:02:11" in out  # clock times are not IPv6 addresses
    cats = {f.category for f in findings}
    assert cats == {"email", "ip-address", "mac-address", "username"}


def test_invalid_ip_lookalike_untouched():
    out, findings = pv.redact_text("version 999.1.1.1 is not an ip")
    assert out == "version 999.1.1.1 is not an ip"
    assert findings == []


def test_private_key_block_redacted():
    text = ("leak -----BEGIN PRIVATE KEY-----\nMIIBfake\n"
            "-----END PRIVATE KEY----- end")
    out, findings = pv.redact_text(text)
    assert "MIIBfake" not in out
    assert [f.category for f in findings] == ["private-key"]


def test_finding_spans_index_original_and_carry_no_secret():
    text = "mail alice@example.org end"
    out, findings = pv.redact_text(text)
    (finding,) = findings
    assert text[finding.start:finding.end] == "alice@example.org"
    assert "alice" not in str(finding) or "example" not in str(finding)
    assert out == "mail [REDACTED:email] end"


def test_redaction_is_idempotent():
    text = "password=hunter2 alice@example.org 192.168.1.20"
    once, _ = pv.redact_text(text)
    twice, findings = pv.redact_text(once)
    assert twice == once
    assert findings == []


def test_documented_limitation_natural_language_not_caught():
    # Honesty test: the redactor does NOT catch prose disclosures,
    # and the suite says so instead of implying full coverage.
    text = "the password is hunter two, tell no one"
    out, findings = pv.redact_text(text)
    assert out == text
    assert findings == []


def test_extra_user_rule_and_builtin_redefinition_refused():
    redactor = pv.Redactor(extra_patterns=[("codename", r"\bZEPHYR-\d+\b")])
    out, findings = redactor.redact_text("op ZEPHYR-42 planned")
    assert out == "op [REDACTED:codename] planned"
    assert findings[0].category == "codename"
    with pytest.raises(pv.PrivacyError):
        pv.Redactor(extra_patterns=[("email", r"x")])


def test_redact_text_rejects_non_string():
    with pytest.raises(pv.PrivacyError):
        pv.redact_text(b"password=hunter2")  # type: ignore[arg-type]


# -- record redaction ---------------------------------------------------

def test_record_redaction_fixture_no_secrets_remain(records):
    for record in records:
        redacted, _ = pv.redact_record(record)
        blob = json.dumps(redacted)
        for secret in SECRETS:
            assert secret not in blob, (record.get("evidence_id"), secret)
    # Structural text survives redaction.
    first, report = pv.redact_record(records[0])
    assert first["kind"] == "log-excerpt"
    assert "sshd accepted" in first["detail"]
    assert report.total >= 6


def test_sensitive_field_name_whole_value_rule(records):
    redacted, report = pv.redact_record(records[0])
    # 'not-a-pattern-shaped-secret' matches no pattern; only the
    # field-name rule (api_key) can have caught it.
    assert redacted["api_key"] == "[REDACTED:credential]"
    assert any(f.field == "api_key" and f.category == "credential"
               for f in report.findings)


def test_record_input_never_mutated(records):
    snapshot = copy.deepcopy(records)
    for record in records:
        pv.redact_record(record)
    assert records == snapshot


def test_record_rejects_non_mapping():
    with pytest.raises(pv.PrivacyError):
        pv.redact_record(["not", "a", "mapping"])  # type: ignore[arg-type]


# -- retention ----------------------------------------------------------

def test_retention_age_rule(records):
    policy = pv.RetentionPolicy(max_age_days=30)
    report = pv.evaluate_retention(records, policy, now=NOW)
    assert report.expired_ids == ["ev-2026-202"]  # 2026-08-01 record
    assert "inc-2026-202" in report.kept_ids


def test_retention_count_rule_keeps_newest_dated(records):
    policy = pv.RetentionPolicy(max_records=1)
    report = pv.evaluate_retention(records, policy, now=NOW)
    # Dated records: ev-2026-201 (11-10), ev-2026-202 (08-01),
    # inc-2026-202 (11-11, newest).  Only the newest is kept.
    assert report.expired_ids == ["ev-2026-201", "ev-2026-202"]
    assert "inc-2026-202" in report.kept_ids


def test_retention_never_expires_undated(records):
    for policy in (pv.RetentionPolicy(max_age_days=0),
                   pv.RetentionPolicy(max_records=0)):
        report = pv.evaluate_retention(records, policy, now=NOW)
        assert "ev-2026-203" not in report.expired_ids
        assert report.unknown_age_ids == ["ev-2026-203"]


def test_retention_does_not_mutate_input(records):
    snapshot = copy.deepcopy(records)
    pv.evaluate_retention(records, pv.RetentionPolicy(max_age_days=1),
                          now=NOW)
    assert records == snapshot


def test_retention_policy_requires_a_bound():
    with pytest.raises(pv.PrivacyError):
        pv.RetentionPolicy()


# -- export preview -------------------------------------------------------

def test_export_preview_redacts_and_excludes_expired(records):
    policy = pv.RetentionPolicy(max_age_days=30)
    preview = pv.build_export_preview(records, policy=policy, now=NOW)
    assert preview.records_in == 4
    assert preview.records_included == 3
    assert preview.expired_excluded == ["ev-2026-202"]
    blob = preview.to_json()
    for secret in SECRETS:
        assert secret not in blob
    assert preview.verify_clean() == []
    assert preview.findings_by_category.get("credential", 0) >= 2
    assert "ev-2026-203" in preview.unknown_age_included
    assert any("nothing was sent" in w for w in preview.warnings)


def test_export_preview_digest_is_stable_and_payload_exact(records):
    first = pv.build_export_preview(records, now=NOW)
    second = pv.build_export_preview(records, now=NOW)
    assert first.to_json() == second.to_json()
    assert first.payload_sha256 == second.payload_sha256
    assert len(first.payload_sha256) == 64
    assert json.loads(first.to_json()) == first.payload


def test_export_preview_without_policy_includes_all_redacted(records):
    preview = pv.build_export_preview(records, now=NOW)
    assert preview.records_included == 4
    assert preview.expired_excluded == []
    assert preview.verify_clean() == []


def test_export_preview_accepts_stored_records(records, tmp_path):
    sys.path.insert(0, str(REPO / "src"))
    from lifthrasir.eventstore import EventStore

    store = EventStore(tmp_path / "events.db")
    try:
        for record in records[:3]:
            store.append(record)
        stored = store.list_all()
    finally:
        store.close()
    preview = pv.build_export_preview(stored, now=NOW)
    assert preview.records_included == 3
    assert "hunter2" not in preview.to_json()
    assert preview.verify_clean() == []
