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
import unicodedata
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
# Presentation canonicalization (retrieval-unlocks-m4)
# ---------------------------------------------------------------------------

#: Bumped whenever the normalization below changes the tree a given
#: MathML string produces. Stored ``equations.mathml_tree_json`` built
#: under an older version is NOT comparable to a freshly-parsed query
#: tree and must be re-indexed (``python -m ingest.index_equations``).
#:
#: v1 → v2 (retrieval-unlocks-m4): parallel-markup reduction, invisible
#: operators dropped, redundant single-child ``mrow`` collapsed, text
#: leaves NFKC-folded. No migration shipped because no equations table
#: had ever been built — v1 trees exist nowhere.
MATHML_TREE_NORMALIZER_VERSION: int = 2

#: LaTeXML runs with ``--format=html5``, which emits PARALLEL MARKUP:
#: every ``<math>`` wraps a ``<semantics>`` holding the presentation
#: subtree PLUS a Content-MathML ``<annotation-xml>`` (``<apply>``/
#: ``<ci>``/``<cn>``) PLUS an x-tex ``<annotation>``. Those annotation
#: subtrees are a parallel ENCODING of the same equation, not extra
#: math — carrying them into the tree more than doubles node count and
#: makes any presentation-only MathML (what every non-LaTeXML converter
#: emits) score a large TED against an identical stored equation.
_ANNOTATION_TAGS: frozenset[str] = frozenset({"annotation", "annotation-xml"})

#: Invisible operators LaTeXML inserts and other converters do not:
#: FUNCTION APPLICATION, INVISIBLE TIMES, INVISIBLE SEPARATOR,
#: INVISIBLE PLUS. They carry no rendered content, so dropping them
#: symmetrically removes pure cross-converter noise.
_INVISIBLE_OPERATOR_CHARS: frozenset[str] = frozenset(
    {"⁡", "⁢", "⁣", "⁤"}
)


def _fold_text(text: str) -> str:
    """Strip and NFKC-fold a MathML text run.

    NFKC collapses the Unicode math-alphanumeric plane onto its ASCII
    base, which the query side needs in order to meet the corpus side:
    LaTeXML writes ``<mi mathvariant="double-struck">C</mi>`` (the
    variant lives in an attribute :func:`_local_tag` drops, leaving leaf
    ``C``) where another converter writes ``<mi>ℂ</mi>`` (U+2102). NFKC
    maps ℂ → ``C``, 𝑡 → ``t``, ℝ → ``R``, so the converted query and the
    stored tree agree on the leaf.

    **Known limitation — this does NOT distinguish font variants, and
    neither does the corpus.** NFKC also folds ℂ ≡ 𝒞 ≡ ℭ ≡ ``C``, so
    ``\\mathbb{C}`` (the complex numbers) and ``\\mathcal{C}`` (a
    category/curve) score TED 0 — a real loss in math.AG/math.NT where
    those are distinct objects. But this is NOT introduced here: the
    stored side ALREADY collapses them, because LaTeXML encodes the
    variant in the ``mathvariant`` attribute that :func:`_local_tag`
    dropped since E10_S03. NFKC only makes the query side match that
    pre-existing collapse. Distinguishing variants would require
    preserving ``mathvariant`` on BOTH sides plus a query-side
    codepoint→variant map — an E10_S03-scope change with a re-index, out
    of scope here. Compatibility folds (µ micro → μ mu, ﬁ → fi, ² → 2)
    ride along; benign-to-helpful for retrieval, and ² is rare since
    ``x^2`` is structural ``<msup>`` not the codepoint.

    Returns ``""`` for whitespace-only.
    """
    stripped = text.strip()
    if not stripped:
        return ""
    return unicodedata.normalize("NFKC", stripped)


# ---------------------------------------------------------------------------
# MathML → zss.Node parse
# ---------------------------------------------------------------------------


def _local_tag(tag: str) -> str:
    """Strip an XML namespace prefix and lowercase a tag name.

    ``defusedxml.ElementTree`` returns tags in Clark notation
    (``{namespace}local``); some inputs use the prefix form
    (``m:mfrac``). We collapse both to the bare local name so two
    equations serialized with different namespaces parse to identical
    trees.

    **F2 (E10_S03 critique) — lowercase the result.** ``looks_like_mathml``
    matches the ``<math>`` root case-insensitively, so an uppercase
    serialization (``<MATH><MI>x</MI></MATH>``) is accepted as MathML and
    must produce the same tree as the lowercase form. Without the
    case-fold, ``parse_mathml_to_tree`` would emit nodes labelled
    ``"MATH"`` / ``"MI"`` and a structurally-identical equation in
    lowercase would score non-zero TED — a wrong-on-common-path
    rank break.
    """
    if tag.startswith("{"):
        return tag.split("}", 1)[1].lower()
    if ":" in tag:
        return tag.split(":", 1)[1].lower()
    return tag.lower()


def parse_mathml_to_tree(mathml: str) -> zss.Node:
    """Parse a MathML string into a ``zss.Node`` tree.

    The label of each node is the LOCAL element tag name with
    namespace stripped and case-folded to lowercase. ALL attributes
    are dropped (presentation noise — ``mathvariant``, ``mathcolor``,
    ``displaystyle`` — would perturb TED for purely cosmetic reasons).

    Text content is captured as leaf children. The element's
    ``text`` (text BEFORE the first child) becomes one leaf;
    ``tail`` (text AFTER the close-tag of each child) becomes a
    second leaf following that child — this preserves mixed-content
    operators like ``<mrow><mi>x</mi> + <mi>y</mi></mrow>`` where the
    operator " + " lives as tail-text on ``<mi>x</mi>``. **F1
    (E10_S03 critique) close** — the previous implementation dropped
    tail-text, which silently conflated ``x+y``, ``x-y``, and ``xy``.

    The tree is canonicalized to PRESENTATION form — see
    :func:`_element_to_node` for the four rules and
    :data:`MATHML_TREE_NORMALIZER_VERSION` for the re-index contract.

    Raises ``ValueError`` on malformed MathML, and on input that
    canonicalizes to nothing at all, so the caller can fall back to
    dense-only retrieval rather than 500-ing the request or silently
    scoring against an empty tree.
    """
    if not isinstance(mathml, str) or not mathml.strip():
        raise ValueError("mathml must be a non-empty string")

    try:
        root = DET.fromstring(mathml)
    except DET.ParseError as exc:
        raise ValueError(f"malformed MathML: {exc}") from exc

    node = _element_to_node(root)
    if node is None:
        # e.g. a bare <annotation-xml> document, or a <semantics> with
        # no presentation child. An empty tree would score TED 0 against
        # every other empty tree and 1.0 against everything else — both
        # meaningless, so refuse rather than rank on it.
        raise ValueError(
            "MathML canonicalized to an empty presentation tree"
        )
    return node


def _element_to_node(el: Any) -> zss.Node | None:
    """Recursively convert an ``ElementTree`` element to a zss.Node,
    canonicalized to its PRESENTATION form.

    Returns ``None`` when the element contributes nothing to the
    presentation tree (an annotation subtree, an invisible operator, or
    a ``<semantics>`` with no presentation child) — callers drop it.

    Inner-text (``el.text``) is captured as a leaf child BEFORE
    recursing into children, matching MathML's "mixed content"
    ordering where significant text precedes any nested element.

    Tail-text (``child.tail`` — text AFTER a child's close tag) is
    captured as a leaf child immediately AFTER the recursive node
    for that child. This is the F1 fix: in mixed-content MathML
    such as ``<mrow><mi>x</mi> + <mi>y</mi></mrow>``, the operator
    " + " lives as tail-text on ``<mi>x</mi>`` and would otherwise
    be lost. Canonical LaTeXML output wraps operators in ``<mo>`` and
    emits no tail-text, so that branch is a no-op on it — only
    mixed-content sources benefit.

    **retrieval-unlocks-m4 canonicalization** (four rules, applied on
    BOTH the ingest and query side because this is the single shared
    normalizer — ``ingest/index_equations.py`` and
    :meth:`EquationIndex.query` both call it):

    1. ``<semantics>`` collapses to its first surviving child. LaTeXML
       parallel markup nests the presentation subtree there.
    2. ``<annotation>`` / ``<annotation-xml>`` subtrees are dropped —
       they re-encode the same equation (Content MathML, x-tex source)
       and would otherwise dominate the node count.
    3. Invisible operators (:data:`_INVISIBLE_OPERATOR_CHARS`) are
       dropped wherever they appear, as element text or as tail-text.
    4. A ``<mrow>`` left with exactly one child collapses to that child
       — converters disagree on redundant row-wrapping, and the wrapper
       carries no meaning.
    """
    tag = _local_tag(el.tag)

    # Rule 2 — an annotation subtree is a parallel encoding, not math.
    if tag in _ANNOTATION_TAGS:
        return None

    # Rule 1 — <semantics> IS the parallel-markup wrapper; keep only the
    # presentation child (the first that survives rules 2/3).
    if tag == "semantics":
        for child in el:
            child_node = _element_to_node(child)
            if child_node is not None:
                return child_node
        return None

    text = _fold_text(el.text or "")

    # Rule 3 — a childless <mo> holding only an invisible operator.
    if tag == "mo" and len(el) == 0 and text in _INVISIBLE_OPERATOR_CHARS:
        return None

    node = zss.Node(tag)
    if text and text not in _INVISIBLE_OPERATOR_CHARS:
        node.addkid(zss.Node(text))
    for child in el:
        child_node = _element_to_node(child)
        if child_node is not None:
            node.addkid(child_node)
        # F1 close — tail-text as a sibling leaf after the child it
        # follows. Whitespace-only and invisible-operator tails drop.
        tail = _fold_text(child.tail or "")
        if tail and tail not in _INVISIBLE_OPERATOR_CHARS:
            node.addkid(zss.Node(tail))

    # Rule 4 — collapse a redundant single-child row wrapper.
    if tag == "mrow" and len(node.children) == 1:
        return node.children[0]
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
#: 0.5ms × 200 — for SMALL trees; see the TED-work bounds below for
#: why that estimate is not a safety guarantee).
DEFAULT_ANN_CANDIDATE_CAP = 200


# ---------------------------------------------------------------------------
# TED-work bounds (retrieval-unlocks-m4)
# ---------------------------------------------------------------------------
#
# ``zss.simple_distance`` is superlinear in tree size and runs once per
# candidate. The 0.5ms-per-candidate estimate above holds for real
# equations (measured median 13 nodes, p99 157, max 590 across 11,734
# corpus equations) but NOT for a large query tree: a 5,002-node tree
# (a 4000-char LaTeX query like ``\pmod{2}`` repeated) measures ~20 s
# against ONE candidate — ~69 minutes at the 200-candidate cap, run
# synchronously on the async event loop. This is the retrieval-unlocks-m4
# security finding, and it is NOT bounded by the handler's 4000-char
# input cap (LaTeX amplifies ~6-900× into MathML nodes). It also affected
# the pre-existing MathML-input path; these bounds fix both.
#
# The bound is on WORK, not input length, because work is the true cost
# driver. Three layered guards, all thread-free and deterministic:

#: A query tree larger than any real equation is not an equation — it is
#: an amplified/adversarial input. Reject it before fetching candidates
#: (cheap: one ``tree_size`` walk) so the handler falls back to dense.
#: 1500 is ~2.5× the largest real corpus equation (590), so no genuine
#: query is refused.
MAX_QUERY_TREE_NODES = 1500

#: Skip TED for an individual candidate whose ``|query| × |candidate|``
#: node-product exceeds this, scoring it cosine-only. ~2500 is the
#: measured ~30ms-per-pair line; a typical query (20 nodes × median-13
#: candidate = 260) is two orders of magnitude under it, so normal
#: retrieval is untouched.
MAX_TED_PAIR_PRODUCT = 2500

#: Cumulative node-product budget across all candidates in one query.
#: Once exceeded, remaining candidates are cosine-only. Caps total TED
#: wall-clock at ~2s worst-case (a typical full 200-candidate scan is
#: ~52,000, well under budget, so it runs in full). Belt to
#: ``MAX_TED_PAIR_PRODUCT``'s suspenders: the per-pair cap bounds one
#: candidate, this bounds the sum.
TED_WORK_BUDGET = 120_000


#: Row cap on the ``_embedding_eq_is_populated`` exception fallback
#: (F3 from the E10_S03b critique). At 1024-dim float32 vectors, 10K
#: rows materialize to ~40MB — bounded regardless of corpus growth.
#: Production embedders run paper-by-paper, so partial population is
#: detectable well within 10K rows.
_POPULATE_CHECK_SLICE = 10_000


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
        #: Populated by :meth:`query` so the handler can surface the
        #: actual dense path that fired. ``"ted_fused_eq"`` when the
        #: equations table's ``embedding_eq`` column was queried
        #: directly; ``"ted_fused"`` when the legacy chunks-proxy
        #: path was used (the latter is the v1 backward-compat
        #: behavior preserved for corpora where ``embedding_eq`` is
        #: still NULL everywhere). Synthesis D11.
        self.last_retrieval_mode: str = "ted_fused"

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

        # retrieval-unlocks-m4 DoS guard 1: a query tree bigger than any
        # real equation is an amplified/adversarial input. Refuse TED
        # (return [] → the handler's dense fallback) rather than run a
        # multi-minute scan on the event loop. Cheap: one size walk
        # before any candidate is fetched.
        query_nodes = tree_size(query_tree)
        if query_nodes > MAX_QUERY_TREE_NODES:
            logger.warning(
                "query tree has %d nodes (> %d cap); skipping TED, "
                "dense-only fallback",
                query_nodes, MAX_QUERY_TREE_NODES,
            )
            return []

        candidates = self._dense_candidates(query_vec)
        if not candidates:
            return []

        # F4 (E10_S03 critique) — track whether ANY candidate had a
        # parseable tree. If none did, return ``[]`` so the handler's
        # ``if not hits: dense_only_fallback`` branch fires, rather
        # than returning ``ted_fused``-tagged results where every
        # row's ted_norm degenerated to 1.0 (purely cosine ranking
        # with the cosine signal halved). The synthesis D10 taxonomy
        # is closed-at-3 modes, so returning empty is the right
        # signal-channel.
        any_tree_seen = False
        ted_work = 0  # cumulative |query|×|cand| node-product (DoS guard 3)
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
                    # DoS guards 2 & 3: skip TED for a pair whose
                    # node-product is individually too expensive, or once
                    # the cumulative work budget is spent. Skipped rows
                    # degrade to cosine-only exactly like a NULL tree —
                    # and crucially do NOT set ``any_tree_seen``, so an
                    # all-skipped query (every pair over-budget, i.e. a
                    # large adversarial tree that slipped under guard 1)
                    # returns [] and the handler reports dense-only
                    # rather than a ``ted_fused`` where TED discriminated
                    # nothing.
                    pair = query_nodes * tree_size(cand_tree)
                    if pair > MAX_TED_PAIR_PRODUCT or ted_work >= TED_WORK_BUDGET:
                        ted_norm = 1.0
                    else:
                        ted_norm = normalized_ted(query_tree, cand_tree)
                        ted_work += pair
                        any_tree_seen = True
                except (
                    ValueError,
                    json.JSONDecodeError,
                    RecursionError,
                ) as exc:
                    # F5 (E10_S03 critique) — also catch RecursionError.
                    # A corrupted tree_json column or a pathologically
                    # deep stored tree should not 500 the request;
                    # degrade this row to cosine-only and log.
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

        # F4 close — if no candidate had a parseable tree, the
        # "ted_fused" mode tag would be misleading. Return empty so
        # the handler falls back to dense_only_fallback.
        if not any_tree_seen:
            return []

        hits.sort(key=lambda h: (-h.final_score, h.equation_id))
        return hits[:k]

    def _dense_candidates(self, query_vec: Any) -> list[_Candidate]:
        """Run the ANN pass and assemble the candidate set.

        Dual-path (synthesis D11):

        * **embedding_eq path** — when the equations table has at
          least one row with non-NULL ``embedding_eq``, query that
          column directly via
          ``equations_table.search(query_vec, vector_column_name="embedding_eq")``.
          The dense signal is equation-specific. Sets
          ``self.last_retrieval_mode = "ted_fused_eq"``.

        * **chunks-proxy path** (v1 legacy) — when ``embedding_eq``
          is all-NULL (corpus not yet re-embedded), fall back to
          ``chunks.embedding_stmt`` ANN + join by
          ``parent_chunk_id``. Sets
          ``self.last_retrieval_mode = "ted_fused"``.

        Returns a list of :class:`_Candidate` rows sorted by
        ``cosine_score`` descending. Capped at ``self._ann_cap``.
        """
        if self._embedding_eq_is_populated():
            self.last_retrieval_mode = "ted_fused_eq"
            return self._dense_candidates_eq(query_vec)
        self.last_retrieval_mode = "ted_fused"
        return self._dense_candidates_chunks_proxy(query_vec)

    def _embedding_eq_is_populated(self) -> bool:
        """Return True iff at least one equation row has a non-NULL
        ``embedding_eq`` value.

        Cheap probe: pull a tiny page (`limit(1)`) filtered to rows
        where the column is non-NULL. We use ``where`` on the same
        Arrow-table read because LanceDB's vector search would
        require a query_vec; the existence check should be
        vec-independent.

        **F3 (E10_S03b critique) close.** The exception fallback is
        bounded at ``_POPULATE_CHECK_SLICE`` rows so a corpus-scale
        table doesn't get materialized in full on every query that
        hits the slow path. 10K rows × 1024 floats × 4 bytes ≈
        40MB cap regardless of corpus growth. The fast path's
        ``.limit(1)`` is already bounded.
        """
        try:
            probe = (
                self._equations.search()
                .where("embedding_eq IS NOT NULL")
                .limit(1)
                .to_arrow()
            )
            return probe.num_rows > 0
        except Exception:  # noqa: BLE001 — older LanceDB may not parse the WHERE
            # Bounded fallback. If the slice contains any non-NULL
            # row, the column is populated. If 10K rows are all NULL,
            # we treat the corpus as "not populated" — at production
            # scale the embedder runs paper-by-paper so partial
            # population is detectable via the first paper's first
            # row, well within 10K.
            arrow = self._equations.to_arrow().slice(
                0, _POPULATE_CHECK_SLICE
            )
            if arrow.num_rows == 0:
                return False
            col = arrow.column("embedding_eq")
            return col.null_count < arrow.num_rows

    def _dense_candidates_eq(self, query_vec: Any) -> list[_Candidate]:
        """ANN pass against ``equations.embedding_eq`` (E10_S03b path).

        No JOIN required — the equations table carries every column
        we need. ``parent_chunk_id`` may still be NULL on individual
        rows (extractor decision); we surface it as-is.
        """
        arrow = (
            self._equations.search(
                query_vec, vector_column_name="embedding_eq"
            )
            .limit(self._ann_cap)
            .to_arrow()
        )
        if arrow.num_rows == 0:
            return []
        rows = arrow.to_pylist()
        distances = arrow.column("_distance").to_pylist()
        out: list[_Candidate] = []
        for row, dist in zip(rows, distances, strict=True):
            out.append(
                _Candidate(
                    equation_id=row["equation_id"],
                    paper_id=row["paper_id"],
                    parent_chunk_id=row.get("parent_chunk_id"),
                    mathml_tree_json=row.get("mathml_tree_json"),
                    cosine_score=_distance_to_cosine(dist),
                )
            )
        out.sort(key=lambda c: (-c.cosine_score, c.equation_id))
        return out[: self._ann_cap]

    def _dense_candidates_chunks_proxy(
        self, query_vec: Any
    ) -> list[_Candidate]:
        """Legacy v1 dense path — chunks.embedding_stmt ANN + JOIN.

        Used when ``embedding_eq`` is all-NULL (typical pre-E10_S03b
        corpora). The chunk-level dense score is paired with every
        equation atom whose ``parent_chunk_id`` matches a top-N
        chunk. Equation atoms with ``parent_chunk_id=None`` (the
        E10_S03b default) score 0 on this path — they only surface
        once ``embedding_eq`` lands and the other path fires.
        """
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
    "MAX_QUERY_TREE_NODES",
    "MAX_TED_PAIR_PRODUCT",
    "TED_WORK_BUDGET",
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
