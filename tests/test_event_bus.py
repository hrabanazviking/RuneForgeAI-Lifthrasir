"""LIF-0201 typed event bus tests.

Covers: schema version present + enforced, boot ID present / stable
within a boot / distinct across boots, typed dispatch reaches only
matching subscribers, malformed + untyped + forbidden events refused,
serialization round-trip.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from lifthrasir.eventbus import (  # noqa: E402
    SCHEMA_VERSION,
    BootIdMismatchError,
    BootSession,
    EventBus,
    EventEnvelope,
    ForbiddenEventTypeError,
    MalformedEventError,
    SchemaVersionError,
    UntypedEventError,
    mint_boot_id,
)


def _bus():
    return EventBus()


def test_schema_version_present_on_every_event():
    bus = _bus()
    ev = bus.make_event("health.observation", "heimdall.test", {"ok": True})
    assert ev.schema_version == SCHEMA_VERSION
    assert ev.to_dict()["schema_version"] == SCHEMA_VERSION


def test_wrong_schema_version_refused_at_construction():
    with pytest.raises(SchemaVersionError):
        EventEnvelope(event_type="health.observation", source="s",
                      payload={}, boot_id="b1", schema_version="99.0")


def test_wrong_schema_version_refused_on_deserialize():
    bus = _bus()
    data = bus.make_event("health.observation", "s", {}).to_dict()
    data["schema_version"] = "0.0-ancient"
    with pytest.raises(SchemaVersionError):
        EventEnvelope.from_dict(data)


def test_missing_schema_version_refused_on_deserialize():
    bus = _bus()
    data = bus.make_event("health.observation", "s", {}).to_dict()
    del data["schema_version"]
    with pytest.raises(MalformedEventError):
        EventEnvelope.from_dict(data)


def test_boot_id_present_and_stable_within_one_bus():
    bus = _bus()
    a = bus.make_event("health.observation", "s", {"n": 1})
    b = bus.make_event("health.observation", "s", {"n": 2})
    assert a.boot_id and a.boot_id == b.boot_id == bus.boot_id


def test_boot_ids_distinct_across_sessions():
    ids = {mint_boot_id() for _ in range(5)}
    assert len(ids) == 5
    assert BootSession().boot_id != BootSession().boot_id
    assert EventBus().boot_id != EventBus().boot_id


def test_event_from_another_boot_refused_not_replayed():
    bus_a, bus_b = _bus(), _bus()
    foreign = bus_a.make_event("health.observation", "s", {})
    with pytest.raises(BootIdMismatchError):
        bus_b.publish(foreign)
    assert bus_b.history == ()


def test_typed_dispatch_reaches_only_matching_subscribers():
    bus = _bus()
    seen_health, seen_incident = [], []
    bus.subscribe("health.observation", seen_health.append)
    bus.subscribe("incident.opened", seen_incident.append)
    ev = bus.make_event("health.observation", "s", {"metric": "psi"})
    assert bus.publish(ev) == 1
    assert seen_health == [ev]
    assert seen_incident == []
    assert bus.history == (ev,)


def test_untyped_events_refused_by_name():
    bus = _bus()
    for bad in ({"event_type": "health.observation"}, "health.observation",
                None, 42, object()):
        with pytest.raises(UntypedEventError):
            bus.publish(bad)
    assert bus.history == ()


def test_malformed_events_refused():
    with pytest.raises(MalformedEventError):
        EventEnvelope(event_type="NoDotsOrCaps", source="s", payload={},
                      boot_id="b")
    with pytest.raises(MalformedEventError):
        EventEnvelope(event_type="health.observation", source="",
                      payload={}, boot_id="b")
    with pytest.raises(MalformedEventError):
        EventEnvelope(event_type="health.observation", source="s",
                      payload=["not", "a", "dict"], boot_id="b")
    with pytest.raises(MalformedEventError):
        EventEnvelope(event_type="health.observation", source="s",
                      payload={}, boot_id="")


def test_command_and_authorization_types_forbidden():
    # ADR-0002: observations are never commands; only the policy
    # engine mints authorizations -- and not over this bus.
    for bad_type in ("command.restart_unit", "repair.authorization",
                     "authorization.grant"):
        with pytest.raises(ForbiddenEventTypeError):
            EventEnvelope(event_type=bad_type, source="s", payload={},
                          boot_id="b")


def test_serialization_round_trip():
    bus = _bus()
    ev = bus.make_event("health.observation", "heimdall.test",
                        {"metric": "memory_psi", "value": 3})
    back = EventEnvelope.from_json(ev.to_json())
    assert back == ev
    assert back.to_dict() == ev.to_dict()
    # A round-tripped event from the same boot still publishes.
    got = []
    bus.subscribe("health.observation", got.append)
    assert bus.publish(back) == 1
    assert got == [back]


def test_event_is_immutable_and_payload_is_copied():
    payload = {"nested": {"x": 1}}
    ev = EventEnvelope(event_type="health.observation", source="s",
                       payload=payload, boot_id="b")
    payload["nested"]["x"] = 999
    assert ev.payload["nested"]["x"] == 1
    with pytest.raises(Exception):
        ev.event_type = "incident.opened"  # frozen dataclass


def test_subscribe_rejects_bad_type_and_non_callable():
    bus = _bus()
    with pytest.raises(MalformedEventError):
        bus.subscribe("BAD TYPE", lambda e: None)
    with pytest.raises(MalformedEventError):
        bus.subscribe("health.observation", "not-callable")
