# SPDX-License-Identifier: GPL-2.0-only
"""LIF-0303 exact text search tests.

Scope: in-memory search over the committed fixture corpus
(tests/fixtures/lif0303/corpus.json) whose records use the
LIF-0004 v0.1 shapes.  No network, no files outside the repo, no
real embedding model: the embedding path is exercised only through
the deterministic counting stub.

Documented behaviour pinned here: matching is CASE-SENSITIVE and
character-exact (character offsets, [start, end)); substring search
may match inside words; phrase search requires word boundaries;
no match returns an honest empty list.
"""
import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from lifthrasir import search as srch  # noqa: E402


@pytest.fixture(scope="module")
def corpus():
    path = REPO / "tests" / "fixtures" / "lif0303" / "corpus.json"
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.fixture()
def engine(corpus):
    return srch.ExactSearch(corpus)


def test_exact_phrase_found_with_record_and_offsets(engine):
    hits = engine.search_phrase("quick brown")
    assert len(hits) == 1
    hit = hits[0]
    assert hit.record_id == "ev-2026-101"
    assert hit.field == "summary"
    assert (hit.start, hit.end) == (4, 15)
    assert hit.text == "quick brown"
    text = "The quick brown fox jumps over the lazy dog"
    assert text[hit.start:hit.end] == "quick brown"


def test_default_search_is_phrase_search(engine):
    assert engine.search("quick brown") == engine.search_phrase("quick brown")


def test_phrase_multiple_records_deterministic_order(engine):
    hits = engine.search_phrase("brown fox")
    keys = [(h.record_id, h.field, h.start) for h in hits]
    assert keys == sorted(keys)
    assert [h.record_id for h in hits] == [
        "ev-2026-101", "inc-2026-101", "inc-2026-101"]
    assert hits[0].field == "summary" and (hits[0].start, hits[0].end) == (10, 19)
    assert hits[1].field == "symptoms[1]" and hits[1].start == 0
    assert hits[2].field == "symptoms[1]" and hits[2].start == 10


def test_substring_matches_inside_words(engine):
    hits = engine.search_substring("emo")
    assert hits, "substring search must find 'emo' inside 'demo'"
    assert all("emo" == h.text for h in hits)
    assert any(h.record_id == "ev-2026-102" for h in hits)


def test_phrase_refuses_mid_word_match(engine):
    # 'emo' occurs only inside 'demo'/'Demo': no word-boundary match.
    assert engine.search_phrase("emo") == []


def test_no_match_returns_empty(engine):
    assert engine.search_phrase("purple elephant") == []
    assert engine.search_substring("purple elephant") == []
    assert engine.search("zzz-not-present") == []


def test_case_sensitive_as_documented(engine):
    hits = engine.search_phrase("Demo")
    assert [h.record_id for h in hits] == ["ev-2026-103"]
    assert (hits[0].start, hits[0].end) == (14, 18)
    lower = engine.search_phrase("demo")
    assert all(h.record_id != "ev-2026-103" or h.start != 14 for h in lower)
    assert engine.search_phrase("DEMO") != engine.search_phrase("demo")
    assert [h.record_id for h in engine.search_phrase("DEMO")] == ["ev-2026-103"]


def test_empty_query_refused(engine):
    with pytest.raises(srch.EmptyQueryError):
        engine.search_phrase("")
    with pytest.raises(srch.EmptyQueryError):
        engine.search_substring("   ")


def test_negative_control_word_order_swapped(engine):
    # Both words are present in ev-2026-101, in this order only.
    assert engine.search_phrase("quick brown") != []
    assert engine.search_phrase("brown quick") == []
    assert engine.search_substring("brown quick") == []


def test_negative_control_inserted_word_breaks_phrase(engine):
    assert engine.search_phrase("quick fox") == []


def test_flag_off_never_touches_embedding_path(corpus):
    stub = srch.StubEmbeddingProvider()
    eng = srch.ExactSearch(corpus, embeddings_enabled=False,
                           embedding_provider=stub)
    assert eng.search_phrase("quick brown")
    assert eng.search_substring("emo")
    assert eng.search_phrase("absent phrase") == []
    with pytest.raises(srch.EmbeddingsDisabledError):
        eng.search_semantic("quick brown")
    assert stub.calls == 0


def test_flag_off_by_default(corpus):
    eng = srch.ExactSearch(corpus)
    assert eng.embeddings_enabled is False
    with pytest.raises(srch.EmbeddingsDisabledError):
        eng.search_semantic("anything")


def test_flag_on_stub_path_labelled_stub(corpus):
    stub = srch.StubEmbeddingProvider()
    eng = srch.ExactSearch(corpus, embeddings_enabled=True,
                           embedding_provider=stub)
    results = eng.search_semantic("quick brown fox")
    assert stub.calls > 0
    assert results, "stub path returns labelled results for the corpus"
    assert all(r.kind == "stub-embedding" for r in results)
    assert all(r.provider == "stub-deterministic-v1" for r in results)
    keys = [(-r.score, r.record_id) for r in results]
    assert keys == sorted(keys)


def test_fts5_candidates_are_superset_of_exact(corpus, engine):
    if not srch.fts5_available():
        pytest.skip("FTS5 unavailable on this host")
    for phrase in ("quick brown", "brown fox", "demo"):
        exact_ids = {h.record_id for h in engine.search_phrase(phrase)}
        assert exact_ids <= set(engine.fts_phrase_candidates(phrase))


def test_stored_record_duck_type_alignment(corpus):
    class FakeStored:
        def __init__(self, payload):
            self.payload = payload
            self.record_id = srch.record_identity(payload)

    eng = srch.ExactSearch([FakeStored(r) for r in corpus])
    hits = eng.search_phrase("quick brown")
    assert [h.record_id for h in hits] == ["ev-2026-101"]
