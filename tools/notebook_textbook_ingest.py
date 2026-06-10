"""Embed m7 textbook chunks and write them into a notebook's LanceDB.

textbook-ingest-m12 — closes the e4 OUTCOME end-to-end (textbook chunks
returned by ``search_papers``) and the follow-up tracked at
``chris-dare-dev/arXMCP#8``.

``ingest.textbook_chunker.chunk_textbook(slug, paper_id)`` renders + chunks
a textbook PDF into :class:`~ingest.chunker_types.ChunkRecord` objects (and
writes per-chunk JSONs) but does NOT write LanceDB. This driver is the
missing embed -> write tail::

    chunk_textbook(slug, paper_id)            -> list[ChunkRecord]
      _build_embed_record(chunks)             -> EmbedRecord   (BGE-M3 dual-column)
      write_chunks(chunks, rec, lancedb_path) -> per-notebook LanceDB

so a textbook chunk becomes retrievable via ``search_papers`` against that
notebook (``ARXMCP_NOTEBOOK=<slug>`` process-level, or
``filters.notebook=<slug>`` per-call) with ``filters.source_kind="textbook"``.

Design (textbook-ingest-m12 research synthesis):

- **Embeds ChunkRecords DIRECTLY** via the embedder's low-level
  :func:`ingest.embedder._encode_batch` + :func:`~ingest.embedder._build_embed_input`
  — the SAME primitives ``ingest/embed_equations.py`` reuses — NOT
  ``embed_paper`` / the global-store NPZ round-trip (which assumes the
  global ``var/arxmcp/corpus/chunks`` layout, not the notebook scope).
  The proof/stmt routing rule is applied from the imported single source,
  never copied (m12 FM-1: a wrong-column placement retrieves the wrong
  body and is NOT caught by ``EmbedRecord`` validation).
- **Always writes the PER-NOTEBOOK LanceDB** (``notebook_lancedb_path(slug)``),
  NEVER the global ``DEFAULT_LANCEDB_PATH`` (m12 FM-3: writing textbook rows
  into the shared arXiv corpus would pollute unfiltered ``search_papers``).
- **No BM25 index.** Notebook retrieval is dense-only at v1
  (notebook-retrieval-m2 AC2: ``retrieval_mode="dense_only"`` over
  ``embedding_stmt``), so a notebook BM25 index would be dead code — and
  skipping it sidesteps the cross-notebook BM25 version-collision surface.
- The chunks carry ``textbook:<slug>:<hex>`` chunk_ids + ``source_kind=
  "textbook"`` from m7; they are passed to ``write_chunks`` UNMODIFIED so
  the m9 prefix<->source_kind invariant holds.

**Known limitation (textbook-ingest-m12 D2):** ``write_chunks`` stamps the
notebook ``corpus-version.json`` marker's ``chunker_version`` field with the
arXiv constant ``"v1.1"`` (``ingest/store.py``), not ``TEXTBOOK_CHUNKER_VERSION
("tv0.1")``. This is observability-only — the integer ``corpus_version`` (the
functional MVCC value) is correct, and BM25 (the only version-gated reader)
is skipped. A future ``store.py`` refactor can thread the textbook version.

Usage::

    uv run python tools/notebook_textbook_ingest.py <slug> \\
        --paper-id textbook:<slug> [--paper-id ...] [--batch-size N] [--dry-run]
"""

from __future__ import annotations

import argparse
import logging
import sys
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from ingest.embedder import (
    EMBED_BATCH_DEFAULT,
    EMBEDDER_VERSION,
    EMBEDDING_DIM,
    _build_embed_input,
    _encode_batch,
)
from ingest.identifiers import is_valid_paper_id
from ingest.schema import EmbedRecord
from ingest.store import write_chunks
from ingest.textbook_chunker import chunk_textbook
from ingest.textbook_markdown_chunker import chunk_textbook_markdown
from tools._notebook_common import (
    NotebookError,
    notebook_lancedb_path,
    validate_slug,
)

if TYPE_CHECKING:
    from ingest.chunker_types import ChunkRecord

logger = logging.getLogger("notebook_textbook_ingest")

#: The encoder seam. ``_encode_batch(texts, chunk_ids=...) -> (ndarray, int)``.
#: Tests inject a synthetic encoder so the embed -> write -> retrieve path
#: runs WITHOUT downloading BGE-M3 (m12 FM-5). Defaults to the real encoder.
EncoderFn = Callable[..., "tuple[Any, int]"]


def _build_embed_record(
    chunks: list[ChunkRecord],
    *,
    batch_size: int = EMBED_BATCH_DEFAULT,
    encoder: EncoderFn = _encode_batch,
) -> EmbedRecord:
    """Embed ``chunks`` into a dual-column :class:`EmbedRecord` via BGE-M3.

    Mirrors ``ingest.embedder._embed_paper_impl``'s build -> batch -> split
    flow EXACTLY, but operates on :class:`ChunkRecord` objects and returns
    the ``EmbedRecord`` in-memory (no NPZ round-trip). Textbook
    ``preamble_text`` is permanently ``""`` (m8 OQ-1 — MinerU expands math at
    render time, so there are no author macros to inherit).

    The proof/stmt routing (``"embedding_proof" if kind == "proof" else
    "embedding_stmt"``) is the SAME single source as
    ``ingest/embedder.py`` — applied here, NOT duplicated as a divergent
    copy. ``EmbedRecord.__post_init__`` validates dup/overlap but does NOT
    detect a wrong-column placement, so keeping one routing source is the
    real FM-1 guard.

    ``encoder`` is injectable (default the real :func:`_encode_batch`) so
    tests pass synthetic L2-normalized vectors and never load the model.
    """
    import numpy as np  # noqa: PLC0415

    embed_inputs: list[str] = []
    routing: list[str] = []  # "embedding_stmt" | "embedding_proof"
    chunk_ids_in_order: list[str] = []
    for chunk in chunks:
        embed_inputs.append(_build_embed_input("", chunk.body_text))
        routing.append(
            "embedding_proof" if chunk.kind == "proof" else "embedding_stmt"
        )
        chunk_ids_in_order.append(chunk.chunk_id)

    if not embed_inputs:
        return EmbedRecord(embedder_version=EMBEDDER_VERSION)

    all_vectors: list[Any] = []
    for start in range(0, len(embed_inputs), batch_size):
        batch_texts = embed_inputs[start : start + batch_size]
        batch_ids = chunk_ids_in_order[start : start + batch_size]
        vectors, _truncated = encoder(batch_texts, chunk_ids=batch_ids)
        all_vectors.append(vectors)
    all_array = np.concatenate(all_vectors, axis=0)

    # Split by routing into the dual columns, kept aligned with the id lists.
    chunk_ids_stmt: list[str] = []
    chunk_ids_proof: list[str] = []
    rows_stmt: list[Any] = []
    rows_proof: list[Any] = []
    for i, column in enumerate(routing):
        if column == "embedding_proof":
            chunk_ids_proof.append(chunk_ids_in_order[i])
            rows_proof.append(all_array[i])
        else:
            chunk_ids_stmt.append(chunk_ids_in_order[i])
            rows_stmt.append(all_array[i])

    embedding_stmt = (
        np.stack(rows_stmt, axis=0)
        if rows_stmt
        else np.zeros((0, EMBEDDING_DIM), dtype=np.float32)
    )
    embedding_proof = (
        np.stack(rows_proof, axis=0)
        if rows_proof
        else np.zeros((0, EMBEDDING_DIM), dtype=np.float32)
    )
    return EmbedRecord(
        chunk_ids_stmt=chunk_ids_stmt,
        embedding_stmt=embedding_stmt,
        chunk_ids_proof=chunk_ids_proof,
        embedding_proof=embedding_proof,
        embedder_version=EMBEDDER_VERSION,
    )


def ingest_textbook_paper(
    slug: str,
    paper_id: str,
    *,
    batch_size: int = EMBED_BATCH_DEFAULT,
    encoder: EncoderFn = _encode_batch,
    dry_run: bool = False,
    chunker: str = "html",
) -> dict[str, Any]:
    """Chunk -> embed -> write ONE textbook paper into the notebook LanceDB.

    Returns ``{"paper_id", "chunks", "lancedb_version"}``. Writes ONLY to the
    per-notebook LanceDB (``notebook_lancedb_path(slug)``) — never the global
    ``DEFAULT_LANCEDB_PATH`` (m12 FM-3).

    ``chunker`` selects the chunking strategy: ``"html"`` (default) reads the
    LaTeXML-rendered ``index.html`` via :func:`chunk_textbook`; ``"markdown"``
    reads the MinerU markdown directly via :func:`chunk_textbook_markdown`
    (finer, captures all content, no LaTeXML render —
    textbook-markdown-chunker-m1).
    """
    chunk_fn = (
        chunk_textbook_markdown if chunker == "markdown" else chunk_textbook
    )
    chunks = chunk_fn(slug, paper_id)
    if not chunks:
        logger.warning(
            "no chunks produced for %s / %s via the %s chunker — confirm the "
            "PDF was parsed (%s present for this paper)",
            slug, paper_id, chunker,
            "MinerU markdown under parsed/<id>/**/auto/*.md"
            if chunker == "markdown"
            else "LaTeXML index.html under parsed/<id>/",
        )
        return {"paper_id": paper_id, "chunks": 0, "lancedb_version": None}

    if dry_run:
        logger.info(
            "[dry-run] %s / %s -> %d chunks (skipping embed + write)",
            slug, paper_id, len(chunks),
        )
        return {"paper_id": paper_id, "chunks": len(chunks), "lancedb_version": None}

    embed_record = _build_embed_record(chunks, batch_size=batch_size, encoder=encoder)
    lancedb_path = notebook_lancedb_path(slug)
    lancedb_path.mkdir(parents=True, exist_ok=True)
    version = write_chunks(chunks, embed_record, lancedb_path=lancedb_path)
    logger.info(
        "%s / %s -> %d chunks written to %s (notebook lancedb version=%d)",
        slug, paper_id, len(chunks), lancedb_path, version,
    )
    return {"paper_id": paper_id, "chunks": len(chunks), "lancedb_version": version}


def run(
    slug: str,
    paper_ids: list[str],
    *,
    batch_size: int = EMBED_BATCH_DEFAULT,
    dry_run: bool = False,
    chunker: str = "html",
) -> int:
    """Ingest each textbook ``paper_id`` into the notebook LanceDB.

    Exit code: 0 = every paper produced >= 1 chunk; 1 = at least one paper
    produced 0 chunks (missing parsed HTML); 2 = no paper_ids supplied.

    Validates the slug + every paper_id UP FRONT (m12 rect F1) so a bad
    slug/paper_id fails fast with a clean :class:`NotebookError` (converted
    to exit-code 1 by :func:`main`) instead of a raw traceback after the
    first chunk attempt — mirroring ``tools/notebook_ingest.py``. Validation
    is explicit here (not a broad ``except ValueError`` in ``main``) so the
    write-time invariants ``write_chunks`` raises — the m9 prefix invariant,
    NULL body_tokens, etc. — still surface as real failures, never masked.
    """
    validate_slug(slug)  # raises NotebookError on a malformed/unsafe slug
    for pid in paper_ids:
        if not is_valid_paper_id(pid):
            raise NotebookError(
                f"invalid paper_id {pid!r}: expected an arXiv id or "
                f"textbook:<slug> form"
            )
    if not paper_ids:
        logger.error("no --paper-id supplied; nothing to ingest")
        return 2
    any_empty = False
    for pid in paper_ids:
        result = ingest_textbook_paper(
            slug, pid, batch_size=batch_size, dry_run=dry_run, chunker=chunker
        )
        if result["chunks"] == 0:
            any_empty = True
    return 1 if any_empty else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Embed textbook chunks into a notebook's LanceDB so they are "
            "retrievable via search_papers (textbook-ingest-m12)."
        ),
    )
    parser.add_argument("slug", help="notebook slug (the textbook notebook)")
    parser.add_argument(
        "--paper-id", dest="paper_ids", action="append", default=[], required=True,
        help="textbook paper_id, e.g. textbook:my-book (repeatable)",
    )
    parser.add_argument(
        "--batch-size", type=int, default=EMBED_BATCH_DEFAULT,
        help=f"BGE-M3 encode batch size (default {EMBED_BATCH_DEFAULT})",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="chunk only; skip embed + LanceDB write",
    )
    parser.add_argument(
        "--chunker", choices=("html", "markdown"), default="html",
        help=(
            "chunking strategy: 'html' (default) reads the LaTeXML-rendered "
            "index.html; 'markdown' reads the MinerU markdown directly "
            "(finer, captures all content, no LaTeXML render)."
        ),
    )
    args = parser.parse_args(argv)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    # m12 rect F1: a malformed/unsafe slug or paper_id raises NotebookError
    # from run()'s up-front validation; convert it to a clean exit-code 1
    # (matching tools/notebook_ingest.py) rather than a raw traceback.
    try:
        return run(
            args.slug, args.paper_ids,
            batch_size=args.batch_size, dry_run=args.dry_run,
            chunker=args.chunker,
        )
    except NotebookError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
