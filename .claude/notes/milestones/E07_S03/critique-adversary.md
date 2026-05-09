# E07_S03 — Adversary critique

## Executive summary

- **Verdict: SHIP WITH RECTIFICATIONS.** No CRITICAL findings; all four brief ACs are met. The off-path passthrough is clean, the singleflight dedup is properly tested, the SHA pin is encoded as a module constant. The reranker is dormant in v1 (default off), which dampens the blast radius of every finding below.
- **Top defect (HIGH F1):** Threat 6 mandates safetensors-only loading; the reranker loader at `server/resources.py:482-491` does not pass `use_safetensors=True`. If transformers ever resolves a `.bin` weight file, pickle load = RCE. The same gap exists in the embedder.
- **HIGH F2:** Singleflight key separator is brittle. `_build_singleflight_key` joins chunk_ids with `b"\n"`; if a chunk_id ever contained `\n` two distinct id-lists would produce identical key inputs. No validation.
- **MEDIUM F3:** `RerankerLoadError` (`server/retrieval/rerank.py:131`) is exported but never raised. Dead code, contradicts its docstring.
- **MEDIUM F4:** `_fetch_body_texts` diverges from the established `_escape_lance_str` pattern (`server/handlers/chunk.py:120-122`). Drops chunk_ids with quotes silently — defensible, but inconsistent.
- **MEDIUM F5:** Score-semantics ambiguity in `rerank()` return type. Off-path returns RRF scores (~0.01..0.05); on-path returns sigmoid logits (0..1). Same return type, two different ranges, no contract.
- **MEDIUM F6:** Two test files mutate module-level state directly (`os.environ`, `qe_mod._get_model`) instead of using `monkeypatch`. Inconsistent with `tests/test_server_startup.py:491` which uses `monkeypatch.setattr` properly.
- **LOW (3 findings):** doc-vs-code mismatch on the chunk_id separator (`b"\x00"` vs `b"\n"` in docstring), unused `_call_count` in `_FakeRerankerModel`, `model_handle` 2-tuple destructuring trap.

## Severity calibration

| Severity | Bar | This milestone |
|---|---|---|
| CRITICAL | data loss / security / broken invariant | none |
| HIGH | wrong behavior on common path / unmitigated security recipe | F1, F2 |
| MEDIUM | subtle correctness / missing test / contract gap | F3, F4, F5, F6 |
| LOW | style / dead code / doc-code drift | F7, F8, F9 |

---

## HIGH

### F1 — Reranker loader does not enforce `safetensors`-only; pickle-RCE vector remains open

**Citation:** `server/resources.py:482-491`, `server/retrieval/rerank.py:18-24` (advertises Threat 6 mitigation), `.claude/notes/08-security-observability-ops.md:84` ("Use `safetensors` format only; refuse `.bin` / pickle weights").

**Detail.** The Threat-6 mitigation list at `08-security-observability-ops.md:82-86` has THREE items: pin SHAs, refuse `.bin`/pickle, set `trust_remote_code=False`. The new loader satisfies items 1 and 3 but not item 2:

```python
tokenizer = AutoTokenizer.from_pretrained(
    RERANKER_MODEL_ID,
    revision=BGE_RERANKER_COMMIT_SHA,
    trust_remote_code=False,
)
model = AutoModelForSequenceClassification.from_pretrained(
    RERANKER_MODEL_ID,
    revision=BGE_RERANKER_COMMIT_SHA,
    trust_remote_code=False,
)
```

`from_pretrained` does NOT default to `use_safetensors=True` in transformers `<=4.47`; it auto-resolves whatever weight file is present in the snapshot. `BAAI/bge-reranker-v2-m3` ships safetensors today, but the loader doesn't enforce it. If a future SHA upgrade ships only `.bin`, the loader will silently `pickle.load` weights — exactly the attack surface Threat 6 names.

The fix is one kwarg: `use_safetensors=True` on both `from_pretrained` calls. This will fail loudly if a SHA ever ships `.bin`-only — the correct behavior for a security mitigation.

The same gap exists in `ingest/embedder.py:291-294` (the embedder load). The rectification should fix both, OR document why the project consciously deviates from Threat 6's second mitigation in `.claude/notes/08-security-observability-ops.md`.

**Why HIGH not CRITICAL.** Today's `BAAI/bge-reranker-v2-m3` ships safetensors and the SHA is pinned, so the immediate attack surface is closed by `revision=`. The HIGH severity reflects: (a) Threat 6 is explicit about the mitigation; (b) the docstring at `server/retrieval/rerank.py:23-24` advertises Threat 6 mitigation but only delivers 2 of 3 items; (c) reranker is opt-in but the same code pattern in the embedder (always loaded) compounds the risk.

---

### F2 — Singleflight key separator allows collision if chunk_id ever contains `\n`

**Citation:** `server/retrieval/rerank.py:240-250`.

**Detail.** The key construction joins chunk_ids with `b"\n"`:

```python
h.update(query_vec.tobytes())
h.update(b"\x00")
sorted_ids = sorted(cid for cid, _score in candidates)
h.update(b"\n".join(cid.encode("utf-8") for cid in sorted_ids))
h.update(b"\x00")
h.update(RERANKER_VERSION.encode("utf-8"))
```

If a chunk_id contained a literal `\n`, two distinct lists would hash to the same value:
- `["a", "b\nc"]` → `b"a\nb\nc"`
- `["a", "b", "c"]` → `b"a\nb\nc"`

Today the chunk_id format `arxiv:<paper_id>:<16-hex>` cannot contain newlines, but there is no validation in `_build_singleflight_key` that rejects ill-formed ids. A future format change OR a tampered upstream candidate list could produce silent cache collisions, returning the wrong ranked result to one caller.

Compounding factor: the `_fetch_body_texts` defensive check (line 271) rejects chunk_ids containing single quotes, but does NOT reject newlines. So a chunk_id with `\n` would (a) collide in the cache key, AND (b) pass through to the LanceDB SQL `IN` clause unaltered.

**Fix options:**
1. Length-prefix each chunk_id: `h.update(struct.pack(">Q", len(cid_bytes))); h.update(cid_bytes)` — collision-free regardless of content.
2. Reject ill-formed chunk_ids upfront (regex match on the documented format).
3. Use a separator known not to appear in chunk_ids (e.g. `b"\x00"`); document the invariant.

Option 1 is the most robust.

---

## MEDIUM

### F3 — `RerankerLoadError` is exported but never raised; doc claims wrap-as-`RerankerUnavailableError` is fictional

**Citation:** `server/retrieval/rerank.py:131-135`, `server/retrieval/__init__.py:24,36`, `server/resources.py:481-498`.

**Detail.** `RerankerLoadError` is defined and re-exported as part of the public retrieval API:

```python
class RerankerLoadError(RuntimeError):
    """Raised when the reranker model cannot be loaded.

    Lifted to a startup-time error by :func:`server.resources._load_reranker_or_raise`,
    which wraps as :class:`server.resources.RerankerUnavailableError`."""
```

`grep -rn "raise RerankerLoadError" .` returns zero hits. `_load_reranker_or_raise` catches the bare `Exception` and wraps directly as `RerankerUnavailableError` — never sees a `RerankerLoadError` to wrap. The class is dead code, the docstring claim is false, and the public-API surface is inflated by a class no caller will ever see.

**Fix:** either (a) actually raise `RerankerLoadError` from `_load_reranker_or_raise` (catch concrete model-load exceptions, raise `RerankerLoadError`, then have the caller wrap as `RerankerUnavailableError`), or (b) remove the class + the export.

---

### F4 — `_fetch_body_texts` SQL escape strategy diverges from established codebase pattern

**Citation:** `server/retrieval/rerank.py:268-281`, `server/handlers/chunk.py:120-122`, `server/handlers/paper.py:94`.

**Detail.** The codebase already has a documented LanceDB SQL escape function:

```python
# server/handlers/chunk.py:120
def _escape_lance_str(s: str) -> str:
    """Escape single quotes for LanceDB SQL-style WHERE clauses."""
    return s.replace("'", "''")
```

The new `_fetch_body_texts` instead drops chunk_ids containing single quotes:

```python
for cid in chunk_ids:
    if "'" in cid:
        logger.warning(...)
        continue
    safe_ids.append(cid)
```

Two issues:
1. **Silent data loss.** A defended chunk_id is dropped, not re-quoted. The phantom-id contract (E07_S02 F5) absorbs the missing chunk in the rerank set, masking that this drop happened. There's no metric/counter for "n_dropped_due_to_unsafe_id".
2. **Inconsistent with the project-wide pattern.** Two callers escape, one drops. A future maintainer reading `chunk.py`/`paper.py` would expect the same treatment in `rerank.py`.

**Fix:** either reuse `_escape_lance_str` (and document that LanceDB SQL doubles quotes), or migrate the existing handlers to drop-and-warn (with a justification). Cross-module consistency reduces the surprise budget.

---

### F5 — Score-semantics ambiguity: same return type carries two incomparable score ranges

**Citation:** `server/retrieval/rerank.py:457-469`, brief deliverable: `(chunk_id, rerank_score)`.

**Detail.** The `rerank()` return type is `list[tuple[str, float]]`, but the second slot has different meaning in each branch:

- **Off-path** (`enabled=False`): `score` is the **RRF fused score** from Phase 2. RRF scores are typically `~0.01..0.05` (sum of `1/(k+rank)` with k=60 — small numbers).
- **On-path** (`enabled=True`): `score` is `sigmoid(cross-encoder logit)`, in `[0, 1]`.

The docstring acknowledges this ("preserves the input RRF score in the second slot" / "cross-encoder scores replace the RRF scores"), but downstream consumers (E07_S04) cannot distinguish which they got without inspecting `RerankPhase.enabled`. Two real risks:

1. **Wire envelope drift.** If E07_S04 publishes `rerank_score` to MCP wire callers (it likely will), the score's semantic range will silently change when `ARXMCP_ENABLE_RERANK` flips. Same query, different deployment, different `score` value for the same chunk.
2. **Score normalization regression.** A naive consumer that does `if rerank_score > 0.5` will behave totally differently in the two regimes.

**Fix options:**
1. Off-path: return `(chunk_id, sentinel)` (e.g. `float("nan")`) so the consumer is forced to check `enabled`.
2. Off-path: re-normalize the RRF score into [0, 1] (e.g. via min-max within the candidate set) so both branches return [0, 1].
3. Document the dual-meaning in the API docstring AND in `.claude/notes/06-mcp-server-design.md`.

The brief itself doesn't mandate a specific score range, but consistency for the future wire-surface E07_S04 will need it.

---

### F6 — Tests mutate `os.environ` and module attributes manually instead of `monkeypatch`

**Citation:** `tests/retrieval/test_rerank.py:614, 619, 634, 639, 653, 660, 668, 672, 680, 684` (`os.environ` mutation), `tests/retrieval/test_rerank.py:705-720` (`qe_mod._get_model = ...`).

**Detail.** The SHA-drift tests and the integration test set `os.environ["HF_HOME"]` and patch `server.query_encoder._get_model` directly:

```python
os.environ["HF_HOME"] = str(tmp_path)
try:
    ...
finally:
    del os.environ["HF_HOME"]
```

```python
qe_mod._get_model = lambda: object()
qe_mod._get_tokenizer = lambda: object()
try:
    ...
finally:
    qe_mod._get_model = original_get_model
    qe_mod._get_tokenizer = original_get_tok
```

If pytest interrupts between setup and teardown (KeyboardInterrupt, an exception in the body), the `finally` blocks run but if `del os.environ["HF_HOME"]` itself raises (because a previous test leaked state), test isolation is broken for subsequent tests.

The codebase already uses the standard `monkeypatch` fixture in `tests/test_server_startup.py:491`. pytest unwinds these automatically and idempotently.

**Fix:** thread the `monkeypatch` fixture through the SHA-drift tests AND the integration test. Use `monkeypatch.setenv("HF_HOME", str(tmp_path))` and `monkeypatch.setattr(qe_mod, "_get_model", ...)`.

---

## LOW

### F7 — Doc/code drift on chunk_id separator in `_build_singleflight_key`

**Citation:** `server/retrieval/rerank.py:244` ("Sorted chunk_ids, joined by NUL.") vs line 246 (uses `b"\n"`, not NUL).

**Detail.** Comment claims NUL; code uses LF. Trivial fix: update the comment (or rotate to NUL — folded into F2).

---

### F8 — `_FakeRerankerModel._call_count` is initialized but never incremented or asserted

**Citation:** `tests/retrieval/test_rerank.py:179-200`.

**Detail.** The fake model's `__init__` sets `self._call_count = 0` but `__call__` never touches it, and no test reads it. The dedup test infers single-invocation via `Singleflight.dedup_count`, which is fine but a direct invocation count would catch a regression where the singleflight returns the right answer for the wrong reason (e.g. the model was invoked twice but coincidentally returned the same ranking both times). Increment `_call_count` in `__call__` and assert it equals 1 in `test_concurrent_identical_rerank_dedups`.

---

### F9 — `model_handle` 2-tuple destructuring is a runtime trap

**Citation:** `server/retrieval/rerank.py:536`.

**Detail.** `model, tokenizer = self._model_handle  # type: ignore[misc]` will fail at runtime with a confusing `ValueError: not enough values to unpack` if a future change makes the handle a 3-tuple or a single object. The `# type: ignore[misc]` already signals this is brittle. A `NamedTuple` (`RerankerHandle = NamedTuple("RerankerHandle", [("model", Any), ("tokenizer", Any)])`) would make the contract explicit and the error message clearer.

---

## What was done well

- **AC #1 coverage is exhaustive.** `TestOffPathPassthrough` covers seven angles: order preservation, top-k truncation, no-singleflight-touch, empty-candidates, `enabled` introspection, top-k validation, and the "enabled=True without model" rejection. Each test is small and independent.
- **`trust_remote_code=False` and `revision=` are correctly passed to BOTH `from_pretrained` calls** — the most important Threat-6 mitigations are in place. The model load is also off-loaded to the executor (`server/resources.py:502-503`), matching the embedder discipline.
- **The off-path is genuinely zero-cost.** Line 483-484 returns `list(candidates[:top_k])` BEFORE building the singleflight key, BEFORE acquiring the semaphore, BEFORE touching the model handle. The test `test_off_path_does_not_touch_singleflight` verifies this by inspecting `dedup_count`. Faithful to the brief AC #1 wording.
- **The Tier-3 singleflight key includes `RERANKER_VERSION` (the SHA prefix)** — bumping the SHA invalidates the cache automatically (server restart suffices). Documented inline at `rerank.py:86-92`.
- **`MAX_K = 50` is mirrored from `server/handlers/search.py:70`** with an explicit comment that the two must stay in lockstep.
- **The phantom-id contract from E07_S02 F5 is carried through correctly.** `_do_rerank` builds aligned id/body lists by skipping ids with no `body_text` row. Both partial- and full-phantom cases are tested.
- **The cancellation-safe singleflight** (`server/resources.py:150-196`, pre-existing but exercised here for the first time) shields the shared task from individual caller cancellation. The dedup test exercises the fast-path cleanly via `asyncio.gather`.
- **The `requires_model` marker** is registered in `pyproject.toml:118-120` and matches the convention from prior milestones. `pytest -k "not requires_model"` is the documented exclusion path; the suite passes (920/4) without a model download.
- **The implementation summary table maps each brief AC to a concrete test** and explicitly documents the three deviations from the brief (cache-stats endpoint reinterpretation, SHA drift = WARNING, signature extension to include `query_vec`).

---

## Recommended rectification order

1. **F1** — add `use_safetensors=True` to both `from_pretrained` calls in `server/resources.py:482-491`. Optionally add the same to `ingest/embedder.py:291-294` to close Threat 6 across the project. Single-line fix per call.
2. **F2** — switch `_build_singleflight_key` to length-prefixed encoding for chunk_ids (or another collision-free separator). Update `test_key_invariant_to_candidate_order` if the byte-layout changes. Folds in F7's doc fix.
3. **F4** — decide: reuse `_escape_lance_str` in `_fetch_body_texts`, OR migrate `chunk.py`/`paper.py` to drop-and-warn. Either way, document the choice.
4. **F5** — pick one of the score-normalization strategies and document the contract in `rerank()`'s docstring. Prefer option 1 (sentinel) for explicit failure on misuse.
5. **F3** — either delete `RerankerLoadError` + its export, or actually raise it from `_load_reranker_or_raise`.
6. **F6** — convert the `os.environ` and direct attribute mutations to `monkeypatch` calls. Mechanical refactor.
7. **F8** — increment `_FakeRerankerModel._call_count` in `__call__`; assert in the dedup test that it equals 1.
8. **F9** — wrap `model_handle` in a `NamedTuple`. Update the loader and the destructuring site.
9. **F7** — folded into F2 if separator changes; otherwise standalone one-line comment fix.

---

## Rectification status

| ID | Status | Commit |
|---|---|---|
| F1 | **fixed (partial)** | Reranker load now passes `use_safetensors=True` (closes Threat 6's second mitigation for the rerank path). Embedder rectification deferred: pinned BGE-M3 SHA `5617a9f6...` ships only `pytorch_model.bin`; adding the kwarg breaks the load. Bumping the SHA invalidates every cached embedding (E04_S02 MVCC re-encode required) — out of scope for this rectification. Tracked inline in `ingest/embedder.py:295-309` for a future ingest milestone. |
| F2 | **fixed** | `_build_singleflight_key` rewritten to length-prefix encoding (8-byte big-endian unsigned-long prefix per field). Collision-free regardless of chunk_id content. Existing tests still pass; `test_key_invariant_to_candidate_order` continues to validate the sort behavior. |
| F3 | **fixed** | Deleted `RerankerLoadError` class. Removed from `server/retrieval/__init__.py` `__all__` + the module's `__all__`. The `_load_reranker_or_raise` already wraps `Exception` as `RerankerUnavailableError` directly — no intermediate class needed. |
| F4 | **fixed** | `_fetch_body_texts` now uses `_escape_lance_str` (single quote → doubled) instead of dropping chunk_ids with quotes. Mirrors the project-wide pattern from `server/handlers/chunk.py:120` and `server/handlers/paper.py`. The helper is duplicated locally with a "DRY-WAIVED" comment to avoid a layering inversion (retrieval phase importing from a handler). Updated `test_quote_in_chunk_id_dropped_defensively` → `test_quote_in_chunk_id_escaped_not_dropped`. |
| F5 | **fixed** | `RerankPhase.rerank` docstring extended with an explicit "Score-semantics contract" section: off-path returns RRF score (~0.01..0.05); on-path returns sigmoid logit (0..1). Documents that downstream consumers (E07_S04 wire-surface) MUST inspect `enabled` to disambiguate. Defer the normalization choice to E07_S04 where the wire decision lands. |
| F6 | **fixed** | `TestShaDriftCheck` (3 tests), `TestHuggingfaceCacheLookup` (2 tests), and `TestResourcesIntegration::test_resources_startup_populates_rerank_phase_off` all converted from manual `os.environ` mutation / direct attribute assignment to `monkeypatch.setenv` / `monkeypatch.setattr`. pytest-managed teardown now guaranteed even on KeyboardInterrupt. |
| F7 | **fixed** | Folded into F2's rewrite — the docstring no longer mentions a separator (length-prefix encoding has no separator concept). |
| F8 | **fixed** | `_FakeRerankerModel.call_count` is now actually incremented in `__call__`. `test_concurrent_identical_rerank_dedups` adds an explicit `assert model.call_count == 1` to catch the "model invoked twice but coincidentally returned same ranking" regression. |
| F9 | **fixed** | New `RerankerHandle = NamedTuple("RerankerHandle", [("model", Any), ("tokenizer", Any)])` in `server/retrieval/rerank.py`. `_load_reranker_or_raise` returns a `RerankerHandle(model=..., tokenizer=...)`. Backwards-compatible: still iterable as a 2-tuple, so the existing `model, tokenizer = self._model_handle` destructuring continues to work; a future 3rd-element addition to the NamedTuple definition will fail the destructure with a clear error. |

Suite at rectification: **920 passed, 4 skipped, ruff clean** (same count as pre-rect; F8 added one assertion; F6 refactored 6 tests in place; F4 replaced 1 test in place).

Reverify pass: F1 was attempted on the embedder too but reverted because the pinned BGE-M3 SHA doesn't ship safetensors — the rectification budget doesn't extend to a SHA bump. Documented inline. F2's length-prefix encoding empirically tested against the existing key tests (all still pass with the new byte layout, which proves the determinism property doesn't depend on separators).
