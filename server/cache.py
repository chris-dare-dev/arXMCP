"""3-tier retrieval cache (E08_S03).

Singleton cache that lives inside the MCP server process and is
shared across all concurrently-connected sub-agents. The cache is
a PERFORMANCE layer — its failure mode is a cache miss (slower but
correct), never a correctness failure (per
``.claude/notes/07-multi-agent-caching.md``: *"Cache layer crash /
OOM → Fall through to recompute; log; alert. Caching is performance,
not correctness."*).

**Three tiers** with progressively-looser equivalence:

- **Tier 1 — Exact-query memo.** SQLite-backed cache, max 10K
  entries, 1-hour TTL. The in-process mirror (an ``OrderedDict``)
  is TRUE LRU on read; the SQLite layer evicts by TTL-priority
  (oldest-expiring first → FIFO under uniform-TTL inserts; F7 fix
  from the E08_S03 critique). Cache key includes ``corpus_version``
  so a corpus bump unreachable-izes every prior entry by hash
  construction. Persists across server restarts (the SQLite file).
- **Tier 2 — Semantic-query memo.** In-process FAISS ``IndexFlatIP``
  over the embeddings of recent queries (deque of 1,000). A hit
  requires cosine similarity ≥ 0.97 AND an exact scope match
  (filters + level + corpus_version + embedder identity) AND an entry
  whose ``k`` was at least the requested ``k``, 15-min TTL. Logs and
  1%-samples every hit for human review (threshold tuning data).
  Cold-start no-op when the ring buffer is empty. **The embedding
  covers the query TEXT axis and nothing else** — every other axis is
  the scope fingerprint's or the ordinal ``k`` test's job (issue #204,
  which found ``k`` covered by neither and a ``k=50`` request being
  served a ``k=5`` payload). A hit carries a :class:`Tier2Match`
  saying whether it was this query's own embedding or a NEIGHBOUR's;
  the ``search_papers`` handler puts that on the wire.
- **Tier 3 — Rerank-set memo.** In-process LRU keyed by the rerank
  singleflight key (reuses
  :func:`server.retrieval.rerank._build_singleflight_key` verbatim).
  TTL 1 hour. Caches the reranker's deterministic output for an
  identical (query, candidates, model) triple.

**Lookup path** for ``search_papers``: Tier-1 → Tier-2 → run pipeline
(possibly skipping Tier-3 for rerank) → write all relevant tiers.
The lookups are sequential, NOT parallel — Tier 2 needs the query
embedding which Tier 1 may avoid computing entirely.

**Singleton lifecycle.** Owned by :class:`server.resources.Resources`;
a module-level reference is also held in this module so handlers can
``from server.cache import get_cache`` without taking the Resources
import. Initialized in :meth:`Resources.startup`, closed in
:meth:`Resources.shutdown`.

**Failure-mode discipline.** Every tier lookup and write is wrapped
in ``try/except Exception`` that logs and falls through. A FAISS
crash, SQLite I/O error, or Prometheus library glitch must NEVER
propagate to the caller — the worst outcome is a cache miss.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import random
import sys
import time
from collections import OrderedDict
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from server.cache_sqlite import (
    DEFAULT_TTL_SECONDS as TIER1_TTL_SECONDS,
)
from server.cache_sqlite import (
    MAX_ROWS as TIER1_MIRROR_CAP,
)
from server.cache_sqlite import (
    Tier1Store,
    derive_tier1_key,
)
from server.metrics import (
    CACHE_EVICTIONS_COUNTER,
    CACHE_HITS_COUNTER,
    CACHE_LOOKUPS_COUNTER,
    CACHE_PAYLOAD_SKIPS_COUNTER,
    TIER_1,
    TIER_2,
    TIER_3,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Tier-2 / Tier-3 constants
# ---------------------------------------------------------------------------

#: Tier-2 TTL (15 minutes per the brief). Shorter than Tier-1
#: because semantic equivalence is fuzzier — we want stale semantic
#: matches to roll over faster.
TIER2_TTL_SECONDS: float = 15 * 60.0

#: Tier-3 TTL (1 hour per the brief).
TIER3_TTL_SECONDS: float = 3600.0

#: Tier-2 ring-buffer capacity. The brief: "up to 1,000 query
#: embeddings retained in the ring buffer".
TIER2_RING_CAPACITY: int = 1_000

#: Tier-2 cosine similarity threshold (the brief: "cosine similarity
#: > 0.97"). We use ``>= 0.97`` for inclusivity (== 0.97 IS a hit).
TIER2_COSINE_THRESHOLD: float = 0.97

#: Tier-2 hit sampling rate (the brief: "Tier-2 hits are logged and
#: 1% sampled for human review"). Bernoulli at 1%.
TIER2_HIT_LOG_SAMPLE_RATE: float = 0.01

#: Tier-3 LRU capacity. Not specified by the brief; 1K entries
#: matches the Tier-2 ring buffer scale. Each entry is small (a list
#: of ranked chunk IDs + scores).
TIER3_LRU_CAPACITY: int = 1_024

#: BGE-M3 embedding dimension. Used to construct the FAISS index.
#: Pinned here for the cache; the source of truth lives in
#: ``server/query_encoder.py``.
EMBEDDING_DIM: int = 1024


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _tier2_scope_fingerprint(
    filters: dict[str, Any] | None,
    *,
    level: str | None = None,
    corpus_version: int,
    embedder_id: str | None = None,
) -> str:
    """Return the canonical SCOPE fingerprint used by Tier-2.

    F12 fix from the E08_S03 critique: the Tier-2 fingerprint derives
    from the SAME ``canonical_key_components`` helper that Tier-1's
    ``derive_tier1_key`` uses. Previously each tier had its own ad-hoc
    encoding, inviting silent drift on a future encoding fix. We hash
    the sub-components via length-prefix encoding (matching Tier-1's F1
    fix) and return the hex digest as the fingerprint string.

    Every axis that changes WHICH rows are correct must be here, because
    the only other thing keying a Tier-2 slot is the query embedding:

    - ``filters`` — ``None`` and ``{}`` produce the same fingerprint so
      a no-filter query and an explicit-empty-filter query share a slot.
      Routing keys (``notebook``, ``include_kinds``) ride this dict.
    - ``level`` — different aggregation levels produce different result
      shapes and must not be treated as matches. ``None`` encodes
      distinctly from any string value.
    - ``corpus_version`` — a per-call notebook override or an in-process
      corpus bump must not be served rows from the other corpus.
    - ``embedder_id`` — a ranking produced by the local fallback while a
      hosted provider was down must not be re-served to a request the
      hosted provider answered (issue #204).

    **``query`` and ``k`` are the two deliberate sentinels, for two
    different reasons.** ``query=""`` is sound: the embedding the slot
    is keyed on IS a function of the query text, so the text axis is
    already covered. ``k=0`` is NOT covered by the embedding — the
    embedding is a function of the query text ONLY — so ``k`` is
    enforced separately, and ordinally, by
    :meth:`RetrievalCache._tier2_lookup`: an entry answers a request
    only when its own ``k`` was at least as large, and the caller
    re-slices. Folding ``k`` in here instead would key ``k=49`` and
    ``k=50`` to separate slots and forfeit that reuse. The pre-#204
    comment claimed the embedding disambiguated ``k`` as well; it does
    not, and that claim is exactly how a ``k=50`` request came to be
    served a five-row payload.
    """
    # Reuse the Tier-1 canonicalizer so any future encoding fix to
    # the Tier-1 key automatically propagates to Tier-2's fingerprint.
    from server.cache_sqlite import canonical_key_components

    canonical = canonical_key_components(
        query="",
        filters=filters,
        k=0,
        corpus_version=corpus_version,
        level=level,
        embedder_id=embedder_id,
    )
    return hashlib.sha256(canonical).hexdigest()


def _approx_payload_bytes(payload: Any) -> int:
    """Return an approximate byte count for a cache payload.

    Tier-1 / Tier-3 byte-usage gauges feed off this. Approximate
    is fine — the gauge is operational telemetry, not a hard limit.
    For dict / JSON-able payloads we use ``len(json.dumps(...))``;
    for already-serialized bytes we use ``len(b)``; for everything
    else we fall back to ``sys.getsizeof``.
    """
    if isinstance(payload, (bytes, bytearray)):
        return len(payload)
    try:
        return len(json.dumps(payload, sort_keys=True, ensure_ascii=False))
    except (TypeError, ValueError):
        return sys.getsizeof(payload)


# ---------------------------------------------------------------------------
# Tier-2 ring-buffer entry
# ---------------------------------------------------------------------------


class _Tier2Entry:
    """One entry in the Tier-2 ring buffer.

    Holds the L2-normalized query embedding (for the FAISS index),
    the scope fingerprint (for the exact-scope-match check), the ``k``
    the payload was built for, the payload, and the expiry timestamp.
    The FAISS index does NOT store the entry by itself — its
    ``ID -> entry`` mapping lives in the parallel ``OrderedDict`` so we
    can rebuild the index cleanly on overflow.

    ``k`` is the ORDINAL axis (issue #204): an entry can answer any
    request for ``k' <= k`` (the caller re-slices) and no request for
    ``k' > k``. It is therefore stored on the entry rather than folded
    into ``scope_fp``, which is the equality axis.
    """

    __slots__ = ("embedding", "scope_fp", "k", "payload", "expires_at")

    def __init__(
        self,
        embedding: np.ndarray,
        scope_fp: str,
        k: int,
        payload: Any,
        expires_at: float,
    ) -> None:
        self.embedding = embedding
        self.scope_fp = scope_fp
        self.k = k
        self.payload = payload
        self.expires_at = expires_at


@dataclass(frozen=True)
class Tier2Match:
    """Provenance of a Tier-2 hit, returned alongside the payload.

    Issue #204: a Tier-2 hit is a NEIGHBOUR's payload whenever
    ``exact_embedding`` is False — the rows answer a query within
    ``TIER2_COSINE_THRESHOLD`` of this one, not this one. Pre-#204 the
    two cases came back shaped byte-identically with nothing on the
    wire to tell them apart. The handler turns this record into the
    response's ``cache_match`` field.

    ``exact_embedding`` is decided by comparing ring-buffer slot keys
    (SHA-256 over the embedding bytes), NOT by a float comparison
    against 1.0 — byte equality is exact and needs no epsilon.

    This is a PROVENANCE axis, deliberately separate from the
    operational ``degraded`` axis and from any epistemic outcome
    (`CLAUDE.md` §4.9: a degraded-but-answered result and an abstention
    never share a token). An approximate hit is a real answer whose
    subject is a nearby question.
    """

    cosine: float
    exact_embedding: bool
    cached_k: int


# ---------------------------------------------------------------------------
# RetrievalCache — the singleton
# ---------------------------------------------------------------------------


class RetrievalCache:
    """3-tier retrieval cache shared across all sub-agents.

    Construct via the :meth:`open` async classmethod which opens the
    SQLite file, initializes the FAISS index, and rehydrates the
    in-process Tier-1 mirror from any unexpired SQLite rows.

    Methods are ``async`` and safe to call from multiple coroutines
    concurrently. Internal state is protected by an ``asyncio.Lock``
    where mutation occurs.
    """

    def __init__(
        self,
        tier1_store: Tier1Store,
        corpus_version: int,
    ) -> None:
        self._tier1_store = tier1_store
        # F18 fix from the E08_S03 critique: defensively cast to int
        # so a future ``corpus-version.json`` containing a JSON
        # number that decodes as float (e.g. ``7.0``) cannot silently
        # produce a ``"7.0"``-keyed entry that misses an int-keyed
        # ``"7"`` lookup. ``read_corpus_version`` is also expected
        # to enforce int but defense in depth is cheap here.
        self._corpus_version = int(corpus_version)

        # Tier-1 in-process mirror (LRU). Stores the deserialized
        # payload so reads avoid the JSON-decode on every hit. The
        # mirror is bounded at the same MAX_ROWS as the SQLite cap.
        self._tier1_mirror: OrderedDict[str, Any] = OrderedDict()
        self._tier1_lock = asyncio.Lock()

        # Tier-2: parallel deque + FAISS index. The deque holds the
        # canonical (key, _Tier2Entry) ordering; the FAISS index is
        # rebuilt from the deque on every overflow rotation.
        self._tier2_buffer: OrderedDict[str, _Tier2Entry] = OrderedDict()
        self._tier2_index: Any = None  # faiss.IndexFlatIP — lazy init
        self._tier2_keys_in_index: list[str] = []  # parallel ordering
        self._tier2_lock = asyncio.Lock()

        # Tier-3 in-process LRU.
        self._tier3_lru: OrderedDict[str, Any] = OrderedDict()
        self._tier3_lock = asyncio.Lock()

    # ------------------------------------------------------------------
    # Open / close
    # ------------------------------------------------------------------

    @classmethod
    async def open(
        cls,
        cache_db_path: Path,
        corpus_version: int,
        *,
        purge_other_versions: bool = False,
    ) -> RetrievalCache:
        """Open the underlying SQLite store, initialize FAISS, and
        rehydrate the Tier-1 mirror from unexpired SQLite rows.

        ``purge_other_versions=True`` drops every Tier-1 row belonging
        to a different ``corpus_version`` BEFORE the rehydrate — issue
        #207. This is the call site
        :meth:`server.cache_sqlite.Tier1Store.purge_other_corpus_versions`
        never had: ``server/corpus.py``'s cache-invalidation contract
        declared that a corpus-version bump MUST clear caches keyed on
        the old version, and the purge method existed to serve that
        contract with zero callers anywhere in the repo.

        Purging BEFORE the rehydrate is load-bearing: the rehydrate
        loads every unexpired row into the bounded in-process mirror,
        so purging afterwards would still let a rebind pull the old
        corpus's rows into memory and evict live ones from the LRU.

        Correctness does not depend on the purge — Tier-1 keys are
        salted with ``corpus_version``, so old-version rows are already
        unreachable by hash construction. It reclaims their disk and
        their mirror slots. ``True`` is passed by
        :meth:`server.resources.Resources._bind_corpus` on every rebind
        and left ``False`` on the cold-start path, where there is no
        previous in-process version to invalidate.
        """
        store = await Tier1Store.open(cache_db_path)
        if purge_other_versions:
            try:
                purged = await store.purge_other_corpus_versions(corpus_version)
                if purged:
                    logger.info(
                        "RetrievalCache.open: purged %d Tier-1 row(s) from "
                        "corpus versions other than %d",
                        purged,
                        corpus_version,
                    )
            except Exception:  # noqa: BLE001 — housekeeping, never fatal
                logger.exception(
                    "RetrievalCache.open: purge_other_corpus_versions failed; "
                    "stale-version rows stay on disk (unreachable by key, so "
                    "this costs disk, not correctness)"
                )
        cache = cls(tier1_store=store, corpus_version=corpus_version)
        await cache._rehydrate_tier1_from_sqlite()
        return cache

    async def invalidate_semantic_tiers(self) -> int:
        """Drop every Tier-2 and Tier-3 entry. Returns the count dropped.

        **Where each tier stands after a corpus bump (issue #207,
        re-checked against #204).**

        * **Tier-1** — keys are salted with ``corpus_version``
          (``derive_tier1_key``), so old entries are unreachable by
          construction. Not this method's problem; the disk they occupy
          is handled by ``purge_other_versions`` on
          :meth:`open`.
        * **Tier-2** — ``_tier2_scope_fingerprint`` folds in
          ``corpus_version``, so as of #204 these are *also* unreachable
          by construction. Clearing them is **reclamation, not
          correctness**: a full ring buffer is 1,000 entries of
          1024-dim float32 embeddings plus payloads, none of which can
          ever be hit again after the bump. (#207 originally justified
          this method on Tier-2 staleness. #204 landed the scope
          fingerprint first and removed that hole — recorded here rather
          than left as a stale rationale.)
        * **Tier-3** — the live reason this method exists. Its key is
          ``sha256(query_embedding + sorted_candidate_ids +
          reranker_version)`` (``_build_singleflight_key``) with NO
          corpus version. The window is narrow but real: a re-ingest
          that rewrites a chunk's BODY while keeping its ``chunk_id``
          leaves a reachable memo whose ranking was computed over the
          old text. Nothing else invalidates it.

        Called on a detected corpus-version change that keeps this
        cache object alive — today, dropping a memoized per-notebook
        table. A full corpus rebind constructs a NEW ``RetrievalCache``
        whose semantic tiers start empty, so it does not need this.

        Deliberately a big hammer: it clears the tiers for EVERY corpus,
        not just the one that bumped, because a Tier-3 entry does not
        record which corpus produced it. Cheap to be wrong-and-safe here
        — these tiers are performance, not correctness, and this fires
        at most once per ingest.
        """
        dropped = 0
        async with self._tier2_lock:
            dropped += len(self._tier2_buffer)
            self._tier2_buffer.clear()
            self._tier2_keys_in_index = []
            if self._tier2_index is not None:
                self._tier2_index.reset()
        async with self._tier3_lock:
            dropped += len(self._tier3_lru)
            self._tier3_lru.clear()
        if dropped:
            logger.info(
                "RetrievalCache.invalidate_semantic_tiers: dropped %d "
                "Tier-2/Tier-3 entr(ies) on a corpus-version change",
                dropped,
            )
        return dropped

    async def close(self) -> None:
        """Flush + close the SQLite store. FAISS index released by GC."""
        try:
            await self._tier1_store.close()
        except Exception:  # noqa: BLE001
            logger.exception("RetrievalCache.close: tier1 close failed")

    async def _rehydrate_tier1_from_sqlite(self) -> None:
        """Load every unexpired SQLite row **for the active corpus
        version** into the in-process LRU.

        Per the brief: *"On server startup, unexpired Tier-1 entries
        are loaded from the SQLite file into the in-process LRU."*

        Capped at the in-process LRU's :data:`MAX_ROWS` cap — if more
        rows are present we keep the most-recently-expiring (i.e.
        most-recently-inserted given uniform TTL).

        **Filtered by ``corpus_version`` (issue #338).** The Tier-1 key
        is salted with the version, so a row from another version is
        unreachable by hash construction — loading it consumes one of
        the 10K mirror slots that a reachable entry could have used, and
        the cap then evicts live entries in its favour. The rows are
        left on disk; ``purge_other_corpus_versions`` (invoked from
        :meth:`open` on the #207 rebind path) is what reclaims them.

        Two things made this filter safe only now. Issue #337 made the
        column honest — before it, a notebook-routed row's column
        disagreed with its key salt, so filtering on the column would
        have dropped REACHABLE rows. And issue #204 added the embedder
        component to the key, which retroactively orphaned every row
        written by an older binary; without this filter the first
        restart after that deploy rehydrates a mirror full of entries
        that can never be hit.

        Notebook-keyed rows are not loaded here, since their salt is the
        notebook's version rather than the shared one. They are still
        reachable — SQLite serves them on the first mirror miss — so
        this costs one lookup per key after a restart, not a re-query.
        """
        try:
            rows = await self._tier1_store.load_all_unexpired(
                corpus_version=self._corpus_version,
            )
        except Exception:  # noqa: BLE001
            logger.exception("RetrievalCache: rehydrate from sqlite failed")
            return

        # Sort by expires_at DESC so the freshest entries land first;
        # F8 fix from the E08_S03 critique: HARD-CAP at TIER1_MIRROR_CAP
        # so the rehydrate cannot overflow the in-process cap (the
        # docstring promised this; the prior implementation only
        # sorted, never truncated).
        rows.sort(key=lambda r: r[2], reverse=True)
        rows = rows[:TIER1_MIRROR_CAP]
        for key, value, expires_at in rows:
            try:
                payload = json.loads(value.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                logger.warning(
                    "RetrievalCache: dropping malformed tier-1 row %s "
                    "during rehydrate", key[:16] + "...",
                )
                continue
            # F2 fix: store ``(payload, expires_at)`` so the mirror
            # enforces TTL on every read. We use the SQLite row's
            # actual expires_at rather than re-deriving (which would
            # silently extend stale entries).
            self._tier1_mirror[key] = (payload, expires_at)
        logger.info(
            "RetrievalCache: rehydrated %d tier-1 entries from sqlite",
            len(self._tier1_mirror),
        )

    # ------------------------------------------------------------------
    # Public lookup / store API for Tier 1 + Tier 2 (search_papers)
    # ------------------------------------------------------------------

    async def lookup_search(
        self,
        query: str,
        filters: dict[str, Any] | None,
        k: int,
        query_embedding: np.ndarray | None = None,
        *,
        level: str | None = None,
        corpus_version: int | None = None,
        embedder_id: str | None = None,
    ) -> tuple[Any | None, str, Tier2Match | None]:
        """Look up a ``search_papers`` payload across Tier 1 + Tier 2.

        Returns ``(payload, hit_tier, match)`` where ``hit_tier`` is one
        of ``"1"``, ``"2"``, or ``""`` (miss) and ``match`` is a
        :class:`Tier2Match` on a Tier-2 hit, ``None`` otherwise. The
        caller is responsible for incrementing
        ``arxmcp_cache_hits_total`` only on the terminating hit; this
        method increments ``arxmcp_cache_lookups_total`` for every tier
        consulted.

        ``query_embedding`` is OPTIONAL. If absent, only Tier 1 is
        consulted (Tier 2 needs the embedding). The handler caller
        should pass the embedding once it has computed it (i.e. after
        the Tier-1 miss, before the ANN call).

        ``level`` is the ``search_papers`` aggregation argument
        (``"theorem" | "section" | "paper"``). Threaded through to
        :func:`derive_tier1_key` so distinct levels do not collide.
        Tier 2 also uses ``level`` to disambiguate its scope
        fingerprint (the brief's "exact filter match" rule extends
        to all tool arguments that affect result shape).

        ``embedder_id`` names the embedder this request intends to use
        (issue #204); see :func:`server.query_encoder.embedder_identity`.
        It participates in BOTH tiers' keys.

        ``k`` is an EQUALITY axis for Tier 1 (it is in the key) and an
        ORDINAL axis for Tier 2 (an entry answers only when it was built
        for at least this many rows). A Tier-2 hit may therefore carry
        MORE rows than ``k`` — read ``match.cached_k`` and slice.
        """
        # Tier 1. F16 fix from the E08_S03 critique: use _safe_inc
        # for ALL counter increments rather than mixing inline
        # try/except + the helper; one helper is the single source
        # of truth for "metrics failure must not propagate".
        # notebook-retrieval-m2 F2: an optional per-call ``corpus_version``
        # override lets a fork-A notebook query salt the keys on the
        # NOTEBOOK's pinned version instead of the process-wide shared
        # version. ``None`` (the default, every non-notebook call) reduces
        # to ``self._corpus_version`` — byte-identical to pre-m2 (AC4).
        # Resolved ONCE so both tiers ask the same question (#337).
        resolved_corpus_version = (
            self._corpus_version if corpus_version is None else corpus_version
        )
        self._safe_inc(CACHE_LOOKUPS_COUNTER, TIER_1)
        try:
            tier1_key = derive_tier1_key(
                query, filters, k,
                resolved_corpus_version,
                level=level,
                embedder_id=embedder_id,
            )
            payload = await self._tier1_get(tier1_key)
            if payload is not None:
                self._safe_inc(CACHE_HITS_COUNTER, TIER_1)
                return payload, TIER_1, None
        except Exception:  # noqa: BLE001
            logger.exception("Tier-1 lookup failed; falling through")

        # Tier 2 (only if embedding provided).
        if query_embedding is None:
            return None, "", None
        self._safe_inc(CACHE_LOOKUPS_COUNTER, TIER_2)
        try:
            payload, match = await self._tier2_lookup(
                query_embedding, filters, k,
                level=level,
                corpus_version=resolved_corpus_version,
                embedder_id=embedder_id,
            )
            if payload is not None:
                self._safe_inc(CACHE_HITS_COUNTER, TIER_2)
                return payload, TIER_2, match
        except Exception:  # noqa: BLE001
            logger.exception("Tier-2 lookup failed; falling through")

        return None, "", None

    async def store_search(
        self,
        query: str,
        filters: dict[str, Any] | None,
        k: int,
        payload: Any,
        query_embedding: np.ndarray | None = None,
        *,
        level: str | None = None,
        corpus_version: int | None = None,
        embedder_id: str | None = None,
    ) -> None:
        """Store a ``search_papers`` payload in BOTH Tier 1 and (if
        the embedding is available) Tier 2.

        Caller passes the same ``query_embedding`` used at lookup
        time so Tier 2 can index it for future semantic hits. If
        the embedding is unavailable (e.g. early-Tier-1 hit path),
        Tier 2 stays cold.

        ``level`` MUST match the value passed to ``lookup_search``
        for the corresponding miss; otherwise the lookup-key and
        the store-key diverge and the entry is unreachable.

        ``embedder_id`` (issue #204) must name the embedder that
        ACTUALLY produced this payload's ranking — including the local
        fallback when a hosted provider was down. Passing the intended
        rather than the actual embedder is what would let a degraded
        ranking be re-served as undegraded.

        ``k`` is recorded on the Tier-2 entry so a later request for a
        LARGER ``k`` misses instead of being served this payload's
        shorter row list.
        """
        # m2 F2: per-call corpus_version override (notebook's version on a
        # fork-A call); None → shared version, byte-identical (AC4).
        # Resolved ONCE, outside the try, so the Tier-1 key salt, the
        # Tier-1 SQLite column and the Tier-2 fingerprint cannot drift
        # apart — #337 is what three independent resolutions of the same
        # value cost.
        resolved_corpus_version = (
            self._corpus_version if corpus_version is None else corpus_version
        )
        try:
            tier1_key = derive_tier1_key(
                query, filters, k,
                resolved_corpus_version,
                level=level,
                embedder_id=embedder_id,
            )
            await self._tier1_put(
                tier1_key, payload, corpus_version=resolved_corpus_version,
            )
        except Exception:  # noqa: BLE001
            logger.exception("Tier-1 store failed; cache stays cold")

        if query_embedding is not None:
            try:
                await self._tier2_put(
                    query_embedding, filters, k, payload,
                    level=level,
                    corpus_version=resolved_corpus_version,
                    embedder_id=embedder_id,
                )
            except Exception:  # noqa: BLE001
                logger.exception("Tier-2 store failed; cache stays cold")

    # F13 fix from the E08_S03 critique: brief specifies the API as
    # ``lookup(query, filters, k) -> Optional[payload]`` and
    # ``store(query, filters, k, payload)``. We expose those names
    # as aliases over ``lookup_search`` / ``store_search`` so a
    # downstream caller following the brief verbatim hits the right
    # method. The (lookup_rerank, store_rerank) Tier-3 surface keeps
    # its distinct name so a single-method ``lookup`` doesn't mix
    # the two semantically-distinct cache families.
    #
    # **Issue #337: these forward EVERY keyword the full methods take.**
    # They previously omitted ``corpus_version``, so a caller following
    # the documented API silently lost the per-call notebook override and
    # got shared-corpus keys — a wrong-corpus answer from an API whose
    # only sin was being the one the brief describes. An alias that
    # narrows its target's contract is worse than no alias: the omission
    # is invisible at the call site. Anything added to
    # ``lookup_search`` / ``store_search`` belongs here in the same
    # commit, and ``TestBriefSpecAliasParity`` fails if it is not.

    async def lookup(
        self,
        query: str,
        filters: dict[str, Any] | None,
        k: int,
        query_embedding: np.ndarray | None = None,
        *,
        level: str | None = None,
        corpus_version: int | None = None,
        embedder_id: str | None = None,
    ) -> tuple[Any | None, str]:
        """Brief-spec alias for :meth:`lookup_search`. See that method
        for details on the (Tier-1, Tier-2) lookup path.

        Returns the brief's ``(payload, hit_tier)`` pair — the
        :class:`Tier2Match` provenance record added for issue #204 is
        dropped here, since the brief pins this surface's shape. A
        caller that renders the approximate-hit marker must use
        :meth:`lookup_search` directly. Every OTHER argument is
        forwarded verbatim (#337).
        """
        payload, hit_tier, _match = await self.lookup_search(
            query=query, filters=filters, k=k,
            query_embedding=query_embedding, level=level,
            corpus_version=corpus_version,
            embedder_id=embedder_id,
        )
        return payload, hit_tier

    async def store(
        self,
        query: str,
        filters: dict[str, Any] | None,
        k: int,
        payload: Any,
        query_embedding: np.ndarray | None = None,
        *,
        level: str | None = None,
        corpus_version: int | None = None,
        embedder_id: str | None = None,
    ) -> None:
        """Brief-spec alias for :meth:`store_search`. Forwards every
        argument verbatim (#337)."""
        return await self.store_search(
            query=query, filters=filters, k=k, payload=payload,
            query_embedding=query_embedding, level=level,
            corpus_version=corpus_version,
            embedder_id=embedder_id,
        )

    # ------------------------------------------------------------------
    # Tier 1 internals
    # ------------------------------------------------------------------

    async def _tier1_get(self, key: str) -> Any | None:
        # F2 fix from the E08_S03 critique: enforce TTL on the
        # in-process mirror, not just at the SQLite layer. The mirror
        # entry is now ``(payload, expires_at)`` — expired hits are
        # lazy-evicted and treated as misses, so the documented
        # 1-hour TTL applies to mirror hits as well.
        now = time.time()
        async with self._tier1_lock:
            mirror_entry = self._tier1_mirror.get(key)
            if mirror_entry is not None:
                payload, expires_at = mirror_entry
                if expires_at < now:
                    # TTL expired — evict from mirror; fall through to
                    # SQLite (which will also lazy-evict its row).
                    self._tier1_mirror.pop(key, None)
                    self._safe_inc(CACHE_EVICTIONS_COUNTER, TIER_1)
                else:
                    # LRU bump.
                    self._tier1_mirror.move_to_end(key)
                    return payload
        # Mirror miss → consult SQLite (which also evicts on TTL).
        row = await self._tier1_store.get_with_expiry(key)
        if row is None:
            return None
        blob, expires_at = row
        try:
            payload = json.loads(blob.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            logger.warning(
                "RetrievalCache: dropping malformed tier-1 row %s "
                "from sqlite (deserialization failed)", key[:16] + "...",
            )
            return None
        # Re-populate the mirror under the ROW's expiry, not a fresh
        # window. Issue #338: this used to write ``now +
        # TIER1_TTL_SECONDS``, described as "a small approximation …
        # worst case: served slightly past TTL". The worst case is not
        # slight — it is 2x. A row written at T and first read from
        # SQLite at T+3599 was re-cached until T+7199, and every
        # subsequent mirror-miss read renewed it again, so a
        # steadily-read key could outlive its TTL indefinitely. The
        # mirror is a MIRROR: it inherits the row's remaining life and
        # never mints new life for it.
        async with self._tier1_lock:
            self._tier1_mirror[key] = (payload, expires_at)
            self._tier1_mirror.move_to_end(key)
        return payload

    async def _tier1_put(
        self, key: str, payload: Any, *, corpus_version: int,
    ) -> None:
        """Write one Tier-1 row.

        ``corpus_version`` MUST be the version the ``key`` was salted
        with — the notebook's on a per-call routed write, the shared one
        otherwise. Issue #337(c): this used to write
        ``self._corpus_version`` unconditionally, so a notebook-routed
        row's column and its key hash described DIFFERENT corpora, and
        the column stopped being usable as an operational filter for the
        thing it names.

        **What this does and does not fix.** It makes the column honest:
        every row now says which corpus version its key was derived
        from, so ``purge_other_corpus_versions`` retains rows that are
        actually reachable at the version it keeps, and drops ones whose
        salt is genuinely superseded. It does NOT make that purge
        notebook-aware — the method keeps ONE version, and a
        notebook-keyed row salted on the notebook's version is not equal
        to the shared version, so a shared-corpus rebind still deletes
        it. That is a cache MISS, not a wrong answer (the row was
        reachable; now it is recomputed), which is the failure direction
        this layer is allowed to take. Making the purge keep a SET of
        live versions is the real remedy and is out of #337's scope —
        notebook tables are opened lazily, so their versions are not
        known at rebind time.
        """
        # Serialize once for SQLite.
        try:
            blob = json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")
        except (TypeError, ValueError):
            logger.warning("Tier-1 payload not JSON-serializable; skipping")
            CACHE_PAYLOAD_SKIPS_COUNTER.labels(
                reason="non_serializable",
            ).inc()
            return
        evicted = await self._tier1_store.put(
            key,
            blob,
            ttl_seconds=TIER1_TTL_SECONDS,
            corpus_version=corpus_version,
        )
        if evicted:
            self._safe_inc(CACHE_EVICTIONS_COUNTER, TIER_1, evicted)
        # Mirror update (post-SQLite write so a SQLite I/O error
        # keeps the mirror out of the success state — i.e. the mirror
        # never holds an entry the durable store does not have).
        # F2 fix: store ``(payload, expires_at)`` rather than the bare
        # payload so the mirror enforces TTL on read.
        expires_at = time.time() + TIER1_TTL_SECONDS
        async with self._tier1_lock:
            self._tier1_mirror[key] = (payload, expires_at)
            self._tier1_mirror.move_to_end(key)
            # Bound the in-process mirror at the same cap as SQLite.
            while len(self._tier1_mirror) > TIER1_MIRROR_CAP:
                self._tier1_mirror.popitem(last=False)
                # The eviction is already counted at the SQLite layer;
                # don't double-count.

    # ------------------------------------------------------------------
    # Tier 2 internals
    # ------------------------------------------------------------------

    def _ensure_faiss_index(self) -> Any:
        """Lazily build the FAISS IndexFlatIP. Imported here so a
        missing faiss-cpu install fails at the cache's first-use
        point, with a clear message."""
        if self._tier2_index is None:
            try:
                import faiss  # noqa: PLC0415
            except ImportError as exc:
                raise RuntimeError(
                    "faiss-cpu is required for Tier-2 cache; install via "
                    "pip install faiss-cpu>=1.7"
                ) from exc
            self._tier2_index = faiss.IndexFlatIP(EMBEDDING_DIM)
        return self._tier2_index

    async def _tier2_lookup(
        self,
        query_embedding: np.ndarray,
        filters: dict[str, Any] | None,
        k: int,
        *,
        level: str | None = None,
        corpus_version: int,
        embedder_id: str | None = None,
    ) -> tuple[Any | None, Tier2Match | None]:
        """Search the FAISS index for a ≥ 0.97 cosine match with the
        same scope fingerprint, a large-enough ``k``, and an unexpired
        TTL.

        F9 fix from the E08_S03 critique: search the top-K nearest
        neighbors (not just top-1) and iterate until one matches EVERY
        acceptance test. The pre-fix version returned a miss when the
        top-1 failed one of them, even when a valid second-nearest
        neighbor existed at cosine ≥ 0.97.

        Issue #204 adds the ``k`` test to that iteration. It is ordinal,
        not equality: an entry built for ``entry.k`` rows can answer any
        request for at most that many (the caller slices) and NO request
        for more, because the missing rows were never retrieved. A
        too-small entry is skipped like a scope mismatch — never
        returned truncated.

        Returns ``(payload, match)`` on a hit; ``(None, None)`` on a
        miss or cold-start (empty ring buffer)."""
        target_scope_fp = _tier2_scope_fingerprint(
            filters, level=level, corpus_version=corpus_version,
            embedder_id=embedder_id,
        )
        now = time.time()

        async with self._tier2_lock:
            if not self._tier2_buffer:
                # Cold start no-op per the brief.
                return None, None
            index = self._ensure_faiss_index()
            if index.ntotal == 0:
                return None, None
            # Normalize for safety even though BGE-M3 returns
            # L2-normalized vectors.
            qv = np.ascontiguousarray(query_embedding.reshape(1, -1).astype(np.float32))
            # The slot key of THIS query's own embedding. Comparing slot
            # keys is how we classify a hit as exact vs approximate
            # (issue #204) — byte equality, no float epsilon.
            self_key = hashlib.sha256(
                np.ascontiguousarray(
                    query_embedding.reshape(-1).astype(np.float32)
                ).tobytes()
            ).hexdigest()
            # The FAISS IndexFlatIP returns inner-product scores;
            # for L2-normalized vectors that equals cosine. We ask
            # for top-K rather than top-1 so a wrong-filter top-1
            # does not mask a right-filter top-2.
            top_k = min(8, index.ntotal)
            scores, indices = index.search(qv, top_k)
            for rank in range(top_k):
                cand_score = float(scores[0][rank])
                cand_idx = int(indices[0][rank])
                if cand_idx < 0:
                    continue
                if cand_score < TIER2_COSINE_THRESHOLD:
                    # FAISS returns scores in DESCENDING order for
                    # IndexFlatIP, so once we drop below threshold no
                    # later candidate will exceed it.
                    return None, None
                cand_key = self._tier2_keys_in_index[cand_idx]
                entry = self._tier2_buffer.get(cand_key)
                if entry is None:
                    # Index drift — should not happen but guard.
                    continue
                if entry.scope_fp != target_scope_fp:
                    continue
                if entry.k < k:
                    # Issue #204: this entry cannot answer a request for
                    # more rows than it was built for. Keep scanning —
                    # a farther neighbour may have been built wider.
                    continue
                if entry.expires_at < now:
                    # Lazy eviction — drop from buffer.
                    self._tier2_buffer.pop(cand_key, None)
                    self._safe_inc(CACHE_EVICTIONS_COUNTER, TIER_2)
                    continue
                # Hit. 1%-sample log per the brief.
                if random.random() < TIER2_HIT_LOG_SAMPLE_RATE:
                    logger.info(
                        "tier2_hit_sample cosine=%.4f scope_fp=%s "
                        "cached_k=%d requested_k=%d exact=%s",
                        cand_score, entry.scope_fp, entry.k, k,
                        cand_key == self_key,
                    )
                return entry.payload, Tier2Match(
                    cosine=cand_score,
                    exact_embedding=(cand_key == self_key),
                    cached_k=entry.k,
                )
            return None, None

    async def _tier2_put(
        self,
        query_embedding: np.ndarray,
        filters: dict[str, Any] | None,
        k: int,
        payload: Any,
        *,
        level: str | None = None,
        corpus_version: int,
        embedder_id: str | None = None,
    ) -> None:
        """Append a query embedding to the ring buffer and rebuild
        the FAISS index. On overflow, evict the oldest entry.

        Embedding key is the SHA-256 of the embedding bytes — so an
        identical query embedding overwrites the previous slot
        (deduplicates).

        **The slot key is the embedding alone**, so one slot holds one
        payload per embedding. Two calls with the same embedding but
        different scopes therefore overwrite rather than coexist: the
        loser's scope fingerprint no longer matches, and it misses
        cleanly (issue #204 — a miss, never a cross-scope serve). The
        same is true of ``k``: a narrower re-store shrinks what the slot
        can answer, which is correct-by-construction rather than a
        silent truncation.
        """
        emb = np.ascontiguousarray(query_embedding.reshape(-1).astype(np.float32))
        # The brief uses the embedding as the "centroid" — we key the
        # ring buffer slot by its hash so identical embeddings dedup.
        key = hashlib.sha256(emb.tobytes()).hexdigest()
        entry = _Tier2Entry(
            embedding=emb,
            scope_fp=_tier2_scope_fingerprint(
                filters, level=level, corpus_version=corpus_version,
                embedder_id=embedder_id,
            ),
            k=k,
            payload=payload,
            expires_at=time.time() + TIER2_TTL_SECONDS,
        )
        async with self._tier2_lock:
            evict_count = 0
            if key in self._tier2_buffer:
                # Update in place (same key).
                self._tier2_buffer[key] = entry
                self._tier2_buffer.move_to_end(key)
            else:
                self._tier2_buffer[key] = entry
                # Overflow — evict oldest.
                while len(self._tier2_buffer) > TIER2_RING_CAPACITY:
                    self._tier2_buffer.popitem(last=False)
                    evict_count += 1
            if evict_count:
                self._safe_inc(CACHE_EVICTIONS_COUNTER, TIER_2, evict_count)
            # Rebuild the FAISS index from scratch — O(n) at n≤1000,
            # dim=1024 is sub-millisecond. Simpler than incremental
            # remove (which IndexFlatIP doesn't support directly).
            self._rebuild_tier2_index()

    def _rebuild_tier2_index(self) -> None:
        """Rebuild the FAISS index from the current ring buffer.

        Holds: caller MUST hold ``self._tier2_lock``."""
        index = self._ensure_faiss_index()
        index.reset()
        self._tier2_keys_in_index.clear()
        if not self._tier2_buffer:
            return
        vecs = np.vstack(
            [entry.embedding.reshape(1, -1) for entry in self._tier2_buffer.values()]
        )
        index.add(vecs)
        self._tier2_keys_in_index.extend(self._tier2_buffer.keys())

    # ------------------------------------------------------------------
    # Tier 3 — rerank-set memo
    # ------------------------------------------------------------------

    async def lookup_rerank(
        self,
        query_embedding: np.ndarray,
        candidates: Sequence[tuple[str, float]],
    ) -> Any | None:
        """Look up a Tier-3 rerank-set memo. Returns the cached
        ranked candidate list or ``None`` on a miss.

        The cache key is computed via
        :func:`server.retrieval.rerank._build_singleflight_key` —
        the SAME key the singleflight uses, so a Tier-3 hit means
        the EXACT (query_embedding, candidate_set, model) triple
        was reranked recently.
        """
        # F16 fix from the E08_S03 critique: use _safe_inc uniformly.
        self._safe_inc(CACHE_LOOKUPS_COUNTER, TIER_3)
        try:
            from server.retrieval.rerank import _build_singleflight_key

            key = _build_singleflight_key(query_embedding, candidates)
        except Exception:  # noqa: BLE001
            logger.exception("Tier-3 key derivation failed")
            return None

        async with self._tier3_lock:
            entry = self._tier3_lru.get(key)
            if entry is None:
                return None
            payload, expires_at = entry
            if expires_at < time.time():
                self._tier3_lru.pop(key, None)
                self._safe_inc(CACHE_EVICTIONS_COUNTER, TIER_3)
                return None
            self._tier3_lru.move_to_end(key)

        self._safe_inc(CACHE_HITS_COUNTER, TIER_3)
        return payload

    async def store_rerank(
        self,
        query_embedding: np.ndarray,
        candidates: Sequence[tuple[str, float]],
        payload: Any,
    ) -> None:
        """Store a Tier-3 rerank-set memo entry."""
        try:
            from server.retrieval.rerank import _build_singleflight_key

            key = _build_singleflight_key(query_embedding, candidates)
        except Exception:  # noqa: BLE001
            logger.exception("Tier-3 key derivation failed; skipping store")
            return

        async with self._tier3_lock:
            self._tier3_lru[key] = (payload, time.time() + TIER3_TTL_SECONDS)
            self._tier3_lru.move_to_end(key)
            evict_count = 0
            while len(self._tier3_lru) > TIER3_LRU_CAPACITY:
                self._tier3_lru.popitem(last=False)
                evict_count += 1
            if evict_count:
                self._safe_inc(CACHE_EVICTIONS_COUNTER, TIER_3, evict_count)

    # ------------------------------------------------------------------
    # Byte-usage gauges (read by server.metrics.refresh_cache_metrics)
    # ------------------------------------------------------------------

    def tier1_bytes_used(self) -> int:
        """Approximate Tier-1 in-process mirror byte usage."""
        # Tier-1 mirror only — SQLite-on-disk bytes are visible via
        # ``ls -la`` and are not reported in this gauge.
        # Mirror entry shape (post-F2 fix): ``(payload, expires_at)``.
        total = 0
        for payload, _expires_at in self._tier1_mirror.values():
            total += _approx_payload_bytes(payload)
        return total

    def tier2_bytes_used(self) -> int:
        """Approximate Tier-2 ring-buffer + FAISS index byte usage."""
        # Embedding bytes (deque) + payload bytes.
        total = 0
        for entry in self._tier2_buffer.values():
            total += entry.embedding.nbytes
            total += _approx_payload_bytes(entry.payload)
        return total

    def tier3_bytes_used(self) -> int:
        """Approximate Tier-3 LRU byte usage."""
        total = 0
        for payload, _expires in self._tier3_lru.values():
            total += _approx_payload_bytes(payload)
        return total

    # ------------------------------------------------------------------
    # Stats accessor (consumed by server/routes/debug.py)
    # ------------------------------------------------------------------

    def stats(self) -> dict[str, dict[str, int]]:
        """Return the per-tier stats dict for the
        ``GET /debug/cache-stats`` endpoint.

        Each tier maps to a dict with ``lookups_total``, ``hits_total``,
        ``evictions_total``, ``bytes_used``. Counter values come from
        the Prometheus registry (so the JSON view and the ``/metrics``
        view never drift); bytes come from this object's accessors.
        """
        return {
            "tier1": _tier_stats(TIER_1, self.tier1_bytes_used()),
            "tier2": _tier_stats(TIER_2, self.tier2_bytes_used()),
            "tier3": _tier_stats(TIER_3, self.tier3_bytes_used()),
        }

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _safe_inc(counter, tier_label: str, amount: int = 1) -> None:
        """Increment a Prometheus counter without ever raising. A
        metrics-library failure is logged and swallowed — the cache
        is performance, not correctness."""
        try:
            counter.labels(tier=tier_label).inc(amount)
        except Exception:  # noqa: BLE001
            logger.debug("metrics inc failed", exc_info=True)


def _tier_stats(tier_label: str, bytes_used: int) -> dict[str, int]:
    """Read the per-tier counter values from the Prometheus registry
    so the ``/debug/cache-stats`` view never drifts from
    ``/metrics``."""
    try:
        lookups = int(CACHE_LOOKUPS_COUNTER.labels(tier=tier_label)._value.get())
        hits = int(CACHE_HITS_COUNTER.labels(tier=tier_label)._value.get())
        evictions = int(CACHE_EVICTIONS_COUNTER.labels(tier=tier_label)._value.get())
    except Exception:  # noqa: BLE001
        logger.debug("metrics read failed", exc_info=True)
        lookups = hits = evictions = 0
    return {
        "lookups_total": lookups,
        "hits_total": hits,
        "evictions_total": evictions,
        "bytes_used": bytes_used,
    }


# ---------------------------------------------------------------------------
# Module-level singleton + test reset
# ---------------------------------------------------------------------------

_CACHE_SINGLETON: RetrievalCache | None = None


def get_cache() -> RetrievalCache | None:
    """Return the process-wide cache singleton.

    Returns ``None`` when the cache has not been initialized yet
    (server still in startup, or test that did not call
    :func:`set_cache`). Handlers must treat ``None`` as "no cache
    available" — fall through to the underlying pipeline.
    """
    return _CACHE_SINGLETON


def set_cache(cache: RetrievalCache | None) -> None:
    """Set the process-wide cache singleton. Called by
    :meth:`server.resources.Resources.startup` AND from
    :func:`reset_cache_for_tests`."""
    global _CACHE_SINGLETON
    _CACHE_SINGLETON = cache


def reset_cache_for_tests() -> None:
    """Test hook — drop the singleton reference (does NOT close the
    SQLite store; tests are responsible for cleanup via tmp_path).

    Use in autouse fixtures alongside
    :func:`server.metrics.reset_cache_metrics_for_tests` to start
    each test with a clean cache state."""
    set_cache(None)


__all__ = [
    "EMBEDDING_DIM",
    "RetrievalCache",
    "TIER2_COSINE_THRESHOLD",
    "TIER2_HIT_LOG_SAMPLE_RATE",
    "TIER2_RING_CAPACITY",
    "TIER2_TTL_SECONDS",
    "TIER3_LRU_CAPACITY",
    "TIER3_TTL_SECONDS",
    "Tier2Match",
    "get_cache",
    "reset_cache_for_tests",
    "set_cache",
]
