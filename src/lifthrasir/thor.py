"""Thor read-only process and package integrity detector (LIF-0801).

SPDX-License-Identifier: GPL-2.0-only

Home justification: master roadmap section 3 places core code under
``src/``; the P5 companion classifier (LIF-0506, service_intent)
already lives in ``src/lifthrasir/`` consuming recorded collector
output, and Thor (P8) is the same shape of component: it consumes
RECORDED fixture snapshots -- a process table and a package file
manifest with hashes -- and emits typed, evidence-carrying verdicts.
It therefore lives in the core package beside service_intent. Per
campaign orders this slice does NOT edit ``src/lifthrasir/__init__.py``;
desired exports are listed in CAMPAIGN_STATE.md for the seat union.

Strictly READ-ONLY contract (master roadmap section 0 invariants;
P8 entry gate: Thor actions always constrained by deterministic
policy; this slice's detector takes NO actions at all):

- Detection runs ONLY over caller-supplied fixture snapshots
  (in-memory records or JSON-shaped dicts). This module never reads
  the live host: no /proc walk, no package-database query, no file
  open. A live-host reading mode is out of scope; if one is ever
  added it must follow the banked collectors' pattern (lab/
  proc_sensors.py, lab/systemd_collector.py: recorded fixture-shaped
  text in, typed records out) and feed THIS detector unchanged.
- The module imports no process, network or filesystem machinery,
  opens nothing, controls no process, and mutates nothing:
  inputs are frozen dataclasses / tuples, detection is a pure
  function, and a source-scan test pins the import allowlist.
- Verdicts never invent data: an absent observed hash stays absent
  (the file is reported missing only when the snapshot itself marks
  it absent; see below), and an empty baseline refuses by name
  instead of silently passing everything.

Detection rules (deterministic, no model involved):

- HASH_MISMATCH: a manifest file is present in the snapshot but its
  observed SHA-256 differs from the manifest's expected SHA-256.
- MISSING_FILE: a manifest file is absent from the snapshot.
- UNEXPECTED_FILE: a snapshot file claims a package owner but is
  not in the manifest (reported, never removed).
- UNKNOWN_PROCESS: a snapshot process whose comm (and exe, when
  recorded) matches no baseline allowlist entry.
- MISSING_PROCESS: a baseline-required process is absent from the
  snapshot (only for baseline entries marked required).

Findings are sorted deterministically (kind, subject) so two runs
over the same snapshot produce byte-identical reports. Every
finding names its baseline (process baseline name or manifest
name), the expected value, and the observed value, and the report
carries LIF-0004-shaped evidence fields.

Evidence status: reproducer / fixture-level lab-verified on
purpleraider. No live-host detection is claimed.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass

THOR_SCHEMA = "lif0801-thor/1"
THOR_VERSION = "0.1"

KIND_HASH_MISMATCH = "hash_mismatch"
KIND_MISSING_FILE = "missing_file"
KIND_UNEXPECTED_FILE = "unexpected_file"
KIND_UNKNOWN_PROCESS = "unknown_process"
KIND_MISSING_PROCESS = "missing_process"
FINDING_KINDS = frozenset({
    KIND_HASH_MISMATCH, KIND_MISSING_FILE, KIND_UNEXPECTED_FILE,
    KIND_UNKNOWN_PROCESS, KIND_MISSING_PROCESS,
})

_HASH_RE = re.compile(r"^(sha256:)?[0-9a-fA-F]{64}$")


class ThorError(Exception):
    """Base class for all named Thor refusals."""


class MalformedSnapshotError(ThorError):
    """Raised when a snapshot, manifest or baseline is malformed."""


class DuplicateEntryError(ThorError):
    """Raised when a manifest/baseline/snapshot repeats a subject."""


def _norm_hash(value, what):
    if not isinstance(value, str) or not _HASH_RE.match(value.strip()):
        raise MalformedSnapshotError(
            f"{what}: expected a SHA-256 hex digest, got {value!r}")
    hexpart = value.strip().lower().removeprefix("sha256:")
    return "sha256:" + hexpart


def sha256_of_bytes(data):
    """SHA-256 of caller-supplied bytes, in sha256:hex form (the
    LIF-0302 provenance digest form). Pure: hashes memory only."""
    if not isinstance(data, (bytes, bytearray)):
        raise MalformedSnapshotError(
            f"sha256_of_bytes: expected bytes, got {type(data).__name__}")
    return "sha256:" + hashlib.sha256(bytes(data)).hexdigest()


@dataclass(frozen=True)
class ProcessObservation:
    """One recorded process-table row (fixture data only)."""
    pid: int
    comm: str
    ppid: int | None = None
    exe: str | None = None
    user: str | None = None
    cmdline: tuple = ()

    def __post_init__(self):
        if not isinstance(self.pid, int) or self.pid <= 0:
            raise MalformedSnapshotError(
                f"process: pid must be a positive int, got {self.pid!r}")
        if not isinstance(self.comm, str) or not self.comm.strip():
            raise MalformedSnapshotError(
                f"process pid={self.pid}: comm must be non-empty")
        object.__setattr__(self, "cmdline", tuple(self.cmdline or ()))


@dataclass(frozen=True)
class ExpectedProcess:
    """One baseline allowlist entry. ``required`` entries must be
    present in the snapshot; optional entries merely allow."""
    comm: str
    exe: str | None = None
    required: bool = False

    def __post_init__(self):
        if not isinstance(self.comm, str) or not self.comm.strip():
            raise MalformedSnapshotError(
                "baseline process: comm must be non-empty")


@dataclass(frozen=True)
class ProcessBaseline:
    """A named allowlist of expected processes."""
    name: str
    processes: tuple = ()

    def __post_init__(self):
        if not isinstance(self.name, str) or not self.name.strip():
            raise MalformedSnapshotError(
                "process baseline: name must be non-empty")
        object.__setattr__(self, "processes", tuple(self.processes or ()))
        seen = set()
        for p in self.processes:
            key = (p.comm, p.exe)
            if key in seen:
                raise DuplicateEntryError(
                    f"process baseline {self.name!r}: duplicate entry "
                    f"comm={p.comm!r} exe={p.exe!r}")
            seen.add(key)


@dataclass(frozen=True)
class ManifestFile:
    """One package-manifest entry: a path and its expected hash."""
    path: str
    expected_sha256: str
    package: str | None = None

    def __post_init__(self):
        if not isinstance(self.path, str) or not self.path.startswith("/"):
            raise MalformedSnapshotError(
                f"manifest file: path must be absolute, got {self.path!r}")
        object.__setattr__(
            self, "expected_sha256",
            _norm_hash(self.expected_sha256,
                       f"manifest file {self.path}"))


@dataclass(frozen=True)
class PackageManifest:
    """A named package file manifest (the integrity baseline)."""
    name: str
    files: tuple = ()

    def __post_init__(self):
        if not isinstance(self.name, str) or not self.name.strip():
            raise MalformedSnapshotError(
                "package manifest: name must be non-empty")
        object.__setattr__(self, "files", tuple(self.files or ()))
        seen = set()
        for f in self.files:
            if f.path in seen:
                raise DuplicateEntryError(
                    f"manifest {self.name!r}: duplicate path {f.path!r}")
            seen.add(f.path)


@dataclass(frozen=True)
class ObservedFile:
    """One recorded snapshot file. ``present=False`` (or the path
    simply absent from the snapshot) means the manifest entry is
    missing. ``observed_sha256`` may be None only when absent."""
    path: str
    observed_sha256: str | None = None
    package: str | None = None
    present: bool = True

    def __post_init__(self):
        if not isinstance(self.path, str) or not self.path.startswith("/"):
            raise MalformedSnapshotError(
                f"observed file: path must be absolute, got {self.path!r}")
        if self.present and self.observed_sha256 is not None:
            object.__setattr__(
                self, "observed_sha256",
                _norm_hash(self.observed_sha256,
                           f"observed file {self.path}"))
        if self.present and self.observed_sha256 is None:
            raise MalformedSnapshotError(
                f"observed file {self.path}: present but no hash recorded "
                "(unknown is not verified; record a hash or mark absent)")


@dataclass(frozen=True)
class Finding:
    """One typed, evidence-carrying integrity finding."""
    kind: str
    subject: str
    baseline_name: str
    expected: str | None = None
    observed: str | None = None
    detail: str = ""

    def __post_init__(self):
        if self.kind not in FINDING_KINDS:
            raise MalformedSnapshotError(
                f"finding: unknown kind {self.kind!r}")

    def as_dict(self):
        return {
            "kind": self.kind, "subject": self.subject,
            "baseline_name": self.baseline_name,
            "expected": self.expected, "observed": self.observed,
            "detail": self.detail,
        }


@dataclass(frozen=True)
class ThorReport:
    """The detector verdict over one snapshot pair."""
    process_baseline_name: str
    manifest_name: str
    findings: tuple = ()
    processes_seen: int = 0
    files_seen: int = 0
    schema: str = THOR_SCHEMA

    @property
    def clean(self):
        return not self.findings

    def by_kind(self, kind):
        return tuple(f for f in self.findings if f.kind == kind)

    def counts(self):
        out = {}
        for f in self.findings:
            out[f.kind] = out.get(f.kind, 0) + 1
        return out

    def as_dict(self):
        return {
            "schema": self.schema,
            "process_baseline": self.process_baseline_name,
            "manifest": self.manifest_name,
            "clean": self.clean,
            "processes_seen": self.processes_seen,
            "files_seen": self.files_seen,
            "counts": self.counts(),
            "findings": [f.as_dict() for f in self.findings],
        }

    def evidence_fields(self, recorded_at, snapshot_digest):
        """LIF-0004-shaped evidence overlap (content_digest,
        recorded_at, source component) for this report."""
        return {
            "content_digest": snapshot_digest,
            "recorded_at": recorded_at,
            "source": {"component": "thor", "schema": self.schema},
            "artifact_refs": [],
        }


def snapshot_digest(processes, files):
    """Canonical digest of a snapshot pair, for evidence records."""
    payload = {
        "processes": [
            {"pid": p.pid, "ppid": p.ppid, "comm": p.comm,
             "exe": p.exe, "user": p.user,
             "cmdline": list(p.cmdline)}
            for p in sorted(processes, key=lambda p: p.pid)],
        "files": [
            {"path": f.path, "hash": f.observed_sha256,
             "package": f.package, "present": f.present}
            for f in sorted(files, key=lambda f: f.path)],
    }
    blob = json.dumps(payload, sort_keys=True,
                      separators=(",", ":")).encode("utf-8")
    return "sha256:" + hashlib.sha256(blob).hexdigest()


def _process_matches(proc, expected):
    if proc.comm != expected.comm:
        return False
    if expected.exe is not None and proc.exe != expected.exe:
        return False
    return True


def detect(processes, files, process_baseline, manifest):
    """Run the read-only detector over fixture snapshots.

    Pure function: no I/O, no process control, no mutation; the same
    inputs always produce the same report.
    """
    if not isinstance(process_baseline, ProcessBaseline):
        raise MalformedSnapshotError(
            "detect: process_baseline must be a ProcessBaseline")
    if not isinstance(manifest, PackageManifest):
        raise MalformedSnapshotError(
            "detect: manifest must be a PackageManifest")
    processes = tuple(processes or ())
    files = tuple(files or ())
    seen_pids = set()
    for p in processes:
        if p.pid in seen_pids:
            raise DuplicateEntryError(
                f"snapshot: duplicate pid {p.pid}")
        seen_pids.add(p.pid)
    seen_paths = set()
    for f in files:
        if f.path in seen_paths:
            raise DuplicateEntryError(
                f"snapshot: duplicate file path {f.path!r}")
        seen_paths.add(f.path)

    findings = []

    manifest_by_path = {f.path: f for f in manifest.files}
    observed_by_path = {f.path: f for f in files if f.present}
    for entry in manifest.files:
        obs = observed_by_path.get(entry.path)
        if obs is None:
            findings.append(Finding(
                kind=KIND_MISSING_FILE, subject=entry.path,
                baseline_name=manifest.name,
                expected=entry.expected_sha256, observed=None,
                detail=f"manifest entry for package "
                       f"{entry.package or 'unknown'} is absent "
                       f"from the snapshot"))
        elif obs.observed_sha256 != entry.expected_sha256:
            findings.append(Finding(
                kind=KIND_HASH_MISMATCH, subject=entry.path,
                baseline_name=manifest.name,
                expected=entry.expected_sha256,
                observed=obs.observed_sha256,
                detail=f"recorded hash differs from manifest "
                       f"(package {entry.package or 'unknown'})"))
    for obs in files:
        if obs.present and obs.package is not None \
                and obs.path not in manifest_by_path:
            findings.append(Finding(
                kind=KIND_UNEXPECTED_FILE, subject=obs.path,
                baseline_name=manifest.name, expected=None,
                observed=obs.observed_sha256,
                detail=f"snapshot file claims package {obs.package} "
                       f"but is not in the manifest"))

    for proc in processes:
        if not any(_process_matches(proc, e)
                   for e in process_baseline.processes):
            findings.append(Finding(
                kind=KIND_UNKNOWN_PROCESS,
                subject=f"{proc.comm} (pid {proc.pid})",
                baseline_name=process_baseline.name, expected=None,
                observed=proc.exe or proc.comm,
                detail="process matches no baseline allowlist entry"))
    for exp in process_baseline.processes:
        if exp.required and not any(
                _process_matches(p, exp) for p in processes):
            findings.append(Finding(
                kind=KIND_MISSING_PROCESS, subject=exp.comm,
                baseline_name=process_baseline.name,
                expected=exp.exe or exp.comm, observed=None,
                detail="baseline-required process is absent from "
                       "the snapshot"))

    findings.sort(key=lambda f: (f.kind, f.subject))
    return ThorReport(
        process_baseline_name=process_baseline.name,
        manifest_name=manifest.name,
        findings=tuple(findings),
        processes_seen=len(processes),
        files_seen=len([f for f in files if f.present]),
    )


# --- JSON-shaped fixture loaders (recorded snapshots only) ---

def process_baseline_from_dict(data):
    if not isinstance(data, dict) or not data.get("name"):
        raise MalformedSnapshotError(
            "process baseline dict: a non-empty 'name' is required")
    return ProcessBaseline(
        name=data["name"],
        processes=tuple(
            ExpectedProcess(
                comm=p.get("comm"), exe=p.get("exe"),
                required=bool(p.get("required", False)))
            for p in data.get("processes", [])))


def manifest_from_dict(data):
    if not isinstance(data, dict) or not data.get("name"):
        raise MalformedSnapshotError(
            "manifest dict: a non-empty 'name' is required")
    return PackageManifest(
        name=data["name"],
        files=tuple(
            ManifestFile(
                path=f.get("path"),
                expected_sha256=f.get("sha256", f.get("expected_sha256")),
                package=f.get("package"))
            for f in data.get("files", [])))


def snapshot_from_dicts(process_rows, file_rows):
    processes = tuple(
        ProcessObservation(
            pid=r.get("pid"), comm=r.get("comm"), ppid=r.get("ppid"),
            exe=r.get("exe"), user=r.get("user"),
            cmdline=tuple(r.get("cmdline", ())))
        for r in (process_rows or []))
    files = tuple(
        ObservedFile(
            path=r.get("path"),
            observed_sha256=r.get("sha256", r.get("observed_sha256")),
            package=r.get("package"),
            present=bool(r.get("present", True)))
        for r in (file_rows or []))
    return processes, files


def detect_from_dicts(process_rows, file_rows, baseline_data,
                      manifest_data):
    processes, files = snapshot_from_dicts(process_rows, file_rows)
    return detect(processes, files,
                  process_baseline_from_dict(baseline_data),
                  manifest_from_dict(manifest_data))
