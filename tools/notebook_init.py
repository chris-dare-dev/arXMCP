"""Scaffold a new notebook directory with empty papers.txt + queries.json.

Variant 1 layout (proof-verify-handler-wiring-m6): global ``corpus/``,
per-notebook ``var/arxmcp/notebooks/<slug>/{papers.txt,queries.json,lancedb/}``.
This script creates the per-notebook dir + the two template files.

Idempotent at the DIRECTORY level — re-running on an existing notebook
is a no-op (logs ``notebook exists; skipping``). Partial-state recovery
(one of the two files manually deleted) requires manual cleanup of the
notebook dir before re-running. See FM-3 in the synthesis.

Usage:

    uv run python tools/notebook_init.py <slug>

Exit codes:
    0 — success or idempotent skip
    1 — slug validation failed (invalid slug → :class:`NotebookError`)
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date

from tools._notebook_common import NotebookError, notebook_dir, validate_slug

PAPERS_TXT_TEMPLATE = """\
# {slug} notebook seed list (created {today})
#
# Add one arXiv paper_id per line. Both new-style (YYMM.NNNNN) and
# old-style (e.g., hep-th/0001234) formats are accepted; the bulk_ingest
# pipeline validates each against ingest.identifiers.is_valid_paper_id.
#
# Once IDs are listed:
#   1. tools/notebook_fetch.py {slug}   # fetches ar5iv HTML for any missing
#   2. tools/notebook_ingest.py {slug}  # chunks, embeds, indexes into per-notebook lancedb
"""


def _queries_template(slug: str) -> dict:
    return {
        "schema_version": "1.0",
        "notebook_slug": slug,
        "notebook_display_name": slug.replace("-", " ").title(),
        "created_at": date.today().isoformat(),
        "comment": (
            "Paper-level relevance labels. For each query, list the paper_ids "
            "in the notebook that ACTUALLY address the pointed sub-question."
        ),
        "queries": [
            {
                "id": "EXAMPLE-q1",
                "difficulty": "easy",
                "text": "replace this with a pointed sub-question",
                "expected_relevant_papers": [],
                "notes": (
                    "Fill in with the 3-8 paper_ids you'd expect a good "
                    "retrieval system to surface. Delete this example query "
                    "and add real ones."
                ),
            }
        ],
    }


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=__doc__.splitlines()[0],
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "slug",
        help="Notebook slug (must match ^[a-z][a-z0-9-]{2,30}$).",
    )
    return parser


def run(slug: str) -> int:
    """Pure function — accepts a slug, returns an exit code.

    Tests call this directly with synthetic slugs + paths; the CLI
    entry just wires argparse into it.
    """
    validate_slug(slug)
    nb_dir = notebook_dir(slug)
    if nb_dir.exists():
        print(f"notebook exists; skipping (slug={slug!r}, path={nb_dir})")
        return 0
    nb_dir.mkdir(parents=True, exist_ok=False)
    papers_txt = nb_dir / "papers.txt"
    papers_txt.write_text(
        PAPERS_TXT_TEMPLATE.format(slug=slug, today=date.today().isoformat()),
        encoding="utf-8",
    )
    queries_json = nb_dir / "queries.json"
    queries_json.write_text(
        json.dumps(_queries_template(slug), indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(f"created {nb_dir}/ with papers.txt + queries.json")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = _build_arg_parser().parse_args(argv)
    try:
        return run(args.slug)
    except NotebookError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
