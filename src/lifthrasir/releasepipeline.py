# SPDX-License-Identifier: GPL-2.0-only
"""Package generation and signed release pipeline (LIF-1201).

Phase P12, queue #56.  Banking gate: P0-P11 (LIF-1102 and LIF-1103
were still building when this slice was built, so this slice BUILDS
AHEAD of its gate; banking waits for the keeper).  Sources read
before designing: the LIF-1201 backlog entry (one line: "Package
generation and signed release pipeline"), master roadmap sections
0 and 5, roadmap/05 (quality, release and governance), roadmap/08
(test matrix and release gates G0-G12), docs/LICENSING.md
(LIF-0005: GPL-2.0-only, per-component SPDX review, artwork needs
its own license note before redistribution) and the LIF-1101
distroprobes honesty discipline this module follows.

What this slice ships -- fixture / record level ONLY:

* A deterministic package-plan layer.  Given RECORDED source files
  (relative path, recorded sha256, size, SPDX identifier and
  reviewed flag), it builds a package plan: files sorted by path,
  a recorded build epoch (never wall time), a canonical manifest
  and its sha256 digest.  Building twice, or from a differently
  ordered recording, yields the identical digest -- the
  reproducibility differential.  No archive is written, no package
  manager is invoked, and no real package is produced.
* A release-gate layer.  A release candidate record is evaluated
  against the named gates (evidence pack per section 5, full
  suite green record, licensing review, release gates G9/G10
  status, human review).  The only passing verdict is
  ``fixture-ready-for-human-review``; there is deliberately no
  ``released`` or ``published`` verdict in this module.
* A SIMULATED signing layer.  Signing uses fixture keys only: a
  key id must start ``fixture-``, its material is a recorded
  fixture string, and the signature is an HMAC-SHA256 over the
  manifest digest, serialised with the literal label
  ``SIMULATED-FIXTURE-SIGNATURE``.  This is NOT cryptographic
  release signing, proves nothing about any real key, and must
  never be presented as a signed release.  Real key ids, key
  file paths and any publish / upload / release action are
  refused by name.

Hard bounds honoured: no real release packages are generated for
publication, nothing is signed with a real key, nothing is
published or uploaded anywhere, no Docker, no host state is read
or changed, README.md and __init__.py are untouched (the seat
unions exports at banking; the desired list is in the team
CAMPAIGN_STATE.md).  Evidence status: reproducer + lab-verified
at fixture scope on this platform only -- a fixture pipeline is
not a release.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import re
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional, Tuple

RELEASE_SCHEMA = "lifthrasir.release-pipeline.v0.1"
RELEASE_SCHEMA_VERSION = "0.1"
MANIFEST_SCHEMA = "lifthrasir.package-manifest.v0.1"
SIGNATURE_LABEL = "SIMULATED-FIXTURE-SIGNATURE"
SIGNATURE_ALGORITHM = "fixture-hmac-sha256-simulation"
PROJECT_LICENSE_SPDX = "GPL-2.0-only"
PACKAGE_FORMATS = ("deb-plan", "rpm-plan", "tarball-plan")
ARTWORK_KINDS = ("artwork", "image")
FILE_KINDS = ("code", "documentation", "data", "artwork", "image", "config")
GATE_NAMES = (
    "evidence_pack_complete", "full_suite_green",
    "licensing_reviewed", "negative_control_recorded",
    "cross_distro_gate_recorded", "security_review_recorded",
    "human_review_recorded",
)
VERDICT_BLOCKED = "blocked"
VERDICT_FIXTURE_READY = "fixture-ready-for-human-review"
VERDICTS = (VERDICT_BLOCKED, VERDICT_FIXTURE_READY)
MAX_FILES = 512
MAX_PATH_CHARS = 512
MAX_NAME_CHARS = 128
_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9+.-]*$")
_VERSION_RE = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+([.-][a-z0-9.]+)?$")
_SHA_RE = re.compile(r"^[0-9a-f]{64}$")
_COMMIT_RE = re.compile(r"^[0-9a-f]{7,64}$")
_FIXTURE_KEY_RE = re.compile(r"^fixture-[a-z0-9][a-z0-9-]*$")


class ReleasePipelineError(Exception):
    """Base class for release-pipeline refusals."""


class MalformedRecordError(ReleasePipelineError):
    """A recorded file, key or candidate record is malformed."""


class UnreviewedLicenseError(MalformedRecordError):
    """A file lacks a reviewed SPDX identifier (LIF-0005)."""


class RealKeyRefusedError(ReleasePipelineError):
    """A non-fixture key was offered; real signing is out of scope."""


class PublishRefusedError(ReleasePipelineError):
    """Any publish, upload or release action is refused by name."""


class SupportClaimError(MalformedRecordError):
    """A record claims a released / published state not earned here."""


@dataclass(frozen=True)
class RecordedFile:
    path: str
    sha256: str
    size: int
    spdx: str
    spdx_reviewed: bool
    kind: str = "code"
    license_note: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {"path": self.path, "sha256": self.sha256,
                "size": self.size, "spdx": self.spdx,
                "spdx_reviewed": self.spdx_reviewed,
                "kind": self.kind, "license_note": self.license_note}


def _require_str(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise MalformedRecordError(f"{field} must be a non-empty string")
    return value


def validate_recorded_file(raw: Any) -> RecordedFile:
    if not isinstance(raw, dict):
        raise MalformedRecordError("recorded file must be an object")
    path = _require_str(raw.get("path"), "path")
    if len(path) > MAX_PATH_CHARS or path.startswith("/") or "\\" in path:
        raise MalformedRecordError(f"path {path!r} is not a safe relative path")
    parts = path.split("/")
    if any(p in ("", ".", "..") for p in parts):
        raise MalformedRecordError(f"path {path!r} contains an unsafe component")
    sha = _require_str(raw.get("sha256"), "sha256")
    if not _SHA_RE.match(sha):
        raise MalformedRecordError(f"sha256 for {path!r} is not 64 lowercase hex")
    size = raw.get("size")
    if not isinstance(size, int) or isinstance(size, bool) or size < 0:
        raise MalformedRecordError(f"size for {path!r} must be a non-negative int")
    spdx = _require_str(raw.get("spdx"), "spdx")
    reviewed = raw.get("spdx_reviewed")
    if reviewed is not True:
        raise UnreviewedLicenseError(
            f"{path!r} has no reviewed SPDX identifier (LIF-0005 rule); "
            f"an assumed identifier is not a reviewed identifier")
    kind = raw.get("kind", "code")
    if kind not in FILE_KINDS:
        raise MalformedRecordError(f"kind {kind!r} for {path!r} is not known")
    note = raw.get("license_note", "")
    if not isinstance(note, str):
        raise MalformedRecordError(f"license_note for {path!r} must be a string")
    if kind in ARTWORK_KINDS and not note.strip():
        raise UnreviewedLicenseError(
            f"artwork {path!r} has no license / permission note; "
            f"LIF-0005 treats artwork licensing as unverified until noted")
    return RecordedFile(path=path, sha256=sha, size=size, spdx=spdx,
                        spdx_reviewed=True, kind=kind, license_note=note)


def recorded_file_from_dict(raw: Any) -> RecordedFile:
    return validate_recorded_file(raw)


@dataclass(frozen=True)
class FixtureKey:
    key_id: str
    material: str

    def to_dict(self) -> Dict[str, Any]:
        return {"key_id": self.key_id, "algorithm": SIGNATURE_ALGORITHM,
                "label": SIGNATURE_LABEL, "simulated": True}


def validate_fixture_key(raw: Any) -> FixtureKey:
    if not isinstance(raw, dict):
        raise MalformedRecordError("fixture key must be an object")
    key_id = raw.get("key_id")
    if isinstance(key_id, str) and ("/" in key_id or key_id.endswith((".pem", ".key", ".asc", ".gpg"))):
        raise RealKeyRefusedError(
            f"key {key_id!r} looks like a real key file path; "
            f"real signing is out of scope for LIF-1201")
    if not isinstance(key_id, str) or not _FIXTURE_KEY_RE.match(key_id):
        raise RealKeyRefusedError(
            f"key id {key_id!r} is not a fixture key (must match "
            f"fixture-<name>); non-fixture keys are refused by name")
    material = raw.get("material")
    if not isinstance(material, str) or len(material) < 8:
        raise MalformedRecordError("fixture key material must be a recorded string of at least 8 chars")
    if raw.get("simulated") is not True:
        raise MalformedRecordError("fixture key record must carry simulated: true")
    return FixtureKey(key_id=key_id, material=material)


@dataclass(frozen=True)
class PackagePlan:
    name: str
    version: str
    fmt: str
    source_commit: str
    build_epoch: int
    license_spdx: str
    files: Tuple[RecordedFile, ...]

    def manifest(self) -> Dict[str, Any]:
        return {"schema": MANIFEST_SCHEMA, "name": self.name,
                "version": self.version, "format": self.fmt,
                "source_commit": self.source_commit,
                "build_epoch": self.build_epoch,
                "license_spdx": self.license_spdx,
                "simulated": True, "release_state": "not-a-release",
                "files": [f.to_dict() for f in self.files],
                "total_size": sum(f.size for f in self.files),
                "file_count": len(self.files)}

    def manifest_text(self) -> str:
        return json.dumps(self.manifest(), sort_keys=True,
                          separators=(",", ":"), ensure_ascii=True)

    def digest(self) -> str:
        return hashlib.sha256(self.manifest_text().encode("utf-8")).hexdigest()

    def to_dict(self) -> Dict[str, Any]:
        out = self.manifest()
        out["digest"] = "sha256:" + self.digest()
        return out


def build_package_plan(raw: Any) -> PackagePlan:
    if not isinstance(raw, dict):
        raise MalformedRecordError("package record must be an object")
    action = raw.get("action", "plan")
    if action != "plan":
        raise PublishRefusedError(
            f"action {action!r} is refused: this pipeline plans and "
            f"records only; it never publishes, uploads or releases")
    if raw.get("release_state") not in (None, "not-a-release"):
        raise SupportClaimError(
            f"release_state {raw.get('release_state')!r} claims a state "
            f"this fixture pipeline cannot grant")
    name = _require_str(raw.get("name"), "name")
    if len(name) > MAX_NAME_CHARS or not _NAME_RE.match(name):
        raise MalformedRecordError(f"package name {name!r} is malformed")
    version = _require_str(raw.get("version"), "version")
    if not _VERSION_RE.match(version):
        raise MalformedRecordError(f"version {version!r} is not MAJOR.MINOR.PATCH")
    fmt = raw.get("format")
    if fmt not in PACKAGE_FORMATS:
        raise MalformedRecordError(f"format {fmt!r} not in {PACKAGE_FORMATS} (plan formats only)")
    commit = _require_str(raw.get("source_commit"), "source_commit")
    if not _COMMIT_RE.match(commit):
        raise MalformedRecordError(f"source_commit {commit!r} is not a hex commit id")
    epoch = raw.get("build_epoch")
    if not isinstance(epoch, int) or isinstance(epoch, bool) or epoch < 0:
        raise MalformedRecordError("build_epoch must be a recorded non-negative int (never wall time)")
    lic = raw.get("license_spdx", PROJECT_LICENSE_SPDX)
    if lic != PROJECT_LICENSE_SPDX:
        raise MalformedRecordError(f"license_spdx {lic!r} differs from project {PROJECT_LICENSE_SPDX}")
    raw_files = raw.get("files")
    if not isinstance(raw_files, list) or not raw_files or len(raw_files) > MAX_FILES:
        raise MalformedRecordError(f"files must be a list of 1..{MAX_FILES} recorded files")
    files = [validate_recorded_file(f) for f in raw_files]
    seen = set()
    for f in files:
        if f.path in seen:
            raise MalformedRecordError(f"duplicate recorded path {f.path!r}")
        seen.add(f.path)
    files.sort(key=lambda f: f.path)
    return PackagePlan(name=name, version=version, fmt=fmt,
                       source_commit=commit, build_epoch=epoch,
                       license_spdx=lic, files=tuple(files))


@dataclass(frozen=True)
class SimulatedSignature:
    key_id: str
    manifest_digest: str
    signature: str

    def to_dict(self) -> Dict[str, Any]:
        return {"label": SIGNATURE_LABEL, "algorithm": SIGNATURE_ALGORITHM,
                "simulated": True, "key_id": self.key_id,
                "manifest_digest": "sha256:" + self.manifest_digest,
                "signature": self.signature,
                "warning": "Fixture simulation only. Not a real "
                           "signature, not a signed release."}


def simulate_sign(plan: PackagePlan, key: FixtureKey) -> SimulatedSignature:
    digest = plan.digest()
    sig = hmac.new(key.material.encode("utf-8"),
                   digest.encode("utf-8"), hashlib.sha256).hexdigest()
    return SimulatedSignature(key_id=key.key_id, manifest_digest=digest, signature=sig)


def verify_simulated_signature(plan: PackagePlan, key: FixtureKey,
                               signature: Any) -> bool:
    if not isinstance(signature, dict):
        return False
    if signature.get("label") != SIGNATURE_LABEL or signature.get("simulated") is not True:
        return False
    if signature.get("key_id") != key.key_id:
        return False
    expected = simulate_sign(plan, key)
    if signature.get("manifest_digest") != "sha256:" + expected.manifest_digest:
        return False
    given = signature.get("signature")
    return isinstance(given, str) and hmac.compare_digest(given, expected.signature)


@dataclass(frozen=True)
class GateResult:
    gate: str
    passed: bool
    detail: str

    def to_dict(self) -> Dict[str, Any]:
        return {"gate": self.gate, "passed": self.passed, "detail": self.detail}


@dataclass(frozen=True)
class ReleaseReport:
    plan_digest: str
    gates: Tuple[GateResult, ...]
    verdict: str
    signature: Optional[Dict[str, Any]]

    def to_dict(self) -> Dict[str, Any]:
        return {"schema": RELEASE_SCHEMA, "simulated": True,
                "release_state": "not-a-release",
                "plan_digest": "sha256:" + self.plan_digest,
                "gates": [g.to_dict() for g in self.gates],
                "verdict": self.verdict, "signature": self.signature}


def _gate(gates: List[GateResult], raw: Dict[str, Any], name: str,
          ok: bool, detail: str) -> None:
    gates.append(GateResult(gate=name, passed=bool(ok), detail=detail))


def evaluate_release_candidate(raw: Any) -> ReleaseReport:
    if not isinstance(raw, dict):
        raise MalformedRecordError("release candidate must be an object")
    plan = build_package_plan(raw.get("package"))
    key = validate_fixture_key(raw.get("fixture_key"))
    ev = raw.get("evidence")
    if not isinstance(ev, dict):
        raise MalformedRecordError("evidence must be an object (section 5 pack)")
    gates: List[GateResult] = []
    pack_keys = ("reproducer", "differential", "negative_control",
                 "tool_versions", "artifact_hashes", "limitations", "undo")
    missing = [k for k in pack_keys if not str(ev.get(k, "")).strip()]
    _gate(gates, raw, "evidence_pack_complete", not missing,
          "all section 5 items recorded" if not missing else f"missing: {missing}")
    suite = ev.get("suite") if isinstance(ev.get("suite"), dict) else {}
    _gate(gates, raw, "full_suite_green",
          suite.get("failed") == 0 and isinstance(suite.get("passed"), int) and suite.get("passed", 0) > 0,
          f"recorded suite passed={suite.get('passed')} failed={suite.get('failed')}")
    _gate(gates, raw, "licensing_reviewed", ev.get("licensing_reviewed") is True,
          "per-component SPDX review recorded (LIF-0005)" if ev.get("licensing_reviewed") is True else "licensing review not recorded")
    _gate(gates, raw, "negative_control_recorded", bool(str(ev.get("negative_control", "")).strip()),
          "negative control recorded" if str(ev.get("negative_control", "")).strip() else "no negative control recorded")
    _gate(gates, raw, "cross_distro_gate_recorded", ev.get("gate_g9") in ("pass", "blocked", "not-run"),
          f"roadmap/08 G9 recorded as {ev.get('gate_g9')!r} (a recorded blocked/not-run is honest; only pass counts toward a real release, which this verdict never grants)")
    _gate(gates, raw, "security_review_recorded", ev.get("gate_g10") in ("pass", "blocked", "not-run"),
          f"roadmap/08 G10 recorded as {ev.get('gate_g10')!r}")
    _gate(gates, raw, "human_review_recorded", ev.get("human_review") in ("pending", "recorded"),
          f"human review state recorded as {ev.get('human_review')!r}; pending is honest and blocks any real release")
    verdict = VERDICT_FIXTURE_READY if all(g.passed for g in gates) else VERDICT_BLOCKED
    sig = simulate_sign(plan, key).to_dict() if verdict == VERDICT_FIXTURE_READY else None
    return ReleaseReport(plan_digest=plan.digest(), gates=tuple(gates),
                         verdict=verdict, signature=sig)


def build_evidence_record(report: ReleaseReport) -> Dict[str, Any]:
    return {"schema": RELEASE_SCHEMA, "status": report.verdict,
            "rung": "lab-verified at fixture scope only",
            "release_state": "not-a-release", "simulated_signing": True,
            "plan_digest": "sha256:" + report.plan_digest}
