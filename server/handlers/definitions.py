"""``get_definitions`` handler — read per-paper notation table.

Source: the LanceDB ``definitions`` table populated by
:mod:`ingest.index_definitions` at ingest time. Each row carries
``(definition_id, paper_id, symbol, symbol_raw, expansion,
defining_chunk_id, scope)``.

Two modes of operation:

* **Without ``term``** — return every definition for ``paper_id``
  sorted by ``symbol`` ascending, paginated at 100 entries per page
  with an opaque ``next_cursor`` token.
* **With ``term``** — lookup hierarchy:
  1. exact match on ``symbol``;
  2. exact match on ``symbol_raw``;
  3. case-insensitive prefix match on ``symbol_raw`` (NOT on
     ``symbol`` — LaTeX commands are case-sensitive, so case-folding
     the canonical form would be semantically wrong; see synthesis
     D7).

The handler returns ``{definitions: [], next_cursor: null, total: 0}``
for unknown papers and for papers with no preamble — both cases
collapse to "empty result, not an error" per the brief.

When the ``definitions`` LanceDB table itself is missing (corpus has
no preamble extraction artefacts), the handler degrades gracefully
to the same empty-result shape and flags ``index_status="absent"`` in
the envelope so callers can distinguish "indexed but empty" from
"index never built". This keeps the tool usable during the ingest
bootstrap path.
"""

from __future__ import annotations

import base64
import logging
from typing import Annotated, Any

from pydantic import Field

from ingest.identifiers import is_valid_paper_id
from server.tools import enforce_byte_cap, envelope, get_resources

logger = logging.getLogger(__name__)


#: Number of definitions returned per page in the un-filtered mode.
#: Per the milestone brief: "paginated at 100 entries per page".
PAGE_SIZE = 100


async def handle_get_definitions(
    paper_id: Annotated[str, Field(min_length=1, description="arXiv paper id")],
    term: Annotated[
        str | None,
        Field(description="Optional symbol or symbol_raw to look up"),
    ] = None,
    cursor: Annotated[
        str | None,
        Field(
            description=(
                "Opaque pagination cursor returned by a prior call as "
                "next_cursor. Ignored when term is set (term lookups are "
                "single-page)."
            )
        ),
    ] = None,
) -> dict[str, Any]:
    # Threat 1 closure: paper_id is interpolated into a LanceDB filter
    # predicate and otherwise echoed to logs; validating against the
    # canonical regex before any further work is the F3 discipline
    # from the E06_S03 critique.
    if not is_valid_paper_id(paper_id):
        raise ValueError(
            f"paper_id {paper_id!r} does not match the arXiv id "
            f"format (new-style YYMM.NNNNN[vN] or old-style "
            f"subject/NNNNNNN[vN])"
        )

    # F1 (E10_S01 critique) — treat an empty/whitespace-only term as
    # "no term". Without this guard ``term=""`` enters the term branch
    # and the case-insensitive prefix step's ``"".casefold()`` matches
    # every row in the table, dumping the whole paper in a single
    # response and bypassing the 100-entry pagination contract. The
    # exact-symbol and exact-symbol_raw steps already short-circuit on
    # empty input; only the prefix step misbehaves, so the cleanest
    # fix is to collapse falsy terms to None at the boundary.
    if term is not None and not term.strip():
        term = None

    table = _get_definitions_table()
    if table is None:
        # Index not built. Surface explicitly so callers can tell the
        # difference between "definitions=[] because nothing matched"
        # and "definitions=[] because there is no index". Both keep
        # the response shape stable.
        return _cap(
            envelope(
                {
                    "definitions": [],
                    "index_status": "absent",
                    "next_cursor": None,
                    "paper_id": paper_id,
                    "term": term,
                    "total": 0,
                }
            )
        )

    # Pull every row for this paper. The corpus has at most a few
    # hundred macros per paper (typical: under 50; pathological: a few
    # thousand for highly notational hep-th papers), so loading all
    # paper-scoped rows then paginating in Python is correct, simple
    # and bounded.
    rows = _load_paper_rows(table, paper_id)

    if term is not None:
        matched = _term_lookup(rows, term)
        return _cap(
            envelope(
                {
                    "definitions": matched,
                    "index_status": "ok",
                    "next_cursor": None,
                    "paper_id": paper_id,
                    "term": term,
                    "total": len(matched),
                }
            )
        )

    # Full-table mode: sort by symbol then paginate.
    rows.sort(key=lambda r: (r["symbol"], r["definition_id"]))
    total = len(rows)

    offset = _decode_cursor(cursor)
    page = rows[offset : offset + PAGE_SIZE]
    next_off = offset + PAGE_SIZE
    next_cursor = _encode_cursor(next_off) if next_off < total else None

    return _cap(
        envelope(
            {
                "definitions": page,
                "index_status": "ok",
                "next_cursor": next_cursor,
                "paper_id": paper_id,
                "term": term,
                "total": total,
            }
        )
    )


def _cap(payload: dict[str, Any]) -> dict[str, Any]:
    """F4 (E10_S01 critique) — apply the 256 KB result byte cap.

    The other 7-tool surface members enforce the cap themselves per
    the ``server/tools.py`` contract; ``get_definitions`` previously
    skipped this step because the per-page count (100) × typical
    macro size (~few hundred bytes) is well under cap by construction.
    The cap is added defensively for two reasons:

    1. A future operator raising ``PAGE_SIZE`` should not have to
       remember to also wire up the cap.
    2. Pathological ``\\DeclareMathOperator{\\X}{<huge body>}`` rows
       are not bounded by the per-row sanity check on input.

    ``enforce_byte_cap`` returns ``(structured, content_blocks)``;
    this handler has no per-row resource-link target so the
    ``content_blocks`` half is discarded (the byte cap path
    truncates ``body_text`` if present and flags
    ``body_truncated=True``; for the definitions envelope which has
    no ``body_text`` field the result is structurally unchanged
    unless someone adds one in a future schema bump).
    """
    structured, _blocks = enforce_byte_cap(payload)
    return structured


# ---------------------------------------------------------------------------
# LanceDB helpers
# ---------------------------------------------------------------------------


def _get_definitions_table() -> Any | None:
    """Return the live ``definitions`` LanceDB handle, or ``None``.

    The handle is set by ``Resources.startup`` if the table exists at
    startup time. ``None`` means the indexer has never run for this
    corpus — the handler degrades to an empty-result response.
    """
    r = get_resources()
    return getattr(r, "definitions_table", None)


def _load_paper_rows(table: Any, paper_id: str) -> list[dict[str, str]]:
    """Pull every definition row for ``paper_id`` as a list of dicts.

    Predicate uses a static-string filter; ``paper_id`` has already
    passed the canonical-id regex (Threat 1 closure above) so it
    cannot inject quotes or SQL-like syntax. LanceDB's filter parser
    rejects single-quote characters inside string literals anyway.
    """
    safe_filter = f"paper_id = '{paper_id}'"
    arrow = table.search().where(safe_filter).to_arrow()
    return arrow.to_pylist()


def _term_lookup(
    rows: list[dict[str, str]], term: str
) -> list[dict[str, str]]:
    """Apply the three-step term hierarchy.

    Returns matches sorted by ``symbol`` for determinism. Empty list
    if nothing matched at any step.
    """
    # Step 1: exact match on canonical symbol.
    exact = [r for r in rows if r["symbol"] == term]
    if exact:
        exact.sort(key=lambda r: (r["symbol"], r["definition_id"]))
        return exact

    # Step 2: exact match on author-form symbol_raw.
    exact_raw = [r for r in rows if r["symbol_raw"] == term]
    if exact_raw:
        exact_raw.sort(key=lambda r: (r["symbol"], r["definition_id"]))
        return exact_raw

    # Step 3: case-insensitive prefix on symbol_raw ONLY. LaTeX
    # command names are case-sensitive, so case-folding ``symbol``
    # would conflate distinct commands (``\AA`` vs ``\Aa``). Apply
    # the fold only to ``symbol_raw`` — the matching is loose because
    # the canonical-form hierarchy has already failed.
    needle = term.casefold()
    prefix = [
        r for r in rows
        if r["symbol_raw"].casefold().startswith(needle)
    ]
    prefix.sort(key=lambda r: (r["symbol"], r["definition_id"]))
    return prefix


# ---------------------------------------------------------------------------
# Cursor encoding (opaque base64 over an integer offset)
# ---------------------------------------------------------------------------


def _encode_cursor(offset: int) -> str:
    """Encode an integer offset as an opaque cursor token.

    Base64-of-decimal is overkill for ints alone, but it keeps the
    wire shape compatible with future cursor formats (e.g. a
    last-symbol token) without a versioning break. The handler does
    not promise stability of the token format across server versions
    — callers MUST treat the cursor as opaque.
    """
    return base64.urlsafe_b64encode(
        str(offset).encode("ascii")
    ).decode("ascii")


def _decode_cursor(cursor: str | None) -> int:
    """Decode an opaque cursor token to an integer offset.

    Returns 0 for ``None``, the empty string, or any malformed token.
    Tolerant decoding is intentional: a stale cursor from a re-ingest
    that shrunk the table should not 4xx the client; returning offset
    0 yields a correct (if redundant) first page.
    """
    if not cursor:
        return 0
    try:
        decoded = base64.urlsafe_b64decode(cursor.encode("ascii"))
        return max(0, int(decoded.decode("ascii")))
    except (ValueError, UnicodeDecodeError):
        return 0
