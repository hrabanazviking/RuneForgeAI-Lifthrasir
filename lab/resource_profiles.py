# SPDX-License-Identifier: GPL-2.0-only
"""LIF-1103: ARM64 SBC and high-memory APU resource profiles.

Phase P11 (distro matrix: second distro, second architecture),
building on banked work only:

- LIF-0901 (lab/kernel_fixtures.py): version-pinned kernel build
  fixtures exist for exactly two architectures, x86_64 and arm64
  (fixture ids linux-6.12.117-x86_64 / linux-6.12.117-arm64). A
  resource profile names the kernel fixture for its architecture;
  an unknown fixture id is refused, never invented.
- LIF-1002 (lab/workload_profiles.py): the five workload families
  are declarative profiles with declared memory caps and thread
  counts. A resource profile declares which workload profiles it
  can host, and the fit rule is checked against the workload's own
  declared envelope (memory cap, threads) -- data against data.
- LIF-0603 (src/lifthrasir/quotas.py): the OS-level quota ceiling
  for one guarded workload is MAX_MEMORY_BYTES = 8 GiB. A resource
  profile's agent memory budget may not exceed that ceiling: a
  profile that promises an agent more than the banked quota layer
  can enforce is refused, never trimmed.
- LIF-0203 (lab/proc_sensors.py): the observer reads /proc/stat,
  /proc/meminfo, PSI and cgroup v2. A resource profile declares
  which of those sensor sources its class is expected to expose;
  an unknown source is refused.

A resource profile is a DECLARATIVE, fixture/record-level
definition of a device CLASS: architecture, CPU cores, total
memory, the memory budget available to Lifthrasir workloads, a
thermal class, the sensor sources, the pinned kernel fixture, the
hostable workload profiles, and an evidence basis. Validation is
fail-closed in the LIF-1002 style: unknown class, architecture /
class mismatch, budget above the device total or above the
LIF-0603 ceiling, unknown kernel fixture, unknown sensor source,
or a workload the envelope cannot host is refused by name.

Evidence honesty (master roadmap sections 0 and 5): every built-in
profile carries basis DECLARED_TARGET -- these are representative
class definitions written as targets for the P11 matrix, NOT
measurements of probed hardware. This module probes nothing: it
opens no /proc or /sys path, runs no command, and claims no live
hardware property. A future slice that records a real device must
add a new basis value with its recorded evidence attached; this
slice does not pre-claim it. Experiments on any real device of
these classes belong in disposable VMs or sacrificial hardware
(section 0 invariant 5); a profile is data, and loading one
changes no system state.

Determinism: a profile has a canonical dict form and a SHA-256
fingerprint over it; render_markdown renders a catalog
byte-stably (sorted, fixed field order, no timestamps, no host
values). Offline guarantee: standard library only, no network, no
subprocess, no disk writes; tests scan the import surface.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from pathlib import Path

PROFILE_SCHEMA = "lifthrasir.resource-profile.v0.1"
CATALOG_SCHEMA = "lifthrasir.resource-catalog.v0.1"

DEVICE_CLASSES = ("arm64-sbc", "high-memory-apu")
CLASS_ARCH = {"arm64-sbc": "arm64", "high-memory-apu": "x86_64"}
ARCHES = ("arm64", "x86_64")
# Banked LIF-0901 fixture ids, per architecture (the only kernel
# fixtures the repo pins; anything else is refused by name).
KERNEL_FIXTURES = {
    "arm64": "linux-6.12.117-arm64",
    "x86_64": "linux-6.12.117-x86_64",
}
# Banked LIF-1002 built-in workload profile ids (the only workload
# profiles a resource profile may claim to host).
WORKLOAD_PROFILE_IDS = (
    "compile-fixture.v1", "graphics-fixture.v1",
    "inference-fixture.v1", "io-fixture.v1", "mem-pressure-fixture.v1",
)
# LIF-0203 sensor source names.
SENSOR_SOURCES = ("cgroup-v2", "proc-meminfo", "proc-stat", "psi")
THERMAL_CLASSES = ("active", "passive", "unknown")
# Evidence basis values. Only declared-target exists in this slice:
# no profile here rests on probed hardware (see module docstring).
BASES = ("declared-target",)
# LIF-0603 ceiling, mirrored: MAX_MEMORY_BYTES = 8 GiB in
# src/lifthrasir/quotas.py. The tests assert this mirror equals the
# banked constant, so drift fails the suite instead of shipping.
QUOTA_CEILING_MB = 8192
MIN_CORES = 1
MAX_CORES = 256
MIN_MEMORY_MB = 256
MAX_MEMORY_MB = 1048576
MIN_BUDGET_MB = 64
_ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]*$")


class ResourceProfileError(Exception):
    """Base class for all resource profile refusals."""


class MalformedProfileError(ResourceProfileError):
    """The profile or catalog data is malformed."""


class UnknownClassError(ResourceProfileError):
    """The device class is not one of the two P11 classes."""


class UnsafeProfileError(ResourceProfileError):
    """The profile asks for something outside the proven bounds."""


class DuplicateProfileError(ResourceProfileError):
    """A catalog carries the same profile id twice."""


def _check_int(name, value, low, high):
    if isinstance(value, bool) or not isinstance(value, int):
        raise MalformedProfileError(name + " must be an int")
    if not low <= value <= high:
        raise MalformedProfileError(
            "%s must be in [%d, %d]" % (name, low, high))
    return value


def _check_str_tuple(name, values, allowed):
    if not isinstance(values, (list, tuple)) or not values:
        raise MalformedProfileError(name + " must be non-empty")
    out = tuple(values)
    for value in out:
        if value not in allowed:
            raise MalformedProfileError(
                "unknown %s entry: %s" % (name, repr(value)))
    if len(set(out)) != len(out):
        raise MalformedProfileError(name + " entries must be unique")
    return tuple(sorted(out))


@dataclass(frozen=True)
class ResourceProfile:
    """A declarative resource profile for one device class."""

    profile_id: str
    device_class: str
    title: str
    architecture: str
    cpu_cores: int
    memory_total_mb: int
    memory_budget_mb: int
    kernel_fixture_id: str
    sensor_sources: tuple
    workload_profile_ids: tuple
    thermal_class: str = "unknown"
    basis: str = "declared-target"
    description: str = ""

    def __post_init__(self):
        if (not isinstance(self.profile_id, str)
                or not _ID_RE.match(self.profile_id)
                or not any(c.isdigit() for c in self.profile_id)):
            raise MalformedProfileError(
                "profile_id must match [a-z0-9][a-z0-9._-]* and "
                "contain a digit: " + repr(self.profile_id))
        if self.device_class not in DEVICE_CLASSES:
            raise UnknownClassError(
                "unknown device class: " + repr(self.device_class))
        if not isinstance(self.title, str) or not self.title:
            raise MalformedProfileError("title must be non-empty")
        if not isinstance(self.description, str):
            raise MalformedProfileError("description must be a string")
        if self.architecture not in ARCHES:
            raise MalformedProfileError(
                "unknown architecture: " + repr(self.architecture))
        expected_arch = CLASS_ARCH[self.device_class]
        if self.architecture != expected_arch:
            raise UnsafeProfileError(
                "device class %s requires architecture %s, not %s"
                % (self.device_class, expected_arch, self.architecture))
        _check_int("cpu_cores", self.cpu_cores, MIN_CORES, MAX_CORES)
        _check_int("memory_total_mb", self.memory_total_mb,
                   MIN_MEMORY_MB, MAX_MEMORY_MB)
        _check_int("memory_budget_mb", self.memory_budget_mb,
                   MIN_BUDGET_MB, MAX_MEMORY_MB)
        if self.memory_budget_mb > self.memory_total_mb:
            raise UnsafeProfileError(
                "memory budget %d MB exceeds device total %d MB"
                % (self.memory_budget_mb, self.memory_total_mb))
        if self.memory_budget_mb > QUOTA_CEILING_MB:
            raise UnsafeProfileError(
                "memory budget %d MB exceeds the LIF-0603 quota "
                "ceiling %d MB" % (self.memory_budget_mb,
                                   QUOTA_CEILING_MB))
        expected_fixture = KERNEL_FIXTURES[self.architecture]
        if self.kernel_fixture_id != expected_fixture:
            raise UnsafeProfileError(
                "kernel fixture %s is not the banked LIF-0901 "
                "fixture for %s (%s)" % (repr(self.kernel_fixture_id),
                                         self.architecture,
                                         expected_fixture))
        object.__setattr__(self, "sensor_sources", _check_str_tuple(
            "sensor_sources", self.sensor_sources, SENSOR_SOURCES))
        object.__setattr__(self, "workload_profile_ids",
                           _check_str_tuple("workload_profile_ids",
                                            self.workload_profile_ids,
                                            WORKLOAD_PROFILE_IDS))
        if self.thermal_class not in THERMAL_CLASSES:
            raise MalformedProfileError(
                "unknown thermal_class: " + repr(self.thermal_class))
        if self.basis not in BASES:
            raise MalformedProfileError(
                "unknown basis: " + repr(self.basis)
                + " (this slice proves no probed-hardware basis)")

    def fingerprint(self):
        """SHA-256 over the canonical dict form of this profile."""
        blob = json.dumps(profile_as_dict(self), sort_keys=True,
                          separators=(",", ":")).encode("utf-8")
        return hashlib.sha256(blob).hexdigest()


_PROFILE_FIELDS = {"schema", "profile_id", "device_class", "title",
                   "description", "architecture", "cpu_cores",
                   "memory_total_mb", "memory_budget_mb",
                   "kernel_fixture_id", "sensor_sources",
                   "workload_profile_ids", "thermal_class", "basis"}


def profile_as_dict(profile):
    return {
        "schema": PROFILE_SCHEMA,
        "profile_id": profile.profile_id,
        "device_class": profile.device_class,
        "title": profile.title,
        "description": profile.description,
        "architecture": profile.architecture,
        "cpu_cores": profile.cpu_cores,
        "memory_total_mb": profile.memory_total_mb,
        "memory_budget_mb": profile.memory_budget_mb,
        "kernel_fixture_id": profile.kernel_fixture_id,
        "sensor_sources": list(profile.sensor_sources),
        "workload_profile_ids": list(profile.workload_profile_ids),
        "thermal_class": profile.thermal_class,
        "basis": profile.basis,
    }


def profile_from_dict(data):
    """Build a ResourceProfile from its strict dict form."""
    if not isinstance(data, dict):
        raise MalformedProfileError("profile must be a dict")
    extra = set(data) - _PROFILE_FIELDS
    if extra:
        raise MalformedProfileError(
            "unknown profile fields: " + ", ".join(sorted(extra)))
    if data.get("schema", PROFILE_SCHEMA) != PROFILE_SCHEMA:
        raise MalformedProfileError("profile schema mismatch")
    for name in ("profile_id", "device_class", "title", "architecture",
                 "cpu_cores", "memory_total_mb", "memory_budget_mb",
                 "kernel_fixture_id", "sensor_sources",
                 "workload_profile_ids"):
        if name not in data:
            raise MalformedProfileError(name + " is required")
    return ResourceProfile(
        profile_id=data["profile_id"],
        device_class=data["device_class"],
        title=data["title"],
        architecture=data["architecture"],
        cpu_cores=data["cpu_cores"],
        memory_total_mb=data["memory_total_mb"],
        memory_budget_mb=data["memory_budget_mb"],
        kernel_fixture_id=data["kernel_fixture_id"],
        sensor_sources=tuple(data["sensor_sources"]),
        workload_profile_ids=tuple(data["workload_profile_ids"]),
        thermal_class=data.get("thermal_class", "unknown"),
        basis=data.get("basis", "declared-target"),
        description=data.get("description", ""),
    )


def fits_workload(profile, memory_cap_mb, threads):
    """Fit rule: a workload's declared envelope fits the profile.

    Data against data: the workload's declared memory cap must fit
    the profile's agent memory budget, and its declared thread
    count must fit the profile's core count. This judges declared
    envelopes only; it runs nothing and measures nothing.
    """
    _check_int("workload memory_cap_mb", memory_cap_mb, 1, MAX_MEMORY_MB)
    _check_int("workload threads", threads, 1, MAX_CORES)
    return (memory_cap_mb <= profile.memory_budget_mb
            and threads <= profile.cpu_cores)


def unhostable(profile, workload_envelopes):
    """Names of claimed workloads whose envelopes do NOT fit.

    workload_envelopes maps workload profile id -> (memory_cap_mb,
    threads) as declared by that workload profile (LIF-1002). A
    claimed id missing from the map is reported unhostable: an
    unverifiable claim never passes silently.
    """
    bad = []
    for wid in profile.workload_profile_ids:
        envelope = workload_envelopes.get(wid)
        if envelope is None or not fits_workload(profile, *envelope):
            bad.append(wid)
    return tuple(bad)


def _profile(profile_id, device_class, title, description, **kw):
    arch = CLASS_ARCH[device_class]
    return ResourceProfile(
        profile_id=profile_id, device_class=device_class, title=title,
        description=description, architecture=arch,
        kernel_fixture_id=KERNEL_FIXTURES[arch], **kw)


_ALL_WORKLOADS = WORKLOAD_PROFILE_IDS
_LIGHT_WORKLOADS = ("graphics-fixture.v1", "io-fixture.v1",
                    "mem-pressure-fixture.v1")

BUILTIN_PROFILES = (
    _profile(
        "arm64-sbc-4gb.v1", "arm64-sbc",
        "ARM64 single-board computer, 4 GB class",
        "Representative low-memory ARM64 SBC class target for the "
        "P11 matrix: light fixture workloads only, passive thermal "
        "class, agent budget a quarter of total memory. Declared "
        "target, not a probed device.",
        cpu_cores=4, memory_total_mb=4096, memory_budget_mb=1024,
        sensor_sources=SENSOR_SOURCES,
        workload_profile_ids=_LIGHT_WORKLOADS,
        thermal_class="passive"),
    _profile(
        "arm64-sbc-8gb.v1", "arm64-sbc",
        "ARM64 single-board computer, 8 GB class",
        "Representative upper ARM64 SBC class target: adds the "
        "compilation fixture to the light set; inference stays "
        "unclaimed at this budget. Declared target, not a probed "
        "device.",
        cpu_cores=8, memory_total_mb=8192, memory_budget_mb=2048,
        sensor_sources=SENSOR_SOURCES,
        workload_profile_ids=("compile-fixture.v1",) + _LIGHT_WORKLOADS,
        thermal_class="passive"),
    _profile(
        "highmem-apu-32gb.v1", "high-memory-apu",
        "High-memory APU, 32 GB class",
        "Representative unified-memory APU class target: hosts "
        "every LIF-1002 fixture workload within a 4 GB agent "
        "budget. Declared target, not a probed device.",
        cpu_cores=8, memory_total_mb=32768, memory_budget_mb=4096,
        sensor_sources=SENSOR_SOURCES,
        workload_profile_ids=_ALL_WORKLOADS,
        thermal_class="active"),
    _profile(
        "highmem-apu-128gb.v1", "high-memory-apu",
        "High-memory APU, 128 GB class",
        "Representative top unified-memory APU class target (the "
        "class the campaign host belongs to): agent budget at the "
        "full LIF-0603 quota ceiling. Declared target, not a "
        "probed device; no host memory figure is claimed.",
        cpu_cores=16, memory_total_mb=131072, memory_budget_mb=8192,
        sensor_sources=SENSOR_SOURCES,
        workload_profile_ids=_ALL_WORKLOADS,
        thermal_class="active"),
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
        if not isinstance(profile, ResourceProfile):
            raise MalformedProfileError(
                "catalog entries must be ResourceProfile values")
        if profile.profile_id in seen:
            raise DuplicateProfileError(
                "duplicate profile id: " + profile.profile_id)
        seen.add(profile.profile_id)
    return tuple(profiles)


def missing_classes(profiles):
    present = {p.device_class for p in profiles}
    return tuple(c for c in DEVICE_CLASSES if c not in present)


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
        "# Resource profile catalog",
        "",
        "- schema: " + CATALOG_SCHEMA,
        "- profiles: %d" % len(ordered),
        "- device classes covered: %d of %d"
        % (len(DEVICE_CLASSES) - len(missing_classes(ordered)),
           len(DEVICE_CLASSES)),
        "",
    ]
    for p in ordered:
        lines += [
            "## " + p.profile_id,
            "",
            "- device class: " + p.device_class,
            "- title: " + p.title,
            "- architecture: " + p.architecture,
            "- cpu cores (declared): %d" % p.cpu_cores,
            "- memory total (declared, MB): %d" % p.memory_total_mb,
            "- memory budget (declared, MB): %d" % p.memory_budget_mb,
            "- thermal class: " + p.thermal_class,
            "- kernel fixture: " + p.kernel_fixture_id,
            "- sensor sources: " + ", ".join(p.sensor_sources),
            "- workload profiles: " + ", ".join(p.workload_profile_ids),
            "- basis: " + p.basis,
            "- fingerprint: " + p.fingerprint(),
            "",
        ]
    lines.append(
        "Declared class-level targets only; no probed hardware is "
        "claimed by this catalog.")
    lines.append("")
    return "\n".join(lines)
