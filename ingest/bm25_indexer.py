"""BM25 index builder over ``body_tokens`` (E04_S04).

Standard Python BM25 over pre-tokenized body_tokens. No Tantivy, no
custom analyzer. See H4 remediation.

Builds a per-corpus-version BM25 index by reading every chunk's
``body_tokens`` from the pinned LanceDB dataset version (E04_S02
:func:`server.corpus.open_chunks_table`) and feeding the
whitespace-split token streams to :class:`rank_bm25.BM25Okapi`. The
fitted index is pickled to ``var/arxmcp/index/bm25/v<N>/bm25.pkl`` and
the row-aligned chunk_id list is written as ``chunk_ids.json`` next to
it. The MCP server (E07, Sonnet B) loads the pair on first lexical
query; it never enters the in-memory ingestion path.

**Production wire-up deferral (H1 from the E04_S04 critique).** This
module exposes :func:`build_bm25_index` but does NOT auto-call it
from :func:`ingest.store.write_chunks`. ``write_chunks`` is called
per-batch (potentially multiple times per ingestion run); building
the BM25 index after every batch would be wasteful AND wrong — the
index should be built ONCE over the final corpus state. The corpus
driver (a future milestone, owner TBD) is responsible for sequencing:

    for paper in seed_corpus:
        chunks = chunk_paper(paper)
        embeddings = embed_paper(paper)
        write_chunks(chunks, embeddings, lancedb_path)  # → marker
    build_bm25_index(lancedb_path, corpus_version=final_version)

Until that driver lands, the BM25 index must be built manually after
ingestion. E07 (Sonnet B) is the first downstream consumer and will
either provide the driver or document the manual step.

**H4 closure.** E02_S03's :func:`ingest.tokenizer.tokenize_body`
produces a math-aware whitespace-joined token stream
(e.g. ``\\mathrm{Spec}`` → ``mathrm_Spec``). All BM25 needs at index
time is to call ``.split()`` on that string. The brief's "fictional
Tantivy LaTeX analyzer" is replaced by a pure-Python regex
pre-tokenizer plus stock ``rank_bm25``. This module's docstring
records the closure verbatim per the AC.

**Idempotent re-build.** The brief: "re-running on the same corpus
version is a no-op if files already exist." We check that **both**
``bm25.pkl`` and ``chunk_ids.json`` are regular files (mirrors
E03_S02's verify-the-artifact discipline + E04_S03's M5 ``is_file()``
choice). A partial state — only one file present — falls through to a
full rebuild because the resulting index would be unusable.

**Atomic writes.** Both ``bm25.pkl`` and ``chunk_ids.json`` are
written via the canonical PID + UUID-suffixed tmp + ``os.replace`` +
``try/finally`` cleanup pattern from
:func:`ingest.preamble._write_preamble_json`. POSIX-atomic on the
same filesystem (the tmp file is co-located with the destination).

**Pickle security.** ``bm25.pkl`` is produced locally from trusted
LanceDB data by this module. ``pickle.load`` on an untrusted file is
remote-code-execution; the path
``var/arxmcp/index/bm25/`` MUST be treated as trusted-local. Threat 6
(``08-security-observability-ops.md``) covers model-weight pickles
(deny); the BM25 pickle is application data with the analogous-
narrower attack surface (trust local, deny remote).

TODO(E07): the loader (in :mod:`server` for query-time BM25) MUST
verify file ownership matches process UID and refuse world-writable
paths before calling ``pickle.load``. The defense-in-depth concern
(M1 from the E04_S04 critique) is that documentation alone is not
enforcement. Rationale: when ``var/arxmcp/index/bm25/`` lives on a
shared filesystem (NFS, Docker bind mount, multi-tenant container)
an attacker who can write to that path achieves RCE in the server
process. The mitigation is a simple stat-based check at load time;
this writer leaves a hook for the loader to honor.
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
import pickle
import time
import uuid
from dataclasses import dataclass
from pathlib import Path

from rank_bm25 import BM25Okapi

from server.corpus import open_chunks_table

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Paths and identity constants
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parent.parent

# The directory layout convention: ``var/arxmcp/index/bm25/v<N>/``.
# Confine the ``f"v{N}"`` literal to ``_bm25_version_dir`` below — every
# other reference goes through that helper.
BM25_DIR_NAME = "bm25"
BM25_INDEX_NAME = "bm25.pkl"
BM25_CHUNK_IDS_NAME = "chunk_ids.json"
BM25_INDEX_ROOT = REPO_ROOT / "var" / "arxmcp" / "index" / BM25_DIR_NAME
BM25_STATS_PATH = REPO_ROOT / "var" / "arxmcp" / "ops" / "bm25-stats.jsonl"


def _bm25_version_dir(corpus_version: int) -> Path:
    """Return the per-version BM25 index directory.

    Confines the ``f"v{N}"`` literal to a single function so a future
    rename (e.g. zero-padding to ``v00007``) is a one-line change.
    """
    return BM25_INDEX_ROOT / f"v{corpus_version}"


# ---------------------------------------------------------------------------
# BM25Stats — per-call ops summary
# ---------------------------------------------------------------------------


@dataclass
class BM25Stats:
    """Per-call summary of a :func:`build_bm25_index` invocation.

    One JSON line per call appended to ``var/arxmcp/ops/bm25-stats.jsonl``.
    Mirrors the ``WriteStats`` shape from :mod:`ingest.store` so ops
    dashboards can ingest both with identical key conventions
    (alphabetical keys at serialization time, no timestamps — BP1).

    Closes L4 from the E04_S04 critique: when ``skipped=True``, the
    other count fields (``chunk_count``, ``empty_chunks_skipped``,
    ``paper_count``) are 0 — the caller did not load the existing
    pickle to recompute them. Ops aggregators MUST filter on
    ``skipped == False`` before averaging or summing the count fields.

    Closes L5 from the E04_S04 critique: ``paper_count`` denormalizes
    a self-contained "how many papers in this index" answer into the
    stats line so triage doesn't have to join against
    ``corpus-version.json``.
    """

    chunk_count: int = 0
    corpus_version: int = 0
    elapsed_s: float = 0.0
    empty_chunks_skipped: int = 0
    paper_count: int = 0
    skipped: bool = False

    def to_dict(self) -> dict:
        return {
            "chunk_count": self.chunk_count,
            "corpus_version": self.corpus_version,
            "elapsed_s": round(self.elapsed_s, 3),
            "empty_chunks_skipped": self.empty_chunks_skipped,
            "paper_count": self.paper_count,
            "skipped": self.skipped,
        }


def _append_bm25_stats(stats: BM25Stats) -> None:
    """Append one JSON line to ``var/arxmcp/ops/bm25-stats.jsonl``.

    Append mode is non-atomic but acceptable for an ops log — mirrors
    :func:`ingest.store._append_store_stats`. The directory is created
    on first write.
    """
    BM25_STATS_PATH.parent.mkdir(parents=True, exist_ok=True)
    line = (
        json.dumps(stats.to_dict(), ensure_ascii=False, sort_keys=True) + "\n"
    )
    try:
        with BM25_STATS_PATH.open("a", encoding="utf-8") as fh:
            fh.write(line)
    except OSError:
        logger.error("could not write to bm25-stats.jsonl: %s", BM25_STATS_PATH)


# ---------------------------------------------------------------------------
# Atomic-write helpers
# ---------------------------------------------------------------------------


def _atomic_write_bytes(out_path: Path, payload: bytes) -> None:
    """Atomically write ``payload`` to ``out_path`` (binary).

    PID + UUID-suffixed tmp + ``os.replace`` + ``try/finally`` cleanup.
    Same pattern as :func:`ingest.preamble._write_preamble_json` but
    for bytes (the BM25 pickle).
    """
    out_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = out_path.with_suffix(
        f"{out_path.suffix}.{os.getpid()}.{uuid.uuid4().hex[:8]}.tmp"
    )
    try:
        tmp.write_bytes(payload)
        os.replace(tmp, out_path)
    finally:
        with contextlib.suppress(OSError):
            tmp.unlink(missing_ok=True)


def _atomic_write_text(out_path: Path, payload: str) -> None:
    """Atomically write UTF-8 ``payload`` to ``out_path``.

    Sibling of :func:`_atomic_write_bytes` for the JSON sidecar.
    """
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


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def build_bm25_index(
    lancedb_path: str | Path,
    corpus_version: int,
) -> None:
    """Build and persist the BM25 index for ``corpus_version``.

    Reads every chunk's ``(chunk_id, body_tokens)`` pair from the pinned
    LanceDB dataset version (via :func:`server.corpus.open_chunks_table`),
    fits a :class:`rank_bm25.BM25Okapi` over the whitespace-split token
    streams, and writes ``bm25.pkl`` + ``chunk_ids.json`` to
    ``<BM25_INDEX_ROOT>/v<corpus_version>/`` atomically.

    .. warning::

       Path-traversal validation (Threat 1 from
       ``08-security-observability-ops.md``) is **deferred to E06's
       tool-input boundary** (TODO(E06)). This function trusts
       ``lancedb_path`` as config-derived. Callers passing
       user-supplied paths MUST validate against an allowlisted
       corpus root first.

    Idempotent: if BOTH ``bm25.pkl`` AND ``chunk_ids.json`` already
    exist as regular files in the per-version directory, the function
    is a no-op (logs INFO + appends a ``skipped=True`` stats row).
    Partial state (only one file present) triggers a full rebuild — a
    half-written index is unusable so we don't honor it as a skip.

    Cross-checking ``corpus_version`` against ``corpus-version.json``
    is intentionally NOT done. Callers may build an index for an
    older version (audit / rebuild path); the version validity is
    enforced by ``open_chunks_table``, which raises ``ValueError``
    on bad versions.

    Raises
    ------
    ValueError
        ``corpus_version`` does not exist in the LanceDB dataset, or
        the dataset has zero rows with non-null ``body_tokens`` (a
        zero-document BM25 corpus produces NaN IDFs and is treated
        as an upstream bug).
    FileNotFoundError
        ``lancedb_path`` does not exist on disk (re-raised from
        :func:`open_chunks_table`).
    """
    # Closes L3 from the E04_S04 critique: defense-in-depth validation
    # of the version integer. ``_bm25_version_dir(-1)`` would produce
    # ``var/.../bm25/v-1/`` — LanceDB ``checkout(-1)`` would reject it
    # downstream, but a stray negative value should never reach the
    # path-construction step. Mirrors ``CorpusVersionInfo.from_dict``'s
    # ``version >= 1`` check from E04_S03 H1.
    if (
        not isinstance(corpus_version, int)
        or isinstance(corpus_version, bool)
        or corpus_version < 1
    ):
        raise ValueError(
            f"corpus_version must be a positive int (>= 1), got "
            f"{type(corpus_version).__name__} ({corpus_version!r})"
        )

    start = time.monotonic()
    version_dir = _bm25_version_dir(corpus_version)
    pkl_path = version_dir / BM25_INDEX_NAME
    ids_path = version_dir / BM25_CHUNK_IDS_NAME

    # Idempotent skip: BOTH files must be regular files. ``is_file()``
    # rejects directories and broken symlinks (mirrors E04_S03 M5
    # discipline).
    if pkl_path.is_file() and ids_path.is_file():
        elapsed = time.monotonic() - start
        logger.info(
            "BM25 index already exists at %s — skipping rebuild", version_dir
        )
        # L4: skipped rows leave the count fields at 0 because the
        # caller did not reload the existing pickle. Aggregators must
        # filter on ``skipped == False`` before averaging.
        _append_bm25_stats(
            BM25Stats(
                chunk_count=0,
                corpus_version=corpus_version,
                elapsed_s=elapsed,
                empty_chunks_skipped=0,
                paper_count=0,
                skipped=True,
            )
        )
        return

    # Read the corpus via the canonical reader-side wrapper. This
    # validates the path, performs ``tbl.checkout(version)`` for MVCC
    # isolation, and re-raises bad-version errors as ``ValueError``.
    tbl = open_chunks_table(lancedb_path, version=corpus_version)
    arrow = tbl.to_arrow()
    raw_chunk_ids = arrow.column("chunk_id").to_pylist()
    raw_body_tokens = arrow.column("body_tokens").to_pylist()
    raw_paper_ids = arrow.column("paper_id").to_pylist()

    # Closes M2 from the E04_S04 critique: skip rows whose
    # ``body_tokens`` is None OR an empty/whitespace-only string. Both
    # produce empty token lists after ``.split()``, which would
    # distort BM25's b-normalized IDFs by inflating the document
    # count without contributing tokens. The schema declares
    # ``body_tokens`` non-nullable but does NOT enforce non-empty;
    # this guard is defense-in-depth against an upstream tokenizer
    # regression that emits the empty string for an edge case.
    chunk_ids: list[str] = []
    corpus: list[list[str]] = []
    paper_id_set: set[str] = set()
    empty_chunks_skipped = 0
    for cid, body, pid in zip(
        raw_chunk_ids, raw_body_tokens, raw_paper_ids, strict=True
    ):
        if body is None:
            empty_chunks_skipped += 1
            continue
        tokens = body.split()
        if not tokens:
            empty_chunks_skipped += 1
            logger.warning(
                "BM25 indexer: chunk_id=%s has empty body_tokens; skipping",
                cid,
            )
            continue
        chunk_ids.append(cid)
        corpus.append(tokens)
        if pid is not None:
            paper_id_set.add(pid)

    if not corpus:
        # Zero-row corpus: ``BM25Okapi([])`` produces NaN IDFs and
        # division-by-zero (verified). A real upstream bug at Tier-0
        # since E02_S03 guarantees non-null body_tokens. Surface
        # explicitly rather than writing a useless index.
        raise ValueError(
            f"no rows with body_tokens at corpus_version={corpus_version}; "
            "cannot build BM25 index (cannot fit BM25Okapi on empty corpus)"
        )

    # Fit the BM25 index. Defaults k1=1.5, b=0.75 per
    # ``05-storage-and-indexing.md``.
    bm25 = BM25Okapi(corpus)

    # Atomic writes. Order: chunk_ids.json first (cheap text), then
    # bm25.pkl (larger binary). If we crash between the two, the
    # idempotent-skip check on next run sees only one file and
    # rebuilds — safe.
    ids_payload = json.dumps(chunk_ids, ensure_ascii=False, sort_keys=False) + "\n"
    _atomic_write_text(ids_path, ids_payload)

    pkl_payload = pickle.dumps(bm25, protocol=pickle.HIGHEST_PROTOCOL)
    _atomic_write_bytes(pkl_path, pkl_payload)

    elapsed = time.monotonic() - start
    logger.info(
        "BM25 index built at %s: %d chunks, %.3fs",
        version_dir,
        len(corpus),
        elapsed,
    )
    _append_bm25_stats(
        BM25Stats(
            chunk_count=len(corpus),
            corpus_version=corpus_version,
            elapsed_s=elapsed,
            empty_chunks_skipped=empty_chunks_skipped,
            paper_count=len(paper_id_set),
            skipped=False,
        )
    )


__all__ = [
    "BM25_CHUNK_IDS_NAME",
    "BM25_DIR_NAME",
    "BM25_INDEX_NAME",
    "BM25_INDEX_ROOT",
    "BM25_STATS_PATH",
    "BM25Stats",
    "build_bm25_index",
]
