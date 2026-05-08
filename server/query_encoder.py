"""Singleflight wrapper for BGE-M3 query encoding (E03_S03).

The MCP server (E06) encodes each incoming ``search_papers`` query string
through ``BAAI/bge-m3`` before running ANN against the LanceDB table. Under
concurrent load — for example, when multiple sub-agents in a multi-agent
proof pipeline submit queries within the same 100ms window — naive
per-request encoding would submit redundant forward passes to the model.
This module coalesces those calls: if multiple concurrent calls to
:func:`encode_query` arrive with the same (canonicalized) query string
while another encode is in flight (or within ``DEDUP_WINDOW_S`` after its
completion), only one BGE-M3 forward pass is issued and the result is
shared.

**GIL release rationale (verbatim from the AC).** BGE-M3 forward pass
releases the GIL inside PyTorch's C++ backend; ThreadPoolExecutor is
therefore safe for concurrent callers. The single-worker executor is
NOT used to parallelize forward passes (BGE-M3 is not safe for
concurrent calls against the same model instance). It off-loads the
blocking C++ kernel call from the asyncio event-loop thread so the loop
stays responsive to other awaitable work. ``torch.no_grad()`` controls
gradient tracking and ``model.eval()`` controls dropout; neither
controls GIL release. PyTorch's GIL release is documented in the C++
Extension docs (`torch.utils.cpp_extension`) and is implemented via
``pybind11::gil_scoped_release`` inside ATen operators.

**Eviction model (D8 of research-synthesis.md).** The dedup is
*completion-based*: 100ms after the encode completes successfully, the
dict entry is evicted via ``loop.call_later``. While the encode is in
flight, ANY concurrent caller shares the future regardless of how long
the call has been running (D9). Errors evict immediately so a retry
does not inherit a stale exception (D10).

**Cancellation (D11).** ``loop.run_in_executor`` futures are not
cancellable — the executor thread continues running even if the calling
task is cancelled. Other waiters still receive the result.

**BP1 byte-stability (07-multi-agent-caching.md).** The encoded vector
is byte-stable across runs because ``model.eval()`` disables XLM-RoBERTa
dropout and the encode chain (CLS pool + explicit ``F.normalize`` +
``np.float32``) matches ``ingest.embedder._encode_batch`` exactly. Query
text is canonicalized as ``unicodedata.normalize("NFC", query.strip())``
matching the Tier-1 cache rule from 07-multi-agent-caching.md.

**Threat 6 (08-security-observability-ops.md).** :data:`BGE_M3_COMMIT_SHA`
is imported from :mod:`ingest.embedder` — never redefined here. A
regression test
(``tests/test_query_encoder.py::TestSingleSourceOfTruth``) scans both
``ingest/`` and ``server/`` to enforce this at lint time.
"""

from __future__ import annotations

import asyncio
import logging
import unicodedata
from concurrent.futures import ThreadPoolExecutor

# Re-import the embedder's lazy loaders + pinned identity. NEVER define a
# second model instance — that would double weight memory (~2.3 GB) and
# decouple the model-version discipline. The ``BGE_M3_COMMIT_SHA`` import
# is also load-bearing for the brief's "imports... not redefined" AC.
from ingest.embedder import (
    BGE_M3_COMMIT_SHA,
    EMBEDDING_DIM,
    MAX_TOKENS,
    _get_model,
    _get_tokenizer,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Module-level constants
# ---------------------------------------------------------------------------

# 100ms post-completion eviction window (D8). The brief says "Completed
# entries are evicted after 100ms"; this constant is the timer delay
# passed to ``loop.call_later`` after a successful encode. Errors evict
# immediately and bypass this delay (D10).
DEDUP_WINDOW_S = 0.1


# ---------------------------------------------------------------------------
# Module state — singleflight registry + observability counters
# ---------------------------------------------------------------------------

# Single-worker executor: serializes BGE-M3 forward passes (the model is
# not thread-safe for concurrent calls against the same instance). The
# asyncio event loop remains responsive while the executor thread is
# inside the C++ kernel (GIL released — see module docstring).
_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="bge-m3-encode")

# Per-process singleflight registry: canonical query text →
# ``asyncio.Future`` resolving to the L2-normalized 1024-dim vector.
# Touched only inside :func:`encode_query` (single-threaded asyncio
# event loop, no ``await`` between dict-check and dict-mutation, so no
# lock is required — D6).
_inflight: dict[str, asyncio.Future] = {}

# Observability hook for the future ``arxmcp_embed_singleflight_dedup_total``
# counter described in 06-mcp-server-design.md. Until a Prometheus client
# is wired in (deferred milestone), this module-level integer is the
# observable signal that singleflight coalesced a call.
SINGLEFLIGHT_DEDUP_COUNT = 0


# ---------------------------------------------------------------------------
# Query canonicalization
# ---------------------------------------------------------------------------


def _canonicalize(query_text: str) -> str:
    """Return the singleflight-key form of ``query_text``.

    Two-step normalization (D4):

    1. ``query_text.strip()`` — matches the Tier-1 cache
       ``canonical_form(query)`` rule from
       ``07-multi-agent-caching.md``: "do NOT lowercase, do NOT strip
       punctuation. ``\\\\'etale`` and ``étale`` produce different
       lexical matches."
    2. ``unicodedata.normalize("NFC", ...)`` — BP1 byte-stability across
       hosts; matches ``ingest.embedder._build_embed_input``.

    The order matters: strip first to remove any leading/trailing
    combining characters that would otherwise normalize to a no-op
    on the inside.
    """
    return unicodedata.normalize("NFC", query_text.strip())


# ---------------------------------------------------------------------------
# Sync encode helper — runs inside the executor thread
# ---------------------------------------------------------------------------


def _encode_query_sync(query_text: str) -> object:
    """Encode a single query string to a 1024-dim L2-normalized vector.

    Runs inside the ``ThreadPoolExecutor`` worker (D7). Calls
    :func:`ingest.embedder._get_tokenizer` and
    :func:`ingest.embedder._get_model` — same lazy loaders as the
    ingestion-time embedder, so the model + tokenizer + revision pin
    are guaranteed identical (D2).

    The encode chain MUST match
    :func:`ingest.embedder._encode_batch` exactly — CLS-pool + explicit
    :func:`torch.nn.functional.normalize` (BGE-M3 / raw ``AutoModel``
    does not apply L2-normalization by default) + ``.cpu().numpy()
    .astype(np.float32)``. Any deviation lands query vectors in a
    different embedding space than the indexed chunks and breaks the
    integration-test cosine-similarity AC (D3).
    """
    import numpy as np  # noqa: PLC0415
    import torch  # noqa: PLC0415
    import torch.nn.functional as F  # noqa: PLC0415

    tokenizer = _get_tokenizer()
    model = _get_model()
    encoded = tokenizer(
        [query_text],
        padding=True,
        truncation=True,
        max_length=MAX_TOKENS,
        return_tensors="pt",
    )
    with torch.no_grad():
        output = model(**encoded)
        # CLS-pool the [batch, seq, hidden] tensor down to [batch, hidden].
        embeddings = output.last_hidden_state[:, 0, :]
        # Explicit L2 normalization — raw ``AutoModel`` does not apply it.
        embeddings = F.normalize(embeddings, p=2, dim=-1)
    # Squeeze the singleton batch dim → shape (EMBEDDING_DIM,).
    return embeddings[0].cpu().numpy().astype(np.float32)


# ---------------------------------------------------------------------------
# Public async API
# ---------------------------------------------------------------------------


async def encode_query(query_text: str) -> object:
    """Return the L2-normalized BGE-M3 embedding of ``query_text``.

    Singleflight: if the canonicalized query is already in flight (or
    within ``DEDUP_WINDOW_S`` after its completion), this call awaits
    the same in-flight :class:`asyncio.Future` and increments
    :data:`SINGLEFLIGHT_DEDUP_COUNT`.

    Returns a fresh ``np.ndarray`` of shape ``(EMBEDDING_DIM,)`` and
    dtype ``np.float32`` — :func:`numpy.ndarray.copy` is called on the
    cached vector before returning (D12) so concurrent callers cannot
    affect each other through in-place mutation.

    The returned vector matches what the indexed chunks were embedded
    with: same model SHA, same CLS pool, same L2 normalization. Cosine
    similarity against indexed chunk vectors is therefore meaningful.
    """
    global SINGLEFLIGHT_DEDUP_COUNT

    key = _canonicalize(query_text)
    loop = asyncio.get_running_loop()

    # FAST PATH: an identical query is already in flight (or recently
    # completed and within the 100ms eviction window). Coalesce — no
    # new forward pass.
    inflight_fut = _inflight.get(key)
    if inflight_fut is not None:
        SINGLEFLIGHT_DEDUP_COUNT += 1
        result = await inflight_fut
        # Defensive copy (D12) — mutation by one waiter must not leak
        # to others.
        return result.copy()

    # SLOW PATH: submit to executor and store the returned future
    # directly in the dict. ``loop.run_in_executor`` returns an
    # ``asyncio.Future`` that wraps the underlying
    # ``concurrent.futures.Future``; sharing this single object across
    # all callers (slow and fast paths) means every caller awaits it
    # and the future's exception (if any) is always retrieved (no
    # "Future exception was never retrieved" warnings).
    #
    # Dict-mutation here is safe without a lock: between the .get()
    # above and this assignment there is no ``await``, so no other
    # coroutine can interleave (D6).
    fut = loop.run_in_executor(_executor, _encode_query_sync, key)
    _inflight[key] = fut

    try:
        result = await fut
    except BaseException:
        # D10: error path evicts IMMEDIATELY (no 100ms delay) so a
        # retry does not inherit a stale exception. The exception is
        # already on the future (set by run_in_executor); concurrent
        # FAST PATH waiters will see it on their own ``await``.
        _inflight.pop(key, None)
        raise

    # SUCCESS path: schedule eviction 100ms after completion (D8).
    # ``call_later`` runs the callback on the event loop after the
    # delay; ``.pop(key, None)`` tolerates a concurrent eviction.
    loop.call_later(DEDUP_WINDOW_S, _inflight.pop, key, None)

    return result.copy()


# ---------------------------------------------------------------------------
# Test/diagnostic helpers — NOT part of the public async API
# ---------------------------------------------------------------------------


def _reset_for_tests() -> None:
    """Clear all in-process state. Call from test fixtures only.

    Test isolation requires a known-clean ``_inflight`` registry and a
    zero ``SINGLEFLIGHT_DEDUP_COUNT`` between tests so cross-test
    contamination cannot mask a regression. Also handles the case where
    a prior test left an entry in the dict (e.g. via a cancelled
    cleanup callback that fires after the test ended).
    """
    global SINGLEFLIGHT_DEDUP_COUNT
    _inflight.clear()
    SINGLEFLIGHT_DEDUP_COUNT = 0


# Re-export for downstream readers that want the model identity without
# importing through ``ingest.embedder`` directly. Keeping the import
# alive at module level (not just inside the function) is what makes
# the brief's "imports BGE_M3_COMMIT_SHA from ingest/embedder.py" AC
# observable to static-analysis and import-time tests.
__all__ = [
    "BGE_M3_COMMIT_SHA",
    "DEDUP_WINDOW_S",
    "EMBEDDING_DIM",
    "MAX_TOKENS",
    "SINGLEFLIGHT_DEDUP_COUNT",
    "encode_query",
]
