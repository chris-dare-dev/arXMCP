"""`AGENTS.md` must not silently drift from `CLAUDE.md`.

Claude reads `CLAUDE.md`; Codex reads `AGENTS.md`. The two are meant to carry
the same contract in different voices, and for six weeks (2026-08-08 ->
2026-09-19) they did not: `AGENTS.md` still mandated a co-author trailer that
`CLAUDE.md` had banned, and its §4.10 state paragraph still said no
`formal_releases` table and no `arxmcp://formal/*` resource existed after both
had landed. A Codex agent reading it was not merely under-informed, it was
misinformed.

Nothing caught that, and the reason is structural rather than an oversight:
`AGENTS.md` is untracked and **gitignored by decision** (the §1 doc layout caps
the repo root at eight named files), so it is absent from every worktree and
every CI checkout. Only the maintainer's own checkout has the file, so only
that checkout can test it. These tests therefore SKIP where the file is
absent, exactly as `tests/test_attribution_trailer_ban.py` does -- a skip is
honest about not having measured, which a pass would not be.

What is asserted here is DERIVED from `CLAUDE.md` rather than hand-listed, so
the gate cannot itself go stale the way the document it guards did.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
CLAUDE_MD = REPO_ROOT / "CLAUDE.md"
AGENTS_MD = REPO_ROOT / "AGENTS.md"
BASELINE = Path(__file__).parent / "fixtures" / "agents_md_section_baseline.json"

#: A section may be terser in the Codex voice, but not by more than this below
#: its recorded baseline. Pure ratchet: the baseline is what the two documents
#: ALREADY are, so this stops further hollowing without pretending the current
#: state is the target. Several sections sit near 0.2 and that is a known debt,
#: recorded rather than asserted away.
_SHRINK_TOLERANCE = 0.05


def _require_agents_md() -> str:
    if not AGENTS_MD.is_file():
        pytest.skip(
            "AGENTS.md is untracked and absent from this checkout "
            "(.gitignore — see the module docstring); drift cannot be measured here"
        )
    return AGENTS_MD.read_text(encoding="utf-8")


def _sections(text: str) -> dict[str, str]:
    """Map normalized heading -> body, for `##`..`####` headings."""
    if text.startswith("---\n"):
        text = text[text.index("\n---\n", 4) + 5:]
    out: dict[str, str] = {}
    current: str | None = None
    buf: list[str] = []
    for line in text.splitlines():
        match = re.match(r"^(#{2,4})\s+(.*)$", line)
        if match:
            if current is not None:
                out[current] = "\n".join(buf)
            current, buf = _key(match.group(2).strip()), []
        else:
            buf.append(line)
    if current is not None:
        out[current] = "\n".join(buf)
    return out


def _key(heading: str) -> str:
    """Normalize a heading so the two voices compare equal."""
    heading = re.sub(r"\bCodex\b", "Claude", heading)
    return re.sub(r"[^a-z0-9]+", " ", heading.lower()).strip()


def test_every_claude_section_exists_in_agents() -> None:
    """A section present for Claude and absent for Codex is a rule one agent
    family is held to and the other has never read."""
    agents = _sections(_require_agents_md())
    claude = _sections(CLAUDE_MD.read_text(encoding="utf-8"))
    # The title differs by design; AGENTS.md may carry Obsidian-only extras.
    missing = [
        k for k in claude
        if k not in agents and not k.startswith("claude md context")
    ]
    assert not missing, (
        "sections in CLAUDE.md with no AGENTS.md counterpart:\n  "
        + "\n  ".join(missing)
        + "\n\nPort the section rather than deleting it from CLAUDE.md."
    )


def test_no_section_is_hollower_than_its_baseline() -> None:
    """Ratchet. Catches a section being gutted while its heading survives --
    the failure mode that hid the stale §4.10 state table behind a heading
    that looked present."""
    agents = _sections(_require_agents_md())
    claude = _sections(CLAUDE_MD.read_text(encoding="utf-8"))
    baseline: dict[str, float] = json.loads(BASELINE.read_text(encoding="utf-8"))

    regressions: list[str] = []
    for key, floor in baseline.items():
        if key not in claude or key not in agents or not claude[key]:
            continue
        ratio = len(agents[key]) / len(claude[key])
        if ratio < floor - _SHRINK_TOLERANCE:
            regressions.append(
                f"  {key}: {ratio:.2f} of CLAUDE.md, baseline {floor:.2f}"
            )
    assert not regressions, (
        "AGENTS.md sections shrank relative to CLAUDE.md:\n"
        + "\n".join(regressions)
        + "\n\nEither port the content across, or — if CLAUDE.md legitimately "
        "grew and the Codex voice stays terser — regenerate the baseline and "
        "say why in the commit."
    )


def test_the_contract_state_date_is_not_behind_claude_md() -> None:
    """§4.10's dated state table is the one part that ROTS rather than merely
    thins: it makes positive claims about what has landed. AGENTS.md carried
    `As of 2026-08-03` for six weeks after two of its "does not exist" rows
    shipped. A date older than CLAUDE.md's means the same rot has recurred.
    """
    pattern = r"As of (\d{4}-\d{2}-\d{2})"
    claude_dates = re.findall(pattern, CLAUDE_MD.read_text(encoding="utf-8"))
    agents_dates = re.findall(pattern, _require_agents_md())
    if not claude_dates or not agents_dates:
        pytest.skip("no dated state table in one of the documents")
    assert max(agents_dates) >= max(claude_dates), (
        f"AGENTS.md's newest dated state claim is {max(agents_dates)}, behind "
        f"CLAUDE.md's {max(claude_dates)}. A stale date on a table of "
        "'what has landed' is a false statement to a Codex agent, not a gap."
    )
