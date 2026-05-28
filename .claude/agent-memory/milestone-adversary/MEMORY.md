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
