"""LanceDB ``chunks`` table v1 schema (E04_S01).

This module is the **single source of truth** for the LanceDB ``chunks``
table schema. All downstream readers (``ingest/store.py``, the MCP
server's ``search_papers`` handler, the eval harness in E05_S01)
import ``CHUNKS_SCHEMA_V1`` from this module and never re-declare a
schema inline.

Schema mutations require a corresponding MVCC version bump. E04_S02
will add a `corpus_version` integer to the dataset metadata; for now
the schema is treated as immutable and any change forces a manual
table re-creation. See ``05-storage-and-indexing.md`` § "MVCC
versioning" for the operational handshake.

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
    "EmbedRecord",
]
