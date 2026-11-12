# SPDX-License-Identifier: GPL-2.0-only
"""LIF-0902 KUnit/kselftest integration, machine-readable results.

Scope: strict TAP parsing of recorded KUnit (TAP 14 / KTAP 1) and
kselftest (TAP 13) output, normalization into validated
machine-readable records, LIF-0004 v0.1 evidence rendering, and
the honesty gates: truncated, plan-short, totals-mismatched,
misnumbered, bailed-out, empty or garbage streams are reported
malformed/error -- never read as a pass. Fixture output only:
no kernel is built or booted and no test binary runs.
"""
import ast
import copy
import json
import sys
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator, FormatChecker

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from lifthrasir import kernellab
from lifthrasir.kernellab import (
    MalformedRunError,
    build_evidence_record,
    detect_framework,
    ingest_file,
    ingest_text,
    parse_kselftest_tap,
    parse_kunit_tap,
    parse_tap,
    report_as_dict,
    summarize_runs,
    validate_report_dict,
)

FIXTURES = REPO / "tests" / "fixtures" / "lif0902"
EVIDENCE_SCHEMA = REPO / "docs" / "protocols" / "schemas" / "v0.1" / "evidence.schema.json"

DESIRED_EXPORTS = (
    "KERNELTEST_SCHEMA", "KERNELTEST_SCHEMA_VERSION", "RUN_VERSION",
    "FRAMEWORKS", "MAX_INPUT_CHARS", "MAX_CASES", "KernelTestError",
    "MalformedRunError", "ParseIssue", "TestCaseResult", "SuiteResult",
    "RunReport", "totals_for", "detect_framework", "parse_kunit_tap",
    "parse_kselftest_tap", "parse_tap", "report_as_dict", "run_digest",
    "validate_report_dict", "ingest_text", "ingest_file", "summarize_runs",
)
KNOWN_COLLIDERS = ("OUTCOMES", "VERDICTS", "build_evidence_record")


def _tap(name):
    return (FIXTURES / name).read_text(encoding="utf-8")


def _record(name, parser=parse_tap, **kw):
    return validate_report_dict(report_as_dict(parser(_tap(name), **kw)))


# ---------------------------------------------------------------- KUnit

def test_kunit_pass_fixture_all_pass():
    record = _record("kunit_pass.tap", parse_kunit_tap)
    assert record["verdict"] == "passed"
    assert record["complete"] is True
    assert record["framework"] == "kunit"
    assert record["header"] == "KTAP version 1"
    assert record["totals"]["passed"] == 5
    assert record["totals"]["total"] == 5
    assert record["parse_issues"] == []


def test_kunit_suites_and_case_paths():
    record = _record("kunit_pass.tap", parse_kunit_tap)
    paths = {tuple(c["suite_path"]) for c in record["cases"]}
    assert paths == {("kunit-example",), ("list-kunit-test",)}
    suites = {s["name"]: s["outcome"] for s in record["suites"]}
    assert suites == {"kunit-example": "passed", "list-kunit-test": "passed"}


def test_kunit_mixed_fixture_failure_skip_and_diagnostics():
    record = _record("kunit_mixed.tap", parse_kunit_tap)
    assert record["verdict"] == "failed"
    assert record["complete"] is True
    totals = record["totals"]
    assert (totals["passed"], totals["failed"], totals["skipped"]) == (3, 1, 1)
    failing = [c for c in record["cases"] if c["outcome"] == "failed"]
    assert failing[0]["name"] == "example_failing_test"
    assert any("EXPECTATION FAILED" in d for d in failing[0]["diagnostics"])
    skipped = [c for c in record["cases"] if c["outcome"] == "skipped"]
    assert skipped[0]["directive"] == "SKIP"
    assert skipped[0]["reason"] == "this test is skipped"


def test_kunit_truncated_fixture_is_malformed_never_pass():
    record = _record("kunit_truncated.tap", parse_kunit_tap)
    assert record["verdict"] == "malformed"
    assert record["complete"] is False
    assert record["verdict"] != "passed"
    messages = " ".join(i["message"] for i in record["parse_issues"])
    assert "truncated" in messages


def test_kunit_suite_totals_mismatch_is_malformed():
    text = (
        "KTAP version 1\n1..1\n"
        "    # Subtest: example\n    1..1\n    ok 1 - only_test\n"
        "    # example: pass:2 fail:0 skip:0 total:2\n"
        "ok 1 - example\n"
    )
    record = validate_report_dict(report_as_dict(parse_kunit_tap(text)))
    assert record["verdict"] == "malformed"
    assert any("declared" in i["message"] for i in record["parse_issues"])


def test_kunit_classic_tap14_header_accepted():
    record = _record("kunit_mixed.tap", parse_kunit_tap)
    assert record["header"] == "TAP version 14"


# ------------------------------------------------------------ kselftest

def test_kselftest_pass_fixture():
    record = _record("kselftest_pass.tap", parse_kselftest_tap)
    assert record["verdict"] == "passed"
    assert record["totals"]["total"] == 3
    assert record["declared_totals"]["passed"] == 3


def test_kselftest_mixed_fixture_exit_skip_timeout():
    record = _record("kselftest_mixed.tap", parse_kselftest_tap)
    assert record["verdict"] == "failed"
    totals = record["totals"]
    assert (totals["passed"], totals["failed"], totals["skipped"]) == (2, 2, 1)
    by_name = {c["name"]: c for c in record["cases"]}
    assert by_name["selftests: net: bind_test"]["reason"] == "exit=1"
    assert by_name["selftests: net: ipv6_test"]["outcome"] == "skipped"
    timeout = by_name["selftests: timers: alarmtimer-suspend"]
    assert timeout["outcome"] == "failed"
    assert timeout["directive"] == "TIMEOUT"


def test_kselftest_malformed_fixture_numbering_plan_totals():
    record = _record("kselftest_malformed.tap", parse_kselftest_tap)
    assert record["verdict"] == "malformed"
    messages = " ".join(i["message"] for i in record["parse_issues"])
    assert "out of sequence" in messages
    assert "Totals" in messages


def test_kselftest_xfail_is_not_a_failure():
    text = (
        "TAP version 13\n1..2\n"
        "not ok 1 selftests: x: known # TODO expected breakage\n"
        "ok 2 selftests: x: fine\n"
        "# Totals: pass:1 fail:0 xfail:1 xpass:0 skip:0 error:0\n"
    )
    record = validate_report_dict(report_as_dict(parse_kselftest_tap(text)))
    assert record["verdict"] == "passed"
    assert record["totals"]["xfailed"] == 1


def test_kselftest_all_skipped_verdict():
    text = (
        "TAP version 13\n1..2\n"
        "ok 1 selftests: x: a # SKIP no hardware\n"
        "ok 2 selftests: x: b # SKIP no hardware\n"
    )
    record = validate_report_dict(report_as_dict(parse_tap(text)))
    assert record["verdict"] == "skipped"
    assert record["complete"] is True


def test_skip_all_plan_is_skipped_not_malformed():
    record = validate_report_dict(report_as_dict(
        parse_tap("TAP version 13\n1..0 # SKIP no hardware\n")))
    assert record["verdict"] == "skipped"
    assert record["complete"] is True
    assert record["skip_all_reason"]


# ------------------------------------------------------- malformed core

@pytest.mark.parametrize("text", ["", "   \n\n", "hello world\nnot tap\n"])
def test_empty_and_garbage_streams_are_malformed(text):
    record = validate_report_dict(report_as_dict(parse_tap(text)))
    assert record["verdict"] == "malformed"
    assert record["complete"] is False


def test_header_only_stream_is_malformed():
    record = validate_report_dict(report_as_dict(parse_tap("KTAP version 1\n")))
    assert record["verdict"] == "malformed"


def test_bail_out_is_error_not_pass():
    text = ("TAP version 13\n1..2\nok 1 selftests: x: a\n"
            "Bail out! kernel panic in guest\n")
    record = validate_report_dict(report_as_dict(parse_tap(text)))
    assert record["verdict"] == "error"
    assert record["bail_out"] == "kernel panic in guest"
    assert record["complete"] is False


def test_plan_overrun_is_malformed():
    text = "TAP version 13\n1..1\nok 1 selftests: x: a\nok 2 selftests: x: b\n"
    record = validate_report_dict(report_as_dict(parse_tap(text)))
    assert record["verdict"] == "malformed"


def test_unrecognized_line_is_malformed():
    text = "TAP version 13\n1..1\nok 1 selftests: x: a\nGARBAGE LINE\n"
    record = validate_report_dict(report_as_dict(parse_tap(text)))
    assert record["verdict"] == "malformed"
    assert any("unrecognized" in i["message"] for i in record["parse_issues"])


def test_oversize_input_refused_as_malformed():
    text = "KTAP version 1\n" + ("x" * (kernellab.MAX_INPUT_CHARS + 1))
    record = validate_report_dict(report_as_dict(parse_kunit_tap(text)))
    assert record["verdict"] == "malformed"
    assert record["totals"]["total"] == 0


def test_preamble_lines_are_not_errors():
    text = ("[    0.000000] Linux version 6.12.117 (lab fixture)\n"
            "[    0.100000] kunit: mapped 2 suites\n" + _tap("kunit_pass.tap"))
    record = validate_report_dict(report_as_dict(parse_kunit_tap(text)))
    assert record["verdict"] == "passed"
    assert record["preamble_lines"] == 2


# ------------------------------------------------- records and evidence

def test_detect_framework():
    assert detect_framework(_tap("kunit_pass.tap")) == "kunit"
    assert detect_framework(_tap("kunit_mixed.tap")) == "kunit"
    assert detect_framework(_tap("kselftest_pass.tap")) == "kselftest"
    assert detect_framework("no tap here\n") is None


def test_parse_is_deterministic():
    first = ingest_text(_tap("kunit_mixed.tap"))
    second = ingest_text(_tap("kunit_mixed.tap"))
    assert first == second
    assert first["run_id"].startswith("kt-")


def test_auto_dispatch_matches_explicit_parsers():
    auto = ingest_text(_tap("kselftest_mixed.tap"))
    explicit = validate_report_dict(report_as_dict(
        parse_kselftest_tap(_tap("kselftest_mixed.tap"))))
    assert auto == explicit


def test_ingest_file_round_trip(tmp_path):
    target = tmp_path / "recorded.tap"
    target.write_text(_tap("kunit_pass.tap"), encoding="utf-8")
    record = ingest_file(target)
    assert record["verdict"] == "passed"
    assert record == ingest_text(_tap("kunit_pass.tap"))


def test_ingest_missing_file_refused():
    with pytest.raises(MalformedRunError):
        ingest_file(FIXTURES / "does-not-exist.tap")


def test_fixture_metadata_carried_and_validated():
    fixture = {"fixture_id": "linux-6.12.117-x86_64", "arch": "x86_64",
               "kernel_release": "6.12.117", "source_ref": None}
    record = ingest_text(_tap("kunit_pass.tap"), fixture=fixture)
    assert record["fixture"]["fixture_id"] == "linux-6.12.117-x86_64"
    with pytest.raises(MalformedRunError):
        ingest_text(_tap("kunit_pass.tap"), fixture={"arch": "riscv64"})
    with pytest.raises(MalformedRunError):
        ingest_text(_tap("kunit_pass.tap"), fixture={"surprise": "x"})
    with pytest.raises(MalformedRunError):
        ingest_text(_tap("kunit_pass.tap"), fixture={"fixture_id": "latest"})


def test_validate_record_rejects_tampered_verdict():
    record = ingest_text(_tap("kunit_mixed.tap"))
    tampered = copy.deepcopy(record)
    tampered["verdict"] = "passed"
    with pytest.raises(MalformedRunError):
        validate_report_dict(tampered)


def test_validate_record_rejects_tampered_totals():
    record = ingest_text(_tap("kunit_pass.tap"))
    tampered = copy.deepcopy(record)
    tampered["totals"]["failed"] = 3
    with pytest.raises(MalformedRunError):
        validate_report_dict(tampered)


def test_validate_record_rejects_unknown_field():
    record = ingest_text(_tap("kunit_pass.tap"))
    tampered = copy.deepcopy(record)
    tampered["sneaky"] = True
    with pytest.raises(MalformedRunError):
        validate_report_dict(tampered)


def test_summarize_runs_worst_verdict_wins():
    good = ingest_text(_tap("kunit_pass.tap"))
    bad = ingest_text(_tap("kunit_mixed.tap"))
    broken = ingest_text(_tap("kunit_truncated.tap"))
    summary = summarize_runs([good, bad])
    assert summary["verdict"] == "failed"
    assert summary["run_count"] == 2
    assert summary["totals"]["total"] == 10
    assert summarize_runs([good, broken])["verdict"] == "malformed"
    assert summarize_runs([])["verdict"] == "malformed"


def _evidence(name, parser):
    report = parser(_tap(name))
    return build_evidence_record(
        report, recorded_at="2026-11-12T09:00:00Z",
        incident_id="inc-kernel-lab-0902", host_local_id="purpleraider",
        tool_versions={"gcc": "15.3.0"})


def test_evidence_record_validates_against_banked_schema():
    schema = json.loads(EVIDENCE_SCHEMA.read_text(encoding="utf-8"))
    validator = Draft202012Validator(schema, format_checker=FormatChecker())
    for name, parser in (("kunit_pass.tap", parse_kunit_tap),
                         ("kunit_mixed.tap", parse_kunit_tap),
                         ("kunit_truncated.tap", parse_kunit_tap),
                         ("kselftest_mixed.tap", parse_kselftest_tap)):
        evidence = _evidence(name, parser)
        errors = list(validator.iter_errors(evidence))
        assert errors == [], f"{name}: {errors}"
        assert evidence["kind"] == "test-run"
        assert evidence["source"]["component"] == "lab"
        assert evidence["tool_versions"]["gcc"] == "15.3.0"


def test_evidence_record_is_honest_about_failures():
    failed = _evidence("kunit_mixed.tap", parse_kunit_tap)
    assert "verdict failed" in failed["summary"]
    assert any("verified failure" in lim for lim in failed["limitations"])
    malformed = _evidence("kunit_truncated.tap", parse_kunit_tap)
    assert "verdict malformed" in malformed["summary"]
    assert any("not a pass" in lim for lim in malformed["limitations"])


def test_evidence_id_is_content_derived():
    first = _evidence("kunit_pass.tap", parse_kunit_tap)
    second = _evidence("kunit_pass.tap", parse_kunit_tap)
    assert first["evidence_id"] == second["evidence_id"]
    assert first["evidence_id"].startswith("ev-kernellab-")
    other = _evidence("kselftest_pass.tap", parse_kselftest_tap)
    assert other["evidence_id"] != first["evidence_id"]


def test_evidence_record_rejects_bad_ids():
    report = parse_kunit_tap(_tap("kunit_pass.tap"))
    with pytest.raises(MalformedRunError):
        build_evidence_record(report, recorded_at="2026-11-12T09:00:00Z",
                              incident_id="not-an-incident")


# ------------------------------------------------------------- standing

def test_module_imports_no_execution_or_network_machinery():
    tree = ast.parse(Path(kernellab.__file__).read_text(encoding="utf-8"))
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
    banned = {"subprocess", "socket", "urllib", "http", "requests",
              "os", "shutil", "ctypes"}
    assert imported & banned == set()


def test_desired_exports_do_not_collide_with_banked_snapshot():
    snapshot = json.loads(
        (FIXTURES / "banked_exports_snapshot.json").read_text(encoding="utf-8"))
    banked = set(snapshot["exports"])
    for name in DESIRED_EXPORTS:
        assert hasattr(kernellab, name), f"missing desired export {name}"
        assert name not in banked, f"{name} collides with the banked package"
    for name in KNOWN_COLLIDERS:
        assert hasattr(kernellab, name)
        assert name in banked, f"{name} should be a known collider"
