"""Attribution trailers are banned in commit messages — CLAUDE.md §4.3.

The maintainer removed the mandatory ``Co-Authored-By:`` trailer on
2026-08-24. Agents do not sign their own work in this repo; authorship is the
maintainer's to record.

**Why this needs a test rather than just a paragraph.** The rule inverted, and
an inverted rule is the kind a well-meaning agent silently restores:

* every commit before the cutoff carries the trailer, so ``git log`` is a
  large, consistent body of evidence for the OLD convention — and copying the
  shape of recent commits is exactly how an agent infers a convention;
* the mandate lived in five separate instruction files, so a stale copy left
  anywhere re-teaches it;
* `.claude/references/milestone-pipeline-commit-format.md` is registry-synced
  (see CLAUDE.md §5 — never edit synced copies) and says each repo's CLAUDE.md
  "mandates its own ``Co-Authored-By:`` line". It defers to this repo, so the
  answer here is "none required" — but a future sync could reintroduce
  mandate-shaped prose, and the deferral only works while the files below say
  what they say.

So the ban is re-derived from the on-disk instruction files, and any file that
starts telling an agent to add a trailer fails the suite.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]

#: Every TRACKED file that instructs an agent or contributor how to write a
#: commit. The registry-synced `milestone-pipeline-commit-format.md` is
#: deliberately absent: it is not ours to edit, and it defers to this repo
#: rather than mandating a trailer itself.
INSTRUCTION_FILES: tuple[str, ...] = (
    "CLAUDE.md",
    "CONTRIBUTING.md",
    "CONTRIBUTORS.md",
    ".claude/references/milestone-pipeline-agent-conventions.md",
    ".claude/references/roadmap-arxmcp-integration.md",
)

#: Untracked instruction files: checked when present, skipped when not.
#:
#: `AGENTS.md` is **gitignored by decision** (.gitignore:74-85 — the §1 doc
#: layout restricts the repo root to eight named files and AGENTS.md is not
#: one of them), so it exists on this working copy and on no fresh clone.
#: Asserting on it unconditionally would fail the suite for everyone else,
#: but skipping it entirely would leave the Codex-facing copy of this rule
#: with no cover at all on the machine where it actually exists.
OPTIONAL_INSTRUCTION_FILES: tuple[str, ...] = ("AGENTS.md",)

ALL_INSTRUCTION_FILES: tuple[str, ...] = (
    INSTRUCTION_FILES + OPTIONAL_INSTRUCTION_FILES
)

#: Phrasings that tell a reader to ADD a trailer. Matched case-insensitively.
#: Deliberately about the instruction, not the token: the token appears
#: legitimately in every one of these files, inside the prohibition itself.
MANDATE_PATTERNS: tuple[str, ...] = (
    r"trailer\s+is\s+mandatory",
    r"trailer[^.\n]{0,60}is\s+mandatory",
    r"mandatory[^.\n]{0,40}co-?author",
    r"co-?author trailer\*{0,2}\s+on every",
    r"must\s+add[^.\n]{0,40}co-?authored-by",
    r"append[^.\n]{0,40}co-?authored-by",
)


def _read(relative: str) -> str:
    path = REPO_ROOT / relative
    if not path.is_file():
        if relative in OPTIONAL_INSTRUCTION_FILES:
            pytest.skip(f"{relative} is untracked and absent from this checkout")
        pytest.fail(f"{relative} is missing; the trailer ban lives there")
    return path.read_text(encoding="utf-8")


@pytest.mark.parametrize("relative", ALL_INSTRUCTION_FILES)
def test_no_instruction_file_mandates_a_trailer(relative: str) -> None:
    text = _read(relative)
    for pattern in MANDATE_PATTERNS:
        match = re.search(pattern, text, re.IGNORECASE)
        assert match is None, (
            f"{relative} tells an agent to add an attribution trailer "
            f"({match.group(0)!r} at offset {match.start()}). The trailer was "
            "removed at the maintainer's direction on 2026-08-24 — CLAUDE.md §4.3"
        )


@pytest.mark.parametrize("relative", ALL_INSTRUCTION_FILES)
def test_no_instruction_file_carries_a_paste_ready_trailer(relative: str) -> None:
    """A trailer at the start of a line is a line an agent will copy.

    The commit-template blocks in these files used to end with one, and a
    HEREDOC example is precisely what gets pasted verbatim. Inline mentions
    inside the prohibition are backticked mid-sentence and are fine.
    """
    for number, line in enumerate(_read(relative).splitlines(), start=1):
        assert not line.strip().startswith("Co-Authored-By:"), (
            f"{relative}:{number} is a paste-ready attribution trailer; an "
            "agent copying the example emits it verbatim"
        )


@pytest.mark.parametrize("relative", ("CLAUDE.md", "AGENTS.md"))
def test_the_ban_is_stated_for_both_agent_families(relative: str) -> None:
    """Claude reads CLAUDE.md, Codex reads AGENTS.md. A ban in one is a ban
    for one — and the maintainer asked for both."""
    text = _read(relative).lower()
    assert "no co-author or attribution trailers" in text, (
        f"{relative} must state the ban outright, not merely omit the old rule "
        "— an omission reads as 'unspecified', and git log then supplies the "
        "answer from thousands of pre-cutoff commits"
    )
    for tool in ("claude", "codex"):
        assert tool in text, (
            f"{relative} must name {tool} in the ban; a rule that names only "
            "one agent family invites the other to consider itself exempt"
        )
