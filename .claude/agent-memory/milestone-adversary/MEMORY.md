## 2026-05-27 — textbook-ingest-m2 — lancedb-cast-nullability-inference
LanceDB `tbl.add_columns({col: "cast('literal' as string)"})` produces a
column with `nullable=False` because the SQL infers non-null from the
literal. A column declared `nullable=True` in `CHUNKS_SCHEMA_V1` but
migrated via this SQL ends up nullable=False on disk — divergent from a
freshly-created table. Always reproduce schema-migration claims by
building both the fresh and migrated paths and comparing
`tbl.schema.field(col).nullable` across them. Use `alter_columns` or
COALESCE-against-typed-NULL to force nullable=True.

## 2026-05-27 — textbook-ingest-m2 — stale-docstring-anti-pattern
When a milestone "ships X", check that the previous milestone's
docstring that said "X is not yet implemented; do Y workaround" got
retracted. The m1 critique F1 closed exactly this class of issue
(`ingest/schema.py:13-15` lying about `_migrate_chunks_schema_if_needed`
not existing); m2's feat commit reintroduced the same shape because the
docstring still says "Existing-row migration is NOT implemented in this
milestone." Grep the module docstring of any file the milestone is
"completing" — stale claims are a recurring HIGH finding.

## 2026-05-27 — textbook-ingest-m3 — bp1-description-vs-handler-validator-drift
On any coordinated-BP1-bump milestone that edits a `ToolMeta.description`
to "document widened acceptance", verify the matching handler validator
was widened in lockstep. m3 promised "filters.paper_id validated against
the arXiv or textbook:<slug> format" in SEARCH_PAPERS.description but
`server/handlers/search.py:175` still calls `is_valid_arxiv_paper_id`
(textbook-rejecting). The m1 docstring on the narrow validator literally
said "once m2 ships, [callers] opt into the union by switching to
`is_valid_paper_id`" — m3 was the switch milestone, description was
edited but the validator was not. Grep the validator import line in the
handler file before declaring the description edit clean.
See [[bp1-description-vs-handler-validator-drift]].

## 2026-05-27 — textbook-ingest-m4 — middleware-cap-vs-handler-cap-read-ordering
When a milestone raises a `RequestBodySizeLimitMiddleware.prefix_caps`
ceiling while keeping a per-kind cap enforced at the route handler,
verify the handler check fires BEFORE `await file.read()` /
`await request.body()`. The m4 D3 synthesis claimed "magic-byte sniff
fires at 5 bytes for non-PDF bodies, so the 200 MB middleware envelope
is safe" — false. The pre-flight runs AFTER `file.read()` which already
buffered the full 200 MB. Memory pressure regresses by the ratio of new-
to-old middleware cap (20× in m4: 10 MB → 200 MB). Worth flagging HIGH
even on a loopback-only threat model because the cost-benefit analysis
that justified the raise is built on a wrong premise. Fix path: either
move the per-kind cap upstream into a `prefix_caps`-aware-of-scope-state
middleware, or add an explicit Content-Length check at the very top of
the handler BEFORE `file.read()`. The "documented limitation" pattern
won't save this one — the synthesis was actively wrong, not silent.
See [[middleware-cap-vs-handler-cap-read-ordering]].

## 2026-05-27 — textbook-ingest-m4 — security-doc-drift-on-multi-byte-magic-sniff
Security design docs that pre-date the implementation milestone tend to
go stale when the implementer widens a check. m4's
`.claude/docs/security-pdf-sandbox.md` was written for "first 4 bytes
must be %PDF" + 4 dangerous tokens + `<HTML>` (opening uppercase). m4
shipped "first 5 bytes must be %PDF-" + 7 tokens + `</html>`/`</body>`
(closing lowercased). The doc is the OPERATOR-FACING claim; it must
move in lockstep with the impl. Grep the design doc for any byte counts,
token lists, or specific marker strings whenever a milestone touches
the matching code path. Treat this as the same shape as the
bp1-description-vs-handler-validator-drift class — both are "doc says
X, code does Y" but on different surfaces (BP1 surface vs threat-model
doc surface). See [[security-doc-drift-on-multi-byte-magic-sniff]].

## 2026-05-28 — textbook-ingest-m5 — uv-lock-transitive-major-version-downgrade
Adding a `[project.optional-dependencies].<extra>` entry to pyproject.toml
can silently force a major-version DOWNGRADE of an existing direct dep.
m5 added `mineru[pipeline]>=3.2.0,<4`; MinerU pins `transformers<5`, so
the project's transformers dropped 5.8.0 → 4.57.6 in uv.lock. Diff check:
`git diff <range> -- uv.lock | grep "^[-+]version = "` + `grep "^-name = "`
flags this. Cross-check removed packages against transitive deps of
project's direct deps — removal implies downgrade. Major-version downgrade
of a core dep (transformers powers BGE-M3 + reranker) with `requires_model`
tests skipped by default = unverified change. Flag HIGH.
See [[uv-lock-transitive-major-version-downgrade]].

## 2026-05-28 — textbook-ingest-m5 — deferred-without-tracking
F-FLAG-1 from research-synthesis explicitly said file a follow-up GitHub
issue at `chris-dare-dev/arXMCP` for `server/lean_repl.py` RLIMIT_AS audit.
implementation-summary said "Outstanding follow-up: server/lean_repl.py
audit (separate issue)". `gh issue list --repo chris-dare-dev/arXMCP`
shows ONLY Threats 2/6/7 — no entry filed. "Deferred without tracking"
is the named anti-pattern. Always `gh issue list` the repo when an
implementation summary punts something to "separate follow-up issue" —
prior pipelines actually filed issues #1-#6 for E13 follow-ups, so the
expectation is "tracked", not "hand-waved". Treat as HIGH because the
synthesis literally promised tracking and the deliverable evaporates
without it.

## 2026-05-27 — textbook-ingest-m6 — parsed-path-leak-vs-m9-redact-precedent
When a tracker milestone stores an on-disk path that surfaces in an
operator-facing JSON/HTML field (here parsed_html_path via /parse-status),
check it against the m9 redaction precedent: server/ingest_tracker.py
::redact_paths scrubs absolute prefixes down to var/arxmcp/. m6's
server/parse_tracker.py:235 stored str(output_html_path) verbatim — an
absolute /Users/.../var/arxmcp/... path leaking the home dir/username —
even though its own code comment claimed it relativizes "if possible".
The path derives from notebook_dir() -> NOTEBOOKS_BASE which is
REPO_ROOT-absolute (tools/_notebook_common.py:30,33). Flag HIGH. Same
"comment says X, code does Y" shape as the bp1/security-doc drift class
but on the path-redaction surface.

## 2026-05-27 — textbook-ingest-m6 — route-tracker-test-fixture-gap
For any milestone wiring a background tracker into a route, the route's
dispatch branch is usually UNTESTED even when the tracker is unit-tested.
The test client fixture (tests/test_notebook_api.py client) only sets
app.state.notebooks_store, NOT app.state.parse_tracker — so any upload
test silently hits the `tracker is None` warn-branch and the
schedule/start_parse transition has zero coverage. Always grep the route
test file for `app.state.<tracker_name>` assignment in the fixture; its
absence = the common-path wiring (arg names, pending->running flip,
is_running collision branch) ships uncovered. Flag HIGH (test surface).

## 2026-05-27 — textbook-ingest-m6 — latex-wrapper-end-document-injection
Strategy-A "wrap markdown as LaTeX" renderers that build a fixed
envelope with str.replace and a hard-coded \end{document} are vulnerable
to content-loss when the wrapped body contains a literal \end{document}
(plausible in any math/CS/LaTeX textbook). LaTeXML stops at the first
\end{document} and silently drops the tail; the renderer's only check is
"index.html exists", so the truncation is invisible. Also check the
documented cross-restart 409 fallback (has_running_parse) is actually
CALLED by the route — m6 implemented+tested it at the store layer but
never wired it, leaving a TOCTOU + dead code. MEDIUM each.

## 2026-05-28 — notebook-retrieval-m1 — forkC-structural-isolation-vs-persisted-cache
When a milestone claims "per-X isolation is automatic because one
process = one X" (fork-C ARXMCP_NOTEBOOK here), STRESS-TEST the claim
against PERSISTED state that survives a relaunch with a different X.
The Tier-1 retrieval cache (`server/cache_sqlite.py`) keys on
`(query,filters,k,corpus_version,level)` with NO notebook slug, and
`cache_db_path` default (`var/arxmcp/cache/retrieval.db`) is NOT
rewritten by the notebook validator — only `lancedb_path` is. So two
notebook servers relaunched at the SAME shared cache file collide IFF
their corpus_version collides. corpus_version is the per-dataset
LanceDB MVCC int (bridgeland=369, shimura=49 on disk — NOT the paper
count; NOT globally unique), so a fresh small notebook can collide →
cross-notebook wrong results within the 1h TTL. `RetrievalCache.open`
does NOT purge_other_corpus_versions and rehydrates ALL unexpired rows.
Cheapest fix = derive a per-notebook `cache_db_path` sibling in the
same validator. The "isolation is automatic" reasoning holds WITHIN a
process but never across relaunches against shared on-disk caches.
When a config validator rewrites ONE path (lancedb_path), enumerate
ALL sibling path fields (cache_db_path, ops_dir, data_dir,
notebooks_db_path) and decide per-field whether sharing is benign
(data_dir disk metric, ops_dir cron sentinels = benign) or a
collision vector (cache_db_path = HIGH).

## 2026-05-28 — textbook-ingest-m8 — verify-descope-by-tracing-input-contract
When a milestone DESCOPES a feature as "structurally inapplicable", do
NOT take the synthesis at its word — trace the actual INPUT CONTRACT to
the disputed code. m8 descoped preamble inheritance claiming "MinerU
sees no author macros". Verified by reading textbook_parser.py:351-357
(input is `-p <pdf_path>`, a RENDERED PDF) + preamble.py:313-358
(`extract_preamble` is `.tex`-source-only, FileNotFoundError otherwise).
The descope was CORRECT. The right adversary move on a descope is to
confirm the skipped work is genuinely impossible/pointless given the
real data flow, then mark CLEAN with file:line evidence — an over-eager
"this skipped work!" HIGH would have been wrong here. Counter-balances
the "deferred-without-tracking" reflex: a descope backed by a verified
input-contract argument is shippable, not a dodge. Residual findings on
such milestones are doc-precision (e.g. off-by-one column counts in the
decision doc that IS the deliverable), not missing logic.
