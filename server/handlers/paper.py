"""``get_paper`` handler — hydrated metadata from the per-notebook
store, synthesized fallback from the chunks table.

paper-metadata-m2: when ``Resources.paper_metadata_store`` (the
per-notebook SQLite store from paper-metadata-m1, hydrated by
``tools/notebook_metadata_backfill.py``) carries a usable row for the
paper — non-empty title AND authors, matching the store's
``hydrated_paper_ids`` gate — the handler returns real values:

- ``title`` / ``abstract`` — wrapped in ``<retrieved_chunk>``
  delimiters (Threat 2: arXiv-authored free text is DATA, not
  instructions)
- ``authors`` — list of names, each delimiter-wrapped
- ``year`` (``0`` in the store means "unparseable" → ``null`` here)
- ``categories``

and ``metadata_status="hydrated"``.

Always synthesized from the chunks table, store or no store:

- ``paper_id`` (echoed)
- ``chunk_count`` (number of chunks for the paper)
- ``section_count`` (distinct ``section_path[0]`` values)
- ``chunker_version`` / ``embedder_version`` (taken from any chunk
  — the contract is that they're identical across all chunks of a
  paper, since ingest writes one paper at a time)

When the store is absent (never hydrated / shared-corpus boot) or has
no usable row for the paper, the identity fields stay ``null`` and
``metadata_status="synthesized_from_chunks"`` — the v1 behavior. A
store read error degrades the same way (metadata is an enrichment,
never a 5xx).

When the paper_id is unknown, returns ``{found: false, ...}``.
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
from server.tools import (
    enforce_byte_cap,
    envelope,
    get_resources,
    wrap_retrieved_text,
)

logger = logging.getLogger(__name__)


def hydrated_paper_fields(record: Any) -> dict[str, Any] | None:
    """Map a ``PaperMetadataRecord`` to the ``get_paper`` identity
    fields, or ``None`` when the row is not usable.

    Mirrors the store's ``hydrated_paper_ids`` gate: a row with an
    empty title OR empty authors (a defensive-write leftover the
    backfill will retry) is treated as absent rather than surfacing
    half-empty identity with ``metadata_status="hydrated"``. The
    store's empty-value conventions map back to nulls: ``year == 0``
    ("unparseable <published>") → ``null``; empty abstract /
    categories → ``null``.

    Text fields are sanitized here (pre-cap, so the byte cap measures
    post-sanitize bytes) but NOT delimiter-wrapped — wrapping happens
    in the handler AFTER ``enforce_byte_cap`` so truncation can never
    slice a delimiter tag (the get_chunk ordering discipline).
    """
    if record is None or not record.title or not record.authors:
        return None
    abstract = sanitize_retrieved_text(record.abstract)
    return {
        "abstract": abstract or None,
        "authors": [sanitize_retrieved_text(a) for a in record.authors],
        "categories": list(record.categories) or None,
        "title": sanitize_retrieved_text(record.title),
        "year": record.year if record.year > 0 else None,
    }


def _cap(payload: dict[str, Any]) -> dict[str, Any]:
    """Apply the 256 KB result byte cap to the per-paper envelope
    (E13_S04b).

    Live since paper-metadata-m2: a hydrated row can carry a
    multi-paragraph LaTeX abstract, and a high-author-count physics
    paper (ATLAS/CMS with 3000+ authors) could push a single
    ``get_paper`` response past 256 KB without this cap.

    Post-F1 rectification (E13_S04b adversary critique): the
    truncation target is the abstract field at
    ``("paper", "abstract")`` — the field most likely to exceed
    the cap. When the cap fires, the abstract is truncated to 1024
    chars and ``body_truncated=True`` is set. ``chunk_id=None``
    because the over-cap surface is the paper-level metadata, not a
    chunk (the agent already knows the ``paper_id`` and can re-fetch
    if needed).
    """
    structured, _blocks = enforce_byte_cap(
        payload, body_text_path=("paper", "abstract")
    )
    return structured


#: Source kinds ``get_paper`` serves (arXMCP#209). Both: the handler reads
#: the chunks table through an escaped ``paper_id =`` predicate, which is
#: kind-agnostic, and the ``textbook:`` slug grammar admits only
#: ``[a-z0-9-]`` after the colon — no quote, dot or separator that could
#: reach the predicate or a path.
SUPPORTED_SOURCE_KINDS: frozenset[str] = ALL_SOURCE_KINDS


def _unsupported_envelope(
    paper_id: str, exc: UnsupportedSourceKind
) -> dict[str, Any]:
    """The abstention response: the normal shape, empty, plus why.

    Keeping ``paper``/``chunk_count`` present plus a positive
    ``outcome`` means an agent gets a parseable answer instead of a
    tool error, and can tell this apart from "paper not in corpus".
    """
    return envelope(
        {
            "chunk_count": 0,
            "metadata_status": "unavailable",
            "paper": None,
            "paper_id": paper_id,
            **unsupported_outcome(exc),
        }
    )


async def handle_get_paper(
    paper_id: Annotated[str, Field(min_length=1, description="arXiv paper id")],
) -> dict[str, Any]:
    # agent-platform-t-inert-args-cleanup (#82): the former ``version``
    # arg was accepted-and-ignored (never referenced) over a corpus that
    # stores no per-version rows. Removed rather than left as a lie; an
    # agent that needs a specific version parses the ``vN`` suffix it
    # already carries on ``paper_id``.
    # F3 fix from the E06_S03 critique: validate before using
    # paper_id in a SQL-style WHERE clause.
    # arXMCP#209: admit the full identifier domain that ``search_papers``
    # emits. This gated on the arXiv-only validator and raised "does not
    # match the arXiv id format" at a ``textbook:`` id the server had just
    # handed the caller. The rows are in the same chunks table under the
    # same ``paper_id`` column, reached by the same escaped predicate
    # below, so there was never a data reason to refuse them.
    try:
        admit_paper_id(paper_id, SUPPORTED_SOURCE_KINDS)
    except UnsupportedSourceKind as exc:
        return _cap(_unsupported_envelope(paper_id, exc))
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
    metadata_status = "synthesized_from_chunks"

    # paper-metadata-m2: overlay real identity from the per-notebook
    # metadata store when a usable row exists. Read errors degrade to
    # the synthesized nulls — metadata is an enrichment, never a 5xx.
    store = getattr(r, "paper_metadata_store", None)
    if store is not None:
        record = None
        try:
            record = await store.get(paper_id)
        except Exception:  # noqa: BLE001 — degrade, don't fail the call
            logger.warning(
                "get_paper: paper_metadata_store.get(%r) failed; "
                "degrading to synthesized-from-chunks nulls",
                paper_id,
                exc_info=True,
            )
        hydrated = hydrated_paper_fields(record)
        if hydrated is not None:
            paper.update(hydrated)
            metadata_status = "hydrated"

    structured = _cap(
        {
            "found": True,
            "metadata_status": metadata_status,
            "paper": paper,
            "paper_id": paper_id,
        }
    )
    # Threat 2 — wrap arXiv-authored free text AFTER the byte cap so
    # abstract truncation can never slice a delimiter tag (same
    # ordering discipline as get_chunk's body_text path).
    capped_paper = structured.get("paper")
    if isinstance(capped_paper, dict):
        for key in ("title", "abstract"):
            if capped_paper.get(key):
                capped_paper[key] = wrap_retrieved_text(
                    capped_paper[key], kind="chunk"
                )
        if capped_paper.get("authors"):
            capped_paper["authors"] = [
                wrap_retrieved_text(a, kind="chunk")
                for a in capped_paper["authors"]
            ]
    return envelope(structured)


def _escape(s: str) -> str:
    return s.replace("'", "''")
