# Spike: Fork A as the future-proofing endpoint — notebook-retrieval-m1

**Date:** 2026-05-28
**Mode:** READ-ONLY analysis. No code changed.
**Question the operator posed:** Fork A (`filters.notebook=<slug>` per-call
routing, many notebooks per process) is the best future-proofing. Build A
directly now, build C as a clean stepping-stone to A, or reconsider?

---

## 1. Verdict up front

**Build C now as a deliberately-shaped stepping-stone to A. Do NOT build A
directly for m1, and do NOT throw C away.**

Fork A *is* the correct architectural endpoint — the operator is right that
`filters.notebook` is with-the-grain of the planned `filters.source_kind`
convention (`plans/textbook-ingest-roadmap.md:55`) and that one-process-many-notebooks
is the eventual multi-agent UX. But A has a hard precondition C uniquely
satisfies: **the server cannot boot today** (`server/resources.py:306-313`
raises `CorpusNotIngestedError` against the empty shared corpus), and A is
*per-request routing on an already-running server*. You cannot route per-call
to notebooks in a process that won't start. C is the minimal change that makes
the server bootable against a real notebook corpus AND proves the
notebook-open path end-to-end.

The decisive quantification (Section 3): of C's ~2 files, the load-bearing
logic — the slug→`lancedb_path` derivation and the slug validation — is
**reused verbatim by A's per-request path**, not replaced. What A replaces is
small (the env-var-as-*sole*-selector and the single-Resources-singleton
assumption). C-then-A is therefore *not* more total work than A-direct in any
way that matters; C front-loads and de-risks the single highest-uncertainty
piece (does a notebook lancedb open and rank correctly through the live
handler?) while deferring the genuinely-large pieces (lazy resource-cache
lifecycle + cache-key SCHEMA_VERSION bump) to a milestone that can give them
their own critique pass.

The one thing to front-load *with* C: put the notebook-path derivation in a
reusable helper (see Section 6) so A's per-request path calls the same code.
Do **not** front-load the cache-key slug bump (Section 4) — it is premature
until multi-notebook is real, and C makes it unnecessary by construction.

---

## 2. Fork A steelman — what it future-proofs (concretely)

### 2.1 Multi-notebook serving from one process

Today every expensive resource is a process singleton: `Resources` holds ONE
`chunks_table`, ONE `bm25_phase`, ONE `corpus_info`
(`server/resources.py:223-247`), handed to handlers via the module-level
`_RESOURCES` (`server/tools.py:329-356`). Under C, switching from
`bridgeland-stability` to `shimura-varieties` means **relaunching the
process** — re-paying the BGE-M3 warm (~10-30 s) and re-opening LanceDB. For a
sketcher→autoformalizer pipeline that may consult bridgeland on one tool call
and shimura on the next, that is a real operational wall.

Fork A removes it: a lazy `dict[str, NotebookResources]` keyed by slug
(research-brief-2's shape) lets a single running server answer
`filters.notebook=bridgeland-stability` then `filters.notebook=shimura-varieties`
back-to-back with no relaunch. The BGE-M3 encoder stays a **shared
process-wide singleton** (`server/query_encoder.py`; only the LanceDB
handle + `BM25Phase` + `ANNPhase` are per-notebook, per the accuracy spike
§2), so the marginal cost of a second notebook is a LanceDB open (~tens of
ms), not a second 1.5 GB model. This is the genuine future-proofing win, and
it is real.

### 2.2 With-the-grain of the planned `filters.source_kind` convention

This is A's strongest argument and it holds. `plans/textbook-ingest-roadmap.md`
KR4 (`:55`):

> `search_papers` with `filters.source_kind={arxiv|textbook}` ships with
> backward-compatible default semantics (queries against an arxiv-only
> notebook return arxiv-only; queries against a textbook-containing notebook
> return both unless filtered).

And the Won't-list (`:62`) explicitly *kills* a separate tool:

> A separate `search_textbooks` MCP tool. Killed per `pdf-ingest-2026`
> challenger T1 ruling: `source_kind` filter on the existing `search_papers`
> handler keeps the 7-tool surface byte-stable.

The textbook family has already *committed* to "scope discriminators live
inside the free-form `filters` dict, never as new tools or new env vars."
`filters.notebook=<slug>` is the identical pattern one level up (which corpus)
to `filters.source_kind` (which slice of that corpus). Both ride the
`dict[str, Any] | None` typing of `filters` (`server/handlers/search.py:303-313`)
so **neither re-pins `EXPECTED_TOOL_SCHEMA_SHA256`** (both research briefs
verified this; the schema renders `filters` as bare `{"type":"object"}`).

Fork C's `ARXMCP_NOTEBOOK` env var is *orthogonal* to this convention — it is
not wrong, but it is a different selection axis (process-launch param vs
per-call filter). When `source_kind` lands, a textbook-notebook query will
look like `filters={"source_kind":"textbook"}` against a process that already
knows its notebook. If that notebook was selected by an env var, the operator
has a per-process notebook + a per-call source_kind — two different
mechanisms for two scoping axes. Under A they unify: `filters={"notebook":
"shimura-varieties", "source_kind":"textbook"}`. **A is the with-the-grain
choice; C is grain-adjacent.** This is correct and is the core of why A is the
endpoint, not the terminus of an unrelated path.

### 2.3 The intended multi-agent consumer model — one notebook or many?

`.claude/notes/02-architecture-overview.md:18-24, 82-84` is unambiguous that
the system is **one long-running server, many concurrent sub-agents** (the
stdio shim is "stateless; all state lives in the central HTTP server"), and
the explicit failure mode it was designed to avoid is "loading bge-m3 four
times because four agents each spawned a stdio MCP." The architecture is
built around *one process, many clients*.

What it does **not** yet say is whether those concurrent agents target one
notebook or many. `01-mission-and-context.md`'s sketcher→autoformalizer→
tactician→fixer pipeline shares "one substrate of grounded context" — for a
*single proof attack* that substrate is plausibly one notebook (all four
agents working the same bridgeland problem). But across *concurrent* attacks
on different problems, the natural shape is many notebooks live at once. The
architecture note's whole thesis (one process owns the indices, §80-89) points
at A: a process that owns *the* indices generalizes cleanly to a process that
owns *several notebooks'* indices. C's "one notebook per process" forces one
process per concurrent problem-domain, which re-introduces exactly the
N-processes-N-models cost the architecture note was written to kill — *if* you
need notebook concurrency. For m1's single demo you do not; for the endpoint
you will. So A is directionally right.

---

## 3. C→A migration cost — is C throwaway or a stepping-stone?

**C is a stepping-stone, not throwaway.** Walk the surface.

### What C builds (research-synthesis "Implementation plan", `server/config.py`
+ `server/resources.py`):

1. **`Config.notebook: str | None` from `ARXMCP_NOTEBOOK`** + the
   slug→`lancedb_path` derivation (`var/arxmcp/notebooks/<slug>/lancedb`),
   applied *before* `read_corpus_version` runs (`server/resources.py:306`).
2. **Slug validation** via `tools._notebook_common.validate_slug`
   (`SLUG_RE = ^[a-z][a-z0-9-]{2,30}$`, the Threat-1 path-traversal guard).
3. **The lancedb-open + corpus_version-pin + BM25Phase-bind path** — already
   exists in `Resources.startup`; C just points it at a notebook path.
4. **AC5 typed-error** for a missing/empty notebook.

### What A reuses VERBATIM from C:

- **(2) slug validation** — A validates `filters["notebook"]` through the
  *same* `validate_slug` before any filesystem touch (research-brief-2 step 1).
  Identical code, different call site (handler body vs config parse).
- **(1, partial) the slug→`lancedb_path` derivation** — A's per-request
  resource-cache builds `var/arxmcp/notebooks/<slug>/lancedb` for *every*
  notebook it opens. This is the single most reusable line. If C factors it
  into a helper (Section 6), A imports it.
- **(3) the lancedb-open + version-pin + BM25Phase-bind sequence** — A's
  `NotebookResources` constructor does exactly what `Resources.startup` steps
  2 + 4b do (`open_chunks_table_with_fallback` at the notebook's pinned
  version, then `BM25Phase.startup(lancedb_path=notebook_path,
  corpus_version=notebook_version)`). C *proves this path works against a real
  notebook lancedb* — the highest-uncertainty thing in the whole milestone
  family. After C ships, A's resource-cache is "do the proven thing, lazily,
  per slug."
- **(4) the AC5 missing-notebook error** — A returns the same typed error,
  just as `isError=True` mid-request instead of at startup.

### What A REPLACES (the genuinely-discarded parts of C):

- **The env var as the *sole* selector.** Under A the env var becomes (at
  most) a *default* notebook; the live selector is `filters.notebook`. C's
  `ARXMCP_NOTEBOOK` doesn't get deleted — it gets demoted from "the only way"
  to "the default when no filter is supplied." Net deletion: ~0 lines; net
  semantic change: one.
- **The single-`Resources`-singleton assumption.** A introduces the
  per-notebook cache + `asyncio.Lock`. But this is *additive* — `get_resources()`
  and the shared-corpus `Resources` stay; A adds a notebook-resources lookup
  alongside. C does not build anything here that A throws away; C simply
  doesn't build it at all (it lives in the deferred-to-A scope).

### Quantification

C ≈ 2 files (config + resources) + tests. A ≈ 4 files (notebook-resource
cache + cache-key slug isolation + boot-without-default-corpus mode + handler
routing) + tests. **C-then-A total ≈ A-direct total**, because every line C
writes is either reused by A (validation, path-derivation, open-sequence) or a
one-line demotion (env var → default). The only "wasted" work is C's tests for
the env-var-sole-selector path, which are cheap and which double as A's
"default-notebook" tests.

**The de-risking is the real argument.** A-direct couples three independent
risks in one milestone: (i) does a notebook lancedb open + rank correctly
through the live dense-ANN handler, (ii) does the lazy per-slug resource cache
behave under concurrency/eviction, (iii) does the cache-key SCHEMA_VERSION
bump cleanly drop stale rows. C isolates and closes (i) — the foundational
one — with no cache refactor and automatic cache isolation. A then tackles
(ii) and (iii) on a *proven* foundation, and gets its own Phase-3 critique
focused on the lifecycle/cache risks rather than splitting attention with "did
we even open the right table." That is the textbook stepping-stone shape.

---

## 4. Boot-mode + cache-slug front-loading analysis

### 4.1 The boot problem is GOOD future-proofing — but C, not A, is where it
belongs

The server "REFUSES to start" without `var/arxmcp/index/lancedb/corpus-version.json`
(`server/README.md:28-29`; enforced at `server/resources.py:306-313`). This is
a deliberate E06_S01 synthesis-D5 guard ("refuse to start on a cold-start
corpus state"). Today the shared corpus is empty, so the production server is
**un-bootable** — a latent breakage independent of either fork.

Decoupling server lifecycle from a monolithic shared corpus *is* good
future-proofing, and it directly serves A's endpoint (a process that serves
notebooks shouldn't require a populated shared corpus it never queries). **But
the cleanest way to introduce that decoupling is exactly Fork C**: C makes the
*effective* `lancedb_path` a notebook path, so `Resources.startup` runs its
existing, battle-tested D5 guard against a *real, populated* corpus
(bridgeland v369 has `corpus-version.json` + `chunks.lance`). C does not
weaken the guard; it points the guard at something that satisfies it. That is
the minimal, safe decoupling.

A's "boot without a populated default corpus" mode is the *bigger* version of
the same idea — a true lazy-corpus startup where the process comes up with
*no* corpus bound and opens notebooks entirely on demand. That is more scope
(the lifespan at `server/main.py:305` and `/readyz` semantics both assume a
warm corpus singleton), and it is the right place for it: A needs it, A can
critique it. Building a full lazy-corpus boot mode *in m1* would be scope
creep; building C's "point the existing guard at a notebook" is not. **The
boot decoupling should land incrementally: C does the safe minimum, A does the
full lazy mode.**

### 4.2 Cache-key slug isolation — do NOT front-load it

The Tier-1 key (`server/cache_sqlite.py:144-187`, `canonical_key_components`):

```python
parts = [
    canonical.encode("utf-8"),              # query.strip()
    filters_json.encode("utf-8"),           # json.dumps(filters or {}, sort_keys=True)
    str(k).encode("ascii"),
    str(corpus_version).encode("ascii"),    # <-- the only corpus-identity axis
    level_token.encode("utf-8"),
]
```

There is **no notebook slug** in the key. And `RetrievalCache` is constructed
with a *single* `corpus_version` at `open()` time (`server/cache.py:268-276`)
and uses `self._corpus_version` for every derivation (`server/cache.py:369,
416`). So the cache is structurally bound to one corpus_version per process.

Under **C this is harmless**: one server = one notebook = one
`corpus_version` = one cache. bridgeland (369) and shimura (49) live in
*different processes* with *different* `RetrievalCache` instances. No
collision is possible (research-brief-1, confirmed). AC3 (cache isolation) is
satisfied **by construction** with zero cache code touched.

Under **A this is a guaranteed-collision bug** (research-brief-2: corpus_version
collision is *guaranteed* — each notebook versions independently from
LanceDB's internal counter; a third notebook reaching v369 would serve
bridgeland's cached rows for its own queries). A *requires* injecting
`notebook_slug` into the key + a `SCHEMA_VERSION` bump (currently `1`,
`cache_sqlite.py:71`) to drop slug-less stale rows on restart.

**Should C front-load the slug bump as a "one-time clean SCHEMA_VERSION
worth doing now"?** No.

- It is **premature**: the bump's *only* purpose is multi-notebook-in-one-cache,
  which does not exist until A. Front-loading it adds a slug parameter that is
  always `None`/single-valued under C, threaded through `derive_tier1_key`,
  `canonical_key_components`, `RetrievalCache.__init__`, `lookup_search`,
  `store_search`, and the Tier-2 `_filter_fingerprint` (research-brief-1 flags
  the Tier-2 consistency requirement) — touching 3 files to support a feature
  C cannot exercise. That is dead parameter-plumbing C's tests can't cover
  meaningfully.
- It **buys nothing for C** (C's isolation is already structural).
- It **belongs in A's critique surface**: the SCHEMA_VERSION bump + the
  guaranteed-collision reasoning is a determinism/cache-stability concern that
  A's Phase-3 `cache-stability-reviewer` + `determinism-reviewer` should own,
  not something smuggled into a 2-file slice.

The clean line is: **C keeps the cache untouched (automatic isolation); A owns
the slug-in-key + SCHEMA_VERSION bump as a first-class, critiqued change.**

---

## 5. Risks of committing to A now (≥4 concrete)

1. **Per-request second-corpus open cost + cold-start window.** A's first
   query against a not-yet-cached notebook pays `open_chunks_table_with_fallback`
   + `BM25Phase.startup` + `ANNPhase(chunks_table)` synchronously inside the
   request. The accuracy spike (§2) confirms this is *latency-only*, not a
   ranking delta — but it is latency on the hot path, and A must hold an
   `asyncio.Lock` per slug so two concurrent first-queries to the same notebook
   don't double-open. C pays this once at startup, off the hot path.

2. **Lazy resource-cache lifecycle: eviction + unbounded memory.** A's
   `dict[str, NotebookResources]` has no eviction story in either brief. Each
   open notebook pins a LanceDB handle + a BM25 pickle in memory (bridgeland's
   BM25 is non-trivial). An agent fleet touching 50 notebooks would hold 50
   open handles indefinitely. A needs an LRU/TTL eviction policy (the session
   registry at `server/session.py:163-171` and the Tier-1 10K cap are
   precedents) — *new lifecycle code with its own failure modes* (close a
   handle mid-query? race a re-open against an evict?). C has zero of this:
   one corpus, process-lifetime, GC at shutdown (`server/resources.py:691`).

3. **Concurrency: two requests opening the same notebook (thundering herd).**
   Without the per-slug `asyncio.Lock` research-brief-2 specifies, N concurrent
   first-queries to `bridgeland` each run a full `BM25Phase.startup` (a disk
   read + chunk_id cross-check, `server/resources.py:379-391`). The
   `Singleflight` primitive (`server/resources.py:125-197`) is the right tool
   but must be wired for *resource open*, not just query encode — new
   integration, new test surface. C sidesteps it (single startup open).

4. **Per-session caps interact poorly with multi-notebook.** `SessionState`
   counts `search_count` per `Mcp-Session-Id` with `MAX_SEARCH_PAPERS_CALLS=3`
   (`server/session.py:54, 207-216`). Under A, one agent querying *three
   different notebooks* in a session burns the entire retrieval budget on
   notebook-*selection*, not retrieval *depth* — the cap was designed (E08_S04)
   to bound retrieval *rounds* against *one* corpus. A multi-notebook server
   arguably wants per-(session,notebook) caps, or a higher cap — a semantic
   the cap code does not model. This is a latent product-correctness question A
   surfaces and C does not.

5. **(Bonus) `corpus_version` collision is a silent wrong-answer bug, not a
   crash.** Per research-brief-2 it is *guaranteed* as the notebook count
   grows, and the operator experiences a cache collision *as a retrieval
   accuracy failure* (notebook-A's rows served for a notebook-B query). The
   `07-multi-agent-caching.md` posture is "caching is performance, not
   correctness" — but a *cross-notebook* collision violates the determinism
   contract (`02-architecture-overview.md:106-115`: bit-identical per
   `(query, filters, k, corpus_version)`), so A *must* fix it before the cache
   is enabled for notebook queries. It cannot ship the cache-naive version.

Every one of these five risks is something C **does not have** and A **must
solve**. That asymmetry is the empirical case for C-first.

---

## 6. Decisive recommendation — exact scope

**(ii) Build C now as a clean stepping-stone, then A.** Reasoning, condensed:

- **Migration cost** (Section 3): C-then-A ≈ A-direct in total LOC, because
  C's load-bearing pieces (slug validation, path derivation, notebook-open
  sequence) are *reused* by A, not replaced. C de-risks A's foundation.
- **With-the-grain** (Section 2.2): A is genuinely the endpoint that aligns
  with `filters.source_kind`. C does not block that — it is a strict
  precondition (a bootable server) that A presupposes.
- **Boot mode** (Section 4.1): C introduces the corpus-lifecycle decoupling
  *safely* (point the existing D5 guard at a real notebook corpus); A's full
  lazy-boot mode is the bigger version that deserves its own critique.

### What C MUST include to be a clean stepping-stone (not throwaway)

1. **Factor the notebook-path derivation into a reusable helper.** Do NOT
   inline `var/arxmcp/notebooks/<slug>/lancedb` into `Config`/`Resources`.
   Add (e.g.) `server/notebook_paths.py::notebook_lancedb_path(slug: str) ->
   Path` that calls `validate_slug` (`tools._notebook_common`) first, then
   resolves + containment-checks the path (reuse the `notebook_dir` resolve
   pattern from `_notebook_common.py`). C's `Resources.startup` calls it once;
   A's per-request resource cache calls the **same** helper per slug. This is
   the single highest-leverage decision that makes C non-throwaway.
2. **Slug validation at the boundary**, via the shared `validate_slug` — A
   reuses it identically.
3. **AC5 typed error** for missing/empty notebook (`corpus-version.json`
   absent at the derived path) — raised at startup under C, reused as the
   mid-request `isError=True` body under A.
4. **Leave the cache untouched.** Document in the implementation summary that
   AC3 is satisfied structurally (one process = one corpus_version) and that
   the slug-in-key + `SCHEMA_VERSION` bump is **explicitly deferred to A**,
   with the guaranteed-collision reasoning (research-brief-2) cited so A's
   researcher inherits it.
5. **Leave `ARXMCP_NOTEBOOK` semantics demotable.** Treat it as "the notebook
   this process serves," knowing A will reread it as "the default notebook
   when `filters.notebook` is absent." Don't bake "env var is the only
   selector" into any handler-side assertion.

### What A (the follow-up milestone) then owns, cleanly scoped

- The lazy `dict[str, NotebookResources]` + per-slug `asyncio.Lock` (or
  `Singleflight`-backed open), **with an eviction policy** (Risk 2/3).
- The `notebook_slug` cache-key component + `SCHEMA_VERSION` bump + Tier-2
  fingerprint consistency (Risk 5, Section 4.2).
- `filters.notebook` handler routing (interception before the `filter_warnings`
  path; `notebook` added to `SUPPORTED_FILTER_KEYS`, `server/handlers/search.py:515`),
  with NO Field-description edit so `EXPECTED_TOOL_SCHEMA_SHA256` stays pinned.
- The full "boot without a default corpus" lazy mode (Section 4.1) and the
  per-session-cap-vs-multi-notebook semantic (Risk 4).

This sequencing gives A a *proven notebook-open foundation* and lets its
Phase-3 critique concentrate fire on the lifecycle + cache-correctness risks
that are A's genuine hard parts — instead of diluting it across "did we open
the right table at all," which C will already have settled.

---

## 7. One-line challenge to the operator's lean (and why it survives)

The strongest case *against* C-first is "C's one-notebook-per-process is a
dead-end operator model and we'll resent relaunching to switch notebooks."
True for the *endpoint* — but m1's job (`notebook-retrieval.md` AC1) is to make
*one* notebook (`bridgeland-stability`) queryable end-to-end and surface
`0705.3794`. The relaunch-to-switch friction is a real A-motivator, not an
m1 blocker. The operator's lean toward A is *correct about the destination*;
C-first is correct about *the order of the road*. Validate the lean, sequence
the build.
