"""Run bulk_ingest against a notebook's papers.txt.

Thin wrapper that:

1. Calls :func:`ingest.bulk_ingest.run_bulk_ingest` with
   ``lancedb_staging_path=var/arxmcp/notebooks/<slug>/lancedb``.
2. Reads the resulting ``corpus-version.json`` to find the per-notebook
   corpus version.
3. ``run_bulk_ingest`` has already built the dataset's BM25, definitions,
   theorem-name and equation indexes inside it, so a cutover or rollback
   moves them with the chunks.
4. Hydrates arXiv metadata (title, authors, abstract, …) for the run's
   papers into the notebook's ``paper_metadata.db``. Best effort: an
   arXiv outage leaves rows missing and the exit code untouched;
   ``tools/notebook_metadata_backfill.py`` repairs them later.
   ``--no-metadata`` skips this step for offline runs.

The brief's ``ARXMCP_LANCEDB_PATH=...`` wording was wrong — that's the
SERVER's env var, not a bulk_ingest one. ``bulk_ingest`` uses the
``--lancedb-staging-path`` CLI argument / ``lancedb_staging_path``
Python keyword. See synthesis "Disagreement 4" resolution.

Usage:

    uv run python tools/notebook_ingest.py <slug> [--no-metadata]

Exit codes:
    0 — every paper ingested and the dataset's indexes were built
    1 — slug validation failed, or any paper failed
    3 — refused, nothing written: the notebook's table holds arXiv rows
        another chunker version wrote (rotate it through staging and
        cutover instead)
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

from ingest.bm25_indexer import resolve_bm25_root
from ingest.bulk_ingest import run_bulk_ingest
from ingest.notebooks import (
    NotebookError,
    notebook_dir,
    read_paper_ids_from_papers_txt,
    validate_slug,
)
from ingest.store import STALE_CHUNKER_EXIT_CODE, StaleChunkerRowsError
from ingest.write_lock import exits_when_write_locked
from tools import notebook_metadata_backfill

logger = logging.getLogger("notebook_ingest")


def runtime_paths_report() -> dict[str, str]:
    """Return every mutable default reached by the ingest child boundary."""
    from ingest import ar5iv_fetch, bulk_ingest, chunker, embedder, store
    from ingest.application_paths import ApplicationPaths

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


def _hydrate_metadata(slug: str, nb_dir: Path, paper_ids: list[str]) -> None:
    """Hydrate metadata for ``paper_ids``; never raise.

    The chunks and indexes are already committed when this runs, so a
    metadata failure must not change the ingest's outcome — it only
    leaves rows for the backfill CLI to fill in.
    """
    repair = f"tools/notebook_metadata_backfill.py {slug}"
    try:
        result = notebook_metadata_backfill.hydrate_paper_ids(nb_dir, paper_ids)
    except Exception:
        logger.warning(
            "metadata hydration failed; the ingest is unaffected — run %s",
            repair,
            exc_info=True,
        )
        print(f"metadata: failed — run {repair}", file=sys.stderr)
        return
    print(
        f"metadata: hydrated={len(result.hydrated)} "
        f"skipped={len(result.skipped)} "
        f"missing={len(result.missing)}"
    )
    if result.missing:
        reasons = ", ".join(f"{pid} ({why})" for pid, why in result.missing)
        print(
            f"metadata missing for {len(result.missing)} paper(s): {reasons} "
            f"— run {repair} once arXiv is reachable",
            file=sys.stderr,
        )


def run(slug: str, *, hydrate_metadata: bool = True) -> int:
    """Pure function — returns exit code. Tests call this directly.

    ``hydrate_metadata=False`` skips the arXiv metadata step.
    """
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

    # Per-notebook log, failures and ingest-summary.json under the
    # notebook's ops/, so one notebook's run never overwrites the summary
    # the shared corpus's /metrics gauges read.
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
        ops_dir=ops_dir,
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
        # The indexes cover whatever did land. Exit non-zero so the
        # operator notices.
    if summary.papers_succeeded == 0:
        print("no papers succeeded — no indexes built", file=sys.stderr)
        return 1

    # run_bulk_ingest built the dataset's indexes inside it.
    corpus_version = _read_corpus_version(lancedb_path)
    bm25_root = resolve_bm25_root(lancedb_path)
    print(f"indexes built for corpus_version={corpus_version} (in {lancedb_path})")

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

    if hydrate_metadata:
        _hydrate_metadata(slug, nb_dir, paper_ids)

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
        "--no-metadata",
        action="store_true",
        help="skip hydrating arXiv metadata after the ingest (offline runs)",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=("DEBUG", "INFO", "WARNING", "ERROR"),
        help="Python logging level for the notebook_ingest module.",
    )
    return parser


@exits_when_write_locked
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
        return run(args.slug, hydrate_metadata=not args.no_metadata)
    except StaleChunkerRowsError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return STALE_CHUNKER_EXIT_CODE
    except NotebookError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
