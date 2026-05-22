"""``search_papers`` handler — dense-only ANN over BGE-M3 embeddings.

v1 ships dense-only retrieval over the ``embedding_stmt`` column
of the chunks table. The hybrid BM25 + RRF + reranker pipeline
lands in E07 (Sonnet B); the wire-level tool contract does not
change when E07 ships — only the internal retrieval mode.

Aggregation per ``level``:
- ``level="theorem"`` (default): one row per chunk.
- ``level="section"``: dedup by ``(paper_id, section_path[0])``,
  keep the highest-score chunk per section.
- ``level="paper"``: dedup by ``paper_id``, keep the highest-score
  chunk per paper.

Sort: ``(score_desc, chunk_id_asc)`` per the determinism contract.

**Snippet contract (E06_S04).** ``snippet`` is the first
:data:`SNIPPET_MAX_CHARS` (=150) characters of the chunk's
canonical body text (column ``body_text`` in the LanceDB chunks
table; conceptually ``body_canonical`` per design note 04). NO
LLM rewriting, NO ellipsis beyond the character cap. The
``summary`` field documented in earlier notes drafts is
permanently dropped (would duplicate snippet, requires Haiku call
that breaks BP1 byte-stability when prompt versions change).

**`resource_link` content blocks (E06_S04).** Per the MCP 2025-06-18
spec's ``CallToolResult.content`` array semantics, this handler
returns BOTH a ``structuredContent`` (machine-readable, the dict
envelope) AND a ``content`` array carrying:

1. ``content[0]``: ``TextContent`` with the JSON-pretty-print of
   structuredContent. Keeps the FastMCP default surface for
   clients that read only ``content[0].text``.
2. ``content[1..N]``: one ``ResourceLink`` block per result row,
   in the same ``(score_desc, chunk_id_asc)`` order, with
   ``uri = "arxmcp://chunks/<chunk_id>"``. The MCP spec permits
   resource_link blocks in tool results; spec-compliant clients
   may follow the link to fetch the chunk.

**Note on body-size cap.** ``search_papers`` enforces the 256 KB
``server.tools.enforce_byte_cap`` (E13_S04b — closes Threat 4
partial-coverage gap G1; GitHub issue #1). The result is bounded
by ``k`` (max 50) × per-row size (snippet ≤150 chars + small
fields), so the cap is a no-op today; the call is defensive for
future reranker output expansion, section-level dedup, or
content-block payload growth. Multi-result tools pass
``chunk_id=None`` to the helper — the cap-overflow surface is
the response envelope, not a single chunk; agents follow the
per-row ``chunk_id`` field in ``results[]`` via ``get_chunk``.

The resource_link blocks are advisory — the agent runtime (E08)
does NOT rely on the client following them. Agents that ignore
them call :func:`server.handlers.chunk.handle_get_chunk` to
materialize a full body. Citations API integration is explicitly
NOT a dependency (Citations API validates document blocks in the
messages array, not MCP tool results — see
``docs/snippet-contract.md``).
"""

from __future__ import annotations

import json
from typing import Annotated, Any, Literal

from mcp.types import CallToolResult, ResourceLink, TextContent
from pydantic import AnyUrl, Field

from ingest.identifiers import is_valid_paper_id
from server.cache import get_cache
from server.observability.sanitize import sanitize_retrieved_text
from server.query_encoder import encode_query, encode_query_with_fallback
from server.tools import (
    CHUNK_RESOURCE_URI_SCHEME,
    cap_result_list,
    envelope,
    get_resources,
    wrap_retrieved_text,
)

#: Hard upper bound on per-tool ``k``. Mirrors the design note's
#: per-tool argument validation rule (k in [1, 50]).
MAX_K = 50

#: Snippet truncation length. E06_S04 will formalize this in a
#: dedicated schema file; the value is pinned here for the v1
#: result shape.
SNIPPET_MAX_CHARS = 150

#: Hard upper bound on the number of items in the ``filters`` dict
#: (E13_S04 Threat 4 resource-exhaustion defense). Enforced via
#: handler-body validation rather than Pydantic
#: ``Field(max_length=...)`` so the constraint does NOT bump the
#: rendered tool schema and trigger ``EXPECTED_TOOL_SCHEMA_SHA256``
#: re-pin per ``.claude/notes/07-multi-agent-caching.md`` BP1
#: byte-stability discipline. The security goal is identical:
#: oversized filter dicts are rejected before any meaningful
#: processing.
MAX_FILTER_ITEMS = 100

#: Hard upper bound on the length of the ``filters["paper_id"]`` list
#: (proof-verify-handler-wiring-m1; FM-4 from the m1 synthesis). The
#: ``MAX_FILTER_ITEMS`` cap above is on the COUNT OF KEYS in the
#: filters dict — a single key ``paper_id`` with a 10K-element list
#: would pass that gate and stress LanceDB's predicate parser with a
#: ~120 KB IN clause. 100 matches the roadmap's design target
#: ("~100 paper_ids per call comfortably"). Enforced in handler body
#: for the same BP1 byte-stability reason as ``MAX_FILTER_ITEMS``.
MAX_PAPER_ID_FILTER_ITEMS = 100

#: Hard upper bound on the length of any KEY in the ``filters`` dict
#: (F2 closure from the m1 critique). The ``filter_warnings`` block
#: reflects unrecognized keys verbatim via ``repr()``; without a
#: per-key length cap, an LLM passing 100 keys of 100 KB each could
#: produce a ~10 MB ``filter_warnings`` payload that bypasses the
#: ``cap_result_list`` byte cap (which only trims ``results[]``).
#: 64 chars is generous for any plausible filter key name.
MAX_FILTER_KEY_LEN = 64


def _escape_paper_id_literal(s: str) -> str:
    """Escape single quotes for LanceDB SQL-style WHERE clauses.

    LanceDB does not accept bound parameters for predicates today
    (``ingest/index_definitions.py:404-405``); manual escape is the
    only option. SQL standard: double the single-quote.

    Defense-in-depth: ``is_valid_paper_id`` regex (called BEFORE this
    function) structurally rejects any string containing a single
    quote. This escape is the belt-and-braces secondary layer per
    the m1 synthesis FM-1 mitigation.
    """
    return s.replace("'", "''")


def _build_paper_id_predicate(paper_id_value: Any) -> str:
    """Build a LanceDB ``paper_id IN ('a','b',...)`` predicate.

    Accepts both a single ``str`` (coerced to a one-element list,
    matching ``server.retrieval.bm25._apply_supported_filters`` at
    lines 683-687) and a ``list[str]``.

    Validates:
    - non-empty list (FM-2: empty list raises rather than silently
      becoming a no-op).
    - length <= ``MAX_PAPER_ID_FILTER_ITEMS`` (FM-4: resource cap).
    - every element passes ``ingest.identifiers.is_valid_paper_id``
      (FM-5: malformed IDs raise rather than partial-filter silently).

    Then escapes single quotes (FM-1 defense-in-depth) and joins
    sorted IDs into the predicate string. Sorting makes the predicate
    deterministic — useful for any caller that hashes the predicate
    (the Tier-1/Tier-2 cache already hashes the ``filters`` dict
    upstream via ``server.cache.canonical_key_components``).
    """
    if isinstance(paper_id_value, str):
        paper_ids: list[str] = [paper_id_value]
    elif isinstance(paper_id_value, list):
        paper_ids = paper_id_value
    else:
        raise ValueError(
            f"filters['paper_id'] must be str or list[str], got "
            f"{type(paper_id_value).__name__}"
        )
    if not paper_ids:
        raise ValueError(
            "filters['paper_id'] must not be empty; use filters=None "
            "(or omit the filters arg entirely) to request no filter"
        )
    if len(paper_ids) > MAX_PAPER_ID_FILTER_ITEMS:
        raise ValueError(
            f"filters['paper_id'] has {len(paper_ids)} items; max "
            f"allowed is {MAX_PAPER_ID_FILTER_ITEMS} (m1 FM-4 "
            f"resource-exhaustion cap)"
        )
    invalid = [pid for pid in paper_ids if not is_valid_paper_id(pid)]
    if invalid:
        raise ValueError(
            f"filters['paper_id'] contains {len(invalid)} invalid "
            f"arXiv IDs; first invalid: {invalid[0]!r}"
        )
    ids_csv = ",".join(
        f"'{_escape_paper_id_literal(pid)}'" for pid in sorted(paper_ids)
    )
    return f"paper_id IN ({ids_csv})"


#: Filter keys this handler recognizes today. Currently only
#: ``paper_id`` is honored (m1). Other keys (``categories``,
#: ``year_min``, etc.) are deferred to a future milestone and will
#: surface in ``filter_warnings``. Mirrors
#: ``server.retrieval.bm25.SUPPORTED_FILTER_KEYS``.
SUPPORTED_FILTER_KEYS: frozenset[str] = frozenset({"paper_id"})


def _inject_filters_applied(
    payload: dict[str, Any],
    canonical_filters: dict[str, Any] | None,
) -> dict[str, Any]:
    """m2: add ``filters_applied`` echo to the payload if any
    SUPPORTED_FILTER_KEYS were honored.

    Returns a shallow-copied dict with the field added; never mutates
    the input. This is load-bearing for the F2 strip-then-re-add
    invariant — the miss path stamps AFTER ``cache.store_search``, so
    if the helper mutated in place the cached reference would
    silently inherit the caller-specific echo (which is what F1's
    `test_cached_payload_omits_filters_applied` regression-guards).

    **Absent**, not null, when no filter was applied — preserves
    byte-equivalence with pre-m2 responses on the common unfiltered
    path. JSON-Schema draft-07 ``additionalProperties: false`` +
    field declared in ``properties`` but NOT in ``required``
    cleanly supports absent-or-present semantics.

    **Canonical form**, not original caller form. The value matches
    what was actually used to scope the LanceDB query (see
    ``_canonicalize_filters`` + ``_build_paper_id_predicate``).

    **SUPPORTED_FILTER_KEYS subset only.** Unrecognized keys appear
    in ``filter_warnings``, not here. ``filters_applied`` and
    ``filter_warnings`` are two non-overlapping views of the
    filter input — applied vs ignored.

    Called on all three cache paths (Tier-1 hit, Tier-2 hit, miss)
    so cached payloads — which do NOT carry caller-specific
    metadata — get the field stamped post-hit, paralleling the
    ``_restamp_degraded`` pattern. The miss path stamps AFTER
    ``cache.store_search`` (so the cached value stays filter-agnostic);
    the two hit paths stamp after ``_restamp_degraded``, which itself
    pops any stale ``filters_applied`` defensively (m2 rect F2).
    """
    if canonical_filters is None:
        return payload
    applied = {
        k: canonical_filters[k]
        for k in SUPPORTED_FILTER_KEYS
        if k in canonical_filters
    }
    if not applied:
        return payload
    return {**payload, "filters_applied": applied}


def _canonicalize_filters(
    filters: dict[str, Any] | None,
) -> dict[str, Any] | None:
    """Normalize semantically-identical filter inputs so the cache
    sees a stable key.

    F4 closure from m1 critique: callers may supply
    ``{"paper_id": "x"}`` or ``{"paper_id": ["x"]}`` interchangeably
    (the helper coerces both to the same predicate). Without
    normalization upstream of the cache lookup, the two forms hash
    differently — semantically-equivalent calls produce cache misses.

    Normalizations applied:
    1. ``str`` paper_id value → one-element ``list``.
    2. ``list`` paper_id values are sorted and **deduplicated**
       (deterministic order; m2 rect F5 — semantically-equivalent
       inputs like ``["a","a","b"]`` and ``["a","b"]`` must share a
       cache key and produce an identical ``filters_applied`` echo).
       ``dict.fromkeys`` preserves first-occurrence semantics for the
       implicit order before ``sorted`` re-orders.

    Returns ``None`` unchanged when filters is None.
    """
    if filters is None:
        return None
    out: dict[str, Any] = dict(filters)
    pid = out.get("paper_id")
    if isinstance(pid, str):
        out["paper_id"] = [pid]
    elif isinstance(pid, list):
        out["paper_id"] = sorted(dict.fromkeys(pid))
    return out


async def handle_search_papers(
    query: Annotated[
        str, Field(min_length=1, max_length=2000, description="Natural-language query")
    ],
    level: Annotated[
        Literal["paper", "section", "theorem"],
        Field(description="Aggregation level for results"),
    ] = "theorem",
    k: Annotated[int, Field(ge=1, le=MAX_K, description="Top-k cutoff")] = 10,
    filters: Annotated[
        dict[str, Any] | None,
        Field(
            description=(
                "Optional filters. Honors 'paper_id' as a str or "
                "list[str] (up to 100 items, each validated against "
                "the arXiv paper_id format); other keys are ignored "
                "and surface in 'filter_warnings'."
            ),
        ),
    ] = None,
    cursor: Annotated[
        str | None,
        Field(description="Reserved for E07_S04 pagination; ignored at v1"),
    ] = None,
) -> dict[str, Any]:
    """Search the corpus and return ranked chunk results.

    Honors ``filters={"paper_id": [...]}`` end-to-end via a LanceDB
    ``.where("paper_id IN (...)", prefilter=True)`` predicate threaded
    into the ANN call (proof-verify-handler-wiring-m1). The ``paper_id``
    value may be a single string or a list of strings, capped at
    ``MAX_PAPER_ID_FILTER_ITEMS`` items, with each element validated
    against ``ingest.identifiers.is_valid_paper_id``. Other filter
    keys (``categories``, ``year_min``, etc.) are still ignored and
    surface in ``filter_warnings``.

    ``cursor`` is still deferred to a future milestone.
    """
    # E13_S04 (Threat 4): handler-body cap on filter dict size.
    # An adversary or runaway LLM might pass `filters={"a": 1, ...}`
    # with thousands of entries to inflate memory before the v1
    # processing even fires. Pydantic ``Field(max_length=...)`` on
    # the dict would bump the tool schema hash; handler-body
    # validation is identical for the security goal without
    # invalidating BP1 prompt-cache discipline.
    if filters is not None and len(filters) > MAX_FILTER_ITEMS:
        raise ValueError(
            f"filters has {len(filters)} items; max allowed is "
            f"{MAX_FILTER_ITEMS} (E13_S04 Threat 4 resource-exhaustion cap)"
        )

    # F2 (HIGH) closure from m1 critique: per-key length cap. Without
    # this, an LLM passing 100 keys of 100 KB each would cause the
    # filter_warnings reflection block below to emit ~10 MB of
    # warning strings (cap_result_list trims results[] only). Reject
    # oversized keys at the boundary before any further processing.
    if filters is not None:
        for key in filters:
            if not isinstance(key, str):
                raise ValueError(
                    f"filters keys must be strings, got "
                    f"{type(key).__name__}"
                )
            if len(key) > MAX_FILTER_KEY_LEN:
                raise ValueError(
                    f"filter key length {len(key)} exceeds cap of "
                    f"{MAX_FILTER_KEY_LEN} (m1 F2 byte-cap-bypass "
                    f"defense; cap_result_list trims results[] only, "
                    f"so reflected keys must be bounded at the "
                    f"boundary)"
                )

    # m1: honor filters={"paper_id": [...]} end-to-end. Build the
    # LanceDB IN-predicate up front so input validation errors raise
    # cleanly (AC #3: clear error, not 500) BEFORE any cache lookup
    # or query encoding. Unknown filter keys (e.g. "year") will be
    # surfaced as warnings in the result envelope below.
    paper_id_predicate: str | None = None
    if filters and "paper_id" in filters:
        paper_id_predicate = _build_paper_id_predicate(filters["paper_id"])

    # F4 closure from m1 critique: canonicalize the filters dict
    # BEFORE the cache lookup so semantically-identical inputs
    # (str vs one-element list, unsorted vs sorted) hash to the
    # same Tier-1/Tier-2 cache key. Use the canonicalized form
    # for ALL cache touchpoints below; the original `filters` is
    # preserved for the filter_warnings reflection block (which
    # reports keys in the order the caller supplied).
    canonical_filters = _canonicalize_filters(filters)

    r = get_resources()

    # E08_S03: 3-tier cache lookup BEFORE the encode + ANN path.
    # Tier 1 is checked first (no embedding required); Tier 2 needs
    # the query embedding, so we defer it until after the encode.
    # ``level`` is threaded through the cache key so different
    # aggregation levels get distinct cache entries (correctness).
    # E14_S02 — pull the OTel cache-layer setter so each tier hit
    # surfaces on the parent span's ``arxmcp.cache_layer_served``
    # attribute. NoOpTracer fast-path when tracing is disabled.
    from server.observability.tracing import (  # noqa: PLC0415
        set_cache_layer,
        span_ann,
    )

    # F1 rectification (E14_S05 adversary critique): compute the
    # degraded-state of the SERVER ONCE up front. The cache hits
    # below re-stamp the cached payload with the current
    # ``degraded`` state so a response served from a degraded
    # process is never silently mis-tagged. The cache key is
    # corpus_version + query; it intentionally does NOT include
    # the degraded axis (that would balloon the key space across
    # recovery transitions and re-warm cost on flap).
    base_degraded_reasons: list[str] = []
    if r.degraded is not None:
        base_degraded_reasons.append(r.degraded.reason)

    cache = get_cache()
    if cache is not None:
        cached_payload, _hit_tier = await cache.lookup_search(
            query=query, filters=canonical_filters, k=k, level=level,
        )
        if cached_payload is not None:
            # Tier-1 hit — bypass Phase 1/2/3.
            set_cache_layer("tier1")
            structured = _restamp_degraded(cached_payload, base_degraded_reasons)
            # m2: stamp filters_applied post-cache (caller-specific
            # metadata; never stored in cached payload).
            structured = _inject_filters_applied(structured, canonical_filters)
            rows = structured.get("results", [])
            structured = _cap(structured)
            content = _build_content_blocks(structured, rows)
            return CallToolResult(content=content, structuredContent=structured)

    # Encode query (singleflight + semaphore — two-tier concurrency).
    # E14_S05 D6: route via the hosted-embedder fallback wrapper
    # only when a non-local provider is configured. The default
    # ``local`` path calls ``encode_query`` directly so existing
    # tests that monkeypatch ``server.handlers.search.encode_query``
    # to fake out the embed call continue to work (the fallback
    # wrapper resolves through server.query_encoder's own binding,
    # which the test fixtures don't patch).
    embed_fallback_active = False
    async with r.embed_semaphore:
        if r.config.query_embed_provider == "local":
            query_vec = await encode_query(query)
        else:
            query_vec, embed_fallback_active = await encode_query_with_fallback(
                query, r.config.query_embed_provider
            )

    # Tier-2 lookup with the freshly-computed embedding.
    if cache is not None:
        cached_payload, _hit_tier = await cache.lookup_search(
            query=query, filters=canonical_filters, k=k,
            query_embedding=query_vec, level=level,
        )
        if cached_payload is not None:
            set_cache_layer("tier2")
            # Build the reason list including any hosted-embedder
            # fallback that fired during THIS request (not present
            # in the cached payload). F1 rectification.
            tier2_reasons = list(base_degraded_reasons)
            if embed_fallback_active:
                tier2_reasons.append("hosted_embedder_outage")
            structured = _restamp_degraded(cached_payload, tier2_reasons)
            # m2: stamp filters_applied post-cache (caller-specific
            # metadata; never stored in cached payload).
            structured = _inject_filters_applied(structured, canonical_filters)
            rows = structured.get("results", [])
            structured = _cap(structured)
            content = _build_content_blocks(structured, rows)
            return CallToolResult(content=content, structuredContent=structured)

    # Dense ANN over embedding_stmt only. embedding_proof is for
    # proof bodies; mixing without RRF would produce inconsistent
    # rankings (E07 is the right venue for dual-column fusion).
    #
    # m1: when a paper_id filter is supplied, chain `.where(predicate,
    # prefilter=True)` between `.search()` and `.limit()`. `prefilter
    # =True` matches the convention in `get_paper`, `get_chunk`, and
    # `ingest/intra_paper_refs.py:226`. It guarantees the ANN search
    # runs over the filtered sub-corpus, avoiding the postfilter
    # case where a small filter set could leave fewer than k results
    # after corpus-wide ANN candidates are discarded.
    with span_ann(k=k):
        search_q = r.chunks_table.search(
            query_vec, vector_column_name="embedding_stmt"
        )
        if paper_id_predicate is not None:
            search_q = search_q.where(paper_id_predicate, prefilter=True)
        arrow = (
            search_q
            .limit(k * 5 if level != "theorem" else k)  # over-fetch for dedup
            .to_arrow()
        )
    rows = _arrow_to_rows(arrow)

    # Aggregate per level.
    if level == "paper":
        rows = _dedup_keep_best(rows, key=lambda r: r["paper_id"])
    elif level == "section":
        rows = _dedup_keep_best(
            rows, key=lambda r: (r["paper_id"], _first_section(r["section_path"]))
        )

    # Sort: (score_desc, chunk_id_asc).
    rows.sort(key=lambda r: (-r["score"], r["chunk_id"]))
    rows = rows[:k]

    # F6: surface ignored filter/cursor warnings explicitly so the
    # agent runtime can detect partial support.
    #
    # m1: ``paper_id`` is now honored end-to-end. The blanket
    # "filters arg accepted but not yet processed" warning is gone.
    # Surface a per-key warning for any filter key NOT in
    # ``SUPPORTED_FILTER_KEYS`` (currently only ``paper_id``) so a
    # caller passing ``filters={"paper_id":[...], "year": 2024}``
    # knows the ``year`` key was silently ignored (FM-9).
    filter_warnings: list[str] = []
    if filters:
        unknown_keys = sorted(set(filters) - SUPPORTED_FILTER_KEYS)
        for key in unknown_keys:
            filter_warnings.append(
                f"filters[{key!r}] is not supported and was ignored "
                f"(deferred to a future milestone; supported keys: "
                f"{sorted(SUPPORTED_FILTER_KEYS)})"
            )
    if cursor is not None:
        filter_warnings.append(
            "cursor arg is accepted but pagination is deferred to E07_S04"
        )

    # E14_S05 D6: surface server-degradation state on every result.
    # ``degraded`` is the orchestrator-facing flag (True iff this
    # request hit any failure-mode fallback path). ``degraded_reason``
    # carries the cause slug — the orchestrator can deprioritize
    # cross-model hits or surface a warning to the operator.
    miss_degraded_reasons: list[str] = list(base_degraded_reasons)
    if embed_fallback_active:
        miss_degraded_reasons.append("hosted_embedder_outage")

    payload: dict[str, Any] = {
        "embed_model": "bge-m3",
        # F5: explicit warning about proof-chunk exclusion at v1.
        "excluded_kinds": ["proof"],
        "filter_warnings": filter_warnings,
        "next_cursor": None,    # v1: no pagination
        "results": rows,
        "retrieval_mode": "dense_only",
    }
    if miss_degraded_reasons:
        payload["degraded"] = True
        payload["degraded_reasons"] = miss_degraded_reasons
    structured = envelope(payload)

    # E08_S03: cache-store on the miss path. We pass the query
    # embedding so Tier 2 indexes it for future semantic-equivalent
    # queries. ``level`` MUST match the lookup key (correctness).
    #
    # m2 rect F2: store the FILTER-AGNOSTIC payload — i.e. WITHOUT
    # the caller-specific ``filters_applied`` echo. The stamp runs
    # post-store below, paralleling ``_restamp_degraded``'s
    # post-cache-hit re-application. This honors the helper's own
    # docstring claim ("never stored in cached payload") and matches
    # the strip-then-re-add pattern used for ``degraded`` (which
    # similarly is not part of the cache key axis).
    if cache is not None:
        await cache.store_search(
            query=query,
            filters=canonical_filters,
            k=k,
            payload=structured,
            query_embedding=query_vec,
            level=level,
        )

    # m2 rect F2: stamp filters_applied AFTER cache-store so the
    # cached value stays caller-agnostic. Wire-form byte stability is
    # preserved because ``_build_content_blocks`` re-serializes via
    # ``json.dumps(sort_keys=True)`` (see server/tools.py:458).
    structured = _inject_filters_applied(structured, canonical_filters)

    # E06_S04: assemble the wire ``content`` array — pretty-printed
    # JSON of structuredContent (the FastMCP default surface) +
    # one ResourceLink per result row. E13_S04b: cap the structured
    # payload (defensive; closes Threat 4 partial-coverage gap G1).
    structured = _cap(structured)
    content = _build_content_blocks(structured, rows)
    return CallToolResult(content=content, structuredContent=structured)


def _restamp_degraded(
    cached_payload: dict[str, Any], current_reasons: list[str]
) -> dict[str, Any]:
    """Re-stamp the cached response with the CURRENT server's
    degraded state. F1 rectification (E14_S05 adversary critique).

    The cache key is corpus_version + query and does NOT include
    the server-degraded axis. A payload cached while the server
    was healthy could be served while the server is degraded
    (e.g. corpus_corruption fallback active) and vice versa. The
    orchestrator-facing contract is that ``degraded`` reflects
    the SERVER STATE at response time, not at cache-write time.

    Returns a shallow-copied dict with ``degraded`` /
    ``degraded_reasons`` set or removed to match
    ``current_reasons``. The ``results`` list (the load-bearing
    cached data) is preserved by reference — no deep copy needed.
    """
    structured = dict(cached_payload)
    # Remove any stale degraded markers from the cached payload.
    structured.pop("degraded", None)
    structured.pop("degraded_reasons", None)
    # m2 rect F2: strip any cached ``filters_applied`` too. The miss
    # path now omits this field from the cached payload (so the
    # cached value is filter-agnostic per the helper's docstring),
    # but defensively pop here in case a payload was cached by an
    # older code path before the post-cache-stamp move landed.
    structured.pop("filters_applied", None)
    if current_reasons:
        structured["degraded"] = True
        structured["degraded_reasons"] = list(current_reasons)
    return structured


def _cap(structured: dict[str, Any]) -> dict[str, Any]:
    """E13_S04b — apply the 256 KB result byte cap to the
    ``results[]`` aggregate.

    A no-op today (50 rows × 150-char snippet + small metadata is
    well under the cap by construction) but defensive against
    future reranker output expansion, ``level="section"`` or
    ``level="paper"`` dedup, and content-block payload growth.

    Uses :func:`server.tools.cap_result_list` with
    ``list_key="results"`` (post-F1 rectification): when the cap
    fires, the LOWEST-relevance trailing rows are trimmed until
    the wire size fits — agents still receive the highest-scoring
    rows with full fidelity. ``body_truncated=True`` is set so
    consumers detect the truncation.

    ``chunk_id=None`` because the cap-overflow surface for a
    multi-result aggregate is the response envelope, not a single
    chunk: agents follow the per-row ``chunk_id`` field in
    ``results[]`` to fetch full bodies via
    :func:`server.handlers.chunk.handle_get_chunk`.
    """
    structured, _blocks = cap_result_list(structured, list_key="results")
    return structured


def _build_content_blocks(
    structured: dict[str, Any], rows: list[dict[str, Any]]
) -> list[Any]:
    """Build the ``content`` array per the E06_S04 contract.

    Block 0 is a TextContent carrying ``json.dumps(structured,
    indent=2, sort_keys=True)`` — same shape FastMCP's default
    dict-handler emits, so clients that only read
    ``content[0].text`` see the full payload.

    Blocks 1..N are ResourceLink blocks in the same order as
    ``rows`` (which is already sorted ``(score_desc,
    chunk_id_asc)``). Each link's URI is
    ``arxmcp://chunks/<chunk_id>`` per the design note's resource
    URI scheme.

    Note: ``search_papers`` does NOT call ``enforce_byte_cap``
    (only ``get_chunk`` does at v1). When a future milestone
    wires cap enforcement here, the per-row ResourceLink overhead
    must be added to the wire-overhead factor calibration in
    ``server/tools.py``.
    """
    blocks: list[Any] = [
        TextContent(
            type="text",
            text=json.dumps(structured, indent=2, sort_keys=True, ensure_ascii=False),
        )
    ]
    for row in rows:
        cid = row["chunk_id"]
        blocks.append(
            ResourceLink(
                type="resource_link",
                uri=AnyUrl(f"{CHUNK_RESOURCE_URI_SCHEME}{cid}"),
                name=cid,
            )
        )
    return blocks


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _arrow_to_rows(arrow) -> list[dict[str, Any]]:  # noqa: ANN001
    """Convert a LanceDB Arrow result to per-row dicts with the v1
    result fields. ``score = 1 - _distance / 2`` for L2-normalized
    BGE-M3 vectors yields cosine similarity in [0, 1]."""
    cids = arrow.column("chunk_id").to_pylist()
    paper_ids = arrow.column("paper_id").to_pylist()
    section_paths = arrow.column("section_path").to_pylist()
    theorem_names = arrow.column("theorem_name").to_pylist()
    theorem_labels = arrow.column("theorem_label").to_pylist()
    body_texts = arrow.column("body_text").to_pylist()
    distances = arrow.column("_distance").to_pylist()
    rows = []
    for cid, pid, sp, tn, tl, bt, dist in zip(
        cids, paper_ids, section_paths, theorem_names, theorem_labels, body_texts,
        distances, strict=True,
    ):
        if cid is None:
            continue
        # F7 fix from the E06_S03 critique: dropped the
        # hardcoded ``version: 1`` field. The chunks schema has no
        # paper-version column; the prior code emitted a literal
        # ``1`` regardless of the paper's actual arXiv version
        # (``v1``, ``v2``, ...) which is misinformation. The
        # paper_id may carry the version suffix; agents that need
        # it parse it from there.
        rows.append(
            {
                "chunk_id": cid,
                "label": _format_label(tn, tl),
                "paper_id": pid,
                "score": _distance_to_score(dist),
                "section_path": list(sp) if sp is not None else [],
                "snippet": _snippet(bt),
            }
        )
    return rows


def _format_label(theorem_name: str | None, theorem_label: str | None) -> str:
    """Build the ``label`` field per design note (e.g.
    ``"Theorem 3.4"``). Returns empty string when both are None."""
    parts = [s for s in (theorem_name, theorem_label) if s]
    return " ".join(parts)


def _snippet(body_text: str | None) -> str:
    """Take the first :data:`SNIPPET_MAX_CHARS` characters of
    ``body_text`` and wrap in ``<retrieved_chunk>`` delimiters.

    E13_S02 (Threat 2) — every emitted snippet is wrapped in
    ``<retrieved_chunk>...</retrieved_chunk>`` after running the
    optional sanitizer. The wrapper applies escape-on-emit (FM-1)
    so adversarial paper content containing the literal close tag
    cannot terminate the wrapper prematurely.

    Order: sanitize raw body_text → truncate to SNIPPET_MAX_CHARS →
    wrap. Truncation runs on the sanitized text so the 150-char
    contract counts visible chars (post-sanitize), not stripped
    injection bytes. The wrap is applied AFTER truncation so the
    delimiter tags are not truncated inside the SNIPPET_MAX_CHARS
    budget (the wrapper adds ~32 chars of overhead).

    E06_S04 freezes the 150-char *content* contract; the delimiter
    overhead is independent of that contract and not part of the
    150-char budget.
    """
    if not body_text:
        return ""
    sanitized = sanitize_retrieved_text(body_text)
    truncated = sanitized[:SNIPPET_MAX_CHARS]
    return wrap_retrieved_text(truncated, kind="chunk")


def _distance_to_score(dist: float | None) -> float:
    """LanceDB squared-L2 distance → cosine similarity in [0, 1].

    LanceDB returns *squared* L2 distance on ``_distance`` for the
    L2 metric (verified empirically — see the rectification note in
    :func:`server.retrieval.ann._distance_to_score`). For unit
    vectors ``||a-b||² = 2 - 2·cos(a, b)``, so ``cos = 1 - dist/2``
    is the correct conversion. Do NOT "fix" to ``1 - sqrt(dist)/2``
    — that would silently break ranking quality."""
    if dist is None:
        return 0.0
    return max(0.0, 1.0 - float(dist) / 2.0)


def _first_section(section_path: list[str] | None) -> str:
    if not section_path:
        return ""
    return section_path[0]


def _dedup_keep_best(
    rows: list[dict[str, Any]], key
) -> list[dict[str, Any]]:
    """Group by ``key(row)``; keep the row with the highest score
    in each group. Stable order across runs because LanceDB
    returns deterministic search order."""
    best: dict[Any, dict[str, Any]] = {}
    for r in rows:
        k = key(r)
        if k not in best or r["score"] > best[k]["score"]:
            best[k] = r
    return list(best.values())


