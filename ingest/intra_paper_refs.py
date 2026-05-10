"""Intra-paper ``\\ref{}`` chain ingest pass (E09_S03).

Static-analysis pass that adds ``cites`` edges with
``source="intra-paper"`` to the Kùzu graph for papers whose LaTeXML
HTML contains intra-paper ``\\ref{label}`` references resolved to
``theorem_label`` chunks in the same paper.

The brief (`E09-citation-graph.md` § E09_S03):

> The milestone also includes a one-time pass at ingest time that
> reads each chunk's ``theorem_label`` and scans the paper's LaTeXML
> HTML for ``\\ref{<theorem_label>}`` occurrences in other chunks. A
> ``cites`` edge with ``source="intra-paper"`` is added between the
> citing chunk's paper node and the cited theorem's paper node (the
> same paper, since ``\\ref{}`` is typically intra-paper). This is a
> lightweight static analysis pass, not a proof-checker.

Implementation:

1. Iterate over papers (either every paper in the LanceDB chunks
   table, or a caller-provided list).
2. For each paper, open
   ``var/arxmcp/corpus/parsed/<paper_id>/index.html`` and scan for
   ``<a class="ltx_ref" href="#<label>">`` anchors. LaTeXML 0.8.x
   renders ``\\ref{label}`` in this exact form (verified in the
   project's parsed-file output footer).
3. Validate each resolved label: a chunk with
   ``paper_id == X AND theorem_label == label`` must exist in
   LanceDB. Unresolved labels (forward refs to bibliographic items,
   external links, etc.) are silently dropped — the static analysis
   doesn't try to be exhaustive.
4. If any valid intra-paper ref exists for paper ``P``, emit ONE
   ``(P)-[:cites {source: "intra-paper", confidence: 1.0}]->(P)``
   self-edge via the shared ``ingest.graph_ingest._merge_cite``.
   The edge is deduplicated by Cypher's ``MERGE`` keyed on
   ``(src, dst, source)`` — re-running the pass is a no-op.

Self-edge model: the Kùzu schema only has ``papers`` nodes (no chunk
nodes), so the intra-paper edge is necessarily ``papers(P) → papers(P)``.
The ``cite_neighbors(direction="depends_on")`` query then surfaces
this self-loop to the agent as a "this paper has intra-paper
references" signal; chunk-level dep info comes from inspecting the
chunk HTML directly.

Confidence: 1.0. ``\\ref{}`` is curated content (the author wrote both
the ``\\label{}`` and the ``\\ref{}``); the static-analysis label
applies to the EXTRACTION pipeline, not to the EVIDENCE itself. A
lower value would be appropriate if we were extracting refs from raw
prose via NLP. See ``research-synthesis.md`` § 8 for the rationale.

Idempotency: ``MERGE`` upserts on edges + atomic checkpoint
(``var/arxmcp/ops/intra-paper-refs-checkpoint.json``) make re-runs
safe. Failed-parse papers are tracked in ``parse_failures`` and
surfaced as a non-zero exit code.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import kuzu
from bs4 import BeautifulSoup

from ingest.graph_ingest import _merge_cite, save_checkpoint
from ingest.identifiers import is_valid_paper_id
from ingest.kuzudb_schema import apply_schema

logger = logging.getLogger(__name__)

#: LaTeXML emits ``\ref{label}`` as ``<a class="ltx_ref" href="#label" ...>``;
#: we walk the parse tree for elements with class containing ``ltx_ref``.
LTX_REF_CSS_CLASS = "ltx_ref"

#: Default location of LaTeXML output (matches ``tools/fetch_seed.py``).
DEFAULT_PARSED_DIR = Path("var/arxmcp/corpus/parsed")

#: Default Kùzu DB directory. Matches the design notes + bootstrap;
#: the brief's ``kuzudb/`` is documented drift (synthesis § 3).
DEFAULT_KUZUDB_PATH = Path("var/arxmcp/index/kuzu")

#: Default LanceDB chunks-table path; mirrors ``ingest.store``.
DEFAULT_LANCEDB_PATH = Path("var/arxmcp/index/lancedb")

#: Atomic-write checkpoint location.
DEFAULT_CHECKPOINT_PATH = Path("var/arxmcp/ops/intra-paper-refs-checkpoint.json")

#: Checkpoint flush cadence (papers / batch).
CHECKPOINT_BATCH_SIZE = 100

#: Cap on parsed HTML body size we will read into BeautifulSoup. The
#: chunker contract is ~5 MiB per paper; a hostile / corrupt file >
#: 50 MiB is a configuration / disk-state issue, not a parse target.
MAX_HTML_BYTES = 50 * 1024 * 1024


@dataclass(frozen=True)
class _IntraPaperResult:
    """Per-paper output of the scan pass."""

    edges_added: bool
    valid_label_count: int
    raw_ref_count: int


# ---------------------------------------------------------------------------
# HTML parser
# ---------------------------------------------------------------------------


def _extract_intrapaper_labels(html_text: str) -> set[str]:
    """Return the set of intra-paper ``\\ref{}`` labels found in HTML.

    A "valid intra-paper href" is one of the form ``#<label>`` where
    ``<label>`` does NOT contain a ``/`` and does NOT begin with
    ``http`` (those forms are external / cross-paper links). Returns
    a deduped set so we don't emit one edge per occurrence.
    """
    soup = BeautifulSoup(html_text, "html.parser")
    labels: set[str] = set()
    # Use string-class match because BS4's class= filter is exact.
    for anchor in soup.find_all("a", class_=lambda c: c and LTX_REF_CSS_CLASS in c):
        href = anchor.get("href")
        if not href or not isinstance(href, str):
            continue
        if not href.startswith("#"):
            continue
        label = href[1:]
        if not label:
            continue
        if "/" in label:
            # Defensive: cross-document references shouldn't fire
            # this branch in a single-paper LaTeXML output but we
            # filter anyway.
            continue
        if label.startswith(("http", "//")):
            continue
        labels.add(label)
    return labels


def _read_parsed_html(parsed_dir: Path, paper_id: str) -> str | None:
    """Return the parsed HTML for one paper; None if missing.

    Per Threat 7 (``08-security-observability-ops.md``) we cap the
    file size to ``MAX_HTML_BYTES`` rather than blindly reading
    untrusted bytes into memory.
    """
    html_path = parsed_dir / paper_id / "index.html"
    if not html_path.exists():
        return None
    try:
        size = html_path.stat().st_size
    except OSError:
        return None
    if size > MAX_HTML_BYTES:
        logger.warning(
            "parsed HTML for %s is %d bytes (> %d cap); skipping",
            paper_id,
            size,
            MAX_HTML_BYTES,
        )
        return None
    try:
        return html_path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        logger.warning("read failed for %s: %s", paper_id, exc)
        return None


# ---------------------------------------------------------------------------
# LanceDB resolved-label lookup
# ---------------------------------------------------------------------------


def _resolved_labels_for_paper(
    paper_id: str,
    candidate_labels: set[str],
    lancedb_path: Path,
) -> set[str]:
    """Filter ``candidate_labels`` to those backed by a chunk with
    matching ``theorem_label`` in the LanceDB chunks table.

    The query is per-paper (small batch — a paper rarely has > a few
    dozen distinct labels); a single batched query across all papers
    would mix labels from different papers and require Python-side
    grouping anyway.

    When ``lancedb_path`` doesn't exist (e.g. in unit tests that
    avoid materializing a LanceDB table), every label is treated as
    UNRESOLVED — the function returns an empty set and the caller
    emits no edge for that paper. This matches the synthesis's
    "best-effort" framing.
    """
    if not candidate_labels:
        return set()
    if not Path(lancedb_path).exists():
        return set()
    from server.corpus import open_chunks_table

    try:
        table = open_chunks_table(lancedb_path=str(lancedb_path), version=None)
    except FileNotFoundError:
        return set()

    labels_csv = ",".join(f"'{_escape_sql(label)}'" for label in sorted(candidate_labels))
    paper_id_escaped = _escape_sql(paper_id)
    where = (
        f"paper_id = '{paper_id_escaped}' "
        f"AND theorem_label IN ({labels_csv})"
    )
    arrow = (
        table.search()
        .where(where, prefilter=True)
        .limit(len(candidate_labels) * 2)
        .to_arrow()
    )
    found: set[str] = set()
    for raw_label in arrow.column("theorem_label").to_pylist():
        if raw_label:
            found.add(raw_label)
    return found


def _escape_sql(value: str) -> str:
    """SQL-string-literal escape (mirrors ``server.handlers.paper._escape``)."""
    return value.replace("'", "''")


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------


def _load_checkpoint(path: Path) -> dict[str, Any]:
    """Load checkpoint or return a fresh skeleton."""
    skeleton = {"processed": [], "edges_added": [], "parse_failures": []}
    if not path.exists():
        return skeleton
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        logger.warning("checkpoint %s unreadable; starting fresh", path)
        return skeleton
    payload.setdefault("processed", [])
    payload.setdefault("edges_added", [])
    payload.setdefault("parse_failures", [])
    return payload


def process_paper(
    paper_id: str,
    parsed_dir: Path,
    lancedb_path: Path,
    conn: kuzu.Connection,
) -> _IntraPaperResult:
    """Scan one paper for intra-paper refs and emit a self-edge if any.

    Returns an ``_IntraPaperResult`` summarizing the scan; the caller
    aggregates these into the checkpoint state.

    Raises ``RuntimeError`` for unrecoverable per-paper failures
    (missing HTML, IO error). The caller catches and records to
    ``parse_failures``.
    """
    html = _read_parsed_html(parsed_dir, paper_id)
    if html is None:
        raise RuntimeError(f"parsed HTML missing or unreadable for {paper_id}")
    raw_labels = _extract_intrapaper_labels(html)
    valid_labels = _resolved_labels_for_paper(paper_id, raw_labels, lancedb_path)
    if valid_labels:
        # Self-edge: paper P refers to itself via intra-paper labels.
        _merge_cite(
            conn,
            src_paper_id=paper_id,
            dst_paper_id=paper_id,
            source="intra-paper",
            confidence=1.0,
        )
    return _IntraPaperResult(
        edges_added=bool(valid_labels),
        valid_label_count=len(valid_labels),
        raw_ref_count=len(raw_labels),
    )


def ingest(
    paper_ids: list[str],
    db_path: Path,
    parsed_dir: Path,
    lancedb_path: Path,
    checkpoint_path: Path,
    *,
    batch_size: int = CHECKPOINT_BATCH_SIZE,
) -> dict[str, Any]:
    """Run the intra-paper ref-chain scan over ``paper_ids``.

    Returns the final checkpoint state dict (useful for tests).

    Idempotent: re-running with the same checkpoint skips already-
    processed papers; ``MERGE`` upserts make the underlying graph
    write a no-op too.
    """
    for arxiv_id in paper_ids:
        if not is_valid_paper_id(arxiv_id):
            raise ValueError(
                f"paper_id {arxiv_id!r} is not a valid arXiv ID"
            )

    apply_schema(db_path)
    db = kuzu.Database(str(db_path))
    try:
        conn = kuzu.Connection(db)
        state = _load_checkpoint(checkpoint_path)
        processed: set[str] = set(state.get("processed", []))
        edges_added: set[str] = set(state.get("edges_added", []))
        parse_failures: dict[str, str] = {
            entry["paper_id"]: entry.get("error", "")
            for entry in state.get("parse_failures", [])
            if isinstance(entry, dict) and "paper_id" in entry
        }

        new_in_pass = 0
        for paper_id in paper_ids:
            if paper_id in processed:
                continue
            try:
                result = process_paper(paper_id, parsed_dir, lancedb_path, conn)
            except RuntimeError as exc:
                logger.warning(
                    "intra-paper scan failed for %s: %s", paper_id, exc
                )
                parse_failures[paper_id] = str(exc)
                # Still count toward batch for crash resilience.
                new_in_pass += 1
                if new_in_pass % batch_size == 0:
                    _flush_state(state, processed, edges_added, parse_failures, checkpoint_path)
                continue
            # Success path — drop any prior failure entry.
            parse_failures.pop(paper_id, None)
            processed.add(paper_id)
            if result.edges_added:
                edges_added.add(paper_id)
            new_in_pass += 1
            if new_in_pass % batch_size == 0:
                _flush_state(state, processed, edges_added, parse_failures, checkpoint_path)

        _flush_state(state, processed, edges_added, parse_failures, checkpoint_path)
        return state
    finally:
        del db


def _flush_state(
    state: dict[str, Any],
    processed: set[str],
    edges_added: set[str],
    parse_failures: dict[str, str],
    checkpoint_path: Path,
) -> None:
    """Atomic flush of the in-memory state to the checkpoint file."""
    state["processed"] = sorted(processed)
    state["edges_added"] = sorted(edges_added)
    state["parse_failures"] = [
        {"paper_id": pid, "error": err}
        for pid, err in sorted(parse_failures.items())
    ]
    save_checkpoint(checkpoint_path, state)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _list_paper_ids_from_lancedb(lancedb_path: Path) -> list[str]:
    """Return the distinct paper_ids in the LanceDB chunks table.

    Used by the CLI when no ``--seed-file`` is provided.
    """
    if not lancedb_path.exists():
        return []
    from server.corpus import open_chunks_table

    try:
        table = open_chunks_table(lancedb_path=str(lancedb_path), version=None)
    except FileNotFoundError:
        return []
    arrow = table.search().limit(1_000_000).to_arrow()
    seen: set[str] = set()
    for paper_id in arrow.column("paper_id").to_pylist():
        if paper_id and isinstance(paper_id, str):
            seen.add(paper_id)
    return sorted(seen)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--seed-file",
        type=Path,
        default=None,
        help=(
            "optional arXiv-ID seed list to constrain the scan. Default: "
            "scan every paper in the LanceDB chunks table."
        ),
    )
    parser.add_argument(
        "--parsed-dir",
        type=Path,
        default=DEFAULT_PARSED_DIR,
        help=f"LaTeXML output root (default: {DEFAULT_PARSED_DIR})",
    )
    parser.add_argument(
        "--kuzudb",
        type=Path,
        default=DEFAULT_KUZUDB_PATH,
        help=f"Kùzu DB directory (default: {DEFAULT_KUZUDB_PATH})",
    )
    parser.add_argument(
        "--lancedb",
        type=Path,
        default=DEFAULT_LANCEDB_PATH,
        help=f"LanceDB chunks table root (default: {DEFAULT_LANCEDB_PATH})",
    )
    parser.add_argument(
        "--checkpoint",
        type=Path,
        default=DEFAULT_CHECKPOINT_PATH,
        help=f"atomic-write checkpoint path (default: {DEFAULT_CHECKPOINT_PATH})",
    )
    args = parser.parse_args(argv)

    # Ensure the schema is up-to-date so even a first-time operator
    # run has the v2 columns + _schema_meta stamp.
    apply_schema(args.kuzudb)

    if args.seed_file is not None:
        from tools.fetch_seed import read_seed_list

        paper_ids = read_seed_list(args.seed_file)
        if not paper_ids:
            sys.stderr.write(
                f"ERROR: seed file {args.seed_file} contains no IDs\n"
            )
            return 2
    else:
        paper_ids = _list_paper_ids_from_lancedb(args.lancedb)
        if not paper_ids:
            sys.stderr.write(
                "ERROR: no papers found in the LanceDB chunks table at "
                f"{args.lancedb}. Run `make ingest` (or pass --seed-file) "
                "first.\n"
            )
            return 2

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    logger.info(
        "scanning %d paper(s) under %s for intra-paper refs",
        len(paper_ids),
        args.parsed_dir,
    )

    try:
        state = ingest(
            paper_ids=paper_ids,
            db_path=args.kuzudb,
            parsed_dir=args.parsed_dir,
            lancedb_path=args.lancedb,
            checkpoint_path=args.checkpoint,
        )
    except KeyboardInterrupt:
        logger.warning("interrupted by user; checkpoint preserved.")
        return 130

    failures = state.get("parse_failures", [])
    edges_added = state.get("edges_added", [])
    logger.info(
        "done: %d papers processed, %d edges added, %d parse failures",
        len(state.get("processed", [])),
        len(edges_added),
        len(failures),
    )
    if failures:
        sys.stderr.write(
            f"WARNING: {len(failures)} paper(s) hit parse failures during "
            "the intra-paper ref scan. Re-run this command to retry; the "
            f"checkpoint at {args.checkpoint} preserves progress.\n"
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
