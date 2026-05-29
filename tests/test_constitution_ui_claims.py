"""notebook-surface-expansion-m3 — constitution UI-claim guard.

The design constitution used to assert "the MCP tool surface is the UI"
(`.claude/notes/02-architecture-overview.md`, `09-feature-priorities.md`). A
loopback-only Jinja2+htmx operator console at `/ui/` has since shipped, so that
absolute is FALSE. m3 reworded those two notes and ADDED a "Browser UI surface"
section to `06-mcp-server-design.md` + a console mention to `CLAUDE.md`.

This guard:
  (1) asserts the stale phrase is ABSENT across the TOP-LEVEL constitution
      (`.claude/notes/*.md`, NON-recursive) + `CLAUDE.md` + `README.md` — a broad
      scan, not the vacuous "absent from the two files that never had it"; and
  (2) asserts the UI surface IS now described in `06-mcp-server-design.md` and
      `CLAUDE.md` (so a future deletion can't silently re-open the omission).

Deliberately NON-recursive: frozen milestone-critique artifacts under
`.claude/notes/milestones/` (e.g. `E13_S06/critique-merged.md` "no frontend
exists") are immutable historical records and are NOT scanned.

Pattern mirrors `tests/test_langfuse_doc.py`.
"""

from __future__ import annotations

from pathlib import Path

import pytest

REPO_ROOT: Path = Path(__file__).resolve().parents[1]
NOTES_DIR: Path = REPO_ROOT / ".claude" / "notes"
DESIGN_NOTE: Path = NOTES_DIR / "06-mcp-server-design.md"
CLAUDE_MD: Path = REPO_ROOT / "CLAUDE.md"

#: The stale absolute. Scanned case-insensitively so a reworded-but-still-present
#: variant cannot slip through.
_STALE_PHRASE: str = "mcp tool surface is the ui"


def _scanned_docs() -> list[Path]:
    """Top-level constitution notes (NON-recursive) + CLAUDE.md + README.md."""
    docs = sorted(NOTES_DIR.glob("*.md"))  # non-recursive: excludes milestones/
    docs.append(CLAUDE_MD)
    readme = REPO_ROOT / "README.md"
    if readme.is_file():
        docs.append(readme)
    return docs


class TestStaleClaimAbsent:
    def test_scanned_set_is_nonempty(self) -> None:
        """Guard against a glob that silently matches nothing (vacuous pass)."""
        docs = _scanned_docs()
        assert len(docs) >= 10, f"expected the full constitution, got {len(docs)}"
        # The two files that historically carried the claim must be in scope.
        names = {d.name for d in docs}
        assert "02-architecture-overview.md" in names
        assert "09-feature-priorities.md" in names

    @pytest.mark.parametrize("doc", _scanned_docs(), ids=lambda p: p.name)
    def test_stale_ui_claim_absent(self, doc: Path) -> None:
        text = doc.read_text(encoding="utf-8").lower()
        assert _STALE_PHRASE not in text, (
            f"{doc.relative_to(REPO_ROOT)} still asserts "
            f"'the MCP tool surface is the UI' — a loopback-only Jinja2+htmx "
            f"operator console at /ui/ ships now (notebook-surface-expansion-m3)."
        )


class TestUiSurfaceDescribed:
    def test_06_describes_ui_surface(self) -> None:
        """06-mcp-server-design.md must now describe the actual UI surface."""
        text = DESIGN_NOTE.read_text(encoding="utf-8")
        assert "Browser UI surface" in text, "06 missing the UI-surface section"
        assert "/ui/" in text, "06 must reference the /ui/ routes"
        assert "htmx" in text.lower(), "06 must name the Jinja2+htmx stack"

    def test_claude_md_mentions_operator_console(self) -> None:
        """CLAUDE.md must mention the shipped browser console (no longer omitted)."""
        text = CLAUDE_MD.read_text(encoding="utf-8")
        assert "/ui/" in text
        assert "operator console" in text.lower() or "browser operator" in text.lower()


class TestDocAccuracyGuards:
    """m3-rect F1/F2/F3: pin the new 06 UI section to facts the code + repo
    actually contain — an inaccurate constitution is worse than a stale one."""

    def test_06_does_not_overstate_issue_as_filed(self) -> None:
        """m3-rect F1: the UI-security-audit issue is PREPARED, not filed (filing
        is the Phase-4 `gh issue create`). 06 must not claim a 'filed issue'."""
        text = DESIGN_NOTE.read_text(encoding="utf-8").lower()
        assert "filed issue" not in text, (
            "06-mcp-server-design.md claims the UI audit is a 'filed issue', but "
            "filing is the Phase-4 external write. Say 'tracked for filing' / "
            "'prepared'; back-fill a real #N only after the issue is actually filed."
        )

    def test_06_does_not_claim_zipbomb_defense(self) -> None:
        """m3-rect F2: the PDF preflight has NO decompression-bomb guard (only
        magic-byte / polyglot / JS-token / page-count checks). 06 must not list
        'zip-bomb' as a current defense and must name the real page-count check."""
        text = DESIGN_NOTE.read_text(encoding="utf-8")
        assert "zip-bomb" not in text.lower(), (
            "06 lists a 'zip-bomb' check the upload preflight does not implement. "
            "Real checks: magic-byte / polyglot / JavaScript-token / page-count."
        )
        assert "page-count" in text.lower(), (
            "06 must name the real declared-page-count preflight cap."
        )

    def test_browser_ui_crossrefs_resolve(self) -> None:
        """m3-rect F3: 02 / 09 / CLAUDE.md cross-reference 06 § 'Browser UI
        surface' by title. Assert the referenced heading actually exists in 06
        (a checked link) and that every referrer's mention is therefore live."""
        design_text = DESIGN_NOTE.read_text(encoding="utf-8")
        assert "## Browser UI surface" in design_text, (
            "06 must keep the literal '## Browser UI surface' heading; renaming it "
            "would orphan the cross-references in 02/09/CLAUDE.md."
        )
        section_title = "Browser UI surface"
        referrers = [
            NOTES_DIR / "02-architecture-overview.md",
            NOTES_DIR / "09-feature-priorities.md",
            CLAUDE_MD,
        ]
        for ref in referrers:
            assert section_title in ref.read_text(encoding="utf-8"), (
                f"{ref.relative_to(REPO_ROOT)} should cross-reference "
                f"06 § '{section_title}' (the live UI-surface section)."
            )
