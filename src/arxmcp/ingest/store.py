"""LanceDB ``chunks`` table writer (E04_S01).

Reads :class:`arxmcp.ingest.chunk.ChunkRecord` rows + an
:class:`arxmcp.ingest.schema.EmbedRecord` (loaded from the embedder's NPZ
store), and writes/upserts them into the canonical LanceDB ``chunks``
dataset at ``var/arxmcp/index/lancedb/`` (table name ``chunks``;
LanceDB's on-disk layout puts the actual files under
``var/arxmcp/index/lancedb/chunks.lance/`` — closes F9 from the
E04_S01 critique by acknowledging that the brief's literal-path
language elides the LanceDB-internal ``.lance`` suffix). The schema is
declared in :mod:`arxmcp.ingest.chunk` (re-exported by :mod:`arxmcp.ingest.schema`),
which also owns the record -> row mapping and its write-time checks; this
module never re-declares either.

**Idempotent upsert.** :func:`write_chunks` uses LanceDB's
``merge_insert(on="chunk_id")`` so a second write of the same chunk
updates its row in place (no duplicates). LanceDB returns a new
dataset version per write — the writer surfaces that integer to the
caller for downstream MVCC pinning (E04_S02).

**HNSW + scalar indices.** A write with ``build_indices`` (the default)
calls ``create_index`` on ``embedding_stmt`` and ``embedding_proof``
with ``HnswSq(m=16, ef_construction=200)``, plus a scalar index on
``paper_id``. Per-paper drivers skip that and call
:func:`refresh_indices` once per run. LanceDB IVF-HNSW with ``num_partitions=1`` (the
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

**Concurrency.** LanceDB's own MVCC layer keeps two simultaneous
commits from corrupting the table, but not from interleaving.

**One writer per dataset, enforced.** Between ``merge_insert`` and the
marker write, a second writer's commit would shift ``tbl.version`` so that
the returned integer and the marker's counts describe neither write.
:func:`write_chunks` and :func:`delete_paper` therefore run under the
dataset's write lock (:mod:`arxmcp.ingest.write_lock`), and the drivers hold it
for their whole run; a second writer is refused at once with
:class:`arxmcp.ingest.write_lock.DatasetWriteLockedError`. A writer that goes
around the lock is caught by the write-audit gate, which names it.

**MVCC handshake (E04_S02).** No symlink swaps. LanceDB version int IS
the corpus_version. Writers use the current dataset; readers call
dataset.checkout(version=N). (The reader-side wrapper lives in
:func:`arxmcp.ingest.corpus.open_chunks_table`.)

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

# ALLOWED_KINDS is re-exported (``__all__``): src/arxmcp/server/handlers/search.py
# derives its proof-route ``excluded_kinds`` from ``arxmcp.ingest.store.ALLOWED_KINDS``
# so the two cannot drift. The write-time checks themselves are arxmcp.ingest.chunk's.
from arxmcp.ingest.chunk import (
    ALLOWED_KINDS,
    CHUNKER_VERSION,
    CHUNKS_SCHEMA_V1,
    EMBEDDING_DIM,
    LEGACY_EMBED_INPUT_POLICY_VERSION,
    ChunkRecord,
    route,
    to_arrow_table,
    to_row,
)
from arxmcp.ingest.chunker import _validate_paper_id
from arxmcp.ingest.embedder import (
    EMBEDDINGS_DIR,
    EMBEDDINGS_MANIFEST_NAME,
    EMBEDDINGS_NPZ_NAME,
    _read_embeddings_manifest,
)
from arxmcp.ingest.schema import (
    CHUNKS_TABLE_NAME,
    DEFINITIONS_TABLE_NAME,
    EQUATIONS_TABLE_NAME,
    LANCE_STORAGE_OPTIONS,
    EmbedRecord,
    add_missing_columns,
)
from arxmcp.ingest.write_lock import holds_dataset_write_lock, write_lock_path
from arxmcp.settings import ApplicationPaths

# NB: ``arxmcp.ingest.corpus.read_corpus_version`` is imported function-locally
# inside ``write_chunks`` (the WAP gate, corpus-integrity-completion-e1).
# A module-level ``from arxmcp.ingest.corpus import read_corpus_version`` here
# would form a circular import — ``src/arxmcp/ingest/corpus.py`` already imports
# ``CORPUS_VERSION_MARKER_NAME`` and ``DEFAULT_LANCEDB_PATH`` back from
# this module, and Python sees ``arxmcp.ingest.store`` mid-load with those names
# not yet bound. The spike-1 §5 rect F5 import-direction analysis cited
# ``src/arxmcp/ingest/bm25_indexer.py:87`` as precedent but that module is loaded
# lazily; ``arxmcp.ingest.store`` is loaded at server startup. Function-local
# import is the surgical fix; the runtime semantics of the gate are
# identical.

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

_APPLICATION_PATHS = ApplicationPaths.resolve()
DEFAULT_LANCEDB_PATH = _APPLICATION_PATHS.lancedb
STORE_STATS_PATH = _APPLICATION_PATHS.ops / "store-stats.jsonl"

# Filename of the corpus-version marker (E04_S03). Co-located with the
# LanceDB dataset directory so it's atomically renameable on the same
# filesystem. The MCP server reads this file at startup to determine
# which LanceDB dataset version to pin.
CORPUS_VERSION_MARKER_NAME = "corpus-version.json"


# ---------------------------------------------------------------------------
# WriteStats — per-call summary
# ---------------------------------------------------------------------------


class WapGateError(RuntimeError):
    """The corpus-version marker and the table disagree after a write.

    Raised by the WAP gate in :func:`write_chunks`. Unlike a failure
    confined to one paper's rows, this is a table-wide state that every
    later write inherits, so drivers stop the run instead of skipping
    the paper.
    """


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
    rows_deleted: int = 0
    indices_created: dict[str, bool] = field(default_factory=dict)
    paper_id: str = ""
    total_rows_after_commit: int = 0
    # corpus-integrity-completion-e1 (rect F2): records WHY the WAP gate
    # raised, so the post-mortem audit row in store-stats.jsonl pins the
    # failure surface. Empty string is the happy-path (and pre-e1) value.
    # Domain (when non-empty): "missing_marker" | "malformed_marker" |
    # "count_mismatch_arithmetic" | "count_mismatch_swallow" |
    # "concurrent_writer" (another process committed to the dataset during
    # the call, so neither count is wrong code).
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
    helper (Threat 1); a public
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
    embed_input_policy_version = sidecar.get("embed_input_policy_version")
    if embed_input_policy_version is None:
        embed_input_policy_version = LEGACY_EMBED_INPUT_POLICY_VERSION
    if not isinstance(embed_input_policy_version, str) or not embed_input_policy_version:
        raise ValueError(f"invalid embedding input policy in {sidecar_path}")
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
        embed_input_policy_version=embed_input_policy_version,
    )


# ---------------------------------------------------------------------------
# Arrow row assembly
# ---------------------------------------------------------------------------


def _migrate_chunks_schema_if_needed(tbl) -> list[str]:
    """Add to an on-disk chunks table the columns :data:`CHUNKS_SCHEMA_V1`
    has and it lacks (:func:`arxmcp.ingest.schema.add_missing_columns`).

    Returns the names added, empty when the table already has the
    canonical shape. Raises :class:`arxmcp.ingest.schema.SchemaEvolutionError`
    for a missing column the existing rows have no value for, and any
    LanceDB error verbatim.
    """
    added = add_missing_columns(tbl, CHUNKS_SCHEMA_V1, CHUNKS_TABLE_NAME)
    if added:
        logger.info(
            "chunks schema migration: added %d columns: %s", len(added), added
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

    The list a chunk's vector is found in must be the chunk's own route
    (:func:`arxmcp.ingest.chunk.route`): a proof chunk whose vector sits in the
    statement list raises instead of being stored with the wrong column
    filled. The per-record checks and the row
    shape are :func:`arxmcp.ingest.chunk.to_row` / :func:`arxmcp.ingest.chunk.to_arrow_table`.
    """
    if not chunks:
        # Empty input is a valid no-op; return an empty table conforming
        # to the schema so downstream code doesn't have to special-case
        # the empty branch.
        return to_arrow_table([])

    # Each chunk_id appears in at most one list (validated by
    # EmbedRecord.__post_init__).
    lookups: dict[str, dict[str, np.ndarray]] = {
        "stmt": {
            cid: embeddings.embedding_stmt[i]
            for i, cid in enumerate(embeddings.chunk_ids_stmt)
        },
        "proof": {
            cid: embeddings.embedding_proof[i]
            for i, cid in enumerate(embeddings.chunk_ids_proof)
        },
    }

    # Validate D7: every chunk must have an embedding somewhere.
    chunk_id_set = {c.chunk_id for c in chunks}
    embedded_set = set(lookups["stmt"]) | set(lookups["proof"])
    missing = chunk_id_set - embedded_set
    if missing:
        raise ValueError(
            f"chunks missing from EmbedRecord (no embedding vector): "
            f"{sorted(missing)}"
        )

    rows: list[dict] = []
    for chunk in chunks:
        chunk_route = route(chunk.kind)
        vector = lookups[chunk_route].get(chunk.chunk_id)
        if vector is None:
            raise ValueError(
                f"chunk {chunk.chunk_id} (kind={chunk.kind!r}) is on the "
                f"{chunk_route} route but its vector is in the EmbedRecord's "
                f"other list; refusing to store a vector from the other "
                f"embedding space"
            )
        rows.append(
            to_row(
                chunk,
                vector.tolist(),
                embedder_version=embeddings.embedder_version,
                policy=embeddings.embed_input_policy_version,
            )
        )
    return to_arrow_table(rows)


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
    # A filtered count, not ``to_arrow()``: the latter reads both 1024-float
    # vector columns of every row to learn one null count.
    return tbl.count_rows(f"{column} IS NOT NULL")


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
    empirically — see :func:`arxmcp.server.retrieval.ann._distance_to_score`
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
    embed_input_policy_version: str = "",
) -> None:
    """Atomically write ``corpus-version.json`` next to the LanceDB dataset.

    The marker file is the **authoritative server startup config**:
    on boot, the MCP server (E06) reads it to determine which LanceDB
    dataset version to pin via :func:`arxmcp.ingest.corpus.open_chunks_table`.
    The ``version`` integer also serves as the cache namespace key for
    all server-side caches (E08_S03) — see the cache contract in
    :mod:`arxmcp.ingest.corpus`'s module docstring.

    .. warning::

       Path-traversal validation (Threat 1) is **left to the
       tool-input boundary** (TODO(E06)) — same discipline as
       :func:`arxmcp.ingest.corpus.open_chunks_table`. This function trusts
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
    :func:`arxmcp.ingest.preamble._write_preamble_json`. The tmp file is
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
        From :data:`arxmcp.ingest.chunk.CHUNKER_VERSION`. Threaded
        through as a parameter (rather than auto-imported) so tests
        can inject arbitrary values; production callers (e.g.
        :func:`write_chunks`) pass the live constant.
    embedder_version:
        From :data:`arxmcp.ingest.embedder.EMBEDDER_VERSION` — the
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
        "embed_input_policy_version": str(embed_input_policy_version),
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
# In-place write guard
# ---------------------------------------------------------------------------


class StaleChunkerRowsError(RuntimeError):
    """A write target holds arXiv rows another chunker version wrote."""


#: Exit code the ingest CLIs (``arxmcp.ingest.bulk_ingest``, ``arxmcp.ingest.oai_delta``,
#: ``src/arxmcp/tools/notebook_ingest.py``) return when they refuse a target with
#: :class:`StaleChunkerRowsError`. A refusal is a state the operator must act
#: on (rotate the table through staging and a cutover; the error message
#: names the commands), not a fault, so it does not share exit 1 with a
#: failed paper; 2 is argparse's usage error.
STALE_CHUNKER_EXIT_CODE = 3


def refuse_stale_chunker_rows(
    lancedb_path: str | Path, *, chunker_version: str = CHUNKER_VERSION
) -> None:
    """Refuse an in-place write into a table another chunker version wrote.

    :func:`write_chunks` upserts by ``chunk_id``; only a ``replace_paper``
    write drops a paper's old rows, and only that paper's. Re-chunking in
    place across a chunker version leaves every paper not yet re-chunked
    in the old version's ids and bodies beside the new ones. A version
    bump can change ids (v1.3 dropped the preamble from arXiv ids) or
    bodies, so a table whose arXiv rows another version wrote must be
    re-chunked through a fresh staging table and a cutover, never written
    in place. This runs once per run, before the first write, from the
    in-place ingest paths (:func:`arxmcp.ingest.bulk_ingest.run_bulk_ingest`,
    which ``make ingest``, ``src/arxmcp/tools/notebook_ingest.py`` and the ``/ui/``
    console reach, and :func:`arxmcp.ingest.oai_delta.run_delta`).

    A missing or empty table passes. Textbook rows carry their own chunker
    versions and are not checked. The check reads the rows, not the
    ``corpus-version.json`` marker: a textbook ingest restamps the marker
    with this code's version without touching a single arXiv row.
    """
    path = Path(lancedb_path)
    if not (path / f"{CHUNKS_TABLE_NAME}.lance").is_dir():
        return
    import lancedb  # noqa: PLC0415

    table = lancedb.connect(str(path)).open_table(CHUNKS_TABLE_NAME)
    safe_version = chunker_version.replace("'", "''")
    stale_filter = (
        "chunk_id LIKE 'arxiv:%' AND (chunker_version IS NULL "
        f"OR chunker_version != '{safe_version}')"
    )
    stale = table.count_rows(stale_filter)
    if not stale:
        return
    sample = (
        table.search()
        .where(stale_filter)
        .select(["chunker_version"])
        .limit(1000)
        .to_list()
    )
    found = sorted({str(row["chunker_version"]) for row in sample})
    raise StaleChunkerRowsError(
        f"refusing to write into {path}: {stale} arXiv row(s) there were "
        f"chunked by another chunker_version (seen: {found}), and this code "
        f"is {chunker_version!r}. Writing in place would mix the two "
        "versions' rows until every paper was re-chunked. "
        "Re-chunk through a fresh staging table and a cutover instead, "
        "with the server stopped. For a notebook: "
        "make re-embed ARGS=\"--notebook=<slug> --dry-run\" (check each "
        "paper's copy/reembed/drop counts), then "
        "make re-embed ARGS=\"--notebook=<slug>\", then "
        "make notebook-cutover ARGS=\"--notebook=<slug> --force\" "
        "(--force because a fresh staging table restarts its version "
        "count). For the shared corpus: make re-embed, make watchdog, "
        "then make cutover."
    )


# ---------------------------------------------------------------------------
# Distinct paper_id set, carried between writes
# ---------------------------------------------------------------------------

#: The distinct ``paper_id`` set of each dataset this process last wrote,
#: keyed by resolved dataset path, with the identity of the table state it
#: describes. Every write needs the paper count for the marker; scanning
#: the ``paper_id`` column for it costs O(rows) per write, so a run of P
#: per-paper writes would cost O(P * rows). A set is only reused while the
#: table is the one this process left: same ``chunks.lance`` directory
#: (a cutover renames another dataset into the path, and that one may be
#: at the same version number) and same version (any other write moves it).
_PAPER_IDS: dict[str, tuple[tuple[int, int, int], set[str]]] = {}


def _sql_str(value: str) -> str:
    """``value`` as a quoted SQL string literal for a LanceDB filter."""
    return "'" + value.replace("'", "''") + "'"


def _table_state(target_path: Path, tbl) -> tuple[int, int, int]:
    st = os.stat(target_path / f"{CHUNKS_TABLE_NAME}.lance")
    return (st.st_dev, st.st_ino, int(getattr(tbl, "version", 0) or 0))


def _scan_paper_ids(tbl, chunk_count: int) -> set[str]:
    # Function-local for the same circular-import reason as
    # ``read_corpus_version`` (see the module-level NB).
    from arxmcp.ingest.corpus import project_column  # noqa: PLC0415

    projected = project_column(tbl, "paper_id", expected_rows=chunk_count)
    if projected is None:
        # Short read: fall back rather than write a marker with a
        # paper_count computed off a partial scan — an under-counted
        # marker is exactly the bug class this marker exists to avoid.
        projected = tbl.to_arrow().column("paper_id").to_pylist()
    return set(projected)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


@holds_dataset_write_lock(
    "lancedb_path", default=lambda: DEFAULT_LANCEDB_PATH
)
def write_chunks(
    chunks: list[ChunkRecord],
    embeddings: EmbedRecord,
    lancedb_path: str | Path | None = None,
    *,
    build_indices: bool = True,
    replace_paper: bool = False,
) -> int:
    """Upsert chunks + embeddings into the LanceDB ``chunks`` table.

    Creates the table on first call (with the v1 schema from
    :mod:`arxmcp.ingest.schema`); subsequent calls upsert via
    ``merge_insert(on="chunk_id")``. With ``build_indices`` (the default)
    it then rebuilds the HNSW + scalar indices over the whole table. A
    driver that writes one paper per call passes ``build_indices=False``
    and calls :func:`refresh_indices` once after its loop: a rebuild per
    paper makes a P-paper run cost O(P * rows).

    ``replace_paper`` makes the call the paper's whole chunk set: rows of
    that paper whose ``chunk_id`` is not in ``chunks`` are deleted in the
    same commit. Re-chunking a revised paper changes ids, and without it
    the old rows stay beside the new ones. ``chunks`` must then be
    non-empty and of one paper; :func:`delete_paper` removes a paper.

    Returns the LanceDB dataset version number written by this call.
    Callers can pin this version later via ``open_table(...,
    version=N)`` (E04_S02 wires the MVCC handshake; E04_S01 just
    surfaces the integer).

    Raises ``ValueError`` if any chunk's chunk_id is missing from the
    EmbedRecord (D7) or if any chunk has ``body_tokens=None`` (D8).
    """
    import lancedb  # noqa: PLC0415

    start = time.monotonic()
    replaced_paper_id = ""
    if replace_paper:
        batch_papers = {c.paper_id for c in chunks}
        if len(batch_papers) != 1:
            raise ValueError(
                "replace_paper needs the chunks of exactly one paper; got "
                f"{len(batch_papers)} paper(s)"
            )
        (replaced_paper_id,) = batch_papers
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
        # A table an older schema wrote gains the columns it lacks.
        _migrate_chunks_schema_if_needed(tbl)
    else:
        # storage_options pins the on-disk Lance format (m2). See
        # arxmcp.ingest.schema.LANCE_STORAGE_OPTIONS for the why + the
        # silent-drop gotcha on the bare data_storage_version kwarg.
        tbl = db.create_table(
            CHUNKS_TABLE_NAME,
            schema=CHUNKS_SCHEMA_V1,
            storage_options=LANCE_STORAGE_OPTIONS,
        )
    paper_ids_key = str(target_path.resolve())
    state_before_write = _table_state(target_path, tbl)
    cached = _PAPER_IDS.get(paper_ids_key)
    known_paper_ids = (
        cached[1] if cached is not None and cached[0] == state_before_write
        else None
    )
    _PAPER_IDS.pop(paper_ids_key, None)

    # Idempotent upsert by chunk_id (D5). LanceDB's merge_insert
    # accepts either a PyArrow Table or a list of dicts; we pass the
    # validated PyArrow Table directly.
    rows_inserted = 0
    rows_updated = 0
    rows_deleted = 0
    if arrow_table.num_rows > 0:
        merge = (
            tbl.merge_insert("chunk_id")
            .when_matched_update_all()
            .when_not_matched_insert_all()
        )
        # The delete arm scans the table for the paper's rows. A paper the
        # known set does not hold has none, so a new paper skips the scan.
        if replaced_paper_id and (
            known_paper_ids is None or replaced_paper_id in known_paper_ids
        ):
            merge = merge.when_not_matched_by_source_delete(
                f"paper_id = {_sql_str(replaced_paper_id)}"
            )
        merge_result = merge.execute(arrow_table)
        # Closes F5 from the E04_S01 critique: direct attribute access
        # on ``MergeResult`` so a future LanceDB rename surfaces as a
        # clear ``AttributeError`` at write time, not as a silently
        # wrong ``rows_inserted=0`` recorded forever in the ops log.
        # If LanceDB ever retires the attribute (vs. renaming),
        # downstream code is the right place to surface that — not
        # here in observability.
        rows_inserted = int(merge_result.num_inserted_rows)
        rows_updated = int(merge_result.num_updated_rows)
        rows_deleted = int(merge_result.num_deleted_rows)

    # Refresh indices best-effort (logs warnings on individual failures).
    indices_created = _create_indices(tbl) if build_indices else {}

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
        rows_deleted=rows_deleted,
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
    # concern). The distinct paper_id set comes from ``_PAPER_IDS`` when this
    # process made the previous write, so only the first write of a run scans.
    try:
        # F4 (corpus-integrity-observability-m1 critique): these counts are read
        # off the SAME `tbl` handle that pinned `dataset_version` above, under the
        # dataset write lock this call holds, so no lock-taking writer lands
        # between the version read and here, and the marker's `version` and
        # counts are coherent. One that bypasses the lock is named by the gate.
        chunk_count = tbl.count_rows()
        # corpus-integrity-observability-e3 (CAND-8): thread the total-row
        # count through WriteStats so callers can accumulate run-level
        # chunks_written for ingest-summary.json without an extra count_rows().
        stats.total_rows_after_commit = chunk_count
        if known_paper_ids is not None:
            paper_ids = known_paper_ids
            paper_ids.update(c.paper_id for c in chunks)
        else:
            paper_ids = _scan_paper_ids(tbl, chunk_count)
        paper_count = len(paper_ids)
        write_corpus_version_marker(
            target_path,
            version=dataset_version,
            chunker_version=CHUNKER_VERSION,
            embedder_version=embeddings.embedder_version,
            embed_input_policy_version=embeddings.embed_input_policy_version,
            paper_count=paper_count,
            chunk_count=chunk_count,
        )
        # corpus-integrity-observability-e2 (scout CAND-4): structured,
        # test-assertable success event on the write path. Emitted INSIDE the
        # try AFTER the marker write so chunk_count/paper_count are bound and it
        # fires only on the success path (a marker-write failure is logged by
        # the except below, not as a spurious "complete"). Aggregate counts are
        # safe at INFO — the RedactionFilter guards body/query fields only.
        logger.info(
            "write_chunks_complete",
            extra={
                "event": "write_chunks_complete",
                "corpus_version": dataset_version,
                "chunk_count": chunk_count,
                "paper_count": paper_count,
            },
        )
        _PAPER_IDS[paper_ids_key] = (_table_state(target_path, tbl), paper_ids)
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
    # block's `raise WapGateError(...)` propagates to the caller. Placing the
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
    # arithmetic (m1 fix + m3 integration test), FM-5 TOCTOU (the dataset
    # write lock; a bypassing writer is the concurrent-writer arm),
    # FM-6/FM-14 schema-version drift (deferred follow-on),
    # FM-8 wrong path (config), FM-9 silent skip (logging), FM-11 sibling
    # marker writers (m3 follow-up F2-extension).
    #
    # Function-local import: see the comment at the module's import block
    # above for why this cannot be a top-level ``from arxmcp.ingest.corpus
    # import read_corpus_version`` (circular import with
    # ``src/arxmcp/ingest/corpus.py``).
    from arxmcp.ingest.corpus import read_corpus_version  # noqa: PLC0415

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
            raise WapGateError(
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
            raise WapGateError(
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
            # A commit this call did not make shows as a marker naming
            # another version or a table past the one written here. Only
            # a writer bypassing the dataset write lock gets there.
            latest_version = _latest_version(target_path)
            concurrent = (
                re_read_marker.version != dataset_version
                or latest_version != dataset_version
            )
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
            elif concurrent:
                stats.gate_failure_reason = "concurrent_writer"
                raise WapGateError(
                    f"WAP gate: corpus-version.json marker at {target_path} reports "
                    f"chunk_count={re_read_marker.chunk_count} but tbl.count_rows()="
                    f"{fresh_count}. Cause: another writer committed to this "
                    f"dataset during this call (this call wrote version "
                    f"{dataset_version}; the marker names version "
                    f"{re_read_marker.version} and the table is at version "
                    f"{latest_version}). The rows and the writer code are not "
                    f"at fault. That writer bypassed the dataset write lock at "
                    f"{write_lock_path(target_path)}: find and stop it, then run "
                    f"`make reconcile` to rewrite the marker from the table."
                )
            else:
                stats.gate_failure_reason = "count_mismatch_arithmetic"
                routing_tag = "Routing: S6 (arithmetic regression)"
                likely_cause = (
                    "a pre-m1-style len(chunks)-instead-of-count_rows "
                    "arithmetic regression in this call (the marker "
                    "write itself succeeded; its content is just wrong)"
                )
            raise WapGateError(
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


def _latest_version(path: Path) -> int:
    """The dataset's newest committed version, read through a fresh handle."""
    import lancedb  # noqa: PLC0415

    tbl = lancedb.connect(str(path)).open_table(CHUNKS_TABLE_NAME)
    return int(getattr(tbl, "version", 0) or 0)


def refresh_indices(lancedb_path: str | Path) -> int | None:
    """Rebuild the vector + scalar indices once, after a run of writes.

    The per-paper drivers write with ``build_indices=False`` and call this
    after their loop. It commits through :func:`write_chunks` with no rows,
    so the marker moves to the post-index version (readers pinned to it
    get indexed ANN) and the write-audit gate runs as on any other write.
    The marker's embedder and input-policy versions are carried over.

    Returns the post-index dataset version, or ``None`` when there is
    nothing to index: no table, or a table without a marker. Every
    committed write leaves a marker, so the second is a table no write
    reached (a bare ``create_table``); the versions to stamp on it would
    have to be guessed.
    """
    path = Path(lancedb_path)
    if not (path / f"{CHUNKS_TABLE_NAME}.lance").is_dir():
        return None
    record = _marker_embed_record(path)
    if record is None:
        logger.warning(
            "not refreshing indices at %s: the chunks table has no "
            "corpus-version.json marker",
            path,
        )
        return None
    return write_chunks([], record, lancedb_path=path, build_indices=True)


def _marker_embed_record(path: Path) -> EmbedRecord | None:
    """An empty record stamped with the versions the marker carries.

    A commit that adds no rows (an index build, a delete) rewrites the
    marker through :func:`write_chunks`; this carries the embedder and
    input-policy versions over instead of guessing them. ``None`` when
    there is no marker.
    """
    from arxmcp.ingest.corpus import read_corpus_version  # noqa: PLC0415

    marker = read_corpus_version(path)
    if marker is None:
        return None
    # The typed view drops the policy field; read it off the file.
    raw = json.loads((path / CORPUS_VERSION_MARKER_NAME).read_text("utf-8"))
    return EmbedRecord(
        embedder_version=marker.embedder_version,
        embed_input_policy_version=str(raw.get("embed_input_policy_version", "")),
    )


@holds_dataset_write_lock("lancedb_path")
def delete_paper(lancedb_path: str | Path, paper_id: str) -> int:
    """Remove a paper from a dataset: its chunks and its derived rows.

    For a paper withdrawn upstream. Deletes the paper's ``chunks`` rows,
    then rewrites the marker through :func:`write_chunks` so it names the
    post-delete version with the new counts and the write-audit gate runs.
    Its rows in the dataset's ``definitions`` and ``equations`` tables and
    in its theorem-name index go too: those are rebuilt only for papers
    still in ``chunks``, so nothing else would remove them. The BM25
    index is rebuilt per version from ``chunks``.

    This is a write under the dataset write lock, like
    :func:`write_chunks`. It runs its own event loop for the
    theorem-name store, so it is for offline callers only. Vector indexes
    stay valid (deleted rows are masked) until the caller's end-of-run
    :func:`refresh_indices` rebuilds them.

    Idempotent. Returns the number of ``chunks`` rows removed.
    """
    import lancedb  # noqa: PLC0415

    from arxmcp.ingest.identifiers import is_valid_paper_id  # noqa: PLC0415

    if not is_valid_paper_id(paper_id):
        raise ValueError(f"paper_id {paper_id!r} is not a valid paper id")
    path = Path(lancedb_path)
    if not (path / f"{CHUNKS_TABLE_NAME}.lance").is_dir():
        return 0
    where = f"paper_id = {_sql_str(paper_id)}"
    db = lancedb.connect(str(path))
    tbl = db.open_table(CHUNKS_TABLE_NAME)
    removed = tbl.count_rows(where)
    if removed:
        key = str(path.resolve())
        cached = _PAPER_IDS.pop(key, None)
        state_before = _table_state(path, tbl)
        tbl.delete(where)
        if cached is not None and cached[0] == state_before:
            cached[1].discard(paper_id)
            _PAPER_IDS[key] = (_table_state(path, tbl), cached[1])
        record = _marker_embed_record(path)
        if record is not None:
            write_chunks([], record, lancedb_path=path, build_indices=False)
    tables_obj = db.list_tables()
    existing = set(getattr(tables_obj, "tables", tables_obj))
    for name in (DEFINITIONS_TABLE_NAME, EQUATIONS_TABLE_NAME):
        if name in existing:
            db.open_table(name).delete(where)
    _delete_theorem_names(path, paper_id)
    logger.info(
        "delete_paper_complete",
        extra={"event": "delete_paper_complete", "paper_id": paper_id,
               "chunks_removed": removed},
    )
    return removed


def _delete_theorem_names(path: Path, paper_id: str) -> None:
    import asyncio  # noqa: PLC0415

    from arxmcp.ingest.index_theorem_names import default_db_path  # noqa: PLC0415
    from arxmcp.ingest.theorem_names_store import TheoremNamesStore  # noqa: PLC0415

    db_path = default_db_path(path)
    if not db_path.is_file():
        return

    async def run() -> None:
        store = await TheoremNamesStore.open(db_path)
        try:
            await store.delete_paper(paper_id)
        finally:
            await store.close()

    asyncio.run(run())


# Closes F11 from the E04_S01 critique: ``_atomic_write_json`` was
# dead code on land. Removed; if a future side-file needs atomic
# writes, copy the pattern from ``arxmcp.ingest.preamble._write_preamble_json``
# (the canonical implementation) rather than re-introducing it here.


__all__ = [
    "ALLOWED_KINDS",
    "CORPUS_VERSION_MARKER_NAME",
    "DEFAULT_LANCEDB_PATH",
    "STORE_STATS_PATH",
    "StaleChunkerRowsError",
    "WapGateError",
    "WriteStats",
    "delete_paper",
    "load_embed_record",
    "refresh_indices",
    "refuse_stale_chunker_rows",
    "write_chunks",
    "write_corpus_version_marker",
]
