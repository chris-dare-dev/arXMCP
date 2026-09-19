"""``get_paper`` handler — per-notebook metadata store + chunk synthesis.

paper-metadata-m1 shipped the per-notebook metadata STORE
(:mod:`server.paper_metadata_store` → ``PaperMetadataStore`` /
``PaperMetadataRecord``, one SQLite file per notebook at
``var/arxmcp/notebooks/<slug>/paper_metadata.db``, hydrated from the
arXiv Atom API by ``tools/notebook_metadata_backfill.py``) but deferred
the *wiring* of ``get_paper`` to it (the "m2" step). This handler IS
that wiring: it overlays the per-notebook store on the historical chunk
synthesis.

Fields synthesized from the chunks table (unchanged):

- ``paper_id`` (echoed)
- ``chunk_count`` (number of chunks for the paper)
- ``section_count`` (distinct ``section_path[0]`` values)
- ``chunker_version`` / ``embedder_version`` (taken from any chunk —
  the contract is that they're identical across all chunks of a paper,
  since ingest writes one paper at a time)

Fields overlaid from the per-notebook metadata store when a row exists:

- ``title``, ``authors``, ``abstract``, ``year``, ``categories`` — the
  arXiv-Atom-hydrated identity (``null`` / empty when no row is found,
  which is the preserved v1 degraded mode).
- ``primary_category`` / ``published`` — the richer m1 fields, surfaced
  additively (``null`` on the synthesized path so the envelope shape is
  stable regardless of hit/miss).

**Per-notebook lookup (the m1→m2 hard part).** ``get_paper(paper_id)``
carries no notebook argument — the MCP tool input schema is byte-frozen
for BP1 prompt-cache discipline, so a ``notebook`` parameter cannot be
added here the way ``search_papers`` accepts ``filters.notebook``. The
handler therefore resolves the paper's notebook SERVER-SIDE: it
enumerates the on-disk notebook directories
(:func:`tools._notebook_common.iter_notebook_slugs` — m1's membership
source of truth is per-notebook on-disk state, NOT the central
``notebook_papers`` junction, which m1 documents as empty), opens each
notebook's ``paper_metadata.db`` that exists, and returns the FIRST row
found for the (version-stripped, prefix-preserved) paper_id. Slugs are
enumerated in sorted order so the "first hit wins" tie-break is
deterministic across processes. The store row's existence IS the
membership proof, so no ``papers.txt`` re-parse is needed.

``metadata_status`` reports which mode produced the metadata fields:
``"notebook_metadata_store"`` when a per-notebook row was found,
``"synthesized_from_chunks"`` otherwise (the v1 constant — existing
consumers keep parsing it unchanged on the degraded path;
``tests/test_tools_all.py`` pins it).

A paper that has a metadata row but no chunks yet (metadata recorded,
embedding pending) returns ``found: true`` with ``chunk_count: 0`` —
metadata presence IS paper presence for this tool's consumers (node
labels, bibliographies). When neither exists: ``{found: false, ...}``.

Zero MCP schema impact: the tool's input schema and ``tools/list``
bytes are untouched (BP1 guard pins this suite-wide); only the response
payload gains real values where NULLs sat.
"""

from __future__ import annotations

import logging
from typing import Annotated, Any

from pydantic import Field

from ingest.identifiers import is_valid_arxiv_paper_id
from server.tools import enforce_byte_cap, envelope, get_resources

logger = logging.getLogger(__name__)

#: ``metadata_status`` value when a per-notebook metadata row supplied
#: the identity fields. Truthful marker for the m1 per-notebook store
#: (paper-metadata-m1 → m2 wiring); replaces arx-a45's ``papers_table``
#: (there is no central papers table any more). The degraded-path value
#: stays the v1 constant ``synthesized_from_chunks``
#: (``tests/test_tools_all.py`` pins it).
METADATA_STATUS_STORE = "notebook_metadata_store"
METADATA_STATUS_SYNTHESIZED = "synthesized_from_chunks"


def _cap(payload: dict[str, Any]) -> dict[str, Any]:
    """E13_S04b — apply the 256 KB result byte cap to the per-paper
    envelope.

    The truncation target is the abstract field at
    ``("paper", "abstract")`` — the field most likely to exceed the cap
    now that the metadata store fills it (a paper with a multi-paragraph
    LaTeX abstract, or a high-author-count physics paper, could push a
    single ``get_paper`` response past 256 KB). When the cap fires, the
    abstract is truncated to 1024 chars and ``body_truncated=True`` is
    set. ``chunk_id=None`` because the over-cap surface is the
    paper-level metadata, not a chunk (the agent already knows the
    ``paper_id`` and can re-fetch if needed).
    """
    structured, _blocks = enforce_byte_cap(
        payload, body_text_path=("paper", "abstract")
    )
    return structured


async def _lookup_notebook_metadata(paper_id: str) -> Any | None:
    """Resolve a paper's per-notebook metadata row, or ``None``.

    Returns the first :class:`server.paper_metadata_store.PaperMetadataRecord`
    found across the on-disk notebooks whose ``paper_metadata.db`` holds a
    row for ``paper_id`` (version-stripped, archive-prefix preserved — the
    key shape m1's backfill writes). ``None`` when no notebook, no store
    file, or no row matches — the caller then serves the synthesized
    fallback.

    Never raises: enumeration / open / query failures are swallowed at
    WARNING (metadata is an enrichment, not a gate — the same posture as
    the retired arx-a45 overlay and every other optional-store read).
    Imports are local so the handler's module-load path stays free of the
    metadata-store + notebook-common dependencies on the common no-store
    path (mirrors ``server.resources`` optional-store discipline).
    """
    from server.paper_metadata_store import PaperMetadataStore  # noqa: PLC0415
    from tools._arxiv_api import strip_id_version  # noqa: PLC0415
    from tools._notebook_common import (  # noqa: PLC0415
        NotebookError,
        iter_notebook_slugs,
        notebook_paper_metadata_db_path,
    )

    # Key shape parity with the m1 backfill: rows are keyed UNVERSIONED
    # with the old-style archive prefix intact (``math/0212237``). The
    # backfill keys via this same ``strip_id_version`` (see
    # ``tools/notebook_metadata_backfill.py``), so the lookup matches.
    lookup_id = strip_id_version(paper_id)

    try:
        slugs = iter_notebook_slugs()
    except Exception:  # noqa: BLE001 — enrichment must not gate get_paper
        logger.warning(
            "get_paper: notebook enumeration failed; serving synthesized "
            "metadata",
            exc_info=True,
        )
        return None

    for slug in slugs:
        try:
            db_path = notebook_paper_metadata_db_path(slug)
        except NotebookError:
            # A slug that passed iter_notebook_slugs' regex can still be
            # rejected by notebook_dir's symlink/containment check (a
            # TOCTOU tamper). Skip it — never surface the path.
            continue
        if not db_path.is_file():
            # Notebook exists but has never been backfilled — no store.
            continue
        try:
            store = await PaperMetadataStore.open(db_path)
            try:
                record = await store.get(lookup_id)
            finally:
                await store.close()
        except Exception:  # noqa: BLE001 — one bad store must not gate the rest
            logger.warning(
                "get_paper: could not read metadata store for notebook %r; "
                "continuing",
                slug,
                exc_info=True,
            )
            continue
        if record is not None:
            return record
    return None


async def handle_get_paper(
    paper_id: Annotated[str, Field(min_length=1, description="arXiv paper id")],
    version: Annotated[int | None, Field(description="Reserved; v1 ignores")] = None,
) -> dict[str, Any]:
    # F3 fix from the E06_S03 critique: validate before using
    # paper_id in a SQL-style WHERE clause.
    if not is_valid_arxiv_paper_id(paper_id):
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

    # paper-metadata-m1→m2 wiring: resolve the paper's per-notebook
    # metadata row (see :func:`_lookup_notebook_metadata`). ``None`` →
    # degraded synthesized mode (the preserved v1 behavior).
    meta_record = await _lookup_notebook_metadata(paper_id)

    if arrow.num_rows == 0 and meta_record is None:
        return envelope(_cap(
            {
                "found": False,
                "metadata_status": METADATA_STATUS_SYNTHESIZED,
                "paper": None,
                "paper_id": paper_id,
            }
        ))

    section_first = set()
    for sp in (
        arrow.column("section_path").to_pylist() if arrow.num_rows else []
    ):
        if sp:
            section_first.add(sp[0])
    chunker_versions = (
        arrow.column("chunker_version").to_pylist() if arrow.num_rows else []
    )
    embedder_versions = (
        arrow.column("embedder_version").to_pylist() if arrow.num_rows else []
    )

    # Synthesized base shape (v1). Metadata fields default to
    # null/empty and are overlaid below when a store row was found.
    # ``primary_category`` / ``published`` are surfaced additively from
    # m1's richer record; null on the synthesized path so the envelope
    # shape is stable regardless of hit/miss.
    paper = {
        "abstract": None,
        "authors": None,
        "categories": None,
        "chunk_count": arrow.num_rows,
        "chunker_version": chunker_versions[0] if chunker_versions else None,
        "embedder_version": embedder_versions[0] if embedder_versions else None,
        "paper_id": paper_id,
        "primary_category": None,
        "published": None,
        "section_count": len(section_first),
        "title": None,
        "year": None,
    }

    metadata_status = METADATA_STATUS_SYNTHESIZED
    if meta_record is not None:
        metadata_status = METADATA_STATUS_STORE
        # PaperMetadataRecord is a frozen dataclass (title:str,
        # authors:tuple, abstract:str, year:int, categories:tuple,
        # primary_category:str, published:str). Empty-string / empty-tuple
        # defaults map to null so consumers see the same null-means-absent
        # contract as the synthesized path (m1 stores '' / () rather than
        # SQL NULL; "non-empty" is m1's "non-NULL").
        paper["title"] = meta_record.title or None
        paper["authors"] = list(meta_record.authors) or None
        paper["abstract"] = meta_record.abstract or None
        # year == 0 is m1's "unparseable <published>" sentinel → null.
        paper["year"] = meta_record.year or None
        paper["categories"] = list(meta_record.categories) or None
        paper["primary_category"] = meta_record.primary_category or None
        paper["published"] = meta_record.published or None

    return envelope(_cap(
        {
            "found": True,
            "metadata_status": metadata_status,
            "paper": paper,
            "paper_id": paper_id,
        }
    ))


def _escape(s: str) -> str:
    return s.replace("'", "''")
