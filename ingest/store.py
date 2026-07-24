"""LanceDB ``chunks`` table writer (E04_S01).

Reads :class:`ingest.chunker_types.ChunkRecord` rows + an
:class:`ingest.schema.EmbedRecord` (loaded from the embedder's NPZ
store), and writes/upserts them into the canonical LanceDB ``chunks``
dataset at ``var/arxmcp/index/lancedb/`` (table name ``chunks``;
LanceDB's on-disk layout puts the actual files under
``var/arxmcp/index/lancedb/chunks.lance/`` — closes F9 from the
E04_S01 critique by acknowledging that the brief's literal-path
language elides the LanceDB-internal ``.lance`` suffix). The schema is
the single source of truth in :mod:`ingest.schema`; this module never
re-declares it.

**Idempotent upsert.** :func:`write_chunks` uses LanceDB's
``merge_insert(on="chunk_id")`` so a second write of the same chunk
updates its row in place (no duplicates). LanceDB returns a new
dataset version per write — the writer surfaces that integer to the
caller for downstream MVCC pinning (E04_S02).

**HNSW + scalar indices.** After every successful write the writer
calls ``create_index`` on ``embedding_stmt`` and ``embedding_proof``
with ``HnswSq(m=16, ef_construction=200)``, plus a scalar index on
``paper_id``. LanceDB IVF-HNSW with ``num_partitions=1`` (the
auto-promoted value for small corpora) does NOT require the 256-row
IVF training threshold — the integration test on 10 rows succeeds.
Each call is wrapped in ``try/except`` so a future LanceDB API
change in HNSW knobs surfaces as a logged WARNING rather than a hard
failure of the whole write.

**NPZ alignment validation (closes the F4-from-E03_S02 analogue).**
:func:`write_chunks` validates that every chunk's chunk_id appears
in exactly one of the EmbedRecord's two ID lists. A chunk missing
an embedding (or appearing in BOTH lists, which the embedder's
routing rule forbids) raises :class:`ValueError` rather than
silently inserting a NULL-embedding row that would poison ANN
results.

**Concurrency.** LanceDB's own MVCC layer serializes concurrent
writers at the dataset level — two simultaneous ``write_chunks`` calls
produce two separate dataset versions, never a corrupt half-write. No
additional filesystem-atomicity wrapper is needed beyond the directory
``mkdir(parents=True, exist_ok=True)``.

**Single-writer assumption (F11 from the E04_S02 critique).** The
function is designed for a SINGLE writer per LanceDB dataset. Between
``merge_insert`` and ``_create_indices``, a concurrent writer-B
landing its own merge against the same dataset would shift
``tbl.version`` such that writer-A's returned integer points to
writer-B's post-merge state, not writer-A's own post-index state.
Callers running concurrent ingest from multiple processes against
the same dataset must serialize writes externally (e.g. a flock on
``<lancedb_path>/.write-lock``). The Tier-0 ingestion pipeline has
exactly one writer (the corpus driver), so this is a documented
constraint rather than an enforced one. Multi-writer support is an
E11 concern.

**MVCC handshake (E04_S02).** No symlink swaps. LanceDB version int IS
the corpus_version. Writers use the current dataset; readers call
dataset.checkout(version=N). (The reader-side wrapper lives in
:func:`server.corpus.open_chunks_table`.)

The integer returned by :func:`write_chunks` is the LanceDB dataset
version AFTER ``_create_indices`` has run — i.e. the post-index version,
not the post-merge version. This is intentional: callers pin readers to
this integer, and a reader that pins to the post-index version gets
indexed ANN queries (HNSW present). A pre-index pin (``merge_result.
version``) would still return correct rows but fall back to brute-force
scan, which is unacceptable at corpus scale. The ``_create_indices``
implementation may produce 1–3 extra LanceDB versions per write
(depending on which embedding columns have rows and whether the scalar
index succeeds); callers should treat the returned integer as opaque
and store it without arithmetic.
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
import time
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pyarrow as pa

from ingest.chunker import _validate_paper_id
from ingest.chunker_types import CHUNKER_VERSION, ChunkRecord
from ingest.embedder import (
    EMBEDDING_DIM,
    EMBEDDINGS_DIR,
    EMBEDDINGS_MANIFEST_NAME,
    EMBEDDINGS_NPZ_NAME,
    _read_embeddings_manifest,
)
from ingest.schema import (
    CHUNKS_SCHEMA_V1,
    CHUNKS_TABLE_NAME,
    LANCE_STORAGE_OPTIONS,
    EmbedRecord,
)

# NB: ``server.corpus.read_corpus_version`` is imported function-locally
# inside ``write_chunks`` (the WAP gate, corpus-integrity-completion-e1).
# A module-level ``from server.corpus import read_corpus_version`` here
# would form a circular import — ``server/corpus.py:101`` already imports
# ``CORPUS_VERSION_MARKER_NAME`` and ``DEFAULT_LANCEDB_PATH`` back from
# this module, and Python sees ``ingest.store`` mid-load with those names
# not yet bound. The spike-1 §5 rect F5 import-direction analysis cited
# ``ingest/bm25_indexer.py:87`` as precedent but that module is loaded
# lazily; ``ingest.store`` is loaded at server startup. Function-local
# import is the surgical fix; the runtime semantics of the gate are
# identical.

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_LANCEDB_PATH = REPO_ROOT / "var" / "arxmcp" / "index" / "lancedb"
STORE_STATS_PATH = REPO_ROOT / "var" / "arxmcp" / "ops" / "store-stats.jsonl"

# Filename of the corpus-version marker (E04_S03). Co-located with the
# LanceDB dataset directory so it's atomically renameable on the same
# filesystem. The MCP server reads this file at startup to determine
# which LanceDB dataset version to pin.
CORPUS_VERSION_MARKER_NAME = "corpus-version.json"


# ---------------------------------------------------------------------------
# WriteStats — per-call summary
# ---------------------------------------------------------------------------


# Closes F10 from the E04_S01 critique: ``kind`` accepts arbitrary
# strings at the schema layer (PyArrow has no native enum); a runtime
# guard against typos at write time catches "theroem" etc. before the
# bad row lands in the dataset.
_ALLOWED_KINDS = frozenset(
    {
        "stmt",
        "proof",
        "section",
        "definition",
        "lemma",
        "proposition",
        "corollary",
        "remark",
        "example",
        "claim",
        "conjecture",
        "fact",
        "hypothesis",
        "observation",
        "problem",
        "question",
        "exercise",
        "assumption",
        "convention",
        "notation",
        "theorem",
    }
)

#: Public alias of :data:`_ALLOWED_KINDS` (retrieval-unlocks-m2).
#: The write-time guard is this module's concern, but the SERVING side
#: needs the same domain to answer "which kinds did this route exclude?"
#: honestly — ``server/handlers/search.py`` computes its proof-route
#: ``excluded_kinds`` as this set minus ``{"proof"}``. Exported rather
#: than duplicated so the two can never disagree about what a kind is.
ALLOWED_KINDS: frozenset[str] = _ALLOWED_KINDS

# textbook-ingest-m2: domain of ``source_kind`` enum on the chunks
# table. Enforced at write time by ``_build_arrow_table`` against
# typos (``"arxv"``, ``"textboook"``) — same pattern as ``_ALLOWED_KINDS``.
_ALLOWED_SOURCE_KINDS = frozenset({"arxiv", "textbook"})

# m2 rect F4: parallel enum guard for ``parser_used`` (the brief's
# "extend the parser_used enum" wording is only meaningful if the
# column is actually enum-validated). None means failure / unknown
# and is accepted by ``_build_arrow_table`` — only non-None values
# must be in this set. Domain mirrors the synthesis D2 documentation
# + the chunker_types.py / 05-storage-and-indexing.md descriptions.
_ALLOWED_PARSER_USED = frozenset(
    {"ar5iv", "latexml", "mineru+latexml", "mineru+markdown"}
)


@dataclass
class WriteStats:
    """Per-call summary of a :func:`write_chunks` invocation.

    Append-mode written to ``var/arxmcp/ops/store-stats.jsonl`` so ops
    can audit which write produced which dataset version. Mirrors the
    embed-stats.jsonl shape from E03_S01.

    Closes F14 from the E04_S01 critique: ``indices_created`` is a
    ``dict[str, bool]`` keyed by canonical index name (``"hnsw_stmt"``,
    ``"hnsw_proof"``, ``"scalar_paper_id"``) so machine consumers (an
    ops dashboard, a CI gate) can filter individual outcomes without
    parsing strings. The previous list-of-strings shape was BP1-
    compliant at serialization time but not query-friendly.
    """

    chunk_count: int = 0
    elapsed_s: float = 0.0
    lancedb_version: int = 0
    rows_inserted: int = 0
    rows_updated: int = 0
    indices_created: dict[str, bool] = field(default_factory=dict)
    paper_id: str = ""
    total_rows_after_commit: int = 0
    # corpus-integrity-completion-e1 (rect F2): records WHY the WAP gate
    # raised, so the post-mortem audit row in store-stats.jsonl pins the
    # failure surface. Empty string is the happy-path (and pre-e1) value.
    # Domain (when non-empty): "missing_marker" | "malformed_marker" |
    # "count_mismatch_arithmetic" | "count_mismatch_swallow".
    # The arithmetic-vs-swallow split mirrors the runbook's S5/S6 routing
    # (rect F3).
    gate_failure_reason: str = ""

    def to_dict(self) -> dict:
        return {
            "chunk_count": self.chunk_count,
            "elapsed_s": round(self.elapsed_s, 3),
            "gate_failure_reason": self.gate_failure_reason,
            "indices_created": dict(self.indices_created),
            "lancedb_version": self.lancedb_version,
            "paper_id": self.paper_id,
            "rows_inserted": self.rows_inserted,
            "rows_updated": self.rows_updated,
            "total_rows_after_commit": self.total_rows_after_commit,
        }


# ---------------------------------------------------------------------------
# EmbedRecord loader — read NPZ + sidecar for one paper
# ---------------------------------------------------------------------------


def load_embed_record(paper_id: str) -> EmbedRecord | None:
    """Load the per-paper :class:`EmbedRecord` from the embedder's NPZ store.

    Reads ``var/arxmcp/corpus/embeddings/<paper_id>/embeddings.npz`` and
    its sidecar ``embeddings_manifest.json``. Returns ``None`` if the
    NPZ is absent (paper hasn't been embedded yet — a routine
    wait-state, not an error). Raises ``ValueError`` if the NPZ is
    present but the sidecar is absent or corrupt: the sidecar is the
    only place ``embedder_version`` is stored, and the LanceDB schema
    requires that column.

    Closes F1 from the E04_S01 adversary critique: ``paper_id`` is
    validated via ``_validate_paper_id`` before any path concatenation.
    The chunker / embedder / preamble loaders all gate on this exact
    helper (Threat 1 in 08-security-observability-ops.md); a public
    function that interpolates ``paper_id`` into a filesystem path
    must do the same.
    """
    _validate_paper_id(paper_id)
    paper_dir = EMBEDDINGS_DIR / paper_id
    npz_path = paper_dir / EMBEDDINGS_NPZ_NAME
    sidecar_path = paper_dir / EMBEDDINGS_MANIFEST_NAME
    if not npz_path.exists():
        return None
    sidecar = _read_embeddings_manifest(sidecar_path)
    if sidecar is None:
        raise ValueError(
            f"NPZ at {npz_path} has no sidecar manifest at {sidecar_path}; "
            "cannot determine embedder_version"
        )
    embedder_version = sidecar.get("embedder_version")
    if not isinstance(embedder_version, str) or not embedder_version:
        raise ValueError(
            f"sidecar at {sidecar_path} has malformed embedder_version: "
            f"{embedder_version!r}"
        )
    # ``allow_pickle=True`` is required because chunk_ids_* arrays use
    # ``dtype=object`` (numpy stores Python strings via pickle by default
    # in NPZ archives). Safe here because the file was produced by our
    # own trusted embedder code path.
    npz = np.load(npz_path, allow_pickle=True)
    chunk_ids_stmt = [str(x) for x in npz["chunk_ids_stmt"]]
    chunk_ids_proof = [str(x) for x in npz["chunk_ids_proof"]]
    embedding_stmt = np.asarray(npz["embedding_stmt"], dtype=np.float32)
    embedding_proof = np.asarray(npz["embedding_proof"], dtype=np.float32)
    # Make sure even zero-row sentinels have shape (0, EMBEDDING_DIM)
    # rather than (0,) — np.load preserves the original 2-D shape but
    # this guard catches accidental shape drift in older NPZs.
    if embedding_stmt.size == 0:
        embedding_stmt = np.zeros((0, EMBEDDING_DIM), dtype=np.float32)
    if embedding_proof.size == 0:
        embedding_proof = np.zeros((0, EMBEDDING_DIM), dtype=np.float32)
    return EmbedRecord(
        chunk_ids_stmt=chunk_ids_stmt,
        embedding_stmt=embedding_stmt,
        chunk_ids_proof=chunk_ids_proof,
        embedding_proof=embedding_proof,
        embedder_version=embedder_version,
    )


# ---------------------------------------------------------------------------
# Arrow row assembly
# ---------------------------------------------------------------------------


#: SQL expressions for LanceDB ``add_columns`` defaults when migrating
#: a pre-textbook-ingest-m2 chunks table. Existing rows are by
#: definition arXiv (no textbook ingest existed), so ``source_kind``
#: and ``license`` backfill with the canonical arXiv tokens; the four
#: textbook-only columns and ``parser_used`` get NULL.
#:
#: Per the lancedb 0.30.2 contract
#: (https://docs.lancedb.com/tables/schema): adding columns to an
#: existing table is a fragment-level operation (no full re-write) —
#: a new data file is appended per fragment with the SQL-expression
#: result for existing rows. FM-6 from m2 synthesis (NULL vs token
#: ambiguity in downstream filters) is resolved here by backfilling
#: ``source_kind`` + ``license`` with explicit tokens rather than
#: leaving NULL.
#: source-truth-m2 (chunks schema v2) extends this same dict with the
#: five new columns — all NULL-defaulted (no arXiv token to backfill; the
#: registry-derived values are hydrated later by the separately-invoked
#: ``tools/notebook_chunks_backfill.py``, and ``truncated`` /
#: ``printed_number`` are only known per-chunk, not as a table-wide SQL
#: default). ``truncated`` is the one boolean; ``cast(NULL as boolean)``
#: was spike-4-proven to ride the identical single-loop ``add_columns``
#: mechanism, so no struct branch or schema-based ``add_columns`` form is
#: needed for any of the five. The dict name keeps its ``_TEXTBOOK_``
#: prefix for continuity with the shipped migration; it is now the
#: canonical "all post-v1 chunks columns" default map.
_TEXTBOOK_MIGRATION_DEFAULTS: dict[str, str] = {
    "source_kind": "cast('arxiv' as string)",
    "license": "cast('arxiv-license' as string)",
    "chapter": "cast(NULL as string)",
    "page_start": "cast(NULL as int)",
    "page_end": "cast(NULL as int)",
    "textbook_slug": "cast(NULL as string)",
    "parser_used": "cast(NULL as string)",
    # source-truth-m2 chunks schema v2:
    "source_revision_id": "cast(NULL as string)",
    "source_span": "cast(NULL as string)",
    "truncated": "cast(NULL as boolean)",
    "printed_number": "cast(NULL as string)",
    "license_ref": "cast(NULL as string)",
}


def _migrate_chunks_schema_if_needed(tbl) -> list[str]:
    """Add textbook-ingest-m2 columns to a pre-m2 chunks table.

    Detects schema drift by reading ``tbl.schema.names`` and calling
    ``tbl.add_columns(...)`` for each column present in
    :data:`CHUNKS_SCHEMA_V1` but absent from the on-disk table. SQL
    expressions in :data:`_TEXTBOOK_MIGRATION_DEFAULTS` backfill
    existing rows: ``source_kind="arxiv"``, ``license="arxiv-license"``,
    everything else ``NULL``.

    Idempotent — when all 12 post-v1 columns (7 textbook-ingest-m2 +
    5 source-truth-m2) are already present (i.e. the table has been
    migrated previously or was created fresh against the new schema),
    returns an empty list and skips the LanceDB call.

    Returns the list of column names that were added (empty when no
    migration was needed).

    Raises any LanceDB ``add_columns`` error verbatim — schema
    migration failures are not recoverable at this layer.
    """
    existing_names = set(tbl.schema.names)
    target_names = set(CHUNKS_SCHEMA_V1.names)
    missing = target_names - existing_names
    if not missing:
        return []

    # Only migrate textbook-ingest-m2 columns. Any other missing
    # columns (a hypothetical future m3 column) would need their own
    # default mapping — fail loud rather than silently leave them out.
    unhandled = missing - set(_TEXTBOOK_MIGRATION_DEFAULTS.keys())
    if unhandled:
        raise RuntimeError(
            f"chunks table missing columns this migration cannot "
            f"handle: {sorted(unhandled)}. Extend "
            f"_TEXTBOOK_MIGRATION_DEFAULTS or write a dedicated "
            f"migration."
        )

    # Apply defaults in CHUNKS_SCHEMA_V1's declared order so the
    # post-migration column order matches the canonical schema. (Order
    # is not load-bearing for correctness, but determinism makes
    # cross-host snapshot tests stable.) Local variable name is
    # ``schema_field`` to avoid shadowing the ``field`` import from
    # ``dataclasses`` (F402).
    added: list[str] = []
    for schema_field in CHUNKS_SCHEMA_V1:
        if schema_field.name in missing:
            sql = _TEXTBOOK_MIGRATION_DEFAULTS[schema_field.name]
            tbl.add_columns({schema_field.name: sql})
            added.append(schema_field.name)

    # m2 rect F2 (HIGH): LanceDB's ``add_columns`` with a non-NULL SQL
    # default (e.g. ``cast('arxiv' as string)``) infers
    # ``nullable=False`` from the expression — so a migrated table
    # gets a stricter ``source_kind`` / ``license`` column than a
    # freshly-created v21 table (where ``CHUNKS_SCHEMA_V1`` declares
    # ``nullable=True``). The skew is path-dependent and reachable
    # via a future bug: a stale fixture writing ``source_kind=None``
    # would succeed on fresh but fail on migrated. Force every m2
    # column to match the canonical nullability via ``alter_columns``.
    # ``alter_columns`` does not change values (existing rows keep
    # their backfilled tokens); it only updates the on-disk schema
    # metadata. One MVCC version per altered column — cheap; cost is
    # bounded by the 7-column m2 delta.
    for schema_field in CHUNKS_SCHEMA_V1:
        if (
            schema_field.name in added
            and schema_field.nullable
            and not tbl.schema.field(schema_field.name).nullable
        ):
            tbl.alter_columns(
                {"path": schema_field.name, "nullable": True}
            )

    logger.info(
        "textbook-ingest-m2 schema migration: added %d columns to "
        "chunks table: %s",
        len(added),
        added,
    )
    return added


def _build_arrow_table(
    chunks: list[ChunkRecord],
    embeddings: EmbedRecord,
) -> pa.Table:
    """Assemble a PyArrow table conforming to :data:`CHUNKS_SCHEMA_V1`.

    Validates D7 from research-synthesis: every chunk's chunk_id must
    appear in exactly one of ``embeddings.chunk_ids_stmt`` /
    ``embeddings.chunk_ids_proof``. A missing chunk raises
    ``ValueError`` (this is the F4-from-E03_S02 analogue: verify the
    artifact, not just the audit trail).

    Validates D8: ``body_tokens is None`` raises (E02_S03 has shipped;
    a None here is a real upstream bug, not a legacy concern).
    """
    if not chunks:
        # Empty input is a valid no-op; return an empty table conforming
        # to the schema so downstream code doesn't have to special-case
        # the empty branch.
        return pa.Table.from_pylist([], schema=CHUNKS_SCHEMA_V1)

    # Build lookup tables for embedding rows. Each chunk_id appears in
    # at most one list (validated by EmbedRecord.__post_init__); we map
    # to (column, vector) here.
    stmt_lookup: dict[str, np.ndarray] = {
        cid: embeddings.embedding_stmt[i]
        for i, cid in enumerate(embeddings.chunk_ids_stmt)
    }
    proof_lookup: dict[str, np.ndarray] = {
        cid: embeddings.embedding_proof[i]
        for i, cid in enumerate(embeddings.chunk_ids_proof)
    }

    # Validate D7: every chunk must have an embedding somewhere.
    chunk_id_set = {c.chunk_id for c in chunks}
    embedded_set = set(stmt_lookup) | set(proof_lookup)
    missing = chunk_id_set - embedded_set
    if missing:
        raise ValueError(
            f"chunks missing from EmbedRecord (no embedding vector): "
            f"{sorted(missing)}"
        )

    rows: list[dict] = []
    for chunk in chunks:
        if chunk.body_tokens is None:
            # D8: body_tokens=None is a real bug (E02_S03 has shipped).
            raise ValueError(
                f"chunk {chunk.chunk_id} has body_tokens=None; "
                "E02_S03 is required and must have populated this field"
            )
        # Closes F10 from the E04_S01 critique: ``kind`` is not enforced
        # by PyArrow (no native enum), so a chunker bug or driver typo
        # like ``"theroem"`` could land in the dataset and silently
        # break the dual-encoding routing rule. Validate against the
        # closed set the chunker emits.
        if chunk.kind not in _ALLOWED_KINDS:
            raise ValueError(
                f"chunk {chunk.chunk_id} has kind={chunk.kind!r} which "
                f"is not in the allowed set {sorted(_ALLOWED_KINDS)!r}"
            )
        # textbook-ingest-m2: same enum-guard pattern for ``source_kind``.
        # The chunks-schema column is nullable to accommodate the
        # in-place migration of pre-m2 rows via
        # ``_migrate_chunks_schema_if_needed`` below, but every NEW write
        # MUST have a valid source_kind from the ChunkRecord default
        # ("arxiv") or the textbook chunker override ("textbook").
        if chunk.source_kind not in _ALLOWED_SOURCE_KINDS:
            raise ValueError(
                f"chunk {chunk.chunk_id} has source_kind="
                f"{chunk.source_kind!r} which is not in the allowed "
                f"set {sorted(_ALLOWED_SOURCE_KINDS)!r}"
            )
        # textbook-ingest-m9 / e4 rect F6: the chunk_id PREFIX and the
        # source_kind COLUMN must agree. The dense retrieval path filters
        # on the authoritative source_kind column; the BM25 path infers
        # source_kind from the chunk_id prefix
        # (server/retrieval/bm25.py:_source_kind_from_chunk_id). If a
        # chunk were written with a "textbook:"-prefixed id but
        # source_kind="arxiv" (or vice versa, via a chunker bug), the two
        # paths would classify the same chunk differently. Enforcing the
        # invariant at write time makes the prefix a guaranteed-reliable
        # proxy so the two paths can never disagree. ``arxiv:`` ⇔
        # "arxiv"; ``textbook:`` ⇔ "textbook".
        expected_prefix = f"{chunk.source_kind}:"
        if not chunk.chunk_id.startswith(expected_prefix):
            raise ValueError(
                f"chunk {chunk.chunk_id} has source_kind="
                f"{chunk.source_kind!r} but its chunk_id does not start "
                f"with the matching prefix {expected_prefix!r}; the "
                f"chunk_id prefix and source_kind column must agree so "
                f"the dense (column) and BM25 (prefix) retrieval paths "
                f"classify the chunk identically"
            )
        # m2 rect F4: ``parser_used`` is a documented enum. None
        # means failure / unknown (accepted). Any other value must
        # be in ``_ALLOWED_PARSER_USED`` so a chunker bug or driver
        # typo (``"latexm"``, ``"mineru"`` alone without ``+latexml``)
        # surfaces at write time instead of polluting chunk-grained
        # re-parse decisions downstream.
        if (
            chunk.parser_used is not None
            and chunk.parser_used not in _ALLOWED_PARSER_USED
        ):
            raise ValueError(
                f"chunk {chunk.chunk_id} has parser_used="
                f"{chunk.parser_used!r} which is not in the allowed "
                f"set {sorted(_ALLOWED_PARSER_USED)!r} (or None for "
                f"failure/unknown)"
            )
        emb_stmt = stmt_lookup.get(chunk.chunk_id)
        emb_proof = proof_lookup.get(chunk.chunk_id)
        # Convert numpy arrays to Python lists for PyArrow's
        # fixed-size-list type. ``.tolist()`` is the standard bridge.
        rows.append(
            {
                "chunk_id": chunk.chunk_id,
                "paper_id": chunk.paper_id,
                "kind": chunk.kind,
                "section_path": list(chunk.section_path),
                "theorem_name": chunk.theorem_name,
                "theorem_label": chunk.theorem_label,
                "body_text": chunk.body_text,
                "body_tokens": chunk.body_tokens,
                "embedding_stmt": (
                    emb_stmt.tolist() if emb_stmt is not None else None
                ),
                "embedding_proof": (
                    emb_proof.tolist() if emb_proof is not None else None
                ),
                # E03_S01 / E10_S03 contract: every row written here has
                # embedding_eq=None. E10_S03 will populate it later via a
                # separate update path.
                "embedding_eq": None,
                "chunker_version": chunk.chunker_version,
                "embedder_version": embeddings.embedder_version,
                "preamble_ref": chunk.preamble_ref,
                # textbook-ingest-m2 columns. ``source_kind`` and
                # ``license`` always populated from ChunkRecord defaults
                # ("arxiv" / "arxiv-license"); the four textbook-only
                # fields and ``parser_used`` stay None for arXiv chunks.
                "source_kind": chunk.source_kind,
                "license": chunk.license,
                "chapter": chunk.chapter,
                "page_start": chunk.page_start,
                "page_end": chunk.page_end,
                "textbook_slug": chunk.textbook_slug,
                "parser_used": chunk.parser_used,
                # source-truth-m2 (chunks schema v2). ``truncated`` and
                # ``printed_number`` are chunker-native: persist the values
                # already on the ChunkRecord (``truncated`` was previously
                # dropped here — the exact silent-drop the milestone closes).
                # The three registry-derived columns stay NULL on a new
                # write — no new-ingest driver consults the per-notebook
                # documents registry yet (forward-wiring is a tracked
                # fast-follow); they are hydrated on existing rows by the
                # separately-invoked ``tools/notebook_chunks_backfill.py``.
                "truncated": chunk.truncated,
                "printed_number": chunk.printed_number,
                "source_revision_id": None,
                "source_span": None,
                "license_ref": None,
            }
        )
    return pa.Table.from_pylist(rows, schema=CHUNKS_SCHEMA_V1)


# ---------------------------------------------------------------------------
# Index helpers
# ---------------------------------------------------------------------------


def _count_non_null(tbl, column: str) -> int:
    """Return the number of non-null rows in ``column``.

    Used to decide whether to attempt HNSW index creation: KMeans
    training requires at least 1 vector. A zero-non-null column is a
    valid state (e.g. a paper with only stmt chunks has zero
    ``embedding_proof`` rows) — not an error.
    """
    arrow_tbl = tbl.to_arrow()
    if arrow_tbl.num_rows == 0:
        return 0
    return arrow_tbl.num_rows - arrow_tbl.column(column).null_count


def _create_indices(tbl) -> dict[str, bool]:
    """Create the HNSW + scalar indices on ``tbl``.

    Closes F3 from the E04_S01 critique: HNSW vector index failures
    are now HARD failures because the brief's AC asserts they exist
    after a write. Previously a LanceDB API drift in the kwarg names
    (e.g. ``m`` → ``hnsw_m``) would silently log a WARNING, complete
    the write, and ship un-indexed production tables.

    Edge case (still F3-compliant): a column with ZERO non-null rows
    cannot be indexed (KMeans can't train on an empty vector set).
    This is a legitimate state — a paper with only stmt chunks has
    zero ``embedding_proof`` rows — not an API failure. We pre-check
    the column's non-null count and skip with ``False`` in the
    structured ``indices_created`` dict so the empty-column state
    is observable in ops logs rather than masked as a "success."

    The scalar index (``paper_id``) remains best-effort because it's
    a performance optimization, not an AC; its failure is logged
    and recorded but does not raise.

    Returns a ``dict[str, bool]`` keyed by canonical index name —
    ``True`` for success, ``False`` when the column had no non-null
    rows OR when the scalar index hit a transient error.

    HNSW config: ``IVF_HNSW_SQ`` with ``m=16, ef_construction=200``
    and ``num_partitions=1`` (closes F13: pinned explicitly so a
    future LanceDB change to the auto-promotion threshold can't
    break the small-corpus integration test). The lancedb 0.30 API
    surfaces these as direct kwargs on ``create_index`` (the older
    ``config=HnswSq(...)`` form was removed). Distance type left at
    the LanceDB default (l2). NOTE: LanceDB returns the *squared* L2
    distance on the ``_distance`` column for this metric (verified
    empirically — see :func:`server.retrieval.ann._distance_to_score`
    docstring). BGE-M3 vectors are L2-normalized so the squared-L2
    ranking is monotone with cosine ranking; the conversion
    ``cos = 1 - dist/2`` is exact for unit vectors.
    """
    created: dict[str, bool] = {}
    for column, key in (
        ("embedding_stmt", "hnsw_stmt"),
        ("embedding_proof", "hnsw_proof"),
    ):
        # Empty columns can't be indexed (KMeans needs ≥1 vector).
        if _count_non_null(tbl, column) == 0:
            logger.info(
                "skipping HNSW index on %s: column has zero non-null rows",
                column,
            )
            created[key] = False
            continue
        # F3: vector indices are AC-required; failures here bubble up.
        # Future API drift will surface as a clear AttributeError or
        # ValueError from LanceDB rather than as silent WARNING-and-
        # ship-broken.
        tbl.create_index(
            vector_column_name=column,
            index_type="IVF_HNSW_SQ",
            num_partitions=1,
            m=16,
            ef_construction=200,
            replace=True,
        )
        created[key] = True
    try:
        tbl.create_scalar_index("paper_id", replace=True)
        created["scalar_paper_id"] = True
    except Exception as exc:
        logger.warning("could not create scalar index on paper_id: %s", exc)
        created["scalar_paper_id"] = False
    return created


# ---------------------------------------------------------------------------
# Stats writer
# ---------------------------------------------------------------------------


def _append_store_stats(stats: WriteStats) -> None:
    """Append one JSON line to ``var/arxmcp/ops/store-stats.jsonl``.

    Append mode is non-atomic but acceptable for an ops log — mirrors
    the ``embed-stats.jsonl`` discipline from E03_S01.
    """
    STORE_STATS_PATH.parent.mkdir(parents=True, exist_ok=True)
    line = (
        json.dumps(stats.to_dict(), ensure_ascii=False, sort_keys=True) + "\n"
    )
    try:
        with STORE_STATS_PATH.open("a", encoding="utf-8") as fh:
            fh.write(line)
    except OSError:
        logger.error("could not write to store-stats.jsonl: %s", STORE_STATS_PATH)


# ---------------------------------------------------------------------------
# E04_S03: corpus_version marker file (server startup config)
# ---------------------------------------------------------------------------


def write_corpus_version_marker(
    lancedb_path: str | Path | None,
    version: int,
    chunker_version: str,
    embedder_version: str,
    paper_count: int,
    chunk_count: int,
) -> None:
    """Atomically write ``corpus-version.json`` next to the LanceDB dataset.

    The marker file is the **authoritative server startup config**:
    on boot, the MCP server (E06) reads it to determine which LanceDB
    dataset version to pin via :func:`server.corpus.open_chunks_table`.
    The ``version`` integer also serves as the cache namespace key for
    all server-side caches (E08_S03) — see the cache contract in
    :mod:`server.corpus`'s module docstring.

    .. warning::

       Path-traversal validation (Threat 1 from
       ``08-security-observability-ops.md``) is **deferred to E06's
       tool-input boundary** (TODO(E06)) — same discipline as
       :func:`server.corpus.open_chunks_table`. This function trusts
       ``lancedb_path`` as config-derived. Callers passing
       user-supplied paths MUST validate against an allowlisted
       corpus root first (closes M2 from the E04_S03 critique).

    Schema (alphabetical keys, ``json.dumps(sort_keys=True)``):

    .. code-block:: json

        {
          "chunk_count": 847,
          "chunker_version": "<CHUNKER_VERSION>",
          "created_at": "2026-05-08T14:30:00Z",
          "embedder_version": "<EMBEDDER_VERSION>",
          "paper_count": 50,
          "version": 3
        }

    The ``created_at`` timestamp is debug-only and outside BP1 scope
    (the marker file is a runtime config artifact, not a cached
    artifact, and never enters the prompt cache or tool result
    payload). Cache key construction in E08_S03 MUST use only
    ``version`` — see the cache contract.

    Atomic-write pattern: PID + UUID-suffixed tmp + ``os.replace`` +
    ``try/finally`` cleanup, mirroring
    :func:`ingest.preamble._write_preamble_json`. The tmp file is
    co-located with the destination on the same filesystem
    (``lancedb_path/`` is the same directory) so ``os.replace`` is
    POSIX-atomic.

    Parameters
    ----------
    lancedb_path:
        Directory hosting the LanceDB dataset. Defaults to
        :data:`DEFAULT_LANCEDB_PATH` when ``None``. The marker file is
        written to ``<lancedb_path>/corpus-version.json``.
    version:
        The LanceDB dataset version integer returned by
        :func:`write_chunks` — the post-index version (see the module
        docstring's "MVCC handshake" section).
    chunker_version:
        From :data:`ingest.chunker_types.CHUNKER_VERSION`. Threaded
        through as a parameter (rather than auto-imported) so tests
        can inject arbitrary values; production callers (e.g.
        :func:`write_chunks`) pass the live constant.
    embedder_version:
        From :data:`ingest.embedder.EMBEDDER_VERSION` — the
        ``"bge-m3@<8-hex>"`` short form already written to LanceDB
        rows.
    paper_count, chunk_count:
        Aggregates derived by the caller. ``write_chunks`` computes
        them from the in-memory chunks list as
        ``len({c.paper_id for c in chunks})`` and ``len(chunks)``.
    """
    target_path = (
        Path(lancedb_path) if lancedb_path is not None else DEFAULT_LANCEDB_PATH
    )
    target_path.mkdir(parents=True, exist_ok=True)
    out_path = target_path / CORPUS_VERSION_MARKER_NAME

    # Build the JSON payload with alphabetical keys (BP1).
    doc = {
        "chunk_count": int(chunk_count),
        "chunker_version": str(chunker_version),
        "created_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "embedder_version": str(embedder_version),
        "paper_count": int(paper_count),
        "version": int(version),
    }
    payload = json.dumps(doc, ensure_ascii=False, sort_keys=True) + "\n"

    # Atomic write — copy of preamble._write_preamble_json's pattern.
    tmp = out_path.with_suffix(
        f"{out_path.suffix}.{os.getpid()}.{uuid.uuid4().hex[:8]}.tmp"
    )
    try:
        tmp.write_text(payload, encoding="utf-8")
        os.replace(tmp, out_path)
    finally:
        with contextlib.suppress(OSError):
            tmp.unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def write_chunks(
    chunks: list[ChunkRecord],
    embeddings: EmbedRecord,
    lancedb_path: str | Path | None = None,
) -> int:
    """Upsert chunks + embeddings into the LanceDB ``chunks`` table.

    Creates the table on first call (with the v1 schema from
    :mod:`ingest.schema`); subsequent calls upsert via
    ``merge_insert(on="chunk_id")``. After every successful write,
    refreshes the HNSW + scalar indices.

    Returns the LanceDB dataset version number written by this call.
    Callers can pin this version later via ``open_table(...,
    version=N)`` (E04_S02 wires the MVCC handshake; E04_S01 just
    surfaces the integer).

    Raises ``ValueError`` if any chunk's chunk_id is missing from the
    EmbedRecord (D7) or if any chunk has ``body_tokens=None`` (D8).
    """
    import lancedb  # noqa: PLC0415

    start = time.monotonic()
    # Closes F7 from the E04_S01 critique: an empty chunks list is more
    # likely a programmer bug (the driver loaded zero chunks for a
    # paper) than a deliberate no-op. Log INFO so the gap is observable
    # rather than silently writing a zero-row table-creation path.
    if not chunks:
        logger.info(
            "write_chunks called with empty chunks list — no rows will be "
            "written. Verify the upstream driver is not silently dropping "
            "chunks."
        )
    target_path = Path(lancedb_path) if lancedb_path is not None else DEFAULT_LANCEDB_PATH
    target_path.mkdir(parents=True, exist_ok=True)

    arrow_table = _build_arrow_table(chunks, embeddings)

    # LanceDB connection + table-or-create. ``list_tables`` is the
    # current API (``table_names`` is deprecated since lancedb 0.30).
    # In 0.30 ``list_tables`` returns a ``ListTablesResponse`` object
    # whose membership semantics use ``.tables``; older versions return
    # a plain list. Handle both.
    db = lancedb.connect(str(target_path))
    tables_obj = db.list_tables()
    existing = set(getattr(tables_obj, "tables", tables_obj))
    if CHUNKS_TABLE_NAME in existing:
        tbl = db.open_table(CHUNKS_TABLE_NAME)
        # textbook-ingest-m2: in-place schema migration for pre-m2
        # chunks tables. Existing tables on disk carry the 14-column
        # arXiv-only schema; this call adds the 7 new columns with
        # arXiv-friendly defaults so every existing row is uniformly
        # tagged ``source_kind="arxiv"`` + ``license="arxiv-license"``
        # (no NULL-vs-default ambiguity in downstream filters).
        _migrate_chunks_schema_if_needed(tbl)
    else:
        # storage_options pins the on-disk Lance format (m2). See
        # ingest.schema.LANCE_STORAGE_OPTIONS for the why + the
        # silent-drop gotcha on the bare data_storage_version kwarg.
        tbl = db.create_table(
            CHUNKS_TABLE_NAME,
            schema=CHUNKS_SCHEMA_V1,
            storage_options=LANCE_STORAGE_OPTIONS,
        )

    # Idempotent upsert by chunk_id (D5). LanceDB's merge_insert
    # accepts either a PyArrow Table or a list of dicts; we pass the
    # validated PyArrow Table directly.
    rows_inserted = 0
    rows_updated = 0
    if arrow_table.num_rows > 0:
        merge_result = (
            tbl.merge_insert("chunk_id")
            .when_matched_update_all()
            .when_not_matched_insert_all()
            .execute(arrow_table)
        )
        # Closes F5 from the E04_S01 critique: direct attribute access
        # on ``MergeResult`` so a future LanceDB rename surfaces as a
        # clear ``AttributeError`` at write time, not as a silently
        # wrong ``rows_inserted=0`` recorded forever in the ops log.
        # If LanceDB ever retires the attribute (vs. renaming),
        # downstream code is the right place to surface that — not
        # here in observability.
        rows_inserted = int(merge_result.num_inserted_rows)
        rows_updated = int(merge_result.num_updated_rows)

    # Refresh indices best-effort (logs warnings on individual failures).
    indices_created = _create_indices(tbl)

    # Resolve the new dataset version. ``tbl.version`` is a stable
    # attribute since lancedb 0.6+; fall back to 0 if unavailable.
    #
    # E04_S02 invariant: this is the POST-index version (after
    # ``_create_indices`` ran), not ``merge_result.version``
    # (post-merge, pre-index). Callers pin readers to this integer
    # so MVCC checkouts return an INDEXED view of the data — a
    # reader pinning to the pre-index version would get correct
    # rows but fall back to brute-force ANN. See the module
    # docstring's "MVCC handshake" section.
    dataset_version = int(getattr(tbl, "version", 0) or 0)

    elapsed_s = time.monotonic() - start
    stats = WriteStats(
        chunk_count=len(chunks),
        elapsed_s=elapsed_s,
        lancedb_version=dataset_version,
        rows_inserted=rows_inserted,
        rows_updated=rows_updated,
        indices_created=indices_created,
        paper_id=chunks[0].paper_id if chunks else "",
        # total_rows_after_commit is populated below (after count_rows()); the
        # stats row is appended AFTER that block so the audit log captures the
        # real value, not 0 (corpus-integrity-observability-e3 critique F1).
    )

    # E04_S03: write the corpus-version marker file as a postcondition
    # of every successful ingest run. The marker is the authoritative
    # server startup config (E06 reads it to determine which LanceDB
    # version to pin) and the cache namespace key (E08_S03).
    #
    # Closes M1 from the E04_S03 critique: the swallow widens from
    # ``OSError`` to ``Exception``. The documented contract is
    # "marker-write failure must not abort ingest"; an OSError-only
    # narrowing was leaving non-OSError post-commit failures
    # (TypeError, ValueError) unhandled, splitting LanceDB-state from
    # the user-visible exception. A widened catch matches the stated
    # best-effort contract — the LanceDB row write has already
    # committed and the dataset_version is what the caller needs.
    #
    # Closes M6: ``embedder_version`` is passed straight through from
    # ``embeddings.embedder_version`` rather than falling back to the
    # live ``EMBEDDER_VERSION`` constant. The fallback masked an
    # upstream contract violation: if a caller hands write_chunks an
    # EmbedRecord with the default-empty embedder_version, the marker
    # would have lied about what model produced the rows. The
    # ``EmbedRecord.__post_init__`` already validates non-empty
    # construction in practice (only the default-default value is
    # empty), and the live-tip fallback created a foot-gun where the
    # marker disagreed with the actual rows.
    # corpus-integrity-observability-m1: derive the marker counts from the
    # COMMITTED TABLE, not the in-flight `chunks` batch. The per-paper callers
    # (bulk_ingest.ingest_one_paper, re_embed copy/re-embed paths,
    # notebook_textbook_ingest) call write_chunks once per paper, so the marker
    # is overwritten each call — with `len(chunks)`/`len({paper_ids})` it
    # recorded only the LAST paper's counts (e.g. chunk_count=106 / paper_count=1
    # on a 10,298-row, 53-paper notebook). Reading `tbl.count_rows()` (O(1) —
    # Lance fragment metadata) + the distinct paper_id set makes the FINAL
    # overwrite reflect the cumulative table, so the marker is correct after a
    # multi-paper run AND the per-call write stays crash-safe + correct for
    # single-call callers (notebook ingest, tests). `version` is still the
    # post-index `tbl.version`; WriteStats.chunk_count stays per-batch (separate
    # concern). The distinct scan materializes only the paper_id column — cheap
    # at the seed/notebook scale that runs this path today; the O(N)-per-call
    # cost would only matter on a 200K-paper bulk run (scoped-out E11/E12), where
    # a caller-maintained running set is the documented escalation.
    # NB lancedb 0.30.x: `to_arrow()` takes no kwargs — project via `.select`.
    try:
        # F4 (corpus-integrity-observability-m1 critique): these counts are read
        # off the SAME `tbl` handle that pinned `dataset_version` above, under the
        # single-writer-per-dataset model (module docstring, "MVCC handshake").
        # No write lands between L862 and here in-process, so the marker's
        # `version` and its counts are coherent. A concurrent external writer is
        # out of scope (E11).
        chunk_count = tbl.count_rows()
        # corpus-integrity-observability-e3 (CAND-8): thread the total-row
        # count through WriteStats so callers can accumulate run-level
        # chunks_written for ingest-summary.json without an extra count_rows().
        stats.total_rows_after_commit = chunk_count
        paper_count = len(
            set(tbl.to_arrow().select(["paper_id"])["paper_id"].to_pylist())
        )
        write_corpus_version_marker(
            target_path,
            version=dataset_version,
            chunker_version=CHUNKER_VERSION,
            embedder_version=embeddings.embedder_version,
            paper_count=paper_count,
            chunk_count=chunk_count,
        )
        # corpus-integrity-observability-e2 (scout CAND-4): structured,
        # test-assertable success event on the write path. Emitted INSIDE the
        # try AFTER the marker write so chunk_count/paper_count are bound and it
        # fires only on the success path (a marker-write failure is logged by
        # the except below, not as a spurious "complete"). Aggregate counts are
        # safe at INFO — the RedactionFilter guards body/query fields only
        # (08-security-observability-ops.md §Logging).
        logger.info(
            "write_chunks_complete",
            extra={
                "event": "write_chunks_complete",
                "corpus_version": dataset_version,
                "chunk_count": chunk_count,
                "paper_count": paper_count,
            },
        )
        marker_write_failed = False
    except Exception as exc:
        # corpus-integrity-completion-e1 rect F3: record that the
        # swallow fired so the WAP gate's COUNT-MISMATCH arm below can
        # tag the routing decision (S5 swallow+stale-marker vs. S6
        # arithmetic regression) in its RuntimeError text. Without this
        # flag the operator-actionability story from spike-1 §3 rect F6
        # requires a separate `grep` against the ingest log on the
        # 2am-page path.
        marker_write_failed = True
        logger.error(
            "could not write corpus-version.json marker for version %d "
            "at %s: %s (LanceDB row write succeeded; marker is best-effort)",
            dataset_version,
            target_path,
            exc,
        )

    # corpus-integrity-completion-e1 (spike-1 §3): WAP gate.
    # Placed OUTSIDE the try/except above (per spike-1 CRITICAL F1) so this
    # block's `raise RuntimeError(...)` propagates to the caller. Placing the
    # gate INSIDE the try-block would have the `except Exception as exc:
    # logger.error(...)` above silently absorb its own raise -- a structurally
    # non-functional gate.
    #
    # The gate reads `corpus-version.json` back from disk and verifies its
    # `chunk_count` matches a fresh `tbl.count_rows()`. This catches the
    # marker-vs-table seam at the WRITE boundary, not at the next-restart
    # inspection. Covers FM-1 (pre-m1 `len(chunks)` regression), FM-2 (JSON
    # truncation), FM-3 (atomic-rename truncation -> ValueError arm), FM-7
    # (int overflow), and FM-10 (swallowed marker-write leaving a stale
    # prior marker OR no marker at all; the stale-marker production-common
    # path fires the count-mismatch arm). Out-of-scope: FM-4 caller
    # arithmetic (m1 fix + m3 integration test), FM-5 TOCTOU (single-writer
    # constraint), FM-6/FM-14 schema-version drift (deferred follow-on),
    # FM-8 wrong path (config), FM-9 silent skip (logging), FM-11 sibling
    # marker writers (m3 follow-up F2-extension).
    #
    # Function-local import: see the comment at the module's import block
    # above for why this cannot be a top-level ``from server.corpus
    # import read_corpus_version`` (circular import with
    # ``server/corpus.py:101``).
    from server.corpus import read_corpus_version  # noqa: PLC0415

    # rect F2: wrap the gate body in try/finally so _append_store_stats
    # lands on the failure path too. The LanceDB rows and indices are
    # already committed by line 876; losing the audit row on the very
    # failure path the gate exists to surface is the observability gap
    # the critic flagged. The gate's RuntimeError still propagates to
    # the caller after the finally executes.
    try:
        try:
            re_read_marker = read_corpus_version(target_path)
        except ValueError as exc:
            stats.gate_failure_reason = "malformed_marker"
            raise RuntimeError(
                f"WAP gate: corpus-version.json marker at {target_path} is "
                f"malformed and cannot be parsed: {exc}. Likely cause: a "
                f"truncated atomic rename, a partial write before os.replace, "
                f"or a JSON serialization bug in write_corpus_version_marker. "
                f"Run `make reconcile` to repair. "
                f"Runbook: docs/ops/corpus-drift-runbook.md."
            ) from exc
        fresh_count = tbl.count_rows()
        if re_read_marker is None:
            stats.gate_failure_reason = "missing_marker"
            raise RuntimeError(
                f"WAP gate: corpus-version.json marker at {target_path} is "
                f"absent after write_corpus_version_marker returned. This is "
                f"the cold-clone case: no prior marker existed AND the write "
                f"was silently swallowed by the best-effort try/except above "
                f"(check the immediately preceding log line for a "
                f"'could not write corpus-version.json marker' warning). "
                f"Table count: {fresh_count}. "
                f"Run `make reconcile` to write a fresh marker. "
                f"Runbook: docs/ops/corpus-drift-runbook.md."
            )
        if re_read_marker.chunk_count != fresh_count:
            # rect F3: deterministic S5/S6 routing tag in the error
            # text. ``marker_write_failed`` is set in the swallow's
            # except block above; true == the prior swallow fired in
            # THIS call, so the stale prior marker is what was read
            # back (S5 recoverable via `make reconcile`). false == the
            # marker write succeeded but reports a wrong count (S6
            # arithmetic regression; needs a code fix). Operators on
            # the 2am-page path get the routing decision in the
            # exception text alone — no separate `grep` required.
            if marker_write_failed:
                stats.gate_failure_reason = "count_mismatch_swallow"
                routing_tag = "Routing: S5 (swallow + stale marker)"
                likely_cause = (
                    "the marker write was swallowed by the best-effort "
                    "try/except above and the PRIOR marker's chunk_count "
                    "is what's being read back (the immediately preceding "
                    "log line contains a 'could not write "
                    "corpus-version.json marker' warning that the "
                    "swallow emitted in this call)"
                )
            else:
                stats.gate_failure_reason = "count_mismatch_arithmetic"
                routing_tag = "Routing: S6 (arithmetic regression)"
                likely_cause = (
                    "a pre-m1-style len(chunks)-instead-of-count_rows "
                    "arithmetic regression in this call (the marker "
                    "write itself succeeded; its content is just wrong)"
                )
            raise RuntimeError(
                f"WAP gate: corpus-version.json marker at {target_path} reports "
                f"chunk_count={re_read_marker.chunk_count} but tbl.count_rows()="
                f"{fresh_count} for corpus_version={dataset_version}. "
                f"{routing_tag}. Likely cause: {likely_cause}. "
                f"Run `make reconcile` to repair the marker (S5) or fix the "
                f"writer code first then reconcile (S6). "
                f"Runbook: docs/ops/corpus-drift-runbook.md."
            )
    finally:
        # corpus-integrity-observability-e3 F1: append the audit row AFTER
        # the marker block so WriteStats.total_rows_after_commit (set inside
        # the try at count_rows() time) is serialized to store-stats.jsonl.
        # rect F2: also lands on the gate's failure path so the audit row
        # records the gate_failure_reason that triggered the abort.
        _append_store_stats(stats)

    return dataset_version


# Closes F11 from the E04_S01 critique: ``_atomic_write_json`` was
# dead code on land. Removed; if a future side-file needs atomic
# writes, copy the pattern from ``ingest.preamble._write_preamble_json``
# (the canonical implementation) rather than re-introducing it here.


__all__ = [
    "CORPUS_VERSION_MARKER_NAME",
    "DEFAULT_LANCEDB_PATH",
    "STORE_STATS_PATH",
    "WriteStats",
    "load_embed_record",
    "write_chunks",
    "write_corpus_version_marker",
]
