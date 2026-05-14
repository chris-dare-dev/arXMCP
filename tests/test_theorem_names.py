"""Tests for the theorem-name SQLite FTS5 index (E10_S02).

Covers:

* Normalize / trigram / dedup helpers — pure functions, no I/O.
* TheoremNamesStore — open / upsert / delete / 3-step lookup against
  a real SQLite file under tmp_path.
* Indexer — walks a hand-built chunks Arrow table; per-paper sweep.
* Handler — 3-step dispatch (exact → FTS5 trigram → Jaccard fallback)
  + in-memory-scan fallback when the DB is absent.
* AC coverage: two papers with "Lemma 3.4" → 2 entries; Yoneda
  matches across papers; paper_id filter; typo-tolerant fuzzy match
  for "riemanroch" → "Riemann-Roch".
* Beyond-AC: FTS5 MATCH injection guard, idempotency, paper_id
  validation, empty/all-punctuation name handling.

Handler-level tests use a hand-built minimal Resources stub plus a
real SQLite store (tmp_path-scoped) so the FTS5 path is exercised
end-to-end; the chunks-table fallback path uses a real LanceDB
chunks table too.
"""

from __future__ import annotations

import asyncio
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pyarrow as pa
import pytest

import server.handlers.lemma as lemma_handler_mod
import server.tools as server_tools
from ingest.index_theorem_names import (
    build_rows_from_chunks_for_paper,
    index_theorem_names_for_paper,
)
from ingest.schema import CHUNKS_SCHEMA_V1
from server.theorem_names_store import (
    DEFAULT_JACCARD_THRESHOLD,
    SCHEMA_VERSION,
    TheoremNamesStore,
    TheoremRow,
    dedup_key,
    fts5_phrase_quote,
    normalize_name,
    serialize_section_path,
    trigram_jaccard,
    trigrams,
)


def _run(coro):
    """Run an async coroutine in a fresh event loop.

    Same pattern as the E10_S01/S03 tests — sync-into-async bridge
    that's safe across the full test suite (prior tests may have
    closed any pre-existing loop).
    """
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


# ===========================================================================
# Pure-function helpers
# ===========================================================================


class TestNormalizeName:
    def test_lowercases(self):
        assert normalize_name("Yoneda Lemma") == "yonedalemma"

    def test_strips_emdash_and_hyphen(self):
        # The chunker emits the em-dash form for "Riemann–Roch".
        assert normalize_name("Riemann–Roch") == "riemannroch"
        # And the plain-hyphen form too.
        assert normalize_name("Riemann-Roch") == "riemannroch"

    def test_strips_punctuation(self):
        assert normalize_name("Lemma 3.4") == "lemma34"
        assert normalize_name("Cauchy–Schwarz Inequality") == "cauchyschwarzinequality"

    def test_handles_unicode_combining_marks(self):
        # 'é' = U+00E9; decomposed = 'e' + U+0301. Both normalize
        # to the same form after NFKD + strip combining marks.
        assert normalize_name("é") == "e"
        assert normalize_name("é") == "e"

    def test_empty_string(self):
        assert normalize_name("") == ""

    def test_all_punctuation_collapses_to_empty(self):
        assert normalize_name("...!?") == ""


class TestTrigrams:
    def test_basic(self):
        assert trigrams("yoneda") == {"yon", "one", "ned", "eda"}

    def test_too_short(self):
        assert trigrams("ab") == {"ab"}

    def test_empty(self):
        assert trigrams("") == set()


class TestTrigramJaccard:
    def test_identical(self):
        assert trigram_jaccard("yoneda", "yoneda") == 1.0

    def test_disjoint(self):
        # No shared trigrams.
        assert trigram_jaccard("abc", "xyz") == 0.0

    def test_riemann_typo_passes_threshold(self):
        """AC4 case: "riemanroch" vs "riemannroch" must score
        comfortably above the default 0.3 threshold."""
        score = trigram_jaccard("riemanroch", "riemannroch")
        assert score >= DEFAULT_JACCARD_THRESHOLD
        # Empirical: 8 query trigrams + 9 indexed trigrams; 7
        # shared, 10 union → Jaccard ≈ 0.7. Comfortably above the
        # 0.3 default threshold.
        assert score >= 0.5


class TestDedupKey:
    def test_distinguishes_same_name_across_papers(self):
        k1 = dedup_key("2401.00001", "Lemma 3.4", "[]")
        k2 = dedup_key("2401.00002", "Lemma 3.4", "[]")
        assert k1 != k2

    def test_distinguishes_same_name_different_section(self):
        k1 = dedup_key("2401.00001", "Lemma 3.4", '["Section 1"]')
        k2 = dedup_key("2401.00001", "Lemma 3.4", '["Section 2"]')
        assert k1 != k2

    def test_stable_across_runs(self):
        k1 = dedup_key("2401.00001", "Yoneda Lemma", "[]")
        k2 = dedup_key("2401.00001", "Yoneda Lemma", "[]")
        assert k1 == k2

    def test_16_hex_chars(self):
        k = dedup_key("a", "b", "c")
        assert len(k) == 16
        assert all(c in "0123456789abcdef" for c in k)


class TestSerializeSectionPath:
    def test_simple_list(self):
        assert (
            serialize_section_path(["Section 1", "Subsection 1.1"])
            == '["Section 1","Subsection 1.1"]'
        )

    def test_none(self):
        assert serialize_section_path(None) == "[]"

    def test_empty(self):
        assert serialize_section_path([]) == "[]"


class TestFts5PhraseQuote:
    def test_basic(self):
        assert fts5_phrase_quote("yoneda") == '"yoneda"'

    def test_doubles_internal_quotes(self):
        # An attacker passing 'foo" OR 1=1 --' is wrapped + escaped.
        assert fts5_phrase_quote('foo"bar') == '"foo""bar"'

    def test_handles_special_chars(self):
        # FTS5 special chars (AND, OR, NOT, *, ^) inside quotes
        # are treated as literals, not as query syntax.
        assert fts5_phrase_quote("OR NOT *") == '"OR NOT *"'

    def test_strips_nul_byte(self):
        """F1 regression (E10_S02 critique) — NUL bytes in the
        input terminate SQLite's C-string parser inside FTS5 phrase
        literals. ``fts5_phrase_quote`` must strip the NUL before
        wrapping so the resulting MATCH expression is parseable.
        """
        assert fts5_phrase_quote("yon\x00eda") == '"yoneda"'

    def test_strips_control_chars(self):
        """F1 regression — the full \\x00-\\x1f control-char range
        is stripped for defense-in-depth.
        """
        assert fts5_phrase_quote("a\x01b\x1fc") == '"abc"'


# ===========================================================================
# TheoremNamesStore — direct unit tests against a real SQLite file
# ===========================================================================


class TestTheoremNamesStore:
    def test_open_creates_schema(self, tmp_path):
        db_path = tmp_path / "theorem_names.db"
        store = _run(TheoremNamesStore.open(db_path))
        try:
            assert db_path.exists()
            # Verify PRAGMA user_version was set.
            conn = sqlite3.connect(str(db_path))
            try:
                ver = conn.execute("PRAGMA user_version").fetchone()[0]
                assert ver == SCHEMA_VERSION
                tables = {
                    r[0] for r in conn.execute(
                        "SELECT name FROM sqlite_master WHERE type='table'"
                    )
                }
                assert "theorem_names" in tables
                assert "theorem_names_fts" in tables
            finally:
                conn.close()
        finally:
            _run(store.close())

    def test_upsert_and_exact_match(self, tmp_path):
        db_path = tmp_path / "theorem_names.db"
        store = _run(TheoremNamesStore.open(db_path))
        try:
            rows = [
                TheoremRow(
                    dedup_key=dedup_key("2401.00001", "Yoneda Lemma", "[]"),
                    paper_id="2401.00001",
                    chunk_id="arxiv:2401.00001:0000000000000001",
                    theorem_name="Yoneda Lemma",
                    display_name="Yoneda Lemma",
                    section_path=[],
                    confidence=1.0,
                )
            ]
            n = _run(store.upsert_rows(rows))
            assert n == 1
            assert _run(store.row_count()) == 1
            matches = _run(store.exact_match("yonedalemma", None, 10))
            assert len(matches) == 1
            assert matches[0].display_name == "Yoneda Lemma"
        finally:
            _run(store.close())

    def test_dedup_two_papers_same_name(self, tmp_path):
        """AC1 — Two papers each with a "Lemma 3.4" produce two
        separate entries in the theorem_names table.
        """
        db_path = tmp_path / "theorem_names.db"
        store = _run(TheoremNamesStore.open(db_path))
        try:
            rows = [
                TheoremRow(
                    dedup_key=dedup_key("2401.00001", "Lemma 3.4", "[]"),
                    paper_id="2401.00001",
                    chunk_id="arxiv:2401.00001:0000000000000001",
                    theorem_name="Lemma 3.4",
                    display_name="Lemma 3.4",
                    section_path=[],
                    confidence=1.0,
                ),
                TheoremRow(
                    dedup_key=dedup_key("2401.00002", "Lemma 3.4", "[]"),
                    paper_id="2401.00002",
                    chunk_id="arxiv:2401.00002:0000000000000001",
                    theorem_name="Lemma 3.4",
                    display_name="Lemma 3.4",
                    section_path=[],
                    confidence=1.0,
                ),
            ]
            _run(store.upsert_rows(rows))
            assert _run(store.row_count()) == 2
            # Both surface under exact lookup.
            matches = _run(store.exact_match("lemma34", None, 10))
            assert len(matches) == 2
            assert {m.paper_id for m in matches} == {"2401.00001", "2401.00002"}
        finally:
            _run(store.close())

    def test_paper_id_filter(self, tmp_path):
        """AC3 — `find_lemma_by_name("Yoneda lemma", paper_id="X")`
        returns only that paper's matches.
        """
        db_path = tmp_path / "theorem_names.db"
        store = _run(TheoremNamesStore.open(db_path))
        try:
            rows = [
                TheoremRow(
                    dedup_key=dedup_key("2401.00001", "Yoneda Lemma", "[]"),
                    paper_id="2401.00001",
                    chunk_id="arxiv:2401.00001:0000000000000001",
                    theorem_name="Yoneda Lemma",
                    display_name="Yoneda Lemma",
                    section_path=[],
                    confidence=1.0,
                ),
                TheoremRow(
                    dedup_key=dedup_key("2401.00002", "Yoneda Lemma", "[]"),
                    paper_id="2401.00002",
                    chunk_id="arxiv:2401.00002:0000000000000001",
                    theorem_name="Yoneda Lemma",
                    display_name="Yoneda Lemma",
                    section_path=[],
                    confidence=1.0,
                ),
            ]
            _run(store.upsert_rows(rows))
            matches = _run(
                store.exact_match("yonedalemma", "2401.00001", 10)
            )
            assert len(matches) == 1
            assert matches[0].paper_id == "2401.00001"
        finally:
            _run(store.close())

    def test_fts5_substring_match(self, tmp_path):
        """FTS5 trigram MATCH on a substring should hit
        (substring-tolerant case, NOT typo-tolerant).
        """
        db_path = tmp_path / "theorem_names.db"
        store = _run(TheoremNamesStore.open(db_path))
        try:
            rows = [
                TheoremRow(
                    dedup_key=dedup_key("2401.00001", "Riemann-Roch", "[]"),
                    paper_id="2401.00001",
                    chunk_id="arxiv:2401.00001:0000000000000001",
                    theorem_name="Riemann-Roch",
                    display_name="Riemann-Roch",
                    section_path=[],
                    confidence=1.0,
                )
            ]
            _run(store.upsert_rows(rows))
            # "riemann" (substring of "riemannroch") matches via FTS5.
            matches = _run(store.fts5_match("riemann", None, 10))
            assert len(matches) == 1
        finally:
            _run(store.close())

    def test_fuzzy_jaccard_handles_typo(self, tmp_path):
        """AC4 — the typo-tolerant path. FTS5 trigram MATCH alone
        does NOT satisfy this (verified separately); the Jaccard
        fallback does.
        """
        db_path = tmp_path / "theorem_names.db"
        store = _run(TheoremNamesStore.open(db_path))
        try:
            rows = [
                TheoremRow(
                    dedup_key=dedup_key("2401.00001", "Riemann-Roch", "[]"),
                    paper_id="2401.00001",
                    chunk_id="arxiv:2401.00001:0000000000000001",
                    theorem_name="Riemann-Roch",
                    display_name="Riemann-Roch",
                    section_path=[],
                    confidence=1.0,
                )
            ]
            _run(store.upsert_rows(rows))
            # FTS5 trigram alone fails this:
            fts_hits = _run(store.fts5_match("riemanroch", None, 10))
            assert fts_hits == []
            # Jaccard succeeds:
            jac_hits = _run(store.fuzzy_jaccard("riemanroch", None, 10))
            assert len(jac_hits) == 1
            assert jac_hits[0].display_name == "Riemann-Roch"
        finally:
            _run(store.close())

    def test_upsert_replaces_existing(self, tmp_path):
        db_path = tmp_path / "theorem_names.db"
        store = _run(TheoremNamesStore.open(db_path))
        try:
            row_v1 = TheoremRow(
                dedup_key=dedup_key("2401.00001", "Yoneda Lemma", "[]"),
                paper_id="2401.00001",
                chunk_id="arxiv:2401.00001:0000000000000001",
                theorem_name="Yoneda Lemma",
                display_name="Yoneda Lemma",
                section_path=[],
                confidence=0.5,
            )
            row_v2 = TheoremRow(
                dedup_key=row_v1.dedup_key,
                paper_id="2401.00001",
                chunk_id="arxiv:2401.00001:0000000000000002",  # changed
                theorem_name="Yoneda Lemma",
                display_name="Yoneda Lemma",
                section_path=[],
                confidence=1.0,
            )
            _run(store.upsert_rows([row_v1]))
            _run(store.upsert_rows([row_v2]))
            assert _run(store.row_count()) == 1
            matches = _run(store.exact_match("yonedalemma", None, 10))
            assert matches[0].confidence == 1.0
            assert matches[0].chunk_id == "arxiv:2401.00001:0000000000000002"
        finally:
            _run(store.close())

    def test_delete_paper_clears_fts(self, tmp_path):
        db_path = tmp_path / "theorem_names.db"
        store = _run(TheoremNamesStore.open(db_path))
        try:
            rows = [
                TheoremRow(
                    dedup_key=dedup_key("2401.00001", "Yoneda Lemma", "[]"),
                    paper_id="2401.00001",
                    chunk_id="arxiv:2401.00001:0000000000000001",
                    theorem_name="Yoneda Lemma",
                    display_name="Yoneda Lemma",
                    section_path=[],
                    confidence=1.0,
                )
            ]
            _run(store.upsert_rows(rows))
            n = _run(store.delete_paper("2401.00001"))
            assert n == 1
            assert _run(store.row_count()) == 0
            # FTS5 cleared too.
            assert _run(store.fts5_match("yoneda", None, 10)) == []
        finally:
            _run(store.close())

    def test_fts5_phrase_quote_blocks_injection(self, tmp_path):
        """FTS5 MATCH injection guard — passing a query with FTS5
        special characters must not raise.
        """
        db_path = tmp_path / "theorem_names.db"
        store = _run(TheoremNamesStore.open(db_path))
        try:
            rows = [
                TheoremRow(
                    dedup_key=dedup_key("2401.00001", "Yoneda Lemma", "[]"),
                    paper_id="2401.00001",
                    chunk_id="arxiv:2401.00001:0000000000000001",
                    theorem_name="Yoneda Lemma",
                    display_name="Yoneda Lemma",
                    section_path=[],
                    confidence=1.0,
                )
            ]
            _run(store.upsert_rows(rows))
            # The attacker payload — without phrase-quoting this is
            # an FTS5 query syntax error. With phrase-quoting in the
            # store, it returns an empty match without raising.
            result = _run(store.fts5_match('OR NOT * "', None, 10))
            assert result == []
            # F1 regression — NUL byte in the user query previously
            # raised sqlite3.OperationalError("unterminated string").
            # Phrase-quote now strips controls; this returns an
            # empty match cleanly.
            nul_result = _run(store.fts5_match("yon\x00eda", None, 10))
            assert isinstance(nul_result, list)
        finally:
            _run(store.close())


# ===========================================================================
# Indexer
# ===========================================================================


def _chunks_table_from_records(
    tmp_path: Path, records: list[dict[str, Any]]
) -> Any:
    """Build a real LanceDB chunks table seeded with the given rows.

    Each ``records`` entry needs (at minimum) chunk_id, paper_id,
    kind, theorem_name, section_path. Other columns get sensible
    defaults to satisfy the schema.
    """
    import lancedb

    from ingest.embedder import EMBEDDING_DIM

    rows: list[dict[str, Any]] = []
    for ch in records:
        rows.append(
            {
                "chunk_id": ch["chunk_id"],
                "paper_id": ch["paper_id"],
                "kind": ch.get("kind", "stmt"),
                "section_path": ch.get("section_path", []),
                "theorem_name": ch.get("theorem_name"),
                "theorem_label": ch.get("theorem_label"),
                "body_text": ch.get("body_text", ""),
                "body_tokens": ch.get("body_tokens", ""),
                "embedding_stmt": [0.0] * EMBEDDING_DIM,
                "embedding_proof": None,
                "embedding_eq": None,
                "chunker_version": "test",
                "embedder_version": "test",
                "preamble_ref": None,
            }
        )
    arrow_table = pa.Table.from_pylist(rows, schema=CHUNKS_SCHEMA_V1)
    db = lancedb.connect(str(tmp_path))
    return db.create_table("chunks", data=arrow_table)


class TestIndexer:
    def test_builds_rows_from_chunks(self, tmp_path):
        ct = _chunks_table_from_records(
            tmp_path,
            [
                {
                    "chunk_id": "arxiv:2401.00001:0000000000000001",
                    "paper_id": "2401.00001",
                    "theorem_name": "Yoneda Lemma",
                    "section_path": ["3. Main results"],
                },
                {
                    "chunk_id": "arxiv:2401.00001:0000000000000002",
                    "paper_id": "2401.00001",
                    "theorem_name": None,  # skipped
                },
                {
                    "chunk_id": "arxiv:2401.00002:0000000000000001",
                    "paper_id": "2401.00002",
                    "theorem_name": "Lemma 3.4",
                },
            ],
        )
        arrow = ct.to_arrow()
        rows = build_rows_from_chunks_for_paper(arrow, "2401.00001")
        # Only the row for 2401.00001 with a non-null theorem_name.
        assert len(rows) == 1
        assert rows[0].theorem_name == "Yoneda Lemma"

    def test_idempotent_per_paper(self, tmp_path):
        ct = _chunks_table_from_records(
            tmp_path,
            [
                {
                    "chunk_id": "arxiv:2401.00001:0000000000000001",
                    "paper_id": "2401.00001",
                    "theorem_name": "Yoneda Lemma",
                },
                {
                    "chunk_id": "arxiv:2401.00001:0000000000000002",
                    "paper_id": "2401.00001",
                    "theorem_name": "Riemann-Roch",
                },
            ],
        )
        db_path = tmp_path / "theorem_names.db"
        store = _run(TheoremNamesStore.open(db_path))
        try:
            n1 = _run(index_theorem_names_for_paper("2401.00001", ct, store))
            n2 = _run(index_theorem_names_for_paper("2401.00001", ct, store))
            assert n1 == 2
            assert n2 == 2
            # Row count stays at 2 — no orphan duplicates.
            assert _run(store.row_count()) == 2
        finally:
            _run(store.close())

    def test_ac1_two_papers_same_lemma_label(self, tmp_path):
        """AC1 end-to-end — two papers each with a "Lemma 3.4"
        produce two separate rows.
        """
        ct = _chunks_table_from_records(
            tmp_path,
            [
                {
                    "chunk_id": "arxiv:2401.00001:0000000000000001",
                    "paper_id": "2401.00001",
                    "theorem_name": "Lemma 3.4",
                },
                {
                    "chunk_id": "arxiv:2401.00002:0000000000000001",
                    "paper_id": "2401.00002",
                    "theorem_name": "Lemma 3.4",
                },
            ],
        )
        db_path = tmp_path / "theorem_names.db"
        store = _run(TheoremNamesStore.open(db_path))
        try:
            _run(index_theorem_names_for_paper("2401.00001", ct, store))
            _run(index_theorem_names_for_paper("2401.00002", ct, store))
            assert _run(store.row_count()) == 2
        finally:
            _run(store.close())


# ===========================================================================
# Handler
# ===========================================================================


@dataclass
class _MinimalConfig:
    lancedb_path: Path
    result_byte_cap: int = 256_000


@dataclass
class _MinimalCorpus:
    version: int = 1


@dataclass
class _MinimalResources:
    config: _MinimalConfig
    corpus_info: _MinimalCorpus
    chunks_table: Any
    theorem_names_db: Any | None


def _install_resources(
    chunks_table: Any, theorem_names_db: Any | None, tmp_path: Path
) -> None:
    res = _MinimalResources(
        config=_MinimalConfig(lancedb_path=tmp_path),
        corpus_info=_MinimalCorpus(),
        chunks_table=chunks_table,
        theorem_names_db=theorem_names_db,
    )
    server_tools._RESOURCES = res


class TestHandler:
    def test_falls_back_to_in_memory_when_db_absent(self, tmp_path):
        ct = _chunks_table_from_records(
            tmp_path,
            [
                {
                    "chunk_id": "arxiv:2401.00001:0000000000000001",
                    "paper_id": "2401.00001",
                    "theorem_name": "Yoneda Lemma",
                }
            ],
        )
        _install_resources(ct, theorem_names_db=None, tmp_path=tmp_path)
        try:
            result = _run(
                lemma_handler_mod.handle_find_lemma_by_name(name="Yoneda")
            )
        finally:
            server_tools._RESOURCES = None
        assert result["retrieval_mode"] == "in_memory_scan_fallback"
        assert len(result["matches"]) == 1
        match = result["matches"][0]
        assert match["display_name"] == "Yoneda Lemma"
        # F3 regression (E10_S02 critique) — fallback rows now
        # carry a synthesized dedup_key matching the indexer's
        # recipe, not None.
        assert match["dedup_key"] is not None
        assert len(match["dedup_key"]) == 16

    def test_ac2_yoneda_across_papers(self, tmp_path):
        """AC2 — `find_lemma_by_name("Yoneda lemma")` returns
        results across all indexed papers.
        """
        ct = _chunks_table_from_records(
            tmp_path,
            [
                {
                    "chunk_id": "arxiv:2401.00001:0000000000000001",
                    "paper_id": "2401.00001",
                    "theorem_name": "Yoneda Lemma",
                },
                {
                    "chunk_id": "arxiv:2401.00002:0000000000000001",
                    "paper_id": "2401.00002",
                    "theorem_name": "Yoneda Lemma",
                },
            ],
        )
        db_path = tmp_path / "theorem_names.db"
        store = _run(TheoremNamesStore.open(db_path))
        try:
            _run(index_theorem_names_for_paper("2401.00001", ct, store))
            _run(index_theorem_names_for_paper("2401.00002", ct, store))
            _install_resources(ct, theorem_names_db=store, tmp_path=tmp_path)
            try:
                result = _run(
                    lemma_handler_mod.handle_find_lemma_by_name(name="Yoneda lemma")
                )
            finally:
                server_tools._RESOURCES = None
            assert result["retrieval_mode"] == "fts5_exact"
            assert len(result["matches"]) == 2
            assert {m["paper_id"] for m in result["matches"]} == {
                "2401.00001",
                "2401.00002",
            }
        finally:
            _run(store.close())

    def test_ac3_paper_id_filter(self, tmp_path):
        """AC3 — paper_id filter restricts to one paper."""
        ct = _chunks_table_from_records(
            tmp_path,
            [
                {
                    "chunk_id": "arxiv:2401.00001:0000000000000001",
                    "paper_id": "2401.00001",
                    "theorem_name": "Yoneda Lemma",
                },
                {
                    "chunk_id": "arxiv:2401.00002:0000000000000001",
                    "paper_id": "2401.00002",
                    "theorem_name": "Yoneda Lemma",
                },
            ],
        )
        db_path = tmp_path / "theorem_names.db"
        store = _run(TheoremNamesStore.open(db_path))
        try:
            _run(index_theorem_names_for_paper("2401.00001", ct, store))
            _run(index_theorem_names_for_paper("2401.00002", ct, store))
            _install_resources(ct, theorem_names_db=store, tmp_path=tmp_path)
            try:
                result = _run(
                    lemma_handler_mod.handle_find_lemma_by_name(
                        name="Yoneda lemma", paper_id="2401.00001"
                    )
                )
            finally:
                server_tools._RESOURCES = None
            assert len(result["matches"]) == 1
            assert result["matches"][0]["paper_id"] == "2401.00001"
        finally:
            _run(store.close())

    def test_ac4_typo_routes_through_fuzzy_jaccard(self, tmp_path):
        """AC4 — `find_lemma_by_name("riemanroch")` returns
        "Riemann-Roch" entries via the Jaccard fallback path.
        """
        ct = _chunks_table_from_records(
            tmp_path,
            [
                {
                    "chunk_id": "arxiv:2401.00001:0000000000000001",
                    "paper_id": "2401.00001",
                    "theorem_name": "Riemann-Roch",
                }
            ],
        )
        db_path = tmp_path / "theorem_names.db"
        store = _run(TheoremNamesStore.open(db_path))
        try:
            _run(index_theorem_names_for_paper("2401.00001", ct, store))
            _install_resources(ct, theorem_names_db=store, tmp_path=tmp_path)
            try:
                result = _run(
                    lemma_handler_mod.handle_find_lemma_by_name(name="riemanroch")
                )
            finally:
                server_tools._RESOURCES = None
            assert result["retrieval_mode"] == "fuzzy_jaccard"
            assert len(result["matches"]) == 1
            assert result["matches"][0]["display_name"] == "Riemann-Roch"
        finally:
            _run(store.close())

    def test_response_shape_carries_new_fields(self, tmp_path):
        ct = _chunks_table_from_records(
            tmp_path,
            [
                {
                    "chunk_id": "arxiv:2401.00001:0000000000000001",
                    "paper_id": "2401.00001",
                    "theorem_name": "Yoneda Lemma",
                }
            ],
        )
        db_path = tmp_path / "theorem_names.db"
        store = _run(TheoremNamesStore.open(db_path))
        try:
            _run(index_theorem_names_for_paper("2401.00001", ct, store))
            _install_resources(ct, theorem_names_db=store, tmp_path=tmp_path)
            try:
                result = _run(
                    lemma_handler_mod.handle_find_lemma_by_name(name="Yoneda lemma")
                )
            finally:
                server_tools._RESOURCES = None
            match = result["matches"][0]
            # Back-compat fields:
            assert "chunk_id" in match
            assert "paper_id" in match
            assert "section_path" in match
            assert "theorem_name" in match
            # New fields:
            assert "dedup_key" in match
            assert "display_name" in match
            assert "confidence" in match
            assert match["confidence"] == 1.0
        finally:
            _run(store.close())

    def test_paper_id_validation_still_enforced(self, tmp_path):
        ct = _chunks_table_from_records(tmp_path, [])
        _install_resources(ct, theorem_names_db=None, tmp_path=tmp_path)
        try:
            with pytest.raises(ValueError, match="paper_id"):
                _run(
                    lemma_handler_mod.handle_find_lemma_by_name(
                        name="x", paper_id="../../../etc"
                    )
                )
        finally:
            server_tools._RESOURCES = None

    def test_all_punctuation_name_returns_empty_with_distinct_mode(
        self, tmp_path
    ):
        """F4 regression (E10_S02 critique) — a name that collapses
        to "" under normalization (e.g. all-punctuation or
        all-whitespace) must use the dedicated
        ``empty_after_normalization`` mode tag so downstream agents
        can distinguish "garbage input" from "exact match found
        nothing." The previous implementation reported
        ``fts5_exact`` for this case, conflating the two outcomes.
        """
        ct = _chunks_table_from_records(tmp_path, [])
        db_path = tmp_path / "theorem_names.db"
        store = _run(TheoremNamesStore.open(db_path))
        try:
            _install_resources(ct, theorem_names_db=store, tmp_path=tmp_path)
            try:
                punctuation_result = _run(
                    lemma_handler_mod.handle_find_lemma_by_name(name="...!?")
                )
                whitespace_result = _run(
                    lemma_handler_mod.handle_find_lemma_by_name(name=" ")
                )
            finally:
                server_tools._RESOURCES = None
            for result in (punctuation_result, whitespace_result):
                assert result["matches"] == []
                assert result["retrieval_mode"] == "empty_after_normalization"
        finally:
            _run(store.close())
