# SPDX-License-Identifier: GPL-2.0-only
"""Tests for LIF-0905: static-analysis and checkpatch reporting.

All inputs are RECORDED fixture outputs in the real tools' formats
(tests/fixtures/lif0905/).  No analyzer is run, no code under
analysis is touched, and malformed input must be reported as
malformed -- never as zero findings.
"""
import ast
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import pytest

from lifthrasir import staticanalysis as sa

FIXTURES = Path(__file__).parent / "fixtures" / "lif0905"


def load(name):
    return (FIXTURES / name).read_text(encoding="utf-8")


def test_checkpatch_dirty_findings_normalized():
    report = sa.parse_analysis_output(
        load("checkpatch_dirty.txt"), "checkpatch")
    assert report.parse_status == "ok"
    assert report.parse_issues == []
    assert len(report.findings) == 5
    assert report.counts_by_severity() == {
        "error": 2, "warning": 2, "check": 1}
    located = [f for f in report.findings if f.file is not None]
    assert len(located) == 4
    trailing = [f for f in report.findings
                if f.message == "trailing whitespace"]
    assert len(trailing) == 1
    assert trailing[0].file.endswith("lab_net.c")
    assert trailing[0].line == 204
    assert trailing[0].severity == "error"
    assert trailing[0].rule is None  # checkpatch carries no rule name
    assert report.declared_totals == {
        "errors": 2, "warnings": 2, "checks": 1, "lines_checked": 312}


def test_checkpatch_commit_log_finding_has_no_location():
    report = sa.parse_analysis_output(
        load("checkpatch_dirty.txt"), "checkpatch")
    commit = [f for f in report.findings
              if f.message.startswith("Missing commit description")]
    assert len(commit) == 1
    # Never inferred from a neighbouring finding.
    assert commit[0].file is None and commit[0].line is None


def test_checkpatch_context_and_trailer_never_become_findings():
    report = sa.parse_analysis_output(
        load("checkpatch_dirty.txt"), "checkpatch")
    messages = [f.message for f in report.findings]
    assert not any("false positives" in m for m in messages)
    assert not any(m.startswith("+") for m in messages)
    assert not any("style problems" in m for m in messages)


def test_checkpatch_clean_run_is_legitimately_zero():
    report = sa.parse_analysis_output(
        load("checkpatch_clean.txt"), "checkpatch")
    assert report.parse_status == "ok"
    assert report.findings == []
    assert report.declared_totals["errors"] == 0
    assert report.declared_totals["lines_checked"] == 148


def test_checkpatch_truncated_is_malformed_not_complete():
    report = sa.parse_analysis_output(
        load("checkpatch_truncated.txt"), "checkpatch")
    assert report.parse_status == "malformed"
    assert len(report.findings) == 2  # carried, but not complete
    kinds = {i.kind for i in report.parse_issues}
    assert "missing-total" in kinds


def test_checkpatch_totals_mismatch_is_flagged():
    text = load("checkpatch_dirty.txt").replace(
        "total: 2 errors", "total: 5 errors")
    report = sa.parse_analysis_output(text, "checkpatch")
    assert report.parse_status == "malformed"
    kinds = {i.kind for i in report.parse_issues}
    assert "totals-mismatch" in kinds
    # Neither figure is silently trusted: both stay visible.
    assert report.declared_totals["errors"] == 5
    assert report.counts_by_severity()["error"] == 2


def test_sparse_findings_and_dedup_occurrences():
    report = sa.parse_analysis_output(load("sparse.txt"), "sparse")
    assert report.parse_status == "ok"
    assert len(report.findings) == 4
    assert report.total_occurrences == 5
    assert report.duplicates_removed == 1
    dup = [f for f in report.findings if f.occurrences == 2]
    assert len(dup) == 1 and dup[0].line == 118
    assert dup[0].column == 9 and dup[0].rule is None
    assert report.counts_by_severity() == {
        "warning": 3, "error": 1, "note": 1}


def test_coccinelle_findings():
    report = sa.parse_analysis_output(
        load("coccinelle.txt"), "coccinelle")
    assert report.parse_status == "ok"
    assert len(report.findings) == 3
    first = report.findings[0]
    assert first.file.endswith("lab_char.c")
    assert first.line == 64 and first.column == 2
    assert first.severity == "warning"
    assert report.counts_by_severity() == {
        "warning": 1, "error": 1, "check": 1}


def test_clang_tidy_rules_extracted():
    report = sa.parse_analysis_output(
        load("clang_tidy.txt"), "clang-tidy")
    assert report.parse_status == "ok"
    rules = {f.rule for f in report.findings}
    assert rules == {"readability-else-after-return",
                     "bugprone-narrowing-conversions",
                     "-Wunused-variable"}
    assert all("[" not in f.message for f in report.findings)


def test_empty_input_is_malformed_never_zero_findings():
    for tool in sa.TOOLS:
        for text in ("", "   \n\n  "):
            report = sa.parse_analysis_output(text, tool)
            assert report.parse_status == "malformed"
            assert report.findings == []
            assert {i.kind for i in report.parse_issues} == {
                "empty-input"}


def test_garbage_input_is_malformed_for_every_tool():
    for tool in sa.TOOLS:
        report = sa.parse_analysis_output(
            load("malformed.txt"), tool)
        assert report.parse_status == "malformed", tool
        assert report.findings == [], tool


def test_severity_words_in_prose_do_not_parse():
    # The malformed fixture mentions "warning" and "error" in
    # prose; severity is only read at its fixed grammar slot.
    report = sa.parse_analysis_output(load("malformed.txt"), "sparse")
    assert report.unparsed_lines == 4
    assert report.findings == []


def test_dedup_never_collapses_distinct_lines_or_tools():
    base = sa.AnalysisFinding(
        "sparse", "a.c", 10, 3, None, "warning", "same message")
    other_line = sa.AnalysisFinding(
        "sparse", "a.c", 11, 3, None, "warning", "same message")
    other_tool = sa.AnalysisFinding(
        "clang-tidy", "a.c", 10, 3, None, "warning", "same message")
    merged = sa.dedupe_findings([base, base, other_line, other_tool])
    assert len(merged) == 3
    assert sum(f.occurrences for f in merged) == 4


def test_report_dict_shape_gate_and_determinism():
    text = load("sparse.txt")
    one = sa.parse_analysis_output(text, "sparse")
    two = sa.parse_analysis_output(text, "sparse")
    assert one.to_dict() == two.to_dict()
    assert one.report_id == two.report_id
    assert sa.validate_report_dict(one.to_dict()) == []
    broken = dict(one.to_dict(), findings_count=99)
    assert sa.validate_report_dict(broken) != []
    malformed = sa.parse_analysis_output(
        load("malformed.txt"), "sparse")
    assert sa.validate_report_dict(malformed.to_dict()) == []


def test_evidence_record_matches_v01_shape():
    report = sa.parse_analysis_output(
        load("checkpatch_dirty.txt"), "checkpatch")
    record = sa.build_evidence_record(
        report, recorded_at="2026-11-12T09:00:00Z",
        incident_id="inc-lif0905-fixture")
    assert record["schema"] == "lifthrasir.evidence.v0.1"
    assert record["schema_version"] == "0.1"
    assert record["kind"] == "test-run"
    assert record["source"]["component"] == "lab"
    assert record["evidence_status"] == "reproducer"
    assert record["tool_versions"]  # kind test-run requires them
    assert record["content_digest"].startswith("sha256:")
    assert "5 distinct findings" in record["summary"]
    again = sa.build_evidence_record(
        report, recorded_at="2026-11-12T10:00:00Z",
        incident_id="inc-lif0905-fixture")
    assert again["evidence_id"] == record["evidence_id"]
    assert again["content_digest"] == record["content_digest"]


def test_evidence_record_for_malformed_report_stays_honest():
    report = sa.parse_analysis_output(
        load("checkpatch_truncated.txt"), "checkpatch")
    record = sa.build_evidence_record(
        report, recorded_at="2026-11-12T09:00:00Z",
        incident_id="inc-lif0905-fixture")
    assert "parse status malformed" in record["summary"]
    assert record["evidence_status"] == "reproducer"


def test_summarize_reports_keeps_cross_tool_findings():
    reports = [
        sa.parse_analysis_output(load("sparse.txt"), "sparse"),
        sa.parse_analysis_output(
            load("clang_tidy.txt"), "clang-tidy"),
        sa.parse_analysis_output(load("malformed.txt"), "coccinelle"),
    ]
    summary = sa.summarize_reports(reports)
    assert summary["total_findings"] == 7
    assert summary["any_malformed"] is True
    assert summary["malformed_tools"] == ["coccinelle"]
    assert summary["tools"]["sparse"]["findings_count"] == 4


def test_differential_vs_naive_grep_baseline():
    text = load("sparse.txt")
    naive = sum(1 for line in text.splitlines()
                if "warning:" in line or "error:" in line
                or "note:" in line)
    report = sa.parse_analysis_output(text, "sparse")
    # Naive counting double-counts the duplicated diagnostic and
    # cannot see occurrences; the parser's ground truth differs.
    assert naive == 5
    assert len(report.findings) == 4
    assert report.total_occurrences == naive


def test_unknown_tool_and_oversize_are_caller_errors():
    with pytest.raises(sa.UnknownToolError):
        sa.parse_analysis_output("anything", "cppcheck")
    with pytest.raises(sa.OversizeInputError):
        sa.parse_analysis_output(
            "x" * (sa.MAX_INPUT_CHARS + 1), "sparse")


def test_ingest_file_roundtrip(tmp_path):
    target = tmp_path / "recorded_sparse.txt"
    target.write_text(load("sparse.txt"), encoding="utf-8")
    report = sa.ingest_file(target, "sparse")
    assert report.source_name == "recorded_sparse.txt"
    assert len(report.findings) == 4


def test_no_execution_or_network_machinery():
    tree = ast.parse(Path(sa.__file__).read_text(encoding="utf-8"))
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
    assert not (imported & {"subprocess", "socket", "os", "sys",
                            "shutil", "urllib", "requests"})
    # The recorded outputs are data: the JSON form is stable.
    report = sa.parse_analysis_output(
        load("coccinelle.txt"), "coccinelle")
    assert json.loads(json.dumps(report.to_dict())) == report.to_dict()


def test_checkpatch_total_without_checks_segment():
    # Non-strict checkpatch omits the checks segment entirely.
    text = ("ERROR: trailing whitespace\n"
            "#12: FILE: drivers/char/lifthrasir/lab_char.c:40:\n"
            "+\tret = lab_char_init(); \n"
            "\n"
            "total: 1 errors, 0 warnings, 96 lines checked\n")
    report = sa.parse_analysis_output(text, "checkpatch")
    assert report.parse_status == "ok"
    assert report.declared_totals == {
        "errors": 1, "warnings": 0, "checks": 0, "lines_checked": 96}


def test_checkpatch_repeated_totals_cross_checked_per_segment():
    text = (load("checkpatch_truncated.txt")
            + "\ntotal: 1 errors, 1 warnings, 0 checks, "
              "60 lines checked\n")
    report = sa.parse_analysis_output(text, "checkpatch")
    assert report.parse_status == "ok"
    assert report.declared_totals["lines_checked"] == 60
    assert len(report.findings) == 2


def test_ansi_colour_escapes_are_stripped():
    text = ("\x1b[31m" + load("sparse.txt").splitlines()[0]
            + "\x1b[0m\n")
    report = sa.parse_analysis_output(text, "sparse")
    assert report.parse_status == "ok"
    assert len(report.findings) == 1
    assert "\x1b" not in report.findings[0].file


def test_line_diagnostic_without_column_and_fatal_error():
    sparse = sa.parse_analysis_output(
        "kernel/lifthrasir/replicater.c:12: error: "
        "whole-file diagnostic without a column\n", "sparse")
    assert sparse.parse_status == "ok"
    assert sparse.findings[0].column is None
    clang = sa.parse_analysis_output(
        "lab.c:3: fatal error: 'missing.h' file not found\n"
        "1 error generated.\n", "clang-tidy")
    assert clang.parse_status == "ok"
    assert clang.findings[0].severity == "error"
    assert clang.findings[0].column is None


def test_coccinelle_without_severity_word_is_unknown_not_dropped():
    report = sa.parse_analysis_output(
        "drivers/char/lab.c:188:9-16: ERR_CAST can be used here\n",
        "coccinelle")
    assert report.parse_status == "ok"
    assert len(report.findings) == 1
    assert report.findings[0].severity == "unknown"
    assert report.findings[0].line == 188
