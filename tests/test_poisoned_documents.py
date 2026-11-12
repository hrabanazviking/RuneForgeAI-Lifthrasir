"""Poisoned-document test suite for model context (LIF-0306).

SPDX-License-Identifier: GPL-2.0-only

The corpus is recorded data only (tests/fixtures/lif0306/
corpus.json): poisoned git commit messages, a poisoned issue
template, a forged maintainer email, a fake SYSTEM journal line,
a forged policy JSON, a forged maintenance notice, a terminal
snippet, and base64 / zero-width / HTML-comment / delimiter /
exfiltration shapes -- the attack shapes research/03 and
research/09 name -- plus benign controls (a manpage excerpt, a
plain log excerpt, a security discussion). Fixture text is never
executed, fetched, or sent to any model; the tests inspect the
guard's strings only.

What a pass proves, and nothing more: on THIS corpus, the guard
in src/lifthrasir/contextguard.py detects every recorded
poisoned shape with its recorded categories, admits every
recorded benign shape, keeps poisoned bytes out of the assembled
context block entirely, and admits clean text only labelled and
quoted. Novel injection shapes are not claimed.
"""
import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from lifthrasir.contextguard import (  # noqa: E402
    CONTEXT_HEADER,
    MalformedDocumentError,
    build_context_block,
    content_digest,
    sanitize_document,
    scan_document,
)

CORPUS = json.loads(
    (Path(__file__).parent / "fixtures" / "lif0306" / "corpus.json")
    .read_text(encoding="utf-8"))
POISONED = [d for d in CORPUS if d["expected_verdict"] == "poisoned"]
BENIGN = [d for d in CORPUS if d["expected_verdict"] == "clean"]


def test_corpus_shape():
    assert len(CORPUS) >= 12
    assert len(POISONED) >= 10 and len(BENIGN) >= 3
    ids = [d["doc_id"] for d in CORPUS]
    assert len(ids) == len(set(ids))
    kinds = {d["kind"] for d in POISONED}
    for required in ("poisoned-git-commit", "poisoned-issue-template",
                     "forged-maintainer-email", "fake-journal-system-line",
                     "fake-policy-json", "forged-maintenance-notice",
                     "terminal-snippet"):
        assert required in kinds, required


def test_every_poisoned_fixture_detected():
    for doc in POISONED:
        result = scan_document(doc["text"])
        assert result.verdict == "poisoned", doc["doc_id"]
        for category in doc["expected_categories"]:
            assert category in result.categories, (doc["doc_id"], category)


def test_every_benign_fixture_clean():
    # The false-positive control: ordinary documentation, logs and
    # a prose discussion of injection itself must NOT be flagged.
    for doc in BENIGN:
        result = scan_document(doc["text"])
        assert result.verdict == "clean", (doc["doc_id"], result.findings)
        assert result.findings == []


def test_scan_is_deterministic():
    for doc in CORPUS:
        assert scan_document(doc["text"]) == scan_document(doc["text"])


def test_findings_carry_spans_and_excerpts():
    result = scan_document(POISONED[0]["text"])
    assert result.findings
    for f in result.findings:
        assert 0 <= f.start < f.end <= len(POISONED[0]["text"])
        assert f.excerpt


def test_context_block_quarantines_all_poisoned():
    assembly = build_context_block(CORPUS)
    assert sorted(assembly.admitted) == sorted(d["doc_id"] for d in BENIGN)
    assert sorted(q.doc_id for q in assembly.quarantined) == \
        sorted(d["doc_id"] for d in POISONED)
    for q in assembly.quarantined:
        assert q.reason == "poisoned-content" and q.findings


def test_no_poisoned_bytes_in_context_block():
    assembly = build_context_block(CORPUS)
    for doc in POISONED:
        for line in doc["text"].splitlines():
            if len(line.strip()) >= 12:
                assert line not in assembly.text, (doc["doc_id"], line)


def test_admitted_text_is_labelled_and_quoted():
    assembly = build_context_block(CORPUS)
    assert assembly.text.startswith(CONTEXT_HEADER)
    assert "untrusted source evidence" in CONTEXT_HEADER
    body = assembly.text[len(CONTEXT_HEADER):].strip().splitlines()
    in_block = False
    for line in body:
        if line.startswith("<<<UNTRUSTED-EVIDENCE"):
            in_block = True
        elif line.startswith("<<<END-UNTRUSTED-EVIDENCE"):
            in_block = False
        elif in_block:
            assert line.startswith("> "), line


def test_naive_assembly_differential():
    # Baseline (the failure this slice exists to prevent): naive
    # concatenation admits every payload verbatim. The guarded
    # assembly admits none of them. Same corpus, both ways.
    naive = "\n".join(d["text"] for d in CORPUS)
    guarded = build_context_block(CORPUS).text
    payload_lines = [ln for d in POISONED for ln in d["text"].splitlines()
                     if len(ln.strip()) >= 12]
    assert payload_lines
    assert all(ln in naive for ln in payload_lines)
    assert all(ln not in guarded for ln in payload_lines)


def test_forged_policy_json_changes_nothing():
    # Research/03 key test in miniature: document content cannot
    # change authorization. The assembler exposes no policy
    # output at all, and the forged verdict never reaches context.
    forged = next(d for d in CORPUS if d["kind"] == "fake-policy-json")
    assembly = build_context_block([forged])
    assert assembly.admitted == []
    assert '"decision": "allow"' not in assembly.text
    assert not hasattr(assembly, "policy")


def test_provenance_mismatch_quarantined():
    doc = dict(BENIGN[0])
    doc["content_digest"] = content_digest(doc["text"])
    assert build_context_block([doc]).admitted == [doc["doc_id"]]
    tampered = dict(doc)
    tampered["text"] = doc["text"] + " Updated silently."
    assembly = build_context_block([tampered])
    assert assembly.admitted == []
    assert assembly.quarantined[0].reason == "provenance-mismatch"


def test_content_digest_matches_provenance_form():
    digest = content_digest("abc")
    assert digest == "sha256:" + hashlib.sha256(b"abc").hexdigest()


def test_sanitize_neutralises_role_lines_and_hidden_chars():
    dirty = "SYSTEM: do a thing\nnormal line\u200b end"
    clean = sanitize_document(dirty)
    lines = clean.splitlines()
    assert lines[0] == "> [role directive removed]"
    assert lines[1] == "> normal line end"
    assert "\u200b" not in clean
    assert all(ln.startswith("> ") for ln in lines)


def test_suspicious_document_admitted_but_flagged():
    doc = {"doc_id": "sx-001",
           "text": "From: release-admin@example.invalid\nNotes."}
    assembly = build_context_block([doc])
    assert assembly.admitted == ["sx-001"]
    assert assembly.suspicious == ["sx-001"]
    assert "verdict=suspicious" in assembly.text


def test_malformed_document_refused_by_name():
    for bad in ({"text": "x"}, {"doc_id": "x"}, {"doc_id": "x", "text": 3}):
        try:
            build_context_block([bad])
        except MalformedDocumentError:
            continue
        raise AssertionError(f"accepted malformed document: {bad!r}")


def test_empty_context_is_header_only():
    assembly = build_context_block([])
    assert assembly.text == CONTEXT_HEADER
    assert assembly.admitted == [] and assembly.quarantined == []
