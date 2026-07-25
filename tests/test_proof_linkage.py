"""retrieval-unlocks-m1 — statement <-> proof linkage on get_chunk.

Covers the milestone's four acceptance criteria plus the two guards that
keep the implementation honest as the corpus code moves:

* AC1 / t-scalar-proof-lookup — labeled stmt -> proof(s)
* AC2 / t-adjacency-fallback — unlabeled: resolve when the section scope
  is unambiguous, ABSTAIN (``ambiguous``) when two unlabeled theorems
  share a section. The AC's "without cross-matching the second theorem's
  proof" is met by returning nothing rather than by guessing, because
  document order is not recoverable from served data (see
  ``server/proof_linkage.py``'s module docstring).
* AC3 / t-reverse-proof-linkage — proof -> originating statement
* AC4 — a theorem whose proof is absent reports ``not-in-corpus``,
  distinct from an operational error and from a silent empty list
  (trust-language-policy.md §5d).
"""

from __future__ import annotations

import asyncio
from typing import Any

import pyarrow as pa
import pytest

from server.handlers.chunk import handle_get_chunk
from server.proof_linkage import (
    MAX_REFERENCED,
    MAX_SECTION_SCAN_ROWS,
    PROOF_PAIRING_STMT_KINDS,
    REF_BODY_MAX_CHARS,
    resolve_referenced,
)

_PAPER = "arxiv:2401.00001"


def _row(
    *,
    chunk_id: str,
    kind: str,
    theorem_label: str | None = None,
    section_path: list[str] | None = None,
    body_text: str = "body",
    paper_id: str = _PAPER,
) -> dict[str, Any]:
    return {
        "chunk_id": chunk_id,
        "paper_id": paper_id,
        "kind": kind,
        "section_path": section_path if section_path is not None else ["S1"],
        "theorem_label": theorem_label,
        "theorem_name": None,
        "body_text": body_text,
        # Columns get_chunk bracket-indexes on the primary-lookup path.
        # proof_linkage never selects these, but the handler-integration
        # tests drive the real handler, which does.
        "chunker_version": "cv0.1",
        "embedder_version": "bge-m3",
        "license": "arxiv-license",
        "preamble_ref": None,
    }


class _FakeTable:
    """A chunks table that answers the WHERE predicates proof_linkage
    builds, by filtering an in-memory row list.

    Deliberately parses the predicate rather than returning a canned
    result: a test that stubs the query away cannot catch a wrong
    predicate, which is most of what this module gets wrong.
    """

    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self.rows = rows
        self.queries: list[str] = []

    def search(self, *a: Any, **k: Any) -> _FakeBuilder:
        return _FakeBuilder(self)


class _FakeBuilder:
    def __init__(self, table: _FakeTable) -> None:
        self._t = table
        self._where = ""
        self._cols: list[str] | None = None
        self._limit = 10_000

    def where(self, pred: str, **k: Any) -> _FakeBuilder:
        self._where = pred
        self._t.queries.append(pred)
        return self

    def select(self, cols: list[str]) -> _FakeBuilder:
        self._cols = cols
        return self

    def limit(self, n: int) -> _FakeBuilder:
        self._limit = n
        return self

    def _match(self, row: dict[str, Any]) -> bool:
        w = self._where
        for clause in w.split(" AND "):
            clause = clause.strip()
            if clause.startswith("paper_id = '"):
                if row["paper_id"] != clause[len("paper_id = '"):-1]:
                    return False
            elif clause.startswith("kind = '"):
                if row["kind"] != clause[len("kind = '"):-1]:
                    return False
            elif clause.startswith("kind != '"):
                if row["kind"] == clause[len("kind != '"):-1]:
                    return False
            elif clause.startswith("theorem_label = '"):
                want = clause[len("theorem_label = '"):-1].replace("''", "'")
                if row["theorem_label"] != want:
                    return False
            elif clause == "theorem_label IS NULL":
                if row["theorem_label"] is not None:
                    return False
            elif clause.startswith("chunk_id = '"):
                # get_chunk's own primary lookup, not a linkage query.
                if row["chunk_id"] != clause[len("chunk_id = '"):-1]:
                    return False
            elif clause.startswith("chunk_id IN ("):
                inner = clause[len("chunk_id IN ("):-1]
                ids = {s.strip().strip("'") for s in inner.split(",")}
                if row["chunk_id"] not in ids:
                    return False
            else:
                raise AssertionError(f"unhandled predicate clause: {clause!r}")
        return True

    def to_arrow(self):
        hits = [r for r in self._t.rows if self._match(r)][: self._limit]
        # No .select() => every column, mirroring a real table scan. The
        # handler's primary lookup takes that path and bracket-indexes
        # columns proof_linkage never asks for.
        if self._cols is not None:
            cols = self._cols
        else:
            cols = list(self._t.rows[0]) if self._t.rows else []
        if not hits:
            return pa.table({c: pa.array([], type=_col_type(c)) for c in cols})
        return pa.table({
            c: pa.array([h.get(c) for h in hits], type=_col_type(c))
            for c in cols
        })


def _col_type(name: str):
    return pa.list_(pa.utf8()) if name == "section_path" else pa.utf8()


# ===========================================================================
# AC1 — labeled statement resolves to its proof window(s)
# ===========================================================================


class TestLabeledStatementToProof:
    def test_returns_proof_sharing_paper_and_label(self) -> None:
        t = _FakeTable([
            _row(chunk_id="c-stmt", kind="stmt", theorem_label="Thmthm1"),
            _row(chunk_id="c-proof", kind="proof", theorem_label="Thmthm1"),
            _row(chunk_id="c-other", kind="proof", theorem_label="Thmthm2"),
        ])
        out = resolve_referenced(t, t.rows[0])
        assert out["linkage"] == {
            "direction": "stmt_to_proof",
            "match_basis": "theorem_label",
            "outcome": "resolved",
        }
        assert [c["chunk_id"] for c in out["referenced_chunks"]] == ["c-proof"]

    def test_multiple_proof_windows_all_returned(self) -> None:
        """A long proof is windowed at ingest; every window belongs."""
        t = _FakeTable([
            _row(chunk_id="c-stmt", kind="stmt", theorem_label="L1"),
            _row(chunk_id="p1", kind="proof", theorem_label="L1"),
            _row(chunk_id="p2", kind="proof", theorem_label="L1"),
        ])
        out = resolve_referenced(t, t.rows[0])
        assert {c["chunk_id"] for c in out["referenced_chunks"]} == {"p1", "p2"}

    def test_other_papers_never_match(self) -> None:
        t = _FakeTable([
            _row(chunk_id="c-stmt", kind="stmt", theorem_label="L1"),
            _row(
                chunk_id="foreign", kind="proof", theorem_label="L1",
                paper_id="arxiv:2402.99999",
            ),
        ])
        out = resolve_referenced(t, t.rows[0])
        assert out["linkage"]["outcome"] == "not-in-corpus"
        assert out["referenced_chunks"] == []

    @pytest.mark.parametrize("kind", sorted(PROOF_PAIRING_STMT_KINDS))
    def test_every_pairing_kind_resolves(self, kind: str) -> None:
        t = _FakeTable([
            _row(chunk_id="s", kind=kind, theorem_label="L1"),
            _row(chunk_id="p", kind="proof", theorem_label="L1"),
        ])
        out = resolve_referenced(t, t.rows[0])
        assert out["linkage"]["outcome"] == "resolved"


# ===========================================================================
# AC3 — reverse direction
# ===========================================================================


class TestProofToStatement:
    def test_proof_resolves_to_originating_statement(self) -> None:
        t = _FakeTable([
            _row(chunk_id="c-stmt", kind="lemma", theorem_label="L7"),
            _row(chunk_id="c-proof", kind="proof", theorem_label="L7"),
        ])
        out = resolve_referenced(t, t.rows[1])
        assert out["linkage"]["direction"] == "proof_to_stmt"
        assert out["linkage"]["outcome"] == "resolved"
        assert [c["chunk_id"] for c in out["referenced_chunks"]] == ["c-stmt"]

    def test_proof_does_not_return_sibling_proof_windows(self) -> None:
        t = _FakeTable([
            _row(chunk_id="s", kind="stmt", theorem_label="L7"),
            _row(chunk_id="p1", kind="proof", theorem_label="L7"),
            _row(chunk_id="p2", kind="proof", theorem_label="L7"),
        ])
        out = resolve_referenced(t, t.rows[1])
        assert [c["chunk_id"] for c in out["referenced_chunks"]] == ["s"]


# ===========================================================================
# AC2 — unlabeled: resolve only when unambiguous, else abstain
# ===========================================================================


class TestSectionScopeFallback:
    def test_single_unlabeled_theorem_in_section_resolves(self) -> None:
        t = _FakeTable([
            _row(chunk_id="s", kind="stmt", section_path=["Intro"]),
            _row(chunk_id="p", kind="proof", section_path=["Intro"]),
        ])
        out = resolve_referenced(t, t.rows[0])
        assert out["linkage"] == {
            "direction": "stmt_to_proof",
            "match_basis": "section_scope",
            "outcome": "resolved",
        }
        assert [c["chunk_id"] for c in out["referenced_chunks"]] == ["p"]

    def test_two_unlabeled_theorems_in_one_section_abstain(self) -> None:
        """THE acceptance case: no cross-matching. Document order is not
        recoverable from served data, so the honest answer is 'ambiguous'
        rather than a coin flip presented as a lookup."""
        t = _FakeTable([
            _row(chunk_id="s1", kind="stmt", section_path=["S2"]),
            _row(chunk_id="p1", kind="proof", section_path=["S2"]),
            _row(chunk_id="s2", kind="stmt", section_path=["S2"]),
            _row(chunk_id="p2", kind="proof", section_path=["S2"]),
        ])
        out = resolve_referenced(t, t.rows[0])
        assert out["linkage"]["outcome"] == "ambiguous"
        assert out["referenced_chunks"] == []
        # Specifically: it did NOT hand back the other theorem's proof.
        assert "p2" not in str(out)

    def test_different_sections_do_not_interfere(self) -> None:
        t = _FakeTable([
            _row(chunk_id="s1", kind="stmt", section_path=["S1"]),
            _row(chunk_id="p1", kind="proof", section_path=["S1"]),
            _row(chunk_id="s2", kind="stmt", section_path=["S2"]),
            _row(chunk_id="p2", kind="proof", section_path=["S2"]),
        ])
        out = resolve_referenced(t, t.rows[0])
        assert out["linkage"]["outcome"] == "resolved"
        assert [c["chunk_id"] for c in out["referenced_chunks"]] == ["p1"]

    def test_unlabeled_statement_with_no_proof_is_not_in_corpus(self) -> None:
        t = _FakeTable([_row(chunk_id="s", kind="stmt", section_path=["S1"])])
        out = resolve_referenced(t, t.rows[0])
        assert out["linkage"]["outcome"] == "not-in-corpus"

    def test_empty_section_path_abstains(self) -> None:
        t = _FakeTable([
            _row(chunk_id="s", kind="stmt", section_path=[]),
            _row(chunk_id="p", kind="proof", section_path=[]),
        ])
        out = resolve_referenced(t, t.rows[0])
        assert out["linkage"]["outcome"] == "ambiguous"

    def test_labeled_rows_never_pollute_the_unlabeled_scope(self) -> None:
        """A labeled theorem in the same section is not a rival candidate
        for an unlabeled one — it owns its proof via theorem_label."""
        t = _FakeTable([
            _row(chunk_id="s-unlab", kind="stmt", section_path=["S1"]),
            _row(chunk_id="p-unlab", kind="proof", section_path=["S1"]),
            _row(
                chunk_id="s-lab", kind="stmt", section_path=["S1"],
                theorem_label="L9",
            ),
            _row(
                chunk_id="p-lab", kind="proof", section_path=["S1"],
                theorem_label="L9",
            ),
        ])
        out = resolve_referenced(t, t.rows[0])
        assert out["linkage"]["outcome"] == "resolved"
        assert [c["chunk_id"] for c in out["referenced_chunks"]] == ["p-unlab"]


# ===========================================================================
# AC4 — abstention is distinct from empty, and from an unsupported kind
# ===========================================================================


class TestAbstentionOutcomes:
    def test_labeled_theorem_without_proof_reports_not_in_corpus(self) -> None:
        t = _FakeTable([_row(chunk_id="s", kind="stmt", theorem_label="L1")])
        out = resolve_referenced(t, t.rows[0])
        assert out["linkage"]["outcome"] == "not-in-corpus"
        assert out["linkage"]["match_basis"] == "theorem_label"
        assert out["referenced_chunks"] == []

    @pytest.mark.parametrize(
        "kind", ["section", "definition", "remark", "example", "textbook"]
    )
    def test_non_pairing_kinds_report_unsupported(self, kind: str) -> None:
        """'We do not pair this kind' is a different claim from 'we
        looked and found nothing' — §5a keeps them distinct."""
        t = _FakeTable([_row(chunk_id="c", kind=kind, theorem_label="L1")])
        out = resolve_referenced(t, t.rows[0])
        assert out["linkage"]["outcome"] == "unsupported-by-provider"
        assert out["linkage"]["direction"] is None

    def test_outcomes_are_drawn_from_the_policy_vocabulary(self) -> None:
        allowed = {
            "resolved", "not-in-corpus", "ambiguous", "unsupported-by-provider",
        }
        cases = [
            _FakeTable([_row(chunk_id="c", kind="section")]),
            _FakeTable([_row(chunk_id="c", kind="stmt", theorem_label="L")]),
            _FakeTable([_row(chunk_id="c", kind="stmt", section_path=[])]),
        ]
        for t in cases:
            assert resolve_referenced(t, t.rows[0])["linkage"]["outcome"] in allowed


# ===========================================================================
# Guards
# ===========================================================================


class TestGuards:
    def test_stmt_kinds_match_the_chunker(self) -> None:
        """PROOF_PAIRING_STMT_KINDS is a hot-path literal; this is the
        pin that catches drift when the chunker's environment tables
        change. Without it, a new theorem-like environment would silently
        stop resolving proofs."""
        from ingest.chunker import _THEOREM_ENV_KINDS, _THEOREM_LIKE_ENVNAMES

        derived = {
            _THEOREM_ENV_KINDS.get(env, "stmt") for env in _THEOREM_LIKE_ENVNAMES
        }
        assert derived == set(PROOF_PAIRING_STMT_KINDS)

    def test_theorem_label_quotes_are_escaped(self) -> None:
        """theorem_label is author-controlled text that reached us through
        LaTeXML. It is interpolated into a WHERE clause, so it must be
        escaped even though it came out of our own table."""
        t = _FakeTable([
            _row(chunk_id="s", kind="stmt", theorem_label="O'Brien"),
            _row(chunk_id="p", kind="proof", theorem_label="O'Brien"),
        ])
        out = resolve_referenced(t, t.rows[0])
        assert any("O''Brien" in q for q in t.queries), t.queries
        assert out["linkage"]["outcome"] == "resolved"

    def test_referenced_bodies_are_length_capped(self) -> None:
        t = _FakeTable([
            _row(chunk_id="s", kind="stmt", theorem_label="L1"),
            _row(
                chunk_id="p", kind="proof", theorem_label="L1",
                body_text="x" * (REF_BODY_MAX_CHARS + 500),
            ),
        ])
        ref = resolve_referenced(t, t.rows[0])["referenced_chunks"][0]
        assert len(ref["body_text"]) == REF_BODY_MAX_CHARS
        assert ref["body_truncated"] is True

    def test_counterpart_count_is_bounded(self) -> None:
        rows = [_row(chunk_id="s", kind="stmt", theorem_label="L1")]
        rows += [
            _row(chunk_id=f"p{i}", kind="proof", theorem_label="L1")
            for i in range(MAX_REFERENCED + 20)
        ]
        t = _FakeTable(rows)
        out = resolve_referenced(t, rows[0])
        assert len(out["referenced_chunks"]) == MAX_REFERENCED

    def test_truncated_section_scan_abstains(self) -> None:
        """A capped candidate set cannot prove uniqueness, so it must not
        claim it."""
        rows = [_row(chunk_id="s0", kind="stmt", section_path=["S1"])]
        rows += [
            _row(chunk_id=f"x{i}", kind="proof", section_path=["Sother"])
            for i in range(MAX_SECTION_SCAN_ROWS + 5)
        ]
        t = _FakeTable(rows)
        out = resolve_referenced(t, rows[0])
        assert out["linkage"]["outcome"] == "ambiguous"


# ===========================================================================
# Handler integration
# ===========================================================================


@pytest.fixture
def wired(monkeypatch: pytest.MonkeyPatch):
    """Install a Resources whose chunks_table is a _FakeTable, so
    get_chunk exercises the real linkage path end to end."""
    from server.tools import reset_resources_for_tests, set_resources

    holder: dict[str, Any] = {"table": None}

    class _Proxy:
        def search(self, *a: Any, **k: Any):
            return holder["table"].search()

    class _Cfg:
        result_byte_cap = 256 * 1024

    class _Info:
        version = 101

    class _Res:
        def __init__(self) -> None:
            self.config = _Cfg()
            self.chunks_table = _Proxy()
            self.corpus_info = _Info()
            self.degraded = None

    set_resources(_Res())  # type: ignore[arg-type]
    yield holder
    reset_resources_for_tests()


class TestHandlerIntegration:
    _SID = "arxiv:2401.00001:0123456789abcdef"

    def test_include_referenced_false_leaves_payload_unchanged(
        self, wired
    ) -> None:
        wired["table"] = _FakeTable([
            _row(chunk_id=self._SID, kind="stmt", theorem_label="L1"),
            _row(chunk_id="p", kind="proof", theorem_label="L1"),
        ])
        out = asyncio.run(handle_get_chunk(chunk_id=self._SID))
        body = out.get("structuredContent", out)
        assert body["include_referenced_applied"] is False
        assert "referenced_chunks" not in body
        assert "linkage" not in body

    def test_include_referenced_true_returns_wrapped_proof(self, wired) -> None:
        wired["table"] = _FakeTable([
            _row(chunk_id=self._SID, kind="stmt", theorem_label="L1"),
            _row(
                chunk_id="p", kind="proof", theorem_label="L1",
                body_text="PROOF BODY",
            ),
        ])
        out = asyncio.run(
            handle_get_chunk(chunk_id=self._SID, include_referenced=True)
        )
        body = out.get("structuredContent", out)
        assert body["include_referenced_applied"] is True
        assert body["linkage"]["outcome"] == "resolved"
        ref = body["referenced_chunks"][0]
        # Threat 2: referenced bodies take the same wrap path as the
        # primary body — an unwrapped one would be a hole in the fence.
        assert "<retrieved_chunk" in ref["body_text"]
        assert "PROOF BODY" in ref["body_text"]

    def test_no_unused_args_field(self, wired) -> None:
        """agent-platform-t-inert-args-cleanup (#82): include_equations
        was the last accepted-and-ignored get_chunk arg. With it removed,
        the whole ``unused_args`` machinery is gone — the response no
        longer carries that field at all."""
        wired["table"] = _FakeTable([
            _row(chunk_id=self._SID, kind="stmt", theorem_label="L1"),
        ])
        out = asyncio.run(
            handle_get_chunk(chunk_id=self._SID, include_referenced=True)
        )
        body = out.get("structuredContent", out)
        assert "unused_args" not in body
        assert "include_equations_applied" not in body
