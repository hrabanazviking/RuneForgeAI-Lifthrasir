"""Typed event bus for the Heimdall observer (LIF-0201).

SPDX-License-Identifier: GPL-2.0-only

A first, honest, in-process typed event bus: versioned envelopes,
per-boot identifiers, type-checked publish/subscribe dispatch and
JSON serialization round-trip. It carries OBSERVATIONS only.

ADR-0002 message-ownership rules honoured here:
- Observations are never commands: event types in the command /
  authorization family are refused by name (ForbiddenEventTypeError).
  Only the policy engine mints authorizations, and it does not do so
  over this bus.
- Every event is source-attributed, schema-versioned, boot-scoped
  and immutable once created.

Schema proposal alignment: research/25 (API and event schemas) --
version every envelope, validate all inputs strictly, default DENY
for unknown version / verb.
"""
from __future__ import annotations

import copy
import json
import re
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

SCHEMA_VERSION = "1.0"
SUPPORTED_SCHEMA_VERSIONS = frozenset({"1.0"})

_EVENT_TYPE_RE = re.compile(r"^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)+$")

# Types this observation bus must never carry (ADR-0002: observations
# are never commands; only the policy engine mints authorizations).
FORBIDDEN_EVENT_TYPE_PREFIXES = (
    "command.",
    "repair.authorization",
    "repair.execution",
    "authorization.",
    "exec.",
)


class EventBusError(Exception):
    """Base class for all named bus refusals."""


class SchemaVersionError(EventBusError):
    """Raised when an event carries an unsupported schema version."""


class UntypedEventError(EventBusError):
    """Raised when a non-envelope / untyped object is published."""


class MalformedEventError(EventBusError):
    """Raised when an envelope field is missing or malformed."""


class BootIdMismatchError(EventBusError):
    """Raised when an event's boot_id does not match the bus boot."""


class ForbiddenEventTypeError(EventBusError):
    """Raised for command/authorization types on the observation bus."""


def _system_boot_id() -> Optional[str]:
    try:
        text = Path("/proc/sys/kernel/random/boot_id").read_text(
            encoding="utf-8").strip()
        return text or None
    except OSError:
        return None


def mint_boot_id() -> str:
    """Mint a fresh boot identifier, never reused across boots.

    Combines the kernel boot_id (when readable) with a fresh UUID so
    two sessions on the same boot still differ, and two boots never
    share an identifier.
    """
    sys_id = _system_boot_id()
    fresh = uuid.uuid4().hex
    return f"{sys_id}:{fresh}" if sys_id else fresh


@dataclass(frozen=True)
class BootSession:
    """One boot/session scope. Stable within, distinct across."""

    boot_id: str = field(default_factory=mint_boot_id)

    def __post_init__(self) -> None:
        if not isinstance(self.boot_id, str) or not self.boot_id.strip():
            raise MalformedEventError("boot_id must be a non-empty string")


def _check_event_type(event_type: Any) -> str:
    if not isinstance(event_type, str) or not event_type:
        raise MalformedEventError(
            f"event_type must be a non-empty string, got {event_type!r}")
    if not _EVENT_TYPE_RE.match(event_type):
        raise MalformedEventError(
            f"event_type {event_type!r} is malformed: expected "
            "'category.name' lowercase dotted form")
    for prefix in FORBIDDEN_EVENT_TYPE_PREFIXES:
        if event_type == prefix.rstrip(".") or event_type.startswith(prefix):
            raise ForbiddenEventTypeError(
                f"event_type {event_type!r} is forbidden on the "
                "observation bus: observations are never commands and "
                "only the policy engine mints authorizations (ADR-0002)")
    return event_type


def _check_schema_version(version: Any) -> str:
    if version not in SUPPORTED_SCHEMA_VERSIONS:
        raise SchemaVersionError(
            f"unsupported schema_version {version!r}: supported "
            f"versions are {sorted(SUPPORTED_SCHEMA_VERSIONS)}; "
            "events are refused, never silently coerced")
    return version


@dataclass(frozen=True)
class EventEnvelope:
    """One immutable, typed, versioned, boot-scoped event."""

    event_type: str
    source: str
    payload: Dict[str, Any]
    boot_id: str
    schema_version: str = SCHEMA_VERSION
    event_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    recorded_at_ns: int = field(default_factory=time.time_ns)

    def __post_init__(self) -> None:
        _check_schema_version(self.schema_version)
        _check_event_type(self.event_type)
        if not isinstance(self.source, str) or not self.source.strip():
            raise MalformedEventError("source must be a non-empty string")
        if not isinstance(self.boot_id, str) or not self.boot_id.strip():
            raise MalformedEventError("boot_id must be a non-empty string")
        if not isinstance(self.payload, dict):
            raise MalformedEventError(
                f"payload must be a dict, got {type(self.payload).__name__}")
        # Defensive copy so later caller mutation cannot rewrite history.
        object.__setattr__(self, "payload", copy.deepcopy(self.payload))

    def to_dict(self) -> Dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "event_type": self.event_type,
            "event_id": self.event_id,
            "boot_id": self.boot_id,
            "source": self.source,
            "recorded_at_ns": self.recorded_at_ns,
            "payload": copy.deepcopy(self.payload),
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), sort_keys=True)

    @classmethod
    def from_dict(cls, data: Any) -> "EventEnvelope":
        if not isinstance(data, dict):
            raise MalformedEventError(
                f"serialized event must be a dict, got "
                f"{type(data).__name__}")
        missing = [k for k in ("schema_version", "event_type", "boot_id",
                               "source", "payload") if k not in data]
        if missing:
            raise MalformedEventError(
                f"serialized event missing fields: {missing}")
        # Version is checked by __post_init__; refuse before trusting rest.
        _check_schema_version(data["schema_version"])
        return cls(
            event_type=data["event_type"],
            source=data["source"],
            payload=data["payload"],
            boot_id=data["boot_id"],
            schema_version=data["schema_version"],
            event_id=data.get("event_id") or uuid.uuid4().hex,
            recorded_at_ns=int(data.get("recorded_at_ns") or time.time_ns()),
        )

    @classmethod
    def from_json(cls, text: str) -> "EventEnvelope":
        try:
            data = json.loads(text)
        except (ValueError, TypeError) as exc:
            raise MalformedEventError(
                f"event is not valid JSON: {exc}") from exc
        return cls.from_dict(data)


Handler = Callable[[EventEnvelope], None]


class EventBus:
    """Append-dispatch pub/sub bus scoped to one boot session."""

    def __init__(self, boot_session: Optional[BootSession] = None,
                 boot_id: Optional[str] = None) -> None:
        if boot_session is not None and boot_id is not None:
            raise MalformedEventError(
                "pass boot_session or boot_id, not both")
        if boot_session is not None:
            self._session = boot_session
        elif boot_id is not None:
            self._session = BootSession(boot_id=boot_id)
        else:
            self._session = BootSession()
        self._subscribers: Dict[str, List[Handler]] = {}
        self._history: List[EventEnvelope] = []

    @property
    def boot_id(self) -> str:
        return self._session.boot_id

    @property
    def history(self) -> tuple:
        return tuple(self._history)

    def make_event(self, event_type: str, source: str,
                   payload: Dict[str, Any]) -> EventEnvelope:
        """Create an envelope stamped with this bus's boot_id."""
        return EventEnvelope(event_type=event_type, source=source,
                             payload=payload, boot_id=self.boot_id)

    def subscribe(self, event_type: str, handler: Handler) -> Handler:
        _check_event_type(event_type)
        if not callable(handler):
            raise MalformedEventError("handler must be callable")
        self._subscribers.setdefault(event_type, []).append(handler)
        return handler

    def publish(self, event: Any) -> int:
        """Validate at the boundary, then dispatch to matching subs.

        Returns the number of handlers that received the event.
        Untyped objects, wrong versions and foreign-boot events are
        refused by name -- never silently coerced or dropped.
        """
        if not isinstance(event, EventEnvelope):
            raise UntypedEventError(
                f"publish requires an EventEnvelope, got "
                f"{type(event).__name__}: untyped events are refused")
        _check_schema_version(event.schema_version)
        _check_event_type(event.event_type)
        if event.boot_id != self.boot_id:
            raise BootIdMismatchError(
                f"event boot_id {event.boot_id!r} does not match bus "
                f"boot_id {self.boot_id!r}: events from another boot "
                "are refused, not replayed")
        self._history.append(event)
        delivered = 0
        for handler in list(self._subscribers.get(event.event_type, [])):
            handler(event)
            delivered += 1
        return delivered
