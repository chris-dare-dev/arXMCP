# Research Brief — corpus-integrity-completion-e1

**Agent:** milestone-researcher (brief-1)
**Generated:** 2026-05-31T23:40:00Z

---

## In-codebase context

### Design notes that apply

- `03-ingestion-pipeline.md` — pipeline shape; `corpus-version.json` marker is written by the LanceDB write step. No constraint here conflicts with the milestone.
- `05-storage-and-indexing.md` — LanceDB MVCC: "every `write` operation on a dataset creates a new integer version"; the marker records this version. Manual symlink swaps are explicitly prohibited; `write_corpus_version_marker` is the only write path.
- `07-multi-agent-caching.md` — prompt-cache byte-stability. The WAP gate does NOT touch `server/tools.py::ALL_TOOLS` or any tool schema; `EXPECTED_TOOL_SCHEMA_SHA256` does NOT need re-pinning for this milestone.

### Gate site — `ingest/store.py` lines 931–985 (verified)

Current structure (verified by direct read):
```
lines 931–977: try: ... except Exception as exc: logger.error(...)
                # [swallow block — best-effort marker write]
line 985:       _append_store_stats(stats)
line 987:       return dataset_version
```

The try-block at line 931 opens, the `except Exception` swallow closes at line 977, and `_append_store_stats(stats)` is at line 985. The spike's CRITICAL F1 constraint is confirmed: **the WAP gate MUST be placed between line 977 (end of except) and line 985 (`_append_store_stats`)**.

Verbatim from `decision.md §3`:
> "The WAP gate is OUTSIDE the best-effort swallow's scope so its `raise RuntimeError(...)` propagates to the caller. Placing the gate INSIDE the try block (the pre-rect-F1 specification) would have the `except Exception as exc: logger.error(...)` at lines 970-976 catch the gate's own raise — a structurally non-functional gate."

The swallow at lines 970–976 logs:
```python
logger.error(
    "could not write corpus-version.json marker for version %d "
    "at %s: %s (LanceDB row write succeeded; marker is best-effort)",
    ...
)
```
This log line is the operator discriminator referenced in all three error messages of the WAP gate.

### `read_corpus_version` contract — `server/corpus.py:479–538` (verified)

```python
def read_corpus_version(
    lancedb_path: str | Path | None = None,
) -> CorpusVersionInfo | None:
```

- Returns `None` when `marker_path.is_file()` is False (absent file).
- Raises `ValueError` on `json.JSONDecodeError` (line 528) — the FM-3 truncated-atomic-rename path.
- Raises `ValueError` when `CorpusVersionInfo.from_dict(data)` fails (line 535) — malformed schema.

This matches the spike's `except ValueError` arm exactly. The `CorpusVersionInfo` dataclass has a `.chunk_count` field used in the mismatch comparison.

### Import direction — confirmed safe

`ingest/bm25_indexer.py:87`: `from server.corpus import open_chunks_table`. The new `from server.corpus import read_corpus_version` in `ingest/store.py` follows the established `ingest → server.corpus` direction. No circular dependency risk.

**`read_corpus_version` is NOT yet imported in `ingest/store.py`** — the implementer must add it to the import block.

### `target_path` in scope at gate site

`target_path = Path(lancedb_path) if lancedb_path is not None else DEFAULT_LANCEDB_PATH` is set at line 807, well before the try-block. It is in scope at the gate site and is the correct argument to pass to `read_corpus_version(target_path)`.

### `tbl` in scope at gate site

`tbl` is the live LanceDB table handle, opened at line 820–821. `tbl.count_rows()` is available at the gate site as `fresh_count`.

### `dataset_version` in scope at gate site

The corpus_version integer, set during the write, is in scope and should be included in the count-mismatch error message (per the spike's code shape).

### `seed_corpus_multi_paper` — fixture shape (verified)

`tests/_corpus_helpers.py::seed_corpus_multi_paper(lancedb_path, n_papers=3, chunks_per_paper=10)`:
- Calls `write_chunks` **N separate times** (one per paper), each with `chunks_per_paper` chunks.
- Returns the final `corpus_version` integer.
- Default 3 × 10 = 30 total chunks; each individual call writes 10 chunks.
- This is the correct multi-call shape for both the positive-path test and Mutations A/B/C/D.

**Note from adversary memory (`seed-helper-single-call-vs-claimed-per-paper-loop`):** `seed_corpus` (the OLD helper) makes a SINGLE `write_chunks` call — do NOT confuse it with `seed_corpus_multi_paper`. The e1 tests must use `seed_corpus_multi_paper` exclusively.

### `test_server_startup_integration.py` mutation pattern (verified)

The m3 mutation test at line 266–278:
```python
real_marker = store_mod.write_corpus_version_marker

def bad_marker_writer(target_path, **kwargs):
    kwargs["chunk_count"] = _CHUNKS_PER_PAPER
    return real_marker(target_path, **kwargs)

monkeypatch.setattr(
    store_mod, "write_corpus_version_marker", bad_marker_writer
)
```

The e1 Mutations A/B/C/D all follow this same pattern — patching `store_mod.write_corpus_version_marker` at the module-local binding (not a caller import alias). This is load-bearing: `write_chunks` calls `write_corpus_version_marker` at bare name inside `ingest/store.py`.

### `docs/ops/corpus-drift-runbook.md` — current structure (verified)

The runbook currently covers:
- `ArXMCPCorpusCountRowsFailed` (Symptom → Quick triage → Likely causes S1/S7 → Remediation)
- `ArXMCPCorpusUnindexedRows` (Symptom → Quick triage → Likely cause S2 → Remediation)
- Reference section for `make reconcile` (as S3 fix for `ArXMCPDegradedMode`)

**The runbook does NOT yet have a section for WAP-gate `RuntimeError` failures.** The e1 milestone adds this section in the same commit as the gate code. The existing Escalation section and See Also remain unchanged.

The doc is under `docs/ops/` — operator-facing content linked from README.md. This is the correct location; no doc-placement violation. The milestone adds to an existing operator-facing file, not a new agent-internal document.

### `ingest/re_embed.py` — two `write_chunks` calls (verified)

`ingest/re_embed.py` calls `write_chunks` at lines 528 and 558 (staging LanceDB path). Both pass `lancedb_path=staging_lancedb_path`. Since the WAP gate is inside `write_chunks`, it applies automatically to both calls without any separate wiring. This is structural coverage from variant (a).

---

## Prior decisions and lessons

### Spike-1 CRITICAL F1 finding — gate placement is non-negotiable

From `decision.md §3`:
> "ingest/store.py::write_chunks, **AFTER** the existing `try/except Exception` block at `ingest/store.py:931-977` closes, **before** the `_append_store_stats(stats)` call at line 985."

This constraint was introduced because the pre-spike specification had the gate INSIDE the try-block — the adversary critic caught this as CRITICAL F1. The decision.md is the binding corrected form; any implementation that places the gate inside the try-block reintroduces the non-functional gate.

### Adversary lesson — `seed_corpus` vs `seed_corpus_multi_paper`

Memory file `seed-helper-single-call-vs-claimed-per-paper-loop.md` documents HIGH risk: `seed_corpus` is a single-call fixture; only `seed_corpus_multi_paper` exercises the multi-call shape that the e1 gate is designed to protect. Tests using the wrong fixture pass silently against both correct and buggy code. **Use `seed_corpus_multi_paper` for ALL e1 tests.**

### Adversary lesson — vacuous discriminator tests

Memory file `vacuous-test-kept-as-documentation.md`: mutation tests that patch something no longer present become no-ops. For e1: Mutation D (stale-swallow case) patches `write_corpus_version_marker` to raise `IOError`. Verify the patch targets the module-local binding (`store_mod.write_corpus_version_marker`), not an import alias, otherwise the mutation silently no-ops.

### m3 follow-up F2-extension

m3's `state.json` records an open follow-up: "add a second mutation test that monkey-patches `server/routes/notebooks._rewrite_corpus_version_marker`." This is explicitly **OUT OF SCOPE for e1** (FM-11 per the spike's deferral list). Do not address it here.

### No conflict between spike-1 decision and current codebase

Verified: the try-block at lines 931–977 and `_append_store_stats` at line 985 match the spike's cited line numbers. No drift detected.

---

## External sources

None required. This milestone is purely in-codebase:
- No MCP server surface changes (tool schema unchanged; `EXPECTED_TOOL_SCHEMA_SHA256` not affected).
- No LanceDB API changes needed; `tbl.count_rows()` and `read_corpus_version()` already exist.
- No new dependencies.

---

## Recommendation

**Implement variant (a) marker-file readback verify as specified in `decision.md §3`, placing the gate after line 977 and before line 985, exactly as the spike's code shape shows.**

The spike's code shape in `decision.md §3` is complete and copy-pasteable with minor adaptation (add `from server.corpus import read_corpus_version` to `ingest/store.py`'s import block; the rest of the code uses `target_path`, `tbl`, and `dataset_version` which are all in scope at the gate site). Do not deviate from the three-arm structure (ValueError, None, count-mismatch).

For tests: create `tests/test_write_chunks_wap_gate.py` with 5 test functions (positive path + Mutations A/B/C/D). Use `seed_corpus_multi_paper` in every test. Use `monkeypatch.setattr(store_mod, "write_corpus_version_marker", ...)` pattern from m3 for all mutations, and add `caplog` to Mutation B to assert the swallow warning is logged.

For the runbook: add a new H2 section "WAP-gate RuntimeError (e1)" to `docs/ops/corpus-drift-runbook.md`. Cover: symptom (RuntimeError in ingest log), quick triage (check preceding "could not write corpus-version.json marker" swallow warning to distinguish swallow-induced from arithmetic regression), remediation (`make reconcile`), escalation (same as existing escalation section).

---

## Open questions

No open questions — implementation can proceed on the above recommendation. The spike is binding; all architectural decisions are resolved. The code shape is complete in `decision.md §3`.

---

## External writes the implementation will require

| type | target | why |
|---|---|---|
| `git push` | `origin main` | Land the feat + rect + chore commit triple after Phase 4 rectification |

All other work is purely local (file edits + `make test`).
