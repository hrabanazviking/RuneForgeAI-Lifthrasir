# SPDX-License-Identifier: GPL-2.0-only
"""LIF-0104: independent pass/fail oracle for synthetic fault fixtures.

INDEPENDENCE: this module imports only the standard library. It does
NOT import the fixture-definition loader (lab.fault_fixtures) or any
fixture file. It receives a fixture's declared symptoms as plain data
(dicts) plus an observed-state dict, and derives its verdict by its
own evaluation logic below. A fixture therefore cannot grade itself.
"""
from __future__ import annotations


def _get(observed, path):
    cur = observed
    for part in path.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return None
        cur = cur[part]
    return cur


def _check_one(observed, symptom):
    kind = symptom.get("kind")
    field = symptom.get("field", "")
    val = _get(observed, field)
    if kind == "equals":
        return val == symptom.get("value")
    if kind == "in":
        return val in symptom.get("values", [])
    if kind == "gte":
        return isinstance(val, (int, float)) and val >= symptom.get("value")
    if kind == "lte":
        return isinstance(val, (int, float)) and val <= symptom.get("value")
    if kind == "contains":
        return isinstance(val, list) and symptom.get("value") in val
    if kind == "is_true":
        return val is True
    if kind == "is_false":
        return val is False
    return False


def evaluate(observed, declared_symptoms, abstain_when=None):
    """Return 'fault', 'abstain', or 'no_fault'.

    Abstention is checked first: if every abstain condition holds, the
    correct verdict is abstention (e.g. intentionally disabled service).
    Otherwise fault iff ALL declared symptoms hold in observed state.
    """
    if abstain_when:
        if all(_check_one(observed, s) for s in abstain_when):
            return "abstain"
    if declared_symptoms and all(_check_one(observed, s) for s in declared_symptoms):
        return "fault"
    return "no_fault"


def passes(observed, fixture_declared):
    """Pass iff oracle verdict equals the fixture's golden verdict."""
    verdict = evaluate(observed, fixture_declared.get("expected_symptoms", []),
                       fixture_declared.get("abstain_when"))
    return verdict == fixture_declared.get("golden_verdict"), verdict
