"""Equation atom extractor (E10_S03b) — closes H5.

Walks the LaTeXML HTML output for a paper at
``var/arxmcp/corpus/parsed/<paper_id>/index.html`` (the same file the
chunker reads), extracts every display-math equation atom, and writes
the rows to the ``equations`` LanceDB table.

**Display math only at v1.** Inline math (``<math display="inline">``
outside an ``ltx_eqn_table`` container) is dense and sub-equational
— each fragment is a sub-expression, not a semantically complete
equation. Scope: ``<table class~="ltx_eqn_table">`` AND
``<tbody id="S*.E*">`` inside ``<table class~="ltx_equationgroup">``.

**`presentation_latex` is `<math alttext="...">`** verbatim. LaTeXML
normalizes whitespace in the attribute; we don't NFC-normalize on
top (matches chunker discipline at ``ingest/chunker.py::_element_text``).

**`mathml` is the serialized `<math>` element** including the wrapper,
so the downstream tree indexer at
:func:`server.retrieval.equations.parse_mathml_to_tree` can re-parse
via ``defusedxml.ElementTree.fromstring`` without surgery.

**`label` is the LaTeXML sequential id suffix** (e.g. ``E1`` from
``id="S0.E1"``), NOT the human-facing ``(1)`` from the
``ltx_tag_equation`` span. The id is the stable handle that matches
``\\eqref{}`` href targets in the rendered HTML; the human-facing
number is a display-format artifact.

**Align-group stitching.** A ``\\begin{align}`` block produces a
``<table class="ltx_equationgroup">`` with one ``<tbody>`` per
labeled row; each ``<tbody>`` holds multiple ``<math display="inline">``
cells. We treat each ``<tbody>`` as ONE equation atom — concatenate
the ``alttext`` of every ``<math>`` cell (space-joined) for
``presentation_latex``, serialize the whole ``<tbody>`` for ``mathml``.

**`parent_chunk_id = None`** at v1. Reimplementing the chunker's
section-path resolution to synthesize a parent linkage adds
significant scope for zero retrieval benefit; the
``server/retrieval/equations.py`` dual-path dense step bypasses the
chunks proxy join once ``embedding_eq`` is populated.

**`context_sentence` is the enclosing ``<p>`` element's text**, capped
at 4000 characters (matches the handler-side ``latex_or_mathml``
Pydantic constraint). No sentence tokenization at v1.

**Concurrency.** Single-writer-per-paper contract; callers MUST
serialize concurrent invocations against the same LanceDB table. The
delete-then-insert pair (per-paper sweep) is two separate MVCC
commits; concurrent runs can interleave and orphan rows.
"""

from __future__ import annotations

import hashlib
import logging
import re
from pathlib import Path
from typing import Any

import pyarrow as pa
from bs4 import BeautifulSoup, Tag

from ingest.identifiers import is_valid_arxiv_paper_id
from ingest.index_equations import open_or_create_equations_table
from ingest.schema import EQUATIONS_SCHEMA_V1

logger = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parent.parent
PARSED_DIR = REPO_ROOT / "var" / "arxmcp" / "corpus" / "parsed"

#: Cap on the ``context_sentence`` column. Matches the handler-side
#: ``latex_or_mathml`` Pydantic max_length so corpus and query rows
#: are bounded by the same constant.
MAX_CONTEXT_SENTENCE_CHARS: int = 4000

#: Regex matching the LaTeXML id pattern for a numbered equation row
#: (`S<section>.E<equation_index>`). The trailing capturing group is
#: the ``label`` value we store.
_EQ_ID_RE = re.compile(r"^S\d+(?:\.SS\d+)*\.E\d+$")


# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------


def _equation_id(paper_id: str, mathml: str, label: str | None) -> str:
    """Compute the content-addressable ``equation_id``.

    NUL-byte separators prevent boundary collisions
    (paper_id ``"AB"`` + mathml ``"C"`` vs paper_id ``"A"`` + mathml
    ``"BC"`` would otherwise share an input). 16 hex chars = 64 bits
    of entropy — collision-free at corpus scale.
    """
    payload = (
        paper_id.encode("utf-8") + b"\x00"
        + mathml.encode("utf-8") + b"\x00"
        + (label or "").encode("utf-8")
    )
    return f"arxiv:{paper_id}:{hashlib.sha256(payload).hexdigest()[:16]}"


# ---------------------------------------------------------------------------
# HTML helpers
# ---------------------------------------------------------------------------


def _enclosing_paragraph_text(eq_table: Tag) -> str:
    """Return the text of the paragraph that precedes the equation.

    Walks up the DOM looking for a sibling ``<p>``; falls back to
    the ancestor ``<div class="ltx_para">``'s first ``<p>`` child.
    Returns an empty string when no candidate paragraph exists.
    Capped at :data:`MAX_CONTEXT_SENTENCE_CHARS` to keep row sizes
    bounded.
    """
    sibling = eq_table.find_previous_sibling("p")
    if sibling is None:
        para_ancestor = eq_table.find_parent("div", class_="ltx_para")
        if para_ancestor is not None:
            sibling = para_ancestor.find("p")
    if sibling is None:
        return ""
    text = sibling.get_text(separator=" ", strip=True)
    return text[:MAX_CONTEXT_SENTENCE_CHARS]


def _ltx_tag_label(eq_container: Tag) -> str | None:
    """Return the LaTeXML id suffix (``E1``, ``E2``) for a numbered
    equation, or ``None`` if the container has no stable id.

    Prefers the container's own ``id`` (``S0.E1``); the last
    dot-delimited segment is the human-stable label. Returns ``None``
    if the id doesn't match the LaTeXML equation-id pattern.
    """
    raw_id = eq_container.get("id") or ""
    if not raw_id:
        return None
    if not _EQ_ID_RE.match(raw_id):
        return None
    return raw_id.rsplit(".", 1)[-1]


def _math_alttext(math: Tag) -> str:
    """Return the ``alttext`` attribute, defaulting to empty string."""
    return (math.get("alttext") or "").strip()


def _serialize_mathml(tag: Tag) -> str:
    """Return the string form of an element including its wrapper.

    ``str(tag)`` includes the opening + closing tags, matching what
    :mod:`defusedxml.ElementTree.fromstring` expects.
    """
    return str(tag)


# ---------------------------------------------------------------------------
# Atom extraction
# ---------------------------------------------------------------------------


def _extract_equation_atom(eq_table: Tag, paper_id: str) -> dict[str, Any] | None:
    """Extract one ``\\begin{equation}``-style atom.

    Detection: ``<table class~="ltx_eqn_table">`` with at least one
    direct ``<math display="block">`` descendant. Returns ``None`` if
    the table has no usable ``alttext`` (treats it as malformed
    LaTeXML output rather than crashing).
    """
    math = eq_table.find("math", attrs={"display": "block"})
    if math is None:
        # Some single-equation tables render without an explicit
        # display="block" — fall back to the first <math> child.
        math = eq_table.find("math")
    if math is None:
        return None

    alttext = _math_alttext(math)
    if not alttext:
        return None

    mathml = _serialize_mathml(math)
    label = _ltx_tag_label(eq_table)
    context = _enclosing_paragraph_text(eq_table)
    eq_id = _equation_id(paper_id, mathml, label)

    return {
        "equation_id": eq_id,
        "paper_id": paper_id,
        "label": label,
        "presentation_latex": alttext,
        "mathml": mathml,
        "ascii_form": "",
        "context_sentence": context,
        "parent_chunk_id": None,
        "mathml_tree_json": None,
        "embedding_eq": None,
    }


def _extract_align_group_atoms(
    group_table: Tag, paper_id: str
) -> list[dict[str, Any]]:
    """Extract atoms from an ``\\begin{align}``-style group table.

    Each labeled ``<tbody>`` in a ``ltx_equationgroup`` table is ONE
    atom. We concatenate the ``alttext`` of every ``<math>`` cell in
    the tbody (space-joined) for ``presentation_latex``, and
    serialize the whole tbody for ``mathml`` (preserving the
    structural relationship between LHS and RHS columns for the TED
    tree).
    """
    out: list[dict[str, Any]] = []
    for tbody in group_table.find_all("tbody"):
        tbody_id = tbody.get("id") or ""
        if not _EQ_ID_RE.match(tbody_id):
            continue
        maths = tbody.find_all("math")
        if not maths:
            continue
        alt_parts: list[str] = []
        for math in maths:
            alt = _math_alttext(math)
            if alt:
                alt_parts.append(alt)
        if not alt_parts:
            continue
        presentation_latex = " ".join(alt_parts)
        # F2 (E10_S03b critique) close — wrap the tbody contents in a
        # synthetic ``<math display="block">`` so the downstream TED
        # tree root is ``math``, matching single-equation atoms. The
        # previous serialization used ``str(tbody)`` which made the
        # TED root ``tbody`` and align-group atoms TED-incomparable
        # with single-equation atoms (empirically scored 0.79 vs 0.0
        # for trivial-equivalent content).
        #
        # We strip the inner per-cell ``<math>`` wrappers when
        # stitching so a single-cell align row becomes
        # ``<math><mrow>...</mrow></math>``, structurally identical
        # to its ``\\begin{equation}`` counterpart with the same
        # content. The cell wrappers are layout artifacts of the
        # align environment, not semantically meaningful tree
        # levels — preserving them would re-introduce the level
        # mismatch that F2 is closing.
        inner_parts = [
            m.decode_contents() for m in maths
        ]
        mathml = (
            '<math xmlns="http://www.w3.org/1998/Math/MathML" '
            f'display="block">{"".join(inner_parts)}</math>'
        )
        label = tbody_id.rsplit(".", 1)[-1]
        context = _enclosing_paragraph_text(group_table)
        eq_id = _equation_id(paper_id, mathml, label)
        out.append(
            {
                "equation_id": eq_id,
                "paper_id": paper_id,
                "label": label,
                "presentation_latex": presentation_latex,
                "mathml": mathml,
                "ascii_form": "",
                "context_sentence": context,
                "parent_chunk_id": None,
                "mathml_tree_json": None,
                "embedding_eq": None,
            }
        )
    return out


def extract_equation_atoms_from_html(
    html: str, paper_id: str
) -> list[dict[str, Any]]:
    """Walk a LaTeXML HTML string and return every equation atom.

    Pure function — no I/O. Used by the indexer below AND by tests
    that load hand-crafted fixture HTML.

    Detection rules:
    - ``<table class="ltx_equation ltx_eqn_table">`` (single
      equation environment) → one atom via
      :func:`_extract_equation_atom`.
    - ``<table class="ltx_equationgroup ltx_eqn_table">`` (align /
      gather / etc.) → one atom per labeled ``<tbody>`` via
      :func:`_extract_align_group_atoms`.
    - Inline math (``<math display="inline">`` outside any
      ``ltx_eqn_table``) is SKIPPED at v1.
    """
    soup = BeautifulSoup(html, "html.parser")
    atoms: list[dict[str, Any]] = []

    for table in soup.find_all("table"):
        css = " ".join(table.get("class") or [])
        if "ltx_equationgroup" in css:
            atoms.extend(_extract_align_group_atoms(table, paper_id))
        elif "ltx_eqn_table" in css and "ltx_equation" in css:
            atom = _extract_equation_atom(table, paper_id)
            if atom is not None:
                atoms.append(atom)

    # Deduplicate by equation_id — a future LaTeXML version that
    # nests labeled groups inside single-equation tables would
    # otherwise produce duplicates. First-seen wins.
    seen: set[str] = set()
    deduped: list[dict[str, Any]] = []
    for atom in atoms:
        if atom["equation_id"] in seen:
            continue
        seen.add(atom["equation_id"])
        deduped.append(atom)
    return deduped


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------


def _parsed_html_path(paper_id: str) -> Path:
    """Default location of the LaTeXML HTML for a given paper."""
    return PARSED_DIR / paper_id / "index.html"


def _table_has_any_rows_for_paper(tbl: Any, paper_id: str) -> bool:
    """Return True iff ``tbl`` contains at least one row with
    ``paper_id == <paper_id>``.

    Precondition check for the delete-then-insert idempotency pattern
    (F5 from the E10_S03b critique). Counting via a filtered Arrow
    batch is bounded by the per-paper row count (low hundreds for
    pathological hep-th papers); the cost is negligible relative to
    the HTML parse upstream.
    """
    try:
        batches = (
            tbl.search()
            .where(f"paper_id = '{paper_id}'")
            .limit(1)
            .to_arrow()
        )
        return batches.num_rows > 0
    except Exception:
        # Defensive: if the filtered read itself fails, surface the
        # failure on the subsequent delete by returning True so the
        # delete actually runs and raises.
        return True


def extract_equations_for_paper(
    paper_id: str,
    lancedb_path: str | Path,
    html_path: Path | None = None,
) -> int:
    """Extract every equation atom for one paper, persist to LanceDB.

    Returns the number of rows written. Per-paper idempotency: any
    prior rows for ``paper_id`` are deleted before the new batch is
    inserted. A paper with no parseable equations (empty HTML, failed
    LaTeXML conversion, or no display math) produces zero writes and
    is logged but not raised.

    ``html_path`` defaults to the canonical
    ``var/arxmcp/corpus/parsed/<paper_id>/index.html`` location used
    by the chunker; tests override with a tmp_path fixture.
    """
    if not is_valid_arxiv_paper_id(paper_id):
        raise ValueError(
            f"paper_id {paper_id!r} does not match the arXiv id format"
        )

    src = html_path or _parsed_html_path(paper_id)
    if not src.is_file():
        logger.warning(
            "extract_equations: no parsed HTML at %s; skipping paper %s",
            src, paper_id,
        )
        return 0

    html = src.read_text(encoding="utf-8", errors="replace")
    atoms = extract_equation_atoms_from_html(html, paper_id)

    table = open_or_create_equations_table(lancedb_path)
    # Per-paper sweep — delete any prior rows for this paper before
    # the bulk insert. The same pattern E10_S01 / E10_S02 use to
    # keep per-paper writes idempotent in the face of HTML
    # re-renders that change the equation count.
    #
    # F5 (E10_S03b critique) close — narrow the prior broad
    # ``except Exception`` by guarding with a row-count precondition.
    # ``tbl.delete`` on a no-match predicate raises on some LanceDB
    # versions (empty table or no matching rows); we now check
    # whether ANY row for this paper exists BEFORE invoking the
    # delete. Any genuine LanceDB error (schema mismatch, permission
    # denied, disk full) now propagates rather than being swallowed
    # under "first-write may raise". Same row-count-precondition
    # pattern the E10_S01 rect uses.
    safe_filter = f"paper_id = '{paper_id}'"
    if _table_has_any_rows_for_paper(table, paper_id):
        table.delete(safe_filter)

    if not atoms:
        logger.info(
            "extract_equations: 0 equations for paper_id=%s (no display math)",
            paper_id,
        )
        return 0

    arrow_table = pa.Table.from_pylist(atoms, schema=EQUATIONS_SCHEMA_V1)
    table.add(arrow_table)
    logger.info(
        "extract_equations: wrote %d equation atom(s) for paper_id=%s",
        len(atoms), paper_id,
    )
    return len(atoms)


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


def _cli(argv: list[str]) -> int:
    import argparse

    parser = argparse.ArgumentParser(
        description="Extract equation atoms from a paper's LaTeXML HTML.",
    )
    parser.add_argument("paper_id", help="arXiv paper id (e.g. 2401.00001)")
    parser.add_argument(
        "--lancedb-path",
        default=str(REPO_ROOT / "var" / "arxmcp" / "index" / "lancedb"),
        help="LanceDB dataset root (default: var/arxmcp/index/lancedb)",
    )
    parser.add_argument(
        "--html-path",
        default=None,
        help="Override path to the LaTeXML HTML file (default: corpus path)",
    )
    args = parser.parse_args(argv)
    n = extract_equations_for_paper(
        args.paper_id,
        args.lancedb_path,
        html_path=Path(args.html_path) if args.html_path else None,
    )
    print(f"extracted {n} equation(s) for {args.paper_id}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    import sys

    sys.exit(_cli(sys.argv[1:]))


__all__ = [
    "MAX_CONTEXT_SENTENCE_CHARS",
    "extract_equation_atoms_from_html",
    "extract_equations_for_paper",
]
