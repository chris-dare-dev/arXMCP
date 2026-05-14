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
TOOL_SCHEMA_VERSION: int = 5

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
        "hybrid path lands in E07. WARNING: v1 indexes statement chunks "
        "only — proof chunks are not retrievable until E07's dual-column "
        "RRF lands. The result envelope's retrieval_mode and "
        "excluded_kinds fields document the active mode."
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
        "Search for equations similar to the supplied LaTeX or MathML. "
        "MathML inputs (detected by a <math> root) route through the "
        "Zhang-Shasha tree-edit-distance + dense-cosine fusion path; "
        "the final score is alpha * (1 - normalized_ted) + (1 - alpha) "
        "* cosine, with alpha tunable via ARXMCP_EQ_TED_WEIGHT (default "
        "0.5). The dense signal is the equations table's embedding_eq "
        "column when populated (retrieval_mode='ted_fused_eq'); it "
        "falls back to the chunks table's embedding_stmt as a proxy "
        "when embedding_eq is all-NULL (retrieval_mode='ted_fused') for "
        "backward compatibility with pre-E10_S03b corpora. LaTeX inputs "
        "fall back to dense-only ANN over the chunks table's statement "
        "embeddings (retrieval_mode='dense_only_stmt_fallback') because "
        "there is no query-time LaTeXML pool. When the equations table "
        "is missing entirely, MathML inputs degrade to "
        "retrieval_mode='dense_only_fallback'. The retrieval_mode field "
        "always documents the active path."
    ),
)

GET_DEFINITIONS = ToolMeta(
    name="get_definitions",
    description=(
        "Return the per-paper notation/definition table for the given "
        "paper_id. With term: lookup hierarchy is exact match on "
        "symbol, then exact match on symbol_raw (author's form), then "
        "case-insensitive prefix match on symbol_raw. Without term: "
        "returns the full table sorted by symbol, paginated at 100 "
        "entries per page with an opaque next_cursor token. Source: "
        "the LanceDB definitions table populated at ingest time from "
        "preamble \\newcommand/\\renewcommand/\\providecommand/"
        "\\DeclareMathOperator/\\def/\\let directives (E10_S01). "
        "Absorbs the planned expand_macro tool; macro resolution is "
        "available via term lookup."
    ),
)

FIND_LEMMA_BY_NAME = ToolMeta(
    name="find_lemma_by_name",
    description=(
        "Find theorems/lemmas/propositions by their natural-language "
        "name. Three-step lookup against the SQLite FTS5 theorem-names "
        "index (E10_S02): (1) exact match on the normalized form "
        "(retrieval_mode='fts5_exact'), (2) FTS5 trigram substring "
        "match (retrieval_mode='fts5_trigram'), (3) Python-side "
        "trigram Jaccard fallback for typo-tolerant lookup "
        "(retrieval_mode='fuzzy_jaccard'). The optional paper_id "
        "argument restricts results to one paper. The response "
        "carries dedup_key, display_name, paper_id, chunk_id, "
        "section_path, and confidence per match. When the theorem-"
        "names index is absent, the handler falls back to an "
        "in-memory scan over chunks (retrieval_mode="
        "'in_memory_scan_fallback')."
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


#: Effective cap multiplier applied at measure time. Closes F4 from
#: the E06_S03 critique: the wire ``CallToolResult`` carries the
#: structured payload AS WELL AS a ``content[0].text`` block with a
#: pretty-printed (indent=2) repeat of the same dict; the actual
#: wire bytes are roughly 2× the inner JSON. Multiplying the inner
#: measurement by 2 guarantees the wire bytes stay under the
#: operator-configured cap.
_WIRE_OVERHEAD_FACTOR = 2


def enforce_byte_cap(
    structured_content: dict[str, Any],
    chunk_id: str | None = None,
    body_text_path: tuple[str, ...] = ("body_text",),
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Enforce the per-tool body-size cap (synthesis D9).

    Returns a 2-tuple of ``(structured_content, content_blocks)``.
    On the happy path (under cap), ``content_blocks`` is empty.

    When the serialized payload exceeds
    :attr:`Config.result_byte_cap` (after applying the
    :data:`_WIRE_OVERHEAD_FACTOR` correction for the wire envelope),
    the content_blocks list carries a ``resource_link`` block
    pointing at the chunk's URI so the agent can follow the link
    for the full body. The body at ``body_text_path`` (default
    top-level ``"body_text"``) is replaced with a 1024-char
    truncation, and ``body_truncated=True`` is flipped at the top
    level.

    Closes F1 from the E06_S03 critique: the original
    implementation only checked the top-level ``"body_text"`` key;
    handlers that nest the body under a sub-dict (like
    ``get_chunk``'s ``payload["chunk"]["body_text"]``) silently
    bypassed the cap. The ``body_text_path`` parameter lets each
    handler tell the helper where the body actually lives.

    Closes F4 from the E06_S03 critique: the cap measurement now
    accounts for the wire envelope's roughly-2× overhead.
    """
    serialized = json.dumps(structured_content, ensure_ascii=False, sort_keys=True)
    cap = get_resources().config.result_byte_cap
    if len(serialized.encode("utf-8")) * _WIRE_OVERHEAD_FACTOR <= cap:
        return structured_content, []

    # Over cap. Truncate body_text at body_text_path; surface
    # resource_link.
    truncated = json.loads(json.dumps(structured_content))  # deep copy
    _truncate_at_path(truncated, body_text_path)
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


def _truncate_at_path(d: dict[str, Any], path: tuple[str, ...]) -> None:
    """Walk ``d`` along ``path`` and truncate the leaf string to
    1024 chars in place. Silent no-op if any intermediate key is
    missing or the leaf is not a string."""
    cur: Any = d
    for key in path[:-1]:
        if not isinstance(cur, dict) or key not in cur:
            return
        cur = cur[key]
    leaf = path[-1]
    if isinstance(cur, dict) and isinstance(cur.get(leaf), str):
        cur[leaf] = cur[leaf][:1024]


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
