"""Tests for the equation embedding populator (E10_S03b).

Covers:

* `embed_pending_equations` runs BGE-M3 over rows with NULL
  embedding_eq, writes the resulting vector, leaves other columns
  untouched.
* Idempotency: re-running on a fully-embedded table writes nothing.
* Skips rows with empty `presentation_latex` + `context_sentence`
  (no embedding input).
* AC2 coverage.

We mock `ingest.embedder._encode_batch` rather than loading the real
2 GB BGE-M3 model. The real model is exercised at production-ingest
time and via the `requires_model` test marker on per-model
opt-in tests elsewhere; this milestone's logic is independent of
the actual vector values.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
import pyarrow as pa
import pytest

from ingest.embed_equations import embed_pending_equations
from ingest.embedder import EMBEDDING_DIM
from ingest.index_equations import open_or_create_equations_table
from ingest.schema import EQUATIONS_SCHEMA_V1


def _empty_lancedb_path(tmp_path: Path) -> Path:
    tmp_path.mkdir(parents=True, exist_ok=True)
    return tmp_path


def _seed_equations(
    lancedb_path: Path, rows: list[dict[str, Any]]
) -> Any:
    """Insert ``rows`` (already shaped to EQUATIONS_SCHEMA_V1) into
    a fresh equations table."""
    table = open_or_create_equations_table(lancedb_path)
    arrow = pa.Table.from_pylist(rows, schema=EQUATIONS_SCHEMA_V1)
    table.add(arrow)
    return table


def _row(
    equation_id: str,
    paper_id: str = "2401.00001",
    presentation_latex: str = r"\int_0^1 f(x) dx",
    context_sentence: str = "An integral over [0, 1].",
    embedding_eq: list[float] | None = None,
) -> dict[str, Any]:
    return {
        "equation_id": equation_id,
        "paper_id": paper_id,
        "label": "E1",
        "presentation_latex": presentation_latex,
        "mathml": "<math><mi>x</mi></math>",
        "ascii_form": "",
        "context_sentence": context_sentence,
        "parent_chunk_id": None,
        "mathml_tree_json": None,
        "embedding_eq": embedding_eq,
    }


@pytest.fixture
def _mocked_encoder(monkeypatch):
    """Replace ``_encode_batch`` with a deterministic stand-in that
    returns L2-normalized unit vectors along distinct axes per
    input. The actual values do not matter for the embedder logic
    test — only that vectors land in the right rows.
    """
    import ingest.embed_equations as eq_mod

    def _fake_encode(texts, chunk_ids=None):
        n = len(texts)
        vectors = np.zeros((n, EMBEDDING_DIM), dtype=np.float32)
        for i in range(n):
            vectors[i, i % EMBEDDING_DIM] = 1.0
        return vectors, 0

    monkeypatch.setattr(eq_mod, "_encode_batch", _fake_encode)
    yield


# ===========================================================================
# Happy path
# ===========================================================================


class TestEmbedPendingEquations:
    def test_populates_null_rows(self, tmp_path, _mocked_encoder):
        lancedb_path = _empty_lancedb_path(tmp_path / "lancedb")
        _seed_equations(
            lancedb_path,
            [
                _row("arxiv:2401.00001:aaaaaaaaaaaaaaaa"),
                _row("arxiv:2401.00001:bbbbbbbbbbbbbbbb"),
            ],
        )
        counts = embed_pending_equations(lancedb_path)
        assert counts["processed"] == 2
        assert counts["embedded"] == 2
        assert counts["skipped"] == 0
        # All rows now have non-NULL embedding_eq.
        table = open_or_create_equations_table(lancedb_path)
        rows = table.to_arrow().to_pylist()
        assert all(r["embedding_eq"] is not None for r in rows)
        assert all(len(r["embedding_eq"]) == EMBEDDING_DIM for r in rows)

    def test_idempotent_on_already_embedded(
        self, tmp_path, _mocked_encoder
    ):
        lancedb_path = _empty_lancedb_path(tmp_path / "lancedb")
        v = [0.0] * EMBEDDING_DIM
        v[0] = 1.0
        _seed_equations(
            lancedb_path,
            [_row("arxiv:2401.00001:aaaaaaaaaaaaaaaa", embedding_eq=v)],
        )
        counts = embed_pending_equations(lancedb_path)
        assert counts["processed"] == 1
        assert counts["embedded"] == 0
        assert counts["skipped"] == 1

    def test_skips_rows_with_no_embedding_input(
        self, tmp_path, _mocked_encoder
    ):
        """A row with both `presentation_latex` and `context_sentence`
        empty has nothing to embed."""
        lancedb_path = _empty_lancedb_path(tmp_path / "lancedb")
        _seed_equations(
            lancedb_path,
            [
                _row(
                    "arxiv:2401.00001:aaaaaaaaaaaaaaaa",
                    presentation_latex="",
                    context_sentence="",
                )
            ],
        )
        counts = embed_pending_equations(lancedb_path)
        assert counts["processed"] == 1
        assert counts["embedded"] == 0
        assert counts["skipped"] == 1

    def test_preserves_other_columns(self, tmp_path, _mocked_encoder):
        """The merge_insert pass must not blow away other columns
        (mathml, mathml_tree_json, label, ...) of the matched row."""
        lancedb_path = _empty_lancedb_path(tmp_path / "lancedb")
        seed_row = _row("arxiv:2401.00001:aaaaaaaaaaaaaaaa")
        seed_row["mathml_tree_json"] = '{"label":"math","children":[]}'
        seed_row["label"] = "E42"
        _seed_equations(lancedb_path, [seed_row])
        embed_pending_equations(lancedb_path)
        table = open_or_create_equations_table(lancedb_path)
        rows = table.to_arrow().to_pylist()
        assert len(rows) == 1
        assert rows[0]["mathml_tree_json"] == '{"label":"math","children":[]}'
        assert rows[0]["label"] == "E42"
        assert rows[0]["embedding_eq"] is not None

    def test_empty_table_no_op(self, tmp_path):
        lancedb_path = _empty_lancedb_path(tmp_path / "lancedb")
        # Create table but seed no rows.
        open_or_create_equations_table(lancedb_path)
        counts = embed_pending_equations(lancedb_path)
        assert counts == {
            "processed": 0,
            "embedded": 0,
            "skipped": 0,
            "truncated_inputs": 0,
        }
