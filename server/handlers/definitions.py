"""``get_definitions`` handler — read per-paper preamble.json macros.

Source: the per-paper ``preamble.json`` written by the E02_S02
preamble extractor at
``var/arxmcp/corpus/preamble/<paper_id>/preamble.json``. Each
``PreambleDoc.macros`` entry is a raw line from the LaTeX source
like ``"\\newcommand{\\R}{\\mathbb{R}}"``; we parse each into
``(symbol, expansion)`` pairs.

When ``term`` is given: filter to symbols matching ``term`` exactly.
Without ``term``: return the full table sorted by symbol.

When the preamble file is absent (paper not yet ingested or
preamble extraction failed — F3 fallback per E02_S02), return
``{macros: [], extraction_status: "no_preamble"}``.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Annotated, Any

from pydantic import Field

from ingest.identifiers import is_valid_paper_id
from server.tools import envelope, get_resources

#: Repo-relative path to per-paper preambles. Mirrors
#: :data:`ingest.preamble.PREAMBLE_DIR`.
PREAMBLE_DIR_NAME = "preamble"

#: ``\newcommand{\X}{...}`` and friends. Matches \newcommand,
#: \renewcommand, \DeclareMathOperator. Captures the symbol name
#: (with leading backslash) and the expansion.
#:
#: F2 fix from the E06_S03 critique: dropped ``re.DOTALL`` and
#: switched to non-greedy ``(.*?)`` so a multi-newcommand source
#: line doesn't slurp across the next ``}``. Brace-balanced
#: expansions with internal ``}`` (e.g. ``\mathbb{R}``) are still
#: handled by the brace-walker fallback in :func:`_extract_pairs`.
_NEWCMD_RE = re.compile(
    r"\\(?:newcommand|renewcommand|DeclareMathOperator\*?)\s*"
    r"(?:\[\d+\])?\s*"
    r"\{(\\[A-Za-z]+|\\[^A-Za-z])\}\s*"
    r"(?:\[\d+\])?\s*"
    r"\{"
)


async def handle_get_definitions(
    paper_id: Annotated[str, Field(min_length=1, description="arXiv paper id")],
    term: Annotated[
        str | None, Field(description="Optional symbol to look up exactly")
    ] = None,
) -> dict[str, Any]:
    # F3 fix from the E06_S03 critique: validate paper_id against
    # the canonical regex BEFORE building a filesystem path. Threat
    # 1 (path traversal) closure on the egress-side handler.
    if not is_valid_paper_id(paper_id):
        raise ValueError(
            f"paper_id {paper_id!r} does not match the arXiv id "
            f"format (new-style YYMM.NNNNN[vN] or old-style "
            f"subject/NNNNNNN[vN])"
        )

    preamble_path = _preamble_path_for(paper_id)
    if not preamble_path.is_file():
        return envelope(
            {
                "extraction_status": "no_preamble",
                "macros": [],
                "paper_id": paper_id,
            }
        )

    try:
        data = json.loads(preamble_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return envelope(
            {
                "extraction_status": "parse_error",
                "macros": [],
                "paper_id": paper_id,
            }
        )

    raw_macros = data.get("macros", []) if isinstance(data, dict) else []
    parsed: list[dict[str, str]] = []
    for line in raw_macros:
        if not isinstance(line, str):
            continue
        parsed.extend(_extract_pairs(line))

    if term is not None:
        parsed = [m for m in parsed if m["symbol"] == term]

    parsed.sort(key=lambda m: m["symbol"])

    return envelope(
        {
            "extraction_status": "ok",
            "macros": parsed,
            "paper_id": paper_id,
            "term": term,
        }
    )


def _extract_pairs(line: str) -> list[dict[str, str]]:
    """Extract every ``\\newcommand``/``\\renewcommand``/
    ``\\DeclareMathOperator`` from ``line``, returning
    ``[{symbol, expansion}, ...]``.

    Uses :data:`_NEWCMD_RE` to find the START of each macro
    declaration, then walks brace-balanced text from the opening
    ``{`` to capture the expansion. Closes F2: a regex with
    greedy matching across newlines slurped the next macro's
    body; the brace walker handles arbitrary nested braces
    correctly.
    """
    out: list[dict[str, str]] = []
    pos = 0
    while True:
        m = _NEWCMD_RE.search(line, pos)
        if m is None:
            break
        symbol = m.group(1)
        body_start = m.end()
        expansion, body_end = _balance_braces(line, body_start)
        if expansion is None:
            # Unbalanced — skip this match, advance past the prefix
            # so the loop doesn't infinite-loop.
            pos = m.end()
            continue
        out.append({"expansion": expansion, "symbol": symbol})
        pos = body_end
    return out


def _balance_braces(text: str, start: int) -> tuple[str | None, int]:
    """Return the substring inside the brace-balanced block that
    begins right after the opening ``{`` at ``start``, plus the
    index AFTER the matching ``}``. Returns ``(None, start)`` on
    unbalanced input.
    """
    depth = 1
    i = start
    while i < len(text):
        c = text[i]
        if c == "\\" and i + 1 < len(text):
            # Escaped character — skip the next char too.
            i += 2
            continue
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return text[start:i], i + 1
        i += 1
    return None, start


def _preamble_path_for(paper_id: str) -> Path:
    """Mirror :func:`ingest.preamble._preamble_out_path` resolution
    without importing it (avoids pulling LaTeXML deps into the
    server process). Caller MUST validate ``paper_id`` first via
    :func:`is_valid_paper_id` (Threat 1 — F3 closure)."""
    r = get_resources()
    # Preamble dir lives under ``var/arxmcp/corpus/preamble/`` — a
    # sibling of the LanceDB index, so we walk up from the LanceDB
    # path to the corpus root.
    lancedb_path = Path(r.config.lancedb_path)
    corpus_root = lancedb_path.parent.parent / "corpus"
    return corpus_root / PREAMBLE_DIR_NAME / paper_id / "preamble.json"
