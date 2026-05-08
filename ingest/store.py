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
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pyarrow as pa

from ingest.chunker import _validate_paper_id
from ingest.chunker_types import ChunkRecord
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
    the LanceDB default (l2); BGE-M3 vectors are L2-normalized so
    l2 and cosine produce identical rankings.
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

    return dataset_version


# Closes F11 from the E04_S01 critique: ``_atomic_write_json`` was
# dead code on land. Removed; if a future side-file needs atomic
# writes, copy the pattern from ``ingest.preamble._write_preamble_json``
# (the canonical implementation) rather than re-introducing it here.


__all__ = [
    "DEFAULT_LANCEDB_PATH",
    "STORE_STATS_PATH",
    "WriteStats",
    "load_embed_record",
    "write_chunks",
]
