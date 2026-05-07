"""Dual-column BGE-M3 embedder (E03_S01).

Reads per-paper chunks written by the structural chunker
(``ingest.chunker``) from
``var/arxmcp/corpus/chunks/<paper_id>/``, encodes each chunk's
``preamble_text + "\\n\\n" + body_text`` view through ``BAAI/bge-m3``
pinned at :data:`BGE_M3_COMMIT_SHA`, and writes the 1024-dim L2-normalized
vectors to a parallel per-paper NPZ store at
``var/arxmcp/corpus/embeddings/<paper_id>/embeddings.npz``.

**Why NPZ-first, not direct LanceDB.** The roadmap lists E03_S01 ↔ E04_S01
as a mutual dependency, so neither can literally block on the other. The
NPZ store breaks the deadlock: E03_S01 ships independent of E04_S01, and
E04_S01's ``ingest/store.py`` reads the NPZ alongside the chunk
manifests when building the LanceDB rows. See
``.claude/notes/milestones/E03_S01/research-synthesis.md`` § D1.

**Routing.** ``kind == "proof"`` → ``embedding_proof``; everything else
(``stmt``, ``section``, ``definition``, ``lemma``, ``proposition``, ...)
→ ``embedding_stmt``. The third column ``embedding_eq`` is reserved for
E10_S03 and is always NULL — the embedder never populates it.

**Threat 6 (08-security-observability-ops.md).** The model is loaded
with ``revision=BGE_M3_COMMIT_SHA`` and ``trust_remote_code=False``;
weights are pulled in safetensors format (enforced via the
``safetensors>=0.4`` dependency). Loading from a floating tag like
``"BAAI/bge-m3"`` without a SHA is forbidden — silent model substitution
between runs would invalidate cached embeddings without a version bump.

**BP1 (07-multi-agent-caching.md).** The embedder applies
``unicodedata.normalize("NFC", ...)`` to the combined embedding input
and calls ``model.eval()`` to disable XLM-RoBERTa dropout, ensuring
byte-stable vectors across runs.
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
import time
import unicodedata
import uuid
from dataclasses import dataclass, field
from pathlib import Path

# Reuse the chunker's paper_id validator + log-field sanitiser to inherit
# its security guarantees (Threat 1) and avoid duplicating the regex.
from ingest.chunker import (
    _sanitize_log_field,
    _validate_paper_id,
)
from ingest.preamble import load_preamble

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Pinned model identity (Threat 6, 08-security-observability-ops.md)
# ---------------------------------------------------------------------------

# Single source of truth for the BGE-M3 commit SHA. Bumping this constant
# invalidates every cached embedding under ``var/arxmcp/corpus/embeddings``
# and signals E04_S02's MVCC writer to re-encode. The value must match the
# project's security manifest entry for ``BAAI/bge-m3`` (Threat 6 mitigation
# in 08-security-observability-ops.md). Refresh procedure:
#   curl -s https://huggingface.co/api/models/BAAI/bge-m3 \
#     | python -c "import sys,json;print(json.load(sys.stdin)['sha'])"
# Verified 2026-05-07; HEAD of `BAAI/bge-m3` `main` (commit message:
# "Update MIRACL evaluation results of BGE-M3", 2024-07-03).
BGE_M3_COMMIT_SHA = "5617a9f61b028005a4858fdac845db406aefb181"

# Convenience formatter used for stats logs and (later) the LanceDB
# ``embedder_version`` column. Same short-and-sortable style as
# ``chunker_version`` (single source of truth in ``chunker_types``).
EMBEDDER_VERSION = f"bge-m3@{BGE_M3_COMMIT_SHA[:8]}"

# BGE-M3's hidden size (XLM-RoBERTa-large backbone). Pinned here so that
# downstream readers (tests, E04_S01's schema) can import the constant
# without cracking the model.
EMBEDDING_DIM = 1024

# Maximum number of tokens BGE-M3 attends to. The chunker already enforces
# this for ``body_text`` alone (stmt: 512, proof: 448) but the embed input
# adds an uncapped preamble prefix; the tokenizer's ``truncation=True,
# max_length=MAX_TOKENS`` handles the overflow at encode time.
MAX_TOKENS = 512

# Default batch size for CPU inference. ~32 chunks ≈ 32 forward passes
# through XLM-RoBERTa-large per call; on a 2020-era laptop this delivers
# acceptable throughput for the 50-paper seed corpus.
EMBED_BATCH_DEFAULT = 32


# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parent.parent
CHUNKS_DIR = REPO_ROOT / "var" / "arxmcp" / "corpus" / "chunks"
EMBEDDINGS_DIR = REPO_ROOT / "var" / "arxmcp" / "corpus" / "embeddings"
EMBED_STATS_PATH = REPO_ROOT / "var" / "arxmcp" / "ops" / "embed-stats.jsonl"
EMBED_LOG_PATH = (
    REPO_ROOT / "var" / "arxmcp" / "ops" / "parser-failures" / "embed.log"
)


# ---------------------------------------------------------------------------
# Per-paper exception envelope (mirrors chunker / preamble)
# ---------------------------------------------------------------------------

# Catch only resilience-pattern exceptions; programmer bugs (AttributeError,
# TypeError, RuntimeError from torch internals) propagate so dev-time
# regressions surface.
PER_PAPER_FAILURE_EXCEPTIONS = (OSError, ValueError, FileNotFoundError)


# ---------------------------------------------------------------------------
# Per-paper EmbedStats row (one JSON line per paper in embed-stats.jsonl)
# ---------------------------------------------------------------------------


@dataclass
class EmbedStats:
    """Per-paper embed run summary.

    One :class:`EmbedStats` is appended to
    ``var/arxmcp/ops/embed-stats.jsonl`` per paper run. The aggregate
    return of :func:`embed_corpus` is the list of all per-paper stats.
    """

    paper_id: str
    chunks_processed: int
    chunks_skipped: int
    truncated_count: int
    elapsed_s: float
    embedder_version: str = field(default=EMBEDDER_VERSION)
    bge_m3_commit_sha: str = field(default=BGE_M3_COMMIT_SHA)
    status: str = field(default="ok")
    error: str | None = field(default=None)

    def to_dict(self) -> dict:
        return {
            "bge_m3_commit_sha": self.bge_m3_commit_sha,
            "chunks_processed": self.chunks_processed,
            "chunks_skipped": self.chunks_skipped,
            "elapsed_s": round(self.elapsed_s, 3),
            "embedder_version": self.embedder_version,
            "error": self.error,
            "paper_id": self.paper_id,
            "status": self.status,
            "truncated_count": self.truncated_count,
        }


# ---------------------------------------------------------------------------
# Lazy model + tokenizer loaders (mirrors chunker._get_tokenizer pattern)
# ---------------------------------------------------------------------------

_model = None
_tokenizer = None


def _get_tokenizer():
    """Return the BGE-M3 tokenizer pinned to :data:`BGE_M3_COMMIT_SHA`.

    Lazy-loaded so importing this module is cheap. Pins the tokenizer to
    the same SHA as the model so that token-id sequences cannot drift
    between encode passes if HuggingFace ships a new tokenizer revision.
    """
    global _tokenizer
    if _tokenizer is None:
        try:
            from transformers import AutoTokenizer  # noqa: PLC0415
        except ImportError as exc:  # pragma: no cover — dependency check
            raise ImportError(
                "transformers is required for ingest.embedder. "
                "Install via `pip install -e '.[dev]'` after adding "
                "transformers to pyproject.toml."
            ) from exc
        _tokenizer = AutoTokenizer.from_pretrained(
            "BAAI/bge-m3",
            revision=BGE_M3_COMMIT_SHA,
        )
    return _tokenizer


def _get_model():
    """Return the BGE-M3 model in eval mode, pinned to :data:`BGE_M3_COMMIT_SHA`.

    Lazy-loaded — the ~2.3 GB safetensors download happens on first call,
    not at import time. Loaded with ``trust_remote_code=False`` per Threat
    6. ``model.eval()`` is required to disable XLM-RoBERTa dropout, without
    which the same input would produce different embeddings on each
    forward pass and break BP1 byte-stability.
    """
    global _model
    if _model is None:
        try:
            import torch  # noqa: F401, PLC0415
            from transformers import AutoModel  # noqa: PLC0415
        except ImportError as exc:  # pragma: no cover — dependency check
            raise ImportError(
                "torch and transformers are required for ingest.embedder. "
                "Add 'torch>=2.0' and 'safetensors>=0.4' to pyproject.toml."
            ) from exc
        _model = AutoModel.from_pretrained(
            "BAAI/bge-m3",
            revision=BGE_M3_COMMIT_SHA,
            # Threat 6: refuse model-card-supplied custom modeling code.
            trust_remote_code=False,
        )
        _model.eval()
        # Default torch CPU thread count can be 1 on some configurations;
        # explicit setting eliminates the surprise. CPU-only by design —
        # never call .cuda() / .to("cuda"); GPU acceleration is an E11
        # concern.
        import torch  # noqa: PLC0415

        torch.set_num_threads(os.cpu_count() or 4)
    return _model


# ---------------------------------------------------------------------------
# Embed input construction (preamble + body_text)
# ---------------------------------------------------------------------------


def _build_embed_input(preamble_text: str, body_text: str) -> str:
    """Return the NFC-normalized ``preamble + "\\n\\n" + body_text`` view.

    F3 fallback: when the per-paper preamble is missing, ``preamble_text``
    is ``""`` and the embedder encodes ``body_text`` alone (no leading
    newlines). Mirrors the same fallback in
    ``ingest.chunker._compute_chunk_id``.

    F6 (NFC): the preamble is already NFC (applied at extraction time),
    but ``body_text`` is stored raw by the chunker (NFC is hash-only).
    Normalising the combined string here protects BP1 byte-stability
    across hosts and matches the tokenizer's discipline (``tokenizer.py``
    line 128).
    """
    combined = (
        preamble_text + "\n\n" + body_text if preamble_text else body_text
    )
    return unicodedata.normalize("NFC", combined)


# ---------------------------------------------------------------------------
# Batch encode
# ---------------------------------------------------------------------------


def _encode_batch(texts: list[str]) -> tuple[object, int]:
    """Encode a list of texts to L2-normalized 1024-dim vectors.

    Returns ``(embeddings, truncated_count)`` where ``embeddings`` is a
    numpy ``float32`` array of shape ``(len(texts), EMBEDDING_DIM)`` and
    ``truncated_count`` is the number of inputs whose token sequence had
    to be truncated to fit ``MAX_TOKENS``.

    Critical: raw ``transformers.AutoModel`` does NOT apply L2
    normalization by default — unlike ``BGEM3FlagModel.encode()``. The
    explicit ``F.normalize`` call below is required to satisfy the
    "All vectors L2-normalized" acceptance criterion.
    """
    import numpy as np  # noqa: PLC0415
    import torch  # noqa: PLC0415
    import torch.nn.functional as F  # noqa: PLC0415

    tokenizer = _get_tokenizer()
    model = _get_model()

    # Pre-count truncations BEFORE the actual encode, so the warning fires
    # with the input still in hand. Uses the same tokenizer as the encode
    # call so the count is accurate.
    truncated_count = 0
    for text in texts:
        ids = tokenizer.encode(text, add_special_tokens=True)
        if len(ids) > MAX_TOKENS:
            truncated_count += 1

    encoded = tokenizer(
        texts,
        padding=True,
        truncation=True,
        max_length=MAX_TOKENS,
        return_tensors="pt",
    )

    with torch.no_grad():
        output = model(**encoded)
        # BGE-M3 dense embedding: CLS token of last hidden state.
        embeddings = output.last_hidden_state[:, 0, :]
        # Explicit L2 normalization — raw AutoModel does not apply it.
        embeddings = F.normalize(embeddings, p=2, dim=-1)

    return embeddings.cpu().numpy().astype(np.float32), truncated_count


# ---------------------------------------------------------------------------
# Per-paper NPZ write (atomic, mirrors preamble._write_preamble_json)
# ---------------------------------------------------------------------------


def _write_embeddings_npz(
    out_path: Path,
    *,
    chunk_ids_stmt: list[str],
    embedding_stmt: object,
    chunk_ids_proof: list[str],
    embedding_proof: object,
) -> None:
    """Atomically write per-paper ``embeddings.npz`` via temp-then-rename.

    The NPZ contains four arrays:

    - ``chunk_ids_stmt``: 1-D string array, len N_stmt
    - ``embedding_stmt``: float32 array, shape ``(N_stmt, EMBEDDING_DIM)``
    - ``chunk_ids_proof``: 1-D string array, len N_proof
    - ``embedding_proof``: float32 array, shape ``(N_proof, EMBEDDING_DIM)``

    Splitting the chunk_id arrays per-column (rather than a single
    ``chunk_ids`` plus aligned dual-column matrices) lets E04_S01 directly
    iterate ``zip(chunk_ids_stmt, embedding_stmt)`` without carrying
    null-vector rows. Closes the routing-table contract from D5.

    Atomic write pattern matches ``preamble._write_preamble_json``:
    PID + UUID-suffixed tmp path, ``np.savez``, ``os.replace``,
    ``try/finally`` cleanup.
    """
    import numpy as np  # noqa: PLC0415

    out_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = out_path.with_suffix(
        f"{out_path.suffix}.{os.getpid()}.{uuid.uuid4().hex[:8]}.tmp"
    )
    try:
        # np.savez auto-appends ".npz" when given a path string/Path that
        # doesn't already end in ".npz" — but the tmp suffix ends in
        # ".tmp", so np.savez would silently rename our tmp to "<tmp>.npz"
        # and the os.replace below would then fail on a missing path.
        # Open the tmp ourselves and hand np.savez a file object so it
        # writes exactly where we asked.
        with tmp.open("wb") as fh:
            np.savez(
                fh,
                chunk_ids_stmt=np.asarray(chunk_ids_stmt, dtype=object),
                embedding_stmt=embedding_stmt,
                chunk_ids_proof=np.asarray(chunk_ids_proof, dtype=object),
                embedding_proof=embedding_proof,
            )
        os.replace(tmp, out_path)
    finally:
        with contextlib.suppress(OSError):
            tmp.unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# Per-paper ChunkRecord loader
# ---------------------------------------------------------------------------


def _load_chunks(paper_id: str) -> list[dict]:
    """Return all per-chunk JSON payloads for ``paper_id`` in manifest order.

    Reads ``var/arxmcp/corpus/chunks/<paper_id>/chunk_manifest.json`` for
    the canonical chunk_id ordering, then loads each
    ``<hash16>.json`` file. Order matches the chunker's document-order
    output (matters for E04_S01 NPZ-to-LanceDB row alignment).

    Returns ``[]`` if the paper directory doesn't exist or the manifest
    is missing — the caller logs the skip and moves on.
    """
    paper_dir = CHUNKS_DIR / paper_id
    manifest_path = paper_dir / "chunk_manifest.json"
    if not manifest_path.exists():
        return []
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        raise ValueError(
            f"could not read chunk_manifest.json for {paper_id}: {exc}"
        ) from exc

    chunks: list[dict] = []
    for entry in manifest.get("chunks", []):
        chunk_id = entry["chunk_id"]
        # The on-disk filename is the 16-char hash suffix (everything
        # after the final colon in chunk_id), per chunker.py line 899.
        hash_suffix = chunk_id.rsplit(":", 1)[-1]
        chunk_path = paper_dir / f"{hash_suffix}.json"
        if not chunk_path.exists():
            raise FileNotFoundError(
                f"chunk file {chunk_path} listed in manifest is missing"
            )
        try:
            chunks.append(json.loads(chunk_path.read_text(encoding="utf-8")))
        except json.JSONDecodeError as exc:
            raise ValueError(
                f"corrupt chunk JSON at {chunk_path}: {exc}"
            ) from exc
    return chunks


# ---------------------------------------------------------------------------
# Stats writers (append-mode JSONL + TSV failure log)
# ---------------------------------------------------------------------------


def _append_embed_stats(stats: EmbedStats) -> None:
    """Append one JSON line to ``var/arxmcp/ops/embed-stats.jsonl``.

    Append mode is non-atomic but acceptable for an ops log (mirrors
    ``chunk.log`` and ``preamble.log``). The directory is created on
    first write.
    """
    EMBED_STATS_PATH.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(stats.to_dict(), ensure_ascii=False, sort_keys=True) + "\n"
    try:
        with EMBED_STATS_PATH.open("a", encoding="utf-8") as fh:
            fh.write(line)
    except OSError:
        logger.error("could not write to embed-stats.jsonl: %s", EMBED_STATS_PATH)


def _log_embed_failure(paper_id: str, elapsed_s: float, message: str) -> None:
    """Append a TSV row to ``embed.log`` (mirrors chunk.log/preamble.log)."""
    EMBED_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    row = (
        f"{_sanitize_log_field(paper_id)}\tfail\t{elapsed_s:.1f}\t"
        f"{_sanitize_log_field(message)}\n"
    )
    try:
        with EMBED_LOG_PATH.open("a", encoding="utf-8") as fh:
            fh.write(row)
    except OSError:
        logger.error("could not write to embed.log: %s", EMBED_LOG_PATH)


# ---------------------------------------------------------------------------
# Public API: per-paper and corpus-wide embed
# ---------------------------------------------------------------------------


def embed_paper(paper_id: str, batch_size: int = EMBED_BATCH_DEFAULT) -> EmbedStats:
    """Encode every chunk for ``paper_id`` and write the per-paper NPZ.

    Looks up the chunks under ``var/arxmcp/corpus/chunks/<paper_id>/``
    and the preamble under ``var/arxmcp/corpus/preamble/<paper_id>/``,
    builds the ``preamble_text + "\\n\\n" + body_text`` embed input for
    each chunk, encodes in batches of ``batch_size``, and writes the
    L2-normalized vectors to
    ``var/arxmcp/corpus/embeddings/<paper_id>/embeddings.npz``.

    Per-paper resilience: any :data:`PER_PAPER_FAILURE_EXCEPTIONS` is
    logged to ``embed.log`` and surfaces as an :class:`EmbedStats` with
    ``status="fail"`` rather than aborting the corpus-wide batch.
    Programmer bugs propagate.
    """
    _validate_paper_id(paper_id)
    start = time.monotonic()
    try:
        return _embed_paper_impl(paper_id, batch_size)
    except PER_PAPER_FAILURE_EXCEPTIONS as exc:
        elapsed = time.monotonic() - start
        _log_embed_failure(paper_id, elapsed, str(exc))
        logger.error("[%s] embed_paper failed: %s", paper_id, exc, exc_info=True)
        return EmbedStats(
            paper_id=paper_id,
            chunks_processed=0,
            chunks_skipped=0,
            truncated_count=0,
            elapsed_s=elapsed,
            status="fail",
            error=str(exc),
        )


def _embed_paper_impl(paper_id: str, batch_size: int) -> EmbedStats:
    if batch_size <= 0:
        raise ValueError(f"batch_size must be positive, got {batch_size}")

    start = time.monotonic()

    chunks = _load_chunks(paper_id)
    if not chunks:
        # No chunks means the chunker hasn't run yet, or the manifest is
        # absent. Treat as a clean skip rather than an error: the corpus
        # driver may invoke embed for paper_ids that haven't yet been
        # chunked, and this path keeps it idempotent.
        elapsed = time.monotonic() - start
        stats = EmbedStats(
            paper_id=paper_id,
            chunks_processed=0,
            chunks_skipped=0,
            truncated_count=0,
            elapsed_s=elapsed,
            status="ok",
        )
        _append_embed_stats(stats)
        return stats

    # F3 fallback: when load_preamble returns None (extraction failed),
    # preamble_text becomes "" and the embedder encodes body_text alone.
    preamble_doc = load_preamble(paper_id)
    preamble_text = preamble_doc.preamble_text if preamble_doc is not None else ""

    # Build embed inputs in document (manifest) order, then split by
    # routing column. We carry parallel index lists so we can reassemble
    # the per-column outputs after batched encoding.
    embed_inputs: list[str] = []
    routing: list[str] = []  # "embedding_stmt" | "embedding_proof"
    chunk_ids_in_order: list[str] = []
    for chunk in chunks:
        kind = chunk["kind"]
        body_text = chunk["body_text"]
        chunk_id = chunk["chunk_id"]
        embed_inputs.append(_build_embed_input(preamble_text, body_text))
        routing.append("embedding_proof" if kind == "proof" else "embedding_stmt")
        chunk_ids_in_order.append(chunk_id)

    # Batched encode. Truncation counts aggregate across batches.
    import numpy as np  # noqa: PLC0415

    all_vectors: list = []
    truncated_total = 0
    for batch_start in range(0, len(embed_inputs), batch_size):
        batch_texts = embed_inputs[batch_start : batch_start + batch_size]
        vectors, truncated_in_batch = _encode_batch(batch_texts)
        all_vectors.append(vectors)
        truncated_total += truncated_in_batch
    all_array = np.concatenate(all_vectors, axis=0)

    if truncated_total > 0:
        logger.warning(
            "[%s] %d / %d chunks had to be truncated to %d tokens "
            "(preamble + body_text exceeded BGE-M3 max length); "
            "consider tightening the chunker's body budget if frequent",
            paper_id,
            truncated_total,
            len(embed_inputs),
            MAX_TOKENS,
        )

    # Split by routing into the dual columns. Vectors stay aligned with
    # ``chunk_ids_*`` so E04_S01 can zip without carrying null rows.
    chunk_ids_stmt: list[str] = []
    chunk_ids_proof: list[str] = []
    rows_stmt: list = []
    rows_proof: list = []
    for i, column in enumerate(routing):
        if column == "embedding_proof":
            chunk_ids_proof.append(chunk_ids_in_order[i])
            rows_proof.append(all_array[i])
        else:
            chunk_ids_stmt.append(chunk_ids_in_order[i])
            rows_stmt.append(all_array[i])

    # Empty arrays must still have a 2-D shape (0, EMBEDDING_DIM) so
    # downstream readers can ``.reshape(-1, EMBEDDING_DIM)`` without a
    # special case. ``np.stack`` on an empty list raises, so we build
    # the empty case explicitly.
    if rows_stmt:
        embedding_stmt = np.stack(rows_stmt, axis=0)
    else:
        embedding_stmt = np.zeros((0, EMBEDDING_DIM), dtype=np.float32)
    if rows_proof:
        embedding_proof = np.stack(rows_proof, axis=0)
    else:
        embedding_proof = np.zeros((0, EMBEDDING_DIM), dtype=np.float32)

    out_path = EMBEDDINGS_DIR / paper_id / "embeddings.npz"
    _write_embeddings_npz(
        out_path,
        chunk_ids_stmt=chunk_ids_stmt,
        embedding_stmt=embedding_stmt,
        chunk_ids_proof=chunk_ids_proof,
        embedding_proof=embedding_proof,
    )

    elapsed = time.monotonic() - start
    stats = EmbedStats(
        paper_id=paper_id,
        chunks_processed=len(embed_inputs),
        chunks_skipped=0,
        truncated_count=truncated_total,
        elapsed_s=elapsed,
        status="ok",
    )
    _append_embed_stats(stats)
    return stats


def embed_corpus(
    lancedb_path: str | None = None,
    corpus_path: str | None = None,
    batch_size: int = EMBED_BATCH_DEFAULT,
) -> list[EmbedStats]:
    """Embed every chunked paper under ``corpus_path`` (or the default).

    Iterates every directory under
    ``var/arxmcp/corpus/chunks/`` (or ``corpus_path`` if provided) that
    contains a ``chunk_manifest.json``, and runs :func:`embed_paper` for
    each. Per-paper failures are isolated — one bad paper does NOT abort
    the batch.

    The ``lancedb_path`` parameter from the milestone-brief signature is
    accepted for forward-compat with E04_S01 but is currently unused: the
    embedder writes NPZ files, not LanceDB rows. See
    ``research-synthesis.md`` § D1.
    """
    if lancedb_path is not None:
        # Forward-compat hook for E04_S01. Logged at DEBUG so callers don't
        # see noise but the wire-in is auditable.
        logger.debug(
            "embed_corpus called with lancedb_path=%s; NPZ-first mode "
            "ignores this parameter (will be wired in E04_S01).",
            lancedb_path,
        )

    chunks_root = Path(corpus_path) if corpus_path else CHUNKS_DIR
    if not chunks_root.exists():
        logger.warning(
            "embed_corpus: chunks root %s does not exist; nothing to embed",
            chunks_root,
        )
        return []

    paper_ids: list[str] = []
    for entry in sorted(chunks_root.iterdir()):
        if not entry.is_dir():
            continue
        if not (entry / "chunk_manifest.json").exists():
            continue
        paper_ids.append(entry.name)

    results: list[EmbedStats] = []
    for paper_id in paper_ids:
        # Validation runs OUTSIDE the per-paper exception envelope inside
        # embed_paper: an invalid directory name shows up as an
        # InvalidPaperIDError which is a subclass of ValueError and is
        # therefore in PER_PAPER_FAILURE_EXCEPTIONS. We log it as a
        # malformed-input failure rather than aborting.
        try:
            _validate_paper_id(paper_id)
        except ValueError:
            logger.warning(
                "embed_corpus: skipping non-paper directory %r under %s",
                paper_id,
                chunks_root,
            )
            continue
        results.append(embed_paper(paper_id, batch_size=batch_size))

    return results
