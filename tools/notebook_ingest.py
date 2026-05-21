"""Run bulk_ingest against a notebook's papers.txt, then build BM25.

Thin wrapper that:

1. Calls :func:`ingest.bulk_ingest.run_bulk_ingest` with
   ``lancedb_staging_path=var/arxmcp/notebooks/<slug>/lancedb``.
2. Reads the resulting ``corpus-version.json`` to find the per-notebook
   corpus version.
3. Calls :func:`ingest.bm25_indexer.build_bm25_index` with that version.

The brief's ``ARXMCP_LANCEDB_PATH=...`` wording was wrong — that's the
SERVER's env var, not a bulk_ingest one. ``bulk_ingest`` uses the
``--lancedb-staging-path`` CLI argument / ``lancedb_staging_path``
Python keyword. See synthesis "Disagreement 4" resolution.

BM25 output path: the synthesis "Disagreement 2" resolves in favor of
the global BM25 path (``var/arxmcp/index/bm25/v<N>/``). The per-notebook
``corpus_version`` is unique per notebook (LanceDB MVCC, each notebook
starts at version 1), so ``v<N>`` directories are effectively per-notebook
by version-integer separation. Modifying :func:`build_bm25_index` to
accept a per-notebook output dir is out of m6's scope.

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

from ingest.bm25_indexer import BM25_INDEX_ROOT, build_bm25_index
from ingest.bulk_ingest import run_bulk_ingest
from tools._notebook_common import (
    NotebookError,
    notebook_dir,
    read_paper_ids_from_papers_txt,
    validate_slug,
)

logger = logging.getLogger("notebook_ingest")


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
    logger.info(
        "building BM25 for slug=%s lancedb=%s corpus_version=%d",
        slug, lancedb_path, corpus_version,
    )
    # F2 fix (HIGH): the BM25 path is global; per-notebook corpus_version
    # is NOT unique across notebooks. Without a slug-sentinel guard,
    # notebook B's v1 build would silently no-op (indexer's idempotent
    # skip at ingest/bm25_indexer.py:313), leaving notebook B serving
    # notebook A's chunk_ids. Write a sentinel BEFORE the build; if a
    # different slug owns the existing v<N>/, raise with a clear remedy.
    bm25_v_dir = BM25_INDEX_ROOT / f"v{corpus_version}"
    sentinel_path = bm25_v_dir / ".notebook_slug"
    if sentinel_path.is_file():
        prior_slug = sentinel_path.read_text(encoding="utf-8").strip()
        if prior_slug and prior_slug != slug:
            raise NotebookError(
                f"BM25 collision at {bm25_v_dir}: previously built by "
                f"notebook {prior_slug!r}, current ingest is {slug!r}. "
                f"Per-notebook corpus_version is not globally unique. "
                f"Recover by: (1) running `tools/notebook_purge.py "
                f"{prior_slug}` to clear the prior notebook's BM25, OR "
                f"(2) manually removing {bm25_v_dir} if {prior_slug!r} "
                f"is no longer needed."
            )
    build_bm25_index(str(lancedb_path), corpus_version=corpus_version)
    # Write the sentinel POST-build so a crashed build doesn't claim
    # ownership of an incomplete v<N>/. mkdir is defensive — the
    # indexer creates v<N>/ on success.
    bm25_v_dir.mkdir(parents=True, exist_ok=True)
    sentinel_path.write_text(slug, encoding="utf-8")
    print(
        f"BM25 built for corpus_version={corpus_version} "
        f"(at {bm25_v_dir}/ — slug={slug!r} written to .notebook_slug "
        f"sentinel to detect future cross-notebook collisions)"
    )

    # F7 fix (LOW): warn if multiple v<N>/ directories exist for this
    # notebook's lancedb. The synthesis FM-7 calls for this; helps
    # operators prune stale BM25 indices.
    existing_vdirs = sorted(BM25_INDEX_ROOT.glob("v*"))
    if len(existing_vdirs) > 1:
        print(
            f"WARN: {len(existing_vdirs)} BM25 version directories exist "
            f"under {BM25_INDEX_ROOT}/. Older versions may be stale; "
            f"consider pruning manually or via `tools/notebook_purge.py "
            f"<slug>` for retired notebooks.",
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
        help="Notebook slug (must match ^[a-z][a-z0-9-]{2,30}$).",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=("DEBUG", "INFO", "WARNING", "ERROR"),
        help="Python logging level for the notebook_ingest module.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_arg_parser().parse_args(argv)
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
