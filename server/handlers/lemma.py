"""``find_lemma_by_name`` handler — in-memory case-insensitive scan.

v1 ships an in-memory substring scan over the chunks table
filtered by ``theorem_name IS NOT NULL``. The 50-paper corpus has
on the order of hundreds of named theorems; the scan is
sub-millisecond. The full-text (SQLite FTS5) index lands in
E10_S02; the API stays stable across the swap.

When ``paper_id`` is given, the scan is restricted to that paper.
"""

from __future__ import annotations

from typing import Annotated, Any

from pydantic import Field

from ingest.identifiers import is_valid_paper_id
from server.tools import envelope, get_resources

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
    # paper_id arg before using it as a filter.
    if paper_id is not None and not is_valid_paper_id(paper_id):
        raise ValueError(
            f"paper_id {paper_id!r} does not match the arXiv id format"
        )
    r = get_resources()
    arrow = r.chunks_table.to_arrow()
    chunk_ids = arrow.column("chunk_id").to_pylist()
    paper_ids = arrow.column("paper_id").to_pylist()
    theorem_names = arrow.column("theorem_name").to_pylist()
    theorem_labels = arrow.column("theorem_label").to_pylist()
    section_paths = arrow.column("section_path").to_pylist()

    name_lower = name.lower()
    matches = []
    for cid, pid, tn, tl, sp in zip(
        chunk_ids, paper_ids, theorem_names, theorem_labels, section_paths,
        strict=True,
    ):
        if tn is None or not isinstance(tn, str):
            continue
        if name_lower not in tn.lower():
            continue
        if paper_id is not None and pid != paper_id:
            continue
        matches.append(
            {
                "chunk_id": cid,
                "label": _format_label(tn, tl),
                "paper_id": pid,
                "section_path": list(sp) if sp else [],
                "theorem_label": tl,
                "theorem_name": tn,
            }
        )

    # Sort: exact-match-first, then chunk_id_asc.
    matches.sort(
        key=lambda r: (
            0 if r["theorem_name"].lower() == name_lower else 1,
            r["chunk_id"],
        )
    )

    return envelope(
        {
            "matches": matches[:k],
            "retrieval_mode": "in_memory_scan",
        }
    )


def _format_label(theorem_name: str | None, theorem_label: str | None) -> str:
    parts = [s for s in (theorem_name, theorem_label) if s]
    return " ".join(parts)
