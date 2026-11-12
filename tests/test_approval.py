# SPDX-License-Identifier: GPL-2.0-only
"""LIF-0404 approval UX + signed/unique plan reference tests.

Scope: pure data/text contract level only. No host state, no real
keys: all signing keys are throwaway fixtures created in this file.
The clock is injected everywhere; no test reads wall time.

NEGATIVE CONTROL (standing): test_tampered_plan_digest_refused and
test_forged_signature_refused -- a plan edited after its reference
was minted, and a reference with a forged signature, must both be
refused. hidden_files/ replays them against a mutant with signature
verification disabled.
"""
import copy
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from lifthrasir import approval as ap  # noqa: E402

KEY = b"lif-0404-fixture-key-throwaway-00"
WRONG_KEY = b"lif-0404-wrong-fixture-key-000000"
T0 = datetime(2026, 11, 12, 4, 0, 0, tzinfo=timezone.utc)


def make_plan(**overrides):
    plan = {
        "schema": "lifthrasir.plan.v0.1",
        "schema_version": "0.1",
        "plan_id": "plan-2026-101",
        "incident_id": "inc-2026-001",
        "hypothesis_ids": ["hyp-2026-001"],
        "title": "Restart the allowlisted demo service on the live host",
        "status": "submitted",
        "risk_level": "L3",
        "consent_mode": "allowlist-notice",
        "steps": [{
            "step_id": "step-1", "action_verb": "restart_unit",
            "target": {"type": "systemd-unit", "name": "demo.service"},
            "args": {"unit": "demo.service", "secret_note": "do-not-print"},
        }],
        "preconditions": ["demo.service is on the human allowlist"],
        "rollback": {"method": "stop_unit", "description": "Stop the unit; prior state recorded."},
        "verification": {"method": "unit_healthy", "timeout_seconds": 30},
        "created_at": "2026-11-12T03:55:00Z",
        "expires_at": "2026-11-12T05:55:00Z",
    }
    plan.update(overrides)
    return plan


def mint(plan=None, **kw):
    kw.setdefault("key", KEY)
    kw.setdefault("now", T0)
    kw.setdefault("nonce", "a" * 32)
    return ap.mint_plan_reference(plan or make_plan(), **kw)


def ledger_with(ref):
    ledger = ap.ApprovalLedger()
    ledger.register(ref, key=KEY)
    return ledger


def test_digest_is_canonical_and_stable():
    plan = make_plan()
    shuffled = dict(reversed(list(plan.items())))
    assert ap.plan_digest(plan) == ap.plan_digest(shuffled)
    assert ap.DIGEST_RE.match(ap.plan_digest(plan))


def test_digest_changes_when_plan_changes():
    ref = mint()
    edited = make_plan()
    edited["steps"][0]["target"]["name"] = "other.service"
    assert ap.plan_digest(edited) != ref.digest


def test_reference_is_signed_unique_and_scoped():
    ref = mint()
    other = mint(nonce="b" * 32)
    assert ref.reference_id != other.reference_id
    assert ref.signature.startswith("hmac-sha256:")
    assert ref.scope == ("systemd-unit:demo.service",)
    assert ref.expires_at == "2026-11-12T04:15:00Z"
    ap.verify_reference_signature(ref, key=KEY)


def test_forged_signature_refused():
    ref = mint()
    forged = copy.replace(ref, signature="hmac-sha256:" + "0" * 64)
    with pytest.raises(ap.SignatureError):
        ap.verify_reference_signature(forged, key=KEY)
    with pytest.raises(ap.SignatureError):
        ap.ApprovalLedger().register(forged, key=KEY)
    with pytest.raises(ap.SignatureError):
        ap.verify_reference_signature(ref, key=WRONG_KEY)


def test_duplicate_nonce_or_reference_refused():
    ledger = ledger_with(mint())
    with pytest.raises(ap.DuplicateReferenceError):
        ledger.register(mint(), key=KEY)


def test_prompt_has_separate_sections_and_no_secrets():
    plan, ref = make_plan(), mint()
    prompt = ap.render_approval_prompt(plan, ref)
    for section in ("WHAT IS PROPOSED", "EXACT SCOPE", "PRECONDITIONS", "ROLLBACK", "VERIFICATION", "REFERENCE AND EXPIRY"):
        assert section in prompt
    assert "demo.service" in prompt and ref.reference_id in prompt
    assert ref.short_check_code() in prompt
    assert "do-not-print" not in prompt
    assert KEY.decode() not in prompt
    assert ap.render_approval_prompt(plan, ref) == prompt


def test_prompt_refuses_mismatched_reference():
    with pytest.raises(ap.DigestMismatchError):
        ap.render_approval_prompt(make_plan(), mint(make_plan(plan_id="plan-2026-102")))


def test_approve_then_consume_exactly_once():
    plan, ref = make_plan(), mint()
    ledger = ledger_with(ref)
    rec = ledger.decide(ref.reference_id, plan, decision="approved", approver="volmarr-local", now=T0)
    assert rec.decision == "approved" and rec.digest == ref.digest
    done = ledger.consume_for_execution(ref.reference_id, plan, resource="systemd-unit:demo.service", now=T0 + timedelta(minutes=5))
    assert done.consumed is True
    with pytest.raises(ap.ReplayError):
        ledger.consume_for_execution(ref.reference_id, plan, resource="systemd-unit:demo.service", now=T0 + timedelta(minutes=6))


def test_rejection_is_terminal_and_not_consumable():
    plan, ref = make_plan(), mint()
    ledger = ledger_with(ref)
    ledger.decide(ref.reference_id, plan, decision="rejected", approver="volmarr-local", now=T0)
    with pytest.raises(ap.ReplayError):
        ledger.decide(ref.reference_id, plan, decision="approved", approver="volmarr-local", now=T0)
    with pytest.raises(ap.DecisionError):
        ledger.consume_for_execution(ref.reference_id, plan, resource="systemd-unit:demo.service", now=T0)


def test_tampered_plan_digest_refused():
    ref = mint()
    ledger = ledger_with(ref)
    edited = make_plan()
    edited["title"] = "Restart a different, unreviewed thing"
    with pytest.raises(ap.DigestMismatchError):
        ledger.decide(ref.reference_id, edited, decision="approved", approver="volmarr-local", now=T0)


def test_expired_reference_refused():
    plan, ref = make_plan(), mint(ttl_seconds=60)
    ledger = ledger_with(ref)
    with pytest.raises(ap.ExpiredReferenceError):
        ledger.decide(ref.reference_id, plan, decision="approved", approver="volmarr-local", now=T0 + timedelta(minutes=2))


def test_wrong_resource_refused():
    plan, ref = make_plan(), mint()
    ledger = ledger_with(ref)
    ledger.decide(ref.reference_id, plan, decision="approved", approver="volmarr-local", now=T0)
    with pytest.raises(ap.ResourceScopeError):
        ledger.consume_for_execution(ref.reference_id, plan, resource="systemd-unit:other.service", now=T0)


def test_consent_below_floor_refused():
    weak = make_plan(risk_level="L4", consent_mode="allowlist-notice")
    with pytest.raises(ap.ConsentFloorError):
        ap.mint_plan_reference(weak, key=KEY, now=T0, nonce="c" * 32)


def test_never_consent_refused_for_agents():
    banned = make_plan(risk_level="L5", consent_mode="never")
    with pytest.raises(ap.ForbiddenApprovalError):
        ap.mint_plan_reference(banned, key=KEY, now=T0, nonce="d" * 32)


def test_malformed_plans_refused():
    with pytest.raises(ap.MalformedPlanError):
        ap.plan_digest(make_plan(plan_id="bogus"))
    with pytest.raises(ap.MalformedPlanError):
        ap.plan_digest(make_plan(steps=[]))
    with pytest.raises(ap.MalformedPlanError):
        ap.plan_digest(make_plan(expires_at="2026-11-12T03:00:00Z"))


def test_unknown_reference_refused():
    with pytest.raises(ap.UnknownReferenceError):
        ap.ApprovalLedger().decide("pref-nope", make_plan(), decision="approved", approver="volmarr-local", now=T0)


def test_reference_expiry_capped_by_plan_expiry():
    plan = make_plan(expires_at="2026-11-12T04:05:00Z")
    ref = mint(plan, ttl_seconds=3600)
    assert ref.expires_at == "2026-11-12T04:05:00Z"
