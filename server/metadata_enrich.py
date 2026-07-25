"""Row-level paper title/year enrichment (agent-platform-t-semantic-identifiers, #84).

``search_papers`` and ``cite_neighbors`` rows carry a ``paper_id`` but no
human-readable identifier, so an agent scanning a result list must call
``get_paper`` once per row just to learn what each paper IS. This joins a
``title`` (and ``year``) from the :class:`PaperMetadataStore` onto each
row, in place.

Shared by both handlers so the version-normalization, null-safety, and
Threat-2 wrapping are written once. The LRU that bounds DB reads lives on
the store instance (see :meth:`PaperMetadataStore.get_cached`); this
module only dedups within a single response and formats the field.
"""

from __future__ import annotations

from typing import Any

from server.observability.sanitize import sanitize_retrieved_text
from server.tools import wrap_retrieved_text
from tools._arxiv_api import strip_id_version


async def enrich_rows_with_titles(
    store: Any,
    rows: list[dict[str, Any]],
    *,
    id_key: str = "paper_id",
) -> None:
    """Add ``title`` and ``year`` to each row in ``rows``, in place.

    - **Idempotent.** Rows already carrying a ``title`` key are skipped,
      so a cache-hit payload enriched at store time is never re-read
      (the search cache stores the enriched rows).
    - **Null-safe + byte-stable.** ``store is None``, an absent or
      un-hydrated row, or any store error yields ``title=None,
      year=None`` — never raises. Every row ends with both keys present
      so the response shape is stable regardless of store state.
    - **One DB read per DISTINCT paper_id.** Version-normalized first
      (the store is keyed unversioned; a ``2401.00001v2`` row id must
      still resolve its ``2401.00001`` record), deduped, then fetched
      through the store's bounded LRU.
    - **Threat 2.** ``title`` is arXiv-authored free text, so it is
      sanitized and ``<retrieved_chunk>``-wrapped exactly like the
      snippet field and get_paper's title. ``year`` is a bare int.
    """
    pending = [r for r in rows if "title" not in r]
    if not pending:
        return
    if store is None:
        for row in pending:
            row["title"] = None
            row["year"] = None
        return

    resolved: dict[str, tuple[str | None, int | None]] = {}
    for norm in {
        strip_id_version(row[id_key]) for row in pending if row.get(id_key)
    }:
        try:
            record = await store.get_cached(norm)
        except Exception:  # noqa: BLE001 — enrichment must never break a response
            record = None
        if record is not None and record.title:
            resolved[norm] = (
                record.title,
                record.year if record.year > 0 else None,
            )
        else:
            resolved[norm] = (None, None)

    for row in pending:
        raw_title, year = resolved.get(
            strip_id_version(row.get(id_key, "")), (None, None)
        )
        row["title"] = (
            wrap_retrieved_text(sanitize_retrieved_text(raw_title), kind="chunk")
            if raw_title
            else None
        )
        row["year"] = year
