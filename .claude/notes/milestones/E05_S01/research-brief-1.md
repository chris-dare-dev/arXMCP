# E05_S01 — Research Brief 1

## 1. In-codebase context

### Applicable design notes
- **`09-feature-priorities.md`** Tier-0 exit criterion (referenced by E05).
- **`07-multi-agent-caching.md`** §"Property 2: Tool result payloads are canonicalized" + BP1 byte-stability rule (relevant for fixture file determinism).
- **`04-parsing-and-chunking.md`** for chunker output shape.
- **`08-security-observability-ops.md`** §Threat 1 — `paper_id` regex; relevant to validator input parsing.

### Chunker version + manifest (E02_S04, landed)
The single source of truth lives in `ingest/chunker_types.py`:

```
CHUNKER_VERSION = "v1.0"
```

Manifest schema written by `ingest/chunker.py::_write_chunk_manifest` (cite chunker.py docstring lines 1009–1029):

```json
{
  "chunker_version": "v1.0",
  "chunks": [{"chunk_id": "arxiv:...:<hash>", "kind": "stmt"}, ...],
  "paper_id": "2307.01156"
}
```

— **sorted JSON keys, no timestamps** (per the chunker module: "no timestamps — BP1 byte-stable"). Manifest path: `var/arxmcp/corpus/chunks/<paper_id>/chunk_manifest.json`. The validator must glob this exact location.

### `chunk_id` shape (load-bearing)
From `chunker.py::_compute_chunk_id`:
> "Return ``arxiv:<paper_id>:<sha256(preamble_text + NFC(body_text))[:16]>``."

`paper_id` regex (security gate) from `chunker.py:_PAPER_ID_RE`:
`^\d{4}\.\d{4,5}(v\d+)?$|^[a-z][a-z\-]*/\d{7}(v\d+)?$`. The validator should reject malformed `chunk_id` strings rather than silently treat them as missing; otherwise a typo in a curated fixture looks like a stale ID.

### `kind` taxonomy (load-bearing for AC)
From `chunker.py::_THEOREM_ENV_KINDS` and `chunker_types.py::ChunkRecord.kind`:
- `"stmt"` (theorem/thm).
- `"proof"` (paired or orphan).
- Plus `"lemma"`, `"proposition"`, `"corollary"`, `"definition"`, `"remark"`, `"example"`, `"claim"`, `"section"`, etc.

The AC requires "≥5 queries reference `kind="stmt"` chunks and ≥5 reference `kind="proof"` chunks". The current manifest stores `kind` per-chunk, so the validator can enforce this without re-reading any per-chunk JSON. Curators must lean on theorem/proof environments — lemmas/propositions don't satisfy the criterion as written.

### What "chunker output" looks like on disk today
**Critical finding:** `var/arxmcp/corpus/` does **not exist** in this worktree. The 50-paper seed corpus has never been ingested. The only chunker output that exists is the 10 hand-crafted goldens under `tests/fixtures/chunker/2307.0000{1..10}.expected.json` (E02_S05). The `expected.json` schema is:

```json
{"chunk_count": 4, "chunker_version": "v1.0",
 "expected_chunk_ids": ["arxiv:2307.00001:13d9aafc9c49463a", ...],
 "kind_counts": {"proof": 2, "stmt": 2}, "paper_id": "2307.00001"}
```

This is **not a `chunk_manifest.json`** — schema differs (`expected_chunk_ids` list vs `chunks: [{chunk_id, kind}]`). The validator must NOT confuse them.

### `seed-papers.txt` reality check
`tools/seed-papers.txt` lists 50 IDs like `2605.03890`, `2604.28085`, etc. — these are **fabricated future-dated arXiv IDs** (May 2026 onwards) used as placeholders by `tools/curate_seed.py`. Whether curation will be against real IDs by E05_S01 hits its tier-0 milestone is unclear; the curator (the user) is the authority here.

## 2. Prior decisions and lessons

### Conflict with the brief: `created_at` timestamp vs BP1
The milestone brief schema includes `"created_at": "2026-05-06"`. `07-multi-agent-caching.md` is unambiguous on byte-stability: "No timestamps, no random tie-breaks. JSON keys serialized in alphabetical order." The chunker honored this religiously: `_write_chunk_manifest`'s docstring literally says "no timestamps — BP1 byte-stable". `E02_S04` deferred any timestamp from manifest deliberately.

**Resolution recommendation:** the fixture is **not in the BP1 cache prefix** — it is consumed by the eval harness (E05_S02), not by the MCP server, the prompt cache, or any tool result. BP1 byte-stability applies to artifacts that flow into agent prompts. `tests/eval/fixtures/queries.json` is build-time test data, not runtime. The `created_at` field is **acceptable** but should be a fixed string (no `datetime.now()` call ever generating it). Recommend: keep it, document its inertness explicitly in `docs/eval-curation.md` ("update on schema_version bump only, not on every edit"), and never base validator output on it. **Do not** include the fixture file in any BP1-shaped artifact (e.g., do not load it server-side).

### "Implementer cannot automate the curation" — what's blocked vs what ships
The brief is explicit: "the implementer cannot automate the curation itself (that would make the eval circular)". Decomposition:

| Deliverable | Implementer can deliver? |
|---|---|
| `tools/validate_eval_fixtures.py` | **Yes** — pure tooling; no curation needed. |
| `docs/eval-curation.md` | **Yes** — process doc; the curator follows it. |
| `make test` integration | **Yes** — Makefile wiring. |
| `queries.json` with 20 real triples | **No** — blocked on the user. |
| `queries.json` **stub/skeleton** with the schema header + an empty `queries: []` | **Yes** — committable as a placeholder so the validator has a file to read. |

Recommend Phase 2 ships: validator, docs, Make wiring, **and** a stub `queries.json` containing schema header with an empty `queries` array. The validator's behavior on an empty array is the key design decision (see Open Questions). A stub avoids leaving the eval harness wedged on absent inputs in E05_S02.

### Lesson from E02_S05 ("things that always break")
E02_S05's implementation summary states: "`var/arxmcp/corpus/parsed/` is not materialized in this worktree (deferred across every prior E02 milestone)". This means **every E02/E03/E04 milestone has shipped without a real corpus run**. E05_S01's validator will inherit the same condition. Two operational modes are required:

1. **No corpus mode** (no `var/arxmcp/corpus/chunks/` exists): validate fixture schema/uniqueness/kind-counts, **skip** chunk_id existence check, exit 0 with a clear info message.
2. **Corpus mode** (one or more `chunk_manifest.json` files exist): full validation including chunk_id existence.

This is the only way the validator can run cleanly under `make test` today (where no corpus exists) AND on a real ingestion later.

### `chunker_version` consistency invariant
From `04-parsing-and-chunking.md` and the chunker module: bumping `CHUNKER_VERSION` invalidates chunk_ids. The fixture `chunker_version` field is a tripwire — when the chunker constant changes, the validator must fail loudly so the curator re-labels. Implement this as: read `CHUNKER_VERSION` from `ingest.chunker_types`, compare against `fixture["chunker_version"]`. AC item 4 requires literal `"v1.0"` today.

## 3. External sources

### TREC qrels conventions (graded relevance)
TREC's standard graded-relevance format is `query_id  iteration  doc_id  relevance`, with `iteration` typically `0` and `relevance` an integer (commonly 0–4 or 0–3). The brief's 0–3 scale aligns with NIST TREC Web Track / TREC Robust convention: **3 = highly relevant, 2 = relevant, 1 = partially/marginally relevant, 0 = not relevant**. Absent docs are graded 0 (the brief follows this). For nDCG computation in E05_S02 the `2^rel - 1` gain variant is conventional; the brief uses the plain `rel_i` form which is also TREC-canonical for nDCG@k. Recommend the validator does **not** convert to TREC qrels format — JSON is fine; conversion is E05_S02's problem.

### JSON-Schema validation idioms
Two viable approaches: (a) hand-written validator in pure Python (no `jsonschema` dep), (b) ship a JSON-Schema document at `tests/eval/fixtures/queries.schema.json` and use `jsonschema.validate()`. Pyproject already has dev deps; adding `jsonschema` is small. Recommend (a) — pure Python — because the validator does cross-file integrity checks (chunk_id existence in manifest globs) that JSON-Schema cannot express. A single Python module with `assertion`-like helpers (`assert_unique`, `assert_kind_counts`, etc.) is cleaner than mixing two validation paradigms.

### NIST 0–3 graded relevance
NIST's TREC-Web qrels use integer grades (Nav=4, Key=3, HRel=2, Rel=1, NRel=0 in some years; standard 0–3 in others). The brief's grades-vocab (3 = primary answer, 2 = direct, 1 = useful context) maps to NIST norms. No external action required.

### MCP spec irrelevance
Confirmed — no protocol surface in this milestone.

## Open questions

(a) **Is the seed corpus chunked yet?** **No.** `var/arxmcp/corpus/` does not exist in this worktree. The validator MUST handle this case gracefully. Recommend: skip-with-warning when no manifest globs match.

(b) **What does the validator do with no curated queries?** Recommend: schema-validate the empty fixture (header fields present, `queries == []`), print `INFO: queries.json contains 0 entries — curation pending`, exit 0. Do NOT exit nonzero on empty — `make test` must remain green for the implementer's deliverable. The AC item "queries.json contains exactly 20 query entries" is the curator's gate; the validator script itself should expose a flag like `--strict-count=20` that E05_S03's `make eval` (not `make test`) toggles. **Confirm with orchestrator: should `make test` or `make eval` enforce the 20-count?**

(c) **Does the validator run only when the file exists, or always?** Always — the file should be created as a stub by Phase 2. No conditional skipping based on file presence.

(d) **What does Phase 4 (rectify) look for?** Verify: validator exits 0 on empty + on corpus-absent path; validator exits non-zero with precise message on a chunk_id known not to exist (synthesize a corpus-mode test); `chunker_version` mismatch path tested; AC items 1, 2, 7 are gated behind the curator's curation pass — Phase 4 must not block these on the implementer.

## External writes the implementation will require

| type | target | why |
|---|---|---|
| filesystem write (committed) | `tests/eval/fixtures/queries.json` (stub) | satisfies E05_S02 dependency on a parseable file; curation populates it later |
| filesystem write (committed) | `tools/validate_eval_fixtures.py` | new validator script |
| filesystem write (committed) | `docs/eval-curation.md` | curation runbook (procedure, kind quotas, regen on `chunker_version` bump) |
| filesystem write (committed) | `Makefile` (edit `test:` target) | wire `python tools/validate_eval_fixtures.py` into `make test` |
| filesystem write (committed) | `tests/eval/__init__.py` + `tests/eval/fixtures/__init__.py` (or `.gitkeep`) | establish package layout |

No git push, no PR creation, no ticket, no infra mutation, no third-party API.
