# Research brief-2 (GENERAL role) — evidence-engine-spike-1

**Milestone:** Labeling-pace dry run — first 5 queries (spike, parent `evidence-engine-e1`)
**Roadmap:** `plans/evidence-engine/roadmap.yaml`
**Role:** general — codebase context, external deps, external-writes list
**Method:** read-only; all claims cited `file:line`; live arxmcp server + on-disk `var/` probed.

---

## TL;DR for the owner

- The dry run measures **pace only**. It does NOT need `validate_eval_fixtures.py` to report
  `status=complete` (5 queries hits the "partial fixture" error path anyway). Label into a
  **scratch file**, not `tests/eval/fixtures/queries.json`.
- The lowest-friction "see ranked candidates to judge" tool that exists TODAY is the
  **already-running arXMCP MCP server** (`search_papers`), which I confirmed serves the
  bridgeland-stability corpus (`corpus_version 4454`, 145 papers, 15,106 chunks). No new script needed.
- Two real friction findings that belong to m1, surfaced here so pace isn't mis-measured:
  1. **`search_papers` cannot surface `kind="proof"` chunks** (`retrieval_mode:"dense_only"`,
     `excluded_kinds:["proof"]`) — but the fixture's AC-7 needs ≥5 proof-kind anchors. Proof
     anchors must be found by reading `chunk_manifest.json` directly, which is slower per-query.
  2. **The validator silently ignores all 25 old-style (`math/NNNNNNN`) paper manifests** — a
     grade-3 anchor from e.g. `math/0212237` (Bridgeland's foundational paper) would FAIL AC-3.
     Prefer new-style (`YYMM.NNNNN`) paper anchors, or fix the validator in m1.
- **External writes required: NONE.** (`external_writes_required: []`)

---

## Q1 — Fixture format & validator completeness rule

### Schema of a single labeled query
Top-level file (`.claude/docs/eval-curation.md:139-155`, enforced by
`tools/validate_eval_fixtures.py:335-397`):

```json
{
  "schema_version": "1.0",            // literal "1.0" (validate_eval_fixtures.py:365)
  "chunker_version": "v1.1",          // MUST equal ingest.chunker_types.CHUNKER_VERSION (:370)
  "created_at": "2026-05-08",         // ISO-8601 YYYY-MM-DD (:388, _ISO_DATE_RE :155)
  "queries": [ ... ]                  // list; 0 (seed) or exactly 20 (complete)
}
```
Exactly these 4 top-level keys — **unknown top-level keys are rejected**
(`validate_eval_fixtures.py:358-364`). The on-disk seed is `{"queries": []}` with
`chunker_version:"v1.0"` (`tests/eval/fixtures/queries.json:1-6`) — note the seed still says
`v1.0` while the running chunker is **`v1.1`** (bridgeland marker confirms
`"chunker_version": "v1.1"`), so on first real curation the file's `chunker_version` must be
bumped to `v1.1` or the validator's AC-4 check fails (`:370-378`; runbook `eval-curation.md:33-40`).

Per-query object (`validate_eval_fixtures.py:400-473`):
```json
{
  "query_id": "q01",                   // non-empty str, unique in file (:418, :502)
  "query_text": "…",                   // non-empty str (:423)
  "relevant_chunks": [                 // non-empty list (:428)
    {"chunk_id": "arxiv:2504.12253:899c2891fdfdf1a9", "relevance": 3}
  ]
}
```

### Graded-relevance scale
**0–3 integers** (`_VALID_RELEVANCE_GRADES = (0,1,2,3)`, `validate_eval_fixtures.py:159`;
grade table in `eval-curation.md:115-120`). `bool`/floats/`4+` rejected (`:458-467`). Grade-3 =
"primary answer"; grade-0 chunks are **omitted, not listed** (`eval-curation.md:120,127-129`).

### How judgments are attached
**By `chunk_id`**, as a `{chunk_id, relevance}` list per query (a qrel list). `chunk_id` is the
content-addressable `arxiv:<paper_id>:<16-hex>` string, copied verbatim from a manifest
(`eval-curation.md:161-163`). `_CHUNK_ID_RE` = `^arxiv:(<paper_id>):[0-9a-f]{16}\Z`
(`validate_eval_fixtures.py:142-148`). There is **no** paper_id-level or qrel-by-paper mode — the
graded eval is chunk-level (contrast the notebook-local paper-level `queries.json`, see Q3).

### Exact completeness rule (verbatim behavior matrix)
From the validator docstring (`validate_eval_fixtures.py:28-44`) and `validate()` (`:546-644`):

| `len(queries)` | `corpus/chunks/` manifests | Behavior |
|---|---|---|
| 0 | 0 | warn "both pending", **exit 0**, `mode="seed"` |
| 0 | ≥1 | warn "queries pending", **exit 0**, `mode="seed"` |
| 1–19 | any | **ERROR** "expected 0 or 20 queries" (`:617-625`) |
| 20 | 0 | ERROR "no manifests" (`:629-634`) |
| 20 | ≥1 | full validation → `mode="complete"` (`:636-644`) |

`status=complete` (i.e. `ValidationResult.mode == "complete"`) requires **all** of:
- exactly `TARGET_QUERY_COUNT = 20` queries (`:94`, `:617`);
- header valid (schema_version `1.0`, `chunker_version == CHUNKER_VERSION`, ISO `created_at`, no
  extra keys) (`:335-397`);
- every query has ≥1 **grade-3** chunk (AC-2, `:508-513`);
- every `chunk_id` resolves in a discovered `chunk_manifest.json` (AC-3, `:515-525`);
- ≥5 queries reference a `kind="stmt"` chunk AND ≥5 reference a `kind="proof"` chunk
  (AC-7, `MIN_QUERIES_BY_KIND = {"stmt":5,"proof":5}` `:99`, checked `:530-538`);
- unique `query_id`s (`:502-506`).

**There is no intermediate "incomplete" status token.** The validator returns `mode ∈
{"seed","complete"}` or raises `FixtureValidationError`. The roadmap's phrase "status=complete"
maps to `mode == "complete"`. **5 queries can never reach it** — they hit the 1–19 error branch.
This is why the dry run must use a scratch file.

---

## Q2 — Labeling runbook (`.claude/docs/eval-curation.md`)

Owner protocol, per query (`eval-curation.md:104-132`):
1. **Write `query_text` first** — do NOT scan chunks and back-form a query (biases the eval
   toward the system's own phrasing) (`:105-109`).
2. **List every chunk you'd expect in a perfect top-10** — "most queries have 1–3 relevant
   chunks; some more" (`:110-112`). This is the pooling method: **owner-recall pooling from
   domain knowledge**, NOT depth-k pooling of a retrieval run. The runbook does not prescribe
   running the retriever to build the candidate pool (see Q3 for why that matters).
3. **Grade each 0–3** (`:113-120`): 3 = primary answer / the actual statement; 2 = direct
   addressee (e.g. proves a corollary of it); 1 = useful one-click context; 0 = not listed.
4. **Each query MUST have ≥1 grade-3** (AC-2) or the query is "not curatable against this
   corpus — pick a different query" (`:122-126`).
5. **Do not include zero-relevance chunks** — inflates the set, corrupts Recall@10 (`:127-131`).

Scale = **0/1/2/3** (`:113-120`). Candidate count per query = **whatever the owner judges
relevant (typ. 1–3)**, not a fixed pool depth (`:110-112`). Kind quotas (AC-7): ≥5 queries →
`stmt`, ≥5 → `proof`; "plan queries against the kind distribution before labeling" (`:94-101`).

**LLM bar (verbatim):** *"the implementer cannot automate the curation itself (that would make
the eval circular)"* (`:9-13`); roadmap `wont` list: *"No LLM-assisted or LLM-judge grading …
every graded label is owner-authored"* (`roadmap.yaml:45`). Every graded label is owner-authored.

**Runbook/corpus mismatch to flag:** the runbook's illustrative topic list is math.AG classics —
Riemann-Roch, Serre duality, Picard group, Hilbert scheme (`:76-91`). The **locally-ingested
corpus is bridgeland-stability** (derived categories, K3 surfaces, stability conditions, t-structures)
— those example queries are largely NOT curatable here. The owner must draw queries from the
actual bridgeland content (Q6), not the runbook's examples. This does not change the protocol,
but the pace estimate should be built on bridgeland-topic queries.

---

## Q3 — Labeling mechanism available TODAY

The fancy static-HTML report (`evidence-engine-t-labeling-report-script`, roadmap m1) does
**not exist yet** (it's a `now`-lane sibling task, `roadmap.yaml:196-208`). What exists today:

### The eval harness itself does NOT dump candidates
`tests/eval/test_retrieval_quality.py` reads the fixture, runs retrieval, and **scores** it — it
never renders candidates for judging (`:120-232`). Worse, it can't even run today: it pins to
`read_corpus_version()`/`open_chunks_table()` at **`DEFAULT_LANCEDB_PATH = var/arxmcp/index/lancedb`**
(`ingest/store.py:126`), which is **ABSENT on this box** (verified). The ingested data lives
**per-notebook** at `var/arxmcp/notebooks/bridgeland-stability/lancedb/` (marker confirms
`version 4454`, 145 papers, 15,106 chunks). So `make eval` today → `pytest.skip("corpus not
ingested")` (`test_retrieval_quality.py:188-192`). Fixing that path is m1's job, not the dry run's.

### Lowest-friction path today: the already-running arXMCP MCP server (`search_papers`)
**Confirmed live this session.** `arxmcp://notebooks` lists `bridgeland-stability` (+ `-pdfs`,
`fourier-duality`, etc.). A `search_papers` call returned real bridgeland chunks with envelope
`{"corpus_version":4454,"retrieval_mode":"dense_only","excluded_kinds":["proof"],"embed_model":"bge-m3"}`
and `arxiv:<paper_id>:<16-hex>` chunk_ids — **exactly the fixture's `_CHUNK_ID_RE` shape**, copy-pasteable.

This is the recommended dry-run mechanism because it is zero-setup and returns
ranked, judgeable, copy-paste-ready chunk_ids + snippets + section paths + `label` fields.
Two ways to drive it:

- **Operator console (mouse-only):** `make up` (must `unset ARXMCP_CONTACT_EMAIL` first — the
  server rejects it, `CLAUDE.md §9`), then the loopback console at `http://127.0.0.1:7733/ui/`
  (`CLAUDE.md §6`). Search surface caveat: `/ui/` is notebook-management; the primary search is
  the MCP tool surface, so an agent driving `search_papers` on the owner's behalf and pasting a
  ranked list is the least-friction console for pure labeling.
- **MCP tool directly (what I used):** `search_papers(query, k=10)` → ranked chunk_ids; then
  `get_chunk(chunk_id)` for full body when the 150-char snippet is not enough to grade.

Concrete per-query loop for the dry run:
```
# server already running against the bridgeland notebook (corpus_version 4454)
search_papers(query="<owner query text>", k=10)      # returns ranked candidate chunk_ids
get_chunk(chunk_id="arxiv:2504.12253:899c...")        # full body to confirm a grade-3
# owner records {chunk_id, relevance} rows into a scratch .json, timing each query
```

### If the owner wants a pytest-driven / no-server path
A throwaway script can point the harness primitives at the notebook explicitly:
`server.corpus.open_chunks_table(lancedb_path="var/arxmcp/notebooks/bridgeland-stability/lancedb",
version=4454)` + `server.query_encoder.encode_query(text)` + dual-column ANN, mirroring
`_run_queries_against_corpus` (`test_retrieval_quality.py:240-323`). This is more setup than the
running server and reproduces logic that already exists — **not recommended for a pace dry run**;
noted only because it is the fallback if the server is down.

### Two mechanism-level friction facts that affect pace (belong to m1, surfaced now)
1. **Proof chunks are unretrievable via `search_papers`** (`excluded_kinds:["proof"]`, hard-coded
   at `server/handlers/search.py:711` per D9.md:8,70; also v1 "indexes statement chunks only",
   tool description). AC-7 needs ≥5 **proof-kind** anchors. Those must be found by reading
   `var/arxmcp/corpus/chunks/<paper_id>/chunk_manifest.json` (lists every chunk_id + `kind`) and
   opening the chunk body file (`eval-curation.md:62-66`). Proof-anchored queries are therefore
   **materially slower per query** than stmt-anchored ones — the dry run's 5 queries should
   include at least one proof-anchored query so the extrapolation isn't optimistic.
2. Retrieval is **dense-only**; `--hybrid`/`--rerank` are opt-in and not what the owner sees in
   `search_papers` today. Fine for labeling (labels are retrieval-independent by design,
   `eval-curation.md:105-109`), but the owner should judge against domain knowledge, not the
   dense ranking.

---

## Q4 — Locally-ingested corpus on THIS Windows workstation

On-disk `var/arxmcp/`:

- **Notebooks** (`var/arxmcp/notebooks/`): `bridgeland-stability`, `bridgeland-stability-pdfs`,
  `fourier-duality`, `fourier-duality-pdfs`, `demo-nb`. Live server also reports a `my-notebook`.
- **`bridgeland-stability` — the labeling target. PRESENT and substantial.**
  `lancedb/corpus-version.json` = `{"version":4454, "paper_count":145, "chunk_count":15106,
  "chunker_version":"v1.1", "embedder_version":"bge-m3@5617a9f6"}`. Seed list
  `notebooks/bridgeland-stability/papers.txt` (foundational Bridgeland papers: `math/0212237`,
  `math/0307164`, K3/moduli/wall-crossing papers `0708.2247`, `1203.4613`, `1301.6968`,
  `1106.5217`, plus recent `2303.07061`, `2411.18554`, `2505.03433`, …). This is the corpus the
  running server serves (`corpus_version 4454` matches).
- **`fourier-duality`**: PRESENT, smaller (`lancedb/` + `documents.db` 28 KB; papers.txt ~1.3 KB).
  A viable *secondary* notebook if the "notebook" slice axis (evidence-engine-e2) needs a second
  source, but bridgeland alone is plenty for a 20-query fixture.
- **Shared `var/arxmcp/corpus/chunks/`**: 197 `chunk_manifest.json` files (172 new-style + 25
  old-style `math/NNNNNNN`). This is what the **validator** resolves chunk_ids against
  (`CHUNKS_DIR`, `validate_eval_fixtures.py:91`). I confirmed the served papers
  (`math/0411613`, `2510.22432`, `2504.12253`, `2006.00756`) all have manifests here — so
  chunk_ids from the live server DO have backing manifests. **See the old-style caveat in Q1/Q6.**
- **Shared `var/arxmcp/index/lancedb/`**: **ABSENT** — the reason `make eval` skips today (Q3).
- `var/arxmcp/ops/eval/`: empty (no eval has ever run — consistent with the never-measured era).

**bridgeland-stability is present, rich (145 papers / 15,106 chunks), and sufficient.** The
20-query fixture is fully curatable from it. **No macOS-only `shimura-varieties` sync is required**
(the `should`-tier assumption `roadmap.yaml:26-28` holds; D9.md open-question #8 is moot for
curation content). Recommendation: draw all dry-run queries from **bridgeland-stability**.

---

## Q5 — D9-R02 paired-comparison floor (AC2 fallback)

**What D9-R02 needs** (`plans/evidence-engine/roadmap.yaml:75-85` epic e2; `_pipeline/.../D9.md:74-79`):
additive `slice` tags + a `--compare BASELINE.jsonl` mode computing **paired bootstrap CIs /
t-tests on per-query nDCG deltas**, per-slice. It is "built now against the reduced ~20-query
fixture" (`roadmap.yaml:78`).

**Is there a hard mathematical floor?** **No — the source gives no hard floor for the paired
machinery itself.** What it gives is an *effect-size detection* floor for the nearest real
decision:
- D9-R02 / G2 (`D9.md:18,77`): the nearest real decision — **hybrid re-open at ≥0.10 absolute
  lift** (`plans/proof-verify-handler-wiring-roadmap.md:196,203`) — is **"detectable at n≈30–50
  with paired tests"**; conventional topic-set size is 50–100 (Sakai), and **only drift-at-5%
  needs ~100**.
- The watchdog encodes the project's own hard minimum: **`min 10 queries`**
  (`ops/watchdog_eval.py:70`) and a 10% (not 5%) threshold because *"5% is below the noise floor
  at 20 queries"* (`:72-75`, per `D9.md:10,76`).

**Defensible reading for AC2's "smallest n that still supports D9-R02's paired-comparison math":**
- The paired bootstrap + paired t-test are *arithmetically valid* for any n≥~2, but only
  *meaningful* (CIs narrow enough to be worth reporting) around **n≈12–15**; below the watchdog's
  **n=10 hard floor** the instrument is not worth computing.
- The roadmap's **design target is n=20** (`validate_eval_fixtures.py:94`; `roadmap.yaml:78`), and
  the **decision-grade** target is **n≈30–50**, grown *opportunistically* later (via D9-R05 mined
  traffic + D9-R15 auto-pairs), explicitly **not** in this milestone (`roadmap.yaml:44,78`;
  `D9.md:76`).

**Recommendation for AC2:** if the extrapolated full-fixture time exceeds ~2 owner-days, cut
toward **n≈12–15** (keeps the paired machinery meaningful and above the watchdog's n=10 floor),
**not below ~10**, and record that the ≥0.10-lift *decision* still needs n≈30–50 reached later by
opportunistic growth. Do **not** cut to satisfy a shorter budget by dropping below n≈12 — that
would make D9-R02's per-slice paired CIs uninformative. (The source states no exact integer;
n≈12 is the defensible minimum synthesized from watchdog n=10 + "meaningful paired CI" practice.)

---

## Q6 — 5 candidate queries from bridgeland-stability content (owner to accept/replace)

All anchors below were returned by the **live `search_papers` this session** against
`corpus_version 4454`; snippets/labels are real. Grades are my *guesses* — the owner authors the
real grade (anti-circularity). Anchors marked **stmt** carry a Definition/Theorem/Lemma `label`
or section; the owner must still confirm the chunk `kind` (via manifest) for AC-7. Slice axes per
evidence-engine-e2: topic × phrasing × stmt/proof × notebook (all bridgeland-stability here).

| # | query_text (phrasing style) | axis | candidate grade-3 anchor(s) | rationale |
|---|---|---|---|---|
| 1 | "A pre-stability condition on a triangulated category is a pair (Z, P)" (formal / LaTeX-shaped) | topic=definition, stmt | `arxiv:2504.12253:899c2891fdfdf1a9` (label `[Bri07, Definition 5.1]`) | The canonical Bridgeland definition, statement chunk, **new-style paper** (validator-safe). Anchors the "definition" topic + stmt-kind quota. |
| 2 | "wall-crossing behavior of Bridgeland moduli spaces on K3 surfaces" (mid-formal) | topic=wall-crossing | `arxiv:1106.5217:1d915c67a43455f3`, `arxiv:1106.5217:1139a81f9be30959` (both §"3. The wall crossing behavior") | Core wall-crossing content; new-style; two candidates lets the owner grade 3 + 2/1. |
| 3 | "stratification of the moduli of Bridgeland stable objects for a primitive Mukai vector" (formal) | topic=moduli, stmt | `arxiv:2505.19890:98add59ae7f620c0` (§"5. Stratification …", "main result of this section") | A theorem-statement chunk on moduli stratification; new-style; recent paper (phrasing diversity vs the classics). |
| 4 | "a bounded t-structure is determined by its heart" (fragment / lemma) | topic=t-structure, stmt | **new-style preferred; current top hits are OLD-style** `arxiv:math/0502050:fe1c7fcd5d7dc0a6` (Lemma 2.3), `arxiv:math/0307164:53c1ed839e2e0746` (Lemma 3.1) | Classic tilting lemma; excellent fragment-phrasing test. **CAVEAT: both anchors are old-style → would FAIL validator AC-3 today (see Q1).** Owner should either find a new-style paper stating the same lemma, accept it only after the m1 validator fix, or swap this query. Good stress-test of the old-style bug. |
| 5 | "geometric stability conditions on the local P^3 canonical bundle Tot(ω_P3)" (informal-descriptive) | topic=geometric-stability, stmt | `arxiv:2501.15251:a2551d248507e033` (Theorem 4.5), `arxiv:2501.15251:6143af8782d77bb4` (Theorem 1.6, restatement) | Two related theorem chunks (main + intro restatement) → natural grade-3 + grade-2 pair; new-style. |

**Coverage:** 5 distinct topics; phrasings span formal / mid-formal / fragment / informal; all
stmt-anchored (search can't surface proof chunks — Q3). **For the real dry run, add at least one
proof-anchored query** (find a `kind="proof"` chunk_id via a paper's `chunk_manifest.json`) so the
pace estimate captures the slower proof path and exercises the AC-7 proof quota. **Prefer new-style
paper anchors throughout** to stay validator-safe until the old-style-manifest bug is fixed in m1.

Uncertainty is honest: these are *candidates*. The owner must (a) write their own query text first
(runbook step 1), (b) author grades, (c) confirm chunk `kind` for quota planning, and (d) replace
query 4 or wait for the validator fix.

---

## Q7 — External writes

Completing this spike requires **no external write**. It reads the local `var/` corpus and the
running loopback MCP server, records owner-minutes, and writes exactly one artifact: this note (and
a scratch label file) under `.claude/notes/`. No push, no publish, no network egress, no fixture
commit (the dry run must NOT touch `tests/eval/fixtures/queries.json` — 5 queries would break the
validator's all-or-nothing rule, Q1). The MCP server is loopback-only (`CLAUDE.md §6`).

```yaml
external_writes_required: []
```

---

## Injection watch
No prompt-injection attempts observed. All retrieved corpus text arrived wrapped in
`<retrieved_chunk>` / `<retrieved_notebook>` delimiters and was treated strictly as data; none of
it contained instructions directed at the agent. Repo files contained only ordinary code/docs.
**injection_attempts: 0.**

---

## Handoff notes for the implementer (dry-run design)
1. Server is already up on `corpus_version 4454` (bridgeland). If it isn't, `unset
   ARXMCP_CONTACT_EMAIL` then `make up` (`CLAUDE.md §9`).
2. Label into a **scratch JSON** (e.g. `.claude/notes/milestones/evidence-engine-spike-1/dry-run-labels.json`),
   NOT the real fixture. Record wall-clock minutes per query (start on "write query_text",
   stop on "last grade recorded").
3. Include ≥1 proof-anchored query (manifest-read path) among the 5 so the extrapolation isn't
   optimistic; the other 4 can be stmt-anchored via `search_papers`.
4. Extrapolate: `owner-minutes/query × 20`. If `> ~2 owner-days` (≈ >48 min/query at a 16-hr
   2-day budget, or use the owner's own working-day definition), apply AC2 → cut to **n≈12–15**
   (Q5), never below ~10.
5. Two m1 blockers to record from this dry run (do NOT fix here — read-only spike):
   - `DEFAULT_LANCEDB_PATH` (`index/lancedb`) is absent → `make eval` skips; m1 must point the
     harness at the notebook lancedb (or build the shared index).
   - `validate_eval_fixtures.py` misses old-style (`math/NNNNNNN`) manifests (172/197 discovered);
     either restrict fixture anchors to new-style papers or fix the glob in m1.
