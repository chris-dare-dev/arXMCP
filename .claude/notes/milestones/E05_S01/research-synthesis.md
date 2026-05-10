# E05_S01 — Research Synthesis

**Inputs:** `research-brief-1.md`, `research-brief-2.md` (both Sonnet, parallel).

Both briefs converge strongly. The few small disagreements are resolved
below with a recorded position.

---

## D1 — Scope split: implementer vs user

**Both briefs agree.** From R1: *"the implementer cannot automate the
curation itself (that would make the eval circular)"* — verbatim from the
brief. R1's decomposition table:

| Deliverable | Implementer can deliver? |
|---|---|
| `tools/validate_eval_fixtures.py` | **Yes** |
| `docs/eval-curation.md` | **Yes** |
| `make test` integration | **Yes** |
| `queries.json` with 20 real triples | **No (user-blocked)** |
| `queries.json` **stub/skeleton** with header + `queries: []` | **Yes** |

R2 confirms: *"ship validator + docs + Makefile wiring + one stub
fixture, mark curation as the user's gate."* Both note this is the
**first user-blocked milestone in the project** — every E01–E04
milestone shipped fully implemented code. The closest precedent is
E02_S05's "live-corpus sweep deferred to user verification" pattern.

**Decision:** Phase 2 ships validator + docs + pytest wrapper + stub
fixture. The 20 hand-labeled triples remain the user's gate; AC-1/2/7
flip from "implementer-blocked" to "user-blocked" at handoff.

## D2 — Stub fixture shape on initial commit

**Both briefs agree.** Ship as:

```json
{
  "schema_version": "1.0",
  "chunker_version": "v1.0",
  "created_at": "2026-05-08",
  "queries": []
}
```

R1: *"validator passes-as-no-op on empty array... a stub avoids leaving
the eval harness wedged on absent inputs in E05_S02"*. R2: *"NOT 20 stub
queries with placeholder flags (adds an invariant the validator must
respect, then must un-respect later)"*.

**Decision:** Empty `queries` array, full header. No `_curation_status`
flags, no 20 stubs.

## D3 — Validator behavior matrix

**The two briefs disagreed slightly on the partial-fixture branch.**

R1 proposed `--strict-count=20` as a CLI flag toggled by `make eval` (a
future target). R2 proposed: validator **always** runs in pytest;
behavior keys off the count of queries:

| `len(queries)` | Behavior |
|---|---|
| 0 (empty seed) | Warn, exit 0 ("curation pending"). |
| 1–19 (partial) | **Exit non-zero** (catches accidental partial merges). |
| 20 (complete) | Full validation: AC-1, AC-2, AC-3, AC-4, AC-7. |

**Pick R2's approach.** Rationale: the project doesn't have a separate
`make eval` target yet (that's E05_S03), and a CLI flag splits the
contract across two callers. R2's count-keyed behavior surfaces partial
curation as an immediate error.

The corpus-presence dimension (R1 §"No corpus mode" / R2 §"a"):

| `var/arxmcp/corpus/chunks/` | `len(queries)` | Behavior |
|---|---|---|
| empty / missing | 0 | Warn "no corpus, no queries — both pending"; exit 0. |
| empty / missing | 1+ | Exit non-zero ("fixture references chunks but no manifest exists"). |
| populated | 0 | Warn "corpus present, queries pending"; exit 0. |
| populated | 1–19 | Exit non-zero (partial fixture). |
| populated | 20 | Full validation (resolve every chunk_id against manifests). |

**Decision:** matrix above is the validator's behavior contract; mirror
it in the validator's docstring and lock it with tests.

## D4 — Where `chunker_version` is sourced

**Both briefs agree.** R2: *"The validator MUST `from
ingest.chunker_types import CHUNKER_VERSION` and compare to fixture
header — never type `"v1.0"` into validator source"*. The fixture's
`chunker_version` field is the curator's commit; the validator's job is
to confirm it matches the running chunker's `CHUNKER_VERSION`. Hardcoding
`"v1.0"` in the validator masks a `CHUNKER_VERSION` bump.

**Decision:** validator imports `CHUNKER_VERSION`. AC-4 is satisfied as
long as both fixture header and constant agree at runtime — the
literal-scan single-source-of-truth pattern from E04_S04 applies here
too.

## D5 — `created_at` and BP1

**Both briefs agree, with R1 giving the load-bearing reasoning.** R1:
*"`tests/eval/fixtures/queries.json` is build-time test data, not
runtime. BP1 byte-stability applies to artifacts that flow into agent
prompts. The `created_at` field is acceptable but should be a fixed
string (no `datetime.now()` call ever generating it)."* R2 same.

**Decision:** Keep `created_at`. Validator MUST NOT use it (no `mtime`
checks, no expiry logic). `docs/eval-curation.md` documents that the
field updates on `schema_version` bumps only, not on every edit.

## D6 — `make test` wiring style

**Disagreement, small.** R1 implies running the validator directly from
the Makefile (`python tools/validate_eval_fixtures.py`); R2 strongly
prefers a `tests/eval/test_fixtures.py` pytest wrapper that imports the
validator and `pytest.fail`s on non-zero.

R2's argument: *"inherits ruff's exclusions and the existing `make test`
invariant doesn't change"*. The current `make test` is `ruff check . &&
pytest` (Makefile:45–46) — adding a Makefile line bypasses pytest's
fixture/skip machinery (e.g., the autouse `_patched_store_stats_path`
pattern), and a developer running `pytest tests/eval` won't pick up the
Makefile call.

**Decision:** Pytest wrapper. The validator module exposes a
`validate(fixture_path: Path) -> None` entry point that raises
`AssertionError` on failure; `tests/eval/test_fixtures.py` calls it.
The CLI entry point at `tools/validate_eval_fixtures.py` is preserved
for ad-hoc / CI invocation.

## D7 — Validator implementation: pure Python, no jsonschema

**Both briefs agree.** R2: *"jsonschema is a ~150 KB pip dep with C
extensions... Recommend lightweight runtime validation in pure Python —
the schema has 6 top-level keys and 3 per-query keys; hand-coded `if
not isinstance(...)` checks are ~30 LOC, zero deps."* R1 reaches the
same conclusion via the orthogonal "JSON-Schema can't express
cross-file integrity checks" argument.

**Decision:** pure-Python validator, mirror `EmbedRecord.__post_init__`
discipline. Tests validate every error path explicitly (no schema doc
to lean on).

## D8 — `kind` quotas (AC-7)

**Both briefs agree.** R1: *"the manifest stores `kind` per-chunk, so
the validator can enforce this without re-reading any per-chunk JSON.
Curators must lean on theorem/proof environments — lemmas/propositions
don't satisfy the criterion as written."*

**Decision:** validator builds an in-memory `chunk_id → kind` map by
walking all `chunk_manifest.json` files, then asserts `≥5 stmt` and
`≥5 proof` queries (a query "references" a `kind` if any of its
`relevant_chunks` resolves to that `kind`). This check fires only in
the `len(queries) == 20` mode.

## D9 — File layout

**Both briefs agree.** Final layout:

```
tools/validate_eval_fixtures.py          # CLI entry (importable as a module)
tests/eval/__init__.py                   # empty pkg marker
tests/eval/fixtures/__init__.py          # empty pkg marker
tests/eval/fixtures/queries.json         # stub: header + queries: []
tests/eval/test_fixtures.py              # pytest wrapper (calls validator)
docs/eval-curation.md                    # curation runbook
```

R1 also flagged `tests/eval/fixtures/__init__.py`. Adopt — keeps Ruff /
mypy / tooling on the package path and is consistent with `tests/`.

## D10 — `paper_id` regex re-validation

**Only R1 raised this.** *"The validator should reject malformed
`chunk_id` strings rather than silently treat them as missing; otherwise
a typo in a curated fixture looks like a stale ID."* The chunker's
`_PAPER_ID_RE` is the source of truth.

**Decision:** validator imports / mirrors the regex; a malformed
`chunk_id` is its own error class with a clear message ("malformed
chunk_id `X` in query `qN` — expected `arxiv:<paper_id>:<16-hex>`").

## D11 — Dedup and uniqueness checks

**Both briefs agree implicitly.** AC implicitly requires: unique
`query_id`s, unique chunk_ids within a query's `relevant_chunks`,
no duplicate keys at any nesting level. Validator enforces all three.

## D12 — Test surface

Lock the validator's behavior with tests in `tests/eval/test_fixtures.py`:

1. **Empty stub fixture** — happy path, exit 0.
2. **Malformed JSON** — raises a clear error.
3. **Missing top-level key** (e.g. drop `chunker_version`) — error.
4. **Wrong `chunker_version`** (set to `"v2.0"`) — error referencing
   `CHUNKER_VERSION`.
5. **Partial fixture** (5 queries) — error "expected 0 or 20 queries".
6. **20 queries but no grade-3** — AC-2 error.
7. **20 queries but only 4 stmt-kind** — AC-7 error.
8. **20 queries with stale chunk_id** (manifest mode) — AC-3 error.
9. **20 queries, all valid** — happy path on the corpus-mode branch
    (uses synthetic `chunk_manifest.json` files in `tmp_path`).
10. **Malformed chunk_id (typo)** — D10 error.
11. **Duplicate `query_id`** — error.
12. **Duplicate chunk_id within a single query** — error.

## Open questions (residual)

- **None blocking implementation.** Both researchers raised "is the
  seed corpus chunked yet?" — answer is **no**, and the validator's
  matrix above explicitly handles that case. The validator does NOT
  cause `make test` to fail on a cold-start dev box.
- **(Confirmed): the user owns the 20-query curation.** Phase 2 cannot
  satisfy AC-1, AC-2, AC-3, AC-7 — these flip from
  "implementer-blocked" to "user-blocked" at the rectification handoff.
  Phase 4 must NOT inflate this as a CRITICAL/HIGH finding; it's the
  brief's stated invariant.

## External writes the implementation will require

Combined and deduped from both briefs:

| type | target | why | blocking? |
|---|---|---|---|
| filesystem write | `tools/validate_eval_fixtures.py` | new validator (CLI + importable module) | no (local only) |
| filesystem write | `tests/eval/__init__.py` | pkg marker | no |
| filesystem write | `tests/eval/fixtures/__init__.py` | pkg marker | no |
| filesystem write | `tests/eval/fixtures/queries.json` | stub fixture (curated content is user-blocked) | no |
| filesystem write | `tests/eval/test_fixtures.py` | pytest wrapper, locks the validator behavior matrix | no |
| filesystem write | `docs/eval-curation.md` | curation runbook | no |

**No git push, no PR, no ticket, no infra mutation, no third-party API
call, no `var/` writes.** Phase 4's external-write gate has nothing to
authorize — the milestone is purely local.

The only non-local handoff is the user's curation pass after Phase 4
lands. That happens outside the pipeline.
