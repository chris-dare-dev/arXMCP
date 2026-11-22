"""LanceDB table names, storage options and schemas.

The ``chunks`` table schema, :data:`CHUNKS_SCHEMA_V1`, is declared in
:mod:`arxmcp.corpus.chunk` with the rest of the chunk's facts and re-exported
here, so readers that import it from this module (the
store, the MCP server, the eval harness) keep working and nothing
re-declares a schema inline. This module keeps the table names
(:data:`CHUNKS_TABLE_NAME` is defined only here), the Lance storage
pin, the ``definitions`` and ``equations`` schemas and
:class:`EmbedRecord`.

**Adding a column is declared here, not coded.** Every LanceDB table a
dataset holds (``chunks``, ``definitions``, ``equations``) gains the
columns its schema has and the on-disk table lacks when a writer opens it
(:func:`add_missing_columns`). Existing rows get NULL in a nullable
column, or the value :data:`PRE_COLUMN_VALUES` records for rows written
before the column existed. A column that is neither nullable nor listed
there cannot be added to existing rows honestly, and the writer refuses
with :class:`SchemaEvolutionError` instead of inventing a value. Retyping,
renaming or removing a column has no in-place path: build the dataset
afresh in staging and cut over. BM25 and the theorem-name index are
rebuilt from ``chunks`` for each corpus version, so they follow a
``chunks`` change on the next index build.

Column order follows the brief's table verbatim. PyArrow doesn't
require a particular order for correctness, but a fixed source-literal
ordering keeps the schema bytes deterministic across runs (BP1
discipline).

**Why a separate module rather than inline in store.py.** The brief
explicitly requires "PyArrow schema definition is imported from a
single ``schema.py`` module — not re-defined inline." Tests
(``tests/test_store.py``) import the same constant for assertion,
which would not be possible if the schema lived inside an internal
helper inside ``store.py``.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pyarrow as pa

# The chunks schema, the vector width and the embedding input policy are
# chunk facts owned by ``arxmcp.corpus.chunk`` (no stray ``1024`` literal here).
# Importing them from there rather than from ``arxmcp.ingest.embedder`` keeps this
# module free of the embedder's import graph.
from arxmcp.corpus.chunk import (
    CHUNKS_SCHEMA_V1,
    EMBED_INPUT_POLICY_VERSION,
    EMBEDDING_COLUMN_NAMES,
    EMBEDDING_DIM,
)

# ---------------------------------------------------------------------------
# Table identity
# ---------------------------------------------------------------------------

# The LanceDB table name used by every reader. Pinned here so a future
# rename is a single-line change. Any reader that hard-codes ``"chunks"``
# inline is a bug.
CHUNKS_TABLE_NAME = "chunks"

# Name of the per-paper definitions/notation table (E10_S01). Defined
# alongside ``CHUNKS_TABLE_NAME`` so future readers (the
# ``get_definitions`` handler, the optional indexer driver) import the
# name string rather than literalize it.
DEFINITIONS_TABLE_NAME = "definitions"

# Name of the per-equation table (E10_S03). Separate from the chunks
# table because the equation atom record carries fields (mathml,
# presentation_latex, mathml_tree_json) that are equation-specific and
# would bloat every chunk row with NULLs if folded into CHUNKS_SCHEMA_V1.
EQUATIONS_TABLE_NAME = "equations"

# ``EMBEDDING_COLUMN_NAMES`` (the two dual-encoding vector columns, stmt
# first, proof second) is a chunk fact declared in ``arxmcp.corpus.chunk`` next
# to ``CHUNKS_SCHEMA_V1`` and re-exported here for readers that import
# it from this module. Its order mirrors the ``EmbedRecord`` field
# ordering.


# ---------------------------------------------------------------------------
# On-disk format pin (notebook-ops-hardening-m2)
# ---------------------------------------------------------------------------

# Explicit Lance on-disk storage-format pin, passed as ``storage_options``
# to EVERY ``db.create_table(...)`` call (chunks, definitions, equations).
# Without it the format follows whatever default the installed lancedb ships;
# a ``uv``/``pip`` upgrade could then silently migrate new tables to a format
# a pinned reader can't decode. Making the value explicit means a future
# default change shows up as a divergence at create time (or in release notes)
# rather than as silent on-disk drift under existing data.
#
# CRITICAL (lancedb 0.30.2): the modern key is
# ``storage_options={"new_table_data_storage_version": "stable"}``. The bare
# ``data_storage_version="stable"`` kwarg is accepted by
# ``LanceDBConnection.create_table`` but SILENTLY DROPPED (never forwarded to
# the Rust layer) — it looks correct and does nothing. Do NOT revert to it.
# ``"stable"`` is the documented default (today: Lance format major 3); it
# only governs NEW tables — existing datasets take the ``open_table`` path and
# are untouched, and ``merge_insert`` appends in the table's existing format.
LANCE_STORAGE_OPTIONS = {"new_table_data_storage_version": "stable"}


# ---------------------------------------------------------------------------
# Definitions table schema (E10_S01)
# ---------------------------------------------------------------------------

# The definitions table captures one row per macro-definition or named
# definition with the columns below. Every column is non-nullable: the
# indexer is responsible for substituting sentinels (e.g. an empty
# string for an unknown ``defining_chunk_id``) rather than relying on
# Arrow NULLs, which keeps downstream filtering predictable and avoids
# the "filter ignores NULLs" surprise common to scalar predicates.
#
# ``scope`` is intentionally stored as a free-text utf8 column rather
# than a dictionary-encoded enum: LanceDB scalar indexes do not yet
# support dictionary columns and string equality is fast at scale.
# The enum domain ``{paper, section, theorem}`` is enforced at write
# time by the indexer.
#
# Scalar indexes (built post-write):
#   * ``paper_id``     — supports per-paper filters from the handler
#   * ``symbol_raw``   — supports exact + prefix lookup on author's
#                        macro command (``\AA``, ``\Hom``, …).
# LanceDB ≥ 0.6 ``create_scalar_index`` does not accept multi-column
# composite indexes; the design note's ``(paper_id, symbol)`` is
# decomposed into the two scalar indexes above (the planner uses both
# during ``where`` evaluation). Documented in ``src/arxmcp/ingest/index_definitions.py``.
DEFINITIONS_SCHEMA_V1 = pa.schema(
    [
        pa.field("definition_id", pa.utf8(), nullable=False),
        pa.field("paper_id", pa.utf8(), nullable=False),
        pa.field("symbol", pa.utf8(), nullable=False),
        pa.field("symbol_raw", pa.utf8(), nullable=False),
        pa.field("expansion", pa.utf8(), nullable=False),
        pa.field("defining_chunk_id", pa.utf8(), nullable=False),
        pa.field("scope", pa.utf8(), nullable=False),
    ]
)


# ---------------------------------------------------------------------------
# Equations table schema (E10_S03)
# ---------------------------------------------------------------------------

# The equation atom carries the columns below. The Zhang-Shasha trees
# are stored as JSON (``mathml_tree_json``), deliberately not pickled:
# pickle is a code-execution vector on read and Python-pickle format
# drift across minor releases can silently corrupt the column. The JSON
# form is trivial because
# ``zss.Node`` is exactly ``{label: str, children: list[Node]}``.
#
# ``embedding_eq`` is reserved at v1 — every row written by E10_S03 has
# it NULL. Populating it requires a dedicated equation encoder pass
# that is explicitly out of scope for this milestone; the dense signal
# in the fusion formula uses ``embedding_stmt`` on the chunks table for
# now. The column is declared here so a future milestone can populate
# it without a schema migration.
EQUATIONS_SCHEMA_V1 = pa.schema(
    [
        pa.field("equation_id", pa.utf8(), nullable=False),
        pa.field("paper_id", pa.utf8(), nullable=False),
        pa.field("label", pa.utf8(), nullable=True),
        pa.field("presentation_latex", pa.utf8(), nullable=False),
        pa.field("mathml", pa.utf8(), nullable=False),
        pa.field("ascii_form", pa.utf8(), nullable=True),
        pa.field("context_sentence", pa.utf8(), nullable=True),
        pa.field("parent_chunk_id", pa.utf8(), nullable=True),
        pa.field("mathml_tree_json", pa.utf8(), nullable=True),
        pa.field(
            "embedding_eq",
            pa.list_(pa.float32(), EMBEDDING_DIM),
            nullable=True,
        ),
        # The tree normalizer version that wrote ``mathml_tree_json``:
        # a stored tree is comparable only to a query tree the same
        # normalizer built. NULL while the row has no tree.
        pa.field("normalizer_version", pa.int32(), nullable=True),
    ]
)


# ---------------------------------------------------------------------------
# Adding columns to an existing table
# ---------------------------------------------------------------------------

#: What a row written before a column existed holds in it, per table,
#: for the columns where that is known and is not NULL. Every chunk
#: written before ``source_kind`` and ``license`` existed is an arXiv
#: chunk under the arXiv licence; leaving them NULL would drop those rows
#: from ``WHERE license = 'arxiv-license'`` filters.
PRE_COLUMN_VALUES: dict[str, dict[str, str]] = {
    CHUNKS_TABLE_NAME: {"source_kind": "arxiv", "license": "arxiv-license"},
}

_SQL_TYPE_NAMES = {pa.utf8(): "string"}


class SchemaEvolutionError(RuntimeError):
    """The on-disk table lacks a column its schema has, and the existing
    rows have no value to give it."""


def _sql_default(column: pa.Field, value: str) -> str:
    sql_type = _SQL_TYPE_NAMES.get(column.type)
    if sql_type is None:
        raise SchemaEvolutionError(
            f"column {column.name!r} has a pre-column value but type "
            f"{column.type}, which has no SQL form here"
        )
    literal = value.replace("'", "''")
    return f"cast('{literal}' as {sql_type})"


def add_missing_columns(tbl, schema: pa.Schema, table_name: str) -> list[str]:
    """Add to ``tbl`` every column of ``schema`` it lacks, in schema order.

    Existing rows get the column's :data:`PRE_COLUMN_VALUES` entry for
    ``table_name``, or NULL when it has none and is nullable. Each added
    column ends with the nullability ``schema`` declares, so a migrated
    table and a fresh one have the same shape. Each addition is its own
    table version, so a retry after a failure adds only what is still
    missing. Returns the names added.

    Raises :class:`SchemaEvolutionError`, before changing anything, when
    a missing column is required and has no pre-column value.
    """
    on_disk = set(tbl.schema.names)
    missing = [f for f in schema if f.name not in on_disk]
    values = PRE_COLUMN_VALUES.get(table_name, {})
    unfillable = [
        f.name for f in missing if not f.nullable and f.name not in values
    ]
    if unfillable:
        raise SchemaEvolutionError(
            f"the {table_name} table lacks required columns {unfillable} "
            "that its existing rows have no value for. Give each a "
            "pre-column value in arxmcp.corpus.schema.PRE_COLUMN_VALUES, or "
            "build the dataset afresh in staging and cut over."
        )
    for column in missing:
        if column.name in values:
            tbl.add_columns({column.name: _sql_default(column, values[column.name])})
        else:
            tbl.add_columns(column)
        # A SQL default is typed non-nullable whatever the schema says.
        if column.nullable and not tbl.schema.field(column.name).nullable:
            tbl.alter_columns({"path": column.name, "nullable": True})
    return [f.name for f in missing]


# ---------------------------------------------------------------------------
# EmbedRecord — the per-call embedding payload
# ---------------------------------------------------------------------------


@dataclass
class EmbedRecord:
    """Embedding payload passed to :func:`arxmcp.corpus.store.write_chunks`.

    The four ``*_ids`` / ``*_proof`` fields are the row-aligned outputs
    of the embedder's NPZ store (see ``arxmcp.ingest.embedder._write_embeddings_npz``):

    - ``chunk_ids_stmt`` is row-aligned with ``embedding_stmt``: row ``i``
      of ``embedding_stmt`` is the embedding for ``chunk_ids_stmt[i]``.
    - Same alignment for ``chunk_ids_proof`` ↔ ``embedding_proof``.
    - A chunk_id appears in EXACTLY ONE of the two lists (never both,
      never neither). The store validates this invariant and raises
      ``ValueError`` on violation (closes the F4-from-E03_S02 analogue:
      verify the artifact, not just the audit trail).

    Single ``EmbedRecord`` per ``write_chunks`` call regardless of how
    many papers are batched: the caller (a future pipeline driver)
    concatenates per-paper NPZ outputs into one ``EmbedRecord`` before
    invoking the writer. The brief's signature is
    ``embeddings: EmbedRecord`` (singular).

    ``embedder_version`` is the model-identity stamp written to every
    row's ``embedder_version`` column. Form: ``"bge-m3@<8-hex>"`` (from
    ``arxmcp.ingest.embedder.EMBEDDER_VERSION``).
    """

    chunk_ids_stmt: list[str] = field(default_factory=list)
    embedding_stmt: np.ndarray = field(
        default_factory=lambda: np.zeros((0, EMBEDDING_DIM), dtype=np.float32)
    )
    chunk_ids_proof: list[str] = field(default_factory=list)
    embedding_proof: np.ndarray = field(
        default_factory=lambda: np.zeros((0, EMBEDDING_DIM), dtype=np.float32)
    )
    embedder_version: str = ""
    embed_input_policy_version: str = EMBED_INPUT_POLICY_VERSION

    def __post_init__(self) -> None:
        # Lightweight sanity checks at construction time so a malformed
        # EmbedRecord raises with a clear message rather than producing
        # a confusing PyArrow error inside the store later.
        if len(self.chunk_ids_stmt) != self.embedding_stmt.shape[0]:
            raise ValueError(
                f"chunk_ids_stmt length ({len(self.chunk_ids_stmt)}) does "
                f"not match embedding_stmt rows ({self.embedding_stmt.shape[0]})"
            )
        if len(self.chunk_ids_proof) != self.embedding_proof.shape[0]:
            raise ValueError(
                f"chunk_ids_proof length ({len(self.chunk_ids_proof)}) does "
                f"not match embedding_proof rows ({self.embedding_proof.shape[0]})"
            )
        if (
            self.embedding_stmt.size > 0
            and self.embedding_stmt.shape[1] != EMBEDDING_DIM
        ):
            raise ValueError(
                f"embedding_stmt dim ({self.embedding_stmt.shape[1]}) != "
                f"EMBEDDING_DIM ({EMBEDDING_DIM})"
            )
        if (
            self.embedding_proof.size > 0
            and self.embedding_proof.shape[1] != EMBEDDING_DIM
        ):
            raise ValueError(
                f"embedding_proof dim ({self.embedding_proof.shape[1]}) != "
                f"EMBEDDING_DIM ({EMBEDDING_DIM})"
            )
        if self.embedding_stmt.dtype != np.float32:
            raise ValueError(
                f"embedding_stmt dtype must be float32, got {self.embedding_stmt.dtype}"
            )
        if self.embedding_proof.dtype != np.float32:
            raise ValueError(
                f"embedding_proof dtype must be float32, got {self.embedding_proof.dtype}"
            )

        # Closes F2 from the E04_S01 critique: each chunk_id must be
        # unique WITHIN each list. Duplicates would silently collapse
        # in the dict-comprehension lookup downstream and discard one
        # vector — the same silent-data-corruption class the
        # cross-list overlap guard catches, but in the within-list
        # direction.
        #
        # Order matters: we check ID-set invariants (duplicate +
        # overlap) BEFORE the L2-norm check below. Domain-validity
        # errors (a chunk_id appearing twice) are more fundamentally
        # wrong than data-quality errors (an un-normalized vector),
        # and surfacing them first gives clearer error messages on
        # malformed inputs.
        stmt_set = set(self.chunk_ids_stmt)
        if len(stmt_set) != len(self.chunk_ids_stmt):
            from collections import Counter

            dup = [
                k for k, n in Counter(self.chunk_ids_stmt).items() if n > 1
            ]
            raise ValueError(
                f"duplicate chunk_id(s) in chunk_ids_stmt: {sorted(dup)}"
            )
        proof_set = set(self.chunk_ids_proof)
        if len(proof_set) != len(self.chunk_ids_proof):
            from collections import Counter

            dup = [
                k for k, n in Counter(self.chunk_ids_proof).items() if n > 1
            ]
            raise ValueError(
                f"duplicate chunk_id(s) in chunk_ids_proof: {sorted(dup)}"
            )

        # Each chunk_id must appear in exactly one of the two lists
        # (never both — the embedder's routing rule is exclusive).
        overlap = stmt_set & proof_set
        if overlap:
            raise ValueError(
                f"chunk_ids in BOTH stmt and proof lists "
                f"(routing rule violated): {sorted(overlap)}"
            )

        # Closes F4 from the E04_S01 critique: BGE-M3 produces
        # L2-normalized vectors and the store's HNSW index runs with
        # ``distance_type='l2'``; un-normalized vectors silently corrupt
        # ANN ranking quality. Validate at the EmbedRecord boundary so
        # a regressed embedder (or a future caller passing raw vectors)
        # surfaces the failure at construction rather than at
        # query-time. ``atol=1e-3`` tolerates float32 round-off from the
        # pooling layer.
        for col_name, arr in (
            ("embedding_stmt", self.embedding_stmt),
            ("embedding_proof", self.embedding_proof),
        ):
            if arr.shape[0] == 0:
                continue
            norms = np.linalg.norm(arr, axis=1)
            if not np.allclose(norms, 1.0, atol=1e-3):
                worst_idx = int(np.argmax(np.abs(norms - 1.0)))
                worst_norm = float(norms[worst_idx])
                raise ValueError(
                    f"{col_name} contains un-normalized vectors "
                    f"(row {worst_idx} has L2 norm {worst_norm:.6f}, "
                    f"expected 1.0 ± 1e-3). BGE-M3 outputs are "
                    f"L2-normalized; pass vectors through "
                    f"torch.nn.functional.normalize(p=2, dim=-1) before "
                    f"constructing EmbedRecord."
                )


__all__ = [
    "CHUNKS_SCHEMA_V1",
    "CHUNKS_TABLE_NAME",
    "EMBEDDING_COLUMN_NAMES",
    "EMBEDDING_DIM",
    "DEFINITIONS_SCHEMA_V1",
    "DEFINITIONS_TABLE_NAME",
    "EQUATIONS_SCHEMA_V1",
    "EQUATIONS_TABLE_NAME",
    "PRE_COLUMN_VALUES",
    "EmbedRecord",
    "SchemaEvolutionError",
    "add_missing_columns",
]
