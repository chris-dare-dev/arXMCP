"""Doc-consistency guards for ``lean_verify``'s ``status`` vocabulary.

Regression guards for the two CRITICAL findings of ``verification-contract-m1``
(critique/dedup.md C1, C2 — each independently raised by both critics as M6/M7):

- **C1** — ``.claude/docs/trust-language-policy.md`` asserted that R3's rename
  "has **not** shipped: ``status`` still carries the value ``"ok"``,
  deliberately". After the rename shipped, that sentence did not merely go
  stale — it affirmatively told the next agent that *not* renaming was the
  deliberate current state, inviting a duplicate rename milestone or a revert.
- **C2** — ``CLAUDE.md`` §4.9 rule 1's worked example named ``status:"ok"`` in
  the present tense. CLAUDE.md is re-read at the start of every agent session
  in this repo, so an agent writing a consumer would branch on a token the
  server no longer emits.

Both checks are **derived from the live schema**
(``server/schemas/lean_verify_result.json``), never from a hard-coded token
list. A future revert of the rename that leaves these docs untouched — or a
doc edit that reintroduces a retired token as live — fails here rather than
silently shipping.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = REPO_ROOT / "server" / "schemas" / "lean_verify_result.json"
POLICY_PATH = REPO_ROOT / ".claude" / "docs" / "trust-language-policy.md"
CLAUDE_MD_PATH = REPO_ROOT / "CLAUDE.md"
API_DOC_PATH = REPO_ROOT / "docs" / "api.md"

#: Words that mark a retired token as historical rather than live. A doc may
#: still quote ``status:"ok"`` — the founding defect is worth remembering —
#: but only when the surrounding text says so.
_HISTORICAL_MARKERS = ("renamed", "original", "formerly", "historical", "was ")


def _status_enum() -> list[str]:
    """The live ``status`` enum — the single authority for this module."""
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    return list(schema["properties"]["status"]["enum"])


def _clean_token() -> str:
    """The enum member denoting a clean elaboration with no open goals."""
    enum = _status_enum()
    for candidate in enum:
        if candidate.startswith("elaborated"):
            return candidate
    pytest.fail(
        "No 'elaborated*' member in the live status enum "
        f"({enum!r}). If the clean-path token was renamed again, update this "
        "helper — do not delete the guard."
    )


class TestTrustLanguagePolicyIsNotStale:
    """C1 — the policy must not assert the rename is unshipped."""

    def test_policy_names_the_live_clean_token(self) -> None:
        text = POLICY_PATH.read_text(encoding="utf-8")
        token = _clean_token()
        assert token in text, (
            f"{POLICY_PATH.name} never mentions the live clean-path status "
            f"token {token!r}. The policy is binding constitution "
            "(CLAUDE.md §4.9); it must describe the vocabulary the server "
            "actually emits."
        )

    def test_unshipped_claim_is_marked_superseded(self) -> None:
        """The stale sentence may remain, but only if marked superseded.

        The file's own convention for an Accepted, owner-approved policy is
        append-don't-edit, so the 2026-07-31 claim is preserved verbatim. What
        must hold is that an amendment supersedes it — otherwise the preserved
        text reads as current state.

        Matching is done on whitespace-normalized text with blockquote
        markers stripped: the claim spans a line wrap inside a ``>`` block, so
        a naive substring search silently never matches it. Position is NOT
        checked — the superseding amendment announces itself in its header,
        which precedes the sentence it quotes back.
        """
        raw = POLICY_PATH.read_text(encoding="utf-8")
        flat = re.sub(r"\s+", " ", raw.replace("\n>", " ").replace(">", " "))

        stale_claim = 'still carries the value `"ok"`'
        if stale_claim not in flat:
            return  # claim removed outright; nothing left to supersede

        assert "superseded" in flat.lower(), (
            f"{POLICY_PATH.name} still contains the 2026-07-31 claim that "
            f"status {stale_claim!r} with nothing marking it superseded. "
            "Append a dated amendment (the file's own convention) rather "
            "than editing §2 in place."
        )
        assert _clean_token() in flat, (
            f"{POLICY_PATH.name} marks the old claim superseded but never "
            f"names the token that replaced it ({_clean_token()!r})."
        )


class TestClaudeMdStatusTokensAreLiveOrMarkedHistorical:
    """C2 — CLAUDE.md must not present a retired token as live."""

    def test_every_attributed_status_token_is_live_or_historical(self) -> None:
        text = CLAUDE_MD_PATH.read_text(encoding="utf-8")
        enum = set(_status_enum())
        lines = text.splitlines()

        offenders: list[str] = []
        for i, line in enumerate(lines):
            for token in re.findall(r'status:"([^"]+)"', line):
                if token in enum:
                    continue
                # A retired token is acceptable only when the immediate
                # context marks it as historical.
                window = " ".join(lines[max(0, i - 1) : i + 2]).lower()
                if any(m in window for m in _HISTORICAL_MARKERS):
                    continue
                offenders.append(f"CLAUDE.md:{i + 1}: status:{token!r}")

        assert not offenders, (
            "CLAUDE.md names status token(s) that are not in the live schema "
            "enum and are not marked historical:\n  "
            + "\n  ".join(offenders)
            + f"\n\nLive enum: {sorted(enum)}\n"
            "CLAUDE.md is loaded at the start of every agent session; a "
            "retired token presented as live sends the next agent to branch "
            "on a value the server never emits."
        )

    def test_claude_md_names_the_live_clean_token(self) -> None:
        text = CLAUDE_MD_PATH.read_text(encoding="utf-8")
        token = _clean_token()
        assert token in text, (
            f"CLAUDE.md never mentions the live clean-path status token "
            f"{token!r}. §4.9 rule 1's worked example is the most-read "
            "description of this token in the repo."
        )


class TestApiDocCoversTheWholeStatusEnum:
    """M1 / M8 — the operator-facing wire contract must list every value."""

    def test_every_enum_member_appears_in_api_doc(self) -> None:
        text = API_DOC_PATH.read_text(encoding="utf-8")
        missing = [member for member in _status_enum() if member not in text]
        assert not missing, (
            f"docs/api.md omits live status enum member(s): {missing}. "
            "It is the only operator-facing description of this tool; an "
            "integrator reading it would treat those values as impossible."
        )
