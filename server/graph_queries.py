"""Graph-query API for the citation graph (E09_S03).

Implements ``cite_neighbors(chunk_id, depth, direction, max_results,
kuzudb_path)`` — the primary read-side entry point for the multi-agent
proof-chain workflow. The MCP-tool wrapper that exposes this on
``tools/list`` lands in E06_S04 / E09_S04; this milestone implements
the underlying graph query and the dataclass result type.

Direction semantics (per brief):

- ``"cites"``: outgoing edges (papers the source paper cites). Filters
  out ``source="intra-paper"`` edges (proof-dependency relations are
  not citations) AND self-loops (a paper does not "cite itself" in
  the outward sense).
- ``"cited_by"``: incoming edges (papers that cite the source). Same
  filters as ``"cites"`` but the Cypher arrow is reversed.
- ``"depends_on"``: intra-paper ``\\ref{}`` chain plus cross-paper
  ``cites`` fallback. KEEPS ``source="intra-paper"`` edges and
  self-loops; cross-paper hops follow any ``cites`` edge.

Result deduplication: Kùzu 0.11.3 returns the same ``paper_id``
multiple times when reachable via multiple paths (e.g. A→B→C and
A→D→C). The implementation dedupes in Python on ``paper_id``,
keeping the row with the smallest ``hop_distance`` (ties broken by
lexicographic ``paper_id``).

Result ordering: ``(hop_distance ASC, paper_id ASC)`` — deterministic
across runs so the ``max_results=50`` cap is reproducible.

Per-hop edge metadata: extracted via Kùzu's ``relationships(p)``
projection on the matched path. The function returns a list of edge
dicts with ``source`` and ``confidence`` directly accessible. The
result row's ``source`` field reflects the LAST edge in the path
(closest to the result paper) — symmetric for ``cited_by`` direction
where "closest to the result paper" reads as "closest to the citer."

Async: ``async def cite_neighbors(...)`` matches the
``server/handlers/*`` async-handler convention. Kùzu's driver is
sync; ``conn.execute`` calls are wrapped in ``asyncio.to_thread`` so
the event loop is not blocked.
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any, Literal

import kuzu

from ingest.identifiers import paper_id_from_chunk_id
from server.graph_types import CitationNeighbor

logger = logging.getLogger(__name__)

#: Default Kùzu DB directory. Matches the Makefile bootstrap target
#: and the design notes (``05-storage-and-indexing.md`` § Kùzu citation
#: graph). The brief signature default is ``var/arxmcp/index/kuzudb/``;
#: that is the path-name drift documented in ``research-synthesis.md``
#: § 3 — three repo signals (Makefile, two design notes, two prior
#: shipped milestones) all use ``kuzu/``. The brief is the outlier.
DEFAULT_KUZUDB_PATH = "var/arxmcp/index/kuzu"

#: Hard cap on the per-call result count. The brief AC#5 mentions 50;
#: we apply this AFTER dedupe + filter so distinct papers aren't
#: silently dropped by an early-truncated query.
DEFAULT_MAX_RESULTS = 50

#: Priority list for the LanceDB ``kind="stmt"`` lookup: a paper without
#: a top-level theorem-statement chunk falls through to the next kind
#: in priority order. Some math papers (especially expository surveys)
#: have only ``definition`` or ``remark`` chunks; the brief's strict
#: ``kind="stmt"`` rule would return ``chunk_id=None`` for those even
#: though a meaningful representative chunk exists.
_REPRESENTATIVE_KIND_PRIORITY = (
    "stmt",
    "lemma",
    "proposition",
    "corollary",
    "definition",
    "remark",
)

Direction = Literal["cites", "cited_by", "depends_on"]


# ---------------------------------------------------------------------------
# Kùzu query layer
# ---------------------------------------------------------------------------


def _build_query(direction: Direction, depth: int) -> str:
    """Build the variable-length Cypher query for a given direction.

    The pattern reverses the arrow for ``cited_by`` so the same
    bound-paper-id parameter (``$paper_id``) names the source paper
    in both directions:

    - ``cites`` / ``depends_on``: source is on the LEFT;
      ``(s {paper_id: $paper_id})-[r:cites*1..N]->(n)``.
    - ``cited_by``: source is on the RIGHT;
      ``(n)-[r:cites*1..N]->(s {paper_id: $paper_id})``.

    The variable-length form ``[r:cites*1..N]`` and the
    ``relationships(p)`` projection both verified live in Kùzu 0.11.3
    (see ``research-synthesis.md`` § 1).
    """
    if depth not in (1, 2):
        raise ValueError(f"depth must be 1 or 2, got {depth}")
    if direction == "cited_by":
        pattern = (
            f"(n:papers)-[r:cites*1..{depth}]->(s:papers {{paper_id: $paper_id}})"
        )
    else:
        # "cites" and "depends_on" use the outgoing arrow; the source
        # filter is what differentiates them in the result mapper.
        pattern = (
            f"(s:papers {{paper_id: $paper_id}})-[r:cites*1..{depth}]->(n:papers)"
        )
    return (
        f"MATCH p = {pattern} "
        "RETURN n.paper_id AS paper_id, length(p) AS hop, "
        "relationships(p) AS rels"
    )


def _execute_traversal(
    conn: kuzu.Connection, paper_id: str, direction: Direction, depth: int
) -> list[tuple[str, int, list[dict[str, Any]]]]:
    """Run the Cypher query; return raw rows (paper_id, hop, rels).

    The relationship-list ``rels`` is a list of dicts; each dict has
    ``source`` and ``confidence`` keys (verified live in Kùzu 0.11.3).
    Internal node-id keys ``_src`` / ``_dst`` / ``_label`` / ``_id``
    are ignored downstream.
    """
    cypher = _build_query(direction, depth)
    result = conn.execute(cypher, {"paper_id": paper_id})
    rows: list[tuple[str, int, list[dict[str, Any]]]] = []
    while result.has_next():
        row = result.get_next()
        rows.append((row[0], int(row[1]), list(row[2])))
    return rows


def _row_passes_direction_filter(
    rels: list[dict[str, Any]],
    direction: Direction,
) -> bool:
    """Return True if the path's edge sources are valid for the
    requested direction.

    - ``cites`` / ``cited_by``: ALL edges in the path must have
      ``source != "intra-paper"``. An intra-paper edge in a citation
      query path is a proof-dependency hop, not a citation hop.
    - ``depends_on``: any source is fine — that direction
      semantically wants to follow intra-paper edges first AND fall
      through to citation edges for cross-paper hops.

    Kùzu 0.11.3's ``ALL(r IN rels WHERE r.source <> 'intra-paper')``
    predicate fails on recursive-rel bindings (the binder can't
    introduce ``r`` as a list scalar), so the filter must run in
    Python after the rows are materialized. This is acceptable at
    Tier-3 scale (≤ 50 results, double-digit total rows including
    duplicates).
    """
    if direction == "depends_on":
        return True
    return all(r.get("source") != "intra-paper" for r in rels)


def _result_source(rels: list[dict[str, Any]]) -> tuple[str, float]:
    """Pick a representative ``(source, confidence)`` for the result row.

    The path may have one or two edges (for depth=1 or depth=2 paths).
    We use the LAST edge (closest to the result paper) as the
    representative — symmetric with ``cited_by`` direction where
    "closest to the result" reads as "closest to the citer" of the
    source paper.

    Empty ``rels`` should never happen for a valid match (Kùzu always
    populates relationships for a path with ≥ 1 hop), but defaults
    are returned defensively to keep the dataclass populated.
    """
    if not rels:
        return ("", 0.0)
    last = rels[-1]
    return (str(last.get("source", "")), float(last.get("confidence", 0.0)))


def _edge_kind_for_result(direction: Direction, rels: list[dict[str, Any]]) -> str:
    """Annotate the result row with the brief's ``edge_kind`` taxonomy.

    - ``"ref"`` when the path's last edge is intra-paper (the brief's
      "intra-paper ``\\ref{}`` chain" semantic).
    - ``"cited_by"`` when the query direction is ``cited_by``.
    - ``"cites"`` otherwise.

    The brief uses ``edge_kind`` to give the agent enough signal to
    distinguish proof-dependency neighbors from citation neighbors
    without a follow-up tool call.
    """
    if direction == "cited_by":
        return "cited_by"
    last_source = (rels[-1].get("source") if rels else None)
    if last_source == "intra-paper":
        return "ref"
    return "cites"


# ---------------------------------------------------------------------------
# LanceDB chunk-id representative lookup
# ---------------------------------------------------------------------------


def _lookup_chunk_ids_for_papers(
    paper_ids: set[str],
    lancedb_path: str | Path | None,
) -> dict[str, str | None]:
    """Map ``paper_id`` → representative ``chunk_id`` (or ``None``).

    Single batched LanceDB query over the full candidate set (up to
    ``max_results+1`` papers) — per-paper queries would multiply
    round-trips by 50.

    Priority: ``stmt`` first, falling back to ``lemma`` /
    ``proposition`` / ``corollary`` / ``definition`` / ``remark``. The
    brief's strict ``kind="stmt"`` rule would return ``None`` for
    papers without a top-level statement chunk even when a meaningful
    representative chunk exists. Lower-priority kinds are
    best-effort and the docstring on the dataclass explains the
    semantic.

    When ``lancedb_path`` is ``None`` or the path doesn't exist (e.g.
    in unit tests that exercise the graph-only path), every paper
    maps to ``None``. This keeps the function callable without
    LanceDB present.

    Returns a dict containing every requested ``paper_id`` (defensive:
    a missing key in the caller would silently produce ``None``).
    """
    out: dict[str, str | None] = {pid: None for pid in paper_ids}
    if not paper_ids:
        return out
    if lancedb_path is None:
        return out
    path = Path(lancedb_path)
    if not path.exists():
        return out

    # Local import to avoid pulling lancedb / pyarrow on the cold path
    # (e.g. tests that don't need the chunk-id lookup).
    from server.corpus import open_chunks_table

    try:
        table = open_chunks_table(lancedb_path=str(path), version=None)
    except FileNotFoundError:
        return out

    ids_csv = ",".join(f"'{_escape_sql(pid)}'" for pid in sorted(paper_ids))
    kinds_csv = ",".join(f"'{k}'" for k in _REPRESENTATIVE_KIND_PRIORITY)
    where = f"paper_id IN ({ids_csv}) AND kind IN ({kinds_csv})"
    arrow = (
        table.search()
        .where(where, prefilter=True)
        .limit(len(paper_ids) * len(_REPRESENTATIVE_KIND_PRIORITY) * 8)
        .to_arrow()
    )

    # Group by paper_id; for each, pick the highest-priority kind that
    # has any chunk; tie-break on lexicographic chunk_id for
    # determinism.
    kind_rank = {k: i for i, k in enumerate(_REPRESENTATIVE_KIND_PRIORITY)}
    by_paper: dict[str, list[tuple[int, str]]] = {}
    paper_col = arrow.column("paper_id").to_pylist()
    kind_col = arrow.column("kind").to_pylist()
    chunk_col = arrow.column("chunk_id").to_pylist()
    for paper_id, kind, chunk_id in zip(paper_col, kind_col, chunk_col, strict=False):
        rank = kind_rank.get(kind)
        if rank is None:
            continue
        by_paper.setdefault(paper_id, []).append((rank, chunk_id))
    for paper_id, hits in by_paper.items():
        # Sort by (rank, chunk_id) so the lowest rank wins; ties go to
        # lexicographically-first chunk_id.
        hits.sort()
        out[paper_id] = hits[0][1]
    return out


def _escape_sql(value: str) -> str:
    """Escape a string literal for inclusion in a LanceDB SQL WHERE
    clause. Mirrors the ``_escape`` helper used by ``server/handlers/paper.py``."""
    return value.replace("'", "''")


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def cite_neighbors(
    chunk_id: str,
    depth: int = 2,
    direction: Direction = "cites",
    max_results: int = DEFAULT_MAX_RESULTS,
    kuzudb_path: str | Path = DEFAULT_KUZUDB_PATH,
    lancedb_path: str | Path | None = None,
) -> list[CitationNeighbor]:
    """Return citation neighbors of ``chunk_id`` up to ``depth`` hops.

    See module docstring for direction semantics, deduplication, and
    ordering.

    Args:
        chunk_id: arXiv chunk_id; the source ``paper_id`` is parsed
            via ``ingest.identifiers.paper_id_from_chunk_id``. Raises
            ``ValueError`` for malformed input.
        depth: 1 or 2.
        direction: ``"cites"`` (outgoing), ``"cited_by"`` (incoming),
            or ``"depends_on"`` (intra-paper-chain-aware). Raises
            ``ValueError`` for unknown values (F8 fix from the
            E09_S03 critique).
        max_results: hard cap on the result list length (after dedupe
            and direction filters).
        kuzudb_path: directory of the Kùzu DB. Default is the design
            constitution / bootstrap path; the brief default
            (``"var/arxmcp/index/kuzudb/"``) is documented drift.
        lancedb_path: optional path to the LanceDB ``chunks`` table.
            ``None`` means "no chunk-id lookup; every result has
            ``chunk_id=None``" — useful for graph-only callers and
            for unit tests that don't materialize a LanceDB table.

    Returns: a list of ``CitationNeighbor``, ordered by
    ``(hop_distance ASC, paper_id ASC)``.

    .. warning::

        Path-traversal validation (Threat 1 from
        ``08-security-observability-ops.md``) is **deferred to E06's
        tool-input boundary**. This function trusts ``kuzudb_path``
        and ``lancedb_path`` as config-derived. The MCP-tool wrapper
        that lands in E06_S04 / E09_S04 MUST NOT pass agent-supplied
        JSON arguments through to either path — derive them from
        ``Resources`` / ``Config`` instead. F2 from the E09_S03
        critique flagged this as a HIGH-severity contract risk;
        the project pattern is to keep library functions trusting
        and lock the contract at the tool-input boundary (mirrors
        ``server.corpus.open_chunks_table``'s warning).
    """
    if max_results <= 0:
        return []
    if direction not in ("cites", "cited_by", "depends_on"):
        # F8 fix from the E09_S03 critique: typed at the signature
        # level (Literal) but Python doesn't enforce at runtime; an
        # unknown value would silently route to "cites"-like behavior.
        raise ValueError(
            "direction must be one of 'cites', 'cited_by', "
            f"'depends_on'; got {direction!r}"
        )
    paper_id = paper_id_from_chunk_id(chunk_id)

    db = kuzu.Database(str(Path(kuzudb_path)))
    try:
        conn = kuzu.Connection(db)
        rows = await asyncio.to_thread(
            _execute_traversal, conn, paper_id, direction, depth
        )
    finally:
        del db

    # Dedupe by paper_id, keeping the smallest hop_distance.
    # Each entry is (hop_distance, source, confidence, edge_kind).
    deduped: dict[str, tuple[int, str, float, str]] = {}
    for neighbor_paper_id, hop, rels in rows:
        if not _row_passes_direction_filter(rels, direction):
            continue
        # Self-loop filter: ``cites`` and ``cited_by`` exclude a paper
        # showing up as its own neighbor; ``depends_on`` keeps
        # self-loops because that's how intra-paper deps are stored.
        if neighbor_paper_id == paper_id and direction != "depends_on":
            continue
        source, confidence = _result_source(rels)
        edge_kind = _edge_kind_for_result(direction, rels)
        existing = deduped.get(neighbor_paper_id)
        if existing is None or hop < existing[0]:
            deduped[neighbor_paper_id] = (hop, source, confidence, edge_kind)

    # Order by (hop_distance, paper_id) — deterministic and matches
    # the synthesis decision so a re-run returns the same 50 papers.
    ordered = sorted(deduped.items(), key=lambda kv: (kv[1][0], kv[0]))
    capped = ordered[:max_results]

    # Look up representative chunk_ids in a single batched LanceDB
    # query. Out-of-corpus papers map to None (AC#7).
    candidate_paper_ids = {pid for pid, _ in capped}
    chunk_id_map = await asyncio.to_thread(
        _lookup_chunk_ids_for_papers, candidate_paper_ids, lancedb_path
    )

    return [
        CitationNeighbor(
            chunk_id=chunk_id_map.get(pid),
            paper_id=pid,
            edge_kind=edge_kind,
            hop_distance=hop,
            source=source,
            confidence=confidence,
        )
        for pid, (hop, source, confidence, edge_kind) in capped
    ]
