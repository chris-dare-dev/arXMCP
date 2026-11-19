"""Partial re-embed driver (E11_S03).

Re-embeds chunks into the staging LanceDB after a ``chunker_version``
or ``embedder_version`` bump. The naive approach — re-embed every
chunk in the 200K-paper corpus — is a GPU-day operation; this module
limits work to chunks whose **content** actually changed by exploiting
the content-addressable chunk_id contract.

The design:

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
from ingest.derived_indexes import build_derived_indexes
from ingest.embedder import EMBED_INPUT_POLICY_VERSION, EMBEDDER_VERSION, embed_paper
from ingest.identifiers import is_valid_paper_id
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


def _staging_paper_signatures(staging_path: Path) -> dict[str, set[tuple]]:
    """Read scalar chunk identity and provenance for a safe resume check."""
    import lancedb

    if not (staging_path / "chunks.lance").is_dir():
        return {}
    table = lancedb.connect(str(staging_path)).open_table(CHUNKS_TABLE_NAME)
    columns = (
        "chunk_id", "paper_id", "kind", "section_path", "theorem_name",
        "theorem_label", "printed_number", "page_start", "page_end",
        "part_index", "part_count", "source_start", "source_end",
    )
    result: dict[str, set[tuple]] = {}
    for row in table.to_arrow().select(
        [*columns, "embedding_stmt", "embedding_proof"]
    ).to_pylist():
        result.setdefault(row["paper_id"], set()).add(
            tuple(
                tuple(row[name]) if name == "section_path" else row[name]
                for name in columns if name != "paper_id"
            ) + (
                row["embedding_stmt"] is not None,
                row["embedding_proof"] is not None,
            )
        )
    return result


def _chunk_signature(chunk: ChunkRecord) -> tuple:
    return (
        chunk.chunk_id, chunk.kind, tuple(chunk.section_path),
        chunk.theorem_name, chunk.theorem_label, chunk.printed_number,
        chunk.page_start, chunk.page_end, chunk.part_index, chunk.part_count,
        chunk.source_start, chunk.source_end,
        chunk.kind != "proof", chunk.kind == "proof",
    )


def _active_input_policies(active_path: Path) -> set[str] | None:
    """Read row policies when a real active table exists; None for test stubs."""
    if not (active_path / "chunks.lance").is_dir():
        return None
    import lancedb

    table = lancedb.connect(str(active_path)).open_table(CHUNKS_TABLE_NAME)
    if "embed_input_policy_version" not in table.schema.names:
        return {"preamble-first-v1"}
    return {
        policy or "preamble-first-v1"
        for policy in table.to_arrow().column("embed_input_policy_version").to_pylist()
    }


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
            "parser_used",
        ]
    )
    out: dict[str, dict] = {}
    ids = arrow["chunk_id"].to_pylist()
    stmts = arrow["embedding_stmt"].to_pylist()
    proofs = arrow["embedding_proof"].to_pylist()
    versions = arrow["embedder_version"].to_pylist()
    kinds = arrow["kind"].to_pylist()
    parsers = arrow["parser_used"].to_pylist()
    for cid, stmt, proof, ver, kind, parser in zip(
        ids, stmts, proofs, versions, kinds, parsers, strict=True
    ):
        out[cid] = {
            "embedding_stmt": stmt,
            "embedding_proof": proof,
            "embedder_version": ver,
            "kind": kind,
            "parser_used": parser,
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


def _route(kind: str | None) -> str:
    """The embedding route a chunk of ``kind`` is stored on.

    Proof chunks carry their vector in ``embedding_proof``; every other
    kind in ``embedding_stmt``. A chunk_id does not hash its kind, so the
    same id can come back from a re-chunk on the other route.
    """
    return "proof" if kind == "proof" else "stmt"


def _route_changed_ids(
    copy_ids: set[str],
    new_chunks: list[ChunkRecord],
    old_kinds: dict[str, str | None],
) -> set[str]:
    """Return the copy candidates whose new kind is on another route
    than their stored row, so their vector cannot be carried over."""
    new_kinds = {c.chunk_id: c.kind for c in new_chunks}
    return {
        cid
        for cid in copy_ids
        if cid in old_kinds
        and _route(old_kinds[cid]) != _route(new_kinds[cid])
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

    Route guard: the new chunk must sit on the same route as the old
    row. ``_plan_paper`` already sends route changes to re-embed; this
    refuses any that reach the copy path anyway.
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
        new_chunk = new_chunks_by_id.get(cid)
        if new_chunk is None:
            raise RuntimeError(
                f"copy path: chunk_id={cid!r} is not among the paper's "
                f"new chunks"
            )
        kind = new_chunk.kind
        if _route(row["kind"]) != _route(kind):
            raise RuntimeError(
                f"copy path: chunk_id={cid!r} moved from the "
                f"{_route(row['kind'])} route (kind={row['kind']!r}) to the "
                f"{_route(kind)} route (kind={kind!r}); its vector cannot "
                f"be copied and must be re-embedded"
            )
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
    paper_id: str, old_chunk_ids_for_paper: set[str],
    *, notebook_slug: str | None = None,
    parser_used: str | None = None,
    force_re_embed: bool = False,
    old_kinds: dict[str, str | None] | None = None,
) -> _PaperWorkPlan:
    """Re-chunk the paper, diff against the old chunk-id set.

    ``old_kinds`` maps the paper's stored chunk_ids to their stored
    kind. A copy candidate whose new kind is on another route is moved
    to re-embed: the same chunk_id does not mean the same vector.
    """
    if paper_id.startswith("textbook:"):
        if notebook_slug is None:
            raise ValueError(f"notebook slug required for {paper_id}")
        from ingest.textbook_chunker import _flat_paper_id, _resolve_notebook_dir
        notebook = _resolve_notebook_dir(notebook_slug)
        pdftotext_source = notebook / "parsed" / _flat_paper_id(paper_id) / "_pdftotext"
        if parser_used == "pdftotext" or pdftotext_source.is_dir():
            from ingest.textbook_pdf_chunker import chunk_textbook_pdf
            new_chunks = chunk_textbook_pdf(notebook_slug, paper_id)
        elif parser_used == "mineru+markdown":
            from ingest.textbook_markdown_chunker import chunk_textbook_markdown
            new_chunks = chunk_textbook_markdown(notebook_slug, paper_id)
        else:
            from ingest.textbook_chunker import chunk_textbook
            new_chunks = chunk_textbook(notebook_slug, paper_id)
    else:
        new_chunks = chunk_paper(paper_id)
    if not new_chunks:
        raise RuntimeError(f"chunker produced no chunks for {paper_id}")
    new_ids = {c.chunk_id for c in new_chunks}
    copy_ids, re_embed_ids, drop_ids = compute_diff(
        old_chunk_ids_for_paper, new_ids
    )
    if force_re_embed:
        copy_ids = set()
        re_embed_ids = new_ids
    elif old_kinds is not None:
        moved = _route_changed_ids(copy_ids, new_chunks, old_kinds)
        copy_ids = copy_ids - moved
        re_embed_ids = re_embed_ids | moved
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
            copy_chunks, copy_record, lancedb_path=staging_lancedb_path,
            build_indices=False,
        )

    # --- Re-embed path ---------------------------------------------------
    if re_embed_pending:
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
            full_record, keep=re_embed_pending
        )
        re_embed_chunks = [by_id[cid] for cid in re_embed_pending]
        write_chunks(
            re_embed_chunks,
            re_embed_record,
            lancedb_path=staging_lancedb_path,
            build_indices=False,
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
        embed_input_policy_version=record.embed_input_policy_version,
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
    arrow = tbl.to_arrow().select(["chunk_id", "paper_id"])
    out: dict[str, set[str]] = {}
    for cid, pid in zip(
        arrow["chunk_id"].to_pylist(), arrow["paper_id"].to_pylist(), strict=True
    ):
        if not isinstance(pid, str) or not is_valid_paper_id(pid):
            raise ValueError(f"invalid paper_id in active row {cid!r}: {pid!r}")
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

    # Closes synthesis D6: read OLD_EMBEDDER_VERSION up front.
    old_embedder_version = _read_old_embedder_version(active_lancedb_path)
    active_marker = json.loads(
        (active_lancedb_path / CORPUS_VERSION_MARKER_NAME).read_text(encoding="utf-8")
    )
    old_input_policy = active_marker.get("embed_input_policy_version", "preamble-first-v1")
    row_policies = _active_input_policies(active_lancedb_path)
    force_re_embed = (
        old_embedder_version != target_embedder_version
        or old_input_policy != EMBED_INPUT_POLICY_VERSION
        or (row_policies is not None and row_policies != {EMBED_INPUT_POLICY_VERSION})
    )
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

    already_in_staging: set[str] = set()
    staged_signatures = _staging_paper_signatures(staging_lancedb_path) if resume else {}
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
            parser_used = next(
                (old_rows_cache[cid].get("parser_used") for cid in old_ids
                 if cid in old_rows_cache), None
            )
            plan = _plan_paper(
                paper_id, old_ids, notebook_slug=notebook_slug,
                parser_used=parser_used, force_re_embed=force_re_embed,
                old_kinds={
                    cid: old_rows_cache[cid].get("kind")
                    for cid in old_ids if cid in old_rows_cache
                },
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
                f"{paper_id}\tcopy={len(plan.copy_ids)}\t"
                f"reembed={len(plan.re_embed_ids)}\t"
                f"drop={len(plan.drop_ids)}"
            )
            continue
        if resume and staged_signatures.get(paper_id) == {
            _chunk_signature(chunk) for chunk in plan.new_chunks
        }:
            summary.chunks_skipped_resume += len(plan.new_chunks)
            continue

        try:
            _delete_staging_paper_rows(staging_lancedb_path, paper_id)
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

    if not dry_run and not summary.papers_failed:
        # Per-paper writes deliberately skip expensive repeated HNSW builds.
        # An empty write creates both indices once and advances the staging
        # marker to their post-index MVCC version.
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
