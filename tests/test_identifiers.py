"""Single-source-of-truth lock for the arxmcp identifier regexes.

Closes F11 from the E06_S03 critique. ``ingest/chunker.py``,
``tools/validate_eval_fixtures.py``, and ``server/handlers/chunk.py``
all previously carried independent definitions of the paper_id /
chunk_id format. ``ingest/identifiers.py`` now collapses them to
one; this test asserts every consumer site routes through that
shared module.
"""

from __future__ import annotations

from ingest.chunker import _PAPER_ID_RE
from ingest.identifiers import (
    PAPER_ID_RE,
    is_valid_chunk_id,
    is_valid_paper_id,
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
    """The CHUNK_ID_RE pattern must contain PAPER_ID_PATTERN."""

    def test_chunk_id_re_uses_paper_id_pattern(self):
        from ingest.identifiers import CHUNK_ID_PATTERN, PAPER_ID_PATTERN

        assert PAPER_ID_PATTERN in CHUNK_ID_PATTERN
