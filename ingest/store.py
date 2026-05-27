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
    EmbedRecord,
)

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

# textbook-ingest-m2: domain of ``source_kind`` enum on the chunks
# table. Enforced at write time by ``_build_arrow_table`` against
# typos (``"arxv"``, ``"textboook"``) — same pattern as ``_ALLOWED_KINDS``.
_ALLOWED_SOURCE_KINDS = frozenset({"arxiv", "textbook"})


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

    def to_dict(self) -> dict:
        return {
            "chunk_count": self.chunk_count,
            "elapsed_s": round(self.elapsed_s, 3),
            "indices_created": dict(self.indices_created),
            "lancedb_version": self.lancedb_version,
            "rows_inserted": self.rows_inserted,
            "rows_updated": self.rows_updated,
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
_TEXTBOOK_MIGRATION_DEFAULTS: dict[str, str] = {
    "source_kind": "cast('arxiv' as string)",
    "license": "cast('arxiv-license' as string)",
    "chapter": "cast(NULL as string)",
    "page_start": "cast(NULL as int)",
    "page_end": "cast(NULL as int)",
    "textbook_slug": "cast(NULL as string)",
    "parser_used": "cast(NULL as string)",
}


def _migrate_chunks_schema_if_needed(tbl) -> list[str]:
    """Add textbook-ingest-m2 columns to a pre-m2 chunks table.

    Detects schema drift by reading ``tbl.schema.names`` and calling
    ``tbl.add_columns(...)`` for each column present in
    :data:`CHUNKS_SCHEMA_V1` but absent from the on-disk table. SQL
    expressions in :data:`_TEXTBOOK_MIGRATION_DEFAULTS` backfill
    existing rows: ``source_kind="arxiv"``, ``license="arxiv-license"``,
    everything else ``NULL``.

    Idempotent — when all 7 textbook columns are already present
    (i.e. the table has been migrated previously or was created fresh
    against the new schema), returns an empty list and skips the
    LanceDB call.

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
        tbl = db.create_table(CHUNKS_TABLE_NAME, schema=CHUNKS_SCHEMA_V1)

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
    )
    _append_store_stats(stats)

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
    try:
        paper_count = len({c.paper_id for c in chunks})
        write_corpus_version_marker(
            target_path,
            version=dataset_version,
            chunker_version=CHUNKER_VERSION,
            embedder_version=embeddings.embedder_version,
            paper_count=paper_count,
            chunk_count=len(chunks),
        )
    except Exception as exc:
        logger.error(
            "could not write corpus-version.json marker for version %d "
            "at %s: %s (LanceDB row write succeeded; marker is best-effort)",
            dataset_version,
            target_path,
            exc,
        )

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
