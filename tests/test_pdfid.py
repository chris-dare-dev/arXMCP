"""Unit tests for ``tools.security.pdfid`` (textbook-ingest-m4).

Lock the detection contract for each of the 7 dangerous PDF name
tokens, plus the limitations the module's docstring acknowledges
(compressed-stream evasion, hex-encoded escape). The negative cases
prevent false-positive drift on benign PDF dictionary keys that
contain the substring ``JS`` etc. (e.g. ``/JSON``, ``/JavaScripts``,
hypothetical sibling names).
"""

from __future__ import annotations

import pytest

from tools.security.pdfid import (
    DANGEROUS_PDF_NAMES,
    find_javascript,
)

# ---------------------------------------------------------------------------
# Positive cases — each dangerous token must be detected
# ---------------------------------------------------------------------------


class TestEachDangerousTokenDetected:
    """Every member of DANGEROUS_PDF_NAMES must fire when present
    in plain PDF object-dictionary syntax.
    """

    @pytest.mark.parametrize("token", sorted(DANGEROUS_PDF_NAMES))
    def test_token_detected_in_dict_value(self, token: str) -> None:
        # Synthetic PDF dictionary: << TOKEN /Body 1 >>
        pdf_bytes = (
            b"%PDF-1.4\n"
            b"1 0 obj\n<< "
            + token.encode("ascii")
            + b" (alert(1)) >>\nendobj\n"
        )
        result = find_javascript(pdf_bytes)
        assert token in result, (
            f"token {token!r} not detected; got {result}"
        )

    @pytest.mark.parametrize("token", sorted(DANGEROUS_PDF_NAMES))
    def test_token_detected_followed_by_whitespace(
        self, token: str,
    ) -> None:
        # Real PDFs may format with newlines between key and value.
        pdf_bytes = (
            b"%PDF-1.4\n"
            + token.encode("ascii")
            + b"\n(action body)\n"
        )
        assert token in find_javascript(pdf_bytes)

    @pytest.mark.parametrize("token", sorted(DANGEROUS_PDF_NAMES))
    def test_token_detected_at_eof(self, token: str) -> None:
        # Token at end-of-stream — the lookahead allows \Z.
        pdf_bytes = b"%PDF-1.4\n" + token.encode("ascii")
        assert token in find_javascript(pdf_bytes)


# ---------------------------------------------------------------------------
# Negative cases — benign tokens must NOT false-positive
# ---------------------------------------------------------------------------


class TestNoFalsePositives:
    def test_no_dangerous_tokens_in_clean_pdf(self) -> None:
        # A minimal valid PDF with no dangerous keys.
        pdf_bytes = (
            b"%PDF-1.4\n"
            b"1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n"
            b"2 0 obj\n<< /Type /Pages /Count 1 /Kids [3 0 R] >>\nendobj\n"
        )
        assert find_javascript(pdf_bytes) == []

    def test_json_substring_not_matched(self) -> None:
        # /JSON contains "JS" as a substring but the lookahead at the
        # end of the regex requires a delimiter byte AFTER the token.
        pdf_bytes = b"%PDF-1.4\n/JSON /value\n"
        assert find_javascript(pdf_bytes) == []

    def test_javascripty_substring_not_matched(self) -> None:
        # /JavaScripts (hypothetical longer name) starts with the
        # /JavaScript pattern but the lookahead rejects it.
        pdf_bytes = b"%PDF-1.4\n/JavaScripts /value\n"
        assert find_javascript(pdf_bytes) == []

    def test_aa_in_word_not_matched(self) -> None:
        # /AA must be followed by a delimiter; ``/AABBB`` is not a
        # match (it's a different name token).
        pdf_bytes = b"%PDF-1.4\n/AABBB /value\n"
        assert find_javascript(pdf_bytes) == []


# ---------------------------------------------------------------------------
# Acknowledged limitations — documented in the module docstring
# ---------------------------------------------------------------------------


class TestDocumentedLimitations:
    """These tests document the KNOWN evasion cases. The module
    docstring explicitly names these as out-of-scope for layer-1
    defense; m5's MinerU sandbox is the backstop.
    """

    def test_compressed_stream_js_misses(self) -> None:
        """JS hidden in a FlateDecode-compressed object stream is
        invisible to byte-grep. This is a documented limitation —
        the assertion locks the behavior so a future refactor that
        accidentally adds compressed-stream parsing surfaces here.
        """
        # Synthetic: ``/JS`` does NOT appear in plaintext, only in
        # a compressed stream the byte-grep can't decode.
        pdf_bytes = (
            b"%PDF-1.4\n"
            b"1 0 obj\n<< /Filter /FlateDecode /Length 42 >>\n"
            b"stream\n"
            b"\x78\x9c\x4a\xce\x4f\x49\x55\x28\x4a\xcc\x4d\xcc\xd1\x51\xd0\xb1\xcd\xd5\xd1\xd1\x55"
            b"\nendstream\nendobj\n"
        )
        # No plaintext /JS → no detection.
        assert find_javascript(pdf_bytes) == []

    def test_hex_encoded_token_misses(self) -> None:
        """Hex-escaped name tokens (``/4A53`` = ``/JS``) bypass the
        byte-grep. Documented limitation; m5 MinerU sandbox catches
        execution at runtime.
        """
        # The hex form /#4A#53 is NOT the literal /JS bytes.
        pdf_bytes = b"%PDF-1.4\n/#4A#53 (alert(1))\n"
        assert find_javascript(pdf_bytes) == []


# ---------------------------------------------------------------------------
# Multi-occurrence + ordering
# ---------------------------------------------------------------------------


class TestMultipleOccurrences:
    def test_duplicates_preserved_in_order(self) -> None:
        pdf_bytes = (
            b"%PDF-1.4\n"
            b"/JS (a)\n"
            b"/JavaScript (b)\n"
            b"/JS (c)\n"
        )
        result = find_javascript(pdf_bytes)
        assert result == ["/JS", "/JavaScript", "/JS"]

    def test_longer_token_preferred_over_shorter(self) -> None:
        """Order in the regex alternation is descending-by-length so
        ``/JavaScript`` is matched before ``/JS`` would be (otherwise
        the shorter would consume the leading bytes and the longer
        would never fire). This is the leftmost-first vs longest-
        match behavior in Python's re engine.
        """
        pdf_bytes = b"%PDF-1.4\n/JavaScript (b)\n"
        # Must return /JavaScript, NOT /JS.
        result = find_javascript(pdf_bytes)
        assert result == ["/JavaScript"]


# ---------------------------------------------------------------------------
# Type contract
# ---------------------------------------------------------------------------


class TestTypeContract:
    def test_rejects_non_bytes(self) -> None:
        with pytest.raises(TypeError):
            find_javascript("not bytes")  # type: ignore[arg-type]

    def test_accepts_bytearray(self) -> None:
        # bytearray is bytes-like; the type guard accepts it.
        pdf_bytes = bytearray(b"%PDF-1.4\n/JS (x)\n")
        assert find_javascript(pdf_bytes) == ["/JS"]

    def test_empty_bytes(self) -> None:
        assert find_javascript(b"") == []

    def test_returns_list_not_set(self) -> None:
        result = find_javascript(b"%PDF-1.4\n/JS (a)\n/JS (b)\n")
        # If the implementation deduped this would be 1; the contract
        # is occurrence-preserving so we get 2.
        assert isinstance(result, list)
        assert len(result) == 2
