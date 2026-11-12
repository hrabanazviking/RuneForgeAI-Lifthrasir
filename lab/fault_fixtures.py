# SPDX-License-Identifier: GPL-2.0-only
"""LIF-0104: loader/validator for synthetic fault fixture definitions.

Fixtures are recorded DATA (JSON under lab/fixtures/), never injected
into the real host. They describe faults inside the disposable lab's
world (lab/vm_workflow.py) only.
"""
from __future__ import annotations
import json
from pathlib import Path

FIXTURE_DIR = Path(__file__).parent / "fixtures"
REQUIRED = ("fault_id", "roadmap_case", "title", "description",
            "injected_state", "expected_symptoms", "golden_observed_state",
            "golden_verdict")


def load_fixtures():
    out = []
    for p in sorted(FIXTURE_DIR.glob("*.json")):
        out.append(json.loads(p.read_text()))
    return out


def validate_fixture(fx):
    errs = []
    for k in REQUIRED:
        if k not in fx:
            errs.append(f"missing {k}")
    if not fx.get("expected_symptoms"):
        errs.append("no expected_symptoms")
    if fx.get("golden_verdict") not in ("fault", "abstain"):
        errs.append("bad golden_verdict")
    return errs
