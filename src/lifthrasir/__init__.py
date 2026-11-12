"""Lifthrasir core package (src layout, master roadmap section 3).

SPDX-License-Identifier: GPL-2.0-only

Banking union (keeper, LIF-0301 banking): LIF-0201 created this package
with the event bus exports; LIF-0301 added the event store exports on
its own branch. Both export lists are unioned here. Name note: both
modules define a SchemaVersionError; the top-level name stays the
event bus one (LIF-0201 banked behaviour, its tests import it from the
package). The event store's class remains available as
lifthrasir.eventstore.SchemaVersionError and is not shadowed there.
"""
from .eventbus import (
    SCHEMA_VERSION,
    SUPPORTED_SCHEMA_VERSIONS,
    BootIdMismatchError,
    BootSession,
    EventBus,
    EventBusError,
    EventEnvelope,
    ForbiddenEventTypeError,
    MalformedEventError,
    SchemaVersionError,
    UntypedEventError,
    mint_boot_id,
)
from .eventstore import (
    CURRENT_SCHEMA_VERSION,
    GENESIS_HASH,
    RECORD_SCHEMA_VERSION,
    AppendOnlyError,
    DuplicateRecordError,
    EventStore,
    EventStoreError,
    MalformedRecordError,
    StorePathError,
    StoredRecord,
)

__all__ = [
    "SCHEMA_VERSION",
    "SUPPORTED_SCHEMA_VERSIONS",
    "BootIdMismatchError",
    "BootSession",
    "EventBus",
    "EventBusError",
    "EventEnvelope",
    "ForbiddenEventTypeError",
    "MalformedEventError",
    "SchemaVersionError",
    "UntypedEventError",
    "mint_boot_id",
    "CURRENT_SCHEMA_VERSION",
    "GENESIS_HASH",
    "RECORD_SCHEMA_VERSION",
    "AppendOnlyError",
    "DuplicateRecordError",
    "EventStore",
    "EventStoreError",
    "MalformedRecordError",
    "StorePathError",
    "StoredRecord",
]
