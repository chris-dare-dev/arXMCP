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

from server.tools import envelope, get_resources

#: Repo-relative path to per-paper preambles. Mirrors
#: :data:`ingest.preamble.PREAMBLE_DIR`.
PREAMBLE_DIR_NAME = "preamble"

#: ``\newcommand{\X}{...}`` and friends. Matches \newcommand,
#: \renewcommand, \DeclareMathOperator. Captures the symbol name
#: (with leading backslash) and the brace-balanced expansion.
_NEWCMD_RE = re.compile(
    r"\\(?:newcommand|renewcommand|DeclareMathOperator\*?)\s*"
    r"(?:\[\d+\])?\s*"
    r"\{(\\[A-Za-z]+|\\[^A-Za-z])\}\s*"
    r"(?:\[\d+\])?\s*"
    r"\{(.*)\}",
    re.DOTALL,
)


async def handle_get_definitions(
    paper_id: Annotated[str, Field(min_length=1, description="arXiv paper id")],
    term: Annotated[
        str | None, Field(description="Optional symbol to look up exactly")
    ] = None,
) -> dict[str, Any]:
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
    parsed = []
    for line in raw_macros:
        if not isinstance(line, str):
            continue
        m = _NEWCMD_RE.search(line)
        if m is None:
            continue
        symbol, expansion = m.group(1), m.group(2)
        parsed.append({"expansion": expansion, "symbol": symbol})

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


def _preamble_path_for(paper_id: str) -> Path:
    """Mirror :func:`ingest.preamble._preamble_out_path` resolution
    without importing it (avoids pulling LaTeXML deps into the
    server process)."""
    r = get_resources()
    # Preamble dir lives under ``var/arxmcp/corpus/preamble/`` — a
    # sibling of the LanceDB index, so we walk up from the LanceDB
    # path to the corpus root.
    lancedb_path = Path(r.config.lancedb_path)
    # lancedb_path is .../var/arxmcp/index/lancedb -> ../../corpus/preamble/<paper>/preamble.json
    corpus_root = lancedb_path.parent.parent / "corpus"
    return corpus_root / PREAMBLE_DIR_NAME / paper_id / "preamble.json"
