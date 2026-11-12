# SPDX-License-Identifier: GPL-2.0-only
"""LIF-0504 verification-and-soak workflow tests.

Scope: fixture workloads only.  Probes are scripted sequences
(tests/fixtures/lif0504/cases.json) or in-code callables; the
clock and sleeper are fakes everywhere, so no test really waits
and no test touches a live host, service or system path.  Event
logging is exercised against the banked LIF-0201 event bus and
the banked LIF-0301 event store (the store on a pytest tmp_path
file only).

Pinned behaviour: a soak verifies only when the trailing all-pass
streak reaches the required count (default: every round); mixed
pass/fail rounds are FLAKY, never verified; an all-fail soak is
FAILED; a duration- or cancel-aborted soak is ABORTED with the
reason named and is never a pass; specs above the hard caps are
refused (unbounded soaks do not exist); a probe map that does not
match the spec exactly is refused (no check is silently skipped);
a raising or malformed probe is a failed check, never a crash
and never a pass.

The mutated-fixture test is this slice's NEGATIVE CONTROL: the
exact healthy fixture that verifies is re-run with ONE scripted
outcome flipped mid-soak, and the run must come back FLAKY -- a
soak that still verifies it has failed its whole purpose.
"""
import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from lifthrasir import soak  # noqa: E402
from lifthrasir.eventbus import EventBus  # noqa: E402
from lifthrasir.eventstore import EventStore  # noqa: E402

FIXTURE = REPO / "tests" / "fixtures" / "lif0504" / "cases.json"
FIXED_WALL = "2026-11-05T18:00:00Z"


def scenarios():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))["scenarios"]


class FakeClock:
    def __init__(self, step=1.0):
        self.now = 0.0
        self.step = step

    def __call__(self):
        value = self.now
        self.now += self.step
        return value


def run_scenario(name, **overrides):
    data = scenarios()[name]
    kwargs = dict(rounds=data["rounds"])
    if "required_consecutive_passes" in data:
        kwargs["required_consecutive_passes"] = data["required_consecutive_passes"]
    kwargs.update(overrides.pop("spec", {}))
    spec = soak.SoakSpec(
        plan_id="plan-2026-0504", incident_id="inc-2026-0504",
        target="demo.service", checks=tuple(data["checks"]), **kwargs)
    probes = {n: soak.sequence_probe(seq)
              for n, seq in data["checks"].items()}
    run_kwargs = dict(clock=FakeClock(step=0.5), sleeper=lambda s: None,
                      wall_clock=lambda: FIXED_WALL)
    run_kwargs.update(overrides)
    return data, soak.run_verification(spec, probes, **run_kwargs)


def test_healthy_fixture_verifies():
    data, report = run_scenario("healthy")
    assert report.verdict == data["expected_verdict"] == "verified"
    assert report.rounds_completed == 4
    assert report.trailing_streak == 4
    assert all(not c.flapped for c in report.checks)
    assert report.abort_reason is None


def test_flaky_fixture_is_flaky_and_names_the_flapping_check():
    data, report = run_scenario("flaky")
    assert report.verdict == data["expected_verdict"] == "flaky"
    flapped = [c.name for c in report.checks if c.flapped]
    assert flapped == data["expected_flapped"]
    by_name = {c.name: c for c in report.checks}
    assert by_name["service-active"].passes == 2
    assert by_name["service-active"].failures == 2
    assert by_name["service-active"].transitions == 3
    assert by_name["port-open"].flapped is False


def test_dead_fixture_fails():
    data, report = run_scenario("dead")
    assert report.verdict == data["expected_verdict"] == "failed"
    assert report.trailing_streak == 0


def test_recovering_fixture_verifies_on_closing_streak():
    data, report = run_scenario("recovering")
    assert report.verdict == data["expected_verdict"] == "verified"
    assert report.trailing_streak == data["expected_trailing_streak"]
    # The early failure is retained, not rewritten away.
    assert report.rounds[0].passed is False
    by_name = {c.name: c for c in report.checks}
    assert by_name["service-active"].flapped is True


def test_early_verify_stops_once_required_streak_is_met():
    data, report = run_scenario("early-verify")
    assert report.verdict == "verified"
    assert report.rounds_completed == data["expected_rounds_completed"]
    assert report.rounds_completed < report.rounds_requested


def test_negative_control_mutated_healthy_fixture_must_not_verify():
    data = scenarios()["healthy"]
    checks = {n: list(s) for n, s in data["checks"].items()}
    checks["service-active"][2] = False  # one mid-soak flip
    spec = soak.SoakSpec(
        plan_id="plan-2026-0504", incident_id="inc-2026-0504",
        target="demo.service", checks=tuple(checks), rounds=4)
    probes = {n: soak.sequence_probe(s) for n, s in checks.items()}
    report = soak.run_verification(
        spec, probes, clock=FakeClock(step=0.5),
        sleeper=lambda s: None, wall_clock=lambda: FIXED_WALL)
    assert report.verdict == "flaky"
    assert report.verdict != "verified"


def test_event_bus_logging_records_the_whole_run():
    bus = EventBus(boot_id="boot-soak-test")
    _, report = run_scenario("healthy", bus=bus)
    types = [e.event_type for e in bus.history]
    assert types[0] == "verification.started"
    assert types[-1] == "verification.completed"
    assert types.count("verification.round") == 4
    assert report.events_published == len(types) == 6
    done = bus.history[-1]
    assert done.payload["verdict"] == "verified"
    assert done.payload["plan_id"] == "plan-2026-0504"
    assert done.source == "eir"


def test_event_store_logging_appends_valid_evidence(tmp_path):
    bus = EventBus(boot_id="boot-soak-test")
    with EventStore(tmp_path / "events.db") as store:
        _, report = run_scenario("healthy", bus=bus, store=store)
        assert report.evidence_id is not None
        assert report.evidence_id.startswith("ev-soak-")
        assert store.count() == 1
        stored = store.get_record(report.evidence_id)
        assert stored.record_type == "evidence"
        assert stored.payload["kind"] == "test-run"
        assert stored.payload["plan_id"] == "plan-2026-0504"
        assert stored.payload["tool_versions"]
        assert store.verify_chain() is True


def test_evidence_record_validates_against_banked_schema(tmp_path):
    jsonschema = pytest.importorskip("jsonschema")
    schema = json.loads((
        REPO / "docs" / "protocols" / "schemas" / "v0.1"
        / "evidence.schema.json").read_text(encoding="utf-8"))
    _, report = run_scenario("flaky")
    record = soak.build_evidence_record(
        report, recorded_at=FIXED_WALL, boot_id="boot-soak-test")
    jsonschema.validate(record, schema)
    assert record["evidence_status"] == "lab-verified"
    assert any("flapped" in lim for lim in record["limitations"])


def test_unbounded_specs_are_refused_by_name():
    base = dict(plan_id="plan-2026-0504", incident_id="inc-2026-0504",
                target="demo.service", checks=("service-active",))
    with pytest.raises(soak.UnboundedSoakError):
        soak.SoakSpec(rounds=soak.MAX_ROUNDS + 1, **base)
    with pytest.raises(soak.UnboundedSoakError):
        soak.SoakSpec(rounds=2, interval_s=soak.MAX_INTERVAL_S + 1, **base)
    with pytest.raises(soak.UnboundedSoakError):
        soak.SoakSpec(rounds=2, max_duration_s=soak.MAX_DURATION_S + 1, **base)
    with pytest.raises(soak.UnboundedSoakError):
        soak.SoakSpec(checks=tuple(f"check-{i}" for i in range(soak.MAX_CHECKS + 1)),
                      **{k: v for k, v in base.items() if k != "checks"})


def test_malformed_specs_are_refused():
    base = dict(plan_id="plan-2026-0504", incident_id="inc-2026-0504",
                target="demo.service", checks=("service-active",))
    with pytest.raises(soak.MalformedSpecError):
        soak.SoakSpec(plan_id="not-a-plan", **{k: v for k, v in base.items() if k != "plan_id"})
    with pytest.raises(soak.MalformedSpecError):
        soak.SoakSpec(checks=(), **{k: v for k, v in base.items() if k != "checks"})
    with pytest.raises(soak.MalformedSpecError):
        soak.SoakSpec(checks=("dup", "dup"), **{k: v for k, v in base.items() if k != "checks"})
    with pytest.raises(soak.MalformedSpecError):
        soak.SoakSpec(rounds=0, **base)
    with pytest.raises(soak.MalformedSpecError):
        soak.SoakSpec(rounds=3, required_consecutive_passes=4, **base)
    with pytest.raises(soak.MalformedSpecError):
        soak.sequence_probe([])


def test_probe_map_must_match_spec_exactly():
    spec = soak.SoakSpec(plan_id="plan-2026-0504",
                         incident_id="inc-2026-0504",
                         target="demo.service",
                         checks=("service-active", "config-valid"),
                         rounds=2)
    with pytest.raises(soak.UnknownCheckError):
        soak.run_verification(spec, {"service-active": lambda: True},
                              clock=FakeClock(), sleeper=lambda s: None)
    with pytest.raises(soak.UnknownCheckError):
        soak.run_verification(
            spec, {"service-active": lambda: True,
                   "config-valid": lambda: True,
                   "surprise": lambda: True},
            clock=FakeClock(), sleeper=lambda s: None)


def test_raising_and_malformed_probes_are_failed_checks_not_crashes():
    def boom():
        raise RuntimeError("probe exploded")

    spec = soak.SoakSpec(plan_id="plan-2026-0504",
                         incident_id="inc-2026-0504",
                         target="demo.service",
                         checks=("service-active", "config-valid"),
                         rounds=2)
    report = soak.run_verification(
        spec, {"service-active": boom, "config-valid": lambda: "yes"},
        clock=FakeClock(), sleeper=lambda s: None)
    assert report.verdict == "failed"
    details = [o.detail for r in report.rounds for o in r.outcomes]
    assert any("probe raised RuntimeError" in d for d in details)
    assert any("malformed result" in d for d in details)


def test_probe_result_shapes_bool_tuple_dict_outcome():
    spec = soak.SoakSpec(plan_id="plan-2026-0504",
                         incident_id="inc-2026-0504",
                         target="demo.service",
                         checks=("a-check", "b-check", "c-check", "d-check"),
                         rounds=1)
    probes = {
        "a-check": lambda: True,
        "b-check": lambda: (True, "tuple detail"),
        "c-check": lambda: {"passed": True, "detail": "dict detail"},
        "d-check": lambda: soak.CheckOutcome("d-check", True, "outcome detail"),
    }
    report = soak.run_verification(spec, probes, clock=FakeClock(),
                                   sleeper=lambda s: None)
    assert report.verdict == "verified"
    details = [o.detail for o in report.rounds[0].outcomes]
    assert details == ["", "tuple detail", "dict detail", "outcome detail"]


def test_fail_fast_stops_at_first_failed_round():
    data, report = run_scenario("flaky", spec={"fail_fast": True})
    assert report.rounds_completed == 2
    assert report.fail_fast_stopped is True
    assert report.verdict == "flaky"


def test_duration_budget_aborts_and_is_never_a_pass():
    clock = FakeClock(step=100.0)
    spec = soak.SoakSpec(plan_id="plan-2026-0504",
                         incident_id="inc-2026-0504",
                         target="demo.service",
                         checks=("service-active",), rounds=5,
                         max_duration_s=150.0)
    report = soak.run_verification(
        spec, {"service-active": lambda: True}, clock=clock,
        sleeper=lambda s: None)
    assert report.verdict == "aborted"
    assert report.abort_reason == "duration-budget"
    assert report.rounds_completed < 5


def test_cancellation_aborts_with_reason_named():
    calls = {"n": 0}

    def cancelled():
        calls["n"] += 1
        return calls["n"] >= 2

    spec = soak.SoakSpec(plan_id="plan-2026-0504",
                         incident_id="inc-2026-0504",
                         target="demo.service",
                         checks=("service-active",), rounds=5)
    report = soak.run_verification(
        spec, {"service-active": lambda: True}, clock=FakeClock(),
        sleeper=lambda s: None, cancelled=cancelled)
    assert report.verdict == "aborted"
    assert report.abort_reason == "cancelled"
    assert report.rounds_completed == 2


def test_interval_is_passed_to_sleeper_between_rounds_only():
    slept = []
    spec = soak.SoakSpec(plan_id="plan-2026-0504",
                         incident_id="inc-2026-0504",
                         target="demo.service",
                         checks=("service-active",), rounds=3,
                         interval_s=5.0)
    soak.run_verification(spec, {"service-active": lambda: True},
                          clock=FakeClock(), sleeper=slept.append)
    assert slept == [5.0, 5.0]


def test_sequence_probe_repeats_last_outcome_when_exhausted():
    probe = soak.sequence_probe([False, True])
    assert [probe(), probe(), probe(), probe()] == [False, True, True, True]


def test_report_to_dict_round_trips_through_json():
    _, report = run_scenario("flaky")
    data = json.loads(json.dumps(report.to_dict()))
    assert data["verdict"] == "flaky"
    assert data["rounds_completed"] == 4
    assert data["checks"][0]["name"] == "service-active"


def test_module_source_has_no_host_mutation_surface():
    src = (REPO / "src" / "lifthrasir" / "soak.py").read_text(encoding="utf-8")
    for token in ("import subprocess", "import socket", "import os",
                  "os.system", "shutil", "eval(", "exec(", "open(",
                  "Popen", "systemd", "Signed-off-by"):
        assert token not in src, token
