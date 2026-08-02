"""The four tools admit one identifier domain — chris-dare-dev/arXMCP#209.

``search_papers`` validates with ``is_valid_paper_id`` (the union) and so
emits ``textbook:<slug>`` paper_ids. ``get_paper``, ``get_definitions`` and
``find_lemma_by_name`` gated on ``is_valid_arxiv_paper_id`` and answered one
with ``ValueError: ... does not match the arXiv id format``.

The server rejected an identifier it had emitted itself moments earlier, on
the canonical documented workflow, and called it malformed. Two separate
questions had been collapsed into one boolean — CLAUDE.md §4.9 rule 2 is
explicit that ``invalid-input`` and ``unsupported-by-provider`` must not
share a token.

These tests pin both halves: the union domain is admitted everywhere, and
the abstention path exists, is typed distinctly, and is reachable.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from ingest.identifiers import (
    SOURCE_KIND_ARXIV,
    SOURCE_KIND_TEXTBOOK,
    is_valid_paper_id,
    paper_id_source_kind,
)
from server.handlers import definitions as definitions_mod
from server.handlers import lemma as lemma_mod
from server.handlers import paper as paper_mod
from server.source_kinds import (
    ALL_SOURCE_KINDS,
    UNSUPPORTED_BY_PROVIDER,
    UnsupportedSourceKind,
    admit_paper_id,
    unsupported_outcome,
)

REPO_ROOT = Path(__file__).resolve().parent.parent

#: A well-formed id of each kind. The textbook one is the shape
#: ``search_papers`` emits.
TEXTBOOK_ID = "textbook:shimura-varieties"
ARXIV_NEW = "2401.00001"
ARXIV_OLD = "hep-th/0001234"

#: The three follow-up handlers, with the set each declares.
FOLLOW_UP_HANDLERS = (
    ("get_paper", paper_mod),
    ("get_definitions", definitions_mod),
    ("find_lemma_by_name", lemma_mod),
)


class TestOneIdentifierDomain:
    """AC1 — all four tools accept the same identifier domain."""

    @pytest.mark.parametrize("tool_name,module", FOLLOW_UP_HANDLERS)
    def test_handler_declares_its_supported_kinds(self, tool_name, module):
        supported = getattr(module, "SUPPORTED_SOURCE_KINDS", None)
        assert supported is not None, (
            f"{tool_name} must declare SUPPORTED_SOURCE_KINDS so its domain "
            "is a stated fact rather than an implicit consequence of which "
            "validator it happened to import (arXMCP#209)"
        )
        assert isinstance(supported, frozenset)

    @pytest.mark.parametrize("tool_name,module", FOLLOW_UP_HANDLERS)
    def test_textbook_ids_are_admitted(self, tool_name, module):
        """THE #209 regression guard.

        Each of these raised ValueError on this exact input before the fix.
        """
        kind = admit_paper_id(TEXTBOOK_ID, module.SUPPORTED_SOURCE_KINDS)
        assert kind == SOURCE_KIND_TEXTBOOK

    @pytest.mark.parametrize("tool_name,module", FOLLOW_UP_HANDLERS)
    @pytest.mark.parametrize("arxiv_id", [ARXIV_NEW, ARXIV_OLD])
    def test_arxiv_ids_still_admitted(self, tool_name, module, arxiv_id):
        """Widening must not have cost the original domain."""
        assert (
            admit_paper_id(arxiv_id, module.SUPPORTED_SOURCE_KINDS)
            == SOURCE_KIND_ARXIV
        )

    def test_no_follow_up_handler_gates_on_the_arxiv_only_validator(self):
        """Pin the cause, not just the symptom.

        A future edit could re-import ``is_valid_arxiv_paper_id`` into one of
        these handlers and reintroduce exactly this bug for one tool while
        the other two stayed correct — which is how it shipped the first
        time. Source-level so it fires regardless of call ordering.
        """
        offenders = []
        for tool_name, module in FOLLOW_UP_HANDLERS:
            src = Path(module.__file__).read_text(encoding="utf-8")
            if "is_valid_arxiv_paper_id" in src:
                offenders.append(tool_name)
        assert not offenders, (
            f"{offenders} gate on the arXiv-only validator again; they must "
            "admit the union and abstain per source kind (arXMCP#209)"
        )

    def test_search_papers_still_emits_the_union(self):
        """The producer half. If search_papers ever narrowed to arXiv-only,
        these tests would pass while the workflow silently lost textbooks."""
        src = (
            REPO_ROOT / "server" / "handlers" / "search.py"
        ).read_text(encoding="utf-8")
        assert "is_valid_paper_id" in src
        assert is_valid_paper_id(TEXTBOOK_ID)


class TestSearchToFollowUpWalk:
    """AC2 — walk ``search_papers`` -> each follow-up tool with a
    textbook-sourced paper_id and assert no spurious rejection."""

    def test_every_id_search_can_emit_is_admitted_downstream(self):
        """The producer's domain must be a subset of every consumer's.

        Derived from the shared regex rather than a hand-listed sample, so a
        future fourth id form cannot pass this by being forgotten.
        """
        emitted = [ARXIV_NEW, ARXIV_OLD, TEXTBOOK_ID]
        for pid in emitted:
            assert is_valid_paper_id(pid), f"{pid} is not search-emittable"
            for tool_name, module in FOLLOW_UP_HANDLERS:
                try:
                    admit_paper_id(pid, module.SUPPORTED_SOURCE_KINDS)
                except (ValueError, UnsupportedSourceKind) as exc:
                    pytest.fail(
                        f"{tool_name} rejected {pid!r}, which search_papers "
                        f"emits: {type(exc).__name__}: {exc}"
                    )

    @pytest.mark.parametrize("tool_name,module", FOLLOW_UP_HANDLERS)
    def test_handler_body_routes_textbook_ids_past_the_gate(
        self, tool_name, module
    ):
        """The declared set is only meaningful if the handler consults it.

        Parses the handler for an ``admit_paper_id`` call — a module could
        declare SUPPORTED_SOURCE_KINDS and never use it, and every assertion
        above would still pass.
        """
        tree = ast.parse(Path(module.__file__).read_text(encoding="utf-8"))
        called = {
            node.func.id
            for node in ast.walk(tree)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
        }
        assert "admit_paper_id" in called, (
            f"{tool_name} declares SUPPORTED_SOURCE_KINDS but never calls "
            "admit_paper_id, so the declaration is inert"
        )


class TestAbstentionIsDistinctFromInvalidInput:
    """AC3 — an unsupported source kind returns ``unsupported-by-provider``,
    kept distinct from ``invalid-input`` (CLAUDE.md §4.9 rule 2)."""

    def test_malformed_id_raises_value_error(self):
        for bad in ["", "not an id", "../etc/passwd", "foo:bar:baz", "2401.1 "]:
            with pytest.raises(ValueError):
                admit_paper_id(bad)

    def test_unsupported_kind_raises_a_different_type(self):
        """The whole point. A tool that cannot serve textbooks must not
        report a textbook id as malformed."""
        with pytest.raises(UnsupportedSourceKind) as caught:
            admit_paper_id(TEXTBOOK_ID, frozenset({SOURCE_KIND_ARXIV}))
        assert caught.value.source_kind == SOURCE_KIND_TEXTBOOK
        # Not a ValueError subclass — callers keying on ValueError for
        # bad input must not swallow an abstention.
        assert not isinstance(caught.value, ValueError)

    def test_abstention_payload_names_the_outcome(self):
        exc = UnsupportedSourceKind(
            TEXTBOOK_ID, SOURCE_KIND_TEXTBOOK, frozenset({SOURCE_KIND_ARXIV})
        )
        payload = unsupported_outcome(exc)
        assert payload["outcome"] == UNSUPPORTED_BY_PROVIDER
        assert payload["unsupported_source_kind"] == SOURCE_KIND_TEXTBOOK

    def test_outcome_token_matches_the_policy_vocabulary(self):
        """§4.9 names the four epistemic outcomes literally; this is one of
        them, spelled the same way ``server/proof_linkage.py`` spells it."""
        assert UNSUPPORTED_BY_PROVIDER == "unsupported-by-provider"
        linkage = (
            REPO_ROOT / "server" / "proof_linkage.py"
        ).read_text(encoding="utf-8")
        assert UNSUPPORTED_BY_PROVIDER in linkage


class TestSourceKindClassification:
    """The shape->kind mapping the admission gate is built on."""

    @pytest.mark.parametrize(
        "pid,expected",
        [
            (ARXIV_NEW, SOURCE_KIND_ARXIV),
            (ARXIV_OLD, SOURCE_KIND_ARXIV),
            ("2401.00001v3", SOURCE_KIND_ARXIV),
            (TEXTBOOK_ID, SOURCE_KIND_TEXTBOOK),
            ("textbook:lnm-1337", SOURCE_KIND_TEXTBOOK),
            ("not an id", None),
            ("", None),
        ],
    )
    def test_classification(self, pid, expected):
        assert paper_id_source_kind(pid) == expected

    def test_kinds_match_the_chunks_table_enum(self):
        """The admission vocabulary and the storage enum must not drift —
        six independent encodings of source-type knowledge is the root cause
        the issue records, and this pins two of them together."""
        from server.handlers.search import _VALID_SOURCE_KIND_FILTER_VALUES

        assert ALL_SOURCE_KINDS == _VALID_SOURCE_KIND_FILTER_VALUES
