"""Tests for the D-2 ``lean_verify`` soundness hardening
(stage2/arx-d2; finding 05 §3-R2; RISKS MA-2; AC-D.1/AC-D.2/AC-D.3).

Two tiers:

1. **Pure-module tests** over ``server/lean_soundness.py`` — snippet
   guard scan, declaration-name extraction, ``#print axioms`` output
   parsing, closure check, provenance reads, transcript hashing, and
   the ``formal_award_ok`` award predicate (fail-closed truth table).
2. **Handler tests** over ``handle_lean_verify`` with a fake REPL —
   crafted smuggling attempts (snippet-declared ``axiom``/``opaque``,
   a smuggled custom axiom surfacing only in the closure,
   ``native_decide``), audit failure modes (REPL error, unparseable
   output, missing env id), provenance recording, and AC-D.3
   transcript-hash replayability. Every new envelope path is validated
   against the frozen v17 result schema.

The real-REPL integration tier lives in ``tests/eval/test_kat_lean.py``
(``@pytest.mark.requires_lean_repl``).
"""

from __future__ import annotations

import asyncio
import json
import re
from pathlib import Path
from typing import Any

import pytest

from server.config import Config
from server.handlers.lean_verify import handle_lean_verify
from server.lean_repl import LeanReplError
from server.lean_soundness import (
    ALLOWED_AXIOMS,
    _strip_lean_comments,
    closure_ok,
    extract_decl_names,
    extract_proved_statement,
    formal_award_ok,
    kernel_check_snippet,
    kernel_decides_linked,
    kernel_statement_for_snippet,
    parse_check_type_output,
    parse_print_axioms_output,
    read_repl_provenance,
    scan_snippet,
    transcript_sha256,
)
from server.tools import reset_resources_for_tests, set_resources


def _run(coro):
    return asyncio.run(coro)


# ===========================================================================
# Tier 1 — pure module
# ===========================================================================


class TestScanSnippet:
    def test_clean_snippet_passes(self):
        scan = scan_snippet("theorem t : 1 + 1 = 2 := rfl")
        assert not scan.rejected
        assert scan.rejected_keywords == ()
        assert scan.flags == ()

    def test_axiom_declaration_rejected(self):
        """AC-D.1 canary shape: a snippet that mints its own axiom."""
        scan = scan_snippet(
            "axiom cheat : (1 : Nat) + 1 = 3\n"
            "theorem t : (1 : Nat) + 1 = 3 := cheat"
        )
        assert scan.rejected
        assert "axiom" in scan.rejected_keywords

    def test_opaque_declaration_rejected(self):
        scan = scan_snippet("opaque mystery : Nat\ntheorem t : True := trivial")
        assert scan.rejected
        assert "opaque" in scan.rejected_keywords

    def test_axiom_in_comment_rejected_fail_closed(self):
        """Deliberate fail-closed behavior: the scan does NOT strip
        comments (a stripper that disagrees with Lean's lexer about
        nesting would be a smuggling hole). A commented 'axiom' costs
        the caller a rewrite, never a soundness hole."""
        scan = scan_snippet("-- this axiom is only mentioned\n"
                            "theorem t : True := trivial")
        assert scan.rejected

    def test_word_boundary_no_false_positive(self):
        """'axiomatic' / 'opaquely' must NOT trip the word-boundary
        guard."""
        scan = scan_snippet(
            "-- axiomatic development, opaquely named\n"
            "theorem t : True := trivial"
        )
        assert not scan.rejected

    def test_flags_native_decide_unsafe_partial(self):
        scan = scan_snippet(
            "unsafe def f : Nat := 0\n"
            "partial def g (n : Nat) : Nat := g n\n"
            "theorem t : 2 + 2 = 4 := by native_decide"
        )
        assert not scan.rejected
        assert set(scan.flags) == {"native_decide", "unsafe", "partial"}


class TestExtractDeclNames:
    def test_simple_theorem(self):
        assert extract_decl_names("theorem foo : True := trivial") == ["foo"]

    def test_lemma_and_modifiers_and_attributes(self):
        snippet = (
            "@[simp]\n"
            "private theorem ns.foo' : True := trivial\n"
            "noncomputable lemma bar_baz : True := trivial\n"
        )
        assert extract_decl_names(snippet) == ["ns.foo'", "bar_baz"]

    def test_def_and_example_not_audited(self):
        """defs are covered transitively through the theorems that use
        them; examples are anonymous — neither is directly auditable."""
        snippet = "def x : Nat := 7\nexample : True := trivial"
        assert extract_decl_names(snippet) == []

    def test_dedupe_preserves_order(self):
        snippet = (
            "theorem a : True := trivial\n"
            "theorem b : True := trivial\n"
            "theorem a : True := trivial\n"
        )
        assert extract_decl_names(snippet) == ["a", "b"]

    def test_indented_declaration(self):
        assert extract_decl_names("  theorem t : True := trivial") == ["t"]


class TestExtractProvedStatement:
    """The proof-/refutation-side statement extractor. Feeds BOTH the
    proof-linkage award gate (findings #1/#2) and the refutation-witness
    linkage gate. Round-3 fix: binders are REFLECTED, not dropped, so a
    vacuous-hypothesis proof cannot masquerade as its bare conclusion
    (finding: proof-side vacuous-hypothesis binder)."""

    def test_binderless_theorem_is_the_type(self):
        assert (
            extract_proved_statement("theorem d6 : ∀ m n, Even (m + n) := by tauto")
            == "∀ m n, Even (m + n)"
        )

    def test_anonymous_example_witness_is_the_type(self):
        """The skeptic lane's canonical witness form — binder-free, so
        unchanged by the reflection fix."""
        assert (
            extract_proved_statement(
                "example : ¬ Nat.Prime (40 ^ 2 + 40 + 41) := by norm_num"
            )
            == "¬ Nat.Prime (40 ^ 2 + 40 + 41)"
        )

    def test_vacuous_hypothesis_binder_is_reflected_not_dropped(self):
        """THE round-3 proof-side hole: ``theorem attack (h : False) : G``
        kernel-proves the vacuously-true ``∀ (h : False), G`` for ANY G,
        but the extractor USED TO return exactly ``G`` — passing statement
        linkage against a gate-checked ``G`` while the kernel established
        nothing about it. The binder is now reflected, so the extracted
        text carries ``∀ (h : False),`` and no longer equals the closed
        ``G``."""
        attack = "theorem attack (h : False) : ∀ n : Nat, n + 1 = n := h.elim"
        proved = extract_proved_statement(attack)
        assert proved == "∀ (h : False), ∀ n : Nat, n + 1 = n"
        # The load-bearing property: it does NOT equal the bare conclusion.
        assert proved != "∀ n : Nat, n + 1 = n"

    def test_example_with_vacuous_binder_is_reflected(self):
        assert (
            extract_proved_statement("example (h : False) : 2 = 3 := h.elim")
            == "∀ (h : False), 2 = 3"
        )

    def test_multiple_and_typeclass_binders_reflected(self):
        assert (
            extract_proved_statement(
                "theorem t {G : Type*} [Group G] (a : G) : a * 1 = a := by simp"
            )
            == "∀ {G : Type*} [Group G] (a : G), a * 1 = a"
        )

    def test_hypothesis_binder_reflected(self):
        assert (
            extract_proved_statement("theorem t (n : Nat) (h : n > 0) : n + 1 > 1 := by omega")
            == "∀ (n : Nat) (h : n > 0), n + 1 > 1"
        )

    def test_binder_colon_not_mistaken_for_type_opener(self):
        """A binder's ``:`` sits at bracket-depth ≥ 1 and must not be read
        as the top-level type ascription — the depth-aware scan handles
        it, and the binder is then reflected."""
        proved = extract_proved_statement(
            "theorem t (m : Nat) : m + 0 = m := by simp"
        )
        assert proved == "∀ (m : Nat), m + 0 = m"

    def test_no_type_ascription_returns_none(self):
        assert extract_proved_statement("theorem foo := rfl") is None

    def test_no_declaration_returns_none(self):
        assert extract_proved_statement("-- just a comment") is None

    def test_whitespace_collapsed(self):
        assert (
            extract_proved_statement("theorem t :  ∀ n,\n   n = n   := by intro n; rfl")
            == "∀ n, n = n"
        )

    # -- Round-3 comment-injection class fix ------------------------------
    # A snippet whose kernel-elaborated content is a trivial
    # `theorem real : True := by trivial` (witness_ok / kernel_confirmed)
    # but which carries a phantom declaration in a Lean comment must NOT
    # extract the commented proposition — the extractor strips comments
    # first, so it returns the REAL kernel statement. Reading phantom
    # comment text would GRANT linkage (proof- or refutation-side); over-
    # stripping only ever DENIES an award (one-directional safety).

    def test_block_comment_phantom_declaration_is_not_extracted(self):
        """The exact report repro: a `/- theorem fake : <TARGET> := by
        sorry -/` block comment before a trivial real theorem must yield
        the REAL statement (`True`), never the commented `<TARGET>`."""
        attack = (
            "/-\n"
            "  theorem fake : Nat.Prime (40 ^ 2 + 40 + 41) := by sorry\n"
            "-/\n"
            "theorem real : True := by trivial"
        )
        assert extract_proved_statement(attack) == "True"

    def test_line_comment_between_type_and_body_is_stripped(self):
        """The ``--`` line-comment variant. A pure single-line
        ``-- theorem fake …`` before the real declaration is NOT itself a
        grant exploit (the line-anchored ``_STMT_DECL_RE`` never matches a
        keyword that sits after ``--`` on its line — the report's §4.1
        note), so the interesting ``--`` case is a line comment BETWEEN
        the real type and its ``:=`` body that carries a spurious ``:=``.
        Before the strip, the depth-scan stopped at the COMMENTED ``:=``
        and leaked the comment text into the extracted type (``True --
        fake``); after the strip it extracts the clean ``True``. This is a
        genuine before/after divergence on a ``--`` comment."""
        snippet = "theorem real : True -- fake := by sorry\n  := by trivial"
        assert extract_proved_statement(snippet) == "True"

    def test_line_comment_before_real_decl_extracts_real(self):
        """A ``--``-commented phantom declaration before the real one:
        the real declaration is what extracts (the phantom is line-
        anchored-safe here because it sits after ``--``)."""
        snippet = (
            "-- theorem fake : Nat.Prime (40 ^ 2 + 40 + 41) := by sorry\n"
            "theorem real : True := by trivial"
        )
        assert extract_proved_statement(snippet) == "True"

    def test_nested_block_comment_fully_stripped(self):
        """Lean block comments NEST: the phantom ``theorem fake`` sits on
        its OWN line (line-anchored, the reproducing form) inside a nested
        ``/- outer /- inner -/ … -/`` comment. A naive ``/-.*?-/`` would
        close at the first ``-/`` (the inner one), leaving the phantom and
        the tail ``-/`` in the snippet — so the phantom would still match.
        The depth-aware scrubber closes only at depth 0, stripping the
        whole comment; the real declaration after it is what extracts."""
        attack = (
            "/- outer\n"
            "/- inner -/\n"
            "theorem fake : ∀ n : Nat, n = n := by sorry\n"
            "-/\n"
            "theorem real : True := by trivial"
        )
        assert extract_proved_statement(attack) == "True"

    def test_strip_lean_comments_helper_nesting_and_line(self):
        """The scrubber itself: nested blocks close at depth 0, line
        comments run to (and keep) the newline."""
        assert (
            _strip_lean_comments("/- a /- b -/ c -/x").strip() == "x"
        )
        assert (
            _strip_lean_comments("y -- trailing\nz").replace(" ", "")
            == "y\nz".replace(" ", "")
        )

    def test_comment_free_snippet_extracts_byte_identically(self):
        """No-regression: comment-free snippets are unchanged by the
        strip (the scrubber is a no-op when there are no comments)."""
        for snippet, expected in [
            ("theorem d6 : ∀ m n, Even (m + n) := by tauto", "∀ m n, Even (m + n)"),
            ("example : ¬ Nat.Prime (40 ^ 2 + 40 + 41) := by norm_num",
             "¬ Nat.Prime (40 ^ 2 + 40 + 41)"),
            ("theorem t (n : Nat) : n + 0 = n := by simp", "∀ (n : Nat), n + 0 = n"),
        ]:
            assert extract_proved_statement(snippet) == expected

    def test_real_declaration_with_trailing_line_comment(self):
        """A legitimate trailing `--` comment on the real declaration is
        stripped without harming the extracted statement."""
        assert (
            extract_proved_statement("theorem real : 2 + 2 = 4 := by norm_num -- ok")
            == "2 + 2 = 4"
        )


class TestParseCheckType:
    """`parse_check_type_output` — the `#check @<name>` -> type parser
    (durable P1 soundness fix; live-probed shapes in the p1 spike)."""

    def test_plain_type(self):
        assert (
            parse_check_type_output("spike_foo : ∀ (n : Nat), n + 0 = n", "spike_foo")
            == "∀ (n : Nat), n + 0 = n"
        )

    def test_hypothesis_binder_arrow(self):
        """A hypothesis binder is reflected by the kernel as an arrow —
        exactly the vacuous-binder property the linkage needs."""
        assert (
            parse_check_type_output("spike_bar : 1 = 1 → True", "spike_bar")
            == "1 = 1 → True"
        )

    def test_type_containing_a_colon_is_not_split_early(self):
        """The name-anchored prefix strip must not be confused by a colon
        INSIDE the type (only the `<name> :` prefix is removed)."""
        assert (
            parse_check_type_output(
                "d : (fun (x : Nat) => x) 0 = 0", "d"
            )
            == "(fun (x : Nat) => x) 0 = 0"
        )

    def test_unicode_identifier_name(self):
        assert parse_check_type_output("αβ_uni : True", "αβ_uni") == "True"

    def test_unknown_identifier_error_is_none(self):
        """An `Unknown identifier` error (anonymous example / comment or
        string-literal phantom / unqueried name) yields None — fail
        closed, no statement."""
        assert (
            parse_check_type_output("Unknown identifier `fake`", "fake") is None
        )

    def test_prefix_for_a_different_name_is_none(self):
        """Defensive: a message that does not start with the queried name
        does not parse (never mis-attribute another decl's type)."""
        assert parse_check_type_output("other : True", "spike_foo") is None

    def test_whitespace_normalized(self):
        assert (
            parse_check_type_output("t :   a    →   b", "t") == "a → b"
        )

    def test_empty_or_missing(self):
        assert parse_check_type_output("", "t") is None
        assert parse_check_type_output("t : ", "t") is None


class TestKernelStatementForSnippet:
    """`kernel_statement_for_snippet` — the authoritative proved-statement
    selector that replaced the text-scanner in the linkage GRANT path
    (durable P1 soundness fix). These are the NEW adversarial vectors the
    text-scanner could not handle but the kernel report does: the map is
    keyed by the KERNEL's view (only names the kernel actually
    elaborated), so a phantom in a comment / string literal, an
    unqueryable unicode name, or a mismatched trailing decl cannot
    fabricate a linked statement."""

    def test_selects_first_decl_kernel_type(self):
        assert (
            kernel_statement_for_snippet(
                "theorem t : True := trivial", {"t": "True"}
            )
            == "True"
        )

    def test_anonymous_example_has_no_kernel_statement(self):
        """The named-declaration contract: an anonymous `example` has no
        name to key the kernel map, so linkage fails closed even if the
        kernel accepted the example."""
        assert (
            kernel_statement_for_snippet(
                "example : ¬ Nat.Prime (40 ^ 2 + 40 + 41) := by norm_num",
                {},
            )
            is None
        )

    def test_empty_or_missing_kernel_statements_is_none(self):
        assert kernel_statement_for_snippet("theorem t : True := trivial", None) is None
        assert kernel_statement_for_snippet("theorem t : True := trivial", {}) is None

    # ----- ADVERSARIAL VECTOR (a): unicode-identifier declaration -----
    def test_unicode_identifier_decl_not_name_extracted_fails_closed(self):
        """A unicode-identifier theorem name (`theorem αβ : …`) is NOT
        matched by the ASCII-only `extract_decl_names` regex, so the
        snippet has no principal name to look up -> None -> linkage fails
        CLOSED. The kernel MAY know `αβ` (it elaborates unicode names),
        but the selector cannot pick it from the snippet, so no mismatched
        grant is possible. (The safe direction: over-rejection costs a
        rename to an ASCII decl, never a false accept.)"""
        snippet = "theorem αβ : (1 : Nat) + 1 = 3 := by sorry"
        # extract_decl_names is ASCII-only by construction -> no name.
        assert extract_decl_names(snippet) == []
        # Even if the kernel map happened to carry a `αβ` entry with a
        # DIFFERENT (attacker-chosen) proposition, the selector returns
        # None because it cannot extract the name from the snippet.
        assert (
            kernel_statement_for_snippet(snippet, {"αβ": "1 + 1 = 2"}) is None
        )

    # ----- ADVERSARIAL VECTOR (b): `theorem` inside a STRING literal ----
    def test_theorem_inside_string_literal_is_invisible_to_kernel(self):
        """A `def` whose BODY is a string literal containing the text
        `theorem fake : 1 = 2 := by sorry`. The kernel elaborates only
        the `def spike_str`; `fake` is never a declaration, so the kernel
        map has NO `fake` entry (live-probed: `#check @fake` errors with
        Unknown identifier). The principal name extracted from the snippet
        is `spike_str` (a `def`, not theorem/lemma -> extract_decl_names
        returns [] since it matches theorem/lemma only), OR if a real
        theorem precedes it, only that real theorem's kernel type is
        selectable. Either way the phantom `fake` proposition can never be
        the selected statement — the text-scanner would have matched
        `theorem fake : 1 = 2` inside the string."""
        snippet = 'def spike_str : String := "theorem fake : 1 = 2 := by sorry"'
        # `def` is not theorem/lemma -> no principal name.
        assert extract_decl_names(snippet) == []
        # The kernel map (as the real handler would build it) has no
        # `fake` — a phantom in a string literal is never elaborated.
        kmap = {"spike_str": "String"}  # only the real def, and def is not selected
        assert kernel_statement_for_snippet(snippet, kmap) is None
        # And a would-be attacker map entry for `fake` is unreachable: the
        # selector keys on the snippet's principal theorem/lemma name,
        # which does not exist here.
        assert (
            kernel_statement_for_snippet(snippet, {"fake": "1 = 2"}) is None
        )

    def test_theorem_inside_string_with_real_named_decl_selects_real(self):
        """A NAMED real theorem alongside a string literal that contains a
        `theorem fake` phantom: the selector picks the REAL theorem's
        kernel type; the phantom in the string never enters the kernel map
        (its `#check @fake` would error), so it cannot be granted."""
        snippet = (
            'def blurb : String := "theorem fake : 1 = 2 := by sorry"\n'
            "theorem real_thm : True := trivial"
        )
        # extract_decl_names matches theorem/lemma only -> ["real_thm"].
        assert extract_decl_names(snippet) == ["real_thm"]
        # The kernel map carries ONLY the real theorem (fake is never
        # elaborated). The selector returns the real proposition.
        assert (
            kernel_statement_for_snippet(snippet, {"real_thm": "True"}) == "True"
        )
        # A `fake` entry (which the kernel would never actually produce)
        # is unreachable — the principal name is `real_thm`.
        assert (
            kernel_statement_for_snippet(
                snippet, {"real_thm": "True", "fake": "1 = 2"}
            )
            == "True"
        )

    # ----- ADVERSARIAL VECTOR (c): multi-decl, trailing decl differs ----
    def test_multi_decl_selects_first_not_trailing(self):
        """A multi-declaration snippet where a TRAILING decl's statement
        differs from the audited/principal one. The selector keys on the
        FIRST decl (`first_thm`), so a trailing `second_thm` proving a
        DIFFERENT (attacker-favourable) proposition cannot be substituted
        as the linked statement. The kernel reports each decl's OWN type
        (live-probed: `#check @first_thm` and `#check @second_thm` return
        distinct types), so the map is honest per-decl; the selector's
        first-decl rule then pins the grant to the principal decl."""
        snippet = (
            "theorem first_thm : True := trivial\n"
            "theorem second_thm : 1 = 1 := rfl"
        )
        assert extract_decl_names(snippet) == ["first_thm", "second_thm"]
        kmap = {"first_thm": "True", "second_thm": "1 = 1"}
        # The principal (first) decl's kernel type is selected — NOT the
        # trailing decl's, so a proof/witness cannot smuggle a mismatched
        # trailing statement past linkage.
        assert kernel_statement_for_snippet(snippet, kmap) == "True"

    def test_first_decl_absent_from_kernel_map_fails_closed(self):
        """If the principal decl's `#check @` did not parse (omitted from
        the map, fail-closed at the handler), the selector returns None
        even when OTHER decls are present — a mismatched sibling is never
        substituted for the missing principal statement."""
        snippet = (
            "theorem first_thm : True := trivial\n"
            "theorem second_thm : 1 = 1 := rfl"
        )
        # first_thm missing from the map (e.g. its #check errored).
        assert (
            kernel_statement_for_snippet(snippet, {"second_thm": "1 = 1"}) is None
        )

    def test_non_string_map_value_fails_closed(self):
        """A malformed kernel map value (non-string) is not trusted."""
        assert (
            kernel_statement_for_snippet(
                "theorem t : True := trivial", {"t": None}  # type: ignore[dict-item]
            )
            is None
        )


class TestKernelCheckSnippet:
    """`kernel_check_snippet` — the combined command that makes THE KERNEL
    decide the formalization⇔proof / witness⇔declaration link (durable P1
    kernel-decides fix)."""

    def test_shape_is_snippet_then_example(self):
        out = kernel_check_snippet(
            "theorem t : True := trivial", "True", "t"
        )
        assert out == "theorem t : True := trivial\nexample : True := @t"

    def test_uses_explicit_at_form(self):
        """`@decl` (explicit-args) so implicit binders are not synthesised
        against the ascribed target."""
        out = kernel_check_snippet("theorem foo : P := pf", "P", "foo")
        assert ":= @foo" in out
        assert out.endswith("example : P := @foo")

    def test_target_ascribed_verbatim(self):
        """The target's own syntax is ascribed verbatim — the KERNEL
        decides defeq, so a natural-syntax target is fine (a malformed one
        can only fail to type-check, never fabricate a link)."""
        out = kernel_check_snippet(
            "theorem d : ∀ (m n : ℕ), m + n = n + m := pf",
            "∀ m n : Nat, m + n = n + m",  # differently phrased, defeq
            "d",
        )
        assert out.endswith("example : ∀ m n : Nat, m + n = n + m := @d")


class TestKernelDecidesLinked:
    """`kernel_decides_linked` — the pure, fail-closed acceptance predicate
    over a `kernel_check_snippet` verification result. A kernel type-check
    ERROR must NEVER be read as linked."""

    def _ok(self):
        return {"status": "ok", "compilation_success": True}

    def test_ok_and_compiled_is_linked(self):
        assert kernel_decides_linked(self._ok()) is True

    def test_type_mismatch_error_is_not_linked(self):
        """The ℝ/ℚ collision (and any non-defeq target) surfaces as a
        Type mismatch -> status error -> NOT linked."""
        assert (
            kernel_decides_linked(
                {"status": "error", "compilation_success": False}
            )
            is False
        )

    def test_sorry_is_not_linked(self):
        assert (
            kernel_decides_linked(
                {"status": "sorry", "compilation_success": False}
            )
            is False
        )

    def test_timeout_is_not_linked(self):
        assert (
            kernel_decides_linked(
                {"status": "timeout", "compilation_success": False}
            )
            is False
        )

    def test_disabled_verifier_is_not_linked(self):
        assert (
            kernel_decides_linked(
                {"status": "unavailable", "compilation_success": None}
            )
            is False
        )

    def test_ok_status_without_compilation_success_is_not_linked(self):
        """Defense-in-depth: status ok but compilation_success not True
        (e.g. a syntax_only pass) is NOT a full kernel acceptance."""
        assert (
            kernel_decides_linked({"status": "ok", "compilation_success": None})
            is False
        )
        assert (
            kernel_decides_linked({"status": "ok", "compilation_success": False})
            is False
        )

    def test_none_and_malformed_fail_closed(self):
        assert kernel_decides_linked(None) is False
        assert kernel_decides_linked({}) is False
        assert kernel_decides_linked("nope") is False  # type: ignore[arg-type]


class TestParsePrintAxioms:
    def test_depends_on_list(self):
        out = parse_print_axioms_output(
            "'t' depends on axioms: [propext, Classical.choice, Quot.sound]"
        )
        assert out == ["propext", "Classical.choice", "Quot.sound"]

    def test_no_axioms(self):
        assert parse_print_axioms_output(
            "'t' does not depend on any axioms"
        ) == []

    def test_multiline_list(self):
        out = parse_print_axioms_output(
            "'t' depends on axioms: [propext,\n Classical.choice]"
        )
        assert out == ["propext", "Classical.choice"]

    def test_garbage_returns_none(self):
        assert parse_print_axioms_output("unknown constant 't'") is None
        assert parse_print_axioms_output("") is None


class TestClosureOk:
    def test_standard_three_ok(self):
        assert closure_ok(ALLOWED_AXIOMS)

    def test_empty_ok(self):
        assert closure_ok([])

    def test_sorry_ax_fails(self):
        assert not closure_ok(["propext", "sorryAx"])

    def test_native_decide_axioms_fail(self):
        assert not closure_ok(
            ["propext", "Lean.ofReduceBool", "Lean.trustCompiler"]
        )

    def test_custom_axiom_mixed_with_choice_fails(self):
        """AC-D.2 negative-control shape: Classical.choice + a custom
        axiom mix must fail."""
        assert not closure_ok(["Classical.choice", "cheat"])


class TestProvenance:
    def test_reads_toolchain_and_mathlib_rev(self, tmp_path):
        (tmp_path / "lean-toolchain").write_text(
            "leanprover/lean4:v4.30.0-rc2\n", encoding="utf-8"
        )
        (tmp_path / "lake-manifest.json").write_text(
            json.dumps(
                {
                    "version": "1.1.0",
                    "packages": [
                        {"name": "repl", "rev": "aaaa"},
                        {"name": "mathlib", "rev": "5450b53e5d"},
                    ],
                }
            ),
            encoding="utf-8",
        )
        toolchain, rev = read_repl_provenance(tmp_path)
        assert toolchain == "leanprover/lean4:v4.30.0-rc2"
        assert rev == "5450b53e5d"

    def test_missing_files_yield_nulls(self, tmp_path):
        assert read_repl_provenance(tmp_path / "nope") == (None, None)

    def test_none_dir_yields_nulls(self):
        assert read_repl_provenance(None) == (None, None)

    def test_manifest_without_mathlib_yields_null_rev(self, tmp_path):
        (tmp_path / "lean-toolchain").write_text("tc\n", encoding="utf-8")
        (tmp_path / "lake-manifest.json").write_text(
            json.dumps({"packages": [{"name": "repl", "rev": "aaaa"}]}),
            encoding="utf-8",
        )
        assert read_repl_provenance(tmp_path) == ("tc", None)


class TestTranscriptHash:
    _KW = dict(
        snippet="theorem t : True := trivial",
        imports=["Mathlib.Tactic"],
        mode="full",
        lean_toolchain="leanprover/lean4:v4.30.0-rc2",
        mathlib_rev="5450b53e5d",
    )

    def test_deterministic(self):
        payload = {"status": "ok", "messages": []}
        h1 = transcript_sha256(payload=dict(payload), **self._KW)
        h2 = transcript_sha256(payload=dict(payload), **self._KW)
        assert h1 == h2
        assert len(h1) == 64 and set(h1) <= set("0123456789abcdef")

    def test_volatile_keys_excluded(self):
        """corpus_version + provenance never perturb the hash — replay
        comparisons must survive corpus updates."""
        base = transcript_sha256(payload={"status": "ok"}, **self._KW)
        noisy = transcript_sha256(
            payload={
                "status": "ok",
                "corpus_version": 999,
                "provenance": {"transcript_sha256": "x"},
            },
            **self._KW,
        )
        assert base == noisy

    def test_snippet_change_changes_hash(self):
        kw = dict(self._KW)
        h1 = transcript_sha256(payload={"status": "ok"}, **kw)
        kw["snippet"] = "theorem t : False := trivial"
        h2 = transcript_sha256(payload={"status": "ok"}, **kw)
        assert h1 != h2

    def test_toolchain_change_changes_hash(self):
        kw = dict(self._KW)
        h1 = transcript_sha256(payload={"status": "ok"}, **kw)
        kw["mathlib_rev"] = "deadbeef"
        h2 = transcript_sha256(payload={"status": "ok"}, **kw)
        assert h1 != h2


def _good_result() -> dict[str, Any]:
    """A minimal award-worthy hardened result."""
    return {
        "status": "ok",
        "mode": "full",
        "compilation_success": True,
        "soundness": {
            "guard": "passed",
            "rejected_keywords": [],
            "flags": [],
            "audit_status": "ok",
            "audit_detail": None,
            "audited_decls": ["t"],
            "axioms_by_decl": {"t": ["propext"]},
            "axiom_closure": ["propext"],
            "axiom_closure_ok": True,
        },
    }


class TestFormalAwardOk:
    """The proven-formal award predicate — finding 05 §4.3 row 1,
    fail-closed on every element (AC-D.13 discipline applied to the
    formal lane)."""

    def test_good_result_awards(self):
        ok, reasons = formal_award_ok(_good_result())
        assert ok, reasons
        assert reasons == []

    @pytest.mark.parametrize(
        ("mutate", "expected_fragment"),
        [
            (lambda r: r.update(status="error"), "status"),
            (lambda r: r.update(mode="syntax_only"), "mode"),
            (lambda r: r.update(compilation_success=None), "compilation_success"),
            (lambda r: r.pop("soundness"), "no soundness block"),
            (
                lambda r: r["soundness"].update(guard="rejected"),
                "guard",
            ),
            (
                lambda r: r["soundness"].update(audit_status="failed"),
                "audit did not complete",
            ),
            (
                lambda r: r["soundness"].update(audit_status="skipped"),
                "audit did not complete",
            ),
            (
                lambda r: r["soundness"].update(axiom_closure_ok=False),
                "closure",
            ),
            (
                lambda r: r["soundness"].update(axiom_closure_ok=None),
                "closure",
            ),
            (
                lambda r: r["soundness"].update(audited_decls=[]),
                "no declarations were audited",
            ),
            (
                lambda r: r["soundness"].update(flags=["native_decide"]),
                "forbidden flags",
            ),
            (
                lambda r: r["soundness"].update(flags=["unsafe"]),
                "forbidden flags",
            ),
            (
                lambda r: r["soundness"].update(flags=["partial"]),
                "forbidden flags",
            ),
        ],
    )
    def test_each_violation_denies(self, mutate, expected_fragment):
        result = _good_result()
        mutate(result)
        ok, reasons = formal_award_ok(result)
        assert not ok
        assert any(expected_fragment in r for r in reasons), (
            f"expected a reason containing {expected_fragment!r}; "
            f"got {reasons}"
        )

    def test_missing_everything_is_denied_with_reasons(self):
        ok, reasons = formal_award_ok({})
        assert not ok
        assert len(reasons) >= 3


# ===========================================================================
# Tier 2 — handler with fake REPL (crafted smuggling attempts)
# ===========================================================================


#: Match a ``#check @<name>`` kernel-type query (durable P1 soundness
#: fix). The fake REPL answers these from ``check_responses`` (or a
#: default parseable ``<name> : True``) WITHOUT consuming the ordered
#: ``responses`` queue, so every existing test's queued elaborate +
#: ``#print axioms`` responses stay valid.
_CHECK_AT_RE = re.compile(r"^#check\s+@(\S+)\s*$")


class _AuditFakeRepl:
    """Fake REPL for the D-2 handler tests.

    ``responses`` are popped in order for the elaboration + ``#print
    axioms`` queries. ``#check @<name>`` KERNEL-type queries (durable P1
    soundness fix) are served OUT OF BAND from ``check_responses`` (name
    -> raw ``data`` string) so the ordered queue is undisturbed; an
    unmapped name defaults to a parseable ``<name> : True`` — override
    per test to exercise a specific kernel type or a query error. Pass
    ``check_responses={name: None}`` to model a ``#check`` that returns no
    parseable type (an error message), which OMITS the name from
    ``kernel_statements`` (fail-closed).

    ``raise_at_call`` (1-indexed, counts ALL queries) raises
    ``raise_with`` on that query — used to fail the audit mid-flight
    while the main verification succeeds.
    """

    def __init__(
        self,
        responses: list[dict[str, Any]],
        raise_with: Exception | None = None,
        raise_at_call: int = 1,
        check_responses: dict[str, str | None] | None = None,
    ) -> None:
        self._responses = list(responses)
        self._raise_with = raise_with
        self._raise_at_call = raise_at_call
        self._check_responses = dict(check_responses or {})
        self.commands: list[dict[str, Any]] = []
        self.closed = False

    async def query(self, command: dict[str, Any]) -> dict[str, Any]:
        self.commands.append(command)
        if (
            self._raise_with is not None
            and len(self.commands) == self._raise_at_call
        ):
            raise self._raise_with
        m = _CHECK_AT_RE.match(str(command.get("cmd", "")))
        if m is not None:
            name = m.group(1)
            # Default: the kernel reports `<name> : True` (a parseable
            # type). `None` -> an "Unknown identifier" error (no entry).
            data = self._check_responses.get(name, f"{name} : True")
            if data is None:
                return {
                    "env": command.get("env"),
                    "messages": [
                        {
                            "severity": "error",
                            "pos": {"line": 1, "column": 8},
                            "data": f"Unknown identifier `{name}`",
                        }
                    ],
                }
            return {
                "env": command.get("env"),
                "messages": [
                    {
                        "severity": "info",
                        "pos": {"line": 1, "column": 0},
                        "data": data,
                    }
                ],
            }
        return self._responses.pop(0)

    async def close(self) -> None:
        self.closed = True


class _FakeCorpusInfo:
    version = 1


def _attach(
    repl: Any,
    *,
    enable_lean: bool = True,
    lean_repl_dir: Path | None = None,
) -> Any:
    cfg = Config(
        result_byte_cap=256 * 1024,
        enable_lean=enable_lean,
        lake_path=None,
        lean_repl_dir=lean_repl_dir,
    )

    class _FakeResources:
        pass

    fake = _FakeResources()
    fake.config = cfg
    fake.corpus_info = _FakeCorpusInfo()
    fake.lean_repl = repl
    set_resources(fake)
    return fake


@pytest.fixture
def schema_validator():
    from jsonschema import Draft7Validator

    schema_path = (
        Path(__file__).parent.parent
        / "server"
        / "schemas"
        / "lean_verify_result.json"
    )
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    return Draft7Validator(schema)


def _info(text: str) -> dict[str, Any]:
    return {"severity": "info", "pos": {"line": 1, "column": 0}, "data": text}


_CLEAN_AUDIT = "'t' depends on axioms: [propext, Classical.choice, Quot.sound]"


class TestHandlerSnippetGuard:
    """AC-D.1 — the axiom-smuggling canary, pinned as a permanent
    regression test."""

    def _reject_case(self, snippet: str, schema_validator) -> dict[str, Any]:
        repl = _AuditFakeRepl(responses=[])
        _attach(repl)
        try:
            result = _run(handle_lean_verify(snippet=snippet))
        finally:
            reset_resources_for_tests()
        schema_validator.validate(result)
        # The REPL was never consulted — rejection is pre-elaboration.
        assert repl.commands == []
        return result

    def test_axiom_canary_rejected(self, schema_validator):
        """The exact AC-D.1 vector: declare `axiom cheat : <goal>`,
        close the theorem with it. status != ok, award denied."""
        result = self._reject_case(
            "axiom cheat : (1 : Nat) + 1 = 3\n"
            "theorem t : (1 : Nat) + 1 = 3 := cheat",
            schema_validator,
        )
        assert result["status"] == "error"
        assert result["compilation_success"] is False
        assert result["soundness"]["guard"] == "rejected"
        assert result["soundness"]["audit_status"] == "rejected"
        assert result["soundness"]["axiom_closure_ok"] is False
        assert "axiom" in result["soundness"]["rejected_keywords"]
        assert "soundness guard" in result["messages"][0]["text"]
        ok, reasons = formal_award_ok(result)
        assert not ok
        assert reasons

    def test_opaque_rejected(self, schema_validator):
        result = self._reject_case(
            "opaque mystery : Nat\ntheorem t : mystery = mystery := rfl",
            schema_validator,
        )
        assert result["soundness"]["rejected_keywords"] == ["opaque"]
        assert not formal_award_ok(result)[0]

    def test_rejection_fires_even_when_lean_disabled(self, schema_validator):
        """The guard is deterministic and REPL-independent."""
        _attach(None, enable_lean=False)
        try:
            result = _run(
                handle_lean_verify(snippet="axiom cheat : False")
            )
        finally:
            reset_resources_for_tests()
        schema_validator.validate(result)
        assert result["status"] == "error"
        assert result["lean_status"] == "disabled"
        assert result["soundness"]["guard"] == "rejected"


class TestHandlerAxiomAudit:
    def test_clean_closure_passes_audit(self, schema_validator):
        repl = _AuditFakeRepl(
            responses=[
                {"env": 5},
                {"env": 6, "messages": [_info(_CLEAN_AUDIT)]},
            ]
        )
        _attach(repl)
        try:
            result = _run(
                handle_lean_verify(snippet="theorem t : 1 + 1 = 2 := rfl")
            )
        finally:
            reset_resources_for_tests()
        schema_validator.validate(result)
        assert result["status"] == "ok"
        s = result["soundness"]
        assert s["audit_status"] == "ok"
        assert s["audited_decls"] == ["t"]
        assert s["axioms_by_decl"] == {
            "t": ["propext", "Classical.choice", "Quot.sound"]
        }
        assert s["axiom_closure"] == [
            "Classical.choice",
            "Quot.sound",
            "propext",
        ]
        assert s["axiom_closure_ok"] is True
        # The audit ran inside the verification env (env id 5).
        assert repl.commands[1] == {"cmd": "#print axioms t", "env": 5}
        ok, reasons = formal_award_ok(result)
        assert ok, reasons

    def test_smuggled_axiom_in_closure_fails_audit(self, schema_validator):
        """A custom axiom that evades the textual guard (e.g. minted
        through a macro) still surfaces in the closure — the audit is
        the backstop, not the regex (AC-D.2 negative control)."""
        repl = _AuditFakeRepl(
            responses=[
                {"env": 0},
                {
                    "env": 1,
                    "messages": [
                        _info(
                            "'t' depends on axioms: [Classical.choice, "
                            "hiddenCheatAxiom]"
                        )
                    ],
                },
            ]
        )
        _attach(repl)
        try:
            result = _run(
                handle_lean_verify(snippet="theorem t : 1 + 1 = 2 := rfl")
            )
        finally:
            reset_resources_for_tests()
        schema_validator.validate(result)
        assert result["status"] == "ok"  # kernel accepted it...
        s = result["soundness"]
        assert s["audit_status"] == "ok"
        assert s["axiom_closure_ok"] is False  # ...but the award is denied
        ok, reasons = formal_award_ok(result)
        assert not ok
        assert any("closure" in r for r in reasons)

    def test_native_decide_flagged_and_closure_fails(self, schema_validator):
        """AC-D.1 flag case: native_decide is flagged textually AND its
        compiler axioms poison the closure."""
        repl = _AuditFakeRepl(
            responses=[
                {"env": 0},
                {
                    "env": 1,
                    "messages": [
                        _info(
                            "'t' depends on axioms: [propext, "
                            "Lean.ofReduceBool, Lean.trustCompiler]"
                        )
                    ],
                },
            ]
        )
        _attach(repl)
        try:
            result = _run(
                handle_lean_verify(
                    snippet="theorem t : 2 + 2 = 4 := by native_decide"
                )
            )
        finally:
            reset_resources_for_tests()
        schema_validator.validate(result)
        s = result["soundness"]
        assert "native_decide" in s["flags"]
        assert s["axiom_closure_ok"] is False
        ok, reasons = formal_award_ok(result)
        assert not ok
        assert any("forbidden flags" in r for r in reasons)
        assert any("closure" in r for r in reasons)

    def test_multiple_decls_audited_with_union_closure(self, schema_validator):
        repl = _AuditFakeRepl(
            responses=[
                {"env": 0},
                {"env": 1, "messages": [_info("'a' depends on axioms: [propext]")]},
                {
                    "env": 2,
                    "messages": [
                        _info("'b' depends on axioms: [Classical.choice]")
                    ],
                },
            ]
        )
        _attach(repl)
        try:
            result = _run(
                handle_lean_verify(
                    snippet=(
                        "theorem a : True := trivial\n"
                        "theorem b : True := trivial"
                    )
                )
            )
        finally:
            reset_resources_for_tests()
        schema_validator.validate(result)
        s = result["soundness"]
        assert s["audited_decls"] == ["a", "b"]
        assert s["axiom_closure"] == ["Classical.choice", "propext"]
        assert s["axiom_closure_ok"] is True
        # The axiom audit runs first over both decls, then the durable-P1
        # kernel-type audit runs `#check @<name>` over the same decls.
        assert [c["cmd"] for c in repl.commands[1:]] == [
            "#print axioms a",
            "#print axioms b",
            "#check @a",
            "#check @b",
        ]
        # kernel_statements populated from the `#check @` queries.
        assert result["kernel_statements"] == {"a": "True", "b": "True"}

    def test_audit_repl_error_fails_closed(self, schema_validator):
        """A REPL crash during the audit leaves the kernel verdict
        intact but the audit failed → award denied."""
        repl = _AuditFakeRepl(
            responses=[{"env": 0}],
            raise_with=LeanReplError("REPL crashed mid-audit"),
            raise_at_call=2,
        )
        _attach(repl)
        try:
            result = _run(
                handle_lean_verify(snippet="theorem t : 1 + 1 = 2 := rfl")
            )
        finally:
            reset_resources_for_tests()
        schema_validator.validate(result)
        assert result["status"] == "ok"
        s = result["soundness"]
        assert s["audit_status"] == "failed"
        assert s["axiom_closure_ok"] is False
        assert not formal_award_ok(result)[0]

    def test_audit_unparseable_output_fails_closed(self, schema_validator):
        repl = _AuditFakeRepl(
            responses=[
                {"env": 0},
                {"env": 1, "messages": [_info("some future output shape")]},
            ]
        )
        _attach(repl)
        try:
            result = _run(
                handle_lean_verify(snippet="theorem t : 1 + 1 = 2 := rfl")
            )
        finally:
            reset_resources_for_tests()
        schema_validator.validate(result)
        assert result["soundness"]["audit_status"] == "failed"
        assert not formal_award_ok(result)[0]

    def test_audit_error_severity_fails_closed(self, schema_validator):
        repl = _AuditFakeRepl(
            responses=[
                {"env": 0},
                {
                    "env": 1,
                    "messages": [
                        {
                            "severity": "error",
                            "pos": {"line": 1, "column": 0},
                            "data": "unknown constant 't'",
                        }
                    ],
                },
            ]
        )
        _attach(repl)
        try:
            result = _run(
                handle_lean_verify(snippet="theorem t : 1 + 1 = 2 := rfl")
            )
        finally:
            reset_resources_for_tests()
        assert result["soundness"]["audit_status"] == "failed"
        assert "unknown constant" in result["soundness"]["audit_detail"]

    def test_missing_env_id_fails_closed(self, schema_validator):
        repl = _AuditFakeRepl(responses=[{}])  # no env key at all
        _attach(repl)
        try:
            result = _run(
                handle_lean_verify(snippet="theorem t : 1 + 1 = 2 := rfl")
            )
        finally:
            reset_resources_for_tests()
        schema_validator.validate(result)
        assert result["soundness"]["audit_status"] == "failed"
        assert "env id" in result["soundness"]["audit_detail"]

    def test_no_auditable_decls_skips_and_denies_award(self, schema_validator):
        repl = _AuditFakeRepl(responses=[{"env": 0}])
        _attach(repl)
        try:
            result = _run(handle_lean_verify(snippet="example : True := trivial"))
        finally:
            reset_resources_for_tests()
        schema_validator.validate(result)
        s = result["soundness"]
        assert s["audit_status"] == "skipped"
        assert s["axiom_closure_ok"] is None
        # Only the verification command ran — no audit query.
        assert len(repl.commands) == 1
        ok, reasons = formal_award_ok(result)
        assert not ok
        assert any("no declarations were audited" in r for r in reasons)

    def test_syntax_only_skips_audit(self, schema_validator):
        repl = _AuditFakeRepl(responses=[{"env": 0}])
        _attach(repl)
        try:
            result = _run(
                handle_lean_verify(
                    snippet="theorem t : True := trivial", mode="syntax_only"
                )
            )
        finally:
            reset_resources_for_tests()
        schema_validator.validate(result)
        assert result["soundness"]["audit_status"] == "skipped"
        assert len(repl.commands) == 1
        assert not formal_award_ok(result)[0]


class TestHandlerProvenance:
    def _repl_dir(self, tmp_path: Path) -> Path:
        d = tmp_path / "replproj"
        d.mkdir()
        (d / "lean-toolchain").write_text(
            "leanprover/lean4:v4.30.0-rc2\n", encoding="utf-8"
        )
        (d / "lake-manifest.json").write_text(
            json.dumps(
                {"packages": [{"name": "mathlib", "rev": "5450b53e5d"}]}
            ),
            encoding="utf-8",
        )
        return d

    def test_provenance_recorded_from_repl_dir(
        self, tmp_path, schema_validator
    ):
        repl = _AuditFakeRepl(
            responses=[
                {"env": 0},
                {"env": 1, "messages": [_info(_CLEAN_AUDIT)]},
            ]
        )
        _attach(repl, lean_repl_dir=self._repl_dir(tmp_path))
        try:
            result = _run(
                handle_lean_verify(snippet="theorem t : 1 + 1 = 2 := rfl")
            )
        finally:
            reset_resources_for_tests()
        schema_validator.validate(result)
        prov = result["provenance"]
        assert prov["lean_toolchain"] == "leanprover/lean4:v4.30.0-rc2"
        assert prov["mathlib_rev"] == "5450b53e5d"
        assert len(prov["transcript_sha256"]) == 64

    def test_transcript_hash_replayable_across_env_ids(
        self, tmp_path, schema_validator
    ):
        """AC-D.3 (unit half): two runs of the same snippet — with
        DIFFERENT volatile REPL env ids — produce identical transcript
        hashes. The real-REPL half lives in tests/eval/test_kat_lean.py."""
        repl_dir = self._repl_dir(tmp_path)
        hashes = []
        for env_id in (0, 7):
            repl = _AuditFakeRepl(
                responses=[
                    {"env": env_id},
                    {"env": env_id + 1, "messages": [_info(_CLEAN_AUDIT)]},
                ]
            )
            _attach(repl, lean_repl_dir=repl_dir)
            try:
                result = _run(
                    handle_lean_verify(snippet="theorem t : 1 + 1 = 2 := rfl")
                )
            finally:
                reset_resources_for_tests()
            hashes.append(result["provenance"]["transcript_sha256"])
        assert hashes[0] == hashes[1]

    def test_disabled_envelope_carries_null_provenance(self, schema_validator):
        _attach(None, enable_lean=False)
        try:
            result = _run(
                handle_lean_verify(snippet="theorem t : True := trivial")
            )
        finally:
            reset_resources_for_tests()
        schema_validator.validate(result)
        assert result["status"] == "unavailable"
        assert result["provenance"]["lean_toolchain"] is None
        assert result["provenance"]["mathlib_rev"] is None
        assert len(result["provenance"]["transcript_sha256"]) == 64
        assert result["soundness"]["audit_status"] == "skipped"
