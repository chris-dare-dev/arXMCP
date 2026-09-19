"""arXiv Atom discovery channel for the exploration pipeline (WS-E v0).

Thin window-aware layer over the shipped Atom library
(``tools/_arxiv_api.py``, notebook-paper-discovery-m2). Two modes:

- **fixture** — parse a saved Atom XML document (tests + offline golden
  path; the mission's "do not depend on live arXiv in tests").
- **live** — ``fetch_candidates`` against ``export.arxiv.org`` with the
  repo's politeness contract (agent-side/CLI fetch, matching the
  existing discovery channel's grain — cross-workstream invariant 2:
  the server itself never fetches).

Both modes end in :func:`filter_to_window` (AC-E.2: every proposed
paper's date falls in the window) and produce the same
``list[Candidate]`` shape, so the golden-path test exercises exactly
the code the live run uses.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from pathlib import Path

from tools._arxiv_api import Candidate, fetch_candidates, parse_atom_feed
from tools.exploration.windowing import Window


def load_fixture_candidates(path: Path) -> list[Candidate]:
    """Parse a saved arXiv Atom XML document into candidates.

    Raises ``RuntimeError`` for malformed XML / arXiv error entries
    (same contract as the live path — ``parse_atom_feed`` is shared).
    """
    if not path.is_file():
        raise ValueError(f"Atom fixture not found: {path}")
    return parse_atom_feed(path.read_bytes())


def fetch_live_candidates(
    category: str,
    max_results: int,
    contact_email: str | None = None,
    *,
    abs_keywords: str | None = None,
    sleep: Callable[[float], None] = time.sleep,
) -> list[Candidate]:
    """Live Atom window scan (politeness inherited from ``_arxiv_api``)."""
    return fetch_candidates(
        category,
        max_results,
        contact_email,
        abs_keywords=abs_keywords,
        sleep=sleep,
    )


def filter_to_window(candidates: list[Candidate], window: Window) -> list[Candidate]:
    """Keep only candidates whose ``submitted_date`` falls in the window.

    Order-preserving (arXiv's submittedDate-descending ranking survives,
    mirroring ``tools/discover_for_notebook.py``), deterministic for a
    fixed feed.
    """
    return [c for c in candidates if window.contains(c.submitted_date)]


def atom_source_citation(category: str, window: Window, *, mode: str) -> str:
    """The AC-E.4 provenance line for an Atom-channel hit."""
    return (
        f"arXiv Atom channel cat:{category} window "
        f"{window.start.isoformat()}..{window.end.isoformat()} "
        f"(sortBy=submittedDate; mode={mode})"
    )


__all__ = [
    "atom_source_citation",
    "fetch_live_candidates",
    "filter_to_window",
    "load_fixture_candidates",
]
