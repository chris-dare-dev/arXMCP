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

from server.observability.sanitize import sanitize_retrieved_text
from server.source_kinds import (
    ALL_SOURCE_KINDS,
    UnsupportedSourceKind,
    admit_paper_id,
    unsupported_outcome,
)
from server.theorem_names_store import (
    TheoremNamesStore,
    TheoremRow,
    dedup_key,
    normalize_name,
    serialize_section_path,
)
from server.tools import (
    cap_result_list,
    envelope,
    get_resources,
    wrap_retrieved_text,
)

logger = logging.getLogger(__name__)

MAX_K = 50


def _cap(payload: dict[str, Any]) -> dict[str, Any]:
    """E13_S04b — apply the 256 KB result byte cap to the
    ``matches[]`` aggregate.

    No-op today (matches are small rows: dedup_key, display_name,
    paper_id, chunk_id, section_path, confidence) but defensive
    against future chunk-body context expansion in the in-memory
    scan fallback (E10_S02).

    Uses :func:`server.tools.cap_result_list` with
    ``list_key="matches"`` (post-F1 rectification): when the cap
    fires, trailing matches are trimmed until the payload fits.
    ``chunk_id=None`` because the cap-overflow surface for a
    multi-match aggregate is the response envelope, not a single
    chunk.
    """
    structured, _blocks = cap_result_list(payload, list_key="matches")
    return structured


#: Source kinds ``find_lemma_by_name`` serves (arXMCP#209). Both: the
#: FTS5 index and the in-memory fallback both read the chunks table
#: without a source-kind filter.
SUPPORTED_SOURCE_KINDS: frozenset[str] = ALL_SOURCE_KINDS


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
    # arXMCP#209: admit the full identifier domain. The FTS5 theorem-names
    # index is built from the chunks table with no source-kind filter, so a
    # textbook's theorem names are already indexed; the arXiv-only gate was
    # refusing to scope a search to them and calling the id malformed.
    if paper_id is not None:
        try:
            admit_paper_id(paper_id, SUPPORTED_SOURCE_KINDS)
        except UnsupportedSourceKind as exc:
            return envelope(_cap(
                {
                    "matches": [],
                    "retrieval_mode": "unsupported_source_kind",
                    **unsupported_outcome(exc),
                }
            ))

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
        return envelope(_cap(
            {
                "matches": [],
                "retrieval_mode": "empty_after_normalization",
            }
        ))

    # Step 1: exact normalized-name match.
    hits = await store.exact_match(normalized, paper_id, k)
    if hits:
        return envelope(_cap(
            {
                "matches": [_row_to_match(h) for h in hits],
                "retrieval_mode": "fts5_exact",
            }
        ))

    # Step 2: FTS5 trigram substring match.
    hits = await store.fts5_match(normalized, paper_id, k)
    if hits:
        return envelope(_cap(
            {
                "matches": [_row_to_match(h) for h in hits],
                "retrieval_mode": "fts5_trigram",
            }
        ))

    # Step 3: Python-side trigram Jaccard (typo-tolerant). This is
    # what makes AC4 satisfiable — FTS5 alone fails the
    # "riemanroch" → "Riemann-Roch" case.
    hits = await store.fuzzy_jaccard(normalized, paper_id, k)
    return envelope(_cap(
        {
            "matches": [_row_to_match(h) for h in hits],
            "retrieval_mode": "fuzzy_jaccard",
        }
    ))


def _row_to_match(row: TheoremRow) -> dict[str, Any]:
    """Convert a TheoremRow to the response-row dict shape.

    E13_S02 (Threat 2) — ``display_name`` is paper-authored text
    (theorem labels written by the paper's author). Wrap in
    ``<retrieved_chunk>`` delimiters with the escape-on-emit defense
    against adversarial close tags. The ``theorem_name`` back-compat
    alias is wrapped consistently.
    """
    safe_name = wrap_retrieved_text(
        sanitize_retrieved_text(row.display_name), kind="chunk"
    )
    return {
        "chunk_id": row.chunk_id,
        "confidence": row.confidence,
        "dedup_key": row.dedup_key,
        "display_name": safe_name,
        "paper_id": row.paper_id,
        "section_path": list(row.section_path),
        "theorem_name": safe_name,  # back-compat alias
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
    # #496: project at the scanner. `LanceTable.to_arrow()` takes no arguments
    # in lancedb 0.30.x, so the previous shape materialized all 14 columns --
    # including two 1024-float vector columns, ~14 KB/row -- and then read four
    # of them. On a production-scale corpus an ordinary request down this
    # fallback path was a multi-gigabyte allocation. Projected, it is ~14 B/row.
    from server.corpus import project_columns  # noqa: PLC0415

    wanted = ["chunk_id", "paper_id", "theorem_name", "section_path"]
    arrow = project_columns(
        r.chunks_table, wanted, expected_rows=r.chunks_table.count_rows()
    )
    if arrow is None:
        # `chunks_table` is opened at a PINNED version (`resources.py` ->
        # `open_chunks_table_with_fallback(version=...)`), so a scan cannot
        # come back short because of a concurrent ingest; a short read here
        # means the read itself failed. Refuse rather than answer from a
        # partial scan, which would render as "no such lemma" for a lemma
        # that exists -- a wrong answer stated confidently.
        raise RuntimeError(
            "lemma fallback scan came back short at a pinned corpus version"
        )
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
        # E13_S02 (Threat 2) — defer wrap until AFTER the
        # exact-match sort below: the sort key compares the raw
        # theorem_name against the query string. Stash the raw
        # name under ``_raw_theorem_name`` (popped before emit) so
        # the sort works on raw text and the wrap applies to the
        # paper-authored content before it leaves this function.
        matches.append(
            {
                "_raw_theorem_name": tn,
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
            0 if r["_raw_theorem_name"].lower() == name_lower else 1,
            r["chunk_id"],
        )
    )
    # F7 rectification (E13_S02 adversary critique): slice to k
    # BEFORE wrapping. The previous implementation wrapped every row
    # in matches then sliced — O(N) wrap calls when O(k) suffices.
    # For pathological corpora with many matches for a common
    # theorem name (default k=10 but could rise), the wasted wrap
    # calls add up.
    matches = matches[:k]
    # E13_S02 — wrap paper-authored display_name / theorem_name in
    # delimiters with the escape-on-emit defense. Mirror the
    # FTS5-indexed ``_row_to_match`` path's wrapping so callers see
    # consistent wrapping regardless of which path produced the row.
    for r in matches:
        r.pop("_raw_theorem_name", None)
        wrapped = wrap_retrieved_text(
            sanitize_retrieved_text(r["theorem_name"]), kind="chunk"
        )
        r["display_name"] = wrapped
        r["theorem_name"] = wrapped

    return envelope(_cap(
        {
            "matches": matches,
            "retrieval_mode": "in_memory_scan_fallback",
        }
    ))
