"""MCP tool registration + shared envelope helpers (E06_S03).

Wires the 7 v1 tools into the :class:`mcp.server.fastmcp.FastMCP`
server constructed by :func:`server.main.create_app`. Tool handlers
live in :mod:`server.handlers.*` (one file per tool); this module is
the dispatch + registration boundary.

**Frozen tool descriptions.** Every tool's name and description are
defined as class-level constants on a frozen :class:`ToolMeta`
dataclass instance — bytes-stable across server restarts. The brief's
"frozen Python dataclasses" requirement is satisfied here; the
inputSchema bytes are derived by FastMCP from each handler's typed
function signature, and the rendered ``tools/list`` JSON is
hash-pinned by E06_S06.

**Per-tool ``_meta``.** Every registered tool carries
``_meta: {"tool_schema_version": <int>}`` per synthesis D3. The
constant :data:`TOOL_SCHEMA_VERSION` is bumped manually on any
schema change; the byte-stability test (E06_S06) catches the gap if
a contributor forgets.

**Resources hand-off.** Tool handlers reach the live
:class:`server.resources.Resources` via :func:`get_resources`. The
lifespan calls :func:`set_resources` after :meth:`Resources.startup`
returns; handlers raise :class:`ResourcesNotReadyError` if they're
called before that. Synthesis D8.

**Result envelope.** Every tool result includes ``corpus_version``
in ``structuredContent`` per the design constitution. Use
:func:`envelope` to wrap a tool's payload before returning.

**Body-size cap.** The E06_S01 ``BodySizeCapMiddleware`` exempts
``/mcp`` (Streamable-HTTP carries SSE streams that defeat
buffering). So tools enforce the 256 KB cap themselves via
:func:`enforce_byte_cap`. Synthesis D9.

**Sort order.** Every list-returning tool sorts its results by
``(score_desc, chunk_id_asc)`` per the determinism contract
(``06-mcp-server-design.md`` lines 270-290) and synthesis D10.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from mcp.server.fastmcp import FastMCP

    from server.resources import Resources

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

#: Bumped manually on any tool schema change. The E06_S06 byte-
#: stability test fails if a schema bytes change without a bump here.
#: Surfaced via per-tool ``_meta: {"tool_schema_version": ...}``.
TOOL_SCHEMA_VERSION: int = 1

#: URI scheme for chunk resource_links per the design note. Used by
#: handlers that switch to resource_link mode when payloads exceed
#: ``Config.result_byte_cap``.
CHUNK_RESOURCE_URI_SCHEME = "arxmcp://chunks/"


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class ResourcesNotReadyError(RuntimeError):
    """Raised by handlers if invoked before :func:`set_resources` was
    called by the lifespan. Should never fire in production — the
    server's lifespan registers tools BEFORE
    :meth:`mcp_server.session_manager.run` opens for requests."""


# ---------------------------------------------------------------------------
# Frozen tool metadata (one ToolMeta per tool — descriptions byte-stable)
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ToolMeta:
    """Immutable name + description constants for one MCP tool.

    Frozen so a contributor cannot accidentally mutate a description
    at runtime (which would break BP1 byte-stability of the
    ``tools/list`` response).
    """

    name: str
    description: str


SEARCH_PAPERS = ToolMeta(
    name="search_papers",
    description=(
        "Search the corpus for chunks matching a natural-language query. "
        "Returns the top-k chunks ranked by relevance. The level argument "
        "controls aggregation: level='theorem' (default) returns one row "
        "per chunk; level='section' deduplicates by (paper_id, section); "
        "level='paper' returns one row per paper. NOTE: v1 ships dense-only "
        "ANN retrieval over BGE-M3 statement embeddings; the BM25 + RRF "
        "hybrid path lands in E07. The result-level retrieval_mode field "
        "exposes the active mode."
    ),
)

GET_CHUNK = ToolMeta(
    name="get_chunk",
    description=(
        "Fetch the full body of one chunk by its content-addressable "
        "chunk_id. Use search_papers first to obtain chunk_ids. Large "
        "chunks (over the 256 KB inline cap) are returned as a "
        "resource_link with body_truncated=True; agents follow the link "
        "to fetch the full payload."
    ),
)

FIND_EQUATION = ToolMeta(
    name="find_equation",
    description=(
        "Search for chunks containing equations similar to the supplied "
        "LaTeX or MathML. v1 ships dense-only fallback (the equation TED "
        "index lands in E10_S03); the LaTeX is embedded as a query and "
        "matched against statement embeddings. The retrieval_mode field "
        "in the result documents the active mode."
    ),
)

GET_DEFINITIONS = ToolMeta(
    name="get_definitions",
    description=(
        "Return the per-paper notation/macro table for the given "
        "paper_id. With term: returns only the macro whose symbol "
        "matches term (exact). Without term: returns the full table. "
        "Source: the per-paper preamble.json written by the E02_S02 "
        "preamble extractor; one entry per \\newcommand."
    ),
)

FIND_LEMMA_BY_NAME = ToolMeta(
    name="find_lemma_by_name",
    description=(
        "Find theorems/lemmas/propositions by their natural-language "
        "name. v1 ships an in-memory case-insensitive substring scan "
        "over chunks where theorem_name is non-null. The full-text "
        "(SQLite FTS5) index lands in E10_S02; the API stays stable "
        "across the swap."
    ),
)

GET_PAPER = ToolMeta(
    name="get_paper",
    description=(
        "Return per-paper metadata. v1 synthesizes from the chunks "
        "table (paper_id, chunker_version, embedder_version, chunk_count, "
        "section_count). Fields like authors, title, abstract, year, "
        "categories are returned as null until a real papers metadata "
        "table lands (E11/E12); metadata_status documents the mode."
    ),
)

CITE_NEIGHBORS = ToolMeta(
    name="cite_neighbors",
    description=(
        "Return citation-graph neighbors of a chunk_id. v1 returns an "
        "empty neighbors list with infrastructure_status='deferred' — "
        "the Kùzu citation graph (E09) and intra-paper theorem "
        "dependency parser (depends_on direction) are not yet built. "
        "API is stable; result population unblocks when E09 ships."
    ),
)


#: All seven tool meta records, in registration order. The
#: E06_S06 byte-stability test pins the rendered ``tools/list``
#: response which depends on this ordering.
ALL_TOOLS: tuple[ToolMeta, ...] = (
    SEARCH_PAPERS,
    GET_CHUNK,
    FIND_EQUATION,
    GET_DEFINITIONS,
    FIND_LEMMA_BY_NAME,
    GET_PAPER,
    CITE_NEIGHBORS,
)


# ---------------------------------------------------------------------------
# Resources hand-off (lifespan → handlers)
# ---------------------------------------------------------------------------

_RESOURCES: Resources | None = None


def set_resources(r: Resources) -> None:
    """Register the live Resources singleton for handler access.

    Called from :func:`server.main.lifespan` after
    :meth:`Resources.startup` returns. Handlers read the singleton
    via :func:`get_resources`.
    """
    global _RESOURCES
    _RESOURCES = r


def get_resources() -> Resources:
    """Return the live Resources singleton or raise.

    Handlers call this on every invocation. In production the
    singleton is set by the lifespan BEFORE the MCP session manager
    opens, so this never raises in steady state.
    """
    if _RESOURCES is None:
        raise ResourcesNotReadyError(
            "Resources singleton not set; the server lifespan has not "
            "completed startup. Tool handlers cannot run before the "
            "embedder + LanceDB are warm."
        )
    return _RESOURCES


def reset_resources_for_tests() -> None:
    """Test hook — clear the singleton so a fresh test_app can attach
    its own Resources without leaking state from a prior test."""
    global _RESOURCES
    _RESOURCES = None


# ---------------------------------------------------------------------------
# Result-envelope helpers
# ---------------------------------------------------------------------------


def envelope(payload: dict[str, Any]) -> dict[str, Any]:
    """Wrap a tool's payload with the canonical result envelope.

    Adds ``corpus_version`` (sourced from the live Resources) and
    sorts the dict alphabetically (BP1 byte-stability).
    """
    r = get_resources()
    payload = {**payload, "corpus_version": r.corpus_info.version}
    return _sort_dict(payload)


def _sort_dict(d: dict[str, Any]) -> dict[str, Any]:
    """Recursively re-build ``d`` with alphabetically sorted keys.

    Lists are NOT sorted (rank ordering is intentional); nested
    dicts are. The result is a fresh dict suitable for JSON
    serialization with byte-stable output.
    """
    out: dict[str, Any] = {}
    for k in sorted(d):
        v = d[k]
        if isinstance(v, dict):
            out[k] = _sort_dict(v)
        elif isinstance(v, list):
            out[k] = [_sort_dict(x) if isinstance(x, dict) else x for x in v]
        else:
            out[k] = v
    return out


def enforce_byte_cap(
    structured_content: dict[str, Any], chunk_id: str | None = None
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Enforce the per-tool body-size cap (synthesis D9).

    Returns a 2-tuple of ``(structured_content, content_blocks)``.
    On the happy path (under cap), ``content_blocks`` is empty.
    When the serialized payload exceeds
    :attr:`Config.result_byte_cap`, the content_blocks list carries
    a ``resource_link`` block pointing at the chunk's URI so the
    agent can follow the link for the full body. The
    structured_content is mutated to flip ``body_truncated=True``
    and replace ``body_text`` with a 1024-char sentinel.

    Returning a tuple (rather than mutating in place) lets each
    handler decide whether to surface the resource_link in its
    own ``content`` array.
    """
    serialized = json.dumps(structured_content, ensure_ascii=False, sort_keys=True)
    cap = get_resources().config.result_byte_cap
    if len(serialized.encode("utf-8")) <= cap:
        return structured_content, []

    # Over cap. Truncate body_text if present, surface resource_link.
    truncated = dict(structured_content)
    if "body_text" in truncated and isinstance(truncated["body_text"], str):
        truncated["body_text"] = truncated["body_text"][:1024]
    truncated["body_truncated"] = True
    blocks: list[dict[str, Any]] = []
    if chunk_id is not None:
        blocks.append(
            {
                "type": "resource_link",
                "uri": f"{CHUNK_RESOURCE_URI_SCHEME}{chunk_id}",
                "name": chunk_id,
            }
        )
    return _sort_dict(truncated), blocks


# ---------------------------------------------------------------------------
# Registration entry point
# ---------------------------------------------------------------------------


def register_all(mcp_server: FastMCP) -> None:
    """Register all 7 v1 tools on ``mcp_server``.

    Called from :func:`server.main.create_app` BEFORE
    ``mount_mcp(app, mcp_server)`` — the streamable_http_app
    snapshots the registered tools at mount time, so registration
    must complete first (synthesis D11).

    Each tool gets ``meta={"tool_schema_version": TOOL_SCHEMA_VERSION}``
    surfaced via FastMCP's ``add_tool(meta=...)`` argument (D3).
    """
    # Lazy imports to avoid a circular import at module load
    # (handlers re-import server.tools for the envelope helpers).
    from server.handlers.chunk import handle_get_chunk
    from server.handlers.citations import handle_cite_neighbors
    from server.handlers.definitions import handle_get_definitions
    from server.handlers.equation import handle_find_equation
    from server.handlers.lemma import handle_find_lemma_by_name
    from server.handlers.paper import handle_get_paper
    from server.handlers.search import handle_search_papers

    handler_by_name = {
        SEARCH_PAPERS.name: handle_search_papers,
        GET_CHUNK.name: handle_get_chunk,
        FIND_EQUATION.name: handle_find_equation,
        GET_DEFINITIONS.name: handle_get_definitions,
        FIND_LEMMA_BY_NAME.name: handle_find_lemma_by_name,
        GET_PAPER.name: handle_get_paper,
        CITE_NEIGHBORS.name: handle_cite_neighbors,
    }

    meta = {"tool_schema_version": TOOL_SCHEMA_VERSION}
    for tm in ALL_TOOLS:
        mcp_server.add_tool(
            handler_by_name[tm.name],
            name=tm.name,
            description=tm.description,
            meta=meta,
        )
    logger.info("registered %d MCP tools (schema_version=%d)", len(ALL_TOOLS), TOOL_SCHEMA_VERSION)


__all__ = [
    "ALL_TOOLS",
    "CHUNK_RESOURCE_URI_SCHEME",
    "CITE_NEIGHBORS",
    "FIND_EQUATION",
    "FIND_LEMMA_BY_NAME",
    "GET_CHUNK",
    "GET_DEFINITIONS",
    "GET_PAPER",
    "ResourcesNotReadyError",
    "SEARCH_PAPERS",
    "TOOL_SCHEMA_VERSION",
    "ToolMeta",
    "enforce_byte_cap",
    "envelope",
    "get_resources",
    "register_all",
    "reset_resources_for_tests",
    "set_resources",
]
