"""``get_chunk`` handler — direct LanceDB lookup by chunk_id.

The body-size cap (E06_S01 ``BodySizeCapMiddleware`` exempts
``/mcp``) is enforced per-handler via :func:`server.tools.enforce_byte_cap`
— a chunk whose JSON-serialized form exceeds
``Config.result_byte_cap`` (default 256 KB) is returned with
``body_truncated=True`` and a ``resource_link`` to
``arxmcp://chunks/<chunk_id>`` in the ``content`` array.

``include_referenced`` resolves statement <-> proof linkage as of
retrieval-unlocks-m1 — see :mod:`server.proof_linkage` for the
``(paper_id, theorem_label, kind)`` join, the uniqueness-gated
section-scope fallback, and the four epistemic outcomes it can report.

**Batch fetch (agent-platform-t-batch-chunk-fetch, #83):** ``chunk_id``
accepts either a scalar id (flat single-chunk envelope, unchanged v1
contract) or a list of up to :data:`MAX_BATCH_CHUNK_IDS` ids, which
returns ``{chunks: [...]}`` in request order — one round-trip for N ids.
The per-session cap counts a batch by its id count, not as one call (see
``server.session.check_both_caps`` / ``SessionCapMiddleware``).

**Inert arg removed (agent-platform-t-inert-args-cleanup, #82):** the
former ``include_equations`` (accepted-and-ignored since v1, equation
atoms never built) is gone from the input schema rather than left as a
lie. ``unused_args`` / ``include_equations_applied`` went with it — get_chunk
has no accepted-and-ignored argument left.
"""

from __future__ import annotations

from typing import Annotated, Any

from pydantic import Field

from ingest.identifiers import is_valid_chunk_id
from server.observability.sanitize import sanitize_retrieved_text
from server.proof_linkage import resolve_referenced
from server.tools import (
    enforce_byte_cap,
    envelope,
    get_resources,
    wrap_retrieved_text,
)

#: agent-platform-t-batch-chunk-fetch (#83): max chunk_ids in one
#: batched call. Enforced in the handler body — NOT as a Pydantic Field
#: constraint — so the bound never perturbs the tools/list inputSchema
#: hash (mirrors search_papers' MAX_PAPER_ID_FILTER_ITEMS discipline).
MAX_BATCH_CHUNK_IDS = 20


async def handle_get_chunk(
    chunk_id: Annotated[
        str | list[str],
        Field(
            description=(
                "A content-addressable chunk_id, OR a list of up to 20 "
                "of them for one batched fetch."
            )
        ),
    ],
    include_referenced: Annotated[
        bool,
        Field(
            description=(
                "Resolve this chunk's statement/proof counterpart(s): a "
                "theorem-like chunk returns its proof window(s), a proof "
                "returns its originating statement. See linkage.outcome "
                "for the result, including the abstention cases."
            )
        ),
    ] = False,
) -> dict[str, Any]:
    """Fetch one chunk by id, or a batch of up to 20.

    A scalar ``chunk_id`` returns the flat single-chunk envelope
    (``{chunk, found, ...}``) unchanged from the v1 contract. A list of
    ids returns ``{chunks: [<the same per-chunk object>, ...]}`` in
    request order — one entry per id, each carrying its own ``found``,
    byte-cap, and linkage — so N ids cost one round-trip instead of N.

    A malformed id raises a JSON-RPC error; a well-formed id absent from
    the corpus yields a per-chunk ``found: false`` (batch elements stay
    positionally aligned with the request so a caller can map a miss
    back to its id).
    """
    # Validate BEFORE touching Resources: a malformed / injection-shaped
    # id (or an over-cap batch) must be rejected without the handler ever
    # reaching the corpus — the security-test contract
    # (tests/security/test_path_traversal.py: the validator fires before
    # get_resources()).
    batch = isinstance(chunk_id, list)
    ids: list[str] = list(chunk_id) if batch else [chunk_id]

    if batch:
        if not ids:
            raise ValueError("chunk_id list must not be empty")
        if len(ids) > MAX_BATCH_CHUNK_IDS:
            raise ValueError(
                f"chunk_id list has {len(ids)} ids; max "
                f"{MAX_BATCH_CHUNK_IDS} per batched get_chunk call"
            )
    for cid in ids:
        if not is_valid_chunk_id(cid):
            raise ValueError(
                f"chunk_id {cid!r} does not match "
                f"arxiv:<paper_id>:<16-hex> format"
            )

    r = get_resources()
    row_map = _fetch_chunk_rows(r, ids)
    if not batch:
        return envelope(
            _build_chunk_result(ids[0], row_map.get(ids[0]), include_referenced, r)
        )
    # Per-element byte budget so the whole chunks[] array is bounded by
    # the per-response cap, not n independent copies of it. Each element
    # gets result_byte_cap // n; a chunk over its share is truncated to a
    # resource_link exactly as a scalar over-cap chunk is, so every
    # requested id is still returned.
    per_elem_cap = getattr(r.config, "result_byte_cap", 256 * 1024) // len(ids)
    return envelope({
        "chunks": [
            _build_chunk_result(
                cid, row_map.get(cid), include_referenced, r,
                byte_cap=per_elem_cap,
            )
            for cid in ids
        ]
    })


def _fetch_chunk_rows(r, ids: list[str]) -> dict[str, Any]:  # noqa: ANN001
    """One LanceDB lookup for all requested ids -> {chunk_id: row}.

    A single ``chunk_id IN (...)`` query serves both the scalar path
    (one id) and the batch path (up to 20), so a batch is one query.
    """
    ids_escaped = ", ".join(f"'{_escape_lance_str(c)}'" for c in ids)
    arrow = (
        r.chunks_table.search()
        .where(f"chunk_id IN ({ids_escaped})", prefilter=True)
        .limit(len(ids))
        .to_arrow()
    )
    return {row["chunk_id"]: row for row in _arrow_all_rows(arrow)}


def _build_chunk_result(
    chunk_id: str,
    row: dict[str, Any] | None,
    include_referenced: bool,
    r: Any,
    byte_cap: int | None = None,
) -> dict[str, Any]:
    """Build the per-chunk result object (used for both the scalar
    return and each batch element). ``row is None`` -> a ``found:false``
    object. Carries its own byte-cap / linkage / resource_link so a
    batch element is self-contained. ``byte_cap`` overrides the global
    per-response cap for a batch element (its share of the total); a
    ``found:false`` batch element also carries ``chunk_id`` so a miss is
    identifiable without positional bookkeeping."""
    if row is None:
        miss: dict[str, Any] = {
            "chunk": None,
            "found": False,
            "include_referenced_applied": False,
        }
        if byte_cap is not None:  # batch element -> self-describe the miss
            miss["chunk_id"] = chunk_id
        return miss
    # E13_S02 (Threat 2) — sanitize body_text BEFORE the byte-cap so the
    # 256 KB cap measures post-sanitize bytes. Wrapping is deferred until
    # AFTER the cap so the delimiter tags are not sliced off by the cap
    # path (which truncates ``body_text`` in-place when the structured
    # payload exceeds the cap).
    raw_body = row["body_text"] or ""
    sanitized_body = sanitize_retrieved_text(raw_body)
    # license-serving-removal-m1: the served corpus is never redistributed,
    # so licensing gates NO serving decision — get_chunk returns the FULL
    # sanitized body for every chunk regardless of its ``license`` token.
    # (The former textbook-ingest-m11 / e5 300-char non-OA truncation gate
    # was removed here.) The only remaining length safeguard is the
    # size-based 256 KB byte-cap + resource_link path below, which is
    # unrelated to license. The ``license`` token is still surfaced as
    # informational provenance, never as a serving control.
    license_token = row["license"] or ""
    chunk = {
        "body_text": sanitized_body,
        "chunk_id": row["chunk_id"],
        "chunker_version": row["chunker_version"],
        "embedder_version": row["embedder_version"],
        "kind": row["kind"],
        # Informational provenance only: the license token is surfaced so an
        # agent can see a chunk's license, but it never gates serving
        # (license-serving-removal-m1).
        "license": license_token,
        # source-truth-m5: the m2 per-revision license DECISION
        # (eligible / not-allowlisted-open / unknown) — ADVISORY /
        # informational only. No license value gates serving: the
        # owner-gated fail-closed cutover (source-truth-m4) was retired and
        # the truncation gate removed (license-serving-removal-m1).
        "license_ref": row.get("license_ref"),
        "paper_id": row["paper_id"],
        "preamble_ref": row["preamble_ref"],
        "printed_number": row.get("printed_number"),
        "section_path": list(row["section_path"]) if row["section_path"] else [],
        # source-truth-m5: revision-grained provenance from the m2 chunks
        # schema v2. Read via ``row.get`` (NOT ``row[...]``): the 2 live
        # ``-pdfs`` notebooks are still on the pre-m2 21-column schema, so
        # these columns are ABSENT from their Arrow rows and bracket-indexing
        # would 500. An explicit ``null`` is the correct AC1 surface for
        # BOTH an unmigrated notebook AND a hydrated-but-abstained
        # ``source_span`` (the backfill couldn't re-anchor). Per §4.9 those
        # two epistemic states collapse to one ``null`` here — the
        # reason-code distinction lives only in m2's offline backfill
        # report, out of m5's serving scope.
        "source_revision_id": row.get("source_revision_id"),
        "source_span": row.get("source_span"),
        "theorem_label": row["theorem_label"],
        "theorem_name": row["theorem_name"],
        # source-truth-m5: INGEST-time provenance — was the STORED body
        # token-capped to STMT_MAX_TOKENS at chunk time (ingest/schema.py).
        # DISTINCT from the SERVING-time completeness flag: whether the
        # RETURNED text is complete is governed solely by the top-level
        # (absent-when-false) ``body_truncated`` (the size-based byte-cap).
        # An agent must NOT read ``chunk.truncated`` to judge whether the
        # body it received is complete (they can disagree in both directions).
        "truncated": row.get("truncated"),
    }

    payload = {
        "chunk": chunk,
        "found": True,
        "include_referenced_applied": False,
    }

    # retrieval-unlocks-m1: stmt <-> proof linkage. Resolved from the
    # (paper_id, theorem_label, kind) scalar join ingest already records,
    # with a uniqueness-gated section-scope fallback when theorem_label
    # is NULL. ``linkage.outcome`` carries the epistemic result — a
    # theorem with no proof in the corpus reports ``not-in-corpus``, and
    # an undecidable unlabeled pairing reports ``ambiguous``, neither
    # collapsing into a silently empty list (trust-language-policy §5d).
    if include_referenced:
        linkage = resolve_referenced(r.chunks_table, row)
        # Threat 2: referenced bodies are author-controlled corpus text,
        # exactly like the primary body, so they take the same
        # sanitize-then-wrap path. Both steps happen here rather than in
        # proof_linkage so there is ONE place where retrieved text
        # becomes response text. Order differs from the primary body by
        # necessity, not accident: enforce_byte_cap only ever truncates
        # ``("chunk", "body_text")``, so a referenced body is never
        # sliced by the cap and its wrap cannot be cut in half.
        for ref in linkage["referenced_chunks"]:
            ref["body_text"] = wrap_retrieved_text(
                sanitize_retrieved_text(ref["body_text"]), kind="chunk"
            )
        payload["include_referenced_applied"] = True
        payload["referenced_chunks"] = linkage["referenced_chunks"]
        payload["linkage"] = linkage["linkage"]
    # F1 fix from E06_S03 critique: tell enforce_byte_cap that
    # body_text is nested under ``chunk``, not at the top level.
    # Without the explicit path, the cap would silently fail to
    # truncate get_chunk responses.
    structured, content_blocks = enforce_byte_cap(
        payload,
        chunk_id=chunk_id,
        body_text_path=("chunk", "body_text"),
        cap_override=byte_cap,
    )
    # E13_S02 — wrap AFTER the byte-cap so the delimiter pair is
    # well-formed regardless of whether the cap fired. The
    # escape-on-emit step inside ``wrap_retrieved_text`` defends
    # against adversarial close tags in body content (FM-1).
    if (
        isinstance(structured.get("chunk"), dict)
        and "body_text" in structured["chunk"]
    ):
        structured["chunk"]["body_text"] = wrap_retrieved_text(
            structured["chunk"]["body_text"], kind="chunk"
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
    return structured


def _arrow_all_rows(arrow) -> list[dict[str, Any]]:  # noqa: ANN001
    """Convert every row of an Arrow table to a list of dicts (batch
    fetch). Column-wise then transposed, so a 0-row table yields []."""
    if arrow.num_rows == 0:
        return []
    cols = {name: arrow.column(name).to_pylist() for name in arrow.column_names}
    return [
        {name: cols[name][i] for name in arrow.column_names}
        for i in range(arrow.num_rows)
    ]


def _escape_lance_str(s: str) -> str:
    """Escape single quotes for LanceDB SQL-style WHERE clauses."""
    return s.replace("'", "''")
