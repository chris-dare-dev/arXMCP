"""Equation embedding populator (E10_S03b) — closes H5.

Reads rows from the ``equations`` LanceDB table where
``embedding_eq`` is NULL, runs BGE-M3 over
``presentation_latex + " " + context_sentence``, and writes the
L2-normalized 1024-dim vector back via
``merge_insert(on="equation_id")``.

**Idempotency.** A re-run skips any row whose ``embedding_eq`` is
already populated. Never re-embeds.

**Reuses the chunks-embedder batch path.** :func:`ingest.embedder._encode_batch`
is the canonical L2-normalized BGE-M3 batched encoder; we import and
call it directly rather than reimplementing the model lifecycle.
Same batch size (``EMBED_BATCH_DEFAULT = 32``), same dtype
(``float32``), same L2 normalization invariant.

**Concurrency.** Single-writer-per-table contract. SQLite WAL it's
not — LanceDB merge_insert against the same table from two
processes can interleave. Document and serialize externally.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import pyarrow as pa

from ingest.embedder import EMBED_BATCH_DEFAULT, _encode_batch
from ingest.index_equations import open_or_create_equations_table
from ingest.schema import EQUATIONS_SCHEMA_V1

logger = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parent.parent


def _embedding_input(row: dict[str, Any]) -> str:
    """Build the BGE-M3 input text for one equation row.

    Per the brief: ``presentation_latex + " " + context_sentence``.
    Both columns may be empty — the encoder accepts arbitrary
    strings. Stripped to keep model input clean.
    """
    pl = (row.get("presentation_latex") or "").strip()
    ctx = (row.get("context_sentence") or "").strip()
    if pl and ctx:
        return f"{pl} {ctx}"
    return pl or ctx


def embed_pending_equations(
    lancedb_path: str | Path,
    batch_size: int = EMBED_BATCH_DEFAULT,
    *,
    force: bool = False,
) -> dict[str, int]:
    """Populate ``embedding_eq`` for every row where it is NULL.

    Returns a counts dict
    ``{processed, embedded, skipped, truncated_inputs}`` so the caller
    (ops tooling or tests) can verify what landed. Idempotent — a
    re-run on a fully-embedded table writes nothing.

    **`force=True` re-embeds every row.** Used by the LaTeXML-drift
    runbook (E10_S04 F7 close) after a LaTeXML upgrade has changed
    ``presentation_latex`` / ``context_sentence`` values on the
    equations table; the previously-embedded vectors are stale and
    must be recomputed. The previous workflow required an inline
    LanceDB Python snippet to NULL the column first — error-prone
    under operator stress.
    """
    counts = {
        "processed": 0,
        "embedded": 0,
        "skipped": 0,
        "truncated_inputs": 0,
    }

    table = open_or_create_equations_table(lancedb_path)
    arrow = table.to_arrow()
    if arrow.num_rows == 0:
        return counts

    rows = arrow.to_pylist()
    pending: list[dict[str, Any]] = []
    for row in rows:
        counts["processed"] += 1
        if not force and row.get("embedding_eq") is not None:
            counts["skipped"] += 1
            continue
        if not _embedding_input(row):
            # Defensive: a row with both presentation_latex and
            # context_sentence empty has nothing to embed. Skip
            # rather than embedding the empty string.
            counts["skipped"] += 1
            continue
        pending.append(row)

    if not pending:
        logger.info(
            "embed_equations: nothing to embed (processed=%d, skipped=%d)",
            counts["processed"], counts["skipped"],
        )
        return counts

    # Batch through BGE-M3. ``_encode_batch`` returns
    # ``(np.ndarray[float32], truncated_count)``; we accumulate the
    # truncation count for the operator log.
    updated_rows: list[dict[str, Any]] = []
    for start in range(0, len(pending), batch_size):
        batch = pending[start : start + batch_size]
        texts = [_embedding_input(r) for r in batch]
        chunk_ids = [r["equation_id"] for r in batch]
        vectors, truncated = _encode_batch(texts, chunk_ids=chunk_ids)
        counts["truncated_inputs"] += int(truncated)
        for r, vec in zip(batch, vectors, strict=True):
            # Convert the numpy float32 row to a list for PyArrow.
            r["embedding_eq"] = vec.tolist()
            updated_rows.append(r)

    if not updated_rows:
        return counts

    arrow_update = pa.Table.from_pylist(
        updated_rows, schema=EQUATIONS_SCHEMA_V1
    )
    # merge_insert on the primary key — every row in updated_rows
    # already exists by equation_id, so when_matched_update_all
    # updates embedding_eq in-place while preserving every other
    # column (including mathml_tree_json from a prior indexer pass).
    (
        table.merge_insert("equation_id")
        .when_matched_update_all()
        .when_not_matched_insert_all()
        .execute(arrow_update)
    )
    counts["embedded"] = len(updated_rows)

    logger.info(
        "embed_equations: processed=%d embedded=%d skipped=%d truncated=%d",
        counts["processed"], counts["embedded"], counts["skipped"],
        counts["truncated_inputs"],
    )
    return counts


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


def _cli(argv: list[str]) -> int:
    import argparse

    parser = argparse.ArgumentParser(
        description="Populate embedding_eq on the equations table.",
    )
    parser.add_argument(
        "--lancedb-path",
        default=str(REPO_ROOT / "var" / "arxmcp" / "index" / "lancedb"),
        help="LanceDB dataset root (default: var/arxmcp/index/lancedb)",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=EMBED_BATCH_DEFAULT,
        help=f"BGE-M3 batch size (default: {EMBED_BATCH_DEFAULT})",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help=(
            "Re-embed every row, even rows whose embedding_eq is "
            "already populated. Use after a LaTeXML upgrade has "
            "changed the presentation_latex / context_sentence "
            "values on the equations table (the previously-embedded "
            "vectors are stale). See "
            "docs/ops/latexml-drift-runbook.md."
        ),
    )
    args = parser.parse_args(argv)
    counts = embed_pending_equations(
        args.lancedb_path, batch_size=args.batch_size, force=args.force
    )
    print(
        f"processed={counts['processed']} embedded={counts['embedded']} "
        f"skipped={counts['skipped']} truncated={counts['truncated_inputs']}"
    )
    return 0


if __name__ == "__main__":  # pragma: no cover
    import sys

    sys.exit(_cli(sys.argv[1:]))


__all__ = [
    "embed_pending_equations",
]
