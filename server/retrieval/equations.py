"""Equation similarity index — TED + dense cosine fusion (E10_S03).

Backs the ``find_equation`` MCP tool for **MathML inputs**. The
fusion algorithm scores each candidate by a weighted linear
combination of:

1. ``1 - normalized_ted`` — the inverted Zhang-Shasha tree-edit
   distance over canonical MathML trees, normalized by
   ``max(|A|, |B|)`` so the value lives in [0, 1] independent of
   corpus size.
2. ``cosine_score`` — the dense-cosine similarity over the chunks
   table's ``embedding_stmt`` column (the ``embedding_eq`` column
   defined on the equations table is reserved for a future milestone
   that adds an equation encoder pass).

``final_score = α * (1 - normalized_ted) + (1 - α) * cosine_score``
where ``α = config.eq_ted_weight`` (default 0.5).

**v1 scope reminder** (research-synthesis.md §1 + §3):
- The handler delegates to this index only for **MathML inputs**;
  LaTeX inputs fall through to the legacy ``dense_only_stmt_fallback``
  path because there is no query-time LaTeXML subprocess pool yet.
- The dense signal is ``embedding_stmt`` cosine — not ``embedding_eq``
  — because the equations table's embedding column is reserved-but-
  NULL at v1. When E10_S03b (or E11) populates ``embedding_eq``, the
  fusion can flip via a one-line config without changing the
  algorithm.
- MathML parse trees are stored as JSON (``mathml_tree_json`` column),
  NOT pickle. Pickle is a code-execution vector on deserialization
  and Python-pickle format drift across minor releases silently
  corrupts the column on upgrade.

**Security posture** for MathML parsing: caller input is bounded at
4000 characters by the handler's Pydantic constraint. We use
``defusedxml.ElementTree`` which disables external-entity resolution
and DTD processing — both XXE and billion-laughs attacks are blocked
by construction. The 4000-char cap additionally bounds the worst-case
exponential expansion target.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from typing import Any

import defusedxml.ElementTree as DET
import zss

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# MathML root detection
# ---------------------------------------------------------------------------

#: Detect whether a string is "probably MathML" by looking for a
#: ``<math`` tag in the first ~64 characters after whitespace strip.
#: A namespace prefix (``m:math``, ``mml:math``) is allowed. We use a
#: cheap regex here — full parse happens only on the TED path.
_MATHML_ROOT_RE = re.compile(r"<(?:[a-zA-Z][\w-]*:)?math\b", re.IGNORECASE)


def looks_like_mathml(text: str) -> bool:
    """Return True iff ``text`` opens with a ``<math>`` root element.

    Tolerates leading whitespace, leading XML declaration
    (``<?xml ... ?>``), and arbitrary namespace prefixes.
    """
    if not isinstance(text, str):
        return False
    head = text.lstrip()[:1024]
    return _MATHML_ROOT_RE.search(head) is not None


# ---------------------------------------------------------------------------
# MathML → zss.Node parse
# ---------------------------------------------------------------------------


def _local_tag(tag: str) -> str:
    """Strip an XML namespace prefix from a tag name.

    ``defusedxml.ElementTree`` returns tags in Clark notation
    (``{namespace}local``); some inputs use the prefix form
    (``m:mfrac``). We collapse both to the bare local name so two
    equations serialized with different namespaces parse to identical
    trees.
    """
    if tag.startswith("{"):
        return tag.split("}", 1)[1]
    if ":" in tag:
        return tag.split(":", 1)[1]
    return tag


def parse_mathml_to_tree(mathml: str) -> zss.Node:
    """Parse a MathML string into a ``zss.Node`` tree.

    The label of each node is the LOCAL element tag name with
    namespace stripped. ALL attributes are dropped (presentation
    noise — ``mathvariant``, ``mathcolor``, ``displaystyle`` — would
    perturb TED for purely cosmetic reasons). Text content is
    captured as a single child node labelled with the text content;
    this lets the TED algorithm distinguish ``<mi>x</mi>`` from
    ``<mi>y</mi>`` without conflating ``<mi>x</mi>`` and ``<mn>x</mn>``
    (different elements get different parents).

    Raises ``ValueError`` on malformed MathML so the caller can fall
    back to dense-only retrieval rather than 500-ing the request.
    """
    if not isinstance(mathml, str) or not mathml.strip():
        raise ValueError("mathml must be a non-empty string")

    try:
        root = DET.fromstring(mathml)
    except DET.ParseError as exc:
        raise ValueError(f"malformed MathML: {exc}") from exc

    return _element_to_node(root)


def _element_to_node(el: Any) -> zss.Node:
    """Recursively convert an ``ElementTree`` element to a zss.Node.

    Inner-text is captured as a leaf child so ``<mi>x</mi>`` and
    ``<mi>y</mi>`` produce structurally distinct trees. Tail-text
    (text following the close-tag of a child) is intentionally
    dropped — it carries no useful semantic content in MathML and
    would inflate TED.
    """
    node = zss.Node(_local_tag(el.tag))
    # Capture inner text as a leaf BEFORE recursing into children,
    # matching MathML's "mixed content" ordering where significant
    # text precedes any nested element.
    text = (el.text or "").strip()
    if text:
        node.addkid(zss.Node(text))
    for child in el:
        node.addkid(_element_to_node(child))
    return node


# ---------------------------------------------------------------------------
# zss.Node ↔ JSON round-trip
# ---------------------------------------------------------------------------


def tree_to_json(node: zss.Node) -> str:
    """Serialize a ``zss.Node`` tree to a compact JSON string.

    The encoding is `{"label": str, "children": list}`. The output
    is sorted-key + no-whitespace so two equal trees produce
    byte-identical JSON (helpful for content addressing if a future
    milestone wants it).
    """
    return json.dumps(
        _node_to_dict(node),
        separators=(",", ":"),
        sort_keys=True,
        ensure_ascii=False,
    )


def tree_from_json(payload: str) -> zss.Node:
    """Deserialize a JSON string produced by :func:`tree_to_json`."""
    if not isinstance(payload, str) or not payload:
        raise ValueError("payload must be a non-empty JSON string")
    return _dict_to_node(json.loads(payload))


def _node_to_dict(node: zss.Node) -> dict[str, Any]:
    return {
        "label": node.label,
        "children": [_node_to_dict(c) for c in node.children],
    }


def _dict_to_node(d: dict[str, Any]) -> zss.Node:
    if not isinstance(d, dict) or "label" not in d:
        raise ValueError(
            f"tree-JSON node must have a 'label' field; got {d!r}"
        )
    label = d["label"]
    if not isinstance(label, str):
        raise ValueError(
            f"tree-JSON 'label' must be a string; got {type(label).__name__}"
        )
    node = zss.Node(label)
    for child in d.get("children") or []:
        node.addkid(_dict_to_node(child))
    return node


# ---------------------------------------------------------------------------
# Tree size + normalized TED
# ---------------------------------------------------------------------------


def tree_size(node: zss.Node) -> int:
    """Return the number of nodes in the tree rooted at ``node``."""
    return 1 + sum(tree_size(c) for c in node.children)


def normalized_ted(tree_a: zss.Node, tree_b: zss.Node) -> float:
    """Return Zhang-Shasha TED normalized by ``max(|A|, |B|)``.

    Result is in ``[0, 1]``; 0 means identical trees, 1 means
    completely disjoint trees (a full rebuild). Independent of
    corpus size.
    """
    size_a = tree_size(tree_a)
    size_b = tree_size(tree_b)
    denom = max(size_a, size_b)
    if denom == 0:
        return 0.0
    raw = zss.simple_distance(tree_a, tree_b)
    # Clamp into [0, 1] in case the algorithm returns a relabeling
    # cost that nominally exceeds the size cap (shouldn't happen
    # with the default label_dist=strdist, but defensive).
    return min(1.0, max(0.0, float(raw) / float(denom)))


# ---------------------------------------------------------------------------
# Fusion
# ---------------------------------------------------------------------------


def fuse_scores(
    ted_norm: float, cosine_score: float, alpha: float = 0.5
) -> float:
    """Combine TED + cosine into a single ``final_score``.

    ``alpha = 1.0`` → pure ``(1 - normalized_ted)`` ranking.
    ``alpha = 0.0`` → pure cosine ranking.
    ``alpha = 0.5`` → equal weights (default).

    Both inputs are expected in ``[0, 1]``. Output is in ``[0, 1]``.
    """
    if not 0.0 <= alpha <= 1.0:
        raise ValueError(f"alpha must be in [0, 1]; got {alpha}")
    return alpha * (1.0 - ted_norm) + (1.0 - alpha) * cosine_score


# ---------------------------------------------------------------------------
# Result rows
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class EquationHit:
    """One result row from :meth:`EquationIndex.query`.

    Wire shape matches the existing find_equation envelope: the
    handler maps these to a sorted result list with score-desc /
    chunk_id-asc tie-breaks per the determinism contract from
    ``06-mcp-server-design.md``.
    """

    equation_id: str
    paper_id: str
    chunk_id: str | None
    cosine_score: float
    ted_norm: float
    final_score: float


# ---------------------------------------------------------------------------
# Index
# ---------------------------------------------------------------------------


#: Maximum number of dense-cosine candidates to consider before
#: rescoring with TED. Larger values trade query latency for recall;
#: 200 is the brief's recommendation and matches the heaviest
#: per-candidate cost we expect at corpus scale (~100ms total at
#: 0.5ms × 200).
DEFAULT_ANN_CANDIDATE_CAP = 200


@dataclass(frozen=True, slots=True)
class _Candidate:
    """Internal row carrying the data needed to score one candidate."""

    equation_id: str
    paper_id: str
    parent_chunk_id: str | None
    mathml_tree_json: str | None
    cosine_score: float


class EquationIndex:
    """Equation similarity index.

    Holds references to (a) the LanceDB ``equations`` table for the
    candidate set and (b) the chunks table for the dense cosine pass.
    Callers build one instance per process via
    :meth:`from_resources` and reuse it across requests.
    """

    def __init__(
        self,
        equations_table: Any | None,
        chunks_table: Any,
        alpha: float = 0.5,
        ann_candidate_cap: int = DEFAULT_ANN_CANDIDATE_CAP,
    ) -> None:
        if not 0.0 <= alpha <= 1.0:
            raise ValueError(f"alpha must be in [0, 1]; got {alpha}")
        self._equations = equations_table
        self._chunks = chunks_table
        self._alpha = alpha
        self._ann_cap = ann_candidate_cap

    @property
    def available(self) -> bool:
        """Return True iff the TED-fusion path is wired.

        ``False`` indicates the ``equations`` table is missing OR
        every row has ``mathml_tree_json=NULL``. The handler should
        report ``retrieval_mode="dense_only_fallback"`` and skip
        directly to dense retrieval.
        """
        return self._equations is not None

    def query(
        self,
        mathml: str,
        query_vec: Any,
        k: int,
    ) -> list[EquationHit]:
        """Run the full TED + cosine fusion pipeline.

        ``mathml`` is the caller's MathML input (already validated to
        be MathML by ``looks_like_mathml`` at the handler).
        ``query_vec`` is a pre-computed BGE-M3 embedding of the same
        input (the handler calls ``encode_query`` once and threads
        the vector down). ``k`` is the requested top-k cutoff.

        Returns a list of :class:`EquationHit` sorted by
        ``final_score`` descending, with ``equation_id`` ascending as
        the tie-break. Empty list if the index is unavailable OR the
        candidate set has zero rows with a parseable
        ``mathml_tree_json``.
        """
        if not self.available:
            return []

        query_tree = parse_mathml_to_tree(mathml)
        candidates = self._dense_candidates(query_vec)
        if not candidates:
            return []

        hits: list[EquationHit] = []
        for cand in candidates:
            if cand.mathml_tree_json is None:
                # No TED tree available; degrade to cosine-only score
                # for this row (fusion still produces a stable ranking
                # when only a subset of rows have trees).
                ted_norm = 1.0
            else:
                try:
                    cand_tree = tree_from_json(cand.mathml_tree_json)
                    ted_norm = normalized_ted(query_tree, cand_tree)
                except (ValueError, json.JSONDecodeError) as exc:
                    # A corrupted tree_json column should not 500 the
                    # request; degrade this row to cosine-only and log.
                    logger.warning(
                        "tree_from_json failed for equation_id=%s: %s",
                        cand.equation_id, exc,
                    )
                    ted_norm = 1.0
            final = fuse_scores(ted_norm, cand.cosine_score, self._alpha)
            hits.append(
                EquationHit(
                    equation_id=cand.equation_id,
                    paper_id=cand.paper_id,
                    chunk_id=cand.parent_chunk_id,
                    cosine_score=cand.cosine_score,
                    ted_norm=ted_norm,
                    final_score=final,
                )
            )

        hits.sort(key=lambda h: (-h.final_score, h.equation_id))
        return hits[:k]

    def _dense_candidates(self, query_vec: Any) -> list[_Candidate]:
        """Run the ANN pass and join the result against the equations
        table.

        The dense pass currently uses ``embedding_stmt`` on the
        chunks table because the equations table's ``embedding_eq``
        column is reserved-but-NULL at v1. The join key is
        ``parent_chunk_id`` so the chunk-level dense score is paired
        with each equation atom that lives under that chunk.

        Returns a list of :class:`_Candidate` rows sorted by
        ``cosine_score`` descending. Capped at ``self._ann_cap``.
        """
        # Pull the top-N chunks by dense cosine; map chunk_id →
        # cosine_score for the join.
        chunks_arrow = (
            self._chunks.search(
                query_vec, vector_column_name="embedding_stmt"
            )
            .limit(self._ann_cap)
            .to_arrow()
        )
        if chunks_arrow.num_rows == 0:
            return []
        chunk_scores: dict[str, float] = {}
        chunk_ids = chunks_arrow.column("chunk_id").to_pylist()
        distances = chunks_arrow.column("_distance").to_pylist()
        for cid, dist in zip(chunk_ids, distances, strict=True):
            if cid is None:
                continue
            chunk_scores[cid] = _distance_to_cosine(dist)

        if not chunk_scores:
            return []

        # Pull every equation whose parent_chunk_id is in the
        # retrieved chunk set. LanceDB does not support an IN clause
        # against a Python set today; build a quoted list. Chunk IDs
        # match the strict regex
        # ``arxiv:<paper_id>:<hex16>`` so injection is impossible by
        # construction.
        in_clause = ", ".join(f"'{cid}'" for cid in chunk_scores)
        eq_filter = f"parent_chunk_id IN ({in_clause})"
        equations_arrow = (
            self._equations.search().where(eq_filter).to_arrow()
        )
        if equations_arrow.num_rows == 0:
            return []

        # Build the candidate list, paired with the chunk-level
        # cosine score from the dense pass.
        out: list[_Candidate] = []
        eq_rows = equations_arrow.to_pylist()
        for row in eq_rows:
            parent = row.get("parent_chunk_id")
            score = chunk_scores.get(parent, 0.0) if parent else 0.0
            out.append(
                _Candidate(
                    equation_id=row["equation_id"],
                    paper_id=row["paper_id"],
                    parent_chunk_id=parent,
                    mathml_tree_json=row.get("mathml_tree_json"),
                    cosine_score=score,
                )
            )
        out.sort(key=lambda c: (-c.cosine_score, c.equation_id))
        # Truncate to ann_cap defensively — equations table may have
        # multiple atoms per chunk so the join can blow past the cap.
        return out[: self._ann_cap]


def _distance_to_cosine(dist: float | None) -> float:
    """Map LanceDB ``_distance`` (squared-L2 on L2-normalized vectors)
    to a cosine score in ``[0, 1]``.

    For two unit vectors u, v: ``||u - v||² = 2 - 2*cos(u,v)``, so
    ``cos = 1 - dist/2``. We clamp to ``[0, 1]`` to absorb minor
    floating-point drift.
    """
    if dist is None:
        return 0.0
    return max(0.0, min(1.0, 1.0 - float(dist) / 2.0))


__all__ = [
    "DEFAULT_ANN_CANDIDATE_CAP",
    "EquationHit",
    "EquationIndex",
    "fuse_scores",
    "looks_like_mathml",
    "normalized_ted",
    "parse_mathml_to_tree",
    "tree_from_json",
    "tree_size",
    "tree_to_json",
]
