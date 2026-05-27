"""LanceDB ``chunks`` table v1 schema (E04_S01).

This module is the **single source of truth** for the LanceDB ``chunks``
table schema. All downstream readers (``ingest/store.py``, the MCP
server's ``search_papers`` handler, the eval harness in E05_S01)
import ``CHUNKS_SCHEMA_V1`` from this module and never re-declare a
schema inline.

Schema mutations require a corresponding MVCC version bump. E04_S02
shipped the ``corpus_version`` integer in ``corpus-version.json``;
the schema version now ratchets via LanceDB's MVCC integer (written
by every successful ``write_chunks`` call). See
``05-storage-and-indexing.md`` § "MVCC versioning" for the
operational handshake.

**Existing-row migration is NOT implemented in this milestone.**
Adding nullable columns (e.g. the textbook-ingest-m2 additions
``source_kind``, ``license``, ``chapter``, ``page_start``,
``page_end``, ``textbook_slug``, ``parser_used``) to an existing
LanceDB table without a migration step causes ``merge_insert`` to
fail with a column-mismatch error. The migration helper that
backfills the missing columns on-open belongs to ``textbook-ingest-m2``
proper (see that milestone's research-brief-2 for the
``tbl.add_columns`` pattern). Until that lands, operators upgrading
a pre-m2 LanceDB dataset must re-create the table (delete and
re-ingest) rather than open in place.

Column order follows the brief's table verbatim. PyArrow doesn't
require a particular order for correctness, but a fixed source-literal
ordering keeps the schema bytes deterministic across runs (BP1
discipline from ``07-multi-agent-caching.md``).

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

# EMBEDDING_DIM is the single source of truth for the BGE-M3 hidden
# size; it lives in ``ingest.embedder`` (alongside BGE_M3_COMMIT_SHA)
# and is imported here to avoid a stray ``1024`` literal.
from ingest.embedder import EMBEDDING_DIM

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

# Names of the two dual-encoding embedding columns. Pinned here so the
# E05_S02 retrieval-quality test (and any future reader that needs to
# enumerate searchable vector columns) imports rather than literalizes
# the column-name strings. Closes F3 from the E05_S02 critique. The
# tuple ordering is the canonical search order: stmt first, proof
# second, mirroring the ``EmbedRecord`` field ordering and the
# ``CHUNKS_SCHEMA_V1`` declaration order below.
EMBEDDING_COLUMN_NAMES = ("embedding_stmt", "embedding_proof")


# ---------------------------------------------------------------------------
# Schema v1 — the canonical ``chunks`` table layout
# ---------------------------------------------------------------------------

# The risk note in the milestone brief is explicit: "Nullable columns
# for ``embedding_eq`` must be declared in PyArrow as
# ``pa.field("embedding_eq", pa.list_(pa.float32(), 1024),
# nullable=True)`` — omitting nullability would cause Arrow errors on
# insertion." We declare every nullable field with ``nullable=True``
# and every required field with ``nullable=False``.
CHUNKS_SCHEMA_V1 = pa.schema(
    [
        # Identity columns (all required).
        pa.field("chunk_id", pa.utf8(), nullable=False),
        pa.field("paper_id", pa.utf8(), nullable=False),
        pa.field("kind", pa.utf8(), nullable=False),
        # Section breadcrumb (always present, may be empty list).
        pa.field("section_path", pa.list_(pa.utf8()), nullable=False),
        # Theorem metadata (nullable when not a theorem environment).
        pa.field("theorem_name", pa.utf8(), nullable=True),
        pa.field("theorem_label", pa.utf8(), nullable=True),
        # Content payload (always present).
        pa.field("body_text", pa.utf8(), nullable=False),
        # ``body_tokens`` is non-nullable here even though
        # ``ChunkRecord.body_tokens: str | None`` allows None for legacy
        # pre-E02_S03 chunks. The store raises ``ValueError`` on a None
        # at write time — see ``ingest.store._build_arrow_table``.
        pa.field("body_tokens", pa.utf8(), nullable=False),
        # Dual-column dense embeddings. Nullable per the dual-encoding
        # contract: ``kind="proof"`` chunks have ``embedding_proof``
        # populated and ``embedding_stmt`` NULL; everything else has
        # ``embedding_stmt`` populated and ``embedding_proof`` NULL.
        pa.field(
            "embedding_stmt",
            pa.list_(pa.float32(), EMBEDDING_DIM),
            nullable=True,
        ),
        pa.field(
            "embedding_proof",
            pa.list_(pa.float32(), EMBEDDING_DIM),
            nullable=True,
        ),
        # ``embedding_eq`` is reserved for E10_S03 (equation embeddings).
        # The embedder NEVER populates this; every row written by E03_S01
        # has ``embedding_eq=None``.
        pa.field(
            "embedding_eq",
            pa.list_(pa.float32(), EMBEDDING_DIM),
            nullable=True,
        ),
        # Versioning columns (required). ``chunker_version`` flows from
        # ``ChunkRecord.chunker_version``; ``embedder_version`` flows from
        # the embedder's ``EMBEDDER_VERSION`` constant via ``EmbedRecord``.
        pa.field("chunker_version", pa.utf8(), nullable=False),
        pa.field("embedder_version", pa.utf8(), nullable=False),
        # ``preamble_ref`` is the SHA-256[:16] of the per-paper preamble;
        # NULL when preamble extraction failed (F3 fallback in E02_S02).
        pa.field("preamble_ref", pa.utf8(), nullable=True),
        # ---- textbook-ingest-m2 columns ----
        # All declared nullable=True so a freshly-created table at
        # this schema version accepts arXiv-only writes (NULL for the
        # textbook-specific columns). The in-place schema-evolution
        # migration that backfills these on a pre-m2 LanceDB table is
        # the work of ``textbook-ingest-m2`` proper — NOT bundled with
        # ``embedder-truncation-m1`` even though that milestone
        # incorporated the schema additions. New writes always populate
        # ``source_kind`` and ``license`` (from ``ChunkRecord``
        # defaults); the four textbook-only columns stay NULL for
        # arXiv chunks.
        #
        # ``source_kind`` enum domain: {"arxiv", "textbook"}. Enforced
        # at write time in ``_build_arrow_table`` against ``_ALLOWED_SOURCE_KINDS``.
        pa.field("source_kind", pa.utf8(), nullable=True),
        # ``license`` is free-text — domain is documentary, not
        # validated. Default ``"arxiv-license"`` for arXiv chunks;
        # textbook chunks carry the textbook's specific license token
        # (``"GFDL"`` for Stacks Project, ``"author-distributed"`` for
        # lecture notes, etc.). ``truncated_for_license`` snippet
        # truncation enforcement lands with textbook-ingest-e5.
        pa.field("license", pa.utf8(), nullable=True),
        # Textbook chapter name (``"Chapter 3: Schemes"``). NULL for
        # arXiv chunks; populated by the textbook chunker (e3).
        pa.field("chapter", pa.utf8(), nullable=True),
        # Inclusive page range for textbook chunks. NULL for arXiv.
        pa.field("page_start", pa.int32(), nullable=True),
        pa.field("page_end", pa.int32(), nullable=True),
        # Notebook slug for textbook chunks (``"shimura-varieties"``).
        # Redundant with ``paper_id = "textbook:<slug>"`` but enables a
        # scalar-index filter without string-splitting at query time.
        # NULL for arXiv chunks.
        pa.field("textbook_slug", pa.utf8(), nullable=True),
        # Per-chunk parser provenance. Enum domain:
        # {"ar5iv", "latexml", "mineru+latexml"}. NULL = unknown /
        # failure. Promoted from ``PaperOutcome`` in m2 so chunk-grain
        # re-parse decisions are possible. Not yet enum-validated at
        # write time (no runtime guard); upstream drivers populate
        # with one of the documented values.
        pa.field("parser_used", pa.utf8(), nullable=True),
    ]
)


# ---------------------------------------------------------------------------
# Definitions table schema (E10_S01)
# ---------------------------------------------------------------------------

# Per ``.claude/notes/05-storage-and-indexing.md`` lines 92-104 the
# definitions table captures one row per macro-definition or named
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
# during ``where`` evaluation). Documented in ``ingest/index_definitions.py``.
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

# Per ``.claude/notes/05-storage-and-indexing.md`` § "Table: equations"
# the equation atom carries the columns below. The brief calls for a
# ``mathml_tree_pickle`` column for the Zhang-Shasha trees; this
# implementation deliberately stores trees as JSON (``mathml_tree_json``)
# instead — pickle is a code-execution vector on read and Python-pickle
# format drift across minor releases can silently corrupt the column
# (see research-synthesis.md D2). The JSON form is trivial because
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
    ]
)


# ---------------------------------------------------------------------------
# EmbedRecord — the per-call embedding payload
# ---------------------------------------------------------------------------


@dataclass
class EmbedRecord:
    """Embedding payload passed to :func:`ingest.store.write_chunks`.

    The four ``*_ids`` / ``*_proof`` fields are the row-aligned outputs
    of the embedder's NPZ store (see ``ingest.embedder._write_embeddings_npz``):

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
    ``ingest.embedder.EMBEDDER_VERSION``).
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
    "DEFINITIONS_SCHEMA_V1",
    "DEFINITIONS_TABLE_NAME",
    "EQUATIONS_SCHEMA_V1",
    "EQUATIONS_TABLE_NAME",
    "EmbedRecord",
]
