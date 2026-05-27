"""Notebook-aware re-embed driver (embedder-truncation-m1).

Discovers every per-notebook LanceDB dataset under
``var/arxmcp/notebooks/<slug>/lancedb/`` and invokes the existing
single-path :func:`ingest.re_embed.run_re_embed` against each. The
shared arXiv corpus at ``var/arxmcp/index/lancedb/`` is also included
if its ``chunks`` table is present.

**Why this exists.** The roadmap for ``embedder-truncation-m1`` bumps
``CHUNKER_VERSION`` from ``v1.0`` to ``v1.1`` and raises
``BGE_M3_MAX_TOKENS`` from 512 to 2048; both changes mandate a
re-embed of every existing chunk in every LanceDB dataset. The
underlying :mod:`ingest.re_embed` driver is single-path-scoped
(``--active-lancedb-path``) and has no enumeration logic — running it
manually per notebook is operator-error-prone, so this thin driver
encapsulates the discovery + invocation loop.

**Out of scope** (intentional — keep this driver minimal):

- The atomic cutover from ``<dataset>/lancedb-staging`` → ``<dataset>/lancedb``.
  Re-embed writes to a staging dir; the operator promotes it via the
  existing E11_S05 cutover tooling.
- Parallelism across datasets. ``ingest.store.write_chunks`` is
  single-writer-per-dataset; serializing across datasets keeps the
  resource budget predictable on CPU.

Usage::

    make re-embed-all
    # or equivalently:
    /Users/chris.dare/Library/Python/3.9/bin/uv run python -m tools.re_embed_all [--dry-run]

Exit codes::

    0 — every discovered dataset re-embedded successfully
    1 — at least one dataset's run_re_embed reported a failure
    2 — discovery failed (no datasets found, or unreadable layout)
"""

from __future__ import annotations

import argparse
import logging
import sys
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger("re_embed_all")

REPO_ROOT = Path(__file__).resolve().parent.parent
NOTEBOOKS_BASE = REPO_ROOT / "var" / "arxmcp" / "notebooks"
SHARED_LANCEDB_PATH = REPO_ROOT / "var" / "arxmcp" / "index" / "lancedb"


@dataclass
class DatasetTarget:
    """One discovered LanceDB dataset to re-embed."""
    label: str                 # human-readable: "bridgeland-stability" or "shared"
    active_lancedb_path: Path  # source (read-only)
    staging_lancedb_path: Path # write target (sibling -staging dir)


def discover_targets(
    *, notebooks_base: Path = NOTEBOOKS_BASE,
    shared_lancedb_path: Path = SHARED_LANCEDB_PATH,
) -> list[DatasetTarget]:
    """Walk ``var/arxmcp/notebooks/*/lancedb/`` + the shared corpus.

    A directory qualifies as a re-embed target iff it contains a
    ``chunks.lance`` subdir (LanceDB stores tables as subdirs of the
    DB root). Empty notebooks (no chunks table yet) are skipped — they
    have nothing to re-embed.
    """
    targets: list[DatasetTarget] = []

    # Shared corpus, if present and non-empty.
    if shared_lancedb_path.is_dir() and (
        shared_lancedb_path / "chunks.lance"
    ).is_dir():
        targets.append(
            DatasetTarget(
                label="shared",
                active_lancedb_path=shared_lancedb_path,
                staging_lancedb_path=shared_lancedb_path.parent
                / "lancedb-staging",
            )
        )

    # Notebook-scoped datasets.
    if notebooks_base.is_dir():
        for nb_dir in sorted(notebooks_base.iterdir()):
            if not nb_dir.is_dir():
                continue
            active = nb_dir / "lancedb"
            if not active.is_dir():
                continue
            if not (active / "chunks.lance").is_dir():
                # Notebook with no chunks table yet — skip silently.
                logger.debug(
                    "skip %s: no chunks.lance subdir", nb_dir.name
                )
                continue
            targets.append(
                DatasetTarget(
                    label=nb_dir.name,
                    active_lancedb_path=active,
                    staging_lancedb_path=nb_dir / "lancedb-staging",
                )
            )
    return targets


def run(
    *,
    dry_run: bool = False,
    notebooks_base: Path = NOTEBOOKS_BASE,
    shared_lancedb_path: Path = SHARED_LANCEDB_PATH,
) -> int:
    """Re-embed every discovered dataset. Returns process exit code."""
    targets = discover_targets(
        notebooks_base=notebooks_base,
        shared_lancedb_path=shared_lancedb_path,
    )
    if not targets:
        print(
            "no LanceDB datasets discovered under "
            f"{notebooks_base} or {shared_lancedb_path}",
            file=sys.stderr,
        )
        return 2

    print(f"discovered {len(targets)} dataset(s):")
    for t in targets:
        print(f"  {t.label}: {t.active_lancedb_path}")

    if dry_run:
        print("dry-run: skipping re-embed invocations")
        return 0

    # Late import so --dry-run + discovery tests don't pay the BGE-M3
    # model-load cost.
    from ingest.re_embed import run_re_embed  # noqa: PLC0415

    failures: list[str] = []
    for t in targets:
        print(f"=== re-embedding {t.label} ===")
        try:
            summary = run_re_embed(
                paper_ids=None,
                active_lancedb_path=t.active_lancedb_path,
                staging_lancedb_path=t.staging_lancedb_path,
            )
        except Exception as exc:  # noqa: BLE001
            logger.exception(
                "re-embed failed for %s: %s", t.label, exc
            )
            failures.append(t.label)
            continue
        # ReEmbedSummary.papers_failed is the canonical per-dataset
        # failure signal (mirrors the single-path CLI's exit-code
        # convention at ingest/re_embed.py:957).
        if summary.papers_failed:
            failures.append(t.label)
            print(
                f"  {t.label}: FAILED "
                f"({summary.papers_failed} paper failures)",
                file=sys.stderr,
            )
        else:
            print(
                f"  {t.label}: ok "
                f"(papers={summary.papers_total} "
                f"chunks_target={summary.chunks_target} "
                f"copied={summary.chunks_copied} "
                f"re_embedded={summary.chunks_re_embedded})"
            )

    if failures:
        print(
            f"\n{len(failures)} dataset(s) failed: {', '.join(failures)}",
            file=sys.stderr,
        )
        return 1
    return 0


def _cli(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Re-embed every LanceDB dataset under var/arxmcp/notebooks/ "
            "+ the shared corpus (embedder-truncation-m1)."
        ),
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help=(
            "Discover and list targets; do NOT invoke run_re_embed. "
            "Use this to sanity-check the path discovery before a "
            "multi-hour run."
        ),
    )
    args = parser.parse_args(argv)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    return run(dry_run=args.dry_run)


if __name__ == "__main__":  # pragma: no cover
    sys.exit(_cli(sys.argv[1:]))


__all__ = [
    "DatasetTarget",
    "discover_targets",
    "run",
]
