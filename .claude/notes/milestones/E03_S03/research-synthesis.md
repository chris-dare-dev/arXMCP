# E03_S03 Research Synthesis — Singleflight wrapper for query encoding

**Sources:** `research-brief-1.md` (Sonnet-A), `research-brief-2.md` (Sonnet-B)
**Status:** convergent on every load-bearing decision below.
**Written:** 2026-05-07

---

## Resolved decisions (both briefs agree)

### D1. `server/` already exists; only `query_encoder.py` is new

`server/__init__.py` and `server/README.md` already exist. No directory
to create. The milestone adds:
- `server/query_encoder.py` — the singleflight wrapper
- `tests/test_query_encoder.py` — the test suite

No `pyproject.toml` changes (torch + transformers + numpy already
shipped via E03_S01).

### D2. Reuse the embedder's lazy loaders — do NOT create a second model instance

```python
from ingest.embedder import (
    BGE_M3_COMMIT_SHA,    # single source of truth (Threat 6 + brief AC)
    EMBEDDING_DIM,        # 1024
    MAX_TOKENS,           # 512
    _get_model,           # lazy AutoModel; revision=SHA, trust_remote_code=False
    _get_tokenizer,       # lazy AutoTokenizer; same revision
)
```

The query encoder calls `_get_model()` / `_get_tokenizer()` inside the
sync helper that runs in the executor. Loading a second model instance
would double the ~2.3 GB weight memory and decouple the version
discipline.

### D3. The encode chain MUST match `_encode_batch` exactly

```python
with torch.no_grad():
    output = model(**encoded)
    embeddings = output.last_hidden_state[:, 0, :]        # CLS pool
    embeddings = F.normalize(embeddings, p=2, dim=-1)     # explicit L2
return embeddings.cpu().numpy().astype(np.float32)        # float32 + cpu
```

Any deviation from CLS pool / explicit `F.normalize(p=2, dim=-1)` /
`np.float32` breaks the AC: query vectors would land in a different
embedding space than the indexed chunks, killing cosine similarity.
Tokenizer call: `padding=True, truncation=True, max_length=MAX_TOKENS,
return_tensors="pt"` (matches embedder).

### D4. Query normalization: `query.strip()` then `unicodedata.normalize("NFC", ...)`

`07-multi-agent-caching.md` Tier-1 cache rule:

> "`canonical_form(query)` is `query.strip()` only — do not lowercase,
> do not strip punctuation. `\\'etale` and `étale` produce different
> lexical matches."

Plus NFC normalization for BP1 byte-stability across hosts (matches the
embedder's `_build_embed_input` discipline). The singleflight dict key
uses the post-NFC stripped string so the key matches what the
tokenizer sees.

### D5. `asyncio.get_running_loop()` — not deprecated `get_event_loop()`

Python 3.10+ deprecated `asyncio.get_event_loop()` outside running
loops. Project requires `>=3.11`. Inside `async def`,
`asyncio.get_running_loop()` is correct and raises `RuntimeError` if
called outside a loop (the right failure mode).

The 07-note's reference singleflight uses `get_event_loop()` — that
sample is stale; we use `get_running_loop()`.

### D6. Singleflight without an asyncio.Lock — single-threaded event loop is sufficient

Between `if key in self._inflight` and `self._inflight[key] = fut`, no
`await` occurs. The event loop is single-threaded, so no other
coroutine can interleave. No lock needed. The 06-note suggests
"asyncio.Lock keyed by query hash" but this is overly conservative; the
07-note's reference implementation uses no lock and is correct.

### D7. ThreadPoolExecutor(max_workers=1) is for OFF-LOADING, not parallelism

The brief's "1 worker" doesn't parallelize the forward pass — it
serializes BGE-M3 calls (BGE-M3 is not safe for concurrent forward
passes against the same instance). The PURPOSE of the executor is to
keep the asyncio event-loop thread responsive while the encode runs in
the C++ kernel (where PyTorch releases the GIL).

The required docstring sentence (verbatim from AC):
> "BGE-M3 forward pass releases the GIL inside PyTorch's C++ backend;
> ThreadPoolExecutor is therefore safe for concurrent callers."

Source for the GIL claim: PyTorch C++ Extension docs
(https://pytorch.org/docs/stable/notes/extending.html) — custom C++
operators use `pybind11::gil_scoped_release`; ATen's built-in
operators do the same internally. `torch.no_grad()` and `model.eval()`
do NOT control GIL release; they control gradient tracking and
dropout respectively.

### D8. Eviction semantics: completion-based with a 100ms post-completion delay

The brief contains internal tension:
- Description: "Completed entries are evicted after 100ms" → completion-based.
- AC: "a call arriving 101ms after the first is treated as a new request" → sounds first-arrival-based.

**Resolution: completion-based.** The `call_later(0.1, cleanup)`
fires 100ms AFTER `fut.set_result(...)`, not 100ms after the first
arrival. Rationale:
- An encode taking 200ms with a first-arrival timer would expire the
  in-flight key at t=100ms while the encode is still running, forcing
  a second forward pass (violating the 1-worker guarantee).
- Completion-based matches the 07-note reference (`finally: del`)
  with an added micro-cache window for late arrivals.

The AC's "101ms" reads as "101ms after completion."

### D9. In-flight dedup: unbounded duration

Any call that arrives while the key is in `_inflight` (in-flight or
within 100ms-post-completion window) shares the future. There is no
"window expired but encode still running" path because the key stays
in the dict until the cleanup callback fires (always after completion).

### D10. Error path: IMMEDIATE eviction, no 100ms delay

When encode raises:
1. `fut.set_exception(exc)` — propagates to all waiters
2. `self._inflight.pop(key, None)` — IMMEDIATE removal (no `call_later`)
3. The exception re-raises

A retry on the same key after a failure should NOT inherit the cached
exception. Asymmetric eviction: success → 100ms delay; error →
immediate.

### D11. Cancellation does NOT cancel the encode

`loop.run_in_executor` futures are not cancellable (the executor
thread continues running). If a caller's task is cancelled while
awaiting, other waiters still receive the result. Document this
clearly in the docstring.

### D12. Each waiter gets a `.copy()` of the numpy array

Multiple waiters share the same in-memory result. Returning the same
array object means a mutation by one caller affects all. Returning
`.copy()` per caller costs one memcpy of 4 KB (1024 × float32) —
negligible — and prevents a defensive-programming footgun.

### D13. Singleflight metric: emit `arxmcp_embed_singleflight_dedup_total`

Per `06-mcp-server-design.md`:
> `arxmcp_embed_singleflight_dedup_total   counter`

For E03_S03 (no Prometheus client yet), expose a module-level
`SINGLEFLIGHT_DEDUP_COUNT` integer that's incremented on every
coalesced call. A future metrics-wiring milestone wraps this in the
real counter. The variable existence + monotonic increment closes the
observability hook.

### D14. Single-source-of-truth scan test for `BGE_M3_COMMIT_SHA`

Mirrors `tests/test_chunker_ids.py::TestSingleVersionDefinition::test_v1_0_literal_count_in_ingest_package`
but scans both `ingest/*.py` AND `server/*.py` for the 40-char hex
literal `"5617a9f61b028005a4858fdac845db406aefb181"`. Asserts exactly
one occurrence (in `ingest/embedder.py`). Closes the redefinition
vector at lint time, not just at code-review time.

### D15. Test strategy: `asyncio.run()` wrapper, no pytest-asyncio

No existing test uses `pytest-asyncio`; it's not in
`pyproject.toml`'s dev deps. The pattern:

```python
def test_singleflight_dedup():
    asyncio.run(_async_test_body())
```

Stays consistent with the project's stdlib-only test discipline.

### D16. Integration test gated by `ARXMCP_RUN_REAL_BGE_M3=1`

Mirrors `tests/test_embedder.py:TestVectorContract`'s precedent: the
mock-everything 10-concurrent-calls test runs unconditionally; the
real-model cosine-similarity test is `pytest.skip`-gated so CI doesn't
download 2.3 GB on every run.

---

## Implementation skeleton (consolidated from both briefs)

```python
"""Singleflight wrapper for BGE-M3 query encoding (E03_S03).

BGE-M3 forward pass releases the GIL inside PyTorch's C++ backend;
ThreadPoolExecutor is therefore safe for concurrent callers.
"""

import asyncio
import unicodedata
from concurrent.futures import ThreadPoolExecutor

import numpy as np

from ingest.embedder import (
    BGE_M3_COMMIT_SHA,  # noqa: F401  re-exported intentionally
    EMBEDDING_DIM,
    MAX_TOKENS,
    _get_model,
    _get_tokenizer,
)

DEDUP_WINDOW_S = 0.1  # 100ms post-completion eviction
SINGLEFLIGHT_DEDUP_COUNT = 0  # observability hook (06-note metrics)

_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="bge-m3-encode")
_inflight: dict[str, asyncio.Future] = {}


def _canonicalize(query_text: str) -> str:
    return unicodedata.normalize("NFC", query_text.strip())


def _encode_query_sync(query_text: str) -> np.ndarray:
    import torch
    import torch.nn.functional as F

    tokenizer = _get_tokenizer()
    model = _get_model()
    encoded = tokenizer(
        [query_text],
        padding=True, truncation=True, max_length=MAX_TOKENS, return_tensors="pt",
    )
    with torch.no_grad():
        output = model(**encoded)
        embeddings = output.last_hidden_state[:, 0, :]
        embeddings = F.normalize(embeddings, p=2, dim=-1)
    return embeddings[0].cpu().numpy().astype(np.float32)


async def encode_query(query_text: str) -> np.ndarray:
    global SINGLEFLIGHT_DEDUP_COUNT
    key = _canonicalize(query_text)
    loop = asyncio.get_running_loop()

    if key in _inflight:
        SINGLEFLIGHT_DEDUP_COUNT += 1
        result = await _inflight[key]
        return np.asarray(result).copy()

    fut = loop.create_future()
    _inflight[key] = fut

    def _on_done(_):
        # Schedule eviction 100ms after completion (success path);
        # error path runs the immediate-evict branch above.
        loop.call_later(DEDUP_WINDOW_S, _inflight.pop, key, None)

    try:
        encoded = await loop.run_in_executor(_executor, _encode_query_sync, key)
        fut.set_result(encoded)
        fut.add_done_callback(_on_done)
        return encoded.copy()
    except BaseException as exc:
        fut.set_exception(exc)
        _inflight.pop(key, None)  # immediate eviction on error
        raise
```

(The skeleton is illustrative; the implementer may refactor for
clarity/locality. The DECISIONS above are the contract.)

---

## Open questions left to the implementer

- **Should the integration test scan return-array byte-identity, not
  just cosine ≥ 0.9999?** The brief AC says "≥ 0.9999" because float
  rounding under different batch sizes can drift slightly. Strict
  byte-identity would be a stronger BP1 claim but might fail spuriously.
  Recommendation: cosine ≥ 0.9999 as the brief says; document the
  rationale in the test docstring.

- **Should `SINGLEFLIGHT_DEDUP_COUNT` be reset between tests?** Yes —
  the test fixture should reset both `_inflight` (clear) and
  `SINGLEFLIGHT_DEDUP_COUNT` (reset to 0) before each test to avoid
  cross-test contamination. Add a pytest fixture (autouse) for this.

---

## External writes the implementation will require

| Path | Event | Notes |
|---|---|---|
| `server/query_encoder.py` | new file | primary deliverable |
| `tests/test_query_encoder.py` | new file | mock-based 10-concurrent test + scan test + env-gated integration test |
| `pyproject.toml` | UNCHANGED | torch/transformers/numpy already there |

No third-party API call. No model download (E03_S01 already populated
the HF cache; the env-gated integration test reuses it). No infra
mutation. No PR/push.
