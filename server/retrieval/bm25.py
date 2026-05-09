"""Phase 1 BM25 retrieval over ``body_tokens`` (E07_S01).

Loads the per-corpus-version BM25 artifact built by
:func:`ingest.bm25_indexer.build_bm25_index` and serves
:meth:`BM25Phase.query` as the cheap-and-broad first stage of the
hybrid retrieval pipeline. E07_S02 (RRF) consumes the returned
candidate list; E07_S03 (reranker) further narrows it.

**Architecture: in-memory pickle, NOT LanceDB FTS.** E04_S04 shipped
``bm25.pkl`` + ``chunk_ids.json`` sidecars under
``var/arxmcp/index/bm25/v<N>/``. ``rank_bm25.BM25Okapi.get_scores``
is read-only after construction (pure NumPy ops on indexed
``idf``/``doc_freqs``/``doc_len`` arrays), so no locking is needed
for concurrent reads. The brief's "LanceDB scalar + FTS predicates"
phrasing is aspirational — no ``create_fts_index`` call exists in
the codebase. See research-synthesis.md D1.

**Pickle loader hardening (E04_S04 TODO(E07)).** The original
``ingest/bm25_indexer.py:62-71`` docstring carries a documented-but-
unenforced threat-model: when ``var/arxmcp/index/bm25/`` lives on a
shared filesystem (NFS, Docker bind mount, multi-tenant container),
an attacker who can write to that path achieves RCE in the server
process via ``pickle.load``. This module enforces the mitigation:
:func:`_assert_pickle_file_safe` stat-checks file ownership and
refuses world-writable paths BEFORE calling ``pickle.load``. Closes
the TODO(E07) hook left by E04_S04. (Threat 6 from
``08-security-observability-ops.md``.)

**Auto-build at startup.** E04_S04 critique H1 flagged that nothing
in production code calls :func:`build_bm25_index`. This module
closes that gap: :meth:`BM25Phase.startup` invokes
``build_bm25_index`` if the per-version artifact is missing, then
loads it. The build is idempotent-skip if both files already exist
(``ingest/bm25_indexer.py:293``), so warm starts pay nothing.

**Filter handling.** The brief lists ``categories``, ``year_min``,
``year_max``, ``authors``, ``include_withdrawn`` as filter keys.
NONE of those columns exist on the ``chunks`` LanceDB table
(verified in ``ingest/schema.py:69-118``). The ``papers`` metadata
table planned in E06_S03 brief 1 has not been built. For Tier-1 v1,
this module honors ``paper_id`` (a real chunks column) and surfaces
all other keys as ``filter_warnings`` strings — same precedent as
``server/handlers/search.py:131-141`` (E06_S03 F6 fix). The brief AC
``filters={"categories": ["math.AG"]}`` is reinterpreted as "the
warning surface is non-empty for unsupported filter keys."

**Query tokenization parity.** The query MUST go through
:func:`ingest.tokenizer.tokenize_body` before BM25 scoring. The
index was built on the tokenizer's output; without parity, raw
``\\Spec`` would miss the indexed ``Spec`` token entirely. The
"byte-faithful" rule in
``.claude/notes/07-multi-agent-caching.md:132-134`` applies upstream
of caching (the cache key uses ``query.strip()`` only); BM25
itself needs the tokenized form to retrieve anything.

**Return shape: ``tuple[list[tuple[str, float]], list[str]]``.**
Deviates from the brief's ``list[tuple[str, float]]`` to also carry
the ``filter_warnings`` array (one warning per unsupported filter
key). Couples the API to filter semantics, but lets E07_S02 propagate
warnings up to ``search.py``'s envelope without an extra side-channel.
See research-synthesis.md, "Open: how to surface filter_warnings."
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import pickle
import stat
from pathlib import Path
from typing import TYPE_CHECKING, Any

import numpy as np

from ingest.bm25_indexer import (
    BM25_CHUNK_IDS_NAME,
    BM25_INDEX_NAME,
    _bm25_version_dir,
    build_bm25_index,
)
from ingest.tokenizer import tokenize_body

if TYPE_CHECKING:
    from rank_bm25 import BM25Okapi

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Public constants
# ---------------------------------------------------------------------------

#: Default top-N candidates returned by :meth:`BM25Phase.query`. Per
#: ``.claude/notes/05-storage-and-indexing.md:323-325`` ("Take
#: top-200"). E07_S02 then narrows to top-50 via RRF.
DEFAULT_TOP_N: int = 200

#: Over-fetch factor when filters are present. We pull
#: ``top_n * OVER_FETCH_FACTOR`` from BM25, post-filter, then truncate
#: to ``top_n``. Mirrors ``server/handlers/search.py:115`` over-fetch
#: discipline. Re-fitting BM25 per-subcorpus would change IDFs and
#: cost ~100ms+ — over-fetching is the right trade.
OVER_FETCH_FACTOR: int = 4

#: Filter keys the chunks table CAN honor in v1. The chunks schema
#: (``ingest/schema.py:69-118``) carries ``paper_id``, ``kind``,
#: ``chunker_version``, ``embedder_version``, ``preamble_ref``. For
#: v1 we honor only ``paper_id`` — the others are unlikely in agent
#: queries and a precise filter API for them lands when the
#: ``papers`` metadata table ships.
SUPPORTED_FILTER_KEYS: frozenset[str] = frozenset({"paper_id"})

#: Filter keys the brief lists but the chunks table does NOT carry.
#: When any of these appear in the ``filters`` arg, we surface a
#: ``filter_warnings`` entry naming the key and the deferring
#: milestone.
DEFERRED_FILTER_KEYS: frozenset[str] = frozenset(
    {"categories", "year_min", "year_max", "authors", "include_withdrawn"}
)


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class BM25IndexUnavailableError(RuntimeError):
    """Raised when the BM25 artifact cannot be loaded AND auto-build
    fails. Lifted to a startup-time error by ``Resources.startup``
    so ``/readyz`` never opens on a half-warm BM25 phase."""


class BM25IndexUnsafeError(BM25IndexUnavailableError):
    """Raised when the BM25 pickle path fails the file-safety check.

    Closes E04_S04 TODO(E07): the loader refuses to ``pickle.load`` a
    file that is (a) not owned by the running process's effective
    UID, OR (b) world-writable (mode bit ``0o002``). When
    ``var/arxmcp/index/bm25/`` lives on a shared filesystem an
    attacker who can write there achieves RCE in the server process
    via crafted pickle data — the stat-check is the
    defense-in-depth backstop.
    """


# ---------------------------------------------------------------------------
# File-safety check (closes E04_S04 TODO(E07))
# ---------------------------------------------------------------------------


def _assert_pickle_file_safe(path: Path) -> None:
    """Raise :class:`BM25IndexUnsafeError` if ``path`` is unsafe to
    ``pickle.load``.

    Two checks (both must pass):

    1. **Ownership match.** ``os.stat(path).st_uid`` must equal the
       process's effective UID. If the file is owned by a different
       user, an attacker with write access to that user's tree could
       have crafted the pickle for RCE.
    2. **Not world-writable.** ``mode & 0o002 == 0``. A
       world-writable pickle is trivially attacker-controllable on a
       shared filesystem regardless of ownership.

    The check is skipped on Windows (no POSIX UID semantics). The
    arXMCP server is local-first / Docker on Linux + macOS; Windows
    support is explicitly out of scope.
    """
    if os.name != "posix":
        # No POSIX UID/mode semantics — trust local on this platform.
        return

    try:
        st = os.stat(path)
    except FileNotFoundError as exc:
        # Re-raise as the more-specific BM25IndexUnavailableError so
        # the caller can distinguish "missing" from "unsafe".
        raise BM25IndexUnavailableError(
            f"BM25 pickle missing at {path}"
        ) from exc

    euid = os.geteuid()
    if st.st_uid != euid:
        raise BM25IndexUnsafeError(
            f"BM25 pickle at {path} is owned by uid={st.st_uid} but the "
            f"server runs as uid={euid}; refusing to pickle.load. An "
            f"attacker with write access to that user's tree could craft "
            f"a malicious pickle (Threat 6 — see "
            f".claude/notes/08-security-observability-ops.md). To fix: "
            f"chown the file to {euid}, or rebuild the index from "
            f"trusted-local data."
        )

    if st.st_mode & stat.S_IWOTH:
        raise BM25IndexUnsafeError(
            f"BM25 pickle at {path} is world-writable (mode={oct(st.st_mode)}); "
            f"refusing to pickle.load. A world-writable pickle is "
            f"attacker-controllable regardless of ownership. To fix: "
            f"chmod o-w {path}."
        )


# ---------------------------------------------------------------------------
# BM25Phase
# ---------------------------------------------------------------------------


class BM25Phase:
    """Phase-1 BM25 retrieval over the ``body_tokens`` column.

    Constructed once at server startup via :meth:`startup` (which
    resolves the per-version artifact path, auto-builds if missing,
    and loads the pickle into memory). Reused across every request.
    Read-only after construction; safe for concurrent readers.

    Public API:

    - :meth:`startup` (classmethod) — async constructor for use from
      :meth:`server.resources.Resources.startup`.
    - :meth:`query` — synchronous BM25 scoring. CPU-bound; callers
      that need to run in an async context should wrap in
      ``asyncio.to_thread`` (the ``server.resources`` integration
      does this for the load step but NOT the query step — query
      is sub-millisecond at the seed-corpus scale).
    """

    def __init__(
        self,
        bm25: BM25Okapi,
        chunk_ids: list[str],
        corpus_version: int,
        artifact_path: Path,
    ) -> None:
        """Direct construction is for internal use / tests. Production
        callers use :meth:`startup` instead."""
        self._bm25 = bm25
        self._chunk_ids = chunk_ids
        self._corpus_version = corpus_version
        self._artifact_path = artifact_path

    # ------------------------------------------------------------------
    # Read-only introspection
    # ------------------------------------------------------------------

    @property
    def corpus_version(self) -> int:
        """The pinned LanceDB corpus version this index was built
        against. ``Resources.startup`` MUST construct only one
        ``BM25Phase`` at the corpus version it pinned; switching
        versions requires a server restart."""
        return self._corpus_version

    @property
    def corpus_size(self) -> int:
        """Number of chunks in the BM25 corpus. Useful for
        observability + tests asserting the artifact loaded correctly."""
        return len(self._chunk_ids)

    @property
    def artifact_path(self) -> Path:
        """Path to the loaded ``bm25.pkl`` file. Useful for log
        lines + the file-safety regression tests."""
        return self._artifact_path

    # ------------------------------------------------------------------
    # Async startup
    # ------------------------------------------------------------------

    @classmethod
    async def startup(
        cls,
        lancedb_path: str | Path,
        corpus_version: int,
    ) -> BM25Phase:
        """Async constructor: resolve artifact path, auto-build if
        missing, file-safety-check, ``pickle.load``, return ready
        instance.

        Off-loads the build + load to the default executor since
        both are synchronous file I/O that would otherwise block the
        startup event loop. Mirrors the LanceDB / BGE-M3 load
        discipline in :meth:`server.resources.Resources.startup`.

        Raises
        ------
        BM25IndexUnavailableError
            ``build_bm25_index`` failed AND no pre-built artifact
            exists — server must refuse to start.
        BM25IndexUnsafeError
            The pickle exists but fails the file-safety check
            (wrong owner OR world-writable). Subclass of
            :class:`BM25IndexUnavailableError`.
        """
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            None, cls._sync_startup, lancedb_path, corpus_version
        )

    @classmethod
    def _sync_startup(
        cls,
        lancedb_path: str | Path,
        corpus_version: int,
    ) -> BM25Phase:
        """Sync implementation of :meth:`startup`. Extracted so tests
        can construct without running a loop."""
        version_dir = _bm25_version_dir(corpus_version)
        pkl_path = version_dir / BM25_INDEX_NAME
        ids_path = version_dir / BM25_CHUNK_IDS_NAME

        # Auto-build (closes E04_S04 H1) — idempotent-skip in the
        # warm-start case.
        if not (pkl_path.is_file() and ids_path.is_file()):
            logger.info(
                "BM25 artifact missing at %s; auto-building from corpus "
                "version=%d", version_dir, corpus_version,
            )
            try:
                build_bm25_index(lancedb_path, corpus_version=corpus_version)
            except Exception as exc:
                raise BM25IndexUnavailableError(
                    f"BM25 auto-build failed for corpus_version="
                    f"{corpus_version} at {lancedb_path}: {exc}"
                ) from exc

        # Post-build sanity: both files MUST now exist.
        if not (pkl_path.is_file() and ids_path.is_file()):
            raise BM25IndexUnavailableError(
                f"BM25 artifact still missing after build attempt at "
                f"{version_dir}; expected both {BM25_INDEX_NAME} and "
                f"{BM25_CHUNK_IDS_NAME}"
            )

        # File safety (closes E04_S04 TODO(E07)). Both files run
        # through the check — chunk_ids.json is JSON not pickle, so
        # the world-writable risk is lower, but a malicious tampered
        # JSON could still misalign chunk_ids with the pickle and
        # cause silent index corruption. Cheap to check both.
        _assert_pickle_file_safe(pkl_path)
        _assert_pickle_file_safe(ids_path)

        # Load.
        with open(pkl_path, "rb") as fh:
            bm25 = pickle.load(fh)  # noqa: S301 — file safety asserted above
        with open(ids_path, encoding="utf-8") as fh:
            chunk_ids = json.load(fh)

        # Sanity: corpus_size and chunk_ids length must match. A
        # mismatch means the artifact pair is from different builds
        # and would silently return wrong chunk_ids.
        if bm25.corpus_size != len(chunk_ids):
            raise BM25IndexUnavailableError(
                f"BM25 artifact pair at {version_dir} is misaligned: "
                f"bm25.corpus_size={bm25.corpus_size} but "
                f"chunk_ids has {len(chunk_ids)} entries. The pair "
                f"must be rebuilt from a single ``build_bm25_index`` "
                f"invocation."
            )

        logger.info(
            "BM25Phase loaded: corpus_version=%d, corpus_size=%d, path=%s",
            corpus_version, bm25.corpus_size, pkl_path,
        )
        return cls(
            bm25=bm25,
            chunk_ids=list(chunk_ids),
            corpus_version=corpus_version,
            artifact_path=pkl_path,
        )

    # ------------------------------------------------------------------
    # Query
    # ------------------------------------------------------------------

    def query(
        self,
        text: str,
        filters: dict[str, Any] | None = None,
        top_n: int = DEFAULT_TOP_N,
    ) -> tuple[list[tuple[str, float]], list[str]]:
        """Score the corpus against ``text``; return top-N candidates +
        any filter warnings.

        Tokenization parity: ``text`` is passed through
        :func:`ingest.tokenizer.tokenize_body` then ``.split()``
        before scoring — same path the indexer used. Without this,
        raw LaTeX (``\\Spec``) would miss the indexed token
        (``Spec``) entirely.

        Filter handling: see module docstring. ``paper_id`` is the
        only honored filter; all others surface as
        ``filter_warnings`` strings naming the key and the deferring
        milestone.

        Returns
        -------
        candidates : list[tuple[str, float]]
            ``(chunk_id, bm25_score)`` tuples, sorted descending by
            score. Length ≤ ``top_n``. May be empty if the tokenized
            query is empty OR if all candidates were filtered out.
        filter_warnings : list[str]
            One human-readable warning per unsupported filter key.
            Empty when no filters or only supported filters.
        """
        if top_n < 1:
            raise ValueError(f"top_n must be >= 1; got {top_n}")

        # 1. Tokenize the query (parity with index-time).
        tokens = tokenize_body(text).split()
        if not tokens:
            # Tokenizer collapsed the query to nothing (e.g. punctuation
            # only). BM25 cannot score an empty query — return empty.
            return ([], _build_filter_warnings(filters))

        # 2. Score the entire corpus. ``get_scores`` is read-only
        #    after construction; safe under concurrent readers.
        scores = self._bm25.get_scores(tokens)  # np.ndarray of length corpus_size

        # 3. Top-K extraction with over-fetch when filters present.
        warnings = _build_filter_warnings(filters)
        # If there's a paper_id filter, over-fetch by OVER_FETCH_FACTOR
        # so we have headroom after post-filtering. If only deferred
        # filters are present, no need to over-fetch (we can't apply
        # them anyway).
        has_supported_filter = bool(
            filters and any(k in SUPPORTED_FILTER_KEYS for k in filters)
        )
        fetch_n = top_n * OVER_FETCH_FACTOR if has_supported_filter else top_n
        # ``argpartition`` is O(n) for top-K; cheaper than a full sort.
        # If the corpus is smaller than fetch_n, just sort the whole thing.
        n_candidates = len(scores)
        if fetch_n >= n_candidates:
            # Full sort.
            order = np.argsort(-scores)
        else:
            # Partial: argpartition the top-fetch_n, then sort that slice.
            unsorted_top = np.argpartition(scores, -fetch_n)[-fetch_n:]
            order = unsorted_top[np.argsort(-scores[unsorted_top])]

        # 4. Build candidates, dropping zero-scoring entries (BM25
        #    score of 0 means no shared tokens — useless candidate).
        candidates: list[tuple[str, float]] = []
        for idx in order:
            score = float(scores[idx])
            if score <= 0.0:
                # Sorted descending — once we hit zero, the rest are
                # zero too. Early exit.
                break
            candidates.append((self._chunk_ids[int(idx)], score))

        # 5. Apply supported filters (post-fetch).
        candidates = _apply_supported_filters(candidates, filters or {})

        # 6. Truncate to top_n.
        return (candidates[:top_n], warnings)


# ---------------------------------------------------------------------------
# Filter helpers
# ---------------------------------------------------------------------------


def _build_filter_warnings(filters: dict[str, Any] | None) -> list[str]:
    """Build the ``filter_warnings`` list from the request's filters
    arg. One warning per unsupported key, naming the deferring
    milestone for the columns the chunks table doesn't carry."""
    if not filters:
        return []
    warnings: list[str] = []
    for key in sorted(filters):
        if key in SUPPORTED_FILTER_KEYS:
            continue
        if key in DEFERRED_FILTER_KEYS:
            warnings.append(
                f"filter key {key!r} is accepted but not yet processed: "
                f"the chunks table has no {key!r} column; the papers "
                f"metadata table planned for a future milestone will "
                f"add it"
            )
        else:
            warnings.append(
                f"filter key {key!r} is unknown; supported keys are "
                f"{sorted(SUPPORTED_FILTER_KEYS)}; deferred keys are "
                f"{sorted(DEFERRED_FILTER_KEYS)}"
            )
    return warnings


def _apply_supported_filters(
    candidates: list[tuple[str, float]],
    filters: dict[str, Any],
) -> list[tuple[str, float]]:
    """Apply only the supported filter keys to ``candidates``.

    For ``paper_id``: parse the chunk_id (format
    ``arxiv:<paper_id>:<16-hex>``) and keep only candidates whose
    paper_id matches the filter value. The filter value may be a
    single string OR a list of strings (matches the
    ``server/handlers/search.py`` filters convention).
    """
    if not filters:
        return candidates

    paper_id_filter = filters.get("paper_id")
    if paper_id_filter is None:
        return candidates

    # Normalize the filter value to a frozenset for O(1) membership.
    if isinstance(paper_id_filter, str):
        allowed = frozenset({paper_id_filter})
    else:
        allowed = frozenset(paper_id_filter)

    out: list[tuple[str, float]] = []
    for chunk_id, score in candidates:
        # chunk_id format: arxiv:<paper_id>:<16-hex>
        # paper_id may itself contain a colon (old-style arXiv ids
        # like ``math/9912001``), so we split on the LAST colon, not
        # the second.
        if ":" not in chunk_id:
            continue
        # strip "arxiv:" prefix, then split off the 16-hex suffix
        if not chunk_id.startswith("arxiv:"):
            continue
        rest = chunk_id[len("arxiv:") :]
        if ":" not in rest:
            continue
        paper_id, _suffix = rest.rsplit(":", 1)
        if paper_id in allowed:
            out.append((chunk_id, score))
    return out
