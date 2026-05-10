# E03_S03 Research Brief 1 — Singleflight Query Encoder

**Milestone:** E03_S03 — `server/query_encoder.py` singleflight wrapper
**Status:** NEW | **Tier:** 0 | **Effort:** M
**Written:** 2026-05-07

---

## 1. In-Codebase Context

### Does `server/` exist?

Yes. `server/__init__.py` exists (empty body, one blank line). This milestone
adds the first real server module. No `server/query_encoder.py` exists yet.
No `pyproject.toml` changes are needed — `torch`, `transformers`, `numpy`, and
`safetensors` are already in `dependencies` (added for E03_S01).

### What `06-mcp-server-design.md` says about the server concurrency model

The design note is explicit and load-bearing:

> "**Singleflight pattern** on the embedder: when N concurrent agents ask the
> same query, only one in-flight `embed(query)` call happens. Implementation:
> Python `asyncio.Lock` keyed by query hash, with a `dict` of `Future`s."

And about resource caps:

> "**Bounded semaphores** in front of expensive resources:
> - Embedder: `max_concurrent_embeddings = 8`."

The `06` note uses `asyncio.Lock` language, but `07-multi-agent-caching.md`
shows the canonical reference implementation with **no lock** — only a
`dict[str, asyncio.Future]` check:

```python
class Singleflight:
    def __init__(self):
        self._inflight: dict[str, asyncio.Future] = {}

    async def do(self, key, fn):
        if key in self._inflight:
            return await self._inflight[key]
        fut = asyncio.get_event_loop().create_future()
        self._inflight[key] = fut
        try:
            result = await fn()
            fut.set_result(result)
            return result
        except Exception as e:
            fut.set_exception(e)
            raise
        finally:
            del self._inflight[key]
```

**Critical: this 07-note pattern has a race condition.** Because `asyncio` is
single-threaded within the event loop, the `if key in self._inflight` check
and the `self._inflight[key] = fut` assignment are effectively atomic (no
`await` between them). The pattern is safe for asyncio. However, the
`07` note uses `asyncio.get_event_loop()` which is **deprecated in Python 3.10+**.
See Section 3 below.

### The 07-note eviction model

The `07` note's singleflight deletes the key in `finally` — i.e., the moment
the encode completes. This is **completion-based eviction**, not 100ms-from-first-
arrival. The milestone brief says two different things:

1. "Completed entries are evicted after 100ms" — completion-based + 100ms delay.
2. AC: "a call arriving 101ms after the first is treated as a new request" —
   sounds first-arrival-based.

These are in tension. See Open Questions.

### What `07-multi-agent-caching.md` says about query normalization (BP1)

> "`canonical_form(query)` is `query.strip()` only — do **not** lowercase, do
> **not** strip punctuation. `\'etale` and `étale` produce different lexical
> matches."

This is the Tier-1 exact-query cache key rule. The singleflight key must use
the same `query.strip()` normalization — stripping leading/trailing whitespace
but preserving internal whitespace, case, and punctuation.

### The query embedding cache key from `07`:

> ```
> key = sha256(model_name + model_version + canonical_form(query))
> value = vector
> ttl = 1 hour
> store = in-process LRU (~10K entries)
> ```

The singleflight wrapper is the **deduplication layer** underneath this LRU
cache; they are complementary, not alternatives.

### What `08-security-observability-ops.md` says about Threat 6

> "Pin model commit SHAs in configuration (`BAAI/bge-m3@<sha>`), not just names."
> "Run model loads with `trust_remote_code=False` unless explicitly opted in."

And the metrics spec includes:

> `arxmcp_embed_singleflight_dedup_total    counter`

The query encoder must emit this counter when it coalesces a duplicate call.

### How `ingest/embedder.py` encodes a query

The load-bearing encoding path (lines 397–412):

```python
with torch.no_grad():
    output = model(**encoded)
    # BGE-M3 dense embedding: CLS token of last hidden state.
    embeddings = output.last_hidden_state[:, 0, :]
    # Explicit L2 normalization — raw AutoModel does not apply it.
    embeddings = F.normalize(embeddings, p=2, dim=-1)
return embeddings.cpu().numpy().astype(np.float32), truncated_count
```

The query encoder must use the **identical** pipeline: CLS pool, `F.normalize(p=2,
dim=-1)`, `.cpu().numpy().astype(np.float32)`. Any deviation breaks the
integration-test cosine similarity ≥ 0.9999 AC because query vectors would be
computed differently from chunk vectors in the LanceDB index.

The `_get_model()` and `_get_tokenizer()` functions in `ingest/embedder.py`
are already lazy-loaded and safe to call from `server/query_encoder.py` — no
re-implementation needed. `BGE_M3_COMMIT_SHA` is defined at
`ingest/embedder.py:112` as the single source of truth.

NFC normalization is applied in `_build_embed_input` (embedder line 328):
`unicodedata.normalize("NFC", combined)`. For a bare query string (no preamble),
the query encoder must apply `unicodedata.normalize("NFC", query_text)` before
tokenizing. This is required by BP1 byte-stability.

### `MAX_TOKENS = 512` (embedder line 128)

Query strings are typically shorter than chunk bodies (no preamble prefix), so
truncation at query time is unlikely but the tokenizer call must still use
`truncation=True, max_length=512`.

---

## 2. Prior Decisions and Lessons

### E03_S01: ARXMCP_RUN_REAL_BGE_M3=1 precedent

From `tests/test_embedder.py` docstring:
> "The model itself is mocked everywhere except in TestVectorContract's
> opt-in real-model test (skipped by default; flip the env var
> ARXMCP_RUN_REAL_BGE_M3=1 to exercise the actual ~2.3 GB weight load)."

The integration test ("two calls → cosine similarity ≥ 0.9999") **must** follow
this pattern. Gate it behind `ARXMCP_RUN_REAL_BGE_M3=1`. The 10-concurrent-calls
mock test runs unconditionally; the cosine-similarity integration test is skipped
unless the env var is set.

### E03_S02: `_paper_is_up_to_date` cache-invalidation discipline

E03_S02's `_paper_is_up_to_date` checks `sidecar.embedder_version == EMBEDDER_VERSION`
which encodes `BGE_M3_COMMIT_SHA[:8]`. If `BGE_M3_COMMIT_SHA` changes, in-process
caches in the query encoder become **stale without warning**. The singleflight
dict itself clears on process restart (it is in-process), so a SHA bump + server
restart is sufficient. But the optional Tier-1 LRU cache (from `07`) keyed by
`sha256(model_name + model_version + canonical_form(query))` already encodes
the model version, so cache invalidation on SHA bump is safe by construction —
if the server module does import `BGE_M3_COMMIT_SHA` from `ingest.embedder`
rather than redefining it.

### CHUNKER_VERSION single-source-of-truth pattern

From `tests/test_chunker_ids.py`:
> `TestSingleVersionDefinition::test_v1_0_literal_count_in_ingest_package`

This test scans all `.py` files under `ingest/` and asserts the string `"v1.0"`
appears exactly once (in `chunker_types.py`). An analogous test should scan
`ingest/` **and** `server/` to assert `BGE_M3_COMMIT_SHA`'s value literal
(the 40-char hex string `"5617a9f6..."`) appears only in `ingest/embedder.py`.
The `server/query_encoder.py` must import the constant, not re-define it.

### E03_S01 F11: avoid duplicate torch import

F11 (LOW, already fixed): `_get_model` had `import torch` twice. The fix
removed the redundant one. In `query_encoder.py`, all torch imports must
happen inside the `_encode_query_sync()` helper that runs in the executor
(lazy pattern, `noqa: PLC0415`), or at module level — not both.

---

## 3. External Sources

### PyTorch GIL Release Semantics

PyTorch releases the GIL during C++ kernel execution. The authoritative source
is the PyTorch developer wiki / C++ Extension docs. From PyTorch docs
(https://pytorch.org/docs/stable/notes/extending.html and the C++ extension
tutorial): "When the GIL is not required [...] you can release it temporarily
using `py::gil_scoped_release`." PyTorch's internal implementation of all
major ops (ATen operators) uses this mechanism. The practical implication:
once a forward pass enters the C++ backend (after Python dispatches `model(**input)`),
the GIL is released for the duration of the matrix multiplications and
activations. This is documented in the PyTorch contributor guide at
https://github.com/pytorch/pytorch/wiki/GIL and in the C++ extension docs.

**Recommended docstring text (verbatim from AC):**
> "BGE-M3 forward pass releases the GIL inside PyTorch's C++ backend;
> ThreadPoolExecutor is therefore safe for concurrent callers."

**Caveat for `torch.no_grad()` context:** `torch.no_grad()` reduces memory
usage and disables gradient tracking but does NOT affect GIL release. The GIL
release happens at the C++ level regardless. `model.eval()` disables dropout.
Both are required for BP1 byte-stability; neither is the GIL mechanism.

**Implication for ThreadPoolExecutor(max_workers=1):** A single-worker executor
means BGE-M3 calls are serialized (one at a time). The singleflight pattern means
at most one call is ever submitted. The GIL release benefit is felt by the asyncio
event loop thread, which remains responsive to other awaitable work while the
executor thread is inside the C++ kernel. This is the correct mental model.

### asyncio + ThreadPoolExecutor: `get_running_loop()` vs `get_event_loop()`

**`asyncio.get_event_loop()` is deprecated in Python 3.10+ when no event loop is
running.** Python 3.12 emits a `DeprecationWarning`; Python 3.14 will remove it.
The project uses Python ≥ 3.11 (`requires-python = ">=3.11"` in `pyproject.toml`).

**The correct call inside an `async def` function is `asyncio.get_running_loop()`**
(available since Python 3.7). It raises `RuntimeError` if called outside a
running event loop, which is the correct failure mode (the function is `async def`,
so it must be called from a running loop).

The `07-multi-agent-caching.md` reference implementation uses
`asyncio.get_event_loop().create_future()` — this is **stale**. The implementation
must use `asyncio.get_running_loop().create_future()`.

For submitting the encode task to the executor:
`loop.run_in_executor(executor, _encode_query_sync, query_text)` returns a
`concurrent.futures.Future` wrapped as an `asyncio.Future` via
`asyncio.wrap_future`. In practice, `loop.run_in_executor` returns an
`asyncio.Future` directly (the wrapping is internal), so awaiting it works.

**asyncio.Future vs concurrent.futures.Future:**
These are NOT interchangeable. The `_inflight` dict must store
`asyncio.Future` objects (created via `loop.create_future()`), not
`concurrent.futures.Future` (returned by `executor.submit()`). An
`asyncio.Future` can be awaited from the event loop; a
`concurrent.futures.Future` cannot be directly awaited. The bridge is
`loop.run_in_executor()` which returns an `asyncio.Future`-compatible
awaitable. When using `run_in_executor`, store the returned awaitable in the
singleflight dict, not the underlying `concurrent.futures.Future`.

### Go `singleflight` (groupcache) vs asyncio

The Go `singleflight.Do(key, fn)` pattern:
- First caller for `key` calls `fn()` and blocks.
- Subsequent callers with same `key` block on the same call.
- On completion, all callers receive the same result.
- The `key` is deleted from the in-flight map **immediately on completion**
  (or error) — no 100ms TTL.

**Go-vs-asyncio difference:** In Go, singleflight uses a mutex; in asyncio it
uses the single-threaded event loop's implicit non-preemptive concurrency. The
`if key in dict` / `dict[key] = fut` sequence is atomic in asyncio (no
`await` between them). No explicit lock is needed.

**The 100ms eviction TTL** is an **arXMCP-specific addition** not in the
canonical Go singleflight. Go singleflight evicts immediately on completion;
arXMCP keeps the completed result for 100ms to serve latecomers without a
re-encode. This means the dict stores **completed** futures after the encode
finishes, not just in-flight ones. Callers who `await` a completed Future get
the result immediately (no suspend). The `call_later(0.1, ...)` cleanup removes
the key after 100ms. This is a caching layer on top of singleflight, not pure
singleflight.

---

## Open Questions

**Q1: When does the 100ms timer start — first arrival or completion?**

The brief says "Completed entries are evicted after 100ms" (completion-based),
but AC says "a call arriving 101ms after the first is treated as a new request"
(first-arrival-based). These conflict when the encode itself takes >1ms.

If a forward pass takes 200ms on CPU:
- First-arrival-based: a call at t=101ms gets a new Future (encode starts again
  at t=101ms even while the first encode is still running at t=200ms). This
  means two concurrent forward passes — violating the "1 worker" guarantee.
- Completion-based: a call at t=101ms awaits the same in-flight Future, gets
  the result at ~t=200ms, and then can re-encode if a new call arrives after
  t=300ms (200ms completion + 100ms eviction).

**Recommendation: use completion-based eviction.** The 07-note singleflight
already deletes in `finally` (= immediate completion-based). Adding a 100ms
`call_later` delay after completion is the right interpretation. The AC's "101ms
after the first" should be read as "101ms after the encode *completes*", not
"101ms after the first call *arrives*". This interpretation is consistent with
both the brief's "completed entries are evicted after 100ms" language AND with
the 1-worker constraint (no concurrent forward passes).

**Q2: IN-FLIGHT dedup — should a call arriving mid-encode always share the result?**

Yes. The in-flight future is in the dict while encoding. Any call that arrives
before `finally:` pops the key will `await` the same future. This is pure
singleflight semantics and requires no special handling.

**Q3: Error propagation to waiters.**

When the encode raises, `fut.set_exception(e)` propagates to all waiters (they
get the same exception on `await`). The `finally` block removes the key
immediately (the `07` note's `del self._inflight[key]` in `finally`). Do NOT
add a 100ms `call_later` for error cases — the next call should retry
immediately after a failure.

**Q4: Singleflight key normalization.**

Use `query.strip()` only, matching the Tier-1 cache `canonical_form(query)`
rule from `07-multi-agent-caching.md`. Do NOT lowercase, do NOT strip internal
whitespace. `"Theorem 1"` and `"Theorem  1"` (extra space) are different keys.

**Q5: Integration test and real model.**

Gate the cosine-similarity integration test behind `ARXMCP_RUN_REAL_BGE_M3=1`,
matching E03_S01's `TestVectorContract` precedent exactly.

**Q6: BGE_M3_COMMIT_SHA single-source-of-truth test.**

The `test_chunker_ids.py::TestSingleVersionDefinition` pattern scans `ingest/`
only. A companion test should scan both `ingest/` AND `server/` for the SHA
literal and assert it appears exactly once (in `ingest/embedder.py`). This
prevents future implementers from hard-coding the SHA in `query_encoder.py`.

---

## External Writes the Implementation Will Require

1. **New file: `server/query_encoder.py`** — the primary deliverable. No
   `server/__init__.py` modification is needed (it is already present as an
   empty module; `query_encoder.py` is a sibling file).

2. **New file: `tests/test_query_encoder.py`** — test suite.

3. **No `pyproject.toml` changes.** All dependencies (`torch`, `transformers`,
   `numpy`, `safetensors`) are already in `dependencies` from E03_S01.
   `asyncio` and `concurrent.futures` are stdlib.

4. **No git push, no PR, no infra mutation, no third-party API calls.** This
   milestone is purely local source code.

5. **Optional: add a scan test to `tests/test_query_encoder.py`** (or to
   `tests/test_chunker_ids.py` extended scope) that asserts the 40-char
   `BGE_M3_COMMIT_SHA` hex literal appears exactly once across `ingest/` and
   `server/`. This is a new test but not a new file (can live in
   `test_query_encoder.py`).
