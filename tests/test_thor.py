"""LIF-0801 tests: Thor read-only process/package integrity detector.

Fixture snapshots only. The detector must flag a tampered manifest
entry, must NOT flag a clean snapshot (negative/positive controls),
and must be provably read-only: a source scan pins its import
allowlist and bans every mutation/signalling token.
"""
import copy
import hashlib
import inspect
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "src"))

import lifthrasir.thor as thor  # noqa: E402
from lifthrasir.thor import (  # noqa: E402
    KIND_HASH_MISMATCH,
    KIND_MISSING_FILE,
    KIND_MISSING_PROCESS,
    KIND_UNEXPECTED_FILE,
    KIND_UNKNOWN_PROCESS,
    DuplicateEntryError,
    MalformedSnapshotError,
    ManifestFile,
    ObservedFile,
    PackageManifest,
    ProcessBaseline,
    ProcessObservation,
    ExpectedProcess,
    detect,
    detect_from_dicts,
    sha256_of_bytes,
    snapshot_digest,
)

H_CLEAN = sha256_of_bytes(b"clean file contents")
H_TAMPERED = sha256_of_bytes(b"tampered file contents")
H_OTHER = sha256_of_bytes(b"other file contents")

BASELINE = ProcessBaseline(name="lab-baseline", processes=(
    ExpectedProcess(comm="init", exe="/sbin/init", required=True),
    ExpectedProcess(comm="sshd"),
    ExpectedProcess(comm="thor-agent"),
))
MANIFEST = PackageManifest(name="lab-manifest", files=(
    ManifestFile(path="/usr/bin/tool", expected_sha256=H_CLEAN,
                 package="toolpkg"),
    ManifestFile(path="/etc/tool.conf", expected_sha256=H_OTHER,
                 package="toolpkg"),
))
CLEAN_PROCS = (
    ProcessObservation(pid=1, comm="init", exe="/sbin/init"),
    ProcessObservation(pid=42, comm="sshd", exe="/usr/sbin/sshd"),
)
CLEAN_FILES = (
    ObservedFile(path="/usr/bin/tool", observed_sha256=H_CLEAN,
                 package="toolpkg"),
    ObservedFile(path="/etc/tool.conf", observed_sha256=H_OTHER,
                 package="toolpkg"),
)


def test_clean_snapshot_is_clean():
    report = detect(CLEAN_PROCS, CLEAN_FILES, BASELINE, MANIFEST)
    assert report.clean is True
    assert report.findings == ()
    assert report.processes_seen == 2 and report.files_seen == 2


def test_tampered_manifest_entry_must_flag():
    files = (ObservedFile(path="/usr/bin/tool",
                          observed_sha256=H_TAMPERED,
                          package="toolpkg"),) + CLEAN_FILES[1:]
    report = detect(CLEAN_PROCS, files, BASELINE, MANIFEST)
    assert report.clean is False
    hits = report.by_kind(KIND_HASH_MISMATCH)
    assert len(hits) == 1
    assert hits[0].subject == "/usr/bin/tool"
    assert hits[0].expected == H_CLEAN
    assert hits[0].observed == H_TAMPERED
    assert hits[0].baseline_name == "lab-manifest"


def test_missing_manifest_entry_flags():
    report = detect(CLEAN_PROCS, CLEAN_FILES[1:], BASELINE, MANIFEST)
    hits = report.by_kind(KIND_MISSING_FILE)
    assert len(hits) == 1 and hits[0].subject == "/usr/bin/tool"
    marked_absent = (ObservedFile(path="/usr/bin/tool",
                                  present=False),) + CLEAN_FILES[1:]
    report2 = detect(CLEAN_PROCS, marked_absent, BASELINE, MANIFEST)
    assert len(report2.by_kind(KIND_MISSING_FILE)) == 1


def test_unknown_process_flags():
    procs = CLEAN_PROCS + (
        ProcessObservation(pid=99, comm="cryptominer",
                           exe="/tmp/miner"),)
    report = detect(procs, CLEAN_FILES, BASELINE, MANIFEST)
    hits = report.by_kind(KIND_UNKNOWN_PROCESS)
    assert len(hits) == 1
    assert "cryptominer" in hits[0].subject
    assert hits[0].baseline_name == "lab-baseline"


def test_exe_mismatch_against_baseline_flags():
    procs = (ProcessObservation(pid=1, comm="init",
                                exe="/tmp/fake-init"),) + CLEAN_PROCS[1:]
    report = detect(procs, CLEAN_FILES, BASELINE, MANIFEST)
    assert len(report.by_kind(KIND_UNKNOWN_PROCESS)) == 1


def test_missing_required_process_flags_optional_does_not():
    procs = (CLEAN_PROCS[1],)  # init (required) gone, thor-agent
    # (optional) was never present in the clean snapshot either.
    report = detect(procs, CLEAN_FILES, BASELINE, MANIFEST)
    hits = report.by_kind(KIND_MISSING_PROCESS)
    assert len(hits) == 1 and hits[0].subject == "init"


def test_unexpected_packaged_file_flags_unowned_does_not():
    files = CLEAN_FILES + (
        ObservedFile(path="/usr/bin/backdoor",
                     observed_sha256=H_OTHER, package="toolpkg"),
        ObservedFile(path="/home/user/notes.txt",
                     observed_sha256=H_OTHER),
    )
    report = detect(CLEAN_PROCS, files, BASELINE, MANIFEST)
    hits = report.by_kind(KIND_UNEXPECTED_FILE)
    assert len(hits) == 1 and hits[0].subject == "/usr/bin/backdoor"


def test_malformed_hash_refused_by_name():
    with pytest.raises(MalformedSnapshotError):
        ManifestFile(path="/x", expected_sha256="not-a-hash")
    with pytest.raises(MalformedSnapshotError):
        ObservedFile(path="/x", observed_sha256="zz" * 32)


def test_present_file_without_hash_refused():
    with pytest.raises(MalformedSnapshotError):
        ObservedFile(path="/x")


def test_duplicate_entries_refused():
    with pytest.raises(DuplicateEntryError):
        PackageManifest(name="m", files=(
            ManifestFile(path="/x", expected_sha256=H_CLEAN),
            ManifestFile(path="/x", expected_sha256=H_OTHER)))
    with pytest.raises(DuplicateEntryError):
        detect(CLEAN_PROCS + CLEAN_PROCS[:1], CLEAN_FILES,
               BASELINE, MANIFEST)


def test_empty_baseline_name_refused():
    with pytest.raises(MalformedSnapshotError):
        ProcessBaseline(name="  ")
    with pytest.raises(MalformedSnapshotError):
        PackageManifest(name="")


def test_detect_is_deterministic_and_sorted():
    procs = CLEAN_PROCS + (
        ProcessObservation(pid=99, comm="cryptominer"),)
    files = (ObservedFile(path="/usr/bin/tool",
                          observed_sha256=H_TAMPERED,
                          package="toolpkg"),)
    r1 = detect(procs, files, BASELINE, MANIFEST)
    r2 = detect(procs, files, BASELINE, MANIFEST)
    assert r1 == r2
    keys = [(f.kind, f.subject) for f in r1.findings]
    assert keys == sorted(keys)


def test_inputs_are_never_mutated():
    procs = [ProcessObservation(pid=1, comm="init", exe="/sbin/init")]
    files = [ObservedFile(path="/usr/bin/tool",
                          observed_sha256=H_TAMPERED,
                          package="toolpkg")]
    before = copy.deepcopy((procs, files))
    detect(procs, files, BASELINE, MANIFEST)
    assert (procs, files) == before


def test_report_evidence_fields_and_digest():
    report = detect(CLEAN_PROCS, CLEAN_FILES, BASELINE, MANIFEST)
    digest = snapshot_digest(CLEAN_PROCS, CLEAN_FILES)
    assert digest.startswith("sha256:")
    ev = report.evidence_fields("2026-11-12T00:00:00+00:00", digest)
    assert ev["content_digest"] == digest
    assert ev["source"]["component"] == "thor"
    d = report.as_dict()
    assert d["clean"] is True and d["manifest"] == "lab-manifest"
    # Digest is order-insensitive for processes/files.
    assert snapshot_digest(tuple(reversed(CLEAN_PROCS)),
                           tuple(reversed(CLEAN_FILES))) == digest


def test_dict_loader_round_trip():
    report = detect_from_dicts(
        [{"pid": 1, "comm": "init", "exe": "/sbin/init"},
         {"pid": 7, "comm": "evil"}],
        [{"path": "/usr/bin/tool", "sha256": H_CLEAN,
          "package": "toolpkg"}],
        {"name": "b", "processes": [
            {"comm": "init", "exe": "/sbin/init", "required": True}]},
        {"name": "m", "files": [
            {"path": "/usr/bin/tool", "sha256": H_CLEAN,
             "package": "toolpkg"},
            {"path": "/etc/tool.conf", "sha256": H_OTHER,
             "package": "toolpkg"}]},
    )
    kinds = report.counts()
    assert kinds.get(KIND_UNKNOWN_PROCESS) == 1
    assert kinds.get(KIND_MISSING_FILE) == 1
    assert KIND_HASH_MISMATCH not in kinds


def test_sha256_of_bytes_matches_hashlib():
    raw = b"abc"
    assert sha256_of_bytes(raw) == \
        "sha256:" + hashlib.sha256(raw).hexdigest()
    with pytest.raises(MalformedSnapshotError):
        sha256_of_bytes("not bytes")


def test_module_is_provably_read_only():
    src = inspect.getsource(thor)
    # Import allowlist: stdlib data/hash helpers only.
    imported = set()
    for line in src.splitlines():
        line = line.strip()
        if line.startswith("import "):
            imported.add(line.split()[1].split(".")[0])
        elif line.startswith("from ") and " import " in line:
            imported.add(line.split()[1].split(".")[0])
    assert imported <= {"__future__", "hashlib", "json", "re",
                        "dataclasses"}
    # No mutation / signalling / execution / IO tokens at all.
    for token in ("subprocess", "signal", "socket", "os.",
                  "open(", "kill", "system(", "popen", "exec(",
                  "eval(", "write_text", "write_bytes", "unlink",
                  "remove(", "rename(", "chmod", "chown"):
        assert token not in src, token


def test_no_top_level_name_collisions_with_package():
    import lifthrasir
    exported = set(dir(thor)) - set(dir(object))
    collisions = sorted(
        n for n in exported
        if not n.startswith("_") and hasattr(lifthrasir, n)
        and getattr(lifthrasir, n) is not getattr(thor, n, None)
        and n not in ("annotations",))
    # Names the seat may add must not clash with existing top-level
    # exports; module internals (hashlib etc.) are not exports.
    desired = [
        "THOR_SCHEMA", "THOR_VERSION", "FINDING_KINDS",
        "KIND_HASH_MISMATCH", "KIND_MISSING_FILE",
        "KIND_MISSING_PROCESS", "KIND_UNEXPECTED_FILE",
        "KIND_UNKNOWN_PROCESS", "ThorError",
        "MalformedSnapshotError", "DuplicateEntryError",
        "ProcessObservation", "ExpectedProcess", "ProcessBaseline",
        "ManifestFile", "PackageManifest", "ObservedFile",
        "ThorReport", "detect", "detect_from_dicts",
        "manifest_from_dict", "process_baseline_from_dict",
        "sha256_of_bytes", "snapshot_digest", "snapshot_from_dicts",
    ]
    bad = [n for n in desired if n in collisions]
    assert bad == [], bad
    # The one known collider: thor.Finding vs the contextguard
    # Finding already exported at top level (LIF-0306). By the
    # confinement precedent it stays at the submodule only.
    assert collisions == ["Finding"], collisions
