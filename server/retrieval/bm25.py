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
the TODO(E07) hook left by E04_S04. (BM25 pickles are an
application-data analog of the model-weight pickle threat
documented under Threat 6 in
``.claude/notes/08-security-observability-ops.md`` — Threat 6
itself is about HuggingFace model weights, but the BM25 pickle
shares the same load-untrusted-bytes risk surface.)

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

#: Filter keys the chunks table CAN honor. The chunks schema
#: (``ingest/schema.py:69-118``) carries ``paper_id``, ``kind``,
#: ``chunker_version``, ``embedder_version``, ``preamble_ref``,
#: ``source_kind``. We honor ``paper_id`` and ``source_kind`` (m9 /
#: e4) — the others are unlikely in agent queries and a precise
#: filter API for them lands when the ``papers`` metadata table ships.
#: Mirrors ``server.handlers.search.SUPPORTED_FILTER_KEYS``.
SUPPORTED_FILTER_KEYS: frozenset[str] = frozenset({"paper_id", "source_kind"})

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


def _assert_stat_safe(st: os.stat_result, path_for_msg: Path) -> None:
    """Raise :class:`BM25IndexUnsafeError` if a stat result fails the
    file-safety check.

    Extracted as a pure function so callers can apply the check to
    EITHER an :func:`os.stat` result OR an :func:`os.fstat` result on
    an open file descriptor. The fd path is the production path
    (closes F1 — the TOCTOU window between ``stat`` and ``open``);
    the path-based form is used for the parent-directory check (F2).

    Two checks (both must pass):

    1. **Ownership match.** ``st.st_uid == os.geteuid()``. Different-uid
       ownership means an attacker with write access to that user's
       tree could have crafted the file.
    2. **Not world-writable.** ``mode & 0o002 == 0``. A world-writable
       file is trivially attacker-controllable on a shared filesystem
       regardless of ownership.
    """
    if os.name != "posix":
        return  # no POSIX uid/mode semantics

    euid = os.geteuid()
    if st.st_uid != euid:
        raise BM25IndexUnsafeError(
            f"BM25 file at {path_for_msg} is owned by uid={st.st_uid} but "
            f"the server runs as uid={euid}; refusing to load. An attacker "
            f"with write access to that user's tree could craft a "
            f"malicious artifact (BM25 pickles are an application-data "
            f"analog of the model-weight pickle threat documented under "
            f"Threat 6 in .claude/notes/08-security-observability-ops.md). "
            f"To fix: chown the file to {euid}, or rebuild the index "
            f"from trusted-local data."
        )

    if st.st_mode & stat.S_IWOTH:
        raise BM25IndexUnsafeError(
            f"BM25 file at {path_for_msg} is world-writable "
            f"(mode={oct(st.st_mode)}); refusing to load. A world-writable "
            f"file is attacker-controllable regardless of ownership. To "
            f"fix: chmod o-w {path_for_msg}."
        )


def _assert_dir_safe(dir_path: Path) -> None:
    """Raise :class:`BM25IndexUnsafeError` if ``dir_path`` is unsafe.

    F2 fix: a per-file ownership/mode check is insufficient if the
    parent directory is world-writable or owned by another uid — the
    attacker can ``unlink + write`` a fresh file with their chosen
    mode/owner. We check the parent dir with the same primitive plus
    the sticky-bit exemption (so ``/tmp``-style world-writable
    directories with sticky bit set are tolerated; in practice the
    BM25 index root is under ``var/`` and should be neither, but the
    exemption keeps the test fixture path workable).
    """
    if os.name != "posix":
        return

    try:
        st = os.stat(dir_path)
    except FileNotFoundError as exc:
        raise BM25IndexUnavailableError(
            f"BM25 directory missing at {dir_path}"
        ) from exc

    euid = os.geteuid()
    if st.st_uid != euid:
        raise BM25IndexUnsafeError(
            f"BM25 directory {dir_path} is owned by uid={st.st_uid} but "
            f"the server runs as uid={euid}; refusing to load. A "
            f"different-uid parent directory means the attacker can "
            f"unlink+replace the artifact regardless of its file mode. "
            f"To fix: chown {dir_path} to {euid}."
        )

    if (st.st_mode & stat.S_IWOTH) and not (st.st_mode & stat.S_ISVTX):
        # World-writable AND not sticky — attacker can swap any file inside.
        raise BM25IndexUnsafeError(
            f"BM25 directory {dir_path} is world-writable without the "
            f"sticky bit (mode={oct(st.st_mode)}); refusing to load. "
            f"A world-writable parent dir lets an attacker unlink the "
            f"trusted artifact and replace it. To fix: chmod o-w "
            f"{dir_path} (recommended 0o700)."
        )


def _open_safely_for_load(path: Path) -> tuple[int, os.stat_result]:
    """Open ``path`` and verify safety atomically via fstat — closes
    F1 (TOCTOU between stat and open).

    Opens with ``O_RDONLY | O_NOFOLLOW`` (refuses symlinks too, which
    a separate-stat path would also miss), fstats the open fd, runs
    the safety checks against the fstat result, and returns the fd +
    stat for the caller to ``os.fdopen`` and read. The fd is the
    canonical reference to "the file we just stat-checked"; no
    subsequent path-based open can be victim of a between-syscall
    swap.

    Returns
    -------
    (fd, stat_result) : tuple[int, os.stat_result]
        The caller owns the fd — must close it (typically via
        ``os.fdopen(fd, "rb")`` which closes on context exit).
    """
    if not path.is_file():
        # Cheap upfront check; the open below would also fail but
        # this gives a more specific error message.
        raise BM25IndexUnavailableError(f"BM25 file missing at {path}")

    flags = os.O_RDONLY
    if os.name == "posix":
        # NOFOLLOW: refuse symlinks. A symlink to /etc/shadow would
        # otherwise let an attacker exfiltrate any readable file.
        flags |= os.O_NOFOLLOW
    fd = os.open(path, flags)
    try:
        st = os.fstat(fd)
        _assert_stat_safe(st, path)
    except Exception:
        os.close(fd)
        raise
    return fd, st


def _assert_pickle_file_safe(path: Path) -> None:
    """Backwards-compatible facade kept for the test surface.

    Production paths use :func:`_open_safely_for_load` instead, which
    closes the TOCTOU window. This function still does a
    stat-then-check (the legacy semantics), so a test that asserts
    "this file passes the safety check" still works. New production
    code should NOT call this — call :func:`_open_safely_for_load`
    and read from the fd.
    """
    if not path.is_file():
        # Re-raise as BM25IndexUnavailableError to preserve the
        # legacy test contract distinguishing missing from unsafe.
        raise BM25IndexUnavailableError(f"BM25 pickle missing at {path}")
    if os.name != "posix":
        return
    st = os.stat(path)
    _assert_stat_safe(st, path)


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
        live_chunk_ids: set[str] | None = None,
    ) -> BM25Phase:
        """Async constructor: resolve artifact path, auto-build if
        missing, file-safety-check (TOCTOU-safe via fstat), load,
        cross-check chunk_ids against the live LanceDB table, return
        ready instance.

        Off-loads the build + load to the default executor since
        both are synchronous file I/O that would otherwise block the
        startup event loop.

        Parameters
        ----------
        lancedb_path: str | Path
            Path to the LanceDB dataset root.
        corpus_version: int
            Pinned corpus version. The artifact at
            ``var/.../bm25/v<corpus_version>/`` is loaded.
        live_chunk_ids: set[str] | None
            F4 fix from the E07_S01 critique: optionally cross-check
            that every chunk_id in ``chunk_ids.json`` exists in the
            live LanceDB chunks table. When provided, missing ids
            cause :class:`BM25IndexUnavailableError`. Recommended in
            production (Resources.startup passes it after opening
            the chunks table); optional in tests that don't have a
            chunks table to cross-check against.

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
            None,
            cls._sync_startup,
            lancedb_path,
            corpus_version,
            live_chunk_ids,
        )

    @classmethod
    def _sync_startup(
        cls,
        lancedb_path: str | Path,
        corpus_version: int,
        live_chunk_ids: set[str] | None = None,
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

        # F2 fix: parent-directory safety — refuse if the directory
        # is world-writable (without sticky bit) or owned by a
        # different uid. Without this, an attacker who controls the
        # parent dir can unlink+swap any file regardless of file mode.
        _assert_dir_safe(version_dir)

        # F1 fix: open + fstat + safety-check + load, all on the same
        # file descriptor. Closes the TOCTOU window between
        # stat-by-name and open-by-name. Same fd is then handed to
        # pickle.load via os.fdopen.
        pkl_fd, _pkl_st = _open_safely_for_load(pkl_path)
        try:
            with os.fdopen(pkl_fd, "rb") as fh:
                bm25 = pickle.load(fh)  # noqa: S301 — fd safety verified above
        except Exception:
            # If pickle.load raises mid-read, the with-statement closed
            # the fd already; nothing more to clean up here.
            raise

        ids_fd, _ids_st = _open_safely_for_load(ids_path)
        try:
            with os.fdopen(ids_fd, encoding="utf-8") as fh:
                chunk_ids = json.load(fh)
        except Exception:
            raise

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

        # F4 fix: cross-check chunk_ids against the LIVE LanceDB
        # table when the caller provides the live id set. Catches
        # phantom-id tampering AND a corrupted-build that wrote
        # chunk_ids that don't exist in the table any longer (e.g.
        # corpus rebuilt without rebuilding BM25). Set membership is
        # O(N).
        if live_chunk_ids is not None:
            missing = set(chunk_ids) - live_chunk_ids
            if missing:
                # Show at most 5 ids in the error to keep the
                # message readable on a large-corpus mismatch.
                sample = sorted(missing)[:5]
                raise BM25IndexUnavailableError(
                    f"BM25 chunk_ids contains {len(missing)} ids not "
                    f"present in the live LanceDB table at "
                    f"corpus_version={corpus_version}. The artifact is "
                    f"stale or tampered — rebuild via "
                    f"``build_bm25_index``. Sample missing ids: "
                    f"{sample}"
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

        # 5b. F13 fix: if a supported filter dropped EVERYTHING, the
        # over-fetch budget was insufficient. Retry once with a full-
        # corpus sort. At seed scale this is free; at 200K scale
        # it's a single-digit-ms cost on a rare path. Bounded to one
        # retry — no infinite loop possible.
        if (
            has_supported_filter
            and not candidates
            and fetch_n < n_candidates
        ):
            full_order = np.argsort(-scores)
            full_candidates: list[tuple[str, float]] = []
            for idx in full_order:
                score = float(scores[idx])
                if score <= 0.0:
                    break
                full_candidates.append((self._chunk_ids[int(idx)], score))
            candidates = _apply_supported_filters(
                full_candidates, filters or {}
            )

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


def _source_kind_from_chunk_id(chunk_id: str) -> str | None:
    """Infer ``source_kind`` from a chunk_id prefix (m9 / e4).

    BM25 candidates are ``(chunk_id, score)`` tuples with no
    source_kind column, so the BM25 path infers it from the id prefix:
    ``arxiv:<paper_id>:<hex>`` → ``"arxiv"``;
    ``textbook:<slug>:<hex>`` → ``"textbook"``. Returns ``None`` for an
    unrecognized prefix (treated as not-matching any source_kind
    filter). This is the SUPPLEMENTARY BM25-path filter; the
    authoritative dense-path filter is the LanceDB ``source_kind``
    pre-filter predicate in ``server/handlers/search.py``.
    """
    if chunk_id.startswith("arxiv:"):
        return "arxiv"
    if chunk_id.startswith("textbook:"):
        return "textbook"
    return None


def _apply_supported_filters(
    candidates: list[tuple[str, float]],
    filters: dict[str, Any],
) -> list[tuple[str, float]]:
    """Apply the supported filter keys to ``candidates`` (BM25 path).

    For ``paper_id``: parse the chunk_id (format
    ``arxiv:<paper_id>:<16-hex>``) and keep only candidates whose
    paper_id matches the filter value (str OR list[str]).

    For ``source_kind`` (m9 / e4): infer the source_kind from the
    chunk_id prefix and keep only matching candidates. Supplementary
    to the authoritative LanceDB dense-path pre-filter.

    Filters compose (AND): a candidate must satisfy EVERY present
    supported filter to survive.
    """
    if not filters:
        return candidates

    out = candidates

    paper_id_filter = filters.get("paper_id")
    if paper_id_filter is not None:
        # Normalize the filter value to a frozenset for O(1) membership.
        if isinstance(paper_id_filter, str):
            allowed = frozenset({paper_id_filter})
        else:
            allowed = frozenset(paper_id_filter)
        filtered: list[tuple[str, float]] = []
        for chunk_id, score in out:
            # chunk_id format: arxiv:<paper_id>:<16-hex>. paper_id may
            # itself contain a colon (old-style ids like
            # ``math/9912001``), so split on the LAST colon.
            if not chunk_id.startswith("arxiv:"):
                continue
            rest = chunk_id[len("arxiv:") :]
            if ":" not in rest:
                continue
            paper_id, _suffix = rest.rsplit(":", 1)
            if paper_id in allowed:
                filtered.append((chunk_id, score))
        out = filtered

    source_kind_filter = filters.get("source_kind")
    if source_kind_filter is not None:
        out = [
            (cid, score) for (cid, score) in out
            if _source_kind_from_chunk_id(cid) == source_kind_filter
        ]

    return out
