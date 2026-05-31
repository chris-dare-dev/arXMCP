#!/usr/bin/env python3
"""Discover new arXiv papers for a notebook's topic (notebook-paper-discovery-m3).

Given a notebook slug, reads its ``discovery_category`` + ``description`` (m1
topic metadata), queries the arXiv Atom API via ``tools/_arxiv_api.py`` (m2),
deduplicates the results against the notebook's ``notebook_papers`` junction,
and returns a ranked candidate list of papers NOT yet in the notebook.

This is the arXiv-Atom discovery CHANNEL. It is deterministic and LLM-free: it
PROPOSES candidates; it does not ingest them (the operator confirms via the m4
console panel; see ``.claude/notes/notebook-discovery-model.md`` §2). Ranking is
arXiv's ``sortBy=submittedDate&sortOrder=descending`` order, preserved through
the dedup filter, so output is deterministic for a fixed API response.

Politeness is inherited from ``_arxiv_api.fetch_candidates`` (per-page 3s sleep;
for ``max_results <= 2000`` — typical for a notebook — a single request with no
sleep). A future multi-notebook caller (m4) owns any inter-notebook delay.

Usage:
    python -m tools.discover_for_notebook <slug> [--max-results N] [--email you@x] [--json]
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass
from pathlib import Path

from server.notebooks_store import NotebooksStore
from server.operator_settings import DEFAULT_DB_PATH
from tools._arxiv_api import fetch_candidates
from tools._notebook_common import NotebookError, validate_slug


@dataclass(frozen=True)
class DiscoveryCandidate:
    """A proposed paper for a notebook — exactly the m3 output contract.

    Decoupled from ``_arxiv_api.Candidate`` (which also carries arXiv-internal
    fields like ``n_authors`` / ``primary_category``); this is the stable shape
    the m4 console panel consumes.
    """

    paper_id: str
    title: str
    abstract_head: str
    submitted_date: str


def _strip_version(paper_id: str) -> str:
    """Drop the trailing ``vN`` suffix, mirroring ``_arxiv_api.parse_atom_feed``.

    The junction may store a versioned id (URL-paste route), while feed
    candidates are already un-versioned; normalising both to this key makes the
    dedup membership test align (rect F1).
    """
    return paper_id.split("v", 1)[0] if "v" in paper_id else paper_id


async def discover_for_notebook_async(
    store: NotebooksStore,
    slug: str,
    *,
    max_results: int = 200,
    contact_email: str | None = None,
    sleep: Callable[[float], None] = time.sleep,
) -> list[DiscoveryCandidate]:
    """Discover + dedup new arXiv papers for ``slug``.

    Async core (takes an already-open ``store`` for testability). Raises
    ``ValueError`` when the notebook is unknown OR has no ``discovery_category``
    set ("not configured" is distinct from "found nothing" — the latter returns
    an empty list). All precondition checks use ``if … raise`` (CLAUDE.md §4.7,
    no ``assert``).
    """
    nb = await store.get_notebook(slug)
    if nb is None:
        raise ValueError(f"notebook {slug!r} not found")

    category = (nb.get("discovery_category") or "").strip()
    if not category:
        raise ValueError(
            f"notebook {slug!r} has no discovery_category set — set a topic "
            "via PATCH /ui/api/notebooks/{slug}/topic first"
        )

    # description is the operator's free-text topic; m2 already strips control
    # chars (m1) and quotes the phrase (injection-safe) — pass it through raw.
    keywords = nb.get("description") or ""

    candidates = fetch_candidates(
        category,
        max_results,
        contact_email,
        abs_keywords=keywords or None,
        sleep=sleep,
    )

    # Dedup against the notebook's existing papers. The candidate side is
    # un-versioned (parse_atom_feed strips the vN suffix), but the junction can
    # hold a VERSIONED id: the URL-paste route stores whatever
    # is_valid_arxiv_paper_id accepts, e.g. "2604.26204v3" from
    # https://arxiv.org/abs/2604.26204v3 (rect F1; tests/test_notebook_api.py).
    # Normalise the stored side to the same un-versioned key so a paper the
    # operator already added is never re-proposed. Order-preserving filter keeps
    # the arXiv submittedDate-descending ranking → deterministic for a fixed feed.
    existing_ids = {
        _strip_version(p["paper_id"]) for p in await store.list_papers(slug)
    }
    return [
        DiscoveryCandidate(
            paper_id=c.paper_id,
            title=c.title,
            abstract_head=c.abstract_head,
            submitted_date=c.submitted_date,
        )
        for c in candidates
        if c.paper_id not in existing_ids
    ]


def discover_for_notebook(
    slug: str,
    *,
    db_path: Path | None = None,
    max_results: int = 200,
    contact_email: str | None = None,
    sleep: Callable[[float], None] = time.sleep,
) -> list[DiscoveryCandidate]:
    """Synchronous wrapper: open the notebooks store, run the async core, close.

    Mirrors the ``tools/notebook_init.py`` ``asyncio.run`` pattern so CLI callers
    need no event-loop ceremony.
    """
    resolved = db_path if db_path is not None else DEFAULT_DB_PATH

    async def _run() -> list[DiscoveryCandidate]:
        store = await NotebooksStore.open(resolved)
        try:
            return await discover_for_notebook_async(
                store,
                slug,
                max_results=max_results,
                contact_email=contact_email,
                sleep=sleep,
            )
        finally:
            await store.close()

    return asyncio.run(_run())


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("slug", help="notebook slug to discover papers for")
    parser.add_argument(
        "--max-results", type=int, default=200,
        help="max candidates to fetch (<=2000 is a single request)",
    )
    parser.add_argument(
        "--email", default=None,
        help="contact email for the arXiv polite-pool User-Agent",
    )
    parser.add_argument(
        "--db-path", default=None, help="override the notebooks.db path",
    )
    parser.add_argument(
        "--json", action="store_true", help="emit JSON instead of TSV",
    )
    args = parser.parse_args()

    try:
        validate_slug(args.slug)
    except NotebookError as e:
        print(f"INVALID SLUG: {e}", file=sys.stderr)
        return 1

    db_path = Path(args.db_path) if args.db_path else None
    try:
        candidates = discover_for_notebook(
            args.slug,
            db_path=db_path,
            max_results=args.max_results,
            contact_email=args.email,
        )
    except (ValueError, RuntimeError) as e:
        print(f"DISCOVERY FAILED: {e}", file=sys.stderr)
        return 1

    print(
        f"# {len(candidates)} new candidate(s) for notebook {args.slug!r} "
        "(deduped against existing papers)",
        file=sys.stderr,
    )
    if args.json:
        print(json.dumps([asdict(c) for c in candidates], indent=2))
    else:
        print("paper_id\tsubmitted_date\ttitle")
        for c in candidates:
            print(f"{c.paper_id}\t{c.submitted_date}\t{c.title}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
