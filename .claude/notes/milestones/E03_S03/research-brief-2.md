# E03_S03 Research Brief 2 — Singleflight Query Encoder

**Milestone:** E03_S03 — `server/query_encoder.py` singleflight wrapper
**Status:** NEW | **Tier:** 0 | **Effort:** M
**Written:** 2026-05-07

---

## 1. In-Codebase Context

### `server/` directory status

`server/` exists with exactly two files: `README.md` and `__init__.py` (the
latter is a single blank line). No `server/query_encoder.py` exists. The
directory must NOT be created — it is already present. Only `query_encoder.py`
needs to be added as a new sibling file.

### Encoding pipeline — the exact path the query encoder must replicate

`ingest/embedder.py:_encode_batch` (lines 336–412) is the canonical encode path.
The load-bearing section is:

```python
with torch.no_grad():
    output = model(**encoded)
    embeddings = output.last_hidden_state[:, 0, :]
    # Explicit L2 normalization — raw AutoModel does not apply it.
    embeddings = F.normalize(embeddings, p=2, dim=-1)
return embeddings.cpu().numpy().astype(np.float32), truncated_count
```

The module docstring states: "Critical: raw `transformers.AutoModel` does NOT
apply L2 normalization by default — unlike `BGEM3FlagModel.encode()`." Any
deviation from CLS-pool + `F.normalize(p=2, dim=-1)` + `.cpu().numpy().astype(np.float32)`
breaks the cosine-similarity AC because query vectors live in a different space
from indexed chunk vectors. The query encoder must call this exact chain — it
cannot call a different normalization, skip normalization, or use `.float16`.

### Lazy loaders are reusable — do not redefine

`_get_model()` and `_get_tokenizer()` (embedder lines 247–303) are already
lazy-loaded module-level singletons. The query encoder imports and calls them
directly. No new model instance, no separate weight load. The docstring:
"Lazy-loaded so importing this module is cheap." That discipline must be
preserved — `server/query_encoder.py` must NOT call `AutoModel.from_pretrained`
or `AutoTokenizer.from_pretrained` itself.

### `BGE_M3_COMMIT_SHA` — single source of truth at embedder line 112

```python
BGE_M3_COMMIT_SHA = "5617a9f61b028005a4858fdac845db406aefb181"
```

The milestone brief: "imports `BGE_M3_COMMIT_SHA` from `ingest/embedder.py` —
not redefined." The `TestSingleVersionDefinition` test pattern in
`tests/test_chunker_ids.py` scans `ingest/` for the `"v1.0"` literal. An
analogous test should scan both `ingest/` AND `server/` for the 40-char hex
literal `"5617a9f6..."` and assert it appears exactly once (only in
`ingest/embedder.py`). This closes the stray-redefinition vector without
relying on reviewer discipline.

### NFC normalization is load-bearing for BP1

`_build_embed_input` (embedder line 311–328) applies
`unicodedata.normalize("NFC", combined)`. For a bare query (no preamble), the
query encoder must apply `unicodedata.normalize("NFC", query_text)` before
tokenizing. The `07-multi-agent-caching.md` Tier-1 cache rule:
"`canonical_form(query)` is `query.strip()` only — do **not** lowercase, do
**not** strip punctuation." These are additive: strip first, then NFC-normalize.

### The 06-note concurrency model is the spec

`06-mcp-server-design.md` under Concurrency model:
> "**Singleflight pattern** on the embedder: when N concurrent agents ask the
> same query, only one in-flight `embed(query)` call happens. Implementation:
> Python `asyncio.Lock` keyed by query hash, with a `dict` of `Future`s."

And from the same note, the metrics requirement:
> `arxmcp_embed_singleflight_dedup_total   counter`

The query encoder must increment this counter (or at minimum expose a module-level
counter) when it coalesces a duplicate call. The `06` note also specifies
`max_concurrent_embeddings = 8` via bounded semaphore — but the milestone brief
specifies `ThreadPoolExecutor(max_workers=1)`, which provides natural serialization
without a semaphore.

### The `07-note` reference implementation — and its deprecated API call

`07-multi-agent-caching.md` contains the canonical singleflight skeleton using
`asyncio.get_event_loop().create_future()`. This call is **deprecated in
Python ≥ 3.10** (the project requires `>=3.11`). The implementation must use
`asyncio.get_running_loop()` instead. The `finally: del self._inflight[key]`
pattern in the 07 note produces immediate-completion eviction. The milestone
brief adds a 100ms post-completion delay via `call_later(0.1, ...)`. That
delay is the only design addition beyond the reference skeleton.

---

## 2. Prior Decisions and Lessons

### E03_S01: lazy loaders and the torch-import discipline

E03_S01 introduced `_get_model` / `_get_tokenizer` as lazy loaders and fixed
F11 (LOW): duplicate `import torch` inside `_get_model` was removed. The query
encoder must follow the same discipline: torch imports happen inside the sync
helper that runs in the executor (`noqa: PLC0415`) or at module level — not both.

### E03_S02: "verify the artifact, not the audit trail"

The E03_S02 F1 CRITICAL: `_paper_is_up_to_date` trusted the sidecar JSON
without verifying `embeddings.npz` exists. Fix: add `if not npz_path.exists(): return False`.
The lesson for E03_S03: the in-process cache (the `_inflight` dict) stores an
`asyncio.Future`. When a caller dequeues a completed Future, there is no risk of
serving a stale wrong-shaped vector — `asyncio.Future.result()` raises if the
future faulted, and returns the exact array that was set. However: callers that
copy the returned numpy array (vs. holding the same object reference) are correct
to do so, since numpy arrays are mutable. The implementer should decide whether
to return the same array object (callers must not mutate it) or a `.copy()`.

### `CHUNKER_VERSION` single-source-of-truth pattern (test_chunker_ids.py)

`TestSingleVersionDefinition.test_v1_0_literal_count_in_ingest_package` scans
only `ingest/`. For E03_S03 the analogous guard scans `ingest/` AND `server/`
for the hex literal `"5617a9f61b028005a4858fdac845db406aefb181"` and asserts
exactly one occurrence. A plain `import` statement in `query_encoder.py` is
sufficient for correctness; the literal-count test closes the enforcement door.

### The test precedent: mock model, env-gated integration test

From `tests/test_embedder.py`:
> "The model itself is mocked everywhere except in `TestVectorContract`'s
> opt-in real-model test (skipped by default; flip the env var
> `ARXMCP_RUN_REAL_BGE_M3=1` to exercise the actual ~2.3 GB weight load)."

The 10-concurrent-calls mock test (the primary AC) runs unconditionally. The
cosine-similarity integration test is skipped unless `ARXMCP_RUN_REAL_BGE_M3=1`
is set. No deviation from this precedent.

### asyncio test strategy: `asyncio.run()` in a synchronous test, no pytest-asyncio

No existing test uses `pytest-asyncio` or async test functions. The project does
not have `pytest-asyncio` in `pyproject.toml`'s `dev` dependencies. The correct
pattern for testing async code in this codebase is:

```python
import asyncio

def test_singleflight_dedup():
    asyncio.run(_async_test_body())
```

Adding `pytest-asyncio` is a dependency decision that would require updating
`pyproject.toml`. Use `asyncio.run()` instead — it is stdlib, requires no
configuration, and matches the project's zero-extra-test-dep discipline.

---

## 3. External Sources

### PyTorch GIL release — canonical reference

PyTorch releases the GIL during C++ kernel execution via `pybind11::gil_scoped_release`
(or its ATen equivalent). The authoritative pointer is the PyTorch C++ Extension
documentation at https://pytorch.org/docs/stable/notes/extending.html, which
states that custom C++ operators should call `pybind11::gil_scoped_release` to
release the GIL. The practical implication: once `model(**encoded)` dispatches
into the ATen dispatcher (after Python-side tokenizer work), the GIL is released
for the duration of matrix multiplications and activations. A `ThreadPoolExecutor`
is therefore safe: the asyncio event-loop thread remains responsive (can handle
other awaitable tasks) while the executor thread is inside the C++ kernel. This
is the correct rationale for `max_workers=1` + executor: *not* to parallelize
the forward pass (that would require the GIL to be held, which it is not), but
to off-load the blocking call from the event loop thread so the loop stays live.

Required module-docstring text (verbatim from AC):
> "BGE-M3 forward pass releases the GIL inside PyTorch's C++ backend;
> ThreadPoolExecutor is therefore safe for concurrent callers."

Note: `torch.no_grad()` disables gradient tracking and reduces peak memory. It
does NOT control GIL release. `model.eval()` disables dropout for BP1
byte-stability. Both are required but neither is the GIL mechanism.

### `asyncio.get_running_loop()` vs `asyncio.get_event_loop()`

Python 3.10 deprecated `asyncio.get_event_loop()` when no running loop exists.
Python 3.12 emits `DeprecationWarning`. The project targets `>=3.11`. Inside an
`async def`, the correct call is `asyncio.get_running_loop()` (available since
Python 3.7, raises `RuntimeError` outside a running loop — the correct failure
mode for an `async def` function). The 07-note reference implementation uses
`asyncio.get_event_loop()` — this is stale and must not be copied.

`loop.run_in_executor(executor, fn, *args)` returns an `asyncio.Future`-like
awaitable (internally wraps a `concurrent.futures.Future` via `asyncio.wrap_future`).
Store this awaitable in the `_inflight` dict, not the raw `concurrent.futures.Future`.
The dict must store `asyncio.Future` objects so that `await _inflight[key]` works
from the event loop. `concurrent.futures.Future` cannot be awaited directly.

### Singleflight pattern — canonical reference

The Go implementation lives at `golang.org/x/sync/singleflight`
(https://pkg.go.dev/golang.org/x/sync/singleflight). Its `Do(key, fn)` method:
blocks all callers with the same `key` on a single in-flight call; on completion
(success or error), removes the key and returns the result to all waiters.
Eviction in Go singleflight is **immediate on completion** — there is no TTL.

The arXMCP brief adds a 100ms post-completion TTL, making it a hybrid between
singleflight (in-flight dedup) and a micro-cache (post-completion dedup window).
This is an intentional design extension, not present in Go's implementation.

The asyncio advantage over Go's mutex-based approach: because the event loop is
single-threaded, the `if key in dict` / `dict[key] = fut` sequence has no `await`
between them and is therefore atomically safe. No `asyncio.Lock` is needed for
the dict-mutation critical section. (The 06-note says "asyncio.Lock keyed by
query hash" but this is overly conservative — the event loop's single-threaded
guarantee is sufficient, as the 07-note's reference implementation demonstrates
by using no lock.)

### Python 3.13 note on `asyncio.get_event_loop()` deprecation

Python 3.12 docs (https://docs.python.org/3/library/asyncio-eventloop.html):
"Deprecated since version 3.10: Deprecation warning is emitted if there is no
running event loop. In future Python release this will become an error."
Use `asyncio.get_running_loop()` throughout.

---

## Open Questions

**Q1 — 100ms eviction: first-arrival vs completion semantics?**

The brief says "Completed entries are evicted after 100ms" (completion-based) but
the AC says "a call arriving 101ms after the first is treated as a new request"
(sounds first-arrival-based). These diverge when encode takes >1ms. **Recommendation:
completion-based.** The `call_later(0.1, cleanup)` fires 100ms after the encode
completes, not 100ms after the first arrival. An encode taking 200ms means a
caller at t=150ms (before completion) still shares the in-flight future. The
AC's "101ms" should be interpreted as "101ms after completion." First-arrival
semantics would require a separate timer started at queue-time, which could race
with the in-flight future while still in-flight — a correctness hazard.

**Q2 — In-flight dedup beyond the 100ms window?**

If encode takes 200ms and a second caller arrives at t=150ms (50ms after first
arrival, well inside the "100ms window"), it shares the in-flight future
regardless of timing — pure singleflight. What if a caller arrives at t=250ms
(after the first-arrival 100ms window expired, but before completion at t=200ms)?
Under completion-based eviction, the key is still in the dict (not yet evicted),
so the caller at t=250ms also shares the result. This is correct: eviction happens
100ms post-completion, so the in-flight window is unlimited duration.

**Q3 — Cancellation semantics.**

If a caller `await`s the future and then cancels their task, does the underlying
encode task cancel? No — `loop.run_in_executor` futures are not cancellable (the
executor thread continues). Other waiters still receive the result. The implementer
should document this: cancelling an individual `await` does not cancel the encode.

**Q4 — Error propagation.**

When encode raises, `fut.set_exception(e)` propagates to all waiters. The 07-note
uses `finally: del self._inflight[key]` for immediate eviction on error. Do NOT
add `call_later` on the error path — the next identical call should retry
immediately. Asymmetric eviction: success → 100ms delay; error → immediate eviction.

**Q5 — Dict race: can two concurrent callers both miss the dict check?**

No. The asyncio event loop is single-threaded. Between `if key in self._inflight`
and `self._inflight[key] = fut`, no `await` occurs, so no other coroutine can
execute. The dict mutation is atomic within the event loop. This is the core
correctness argument for no-lock singleflight in asyncio.

**Q6 — Query-text normalization key.**

Use `query.strip()` only, matching the Tier-1 cache `canonical_form(query)` from
`07-multi-agent-caching.md`. Do NOT lowercase, do NOT strip punctuation. Then
apply `unicodedata.normalize("NFC", stripped)` for the actual tokenizer input.
The singleflight dict key should use the NFC-normalized stripped string so that
the key matches what the tokenizer sees.

**Q7 — Return same array object or `.copy()`?**

Multiple waiters all receive the same numpy array. If any caller mutates it, all
callers are affected. The implementer must decide: return the same object (fast,
but requires callers not to mutate) or return `.copy()` per caller. Given BP1
byte-stability requirements and defensive programming, returning `.copy()` is
safer — the cost is one memcpy of 1024 floats (4 KB), negligible.

**Q8 — Should `call_later` use `loop.call_later` or `asyncio.get_running_loop().call_later`?**

Since `call_later` is called inside the `async def`, use
`asyncio.get_running_loop().call_later(0.1, lambda: self._inflight.pop(key, None))`.
The cleanup callback must use `.pop(key, None)` not `del` to handle the case
where the key was already evicted by a concurrent cleanup.

---

## External Writes the Implementation Will Require

1. **New file: `server/query_encoder.py`** — primary deliverable. No changes to
   `server/__init__.py` (already present as an empty module). No changes to
   `server/README.md` needed for the implementation itself.

2. **New file: `tests/test_query_encoder.py`** — test suite. Must include:
   - Unconditional: 10 concurrent `encode_query("test query")` calls → exactly 1
     forward pass (mock `_get_model`, `_get_tokenizer`).
   - Unconditional: literal-count scan asserting the SHA `"5617a9f61b028005a4858fdac845db406aefb181"`
     appears exactly once across `ingest/*.py` and `server/*.py`.
   - Env-gated (`ARXMCP_RUN_REAL_BGE_M3=1`): two calls → cosine similarity ≥ 0.9999.

3. **No `pyproject.toml` changes.** All required packages (`torch`, `transformers`,
   `numpy`, `asyncio`, `concurrent.futures`) are already in `dependencies` from
   E03_S01 or stdlib. `pytest-asyncio` is NOT needed — use `asyncio.run()` wrapper.

4. **No git push, no PR creation, no infra mutation, no third-party API calls.**
   This milestone is purely local source code addition.

5. **Opinionated on `pytest-asyncio`:** do not add it. The `asyncio.run()` pattern
   is already available in stdlib for Python ≥ 3.11, adds no configuration surface,
   and is consistent with the rest of the test suite which uses only stdlib + pytest.
   If the test framework ever needs to grow async fixtures, that is a separate
   dependency decision for a future milestone.
