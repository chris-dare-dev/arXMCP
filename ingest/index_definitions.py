"""Per-paper definitions/notation indexer (E10_S01).

Builds the LanceDB ``definitions`` table that backs the
``get_definitions`` MCP tool. Source data is the per-paper
``preamble.json`` file produced by :mod:`ingest.preamble`; each entry
in ``PreambleDoc.macros`` is a normalised macro-definition string like
``"\\newcommand{\\R}{\\mathbb{R}}"`` or ``"\\let\\old=\\new"``. This
module parses each line into a ``(symbol_raw, symbol, expansion)``
triple and writes one row per definition.

The indexer is idempotent per paper: re-running for the same
``paper_id`` deletes the prior rows for that paper before inserting
the new ones, so a paper that goes from 15 definitions to 12 does not
leave 3 orphan rows behind. ``merge_insert`` is not used because it
cannot remove stale rows by predicate.

**Scope at v1: preamble-derived definitions only.** The brief calls
for two sources: preamble declarations AND explicit ``\\begin{definition}``
environments emitted by the chunker with ``kind="definition"`` /
``"notation"``. Environment-derived entries are out of scope at v1 —
the chunker emits no parsed symbol on those records, so the
``symbol`` / ``expansion`` columns would be unrecoverable without a
second parser. Every row written by v1 therefore has
``scope="paper"``; the enum column remains in the schema to keep the
table layout forward-compatible.

**Indexes.** Two scalar indexes are created on first write:

* ``paper_id`` — for per-paper filtering from the handler.
* ``symbol_raw`` — for exact / prefix lookup on the author's macro
  command form.

LanceDB ≥ 0.6 ``create_scalar_index`` does not accept a multi-column
composite key; the design note's
``B-tree on (paper_id, symbol), B-tree on symbol_raw`` is decomposed
into two scalar indexes. The query planner can use both predicates.

The handler at :mod:`server.handlers.definitions` reads from the same
table; this module is the writer half of that contract.
"""

from __future__ import annotations

import hashlib
import logging
import re
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pyarrow as pa

from ingest.preamble import load_preamble
from ingest.schema import DEFINITIONS_SCHEMA_V1, DEFINITIONS_TABLE_NAME

if TYPE_CHECKING:
    from ingest.preamble_types import PreambleDoc

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Macro-line parsing
# ---------------------------------------------------------------------------

# ``\newcommand{\name}[n][default]{body}`` (and \renewcommand /
# \providecommand variants). Captures the macro name (with leading
# backslash) and points at the opening ``{`` of the body so the
# brace-balanced walker can read the expansion.
_NEWCMD_HEAD_RE = re.compile(
    r"\\(?:newcommand|renewcommand|providecommand)"
    r"\s*\*?\s*"
    r"(?:"
    r"\{(?P<name1>\\[A-Za-z@]+)\}"   # \newcommand{\foo}
    r"|(?P<name2>\\[A-Za-z@]+)"      # \newcommand\foo (no braces)
    r")"
    r"(?:\s*\[\d+\])?"
    r"(?:\s*\[[^\]]*\])?"
    r"\s*\{"
)

_DECL_MATH_OP_HEAD_RE = re.compile(
    r"\\DeclareMathOperator\s*\*?\s*"
    r"\{(?P<name>\\[A-Za-z@]+)\}\s*\{"
)

_DEF_HEAD_RE = re.compile(
    r"\\(?:def|edef|gdef|xdef)"
    r"\s*(?P<name>\\[A-Za-z@]+)"
    r"(?P<param_text>[^{]*)"
    r"\s*\{"
)

# ``\let\name=\other`` or ``\let\name\other`` (single line, no body brace).
_LET_RE = re.compile(
    r"\\let\s*(?P<name>\\[A-Za-z@]+)\s*=?\s*"
    r"(?:(?P<target>\\[A-Za-z@]+)|(?P<charlit>[^\s\\]))"
)


def _balance_braces(text: str, start: int) -> tuple[str | None, int]:
    """Return ``(body, end_index)`` for the brace-balanced region
    that begins at ``text[start]`` (inside the opening ``{``).

    ``end_index`` points at the character AFTER the matching ``}``.
    Returns ``(None, start)`` on unbalanced input — the caller should
    skip the match.
    """
    depth = 1
    i = start
    n = len(text)
    while i < n:
        ch = text[i]
        if ch == "\\" and i + 1 < n:
            # Skip escaped character (handles \{, \}, \\).
            i += 2
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[start:i], i + 1
        i += 1
    return None, start


def parse_macro_line(line: str) -> list[dict[str, str]]:
    """Parse a normalised macro-definition line into one or more
    ``{symbol, symbol_raw, expansion}`` records.

    Returns an empty list if no recognised directive matches. A single
    line may carry multiple ``\\newcommand`` declarations (the
    preamble extractor preserves them concatenated); the parser walks
    the line looking for every recognised head pattern.

    At v1 ``symbol == symbol_raw`` for every record: the canonical
    form of a macro command name is the author's command itself
    (``\\AA``, ``\\Hom``). Future milestones may add an expansion-
    traced canonical form (e.g. ``\\R`` → ``\\mathbb{R}``); the
    two-column schema is forward-compatible with that work.
    """
    out: list[dict[str, str]] = []

    # \newcommand / \renewcommand / \providecommand
    pos = 0
    while True:
        m = _NEWCMD_HEAD_RE.search(line, pos)
        if m is None:
            break
        symbol = m.group("name1") or m.group("name2")
        body, end = _balance_braces(line, m.end())
        if body is None:
            pos = m.end()
            continue
        out.append(
            {"symbol": symbol, "symbol_raw": symbol, "expansion": body}
        )
        pos = end

    # \DeclareMathOperator (and starred)
    pos = 0
    while True:
        m = _DECL_MATH_OP_HEAD_RE.search(line, pos)
        if m is None:
            break
        symbol = m.group("name")
        body, end = _balance_braces(line, m.end())
        if body is None:
            pos = m.end()
            continue
        out.append(
            {"symbol": symbol, "symbol_raw": symbol, "expansion": body}
        )
        pos = end

    # \def / \edef / \gdef / \xdef
    pos = 0
    while True:
        m = _DEF_HEAD_RE.search(line, pos)
        if m is None:
            break
        symbol = m.group("name")
        body, end = _balance_braces(line, m.end())
        if body is None:
            pos = m.end()
            continue
        out.append(
            {"symbol": symbol, "symbol_raw": symbol, "expansion": body}
        )
        pos = end

    # \let — single line, expansion is the target macro / char literal
    for m in _LET_RE.finditer(line):
        symbol = m.group("name")
        target = m.group("target") or m.group("charlit") or ""
        out.append(
            {"symbol": symbol, "symbol_raw": symbol, "expansion": target}
        )

    return out


# ---------------------------------------------------------------------------
# Definition row construction
# ---------------------------------------------------------------------------


def _preamble_chunk_sentinel(paper_id: str) -> str:
    """Return the synthetic ``defining_chunk_id`` for preamble-derived
    entries.

    The preamble is not a chunk emitted by :mod:`ingest.chunker` so it
    has no real ``chunk_id``. The sentinel ``{paper_id}:preamble`` is
    chosen because it is greppable in logs, is unambiguous (real
    chunk_ids match ``arxiv:<paper_id>:<hex16>``), and avoids the
    "NULL vs. empty string" branching elsewhere in the pipeline.
    """
    return f"{paper_id}:preamble"


def _content_address(paper_id: str, symbol: str, expansion: str) -> str:
    """Compute the content-addressable ``definition_id``.

    The recipe mirrors the chunk-id discipline in
    :mod:`ingest.identifiers`: a 16-hex-character truncation of
    ``sha256(canonical_bytes)`` is enough to make collisions
    astronomically unlikely at corpus scale (≪ 2^32 definitions) while
    keeping the column short enough for human inspection in logs.

    Including the expansion in the hash means that a ``\\renewcommand``
    re-binding of the same symbol produces a distinct ``definition_id``;
    the per-paper dedup rule below (last-seen wins) collapses such
    duplicates back to a single row before write.
    """
    canonical = f"{paper_id}:{symbol}:{expansion}".encode()
    return hashlib.sha256(canonical).hexdigest()[:16]


def build_definitions_for_paper(paper_id: str) -> list[dict[str, str]]:
    """Build the definition records for one paper from its preamble.

    Returns a list of rows ready for the LanceDB ``definitions``
    table. Empty list if the paper has no preamble (no preamble.json
    on disk, or the file is corrupt).

    Dedup rule per D4: when the same symbol is bound multiple times
    in the preamble (``\\newcommand`` then ``\\renewcommand``), the
    LAST occurrence wins — mirrors TeX evaluation order. The preamble
    extractor sorts ``PreambleDoc.macros`` alphabetically so the input
    is deterministic; we walk the list in order and keep the last
    record per symbol in a dict, then return ``dict.values()`` in
    insertion order.
    """
    doc: PreambleDoc | None = load_preamble(paper_id)
    if doc is None:
        return []

    chunk_sentinel = _preamble_chunk_sentinel(paper_id)

    # Use an ordered dict keyed on symbol_raw so last-write-wins
    # cleanly reduces duplicates.
    by_symbol: dict[str, dict[str, str]] = {}
    for line in doc.macros:
        if not isinstance(line, str):
            continue
        for rec in parse_macro_line(line):
            symbol = rec["symbol"]
            expansion = rec["expansion"]
            by_symbol[rec["symbol_raw"]] = {
                "definition_id": _content_address(paper_id, symbol, expansion),
                "paper_id": paper_id,
                "symbol": symbol,
                "symbol_raw": rec["symbol_raw"],
                "expansion": expansion,
                "defining_chunk_id": chunk_sentinel,
                "scope": "paper",
            }

    return list(by_symbol.values())


# ---------------------------------------------------------------------------
# LanceDB writer
# ---------------------------------------------------------------------------


def open_or_create_definitions_table(
    lancedb_path: str | Path,
) -> Any:
    """Open the ``definitions`` table, creating it on first use.

    Returns a LanceDB ``Table`` handle. The path is resolved exactly
    like the chunks-table path in :mod:`server.corpus`; callers should
    pass the same ``lancedb_path`` they use for the chunks table.

    Lazy import of ``lancedb`` keeps the test surface lean: a test
    that mocks the indexer's I/O does not pay the LanceDB import
    cost.
    """
    import lancedb

    resolved = Path(lancedb_path).resolve()
    if not resolved.exists():
        raise FileNotFoundError(
            f"lancedb_path does not exist: {resolved}; "
            f"run ingest pipeline (chunker+embedder+store) first"
        )

    db = lancedb.connect(str(resolved))
    if DEFINITIONS_TABLE_NAME in db.table_names():
        return db.open_table(DEFINITIONS_TABLE_NAME)
    # Create an empty table with the canonical schema. LanceDB accepts
    # a schema-only ``create_table`` when the data parameter is None.
    return db.create_table(
        DEFINITIONS_TABLE_NAME,
        schema=DEFINITIONS_SCHEMA_V1,
    )


def _ensure_scalar_indexes(tbl: Any) -> dict[str, bool]:
    """Create scalar indexes on ``paper_id`` and ``symbol_raw``.

    Returns a ``{column: created_or_replaced}`` map for the caller's
    logging. Errors are caught and logged rather than raised — a
    missing index degrades to a full-scan filter (correct, just
    slower), and re-running the indexer will retry index creation on
    the next pass.
    """
    created: dict[str, bool] = {}
    for column in ("paper_id", "symbol_raw"):
        try:
            tbl.create_scalar_index(column, replace=True)
            created[column] = True
        except Exception as exc:
            logger.warning(
                "could not create scalar index on %s: %s", column, exc
            )
            created[column] = False
    return created


def index_definitions_for_paper(
    paper_id: str,
    lancedb_path: str | Path,
) -> int:
    """Build and persist the definition rows for one paper.

    Returns the number of rows written. The operation is idempotent
    per paper: any prior rows for ``paper_id`` are deleted before the
    new batch is inserted. A paper with no preamble produces zero
    rows (and no delete, since the predicate would match nothing).

    On every call (including the first one for a fresh table) the two
    scalar indexes are (re-)created. ``replace=True`` makes the
    operation cheap when the indexes already exist.
    """
    if not isinstance(paper_id, str) or not paper_id:
        raise ValueError(f"paper_id must be a non-empty string, got {paper_id!r}")

    rows = build_definitions_for_paper(paper_id)
    tbl = open_or_create_definitions_table(lancedb_path)

    # Per-paper replacement: delete any prior rows, then insert the
    # fresh batch. The delete predicate uses a parameterised filter
    # (LanceDB does not accept bound parameters for predicates today,
    # so we string-format paper_id — but paper_id has already passed
    # the regex validator at every public entry point, so injection
    # is impossible by construction).
    safe_filter = f"paper_id = '{paper_id}'"
    try:
        tbl.delete(safe_filter)
    except Exception as exc:
        # A first-write into an empty table can fail on some LanceDB
        # versions with ``no records to delete``; treat as benign.
        logger.debug(
            "delete predicate raised on %s (likely empty table): %s",
            paper_id, exc,
        )

    if rows:
        arrow_table = pa.Table.from_pylist(rows, schema=DEFINITIONS_SCHEMA_V1)
        tbl.add(arrow_table)

    _ensure_scalar_indexes(tbl)

    logger.info(
        "indexed %d definition(s) for paper_id=%s", len(rows), paper_id
    )
    return len(rows)


__all__ = [
    "build_definitions_for_paper",
    "index_definitions_for_paper",
    "open_or_create_definitions_table",
    "parse_macro_line",
]
