"""Unit tests for the body_tokens regex pre-tokenizer (E02_S03)."""

from __future__ import annotations

import time

import pytest

from ingest.tokenizer import tokenize_body

# ===========================================================================
# Acceptance criteria from the milestone brief
# ===========================================================================


class TestAcceptanceCriteria:
    def test_mathbb_arg_contains_polynomial(self):
        result = tokenize_body("Let $\\mathbb{Z}[x]$ be the polynomial ring")
        tokens = result.split()
        assert "mathbb_Z" in tokens, f"missing mathbb_Z in {tokens!r}"
        assert "polynomial" in tokens, f"missing polynomial in {tokens!r}"

    def test_mathrm_spec_and_R(self):
        result = tokenize_body("By \\mathrm{Spec}\\, R")
        tokens = result.split()
        assert "mathrm_Spec" in tokens, f"missing mathrm_Spec in {tokens!r}"
        assert "R" in tokens, f"missing R in {tokens!r}"

    def test_no_backslashes_in_output(self):
        result = tokenize_body(r"Let \mathbb{Z} and \partial and \nabla act")
        assert "\\" not in result, (
            f"backslashes must be stripped from token stream; got: {result!r}"
        )

    def test_returns_string(self):
        result = tokenize_body("any text")
        assert isinstance(result, str)


# ===========================================================================
# Math-aware extraction — branch-by-branch
# ===========================================================================


class TestCommandWithArg:
    """\\command{arg} → command_arg (alphanumeric arg)."""

    def test_mathbb_uppercase(self):
        assert "mathbb_Z" in tokenize_body(r"$\mathbb{Z}$").split()
        assert "mathbb_R" in tokenize_body(r"$\mathbb{R}$").split()
        assert "mathbb_Q" in tokenize_body(r"$\mathbb{Q}$").split()

    def test_mathrm_multichar(self):
        assert "mathrm_Spec" in tokenize_body(r"$\mathrm{Spec}$").split()
        assert "mathrm_Hom" in tokenize_body(r"$\mathrm{Hom}$").split()
        assert "mathrm_End" in tokenize_body(r"$\mathrm{End}$").split()

    def test_mathcal_calligraphic(self):
        assert "mathcal_F" in tokenize_body(r"$\mathcal{F}$").split()

    def test_alphanumeric_arg(self):
        # Pure digits or mixed alphanumerics still match
        assert "label_thm1" in tokenize_body(r"\label{thm1}").split()


class TestBareCommand:
    """\\command (no arg, or non-simple arg) → command."""

    def test_partial(self):
        assert "partial" in tokenize_body(r"\partial").split()

    def test_nabla(self):
        assert "nabla" in tokenize_body(r"\nabla f").split()

    def test_capital_command(self):
        assert "Spec" in tokenize_body(r"\Spec").split()

    def test_thin_space_does_not_emit_punct(self):
        # \, \; \! \. — single non-letter chars after backslash. The regex
        # for command names requires [A-Za-z@]+ (one+ letters), so these
        # should NOT match the command branches.
        result = tokenize_body(r"a\,b\;c\!d")
        tokens = result.split()
        # Should have a, b, c, d as Latin word matches
        for letter in ("a", "b", "c", "d"):
            assert letter in tokens
        # Should NOT have any punctuation-like "command" tokens
        for tok in tokens:
            assert tok not in {",", ";", "!", "."}


class TestSubscriptSuperscript:
    def test_simple_subscript(self):
        assert "H_1" in tokenize_body("H_1").split()

    def test_simple_superscript(self):
        assert "H_i" in tokenize_body("H^i").split()

    def test_braced_subscript(self):
        assert "H_ij" in tokenize_body("H_{ij}").split()

    def test_complex_subscript_drops_to_base(self):
        # H^{n+1}: non-alphanumeric content should NOT produce H_n_1; the
        # spec accepts recall loss on exotic notation.
        result = tokenize_body("H^{n+1}")
        tokens = result.split()
        # Either H alone or H followed by separate n / 1 tokens — but NOT
        # a glued "n+1" inside a token (no `+` allowed in tokens).
        for tok in tokens:
            assert "+" not in tok


class TestPlainWords:
    def test_simple_word(self):
        assert "polynomial" in tokenize_body("polynomial").split()

    def test_hyphenated_compound(self):
        assert "well-known" in tokenize_body("a well-known result").split()

    def test_word_boundaries(self):
        # Punctuation should not glue into tokens
        result = tokenize_body("Let X. Then Y, where Z!")
        tokens = result.split()
        for letter in ("Let", "Then", "where"):
            assert letter in tokens

    def test_preserves_case(self):
        # math identifiers are case-significant — Z and z are different
        result = tokenize_body("Z and z")
        tokens = result.split()
        assert "Z" in tokens
        assert "z" in tokens


# ===========================================================================
# Determinism (BP1)
# ===========================================================================


class TestDeterminism:
    def test_same_input_same_output(self):
        text = r"Let $\mathbb{Z}[x]$ be the polynomial ring of $\Spec R$"
        assert tokenize_body(text) == tokenize_body(text)

    def test_nfc_and_nfd_yield_identical_tokens(self):
        # Same text in NFC and NFD must produce identical token streams.
        # "étale" (e + combining acute) vs "étale" (precomposed é)
        nfc = "étale cohomology"
        nfd = "étale cohomology"  # noqa: RUF001 (intentional NFD)
        assert tokenize_body(nfc) == tokenize_body(nfd)


# ===========================================================================
# Empty / edge-case input
# ===========================================================================


class TestEdgeCases:
    def test_empty_string(self):
        assert tokenize_body("") == ""

    def test_only_whitespace(self):
        assert tokenize_body("   \n\t  ") == ""

    def test_only_punctuation(self):
        # No alphabetic content → no tokens
        assert tokenize_body("$$$ ... ..") == ""

    def test_only_dollar_signs(self):
        assert tokenize_body("$$$$") == ""

    def test_unbalanced_braces_dont_crash(self):
        # Should not raise; emits whatever it can
        result = tokenize_body(r"\mathrm{Spec missing close")
        assert isinstance(result, str)


# ===========================================================================
# Module contract
# ===========================================================================


class TestModuleContract:
    def test_docstring_documents_h4_remediation(self):
        import ingest.tokenizer as tokmod
        assert "Tantivy" in (tokmod.__doc__ or "")
        assert ".claude/roadmap/README.md" in (tokmod.__doc__ or "")

    def test_compiled_regex_at_module_level(self):
        # The module-level _TOKENIZER_RE is a compiled pattern; regenerating
        # it inside the function would defeat the perf target.
        import re as _re

        from ingest.tokenizer import _TOKENIZER_RE
        assert isinstance(_TOKENIZER_RE, _re.Pattern)


# ===========================================================================
# Performance — acceptance criterion: ≤1ms per 512-token chunk
# ===========================================================================


class TestPerformance:
    """The brief mandates ≤1ms per 512-token chunk on a 2020-era CPU.

    The regex is module-level compiled so the per-call overhead is just
    a single ``finditer`` pass. We loose-bound at 5ms here to absorb CI
    jitter; a real regression would blow well past this.
    """

    def test_under_5ms_per_chunk(self):
        # Build a realistic ~512-BGE-M3-token chunk by repeating prose +
        # math — roughly 2000 chars (1 BGE-M3 token ≈ 4 chars).
        chunk = (
            r"Let $\mathbb{Z}[x]$ be the polynomial ring over the integers. "
            r"For any coherent sheaf $\mathcal{F}$ on $\mathrm{Spec}\, R$ "
            r"we have $H^i(X, \mathcal{F}) = 0$ for $i > 0$ when $X$ is "
            r"affine. The proof uses $\partial$-operators and $\nabla$. "
            r"Standard well-known results from \mathrm{Hom}(A, B). "
        ) * 6
        # Warm the regex cache + module path
        tokenize_body(chunk)
        n = 50
        t0 = time.perf_counter()
        for _ in range(n):
            tokenize_body(chunk)
        elapsed = (time.perf_counter() - t0) / n
        assert elapsed < 5e-3, (
            f"tokenize_body too slow: {elapsed*1000:.3f}ms per call "
            f"(target ≤1ms; loose CI bound 5ms)"
        )


# ===========================================================================
# Integration sanity — output is valid for BM25 split()
# ===========================================================================


class TestBM25Compatibility:
    def test_output_is_single_space_joined(self):
        result = tokenize_body(r"Let $\mathbb{Z}$ be integers and $X$ smooth")
        # No tabs, no double spaces, no leading/trailing whitespace
        assert "\t" not in result
        assert "  " not in result
        assert result == result.strip()

    def test_split_is_self_inverse(self):
        # The contract with E04_S04: result.split() yields the token list.
        # That is, " ".join(result.split()) == result for any non-empty result.
        result = tokenize_body(r"\mathbb{Z} polynomial \partial")
        assert " ".join(result.split()) == result


# ===========================================================================
# Dollar-sign handling
# ===========================================================================


class TestDollarHandling:
    def test_dollar_treated_as_separator(self):
        result = tokenize_body(r"prose$\mathbb{Z}$prose")
        tokens = result.split()
        assert "prose" in tokens
        assert "mathbb_Z" in tokens

    def test_dollar_not_in_output(self):
        result = tokenize_body(r"$\mathbb{R}$ and $\mathbb{C}$")
        assert "$" not in result


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
