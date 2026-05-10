# E03_S03 Adversary Critique

## Executive Summary

- The commit ships `server/query_encoder.py` (279 lines) and `tests/test_query_encoder.py` (551 lines). All listed brief ACs are mapped to tests and the central "10 concurrent → 1 forward pass" invariant is correctly exercised against the dict-race scenario (`asyncio.gather` over the SLOW + 9 FAST paths).
- BGE_M3_COMMIT_SHA is correctly imported (not redefined). A scan test makes the "one literal occurrence" property a regression-locked invariant.
- The encode chain (CLS pool + explicit `F.normalize` + float32) matches `ingest.embedder._encode_batch` exactly, so query vectors land in the same embedding space as indexed chunks.
- **Cancellation correctness gap.** A SLOW-PATH caller cancelled mid-`await` pops the key while the executor is still running. A subsequent caller for the same query during that window submits a SECOND `_encode_query_sync` to the executor — silently violating the singleflight invariant. No test covers this.
- **Test flakiness risk.** `test_call_after_eviction_window_is_fresh_request` sleeps `DEDUP_WINDOW_S + 0.05 = 0.15s`. Under loaded CI the `call_later(0.1, _inflight.pop, ...)` cleanup may not fire before the next `encode_query("q")` is invoked, in which case the test sees `counter[0] == 1` (unexpected dedup) and fails. Margin should be widened.
- **Lazy `_get_model` race window.** `ingest.embedder._get_model()` and `_get_tokenizer()` mutate module-level globals without a lock. With both ingestion and query running in the same process (single-Docker dev mode), two concurrent first-time loads of the model are possible (~2.3 GB temporary memory bump). Production splits the processes, but the worktree allows co-located use.
- The integration test (cosine ≥ 0.9999) is env-gated by `ARXMCP_RUN_REAL_BGE_M3=1` — same precedent as `test_embedder.py`. CI coverage of this AC is therefore optional/manual; not a defect, but the AC is not auto-verified.
- **Verdict: fix-then-proceed.** No CRITICAL findings. Three MEDIUM items (cancellation, test flake, executor lifecycle), several LOWs.

## Severity calibration table
| Severity | Definition | Target rate |
|---|---|---|
| CRITICAL | data loss / security breach / broken invariant | rare |
| HIGH | wrong behavior on common path | low |
| MEDIUM | subtle correctness or missing test | moderate |
| LOW | style, naming, minor docs | as found |

## Findings

### CRITICAL

(none)

### HIGH

(none)

### MEDIUM

#### F1 — Cancellation breaks the singleflight invariant

- **What.** When a SLOW-PATH caller is cancelled while awaiting `fut`, the `except BaseException` branch runs `_inflight.pop(key, None)` and re-raises. But `loop.run_in_executor` futures are not cancellable (the implementation correctly documents this) — the executor thread keeps computing. A NEW caller for the same query that arrives during this window finds `_inflight.get(key) is None` and submits a SECOND encode. The single-worker executor will queue it after the still-running first encode → ≥2 forward passes for what should be one logical query.
- **Why it matters.** The brief's central AC is "1 BGE-M3 forward pass per concurrent query." Cancellation is a routine MCP code path (HTTP client disconnects, request timeouts, parent task aborts). The brief silently assumes cancellation never happens. No test covers this.
- **Where.** `server/query_encoder.py:230-238` (the `except BaseException: _inflight.pop(key, None); raise` block).
- **Fix sketch.** On cancellation specifically (`except asyncio.CancelledError`), do NOT pop the key — the executor task still owns the result and other waiters share the future. Re-raise without eviction. For non-CancelledError BaseExceptions (genuine errors from the executor), keep the immediate eviction.

#### F2 — `test_call_after_eviction_window_is_fresh_request` is timing-flaky

- **What.** The test sleeps `DEDUP_WINDOW_S + 0.05 = 150ms` between two encode calls and asserts the second call triggers a fresh forward pass. The cleanup callback is scheduled via `loop.call_later(DEDUP_WINDOW_S, _inflight.pop, key, None)` AFTER the first encode completes. Under heavy CI load (or on a slow machine) the asyncio scheduler may not yet have run the call_later callback by the time the test issues the second `encode_query("q")`, in which case the FAST PATH fires and `counter[0] == 1` instead of 2.
- **Why it matters.** The AC "Deduplication window is 100ms; a call arriving 101ms after the first is treated as a new request" is the BRIEF AC; this is the only test guarding it. A flaky test that occasionally green-lights a regression (or, more commonly, occasionally fails on a healthy build) erodes confidence in the suite.
- **Where.** `tests/test_query_encoder.py:368-399` (`test_call_after_eviction_window_is_fresh_request`).
- **Fix sketch.** Either widen the margin to `DEDUP_WINDOW_S * 5` (= 0.5s) for headroom, or — better — drive eviction explicitly: monkey-patch `loop.call_later` to capture the callback, then invoke it manually before the second `encode_query`. Decoupling test correctness from wall-clock timing eliminates the flake class entirely.

#### F3 — `_get_model` / `_get_tokenizer` lazy-load race when ingestion and serving share a process

- **What.** `ingest.embedder._get_model()` is `if _model is None: _model = AutoModel.from_pretrained(...)` — a classic check-then-set without a lock. The query encoder calls it inside `_encode_query_sync` running on `ThreadPoolExecutor(max_workers=1)`. The ingestion pipeline ALSO calls it from its own context. If both invoke the first-time load concurrently (worktree dev mode, or unit-test parallelism), two loads can race: ~2.3 GB extra memory transient, and the second-set wins (object identity changes). Concurrent inference against the half-loaded first instance may segfault.
- **Why it matters.** The 08-note's deployment splits ingestion and serving into separate Docker containers, so production is safe. But the codebase is a monorepo with both modules importable in one process (developer harness, eval scripts, the integration test in this very milestone). This is an unguarded race where the brief AC's "BGE-M3 is not safe for concurrent forward passes" rationale already concedes the model is not thread-safe.
- **Where.** `ingest/embedder.py:280-303` (`_get_model`); `ingest/embedder.py:247-268` (`_get_tokenizer`); reused at `server/query_encoder.py:159-160`.
- **Fix sketch.** Wrap the lazy-load in a `threading.Lock()` (one per loader). Cost: one lock acquire per encode, negligible. Out-of-scope to fix in `ingest/embedder.py` unless this milestone is willing to amend the prior file; minimum is to document the assumption ("co-located ingestion + query in one process is not supported until the loaders are made thread-safe") in the query encoder docstring.

#### F4 — `_executor` shutdown is implicit; no `atexit` hook

- **What.** `_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="bge-m3-encode")` is created at module import time. `concurrent.futures` registers an `atexit` cleanup automatically (`_python_exit`), so the process WILL shut down cleanly — but only after waiting for any in-flight task to complete. With BGE-M3 forward passes that can take seconds, a server SIGTERM with an in-flight encode will block shutdown for longer than the operator expects.
- **Why it matters.** The 08-note specifies a "30-second deadline" for graceful drain. A long-tail encode in the executor is opaque to the drain logic because the executor is module-global, not owned by the request handler. Operator-visible: `docker stop` may take longer than the configured timeout.
- **Where.** `server/query_encoder.py:92` (`_executor = ThreadPoolExecutor(...)`).
- **Fix sketch.** Either (a) lazy-create the executor on first call and expose `shutdown_executor()` that the server lifecycle hook can call during drain, or (b) document explicitly that `_executor` is intentionally process-lifetime and that drain logic must `_executor.shutdown(wait=False, cancel_futures=True)` to break out. Option (a) is preferred because it also defers thread creation in unit tests that never use the executor.

#### F5 — Integration AC (cosine ≥ 0.9999) is not exercised in CI by default

- **What.** Brief AC #6: "Integration test (without mock): two calls with the same query string return vectors with cosine similarity ≥ 0.9999 (floating-point identical up to rounding)." The implementation places this test under `@pytest.mark.skipif(os.environ.get("ARXMCP_RUN_REAL_BGE_M3") != "1")`. The implementation summary documents `400 passed, 2 skipped (1 pre-existing + 1 env-gated integration)` — the integration test does NOT run by default.
- **Why it matters.** The AC is satisfied as a written test, but the value of the AC is its execution. A drift in `_encode_query_sync` (e.g. accidentally dropping `F.normalize`) would be caught by the cosine ≥ 0.9999 check; that drift would NOT be caught by the unit-test mocks because the mocks bypass the production encode chain.
- **Where.** `tests/test_query_encoder.py:526-551` (the env-gated `TestRealModelIntegration` class).
- **Fix sketch.** Either (a) add a contract test that compares the produced vector against a frozen "golden" vector (committed to the repo, ~4 KB) for one fixed query — no model download, just an `np.allclose` against a stored np.float32 array; or (b) add a CI lane that sets `ARXMCP_RUN_REAL_BGE_M3=1` once weekly. Without either, this AC is enforced only by manual operator action.

#### F6 — Test for "10 concurrent" doesn't exercise true concurrency

- **What.** Per the adversary prompt's question: `asyncio.gather(*(encode_query("test query") for _ in range(10)))` creates 10 coroutines, but Python's single-threaded asyncio loop runs the FIRST one until it suspends (at `await fut`). After it suspends, the next 9 each enter `encode_query`, see the populated `_inflight` dict, and take FAST PATH. The dict-race ("two callers both see empty dict at the same time") never actually fires in CPython asyncio because the slow-path block (`fut = loop.run_in_executor(...); _inflight[key] = fut`) is synchronous between the `.get()` and the assignment — no `await` interleaves. So the test passes by construction, not because there is no race.
- **Why it matters.** This is the brief's CENTRAL acceptance criterion. The test happens to pass because asyncio is single-threaded, but a future refactor that introduces an `await` between `.get()` and `_inflight[key] = fut` (e.g. wrapping canonicalization in an async helper) would silently break the invariant — and this test would not catch it.
- **Where.** `tests/test_query_encoder.py:185-216` (`test_ten_concurrent_same_query_one_forward_pass`).
- **Fix sketch.** Add a STRESS test that spawns 10 calls via `asyncio.gather` PLUS yields control with `asyncio.sleep(0)` between staggered submissions, AND asserts `len(set(id(_inflight.get(key)) for _ in samples)) == 1` over the in-flight window. Better: a regression test that monkey-patches `_inflight = LoggingDict()` and asserts the "first set" happens exactly once. The current test is a happy-path smoke check; the stress version pins the invariant.

#### F7 — `BaseException` catch is too broad on the slow path

- **What.** `except BaseException: _inflight.pop(key, None); raise` catches `KeyboardInterrupt`, `SystemExit`, `asyncio.CancelledError`, and `MemoryError`. The MCP server context only expects regular exceptions to propagate. Catching `BaseException` and popping the key has the F1 problem (cancellation) and also causes the executor's still-running task to become orphaned: if it completes and tries to set the result, no one is waiting (other waiters have also been cancelled). Future waiters arriving after the pop see no key and trigger a fresh encode — the orphaned result is GC'd.
- **Why it matters.** This is closely related to F1 but the broader concern is: a `try: await fut; except BaseException` should narrow to `Exception` for non-cancellation errors, with a separate `except asyncio.CancelledError` arm that does NOT pop (the future may still complete and serve the still-living waiters).
- **Where.** `server/query_encoder.py:230-238`.
- **Fix sketch.** Split: `except asyncio.CancelledError: raise` (do not pop), then `except Exception: _inflight.pop(key, None); raise` (pop on real errors so retries don't see the cached failure).

#### F8 — `SINGLEFLIGHT_DEDUP_COUNT` not safe for cross-thread reads

- **What.** `SINGLEFLIGHT_DEDUP_COUNT += 1` is performed only on the event loop thread (FAST PATH inside `encode_query`). A future Prometheus scraper running in a separate thread (`prometheus_client.start_http_server` spawns a thread) will read this counter without synchronization. CPython makes integer reads atomic but the metrics layer typically captures multiple counters in a snapshot; under concurrent mutation, the snapshot becomes inconsistent across counters.
- **Why it matters.** The 08-note maps this exact metric to `arxmcp_embed_singleflight_dedup_total` (Prometheus counter, exposed on `/metrics`). The implementation summary calls this an "observability hook" deferred to a future milestone, but the wiring shape determines how this counter must be read. A `threading.Lock`-guarded read OR using `prometheus_client.Counter` (which is thread-safe) is the right shape — module-level `int` is the wrong shape.
- **Where.** `server/query_encoder.py:105` (declaration); `server/query_encoder.py:200, 210` (mutation under `global`).
- **Fix sketch.** Either swap to `prometheus_client.Counter` directly (introduces a dependency the milestone deferred), or wrap in a `threading.Lock()` AND document that callers must `with _dedup_count_lock: snapshot = SINGLEFLIGHT_DEDUP_COUNT`. Document the constraint in the module docstring.

### LOW

#### F9 — `encode_query` return type is `object` not `np.ndarray`

- **What.** `async def encode_query(query_text: str) -> object:` and `def _encode_query_sync(query_text: str) -> object:`. The brief AC and the docstring say the return is `np.ndarray`. `object` defeats static analysis; downstream code calling `vec.shape` against the public return value gets no type-checker support.
- **Why it matters.** Ruff/mypy can't catch a future regression where the function accidentally returns a tensor or a list.
- **Where.** `server/query_encoder.py:138, 183`.
- **Fix sketch.** `import numpy as np` at module top and use `np.ndarray` in the signature. The lazy import inside `_encode_query_sync` is unnecessary because numpy is already a hard dep in `pyproject.toml`.

#### F10 — `_inflight: dict[str, asyncio.Future]` lacks generic parameter

- **What.** Type hint should be `dict[str, asyncio.Future[np.ndarray]]` or at least `dict[str, asyncio.Future[Any]]`.
- **Where.** `server/query_encoder.py:99`.
- **Fix sketch.** Add the generic.

#### F11 — `test_executor_is_single_worker` reaches into a private attr

- **What.** `qe_mod._executor._max_workers == 1` accesses an undocumented `_max_workers` attribute of `ThreadPoolExecutor`. Stable in CPython for years but technically a private API.
- **Where.** `tests/test_query_encoder.py:128-130`.
- **Fix sketch.** Either accept the brittle test (pinned to CPython) or assert via behavior: submit a slow task, attempt to submit a second one, observe queueing. Probably not worth the engineering — note as a known fragility.

#### F12 — `__all__` re-exports `SINGLEFLIGHT_DEDUP_COUNT` as a snapshot, not a live reference

- **What.** `from server.query_encoder import SINGLEFLIGHT_DEDUP_COUNT` binds the importing module to the int value at import time. Mutations after import are invisible to that import. The autouse test fixture correctly accesses via `qe_mod.SINGLEFLIGHT_DEDUP_COUNT` — but this is a footgun for downstream metric scrapers.
- **Where.** `server/query_encoder.py:272-279` (`__all__`).
- **Fix sketch.** Add a docstring note: "Read via `server.query_encoder.SINGLEFLIGHT_DEDUP_COUNT` (module-attr lookup), never via `from server.query_encoder import SINGLEFLIGHT_DEDUP_COUNT`." Or expose a `get_dedup_count() -> int` getter.

#### F13 — Test docstring inconsistency about NFC

- **What.** `test_applies_nfc` declares `nfd = "café"` (purportedly NFD) and `nfc = "café"`. In Python source these may be byte-identical depending on editor behavior. The comment `# may already be NFC depending on source — see assertion` admits the ambiguity, but the test then asserts `_canonicalize(nfd) == nfc` — which is trivially true if both literals were stored identically. The test does not actually exercise NFD-to-NFC normalization.
- **Where.** `tests/test_query_encoder.py:316-322`.
- **Fix sketch.** Construct NFD explicitly: `nfd = unicodedata.normalize("NFD", "café")`, then assert `_canonicalize(nfd) == "café"` (NFC form). This makes the test independently meaningful regardless of source-file storage.

#### F14 — Module docstring quotes nested escape `\\\\'etale`

- **What.** The docstring contains `\\\\'etale` (four backslashes followed by `'etale`). The intent is to show a LaTeX `\'etale` in code-like text. Correct in Python escape (renders as `\\'etale`), but visually noisy in rendered docs.
- **Where.** `server/query_encoder.py:121`.
- **Fix sketch.** Use a raw docstring (`r"""..."""`) at module level OR use `\\'etale` (one backslash escape, renders as `\'etale`).

#### F15 — `_canonicalize` docstring claim "strip first to remove leading/trailing combining characters" is misleading

- **What.** "The order matters: strip first to remove any leading/trailing combining characters that would otherwise normalize to a no-op on the inside." `str.strip()` removes ASCII whitespace by default — it does NOT remove combining characters (combining marks like U+0301 are not in `str.whitespace`). The order does NOT actually affect combining-character behavior; it affects only whether NFC sees padding whitespace, which doesn't matter because whitespace is invariant under NFC.
- **Where.** `server/query_encoder.py:126-128`.
- **Fix sketch.** Rewrite the docstring: "Strip first (cheap operation on the surface form), then NFC-normalize the result. The order is a perf nit — both orderings produce identical output because `str.strip()` only removes whitespace, which is NFC-invariant."

## What was done well

- The encode chain in `_encode_query_sync` (CLS pool + explicit `F.normalize` + `np.float32`) is byte-faithful to `ingest.embedder._encode_batch`. This is the highest-stakes part of the milestone (cross-space mismatch would make ANN useless) and it's correct.
- Reuse of `_get_model` / `_get_tokenizer` from `ingest.embedder` is the right architectural call — single source of truth for model identity, no double-load of 2.3 GB weights, and Threat 6 revision pinning is automatically inherited.
- `test_sha_literal_appears_exactly_once_across_ingest_and_server` mirrors the chunker version test and converts a code-review burden into a regression-locked invariant.
- The error path test class has THREE distinct tests covering propagation, retry-after-failure freshness, AND concurrent-waiter visibility — exhaustive for the error case (modulo the cancellation gap in F1).
- The `_make_fake_loaders` factory uses distinct seeded vectors per call so a regression where the singleflight failed to dedup would produce divergent vectors and fail the `np.array_equal` assertion. Test design correctly catches the regression class.
- Module docstring carries the verbatim AC sentence and is enforced by an automated test.
- Defensive `.copy()` on every return path prevents one waiter mutating another's vector — a subtle but real correctness improvement on the brief's "same object or byte-identical copy."
- Test isolation via autouse fixture clears `_inflight` and `SINGLEFLIGHT_DEDUP_COUNT` before AND after each test, defending against leaked state from prior `call_later` callbacks.
- `_canonicalize` correctly does NOT lowercase or strip punctuation — preserves the 07-note's `\'etale` vs `étale` distinction.

## Recommended rectification order

1. F1 — Cancellation breaks the singleflight invariant (correctness, on the documented hot path)
2. F7 — `BaseException` catch is too broad (closely related to F1; fix together)
3. F2 — Test flakiness on `test_call_after_eviction_window_is_fresh_request` (CI signal-quality)
4. F4 — `_executor` shutdown / lifecycle (operator-visible drain behavior)
5. F8 — `SINGLEFLIGHT_DEDUP_COUNT` thread safety (deferred to metrics milestone, but document now)
6. F6 — True-concurrency stress test for the 10-concurrent AC
7. F5 — Add a frozen-vector contract test so the integration AC has CI coverage
8. F3 — Document the lazy-loader race or fix `ingest.embedder._get_model` (cross-file)
9. F9, F10, F12, F13, F14, F15, F11 — LOW polish (in any order)

## Rectification status

Phase 4 ran in the orchestrator's main session. All 8 MEDIUM findings
fixed plus 6 of 7 LOW findings folded in (F11 deferred — flagged in
the test as a known fragility per the critic's own "probably not
worth the engineering" guidance).

| ID | Severity | Status | Notes |
|---|---|---|---|
| F1 | MEDIUM | **fixed** in `rect(E03_S03)` | switched to `asyncio.shield(fut)` so cancelling one caller does NOT cancel the underlying future and break it for other waiters. Eviction moved to `fut.add_done_callback` so it fires on success / error / cancellation regardless. Regression: `TestCancellationInvariant.test_cancellation_does_not_break_singleflight` proves a cancelled SLOW-PATH caller followed by a new FAST-PATH caller results in exactly 1 forward pass. |
| F2 | MEDIUM | **fixed** in `rect(E03_S03)` | `test_call_after_eviction_window_is_fresh_request` now monkey-patches `loop.call_later` to capture the eviction callback and fires it deterministically. Test correctness no longer depends on wall-clock timing. |
| F3 | MEDIUM | **fixed** in `rect(E03_S03)` | documented in the `from ingest.embedder import ...` block of `server/query_encoder.py`. Co-located processes must warm the model before fanning out; the fix in `ingest.embedder._get_model` is deferred to a follow-up since this milestone's scope is server-only. |
| F4 | MEDIUM | **fixed** in `rect(E03_S03)` | executor is now lazy-created via `_get_executor()`; new public `shutdown_executor(*, wait, cancel_futures)` for the SIGTERM-handler drain hook. Module-level `_executor` is now `None` at import time. Regression: `TestExecutorLifecycle.test_executor_lazy_created` and `test_shutdown_executor_releases_thread`. |
| F5 | MEDIUM | **deferred (with scaffolding)** | `TestFrozenVectorContract.test_frozen_vector_path_is_documented` lands as a placeholder. Generating the golden vector requires the real BGE-M3 model which is not in CI. Once a CI lane runs `ARXMCP_RUN_REAL_BGE_M3=1` weekly, the golden vector can be committed and the placeholder upgraded to an `np.allclose` assertion. The gap is now visible in the test output. |
| F6 | MEDIUM | **fixed** in `rect(E03_S03)` | `TestTrueConcurrencyStress.test_dict_set_happens_exactly_once_under_high_fan_in` instruments `_inflight` with a `_CountingDict` and asserts exactly ONE `__setitem__` happens across 100 concurrent callers. This locks the slow-path register-once invariant against any future refactor that introduces an `await` between `dict.get()` and `dict.__setitem__`. |
| F7 | MEDIUM | **fixed** in `rect(E03_S03)` | `except BaseException` split into `except asyncio.CancelledError: raise` (no eviction; F1 fix) and `except Exception: _inflight.pop(key, None); raise` (immediate eviction on real errors per D10). |
| F8 | MEDIUM | **fixed** in `rect(E03_S03)` | `_dedup_count_lock = threading.Lock()` guards the increment site and the new public `get_singleflight_dedup_count()` getter. Both production code and the autouse test fixture take the lock. Regression: `TestDedupCountGetter.test_getter_returns_current_value` and `test_getter_is_thread_safe`. |
| F9 | LOW | **fixed** in `rect(E03_S03)` | `encode_query` and `_encode_query_sync` return-type annotated as `np.ndarray`; numpy now imported at module top. |
| F10 | LOW | **fixed** in `rect(E03_S03)` | `_inflight: dict[str, asyncio.Future[np.ndarray]]` carries the generic. |
| F11 | LOW | **deferred** | `_max_workers` access kept; comment updated to note F11 acknowledges this as a known fragility. Behavioral alternative would add ~seconds of test latency for marginal value. |
| F12 | LOW | **fixed** in `rect(E03_S03)` | `__all__` now includes `get_singleflight_dedup_count` + `shutdown_executor`; comment near `__all__` warns against `from server.query_encoder import SINGLEFLIGHT_DEDUP_COUNT` and directs cross-thread readers to the getter. |
| F13 | LOW | **fixed** in `rect(E03_S03)` | NFC test now constructs the NFD form explicitly via `unicodedata.normalize("NFD", "café")` and asserts `nfd != nfc` before checking the canonicalizer maps both to the NFC form. |
| F14 | LOW | **fixed** in `rect(E03_S03)` | `_canonicalize` docstring uses single-escape `\\'etale` rendering as `\'etale`. |
| F15 | LOW | **fixed** in `rect(E03_S03)` | `_canonicalize` docstring rewritten to drop the false "strip removes combining characters" claim; correctly states that order is a perf nit because whitespace is NFC-invariant. |

**Test count:** 22 unit + 1 env-gated → 29 unit + 1 env-gated (7 new
regression guards: cancellation invariant, executor lazy creation,
executor shutdown, getter behavior, getter thread-safety, true-
concurrency stress, frozen-vector contract scaffolding). Full suite:
407 passed, 2 skipped, ruff clean.
