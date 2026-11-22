"""Dual-column BGE-M3 embedder (E03_S01) + idempotent re-embed (E03_S02).

Reads per-paper chunks written by the structural chunker
(``arxmcp.ingest.chunker``) from
``var/arxmcp/corpus/chunks/<paper_id>/``, encodes each chunk's
embedding input (:func:`arxmcp.corpus.chunk.embedding_input`, policy
``body-first-v1``: the NFC body) through ``BAAI/bge-m3``
pinned at :data:`BGE_M3_COMMIT_SHA`, and writes the 1024-dim L2-normalized
vectors to a parallel per-paper NPZ store at
``var/arxmcp/corpus/embeddings/<paper_id>/embeddings.npz``.

**Why NPZ-first, not direct LanceDB.** Embedding and the LanceDB store
depend on each other, so neither can block on the other. The NPZ store
breaks the cycle: ``src/arxmcp/corpus/store.py`` reads the NPZ alongside the chunk
manifests when building the LanceDB rows.

**Routing.** :func:`arxmcp.corpus.chunk.route`: ``kind == "proof"`` →
``embedding_proof``; everything else (``stmt``, ``section``,
``definition``, ``lemma``, ``proposition``, ...) → ``embedding_stmt``.
The third column ``embedding_eq`` is reserved for
E10_S03 and is always NULL — the embedder never populates it.

**Threat 6.** The model is loaded
with ``revision=BGE_M3_COMMIT_SHA`` and ``trust_remote_code=False``;
weights are pulled in safetensors format (enforced via the
``safetensors>=0.4`` dependency). Loading from a floating tag like
``"BAAI/bge-m3"`` without a SHA is forbidden — silent model substitution
between runs would invalidate cached embeddings without a version bump.

**BP1.** The embedding input is
NFC-normalised (:func:`arxmcp.corpus.chunk.embedding_input`) and the embedder
calls ``model.eval()`` to disable XLM-RoBERTa dropout, ensuring
byte-stable vectors across runs.

**Idempotent re-embed (E03_S02).** Each successful per-paper encode
also writes a sidecar
``var/arxmcp/corpus/embeddings/<paper_id>/embeddings_manifest.json``
recording ``{chunker_version, embed_input_policy_version,
embedded_chunks, embedder_version, paper_id}``; each ``embedded_chunks``
entry carries the chunk's reuse identity (the sidecar has no chunk
bodies, so the identity is stored). On re-run, the embedder loads
the paper's chunks, computes their reuse identities and skips the paper
iff:

  1. the sidecar and its NPZ exist, AND
  2. ``sidecar.chunker_version == EXPECTED_CHUNKER_VERSION``, AND
  3. ``sidecar.embedder_version == EMBEDDER_VERSION`` and the sidecar's
     policy is the current one, AND
  4. the sidecar's entries are exactly the current chunks: the same
     ``chunk_id`` set (the NPZ is keyed by it), each with its reuse
     identity.

If any condition fails, the entire paper is re-encoded (NPZ rewrite
is atomic via tmp + ``os.replace``; ``np.savez`` does not support
partial archive updates). The brief's "MVCC writer serializes writes"
language refers to E04_S02's LanceDB writer, which is not yet built;
the actual concurrency safety here comes from POSIX-atomic
``os.replace``. Two processes embedding the same paper concurrently
each produce a complete NPZ + sidecar pair via tmp + rename — last
writer wins, neither reader ever sees a partial file, and BP1
byte-stability means both writers' outputs would be identical on
identical input.

The "MVCC handshake" the brief describes is implemented as the
``chunker_version`` field in the sidecar: a ``CHUNKER_VERSION`` bump
in ``src/arxmcp/corpus/chunk.py`` automatically forces re-embed
because :data:`EXPECTED_CHUNKER_VERSION` is an alias for that
constant (see D2 of the E03_S02 research synthesis).
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path

# The corpus paper_id validator + log-field sanitiser carry the Threat 1
# guarantees every writer shares.
from arxmcp.corpus import (
    BGE_M3_COMMIT_SHA,
    EMBED_DEVICE,
    EMBED_INPUT_POLICY_VERSION,
    EMBEDDER_VERSION,
    EMBEDDING_DIM,
    EMBEDDINGS_DIR,
    EMBEDDINGS_MANIFEST_NAME,
    EMBEDDINGS_NPZ_NAME,
    MAX_TOKENS,
    embedding_input,
    get_embedding_model,
    get_embedding_tokenizer,
    read_embeddings_manifest,
    reuse_identity,
    route,
    sanitize_log_field,
    validate_paper_id,
)

# Alias rather than redefine. ``CHUNKER_VERSION`` lives in
# ``arxmcp.corpus.chunk`` as the SINGLE source of truth (locked by
# ``tests/test_chunker_ids.py::TestSingleVersionDefinition``). Defining
# ``EXPECTED_CHUNKER_VERSION`` as a fresh string literal here would
# either fail that regression check or, if exempted, drift on the next
# bump. ``EMBED_INPUT_POLICY_VERSION`` and ``EMBEDDING_DIM`` are chunk facts
# too; this module re-exports them for its existing importers.
from arxmcp.corpus import CHUNKER_VERSION as EXPECTED_CHUNKER_VERSION
from arxmcp.settings import ApplicationPaths

logger = logging.getLogger(__name__)

# Default batch size for CPU inference. Lowered from 32 to 8 in
# embedder-truncation-m1 because XLM-RoBERTa's O(n²) attention makes a
# 32-batch of 2048-token inputs OOM-prone on CPU (16× attention memory
# vs the prior 512-token regime).
EMBED_BATCH_DEFAULT = 2 if EMBED_DEVICE == "cuda" else 8


# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

_APPLICATION_PATHS = ApplicationPaths.resolve()
CHUNKS_DIR = _APPLICATION_PATHS.corpus / "chunks"
EMBED_STATS_PATH = _APPLICATION_PATHS.ops / "embed-stats.jsonl"
EMBED_LOG_PATH = _APPLICATION_PATHS.ops / "parser-failures" / "embed.log"


# ---------------------------------------------------------------------------
# Per-paper exception envelope (mirrors chunker / preamble)
# ---------------------------------------------------------------------------

# Catch only resilience-pattern exceptions; programmer bugs (AttributeError,
# TypeError, RuntimeError from torch internals) propagate so dev-time
# regressions surface.
PER_PAPER_FAILURE_EXCEPTIONS = (OSError, ValueError, FileNotFoundError)


class _ChunkFileMissingError(FileNotFoundError):
    """A manifest entry referenced a chunk file that is not on disk.

    Distinct from the bare ``FileNotFoundError`` that a genuinely-absent
    manifest would produce (the latter takes the silent-skip path in
    ``_load_chunks``). Closes F4 from the E03_S01 adversary critique by
    giving ops a way to distinguish "chunker hasn't run yet" from "corpus
    state is internally inconsistent" via the ``error_class`` field on
    :class:`EmbedStats`.
    """


class _ManifestCorruptError(ValueError):
    """The chunk_manifest.json file exists but cannot be parsed."""


class _ChunkJsonCorruptError(ValueError):
    """A per-chunk JSON file exists but cannot be parsed."""


# ---------------------------------------------------------------------------
# Per-paper EmbedStats row (one JSON line per paper in embed-stats.jsonl)
# ---------------------------------------------------------------------------


# Closes F4 from E03_S01 critique: distinguish "manifest absent / chunker
# hasn't run yet" (a routine wait-state) from genuine corpus corruption
# (a manifest references a chunk file that does not exist on disk). Both
# previously surfaced as a generic ``status="fail"`` row with free-text
# ``error``; ops now has a queryable enum field instead of grep targets.
EMBED_ERROR_CLASS_NONE = "none"
EMBED_ERROR_CLASS_CHUNK_MISSING = "chunk_missing"
EMBED_ERROR_CLASS_MANIFEST_CORRUPT = "manifest_corrupt"
EMBED_ERROR_CLASS_JSON_CORRUPT = "json_corrupt"
EMBED_ERROR_CLASS_OTHER = "other"


@dataclass
class EmbedStats:
    """Per-paper embed run summary.

    One :class:`EmbedStats` is appended to
    ``var/arxmcp/ops/embed-stats.jsonl`` per paper run **regardless of
    outcome** — closes F1 from the E03_S01 adversary critique by
    ensuring the JSONL audit trail captures every paper attempt, not
    just successes. The aggregate return of :func:`embed_corpus` is the
    list of all per-paper stats followed by one ``run_summary`` JSONL
    line (closes F2).

    The ``error_class`` field carries a small enum so ops can
    distinguish manifest-missing / chunk-missing / json-corrupt failures
    without grepping the ``error`` text (closes F4).
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
    error_class: str = field(default=EMBED_ERROR_CLASS_NONE)

    def to_dict(self) -> dict:
        return {
            "bge_m3_commit_sha": self.bge_m3_commit_sha,
            "chunks_processed": self.chunks_processed,
            "chunks_skipped": self.chunks_skipped,
            "elapsed_s": round(self.elapsed_s, 3),
            "embedder_version": self.embedder_version,
            "error": self.error,
            "error_class": self.error_class,
            "paper_id": self.paper_id,
            "status": self.status,
            "truncated_count": self.truncated_count,
        }


# ---------------------------------------------------------------------------
# Batch encode
# ---------------------------------------------------------------------------


def _encode_batch(
    texts: list[str], chunk_ids: list[str] | None = None
) -> tuple[object, int]:
    """Encode a list of texts to L2-normalized 1024-dim vectors.

    Returns ``(embeddings, 0)`` where ``embeddings`` is a numpy ``float32``
    array of shape ``(len(texts), EMBEDDING_DIM)``. An input longer than
    ``MAX_TOKENS``, including special tokens, raises before model inference.

    Closes F3 from the E03_S01 adversary critique: the truncation count
    is now derived from the SAME tokenizer call style that produces the
    encode tensor, via a ``truncation=False, return_length=True``
    pre-pass. The previous implementation made two distinct tokenizer
    calls (one ``tokenizer.encode`` per text in a Python loop, then a
    batch ``tokenizer(...)`` with truncation) that were not guaranteed
    to produce identical token-id lengths for non-trivial inputs.

    When ``chunk_ids`` is supplied, an overflow error identifies the
    offending chunk.

    Critical: raw ``transformers.AutoModel`` does NOT apply L2
    normalization by default — unlike ``BGEM3FlagModel.encode()``. The
    explicit ``F.normalize`` call below is required to satisfy the
    "All vectors L2-normalized" acceptance criterion.
    """
    import numpy as np  # noqa: PLC0415
    import torch  # noqa: PLC0415
    import torch.nn.functional as F  # noqa: PLC0415

    tokenizer = get_embedding_tokenizer()

    # Closes F3: single no-truncation pre-pass that returns un-clipped
    # length per text, matching the call-style of the actual encode
    # below. ``return_length=True`` makes ``length`` a per-input list
    # in the returned batch encoding.
    #
    # Count CLS/SEP here because the actual model input includes them.
    pre = tokenizer(
        texts,
        padding=False,
        truncation=False,
        return_length=True,
        add_special_tokens=True,
    )
    lengths = pre["length"]
    for i, length in enumerate(lengths):
        if length > MAX_TOKENS:
            chunk_id = chunk_ids[i] if chunk_ids is not None else str(i)
            raise ValueError(
                f"embedding input exceeds {MAX_TOKENS} tokens including "
                f"special tokens: chunk_id={chunk_id} tokens={length}"
            )

    encoded = tokenizer(
        texts,
        padding=True,
        truncation=False,
        return_tensors="pt",
    )
    if EMBED_DEVICE == "cuda":
        encoded = {key: value.to("cuda") for key, value in encoded.items()}
    model = get_embedding_model()

    with torch.no_grad():
        output = model(**encoded)
        # BGE-M3 dense embedding: CLS token of last hidden state.
        embeddings = output.last_hidden_state[:, 0, :]
        # Explicit L2 normalization — raw AutoModel does not apply it.
        embeddings = F.normalize(embeddings, p=2, dim=-1)

    return embeddings.cpu().numpy().astype(np.float32), 0


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

    The NPZ contains four arrays, written in **alphabetical key order**
    (closes F5 from the E03_S01 critique — ``np.savez`` writes archive
    members in kwargs insertion order, so file bytes are deterministic
    only if the kwargs order is fixed; alphabetical matches the
    BP1-byte-stability discipline):

    - ``chunk_ids_proof``: 1-D string array, len N_proof
    - ``chunk_ids_stmt``: 1-D string array, len N_stmt
    - ``embedding_proof``: float32 array, shape ``(N_proof, EMBEDDING_DIM)``
    - ``embedding_stmt``: float32 array, shape ``(N_stmt, EMBEDDING_DIM)``

    Splitting the chunk_id arrays per-column (rather than a single
    ``chunk_ids`` plus aligned dual-column matrices) lets E04_S01 directly
    iterate ``zip(chunk_ids_stmt, embedding_stmt)`` without carrying
    null-vector rows. Closes the routing-table contract from D5.

    **Empty-paper / single-column edge cases (closes F9):** when a paper
    has zero proof chunks (or zero stmt chunks), the corresponding
    array is written as a ``(0, EMBEDDING_DIM)`` zero-row array — NOT
    omitted from the NPZ. Consumers MUST check ``len(chunk_ids_*) > 0``
    or equivalently ``embedding_*.shape[0] > 0`` before iterating, and
    must NOT rely on key presence (``"embedding_proof" in npz.files``)
    as a signal of absence. The zero-row sentinel is preferred over
    omitting the key because it makes the NPZ schema invariant across
    papers.

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
        # Closes F5: kwargs in alphabetical order — ``np.savez`` writes
        # archive members in kwargs insertion order, so this ordering is
        # load-bearing for byte-stable NPZ files.
        with tmp.open("wb") as fh:
            np.savez(
                fh,
                chunk_ids_proof=np.asarray(chunk_ids_proof, dtype=object),
                chunk_ids_stmt=np.asarray(chunk_ids_stmt, dtype=object),
                embedding_proof=embedding_proof,
                embedding_stmt=embedding_stmt,
            )
        os.replace(tmp, out_path)
    finally:
        with contextlib.suppress(OSError):
            tmp.unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# E03_S02: per-paper embeddings sidecar (idempotent re-embed handshake)
# ---------------------------------------------------------------------------

class _SidecarCorruptError(ValueError):
    """A sidecar exists on disk but contains malformed entries.

    Distinct from "absent or unparseable JSON" (which
    :func:`read_embeddings_manifest` swallows and returns ``None`` for,
    forcing a self-healing re-embed). This exception is raised when the
    JSON parses but contains entries that violate the schema contract —
    e.g. an ``embedded_chunks`` entry that is a dict but missing
    ``chunk_id``, or a non-list ``embedded_chunks``. Closes F9 from the
    E03_S02 adversary critique.
    """


def _write_embeddings_manifest(
    out_path: Path,
    *,
    paper_id: str,
    embedded_chunks: list[dict],
) -> None:
    """Atomically write the per-paper embeddings sidecar (E03_S02).

    Schema (alphabetical keys, sorted by ``json.dumps(sort_keys=True)``,
    no timestamps — load-bearing for BP1 byte-stability across hosts):

    .. code-block:: json

        {
          "chunker_version": "<EXPECTED_CHUNKER_VERSION>",
          "embed_input_policy_version": "<EMBED_INPUT_POLICY_VERSION>",
          "embedded_chunks": [
            {"chunk_id": "arxiv:2307.01156:a1b2c3d4e5f60718",
             "kind": "stmt",
             "reuse_identity": "<64 hex>"},
            ...
          ],
          "embedder_version": "<EMBEDDER_VERSION>",
          "paper_id": "2307.01156"
        }

    ``reuse_identity`` is :func:`arxmcp.corpus.chunk.reuse_identity` of the
    entry's chunk under this sidecar's embedder version and policy. The
    sidecar holds no chunk bodies, so the identity is stored here
    instead of recomputed.

    The ``embedded_chunks`` list is written in document order (the same
    order as ``chunk_manifest.json``) so BP1 byte-stability holds: two
    runs with identical inputs produce a byte-identical sidecar.

    Writes via tmp + ``os.replace`` to mirror
    :func:`_write_embeddings_npz`'s atomic discipline. The sidecar is
    written **after** the NPZ; a reader that finds an NPZ but no
    sidecar treats the paper as not-yet-up-to-date and re-embeds (this
    is also the migration path from pre-E03_S02 NPZs).

    The ``chunker_version`` field carries :data:`EXPECTED_CHUNKER_VERSION`
    (alias for ``CHUNKER_VERSION``); ``embedder_version`` carries
    :data:`EMBEDDER_VERSION` (model SHA prefix). Both are required by
    :func:`_paper_is_up_to_date` for the skip decision.
    """
    sidecar = {
        "chunker_version": EXPECTED_CHUNKER_VERSION,
        "embedded_chunks": embedded_chunks,
        "embedder_version": EMBEDDER_VERSION,
        "embed_input_policy_version": EMBED_INPUT_POLICY_VERSION,
        "paper_id": paper_id,
    }
    payload = json.dumps(sidecar, ensure_ascii=False, sort_keys=True) + "\n"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = out_path.with_suffix(
        f"{out_path.suffix}.{os.getpid()}.{uuid.uuid4().hex[:8]}.tmp"
    )
    try:
        tmp.write_text(payload, encoding="utf-8")
        os.replace(tmp, out_path)
    finally:
        with contextlib.suppress(OSError):
            tmp.unlink(missing_ok=True)


def _paper_is_up_to_date(paper_id: str, current: dict[str, str]) -> bool:
    """Return True iff the paper's stored vectors can be reused as they are.

    ``current`` maps each current chunk's ``chunk_id`` to its reuse
    identity under :data:`EMBEDDER_VERSION` (:func:`arxmcp.corpus.chunk.reuse_identity`).
    The paper is up to date iff ALL of the following hold:

    1. the sidecar exists at
       ``var/arxmcp/corpus/embeddings/<paper_id>/embeddings_manifest.json``,
       AND
    2. ``embeddings.npz`` ALSO exists in the same directory (closes F1
       from the E03_S02 critique — a present sidecar with a missing NPZ
       previously caused a false skip), AND
    3. ``sidecar.chunker_version == EXPECTED_CHUNKER_VERSION``, AND
    4. ``sidecar.embedder_version == EMBEDDER_VERSION`` and
       ``sidecar.embed_input_policy_version == EMBED_INPUT_POLICY_VERSION``,
       AND
    5. every current chunk has a sidecar entry with the same ``chunk_id``
       (the NPZ is keyed by it) whose ``reuse_identity`` equals the
       chunk's current identity (same embedding input, embedder
       version, policy and route). An entry without a
       ``reuse_identity`` (an older sidecar) never matches, so such a
       paper is re-embedded once. An entry for a chunk the paper no
       longer has also fails the check: nothing else ever removes a
       vector from the NPZ, so the re-encode, which rewrites the NPZ and
       sidecar from the current chunks alone, is what drops it.

    Any failure of any condition triggers re-embed.

    Closes F13 from the E03_S02 critique: ``paper_id`` is validated
    here as defense-in-depth, even though every public caller already
    validates.

    A malformed sidecar (a non-list ``embedded_chunks``, an
    entry that is not a dict or has no string ``chunk_id``) is not up to
    date, so the paper gets a clean re-embed that regenerates it.
    """
    validate_paper_id(paper_id)
    paper_dir = EMBEDDINGS_DIR / paper_id
    sidecar_path = paper_dir / EMBEDDINGS_MANIFEST_NAME
    npz_path = paper_dir / EMBEDDINGS_NPZ_NAME
    sidecar = read_embeddings_manifest(sidecar_path)
    if sidecar is None:
        return False
    # Closes F1: the NPZ companion file must also exist. Without this
    # check, a half-cleaned-up corpus (NPZ deleted, sidecar kept)
    # silently stays half-broken across re-runs.
    if not npz_path.exists():
        logger.warning(
            "[%s] sidecar exists but %s is missing; forcing re-embed",
            paper_id,
            EMBEDDINGS_NPZ_NAME,
        )
        return False
    if sidecar.get("chunker_version") != EXPECTED_CHUNKER_VERSION:
        return False
    if sidecar.get("embedder_version") != EMBEDDER_VERSION:
        return False
    if sidecar.get("embed_input_policy_version") != EMBED_INPUT_POLICY_VERSION:
        return False
    embedded = sidecar.get("embedded_chunks", [])
    if not isinstance(embedded, list):
        return False
    stored: dict[str, object] = {}
    for entry in embedded:
        if not isinstance(entry, dict) or not isinstance(entry.get("chunk_id"), str):
            return False
        stored[entry["chunk_id"]] = entry.get("reuse_identity")
    return len(stored) == len(embedded) and stored == current


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
        # Manifest absent — chunker has not run yet for this paper. This
        # is a routine wait-state, NOT a failure: the corpus driver may
        # invoke embed for paper_ids before the chunker has produced
        # output. Closes F4: silent skip with empty list, no exception.
        return []
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        raise _ManifestCorruptError(
            f"could not read chunk_manifest.json for {paper_id}: {exc}"
        ) from exc

    seen_ids: set[str] = set()
    chunks: list[dict] = []
    for entry in manifest.get("chunks", []):
        chunk_id = entry["chunk_id"]
        # Closes F8 from the E03_S02 critique: a duplicate chunk_id in
        # the manifest is a corpus-corruption signal — silently
        # collapsing duplicates would let the skip predicate trivially
        # pass on every subsequent run. Surface it as a manifest-corrupt
        # error so ops sees the bad input.
        if chunk_id in seen_ids:
            raise _ManifestCorruptError(
                f"duplicate chunk_id {chunk_id!r} in chunk_manifest.json "
                f"for paper {paper_id}"
            )
        seen_ids.add(chunk_id)
        # The on-disk filename is the 16-char hash suffix (everything
        # after the final colon in chunk_id), per chunker.py line 899.
        hash_suffix = chunk_id.rsplit(":", 1)[-1]
        chunk_path = paper_dir / f"{hash_suffix}.json"
        if not chunk_path.exists():
            # The manifest references a chunk file that is not on disk.
            # This is genuine corpus corruption (a P0 ops signal),
            # distinct from manifest-absent. Closes F4.
            raise _ChunkFileMissingError(
                f"chunk file {chunk_path} listed in manifest is missing"
            )
        try:
            chunks.append(json.loads(chunk_path.read_text(encoding="utf-8")))
        except json.JSONDecodeError as exc:
            raise _ChunkJsonCorruptError(
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
        f"{sanitize_log_field(paper_id)}\tfail\t{elapsed_s:.1f}\t"
        f"{sanitize_log_field(message)}\n"
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

    Looks up the chunks under ``var/arxmcp/corpus/chunks/<paper_id>/``,
    builds each chunk's embedding input (:func:`arxmcp.corpus.chunk.embedding_input`),
    encodes in batches of ``batch_size``, and writes the
    L2-normalized vectors to
    ``var/arxmcp/corpus/embeddings/<paper_id>/embeddings.npz``.

    Per-paper resilience: any :data:`PER_PAPER_FAILURE_EXCEPTIONS` is
    logged to ``embed.log`` and surfaces as an :class:`EmbedStats` with
    ``status="fail"`` rather than aborting the corpus-wide batch.
    Programmer bugs propagate.
    """
    validate_paper_id(paper_id)
    start = time.monotonic()
    try:
        return _embed_paper_impl(paper_id, batch_size)
    except PER_PAPER_FAILURE_EXCEPTIONS as exc:
        elapsed = time.monotonic() - start
        _log_embed_failure(paper_id, elapsed, str(exc))
        logger.error("[%s] embed_paper failed: %s", paper_id, exc, exc_info=True)
        # Closes F4: map specific exception subclasses to error_class
        # enum values so ops can distinguish "chunker hasn't run yet"
        # (manifest absent path takes the silent-skip branch and never
        # reaches here) from "corpus state is inconsistent".
        if isinstance(exc, _ChunkFileMissingError):
            error_class = EMBED_ERROR_CLASS_CHUNK_MISSING
        elif isinstance(exc, _ManifestCorruptError):
            error_class = EMBED_ERROR_CLASS_MANIFEST_CORRUPT
        elif isinstance(exc, _ChunkJsonCorruptError):
            error_class = EMBED_ERROR_CLASS_JSON_CORRUPT
        else:
            error_class = EMBED_ERROR_CLASS_OTHER
        stats = EmbedStats(
            paper_id=paper_id,
            chunks_processed=0,
            chunks_skipped=0,
            truncated_count=0,
            elapsed_s=elapsed,
            status="fail",
            error=str(exc),
            error_class=error_class,
        )
        # Closes F1: failed runs MUST also write to embed-stats.jsonl so
        # ops queries against the JSONL audit trail catch every paper
        # attempt, not just the successes. The TSV embed.log is a
        # human-friendly grep target; the JSONL is the structured one.
        _append_embed_stats(stats)
        return stats


def _embed_paper_impl(paper_id: str, batch_size: int) -> EmbedStats:
    if batch_size <= 0:
        raise ValueError(f"batch_size must be positive, got {batch_size}")

    start = time.monotonic()

    # The skip pre-flight needs each current chunk's reuse identity, which
    # hashes its embedding input, so it reads the chunk bodies. (Skipping
    # on the manifest + sidecar alone would compare chunk ids, and a chunk
    # id is not a reuse key.) A missing manifest is the
    # routine "chunker has not run yet" wait-state and returns no chunks.
    chunks = _load_chunks(paper_id)
    if not chunks:
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

    identities = {
        chunk["chunk_id"]: reuse_identity(
            chunk["kind"], chunk["body_text"], embedder_version=EMBEDDER_VERSION
        )
        for chunk in chunks
    }
    if _paper_is_up_to_date(paper_id, identities):
        # No NPZ open, no model load.
        elapsed = time.monotonic() - start
        stats = EmbedStats(
            paper_id=paper_id,
            chunks_processed=0,
            chunks_skipped=len(chunks),
            truncated_count=0,
            elapsed_s=elapsed,
            status="ok",
        )
        logger.debug(
            "[%s] up to date (chunker_version=%s, embedder_version=%s, "
            "%d chunks); skipping",
            paper_id,
            EXPECTED_CHUNKER_VERSION,
            EMBEDDER_VERSION,
            len(chunks),
        )
        _append_embed_stats(stats)
        return stats

    # Build embed inputs in document (manifest) order, then split by
    # route. We carry parallel index lists so we can reassemble the
    # per-column outputs after batched encoding.
    embed_inputs: list[str] = []
    routes: list[str] = []  # "stmt" | "proof" (arxmcp.corpus.chunk.route)
    chunk_ids_in_order: list[str] = []
    for chunk in chunks:
        embed_inputs.append(embedding_input(chunk["body_text"]))
        routes.append(route(chunk["kind"]))
        chunk_ids_in_order.append(chunk["chunk_id"])

    # Batched encode. Truncation counts aggregate across batches.
    import numpy as np  # noqa: PLC0415

    all_vectors: list = []
    truncated_total = 0
    for batch_start in range(0, len(embed_inputs), batch_size):
        batch_texts = embed_inputs[batch_start : batch_start + batch_size]
        # Pass chunk_ids slice for F10 per-chunk DEBUG log on truncation.
        batch_ids = chunk_ids_in_order[batch_start : batch_start + batch_size]
        vectors, truncated_in_batch = _encode_batch(batch_texts, chunk_ids=batch_ids)
        all_vectors.append(vectors)
        truncated_total += truncated_in_batch
    all_array = np.concatenate(all_vectors, axis=0)

    if truncated_total > 0:
        logger.warning(
            "[%s] %d / %d chunks had to be truncated to %d tokens "
            "(the embedding input exceeded BGE-M3 max length); "
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
    for i, chunk_route in enumerate(routes):
        if chunk_route == "proof":
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

    out_path = EMBEDDINGS_DIR / paper_id / EMBEDDINGS_NPZ_NAME
    _write_embeddings_npz(
        out_path,
        chunk_ids_stmt=chunk_ids_stmt,
        embedding_stmt=embedding_stmt,
        chunk_ids_proof=chunk_ids_proof,
        embedding_proof=embedding_proof,
    )

    # E03_S02: sidecar manifest written AFTER the NPZ. A reader that
    # finds an NPZ but no sidecar treats the paper as not-yet-up-to-date
    # and re-embeds (also the migration path from pre-E03_S02 NPZs).
    # ``embedded_chunks`` is in document order (matches manifest order)
    # so BP1 byte-stability holds across hosts. Each entry carries the
    # chunk's kind and its reuse identity, which the next
    # run's skip check compares against.
    sidecar_path = EMBEDDINGS_DIR / paper_id / EMBEDDINGS_MANIFEST_NAME
    embedded_chunks = [
        {
            "chunk_id": chunk["chunk_id"],
            "kind": chunk["kind"],
            "reuse_identity": identities[chunk["chunk_id"]],
        }
        for chunk in chunks
    ]
    _write_embeddings_manifest(
        sidecar_path,
        paper_id=paper_id,
        embedded_chunks=embedded_chunks,
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
    embedder writes NPZ files, not LanceDB rows.
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

    run_started = time.monotonic()
    results: list[EmbedStats] = []
    for paper_id in paper_ids:
        # Validation runs OUTSIDE the per-paper exception envelope inside
        # embed_paper: an invalid directory name shows up as an
        # InvalidPaperIDError which is a subclass of ValueError and is
        # therefore in PER_PAPER_FAILURE_EXCEPTIONS. We log it as a
        # malformed-input failure rather than aborting.
        try:
            validate_paper_id(paper_id)
        except ValueError:
            logger.warning(
                "embed_corpus: skipping non-paper directory %r under %s",
                paper_id,
                chunks_root,
            )
            continue
        results.append(embed_paper(paper_id, batch_size=batch_size))

    # Closes F2 from E03_S01 critique: brief says "embed-stats.jsonl
    # entry written per run, including paper count, chunk count,
    # wall-clock seconds, and the pinned BGE_M3_COMMIT_SHA." The
    # per-paper rows already carry this for individual papers, but the
    # run boundary itself was unobservable to ops. Append one
    # ``event="run_summary"`` JSONL line per ``embed_corpus`` call so
    # dashboards can ingest "embed_corpus completed" events directly.
    elapsed_s = time.monotonic() - run_started
    _append_run_summary(results, elapsed_s)

    # E03_S02 acceptance criterion: re-running on an unchanged corpus
    # writes 0 rows and logs "all up to date". Fire at corpus level so
    # ops sees a single message rather than per-paper noise. The
    # gate (results AND total_processed == 0 AND total_skipped > 0)
    # ensures the log fires only when at least one paper was actually
    # checked AND nothing required encoding. An empty corpus, or a
    # corpus where every paper is in the manifest-absent state, leaves
    # ``total_skipped == 0`` and the log stays silent (closes F12 from
    # the E03_S02 critique).
    total_processed = sum(r.chunks_processed for r in results)
    total_skipped = sum(r.chunks_skipped for r in results)
    skipped_papers = sum(1 for r in results if r.chunks_skipped > 0)
    if results and total_processed == 0 and total_skipped > 0:
        # Closes F11: previously logged "%d/%d" with both numerator and
        # denominator equal to total_skipped — tautological. Report the
        # paper count too; ops gains the "across N papers" dimension
        # without inventing a fake total.
        logger.info(
            "Skipped %d chunks across %d papers — all up to date.",
            total_skipped,
            skipped_papers,
        )

    return results


def _append_run_summary(
    results: list[EmbedStats], elapsed_s: float
) -> None:
    """Append a corpus-level run-summary JSONL line.

    Closes F2: ops dashboards now have a single event per
    :func:`embed_corpus` call with aggregate ``paper_count``,
    ``chunk_count``, ``wall_clock_seconds``, and the pinned
    ``BGE_M3_COMMIT_SHA``. Per-paper rows are unchanged; this line is
    additional, not a replacement, distinguished from per-paper rows by
    its ``event="run_summary"`` discriminator (the only top-level field
    not present on per-paper rows).
    """
    paper_count = len(results)
    chunk_count = sum(r.chunks_processed for r in results)
    chunks_skipped = sum(r.chunks_skipped for r in results)
    fail_count = sum(1 for r in results if r.status == "fail")
    # E03_S02 D5: aggregate ``chunks_skipped`` exposed at run boundary so
    # an "all up to date" run is observable from the audit trail. Per-
    # paper rows already carry chunks_skipped individually; this is the
    # corpus-level roll-up.
    summary = {
        "bge_m3_commit_sha": BGE_M3_COMMIT_SHA,
        "chunk_count": chunk_count,
        "chunks_skipped": chunks_skipped,
        "elapsed_s": round(elapsed_s, 3),
        "embedder_version": EMBEDDER_VERSION,
        "event": "run_summary",
        "fail_count": fail_count,
        "paper_count": paper_count,
    }
    EMBED_STATS_PATH.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(summary, ensure_ascii=False, sort_keys=True) + "\n"
    try:
        with EMBED_STATS_PATH.open("a", encoding="utf-8") as fh:
            fh.write(line)
    except OSError:
        logger.error("could not write run_summary to %s", EMBED_STATS_PATH)
