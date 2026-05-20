"""``get_paper`` handler — synthesize per-paper metadata from chunks.

v1 has no ``papers`` metadata table (E11/E12 will land one). This
handler synthesizes what it can from the chunks table:

- ``paper_id`` (echoed)
- ``chunk_count`` (number of chunks for the paper)
- ``section_count`` (distinct ``section_path[0]`` values)
- ``chunker_version`` / ``embedder_version`` (taken from any chunk
  — the contract is that they're identical across all chunks of a
  paper, since ingest writes one paper at a time)
- ``authors``, ``title``, ``abstract``, ``year``, ``categories``
  → ``null`` (not in the v1 schema)

The ``metadata_status`` field exposes the synthesized-from-chunks
mode so callers know which fields are partial.

When the paper_id is unknown, returns ``{found: false, ...}``.
"""

from __future__ import annotations

from typing import Annotated, Any

from pydantic import Field

from ingest.identifiers import is_valid_paper_id
from server.tools import enforce_byte_cap, envelope, get_resources


def _cap(payload: dict[str, Any]) -> dict[str, Any]:
    """E13_S04b — apply the 256 KB result byte cap to the per-paper
    envelope.

    No-op today (v1 returns NULL for abstract/authors/title/year/
    categories; only chunk_count/section_count/chunker_version/
    embedder_version are non-NULL, all tiny) but ESSENTIAL
    forward-compat for E11/E12 when the metadata table lands. A
    high-author-count physics paper (ATLAS/CMS with 3000+ authors)
    or a paper with a multi-paragraph LaTeX abstract could push a
    single ``get_paper`` response past 256 KB without this cap.

    Post-F1 rectification (E13_S04b adversary critique): the
    truncation target is the abstract field at
    ``("paper", "abstract")`` — the field most likely to exceed
    the cap in the E11/E12 metadata schema. When the cap fires,
    the abstract is truncated to 1024 chars and
    ``body_truncated=True`` is set. ``chunk_id=None`` because the
    over-cap surface is the paper-level metadata, not a chunk
    (the agent already knows the ``paper_id`` and can re-fetch
    if needed).
    """
    structured, _blocks = enforce_byte_cap(
        payload, body_text_path=("paper", "abstract")
    )
    return structured


async def handle_get_paper(
    paper_id: Annotated[str, Field(min_length=1, description="arXiv paper id")],
    version: Annotated[int | None, Field(description="Reserved; v1 ignores")] = None,
) -> dict[str, Any]:
    # F3 fix from the E06_S03 critique: validate before using
    # paper_id in a SQL-style WHERE clause.
    if not is_valid_paper_id(paper_id):
        raise ValueError(
            f"paper_id {paper_id!r} does not match the arXiv id format"
        )
    r = get_resources()

    # Filter to rows matching paper_id. LanceDB doesn't expose a
    # native group-by; pull the matching rows in Arrow and aggregate
    # in Python. For the 50-paper corpus the worst case is ~100s of
    # rows per paper — fast enough.
    arrow = (
        r.chunks_table.search()
        .where(f"paper_id = '{_escape(paper_id)}'", prefilter=True)
        .limit(10000)
        .to_arrow()
    )

    if arrow.num_rows == 0:
        return envelope(_cap(
            {
                "found": False,
                "metadata_status": "synthesized_from_chunks",
                "paper": None,
                "paper_id": paper_id,
            }
        ))

    section_first = set()
    for sp in arrow.column("section_path").to_pylist():
        if sp:
            section_first.add(sp[0])
    chunker_versions = arrow.column("chunker_version").to_pylist()
    embedder_versions = arrow.column("embedder_version").to_pylist()

    paper = {
        "abstract": None,
        "authors": None,
        "categories": None,
        "chunk_count": arrow.num_rows,
        "chunker_version": chunker_versions[0] if chunker_versions else None,
        "embedder_version": embedder_versions[0] if embedder_versions else None,
        "paper_id": paper_id,
        "section_count": len(section_first),
        "title": None,
        "year": None,
    }

    return envelope(_cap(
        {
            "found": True,
            "metadata_status": "synthesized_from_chunks",
            "paper": paper,
            "paper_id": paper_id,
        }
    ))


def _escape(s: str) -> str:
    return s.replace("'", "''")
