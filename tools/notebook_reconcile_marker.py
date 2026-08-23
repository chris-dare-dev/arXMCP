"""Server-down CLI fallback for ``make reconcile [NOTEBOOK=<slug>]``
(``onboarding-uplift-m3``).

Opens a notebook's LanceDB at the pinned marker version (MVCC
snapshot — concurrent-ingest-safe), recounts ``chunk_count`` +
distinct ``paper_id``s, and atomically rewrites the marker.

When called without a slug (``make reconcile`` no ``NOTEBOOK=``), it
reconciles the SHARED global corpus at
``var/arxmcp/index/lancedb/corpus-version.json`` instead.

Mirrors the server-up ``POST /ui/api/notebooks/<slug>/reconcile-marker``
REST endpoint's behavior for operators running ``make reconcile``
against a stopped server.

Usage:

    uv run python -m tools.notebook_reconcile_marker <slug>
    uv run python -m tools.notebook_reconcile_marker --shared
    uv run python -m tools.notebook_reconcile_marker --lancedb-path <dir>

The third form (issue #429) reaches a corpus at a non-default index path —
``var/arxmcp/index/lancedb-staging``, ``index/lancedb-mathag`` — which
neither a slug nor ``--shared`` can address.

Exit codes:
    0 — recount completed (drift may be zero on idempotent re-run)
    1 — operational failure (missing marker, malformed marker, LanceDB
        open failure)
"""

from __future__ import annotations

import argparse
import contextlib
import json
import logging
import os
import sys
import uuid
from pathlib import Path

from tools._notebook_common import (
    NotebookError,
    notebook_lancedb_path,
    validate_slug,
)

logger = logging.getLogger("notebook_reconcile_marker")

#: Path to the SHARED global corpus's marker (used when ``--shared`` is
#: passed). Resolves the same way :class:`server.config.Config`
#: defaults its ``lancedb_path`` field.
_SHARED_LANCEDB_PATH: Path = Path("var/arxmcp/index/lancedb")


def _recount_lancedb(
    lance_path: Path, *, version: int
) -> tuple[int, int]:
    """Identical contract to
    ``server/routes/notebooks.py::_recount_notebook_lancedb`` —
    MVCC-pinned ``count_rows`` + distinct paper_id via PyArrow."""
    import pyarrow.compute as pc  # noqa: PLC0415

    from server.corpus import open_chunks_table  # local

    tbl = open_chunks_table(lance_path, version=version)
    chunk_count = tbl.count_rows()
    arrow_tbl = tbl.to_arrow()
    paper_count = int(pc.count_distinct(arrow_tbl["paper_id"]).as_py())
    return chunk_count, paper_count


def _write_marker_atomically(lance_path: Path, info: object) -> None:
    """Atomic rewrite — mirrors
    ``server/routes/notebooks.py::_write_marker_atomically`` verbatim
    (m3 synthesis §2 load-bearing facts)."""
    out_path = lance_path / "corpus-version.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    # Mirror ``ingest/store.py::write_corpus_version_marker`` verbatim
    # (default separators, trailing "\n") so a reconcile output is
    # byte-identical to a fresh-ingest marker. Diverging here would
    # break the m3 synthesis §3 D4 idempotency contract.
    payload = (
        json.dumps(
            info.to_dict(),  # type: ignore[attr-defined]
            ensure_ascii=False,
            sort_keys=True,
        )
        + "\n"
    )
    tmp = out_path.with_suffix(
        f"{out_path.suffix}.{os.getpid()}.{uuid.uuid4().hex[:8]}.tmp"
    )
    try:
        tmp.write_text(payload, encoding="utf-8")
        os.replace(tmp, out_path)
    finally:
        with contextlib.suppress(OSError):
            tmp.unlink(missing_ok=True)


def _reconcile_one(lance_path: Path, *, label: str) -> int:
    """Reconcile a single LanceDB. ``label`` is a human-readable
    identifier ("shimura-varieties" or "shared") used in the log line.

    Returns 0 on success, 1 on operational failure.
    """
    from server.corpus import read_corpus_version  # local

    try:
        old_info = read_corpus_version(lance_path)
    except (ValueError, OSError, json.JSONDecodeError) as exc:
        print(
            f"ERROR: corpus-version.json at {lance_path} is malformed: {exc}",
            file=sys.stderr,
        )
        return 1

    if old_info is None:
        print(
            f"ERROR: no corpus-version.json at {lance_path}; "
            "run `make ingest` first",
            file=sys.stderr,
        )
        return 1

    try:
        new_chunks, new_papers = _recount_lancedb(
            lance_path, version=old_info.version
        )
    except Exception as exc:  # noqa: BLE001 — operator surfaces opaque failures
        print(
            f"ERROR: LanceDB recount at {lance_path} failed: {exc}",
            file=sys.stderr,
        )
        return 1

    new_info = old_info.with_counts(
        chunk_count=new_chunks, paper_count=new_papers
    )
    _write_marker_atomically(lance_path, new_info)
    drift = new_chunks - old_info.chunk_count
    print(
        f"reconcile-marker [{label}]: version={old_info.version} "
        f"before={old_info.chunk_count} chunks / {old_info.paper_count} papers "
        f"after={new_chunks} chunks / {new_papers} papers "
        f"drift_resolved={drift}"
    )
    return 0


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=__doc__.splitlines()[0],
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "slug",
        nargs="?",
        default=None,
        help="Notebook slug to reconcile; mutually exclusive with --shared.",
    )
    parser.add_argument(
        "--shared",
        action="store_true",
        help=(
            "Reconcile the SHARED global corpus marker at "
            "var/arxmcp/index/lancedb/corpus-version.json instead of "
            "a per-notebook one. Mutually exclusive with a slug arg."
        ),
    )
    parser.add_argument(
        "--lancedb-path",
        default=None,
        metavar="PATH",
        help=(
            "Reconcile the corpus at an ARBITRARY LanceDB path (issue #429). "
            "Neither a notebook slug nor --shared can reach a corpus at a "
            "non-default index path such as var/arxmcp/index/lancedb-staging "
            "or index/lancedb-mathag, so the divergence warning's remedy was "
            "unreachable for exactly those. Mutually exclusive with both."
        ),
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_arg_parser().parse_args(argv)

    selectors = [bool(args.slug), bool(args.shared), bool(args.lancedb_path)]
    if sum(selectors) > 1:
        print(
            "ERROR: pass exactly one of a slug, --shared, or --lancedb-path",
            file=sys.stderr,
        )
        return 1
    if not any(selectors):
        print(
            "ERROR: pass a slug (e.g. "
            "`python -m tools.notebook_reconcile_marker shimura-varieties`), "
            "--shared for the global corpus, or --lancedb-path <dir> for a "
            "corpus at a non-default index path",
            file=sys.stderr,
        )
        return 1

    if args.lancedb_path:
        path = Path(args.lancedb_path)
        return _reconcile_one(path, label=path.name)

    if args.shared:
        return _reconcile_one(_SHARED_LANCEDB_PATH, label="shared")

    try:
        validate_slug(args.slug)
    except NotebookError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    return _reconcile_one(notebook_lancedb_path(args.slug), label=args.slug)


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main(sys.argv[1:]))
