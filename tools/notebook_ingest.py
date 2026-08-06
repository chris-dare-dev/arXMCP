"""Run bulk_ingest against a notebook's papers.txt, then build BM25.

Thin wrapper that:

1. Calls :func:`ingest.bulk_ingest.run_bulk_ingest` with
   ``lancedb_staging_path=var/arxmcp/notebooks/<slug>/lancedb``.
2. Reads the resulting ``corpus-version.json`` to find the per-notebook
   corpus version.
3. Calls :func:`ingest.bm25_indexer.build_bm25_index` with that version,
   writing the artifact under ``var/arxmcp/notebooks/<slug>/index/bm25/``
   (the per-notebook BM25 root).

The brief's ``ARXMCP_LANCEDB_PATH=...`` wording was wrong — that's the
SERVER's env var, not a bulk_ingest one. ``bulk_ingest`` uses the
``--lancedb-staging-path`` CLI argument / ``lancedb_staging_path``
Python keyword. See synthesis "Disagreement 4" resolution.

BM25 output path: notebook-bm25-isolation-m1 isolates the BM25 index
under ``var/arxmcp/notebooks/<slug>/index/bm25/v<N>/``, NOT the global
``var/arxmcp/index/bm25/``. The per-notebook root mirrors the existing
``lancedb_path`` / ``cache_db_path`` fork-C isolation in
:class:`server.config.Config`. The global BM25 root is unchanged for
the shared (non-notebook) server. A fork-C server's first startup after
this milestone rebuilds BM25 from scratch under the new per-notebook
root if the artifacts were only built pre-fix (FM-1: first-boot auto-build
via :meth:`server.retrieval.bm25.BM25Phase._sync_startup` is the safety net).

Usage:

    uv run python tools/notebook_ingest.py <slug>

Exit codes:
    0 — ingest succeeded AND BM25 index was built (or both skipped idempotently)
    1 — slug validation failed, ingest had any paper failure, or BM25 build raised
"""

from __future__ import annotations

import argparse
import json
import logging
import sys

from ingest.bm25_indexer import build_bm25_index
from ingest.bulk_ingest import run_bulk_ingest
from tools._notebook_common import (
    NotebookError,
    notebook_dir,
    read_paper_ids_from_papers_txt,
    validate_slug,
)

logger = logging.getLogger("notebook_ingest")


def runtime_paths_report() -> dict[str, str]:
    """Return every mutable default reached by the ingest child boundary."""
    from ingest import ar5iv_fetch, bulk_ingest, chunker, embedder, store
    from server.application_paths import ApplicationPaths

    paths = ApplicationPaths.resolve()
    return {
        "mode": paths.mode,
        "root": str(paths.root),
        "notebooks": str(paths.notebooks),
        "ar5iv_cache": str(ar5iv_fetch.DEFAULT_AR5IV_CACHE_DIR),
        "parsed": str(ar5iv_fetch.DEFAULT_PARSED_DIR),
        "chunker_parsed": str(chunker.PARSED_DIR),
        "chunks": str(chunker.CHUNKS_DIR),
        "chunk_log": str(chunker.CHUNK_LOG_PATH),
        "embedder_chunks": str(embedder.CHUNKS_DIR),
        "embeddings": str(embedder.EMBEDDINGS_DIR),
        "embed_stats": str(embedder.EMBED_STATS_PATH),
        "embed_log": str(embedder.EMBED_LOG_PATH),
        "lancedb": str(store.DEFAULT_LANCEDB_PATH),
        "store_stats": str(store.STORE_STATS_PATH),
        "lancedb_staging": str(bulk_ingest.DEFAULT_LANCEDB_STAGING_PATH),
        "parser_failures": str(bulk_ingest.DEFAULT_PARSER_FAILURES_PATH),
        "ingestion_log": str(bulk_ingest.DEFAULT_INGESTION_LOG_PATH),
        "ops": str(bulk_ingest.DEFAULT_OPS_DIR),
    }


def _read_corpus_version(lancedb_path) -> int:
    """Read ``corpus-version.json`` and return the integer version."""
    marker = lancedb_path / "corpus-version.json"
    if not marker.is_file():
        raise NotebookError(
            f"corpus-version.json not found at {marker} — "
            f"bulk_ingest may have failed before writing any chunks"
        )
    data = json.loads(marker.read_text(encoding="utf-8"))
    version = data.get("version")
    if not isinstance(version, int) or version < 1:
        raise NotebookError(
            f"corpus-version.json has invalid version {version!r}"
        )
    return version


def run(slug: str) -> int:
    """Pure function — returns exit code. Tests call this directly."""
    validate_slug(slug)
    nb_dir = notebook_dir(slug)
    if not nb_dir.exists():
        raise NotebookError(
            f"notebook dir does not exist at {nb_dir} — "
            f"run `tools/notebook_init.py {slug}` first"
        )
    papers_txt = nb_dir / "papers.txt"
    paper_ids = read_paper_ids_from_papers_txt(papers_txt)
    if not paper_ids:
        raise NotebookError(
            f"papers.txt at {papers_txt} has no paper_ids — "
            f"add IDs before running ingest"
        )

    # FM-6 mitigation — ensure lancedb dir and ops dir exist before
    # bulk_ingest tries to write into them. mkdir is idempotent
    # (exist_ok=True) so this is safe on re-runs.
    lancedb_path = nb_dir / "lancedb"
    lancedb_path.mkdir(parents=True, exist_ok=True)
    ops_dir = nb_dir / "ops"
    ops_dir.mkdir(parents=True, exist_ok=True)

    # Per-notebook log path under ops/ — keeps notebook ingest logs
    # separate from the global var/arxmcp/ops/ingestion.log.
    log_path = ops_dir / "ingestion.log"
    failures_path = ops_dir / "parser-failures.jsonl"

    logger.info(
        "running bulk_ingest for slug=%s (%d paper_ids) → %s",
        slug, len(paper_ids), lancedb_path,
    )
    summary = run_bulk_ingest(
        paper_ids,
        lancedb_staging_path=lancedb_path,
        log_path=log_path,
        failures_path=failures_path,
    )
    print(
        f"bulk_ingest: total={summary.papers_total} "
        f"ok={summary.papers_succeeded} "
        f"fail={summary.papers_failed} "
        f"ar5iv_rate={summary.ar5iv_hit_rate:.3f}"
    )
    if summary.papers_failed > 0:
        print(
            f"bulk_ingest had {summary.papers_failed} failures — "
            f"see {failures_path}",
            file=sys.stderr,
        )
        # We still try to build BM25 on the partial corpus; the index
        # reflects whatever did land. Exit non-zero so the operator
        # notices.
    if summary.papers_succeeded == 0:
        print("no papers succeeded — skipping BM25 build", file=sys.stderr)
        return 1

    corpus_version = _read_corpus_version(lancedb_path)
    # Per-notebook BM25 root: isolated under the notebook directory so
    # two notebooks at the same corpus_version N do NOT collide
    # (notebook-bm25-isolation-m1). The global BM25 root
    # (var/arxmcp/index/bm25/) is untouched — the shared server still
    # finds its own artifacts there. The sentinel workaround
    # (.notebook_slug file) is removed because the directory namespaces
    # are now 1:1 by construction (FM-7 resolution).
    bm25_root = nb_dir / "index" / "bm25"
    bm25_v_dir = bm25_root / f"v{corpus_version}"
    logger.info(
        "building BM25 for slug=%s lancedb=%s corpus_version=%d root=%s",
        slug, lancedb_path, corpus_version, bm25_root,
    )
    build_bm25_index(
        str(lancedb_path),
        corpus_version=corpus_version,
        index_root=bm25_root,
    )
    print(
        f"BM25 built for corpus_version={corpus_version} "
        f"(at {bm25_v_dir}/)"
    )

    # Warn if multiple v<N>/ directories exist under the per-notebook
    # BM25 root. Helps operators prune stale indices after a
    # corpus rebuild that incremented the version.
    existing_vdirs = sorted(bm25_root.glob("v*"))
    if len(existing_vdirs) > 1:
        print(
            f"WARN: {len(existing_vdirs)} BM25 version directories exist "
            f"under {bm25_root}/. Older versions may be stale; "
            f"consider pruning manually.",
            file=sys.stderr,
        )

    return 0 if summary.papers_failed == 0 else 1


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=__doc__.splitlines()[0],
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "slug",
        nargs="?",
        help="Notebook slug (must match ^[a-z][a-z0-9-]{2,30}$).",
    )
    parser.add_argument(
        "--print-runtime-paths",
        action="store_true",
        help="print installed ingest writer paths as JSON and exit",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=("DEBUG", "INFO", "WARNING", "ERROR"),
        help="Python logging level for the notebook_ingest module.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_arg_parser()
    args = parser.parse_args(argv)
    if args.print_runtime_paths:
        print(json.dumps(runtime_paths_report(), sort_keys=True))
        return 0
    if args.slug is None:
        parser.error("slug is required unless --print-runtime-paths is used")
    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    try:
        return run(args.slug)
    except NotebookError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
