"""``find_lemma_by_name`` handler — FTS5 + Jaccard fallback (E10_S02).

Three-step lookup against the SQLite-backed
:class:`server.theorem_names_store.TheoremNamesStore`:

1. **Exact match** on the normalized form
   (``retrieval_mode="fts5_exact"``).
2. **FTS5 trigram MATCH** for substring-tolerant lookup
   (``retrieval_mode="fts5_trigram"``).
3. **Python-side trigram Jaccard fallback** for typo-tolerant lookup
   (``retrieval_mode="fuzzy_jaccard"``). This is the AC4-satisfying
   path — FTS5 trigram MATCH does NOT satisfy
   "``find_lemma_by_name('riemanroch')`` returns Riemann-Roch entries"
   on its own because the query trigrams ``ano,noc`` are not
   substrings of the indexed ``"riemannroch"``. The Jaccard step
   scores by trigram-set overlap which tolerates inner-character
   typos.

The optional ``paper_id`` argument restricts the search to one paper
on all three steps (SQL WHERE on steps 1 and 2; Python filter on
step 3).

When the theorem-names SQLite DB is absent (corpus has not been
indexed yet), the handler falls back to the legacy in-memory scan
over the chunks table; ``retrieval_mode="in_memory_scan_fallback"``.
This mirrors the E10_S01 ``get_definitions`` "graceful absent" path.

Response shape: superset of the v1 handler. ``chunk_id``,
``paper_id``, ``section_path``, ``theorem_name`` are preserved.
``dedup_key``, ``display_name``, ``confidence`` are added. The
derived ``label`` and ``theorem_label`` fields are dropped (callers
can format from ``display_name``).
"""

from __future__ import annotations

import logging
from typing import Annotated, Any

from pydantic import Field

from ingest.identifiers import is_valid_paper_id
from server.theorem_names_store import (
    TheoremNamesStore,
    TheoremRow,
    dedup_key,
    normalize_name,
    serialize_section_path,
)
from server.tools import envelope, get_resources

logger = logging.getLogger(__name__)

MAX_K = 50


async def handle_find_lemma_by_name(
    name: Annotated[
        str, Field(min_length=1, max_length=200, description="Theorem/lemma name")
    ],
    paper_id: Annotated[
        str | None, Field(description="Optional restrict to one paper")
    ] = None,
    k: Annotated[int, Field(ge=1, le=MAX_K, description="Top-k cutoff")] = 10,
) -> dict[str, Any]:
    # F3 fix from the E06_S03 critique: validate the optional
    # paper_id arg before using it as a filter (same as v1).
    if paper_id is not None and not is_valid_paper_id(paper_id):
        raise ValueError(
            f"paper_id {paper_id!r} does not match the arXiv id format"
        )

    r = get_resources()
    store: TheoremNamesStore | None = getattr(r, "theorem_names_db", None)
    if store is None:
        # Index not built yet. Fall back to the legacy in-memory
        # scan so the tool stays usable during ingest bootstrap.
        return await _in_memory_scan_fallback(r, name, paper_id, k)

    normalized = normalize_name(name)
    # F4 (E10_S02 critique) close — a name that collapses to "" under
    # normalization (e.g. all-punctuation, all-whitespace) has nothing
    # meaningful to look up. Use a distinct ``retrieval_mode`` tag so
    # downstream agents can tell "input was effectively garbage" apart
    # from "exact match found nothing." This is a NEW response-shape
    # value (not pinned in tools/list since input/output schemas live
    # there, but the actual ``retrieval_mode`` taxonomy does not) so
    # no hash repin is required.
    if not normalized:
        return envelope(
            {
                "matches": [],
                "retrieval_mode": "empty_after_normalization",
            }
        )

    # Step 1: exact normalized-name match.
    hits = await store.exact_match(normalized, paper_id, k)
    if hits:
        return envelope(
            {
                "matches": [_row_to_match(h) for h in hits],
                "retrieval_mode": "fts5_exact",
            }
        )

    # Step 2: FTS5 trigram substring match.
    hits = await store.fts5_match(normalized, paper_id, k)
    if hits:
        return envelope(
            {
                "matches": [_row_to_match(h) for h in hits],
                "retrieval_mode": "fts5_trigram",
            }
        )

    # Step 3: Python-side trigram Jaccard (typo-tolerant). This is
    # what makes AC4 satisfiable — FTS5 alone fails the
    # "riemanroch" → "Riemann-Roch" case.
    hits = await store.fuzzy_jaccard(normalized, paper_id, k)
    return envelope(
        {
            "matches": [_row_to_match(h) for h in hits],
            "retrieval_mode": "fuzzy_jaccard",
        }
    )


def _row_to_match(row: TheoremRow) -> dict[str, Any]:
    """Convert a TheoremRow to the response-row dict shape."""
    return {
        "chunk_id": row.chunk_id,
        "confidence": row.confidence,
        "dedup_key": row.dedup_key,
        "display_name": row.display_name,
        "paper_id": row.paper_id,
        "section_path": list(row.section_path),
        "theorem_name": row.display_name,  # back-compat alias
    }


# ---------------------------------------------------------------------------
# Legacy in-memory scan fallback (kept for the absent-index case)
# ---------------------------------------------------------------------------


async def _in_memory_scan_fallback(
    r: Any, name: str, paper_id: str | None, k: int
) -> dict[str, Any]:
    """Original v1 behavior — used when the SQLite DB is absent.

    Scans the chunks table for rows where ``theorem_name`` is
    non-null and case-insensitively contains ``name``. Reports
    ``retrieval_mode="in_memory_scan_fallback"`` so callers can
    detect the degraded path.
    """
    arrow = r.chunks_table.to_arrow()
    chunk_ids = arrow.column("chunk_id").to_pylist()
    paper_ids = arrow.column("paper_id").to_pylist()
    theorem_names = arrow.column("theorem_name").to_pylist()
    section_paths = arrow.column("section_path").to_pylist()

    name_lower = name.lower()
    matches: list[dict[str, Any]] = []
    for cid, pid, tn, sp in zip(
        chunk_ids, paper_ids, theorem_names, section_paths, strict=True
    ):
        if tn is None or not isinstance(tn, str):
            continue
        if name_lower not in tn.lower():
            continue
        if paper_id is not None and pid != paper_id:
            continue
        # F3 (E10_S02 critique) close — synthesize a dedup_key in
        # the fallback path using the same recipe as the indexer
        # so downstream callers see a stable, non-NULL identifier
        # regardless of which path produced the row. The
        # ``in_memory_scan_fallback`` mode tag is the channel that
        # tells callers this row didn't go through the SQLite index.
        sp_list = list(sp) if sp else []
        sp_json = serialize_section_path(sp_list)
        matches.append(
            {
                "chunk_id": cid,
                "confidence": 1.0,
                "dedup_key": dedup_key(pid, tn, sp_json),
                "display_name": tn,
                "paper_id": pid,
                "section_path": sp_list,
                "theorem_name": tn,
            }
        )

    matches.sort(
        key=lambda r: (
            0 if r["theorem_name"].lower() == name_lower else 1,
            r["chunk_id"],
        )
    )

    return envelope(
        {
            "matches": matches[:k],
            "retrieval_mode": "in_memory_scan_fallback",
        }
    )
