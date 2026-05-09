"""``get_chunk`` handler — direct LanceDB lookup by chunk_id.

The body-size cap (E06_S01 ``BodySizeCapMiddleware`` exempts
``/mcp``) is enforced per-handler via :func:`server.tools.enforce_byte_cap`
— a chunk whose JSON-serialized form exceeds
``Config.result_byte_cap`` (default 256 KB) is returned with
``body_truncated=True`` and a ``resource_link`` to
``arxmcp://chunks/<chunk_id>`` in the ``content`` array.

``include_referenced`` and ``include_equations`` accept the schema
arguments but return empty arrays at v1 — referenced-chunk
expansion (E07_S03 reranker output) and equation atoms
(E10_S03) are not yet built.
"""

from __future__ import annotations

from typing import Annotated, Any

from pydantic import Field

from ingest.identifiers import is_valid_chunk_id
from server.tools import enforce_byte_cap, envelope, get_resources


async def handle_get_chunk(
    chunk_id: Annotated[str, Field(description="Content-addressable chunk_id")],
    include_referenced: Annotated[
        bool, Field(description="Reserved for E07_S03; ignored at v1")
    ] = False,
    include_equations: Annotated[
        bool, Field(description="Reserved for E10_S03; ignored at v1")
    ] = False,
) -> dict[str, Any]:
    """Fetch one chunk by id. Raises a JSON-RPC error if the id
    is malformed. Returns ``{found: false, ...}`` if the chunk_id
    is well-formed but not in the corpus.
    """
    if not is_valid_chunk_id(chunk_id):
        raise ValueError(
            f"chunk_id {chunk_id!r} does not match "
            f"arxiv:<paper_id>:<16-hex> format"
        )
    r = get_resources()

    arrow = (
        r.chunks_table.search()
        .where(f"chunk_id = '{_escape_lance_str(chunk_id)}'", prefilter=True)
        .limit(1)
        .to_arrow()
    )
    if arrow.num_rows == 0:
        return envelope(
            {
                "chunk": None,
                "found": False,
                "include_equations_applied": False,
                "include_referenced_applied": False,
            }
        )

    row = _arrow_first_row(arrow)
    chunk = {
        "body_text": row["body_text"] or "",
        "chunk_id": row["chunk_id"],
        "chunker_version": row["chunker_version"],
        "embedder_version": row["embedder_version"],
        "kind": row["kind"],
        "paper_id": row["paper_id"],
        "preamble_ref": row["preamble_ref"],
        "section_path": list(row["section_path"]) if row["section_path"] else [],
        "theorem_label": row["theorem_label"],
        "theorem_name": row["theorem_name"],
    }

    payload = {
        "chunk": chunk,
        "found": True,
        "include_equations_applied": False,  # v1: deferred to E10_S03
        "include_referenced_applied": False,  # v1: deferred to E07_S03
        "unused_args": _record_unused_args(include_referenced, include_equations),
    }
    # F1 fix from E06_S03 critique: tell enforce_byte_cap that
    # body_text is nested under ``chunk``, not at the top level.
    # Without the explicit path, the cap would silently fail to
    # truncate get_chunk responses.
    structured, content_blocks = enforce_byte_cap(
        payload,
        chunk_id=chunk_id,
        body_text_path=("chunk", "body_text"),
    )
    if content_blocks:
        # FastMCP's add_tool handlers return structuredContent; the
        # content blocks are appended via FastMCP's automatic
        # text-content wrapping. We surface the resource_link by
        # encoding it into the structured payload AND signaling
        # body_truncated. E06_S04 will pin a richer resource_link
        # surface on search_papers; for get_chunk a single link is
        # sufficient.
        structured["resource_link_uri"] = content_blocks[0]["uri"]
    return envelope(structured)


def _arrow_first_row(arrow) -> dict[str, Any]:  # noqa: ANN001
    """Convert the first row of a 1-row Arrow table to a dict."""
    out: dict[str, Any] = {}
    for col in arrow.column_names:
        out[col] = arrow.column(col).to_pylist()[0]
    return out


def _record_unused_args(*flags: bool) -> list[str]:
    """Return a list of unused-arg names for any True flag — pure
    audit trail for the agent runtime to know which features it
    requested were silently ignored. Empty list when all False."""
    names = ("include_referenced", "include_equations")
    return [n for n, f in zip(names, flags, strict=True) if f]


def _escape_lance_str(s: str) -> str:
    """Escape single quotes for LanceDB SQL-style WHERE clauses."""
    return s.replace("'", "''")
