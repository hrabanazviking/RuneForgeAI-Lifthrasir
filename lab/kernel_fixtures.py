# SPDX-License-Identifier: GPL-2.0-only
"""LIF-0901: version-pinned Linux build fixtures for x86-64 and arm64.

Home: master roadmap section 3 places lab tooling under ``lab/`` and
Book III (roadmap/03, P9) requires every kernel experiment to be
pinned to an exact source, configuration checksum and toolchain
version, built and run only inside disposable VMs. This module is the
fixture layer for that lab, following the LIF-0101 recipe precedent
(``lab/images/``: declarative pin as data beside the code that
consumes it, fail-closed verification, checksums retrieved from the
official source or labelled UNVERIFIED - never invented).

A fixture (``lab/kernels/<fixture-id>/fixture.json``) pins, for one
architecture:

* the exact kernel release: version, release tarball name, official
  origin + checksum URLs, the tarball SHA-256 with its provenance
  status, and the stable-tree git tag object + commit;
* the configuration: a named defconfig base plus config fragments
  whose own SHA-256 and required CONFIG options are pinned - the
  fragment file beside the fixture must hash to the pinned value and
  contain every required option, or loading refuses;
* the toolchain expectations: per-role tool/command with either a
  lab-observed exact version or an explicit UNVERIFIED status with
  no version claimed (an expectation is never invented);
* the disposable-guest expectation (emulator + machine) and the
  safety block: disposable-VM-only, host kernel / bootloader /
  firmware never touched. A fixture whose safety block says anything
  else refuses to load at all.

Two honesty gates, kept separate on purpose:

* ``validate_fixture`` / ``load_fixture`` prove a fixture is
  well-formed and fully pinned (an unpinned, floating, mismatched or
  unofficial-origin fixture refuses with a named error);
* ``assert_buildable`` additionally requires every pin to be
  VERIFIED: a fixture carrying an UNVERIFIED source checksum or an
  UNVERIFIED toolchain expectation is valid data but NOT buildable,
  and this gate says so by name. (The shipped arm64 fixture is
  exactly that case for its cross-compiler: no aarch64 cross-gcc is
  installed on the lab host, so its version is UNVERIFIED, not
  guessed.)

Scope honesty (master roadmap section 0, invariants 2 and 5): this
module downloads nothing, builds nothing and boots nothing. It
validates fixture data and hashes bytes a caller hands it
(``verify_source_bytes`` / ``verify_source_file``). No kernel was
downloaded or built for this slice - the 149 MB tarball was checked
by HEAD request only; its pinned SHA-256 comes from kernel.org's
PGP-signed sha256sums.asc (see the fixture docs). Kernel builds, when
later slices run them, happen only in disposable VMs. This module
imports no network, subprocess or process machinery at all
(AST-pinned in tests).
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

KERNEL_FIXTURE_SCHEMA = "lifthrasir.kernel-fixture.v1"
KERNEL_FIXTURE_SCHEMA_VERSION = "1"
KERNELS_DIR = Path(__file__).resolve().parent / "kernels"
SUPPORTED_ARCHES = ("arm64", "x86_64")
ARCH_MAKE_MAP = {"x86_64": "x86_64", "arm64": "arm64"}
ARCH_DEFCONFIG = {"x86_64": "x86_64_defconfig", "arm64": "defconfig"}
ARCH_EMULATOR = {"x86_64": "qemu-system-x86_64", "arm64": "qemu-system-aarch64"}
OFFICIAL_SOURCE_HOSTS = frozenset(
    {"cdn.kernel.org", "git.kernel.org", "www.kernel.org", "kernel.org"})
CHECKSUM_STATUSES = ("retrieved-from-official-source", "UNVERIFIED")
VERSION_STATUSES = ("lab-observed", "UNVERIFIED")
_VERSION_RE = re.compile(r"^\d+\.\d+\.\d+$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_OID_RE = re.compile(r"^[0-9a-f]{40}$")
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_OPTION_RE = re.compile(r"^CONFIG_[A-Z0-9_]+=")


class KernelFixtureError(Exception):
    """Base class for all named kernel-fixture refusals."""


class MalformedFixtureError(KernelFixtureError):
    """Raised when a fixture is structurally malformed or unsafe."""


class UnpinnedFixtureError(KernelFixtureError):
    """Raised when a required pin is missing or not exact."""


class UnofficialOriginError(KernelFixtureError):
    """Raised when a source URL is not on an official kernel.org host."""


class UnsupportedArchitectureError(KernelFixtureError):
    """Raised when the architecture is not x86_64 or arm64."""


class FragmentMismatchError(KernelFixtureError):
    """Raised when a config fragment fails its pinned hash/options."""


class ChecksumMismatchError(KernelFixtureError):
    """Raised when handed source bytes do not match the pinned SHA-256."""


class UnverifiedPinError(KernelFixtureError):
    """Raised when a build is asked to rely on an UNVERIFIED pin."""


@dataclass(frozen=True)
class KernelSource:
    version: str
    series: str
    release_kind: str
    tarball: str
    origin_url: str
    checksum_url: str
    checksum_sha256: str | None
    checksum_status: str
    checksum_retrieved: str | None
    tarball_size_bytes: int | None
    git_repo: str
    git_tag: str
    git_tag_object: str | None
    git_commit: str | None
    git_status: str


@dataclass(frozen=True)
class ToolchainExpectation:
    role: str
    tool: str
    command: str
    expected_version: str | None
    version_status: str
    note: str


@dataclass(frozen=True)
class ConfigFragment:
    name: str
    file: str
    sha256: str
    required_options: tuple


@dataclass(frozen=True)
class GuestExpectation:
    emulator: str
    machine: str
    disposable: bool


@dataclass(frozen=True)
class SafetyExpectation:
    disposable_vm_only: bool
    host_kernel_touched: bool
    bootloader_touched: bool
    firmware_touched: bool


@dataclass(frozen=True)
class KernelFixture:
    fixture_id: str
    slice: str
    schema: str
    architecture: str
    make_arch: str
    defconfig: str
    source: KernelSource
    config_fragments: tuple
    toolchain: tuple
    guest: GuestExpectation
    safety: SafetyExpectation

    def to_dict(self) -> dict:
        s = self.source
        return {
            "slice": self.slice, "schema": self.schema,
            "fixture_id": self.fixture_id,
            "architecture": self.architecture,
            "make_arch": self.make_arch, "defconfig": self.defconfig,
            "source": {
                "version": s.version, "series": s.series,
                "release_kind": s.release_kind, "tarball": s.tarball,
                "origin_url": s.origin_url, "checksum_url": s.checksum_url,
                "checksum_sha256": s.checksum_sha256,
                "checksum_status": s.checksum_status,
                "checksum_retrieved": s.checksum_retrieved,
                "tarball_size_bytes": s.tarball_size_bytes,
                "git_repo": s.git_repo, "git_tag": s.git_tag,
                "git_tag_object": s.git_tag_object,
                "git_commit": s.git_commit, "git_status": s.git_status},
            "config_fragments": [
                {"name": f.name, "file": f.file, "sha256": f.sha256,
                 "required_options": list(f.required_options)}
                for f in self.config_fragments],
            "toolchain": [
                {"role": t.role, "tool": t.tool, "command": t.command,
                 "expected_version": t.expected_version,
                 "version_status": t.version_status, "note": t.note}
                for t in self.toolchain],
            "guest": {"emulator": self.guest.emulator,
                      "machine": self.guest.machine,
                      "disposable": self.guest.disposable},
            "safety": {
                "disposable_vm_only": self.safety.disposable_vm_only,
                "host_kernel_touched": self.safety.host_kernel_touched,
                "bootloader_touched": self.safety.bootloader_touched,
                "firmware_touched": self.safety.firmware_touched}}


def _req_str(data: dict, key: str, where: str) -> str:
    value = data.get(key)
    if not isinstance(value, str) or not value.strip():
        raise UnpinnedFixtureError(f"{where}: missing or empty pin: {key}")
    return value


def _official_https(url: str, where: str) -> str:
    parsed = urlparse(url)
    if parsed.scheme != "https" or parsed.hostname not in OFFICIAL_SOURCE_HOSTS:
        raise UnofficialOriginError(
            f"{where}: not an official kernel.org https origin: {url}")
    return url


def _validate_source(raw: object) -> KernelSource:
    if not isinstance(raw, dict):
        raise MalformedFixtureError("source: must be an object")
    version = _req_str(raw, "version", "source")
    if not _VERSION_RE.match(version):
        raise UnpinnedFixtureError(
            f"source: version is not an exact pinned release: {version!r}")
    series = _req_str(raw, "series", "source")
    if series != ".".join(version.split(".")[:2]):
        raise MalformedFixtureError(
            f"source: series {series!r} does not match version {version!r}")
    release_kind = _req_str(raw, "release_kind", "source")
    tarball = _req_str(raw, "tarball", "source")
    if tarball != f"linux-{version}.tar.xz":
        raise MalformedFixtureError(
            f"source: tarball {tarball!r} does not match version {version!r}")
    origin_url = _official_https(_req_str(raw, "origin_url", "source"), "source.origin_url")
    if not origin_url.endswith("/" + tarball):
        raise MalformedFixtureError("source: origin_url does not end with the pinned tarball name")
    checksum_url = _official_https(_req_str(raw, "checksum_url", "source"), "source.checksum_url")
    status = _req_str(raw, "checksum_status", "source")
    if status not in CHECKSUM_STATUSES:
        raise MalformedFixtureError(f"source: unknown checksum_status: {status!r}")
    sha = raw.get("checksum_sha256")
    retrieved = raw.get("checksum_retrieved")
    if status == "UNVERIFIED":
        if sha is not None:
            raise MalformedFixtureError(
                "source: UNVERIFIED checksum must not claim a sha256 value")
    else:
        if not isinstance(sha, str) or not _SHA256_RE.match(sha):
            raise UnpinnedFixtureError(
                "source: verified checksum_status requires a lowercase sha256 pin")
        if not isinstance(retrieved, str) or not _DATE_RE.match(retrieved):
            raise UnpinnedFixtureError(
                "source: verified checksum requires a checksum_retrieved date")
    size = raw.get("tarball_size_bytes")
    if size is not None and (not isinstance(size, int) or isinstance(size, bool) or size <= 0):
        raise MalformedFixtureError("source: tarball_size_bytes must be a positive int or null")
    git_repo = _official_https(_req_str(raw, "git_repo", "source"), "source.git_repo")
    git_tag = _req_str(raw, "git_tag", "source")
    if git_tag != f"v{version}":
        raise MalformedFixtureError(f"source: git_tag {git_tag!r} does not match version")
    git_status = _req_str(raw, "git_status", "source")
    if git_status not in CHECKSUM_STATUSES:
        raise MalformedFixtureError(f"source: unknown git_status: {git_status!r}")
    tag_object = raw.get("git_tag_object")
    commit = raw.get("git_commit")
    if git_status == "UNVERIFIED":
        if tag_object is not None or commit is not None:
            raise MalformedFixtureError(
                "source: UNVERIFIED git pin must not claim tag object or commit values")
    else:
        if not isinstance(tag_object, str) or not _OID_RE.match(tag_object):
            raise UnpinnedFixtureError("source: verified git pin requires a git_tag_object")
        if not isinstance(commit, str) or not _OID_RE.match(commit):
            raise UnpinnedFixtureError("source: verified git pin requires a full git_commit")
    return KernelSource(
        version=version, series=series, release_kind=release_kind,
        tarball=tarball, origin_url=origin_url, checksum_url=checksum_url,
        checksum_sha256=sha, checksum_status=status,
        checksum_retrieved=retrieved, tarball_size_bytes=size,
        git_repo=git_repo, git_tag=git_tag, git_tag_object=tag_object,
        git_commit=commit, git_status=git_status)


def _validate_fragments(raw: object, base_dir: Path | None) -> tuple:
    if not isinstance(raw, list) or not raw:
        raise UnpinnedFixtureError("config_fragments: at least one pinned fragment is required")
    out = []
    for i, item in enumerate(raw):
        where = f"config_fragments[{i}]"
        if not isinstance(item, dict):
            raise MalformedFixtureError(f"{where}: must be an object")
        name = _req_str(item, "name", where)
        fname = _req_str(item, "file", where)
        if Path(fname).name != fname:
            raise MalformedFixtureError(f"{where}: fragment file must be a bare filename: {fname!r}")
        sha = item.get("sha256")
        if not isinstance(sha, str) or not _SHA256_RE.match(sha):
            raise UnpinnedFixtureError(f"{where}: fragment requires a lowercase sha256 pin")
        options = item.get("required_options")
        if not isinstance(options, list) or not options:
            raise UnpinnedFixtureError(f"{where}: required_options must be a non-empty list")
        for opt in options:
            if not isinstance(opt, str) or not _OPTION_RE.match(opt):
                raise MalformedFixtureError(f"{where}: bad required option: {opt!r}")
        if base_dir is not None:
            fpath = base_dir / fname
            if not fpath.is_file():
                raise FragmentMismatchError(f"{where}: fragment file not found: {fname}")
            actual = hashlib.sha256(fpath.read_bytes()).hexdigest()
            if actual != sha:
                raise FragmentMismatchError(
                    f"{where}: fragment sha256 mismatch: pinned {sha}, got {actual}")
            lines = fpath.read_text(encoding="utf-8").splitlines()
            for opt in options:
                if not any(line.strip() == opt for line in lines):
                    raise FragmentMismatchError(
                        f"{where}: required option missing from fragment: {opt}")
        out.append(ConfigFragment(name=name, file=fname, sha256=sha,
                                  required_options=tuple(options)))
    return tuple(out)


def _validate_toolchain(raw: object) -> tuple:
    if not isinstance(raw, list) or not raw:
        raise UnpinnedFixtureError("toolchain: at least one expectation is required")
    out = []
    for i, item in enumerate(raw):
        where = f"toolchain[{i}]"
        if not isinstance(item, dict):
            raise MalformedFixtureError(f"{where}: must be an object")
        role = _req_str(item, "role", where)
        tool = _req_str(item, "tool", where)
        command = _req_str(item, "command", where)
        status = _req_str(item, "version_status", where)
        if status not in VERSION_STATUSES:
            raise MalformedFixtureError(f"{where}: unknown version_status: {status!r}")
        expected = item.get("expected_version")
        if status == "UNVERIFIED":
            if expected is not None:
                raise MalformedFixtureError(
                    f"{where}: UNVERIFIED expectation must not claim a version")
        elif not isinstance(expected, str) or not expected.strip():
            raise UnpinnedFixtureError(
                f"{where}: lab-observed expectation requires an exact expected_version")
        note = item.get("note")
        if not isinstance(note, str):
            raise MalformedFixtureError(f"{where}: note must be a string")
        out.append(ToolchainExpectation(role=role, tool=tool, command=command,
                                        expected_version=expected,
                                        version_status=status, note=note))
    return tuple(out)


def fixture_from_dict(data: object, *, base_dir: Path | None = None) -> KernelFixture:
    """Validate fixture data; with base_dir, also verify fragment files."""
    if not isinstance(data, dict):
        raise MalformedFixtureError("fixture: must be a JSON object")
    schema = data.get("schema")
    if schema != KERNEL_FIXTURE_SCHEMA:
        raise MalformedFixtureError(f"fixture: schema must be {KERNEL_FIXTURE_SCHEMA!r}")
    slice_id = _req_str(data, "slice", "fixture")
    arch = data.get("architecture")
    if arch not in SUPPORTED_ARCHES:
        raise UnsupportedArchitectureError(f"fixture: unsupported architecture: {arch!r}")
    make_arch = _req_str(data, "make_arch", "fixture")
    if make_arch != ARCH_MAKE_MAP[arch]:
        raise MalformedFixtureError(
            f"fixture: make_arch {make_arch!r} does not match architecture {arch!r}")
    defconfig = _req_str(data, "defconfig", "fixture")
    if defconfig != ARCH_DEFCONFIG[arch]:
        raise MalformedFixtureError(
            f"fixture: defconfig {defconfig!r} does not match architecture {arch!r}")
    source = _validate_source(data.get("source"))
    fixture_id = _req_str(data, "fixture_id", "fixture")
    expected_id = f"linux-{source.version}-{arch}"
    if fixture_id != expected_id:
        raise MalformedFixtureError(
            f"fixture: fixture_id {fixture_id!r} does not match {expected_id!r}")
    fragments = _validate_fragments(data.get("config_fragments"), base_dir)
    toolchain = _validate_toolchain(data.get("toolchain"))
    guest_raw = data.get("guest")
    if not isinstance(guest_raw, dict):
        raise MalformedFixtureError("guest: must be an object")
    emulator = _req_str(guest_raw, "emulator", "guest")
    if emulator != ARCH_EMULATOR[arch]:
        raise MalformedFixtureError(
            f"guest: emulator {emulator!r} does not match architecture {arch!r}")
    machine = _req_str(guest_raw, "machine", "guest")
    if guest_raw.get("disposable") is not True:
        raise MalformedFixtureError("guest: disposable must be true (roadmap section 0, invariant 5)")
    guest = GuestExpectation(emulator=emulator, machine=machine, disposable=True)
    safety_raw = data.get("safety")
    if not isinstance(safety_raw, dict):
        raise MalformedFixtureError("safety: must be an object")
    if safety_raw.get("disposable_vm_only") is not True:
        raise MalformedFixtureError("safety: disposable_vm_only must be true")
    for key in ("host_kernel_touched", "bootloader_touched", "firmware_touched"):
        if safety_raw.get(key) is not False:
            raise MalformedFixtureError(f"safety: {key} must be false (roadmap section 0, invariant 2)")
    safety = SafetyExpectation(disposable_vm_only=True, host_kernel_touched=False,
                               bootloader_touched=False, firmware_touched=False)
    return KernelFixture(fixture_id=fixture_id, slice=slice_id, schema=schema,
                         architecture=arch, make_arch=make_arch, defconfig=defconfig,
                         source=source, config_fragments=fragments,
                         toolchain=toolchain, guest=guest, safety=safety)


def validate_fixture(data: object) -> KernelFixture:
    """Structural + pin validation only (no filesystem access)."""
    return fixture_from_dict(data)


def load_fixture(path: Path) -> KernelFixture:
    """Load a fixture.json and verify its fragment files beside it."""
    path = Path(path)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise MalformedFixtureError(f"{path}: unreadable fixture: {exc}") from exc
    return fixture_from_dict(data, base_dir=path.parent)


def assert_buildable(fixture: KernelFixture) -> None:
    """Refuse unless every pin a build would rely on is VERIFIED."""
    if fixture.source.checksum_status != "retrieved-from-official-source":
        raise UnverifiedPinError(
            f"{fixture.fixture_id}: source checksum is UNVERIFIED - not buildable")
    if fixture.source.git_status != "retrieved-from-official-source":
        raise UnverifiedPinError(
            f"{fixture.fixture_id}: git pin is UNVERIFIED - not buildable")
    for entry in fixture.toolchain:
        if entry.version_status == "UNVERIFIED":
            raise UnverifiedPinError(
                f"{fixture.fixture_id}: toolchain {entry.tool} ({entry.role}) "
                "version is UNVERIFIED - not buildable")


def verify_source_bytes(fixture: KernelFixture, data: bytes) -> str:
    """Hash handed-in source bytes against the pinned tarball SHA-256."""
    if fixture.source.checksum_sha256 is None:
        raise UnverifiedPinError(
            f"{fixture.fixture_id}: no verified checksum pin to verify against")
    actual = hashlib.sha256(data).hexdigest()
    if actual != fixture.source.checksum_sha256:
        raise ChecksumMismatchError(
            f"{fixture.fixture_id}: sha256 mismatch: pinned "
            f"{fixture.source.checksum_sha256}, got {actual}")
    return actual


def verify_source_file(fixture: KernelFixture, path: Path) -> str:
    path = Path(path)
    if not path.is_file():
        raise ChecksumMismatchError(f"{fixture.fixture_id}: file not found: {path}")
    return verify_source_bytes(fixture, path.read_bytes())


def build_kernel_manifest(fixture_dir: Path) -> str:
    """Deterministic manifest for a fixture directory (cf. LIF-0101).

    Output depends ONLY on fixture.json + its fragment files: entries
    sorted, no timestamps, no host data. Two runs are byte-identical.
    """
    fixture_dir = Path(fixture_dir)
    fixture = load_fixture(fixture_dir / "fixture.json")
    s = fixture.source
    lines = ["lifthrasir-kernel-fixture-manifest-v1",
             f"slice={fixture.slice}", f"fixture_id={fixture.fixture_id}",
             f"architecture={fixture.architecture}",
             f"make_arch={fixture.make_arch}", f"defconfig={fixture.defconfig}",
             f"version={s.version}", f"tarball={s.tarball}",
             f"origin_url={s.origin_url}",
             f"checksum_sha256={s.checksum_sha256}",
             f"checksum_status={s.checksum_status}",
             f"git_commit={s.git_commit}", "fragments:"]
    for frag in sorted(fixture.config_fragments, key=lambda f: f.name):
        lines.append(f"  - {frag.name} sha256={frag.sha256}")
    lines.append("toolchain:")
    for entry in sorted(fixture.toolchain, key=lambda t: t.role):
        version = entry.expected_version if entry.expected_version is not None else "UNVERIFIED"
        lines.append(f"  - {entry.role} {entry.tool} {version} ({entry.version_status})")
    lines.append(f"guest={fixture.guest.emulator} {fixture.guest.machine} disposable=true")
    body = "\n".join(lines) + "\n"
    digest = hashlib.sha256(body.encode("utf-8")).hexdigest()
    return body + f"manifest_sha256={digest}\n"


def builtin_fixture_ids() -> list:
    if not KERNELS_DIR.is_dir():
        return []
    return sorted(p.parent.name for p in KERNELS_DIR.glob("*/fixture.json"))


def load_builtin_fixture(fixture_id: str) -> KernelFixture:
    if fixture_id not in builtin_fixture_ids():
        raise MalformedFixtureError(f"unknown builtin fixture: {fixture_id!r}")
    return load_fixture(KERNELS_DIR / fixture_id / "fixture.json")
