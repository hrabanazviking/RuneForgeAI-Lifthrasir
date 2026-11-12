"""Install/upgrade/uninstall/recovery acceptance suite (LIF-1203).

SPDX-License-Identifier: GPL-2.0-only

Home justification: master roadmap section 3 places core
implementation in ``src/``; roadmap/08 (test matrix + release
gates) names the Release layer "clean install, upgrade, rollback,
uninstall and emergency-stop tests" and gate G9 "Cross-distro
package install and uninstall validated"; Book V's release lane
requires "clean install/upgrade/uninstall, package signatures,
recovery smoke test". This suite is that release-lane acceptance
harness for Phase P12, beside the transaction store (LIF-0405)
and the reversal runner (LIF-0505) whose semantics it composes.

WHAT THIS SUITE ACTUALLY EXERCISES (evidence-status honesty,
master roadmap sections 0 and 5 -- read this before citing it):

- Every target is a FIXTURE target: an in-memory ``FixtureSystem``
  standing in for an installed system inside a disposable lab
  guest. NO package is installed, upgraded, uninstalled or
  recovered on the real host (purpleraider) or on any real
  machine: the engine's only effects are state transitions inside
  plain fixture data, plus -- for exactly one case -- the banked
  LIF-0505 journal file inside a caller-supplied temporary
  directory. A target that is not disposable, or not in the
  disposable-lab environment, is refused BY NAME before anything
  happens (``HostTargetError``); host identifiers are refused
  even if they claim to be disposable.
- Packages are version-pinned fixtures whose canonical manifest
  carries a SHA-256 checksum, verified before any mutation: an
  unpinned package is refused (``UnpinnedPackageError``) and a
  tampered one is refused (``ChecksumMismatchError``), in the
  LIF-0101/LIF-0901 pinning style.
- The lifecycle semantics under test are the project's own:
  install records a before-image undo manifest for every step
  (the LIF-0405 durable-transaction shape); an interrupted
  install or upgrade is recovered from that manifest alone and
  the restored digest must equal the recorded original or the
  recovery is a named divergence, never a claim on faith (the
  LIF-0505 rule). One case composes the banked reversal runner
  and its on-disk journal directly, so the acceptance suite also
  proves the journaled path end to end at fixture level.
- Each case carries a HAND-WRITTEN oracle: the expected final
  snapshot is literal data written in the case definition, not
  derived from the engine's output. A case passes only when the
  observed snapshot equals the oracle snapshot exactly (digest
  equality included). Refusal cases pass only when the named
  refusal occurs and the fixture state is untouched.
- Honest scope: this proves the acceptance LOGIC and lifecycle
  semantics at fixture level on one machine. It does NOT prove
  real .deb/.rpm install/uninstall: real package generation and
  signing are LIF-1201 (building in parallel, deliberately not
  depended on), and the cross-distro matrix is contract-level
  (P11). The suite report says so in its own ``not_covered``
  list; gate G9 is therefore claimed only at fixture level.

Safety invariants bound here (master roadmap section 0): no
ambient root (nothing runs privileged, or anything external at
all -- this module imports no subprocess/socket/network
machinery, AST-pinned in tests); no mutation of bootloader,
kernel, firmware, partitions, encryption or trust roots (no
code path can name a real target); emergency stop is honoured
before any mutation (``EmergencyStopError``); every operation
is bounded, journaled in its undo manifest, and reversible.
"""
from __future__ import annotations

import hashlib
import json
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from . import reversal as _reversal

ACCEPTANCE_SCHEMA = "lifthrasir.acceptance.v0.1"
ACCEPTANCE_SCHEMA_VERSION = "0.1"
LAB_ENVIRONMENT = "disposable-lab"
TARGET_KINDS = ("fixture-vm", "fixture-dir", "fixture-memory")
HOST_TARGET_IDS = frozenset(
    {"host", "real-host", "purpleraider", "localhost", "production"})
EVIDENCE_STATUS = "lab-verified (fixture level, one machine)"

# ---------------------------------------------------------------------
# Errors: every refusal is named; nothing fails silently.
# ---------------------------------------------------------------------


class AcceptanceError(Exception):
    """Base class for all named acceptance-suite refusals."""


class MalformedPackageError(AcceptanceError):
    """A package fixture is structurally invalid."""


class UnpinnedPackageError(AcceptanceError):
    """A package fixture carries no checksum pin; refused."""


class ChecksumMismatchError(AcceptanceError):
    """A package fixture's contents do not match its pin."""


class MalformedTargetError(AcceptanceError):
    """A target descriptor is structurally invalid."""


class HostTargetError(AcceptanceError):
    """The target is not a disposable lab fixture; refused by name."""


class VersionRefusedError(AcceptanceError):
    """The version transition is not permitted (downgrade/equal)."""


class NotInstalledError(AcceptanceError):
    """The operation needs an installed package; none is present."""


class AlreadyInstalledError(AcceptanceError):
    """Install was asked for the exact version already installed."""


class EmergencyStopError(AcceptanceError):
    """The emergency stop is engaged; refused before any mutation."""


class NoRecoveryError(AcceptanceError):
    """Recovery was asked for but no undo manifest is pending."""


class AcceptanceDivergenceError(AcceptanceError):
    """Recovered state does not match the recorded original."""


class UnknownCaseError(AcceptanceError):
    """An acceptance case id that does not exist was requested."""


class SimulatedInstallInterrupt(Exception):
    """Simulated crash/power-loss mid-operation (fixture only).

    Deliberately NOT an AcceptanceError, mirroring LIF-0505's
    SimulatedInterrupt: a real interruption is not a refusal, and
    the engine must not catch or soften it. The caller discards
    the operation and recovers from the undo manifest alone.
    """


# ---------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=True)


def _digest(value: Any) -> str:
    return "sha256:" + hashlib.sha256(
        _canonical(value).encode("utf-8")).hexdigest()


def parse_version(version: Any) -> Tuple[int, ...]:
    if not isinstance(version, str) or not version:
        raise MalformedPackageError(
            f"version must be a non-empty string, got {version!r}")
    parts = version.split(".")
    out: List[int] = []
    for part in parts:
        if not part.isdigit():
            raise MalformedPackageError(
                f"version {version!r} is not dotted-numeric")
        out.append(int(part))
    return tuple(out)


def compare_versions(a: str, b: str) -> int:
    """Return -1/0/1 as version a is below/equal/above version b."""
    ta, tb = parse_version(a), parse_version(b)
    width = max(len(ta), len(tb))
    ta = ta + (0,) * (width - len(ta))
    tb = tb + (0,) * (width - len(tb))
    if ta < tb:
        return -1
    if ta > tb:
        return 1
    return 0


# ---------------------------------------------------------------------
# Package fixtures: version-pinned, checksum-verified before use.
# ---------------------------------------------------------------------


def package_checksum(body: Dict[str, Any]) -> str:
    """SHA-256 over the canonical package body (no checksum field)."""
    return _digest(body)


@dataclass
class PackageFixture:
    name: str
    version: str
    files: Dict[str, str]
    config_defaults: Dict[str, str]
    services: List[str]
    user_data_keys: List[str]
    checksum: str

    def body(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "version": self.version,
            "files": dict(self.files),
            "config_defaults": dict(self.config_defaults),
            "services": list(self.services),
            "user_data_keys": list(self.user_data_keys),
        }

    def to_dict(self) -> Dict[str, Any]:
        data = self.body()
        data["checksum"] = self.checksum
        return data


def _check_package_path(path: Any) -> str:
    if not isinstance(path, str) or not path:
        raise MalformedPackageError(
            f"package file path must be a non-empty string: {path!r}")
    if path.startswith("/") or path.startswith("\\"):
        raise MalformedPackageError(
            f"package file path must be target-relative: {path!r}")
    if ".." in path.split("/"):
        raise MalformedPackageError(
            f"package file path must not traverse upwards: {path!r}")
    return path


def package_from_dict(data: Any) -> PackageFixture:
    if not isinstance(data, dict):
        raise MalformedPackageError("package fixture is not an object")
    name = data.get("name")
    if not isinstance(name, str) or not name:
        raise MalformedPackageError("package name is missing")
    version = data.get("version")
    parse_version(version)  # raises MalformedPackageError when bad
    files = data.get("files")
    if not isinstance(files, dict) or not files:
        raise MalformedPackageError("package files must be a non-empty object")
    for path, content in files.items():
        _check_package_path(path)
        if not isinstance(content, str):
            raise MalformedPackageError(
                f"package file content must be text: {path!r}")
    config = data.get("config_defaults", {})
    if not isinstance(config, dict):
        raise MalformedPackageError("config_defaults must be an object")
    services = data.get("services", [])
    if not isinstance(services, list) or not all(
            isinstance(s, str) and s for s in services):
        raise MalformedPackageError("services must be a list of names")
    data_keys = data.get("user_data_keys", [])
    if not isinstance(data_keys, list) or not all(
            isinstance(k, str) and k for k in data_keys):
        raise MalformedPackageError("user_data_keys must be a list of keys")
    checksum = data.get("checksum")
    if checksum is None:
        raise UnpinnedPackageError(
            f"package {name} {version} carries no checksum pin; "
            "unpinned packages are refused")
    body = {
        "name": name, "version": version, "files": dict(files),
        "config_defaults": dict(config), "services": list(services),
        "user_data_keys": list(data_keys),
    }
    expected = package_checksum(body)
    if checksum != expected:
        raise ChecksumMismatchError(
            f"package {name} {version} checksum mismatch: pinned "
            f"{checksum!r}, computed {expected!r}; contents were "
            "altered after pinning; refusing")
    return PackageFixture(name=name, version=version, files=dict(files),
                          config_defaults=dict(config),
                          services=list(services),
                          user_data_keys=list(data_keys),
                          checksum=checksum)


def make_package(name: str, version: str, files: Dict[str, str],
                 config_defaults: Optional[Dict[str, str]] = None,
                 services: Optional[List[str]] = None,
                 user_data_keys: Optional[List[str]] = None
                 ) -> PackageFixture:
    """Build a package fixture and pin it (test/fixture helper)."""
    body = {
        "name": name, "version": version, "files": dict(files),
        "config_defaults": dict(config_defaults or {}),
        "services": list(services or []),
        "user_data_keys": list(user_data_keys or []),
    }
    return package_from_dict({**body, "checksum": package_checksum(body)})


# The built-in demo package, two pinned versions. The v2 delta is
# deliberate acceptance material: one file changed, one file added,
# one file removed, one config default changed, one config key
# dropped, one config key added, one service added.
PACKAGE_V1 = make_package(
    "lifthrasir-demo", "1.0.0",
    files={
        "usr/share/lifthrasir/demo.txt": "demo v1\n",
        "usr/lib/lifthrasir/core.bin": "core-1",
        "usr/share/lifthrasir/legacy.txt": "legacy\n",
    },
    config_defaults={
        "demo.timeout": "30",
        "demo.mode": "safe",
        "demo.legacy": "on",
    },
    services=["lifthrasir-demo.service"],
    user_data_keys=["demo.user.notes"],
)

PACKAGE_V2 = make_package(
    "lifthrasir-demo", "1.1.0",
    files={
        "usr/share/lifthrasir/demo.txt": "demo v2\n",
        "usr/lib/lifthrasir/core.bin": "core-2",
        "usr/share/lifthrasir/new.txt": "new in v2\n",
    },
    config_defaults={
        "demo.timeout": "45",
        "demo.mode": "safe",
        "demo.new": "yes",
    },
    services=["lifthrasir-demo.service", "lifthrasir-helper.service"],
    user_data_keys=["demo.user.notes"],
)


def builtin_packages() -> Dict[str, PackageFixture]:
    return {"1.0.0": PACKAGE_V1, "1.1.0": PACKAGE_V2}


# ---------------------------------------------------------------------
# Fixture target + fixture system
# ---------------------------------------------------------------------


@dataclass
class FixtureTarget:
    target_id: str
    kind: str
    environment: str
    disposable: bool

    def to_dict(self) -> Dict[str, Any]:
        return {"target_id": self.target_id, "kind": self.kind,
                "environment": self.environment,
                "disposable": self.disposable}


def validate_target(data: Any) -> FixtureTarget:
    """Validate a target descriptor; refuse anything not a fixture.

    This is the suite's section-0 gate: install/upgrade/uninstall/
    recovery may only ever run against a disposable target in the
    disposable-lab environment. Host identifiers are refused even
    when the descriptor claims to be disposable.
    """
    if not isinstance(data, dict):
        raise MalformedTargetError("target descriptor is not an object")
    target_id = data.get("target_id")
    if not isinstance(target_id, str) or not target_id:
        raise MalformedTargetError("target_id is missing")
    if target_id in HOST_TARGET_IDS:
        raise HostTargetError(
            f"target {target_id!r} names a real host; acceptance "
            "operations run on fixture targets only; refused")
    kind = data.get("kind")
    if kind not in TARGET_KINDS:
        raise HostTargetError(
            f"target {target_id!r} kind {kind!r} is not a fixture "
            f"kind {TARGET_KINDS}; refused")
    if data.get("disposable") is not True:
        raise HostTargetError(
            f"target {target_id!r} is not marked disposable; "
            "acceptance operations require a disposable target; "
            "refused")
    if data.get("environment") != LAB_ENVIRONMENT:
        raise HostTargetError(
            f"target {target_id!r} environment "
            f"{data.get('environment')!r} is not {LAB_ENVIRONMENT!r}; "
            "refused")
    return FixtureTarget(target_id=target_id, kind=kind,
                         environment=LAB_ENVIRONMENT, disposable=True)


def fixture_target(target_id: str = "fixture-guest-01") -> Dict[str, Any]:
    return {"target_id": target_id, "kind": "fixture-vm",
            "environment": LAB_ENVIRONMENT, "disposable": True}


class FixtureSystem:
    """In-memory stand-in for an installed system (fixture only).

    ``files``/``config``/``services`` are what a package manages;
    ``user_data`` is data the user created while the package was
    installed (uninstall preserves it only on explicit request,
    per the master roadmap's uninstall-cleanliness target).
    ``pending_manifest`` is the durable undo record of an
    interrupted operation; recovery consumes exactly it.
    """

    def __init__(self) -> None:
        self.files: Dict[str, str] = {}
        self.config: Dict[str, str] = {}
        self.services: Dict[str, str] = {}
        self.user_data: Dict[str, str] = {}
        self.installed: Optional[Dict[str, str]] = None
        self.pending_manifest: Optional[Dict[str, Any]] = None

    def snapshot(self) -> Dict[str, Any]:
        return {
            "installed": (dict(self.installed)
                          if self.installed is not None else None),
            "files": dict(self.files),
            "config": dict(self.config),
            "services": dict(self.services),
            "user_data": dict(self.user_data),
        }

    def digest(self) -> str:
        return _digest(self.snapshot())


EMPTY_DIGEST = FixtureSystem().digest()


# ---------------------------------------------------------------------
# Lifecycle engine: every mutation is a journaled, reversible step.
# A step target is "<area>:<key>" with area in file/config/service/
# data/meta. Before-images are captured per step, write-ahead style
# (LIF-0505), so an interruption at any point is recoverable.
# ---------------------------------------------------------------------

_DELETE = object()


def _read_area(system: FixtureSystem, area: str, key: str) -> Any:
    if area == "file":
        return system.files.get(key, _DELETE)
    if area == "config":
        return system.config.get(key, _DELETE)
    if area == "service":
        return system.services.get(key, _DELETE)
    if area == "data":
        return system.user_data.get(key, _DELETE)
    if area == "meta" and key == "installed":
        return (dict(system.installed)
                if system.installed is not None else _DELETE)
    raise AcceptanceError(f"unknown step area/key: {area}:{key}")


def _write_area(system: FixtureSystem, area: str, key: str,
                value: Any) -> None:
    store = {"file": system.files, "config": system.config,
             "service": system.services,
             "data": system.user_data}.get(area)
    if area == "meta" and key == "installed":
        system.installed = (None if value is _DELETE else dict(value))
        return
    if store is None:
        raise AcceptanceError(f"unknown step area: {area}")
    if value is _DELETE:
        store.pop(key, None)
    else:
        store[key] = value


def _image(value: Any) -> Dict[str, Any]:
    if value is _DELETE:
        return {"present": False, "value": None}
    return {"present": True, "value": value}


def _unimage(image: Dict[str, Any]) -> Any:
    return image["value"] if image["present"] else _DELETE


def _run_steps(system: FixtureSystem, op: str,
               steps: List[Dict[str, Any]], *,
               interrupt_after: Optional[int] = None
               ) -> Dict[str, Any]:
    """Apply steps under an undo manifest; maybe simulate a crash.

    The manifest is stored on the system BEFORE the first step is
    applied and updated per step, so discarding this call (the
    simulated crash) still leaves a complete recovery record.
    """
    manifest: Dict[str, Any] = {
        "op": op,
        "original_digest": system.digest(),
        "steps": [],
    }
    system.pending_manifest = manifest
    if interrupt_after is not None and interrupt_after <= 0:
        raise SimulatedInstallInterrupt(
            f"simulated interruption during {op} before the first step")
    applied = 0
    for step in steps:
        area, key = step["area"], step["key"]
        entry = {"area": area, "key": key,
                 "before": _image(_read_area(system, area, key)),
                 "after": _image(step["value"]), "applied": False}
        manifest["steps"].append(entry)
        _write_area(system, area, key, step["value"])
        entry["applied"] = True
        applied += 1
        if interrupt_after is not None and applied >= interrupt_after:
            raise SimulatedInstallInterrupt(
                f"simulated interruption during {op} after "
                f"{applied} applied step(s)")
    system.pending_manifest = None
    manifest["completed"] = True
    return manifest


def _check_gate(target: Any, stop: bool) -> FixtureTarget:
    checked = validate_target(target)
    if stop:
        raise EmergencyStopError(
            "emergency stop is engaged; acceptance operation "
            "refused before any mutation (model-independent, "
            "master roadmap section 0 invariant 8)")
    return checked


def _require_installed(system: FixtureSystem,
                       package: PackageFixture) -> None:
    if system.installed is None:
        raise NotInstalledError(
            f"package {package.name!r} is not installed on this "
            "fixture system; nothing to operate on")
    if system.installed.get("name") != package.name:
        raise NotInstalledError(
            f"installed package is {system.installed.get('name')!r}, "
            f"not {package.name!r}")


def install(system: FixtureSystem, target: Any, package: PackageFixture,
            *, emergency_stop: bool = False,
            interrupt_after: Optional[int] = None) -> Dict[str, Any]:
    """Install a pinned package fixture onto a fixture system."""
    _check_gate(target, emergency_stop)
    package_from_dict(package.to_dict())  # re-verify the pin, always
    if system.pending_manifest is not None:
        raise AcceptanceError(
            "an interrupted operation is pending recovery; recover "
            "before installing")
    if system.installed is not None:
        if system.installed.get("version") == package.version:
            raise AlreadyInstalledError(
                f"{package.name} {package.version} is already "
                "installed; reinstall is a no-op refusal")
        raise AlreadyInstalledError(
            f"{package.name} {system.installed.get('version')} is "
            "installed; use upgrade, not install")
    steps: List[Dict[str, Any]] = []
    for path in sorted(package.files):
        steps.append({"area": "file", "key": path,
                      "value": package.files[path]})
    for key in sorted(package.config_defaults):
        if key not in system.config:
            steps.append({"area": "config", "key": key,
                          "value": package.config_defaults[key]})
    for name in sorted(package.services):
        steps.append({"area": "service", "key": name,
                      "value": "active"})
    steps.append({"area": "meta", "key": "installed",
                  "value": {"name": package.name,
                            "version": package.version}})
    manifest = _run_steps(system, "install", steps,
                          interrupt_after=interrupt_after)
    return {"op": "install", "package": package.name,
            "version": package.version, "steps_applied": len(steps),
            "digest": system.digest(), "manifest": manifest}


def upgrade(system: FixtureSystem, target: Any,
            old_package: PackageFixture, new_package: PackageFixture,
            *, allow_downgrade: bool = False,
            emergency_stop: bool = False,
            interrupt_after: Optional[int] = None) -> Dict[str, Any]:
    """Upgrade (or, only when explicitly allowed, downgrade).

    Config rule (Book V operational proof): a key still at its old
    default takes the new default; a user-modified key is
    preserved; a key dropped by the new version is removed only
    when untouched (still at its old default).
    """
    _check_gate(target, emergency_stop)
    package_from_dict(old_package.to_dict())
    package_from_dict(new_package.to_dict())
    _require_installed(system, old_package)
    if system.pending_manifest is not None:
        raise AcceptanceError(
            "an interrupted operation is pending recovery; recover "
            "before upgrading")
    installed_version = system.installed["version"]  # type: ignore
    if installed_version != old_package.version:
        raise VersionRefusedError(
            f"installed version is {installed_version}, not the "
            f"declared from-version {old_package.version}")
    order = compare_versions(new_package.version, old_package.version)
    if order == 0:
        raise VersionRefusedError(
            f"upgrade to the same version {new_package.version} "
            "is not an upgrade")
    if order < 0 and not allow_downgrade:
        raise VersionRefusedError(
            f"downgrade {old_package.version} -> "
            f"{new_package.version} refused; downgrades require "
            "explicit allow_downgrade")
    steps: List[Dict[str, Any]] = []
    for path in sorted(old_package.files):
        if path not in new_package.files:
            steps.append({"area": "file", "key": path,
                          "value": _DELETE})
    for path in sorted(new_package.files):
        if system.files.get(path) != new_package.files[path]:
            steps.append({"area": "file", "key": path,
                          "value": new_package.files[path]})
    for key in sorted(old_package.config_defaults):
        if key not in new_package.config_defaults:
            if system.config.get(key) == old_package.config_defaults[key]:
                steps.append({"area": "config", "key": key,
                              "value": _DELETE})
    for key in sorted(new_package.config_defaults):
        current = system.config.get(key)
        if current is None:
            steps.append({"area": "config", "key": key,
                          "value": new_package.config_defaults[key]})
        elif (key in old_package.config_defaults
              and current == old_package.config_defaults[key]
              and current != new_package.config_defaults[key]):
            steps.append({"area": "config", "key": key,
                          "value": new_package.config_defaults[key]})
    for name in sorted(old_package.services):
        if name not in new_package.services:
            steps.append({"area": "service", "key": name,
                          "value": _DELETE})
    for name in sorted(new_package.services):
        if system.services.get(name) != "active":
            steps.append({"area": "service", "key": name,
                          "value": "active"})
    steps.append({"area": "meta", "key": "installed",
                  "value": {"name": new_package.name,
                            "version": new_package.version}})
    manifest = _run_steps(system, "upgrade", steps,
                          interrupt_after=interrupt_after)
    return {"op": "upgrade", "package": new_package.name,
            "from_version": old_package.version,
            "version": new_package.version,
            "steps_applied": len(steps), "digest": system.digest(),
            "manifest": manifest}


def uninstall(system: FixtureSystem, target: Any,
              package: PackageFixture, *,
              keep_user_data: bool = False,
              emergency_stop: bool = False,
              interrupt_after: Optional[int] = None) -> Dict[str, Any]:
    """Remove a package; user data only by explicit choice."""
    _check_gate(target, emergency_stop)
    package_from_dict(package.to_dict())
    _require_installed(system, package)
    if system.pending_manifest is not None:
        raise AcceptanceError(
            "an interrupted operation is pending recovery; recover "
            "before uninstalling")
    steps: List[Dict[str, Any]] = []
    for path in sorted(package.files):
        if path in system.files:
            steps.append({"area": "file", "key": path,
                          "value": _DELETE})
    for key in sorted(package.config_defaults):
        if key in system.config:
            steps.append({"area": "config", "key": key,
                          "value": _DELETE})
    for name in sorted(package.services):
        if name in system.services:
            steps.append({"area": "service", "key": name,
                          "value": _DELETE})
    if not keep_user_data:
        for key in sorted(package.user_data_keys):
            if key in system.user_data:
                steps.append({"area": "data", "key": key,
                              "value": _DELETE})
    steps.append({"area": "meta", "key": "installed",
                  "value": _DELETE})
    manifest = _run_steps(system, "uninstall", steps,
                          interrupt_after=interrupt_after)
    return {"op": "uninstall", "package": package.name,
            "version": package.version,
            "kept_user_data": keep_user_data,
            "steps_applied": len(steps), "digest": system.digest(),
            "manifest": manifest}


def recover(system: FixtureSystem) -> Dict[str, Any]:
    """Recover an interrupted operation from its undo manifest.

    Model-independent (section 0 invariant 8): the manifest alone
    decides. The restored digest must equal the recorded original
    or a named divergence is raised -- never a claim on faith.
    """
    manifest = system.pending_manifest
    if manifest is None:
        raise NoRecoveryError(
            "no interrupted operation is pending; nothing to "
            "recover and no recovery will be invented")
    reversed_steps: List[str] = []
    for entry in reversed(manifest["steps"]):
        if not entry["applied"]:
            continue
        _write_area(system, entry["area"], entry["key"],
                    _unimage(entry["before"]))
        reversed_steps.append(f"{entry['area']}:{entry['key']}")
    restored = system.digest()
    if restored != manifest["original_digest"]:
        raise AcceptanceDivergenceError(
            f"recovery of {manifest['op']} did not restore the "
            f"original state: expected {manifest['original_digest']}, "
            f"got {restored}")
    system.pending_manifest = None
    return {"op": "recover", "recovered_from": manifest["op"],
            "reversed_steps": reversed_steps,
            "restored_digest": restored, "verified": True}


def verify_install(system: FixtureSystem,
                   package: PackageFixture) -> List[str]:
    """Return mismatches between the fixture system and a package.

    An empty list means the installed state matches the package
    exactly: version, every file's content, every config key's
    presence, every service active. User-modified config VALUES
    are reported as mismatches too -- verification is strict, and
    the acceptance cases use untouched systems for verify-clean.
    """
    mismatches: List[str] = []
    if system.installed is None:
        return [f"package {package.name} is not installed"]
    if system.installed.get("version") != package.version:
        mismatches.append(
            f"installed version {system.installed.get('version')} "
            f"!= package version {package.version}")
    for path in sorted(package.files):
        if system.files.get(path) != package.files[path]:
            mismatches.append(f"file mismatch: {path}")
    for key in sorted(package.config_defaults):
        if key not in system.config:
            mismatches.append(f"config key missing: {key}")
    for name in sorted(package.services):
        if system.services.get(name) != "active":
            mismatches.append(f"service not active: {name}")
    return mismatches


# ---------------------------------------------------------------------
# Acceptance cases. Each oracle below is HAND-WRITTEN literal data:
# the expected snapshot is spelled out in the case, never derived
# from engine output. A case passes only on exact equality.
# ---------------------------------------------------------------------

V1_SNAPSHOT: Dict[str, Any] = {
    "installed": {"name": "lifthrasir-demo", "version": "1.0.0"},
    "files": {
        "usr/share/lifthrasir/demo.txt": "demo v1\n",
        "usr/lib/lifthrasir/core.bin": "core-1",
        "usr/share/lifthrasir/legacy.txt": "legacy\n",
    },
    "config": {"demo.timeout": "30", "demo.mode": "safe",
               "demo.legacy": "on"},
    "services": {"lifthrasir-demo.service": "active"},
    "user_data": {},
}

V2_SNAPSHOT: Dict[str, Any] = {
    "installed": {"name": "lifthrasir-demo", "version": "1.1.0"},
    "files": {
        "usr/share/lifthrasir/demo.txt": "demo v2\n",
        "usr/lib/lifthrasir/core.bin": "core-2",
        "usr/share/lifthrasir/new.txt": "new in v2\n",
    },
    "config": {"demo.timeout": "45", "demo.mode": "safe",
               "demo.new": "yes"},
    "services": {"lifthrasir-demo.service": "active",
                 "lifthrasir-helper.service": "active"},
    "user_data": {},
}

EMPTY_SNAPSHOT: Dict[str, Any] = {
    "installed": None, "files": {}, "config": {}, "services": {},
    "user_data": {},
}


@dataclass
class CaseResult:
    case_id: str
    title: str
    gates: List[str]
    status: str  # "passed" | "failed"
    expected_digest: str
    observed_digest: str
    detail: str

    def to_dict(self) -> Dict[str, Any]:
        return {"case_id": self.case_id, "title": self.title,
                "gates": list(self.gates), "status": self.status,
                "expected_digest": self.expected_digest,
                "observed_digest": self.observed_digest,
                "detail": self.detail}


def _verdict(case_id: str, title: str, gates: List[str],
             expected: Dict[str, Any], system: FixtureSystem,
             detail: str) -> CaseResult:
    observed = system.snapshot()
    ok = observed == expected
    return CaseResult(
        case_id=case_id, title=title, gates=gates,
        status="passed" if ok else "failed",
        expected_digest=_digest(expected),
        observed_digest=system.digest(),
        detail=detail if ok else
        f"{detail} ORACLE MISMATCH: expected {expected!r}, "
        f"observed {observed!r}")


def _refusal_verdict(case_id: str, title: str, gates: List[str],
                     system: FixtureSystem, before_digest: str,
                     caught: Optional[Exception],
                     expected_type: type) -> CaseResult:
    ok = (isinstance(caught, expected_type)
          and system.digest() == before_digest)
    detail = (f"refused by name ({type(caught).__name__}) and the "
              "fixture state is untouched" if ok else
              f"expected {expected_type.__name__} with untouched "
              f"state; got {caught!r}, digest "
              f"{system.digest()} vs before {before_digest}")
    return CaseResult(case_id=case_id, title=title, gates=gates,
                      status="passed" if ok else "failed",
                      expected_digest=before_digest,
                      observed_digest=system.digest(), detail=detail)


def _case_clean_install(work_dir: Optional[Path]) -> CaseResult:
    system = FixtureSystem()
    install(system, fixture_target(), PACKAGE_V1)
    problems = verify_install(system, PACKAGE_V1)
    result = _verdict("clean-install", "Clean install onto an empty "
                      "fixture target", ["G9", "release-lane"],
                      V1_SNAPSHOT, system,
                      "installed state equals the hand-written v1 "
                      "oracle and strict verification is clean")
    if problems:
        result.status = "failed"
        result.detail += f"; verify_install reported {problems!r}"
    return result


def _case_upgrade_forward(work_dir: Optional[Path]) -> CaseResult:
    system = FixtureSystem()
    install(system, fixture_target(), PACKAGE_V1)
    upgrade(system, fixture_target(), PACKAGE_V1, PACKAGE_V2)
    return _verdict("upgrade-forward", "Upgrade v1.0.0 -> v1.1.0 "
                    "applies the full package delta",
                    ["G9", "release-lane"], V2_SNAPSHOT, system,
                    "changed/added/removed files, config defaults "
                    "and services all match the v2 oracle")


def _case_upgrade_preserves_config(work_dir: Optional[Path]
                                   ) -> CaseResult:
    system = FixtureSystem()
    install(system, fixture_target(), PACKAGE_V1)
    system.config["demo.timeout"] = "99"  # user-modified value
    upgrade(system, fixture_target(), PACKAGE_V1, PACKAGE_V2)
    expected = json.loads(_canonical(V2_SNAPSHOT))
    expected["config"]["demo.timeout"] = "99"
    return _verdict("upgrade-preserves-user-config",
                    "Upgrade preserves a user-modified config value "
                    "while untouched keys follow the new defaults",
                    ["G9", "BookV-operational"], expected, system,
                    "demo.timeout stayed at the user's 99; the "
                    "dropped legacy key was removed (untouched) and "
                    "the new key arrived")


def _case_downgrade_refused(work_dir: Optional[Path]) -> CaseResult:
    system = FixtureSystem()
    install(system, fixture_target(), PACKAGE_V1)
    upgrade(system, fixture_target(), PACKAGE_V1, PACKAGE_V2)
    before = system.digest()
    caught: Optional[Exception] = None
    try:
        upgrade(system, fixture_target(), PACKAGE_V2, PACKAGE_V1)
    except Exception as exc:  # the refusal IS the oracle here
        caught = exc
    return _refusal_verdict("downgrade-refused",
                            "Downgrade without explicit allowance is "
                            "refused and changes nothing",
                            ["G4", "release-lane"], system, before,
                            caught, VersionRefusedError)


def _case_uninstall_clean(work_dir: Optional[Path]) -> CaseResult:
    system = FixtureSystem()
    install(system, fixture_target(), PACKAGE_V1)
    system.user_data["demo.user.notes"] = "keep me"
    uninstall(system, fixture_target(), PACKAGE_V1)
    return _verdict("uninstall-clean", "Uninstall removes files, "
                    "config, services and (by default) user data",
                    ["G9", "release-lane"], EMPTY_SNAPSHOT, system,
                    "the fixture system is byte-identical to a "
                    "never-installed system (uninstall cleanliness, "
                    "master roadmap section 7)")


def _case_uninstall_preserve_data(work_dir: Optional[Path]
                                  ) -> CaseResult:
    system = FixtureSystem()
    install(system, fixture_target(), PACKAGE_V1)
    system.user_data["demo.user.notes"] = "keep me"
    uninstall(system, fixture_target(), PACKAGE_V1,
              keep_user_data=True)
    expected = json.loads(_canonical(EMPTY_SNAPSHOT))
    expected["user_data"] = {"demo.user.notes": "keep me"}
    return _verdict("uninstall-preserve-user-data",
                    "Uninstall with explicit keep_user_data leaves "
                    "only the user data behind",
                    ["G9", "BookV-operational"], expected, system,
                    "user data remains by explicit choice; "
                    "everything the package owned is gone")


def _case_reinstall_idempotent(work_dir: Optional[Path]) -> CaseResult:
    system = FixtureSystem()
    install(system, fixture_target(), PACKAGE_V1)
    before = system.digest()
    caught: Optional[Exception] = None
    try:
        install(system, fixture_target(), PACKAGE_V1)
    except Exception as exc:
        caught = exc
    return _refusal_verdict("reinstall-idempotent",
                            "Reinstalling the installed version is a "
                            "named no-op refusal; state unchanged",
                            ["G9"], system, before, caught,
                            AlreadyInstalledError)


def _case_interrupted_install_recovery(work_dir: Optional[Path]
                                       ) -> CaseResult:
    system = FixtureSystem()
    caught: Optional[Exception] = None
    try:
        install(system, fixture_target(), PACKAGE_V1,
                interrupt_after=2)
    except SimulatedInstallInterrupt as exc:
        caught = exc
    if caught is None or system.pending_manifest is None:
        return CaseResult("interrupted-install-recovery",
                          "Interrupted install recovers to empty",
                          ["G3", "G4"], "failed", EMPTY_DIGEST,
                          system.digest(),
                          "the simulated interruption did not occur")
    outcome = recover(system)
    result = _verdict("interrupted-install-recovery",
                      "Install interrupted after 2 steps recovers "
                      "from the undo manifest alone",
                      ["G3", "G4"], EMPTY_SNAPSHOT, system,
                      "recovery reversed the applied steps and the "
                      "restored digest verified against the recorded "
                      "original")
    if not outcome.get("verified"):
        result.status = "failed"
        result.detail += "; recovery did not self-verify"
    return result


def _case_interrupted_upgrade_rollback(work_dir: Optional[Path]
                                       ) -> CaseResult:
    system = FixtureSystem()
    install(system, fixture_target(), PACKAGE_V1)
    caught: Optional[Exception] = None
    try:
        upgrade(system, fixture_target(), PACKAGE_V1, PACKAGE_V2,
                interrupt_after=3)
    except SimulatedInstallInterrupt as exc:
        caught = exc
    if caught is None or system.pending_manifest is None:
        return CaseResult("interrupted-upgrade-rollback",
                          "Interrupted upgrade rolls back to v1",
                          ["G3", "G4"], "failed", _digest(V1_SNAPSHOT),
                          system.digest(),
                          "the simulated interruption did not occur")
    recover(system)
    return _verdict("interrupted-upgrade-rollback",
                    "Upgrade interrupted mid-delta rolls back to "
                    "the exact v1 state (rollback, roadmap/08 "
                    "Release layer)", ["G3", "G4"], V1_SNAPSHOT,
                    system, "post-recovery snapshot equals the "
                    "hand-written v1 oracle exactly")


def _case_tamper_verify_repair(work_dir: Optional[Path]) -> CaseResult:
    system = FixtureSystem()
    install(system, fixture_target(), PACKAGE_V1)
    system.files["usr/lib/lifthrasir/core.bin"] = "tampered"
    problems = verify_install(system, PACKAGE_V1)
    if problems != ["file mismatch: usr/lib/lifthrasir/core.bin"]:
        return CaseResult("tampered-install-verification-and-repair",
                          "Tampered file is detected and repaired",
                          ["G4", "G5"], "failed", _digest(V1_SNAPSHOT),
                          system.digest(),
                          f"verification reported {problems!r}, not "
                          "exactly the tampered file")
    uninstall(system, fixture_target(), PACKAGE_V1)
    install(system, fixture_target(), PACKAGE_V1)
    return _verdict("tampered-install-verification-and-repair",
                    "Strict verification names the tampered file; "
                    "uninstall + clean reinstall repairs it",
                    ["G4", "G5"], V1_SNAPSHOT, system,
                    "after repair the snapshot equals the v1 oracle "
                    "and the tamper is gone")


def _case_journaled_recovery(work_dir: Optional[Path]) -> CaseResult:
    """Compose the banked LIF-0505 reversal journal directly."""
    if work_dir is None:
        tmp = Path(tempfile.mkdtemp(prefix="lif1203-journal-"))
    else:
        # a fresh subdir per run: the journal is single-transaction
        # by design (LIF-0505), so reusing one path would refuse
        tmp = Path(tempfile.mkdtemp(prefix="journal-",
                                    dir=str(work_dir)))
    tmp.mkdir(parents=True, exist_ok=True)
    journal_path = tmp / "undo.json"
    state = _reversal.FixtureState({})
    runner = _reversal.OperationRunner(state, journal_path)
    steps = [_reversal.Step(f"file-{i}", f"file:{path}", content)
             for i, (path, content) in enumerate(
                 sorted(PACKAGE_V1.files.items()))]
    runner.plan("lif1203-install", steps)
    caught: Optional[Exception] = None
    try:
        runner.run(after_steps=1)
    except _reversal.SimulatedInterrupt as exc:
        caught = exc
    if caught is None:
        return CaseResult("journaled-interruption-recovery",
                          "Banked reversal journal recovers an "
                          "interrupted install", ["G3", "G4"],
                          "failed", _reversal.FixtureState({}).digest(),
                          state.digest(),
                          "the simulated interruption did not occur")
    outcome = _reversal.OperationRunner.recover(state, journal_path)
    ok = (outcome.get("verified") is True
          and state.digest() == _reversal.FixtureState({}).digest())
    return CaseResult(
        "journaled-interruption-recovery",
        "Banked LIF-0505 journal + fresh-runner recovery restores "
        "the pre-install state", ["G3", "G4"],
        "passed" if ok else "failed",
        _reversal.FixtureState({}).digest(), state.digest(),
        "recovery came from the on-disk journal alone (the "
        "original runner was discarded) and self-verified")


def _case_host_target_refused(work_dir: Optional[Path]) -> CaseResult:
    system = FixtureSystem()
    before = system.digest()
    host = {"target_id": "purpleraider", "kind": "fixture-vm",
            "environment": LAB_ENVIRONMENT, "disposable": True}
    nondisposable = {"target_id": "fixture-guest-02",
                     "kind": "fixture-vm",
                     "environment": LAB_ENVIRONMENT,
                     "disposable": False}
    caught: List[Exception] = []
    for target in (host, nondisposable):
        try:
            install(system, target, PACKAGE_V1)
        except Exception as exc:
            caught.append(exc)
    ok = (len(caught) == 2
          and all(isinstance(c, HostTargetError) for c in caught)
          and system.digest() == before)
    return CaseResult(
        "host-target-refused",
        "A real-host id and a non-disposable target are both "
        "refused by name before any mutation (section 0)",
        ["G4", "section-0"], "passed" if ok else "failed", before,
        system.digest(),
        "both refusals were HostTargetError and the fixture "
        "system is untouched" if ok else
        f"refusals were {caught!r}")


def _case_emergency_stop(work_dir: Optional[Path]) -> CaseResult:
    system = FixtureSystem()
    before = system.digest()
    caught: Optional[Exception] = None
    try:
        install(system, fixture_target(), PACKAGE_V1,
                emergency_stop=True)
    except Exception as exc:
        caught = exc
    return _refusal_verdict("emergency-stop",
                            "Emergency stop refuses install before "
                            "any mutation, without any model",
                            ["G3", "section-0"], system, before,
                            caught, EmergencyStopError)


CASE_BUILDERS = {
    "clean-install": _case_clean_install,
    "upgrade-forward": _case_upgrade_forward,
    "upgrade-preserves-user-config": _case_upgrade_preserves_config,
    "downgrade-refused": _case_downgrade_refused,
    "uninstall-clean": _case_uninstall_clean,
    "uninstall-preserve-user-data": _case_uninstall_preserve_data,
    "reinstall-idempotent": _case_reinstall_idempotent,
    "interrupted-install-recovery": _case_interrupted_install_recovery,
    "interrupted-upgrade-rollback": _case_interrupted_upgrade_rollback,
    "tampered-install-verification-and-repair":
        _case_tamper_verify_repair,
    "journaled-interruption-recovery": _case_journaled_recovery,
    "host-target-refused": _case_host_target_refused,
    "emergency-stop": _case_emergency_stop,
}

CASE_ORDER = [
    "clean-install", "upgrade-forward",
    "upgrade-preserves-user-config", "downgrade-refused",
    "uninstall-clean", "uninstall-preserve-user-data",
    "reinstall-idempotent", "interrupted-install-recovery",
    "interrupted-upgrade-rollback",
    "tampered-install-verification-and-repair",
    "journaled-interruption-recovery", "host-target-refused",
    "emergency-stop",
]


def run_case(case_id: str,
             work_dir: Optional[Path] = None) -> CaseResult:
    builder = CASE_BUILDERS.get(case_id)
    if builder is None:
        raise UnknownCaseError(
            f"unknown acceptance case {case_id!r}; known: "
            f"{CASE_ORDER}")
    try:
        return builder(work_dir)
    except Exception as exc:  # a case must report, never explode
        return CaseResult(case_id, f"case {case_id}", [], "failed",
                          "", "", f"case raised unexpectedly: {exc!r}")


@dataclass
class SuiteReport:
    results: List[CaseResult]
    passed: int
    failed: int
    skipped: int
    gates: Dict[str, str]
    not_covered: List[str]
    provenance_hash: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "schema": ACCEPTANCE_SCHEMA,
            "schema_version": ACCEPTANCE_SCHEMA_VERSION,
            "evidence_status": EVIDENCE_STATUS,
            "passed": self.passed, "failed": self.failed,
            "skipped": self.skipped,
            "results": [r.to_dict() for r in self.results],
            "gates": dict(self.gates),
            "not_covered": list(self.not_covered),
            "provenance_hash": self.provenance_hash,
        }


GATE_COVERAGE = {
    "G3": "covered at fixture level: interrupted install/upgrade "
          "recovery + emergency stop (cases "
          "interrupted-install-recovery, "
          "interrupted-upgrade-rollback, "
          "journaled-interruption-recovery, emergency-stop)",
    "G4": "covered at fixture level: downgrade refusal, host-target "
          "refusal, tamper detection (cases downgrade-refused, "
          "host-target-refused, "
          "tampered-install-verification-and-repair)",
    "G9": "covered at FIXTURE level only: clean install, upgrade, "
          "uninstall against hand-written oracles (cases "
          "clean-install, upgrade-forward, uninstall-clean, "
          "uninstall-preserve-user-data, reinstall-idempotent)",
}

NOT_COVERED = [
    "real .deb/.rpm generation, signing and repository publication "
    "(LIF-1201, building in parallel; deliberately not depended on)",
    "real package-manager install/upgrade/uninstall on any distro "
    "(no real target is ever touched by this suite)",
    "cross-distro execution of the matrix (P11 adapters are "
    "contract-level; G9 is claimed at fixture level only)",
    "reboot persistence, power-loss on real hardware, and GUI "
    "install flows (LIF-1202 UX; human-reviewed release work)",
]


def run_acceptance_suite(
        work_dir: Optional[Path] = None) -> SuiteReport:
    """Run every acceptance case against fresh fixture systems."""
    results = [run_case(case_id, work_dir) for case_id in CASE_ORDER]
    passed = sum(1 for r in results if r.status == "passed")
    failed = sum(1 for r in results if r.status == "failed")
    body = {"results": [r.to_dict() for r in results],
            "passed": passed, "failed": failed, "skipped": 0}
    return SuiteReport(results=results, passed=passed, failed=failed,
                       skipped=0, gates=dict(GATE_COVERAGE),
                       not_covered=list(NOT_COVERED),
                       provenance_hash=_digest(body))
