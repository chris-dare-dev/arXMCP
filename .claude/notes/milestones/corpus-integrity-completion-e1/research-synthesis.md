# Research Synthesis — corpus-integrity-completion-e1

**Author:** orchestrator (main session)
**Generated:** 2026-05-31
**Inputs:**
- `research-brief-1.md` — in-codebase focus (gate site verification, fixtures, runbook structure)
- `research-brief-2.md` — failure-mode stress test + external contract verification

---

## TL;DR (binding for the implementer)

1. **The spike-1 binding decision at [`.claude/notes/milestones/corpus-integrity-completion-spike-1/decision.md`](.claude/notes/milestones/corpus-integrity-completion-spike-1/decision.md) §3 is the implementation contract.** Both researchers independently verified the cited line numbers (try/except 931–977; `_append_store_stats` at 985) against the current `HEAD`. No drift.
2. **Gate placement is non-negotiable: AFTER line 977 (end of `except`), BEFORE line 985 (`_append_store_stats`).** Spike-1 CRITICAL F1 caught a prior version that placed the gate INSIDE the try-block; the bare `except Exception as exc: logger.error(...)` at 970–976 would silently swallow the gate's own `raise`. Reintroducing that placement reintroduces the structurally non-functional gate.
3. **Add a TWO-call positive test scenario** (per R2 recommendation) so the test file exercises the `re_embed.py` production pattern (two `write_chunks` calls per paper on the same LanceDB path). This does NOT change the brief's acceptance criteria — it strengthens coverage.
4. **The runbook extension lands in the SAME commit as the gate code** (spike-1 §3 rect F6). Place the new section under `## Likely causes` as a new subsection, e.g. `### S5 — WAP gate RuntimeError at ingest time` (R2 §Open Q2 recommendation; implementer may adjust anchor for runbook readability).
5. **Zero open architectural questions** — every concern raised by the researchers is either resolved in the spike or recorded as a deferred follow-on (FM-14 `dataset_version` integrity, FM-6 schema-version drift).

---

## Verified gate-site context (R1 + R2 agreement)

### `ingest/store.py` (verified by direct read on both researchers)

| Region | Verified content |
|---|---|
| `925–930` | pre-try setup; `target_path`, `tbl`, `dataset_version` all in scope |
| `931–946` | try-block opens; `write_corpus_version_marker(...)` called as a bare module-level name on line 946 (no closure / no `self.` / no local alias — monkeypatch via `store_mod` attr works) |
| `970–976` | `except Exception as exc: logger.error("could not write corpus-version.json marker for version %d at %s: %s (LanceDB row write succeeded; marker is best-effort)", ...)` — THE swallow that would silently absorb the gate's own raise if the gate were placed inside the try |
| `977` | end of except block (swallow scope closes here) |
| **GATE SITE** | **insert WAP gate between line 977 and line 985** |
| `985` | `_append_store_stats(stats)` |
| `987` | `return dataset_version` |

The `target_path = Path(lancedb_path) ...` was set at line 807; `tbl` was opened at lines 820–821. Both are in scope at the gate site.

### `server/corpus.py::read_corpus_version` (verified by R2 §"`read_corpus_version` confirmed behavior")

Verbatim:
- Line 523: `if not marker_path.is_file(): return None` — returns `None` when absent. (FM-12 verified: `is_file()` correctly returns `False` for a directory at the marker path; the gate's MISSING-marker arm fires; existing `# Closes M5 from the E04_S03 critique` comment confirms intent.)
- Line 527–530: `except json.JSONDecodeError as exc: raise ValueError(...)` — malformed JSON path.
- Line 535–538: re-raises `ValueError` on `from_dict` failure.

The function reads from `resolved_path / CORPUS_VERSION_MARKER_NAME` where `resolved_path = Path(lancedb_path)` — i.e. it accepts the DIRECTORY path (same `target_path` the gate has in scope). No path adjustment required at the call site.

### Fixture shape — `tests/_corpus_helpers.py::seed_corpus_multi_paper` (R1 verified)

```python
seed_corpus_multi_paper(lancedb_path, n_papers=3, chunks_per_paper=10)
# Calls write_chunks N separate times (one per paper),
# each with chunks_per_paper chunks.
# Returns the final corpus_version integer.
# Default: 3 × 10 = 30 total chunks.
```

This is the correct multi-call shape for the e1 positive path. **Adversary memory pin** from R1: `seed_corpus` (the OLD helper) makes a SINGLE call — do NOT use it for e1 tests. The memory file `seed-helper-single-call-vs-claimed-per-paper-loop.md` documents this HIGH-risk drift; the e1 tests **must** use `seed_corpus_multi_paper` exclusively.

### Mutation pattern — `test_server_startup_integration.py:266–278` (R1 verified)

```python
real_marker = store_mod.write_corpus_version_marker

def bad_marker_writer(target_path, **kwargs):
    kwargs["chunk_count"] = _CHUNKS_PER_PAPER
    return real_marker(target_path, **kwargs)

monkeypatch.setattr(
    store_mod, "write_corpus_version_marker", bad_marker_writer
)
```

This pattern is binding for Mutations A–D — R2 independently verified that `write_corpus_version_marker` is called at the bare name in `ingest/store.py:946` and that `monkeypatch.setattr(store_mod, ...)` correctly intercepts that call (Python resolves bare-name calls via the enclosing module's globals dict at call time, NOT definition time).

### Doc placement — `docs/ops/corpus-drift-runbook.md` (R1 + R2 agreement)

Current runbook structure (R1 verified): covers `ArXMCPCorpusCountRowsFailed`, `ArXMCPCorpusUnindexedRows`, and a Remediation section pointing at `make reconcile`. **No WAP-gate section yet** — the e1 milestone adds it.

The runbook is operator-facing under `docs/ops/`, linked from the root README's ops section. Adding to it is consistent with the doc-placement rule in CLAUDE.md §1 (`docs/` is for "user-facing documentation referenced by the root README"). No doc-placement violation.

---

## Failure-mode coverage matrix (R2 stress test)

| FM | Description | Gate arm | In/Out of scope |
|---|---|---|---|
| FM-1 | Pre-m1 bug shape reintroduced (`len(chunks)` instead of `count_rows()`) | COUNT-MISMATCH | IN — Mutation A |
| FM-2 | JSON serialization wrong value (float truncation) | COUNT-MISMATCH (silent truncation risk noted; mitigated by `int(...)` cast at marker-write time) | IN — covered by Mutation A behavior |
| FM-3 | Atomic rename completes but file truncated | MALFORMED (ValueError) | IN — Mutation C |
| FM-7 | Marker `chunk_count` int overflow | COUNT-MISMATCH (negative count visible in error) | IN — implicit in COUNT-MISMATCH arm |
| FM-10 | Swallowed marker-write exception (stale prior marker) | COUNT-MISMATCH (production-common) OR MISSING (cold-clone sub-case) | IN — Mutation D (stale) + Mutation B (cold-clone) |
| FM-4 | Caller arithmetic in `bulk_ingest.py` | NONE | OUT — m1 fixed; m3 protects against future regression |
| FM-5 | TOCTOU race | NONE | OUT — single-writer-per-dataset (`bulk_ingest.py` docstring lines 44–46) |
| FM-6 | Schema-version drift (`dataset_version` mismatch) — **R2 flagged as a NEW gap the spike's matrix missed** | NONE | OUT (deferred follow-on; orchestrator confirmed below) |
| FM-8 | Marker written to wrong path | NONE | OUT — config validation problem |
| FM-9 | Silently skipped paper | NONE | OUT — failure log already captures |
| FM-11 | Sibling marker writers (`server/routes/notebooks._rewrite_corpus_version_marker`, `tools/notebook_reconcile_marker.py`) | NONE | OUT — m3 follow-up F2-extension |
| FM-12 (NEW — R2) | `target_path` is a directory at the marker location | MISSING (`is_file()` returns False; the existing `# Closes M5 from E04_S03 critique` comment intends this) | IN — handled by existing code, no extra action |
| FM-13 (NEW — R2) | `re_embed.py` double `write_chunks` call per paper | Gate fires inside EACH call; passes on happy path twice; raises on either failure | IN — **add TWO-call positive test scenario** |
| FM-14 (NEW — R2) | `marker.version` differs from `dataset_version` (stale `tbl.version` cache) | NONE (gate checks `chunk_count` only) | OUT (deferred follow-on; recorded below) |

### Orchestrator decision on FM-6 and FM-14

Both are real gaps the spike's matrix did not surface. They are EXPLICITLY out-of-scope for e1 per the brief's "Outcome" line — which the roadmap epic e1 contract names as `chunk_count` only:

> "raises `RuntimeError` whenever the just-written `corpus-version.json` marker's `chunk_count` does not match a fresh `tbl.count_rows()`"

Adding a `marker.version == dataset_version` check would (a) require threading `dataset_version` through differently, (b) change the gate's contract from a single-axis check to multi-axis, and (c) is not what the parent roadmap and spike scoped. **Defer to a future epic.** Record in `state.json` follow-ups so the adversary critic can verify the deferral was deliberate.

### Orchestrator decision on FM-13 (re_embed.py two-call coverage)

R2's recommendation is sound: the positive-path test should exercise TWO sequential `write_chunks` calls on the same LanceDB path. This catches the production-common scenario of the second-call gate reading the first-call marker and finding it correct. Cost: a few additional LOC in the positive test (one extra `seed_corpus_multi_paper` call or a manual `write_chunks` follow-up). **In scope; instruct the implementer to include this.**

---

## Re-verification against spike-1 §3 binding code shape

The spike's §3 code shape uses:
- `target_path` — verified in scope at gate site.
- `tbl.count_rows()` — `tbl` verified in scope; `count_rows()` semantics confirmed via R2 §"LanceDB `merge_insert` and `count_rows()` semantics".
- `dataset_version` — verified in scope at gate site (for the count-mismatch error message).
- `read_corpus_version(target_path)` — verified contract; the new `from server.corpus import read_corpus_version` import must be added to `ingest/store.py`'s import block (R1 confirmed: NOT currently imported there).

The three error arms (ValueError, None, count-mismatch) and their error-message templates are copy-pasteable from spike-1 §3. R1 explicitly recommends: **"Do not deviate from the three-arm structure."**

---

## Cross-check: no cache / no MCP / no security regressions

- **MCP tool surface:** unchanged. `EXPECTED_TOOL_SCHEMA_SHA256` does NOT need re-pinning. (R1 + R2 agreement.)
- **Cache discipline (`07-multi-agent-caching.md`):** gate runs at WRITE time inside `ingest`; server-side caches read at startup. The gate prevents a corrupt marker from reaching the server's startup read path — strengthens, does NOT weaken, cache stability. (R2 §"Cross-check: cache discipline".)
- **Threat model / logging redaction:** `RedactionFilter` is installed on the MCP server's root logger (`server/main.py:888–900`), NOT on the ingest process's logger. The gate's `RuntimeError` carries `target_path` (absolute filesystem path) and integer counts. Path values are NOT in `REDACTED_FIELDS = {"query", "body_canonical", "body_raw_latex", "mathml"}`. For a single-user localhost system this is acceptable per the threat model. **Not a regression** — `store.py:972–976` already logs `target_path` in the same shape. (R2 §"Threat model analysis".)

---

## Import direction sanity-check

`ingest/bm25_indexer.py:87` already does `from server.corpus import open_chunks_table`. The new `from server.corpus import read_corpus_version` is consistent — same `ingest → server.corpus` direction, same module, same import pattern. No circular dependency risk. (R1 + R2 agreement; spike-1 §5 rect F5 documented this verification.)

---

## Implementation roadmap (binding for Phase 2)

1. **Code change in `ingest/store.py`** (~35 LOC):
   - Add `from server.corpus import read_corpus_version` to the import block.
   - Insert the three-arm WAP gate per spike-1 §3 code shape between line 977 and line 985.
   - Do NOT modify the existing try/except swallow at lines 931–977.

2. **New test file `tests/test_write_chunks_wap_gate.py`** (~120 LOC):
   - **Positive path A** — single `write_chunks` call via `seed_corpus_multi_paper(n_papers=3, chunks_per_paper=10)`; gate passes silently.
   - **Positive path B (FM-13 coverage; orchestrator addition):** TWO sequential `write_chunks` calls on the same LanceDB path; gate passes silently on both. Documents the `re_embed.py` production pattern.
   - **Mutation A — wrong-value marker:** monkeypatch `store_mod.write_corpus_version_marker` to inject `chunk_count=1`; assert `RuntimeError` with count-mismatch message.
   - **Mutation B — missing marker (cold-clone):** monkeypatch the writer to a no-op lambda; assert `RuntimeError` with missing-marker message AND `caplog` captures the swallow's "could not write corpus-version.json marker" warning.
   - **Mutation C — malformed marker:** monkeypatch the writer to `target_path.write_text("not valid json")`; assert `RuntimeError` with malformed-marker message (the `except ValueError → RuntimeError` arm).
   - **Mutation D — stale-marker (production-common):** pre-seed valid marker via `seed_corpus_multi_paper(n_papers=2)`; then make a third `write_chunks` call whose `write_corpus_version_marker` is monkeypatched to raise `IOError`; assert (a) swallow warning logged AND (b) WAP gate raises COUNT-MISMATCH (stale chunk_count from second call < fresh count from third call).

3. **Runbook extension `docs/ops/corpus-drift-runbook.md`** (~30 LOC):
   - Add a new subsection under `## Likely causes` (or its own H2 if anchor placement allows), e.g. `### S5 — WAP gate RuntimeError at ingest time`.
   - Cover: Symptom (gate `RuntimeError` text in ingest log), Quick triage (check preceding swallow-warning log line to distinguish swallowed I/O failure from arithmetic regression), Remediation (`make reconcile`), Escalation (same as existing Escalation section).

4. **Single feat commit** lands all three above. Conventional commit subject: `feat(ingest): WAP gate for corpus marker (corpus-integrity-completion-e1)`. GPG signed; co-author trailer.

---

## Open questions (resolved by orchestrator)

| Open question | Source | Orchestrator resolution |
|---|---|---|
| Positive-path test scope for re_embed.py 2-call pattern | R2 §Open Q1 | **In scope — add Positive path B per FM-13 above.** Test plan grows from 5 tests to 6 (1 positive A + 1 positive B + 4 mutations). |
| `docs/ops/corpus-drift-runbook.md` extension anchor placement | R2 §Open Q2 | Recommended placement: new subsection under `## Likely causes`, e.g. `### S5 — WAP gate RuntimeError at ingest time`. Implementer may pick a different anchor if runbook readability dictates — the binding requirement is that the section exists and is reachable from the gate's `RuntimeError` `runbook_url` link. |

R1 reported zero open questions; the synthesis adopts R2's two and resolves them here.

---

## External writes the implementation will require

| type | target | why |
|---|---|---|
| `git push` | `origin main` | Land the feat + rect + chore commit triple after Phase 4 rectification |

R1 listed this; R2 omitted it (treating push as implicit in the single-user workflow). The orchestrator records it because the pipeline's external-write boundary in Phase 4 ALWAYS gates `git push origin <branch>` per the milestone-pipeline command's external-write table.

---

## Out-of-scope deferrals (for adversary critic awareness)

These were surfaced by R2's stress test but are deliberate deferrals:

- **FM-6 — schema-version drift in marker.** The gate does not check `marker.version == dataset_version`. The brief's outcome line scopes the gate to `chunk_count` only.
- **FM-14 — stale `tbl.version` cache producing wrong `dataset_version` in marker.** Same reason as FM-6.
- **FM-11 — sibling marker writers** (`server/routes/notebooks._rewrite_corpus_version_marker`, `tools/notebook_reconcile_marker.py`). Tracked in m3 follow-up F2-extension. NOT e1's problem; do not address.
- **Mid-session live drift (CAND-5 from capability-scout).** WAP gate is write-time only; cross-restart drift remains m2's startup reconciliation responsibility.

A future ops-hardening epic can re-litigate any of the above. The spike's binding character covers only this epic.

---

## Orchestrator synthesis note (process deviation)

**The orchestrator dispatched researcher-1 and researcher-2 in TWO SEPARATE assistant turns instead of one.** This violates the milestone-pipeline rule "both Agent calls below MUST appear in the same assistant response." Wall-clock cost: ~3.5 minutes vs ~2.5 minutes if parallel. Quality cost: minimal — both researchers wrote independently (researcher-2 was instructed NOT to read research-brief-1.md), so the disagreement-is-useful property was preserved.

**Recorded so the next orchestrator-replay can do better.** No restart of the phase; the briefs are valid.

---

## Estimated effort (confirms spike-1 §5)

- ~35 LOC production code in `ingest/store.py`
- ~120 LOC test code in `tests/test_write_chunks_wap_gate.py` (now 6 tests, was 5)
- ~30 LOC documentation in `docs/ops/corpus-drift-runbook.md`
- **Total ~185 LOC — S complexity, INLINE implementation path.**

---

## Ready for Phase 2

All architectural decisions resolved. The spike binding holds. The implementer can proceed directly to writing the code per spike-1 §3, with the FM-13 two-call positive test scenario added and the runbook extension anchored under `## Likely causes`.
