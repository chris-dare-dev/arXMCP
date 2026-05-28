"""Unit tests for the OA-allowlist license policy (textbook-ingest-m11).

``server.license_policy.is_open_access`` is the fail-closed predicate that
decides whether ``get_chunk`` surfaces a chunk's full body or truncates it
to :data:`LICENSE_TRUNCATION_CHARS` chars. These tests pin the allowlist
membership + the fail-closed default for None/empty/unknown tokens.
"""

from __future__ import annotations

import pytest

from server.license_policy import (
    LICENSE_TRUNCATION_CHARS,
    OA_ALLOWLIST,
    is_open_access,
)


class TestIsOpenAccess:
    @pytest.mark.parametrize(
        "token",
        ["arxiv-license", "CC-BY", "CC-BY-SA", "CC0", "public-domain", "GFDL"],
    )
    def test_allowlisted_tokens_are_open_access(self, token: str) -> None:
        """Every member of the documented OA allowlist returns True."""
        assert is_open_access(token) is True

    @pytest.mark.parametrize(
        "token",
        ["author-distributed", "copyrighted", "no explicit license", "all-rights-reserved", "BSD"],
    )
    def test_non_allowlisted_tokens_are_not_open_access(self, token: str) -> None:
        """Anything outside the allowlist is non-OA (fail-closed)."""
        assert is_open_access(token) is False

    def test_none_is_fail_closed(self) -> None:
        """A None license (legacy row, missing column) → non-OA."""
        assert is_open_access(None) is False

    def test_empty_string_is_fail_closed(self) -> None:
        """An empty-string license → non-OA (the `if not token` guard)."""
        assert is_open_access("") is False

    def test_case_sensitive_no_lowercasing(self) -> None:
        """The allowlist is exact-string, case-sensitive: a case variant
        is NOT open-access (fail-closed). Prevents a sloppy 'cc-by' from
        being treated as the canonical 'CC-BY'."""
        assert is_open_access("cc-by") is False
        assert is_open_access("ARXIV-LICENSE") is False
        assert is_open_access("Gfdl") is False

    def test_whitespace_padded_token_is_fail_closed(self) -> None:
        """No trimming — a padded token is treated as unknown (non-OA).
        Write-time tokens are exact; padding signals a malformed value."""
        assert is_open_access(" CC-BY ") is False


class TestPolicyConstants:
    def test_truncation_chars_is_300(self) -> None:
        assert LICENSE_TRUNCATION_CHARS == 300

    def test_allowlist_is_the_documented_six_token_set(self) -> None:
        """Pin the allowlist membership so a token add/remove forces a
        deliberate update (+ a snippet-contract.md doc update)."""
        expected = frozenset({
            "arxiv-license", "CC-BY", "CC-BY-SA", "CC0",
            "public-domain", "GFDL",
        })
        assert expected == OA_ALLOWLIST

    def test_allowlist_is_frozen(self) -> None:
        """frozenset → immutable; no handler can mutate the policy."""
        assert isinstance(OA_ALLOWLIST, frozenset)
