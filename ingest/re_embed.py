"""Partial re-embed driver (E11_S03).

Re-embeds chunks into the staging LanceDB after a ``chunker_version``
or ``embedder_version`` bump. The naive approach — re-embed every
chunk in the 200K-paper corpus — is a GPU-day operation; this module
limits work to chunks whose embedding input actually changed.

* **Reuse identity:** a stored vector is
  copied onto a freshly chunked chunk only when the chunk's reuse
  identity (:func:`ingest.chunk.reuse_identity` under the TARGET
  embedder version) equals a stored row's
  (:func:`ingest.chunk.stored_reuse_identity`): same embedding input,
  embedder version, embedding input policy and route. The chunk id
  plays no part, so a chunk whose kind moved it to the other route, a
  row from another embedder and a row under a legacy or NULL policy all
  fall to re-embed, and a chunk whose id rotated with an unchanged body
  is still copied. Reuse is per paper: a chunk is matched only against
  its own paper's stored rows.
* **Stored identity:** a stored row's identity is recomputed from the row's own
  ``body_text``, ``kind``, ``embedder_version`` and
  ``embed_input_policy_version`` columns.
* **Re-embed path:** chunks with no match are embedded via
  ``ingest.embedder.embed_paper`` (or, for textbook and TeX papers,
  ``tools.notebook_textbook_ingest._build_embed_record``).
* **Embedding-space mixing guard:** the staging table is checked
  before any write. Mixed ``embedder_version`` values → refuse.
* **Staging-path discipline:** writes go to
  ``var/arxmcp/index/lancedb-staging/``. The active
  ``corpus-version.json`` is NEVER touched.
* **`--resume`:** a paper whose staged rows already equal what this
  run would write (same chunk ids, chunker version, scalar fields and
  reuse identities) is skipped; any other paper's staged rows are
  replaced. A row a run under another ``CHUNKER_VERSION`` staged is
  therefore rewritten, not kept. No flag turns a run into a no-op.
* **One-time id rotation:** ``CHUNKER_VERSION`` v1.3 stopped hashing the
  preamble into arXiv chunk ids, so every preamble-bearing id changed.
  The bodies are unchanged, so every vector is copied. Per notebook,
  with its server stopped and any old ``lancedb-staging`` moved aside:
  ``make re-embed ARGS="--notebook=<slug> --dry-run"`` (expect
  ``reembed=0`` on every paper), ``make re-embed
  ARGS="--notebook=<slug>"``, then ``make notebook-cutover
  ARGS="--notebook=<slug> --force"``.
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
from ingest.chunk import (
    CHUNKER_VERSION,
    EMBED_INPUT_POLICY_VERSION,
    EMBEDDING_DIM,
    ChunkRecord,
    reusable_vectors,
    reuse_identity,
    route,
    stored_reuse_identity,
)
from ingest.chunker import chunk_paper
from ingest.derived_indexes import build_derived_indexes
from ingest.embedder import EMBEDDER_VERSION, embed_paper
from ingest.identifiers import is_valid_paper_id
from ingest.schema import (
    CHUNKS_TABLE_NAME,
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
    chunks_copied: int = 0          # reuse identity matched; vector copied
    chunks_re_embedded: int = 0     # no stored match; GPU compute
    chunks_dropped: int = 0         # stored id no new chunk carries
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

    Recorded in the state file. Its absence means the active corpus was
    never ingested, so the run refuses to start. Copy decisions do not use
    it: each stored row's own ``embedder_version`` is part of its reuse
    identity.
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
    if "embed_input_policy_version" not in tbl.schema.names and tbl.count_rows():
        raise RuntimeError("staging table predates embedding input policy tracking")
    if "embed_input_policy_version" in tbl.schema.names:
        policies = set(
            tbl.to_arrow().column("embed_input_policy_version").to_pylist()
        )
        if policies and policies != {EMBED_INPUT_POLICY_VERSION}:
            raise RuntimeError(
                f"staging table contains input policies {policies!r}; "
                f"expected {EMBED_INPUT_POLICY_VERSION!r}"
            )


def _delete_staging_paper_rows(staging_path: Path, paper_id: str) -> None:
    """Replace a paper atomically at the row level on resume/retry."""
    import lancedb

    if not (staging_path / "chunks.lance").is_dir():
        return
    tbl = lancedb.connect(str(staging_path)).open_table(CHUNKS_TABLE_NAME)
    safe_id = paper_id.replace("'", "''")
    tbl.delete(f"paper_id = '{safe_id}'")


#: Scalar columns a staged row must match for ``--resume`` to skip its paper.
#: ``chunker_version`` is one of them: without it a row a run under another
#: ``CHUNKER_VERSION`` staged, with an unchanged id, would be skipped and keep
#: the old stamp.
_SIGNATURE_COLUMNS = (
    "chunk_id", "chunker_version", "kind", "section_path", "theorem_name",
    "theorem_label", "printed_number", "page_start", "page_end",
    "part_index", "part_count", "source_start", "source_end",
)


def _staging_paper_signatures(staging_path: Path) -> dict[str, set[tuple]]:
    """Read each staged row's scalar fields, reuse identity and vector
    placement, grouped by paper, for the ``--resume`` skip check."""
    import lancedb

    if not (staging_path / "chunks.lance").is_dir():
        return {}
    table = lancedb.connect(str(staging_path)).open_table(CHUNKS_TABLE_NAME)
    identity_columns = (
        "paper_id", "body_text", "embedder_version", "embed_input_policy_version",
        "embedding_stmt", "embedding_proof",
    )
    result: dict[str, set[tuple]] = {}
    for row in table.to_arrow().select(
        list(dict.fromkeys(_SIGNATURE_COLUMNS + identity_columns))
    ).to_pylist():
        result.setdefault(row["paper_id"], set()).add(
            tuple(
                tuple(row[name]) if name == "section_path" else row[name]
                for name in _SIGNATURE_COLUMNS
            ) + (
                stored_reuse_identity(row),
                row["embedding_stmt"] is not None,
                row["embedding_proof"] is not None,
            )
        )
    return result


def _chunk_signature(chunk: ChunkRecord, target_embedder_version: str) -> tuple:
    """The staged-row signature this run would write for ``chunk``."""
    chunk_route = route(chunk.kind)
    return (
        chunk.chunk_id, chunk.chunker_version, chunk.kind,
        tuple(chunk.section_path),
        chunk.theorem_name, chunk.theorem_label, chunk.printed_number,
        chunk.page_start, chunk.page_end, chunk.part_index, chunk.part_count,
        chunk.source_start, chunk.source_end,
        reuse_identity(
            chunk.kind, chunk.body_text, embedder_version=target_embedder_version
        ),
        chunk_route == "stmt", chunk_route == "proof",
    )


# ---------------------------------------------------------------------------
# Diff: which new chunks reuse a stored vector
# ---------------------------------------------------------------------------


def compute_diff(
    old_rows: list[dict],
    new_chunks: list[ChunkRecord],
    *,
    target_embedder_version: str,
) -> tuple[dict[str, list[float]], set[str], set[str]]:
    """Partition one paper's new chunks into (copy, re_embed, drop).

    * ``copy``: new ``chunk_id`` -> the stored vector to reuse. A new
      chunk is copied only when its reuse identity under
      ``target_embedder_version`` equals a stored row's identity (same
      embedding input, embedder version, policy and route); the row's
      chunk id plays no part.
    * ``re_embed``: new chunk ids with no stored match.
    * ``drop``: stored chunk ids no new chunk carries. Reporting only;
      it moves no vector.

    ``old_rows`` are the paper's stored ``chunks`` rows (dicts with at
    least ``chunk_id``, ``kind``, ``body_text``, ``embedder_version``,
    ``embed_input_policy_version`` and the two vector columns).
    """
    reusable = reusable_vectors(old_rows)
    copy: dict[str, list[float]] = {}
    re_embed: set[str] = set()
    for chunk in new_chunks:
        identity = reuse_identity(
            chunk.kind, chunk.body_text, embedder_version=target_embedder_version
        )
        vector = reusable.get(identity)
        if vector is None:
            re_embed.add(chunk.chunk_id)
        else:
            copy[chunk.chunk_id] = list(vector)
    drop = {row["chunk_id"] for row in old_rows} - {c.chunk_id for c in new_chunks}
    return copy, re_embed, drop


# ---------------------------------------------------------------------------
# Active table: one scan, grouped by paper
# ---------------------------------------------------------------------------

#: Columns the per-paper diff reads from the active table.
_ACTIVE_COLUMNS = (
    "chunk_id", "paper_id", "kind", "body_text", "parser_used",
    "embedder_version", "embed_input_policy_version",
    "embedding_stmt", "embedding_proof",
)


def _index_active_table(active_lancedb_path: Path) -> dict[str, list[dict]]:
    """Read the active ``chunks`` table ONCE and group its rows by paper.

    One scan at run start, so per-paper lookups are dict-keyed rather
    than full-table scans. A table that
    predates a column (``embed_input_policy_version`` before the
    Bridgeland repair) reads it as NULL, which makes its rows
    non-reusable.
    """
    import lancedb  # noqa: PLC0415

    tbl = lancedb.connect(str(active_lancedb_path)).open_table(CHUNKS_TABLE_NAME)
    present = [name for name in _ACTIVE_COLUMNS if name in tbl.schema.names]
    # lancedb 0.30.x: to_arrow() takes no kwargs; project after load.
    rows = tbl.to_arrow().select(present).to_pylist()
    out: dict[str, list[dict]] = {}
    for row in rows:
        for name in _ACTIVE_COLUMNS:
            row.setdefault(name, None)
        pid = row["paper_id"]
        if not isinstance(pid, str) or not is_valid_paper_id(pid):
            raise ValueError(
                f"invalid paper_id in active row {row['chunk_id']!r}: {pid!r}"
            )
        out.setdefault(pid, []).append(row)
    return out


def _build_copy_embed_record(
    new_chunks_by_id: dict[str, ChunkRecord],
    copy: dict[str, list[float]],
    embedder_version: str,
) -> EmbedRecord:
    """Build the EmbedRecord for the copied vectors.

    Each vector goes in the list of its NEW chunk's route; the identity
    match guarantees the stored row was on the same route, embedded by
    ``embedder_version`` under the current policy, so both stamps are the
    row's own.
    """
    ids: dict[str, list[str]] = {"stmt": [], "proof": []}
    vectors: dict[str, list[list[float]]] = {"stmt": [], "proof": []}
    for cid, vector in copy.items():
        chunk_route = route(new_chunks_by_id[cid].kind)
        ids[chunk_route].append(cid)
        vectors[chunk_route].append(vector)

    def _array(rows: list[list[float]]) -> np.ndarray:
        if not rows:
            return np.zeros((0, EMBEDDING_DIM), dtype=np.float32)
        return np.asarray(rows, dtype=np.float32)

    return EmbedRecord(
        chunk_ids_stmt=ids["stmt"],
        embedding_stmt=_array(vectors["stmt"]),
        chunk_ids_proof=ids["proof"],
        embedding_proof=_array(vectors["proof"]),
        embedder_version=embedder_version,
        embed_input_policy_version=EMBED_INPUT_POLICY_VERSION,
    )


# ---------------------------------------------------------------------------
# Per-paper driver
# ---------------------------------------------------------------------------


@dataclass
class _PaperWorkPlan:
    """Per-paper diff result; what each chunk needs."""

    paper_id: str
    new_chunks: list[ChunkRecord]
    copy: dict[str, list[float]]
    re_embed_ids: set[str]
    drop_ids: set[str]


def _rechunk(
    paper_id: str, *, notebook_slug: str | None, parser_used: str | None
) -> list[ChunkRecord]:
    """Re-chunk one paper with the chunker that produced it."""
    if not paper_id.startswith("textbook:"):
        return chunk_paper(paper_id)
    if notebook_slug is None:
        raise ValueError(f"notebook slug required for {paper_id}")
    from ingest.textbook_chunker import _flat_paper_id, _resolve_notebook_dir
    notebook = _resolve_notebook_dir(notebook_slug)
    pdftotext_source = notebook / "parsed" / _flat_paper_id(paper_id) / "_pdftotext"
    if parser_used == "pdftotext" or pdftotext_source.is_dir():
        from ingest.textbook_pdf_chunker import chunk_textbook_pdf
        return chunk_textbook_pdf(notebook_slug, paper_id)
    if parser_used == "mineru+markdown":
        from ingest.textbook_markdown_chunker import chunk_textbook_markdown
        return chunk_textbook_markdown(notebook_slug, paper_id)
    from ingest.textbook_chunker import chunk_textbook
    return chunk_textbook(notebook_slug, paper_id)


def _plan_paper(
    paper_id: str,
    old_rows: list[dict],
    *,
    target_embedder_version: str,
    notebook_slug: str | None = None,
) -> _PaperWorkPlan:
    """Re-chunk the paper and diff it against its stored rows."""
    parser_used = old_rows[0]["parser_used"] if old_rows else None
    new_chunks = _rechunk(
        paper_id, notebook_slug=notebook_slug, parser_used=parser_used
    )
    if not new_chunks:
        raise RuntimeError(f"chunker produced no chunks for {paper_id}")
    copy, re_embed_ids, drop_ids = compute_diff(
        old_rows, new_chunks, target_embedder_version=target_embedder_version
    )
    return _PaperWorkPlan(
        paper_id=paper_id,
        new_chunks=new_chunks,
        copy=copy,
        re_embed_ids=re_embed_ids,
        drop_ids=drop_ids,
    )


def _process_paper(
    plan: _PaperWorkPlan,
    *,
    staging_lancedb_path: Path,
    target_embedder_version: str,
) -> tuple[int, int]:
    """Apply one paper's work plan. Returns ``(copied, re_embedded)``."""
    by_id: dict[str, ChunkRecord] = {
        c.chunk_id: c for c in plan.new_chunks
    }

    # --- Copy path -------------------------------------------------------
    if plan.copy:
        copy_record = _build_copy_embed_record(
            by_id, plan.copy, target_embedder_version
        )
        write_chunks(
            [by_id[cid] for cid in plan.copy], copy_record,
            lancedb_path=staging_lancedb_path, build_indices=False,
        )

    # --- Re-embed path ---------------------------------------------------
    if plan.re_embed_ids:
        if plan.paper_id.startswith("textbook:") or (
            plan.new_chunks and plan.new_chunks[0].parser_used == "tex"
        ):
            from tools.notebook_textbook_ingest import _build_embed_record
            full_record = _build_embed_record(plan.new_chunks)
        else:
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
            full_record, keep=plan.re_embed_ids
        )
        write_chunks(
            [by_id[cid] for cid in plan.re_embed_ids],
            re_embed_record,
            lancedb_path=staging_lancedb_path,
            build_indices=False,
        )

    return len(plan.copy), len(plan.re_embed_ids)


def _subset_embed_record(
    record: EmbedRecord, *, keep: set[str]
) -> EmbedRecord:
    """Return a new EmbedRecord containing only chunk_ids in ``keep``.

    Used by the re-embed path: ``embed_paper`` produces an
    EmbedRecord for the whole paper, but we only need the rows
    whose chunk_id appears in ``keep`` (the chunks with no reusable
    stored vector).
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
        embed_input_policy_version=record.embed_input_policy_version,
    )


# ---------------------------------------------------------------------------
# Top-level run
# ---------------------------------------------------------------------------


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
    notebook_slug: str | None = None,
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

    # Read OLD_EMBEDDER_VERSION up front (state file;
    # a missing marker refuses the run). Reuse is decided per row by the
    # reuse identity, which already carries each row's embedder version
    # and policy, so a model or policy change needs no separate switch.
    old_embedder_version = _read_old_embedder_version(active_lancedb_path)
    logger.info(
        "re_embed: OLD_EMBEDDER_VERSION=%s -> TARGET=%s",
        old_embedder_version, target_embedder_version,
    )

    # Closes synthesis D5: refuse to mix embedder versions in staging.
    _check_staging_embedder_versions(
        staging_lancedb_path, target_embedder_version
    )

    # Scan the active LanceDB ONCE, grouped by paper.
    # Without this hoist every paper triggered a full-table scan and the
    # partial re-embed was O(N²) in I/O.
    old_by_paper = _index_active_table(active_lancedb_path)
    summary.chunks_source = sum(len(v) for v in old_by_paper.values())

    if paper_ids is not None:
        work_papers = paper_ids
    elif notebook_slug is not None:
        from ingest.textbook_chunker import _resolve_notebook_dir
        from tools._notebook_common import read_paper_ids_from_papers_txt
        notebook = _resolve_notebook_dir(notebook_slug)
        seeded = read_paper_ids_from_papers_txt(notebook / "papers.txt")
        work_papers = sorted(set(old_by_paper) | set(seeded))
    else:
        work_papers = sorted(old_by_paper)
    # Validate every input paper_id at the input boundary.
    for pid in work_papers:
        if not is_valid_paper_id(pid):
            raise ValueError(f"invalid paper_id: {pid!r}")
        if pid.startswith("textbook:") and notebook_slug is None:
            raise ValueError(f"notebook_slug required for {pid!r}")
    summary.papers_total = len(work_papers)

    staged_signatures = _staging_paper_signatures(staging_lancedb_path) if resume else {}

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
        try:
            plan = _plan_paper(
                paper_id, old_by_paper.get(paper_id, []),
                target_embedder_version=target_embedder_version,
                notebook_slug=notebook_slug,
            )
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
                f"{paper_id}\tcopy={len(plan.copy)}\t"
                f"reembed={len(plan.re_embed_ids)}\t"
                f"drop={len(plan.drop_ids)}"
            )
            continue
        if resume and staged_signatures.get(paper_id) == {
            _chunk_signature(chunk, target_embedder_version)
            for chunk in plan.new_chunks
        }:
            summary.chunks_skipped_resume += len(plan.new_chunks)
            continue

        try:
            _delete_staging_paper_rows(staging_lancedb_path, paper_id)
            copied, re_embedded = _process_paper(
                plan,
                staging_lancedb_path=staging_lancedb_path,
                target_embedder_version=target_embedder_version,
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

    if not dry_run and (staging_lancedb_path / CORPUS_VERSION_MARKER_NAME).is_file():
        # Per-paper writes deliberately skip expensive repeated HNSW builds.
        # An empty write creates both indices once and advances the staging
        # marker to their post-index MVCC version.
        #
        # This runs even when some papers failed: ``ops/cutover.py`` C3
        # accepts ``complete_with_failures``, and its integrity probe refuses
        # an unindexed staging table. The build covers whatever staging
        # holds, which is what a cutover would serve. With no marker nothing
        # was staged, and the empty write would only create an empty table.
        try:
            write_chunks(
                [], EmbedRecord(embedder_version=target_embedder_version),
                lancedb_path=staging_lancedb_path, build_indices=True,
            )
        except Exception as exc:  # noqa: BLE001
            summary.papers_failed.append("<index-finalize>")
            summary.chunks_failed += 1
            _append_failure(failures_path, "<index-finalize>", "index_failed", str(exc))

    # Before the terminal sentinel, so a staging dataset marked complete
    # always carries the indexes built from its own chunks. After the
    # vector-index build, which advances the marker these are keyed to.
    if not dry_run and (staging_lancedb_path / CORPUS_VERSION_MARKER_NAME).is_file():
        build_derived_indexes(staging_lancedb_path)

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
            "Default: every paper in the active LanceDB (plus the "
            "notebook's papers.txt with --notebook)."
        ),
    )
    parser.add_argument(
        "--notebook",
        default=None,
        metavar="SLUG",
        help=(
            "Re-embed one notebook: its lancedb is the active source, its "
            "lancedb-staging the write target and its ops/re-embed-state.json "
            "the state file, unless the matching flag below is given. "
            "Required for a dataset that holds textbook papers."
        ),
    )
    parser.add_argument(
        "--active-lancedb-path",
        default=None,
        type=Path,
        help=(
            f"Active LanceDB path (read-only source). Default: "
            f"{DEFAULT_LANCEDB_PATH}, or the notebook's lancedb."
        ),
    )
    parser.add_argument(
        "--lancedb-staging-path",
        default=None,
        type=Path,
        help=(
            f"Staging LanceDB path (write target). Default: "
            f"{DEFAULT_LANCEDB_STAGING_PATH}, or the notebook's "
            f"lancedb-staging."
        ),
    )
    parser.add_argument(
        "--state-file",
        default=None,
        type=Path,
        help=(
            f"State file path (default: {DEFAULT_STATE_PATH}, or the "
            f"notebook's ops/re-embed-state.json)"
        ),
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
            "Skip a paper whose staged rows already equal what this run "
            "would write; replace any other paper's staged rows. See "
            "docs/ops/re-embed-runbook.md for the semantics."
        ),
    )
    args = parser.parse_args(argv)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    active_path = args.active_lancedb_path
    staging_path = args.lancedb_staging_path
    state_path = args.state_file
    if args.notebook is not None:
        # Late import: tools/ depends on ingest/, not the other way round
        # at module load. notebook_dir validates the slug and refuses a
        # symlinked or escaping notebook dir (Threat-1).
        from tools._notebook_common import notebook_dir  # noqa: PLC0415

        nb = notebook_dir(args.notebook)
        active_path = active_path or nb / "lancedb"
        staging_path = staging_path or nb / "lancedb-staging"
        state_path = state_path or nb / "ops" / "re-embed-state.json"
    active_path = active_path or DEFAULT_LANCEDB_PATH
    staging_path = staging_path or DEFAULT_LANCEDB_STAGING_PATH
    state_path = state_path or DEFAULT_STATE_PATH

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
        active_lancedb_path=active_path,
        staging_lancedb_path=staging_path,
        state_path=state_path,
        target_embedder_version=args.target_embedder_version,
        dry_run=args.dry_run,
        resume=args.resume,
        notebook_slug=args.notebook,
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
