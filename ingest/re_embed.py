"""Partial re-embed driver (E11_S03).

Re-embeds chunks into the staging LanceDB after a ``chunker_version``
or ``embedder_version`` bump. The naive approach — re-embed every
chunk in the 200K-paper corpus — is a GPU-day operation; this module
limits work to chunks whose **content** actually changed by exploiting
the content-addressable chunk_id contract.

Per [research-synthesis.md](.claude/notes/milestones/E11_S03/research-synthesis.md):

* **Content identity:** ``ingest.chunker._compute_chunk_id`` is
  ``sha256(preamble_text + NFC(body_text))[:16]``. Two chunks with
  byte-identical canonical content have the same id; their
  embeddings are valid across chunker bumps (NOT across embedder
  bumps).
* **Copy path:** chunks whose id appears in both the OLD and NEW
  set have their embedding VECTORS copied from the old LanceDB
  version via ``to_arrow(filter=...)``. No GPU work.
* **Re-embed path:** chunks whose id is NEW must be embedded via
  the existing ``ingest.embedder.embed_paper``. The chunker is
  invoked first; the embedder's per-paper sidecar is the source
  of vectors.
* **F1-class guard:** copied rows must come from old rows whose
  ``embedder_version`` matches the version recorded in the active
  ``corpus-version.json`` at run start. A mismatch refuses.
* **Embedding-space mixing guard:** the staging table is checked
  before any write. Mixed ``embedder_version`` values → refuse.
* **Staging-path discipline:** writes go to
  ``var/arxmcp/index/lancedb-staging/``. The active
  ``corpus-version.json`` is NEVER touched.
* **`--resume`:** LanceDB-write-side. Scan the staging table for
  chunk_ids already present; subtract from the work queue. No
  no-op flag (closes E11_S01 F3 lesson).
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import logging
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from ingest.bulk_ingest import DEFAULT_LANCEDB_STAGING_PATH
from ingest.chunker import chunk_paper
from ingest.chunker_types import CHUNKER_VERSION, ChunkRecord
from ingest.embedder import EMBEDDER_VERSION, embed_paper
from ingest.identifiers import is_valid_arxiv_paper_id, paper_id_from_chunk_id
from ingest.schema import (
    CHUNKS_TABLE_NAME,
    EMBEDDING_DIM,
    EmbedRecord,
)
from ingest.store import (
    CORPUS_VERSION_MARKER_NAME,
    DEFAULT_LANCEDB_PATH,
    load_embed_record,
    write_chunks,
)

logger = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parent.parent

#: Default state file location.
DEFAULT_STATE_PATH: Path = (
    REPO_ROOT / "var" / "arxmcp" / "ops" / "re-embed-state.json"
)

#: Default per-paper failures JSONL.
DEFAULT_FAILURES_PATH: Path = (
    REPO_ROOT / "var" / "arxmcp" / "ops" / "parser-failures" / "re-embed.jsonl"
)


# ---------------------------------------------------------------------------
# Result type
# ---------------------------------------------------------------------------


@dataclass
class ReEmbedSummary:
    """Aggregate of one re-embed run.

    ``copy_fraction`` is the AC1 metric: at 95% unchanged content,
    this should be ≥ 0.95.
    """

    papers_total: int = 0
    chunks_source: int = 0          # chunks in the OLD LanceDB version
    chunks_target: int = 0          # chunks in the NEW chunker output
    chunks_copied: int = 0          # unchanged id; vectors copied from old
    chunks_re_embedded: int = 0     # new id; GPU compute
    chunks_dropped: int = 0         # in old but not new (content restructured)
    chunks_skipped_resume: int = 0  # already in staging (--resume path)
    chunks_failed: int = 0
    elapsed_seconds: float = 0.0
    papers_failed: list[str] = field(default_factory=list)

    @property
    def copy_fraction(self) -> float:
        """Brief AC1: ``chunks_copied / (chunks_copied + chunks_re_embedded)``."""
        total = self.chunks_copied + self.chunks_re_embedded
        return self.chunks_copied / total if total else 0.0


# ---------------------------------------------------------------------------
# State file (atomic JSON)
# ---------------------------------------------------------------------------


def _read_state(path: Path) -> dict:
    if not path.is_file():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise RuntimeError(
            f"re-embed-state.json at {path} is malformed: {exc}"
        ) from exc


def _write_state(path: Path, state: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(
        json.dumps(state, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    tmp.replace(path)


def _utc_iso() -> str:
    return _dt.datetime.now(_dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


# ---------------------------------------------------------------------------
# Staging-marker sentinel — closes adversary F2 (synthesis D8)
# ---------------------------------------------------------------------------

#: Filename of the sentinel that sits alongside the staging
#: ``corpus-version.json``. Read by E11_S05's cutover gating and by
#: operators inspecting the staging path mid-run. The staging
#: ``corpus-version.json`` is overwritten by ``write_chunks`` on every
#: per-paper call (no ``status`` field), so we carry the status
#: contract in this companion file instead of patching ``write_chunks``.
RE_EMBED_PROGRESS_NAME: str = "re-embed-progress.json"


def _write_progress_sentinel(
    staging_path: Path,
    *,
    status: str,
    target_embedder_version: str,
    target_chunker_version: str,
    extra: dict | None = None,
) -> None:
    """Write the re-embed progress sentinel alongside the staging
    ``corpus-version.json`` (closes adversary F2 / synthesis D8).

    Atomic via tmp + rename. The presence of ``status="complete"``
    is the signal to E11_S05's cutover gating that the staging
    dataset is safe to promote; any other value (or an absent
    file) means the run is incomplete or has failed.
    """
    staging_path.mkdir(parents=True, exist_ok=True)
    payload = {
        "status": status,
        "target_embedder_version": target_embedder_version,
        "target_chunker_version": target_chunker_version,
        "updated_utc": _utc_iso(),
    }
    if extra:
        payload.update(extra)
    target = staging_path / RE_EMBED_PROGRESS_NAME
    tmp = target.with_suffix(target.suffix + ".tmp")
    tmp.write_text(
        json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    tmp.replace(target)


# ---------------------------------------------------------------------------
# Active-corpus inspection — read OLD_EMBEDDER_VERSION before run
# ---------------------------------------------------------------------------


def _read_old_embedder_version(active_lancedb_path: Path) -> str:
    """Read ``embedder_version`` from the active ``corpus-version.json``.

    Used as the F1-class guard's authoritative reference: any row
    copied from the old LanceDB must carry this exact version
    string, otherwise the copy is refused.
    """
    marker = active_lancedb_path / CORPUS_VERSION_MARKER_NAME
    if not marker.is_file():
        raise RuntimeError(
            f"active corpus-version.json missing at {marker}; "
            f"cannot determine OLD_EMBEDDER_VERSION. "
            f"Run the bulk ingest first."
        )
    data = json.loads(marker.read_text(encoding="utf-8"))
    embed_version = data.get("embedder_version")
    if not isinstance(embed_version, str) or not embed_version:
        raise RuntimeError(
            f"active corpus-version.json at {marker} has no "
            f"`embedder_version` field; cannot run partial re-embed."
        )
    return embed_version


# ---------------------------------------------------------------------------
# Embedding-space mixing guard
# ---------------------------------------------------------------------------


def _check_staging_embedder_versions(
    staging_path: Path, target_embedder_version: str
) -> None:
    """Refuse if the staging table has rows with a different embedder
    version than the target. Closes synthesis D5.

    No-op when the staging path does not yet exist (clean start) or
    the chunks table is absent.
    """
    if not staging_path.exists():
        return
    import lancedb  # noqa: PLC0415

    db = lancedb.connect(str(staging_path))
    tables_obj = db.list_tables()
    existing = set(getattr(tables_obj, "tables", tables_obj))
    if CHUNKS_TABLE_NAME not in existing:
        return
    tbl = db.open_table(CHUNKS_TABLE_NAME)
    # lancedb 0.30.x: to_arrow() takes no kwargs; project after load.
    versions = tbl.to_arrow().select(["embedder_version"]).to_pydict()
    distinct = set(versions["embedder_version"])
    bad = {v for v in distinct if v != target_embedder_version}
    if bad:
        raise RuntimeError(
            f"staging table at {staging_path} already contains rows with "
            f"embedder_version(s) {sorted(bad)} which differ from the "
            f"target {target_embedder_version!r}. Refusing to mix "
            f"embedding spaces (cosine distance is meaningless across "
            f"spaces). Drop the staging dataset and retry, OR change "
            f"the target embedder_version to match the existing rows."
        )


# ---------------------------------------------------------------------------
# Diff: old chunk-id set vs new chunk-id set
# ---------------------------------------------------------------------------


def compute_diff(
    old_chunk_ids: set[str], new_chunk_ids: set[str]
) -> tuple[set[str], set[str], set[str]]:
    """Partition chunk_ids into (copy, re_embed, drop).

    * ``copy``: ids in BOTH sets — unchanged content.
    * ``re_embed``: ids in NEW but not OLD — new/changed content.
    * ``drop``: ids in OLD but not NEW — removed/restructured.
    """
    copy = old_chunk_ids & new_chunk_ids
    re_embed = new_chunk_ids - old_chunk_ids
    drop = old_chunk_ids - new_chunk_ids
    return copy, re_embed, drop


# ---------------------------------------------------------------------------
# Already-written set (for --resume)
# ---------------------------------------------------------------------------


def _staging_chunk_ids(staging_path: Path) -> set[str]:
    """Return the set of chunk_ids already in the staging table.

    Returns empty set when the staging path or chunks table doesn't
    exist.
    """
    if not staging_path.exists():
        return set()
    import lancedb  # noqa: PLC0415

    db = lancedb.connect(str(staging_path))
    tables_obj = db.list_tables()
    existing = set(getattr(tables_obj, "tables", tables_obj))
    if CHUNKS_TABLE_NAME not in existing:
        return set()
    tbl = db.open_table(CHUNKS_TABLE_NAME)
    # lancedb 0.30.x: to_arrow() takes no kwargs; project after load.
    rows = tbl.to_arrow().select(["chunk_id"]).to_pydict()
    return set(rows["chunk_id"])


# ---------------------------------------------------------------------------
# Copy path: read old LanceDB rows and reconstruct EmbedRecord
# ---------------------------------------------------------------------------


def _build_old_rows_index(active_lancedb_path: Path) -> dict[str, dict]:
    """Read the active LanceDB chunks table ONCE and return a
    chunk_id-keyed index of the columns needed for the copy path.

    Closes adversary F1: the previous ``_load_old_rows`` re-scanned
    the full table on every paper, undoing the GPU-budget savings
    the brief targeted. This function is called exactly once at
    run start; subsequent per-paper copy lookups are dict-keyed.

    Returns a dict keyed by chunk_id with ``embedding_stmt``,
    ``embedding_proof``, ``embedder_version``, ``kind``.
    """
    import lancedb  # noqa: PLC0415

    db = lancedb.connect(str(active_lancedb_path))
    tbl = db.open_table(CHUNKS_TABLE_NAME)
    # lancedb 0.30.x: to_arrow() takes no kwargs; project after load.
    # The 5 projected columns (chunk_id + 2 embeddings + version + kind)
    # are the read-only seed for the per-paper copy plan; the embeddings
    # are the only ones that matter for size.
    arrow = tbl.to_arrow().select(
        [
            "chunk_id",
            "embedding_stmt",
            "embedding_proof",
            "embedder_version",
            "kind",
        ]
    )
    out: dict[str, dict] = {}
    ids = arrow["chunk_id"].to_pylist()
    stmts = arrow["embedding_stmt"].to_pylist()
    proofs = arrow["embedding_proof"].to_pylist()
    versions = arrow["embedder_version"].to_pylist()
    kinds = arrow["kind"].to_pylist()
    for cid, stmt, proof, ver, kind in zip(
        ids, stmts, proofs, versions, kinds, strict=True
    ):
        out[cid] = {
            "embedding_stmt": stmt,
            "embedding_proof": proof,
            "embedder_version": ver,
            "kind": kind,
        }
    return out


def _load_old_rows(
    active_lancedb_path: Path,
    chunk_ids: set[str],
    *,
    cache: dict[str, dict] | None = None,
) -> dict[str, dict]:
    """Look up old rows for the given chunk_ids.

    If ``cache`` is provided (the index built by
    :func:`_build_old_rows_index`), the lookup is a dict slice —
    O(len(chunk_ids)) and zero LanceDB I/O. If not, falls back to
    the legacy per-call scan (kept for tests that mock the function
    pointer; production callers always pass the cache).
    """
    if not chunk_ids:
        return {}
    if cache is not None:
        return {cid: cache[cid] for cid in chunk_ids if cid in cache}
    return {
        cid: row
        for cid, row in _build_old_rows_index(active_lancedb_path).items()
        if cid in chunk_ids
    }


def _build_copy_embed_record(
    new_chunks_by_id: dict[str, ChunkRecord],
    old_rows_by_id: dict[str, dict],
    old_embedder_version: str,
    target_embedder_version: str,
) -> EmbedRecord:
    """Build an EmbedRecord from old rows that should be copied.

    F1-class guard: every old row's ``embedder_version`` MUST match
    ``old_embedder_version`` (read from the active corpus-version.json
    at run start). A mismatch is a stale or corrupt input — refuse.
    """
    chunk_ids_stmt: list[str] = []
    chunk_ids_proof: list[str] = []
    embeddings_stmt: list[list[float]] = []
    embeddings_proof: list[list[float]] = []

    for cid, row in old_rows_by_id.items():
        if row["embedder_version"] != old_embedder_version:
            raise RuntimeError(
                f"copy path: old row for chunk_id={cid!r} has "
                f"embedder_version={row['embedder_version']!r}, "
                f"expected {old_embedder_version!r} (the active "
                f"corpus-version.json's value). Refusing to copy a "
                f"row from a different embedding space."
            )
        kind = row["kind"]
        # Statement chunks store the vector in ``embedding_stmt``;
        # proof chunks store it in ``embedding_proof``. The other
        # column is NULL.
        if kind == "proof":
            vec = row["embedding_proof"]
            if vec is None:
                raise RuntimeError(
                    f"copy path: proof chunk {cid!r} has NULL "
                    f"embedding_proof in the old LanceDB version"
                )
            chunk_ids_proof.append(cid)
            embeddings_proof.append(vec)
        else:
            vec = row["embedding_stmt"]
            if vec is None:
                raise RuntimeError(
                    f"copy path: stmt-side chunk {cid!r} (kind={kind}) "
                    f"has NULL embedding_stmt in the old LanceDB version"
                )
            chunk_ids_stmt.append(cid)
            embeddings_stmt.append(vec)

    stmt_arr = (
        np.asarray(embeddings_stmt, dtype=np.float32)
        if embeddings_stmt
        else np.zeros((0, EMBEDDING_DIM), dtype=np.float32)
    )
    proof_arr = (
        np.asarray(embeddings_proof, dtype=np.float32)
        if embeddings_proof
        else np.zeros((0, EMBEDDING_DIM), dtype=np.float32)
    )
    # The COPIED row is stamped with the NEW target embedder version
    # because the VECTOR is valid in the new corpus version's space
    # (it came from the same embedder model — only chunker bumped).
    return EmbedRecord(
        chunk_ids_stmt=chunk_ids_stmt,
        embedding_stmt=stmt_arr,
        chunk_ids_proof=chunk_ids_proof,
        embedding_proof=proof_arr,
        embedder_version=target_embedder_version,
    )


# ---------------------------------------------------------------------------
# Per-paper driver
# ---------------------------------------------------------------------------


@dataclass
class _PaperWorkPlan:
    """Per-paper diff result; what each chunk needs."""

    paper_id: str
    new_chunks: list[ChunkRecord]
    copy_ids: set[str]
    re_embed_ids: set[str]
    drop_ids: set[str]


def _plan_paper(
    paper_id: str, old_chunk_ids_for_paper: set[str]
) -> _PaperWorkPlan:
    """Re-chunk the paper, diff against the old chunk-id set."""
    new_chunks = chunk_paper(paper_id)
    new_ids = {c.chunk_id for c in new_chunks}
    copy_ids, re_embed_ids, drop_ids = compute_diff(
        old_chunk_ids_for_paper, new_ids
    )
    return _PaperWorkPlan(
        paper_id=paper_id,
        new_chunks=new_chunks,
        copy_ids=copy_ids,
        re_embed_ids=re_embed_ids,
        drop_ids=drop_ids,
    )


def _process_paper(
    plan: _PaperWorkPlan,
    *,
    active_lancedb_path: Path,
    staging_lancedb_path: Path,
    old_embedder_version: str,
    target_embedder_version: str,
    already_in_staging: set[str],
    old_rows_cache: dict[str, dict] | None = None,
) -> tuple[int, int, int]:
    """Apply one paper's work plan. Returns ``(copied, re_embedded,
    skipped_resume)``."""
    by_id: dict[str, ChunkRecord] = {
        c.chunk_id: c for c in plan.new_chunks
    }

    copy_pending = plan.copy_ids - already_in_staging
    re_embed_pending = plan.re_embed_ids - already_in_staging
    skipped = len(plan.copy_ids) + len(plan.re_embed_ids) - (
        len(copy_pending) + len(re_embed_pending)
    )

    # --- Copy path -------------------------------------------------------
    if copy_pending:
        old_rows = _load_old_rows(
            active_lancedb_path, copy_pending, cache=old_rows_cache
        )
        # Sanity: every requested id must come back from the old table.
        missing = copy_pending - old_rows.keys()
        if missing:
            raise RuntimeError(
                f"paper={plan.paper_id}: copy path expected {len(copy_pending)} "
                f"chunk_ids in the old LanceDB, got {len(old_rows)} "
                f"(missing {sorted(missing)[:5]}...). The chunk-id set "
                f"may have drifted out of sync with the active dataset."
            )
        copy_record = _build_copy_embed_record(
            new_chunks_by_id=by_id,
            old_rows_by_id=old_rows,
            old_embedder_version=old_embedder_version,
            target_embedder_version=target_embedder_version,
        )
        copy_chunks = [by_id[cid] for cid in copy_pending]
        write_chunks(
            copy_chunks, copy_record, lancedb_path=staging_lancedb_path
        )

    # --- Re-embed path ---------------------------------------------------
    if re_embed_pending:
        embed_stats = embed_paper(plan.paper_id)
        if embed_stats.status != "ok":
            raise RuntimeError(
                f"paper={plan.paper_id}: embedder returned status="
                f"{embed_stats.status!r} ({embed_stats.error_class}): "
                f"{embed_stats.error}"
            )
        full_record = load_embed_record(plan.paper_id)
        if full_record is None:
            raise RuntimeError(
                f"paper={plan.paper_id}: embed_paper ok but no NPZ "
                f"sidecar found"
            )
        if full_record.embedder_version != target_embedder_version:
            raise RuntimeError(
                f"paper={plan.paper_id}: embedder sidecar version "
                f"{full_record.embedder_version!r} != target "
                f"{target_embedder_version!r}. The on-disk embedder "
                f"is out of sync with the target."
            )
        re_embed_record = _subset_embed_record(
            full_record, keep=re_embed_pending
        )
        re_embed_chunks = [by_id[cid] for cid in re_embed_pending]
        write_chunks(
            re_embed_chunks,
            re_embed_record,
            lancedb_path=staging_lancedb_path,
        )

    return len(copy_pending), len(re_embed_pending), skipped


def _subset_embed_record(
    record: EmbedRecord, *, keep: set[str]
) -> EmbedRecord:
    """Return a new EmbedRecord containing only chunk_ids in ``keep``.

    Used by the re-embed path: ``embed_paper`` produces an
    EmbedRecord for the whole paper, but we only need the rows
    whose chunk_id appears in ``keep`` (the new/changed ids).
    """
    stmt_mask = [cid in keep for cid in record.chunk_ids_stmt]
    proof_mask = [cid in keep for cid in record.chunk_ids_proof]
    return EmbedRecord(
        chunk_ids_stmt=[
            cid for cid, m in zip(record.chunk_ids_stmt, stmt_mask, strict=True) if m
        ],
        embedding_stmt=record.embedding_stmt[stmt_mask]
        if stmt_mask
        else np.zeros((0, EMBEDDING_DIM), dtype=np.float32),
        chunk_ids_proof=[
            cid for cid, m in zip(record.chunk_ids_proof, proof_mask, strict=True) if m
        ],
        embedding_proof=record.embedding_proof[proof_mask]
        if proof_mask
        else np.zeros((0, EMBEDDING_DIM), dtype=np.float32),
        embedder_version=record.embedder_version,
    )


# ---------------------------------------------------------------------------
# Top-level run
# ---------------------------------------------------------------------------


def _index_old_chunk_ids_by_paper(
    active_lancedb_path: Path,
) -> dict[str, set[str]]:
    """Scan the active LanceDB and group every chunk_id by paper_id."""
    import lancedb  # noqa: PLC0415

    db = lancedb.connect(str(active_lancedb_path))
    tbl = db.open_table(CHUNKS_TABLE_NAME)
    # lancedb 0.30.x's LanceTable.to_arrow() accepts no kwargs; project
    # the chunk_id column on the loaded pyarrow.Table instead. The
    # full-table load is acceptable here because chunk_id is a short
    # utf8 column (16-32 bytes per row); a 10K-row table fits in ~1 MB.
    arrow = tbl.to_arrow().select(["chunk_id"])
    out: dict[str, set[str]] = {}
    for cid in arrow["chunk_id"].to_pylist():
        try:
            pid = paper_id_from_chunk_id(cid)
        except ValueError:
            logger.warning(
                "re_embed: malformed chunk_id in active LanceDB: %r",
                cid,
            )
            continue
        out.setdefault(pid, set()).add(cid)
    return out


def run_re_embed(
    *,
    paper_ids: list[str] | None = None,
    active_lancedb_path: Path = DEFAULT_LANCEDB_PATH,
    staging_lancedb_path: Path = DEFAULT_LANCEDB_STAGING_PATH,
    state_path: Path = DEFAULT_STATE_PATH,
    failures_path: Path = DEFAULT_FAILURES_PATH,
    target_embedder_version: str = EMBEDDER_VERSION,
    target_chunker_version: str = CHUNKER_VERSION,
    dry_run: bool = False,
    resume: bool = False,
) -> ReEmbedSummary:
    """Drive a partial re-embed of the corpus.

    The active ``corpus-version.json`` is NEVER advanced — writes go
    to the staging path. Promotion is E11_S05's atomic cutover.
    """
    started = time.monotonic()
    # Closes infra-safety IS4: capture started_utc ONCE so per-paper
    # checkpoint writes don't show a drifting timestamp.
    started_utc = _utc_iso()
    summary = ReEmbedSummary()

    # Closes synthesis D6: read OLD_EMBEDDER_VERSION up front.
    old_embedder_version = _read_old_embedder_version(active_lancedb_path)
    logger.info(
        "re_embed: OLD_EMBEDDER_VERSION=%s -> TARGET=%s",
        old_embedder_version, target_embedder_version,
    )

    # Closes synthesis D5: refuse to mix embedder versions in staging.
    _check_staging_embedder_versions(
        staging_lancedb_path, target_embedder_version
    )

    # Build the old-chunk-id index per paper. Used to compute the diff.
    old_by_paper = _index_old_chunk_ids_by_paper(active_lancedb_path)
    summary.chunks_source = sum(len(v) for v in old_by_paper.values())

    # Closes adversary F1: scan the active LanceDB ONCE for the copy
    # path. Without this hoist, every paper triggered a full-table
    # scan and the partial re-embed was O(N²) in I/O.
    old_rows_cache = _build_old_rows_index(active_lancedb_path)

    work_papers = (
        paper_ids
        if paper_ids is not None
        else sorted(old_by_paper.keys())
    )
    # Validate every input paper_id at the input boundary.
    for pid in work_papers:
        if not is_valid_arxiv_paper_id(pid):
            raise ValueError(f"invalid paper_id: {pid!r}")
    summary.papers_total = len(work_papers)

    already_in_staging = _staging_chunk_ids(staging_lancedb_path) if resume else set()
    summary.chunks_skipped_resume = 0  # accumulated below

    # Closes adversary F2 (synthesis D8): write the in-progress
    # sentinel BEFORE any write_chunks call. The staging
    # corpus-version.json will be overwritten on every per-paper
    # write with a standard (no-status) doc; the sentinel here is
    # the durable run-status signal an E11_S05 cutover script
    # checks before promoting the staging dataset.
    if not dry_run:
        _write_progress_sentinel(
            staging_lancedb_path,
            status="in_progress",
            target_embedder_version=target_embedder_version,
            target_chunker_version=target_chunker_version,
            extra={
                "started_utc": started_utc,
                "papers_total": summary.papers_total,
            },
        )

    # Initial state-file write (in-progress). Closes IS4:
    # use the boot-time started_utc throughout.
    _write_state(
        state_path,
        {
            "status": "in_progress",
            "from_lancedb_path": str(active_lancedb_path),
            "to_lancedb_staging_path": str(staging_lancedb_path),
            "old_embedder_version": old_embedder_version,
            "target_embedder_version": target_embedder_version,
            "target_chunker_version": target_chunker_version,
            "papers_total": summary.papers_total,
            "started_utc": started_utc,
            "last_checkpoint_utc": started_utc,
        },
    )

    for paper_id in work_papers:
        old_ids = old_by_paper.get(paper_id, set())
        try:
            plan = _plan_paper(paper_id, old_ids)
        except Exception as exc:  # noqa: BLE001 — per-paper isolation
            logger.warning(
                "re_embed: chunker failure on paper=%s: %s", paper_id, exc
            )
            summary.papers_failed.append(paper_id)
            summary.chunks_failed += 1
            _append_failure(failures_path, paper_id, "chunker_failed", str(exc))
            continue
        summary.chunks_target += len(plan.new_chunks)
        summary.chunks_dropped += len(plan.drop_ids)

        if dry_run:
            print(
                f"{paper_id}\tcopy={len(plan.copy_ids)}\t"
                f"reembed={len(plan.re_embed_ids)}\t"
                f"drop={len(plan.drop_ids)}"
            )
            continue

        try:
            copied, re_embedded, skipped = _process_paper(
                plan,
                active_lancedb_path=active_lancedb_path,
                staging_lancedb_path=staging_lancedb_path,
                old_embedder_version=old_embedder_version,
                target_embedder_version=target_embedder_version,
                already_in_staging=already_in_staging,
                # Closes adversary F1: pass the pre-built old-rows
                # index so per-paper copy lookups are dict-keyed
                # rather than full-table scans.
                old_rows_cache=old_rows_cache,
            )
        except Exception as exc:  # noqa: BLE001 — per-paper isolation
            logger.error(
                "re_embed: failure on paper=%s: %s", paper_id, exc
            )
            summary.papers_failed.append(paper_id)
            summary.chunks_failed += 1
            _append_failure(failures_path, paper_id, "process_failed", str(exc))
            continue

        summary.chunks_copied += copied
        summary.chunks_re_embedded += re_embedded
        summary.chunks_skipped_resume += skipped

        # Checkpoint after every paper.
        _write_state(
            state_path,
            {
                "status": "in_progress",
                "from_lancedb_path": str(active_lancedb_path),
                "to_lancedb_staging_path": str(staging_lancedb_path),
                "old_embedder_version": old_embedder_version,
                "target_embedder_version": target_embedder_version,
                "target_chunker_version": target_chunker_version,
                "papers_total": summary.papers_total,
                "last_paper_id_written": paper_id,
                "chunks_copied": summary.chunks_copied,
                "chunks_re_embedded": summary.chunks_re_embedded,
                "chunks_dropped": summary.chunks_dropped,
                # Closes IS5: persist chunks_skipped_resume per
                # checkpoint so operators can observe resume
                # progress in the durable state file.
                "chunks_skipped_resume": summary.chunks_skipped_resume,
                # Closes IS4: use the boot-time started_utc so the
                # state file's started_utc doesn't drift mid-run.
                "started_utc": started_utc,
                "last_checkpoint_utc": _utc_iso(),
            },
        )

    summary.elapsed_seconds = time.monotonic() - started

    # Finalize state on success (no failures past the per-paper isolation).
    final_status = "complete" if not summary.papers_failed else "complete_with_failures"
    _write_state(
        state_path,
        {
            "status": final_status,
            "from_lancedb_path": str(active_lancedb_path),
            "to_lancedb_staging_path": str(staging_lancedb_path),
            "old_embedder_version": old_embedder_version,
            "target_embedder_version": target_embedder_version,
            "target_chunker_version": target_chunker_version,
            "papers_total": summary.papers_total,
            "papers_failed": summary.papers_failed,
            "chunks_copied": summary.chunks_copied,
            "chunks_re_embedded": summary.chunks_re_embedded,
            "chunks_dropped": summary.chunks_dropped,
            # Closes IS5: include the resume-skip count in the
            # terminal record. The CLI summary scrolls; the state
            # file is the durable artifact.
            "chunks_skipped_resume": summary.chunks_skipped_resume,
            "elapsed_seconds": round(summary.elapsed_seconds, 1),
            # Closes IS4: keep started_utc stable; add completed_utc.
            "started_utc": started_utc,
            "completed_utc": _utc_iso(),
        },
    )

    # Closes adversary F2 (synthesis D8) — write the terminal
    # sentinel. The presence of status="complete" is what gates
    # E11_S05's atomic cutover from promoting a half-finished
    # staging dataset.
    if not dry_run:
        _write_progress_sentinel(
            staging_lancedb_path,
            status=final_status,
            target_embedder_version=target_embedder_version,
            target_chunker_version=target_chunker_version,
            extra={
                "started_utc": started_utc,
                "completed_utc": _utc_iso(),
                "papers_total": summary.papers_total,
                "papers_failed_count": len(summary.papers_failed),
                "chunks_copied": summary.chunks_copied,
                "chunks_re_embedded": summary.chunks_re_embedded,
                "chunks_skipped_resume": summary.chunks_skipped_resume,
            },
        )
    return summary


def _append_failure(
    path: Path, paper_id: str, reason: str, detail: str
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "paper_id": paper_id,
        "reason": reason,
        "detail": detail,
        "timestamp": _utc_iso(),
    }
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _cli(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        description="arXMCP partial re-embed driver (E11_S03).",
    )
    parser.add_argument(
        "--paper-ids-file",
        default=None,
        type=Path,
        help=(
            "Newline-separated paper-id list to scope the run. "
            "Default: every paper in the active LanceDB."
        ),
    )
    parser.add_argument(
        "--active-lancedb-path",
        default=str(DEFAULT_LANCEDB_PATH),
        type=Path,
        help=(
            f"Active LanceDB path (read-only source). Default: "
            f"{DEFAULT_LANCEDB_PATH}."
        ),
    )
    parser.add_argument(
        "--lancedb-staging-path",
        default=str(DEFAULT_LANCEDB_STAGING_PATH),
        type=Path,
        help=(
            f"Staging LanceDB path (write target). Default: "
            f"{DEFAULT_LANCEDB_STAGING_PATH}."
        ),
    )
    parser.add_argument(
        "--state-file",
        default=str(DEFAULT_STATE_PATH),
        type=Path,
        help=f"State file path (default: {DEFAULT_STATE_PATH})",
    )
    parser.add_argument(
        "--target-embedder-version",
        default=EMBEDDER_VERSION,
        help=(
            f"Target embedder_version stamped on every written row. "
            f"Default (current build): {EMBEDDER_VERSION!r}."
        ),
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help=(
            "Run the chunker + diff per paper; print copy / re-embed "
            "/ drop counts; perform no LanceDB writes."
        ),
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help=(
            "Skip chunk_ids already written to the staging table. "
            "LanceDB-write-side resume — see "
            "docs/ops/re-embed-runbook.md for the semantics."
        ),
    )
    args = parser.parse_args(argv)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    paper_ids: list[str] | None = None
    if args.paper_ids_file is not None:
        if not args.paper_ids_file.is_file():
            raise FileNotFoundError(
                f"--paper-ids-file not found: {args.paper_ids_file}"
            )
        paper_ids = [
            line.strip()
            for line in args.paper_ids_file.read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        ]

    summary = run_re_embed(
        paper_ids=paper_ids,
        active_lancedb_path=args.active_lancedb_path,
        staging_lancedb_path=args.lancedb_staging_path,
        state_path=args.state_file,
        target_embedder_version=args.target_embedder_version,
        dry_run=args.dry_run,
        resume=args.resume,
    )
    print(
        f"papers={summary.papers_total} "
        f"chunks_source={summary.chunks_source} "
        f"chunks_target={summary.chunks_target} "
        f"copied={summary.chunks_copied} "
        f"re_embedded={summary.chunks_re_embedded} "
        f"dropped={summary.chunks_dropped} "
        f"skipped_resume={summary.chunks_skipped_resume} "
        f"failed={summary.chunks_failed} "
        f"copy_fraction={summary.copy_fraction:.3f} "
        f"elapsed={summary.elapsed_seconds:.1f}s"
    )
    return 0 if not summary.papers_failed else 1


if __name__ == "__main__":  # pragma: no cover
    sys.exit(_cli(sys.argv[1:]))


__all__ = [
    "DEFAULT_FAILURES_PATH",
    "DEFAULT_STATE_PATH",
    "ReEmbedSummary",
    "compute_diff",
    "run_re_embed",
]
