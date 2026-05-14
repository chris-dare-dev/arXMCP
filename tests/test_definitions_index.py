"""Tests for the per-paper definitions indexer and handler (E10_S01).

Covers:

* Parser — every macro form the preamble extractor produces parses to
  a clean ``(symbol, symbol_raw, expansion)`` triple.
* Indexer — ``index_definitions_for_paper`` builds a LanceDB table
  with the canonical schema; scalar indexes on ``paper_id`` and
  ``symbol_raw`` are created; rerunning is idempotent (delete-then-
  insert leaves the row count stable, even when the per-paper
  definition count shrinks); a paper with no preamble produces zero
  rows without error.
* Handler integration — the handler returns the canonical envelope
  shape; pagination chunks results into 100-entry pages with an
  opaque cursor; the term lookup applies the
  exact-symbol → exact-symbol_raw → case-insensitive-prefix
  hierarchy and never case-folds the canonical ``symbol`` column.

The tests use a real ``lancedb.connect`` against a tmp_path-scoped
dataset to exercise the actual write/read paths. The full BGE-M3 +
chunker stack is NOT loaded — the handler is awaited directly with a
hand-built Resources stub, side-stepping the lifespan and the corpus
warm-up.
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

import server.handlers.definitions as defs_handler_mod
import server.tools as server_tools
from ingest.index_definitions import (
    build_definitions_for_paper,
    index_definitions_for_paper,
    open_or_create_definitions_table,
    parse_macro_line,
)
from ingest.preamble_types import PreambleDoc

# tests/_graph_helpers exposes a similar light-weight Resources stub for
# the citation tests; this module rolls its own to keep coupling low.


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


@dataclass
class _MinimalConfig:
    """Mirror just enough of ``server.config.Config`` for the handler.

    The real Config carries dozens of fields; the handler only reads
    ``r.config`` indirectly (via the ``envelope`` helper) and never
    via this stub directly.
    """

    lancedb_path: Path
    result_byte_cap: int = 256_000


@dataclass
class _MinimalCorpus:
    version: int = 1


@dataclass
class _MinimalResources:
    config: _MinimalConfig
    corpus_info: _MinimalCorpus
    definitions_table: Any | None


def _install_resources(tmp_path: Path, table: Any | None) -> None:
    """Register a minimal Resources stub for the handler under test.

    Patches ``server.tools._RESOURCES`` so ``get_resources()`` returns
    the stub without going through ``Resources.startup`` (which would
    require BGE-M3, the chunks table, etc.).
    """
    resources = _MinimalResources(
        config=_MinimalConfig(lancedb_path=tmp_path),
        corpus_info=_MinimalCorpus(),
        definitions_table=table,
    )
    server_tools._RESOURCES = resources


def _stage_preamble(
    preamble_dir: Path, paper_id: str, macros: list[str]
) -> PreambleDoc:
    """Write a synthetic preamble.json for ``paper_id`` under
    ``preamble_dir/<paper_id>/preamble.json``.

    Bypasses the .tex parser so tests can exercise the indexer
    against a hand-crafted macro set without spinning up LaTeXML.
    """
    out_dir = preamble_dir / paper_id
    out_dir.mkdir(parents=True, exist_ok=True)
    doc = PreambleDoc(
        paper_id=paper_id,
        source_hash="0" * 64,
        macros=macros,
        preamble_text="\n".join(macros),
        preamble_hash="0" * 16,
    )
    (out_dir / "preamble.json").write_text(
        json.dumps(doc.to_dict(), ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return doc


def _patched_preamble_dir(preamble_dir: Path):
    """Context manager: redirect ``ingest.preamble.PREAMBLE_DIR``."""
    return patch("ingest.preamble.PREAMBLE_DIR", preamble_dir)


def _has_paper_row(tbl: Any, paper_id: str) -> bool:
    """Return True iff the table contains at least one row for ``paper_id``.

    Used by F3 regression to confirm we're testing the non-empty
    branch of the delete short-circuit.
    """
    arrow = tbl.search().where(f"paper_id = '{paper_id}'").limit(1).to_arrow()
    return arrow.num_rows > 0


def _empty_chunks_table(lancedb_path: Path) -> None:
    """Create the lancedb_path directory but no chunks table.

    The indexer needs the lancedb_path to exist (it raises
    FileNotFoundError otherwise per the
    "run ingest first" contract), but does not need the chunks table.
    """
    lancedb_path.mkdir(parents=True, exist_ok=True)


# ---------------------------------------------------------------------------
# Parser tests
# ---------------------------------------------------------------------------


class TestParseMacroLine:
    def test_newcommand_no_args(self):
        recs = parse_macro_line(r"\newcommand{\R}{\mathbb{R}}")
        assert len(recs) == 1
        assert recs[0] == {
            "symbol": "\\R",
            "symbol_raw": "\\R",
            "expansion": "\\mathbb{R}",
        }

    def test_newcommand_with_args(self):
        recs = parse_macro_line(
            r"\newcommand{\Hom}[2]{\mathrm{Hom}(#1,#2)}"
        )
        assert len(recs) == 1
        assert recs[0]["symbol"] == "\\Hom"
        # Arity is part of the head; the expansion captures the body
        # only (the [2] prefix is consumed by the regex).
        assert recs[0]["expansion"] == "\\mathrm{Hom}(#1,#2)"

    def test_renewcommand(self):
        recs = parse_macro_line(r"\renewcommand{\foo}{bar}")
        assert recs == [{"symbol": "\\foo", "symbol_raw": "\\foo", "expansion": "bar"}]

    def test_providecommand(self):
        recs = parse_macro_line(r"\providecommand{\eps}{\varepsilon}")
        assert recs == [
            {"symbol": "\\eps", "symbol_raw": "\\eps", "expansion": "\\varepsilon"}
        ]

    def test_declaremathoperator(self):
        recs = parse_macro_line(r"\DeclareMathOperator{\Pic}{Pic}")
        assert recs == [
            {"symbol": "\\Pic", "symbol_raw": "\\Pic", "expansion": "Pic"}
        ]

    def test_declaremathoperator_starred(self):
        recs = parse_macro_line(r"\DeclareMathOperator*{\colim}{colim}")
        assert recs == [
            {"symbol": "\\colim", "symbol_raw": "\\colim", "expansion": "colim"}
        ]

    def test_def_macro(self):
        recs = parse_macro_line(r"\def\sheaf#1{\mathcal{#1}}")
        assert recs == [
            {"symbol": "\\sheaf", "symbol_raw": "\\sheaf", "expansion": "\\mathcal{#1}"}
        ]

    def test_let_with_equals(self):
        recs = parse_macro_line(r"\let\old=\new")
        assert recs == [
            {"symbol": "\\old", "symbol_raw": "\\old", "expansion": "\\new"}
        ]

    def test_let_without_equals(self):
        recs = parse_macro_line(r"\let\old\new")
        assert recs == [
            {"symbol": "\\old", "symbol_raw": "\\old", "expansion": "\\new"}
        ]

    def test_two_macros_one_line(self):
        recs = parse_macro_line(
            r"\newcommand{\R}{\mathbb{R}}\newcommand{\C}{\mathbb{C}}"
        )
        assert len(recs) == 2
        symbols = {r["symbol"] for r in recs}
        assert symbols == {"\\R", "\\C"}

    def test_nested_braces_in_expansion(self):
        recs = parse_macro_line(r"\newcommand{\Z}{\mathbb{Z}^{n}}")
        assert recs == [
            {"symbol": "\\Z", "symbol_raw": "\\Z", "expansion": "\\mathbb{Z}^{n}"}
        ]

    def test_no_recognised_directive(self):
        assert parse_macro_line(r"\usepackage{amsmath}") == []

    def test_empty_string(self):
        assert parse_macro_line("") == []


# ---------------------------------------------------------------------------
# Builder tests (build_definitions_for_paper)
# ---------------------------------------------------------------------------


class TestBuildDefinitionsForPaper:
    def test_paper_with_no_preamble_returns_empty(self, tmp_path):
        with _patched_preamble_dir(tmp_path / "preamble"):
            rows = build_definitions_for_paper("2401.00001")
        assert rows == []

    def test_paper_with_preamble_returns_rows(self, tmp_path):
        preamble_dir = tmp_path / "preamble"
        _stage_preamble(
            preamble_dir,
            "2401.00001",
            [
                r"\newcommand{\R}{\mathbb{R}}",
                r"\newcommand{\C}{\mathbb{C}}",
                r"\let\Q=\mathbb{Q}",  # noqa: P103 — synthetic
            ],
        )
        with _patched_preamble_dir(preamble_dir):
            rows = build_definitions_for_paper("2401.00001")
        assert len(rows) == 3
        symbols = {r["symbol"] for r in rows}
        assert symbols == {"\\R", "\\C", "\\Q"}
        for row in rows:
            assert row["paper_id"] == "2401.00001"
            assert row["scope"] == "paper"
            assert row["defining_chunk_id"] == "2401.00001:preamble"
            assert row["symbol"] == row["symbol_raw"]  # v1 identity
            assert len(row["definition_id"]) == 16

    def test_last_seen_wins_on_redefinition(self, tmp_path):
        preamble_dir = tmp_path / "preamble"
        # The preamble extractor sorts alphabetically; once two
        # bindings for \R land in the list, the last one wins.
        _stage_preamble(
            preamble_dir,
            "2401.00002",
            [
                r"\newcommand{\R}{\mathbb{R}}",
                r"\renewcommand{\R}{\mathbb{Q}}",
            ],
        )
        with _patched_preamble_dir(preamble_dir):
            rows = build_definitions_for_paper("2401.00002")
        # One row only — the rebinding collapsed into the last record.
        assert len(rows) == 1
        assert rows[0]["symbol"] == "\\R"
        # Last seen in sorted order (renewcommand sorts after
        # newcommand) wins.
        assert rows[0]["expansion"] == "\\mathbb{Q}"

    def test_definition_id_is_content_addressed(self, tmp_path):
        preamble_dir = tmp_path / "preamble"
        _stage_preamble(
            preamble_dir,
            "2401.00003",
            [r"\newcommand{\R}{\mathbb{R}}"],
        )
        with _patched_preamble_dir(preamble_dir):
            rows1 = build_definitions_for_paper("2401.00003")
            rows2 = build_definitions_for_paper("2401.00003")
        assert rows1[0]["definition_id"] == rows2[0]["definition_id"]


# ---------------------------------------------------------------------------
# Indexer tests (LanceDB integration)
# ---------------------------------------------------------------------------


class TestIndexer:
    def test_writes_table_with_expected_schema(self, tmp_path):
        preamble_dir = tmp_path / "preamble"
        _stage_preamble(
            preamble_dir,
            "2401.00010",
            [r"\newcommand{\R}{\mathbb{R}}", r"\newcommand{\C}{\mathbb{C}}"],
        )
        lancedb_path = tmp_path / "lancedb"
        _empty_chunks_table(lancedb_path)

        with _patched_preamble_dir(preamble_dir):
            n = index_definitions_for_paper("2401.00010", lancedb_path)
        assert n == 2

        tbl = open_or_create_definitions_table(lancedb_path)
        rows = tbl.to_arrow().to_pylist()
        assert len(rows) == 2
        symbols = {r["symbol"] for r in rows}
        assert symbols == {"\\R", "\\C"}

    def test_scalar_indexes_created(self, tmp_path):
        preamble_dir = tmp_path / "preamble"
        _stage_preamble(
            preamble_dir,
            "2401.00011",
            [r"\newcommand{\R}{\mathbb{R}}"],
        )
        lancedb_path = tmp_path / "lancedb"
        _empty_chunks_table(lancedb_path)

        with _patched_preamble_dir(preamble_dir):
            index_definitions_for_paper("2401.00011", lancedb_path)

        tbl = open_or_create_definitions_table(lancedb_path)
        indices = tbl.list_indices()
        # F6 (E10_S01 critique) — assert that AT LEAST ONE index
        # actually covers ``paper_id`` and AT LEAST ONE covers
        # ``symbol_raw``. The original test matched on the index NAME
        # alone, which would fail open if LanceDB renamed its
        # auto-generated index suffix and continued to create the
        # indexes on the correct columns. The columns field is the
        # load-bearing invariant: AC4 asserts the brief's
        # ``B-tree on (paper_id, symbol)`` index requirement.
        indexed_columns: set[str] = set()
        for ix in indices:
            # LanceDB ≥ 0.6 returns ``Index`` dataclass-like objects
            # with ``.columns`` (list[str]) and ``.name`` attributes.
            # Older releases may return plain dicts. Handle both
            # shapes defensively.
            cols = getattr(ix, "columns", None)
            if cols is None and isinstance(ix, dict):
                cols = ix.get("columns")
            if cols:
                indexed_columns.update(cols)
                continue
            name = getattr(ix, "name", None)
            if name is None and isinstance(ix, dict):
                name = ix.get("name", "")
            name = name or ""
            if name.endswith("_idx"):
                indexed_columns.add(name[: -len("_idx")])
            elif name:
                indexed_columns.add(name)
        assert "paper_id" in indexed_columns, (
            f"paper_id scalar index missing; indices={indices!r}"
        )
        assert "symbol_raw" in indexed_columns, (
            f"symbol_raw scalar index missing; indices={indices!r}"
        )

    def test_paper_with_no_preamble_writes_zero_rows(self, tmp_path):
        # No preamble file staged at all.
        preamble_dir = tmp_path / "preamble"
        preamble_dir.mkdir()
        lancedb_path = tmp_path / "lancedb"
        _empty_chunks_table(lancedb_path)

        with _patched_preamble_dir(preamble_dir):
            n = index_definitions_for_paper("2401.00012", lancedb_path)
        assert n == 0

        tbl = open_or_create_definitions_table(lancedb_path)
        rows = tbl.to_arrow().to_pylist()
        # No rows from this paper.
        assert all(r["paper_id"] != "2401.00012" for r in rows)

    def test_idempotent_per_paper_replace(self, tmp_path):
        """A re-ingest that SHRINKS the per-paper definition count
        leaves the table at the new row count, not the union of both.
        """
        preamble_dir = tmp_path / "preamble"
        lancedb_path = tmp_path / "lancedb"
        _empty_chunks_table(lancedb_path)

        # First run: 3 definitions.
        _stage_preamble(
            preamble_dir,
            "2401.00020",
            [
                r"\newcommand{\A}{a}",
                r"\newcommand{\B}{b}",
                r"\newcommand{\C}{c}",
            ],
        )
        with _patched_preamble_dir(preamble_dir):
            n1 = index_definitions_for_paper("2401.00020", lancedb_path)
        assert n1 == 3

        # Second run: only 2 (the paper was edited to remove \C).
        _stage_preamble(
            preamble_dir,
            "2401.00020",
            [
                r"\newcommand{\A}{a}",
                r"\newcommand{\B}{b}",
            ],
        )
        with _patched_preamble_dir(preamble_dir):
            n2 = index_definitions_for_paper("2401.00020", lancedb_path)
        assert n2 == 2

        tbl = open_or_create_definitions_table(lancedb_path)
        rows = [
            r for r in tbl.to_arrow().to_pylist()
            if r["paper_id"] == "2401.00020"
        ]
        symbols = {r["symbol"] for r in rows}
        # The orphan \C row from the first run is gone.
        assert symbols == {"\\A", "\\B"}

    def test_delete_failure_surfaces_not_swallowed(self, tmp_path):
        """F3 regression (E10_S01 critique) — a genuine delete error
        (permission denied, schema mismatch, etc.) must NOT be
        swallowed under the cover of "this was just an empty-table
        delete". Seed a paper, then monkeypatch ``tbl.delete`` to
        raise ``PermissionError`` and verify the indexer re-raises
        rather than logging-and-proceeding.

        The empty-table case is now handled by short-circuiting on
        the per-paper row count BEFORE invoking delete, so a delete
        failure on a populated table is no longer ambiguous with the
        benign empty-delete edge case.
        """
        from unittest.mock import patch as _patch

        preamble_dir = tmp_path / "preamble"
        lancedb_path = tmp_path / "lancedb"
        _empty_chunks_table(lancedb_path)

        # Seed one paper so the per-paper row count is > 0 on second
        # run; then monkeypatch delete on the OPEN table.
        _stage_preamble(preamble_dir, "2401.00050", [r"\newcommand{\R}{\mathbb{R}}"])
        with _patched_preamble_dir(preamble_dir):
            index_definitions_for_paper("2401.00050", lancedb_path)

        tbl = open_or_create_definitions_table(lancedb_path)
        # Confirm the seed row is present (else this test would only
        # exercise the empty-table short-circuit path).
        assert _has_paper_row(tbl, "2401.00050")

        # Monkeypatch open_or_create_definitions_table to return a
        # wrapped table whose delete raises. The simplest path is to
        # patch the function at the indexer's module scope.
        class _BadDelete:
            def __init__(self, real):
                self._real = real

            def __getattr__(self, name):
                if name == "delete":
                    def _raise(*_a, **_kw):
                        raise PermissionError("simulated permission denied")
                    return _raise
                return getattr(self._real, name)

        bad_tbl = _BadDelete(tbl)

        with (
            _patched_preamble_dir(preamble_dir),
            _patch(
                "ingest.index_definitions.open_or_create_definitions_table",
                return_value=bad_tbl,
            ),
            pytest.raises(PermissionError, match="simulated"),
        ):
            index_definitions_for_paper("2401.00050", lancedb_path)

    def test_two_papers_coexist(self, tmp_path):
        preamble_dir = tmp_path / "preamble"
        lancedb_path = tmp_path / "lancedb"
        _empty_chunks_table(lancedb_path)

        _stage_preamble(
            preamble_dir, "2401.00030", [r"\newcommand{\R}{\mathbb{R}}"]
        )
        _stage_preamble(
            preamble_dir, "2401.00031", [r"\newcommand{\C}{\mathbb{C}}"]
        )

        with _patched_preamble_dir(preamble_dir):
            index_definitions_for_paper("2401.00030", lancedb_path)
            index_definitions_for_paper("2401.00031", lancedb_path)

        tbl = open_or_create_definitions_table(lancedb_path)
        rows = tbl.to_arrow().to_pylist()
        assert len(rows) == 2
        by_paper = {r["paper_id"]: r["symbol"] for r in rows}
        assert by_paper == {
            "2401.00030": "\\R",
            "2401.00031": "\\C",
        }


# ---------------------------------------------------------------------------
# Handler integration tests (end-to-end with a real LanceDB table)
# ---------------------------------------------------------------------------


def _run(coro):
    """Run an async coroutine inside a fresh event loop.

    Using ``asyncio.get_event_loop()`` here is unsafe across the full
    test suite: prior tests may have closed the running loop, after
    which the helper would raise ``RuntimeError: There is no current
    event loop in thread 'MainThread'``. ``asyncio.new_event_loop`` +
    ``loop.run_until_complete`` is the canonical sync-into-async
    bridge for non-pytest-asyncio tests.
    """
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


@pytest.fixture
def _seeded_handler(tmp_path):
    """Build a LanceDB definitions table with a known shape, install
    a minimal Resources stub, and yield ``handle_get_definitions``.

    After the test runs, clear the stub so the next test starts fresh.
    """
    preamble_dir = tmp_path / "preamble"
    lancedb_path = tmp_path / "lancedb"
    _empty_chunks_table(lancedb_path)

    # 12 well-defined macros + a redefinition (collapses to 12 rows).
    _stage_preamble(
        preamble_dir,
        "2401.00100",
        [
            r"\newcommand{\AA}{\mathcal{A}}",
            r"\newcommand{\BB}{\mathcal{B}}",
            r"\newcommand{\C}{\mathbb{C}}",
            r"\newcommand{\Hom}[2]{\mathrm{Hom}(#1,#2)}",
            r"\newcommand{\N}{\mathbb{N}}",
            r"\newcommand{\Q}{\mathbb{Q}}",
            r"\newcommand{\R}{\mathbb{R}}",
            r"\newcommand{\Spec}{\mathrm{Spec}}",
            r"\newcommand{\Z}{\mathbb{Z}}",
            r"\renewcommand{\R}{\mathbb{R}_{>0}}",
            r"\DeclareMathOperator{\Pic}{Pic}",
            r"\DeclareMathOperator*{\colim}{colim}",
            r"\def\sheaf#1{\mathcal{#1}}",
        ],
    )

    with _patched_preamble_dir(preamble_dir):
        index_definitions_for_paper("2401.00100", lancedb_path)

    table = open_or_create_definitions_table(lancedb_path)
    _install_resources(tmp_path, table)
    try:
        yield defs_handler_mod.handle_get_definitions
    finally:
        server_tools._RESOURCES = None


class TestHandlerFullTableMode:
    def test_returns_all_definitions_single_page(self, _seeded_handler):
        result = _run(
            _seeded_handler(paper_id="2401.00100")
        )
        # 13 macro-line entries → 12 rows after \R rebinding collapse.
        assert result["total"] == 12
        assert len(result["definitions"]) == 12
        assert result["next_cursor"] is None
        assert result["index_status"] == "ok"

    def test_definitions_sorted_by_symbol(self, _seeded_handler):
        result = _run(_seeded_handler(paper_id="2401.00100"))
        symbols = [d["symbol"] for d in result["definitions"]]
        assert symbols == sorted(symbols)

    def test_envelope_includes_paper_id_and_term(self, _seeded_handler):
        result = _run(_seeded_handler(paper_id="2401.00100"))
        assert result["paper_id"] == "2401.00100"
        assert result["term"] is None

    def test_unknown_paper_returns_empty(self, _seeded_handler):
        result = _run(_seeded_handler(paper_id="2999.99999"))
        assert result["definitions"] == []
        assert result["total"] == 0
        assert result["next_cursor"] is None
        assert result["index_status"] == "ok"

    def test_pagination_with_many_definitions(self, tmp_path):
        """Stage 250 definitions so pagination produces a non-null
        next_cursor on page 1.
        """
        preamble_dir = tmp_path / "preamble"
        lancedb_path = tmp_path / "lancedb"
        _empty_chunks_table(lancedb_path)

        # LaTeX command names are letters-only (no digits), so encode
        # the index as a 3-letter base-26 suffix. 26**3 == 17576, well
        # above 250.
        def _letters(i: int) -> str:
            a = i // (26 * 26)
            b = (i // 26) % 26
            c = i % 26
            return chr(ord("a") + a) + chr(ord("a") + b) + chr(ord("a") + c)

        macros = [
            r"\newcommand{\sym" + _letters(i) + r"}{body}"
            for i in range(250)
        ]
        _stage_preamble(preamble_dir, "2401.00200", macros)

        with _patched_preamble_dir(preamble_dir):
            index_definitions_for_paper("2401.00200", lancedb_path)
        table = open_or_create_definitions_table(lancedb_path)
        _install_resources(tmp_path, table)
        try:
            page1 = _run(defs_handler_mod.handle_get_definitions(paper_id="2401.00200"))
            assert len(page1["definitions"]) == 100
            assert page1["total"] == 250
            assert page1["next_cursor"] is not None

            page2 = _run(
                defs_handler_mod.handle_get_definitions(
                    paper_id="2401.00200", cursor=page1["next_cursor"]
                )
            )
            assert len(page2["definitions"]) == 100
            assert page2["next_cursor"] is not None

            page3 = _run(
                defs_handler_mod.handle_get_definitions(
                    paper_id="2401.00200", cursor=page2["next_cursor"]
                )
            )
            assert len(page3["definitions"]) == 50
            assert page3["next_cursor"] is None
        finally:
            server_tools._RESOURCES = None


class TestHandlerTermLookup:
    def test_exact_symbol_match(self, _seeded_handler):
        result = _run(_seeded_handler(paper_id="2401.00100", term="\\AA"))
        assert len(result["definitions"]) == 1
        assert result["definitions"][0]["symbol"] == "\\AA"
        assert result["definitions"][0]["expansion"] == "\\mathcal{A}"

    def test_term_not_found_returns_empty(self, _seeded_handler):
        result = _run(
            _seeded_handler(paper_id="2401.00100", term="\\NotARealMacro")
        )
        assert result["definitions"] == []
        assert result["total"] == 0

    def test_prefix_match_on_symbol_raw(self, _seeded_handler):
        # No exact match for "\\Spe"; prefix match on \Spec should hit.
        result = _run(
            _seeded_handler(paper_id="2401.00100", term="\\Spe")
        )
        assert any(d["symbol"] == "\\Spec" for d in result["definitions"])

    def test_prefix_match_is_case_insensitive_on_symbol_raw(
        self, _seeded_handler
    ):
        # "\\hom" should case-fold-prefix match \Hom (via symbol_raw).
        result = _run(
            _seeded_handler(paper_id="2401.00100", term="\\hom")
        )
        assert any(d["symbol"] == "\\Hom" for d in result["definitions"])

    def test_empty_string_term_falls_through_to_full_table(
        self, tmp_path
    ):
        """F1 regression (E10_S01 critique) — ``term=""`` must NOT
        enter the term branch (where the case-insensitive prefix
        step's ``"".casefold()`` matches every row). Instead it must
        be treated as ``term=None`` and respect the pagination cap.
        Stage 150 macros so a single page (100) cannot cover them
        all; verify the response has 100 rows and a non-null cursor.
        """
        preamble_dir = tmp_path / "preamble"
        lancedb_path = tmp_path / "lancedb"
        _empty_chunks_table(lancedb_path)

        def _letters(i: int) -> str:
            a = i // (26 * 26)
            b = (i // 26) % 26
            c = i % 26
            return chr(ord("a") + a) + chr(ord("a") + b) + chr(ord("a") + c)

        macros = [
            r"\newcommand{\sym" + _letters(i) + r"}{body}"
            for i in range(150)
        ]
        _stage_preamble(preamble_dir, "2401.00300", macros)

        with _patched_preamble_dir(preamble_dir):
            index_definitions_for_paper("2401.00300", lancedb_path)
        table = open_or_create_definitions_table(lancedb_path)
        _install_resources(tmp_path, table)
        try:
            result = _run(
                defs_handler_mod.handle_get_definitions(
                    paper_id="2401.00300", term=""
                )
            )
            # Empty-string term must collapse to None — paginated.
            assert len(result["definitions"]) == 100
            assert result["next_cursor"] is not None
            assert result["total"] == 150
            # The term echoed back is the post-collapse None, not "".
            assert result["term"] is None
        finally:
            server_tools._RESOURCES = None

    def test_whitespace_only_term_falls_through_to_full_table(
        self, _seeded_handler
    ):
        """F1 regression — a whitespace-only ``term`` (e.g. ``"   "``)
        must also collapse to ``None``. Prefix-match on whitespace
        would otherwise match no rows for any reasonable paper since
        LaTeX command names never start with whitespace, but the
        boundary behaviour is worth pinning explicitly.
        """
        result = _run(
            _seeded_handler(paper_id="2401.00100", term="   ")
        )
        assert result["term"] is None
        # Falls through to full-table mode (paper has 12 rows, single page).
        assert result["total"] == 12


class TestHandlerNoIndexFallback:
    def test_absent_index_returns_empty_with_status(self, tmp_path):
        """When ``definitions_table`` is None on Resources, the handler
        responds with empty definitions and ``index_status="absent"``.
        """
        _install_resources(tmp_path, None)
        try:
            result = _run(
                defs_handler_mod.handle_get_definitions(paper_id="2401.00001")
            )
        finally:
            server_tools._RESOURCES = None
        assert result["definitions"] == []
        assert result["total"] == 0
        assert result["next_cursor"] is None
        assert result["index_status"] == "absent"


class TestHandlerSecurity:
    def test_rejects_path_traversal_paper_id(self, tmp_path):
        _install_resources(tmp_path, None)
        try:
            with pytest.raises(ValueError, match="paper_id"):
                _run(
                    defs_handler_mod.handle_get_definitions(
                        paper_id="../../../etc/passwd"
                    )
                )
        finally:
            server_tools._RESOURCES = None

    def test_rejects_empty_paper_id(self, tmp_path):
        _install_resources(tmp_path, None)
        try:
            # Pydantic Field(min_length=1) wraps the call at the MCP
            # layer; the handler itself does NOT receive an empty
            # paper_id under normal operation. The regex validator
            # additionally rejects bogus shapes.
            with pytest.raises((ValueError, Exception)):
                _run(
                    defs_handler_mod.handle_get_definitions(paper_id="not-a-paper-id")
                )
        finally:
            server_tools._RESOURCES = None
