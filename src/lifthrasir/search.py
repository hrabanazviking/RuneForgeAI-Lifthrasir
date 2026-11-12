"""Exact text search for Mimir records; optional stub embeddings (LIF-0303).

SPDX-License-Identifier: GPL-2.0-only

Home justification: ADR-0002 D4 fixes the Mimir evidence store as
SQLite + FTS with append-only hash-linked records, and LIF-0301
(team-03, in flight) places that store at ``src/lifthrasir/eventstore.py``
in the core package (master roadmap section 3: ``src/`` for core).
Exact search is the store's companion retrieval surface (ADR-0002
process table: ``lifthrasir-indexer`` owns "local keyword, exact-match
and optional vector retrieval"), so it lives beside the store in
``src/lifthrasir/`` -- not in ``lab/``, which D2 reserves for rapid
prototypes whose contracts have not stabilised.  This module ships
WITHOUT an ``__init__.py`` on purpose: LIF-0201/LIF-0301 own the
package ``__init__`` export lists on their branches, and a namespace
package import works both before and after those slices bank, so
this slice can never conflict with or overwrite their exports.

Record shapes: plain mappings in the LIF-0004 v0.1 shapes
(``docs/protocols/schemas/v0.1/``).  A record's identity is its typed
identifier -- the first present of ``evidence_id``, ``incident_id``,
``hypothesis_id``, ``plan_id``, ``record_id``, ``id``.  Searchable
text is every string value in the record: top-level fields under
their field name, list-of-string items as ``field[index]``, and
nested mapping values as ``field.key`` (one level).  The module also
accepts LIF-0301 ``StoredRecord`` objects by duck-typing (anything
with ``record_id`` and ``payload`` attributes); it never imports the
store, so it works whether or not LIF-0301 has banked.  Alignment
note: team-03's in-flight store extracts only ``summary`` as a
column and keeps the full record in ``payload_json``; this module
searches the full payload, which is a superset of the store's
extracted fields -- recorded in CAMPAIGN_STATE.md, not diverged
silently.

Exactness contract (the whole point of the slice):

- Matching is CASE-SENSITIVE and character-exact.  ``Demo`` does not
  match ``demo``.  No case folding, no stemming, no fuzziness, no
  Unicode normalisation: punctuation and whitespace are literal.
- ``search_substring(term)`` finds every occurrence of ``term``,
  including inside longer words.
- ``search_phrase(phrase)`` finds every occurrence of the exact
  contiguous phrase whose match starts and ends on a word boundary
  (a non-word character or the edge of the field text on both
  sides), so a phrase never matches glued inside a longer word.
- A query with no exact match returns an empty list.  Near-misses
  are NEVER dressed as matches.
- Results are ``Match`` records carrying record identity, field,
  character offsets ``[start, end)`` into that field's text, and the
  matched text itself, ordered deterministically by
  ``(record_id, field, start)``.  Overlapping occurrences are all
  reported.  Empty or whitespace-only queries are refused.

Engine choice (recorded, per slice instructions): SQLite FTS5 IS
available on the build host (stdlib sqlite3, SQLite 3.53.4, probed
at import time by ``fts5_available()``), and this module builds an
FTS5 candidate index when it is available (``fts_phrase_candidates``).
FTS5 is, however, a tokenising, case-insensitive index: it cannot
guarantee character-exact offsets, case sensitivity, or mid-word
substring hits, so it is used ONLY as a candidate pre-filter whose
output the tests differentially check against the exact engine on
the fixture corpus.  The authoritative results always come from the
exact in-memory scan (``str.find`` over the extracted field texts),
which is the only engine that can honour the exactness contract.
If FTS5 were unavailable the module would behave identically, minus
the candidate helper.

Embeddings (ADR-0002 D4: "optional, local-only, behind a feature
flag"): an ``EmbeddingProvider`` protocol plus a deterministic
local ``StubEmbeddingProvider`` used in tests.  The feature flag is
OFF by default (``embeddings_enabled=False``).  With the flag off,
no embedding code runs at all: exact search never touches the
provider, and ``search_semantic`` raises ``EmbeddingsDisabledError``
BEFORE consulting any provider.  With the flag on, the stub path
returns ``SemanticResult`` items explicitly labelled
``kind="stub-embedding"`` with the provider name attached; stub
output is a plumbing proof, NEVER a claim of semantic quality.
No network, no model downloads, no real embedding model exists in
this slice.
"""
from __future__ import annotations

import hashlib
import sqlite3
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Mapping, Optional, Protocol


class SearchError(Exception):
    """Base class for named search refusals."""


class EmptyQueryError(SearchError):
    """Raised for empty or whitespace-only queries."""


class EmbeddingsDisabledError(SearchError):
    """Raised when semantic search is attempted with the flag off."""


_ID_FIELDS = ("evidence_id", "incident_id", "hypothesis_id",
              "plan_id", "record_id", "id")


def record_identity(record: Mapping[str, Any]) -> str:
    for field in _ID_FIELDS:
        value = record.get(field)
        if isinstance(value, str) and value:
            return value
    raise SearchError(f"record carries no typed identifier: {sorted(record)}")


def extract_fields(record: Mapping[str, Any]) -> List[tuple]:
    """Return [(field_name, text)] for every searchable string, sorted."""
    out = []
    for key in sorted(record):
        value = record[key]
        if isinstance(value, str):
            out.append((key, value))
        elif isinstance(value, list):
            for idx, item in enumerate(value):
                if isinstance(item, str):
                    out.append((f"{key}[{idx}]", item))
        elif isinstance(value, Mapping):
            for sub in sorted(value):
                if isinstance(value[sub], str):
                    out.append((f"{key}.{sub}", value[sub]))
    return out


@dataclass(frozen=True)
class Match:
    record_id: str
    field: str
    start: int
    end: int
    text: str


@dataclass(frozen=True)
class SemanticResult:
    record_id: str
    score: float
    kind: str  # always "stub-embedding" in this slice
    provider: str


class EmbeddingProvider(Protocol):
    """Interface a real local embedding provider would implement."""

    name: str

    def embed(self, text: str) -> List[float]:
        ...


class StubEmbeddingProvider:
    """Deterministic local stub. Counts calls so tests can prove use."""

    name = "stub-deterministic-v1"

    def __init__(self) -> None:
        self.calls = 0

    def embed(self, text: str) -> List[float]:
        self.calls += 1
        digest = hashlib.sha256(text.encode("utf-8")).digest()
        return [b / 255.0 for b in digest[:8]]


def _is_word_char(ch: str) -> bool:
    return ch.isalnum() or ch == "_"


def _occurrences(text: str, needle: str) -> List[int]:
    starts = []
    pos = text.find(needle)
    while pos != -1:
        starts.append(pos)
        pos = text.find(needle, pos + 1)
    return starts


def fts5_available() -> bool:
    try:
        conn = sqlite3.connect(":memory:")
        conn.execute("CREATE VIRTUAL TABLE t USING fts5(x)")
        conn.close()
        return True
    except sqlite3.Error:
        return False


class ExactSearch:
    """Exact search over a fixed corpus of LIF-0004-shaped records."""

    def __init__(self, records: Iterable[Any], *,
                 embeddings_enabled: bool = False,
                 embedding_provider: Optional[EmbeddingProvider] = None):
        self._docs = []  # [(record_id, [(field, text)], record)]
        for item in records:
            if isinstance(item, Mapping):
                record, rid = item, record_identity(item)
            else:  # StoredRecord duck-type from LIF-0301
                record, rid = item.payload, item.record_id
            self._docs.append((rid, extract_fields(record), record))
        self._docs.sort(key=lambda d: d[0])
        self.embeddings_enabled = bool(embeddings_enabled)
        self._provider = embedding_provider
        self._fts = None
        if fts5_available():
            self._fts = sqlite3.connect(":memory:")
            self._fts.execute(
                "CREATE VIRTUAL TABLE docs USING fts5(record_id, field, text)")
            for rid, fields, _ in self._docs:
                for field, text in fields:
                    self._fts.execute(
                        "INSERT INTO docs VALUES (?, ?, ?)", (rid, field, text))

    # -- exact engine (authoritative) --------------------------------
    def _scan(self, needle: str, phrase: bool) -> List[Match]:
        if not needle or not needle.strip():
            raise EmptyQueryError("query must be non-empty")
        results = []
        for rid, fields, _ in self._docs:
            for field, text in fields:
                for start in _occurrences(text, needle):
                    end = start + len(needle)
                    if phrase:
                        if start > 0 and _is_word_char(text[start - 1]):
                            continue
                        if end < len(text) and _is_word_char(text[end]):
                            continue
                    results.append(Match(rid, field, start, end,
                                         text[start:end]))
        results.sort(key=lambda m: (m.record_id, m.field, m.start))
        return results

    def search_substring(self, term: str) -> List[Match]:
        return self._scan(term, phrase=False)

    def search_phrase(self, phrase: str) -> List[Match]:
        return self._scan(phrase, phrase=True)

    def search(self, query: str) -> List[Match]:
        """Default search = exact whole-phrase matching."""
        return self.search_phrase(query)

    # -- FTS5 candidate pre-filter (never authoritative) -------------
    def fts_phrase_candidates(self, phrase: str) -> List[str]:
        """Record ids FTS5 nominates for a phrase; [] if FTS5 absent.

        Candidates are a token-level superset check only -- callers
        must verify with the exact engine.  Returns sorted unique ids.
        """
        if self._fts is None:
            return []
        quoted = '"' + phrase.replace('"', '""') + '"'
        rows = self._fts.execute(
            "SELECT DISTINCT record_id FROM docs WHERE docs MATCH ?",
            (quoted,)).fetchall()
        return sorted(r[0] for r in rows)

    # -- optional embeddings (flag-gated, stub-only in this slice) ---
    def search_semantic(self, query: str) -> List[SemanticResult]:
        if not self.embeddings_enabled:
            raise EmbeddingsDisabledError(
                "embeddings are behind a feature flag and it is OFF")
        if not query or not query.strip():
            raise EmptyQueryError("query must be non-empty")
        provider = self._provider or StubEmbeddingProvider()
        qvec = provider.embed(query)
        scored = []
        for rid, fields, _ in self._docs:
            text = " ".join(t for _, t in fields)
            dvec = provider.embed(text)
            denom = (sum(v * v for v in qvec) ** 0.5) * \
                (sum(v * v for v in dvec) ** 0.5)
            score = sum(a * b for a, b in zip(qvec, dvec)) / denom \
                if denom else 0.0
            scored.append(SemanticResult(rid, score, "stub-embedding",
                                         provider.name))
        scored.sort(key=lambda r: (-r.score, r.record_id))
        return scored
