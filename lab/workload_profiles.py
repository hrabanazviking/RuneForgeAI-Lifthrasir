# SPDX-License-Identifier: GPL-2.0-only
"""LIF-1002: workload profiles for the P10 performance laboratory.

Phase P10 (performance optimizer), building directly on the LIF-1001
benchmark harness (lab/benchmark_harness.py). The harness measures;
this module declares WHAT is measured. A workload profile is a
declarative, deterministic, fixture-level definition of one of the
five workload families the backlog names for LIF-1002: memory
pressure, compilation, inference, graphics, and I/O.

Design (following the LIF-1001 harness contract and master roadmap
section 5 benchmark science):

- A profile is data, never code and never a shell command. It names
a category, an ordered list of synthetic operations drawn from a
closed allowlist, a seed, repetition/warmup counts, a wall timeout,
a declared resource envelope (memory cap, thread count), the
metrics a run must report, a safety class, environment pins, and
the LIF-1001 harness workload it binds to. Validation is
fail-closed: an unknown category, an operation kind outside the
allowlist, an operation above the fixture size caps, a pin that
would subvert the measured process, or an envelope outside bounds
is refused, never trimmed or silently repaired.
- Profiles are FIXTURE-LEVEL by construction. The synthetic executor
in this module interprets operations as bounded in-memory integer
and byte work (the largest single operation touches 64 KiB). It
never allocates under real memory pressure, never invokes a
compiler, never loads a model, never touches a GPU or a display,
and never writes to disk. A profile whose safety class is lab-vm
is a declaration that any REAL run of that shape belongs in a
disposable VM (master roadmap section 0 invariant 5); the built-in
catalog is entirely fixture class. Nothing in this slice runs a
heavy workload on any machine, shared or otherwise.
- Determinism: a profile has a canonical dict form and a SHA-256
fingerprint over it. The synthetic executor is a pure function of
the profile and its seed: the same profile always yields the same
result checksum, so a profile edit that changes behaviour changes
both the fingerprint and the checksum -- the fixture-level
differential this slice is tested at.
- Harness binding: environment_spec_dict renders the profile's
measurement controls in the exact LIF-1001 EnvironmentSpec dict
shape (schema lifthrasir.benchmark.v0.1), so a profile can be
measured by the banked harness without translation drift. The
tests prove the banked harness accepts every built-in profile's
rendered spec.
- Catalogs: a catalog is a set of profiles with unique ids.
  catalog_from_dict / load_catalog validate strictly (unknown
  fields refused, duplicate ids refused). missing_categories
  reports which of the five backlog families a catalog does not
  cover; the built-in catalog covers all five.
- Reports: render_markdown renders a catalog deterministically
  (fixed field order, sorted by profile id, no timestamps, no host
  values), so the same catalog yields a byte-identical report.

Offline guarantee: this module imports only standard-library
modules, reads only files it is explicitly given, and performs no
network access, no subprocess, and no disk writes. The test suite
proves the import surface by scanning this module's imports.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from pathlib import Path

PROFILE_SCHEMA = "lifthrasir.workload-profile.v0.1"
CATALOG_SCHEMA = "lifthrasir.workload-catalog.v0.1"
BENCH_SCHEMA = "lifthrasir.benchmark.v0.1"

CATEGORIES = ("memory-pressure", "compilation", "inference",
              "graphics", "io")

# Closed operation allowlist. Each kind is a bounded synthetic
# operation interpreted in memory by execute_profile; there is no
# operation kind that shells out, writes files, or stresses a host
# subsystem. Sizes are element counts, capped per operation and in
# total so a profile stays fixture-scale by construction.
OP_KINDS = ("alloc-touch", "buffer-copy", "hash-chain",
            "matvec", "pixel-mix", "sort-fixed")
MAX_OP_SIZE = 65536
MAX_OPERATIONS = 16
MAX_TOTAL_SIZE = 262144

MIN_REPETITIONS = 3
MAX_REPETITIONS = 1000
MAX_WARMUP = 100
MIN_TIMEOUT_S = 0.05
MAX_TIMEOUT_S = 600.0
MIN_MEMORY_CAP_MB = 1
MAX_MEMORY_CAP_MB = 4096
MAX_THREADS = 64

METRICS = ("wall_time_s", "checksum", "bytes_touched",
           "ops_completed", "allocations")
SAFETY_CLASSES = ("fixture", "lab-vm")
HARNESS_WORKLOADS = ("hash-chain", "sort-fixed")

FORBIDDEN_PIN_KEYS = frozenset({
    "LD_PRELOAD", "LD_LIBRARY_PATH", "LD_AUDIT", "LD_DEBUG",
    "PYTHONPATH", "PYTHONSTARTUP", "PYTHONHOME", "PERL5OPT",
    "RUBYOPT", "NODE_OPTIONS",
})
_ENV_KEY_CHARS = frozenset(
    "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_")
_ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]*$")


class ProfileError(Exception):
    """Base class for all workload profile refusals."""


class MalformedProfileError(ProfileError):
    """The profile or catalog data is malformed."""


class UnknownCategoryError(ProfileError):
    """The category is not one of the five backlog families."""


class UnsafeProfileError(ProfileError):
    """The profile asks for something outside the fixture bounds."""


class DuplicateProfileError(ProfileError):
    """A catalog carries the same profile id twice."""


def _check_env_key(key):
    if not isinstance(key, str) or not key:
        raise UnsafeProfileError("env key must be a non-empty string")
    if key[0].isdigit() or any(c not in _ENV_KEY_CHARS for c in key):
        raise UnsafeProfileError("malformed env key: " + repr(key))
    if key != key.upper():
        raise UnsafeProfileError("env key must be uppercase: " + repr(key))
    return key


def _check_int(name, value, low, high):
    if isinstance(value, bool) or not isinstance(value, int):
        raise MalformedProfileError(name + " must be an int")
    if not low <= value <= high:
        raise MalformedProfileError(
            "%s must be in [%d, %d]" % (name, low, high))
    return value


@dataclass(frozen=True)
class Operation:
    """One bounded synthetic operation (kind from the allowlist)."""

    kind: str
    size: int

    def __post_init__(self):
        if self.kind not in OP_KINDS:
            raise UnsafeProfileError(
                "operation kind not in allowlist: " + repr(self.kind))
        _check_int("operation size", self.size, 1, MAX_OP_SIZE)


def op_as_dict(op):
    return {"kind": op.kind, "size": op.size}


def op_from_dict(data):
    if not isinstance(data, dict):
        raise MalformedProfileError("operation must be a dict")
    extra = set(data) - {"kind", "size"}
    if extra:
        raise MalformedProfileError(
            "unknown operation fields: " + ", ".join(sorted(extra)))
    if "kind" not in data or "size" not in data:
        raise MalformedProfileError("operation needs kind and size")
    return Operation(kind=data["kind"], size=data["size"])


@dataclass(frozen=True)
class WorkloadProfile:
    """A declarative, deterministic workload profile (data only)."""

    profile_id: str
    category: str
    title: str
    operations: tuple
    seed: int = 1
    repetitions: int = 5
    warmup: int = 1
    timeout_s: float = 30.0
    memory_cap_mb: int = 64
    threads: int = 1
    metrics: tuple = ("wall_time_s", "checksum")
    safety_class: str = "fixture"
    harness_workload: str = "hash-chain"
    pinned_env: dict = field(default_factory=dict)
    description: str = ""

    def __post_init__(self):
        if (not isinstance(self.profile_id, str)
                or not _ID_RE.match(self.profile_id)
                or not any(c.isdigit() for c in self.profile_id)):
            raise MalformedProfileError(
                "profile_id must match [a-z0-9][a-z0-9._-]* and "
                "contain a digit: " + repr(self.profile_id))
        if self.category not in CATEGORIES:
            raise UnknownCategoryError(
                "unknown workload category: " + repr(self.category))
        if not isinstance(self.title, str) or not self.title:
            raise MalformedProfileError("title must be non-empty")
        if not isinstance(self.description, str):
            raise MalformedProfileError("description must be a string")
        if (not isinstance(self.operations, (list, tuple))
                or not self.operations):
            raise MalformedProfileError(
                "operations must be a non-empty list")
        ops = tuple(self.operations)
        if len(ops) > MAX_OPERATIONS:
            raise UnsafeProfileError(
                "too many operations: %d > %d"
                % (len(ops), MAX_OPERATIONS))
        for op in ops:
            if not isinstance(op, Operation):
                raise MalformedProfileError(
                    "operations must be Operation values")
        total = sum(op.size for op in ops)
        if total > MAX_TOTAL_SIZE:
            raise UnsafeProfileError(
                "total operation size %d exceeds fixture cap %d"
                % (total, MAX_TOTAL_SIZE))
        object.__setattr__(self, "operations", ops)
        if isinstance(self.seed, bool) or not isinstance(self.seed, int):
            raise MalformedProfileError("seed must be an int")
        _check_int("repetitions", self.repetitions,
                   MIN_REPETITIONS, MAX_REPETITIONS)
        _check_int("warmup", self.warmup, 0, MAX_WARMUP)
        if (isinstance(self.timeout_s, bool)
                or not isinstance(self.timeout_s, (int, float))
                or not MIN_TIMEOUT_S <= float(self.timeout_s)
                <= MAX_TIMEOUT_S):
            raise MalformedProfileError(
                "timeout_s must be in [%s, %s]"
                % (MIN_TIMEOUT_S, MAX_TIMEOUT_S))
        _check_int("memory_cap_mb", self.memory_cap_mb,
                   MIN_MEMORY_CAP_MB, MAX_MEMORY_CAP_MB)
        _check_int("threads", self.threads, 1, MAX_THREADS)
        if (not isinstance(self.metrics, (list, tuple))
                or not self.metrics):
            raise MalformedProfileError("metrics must be non-empty")
        metrics = tuple(self.metrics)
        for name in metrics:
            if name not in METRICS:
                raise MalformedProfileError(
                    "unknown metric: " + repr(name))
        if len(set(metrics)) != len(metrics):
            raise MalformedProfileError("metrics must be unique")
        if "checksum" not in metrics:
            raise MalformedProfileError(
                "metrics must include checksum (determinism gate)")
        object.__setattr__(self, "metrics", metrics)
        if self.safety_class not in SAFETY_CLASSES:
            raise MalformedProfileError(
                "unknown safety_class: " + repr(self.safety_class))
        if self.harness_workload not in HARNESS_WORKLOADS:
            raise MalformedProfileError(
                "unknown harness_workload: "
                + repr(self.harness_workload))
        if not isinstance(self.pinned_env, dict):
            raise MalformedProfileError("pinned_env must be a dict")
        for key, value in self.pinned_env.items():
            _check_env_key(key)
            if key in FORBIDDEN_PIN_KEYS:
                raise UnsafeProfileError(
                    "pin refused (process-subverting key): " + key)
            if not isinstance(value, str):
                raise MalformedProfileError(
                    "pinned env value must be a string: " + key)

    def fingerprint(self):
        """SHA-256 over the canonical dict form of this profile."""
        blob = json.dumps(profile_as_dict(self), sort_keys=True,
                          separators=(",", ":")).encode("utf-8")
        return hashlib.sha256(blob).hexdigest()


_PROFILE_FIELDS = {"schema", "profile_id", "category", "title",
                   "description", "operations", "seed", "repetitions",
                   "warmup", "timeout_s", "memory_cap_mb", "threads",
                   "metrics", "safety_class", "harness_workload",
                   "pinned_env"}


def profile_as_dict(profile):
    return {
        "schema": PROFILE_SCHEMA,
        "profile_id": profile.profile_id,
        "category": profile.category,
        "title": profile.title,
        "description": profile.description,
        "operations": [op_as_dict(op) for op in profile.operations],
        "seed": profile.seed,
        "repetitions": profile.repetitions,
        "warmup": profile.warmup,
        "timeout_s": float(profile.timeout_s),
        "memory_cap_mb": profile.memory_cap_mb,
        "threads": profile.threads,
        "metrics": list(profile.metrics),
        "safety_class": profile.safety_class,
        "harness_workload": profile.harness_workload,
        "pinned_env": dict(sorted(profile.pinned_env.items())),
    }


def profile_from_dict(data):
    """Build a WorkloadProfile from its strict dict form."""
    if not isinstance(data, dict):
        raise MalformedProfileError("profile must be a dict")
    extra = set(data) - _PROFILE_FIELDS
    if extra:
        raise MalformedProfileError(
            "unknown profile fields: " + ", ".join(sorted(extra)))
    if data.get("schema", PROFILE_SCHEMA) != PROFILE_SCHEMA:
        raise MalformedProfileError("profile schema mismatch")
    for name in ("profile_id", "category", "title", "operations"):
        if name not in data:
            raise MalformedProfileError(name + " is required")
    if not isinstance(data["operations"], list):
        raise MalformedProfileError("operations must be a list")
    return WorkloadProfile(
        profile_id=data["profile_id"],
        category=data["category"],
        title=data["title"],
        operations=tuple(op_from_dict(op) for op in data["operations"]),
        seed=data.get("seed", 1),
        repetitions=data.get("repetitions", 5),
        warmup=data.get("warmup", 1),
        timeout_s=data.get("timeout_s", 30.0),
        memory_cap_mb=data.get("memory_cap_mb", 64),
        threads=data.get("threads", 1),
        metrics=tuple(data.get("metrics", ("wall_time_s", "checksum"))),
        safety_class=data.get("safety_class", "fixture"),
        harness_workload=data.get("harness_workload", "hash-chain"),
        pinned_env=data.get("pinned_env", {}),
        description=data.get("description", ""),
    )


def environment_spec_dict(profile):
    """Render measurement controls in the LIF-1001 harness shape."""
    return {
        "schema": BENCH_SCHEMA,
        "workload_id": profile.harness_workload,
        "seed": profile.seed,
        "repetitions": profile.repetitions,
        "warmup": profile.warmup,
        "timeout_s": float(profile.timeout_s),
        "pinned_env": dict(sorted(profile.pinned_env.items())),
    }


def _mix(state, value):
    state ^= (value + 0x9E3779B97F4A7C15) & 0xFFFFFFFFFFFFFFFF
    state = (state * 6364136223846793005 + 1442695040888963407) \
        & 0xFFFFFFFFFFFFFFFF
    state ^= state >> 29
    return state


def _run_operation(state, op, seed):
    """Bounded synthetic work for one operation; returns (state, bytes)."""
    n = op.size
    if op.kind == "alloc-touch":
        buf = bytearray(n)
        for i in range(0, n, 257):
            buf[i] = (state + i) & 0xFF
        return _mix(state, sum(buf[::257]) + n), n
    if op.kind == "buffer-copy":
        src = bytes(((state >> (i % 8)) + i) & 0xFF for i in range(n))
        dst = bytes(src)
        return _mix(state, sum(dst[::251]) + n), 2 * n
    if op.kind == "hash-chain":
        for i in range(n):
            state ^= (state << 13) & 0xFFFFFFFFFFFFFFFF
            state ^= state >> 7
            state ^= (state << 17) & 0xFFFFFFFFFFFFFFFF
            state = (state + i) & 0xFFFFFFFFFFFFFFFF
        return state, 0
    if op.kind == "matvec":
        dim = max(1, int(n ** 0.5))
        acc = state
        for r in range(dim):
            row = 0
            for c in range(dim):
                row = (row + ((r * 31 + c * 17 + seed) & 0xFF)
                       * ((c + seed) & 0xFF)) & 0xFFFFFFFFFFFFFFFF
            acc = _mix(acc, row)
        return acc, dim * dim
    if op.kind == "pixel-mix":
        buf = bytearray(n)
        for i in range(n):
            buf[i] = (buf[i - 1] + ((state >> (i % 8)) & 0xFF) + i) & 0xFF \
                if i else (state & 0xFF)
        return _mix(state, sum(buf[::241]) + n), n
    if op.kind == "sort-fixed":
        values = []
        s = seed & 0x7FFFFFFF
        for _ in range(n):
            s = (s * 1103515245 + 12345) & 0x7FFFFFFF
            values.append(s)
        values.sort()
        digest = hashlib.sha256(
            ",".join(str(v) for v in values[::257]).encode("utf-8"))
        return _mix(state, int(digest.hexdigest()[:8], 16)), 0
    raise UnsafeProfileError("unreachable operation kind: " + op.kind)


def execute_profile(profile):
    """Deterministic synthetic execution of a fixture profile.

    Pure function of the profile: in-memory bounded work only, no
    disk, no subprocess, no host stress of any kind. A lab-vm class
    profile is refused here -- this executor is fixture-only, and a
    real run of a lab-vm shape belongs in a disposable VM driven by
    other tooling, never by this function on a host.
    """
    if profile.safety_class != "fixture":
        raise UnsafeProfileError(
            "execute_profile is fixture-only; safety_class "
            + repr(profile.safety_class)
            + " requires a disposable VM, not host execution")
    state = (profile.seed * 2654435761 + 0x4C494653) \
        & 0xFFFFFFFFFFFFFFFF
    bytes_touched = 0
    for index, op in enumerate(profile.operations):
        state = _mix(state, index + 1)
        state, touched = _run_operation(state, op, profile.seed)
        bytes_touched += touched
    checksum = "%016x" % state
    return {
        "schema": PROFILE_SCHEMA,
        "profile_id": profile.profile_id,
        "fingerprint": profile.fingerprint(),
        "checksum": checksum,
        "ops_completed": len(profile.operations),
        "bytes_touched": bytes_touched,
    }


def _profile(profile_id, category, title, description, operations,
             **kw):
    return WorkloadProfile(profile_id=profile_id, category=category,
                           title=title, description=description,
                           operations=tuple(operations), **kw)


BUILTIN_PROFILES = (
    _profile(
        "mem-pressure-fixture.v1", "memory-pressure",
        "Memory pressure (fixture)",
        "Bounded allocation-touch and copy pattern standing in for "
        "allocation, reclaim and pressure behaviour; synthetic and "
        "in-memory only, never real host pressure.",
        [Operation("alloc-touch", 32768), Operation("buffer-copy", 16384)],
        seed=11, memory_cap_mb=64, threads=1,
        metrics=("wall_time_s", "checksum", "bytes_touched",
                 "allocations"),
        harness_workload="hash-chain"),
    _profile(
        "compile-fixture.v1", "compilation",
        "Compilation (fixture)",
        "Hash-chain and fixed-sort pattern standing in for a "
        "parallel build pipeline; no compiler is invoked.",
        [Operation("hash-chain", 20000), Operation("sort-fixed", 4000)],
        seed=12, memory_cap_mb=256, threads=4,
        metrics=("wall_time_s", "checksum", "ops_completed"),
        harness_workload="sort-fixed",
        pinned_env={"MAKEFLAGS": "-j4"}),
    _profile(
        "inference-fixture.v1", "inference",
        "Local inference (fixture)",
        "Small deterministic matrix-vector pattern standing in for "
        "local model inference; no model is loaded or run.",
        [Operation("matvec", 4096), Operation("hash-chain", 8000)],
        seed=13, memory_cap_mb=512, threads=2,
        metrics=("wall_time_s", "checksum", "ops_completed"),
        harness_workload="hash-chain"),
    _profile(
        "graphics-fixture.v1", "graphics",
        "Graphics (fixture)",
        "In-memory pixel-buffer mixing standing in for a graphics "
        "frame workload; no GPU, display or driver is touched.",
        [Operation("pixel-mix", 16384), Operation("buffer-copy", 8192)],
        seed=14, memory_cap_mb=128, threads=1,
        metrics=("wall_time_s", "checksum", "bytes_touched"),
        harness_workload="sort-fixed"),
    _profile(
        "io-fixture.v1", "io",
        "I/O (fixture)",
        "In-memory buffer copy and checksum pattern standing in "
        "for storage I/O; nothing is written to any disk.",
        [Operation("buffer-copy", 32768), Operation("hash-chain", 8000)],
        seed=15, memory_cap_mb=64, threads=1,
        metrics=("wall_time_s", "checksum", "bytes_touched"),
        harness_workload="hash-chain"),
)
PROFILES = {p.profile_id: p for p in BUILTIN_PROFILES}
PROFILE_IDS = tuple(sorted(PROFILES))


def get_profile(profile_id):
    profile = PROFILES.get(profile_id)
    if profile is None:
        raise MalformedProfileError(
            "unknown built-in profile: " + repr(profile_id))
    return profile


def validate_catalog(profiles):
    """Validate a profile sequence: unique ids, all well-formed."""
    seen = set()
    for profile in profiles:
        if not isinstance(profile, WorkloadProfile):
            raise MalformedProfileError(
                "catalog entries must be WorkloadProfile values")
        if profile.profile_id in seen:
            raise DuplicateProfileError(
                "duplicate profile id: " + profile.profile_id)
        seen.add(profile.profile_id)
    return tuple(profiles)


def missing_categories(profiles):
    present = {p.category for p in profiles}
    return tuple(c for c in CATEGORIES if c not in present)


def catalog_as_dict(profiles):
    ordered = sorted(validate_catalog(profiles),
                     key=lambda p: p.profile_id)
    return {
        "schema": CATALOG_SCHEMA,
        "profiles": [profile_as_dict(p) for p in ordered],
    }


def catalog_from_dict(data):
    if not isinstance(data, dict):
        raise MalformedProfileError("catalog must be a dict")
    extra = set(data) - {"schema", "profiles"}
    if extra:
        raise MalformedProfileError(
            "unknown catalog fields: " + ", ".join(sorted(extra)))
    if data.get("schema") != CATALOG_SCHEMA:
        raise MalformedProfileError("catalog schema mismatch")
    if not isinstance(data.get("profiles"), list):
        raise MalformedProfileError("catalog profiles must be a list")
    profiles = [profile_from_dict(p) for p in data["profiles"]]
    return validate_catalog(profiles)


def load_catalog(path):
    """Load and validate a catalog fixture file (JSON)."""
    text = Path(path).read_text(encoding="utf-8")
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise MalformedProfileError("catalog is not valid JSON") from exc
    return catalog_from_dict(data)


def render_markdown(profiles):
    """Render a catalog deterministically (byte-stable output)."""
    ordered = sorted(validate_catalog(profiles),
                     key=lambda p: p.profile_id)
    lines = [
        "# Workload profile catalog",
        "",
        "- schema: " + CATALOG_SCHEMA,
        "- profiles: %d" % len(ordered),
        "- categories covered: %d of %d"
        % (len(CATEGORIES) - len(missing_categories(ordered)),
           len(CATEGORIES)),
        "",
    ]
    for p in ordered:
        ops = ", ".join("%s:%d" % (op.kind, op.size)
                        for op in p.operations)
        lines += [
            "## " + p.profile_id,
            "",
            "- category: " + p.category,
            "- title: " + p.title,
            "- safety class: " + p.safety_class,
            "- harness workload: " + p.harness_workload,
            "- seed: %d" % p.seed,
            "- repetitions: %d (warmup %d)" % (p.repetitions, p.warmup),
            "- memory cap (declared, MB): %d" % p.memory_cap_mb,
            "- threads (declared): %d" % p.threads,
            "- operations: " + ops,
            "- metrics: " + ", ".join(p.metrics),
            "- fingerprint: " + p.fingerprint(),
            "",
        ]
    lines.append(
        "Fixture-level definitions only; no live workload is claimed "
        "by this catalog.")
    lines.append("")
    return "\n".join(lines)
