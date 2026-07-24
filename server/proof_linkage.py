"""Statement <-> proof linkage for ``get_chunk(include_referenced=True)``.

retrieval-unlocks-m1 (D2-R01). Resolves the pairing that ingest already
records but nothing ever served: a theorem-like statement chunk and the
proof window(s) that discharge it, in BOTH directions.

**Primary key: ``(paper_id, theorem_label, kind)``.** The chunker copies
the statement's ``theorem_label`` onto every proof window it emits for
that statement (``ingest/chunker.py``), so the join is a scalar equality
lookup — no vector search, no reranker, no heuristic.

**The unlabeled case, and why it abstains.** ``theorem_label`` is NULL
whenever LaTeXML emitted no auto-id (unnumbered environments, and some
custom ``\\newtheorem`` environments). For those the only remaining
signal is ``section_path``, and *it is not sufficient to order chunks
within a section*: the chunker assigns a monotonic ``idx<N>`` while
walking the document, then **discards it** — ``ingest/chunker.py``
rewrites every id to the content hash ``sha256(preamble + body)[:16]``
before the record is written. No column of ``CHUNKS_SCHEMA_V1`` records
document position. So for two unlabeled theorems in one section, "the
adjacent proof" is not computable from served data.

Rather than guess, this module resolves an unlabeled pairing ONLY when
the section scope makes it unambiguous (exactly one unlabeled
statement-kind chunk in that section), and otherwise returns the
``ambiguous`` epistemic outcome from
``.claude/docs/trust-language-policy.md`` §5a. A wrong proof attached to
a theorem is worse than no proof: the agent cannot tell it is wrong,
because both are well-formed chunks from the right paper.

**Outcomes** (``linkage.outcome``) — all four are SUCCESS states per
§5a, never errors, and are kept distinct from an operational failure and
from a silently empty list (the ``get_definitions`` collapse §5d names):

``resolved``
    At least one counterpart chunk was found.
``not-in-corpus``
    The chunk pairs in principle, but this paper contains no
    counterpart. A theorem whose proof is genuinely absent.
``ambiguous``
    Multiple candidates, none dominant — the unlabeled multi-statement
    section above. The tool declines to pick.
``unsupported-by-provider``
    This chunk's ``kind`` does not participate in statement/proof
    pairing at all (``section`` prose, ``definition``, ``remark``, a
    ``textbook`` chunk).

Per §6 rule 1 the field is ``linkage.outcome``, namespaced and
axis-specific — NOT a new bare ``status``.
"""

from __future__ import annotations

import logging
from typing import Any, Final

logger = logging.getLogger(__name__)

#: ``kind`` of a proof window.
PROOF_KIND: Final[str] = "proof"

#: The ``kind`` values that can pair with a proof. Derived in
#: ``ingest/chunker.py`` by mapping ``_THEOREM_LIKE_ENVNAMES`` through
#: ``_THEOREM_ENV_KINDS``; pinned here as a literal so this module (on
#: the request hot path) does not import the chunker, which pulls in
#: BeautifulSoup and the tokenizer at module scope.
#:
#: ``tests/test_proof_linkage.py::test_stmt_kinds_match_the_chunker``
#: imports the chunker and asserts equality, so drift fails a test
#: instead of silently dropping a whole environment class out of
#: linkage. Same pin-plus-guard discipline as
#: ``EXPECTED_TOOL_SCHEMA_SHA256``.
#:
#: Deliberately EXCLUDES ``definition`` / ``remark`` / ``example`` /
#: ``problem`` / ``question`` / ``exercise`` / ``assumption`` /
#: ``convention`` / ``notation``: the chunker never pairs a proof with
#: them (``_THEOREM_LIKE_ENVNAMES``), so claiming a linkage would be an
#: overclaim, not a lookup.
PROOF_PAIRING_STMT_KINDS: Final[frozenset[str]] = frozenset({
    "stmt",
    "lemma",
    "proposition",
    "corollary",
    "claim",
    "conjecture",
    "fact",
    "hypothesis",
    "observation",
})

#: Hard ceiling on rows pulled for a section-scope fallback. One paper's
#: chunks are a bounded set (low hundreds), but the corpus is untrusted
#: input, so the read is capped rather than trusted to be small. Hitting
#: the cap yields ``ambiguous`` — a truncated candidate set cannot prove
#: uniqueness, and asserting it anyway is exactly the wrong-proof failure
#: this module exists to avoid.
MAX_SECTION_SCAN_ROWS: Final[int] = 2000

#: Ceiling on counterpart chunks returned. A long proof is split into
#: several windows, so >1 is normal; a theorem with more than 8 is
#: pathological. Kept small deliberately: referenced bodies ride along
#: in the same response, and ``enforce_byte_cap`` can only truncate the
#: PRIMARY body (``body_text_path=("chunk", "body_text")``) — so an
#: unbounded counterpart set could push a response past the 256 KB cap
#: with nothing left to trim. ``MAX_REFERENCED * REF_BODY_MAX_CHARS``
#: is the hard ceiling on that ride-along, and it is ~32 KB.
MAX_REFERENCED: Final[int] = 8

#: Per-counterpart body budget, in characters. A proof window is ~448
#: BGE-M3 tokens (~2 KB), so this truncates almost nothing in practice
#: while bounding the pathological case. Truncation is flagged per
#: counterpart via ``body_truncated`` — never silent.
REF_BODY_MAX_CHARS: Final[int] = 4000

#: Columns fetched for counterpart rows. Excludes the three embedding
#: columns (1024 float32 each) — pulling them would dwarf the payload.
_REF_COLUMNS: Final[list[str]] = [
    "chunk_id",
    "paper_id",
    "kind",
    "section_path",
    "theorem_label",
    "theorem_name",
    "body_text",
]

#: Columns needed to judge section-scope uniqueness. No body_text: the
#: fallback counts candidates before deciding, and bodies are only
#: fetched for the winner.
_SCOPE_COLUMNS: Final[list[str]] = [
    "chunk_id",
    "kind",
    "section_path",
    "theorem_label",
]


def escape_lance_str(s: str) -> str:
    """Escape single quotes for a LanceDB SQL-style WHERE clause.

    Applied to EVERY interpolated value, including values read back out
    of the corpus. ``theorem_label`` is author-controlled content that
    arrived through LaTeXML — under the project threat model that is
    untrusted input no matter that it came from our own table.
    """
    return s.replace("'", "''")


def _rows(arrow) -> list[dict[str, Any]]:  # noqa: ANN001
    """Arrow table -> list of row dicts (column-wise, then zipped)."""
    if arrow is None or arrow.num_rows == 0:
        return []
    cols = {name: arrow.column(name).to_pylist() for name in arrow.column_names}
    return [
        {name: cols[name][i] for name in arrow.column_names}
        for i in range(arrow.num_rows)
    ]


def _query(table, where: str, columns: list[str], limit: int):  # noqa: ANN001
    """Run one scalar (non-vector) LanceDB lookup."""
    return (
        table.search()
        .where(where, prefilter=True)
        .select(columns)
        .limit(limit)
        .to_arrow()
    )


def _outcome(
    referenced: list[dict[str, Any]],
    *,
    direction: str | None,
    match_basis: str | None,
    outcome: str,
) -> dict[str, Any]:
    return {
        "referenced_chunks": referenced,
        "linkage": {
            "direction": direction,
            "match_basis": match_basis,
            "outcome": outcome,
        },
    }


def _shape(row: dict[str, Any]) -> dict[str, Any]:
    """Project a counterpart row into the served shape.

    ``body_text`` is returned RAW and length-capped here. The caller
    sanitizes and wraps it on the way out, so referenced bodies go
    through the identical Threat-2 path as the primary chunk body —
    doing it here would either duplicate that logic or (worse) skip it.
    """
    body = row.get("body_text") or ""
    truncated = len(body) > REF_BODY_MAX_CHARS
    out = {
        "chunk_id": row.get("chunk_id"),
        "kind": row.get("kind"),
        "theorem_label": row.get("theorem_label"),
        "theorem_name": row.get("theorem_name"),
        "section_path": list(row.get("section_path") or []),
        "body_text": body[:REF_BODY_MAX_CHARS] if truncated else body,
    }
    if truncated:
        # Absent-when-false, mirroring the top-level ``body_truncated``
        # convention rather than emitting a False on every counterpart.
        out["body_truncated"] = True
    return out


def resolve_referenced(table, chunk: dict[str, Any]) -> dict[str, Any]:  # noqa: ANN001
    """Resolve the statement/proof counterpart(s) of ``chunk``.

    Pure lookup over ``table``; never raises for a data-shaped miss —
    every "no answer" is one of the four §5a epistemic outcomes. An
    operational failure (a broken table handle) propagates to the
    caller, which is the separate lane §5b requires.
    """
    kind = chunk.get("kind") or ""
    paper_id = chunk.get("paper_id") or ""
    label = chunk.get("theorem_label")

    is_proof = kind == PROOF_KIND
    is_stmt = kind in PROOF_PAIRING_STMT_KINDS
    if not (is_proof or is_stmt):
        # section prose, definition, remark, textbook chunk: pairing is
        # not defined for this kind, which is a different statement from
        # "we looked and found nothing".
        return _outcome(
            [], direction=None, match_basis=None,
            outcome="unsupported-by-provider",
        )

    direction = "proof_to_stmt" if is_proof else "stmt_to_proof"
    if not paper_id:
        return _outcome(
            [], direction=direction, match_basis=None, outcome="not-in-corpus",
        )

    esc_paper = escape_lance_str(paper_id)

    # ---- Primary path: the theorem_label scalar join -------------------
    if label:
        esc_label = escape_lance_str(str(label))
        kind_pred = (
            f"kind != '{PROOF_KIND}'" if is_proof else f"kind = '{PROOF_KIND}'"
        )
        where = (
            f"paper_id = '{esc_paper}' AND {kind_pred} "
            f"AND theorem_label = '{esc_label}'"
        )
        rows = _rows(_query(table, where, _REF_COLUMNS, MAX_REFERENCED))
        # Self-exclusion: a statement and its proof never share a
        # chunk_id (ids are content hashes), but a defensive filter keeps
        # a degenerate row from being returned as its own counterpart.
        rows = [r for r in rows if r.get("chunk_id") != chunk.get("chunk_id")]
        if rows:
            return _outcome(
                [_shape(r) for r in rows],
                direction=direction,
                match_basis="theorem_label",
                outcome="resolved",
            )
        return _outcome(
            [], direction=direction, match_basis="theorem_label",
            outcome="not-in-corpus",
        )

    # ---- Fallback: section scope, uniqueness-gated ---------------------
    # theorem_label is NULL. Pull the paper's unlabeled chunks and decide
    # whether this section's pairing is unambiguous. See the module
    # docstring for why document adjacency is NOT available here.
    section_path = list(chunk.get("section_path") or [])
    if not section_path:
        # No label AND no section breadcrumb: nothing to scope by.
        return _outcome(
            [], direction=direction, match_basis=None, outcome="ambiguous",
        )

    where = f"paper_id = '{esc_paper}' AND theorem_label IS NULL"
    scope_rows = _rows(
        _query(table, where, _SCOPE_COLUMNS, MAX_SECTION_SCAN_ROWS)
    )
    if len(scope_rows) >= MAX_SECTION_SCAN_ROWS:
        # Truncated candidate set — uniqueness is unprovable from here.
        logger.warning(
            "proof-linkage section scan hit the %d-row cap for paper %s; "
            "returning ambiguous",
            MAX_SECTION_SCAN_ROWS,
            paper_id,
        )
        return _outcome(
            [], direction=direction, match_basis="section_scope",
            outcome="ambiguous",
        )

    in_scope = [
        r for r in scope_rows if list(r.get("section_path") or []) == section_path
    ]
    statements = [
        r for r in in_scope if (r.get("kind") or "") in PROOF_PAIRING_STMT_KINDS
    ]
    proofs = [r for r in in_scope if (r.get("kind") or "") == PROOF_KIND]

    # Uniqueness gate. The pairing is only well-determined when exactly
    # ONE unlabeled statement lives in this section — with two, "which
    # proof belongs to which theorem" is precisely the question the
    # discarded document ordering would have answered.
    if len(statements) != 1:
        return _outcome(
            [], direction=direction, match_basis="section_scope",
            outcome="ambiguous",
        )

    # Proof -> the one statement; statement -> every proof window in
    # scope (several unlabeled proofs alongside a single unlabeled
    # statement are windows of that statement's proof, not rival
    # candidates, so this stays unambiguous in both directions).
    counterparts = statements if is_proof else proofs
    if not counterparts:
        return _outcome(
            [], direction=direction, match_basis="section_scope",
            outcome="not-in-corpus",
        )

    ids = [str(r.get("chunk_id")) for r in counterparts if r.get("chunk_id")]
    ids = [i for i in ids if i != chunk.get("chunk_id")][:MAX_REFERENCED]
    if not ids:
        return _outcome(
            [], direction=direction, match_basis="section_scope",
            outcome="not-in-corpus",
        )

    id_list = ", ".join(f"'{escape_lance_str(i)}'" for i in ids)
    hydrated = _rows(
        _query(
            table,
            f"chunk_id IN ({id_list})",
            _REF_COLUMNS,
            MAX_REFERENCED,
        )
    )
    if not hydrated:
        return _outcome(
            [], direction=direction, match_basis="section_scope",
            outcome="not-in-corpus",
        )
    return _outcome(
        [_shape(r) for r in hydrated],
        direction=direction,
        match_basis="section_scope",
        outcome="resolved",
    )


__all__ = [
    "MAX_REFERENCED",
    "MAX_SECTION_SCAN_ROWS",
    "REF_BODY_MAX_CHARS",
    "PROOF_KIND",
    "PROOF_PAIRING_STMT_KINDS",
    "escape_lance_str",
    "resolve_referenced",
]
