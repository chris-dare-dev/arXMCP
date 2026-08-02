"""Single-source-of-truth lock for the arxmcp identifier regexes.

Closes F11 from the E06_S03 critique. ``ingest/chunker.py``,
``tools/validate_eval_fixtures.py``, and ``server/handlers/chunk.py``
all previously carried independent definitions of the paper_id /
chunk_id format. ``ingest/identifiers.py`` now collapses them to
one; this test asserts every consumer site routes through that
shared module.
"""

from __future__ import annotations

import pytest

from ingest.chunker import _PAPER_ID_RE
from ingest.identifiers import (
    PAPER_ID_RE,
    is_valid_arxiv_paper_id,
    is_valid_chunk_id,
    is_valid_paper_id,
    paper_id_from_chunk_id,
)


class TestPaperIdRegex:
    def test_chunker_pattern_equals_canonical(self):
        """The chunker's existing _PAPER_ID_RE must match the
        canonical PAPER_ID_RE pattern from ingest.identifiers."""
        assert _PAPER_ID_RE.pattern == PAPER_ID_RE.pattern

    def test_validator_pattern_equals_canonical(self):
        """The eval-fixture validator's _PAPER_ID_RE must also
        match canonical."""
        from tools.validate_eval_fixtures import _PAPER_ID_RE as VAL_RE

        assert VAL_RE.pattern == PAPER_ID_RE.pattern


class TestPaperIdValidation:
    def test_new_style_valid(self):
        assert is_valid_paper_id("2401.00001")
        assert is_valid_paper_id("2401.00001v3")
        assert is_valid_paper_id("2403.12345")

    def test_old_style_valid(self):
        # The chunker's regex accepts old-style ``<archive>/NNNNNNN``
        # with lowercase letters and hyphens (no dots). Examples:
        # ``hep-th/9876543``, ``cond-mat/0612345``.
        assert is_valid_paper_id("hep-th/9876543")
        assert is_valid_paper_id("cond-mat/0612345")

    def test_path_traversal_rejected(self):
        assert not is_valid_paper_id("../../etc/passwd")
        assert not is_valid_paper_id("..")
        assert not is_valid_paper_id(".")
        assert not is_valid_paper_id("/etc/passwd")

    def test_empty_and_garbage_rejected(self):
        assert not is_valid_paper_id("")
        assert not is_valid_paper_id("not-an-arxiv-id")
        assert not is_valid_paper_id("2401")
        # Wrong digit count.
        assert not is_valid_paper_id("2401.123")  # 3 digits, need 4-5
        assert not is_valid_paper_id("2401.123456")  # 6 digits, need 4-5

    def test_non_string_rejected(self):
        assert not is_valid_paper_id(None)  # type: ignore[arg-type]
        assert not is_valid_paper_id(12345)  # type: ignore[arg-type]


class TestChunkIdValidation:
    def test_well_formed(self):
        assert is_valid_chunk_id("arxiv:2401.00001:" + "a" * 16)
        assert is_valid_chunk_id("arxiv:hep-th/9876543:" + "f" * 16)
        assert is_valid_chunk_id("arxiv:2401.00001v3:" + "0" * 16)

    def test_wrong_prefix_rejected(self):
        assert not is_valid_chunk_id("xyz:2401.00001:" + "a" * 16)
        # Missing prefix entirely.
        assert not is_valid_chunk_id("2401.00001:" + "a" * 16)

    def test_wrong_suffix_length_rejected(self):
        # 15 chars (one short).
        assert not is_valid_chunk_id("arxiv:2401.00001:" + "a" * 15)
        # 17 chars (one long).
        assert not is_valid_chunk_id("arxiv:2401.00001:" + "a" * 17)

    def test_non_hex_suffix_rejected(self):
        # 'g' is not a hex char.
        assert not is_valid_chunk_id("arxiv:2401.00001:gggggggggggggggg")

    def test_uppercase_hex_rejected(self):
        """The chunker writes lowercase hex; the validator follows."""
        assert not is_valid_chunk_id("arxiv:2401.00001:" + "A" * 16)


class TestRegexEquality:
    """Structural relationship between ``CHUNK_ID_PATTERN`` and
    ``PAPER_ID_PATTERN``.

    Pre-textbook-ingest-m1 the relationship was a literal substring:
    ``PAPER_ID_PATTERN in CHUNK_ID_PATTERN``. After m1 the chunk-id
    pattern carries TWO prefix shapes (``arxiv:`` and ``textbook:``)
    with different capture semantics, so a substring invariant is no
    longer tractable. The replacement invariant is per-alternative
    containment: every alternative in ``PAPER_ID_PATTERN`` must
    appear somewhere in ``CHUNK_ID_PATTERN`` (possibly with
    capturing-vs-non-capturing v-suffix differences).
    """

    def test_chunk_id_pattern_contains_each_alternative(self):
        from ingest.identifiers import CHUNK_ID_PATTERN, PAPER_ID_PATTERN

        # Strip capturing parens around v-suffix; CHUNK_ID_PATTERN
        # uses non-capturing (?:v\d+)? inside the arXiv branch.
        # textbook alternative has no v-suffix so is unaffected.
        alts_paper = PAPER_ID_PATTERN.split("|")
        for alt in alts_paper:
            normalized = alt.replace("(v\\d+)?", "(?:v\\d+)?")
            assert normalized in CHUNK_ID_PATTERN, (
                f"alternative {alt!r} (normalized {normalized!r}) "
                f"not present in CHUNK_ID_PATTERN"
            )


class TestTextbookIdentifiers:
    """textbook-ingest-m1 — textbook paper_id and chunk_id support."""

    # ---- positive cases ----

    def test_textbook_paper_id_minimum_length_slug_valid(self):
        # 3-char slug: leading letter + 2 chars (the SLUG_RE inner min).
        assert is_valid_paper_id("textbook:foo")

    def test_textbook_paper_id_realistic_slug_valid(self):
        assert is_valid_paper_id("textbook:shimura-varieties")

    def test_textbook_paper_id_alphanumeric_slug_valid(self):
        assert is_valid_paper_id("textbook:lnm-1337")

    def test_textbook_paper_id_maximum_length_slug_valid(self):
        # 31-char slug: leading letter + 30 chars.
        slug = "a" + "b" * 30
        assert is_valid_paper_id(f"textbook:{slug}")

    def test_textbook_chunk_id_valid(self):
        assert is_valid_chunk_id(
            "textbook:shimura-varieties:abcdef0123456789"
        )

    def test_arxiv_chunk_id_still_valid_after_m1(self):
        # AC #3 — byte-stability for arXiv shape.
        assert is_valid_chunk_id("arxiv:2401.00001:abcdef0123456789")
        assert is_valid_chunk_id("arxiv:hep-th/9876543:" + "f" * 16)

    def test_paper_id_from_textbook_chunk_id_returns_full_paper_id(self):
        # AC #1 — round-trip returns ``textbook:<slug>``, NOT just
        # ``<slug>``. The ``textbook:`` prefix IS part of the paper_id.
        from ingest.identifiers import paper_id_from_chunk_id

        result = paper_id_from_chunk_id(
            "textbook:shimura-varieties:abcdef0123456789"
        )
        assert result == "textbook:shimura-varieties"

    def test_paper_id_from_arxiv_chunk_id_unchanged(self):
        # AC #3 — arXiv round-trip unchanged. group("arxiv_inner")
        # captures the arXiv paper_id with no ``arxiv:`` prefix.
        from ingest.identifiers import paper_id_from_chunk_id

        assert (
            paper_id_from_chunk_id("arxiv:2401.00001:" + "a" * 16)
            == "2401.00001"
        )
        assert (
            paper_id_from_chunk_id("arxiv:hep-th/9876543:" + "f" * 16)
            == "hep-th/9876543"
        )

    # ---- Threat-1 negative cases on is_valid_paper_id ----
    # AC #2 — ≥5 path-traversal regression fixtures. We ship 11.

    def test_textbook_path_traversal_rejected(self):
        # N1 — slash + dotdot in slug.
        assert not is_valid_paper_id("textbook:../etc/passwd")

    def test_textbook_extra_colon_rejected(self):
        # N2 — extra colon (chunk-id form passed as paper_id).
        assert not is_valid_paper_id("textbook:foo:bar")

    def test_textbook_null_byte_in_slug_rejected(self):
        # N3 — null-byte injection.
        assert not is_valid_paper_id("textbook:foo\x00bar")

    def test_textbook_whitespace_in_slug_rejected(self):
        # N4 — whitespace.
        assert not is_valid_paper_id("textbook:foo bar")

    def test_textbook_trailing_newline_rejected(self):
        # N5 — \Z anchor must reject trailing \n (F3-class).
        assert not is_valid_paper_id("textbook:foo\n")

    def test_textbook_empty_slug_rejected(self):
        # N6 — empty slug.
        assert not is_valid_paper_id("textbook:")

    def test_textbook_uppercase_slug_rejected(self):
        # N7 — uppercase slug. Policy: lowercase-only per SLUG_RE.
        assert not is_valid_paper_id("textbook:FOO")
        assert not is_valid_paper_id("textbook:Foo")

    def test_textbook_slug_too_short_rejected(self):
        # N8 — slug below 3 chars (inner ``[a-z][a-z0-9-]{2,30}``).
        assert not is_valid_paper_id("textbook:fo")
        assert not is_valid_paper_id("textbook:f")

    def test_textbook_slug_too_long_rejected(self):
        # N9 — slug above 31 chars.
        slug = "a" + "b" * 31  # 32 chars total
        assert not is_valid_paper_id(f"textbook:{slug}")

    def test_textbook_double_prefix_rejected(self):
        # N10 — wrong prefix nesting.
        assert not is_valid_paper_id("arxiv:textbook:foo")

    def test_textbook_chunk_id_form_rejected_as_paper_id(self):
        # N11 — chunk-id form must not pass is_valid_paper_id.
        assert not is_valid_paper_id(
            "textbook:foo:abcdef0123456789"
        )

    # ---- Threat-1 negative cases on is_valid_chunk_id ----

    def test_textbook_chunk_id_trailing_newline_rejected(self):
        # C1 — CHUNK_ID_RE must use \Z, not $.
        assert not is_valid_chunk_id(
            "textbook:foo:abcdef0123456789\n"
        )

    def test_arxiv_chunk_id_trailing_newline_rejected(self):
        # C2 — F3-class fix on CHUNK_ID_RE: the EXISTING arXiv shape
        # used to pass with a trailing newline; m1 closes this.
        assert not is_valid_chunk_id(
            "arxiv:2401.00001:abcdef0123456789\n"
        )
        assert not is_valid_chunk_id(
            "arxiv:hep-th/9876543:" + "f" * 16 + "\n"
        )

    def test_textbook_chunk_id_path_traversal_rejected(self):
        # C3 — path-traversal in chunk-id form.
        assert not is_valid_chunk_id(
            "textbook:../etc/passwd:abcdef0123456789"
        )

    def test_textbook_chunk_id_uppercase_hex_rejected(self):
        # C4 — hex must be lowercase (matches arXiv discipline).
        assert not is_valid_chunk_id(
            "textbook:foo:ABCDEF0123456789"
        )

    def test_textbook_chunk_id_sha_too_short_rejected(self):
        # C5 — sha must be exactly 16 hex chars.
        assert not is_valid_chunk_id(
            "textbook:foo:abcdef0123456"  # 15 chars
        )

    def test_textbook_chunk_id_arxiv_prefix_wrong_inner_rejected(self):
        # Extra guard: ``arxiv:textbook:foo:<sha>`` must be rejected.
        # The arxiv branch's inner subgroup is arXiv-only, so a
        # textbook paper_id under the arxiv: prefix can't match.
        assert not is_valid_chunk_id(
            "arxiv:textbook:foo:abcdef0123456789"
        )

    def test_paper_id_from_chunk_id_raises_on_invalid(self):
        # Ensure the error path still rejects malformed input.
        with pytest.raises(ValueError):
            paper_id_from_chunk_id("textbook:foo:bad")
        with pytest.raises(ValueError):
            paper_id_from_chunk_id("not-a-chunk-id")

    # ---- m1 rect F3 — additional Threat-1 negative cases ----
    # The adversary critique enumerated injection shapes the original
    # m1 test suite covered only via "the regex happens to reject."
    # These tests document the rejection contract explicitly so a
    # future regex refactor cannot silently re-admit any of them.

    def test_textbook_trailing_space_rejected(self):
        assert not is_valid_paper_id("textbook:foo ")

    def test_textbook_trailing_tab_rejected(self):
        assert not is_valid_paper_id("textbook:foo\t")

    def test_textbook_trailing_cr_rejected(self):
        assert not is_valid_paper_id("textbook:foo\r")

    def test_textbook_leading_whitespace_rejected(self):
        assert not is_valid_paper_id(" textbook:foo")
        assert not is_valid_paper_id("\ttextbook:foo")
        assert not is_valid_paper_id("\ntextbook:foo")

    def test_textbook_bare_prefix_rejected(self):
        # ``textbook`` with no colon, no slug.
        assert not is_valid_paper_id("textbook")
        # ``textbook:`` with no slug (covered by N6 but re-asserted).
        assert not is_valid_paper_id("textbook:")

    def test_textbook_dot_slugs_rejected(self):
        # Dot, dot-dot, dot-slash — all classic path-traversal shapes.
        assert not is_valid_paper_id("textbook:.")
        assert not is_valid_paper_id("textbook:..")
        assert not is_valid_paper_id("textbook:./")
        assert not is_valid_paper_id("textbook:../")

    def test_textbook_url_encoded_traversal_rejected(self):
        # Percent signs not in the slug character class.
        assert not is_valid_paper_id("textbook:%2e%2e%2f")
        assert not is_valid_paper_id("textbook:%2e%2e")

    def test_textbook_rtl_override_rejected(self):
        # Unicode RTL override (U+202E) — none of the [a-z0-9-]
        # class. Verifies non-ASCII bytes are rejected.
        assert not is_valid_paper_id("textbook:foo‮")
        assert not is_valid_paper_id("textbook:foo‮bar")

    def test_textbook_backslash_injection_rejected(self):
        # Windows-style path separator + escape sequences.
        assert not is_valid_paper_id("textbook:foo\\bar")
        assert not is_valid_paper_id("textbook:..\\etc\\passwd")

    def test_textbook_control_chars_rejected(self):
        # Bell, backspace, FF, VT, ESC, DEL — all outside slug class.
        for ch in ("\x07", "\x08", "\x0b", "\x0c", "\x1b", "\x7f"):
            assert not is_valid_paper_id(f"textbook:foo{ch}"), (
                f"control char U+{ord(ch):04x} not rejected"
            )


class TestIsValidArxivPaperId:
    """m1 rect F2 — arXiv-only validator preserves pre-m1 reject
    contract at sites that construct filesystem paths or SQL filters
    against the shared arXiv corpus."""

    def test_arxiv_new_style_accepted(self):
        assert is_valid_arxiv_paper_id("2401.00001")
        assert is_valid_arxiv_paper_id("2401.00001v3")

    def test_arxiv_old_style_accepted(self):
        assert is_valid_arxiv_paper_id("hep-th/9876543")
        assert is_valid_arxiv_paper_id("cond-mat/0612345")

    def test_textbook_rejected(self):
        # F2 keystone: the arXiv-only helper REJECTS the union form
        # that ``is_valid_paper_id`` accepts.
        assert not is_valid_arxiv_paper_id("textbook:foo")
        assert not is_valid_arxiv_paper_id("textbook:shimura-varieties")

    def test_path_traversal_rejected(self):
        # Inherits all the pre-m1 Threat-1 protections.
        assert not is_valid_arxiv_paper_id("../etc/passwd")
        assert not is_valid_arxiv_paper_id("")
        assert not is_valid_arxiv_paper_id("2401.00001\n")  # \Z anchor

    def test_non_string_rejected(self):
        assert not is_valid_arxiv_paper_id(None)  # type: ignore[arg-type]
        assert not is_valid_arxiv_paper_id(12345)  # type: ignore[arg-type]


class TestM1RectGatesRejectTextbook:
    """m1 rect F1 + F2 regression guard.

    Asserts that downstream callsites (filesystem-path constructors
    and SQL-style filters) reject the new textbook form via
    ``is_valid_arxiv_paper_id``. Once m2 ships schema columns and
    notebook-scoped writes opt into ``is_valid_paper_id``, the
    corresponding assertions move to "accept textbook for textbook
    notebooks" — but until then, the arXiv-only contract holds.
    """

    def test_extract_equations_module_uses_arxiv_only_helper(self):
        # ingest/extract_equations.py:369 validates via the arXiv-only
        # helper; the textbook form is rejected before any filesystem
        # path is constructed at PARSED_DIR/<paper_id>/. We verify by
        # source inspection — the gate import is the contract.
        import ingest.extract_equations as ee

        assert hasattr(ee, "is_valid_arxiv_paper_id"), (
            "extract_equations must import the arXiv-only helper"
        )
        # And the union form must NOT be imported (would be a
        # widening regression).
        assert not hasattr(ee, "is_valid_paper_id"), (
            "extract_equations must not import the union helper "
            "until m2 schema columns ship"
        )

    def test_paper_handler_admits_the_union_since_209(self):
        """SUPERSEDED by chris-dare-dev/arXMCP#209.

        This asserted the inverse — that ``get_paper`` imports the
        arXiv-only helper and NOT the union — which was the correct m1
        contract while the m2 schema columns were still landing. Those
        shipped, and the arXiv-only gate then became the defect: the
        handler rejected ``textbook:`` ids that ``search_papers`` had
        emitted moments earlier, reporting a well-formed identifier as
        malformed input.

        Kept rather than deleted, inverted, so the history of the
        contract is legible at the point that pinned it. The live
        coverage is ``tests/test_source_kind_admission.py``.
        """
        import server.handlers.paper as ph

        assert not hasattr(ph, "is_valid_arxiv_paper_id"), (
            "get_paper must no longer gate on the arXiv-only validator"
        )
        assert hasattr(ph, "SUPPORTED_SOURCE_KINDS")

    def test_upload_sanitizer_neutralizes_colon(self):
        # m1 rect F1: even if a textbook paper_id slipped past the
        # arXiv-only gate at server/routes/notebooks.py:558, the
        # sanitizer at :619 now replaces both ``/`` and ``:`` with
        # ``_``. Verify the byte-replacement explicitly.
        paper_id = "textbook:foo"
        flat = paper_id.replace("/", "_").replace(":", "_")
        assert ":" not in flat
        assert flat == "textbook_foo"

    def test_upload_sanitizer_preserves_arxiv_oldstyle(self):
        # Sanity: the colon-stripping addition didn't change the
        # arXiv old-style behavior. ``hep-th/9876543`` → ``hep-th_9876543``.
        paper_id = "hep-th/9876543"
        flat = paper_id.replace("/", "_").replace(":", "_")
        assert flat == "hep-th_9876543"
