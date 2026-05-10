# E09_S01 Research Synthesis

**Milestone:** Kùzu schema migrations + OpenAlex bulk ingest (math.AG / math.NT).
**Inputs merged:** [research-brief-1.md](research-brief-1.md), [research-brief-2.md](research-brief-2.md).
**Date:** 2026-05-10.

The two researchers agreed on most structural choices but **disagreed on
two upstream-vendor facts** that change the implementation. Researcher 1
verified vendor state live; researcher 2 worked from prior knowledge.
Where they conflict on a checkable fact, R1's live verification wins
and is the recorded recommendation. Where they offered different
opinions on tradeoffs, both positions are surfaced and a pick is made
with reasoning.

---

## 1. Two CRITICAL upstream-spec problems the brief did not anticipate

These are blocking-quality findings — the brief literally cannot be
implemented as written without resolving them. They are NOT optional
discussion items.

### 1.1 Kùzu was archived 2025-10-10

> R1, verbatim: *"Kùzu was archived on 2025-10-10. The Register, BigGo
> News, and the GitHub banner all confirm. Quote
> (`https://github.com/kuzudb/kuzu`): 'Kuzu is working on something new!
> We are archiving the KuzuDB project here…' The final stable release
> is **v0.11.3 (October 10, 2025)**. PyPI package `kuzu==0.11.3`
> remains installable."*

R2 wrote `kuzu>=0.7,<0.8` from older knowledge ("the project did not yet
ship 1.0 GA in 2025"); this is contradicted by R1's live verification.

**Resolution (RECOMMENDED):**

- Pin **`kuzu==0.11.3`** in `pyproject.toml` runtime deps. Exact pin,
  not a range — the upstream is frozen.
- Add a one-line module-docstring note in `ingest/kuzudb_schema.py`:
  *"Kuzu archived 2025-10-10; pinned to v0.11.3 (last stable, MIT).
  Future fork migration tracked separately."*
- Do NOT switch to a fork (Kineviz `bighorn`, `Vela-Engineering/kuzu`)
  inside this milestone — both are pre-PyPI as of 2026-05 and would
  multiply the risk surface.

### 1.2 OpenAlex concept IDs in the brief are wrong AND Concepts are deprecated

> R1, verbatim: *"Verified live against
> `https://api.openalex.org/concepts/C66938386`: returns concept
> 'Structural engineering', level 1. Not algebraic geometry. And
> `https://api.openalex.org/concepts/C15736585` returns 404."*
>
> Correct IDs (also verified live by R1):
> - **Algebraic geometry: `C68363185`** (level 2, 32,647 works)
> - **Number theory: `C169654258`** (level 2, 33,918 works)
>
> Quote, OpenAlex docs: *"Concepts are **deprecated** and have been
> replaced by Topics."*

R2 noted Concepts are deprecated but recommended *"stick with
`concepts.id` per the brief and document the deprecation as a future
migration."* — that recommendation is incompatible with R1's live
finding that the brief's specific IDs return wrong/404 results.

**Resolution (RECOMMENDED):**

- The milestone AC only requires the **seed-corpus path** (50 papers
  from `tools/seed-papers.txt`). Implement that path via direct
  per-paper resolution — concept IDs are NOT needed to satisfy any
  AC.
- Resolve each seed-corpus arXiv ID → OpenAlex Work via OpenAlex's
  arXiv-URL-as-identifier endpoint:
  `GET https://api.openalex.org/works/https://arxiv.org/abs/<paper_id>`
  (R2's mechanism). Falling back to the DOI-as-ID form
  `GET .../works/doi:10.48550/arXiv.<paper_id>` (R1's mechanism) is
  acceptable on 404; both are documented as canonical.
- For the Tier-3 category-discovery path
  (`--category math.AG math.NT`), do NOT hardcode the brief's wrong
  concept IDs. Either:
  - (a) leave the category path as a `NotImplementedError` with a
    `TODO(E11)` comment pointing at Topics (`primary_topic.id`,
    `topics.id`), or
  - (b) wire it to the **corrected** Concept IDs (`C68363185`,
    `C169654258`) AND add a docstring note that Concepts are
    deprecated.
  The integration-test AC does not exercise this path, so (a) is
  cheaper and safer. Either way, the brief's two wrong IDs MUST NOT
  appear in shipped code.
- Out of scope, but flag: the milestone brief itself should be edited
  in a follow-up to point at Topics + the correct IDs. Not a Phase-2
  deliverable; a docs-only patch in a later milestone or a
  `docs(roadmap):` commit at user request.

---

## 2. Path & schema disagreements with the design constitution

These are conflicts between the milestone brief and
`.claude/notes/05-storage-and-indexing.md` /
`08-security-observability-ops.md`. Both researchers flagged. Picks:

### 2.1 Disk path: `var/arxmcp/index/kuzudb/` (brief) vs `var/arxmcp/index/kuzu/citations.kuzu` (design notes)

Both researchers flagged. R1 recommended follow the design notes
(`kuzu/`); R2 recommended follow the brief (`kuzudb/`).

**Resolution (FINAL — flipped after Phase-2 entry):** **Follow the
design notes — `var/arxmcp/index/kuzu/`.** The original synthesis
position was "follow the brief"; that position is reversed by the
existing `Makefile:bootstrap` target which already does
`mkdir -p var/arxmcp/index/kuzu` (line 30). Three signals
align on `kuzu/`: the bootstrap, `05-storage-and-indexing.md`, and
`08-security-observability-ops.md`. Only the brief's AC text uses
`kuzudb/`. The brief is the outlier; implementing `kuzudb/` would
produce a directory the bootstrap doesn't create, contradicting the
design constitution and the existing repo state. The implementation
summary will explicitly flag the AC#1 path-name drift so Phase 3 can
score it as a documentation issue, not a correctness one.

`var/arxmcp/` is gitignored (`.gitignore` line 24: `/var/arxmcp/`) —
verified. Tests MUST use `tmp_path`, never the production path.

### 2.2 Schema shape: simple 2-table (brief) vs richer 5-table (design notes)

`05-storage-and-indexing.md` § Kùzu citation graph defines a richer
schema with `Paper`/`Author`/`Theorem` node tables and
`CITES`/`AUTHORED`/`PROVES`/`NAMED_AFTER` rel tables, with `CITES`
having `source ENUM('inspire', 'openalex', 'tex_extracted')` and a
`citation_count INT` field.

The brief's schema is `papers` + `cites` only, with `source STRING`
and `confidence FLOAT`.

R1 framed this as *"a deliberate Tier-3 simplification of the design-note
schema — not a contradiction"*; R2 framed it as a conflict and
recommended following the brief verbatim. Functionally, both arrive
at the same outcome.

**Resolution:** **Implement the brief's schema verbatim.** The
design-note schema is aspirational; the milestone scope only requires
`papers` + `cites`. Document in the schema-migration script docstring:
*"This is a Tier-3 minimal schema. The full
05-storage-and-indexing.md schema (Author, Theorem, AUTHORED, PROVES,
NAMED_AFTER) is intentionally deferred."*

### 2.3 Mailto placement: User-Agent header (brief) vs query parameter (design note + OpenAlex docs preference)

Both researchers recommended sending **BOTH** — query string
`?mailto=…` AND `User-Agent: arXMCP/0.1 (mailto:…)`. Cost is zero;
satisfies both phrasings; the AC text ("`User-Agent` header includes
`arXMCP/0.1 (mailto:...)`") stays satisfied verbatim.

**Resolution:** Send both. Re-use `tools/arxiv_fetch.py:build_user_agent()`
for the header; append `?mailto=<email>` to every OpenAlex URL
(read the email from `ARXMCP_CONTACT_EMAIL` via the same helper that
already raises if unset).

---

## 3. Implementation skeleton (de-duplicated)

Both researchers agree on the structural shape. Consolidated:

**File layout:**

- `ingest/kuzudb_schema.py` — both library (`apply_schema(path: Path) -> None`)
  and thin CLI. Idempotent via `CREATE NODE TABLE IF NOT EXISTS papers (...)`
  + `CREATE REL TABLE IF NOT EXISTS cites (...)`. Module shape mirrors
  `ingest/store.py` / `ingest/bm25_indexer.py` (the project's
  established library+CLI pattern).
- `ingest/graph_ingest.py` — CLI: `python -m ingest.graph_ingest
  --source openAlex --seed-file tools/seed-papers.txt
  --checkpoint var/arxmcp/ops/graph-ingest-checkpoint.json
  --kuzudb var/arxmcp/index/kuzudb/`. Calls `apply_schema()` before
  any insert. Two flow paths:
  - Default (`--seed-file`): per-paper resolution + reverse-mapping
    pass. Required by AC.
  - Optional (`--category math.AG math.NT`): NotImplementedError
    with TODO comment OR corrected Concept IDs (see §1.2). NOT
    required by AC.
- `tests/test_graph_ingest.py` — 5-paper fixture, `monkeypatch.setattr`
  to stub the OpenAlex HTTP layer (matching the codebase's existing
  mocking pattern; no new test deps). Asserts node count, edge count,
  and idempotency of `apply_schema`.

**Reuse, do not reinvent:**

- `tools/arxiv_fetch.py:build_user_agent()` — politeness contract
  (User-Agent + `ARXMCP_CONTACT_EMAIL` env). R1 flagged the exact line
  numbers (`24-26`, `62-75`); use the helper, don't re-derive the
  format string.
- `tools/arxiv_fetch.py:parse_retry_after()` — `Retry-After` header
  parsing. Same contract for OpenAlex 429/503 backoff.
- `tools/arxiv_fetch.py:POLITENESS_SLEEP_SECONDS = 3.0` —
  a 0.1s sleep between OpenAlex requests is the polite-pool equivalent
  (10 rps cap). Define a separate constant; keep the arXiv 3.0s
  unchanged.
- `ingest/identifiers.py:PAPER_ID_RE` — single source of truth for
  arXiv ID validation. Validate on every `paper_id` derived from
  OpenAlex BEFORE writing to Kùzu (R1's Threat-1 reminder).
- `tools/fetch_seed.py:read_seed_list()` — for reading
  `tools/seed-papers.txt`. Don't re-implement.
- `tools/fetch_seed.py` checkpoint pattern — atomic write
  (`tmp + rename`) of the entire checkpoint after each batch. Brief
  AC says "after each batch of 100 papers"; `fetch_seed.py` writes
  per-paper. Pick the brief's batch=100 (it's an explicit AC) but
  use the atomic write idiom from `fetch_seed.py`.
- HTTP layer: **stdlib `urllib.request` only.** Both researchers
  confirmed — no `httpx`/`requests`/`aiohttp` is in `pyproject.toml`,
  and adding one would be unauthorized scope creep.
- Mocking pattern: `monkeypatch.setattr` on the script's HTTP fetch
  helper (define it as a top-level function so tests can patch it).
  No `responses`/`httpx_mock`/`requests_mock` library is in deps.

**Key data shapes:**

- `referenced_works` is a list of OpenAlex Work URL strings
  (`"https://openalex.org/W272048707"`), NOT arXiv IDs. Strip the
  `https://openalex.org/` prefix to get the bare `W…` ID.
- `ids.arxiv` on each Work record gives back the arXiv URL when the
  work originated on arXiv. Two-pass shape (R2's resolution):
  1. For each seed arXiv ID: fetch its OpenAlex Work; cache
     `(arxiv_id, oa_work_id)` in an in-memory dict.
  2. After all 50 seed papers are resolved: walk each Work's
     `referenced_works` list, look up each `oa_work_id` in the dict,
     and emit a `cites` edge ONLY if it's in the corpus
     (= "in-corpus citation").

**Idempotency strategy:**

- DDL: `CREATE NODE TABLE IF NOT EXISTS …` (Kùzu supports `IF NOT
  EXISTS` since 0.4 per R2). Re-running the schema migration is a
  no-op.
- Per-paper inserts: `MERGE (p:papers {paper_id: $id}) ON CREATE SET
  … ON MATCH SET …` — Cypher idempotent upsert. Same for `cites`
  edges.
- The checkpoint file is metadata, not source-of-truth. Source-of-truth
  for "have I processed paper X?" is the Kùzu graph itself (R1's
  E04_S01 lesson). When resuming from checkpoint, first probe
  `MATCH (p:papers {paper_id: $id}) RETURN p` and skip if found.

**Confidence column:** brief says `1.0 for confirmed, lower for
inferred`. OpenAlex `referenced_works` are curated => hard-code
`confidence=1.0` for `source="openAlex"`. Reserve <1.0 for
intra-paper extraction in E09_S03. (R1 recommendation; R2 silent.)

---

## 4. Open questions (consolidated)

Items the implementer can resolve from this synthesis:

1. ✅ **OA → arXiv reverse mapping**: use `ids.arxiv` field on each
   Work; build in-memory dict (R2). Spot-check 10 records during
   implementation to confirm `ids.arxiv` is consistently populated.
2. ✅ **Seed-corpus paper not in OpenAlex**: write `papers` node with
   `oa_work_id=NULL` (Kùzu nullable column); skip `cites` edges. AC#3
   ("for each of 50 seed papers, a node exists") is satisfied; AC#4
   ("edges for OpenAlex-confirmed pairs") silently no-ops for that
   paper.
3. ✅ **Source-of-truth for 50 seed papers**: `tools/seed-papers.txt`
   read via `tools.fetch_seed.read_seed_list()`. No env var needed.
4. ✅ **`var/arxmcp/` gitignored**: yes, line 24 of `.gitignore`.
   Tests use `tmp_path`; new autouse `_patched_kuzudb_path` fixture
   in `tests/conftest.py` redirects the production Kùzu path the same
   way the cache/store/BM25 paths are redirected (R2's pattern,
   verified at `tests/conftest.py:159-234`).
5. ✅ **`kuzudb_schema.py` library vs CLI**: ship as both. Module
   exposes `apply_schema(path: Path) -> None`; module-level CLI is a
   thin argparse wrapper. Mirrors `ingest/store.py`.
6. ✅ **AC "50 seed papers" vs brief "Tier-3 tens of thousands"**:
   AC is the contract; bulk-discovery is a future-Tier-3 path.
   Implement seed-file as default, leave category-bulk as
   `NotImplementedError` with TODO (or corrected Concept IDs).
7. ✅ **Schema/path/mailto**: see §2 above. Pick brief verbatim for
   path + schema; send both header AND query string for mailto.

Items the implementer should resolve during Phase 2 (verify, don't
guess):

1. **`ids.arxiv` consistency**: spot-check 10 OpenAlex Work records
   for math arxiv papers; if `ids.arxiv` is missing, fall back to
   parsing `primary_location.landing_page_url` for `arxiv.org/abs/<id>`.
2. **Kùzu Cypher single-writer constraint**: same as LanceDB's
   E04_S01 single-writer assumption. Document in module docstring;
   don't enforce a flock at this milestone.
3. **`var/arxmcp/ops/` bootstrap**: per E01_S01 `tools/README.md` the
   make-bootstrap target only creates `parser-failures/`. The script
   should `mkdir -p` for `ops/` if missing.
4. **macOS `KMP_DUPLICATE_LIB_OK` interaction with `kuzu` import**:
   untested. Verify `pytest -q` is green on macOS after adding the
   `kuzu` dep; if it segfaults, `tests/conftest.py` already sets the
   workaround (R1's gotcha #1) — but this is a smoke-test item.
5. **Confidence on missing `confidence FLOAT` Kùzu support**: brief
   uses `FLOAT`; R1 confirmed `FLOAT` (32-bit) works in Kùzu. No
   action needed.
6. **OpenAlex API key transition**: a Jan 2026 announcement floated
   requiring API keys post Feb 13 2026; the canonical docs source
   still has the polite-pool/mailto pattern intact as of this research.
   Bake mailto in; leave a TODO for an API-key path. Not blocking.

---

## 5. External writes the implementation will require

Combined and deduped from both briefs.

**Local-only (no user gate needed beyond standard milestone authorization):**

| type | target | why |
|---|---|---|
| `pyproject.toml` dep add | runtime deps | pin `kuzu==0.11.3` (archived upstream, last stable, MIT) |
| `tests/conftest.py` edit | autouse fixture | redirect Kùzu path to `tmp_path` for tests |
| filesystem write | `./var/arxmcp/index/kuzudb/` (operator local) | Kùzu DB; gitignored |
| filesystem write | `./var/arxmcp/ops/graph-ingest-checkpoint.json` (operator local) | per-batch checkpoint state; gitignored |
| filesystem write | `./var/arxmcp/ops/graph-ingest.log` (operator local; optional) | structured log; gitignored |

**Network calls (operator-only, NEVER in CI; tests MUST mock):**

| type | target | why |
|---|---|---|
| HTTP GET (×~50) | `https://api.openalex.org/works/https://arxiv.org/abs/<paper_id>?mailto=<email>` | seed-corpus arxiv→OA-Work resolution |
| HTTP GET (≤×~50) | `https://api.openalex.org/works/<W…>?mailto=<email>` (or batched) | resolve `referenced_works` per seed paper |

**Phase 4 external-write boundary:**

- **No `git push`** required. Per per-event authorization (HANDOFF.md
  §595).
- **No GitHub PR / issue / ticket creation**.
- **No live API call in CI**. The operator-only HTTP GETs above are
  development-time only — `tests/test_graph_ingest.py` MUST stub the
  HTTP layer via `monkeypatch.setattr`.
- **Phase 4 will gate**: confirm Phase 2 actually mocks the HTTP layer
  and never calls live OpenAlex from a test or `pytest -q` run.

---

## 6. Severity-tagged risk register for Phase 3

The adversary critic should focus here:

- **CRITICAL**: brief's wrong Concept IDs survive into shipped code,
  or live OpenAlex calls leak into CI.
- **HIGH**: Kùzu version drift (anything other than `==0.11.3`) — the
  upstream is frozen; a range pin is misleading.
- **HIGH**: Kùzu DB written to the production `var/arxmcp/` path during
  tests (path-redirect fixture missing or bypassed).
- **HIGH**: `paper_id` regex validation skipped on OpenAlex-derived IDs
  (Threat 1 reminder from `08-security-observability-ops.md`).
- **MEDIUM**: checkpoint file rewritten non-atomically (corrupted on
  crash mid-write).
- **MEDIUM**: schema migration not idempotent (re-run raises instead
  of being a no-op) — directly contradicts AC#2.
- **MEDIUM**: mailto sent only in User-Agent OR only in query string,
  not both (less polite-pool-friendly; AC#7 tests for the User-Agent
  form specifically).
- **MEDIUM**: `referenced_works` list not stripped of the
  `https://openalex.org/` URL prefix → reverse-mapping never finds
  matches → zero `cites` edges written → AC#4 silently fails.
- **LOW**: missing `noqa: S310` on `urllib.request.urlopen` calls
  (linter pattern from E01_S02).
- **LOW**: `kuzudb_schema.py` library vs CLI shape inconsistent with
  `ingest/store.py`.

---

**End of synthesis.** Phase 2 implementer reads this in full +
`research-brief-1.md` (for the live-verified vendor facts) +
`research-brief-2.md` (for the codebase-pattern citations).
