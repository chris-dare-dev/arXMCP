<!-- scan provenance: generated 2026-07-25..29; moved here 2026-07-29 -->

> [!info] Principal-engineer architecture review — arXMCP scan, 2026-07-29
> **Method.** 8 parallel subsystem readers -> 8 adversarial refuters (refute-by-default) -> 3 independent cross-cutting judges. 51 CONFIRMED / 27 PARTIAL / 1 REFUTED, plus 32 findings the refuters caught that their reader missed. All three judges returned `fragile`.
> **Status.** **Partly executed.** The 9 verified must-fixes are filed as issues **#202-#210** under milestone **#7 Boundary hardening**. The rest of the 78 findings are recorded here and nowhere else. The two synthesis agents (completeness critic, final author) never ran -- they hit a spend limit -- so this document was written by the reviewing engineer from the 19 completed agents' output, and **no independent completeness pass was performed**. Section 7 states the scope honestly.
> **Origin.** Produced in a single principal-engineer review session; the board state it
> cites was read live from the GitHub API. Numbers are dated -- re-verify before acting on
> any of them.

# arXMCP — Architecture Review (principal-engineer pass)

Method: 8 parallel subsystem readers → 8 adversarial refuters (refute-by-default, re-open the
cited file) → 3 independent cross-cutting judges. **51 CONFIRMED, 27 PARTIAL, 1 REFUTED**, plus
**32 findings the refuters found that their reader had missed**. 19 of 21 agents completed; the
two synthesis agents died on a spend limit, so this document is written by the reviewing engineer
directly from the agent corpus, with every claim below re-verified by hand against the code.

Analyzed state: `main` @ `416220c`, working tree dirty (47 modified/untracked, mostly
`.claude/` notes). `ruff check .` clean; pytest collection clean.

---

## 0. Verdict

**arXMCP is a well-built monolith with excellent craft inside each subsystem and effectively no
seams between them, and it is fragile at every boundary where the served process hands off to
something else** — to cron, to the filesystem, to the packaging system, to the operator. All
three independent judges returned `fragile`, by three different routes, which is the strongest
signal in the review: correctness, operability and extensibility fail at the *same* boundaries.

The distinction that matters, and which the review holds carefully: loopback-only with no auth, a
single uvicorn worker, manual operator-gated cutover, no HA — these are **correct scoping** for a
single-user local-first tool and are explicitly excluded from the verdict. Shipping the
hybrid/rerank pipeline dormant after measuring +0.000 P@10 at 122× latency is **admirable
restraint**. What is *not* scoping: unverifiable backups, an ops layer that ships in no artifact,
a read path that serves stale results after the operator's most common action, and a first-run
experience with three independent dead ends.

| Dimension | Verdict | One-line reason |
|---|---|---|
| Overall architecture | adequate-with-gaps | Strong runtime, no extension structure, no cross-subsystem owner |
| Production readiness (OSS local-first) | **fragile** | Recovery machinery ships in no artifact; backup undetectably broken at 4 layers |
| Correctness / trust | **fragile** | 3 surfaces can each manufacture a confident falsehood with no marker on the wire |
| Extensibility / cross-functionality | **fragile** | 0 Protocols, 0 ABCs in 47k LOC; source type #2 half-landed and stayed half-landed |
| Operability | **fragile** | The one defense against total corpus loss has never executed |
| Test + CI posture | fragile | 4000+ tests, no CI, no coverage, the sole quality gate cannot run on the primary workstation |
| Security posture | adequate-with-gaps | Threat model real and mostly closed; `/ui/` explicitly unaudited (#9), `/metrics` is a write path |
| Documentation truthfulness | fragile | 59 recorded doc-drift items; `CLAUDE.md` §3/§7 are stale by design and say so |

Per-subsystem: `server-core`, `handlers`, `retrieval-cache`, `ingest-pipeline` =
**adequate-with-gaps**; `stores-graph`, `textbook-lean`, `ops-observability-security`,
`packaging-tests-ui` = **fragile**.

---

## 1. What the system actually is

~47k LOC first-party Python (`server/` 29.3k, `ingest/` 14.7k, `ops/` 2.8k, `tools/` 11.9k,
`shim/` 172) against ~88.7k LOC of tests across 160 files — a test-to-source ratio near 1.9:1,
which is unusual and to the project's credit. 25 runtime dependencies, **39 distinct `ARXMCP_*`
env knobs of which only 22 appear anywhere in `docs/`**. Seven distinct on-disk persistence
engines (LanceDB, Kùzu, four SQLite stores, a BM25 pickle, JSON markers).

The shipped shape differs from the documented shape in ways worth stating:

- `CLAUDE.md` §7 "Known stubs" is largely **obsolete in the good direction** — `cite_neighbors`,
  FTS5 `find_lemma_by_name`, TED `find_equation`, `make ingest` and hydrated `get_paper` have all
  landed since it was written. The three residual `del db` Windows-lock sites it warns about
  (gotcha 8) **are fixed**; I verified zero `del db` occurrences remain in `server/`, `ingest/`,
  `ops/`.
- The stated layering — offline ingest below a read-only serving layer, `tools/` as dev utilities
  — is **not** what the import graph says. `ingest/` imports `server/` at three module-level
  sites while `server/` imports `tools/` at fourteen, including inside a pydantic validator that
  performs disk I/O. It is a three-way cycle held together by function-local imports.
- One live violation of the project's own §4.7 ban on `assert` for invariants:
  `server/main.py:253` (`assert start_event is not None`) inside the response-size-cap ASGI
  middleware. Under `python -O` the guard vanishes and `send(None)` reaches the ASGI server.

---

## 2. What is genuinely well designed

This is not a hit piece; 86 distinct strengths were recorded. The load-bearing ones:

- **`server/proof_linkage.py` is the best module in the repository.** It refuses to pair an
  unlabeled theorem with a proof unless section scope proves uniqueness, states the value
  judgement out loud — *"A wrong proof attached to a theorem is worse than no proof: the agent
  cannot tell it is wrong"* — and implements all four epistemic outcomes the trust policy
  requires. It is the standard the rest of the surface should be held to.
- **Pure-ASGI middleware with the two genuinely hard cases solved**: the deferred
  `http.response.start` and the eager body pre-read. The `BaseHTTPMiddleware` ban is real and
  honored (only docstring references remain).
- **`ingest/schema.py`** validates invariants at the boundary with real exceptions (not asserts):
  row-alignment, cross-list exclusivity, duplicate ids, and L2-normalization of every embedding
  — catching a whole class of silent ANN-ranking corruption at construction time. Migrations are
  idempotent and each `add_columns` is its own MVCC version, so partial failure is recoverable.
- **Content-addressed chunk ids** with a version-freeze test, a write-ahead-publish gate that
  re-reads the marker, generation-scoped Lean continuation tokens, an anti-corruption layer
  around the MCP SDK mount, and per-line dependency-pin rationale in `pyproject.toml`.
- **Engineering restraint**: measuring the hybrid+rerank pipeline at +0.000 P@10 for 122× latency
  and then *shipping it dormant rather than deleting or enabling it* is the correct call, made on
  evidence.

---

## 3. Findings

78 findings survived adversarial review (1 was refuted outright). Ordered by severity, then
subsystem. `PARTIAL` means something real is there but the original claim was overstated or
mis-located; the refuter's correction governs.

| # | sev | ruling | subsystem | finding | evidence |
|---|---|---|---|---|---|
| 1 | **critical** | CONFIRMED | ops-observability-security | No alert path can ever detect a degraded or failing backup: the "last success" gauge advances unconditionally and the status enum does not match what the wrapper emits | `server/health.py:76` · `server/health.py:683-692` |
| 2 | **high** | CONFIRMED | handlers | Batched get_chunk bypasses the 256 KB byte cap: the cap is enforced per element, never on the aggregate | `server/handlers/chunk.py:116-121` · `server/handlers/chunk.py:247-251` |
| 3 | **high** | CONFIRMED | handlers | lean_verify mutates the Resources singleton from the request path with no lock — concurrent timeouts orphan a Lean subprocess and strand in-flight callers | `server/handlers/lean_verify.py:808-822` · `server/handlers/lean_verify.py:950-963` |
| 4 | **high** | CONFIRMED | handlers | All handler LanceDB I/O runs synchronously on the event loop, and find_lemma_by_name's fallback materializes the whole chunks table including three 1024-dim embedding columns | `server/handlers/lemma.py:193` · `server/handlers/search.py:781-785` |
| 5 | **high** | CONFIRMED | handlers | lean_verify's status still collapses the elaboration axis into a fidelity verdict — the exact §4.9 violation CLAUDE.md names, unremediated | `server/handlers/lean_verify.py:438-454` · `server/handlers/lean_verify.py:467-479` |
| 6 | **high** | CONFIRMED | ingest-pipeline | write_chunks is O(N²): full HNSW rebuild plus three whole-table Arrow materializations on every single-paper write | `ingest/store.py:669` · `ingest/store.py:611-622` |
| 7 | **high** | CONFIRMED | ingest-pipeline | chunk_id identity depends on whether raw .tex happens to be on disk, so every chunk_id silently rotates when preambles are recovered | `ingest/chunker.py:1277-1301` · `ingest/chunker.py:1160-1163` |
| 8 | **high** | CONFIRMED | ingest-pipeline | The nightly OAI-PMH delta loop hard-fails with ValueError on any same-day re-run or crash-retry | `ingest/oai_delta.py:590-594` · `ingest/oai_delta.py:267-272` |
| 9 | **high** | CONFIRMED | ingest-pipeline | No delete path and no version GC anywhere: superseded chunks, withdrawn papers, and every superseded HNSW index accumulate forever | `ingest/store.py:907-912` · `ingest/re_embed.py:273` |
| 10 | **high** | CONFIRMED | ops-observability-security | The entire ops layer is unshippable: `ops/` is in neither the wheel nor the container, and the watchdog imports from `tests/` | `pyproject.toml:20` · `docker/Dockerfile.server:62-68` |
| 11 | **high** | CONFIRMED | ops-observability-security | The default JSON log format silently discards every exception traceback | `server/observability/logging_setup.py:60-78` · `server/observability/logging_setup.py:102-118` |
| 12 | **high** | CONFIRMED | ops-observability-security | `GET /metrics` is the ingest control plane: the scrape hook writes filesystem state, does unbounded blocking I/O on the event loop, and the disk-full mitigation is inert without an external scraper | `server/main.py:811-821` · `server/health.py:545-626` |
| 13 | **high** | CONFIRMED | ops-observability-security | Cutover never verifies the promoted corpus is the one being served, and its post-activation gate can read another process's report | `ops/cutover.py:819-853` · `ops/cutover.py:610-638` |
| 14 | **high** | CONFIRMED | ops-observability-security | The backup / restore-drill / cutover chain has never been exercised, and the restore-drill gate accepts a pass flag of unlimited age | `ops/cutover.py:185-217` · `ops/restore_drill_check.py:266-293` |
| 15 | **high** | CONFIRMED | packaging-tests-ui | requires_latexmlc deselects nothing, so a fresh clone without LaTeXML hard-fails `make test` — the project's designated sole authority | `pyproject.toml:230` · `pyproject.toml:234` |
| 16 | **high** | PARTIAL | packaging-tests-ui | The sole quality gate does not gate: no CI, no coverage instrumentation, an empty eval fixture, 61% of runtime in one unrelated test, and ~130 lines of untested Makefile shell that cannot run on the primary workstation | `.github/release.yml:1-6` · `pyproject.toml:203-206` |
| 17 | **high** | CONFIRMED | packaging-tests-ui | The operator console does unbounded blocking work on the single event loop that serves the agent data plane, with no thread-offload seam and no separate worker | `server/routes/notebooks.py:762-798` · `tools/_arxiv_api.py:448` |
| 18 | **high** | CONFIRMED | retrieval-cache | The entire hybrid retrieval pipeline is dormant, yet Phase-1 is a FATAL startup dependency | `server/handlers/search.py:757` · `server/handlers/search.py:758-785` |
| 19 | **high** | CONFIRMED | retrieval-cache | Startup materializes the whole chunks table — both 1024-dim embedding columns included — twice | `server/resources.py:712-714` · `ingest/bm25_indexer.py:355` |
| 20 | **high** | CONFIRMED | retrieval-cache | No corpus-freshness seam: a mid-session re-ingest is invisible, and the Tier-1 mirror re-population doubles the TTL | `server/routes/notebooks.py:2117-2188` · `server/resources.py:1215-1265` |
| 21 | **high** | CONFIRMED | server-core | GET /metrics performs blocking synchronous disk I/O and filesystem WRITES on the event loop | `server/main.py:811-821` · `server/health.py:545-625` |
| 22 | **high** | CONFIRMED | server-core | /readyz returns 503 for 'degraded but serving correctly', and the Docker HEALTHCHECK is wired to it | `server/health.py:259-273` · `server/resources.py:590-616` |
| 23 | **high** | PARTIAL | stores-graph | Kùzu's mandatory exclusive lock + per-call Database open turns concurrent cite_neighbors into a silent empty result | `server/graph_queries.py:372` · `server/graph_queries.py:376` |
| 24 | **high** | CONFIRMED | stores-graph | Notebook isolation is partial: the Kùzu graph and the theorem-name index are global while everything else is per-notebook | `server/config.py:499-604` · `server/config.py:128` |
| 25 | **high** | CONFIRMED | textbook-lean | A crashed Lean REPL is never respawned and keeps reporting lean_status="available" | `server/handlers/lean_verify.py:937-972` · `server/handlers/lean_verify.py:973-999` |
| 26 | **high** | CONFIRMED | textbook-lean | MinerU runs inside the served process with no cancellation path, no cross-restart dedup, and a shutdown that can hang the server for 30 minutes | `server/parse_tracker.py:232-244` · `server/parse_tracker.py:245-266` |
| 27 | **high** | CONFIRMED | textbook-lean | The server refuses to start if given the env vars that configure its own parse path, on the grounds that it does not have one | `server/main.py:299-325` · `server/main.py:385-425` |
| 28 | **high** | CONFIRMED | textbook-lean | `syntax_only` mode picks its wrapping strategy from a four-prefix `startswith`, and mis-wraps most real Lean declarations | `server/handlers/lean_verify.py:674-703` · `server/handlers/lean_verify.py:691-700` |
| 29 | **high** | CONFIRMED | textbook-lean | status="ok" collapses elaboration, kernel acceptance, and axiom hygiene into one token that a one-line snippet can game | `server/handlers/lean_verify.py:438-445` · `server/handlers/lean_verify.py:451-454` |
| 30 | **medium** | PARTIAL | handlers | Every resource_link the handlers emit points at an unroutable URI — the byte-cap escape hatch is a dead end | `server/tools.py:207` · `server/tools.py:741-749` |
| 31 | **medium** | PARTIAL | handlers | No shared handler contract: eight bespoke response shapes, three incompatible error conventions, and the §4.9 abstention vocabulary implemented in exactly one place | `server/handlers/__init__.py:1` · `server/handlers/lean_verify.py:605-635` |
| 32 | **medium** | PARTIAL | handlers | One global schema version for eight tools, no published outputSchema, and result schemas that the handlers themselves violate | `server/tools.py:95-202` · `server/schemas/search_papers_result.json (additionalProperties:false; top-level properties = corpus_version, embed_model, excluded_kinds, filter_warnings, filters_applied, next_cursor, results, retrieval_mode)` |
| 33 | **medium** | CONFIRMED | handlers | Notebook routing is a private feature of search_papers, so the canonical search→get_chunk workflow silently breaks across notebooks — and the session middleware reaches into get_chunk's argument shape to compensate for the missing seam | `server/handlers/search.py:544-563` · `server/handlers/search.py:607-638` |
| 34 | **medium** | PARTIAL | ingest-pipeline | Three derived indices have no driver and no CLI, yet the server's remediation messages tell operators to run non-existent module entry points | `ingest/index_theorem_names.py:199-205` · `ingest/index_definitions.py:443-448` |
| 35 | **medium** | CONFIRMED | ingest-pipeline | re_embed materializes both 1024-dim embedding columns of the entire active corpus into Python lists, under a comment that understates the cost 100× | `ingest/re_embed.py:328-352` · `ingest/re_embed.py:608-612` |
| 36 | **medium** | PARTIAL | ingest-pipeline | Single-writer-per-dataset is documented as a requirement, the enforcement mechanism it names does not exist, and the WAP gate misdiagnoses the violation | `ingest/store.py:44-55` · `ingest/store.py:993-999` |
| 37 | **medium** | PARTIAL | ingest-pipeline | The failure taxonomy collapses retriable and terminal fetch outcomes into one opaque reason, and ar5iv never retries a 429/503 | `ingest/ar5iv_fetch.py:22-26` · `ingest/ar5iv_fetch.py:241-261` |
| 38 | **medium** | CONFIRMED | ingest-pipeline | The chunker destroys the previous chunk set before producing the new one, so a mid-chunk crash leaves the paper with no on-disk chunks while its LanceDB rows and NPZ persist | `ingest/chunker.py:1127-1132` · `ingest/chunker.py:1216-1234` |
| 39 | **medium** | CONFIRMED | ingest-pipeline | Schema evolution is a hand-maintained SQL-default dict that hard-fails on unknown columns and does not reach the derived indices; equations trees are un-reindexable after a normalizer bump | `ingest/store.py:338-352` · `ingest/store.py:376-392` |
| 40 | **medium** | CONFIRMED | ingest-pipeline | Corpus paths are hard-coded module constants with no env override, and bulk_ingest's staging isolation covers only LanceDB — the intermediate corpus tree and the ops sentinel are shared | `ingest/chunker.py:77-80` · `ingest/embedder.py:160-166` |
| 41 | **medium** | PARTIAL | ops-observability-security | Threat-8 log redaction is installed by only one of the two entry points, and never covers uvicorn's own loggers | `server/main.py:928-932` · `server/main.py:877-890` |
| 42 | **medium** | CONFIRMED | ops-observability-security | Threat-7 CA pinning is API-only — no production caller threads the SSLContext, and SECURITY.md does not say so | `server/main.py:960-975` · `server/ssl_pin.py:87-112` |
| 43 | **medium** | CONFIRMED | ops-observability-security | The container build bypasses uv.lock, so the shipped image's dependency closure is not reproducible | `docker/Dockerfile.server:76-79` · `pyproject.toml:37-199` |
| 44 | **medium** | PARTIAL | packaging-tests-ui | The documented install produces a package whose main binary does not exist and whose wheel omits every non-Python file the server needs | `pyproject.toml:22-27` · `arxmcp.egg-info/entry_points.txt:1-2` |
| 45 | **medium** | CONFIRMED | packaging-tests-ui | One ARXMCP_* namespace is shared between a strict extra-forbid server Config and loose ingest/test consumers, so eight documented environment variables hard-fail server startup | `server/main.py:409-425` · `server/main.py:281-324` |
| 46 | **medium** | CONFIRMED | packaging-tests-ui | The operator console is an unauthenticated mutating API with header-only CSRF defense, no kill switch, and untrusted paper HTML served same-origin with itself | `server/main.py:769-807` · `server/middleware.py:388-402` |
| 47 | **medium** | CONFIRMED | packaging-tests-ui | The entire client-side layer is verified by substring matching over source text; the repo's own templates document two shipped bugs this could not catch | `frontend/templates/base.html:16-38` · `frontend/templates/base.html:30-38` |
| 48 | **medium** | CONFIRMED | packaging-tests-ui | The shim treats HTTP 202 (the MCP spec's response for notifications) as an error, and its transport retry is non-idempotent on read timeout | `shim/arxmcp_shim.py:139-156` · `shim/arxmcp_shim.py:104-122` |
| 49 | **medium** | PARTIAL | retrieval-cache | corpus_version is incoherent across the three tiers, and the SQLite column disagrees with the key it describes | `server/cache.py:154-163` · `server/cache.py:375-379` |
| 50 | **medium** | PARTIAL | retrieval-cache | Retrieval quality is unmeasurable — the eval fixture contains zero queries, so no retrieval change can be regressed | `tests/eval/fixtures/queries.json:5` · `tests/eval/test_retrieval_quality.py:19-21` |
| 51 | **medium** | PARTIAL | retrieval-cache | Tier-1 is entry-bounded but not byte-bounded, and its byte gauge does an O(n) JSON serialization on the event loop at every scrape | `server/cache.py:781-805` · `server/cache.py:166-180` |
| 52 | **medium** | CONFIRMED | retrieval-cache | Singleflight.run awaits the shared task while holding the registry lock, serializing all keys behind any duplicate waiter | `server/resources.py:178-192` · `server/resources.py:187` |
| 53 | **medium** | CONFIRMED | server-core | ARXMCP_TRUST_REMOTE_CODE is a documented, audit-blessed escape hatch that makes the server refuse to start | `server/model_loader.py:96` · `server/model_loader.py:110` |
| 54 | **medium** | PARTIAL | server-core | The readiness body's per-resource warm map can never name the un-warm resource — the branch that would is dead code | `server/health.py:196-252` · `server/health.py:233-248` |
| 55 | **medium** | CONFIRMED | server-core | Layering inversion: the served process depends on the tools/ dev-utility package at 14 sites, including inside a pydantic config validator | `server/config.py:558-581` · `server/health.py:969` |
| 56 | **medium** | PARTIAL | server-core | Importing server.tools transitively compiles router_patterns.yaml — a dead-code YAML file gates whole-server startup | `server/tools.py:54` · `server/observability/__init__.py:30` |
| 57 | **medium** | PARTIAL | server-core | SessionCapMiddleware is coupled to one tool's argument schema and fails silently-open on any internal error | `server/middleware.py:1192-1196` · `server/middleware.py:1218-1233` |
| 58 | **medium** | CONFIRMED | stores-graph | notebooks_store v2→v3 and v3→v4 migrations are non-atomic — the exact crash-loop the v4→v5 block was written to prevent | `server/notebooks_store.py:225-230` · `server/notebooks_store.py:246-259` |
| 59 | **medium** | PARTIAL | stores-graph | No cross-engine epoch owner: a LanceDB cutover leaves the graph and the theorem index stale, and content-addressed chunk_ids dangle | `ingest/bulk_ingest.py:372-420` · `tools/notebook_ingest.py:135-153` |
| 60 | **medium** | PARTIAL | stores-graph | The disaster-recovery drill can never validate the citation graph — it queries a node label that does not exist | `ops/restore_drill_check.py:145` · `ops/restore_drill_check.py:151-154` |
| 61 | **medium** | CONFIRMED | stores-graph | The graph path reads LanceDB at the live tip, bypassing the corpus_version every other handler is pinned to | `server/graph_queries.py:257` · `server/corpus.py:248` |
| 62 | **medium** | PARTIAL | stores-graph | ParseTaskTracker cancellation cannot stop the work it cancels — the DB row lies and daemon shutdown can hang | `server/parse_tracker.py:234-244` · `server/parse_tracker.py:245-266` |
| 63 | **medium** | PARTIAL | textbook-lean | Respawn mutates shared Resources state with no mutual exclusion | `server/handlers/lean_verify.py:808-822` · `server/handlers/lean_verify.py:950-963` |
| 64 | **medium** | CONFIRMED | textbook-lean | The per-query timeout is a hardcoded module constant smaller than the cold-start cost the tool description advertises | `server/lean_repl.py:58-63` · `server/config.py:198-264` |
| 65 | **medium** | CONFIRMED | textbook-lean | Three subprocess sandboxes, three platform predicates, no shared seam — and the riskiest input gets the weakest one | `server/lean_repl.py:193-219` · `ingest/textbook_parser.py:104-173` |
| 66 | **medium** | CONFIRMED | textbook-lean | A successful MinerU parse is failed hard on the absence of an artifact no consumer reads | `ingest/textbook_parser.py:333-374` · `ingest/textbook_parser.py:299-315` |
| 67 | **medium** | CONFIRMED | textbook-lean | Two chunk lineages share one table with no purge, no read-side discrimination, and the weaker one is the default | `ingest/textbook_chunker.py:82-93` · `ingest/textbook_markdown_chunker.py:51-55` |
| 68 | **low** | PARTIAL | ingest-pipeline | ingest/ imports server/ at three module-level sites, forcing function-local imports elsewhere to break a real cycle | `ingest/bm25_indexer.py:87` · `ingest/index_theorem_names.py:35` |
| 69 | **low** | CONFIRMED | ingest-pipeline | Cluster of doc-vs-code drift inside the ingest package itself, including a self-contradicting docstring and a metric that does not measure what its contract says | `ingest/chunker_types.py:109-112` · `ingest/chunker_types.py:186-196` |
| 70 | **low** | PARTIAL | ops-observability-security | Registered-but-unwired spend metric carries a test that will fail purely with the passage of time | `server/observability/spend_constants.py:84` · `server/observability/spend_constants.py:161-231` |
| 71 | **low** | PARTIAL | retrieval-cache | The BM25 pickle-RCE mitigation is a silent no-op on Windows, the platform this project is actually run on | `server/retrieval/bm25.py:18-31` · `server/retrieval/bm25.py:141-151` |
| 72 | **low** | PARTIAL | server-core | A single global TOOL_SCHEMA_VERSION echoed into every tool's _meta structurally defeats the BP1 byte-stability discipline it exists to protect | `server/tools.py:202` · `server/tools.py:1051-1059` |
| 73 | **low** | CONFIRMED | server-core | `assert` used for an invariant in the response-cap middleware — the single violation of the project's -O ban in server/ | `server/main.py:253` · `CLAUDE.md:4.7` |
| 74 | **low** | CONFIRMED | server-core | Stale in-code contracts across server-core: middleware count, mount order, cap values, field counts, and the agent-facing instructions all disagree with the code beside them | `server/middleware.py:3` · `server/middleware.py:29-32` |
| 75 | **low** | PARTIAL | server-core | 36 env knobs with roughly 15 documented, and set_resources has no paired teardown | `server/config.py:87-494` · `server/tools.py:438-472` |
| 76 | **low** | PARTIAL | stores-graph | Six SQLite stores with no shared abstraction, five duplicated open/close/lock implementations, and two blind versioning schemes in one file | `server/notebooks_store.py:86` · `server/documents_store.py:131` |
| 77 | **low** | PARTIAL | textbook-lean | Segmented textbook parses silently lose every segment but the first | `ingest/textbook_markdown_chunker.py:84-94` · `ingest/textbook_markdown_chunker.py:26-29` |
| 78 | **low** | CONFIRMED | textbook-lean | Parse-quality signals are computed, logged, and then discarded — the operator console can only ever show pass/fail | `ingest/textbook_renderer.py:430-458` · `server/parse_tracker.py:286-299` |

### The critical and high findings, in prose

**C1 — Backup is undetectably broken at four independent layers, and has never executed.**
I verified this by hand and it is *worse* than the agents reported.
`ops/cron/arxmcp-backup.sh:221` sets `FINAL_STATUS="success"`; line 223 sets composites like
`backup_${BACKUP_STATUS}_forget_${FORGET_STATUS}`. `server/health.py:76` declares
`_BACKUP_STATES = ("ok","failed","running","unknown")`. **No value the producer can emit is a
member of the consumer's enum** — so a *perfect* backup routes to `state="unknown"` and the
`{state="ok"}` series is pinned at 0.0 forever. Then `health.py:690` advances the last-success
gauge from `finished_at` *before* inspecting status, so a failed run moves the freshness clock
forward. And `infra/prometheus/alerts.yml` contains no rule referencing `arxmcp_backup_status` at
all — the only backup alert keys on that unconditionally-advancing timestamp. Four defenses, four
independent breaks, guarding the one thing standing between a single-user tool and total corpus
loss. `var/arxmcp/ops/` holds no `backup-status.json`: none of it has ever run. This is only
possible because no test ever pipes the producer's real output into the consumer.

**C2 — The Tier-2 semantic cache serves one query's results for another, and `k` is structurally
inexpressible in its key.** `server/cache.py::_filter_fingerprint` hardcodes `k=0`, and the
comment justifying it says *"the query and k are already disambiguated by the embedding."* The
embedding is a function of query text only — **not** of `k`. So `search_papers(Q, k=5)` followed
by `search_papers(Q, k=50)` hits the same slot and the second call is served the 5-row payload,
with the handler returning `structured["results"]` verbatim and no re-slice. The ring-buffer slot
is keyed on `sha256(embedding)` alone, so a cosine-0.97 *neighbour's* rows arrive byte-identical
in shape to an exact hit. Silent under-retrieval on the tool an agent starts with, on the path
this server exists to serve.

**C3 — `lean_verify` is the only verdict-emitting surface in the system and it audits nothing
about axiom soundness.** Every other tool returns evidence an agent can weigh; `lean_verify`
returns a judgement an agent is meant to defer to — which is the entire premise of the "Lean
kernel is the better critic" framing. `status` is derived purely from `has_error` and
`has_sorry`. I verified: a case-insensitive grep for `axiom`, `sorryAx`, or `print axioms` across
`server/handlers/lean_verify.py` and `server/lean_repl.py` returns **0 hits in both files**. So
`axiom h : False` returns `status="ok"`. CLAUDE.md §4.9 rule 1 names this exact defect as the
live case the trust policy exists to prevent; it is still live.

**C4 — The identifier regex union *is* the source-type registry, and source type #2 is already
broken across the tool surface.** `search_papers` moved to `is_valid_paper_id` and emits
`textbook:<slug>` ids (`server/handlers/search.py:195`). `get_paper`, `get_definitions` and
`find_lemma_by_name` still gate on `is_valid_arxiv_paper_id`
(`paper.py:119`, `definitions.py:89`, `lemma.py:94`) and reject them. The server rejects
identifiers it emitted itself moments earlier. Source-type knowledge lives in at least six
uncoordinated places with no owner and no adapter — which is *why* source #2 half-landed and
stayed half-landed, and why source #3 has nowhere to go.

**H1 — There is not one structural interface in ~47k LOC.** Zero `typing.Protocol`, zero
`abc.ABC` (verified: grep returns 0). `server/handlers/__init__.py` is **0 bytes**. Every
pluggable axis — tool handler, retrieval phase, persistence store, source type — is N parallel
hand-maintained lists kept consistent by the author's memory plus tests that pin the current
state rather than the contract. Adding one MCP tool is a nine-artifact coordinated edit that
re-pins three SHA constants.

**H2 — No cross-store epoch owner.** Seven on-disk stores must agree about what "the corpus" is
and nothing owns that agreement. `server/corpus.py:66-80` declares cache invalidation on
corpus-version change a MUST and asserts the implementation "honors this contract". It does not:
I verified `purge_other_corpus_versions` has **zero callers** — its only two references are its
own definition and a docstring in the same file. `Resources.notebook_table` memoizes with no
mtime recheck, and nothing re-reads the marker after startup. Consequence: the operator clicks
**Ingest** in the shipped `/ui/` console, the subprocess completes, `corpus-version.json` bumps,
and the running server keeps serving the memoized pre-ingest table while echoing the *old*
`corpus_version` as truth.

**H3 — The entire operability layer ships in no artifact.** `pyproject.toml:20` declares
`include = ["server*", "ingest*", "tools*", "shim*"]` — no `ops*`; `SOURCES.txt` contains zero
`ops/` entries. So the documented compose path yields a server with no backup, cutover, restore
drill or watchdog, and no error saying so. Compounding: `docs/install.md:175` tells the new user
to verify with `arxmcp-server --help`, and there is **no `[project.scripts]` section in
`pyproject.toml` at all** — the console script does not exist.

**H4 — `GET /metrics` is the ingest control plane.** A Prometheus scrape hook performs blocking
synchronous disk I/O *and filesystem writes* on the event loop, and mutates ingest state from a
GET. The disk-full mitigation (pause ingest, allow reads) lives entirely inside that hook — and
the shipped compose stack contains no Prometheus, so on a stock install the mitigation never runs
while the docs and the `ArXMCPDiskFull` alert both present it as live. When it *does* run, it
crashes both `/metrics` and startup in exactly the read-only condition it exists to report.

**H5 — One event loop, blocking work from five directions, and the healthcheck restarts on the
stall.** The project deliberately runs one uvicorn worker to preserve shared-cache semantics.
Then the Prometheus scrape, four operator-console routes, every handler's synchronous LanceDB
I/O, `find_lemma_by_name`, and two external-binary drivers all block it. Each reviewer found one
source; the compounding is invisible per-subsystem. Docker's `HEALTHCHECK` on `/readyz` then
restarts the container during the stall.

**H6 — `write_chunks` is O(N²)** — full HNSW rebuild plus three whole-table Arrow
materializations per call — and there is **no delete path and no version GC anywhere**, so
superseded chunks and withdrawn papers accumulate forever. Alongside: `chunk_id` identity depends
on whether raw `.tex` happens to be on disk, so the identity the whole re-embed copy path rests
on is environment-dependent.

**H7 — The sole quality gate does not gate.** No `.github/workflows/`, no coverage
instrumentation, no non-sample git hook; `requires_latexmlc` deselects nothing so a fresh clone
without LaTeXML hard-fails `make test`; and the Makefile is bash-only while the primary
workstation is Windows. The eval fixture is an empty stub, so the one instrument that could
regress any of C2/C3/H2 is a permanent SKIP.

### Findings the readers missed and the refuters caught

The refute pass added 32 findings, which is itself a result: a single-pass review of this
codebase would have missed roughly a third of what is here.

| sev | subsystem | finding (refuter found; reader missed) | evidence |
|---|---|---|---|
| **high** | handlers | Textbook paper_ids returned by search_papers are rejected outright by get_paper, get_definitions and find_lemma_by_name — a hard cross-tool contract break on the corpus's second source_kind | `ingest/identifiers.py:30-38 — PAPER_ID_PATTERN has three alternatives, the third being `textbook:<slug>`; ingest/identifiers.py:74-92 defines a SEPARATE arXiv-only ARXIV_PAPER_ID_RE / is_valid_arxiv_paper_id for 'sites that construct filesystem paths or LanceDB SQL filters against the shared arXiv corpus'` · `ingest/identifiers.py:94-113 — is_valid_chunk_id DOES accept the `textbook:<slug>:<16-hex>` chunk-id form` |
| **high** | ops-observability-security | The disk-full mitigation destroys the disk-full alarm: an ENOSPC/read-only sentinel write raises out of the scrape hook and makes GET /metrics return 500 | `server/health.py:954-963 — refresh_disk_free_metric wraps ONLY shutil.disk_usage in try/except OSError; everything after it is unguarded` · `server/health.py:972-986 — the sentinel write path (ingest_sentinel.write_pause) runs bare when free < 10 GB` |
| **high** | ops-observability-security | `restic forget --keep-daily 7` runs unconditionally after a partial backup, so the script's own stated mitigation — "forget keeps the prior good snapshot" — is false | `ops/cron/arxmcp-backup.sh:167-172 — comment: "force partial so the operator sees it and forget keeps the prior good snapshot"; sets BACKUP_STATUS=partial` · `ops/cron/arxmcp-backup.sh:195-205 — `restic forget --prune --group-by host --keep-daily 7 --keep-weekly 4 --keep-monthly 12` executes with no reference to BACKUP_STATUS or CHECKPOINT_DEGRADED` |
| **high** | stores-graph | cite_neighbors opens Kùzu in READ-WRITE mode; read_only=True exists in 0.11.3, permits unlimited concurrent opens, and is the one-line fix the reviewer's own sg-1 missed | `server/graph_queries.py:372 — db = kuzu.Database(str(Path(kuzudb_path))) with no read_only argument; kuzu.Database.__init__ signature (introspected in .venv) is (database_path, *, buffer_pool_size, max_num_threads, compression, lazy_init, read_only=False, max_db_size, auto_checkpoint, checkpoint_threshold)` · `ingest/intra_paper_refs.py:348 and ops/restore_drill_check.py:143 — same read-write open on two more read-only paths` |
| **high** | stores-graph | cite_neighbors resolves chunk_ids and titles against NOTEBOOK-scoped stores while traversing the GLOBAL graph, and the inline comment asserts the opposite | `server/handlers/citations.py:103 — kuzu_path = config.kuzu_path (global; never rewritten by derive_notebook_lancedb_path, config.py:128)` · `server/handlers/citations.py:118 — lancedb_path=str(config.lancedb_path), which config.py:590 REWRITES to var/arxmcp/notebooks/<slug>/lancedb under ARXMCP_NOTEBOOK` |
| **high** | ingest-pipeline | No per-paper exception isolation in run_bulk_ingest or run_delta: a single write_chunks raise aborts the entire multi-day run, and --resume was deliberately removed | `ingest/bulk_ingest.py:413-431 — the bulk loop calls ingest_one_paper with NO try/except; any exception propagates out of run_bulk_ingest and the run dies mid-corpus` · `ingest/bulk_ingest.py:353-361 — write_chunks is called inside a try/finally whose finally only records elapsed time; nothing catches` |
| **high** | textbook-lean | A failed respawn silently reclassifies a crashed Lean REPL as operator-disabled — the mirror of lean-1, and equally an axis collapse | `server/handlers/lean_verify.py:961-967 — the `except (LeanUnavailableError, OSError)` tail of the timeout path sets `resources.lean_repl = None`` · `server/handlers/lean_verify.py:812-814 — `if lean_repl is None: return envelope(_disabled_envelope(mode))`` |
| **high** | retrieval-cache | Tier-2 keys on the embedding but NOT on k, so a k=50 request can be served the 5-row payload cached for k=5 | `server/cache.py:151-162` · `server/cache.py:199` |
| **high** | server-core | A disk-low scrape can crash the server at startup and 500 every /metrics scrape — write_pause is not OSError-guarded | `server/health.py:954-963 — only `shutil.disk_usage` is wrapped: `try: usage = shutil.disk_usage(str(data_dir)) except OSError as exc: ... return`` · `server/health.py:981-986 — `ingest_sentinel.write_pause(reason=..., path=sentinel_path)` is called with NO try/except` |
| **medium** | handlers | cap_result_list re-serializes the entire over-cap payload once per trimmed row — O(n²) JSON work on the event loop precisely when the payload is largest | `server/tools.py:820-823 — `_measure(d)` is `len(json.dumps(d, ensure_ascii=False, sort_keys=True).encode('utf-8')) * _WIRE_OVERHEAD_FACTOR`` · `server/tools.py:829-833 — `truncated = json.loads(json.dumps(structured_content))` (a full deep copy) followed by `while rows and _measure(truncated) > cap: rows.pop()` — a complete re-serialization of the whole payload on every single pop` |
| **medium** | handlers | search_papers emits ResourceLink blocks for rows the cap already deleted, and those blocks are outside every cap measurement — with a docstring that still denies the handler caps at all | `server/handlers/search.py:903-904 — `structured = _cap(structured)` (which trims trailing rows out of `structured['results']`) is immediately followed by `content = _build_content_blocks(structured, rows)`, passing the UNCAPPED local `rows` list` · `server/handlers/search.py:1007-1015 — `for row in rows:` appends one ResourceLink per element of that uncapped list` |
| **medium** | handlers | get_paper materializes up to 10,000 full chunk rows — every column, including the fixed-size 1024-float embedding columns — on EVERY call, to read four scalars | `server/handlers/paper.py:129-134 — `r.chunks_table.search().where(f"paper_id = '{_escape(paper_id)}'", prefilter=True).limit(10000).to_arrow()` with no `.select(...)`` · `server/handlers/paper.py:146-151, 157-159 — the only columns ever read from that Arrow table are section_path, chunker_version, embedder_version, and arrow.num_rows` |
| **medium** | ops-observability-security | No `arxmcp-server.service` systemd unit ships, yet four runbooks instruct the operator to systemctl stop/start it — including the cutover step whose omission causes ops-6 | `ops/systemd/ contains 12 files: arxmcp-{backup,daily-report,delta,parser-failures-weekly,quarterly-drill,watchdog}.{service,timer} — no server unit` · `docs/ops/cutover-runbook.md:121 — `sudo systemctl stop arxmcp-server.service` (the pre-swap step)` |
| **medium** | ops-observability-security | No alerting rule references `arxmcp_backup_status` at all, so fixing the ops-1 enum still buys zero detection | `infra/prometheus/alerts.yml:18-173 — the complete rule set is six alerts: ArXMCPDiskFull, ArXMCPDegradedMode, ArXMCPBackupStale, ArXMCPEvalQuarantine, ArXMCPLatexmlDrift, ArXMCPCorpusCountRowsFailed, ArXMCPCorpusUnindexedRows` · `infra/prometheus/alerts.yml:63-76 — ArXMCPBackupStale is the only component: backup rule and keys solely on arxmcp_backup_last_success_timestamp_seconds` |
| **medium** | stores-graph | A theorem_names schema bump degrades find_lemma_by_name to zero matches under a normal-looking retrieval_mode instead of the documented fallback — and the server itself performs the DROP | `server/theorem_names_store.py:238-256 — on current < SCHEMA_VERSION the open path executes DROP TABLE IF EXISTS theorem_names_fts / theorem_names and recreates them EMPTY` · `server/resources.py:930-932 — that open is invoked by Resources.startup inside the server process whenever the file exists` |
| **medium** | stores-graph | The absent-index fallback for find_lemma_by_name materializes the entire chunks table into memory on every call, and theorem_names.db is outside the backup set that would prevent reaching it | `server/handlers/lemma.py:193 — arrow = r.chunks_table.to_arrow() inside _in_memory_scan_fallback, with no filter, limit or projection pushdown; it then to_pylist()s four full columns` · `server/handlers/lemma.py:99-103 — this path is taken whenever config.theorem_names_db_path does not exist, and resources.py:952-957 logs that as routine ('will use in-memory scan fallback')` |
| **medium** | ingest-pipeline | The `parsed_dir` footgun the CLI comment claims to have closed is still live in the Python API: ar5iv writes to the caller's parsed_dir while chunk_paper reads a module constant | `ingest/bulk_ingest.py:522-526 — 'Closes F2: --parsed-dir was a CLI footgun. The chunker reads from a hardcoded module-level PARSED_DIR; honoring the CLI override at the ar5iv-write step but ignoring it at the chunker step caused silent chunker_returned_empty failures. The parsed-dir is now fixed at ingest.chunker.PARSED_DIR.'` · `ingest/bulk_ingest.py:377 — run_bulk_ingest still exposes `parsed_dir: Path = DEFAULT_PARSED_DIR` as a keyword parameter` |
| **medium** | ingest-pipeline | The embedder's skip predicate justifies tolerating orphan sidecar entries by citing a garbage-collector that does not exist | `ingest/embedder.py:678-684 — condition 5 tolerates orphans because 'orphan vectors are GC'd by E04_S02'` · `ingest/store.py:906-912 — E04_S02's writer is merge_insert-only; there is no delete arm and no GC anywhere in the module` |
| **medium** | textbook-lean | A REPL that dies mid-write raises OSError, which escapes both of the handler's except clauses and breaks the "the agent always gets an envelope" contract | `server/lean_repl.py:345-346 — `stdin.write(...)` then `await stdin.drain()` with no OSError guard` · `server/lean_repl.py:311-316 — the `returncode is not None` liveness check runs BEFORE the write, leaving a window` |
| **medium** | textbook-lean | The parse worker's success-path DB write sits outside its try/except, wedging the notebook in parse_status=running and then losing the successful parse on the next boot | `server/parse_tracker.py:233-279 — the `try:` block ends at the failure branch's `return`; the success code is outside it` · `server/parse_tracker.py:286-292 — unprotected `redact_html_path(...)` and `await store.update_parse_status(slug, PARSE_STATUS_COMPLETE, ...)`` |
| **medium** | retrieval-cache | Tier-1 keys carry no embedder identity, so results computed by the hosted-fallback embedder are re-served as clean after the outage | `server/cache_sqlite.py:170-187` · `server/corpus.py:70-80` |
| **medium** | retrieval-cache | Tier-2 approximate hits serve a DIFFERENT query's result set with no wire-level marker | `server/cache.py:103-105` · `server/cache.py:642-648` |
| **medium** | server-core | The ingest-paused sentinel is rewritten on every scrape, destroying the pause-start timestamp and flooding the log | `server/health.py:972-986 — inside `if usage.free < DISK_PAUSE_THRESHOLD_BYTES:` the `if not sentinel_path.is_file():` guard (line 973) wraps ONLY the `logger.warning`; the `ingest_sentinel.write_pause(...)` call at line 981 is unconditional` · `tools/ingest_sentinel.py:133-138 — every write_pause builds a fresh `PauseRecord(reason=..., written_at=_now_iso(), free_bytes=..., ...)`` |
| **medium** | server-core | The container's installed wheel is inert — all imports resolve from the 'inspection-only' source copy, masking the wheel's missing data files | `docker/Dockerfile.server:118 — `RUN /opt/venv/bin/pip install --no-cache-dir --no-deps /wheels/*.whl`` · `docker/Dockerfile.server:120-122 — `# Source tree for in-container inspection (NOT used for imports).` followed by `COPY server/ ./server/` and `COPY ingest/ ./ingest/`` |
| **medium** | packaging-tests-ui | The wheel claims four of the most generic top-level import names in Python (server, tools, ingest, shim) as installed site-packages modules | `pyproject.toml:20 — include = ["server*", "ingest*", "tools*", "shim*"]` · `arxmcp.egg-info/top_level.txt:1-4 — ingest / server / shim / tools` |
| **medium** | packaging-tests-ui | The equations-parity gate keys its skip decision off a CWD-relative path, so whether the most expensive test in the suite runs depends on which directory pytest was invoked from | `tests/eval/test_equations_parity.py:63 — _CORPUS = Path("var/arxmcp/corpus/parsed")` · `tests/eval/test_equations_parity.py:78-79 — if not _CORPUS.is_dir(): return []` |
| **medium** | packaging-tests-ui | The whole 4200-test suite runs under KMP_DUPLICATE_LIB_OK=TRUE, a flag the production server process never has | `tests/conftest.py:36-38 — _KMP_KEY = "KMP_DUPLICATE_LIB_OK"; os.environ.setdefault(_KMP_KEY, "TRUE")` · `tests/conftest.py:43-49 — pytest_sessionfinish pops it again, bounding it to the session` |
| **low** | ingest-pipeline | CLAUDE.md §3's kuzu `del db` residual list is stale — all three named sites now close explicitly | `CLAUDE.md §3 — 'Residual `del db` sites remain at server/graph_queries.py::cite_neighbors, ingest/intra_paper_refs.py::ingest, and ops/restore_drill_check.py (tracked fast-follow — the identical Windows lock bug on those paths).'` · `ingest/intra_paper_refs.py:389-395 — finally: try conn.close() / finally db.close(), with the 'Explicit close releases kuzu's file lock deterministically' comment` |
| **low** | textbook-lean | The MinerU scratch directory is reused across parses with no cleanup and no freshness check, so a re-parse that exits 0 without producing output silently re-serves the previous run's markdown | `server/routes/notebooks.py:1933-1935 — `mineru_output_dir = nb_dir / "parsed" / flat_paper_id / "_mineru"` with `mkdir(parents=True, exist_ok=True)`, no rmtree, no run-scoped subdir` · `server/routes/notebooks.py:1850-1851 — the upload is always stored as `<flat_paper_id>.pdf`, so the MinerU output stem is constant across parses of the same paper` |
| **low** | retrieval-cache | A Tier-2 slot is keyed by embedding hash alone, so storing a second filter-variant of a query destroys the first | `server/cache.py:666-681` · `server/cache.py:635-636` |
| **low** | server-core | The /metrics scrape path depends on prometheus_client's private `Gauge._metrics` internals | `server/health.py:907-910 — `existing = {labelvalues[0] for labelvalues in list(EVAL_NDCG5_GAUGE._metrics.keys())}` inside `_refresh_eval_ndcg5`` · `server/health.py:911-915 — the derived set drives `EVAL_NDCG5_GAUGE.remove(stale)` for label eviction` |
| **low** | packaging-tests-ui | httpx is an undeclared dependency of the test suite — 60 test modules import fastapi.testclient and get httpx only by accident, transitively through the mcp SDK | `pyproject.toml:203-206 — dev = ["ruff>=0.5", "pytest>=8.0"]` · `arxmcp.egg-info/requires.txt — 25 runtime deps, none of them httpx` |

### Refuted

One finding was refuted outright and is excluded. The 27 `PARTIAL` rulings are included above
with the refuter's correction governing the claim.

---

## 4. Cross-cutting structural problems

These exist only *between* subsystems and no per-subsystem reader could see them whole.

1. **No epoch owner.** Seven stores, one declared-but-unimplemented invalidation contract, four
   stores stale by construction after any cutover. (H2)
2. **No shared kernel.** `server/`, `ingest/`, `tools/` form a three-way import cycle with
   private-symbol coupling in both directions. This blocks every other extensibility fix, so it
   sequences first.
3. **Producer/consumer file contracts are stringly-typed and never reconciled.** The backup enum
   is the flagship, but the pattern repeats wherever cron, the filesystem, or the packaging
   system is the boundary. No test, no type, and no CI crosses those lines.
4. **The trust vocabulary is implemented in one module out of eight tools.** The four-outcome
   abstention contract is real in `proof_linkage.py` and absent elsewhere; the rest signal
   absence with an empty list plus one of five uncoordinated per-tool status tokens
   (`index_status`, `graph_status`, `retrieval_mode`, `lean_status`, `metadata_status`).
5. **Byte-stable `tools/list` froze the surface as a process-global constant**, so the server
   cannot advertise what it can actually do. Capability discovery degenerates into those same
   five vocabularies, parseable only by a consumer written against this exact server.
6. **Provenance is dropped at the handoff.** Ingest-time `truncated` is faithfully recorded and
   faithfully surfaced by `get_chunk` — and never reaches `search_papers`, the tool an agent
   starts with.
7. **The corpus is not a portable object.** Hardcoded `REPO_ROOT` paths, a wheel with no data
   files, notebook isolation implemented as four hand-listed rewrites inside one validator. "Run
   this corpus on a second machine" has no supported answer.

---

## 5. Hardening plan

**Must, before this can be called production-ready** (all S or M; none is deep):

| # | Item | Size | Why |
|---|---|---|---|
| 1 | Reconcile the backup status contract end-to-end, with one test that pipes the real script output through `health.py`, and an alert on `arxmcp_backup_status` | S | C1 — the only defense against total corpus loss |
| 2 | Fix the gauge ordering in `health.py:690` (inspect status *before* advancing the freshness clock) | S | C1 |
| 3 | Put `k` in the Tier-2 fingerprint; key the slot on `(embedding, k, filters, level, corpus_version, embedder_id)`; re-slice on return | S | C2 — silent under-retrieval |
| 4 | Add an axiom-hygiene axis to `lean_verify` (`#print axioms` on the result) and split `status` into per-axis fields | M | C3 — the live trust-policy violation |
| 5 | Add `ops*` to the wheel `include` and a `COPY ops/` to the Dockerfile; declare `[project.scripts]` | S | H3 — ships nothing today |
| 6 | Implement the corpus-version invalidation the contract already declares: call `purge_other_corpus_versions`, re-read the marker, drop the memoized table | M | H2 — stale serving after the console's Ingest button |
| 7 | Move the disk-full mitigation out of the `/metrics` scrape hook into a background task; make `/metrics` read-only | M | H4 — a GET that mutates ingest state |
| 8 | Replace `assert start_event is not None` at `server/main.py:253` with an explicit raise | XS | §4.7 violation, stripped under `-O` |

**Should**: offload blocking I/O to a thread pool (H5); split `/readyz` liveness from
degraded-but-serving; make `requires_latexmlc` actually deselect; add a delete path and version
GC (H6); linearize `write_chunks`; make the OAI delta loop re-runnable same-day.

**Nice**: coverage instrumentation; a minimal CI that at least runs `ruff` + the non-optional
test subset on Linux; reconcile the 17 undocumented env knobs.

---

## 6. Cross-functionality plan

Sequenced — nothing below is worth doing before (1).

1. **A neutral shared kernel** (`arxmcp_core` or equivalent): identifiers, schema, config, paths.
   Break the `server/ ↔ ingest/ ↔ tools/` cycle. **Precondition for everything else.** (M)
2. **A source-type adapter protocol.** One interface owning: id pattern, `source_kind`, chunk-id
   prefix, validation gate, metadata resolution. Migrate arXiv and textbook onto it — which also
   *fixes* C4 rather than papering over it. Source #3 then has a place to go. (M)
3. **A handler protocol + registry** to replace the five parallel lists in `server/tools.py`, and
   fill the 0-byte `server/handlers/__init__.py`. Adding a tool becomes one registration. (M)
4. **Separate the cached projection from the evolving contract.** Keep `tools/list` byte-stable
   *as a projection*, and add a separate, non-cached capability/health document reporting
   per-deployment truth (graph ingested? theorem index built? Lean available?) — collapsing the
   five status vocabularies into one. (M)
5. **A retrieval-lane protocol** over the three concrete classes currently hand-wired in
   `Resources.startup`. (S)
6. **Make "a corpus" a first-class object**: an explicit root, a manifest, an
   export/import path. This is what unlocks a second machine, sharing, and citability. (M)
7. **`outputSchema` on every tool** and result schemas the handlers actually satisfy — the
   machine-readable half of the contract is missing today, which is what makes non-Claude-Code
   consumers unsupported in practice. (S)

---

## 7. What this review did NOT cover

- The two synthesis agents (completeness critic, final author) **did not run** — they hit the
  monthly spend limit. This document replaces them, written by the reviewing engineer from the
  19 completed agents' output, but it means **no independent completeness pass ran**: no one
  systematically asked "which files did nobody open?"
- Not opened by anyone: most of `tools/` (36 files, 11.9k LOC), the Makefile's ~32 KB of targets,
  `infra/` manifests, `.agents/`, `server/schemas/`.
- **No dynamic verification.** The full test suite was not run (collection only). No server was
  started, no ingest executed, no failure injected. Every finding is static.
- Performance claims (O(N²) write path, 122× rerank latency) are read from code and from the
  project's own recorded measurements, not re-measured here.
- Security review is limited to the recorded threat model plus what the readers saw; the `/ui/`
  console remains explicitly unaudited (tracked at issue #9).
