---
milestone_id: "paper-metadata-m1"
researcher_role: "general"
external_writes_required:
  - "git push origin main"
sources:
  - url: "https://info.arxiv.org/help/api/user-manual.html"
    sha256: "6b2b7b01f101d2b8ce2c81934492bb31bb96271062d7dcac2b7455ae257f5925"
    takeaway: "id_list is comma-delimited with old-style + versioned IDs as first-class doc examples (cs/9901002v1, cond-mat/0702661v2); every entry carries title/id/published/updated/summary/author+/category+/arxiv:primary_category; max_results DEFAULTS TO 10; caps are 2000/slice, 30000/query; malformed IDs return an HTTP-200 single-entry error feed (§3.4)."
  - url: "https://info.arxiv.org/help/api/tou.html"
    sha256: "419ce7c8767b70240a144b0c3400e99ff38d49c57a48678d485ce8640e056056"
    takeaway: "Rate limit for the arXiv API: no more than one request every three seconds, single connection at a time, across ALL machines under your control — matches the repo's POLITENESS_SLEEP_SECONDS = 3.0."
  - url: "https://info.arxiv.org/help/api/basics.html"
    sha256: "2d2b9bccab5400dd4583542a635312b23d53ff8585a763de37a24bd9eefa6007"
    takeaway: "API landing page; confirms Atom 1.0 as the response format and defers all field semantics to the user manual — no additional guarantees."
  - url: "https://info.arxiv.org/help/withdraw.html"
    sha256: "c1a7c33caaca65e3936c072bbf296bc37c908ccccd33b2d58e713a1adf44402d"
    takeaway: "Announced articles cannot be completely removed; withdrawal creates a NEW marked version and metadata persists — withdrawn IDs still return Atom entries with non-empty title/authors (possibly author-mangled)."
injection_attempts: 0
---

# Research brief (general) — paper-metadata-m1

## External sources

The four hashed sources above are the official arXiv docs. Live probing of
`export.arxiv.org/api/query` was performed on 2026-07-05 (curl from this
workstation AND Anthropic's WebFetch egress — two independent IP origins);
the probe log is evidence in its own right and is quoted in the spike
section below.

## Spike resolution — paper-metadata-spike-1 "Atom API field coverage across corpus ID shapes"

### Corpus ID shapes (measured from repo data, not assumed)

- **Ground truth denominator** — `var/arxmcp/notebooks/bridgeland-stability/lancedb`
  `chunks` table: **126 distinct paper_ids, all arxiv-kind** — 112 new-style
  (`0705.3794` … `2603.23033`), **14 old-style** (`math/0212237`,
  `math/0307164`, `alg-geom/9410026`, `alg-geom/9606006`, `hep-th/0212218`,
  `math/9809114`, + 8 more `math/*`), 0 versioned, 0 `textbook:`. The >=95%
  acceptance gate therefore means **>=120 of 126** rows with non-NULL
  title+authors (at most 6 misses).
- Seed list `papers.txt` has 127 IDs; `hep-th/0002037` was seeded but never
  ingested (absent from chunks) — the acceptance denominator must be the
  notebook's *ingested* paper_ids, not `papers.txt` lines.
- `fourier-duality` (second populated notebook): 52 IDs — 42 new-style,
  10 old-style. Same shape mix; nothing new.
- Versioned IDs: none stored (versions stripped at seed time per
  `papers.txt` comments), but `ingest.identifiers.ARXIV_PAPER_ID_RE` accepts
  `v<int>` and the API echoes versioned abs-URLs — the mapper must normalize
  to unversioned before keying rows.

### Field coverage across ID shapes

Per the hashed user manual (§3.3.2 + appendix 5.2), every real entry carries:
`<title>`, `<id>` (abs URL), `<published>` (**date v1 was submitted** — this
is the correct `year` source; `<updated>` is the retrieved version's date),
`<summary>` (abstract), one `<author><name>` per author, one or more
`<category term=...>`, and `<arxiv:primary_category term=...>`. Optional
extras: `arxiv:affiliation`, `arxiv:comment`, `arxiv:journal_ref`,
`arxiv:doi`. The manual's own examples exercise **old-style versioned IDs in
id_list** (`id_list=cs/9901002v1`, `id_list=cond-mat/0702661v2`) — old-style
and versioned shapes are first-class, not a compatibility afterthought.

**Live numeric measurement was blocked by an arXiv-side outage during the
entire research window (2026-07-05, ~25 min of attempts):**

```
id_list=1203.4613                        -> curl timeout 30s/45s (000), then 503 after 46.3s (HTML body)
id_list=math/0212237,0708.2247,...       -> 429 "Rate exceeded." / 503 / 429 (15s backoffs)
after 150s cooldown, combined 15-ID query -> 503, header "Retry-After: 0"
after further 120s cooldown               -> 429; malformed-ID probe -> 429
same combined URL via WebFetch (different egress IP) -> 429
after a further 8-min cooldown, minimal single-ID probe (id_list=1203.4613) -> 503, "Retry-After: 0"
```

429 from two independent IP origins on first contact proves the throttling
is arXiv-side degradation, not this client. The exact re-run query (one
polite GET, covers all shapes + withdrawn + not-found in one request) is:

```
https://export.arxiv.org/api/query?id_list=math/0212237,math/0307164,0708.2247,1203.4613v1,alg-geom/9410026,hep-th/0002037,cond-mat/0512434,hep-ex/0202036,2401.99999,2303.07061,2601.22994,2603.23033,1509.04608,math/9809114,hep-th/0212218&max_results=20
```

(`cond-mat/0512434` + `hep-ex/0202036` are known-withdrawn; `2401.99999` is
well-formed-but-nonexistent; analyzer script staged at
`%LOCALAPPDATA%\Temp\claude\analyze_combined.py`.)

### Rate limits and batching

- **ToU (hashed):** <=1 request / 3 s, single connection, counted across all
  your machines. Identical to `tools.arxiv_fetch.POLITENESS_SLEEP_SECONDS`.
- **id_list batching works and is the cheap path**: comma-delimited;
  whole-notebook backfill = 126 IDs ≈ 3 batches of 50 (or one batch of 126)
  — well under the 2000/slice cap. Minutes, not hours.
- **Footgun: `max_results` defaults to 10.** An id_list of 50 with
  max_results unset silently returns 10 entries. Every id_list request MUST
  set `max_results >= len(id_list)`.
- `tools/_arxiv_api.build_query_url` is **search_query-only** — it cannot
  express an id_list query at all. The t-atom-mapper task needs a new
  id_list URL builder in `_arxiv_api` (the spike's "queried via
  tools/_arxiv_api.py" wording is currently unsatisfiable as written; this
  is itself a spike finding).

### Error modes (live-verified where marked)

1. **[LIVE] 503 with minimal HTML body and `Retry-After: 0`.**
   `tools.arxiv_fetch.parse_retry_after` honors a parseable value — `0`
   means immediate retry, i.e. hammering. The driver must clamp:
   `max(parse_retry_after(...), DEFAULT_503_BACKOFF_SECONDS)`.
2. **[LIVE] 429 with 14-byte plain-text body `Rate exceeded.`** — not XML,
   not HTML. No existing repo code handles 429 (the arxiv_fetch contract
   only documents 503 backoff). urllib raises HTTPError before parsing, so
   `parse_atom_feed` never sees these bodies — but the driver needs a 429
   branch with a long (>=60 s) cool-down; 15 s was observed to be
   insufficient.
3. **[LIVE] Sustained multi-minute outage windows + 46 s first-byte
   latency** — `_fetch_url`'s 60 s timeout is tight; the backfill must be
   resumable (re-run-as-no-op is already t-backfill-driver acceptance) and
   the ingest-time hook must be best-effort/non-blocking so an arXiv outage
   cannot wedge notebook ingest.
4. **[DOC §3.4] Malformed ID → HTTP-200 error feed** ("Errors are returned
   as Atom feeds with a single entry representing the error"; id contains
   `/api/errors#`, title `Error`). `parse_atom_feed` raises `RuntimeError`
   on ANY error entry — so one bad ID in a batch fails the whole batch.
   Mitigation: all corpus IDs already pass `ARXIV_PAPER_ID_RE`
   pre-validation, plus per-ID (or bisecting) fallback when a batch raises.
5. **[OPEN] Well-formed-but-nonexistent ID** (`2401.99999`): the manual does
   not specify whether it yields an absent entry, an empty entry, or an
   error entry; the live probe was blocked. The driver must tolerate all
   three (treat "no entry for requested id" as a per-id miss, not a crash).
6. **[DOC, withdraw.html] Withdrawn papers keep their metadata** —
   withdrawal creates a new marked version; announced articles cannot be
   removed. They hydrate with non-NULL title/authors (title may be
   author-mangled, e.g. `cond-mat/0512434`'s title is literally "This paper
   as been withdrawn") and count toward the >=95% gate.

### Repo-side blocker found (load-bearing, verified offline)

`tools/_arxiv_api.parse_atom_feed` line 189 extracts
`paper_id = id_url.rsplit("/", 1)[-1]` — **this drops the archive prefix on
old-style IDs**. Verified by running the real function against a synthetic
feed: entry id `http://arxiv.org/abs/math/0212237v3` →
`Candidate.paper_id == '0212237'` (expected `math/0212237`). Never mattered
before (prior consumers were category searches returning mostly new-style
IDs), but if the m1 mapper reuses `Candidate.paper_id` naively, all 14
old-style IDs mis-key: max coverage 112/126 = **88.9% < 95% — the acceptance
criterion fails on this bug alone**. Fix: key rows by the *requested* ID
(request-order correlation or regex the full abs-URL path with
`ARXIV_PAPER_ID_RE`), and satisfy t-atom-mapper's "id round-trips
unversioned" acceptance with an old-style regression test.

### Spike verdict

**GO — resolve paper-metadata-spike-1 as PASSED-with-one-caveat.** Evidence:
(a) official hashed docs guarantee the five required fields
(title/authors/abstract/year/categories) as core Atom elements of every real
entry and demonstrate id_list working with old-style + versioned IDs; (b)
the corpus contains only shapes the API demonstrably supports (112 new-style
+ 14 old-style, no textbook-kind in this notebook); (c) withdrawn papers
retain metadata per policy; (d) the repo's own `_arxiv_api` client already
parses these exact fields from live feeds in shipped milestones
(notebook-paper-discovery m2/m3). Caveat: numeric per-field coverage on the
live mixed sample could not be recorded because export.arxiv.org served
429/503 for the whole window from two independent egress IPs; the one-GET
re-run URL is recorded above and should be executed (and pasted into the
spike note) at implementation start. The real risk to m1 is NOT field
coverage — it is the old-style prefix-drop bug and driver-side
throttle/batch-error handling, both documented above.

## External writes enumeration

- `git push origin main` — the only true external write. CLAUDE.md §4.1
  (single-user project, all work lands on `main`, commit + push) and §4.4
  (push is per-event authorized by the user; Phase-4 orchestrator boundary —
  never executed by researcher/implementer agents).
- **Not writes, but external egress the implementation performs:** HTTPS
  GETs to `export.arxiv.org/api/query` (read-only, <=1/3s politeness, polite
  User-Agent via `ARXMCP_CONTACT_EMAIL` — an ingest-tool env var the server
  rejects, CLAUDE.md §9). Purely local otherwise: a new SQLite metadata
  store under gitignored `var/arxmcp/`, code + tests.
- No package publish, no deploy/release, no mutating third-party API, no
  GitHub issue writes required by this milestone. Verified against
  CLAUDE.md — matches expectation ("none beyond arXiv API GETs" + the
  standard commit/push landing).

## Riskiest assumption + concrete alternative

The riskiest assumption in the brief is that "hydrated from the arXiv Atom
API at ingest, plus a backfill driver" can treat the Atom API as a reliable,
batch-safe dependency. Live evidence from this very research window says
otherwise: multi-minute 429/503 outage windows, a `Retry-After: 0` header
that turns the repo's existing backoff helper into a hammer, 46 s
first-byte latencies against a 60 s client timeout, doc-confirmed
whole-feed error poisoning, and a client parser that silently mis-keys 11%
of this notebook's IDs. If the ingest-time hook calls the API inline and
blocking, a bad arXiv day breaks notebook ingest entirely — the hook must be
best-effort with the backfill driver as the authoritative repair path.

Concrete alternative: hydrate via **OAI-PMH `GetRecord`**
(`https://oaipmh.arxiv.org/oai?verb=GetRecord&identifier=oai:arXiv.org:<id>&metadataPrefix=arXiv`)
instead of Atom `id_list`. Per-record requests cannot be batch-poisoned,
not-found is an unambiguous `idDoesNotExist` error code, the `arXiv`
metadata format carries structured authors (keyname/forenames) plus
license/DOI, and the repo already ships a hardened OAI-PMH client surface —
`ingest/oai_delta.py` (E11_S02), whose D13 note explicitly deferred exactly
this papers-table metadata upsert. Cost: one request per paper
(126 × 3 s ≈ 6.5 min per notebook backfill) vs ~3 batched Atom requests —
acceptable for a CLI driver, and arguably the more robust default.

## Acceptance criteria the implementer must meet

1. >=95% of the bridgeland-stability notebook's **ingested** arxiv-kind
   paper_ids (126 → at least 120) have a metadata row with non-NULL title
   AND authors after the backfill run (m1 acceptance 1; denominator
   clarified above).
2. After process restart + cold store reopen, metadata is served without
   touching the LanceDB `chunks` table (m1 acceptance 2) — the store must be
   self-contained SQLite, not synthesized-from-chunks like today's
   `server/handlers/paper.py`.
3. Old-style IDs round-trip unversioned through the Atom mapper
   (t-atom-mapper acceptance) — requires fixing/bypassing the
   `parse_atom_feed` prefix-drop, with an old-style regression test.
4. Store schema init is idempotent — second init is a no-op with an
   unchanged schema-version row (t-store-schema acceptance); follow
   `notebooks_store.py`'s ADDITIVE-migration pattern, never Tier-1's
   DROP-AND-RECREATE.
5. Every backfill lookup honors the politeness contract (<=1 req/3s, polite
   UA, clamped 429/503 backoff) and a re-run is a no-op
   (t-backfill-driver acceptance).
6. No LanceDB chunks-schema change and no MCP tool-surface change (epic
   should-assumption; `EXPECTED_TOOL_SCHEMA_SHA256` untouched — get_paper
   wiring is m2, not m1).
7. `make test` green + `ruff check .` clean with new metadata-path
   regression tests (roadmap key_results; CLAUDE.md §4.5).

## Risks and open questions

1. **Not-found response shape unverified** (outage-blocked): absent entry vs
   empty entry vs error entry for a well-formed nonexistent ID — driver must
   tolerate all three; re-run the recorded query at implementation start.
2. **Batch error poisoning**: one malformed/unknown ID can turn the whole
   id_list feed into an error feed, and `parse_atom_feed` raises on the
   entire page — needs pre-validation + per-ID fallback (or the OAI-PMH
   alternative).
3. **Throttle handling is genuinely hard right now**: observed
   `Retry-After: 0`, plain-text 429s, and >25-minute degradation windows —
   clamp backoffs, cap total retry budget, and make the ingest-time hook
   non-blocking so notebook ingest survives arXiv outages.
4. **`max_results` default of 10 silently truncates id_list batches** — an
   easy-to-miss correctness bug; pin with a test asserting
   `max_results >= len(id_list)` in the new URL builder.
5. **~6-ID failure budget is thin**: recent future-dated IDs (`2601.22994`,
   `2603.23033`, `2512.14207`…) and any metadata quirks share the same 6-ID
   slack with transient per-ID fetch failures; the driver should log per-ID
   failure reasons so a miss is diagnosable rather than silently eating the
   budget.
