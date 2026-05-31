- [spy-passthrough-vs-binding-forward](spy-passthrough-vs-binding-forward.md) — a monkeypatch spy on a native-binding call proves the kwarg was PASSED, not FORWARDED to Rust/C; the silent-drop class the pin defends goes unguarded → MEDIUM (notebook-ops-hardening-m2)
- [threading-pinned-by-reading-not-assertion](threading-pinned-by-reading-not-assertion.md) — thread-param-through-startup milestones verify wiring by reading but rarely pin artifact LOCATION in the boot test → MEDIUM (notebook-bm25-isolation-m1 F2/F3)
- [synthesis-api-claim-vs-real-binding-return](synthesis-api-claim-vs-real-binding-return.md) — synthesis "list_indices returns ANN-only" was FALSE (scalar paper_id idx leaks in); stub-only tests masked the D2 false-clean → HIGH (corpus-integrity-observability-m3 F1)
- [escape-on-emit-untested-for-new-wrap-kind](escape-on-emit-untested-for-new-wrap-kind.md) — new wrap_retrieved_text kind: injection test seeds instruction-LIKE string w/ no literal delimiter, so escape-on-emit for the new kind goes untested → MEDIUM (notebook-surface-expansion-m4 F1/F3)
- [ustar-name-field-100-not-255](ustar-name-field-100-not-255.md) — USTAR name field is 100 chars (+155 prefix split), NOT 255; preflight at 255 admits filenames tarfile then refuses → HIGH (notebook-surface-expansion-m6 F1)
- [tarfile-extractfile-follows-intra-archive-symlinks](tarfile-extractfile-follows-intra-archive-symlinks.md) — tar.extractfile silently follows SYMTYPE→another-member; relevant when manifest read precedes safe-member pre-pass; PEP 706 filter="data" does NOT cover extractfile → LOW ordering (notebook-surface-expansion-m7 F3)
- [cli-direct-sqlite-vs-destructive-v0-v1](cli-direct-sqlite-vs-destructive-v0-v1.md) — CLI writes notebooks row w/o touching user_version + async store's v0→v1 is DROP TABLE → silent wipe on first server boot; mask: shared-DB test → CRITICAL (onboarding-uplift-m2 F1)
- [dark-mode-token-redeclaration-vs-hardcoded-color-literals](dark-mode-token-redeclaration-vs-hardcoded-color-literals.md) — @media dark redeclares :root tokens but hardcoded #hex literals (input bg #fff, tertiary greys) bypass the cascade → HIGH (ui-attractive-polish-m3 F1)

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

## 2026-05-28 — textbook-ingest-m10 — doc-finalize-leaves-sibling-snippet-stale
On a "finalize the doc to match built code" milestone, the implementer
often fixes the ONE snippet the brief names and leaves SIBLING snippets
in the SAME code block stale. m10 fixed the JS snippet
(security-pdf-sandbox.md:222-243 — now matches find_javascript(bytes)->list)
but left the page-count snippet right below it (:262-266) documenting a
non-existent `_pdf_page_count(pdf_path: Path)` PyMuPDF probe when the real
code is `_pdf_declared_page_count(pdf_bytes)` using a /Count byte-regex
(server/routes/notebooks.py:636) — and it contradicts the doc's OWN "Caps
enforced" bullet (:295). On any doc-accuracy milestone, read the ENTIRE
edited code block + the headline threat table, not just the lines git-diff
touched: grep every function name in the doc snippet against the module
and flag the ones that don't resolve. Also cross-check the threat-table
summary rows against the doc's own detail sections (m10 threat-row said
"/JS or /JavaScript" = 2 tokens while its own bullet + DANGEROUS_PDF_NAMES
say 7). The diff shows what changed; the audit surface is the whole doc.

## 2026-05-28 — textbook-ingest-m10 — AC-names-missing-but-test-only-covers-malformed
When an AC enumerates a LIST of edge cases ("malformed/missing
content-length") and the new test docstring claims to close all of them,
count the actual assert methods against the list. m10's
TestUploadPathContentLengthGuards docstring claimed "malformed/missing"
but only had malformed + negative tests; "missing" is a benign
pass-through (middleware skips the C-L block when header absent), so it
was safe — but asserted-as-covered-yet-untested is the honest-descope
risk. Verdict: MEDIUM (docstring overclaim), not HIGH, BECAUSE the
untested case is verifiably benign by reading the middleware
(server/middleware.py:899 — None C-L falls through to eager pre-read).
Always trace the untested branch before picking severity: a benign
pass-through gap is MEDIUM; a rejection-guard gap would be HIGH.

## 2026-05-28 — textbook-ingest-m12 — embedrecord-wrong-column-placement-blindspot
`EmbedRecord.__post_init__` (ingest/schema.py:309-414) validates ONLY:
dup-within-stmt-list, dup-within-proof-list, stmt/proof set-overlap, and
L2-norm. It does NOT catch (a) a stmt chunk routed into the proof column
(its id is in exactly one list → no dup, no overlap, vector still normed
→ all 4 checks pass), nor (b) a vector/id TRANSPOSE in the split (chunk A's
vector under chunk B's id, both normalized → passes). So on ANY milestone
mirroring the embedder's build->batch->split-into-dual-columns flow
(_embed_paper_impl, ingest/embedder.py:1017-1081; the embed_equations.py
precedent), the routing/alignment backstop MUST be an INTEGRATION test that
retrieves the stmt-routed chunk via the dense `embedding_stmt` path
(.search(vector_column_name="embedding_stmt").where(..., prefilter=True) —
the server's actual mechanism at server/handlers/search.py:628-650), AND a
unit test that pins vectors to ids (e.g. argmax-marker encoder). Asserting
only `chunk_ids_stmt == [...]` catches a routing swap but NOT a vector
transpose. Check both when a milestone claims "routing single-source (FM-1)".

## 2026-05-28 — textbook-ingest-m12 — notebook-cli-validate-slug-main-guard-contract
The notebook CLI family (tools/notebook_*.py) has a CONTRACT the sibling
tools/notebook_ingest.py:70,204-208 establishes: call validate_slug(slug) at
run() TOP, and wrap run() in main() with try/except NotebookError -> return 1.
New notebook CLIs often skip BOTH and lean on a downstream callee
(chunk_textbook validates per-paper at ingest/textbook_chunker.py:296-302) —
which RAISES (not returns []) for a bad slug, so a malformed slug produces an
uncaught traceback + nonzero SystemExit instead of the documented 0/1/2 exit
code. NOT a security hole (slug still rejected; path traversal still blocked),
so MEDIUM not HIGH. Always diff a new notebook CLI's main()/run() against
notebook_ingest.py:198-208 for the validate-slug + NotebookError-guard pair.

## 2026-05-28 — corpus-integrity-observability-m1 — synthesis-FM-claim-vs-actual-control-flow
When a synthesis "failure mode" entry justifies SKIPPING a test by asserting
a control-flow fact (FM-7: "write_chunks([]) returns early today"), VERIFY the
claim against the code before accepting the skip. Here write_chunks([],...)
does NOT early-return (ingest/store.py:796-801 logs INFO then falls through to
build an empty arrow table, skip merge_insert via num_rows>0 guard, run
_create_indices, and reach the marker block). The behavior happened to be
benign (chunk_count=0/paper_count=0) but the synthesis reasoning that waved off
the empty-path test was factually wrong. Pattern: a synthesis FM that says
"X path is safe because the code does Y" is a CLAIM about control flow — grep
the cited function for the early-return/guard it asserts. Same shape as the
bp1/security-doc drift class but on the research-synthesis surface, not a
shipped doc. Severity of the resulting test gap is MEDIUM when the untested
behavior is verifiably benign by reading the actual flow (matches the
m10 AC-names-missing-but-test-only-covers-malformed calibration).

## 2026-05-28 — corpus-integrity-observability-m2 — synthesis-required-FM-test-vs-pure-helper-only
When a milestone extracts a PURE decision helper (compute_chunk_count_divergence)
and tests it exhaustively, the integration-BOUNDARY failure modes the synthesis
listed as REQUIRED regression coverage often ship untested. Here synthesis §5+§6
explicitly named "FM-7 (corpus_corruption not clobbered)" + FM-2 (count_rows
raises = non-fatal) as required, but tests covered only the helper's actual<0
sentinel + a hand-set -1 gauge — NEVER booted Resources.startup with a pre-set
corpus_corruption degraded state nor with count_rows raising. The clobber guard
(resources.py: `if degraded is not None: skip`) was brief-2's TOP RISK yet has
zero startup test; a future reorder regresses silently. Pattern: grep the
synthesis for "regression coverage" / "FM-N" lists, then grep the test file for a
test that drives the INTEGRATION entrypoint (not just the pure helper) for each.
HIGH when the untested guard protects a more-severe signal on a reachable path
(corpus_corruption N-1 fallback at corpus.py:224 IS reachable). Also: a new
config @field_validator mirroring an existing one (validate_eq_ted_weight) is a
copy-paste-typo magnet — grep tests/ for the new field name; absent = MEDIUM.

## 2026-05-29 — notebook-ops-hardening-m1 — busy-truncate-checkpoint-corrupts-not-staleness
When a backup wrapper TRUNCATE-checkpoints a WAL-mode sqlite (notebooks.db)
and EXCLUDES the -wal/-shm sidecars from the manifest (relying on the
checkpoint to fold all frames), the "WARN-not-fail on busy" decision is
WRONG, and the usual justification ("a slightly-behind DB is degraded, not
corrupt") is FALSE. Live-verified on Darwin: a `wal_checkpoint(TRUNCATE)`
blocked by a concurrent read txn returns (busy=1, log=4, checkpointed=3) —
WAL is NOT truncated, latest committed frame stays only in -wal. Copying the
MAIN FILE ALONE then raises "database disk image is malformed" on both a
plain open AND `PRAGMA integrity_check`. So a busy checkpoint can ship an
unreadable notebooks.db snapshot, and the restore drill's integrity_check
only catches it quarterly (by which time 7/4/12 retention may have aged out
the last good snapshot). Repro recipe: conn A WAL writer, conn B holds open
read txn (BEGIN + SELECT), A commits a frame, conn C runs TRUNCATE checkpoint
-> busy. Fix shape: retry-with-backoff then mark backup PARTIAL (so forget
keeps the prior good snapshot) OR include the sidecars for that run; never
silently proceed. Calibrate HIGH not CRITICAL: requires concurrent reader in
the idle backup window. Also: any `python3 helper 2>/dev/null || echo error`
in an ops wrapper collapses all failure causes into one opaque token and
hides the helper's diagnostics — flag MEDIUM on data-durability paths.

## 2026-05-29 — notebook-ops-hardening-m3 — documented-deploy-flow-crashes-on-empty-corpus
For any compose/deploy milestone whose documented happy-path is `make
bootstrap` → `up --wait` → `/readyz` 200: TRACE whether `make bootstrap`
actually POPULATES a corpus or only creates EMPTY dirs (Makefile:44-45
= empty `var/arxmcp/index/lancedb`). `Resources.startup` opens the
chunks table at `config.lancedb_path` (default `var/arxmcp/index/lancedb`);
`server/corpus.py:291` raises `FileNotFoundError` on a MISSING dataset
(distinct from a missing MARKER, which `read_corpus_version` tolerates
as None). config.py:113-114 names it `CorpusNotIngestedError` "when that
corpus is empty". The exception propagates through the lifespan → the
container EXITS at startup (NOT a graceful 503). So the documented flow
is non-functional for a fresh operator unless a corpus was already
ingested OR `ARXMCP_NOTEBOOK=<slug>` points at a populated notebook
corpus. Flag HIGH when the deploy docs omit the corpus prerequisite —
the doc IS the deliverable. The synthesis FM that says "→ /readyz 503"
is wrong; verify the actual failure is the harder startup crash.
Also: when a new compose test is copy-adapted from
tests/test_compose_phoenix.py, diff the test FUNCTION lists — m3 dropped
phoenix's test_restart_policy_is_no() guard, leaving the recorded
judgment-call `restart: "no"` unprotected (MEDIUM).

## 2026-05-29 — corpus-integrity-observability-e3 — populate-after-append-dead-write
When a milestone adds a field to a dataclass that gets SERIALIZED to a
.jsonl/audit log mid-function, trace the ORDER: the populate of the new
field may happen AFTER the serialize call. e3 added
WriteStats.total_rows_after_commit (ingest/store.py:196); the dataclass
is `_append_store_stats(stats)`-ed at :887 but the field is only set at
:941 (after a count_rows()), and write_chunks returns an int (not stats)
— so the field is ALWAYS 0 in store-stats.jsonl and the :941 write is
dead. The AC said "WriteStats records X" and the impl-summary deviation
note CLAIMED "populated correctly for ops log consumers" — both false.
Adversary move: for any new dataclass field, grep every call site that
serializes/returns the object and confirm the populate happens BEFORE
the earliest consumer. Same "doc/summary says X, code does Y" family as
the bp1/security-doc drift class, but on the dataclass-ordering surface.
Flag HIGH (broken AC on common path + actively false summary claim).

## 2026-05-31 — notebook-paper-discovery-m2 — strip-quote-empty-phrase
When a library sanitizes user keywords with `value.strip()` then wraps
in double-quotes (`field:"cleaned"`), a whitespace-only input produces a
degenerate empty phrase `field:""`. Always test the whitespace-only
keyword path: either raise ValueError, skip the clause, or document the
arXiv API behavior for empty phrases. The guard belongs in the sanitizer
(return None + skip clause), not in the caller. MEDIUM when the library
will be used by a driver that populates keywords from user-controlled
metadata (e.g., notebook descriptions).
