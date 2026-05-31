# Milestone Researcher — Project Memory

## 2026-05-31 — onboarding-uplift-m3 — startup-chunk-count-is-shared-corpus-not-per-notebook
`Resources.startup_chunk_count` measures the SHARED global corpus (`var/arxmcp/index/lancedb/`),
NOT any per-notebook LanceDB. Per-notebook health endpoints MUST read the notebook's own
`corpus-version.json` + call `open_chunks_table(notebook_lancedb_path(slug), version=N).count_rows()`
on-demand. The brief's "use cached startup_chunk_count" safety check applies to `/status` only.

## 2026-05-31 — onboarding-uplift-m3 — repair-registry-display-name-created-at-convention
For `repair-registry` re-registering an on-disk notebook dir: use `display_name=""`,
`created_at=_now_iso()` (registration time, NOT the marker's ingest `created_at`),
`notebook_kind="arxiv"` (can't infer from disk). Operator renames via PATCH afterward.

## 2026-05-31 — onboarding-uplift-m3 — details-outerHTML-swap-loses-open-state
htmx `hx-swap="outerHTML"` on the status-badge replaces the entire `<span>` every 10s.
A `<details>` child element's `open` attribute is LOST on each poll — the tooltip auto-closes
every 10s regardless of user interaction. `hx-preserve` prevents any content update (defeats
the badge purpose). Safer pattern: a `<small>` sub-element visible only when `css != "ok"`,
no `<details>` toggle needed.

## 2026-05-31 — onboarding-uplift-m3 — reconcile-marker-preserve-created-at-for-idempotency
`write_corpus_version_marker` sets `created_at=datetime.now(UTC)` on each call. A reconcile
rewrite that uses the same pattern produces a different timestamp and a different file even when
chunk_count is unchanged. To achieve true byte-identical idempotency on re-run, preserve the
ORIGINAL `created_at` from the marker that was read, and only update `chunk_count`/`paper_count`.

## 2026-05-31 — onboarding-uplift-m2 — user-version-shared-across-stores
`PRAGMA user_version` is per-database-FILE, not per-table. When two stores
(`NotebooksStore`, `OperatorSettingsStore`) open the same `notebooks.db`,
their migrations must share a single version sequence in `NotebooksStore._open_sync`.
Recommended: add v4→v5 block for `operator_settings` table there; `OperatorSettingsStore`
asserts `user_version >= 5` but does NOT run its own migrations.

## 2026-05-31 — onboarding-uplift-m2 — ingest-to-tools-import-direction
`ingest/` files (`inspire_ingest.py`, `graph_ingest.py`) currently import from `ingest/`
and stdlib only — no `tools/` imports. Adding `from tools._notebook_common import X`
would create a new cross-direction import (`ingest/ → tools/`). The safer path:
expose a standalone helper in `server/operator_settings.py` and import from there
in `ingest/` files (avoids the circular dependency risk entirely).

## 2026-05-31 — ui-attractive-polish-m3 — htmx-request-class-on-form-not-button
When a `<form hx-post>` is submitted, htmx 2.0.10 applies `htmx-request`
to the `<form>` element itself, NOT to the `<button type="submit">` child.
CSS selector `button.htmx-request` alone will NOT dim the button on
form-submission. Add `form.htmx-request button[type="submit"]` as an
additional selector in the spinner CSS chain.

## 2026-05-31 — ui-attractive-polish-m3 — dark-accent-white-text-contrast-fail
White (`#fff`) text on Primer dark `--accent: #58a6ff` gives only ~3.1:1
contrast — FAILS WCAG SC 1.4.3 (4.5:1 required for 0.875rem/14px button text).
Fix: add `button, .button { color: #0d1117; }` inside the dark-mode `:root`
block. Dark text on #58a6ff = ~7.2:1, passes easily.

## 2026-05-31 — ui-attractive-polish-m3 — hx-disabled-elt-form-vs-button
htmx docs confirm `hx-disabled-elt` adds the HTML `disabled` attribute.
`<form>` has NO standard `disabled` attribute in HTML spec — applying
`hx-disabled-elt="this"` to a `<form>` may silently no-op. Always apply
to `<button type="submit">` or standalone `<button type="button">` elements.
htmx does NOT auto-apply `aria-disabled` — native `<button disabled>` is
accessible via the browser's accessibility tree without explicit aria.

## 2026-05-31 — ui-attractive-polish-m2 — svg-favicon-no-css-vars
SVG favicons rendered in the browser tab context do NOT inherit the page's CSS,
so `fill="var(--accent)"` silently renders as black. Use the hardcoded hex
`fill="#1e5b8a"` (matching `--accent`) in `frontend/static/favicon.svg`.
Also: `<link rel="icon" href="/ui/static/favicon.svg">` redirects the browser's
`/favicon.ico` 403 (SecFetchSite blocks non-`/ui/` requests with `same-origin`
Sec-Fetch-Site) to the `/ui/static/` mount which IS in the exempt prefix — no
SecFetchSite or CSP change needed.

## 2026-05-31 — ui-attractive-polish-m2 — vendored-md-only-covers-third-party
`frontend/static/VENDORED.md` + `tests/test_vendored_assets_integrity.py` only
track THIRD-PARTY vendored assets (currently only `htmx.min.js`). Project-authored
files like `app.css` and `favicon.svg` are explicitly NOT tracked. Adding a
hand-authored SVG requires NO update to `VENDORED.md` or the integrity test.

## 2026-05-31 — ui-attractive-polish-m1 — outerHTML-swap-breaks-aria-live
htmx `hx-swap="outerHTML"` REPLACES the element — the new element from the server
must carry `aria-live` in its markup or the live region silently stops announcing
after the first swap. For m1 UPL-3: add `aria-live="polite"` to BOTH the static
template element AND the server-rendered fragment in `server/routes/notebooks.py`
(for `#display-name-block` and `#ingest-status`). `#papers-tbody` uses `beforeend`
(element is NOT replaced) so this hazard does not apply there.

## 2026-05-30 — verification-feedback-m4 — progress-heartbeat-two-task-pattern
FastMCP `Context.report_progress` silently no-ops when client sends no `_meta.progressToken`
(per mcp==1.27.1 source). For `lean_verify` heartbeat: spawn TWO `asyncio.create_task` —
one for `lean_repl.query()`, one for the heartbeat loop — join with `asyncio.wait(
return_when=FIRST_COMPLETED)`, cancel heartbeat in `try/finally`. 3s interval satisfies
spec "SHOULD rate limit". `ctx: Context` annotation does NOT appear in inputSchema;
`EXPECTED_TOOL_SCHEMA_SHA256` is UNCHANGED. Tests must mock a non-None `progressToken`
to exercise the emission path (without it, `report_progress` no-ops and tests only
confirm the no-op).

## 2026-05-30 — verification-feedback-m4 — contextvar-vs-ctx-prior-decision
`server/middleware.py:1427` contains an explicit prior decision against threading
`Context` through all 7 handlers: "threading one through would touch all 7 handlers
+ risk a TOOL_SCHEMA_VERSION bump if FastMCP exposes it on the wire." For m4, ONLY
`handle_lean_verify` gets `ctx: Context` — the 7 existing handlers are NOT modified.

## 2026-05-29 — notebook-surface-expansion-m7 — tar-restore-dual-layer-security
`tools/notebook_restore.py` must have TWO security layers: (1) `_safe_member`
pre-pass iterating `tar.getmembers()` that REJECTS the whole restore on ANY bad member
(absolute/`..`/symlink/hardlink/device/FIFO/non-slug-prefix); (2) `filter="data"` on
`extractall`. `filter="data"` requires Python 3.12 (PEP 706 backport raises DeprecationWarning
on 3.11). `lancedb_path` omitted from manifest — reconstruct as `notebook_dir(slug)/lancedb`.
`--force` allows DB-clobber ONLY, NOT on-disk dir overwrite; require `notebook_purge.py` first.

## 2026-05-29 — notebook-surface-expansion-m6 — no-streaming-precedent-use-bytesio-tar
No `StreamingResponse` or `application/x-tar` exists anywhere in `server/` source.
For notebook export: build tar in-memory (`tarfile.open(fileobj=BytesIO(), mode="w")`),
zero all `tarinfo.mtime=0`, iterate files via `sorted(nb_dir.rglob("*"))` for stable order,
return `StreamingResponse(iter([buf.getvalue()]), media_type="application/x-tar")`.

## 2026-05-29 — notebook-surface-expansion-m6 — manifest-allowlist-omit-host-paths
The `get_notebook()` dict has `lancedb_path` + `parsed_html_path` — both absolute host paths.
OMIT from any export manifest (info-leak; backup consumers on another host get wrong paths).
Allowlist: slug, display_name, notebook_kind, created_at, parse_status. Mirrors m4 D3/F4.
Use `json.dumps(..., sort_keys=True, separators=(",", ":"))` for deterministic manifest bytes.

## 2026-05-29 — notebook-surface-expansion-m4 — fastmcp-resource-vs-template-split
`@mcp_server.resource("uri")` with NO `{param}` → concrete `FunctionResource` → appears
in `resources/list`. `@mcp_server.resource("uri/{param}")` → `ResourceTemplate` → appears
in `list_resource_templates` only, NOT `resources/list`. To enumerate notebooks in
`resources/list`, register a concrete index resource + use the template for per-slug reads.

## 2026-05-29 — notebook-surface-expansion-m4 — notebooks-store-in-mcp-callback-pattern
FastMCP resource callbacks have no FastAPI Request (no DI). Access `NotebooksStore`
via a module-level global `_notebooks_store` set in the lifespan (mirrors
`set_resources()` / `get_resources()` pattern in `server/tools.py`). The MCP callbacks
run in the SAME asyncio event loop as FastAPI — no cross-loop hazard.

## 2026-05-29 — corpus-integrity-observability-m3 — lancedb-list-indices-api-verified
`tbl.list_indices() -> Iterable[IndexConfig]` (NOT `list_indexes`); `IndexConfig` has
`.name`, `.columns`, `.index_type`. `tbl.index_stats(name) -> Optional[IndexStatistics]`
where `IndexStatistics.num_unindexed_rows: int` is the field for the unindexed-rows guard.
Returns `None` when name not found. Verified on lancedb==0.30.2. No-index-at-all case
(empty iterable) should set sentinel `-1`, NOT `0`, to avoid false-clean signal.

## 2026-05-29 — corpus-integrity-observability-m3 — warn-only-not-degraded-for-perf-issues
WARN+gauge is the right pattern when results remain CORRECT (just slower). Degraded/503
is for CORRECTNESS regressions (corpus_corruption, chunk_count_diverged). Unindexed ANN
rows = brute-force fallback = correct but slower → WARN+gauge only. This resolves the
OPEN DESIGN QUESTION in the m3 brief without needing to extend the degraded reason enum.

## 2026-05-29 — notebook-bm25-isolation-m1 — bm25-root-global-monkeypatch-is-load-bearing
`ingest.bm25_indexer.BM25_INDEX_ROOT` module-global is patched by ~40 tests via
`tests/conftest.py` autouse `_patched_bm25_index_root`. Any fix that adds an `index_root`
parameter MUST keep the module-level default pointing at `BM25_INDEX_ROOT` so existing
tests remain valid. The safe shape: `index_root: Path | None = None` → uses `BM25_INDEX_ROOT`
when None. Do not rename or remove the module global.

## 2026-05-29 — notebook-bm25-isolation-m1 — sentinel-workaround-is-dead-code-post-fix
`tools/notebook_ingest.py:132–157` contains a `.notebook_slug` sentinel workaround for
the global-BM25 collision. Once per-notebook BM25 root is wired, remove this workaround
entirely — do not keep it as dead code. The docstring (lines 14–21) must also be updated.


## 2026-05-29 — notebook-surface-expansion-m1 — parse_status-is-notebook-not-paper-scoped
`parse_status` is on the `notebooks` table (v3→v4 migration, textbook-ingest-m6), NOT on
`notebook_papers`. `list_papers()` returns only `paper_id` + `added_at`. Any milestone brief
that says "per-paper parse_status" is schema drift — the field is notebook-scoped (one value
for the whole textbook; always 'skipped' for arxiv-kind). Render once in notebook header.

## 2026-05-29 — notebook-surface-expansion-m1 — jinja2-autoescape-explicit-construction
`server/routes/ui.py` constructs `jinja2.Environment` with `autoescape=jinja2.select_autoescape(
enabled_extensions=("html","htm","xml"), default_for_string=True)` explicitly. Zero `| safe`
filters exist in any template. This is load-bearing — never introduce `| safe` for
`display_name` or other operator-controlled fields (stored-XSS vector).

## 2026-05-29 — corpus-integrity-observability-e3 — sentinel-gauge-placement-rule
Startup-set gauges (`CORPUS_VERSION_GAUGE`, `CORPUS_CHUNK_COUNT_*`) live in `server/health.py`.
Scrape-time/sentinel-bridged gauges (`BACKUP_*`, `EVAL_*`, `DELTA_TIMEOUT_*`, etc.) live in
`server/metrics.py` and are imported lazily inside `refresh_sentinel_metrics`. New sentinel-
bridged gauges MUST go in `server/metrics.py` — not health.py — to match the established pattern.

## 2026-05-29 — corpus-integrity-observability-e3 — health.py-line-numbers-shift-with-ops-features
`server/health.py` line numbers shift significantly when notebook-ops-hardening milestones add new
endpoints. The spike's cited line numbers (`refresh_sentinel_metrics:342`, `_read_capped:444`) are
unreliable by the time implementation starts. Always re-grep for function names; do NOT trust
spike-era line numbers in health.py.

## 2026-05-29 — corpus-integrity-observability-e3 — cross-filesystem-tmp-trap
`os.replace()` is only POSIX-atomic when src and dst are on the same filesystem. Using
`tempfile.NamedTemporaryFile(dir=None)` defaults to `/tmp`, which may be a different
filesystem from `var/arxmcp/ops/`. Always use `path.with_suffix(path.suffix + ".tmp")`
(same dir as target) — copy the `_write_state` idiom from `oai_delta.py:219` verbatim.

## 2026-05-29 — corpus-integrity-observability-e3 — schema_version-check-must-be-first
Sentinel readers must check `schema_version` BEFORE accessing any field. A missing check
silently returns `None` for unknown fields and sets gauges to 0.0 — indistinguishable from
"no ingest has run." Leave-prior on unknown version with a WARNING log is the correct pattern
(mirrors the `_BACKUP_STATES` unknown-routing pattern in `health.py:631`).

## 2026-05-29 — notebook-ops-hardening-m4 — SecFetchSiteMiddleware-blocks-cross-path-htmx-XHR
htmx XHRs from `/ui/*` pages to paths NOT under `/ui/` (e.g. `/status`, `/readyz`) carry
`Sec-Fetch-Site: same-origin`. `SecFetchSiteMiddleware` only allows `same-origin` on its
`exempt_prefixes` (currently `/ui`). Any new endpoint that htmx polls from `/ui/` pages
must be added to `exempt_prefixes` in `create_app`, OR placed under `/ui/` itself.

## 2026-05-29 — corpus-integrity-observability-e2 — json-formatter-new-handler-bypasses-redaction
Installing `JsonFormatter` as a NEW `StreamHandler` after `configure()` runs bypasses
`RedactionFilter` — `configure()` only protects handlers present at call time. The safe
wiring is to call `handler.setFormatter(JsonFormatter())` on the EXISTING root handler
inside `configure()`, not to add a second handler.

## 2026-05-29 — corpus-integrity-observability-e2 — JsonFormatter-exists-not-wired
`server/observability/logging_setup.py::JsonFormatter` (line 78) exists but is NOT
installed by default — the E13_S08 audit explicitly scoped it out. The e2 milestone is
the correct place to wire it via `ARXMCP_LOG_FORMAT={text|json}` (default json).
The `configure()` function at line 118 only installs `RedactionFilter`; add the
`JsonFormatter` handler-install there.

## 2026-05-29 — corpus-integrity-observability-e2 — readyz-200-body-no-exhaustive-pin
The `/readyz` 200 "ready" body (`server/health.py:241-251`) has NO test that asserts
its exact key set. Adding `chunk_count`/`marker_chunk_count` to the 200 body is additive
with no existing test update needed. Only the 503 degraded body is exhaustively tested
(via `TestReadyzChunkCountDivergedBody` in `test_corpus_count_reconciliation.py`).

## 2026-05-29 — notebook-ops-hardening-m3 — compose-file-F1-trap-relative-paths
`infra/docker-compose.yml` resolves relative bind-mount paths against the compose
FILE's directory (`infra/`), NOT the repo root. Use `../../var/arxmcp` to reach
`<repo-root>/var/arxmcp`. Documented in latexml IS4 and phoenix-compose F1 — this is a
recurrent trap; always verify with `docker compose config` after writing a bind-mount.

## 2026-05-29 — notebook-ops-hardening-m3 — compose-test-pattern-mirror-phoenix
`tests/test_compose_phoenix.py` is the canonical reference for static compose tests.
Mirror its structure for any new compose file: `yaml.safe_load` (no Docker dep) for
port/cap_drop/security_opt/mem_limit/init assertions; optional `docker compose config`
gated on `shutil.which("docker") is not None`. `pyyaml>=6.0` is already a project dep.

## 2026-05-29 — notebook-ops-hardening-m3 — compose-up-wait-is-the-healthcheck-gate
`docker compose up --wait` blocks until all services reach running|healthy state. For a
single-service compose (no depends_on), this IS the AC1 "service_healthy gate honored"
mechanism. No self-referential depends_on needed. Use `--wait-timeout` for CI-style gates.

## 2026-05-29 — notebook-ops-hardening-m1 — wal-checkpoint-before-restic-backup
notebooks.db uses WAL mode (PRAGMA journal_mode=WAL). File-level restic backup
must run `PRAGMA wal_checkpoint(TRUNCATE)` BEFORE `restic backup` fires, or
the restored DB may be stale/inconsistent. External process can checkpoint
safely (WAL allows external checkpointer while server is running). Include
only `notebooks.db` (not -wal/-shm) after checkpoint.

## 2026-05-29 — notebook-ops-hardening-m1 — restic-files-from-verbatim-is-literal
`--files-from-verbatim -` reads each line as a literal path (no glob, no
whitespace stripping, no # comment skipping; empty lines skipped). It is
include-only — excludes require separate `--exclude` flags. Use verbatim,
not `--files-from`, when paths must be treated literally.

## 2026-05-29 — notebook-ops-hardening-m1 — restic-forget-group-by-paths-fragmentation
`restic forget` default groups by `host,paths`. Adding new paths to the
include-manifest creates a NEW snapshot group; old snapshots fall into a
DIFFERENT group and age out independently. Use `--group-by host` to avoid
fragmentation as the manifest evolves. Current arxmcp-backup.sh does not
pass `--group-by`; this is a latent issue to fix when extending the manifest.

## 2026-05-29 — notebook-ops-hardening-m1 — flock-subshell-stdin-and-heredoc
arxmcp-backup.sh wraps the body in `exec flock -n ... bash -euo pipefail -c '...'`.
The `--files-from-verbatim -` flag reads stdin. bash heredoc (`<<'EOF'`) creates an
in-process pipe, NOT inherited stdin — so it works even when the outer stdin is
/dev/null (cron/systemd). Verify with: `bash -c 'cat <<EOF\nfoo\nEOF'` before landing.

## 2026-05-29 — notebook-ops-hardening-m1 — backup-status-json-paths-backed-up-needs-update
`ops/cron/arxmcp-backup.sh` writes `paths_backed_up` TWICE (lines 112–127 partial
sentinel, lines 156–173 final sentinel). Both hardcode the three original paths as
literal strings inside the single-quote flock heredoc. Adding notebook paths requires
updating BOTH cat-heredoc blocks — not just BACKUP_PATHS. Easy to miss the second write.

## 2026-05-28 — corpus-integrity-observability-m2 — DegradedState-clobber-guard
When adding a new DegradedState reason (e.g. "chunk_count_diverged"), check that
`degraded is None` before setting it. If `open_chunks_table_with_fallback` already
set reason="corpus_corruption", the new check must skip to avoid clobbering a more
serious degraded state. Both `refresh_degraded_mode_metric` label enumeration AND
the skipped-reconciliation log must be updated together.

## 2026-05-28 — corpus-integrity-observability-m2 — prometheus-gauge-set-not-recomputed
`prometheus_client==0.25.0` Gauge.set(value) stores the value in an atomic;
generate_latest() reads it directly at scrape time — no user function is called.
A gauge set once at startup never recomputes. `set_function()` is the
recompute-on-scrape variant. This is the mechanism behind "count_rows() called
at most once, never per /metrics scrape" in the brief.


## 2026-05-28 — corpus-integrity-m1 — write_chunks-single-call-contract-is-load-bearing
Moving `write_corpus_version_marker` OUT of `write_chunks` breaks notebook_textbook_ingest.py
(single-paper callers) and all tests seeding LanceDB via write_chunks. The marker must stay
inside write_chunks. Fix = replace `len(chunks)` with `tbl.count_rows()` (O(1)) for chunk_count;
paper_count uses a running set maintained by multi-paper callers and passed in.

## 2026-05-28 — textbook-ingest-m12 — embed-paper-hardcodes-global-corpus-paths
`embed_paper(paper_id)` in `ingest/embedder.py` hardcodes `CHUNKS_DIR` and `EMBEDDINGS_DIR`
(arXiv global paths). No public lower-level function accepts `list[ChunkRecord]`. For textbook
chunks, use the private primitives `_build_embed_input` + `_encode_batch` in a driver-local
`_embed_chunk_records(chunks, batch_size) -> EmbedRecord` helper. Tests use
`_make_synthetic_embeddings` from `tests/test_store.py` as the model-free pattern.

## 2026-05-28 — textbook-ingest-m12 — write-chunks-hardcodes-arxiv-chunker-version
`ingest/store.write_chunks` at line 904 always passes `chunker_version=CHUNKER_VERSION`
("v1.1") to `write_corpus_version_marker`, even when writing textbook chunks with
`chunker_version="tv0.1"`. This means the corpus-version.json for a textbook-only
notebook LanceDB will claim the arXiv chunker version. Acceptable inaccuracy for m12;
note in a code comment. A future store.py refactor can thread the version through.

## 2026-05-28 — textbook-ingest-m11 — get-chunk-only-full-body-surface
`get_chunk` is the ONLY handler returning full `body_text`. `search_papers` slices to
150 chars (SNIPPET_MAX_CHARS); `find_equation`, `find_lemma_by_name` return metadata
only; `get_definitions` returns macro `expansion` (not chunk body_text). The license-
truncation gate in m11 is correctly scoped to `get_chunk` only. License truncation must
be placed AFTER `sanitize_retrieved_text` and BEFORE `enforce_byte_cap` + `wrap_retrieved_text`
to prevent the resource_link bypass (FM-2) and delimiter-tag slicing (FM-1).

## 2026-05-28 — textbook-ingest-m11 — get-chunk-no-cache-bypass-risk
`get_chunk` does NOT use the 3-tier retrieval cache (`server/cache.py`). It goes
directly to LanceDB. Cache-key correctness is not a risk for m11 license truncation.
The retrieval cache is for `search_papers` query results only.

## 2026-05-28 — textbook-ingest-m10 — upload-cap-already-shipped-in-m4
The 200 MB middleware envelope + 10 MB per-kind handler check BOTH shipped in
textbook-ingest-m4 (state: complete). `server/main.py:549` sets
`prefix_caps={"/ui/api/notebooks": 200*1024*1024}`; handler check at
`server/routes/notebooks.py:824`. m10 is a doc-accuracy pass + 2-3 new tests only.
The accepted trade-off (200 MB buffered before 10 MB arxiv-kind rejection) is
loopback-only acceptable; documented in `server/main.py:532-545`.

## 2026-05-28 — textbook-ingest-m10 — security-pdf-sandbox-doc-function-name-wrong
`.claude/docs/security-pdf-sandbox.md` line 226 shows `_pdf_has_javascript(pdf_path: Path)`
but the actual code uses `_pdf_find_javascript(content: bytes)` (aliased from
`tools.security.pdfid.find_javascript`). Any milestone touching the sandbox doc
must fix this signature mismatch.

## 2026-05-28 — textbook-ingest-m9 — no-textbook-embed-write-path-exists
`chunk_textbook` writes chunk JSONs to `var/arxmcp/notebooks/<slug>/chunks/` ONLY.
No driver calls `chunk_textbook` externally; no embed→write-notebook-LanceDB path
exists for textbook chunks. `bulk_ingest.py` handles arXiv only. Tests must seed
synthetic notebook LanceDB directly via `write_chunks(chunks, embed_record, lancedb_path=tmp_path)`.

## 2026-05-28 — textbook-ingest-m9 — bm25-apply-filters-skips-textbook-chunks
`bm25._apply_supported_filters` (line 699) hardcodes `if not chunk_id.startswith("arxiv:"):`
and skips all non-arxiv candidates. source_kind filtering in BM25 must infer kind from
chunk_id prefix (`textbook:` → "textbook", `arxiv:` → "arxiv"). BM25 candidates are
only `(chunk_id, score)` — no column available at filter point.

## 2026-05-28 — textbook-ingest-m9 — TWO-SUPPORTED-FILTER-KEYS-copies
`SUPPORTED_FILTER_KEYS = frozenset({"paper_id"})` exists in BOTH `server/retrieval/bm25.py:117`
AND `server/handlers/search.py:208`. Both must be updated in lockstep for any new filter key.
`_inject_filters_applied` uses the handler copy; `_apply_supported_filters` uses the bm25 copy.

## 2026-05-28 — textbook-ingest-m8 — ProofNet-schema-5-fields-id-is-TextbookPipe-exercise
ProofNet (hoskinson-center/proofnet on HuggingFace, arXiv:2302.12433) has 5 fields:
id, nl_statement, nl_proof, formal_statement, src_header. id follows `Textbook|exercise_N_Ma`
(e.g. `Rudin|exercise_1_1a`). For PDF-sourced textbooks, `theorem_label` from MinerU+LaTeXML
is auto-generated (not the author label), so cross-reference by label is unreliable. Do NOT
add proofnet_id to schema — document the join contract in .claude/docs/ instead.

## 2026-05-28 — textbook-ingest-m8 — PDF-MinerU-path-kills-preamble-inheritance-unconditionally
OQ-1 reading (a) wins with certainty: MinerU processes rendered PDF glyphs; author macros
are expanded before PDF rendering. No `\newcommand` survives. `preamble_text=""` is correct
and permanent for PDF-sourced textbooks. Replace `# TODO(m8)` with a decision comment;
do NOT build a .tex preamble extractor for a path that cannot produce .tex.

## 2026-05-28 — textbook-ingest-m7 — _compute_chunk_id-hardcodes-arxiv-prefix
`ingest/chunker.py::_compute_chunk_id` (line 1050) hardcodes `f"arxiv:{paper_id}:{digest}"`.
Textbook chunker CANNOT call it directly — must implement `_compute_textbook_chunk_id`
emitting `f"textbook:{slug}:{digest}"`. Same hash discipline (SHA-256, NFC), different prefix.

## 2026-05-28 — textbook-ingest-m7 — page-metadata-lost-through-latexml
MinerU content_list.json carries `page_idx` per block. LaTeXML HTML5 output has NO
page_idx attributes — page info is lost in the m6 MinerU→LaTeXML pipeline.
page_start/page_end must be NULL in m7 v0; flag with comment for m8.

## 2026-05-28 — textbook-ingest-m7 — stacks-project-NOT-latexml-rendered
live stacks.math.columbia.edu does NOT use LaTeXML (uses custom engine + MathJax).
4-char tags (01AB) are Stacks-internal, not LaTeXML id attributes. Test fixture
must be project-original synthetic HTML5 mimicking LaTeXML shape — not scraped.

## 2026-05-28 — textbook-ingest-m7 — ChunkRecord-has-all-m2-fields-no-gap
`ingest/chunker_types.py::ChunkRecord` already carries ALL textbook-ingest-m2 columns:
source_kind, license, chapter, page_start, page_end, textbook_slug, parser_used.
No dataclass extension needed for m7; no CHUNKER_VERSION bump required.

## 2026-05-28 — textbook-ingest-m7 — textbook-chunker-needs-own-version-constant
CHUNKER_VERSION = "v1.1" is shared by arXiv chunker. Bumping it for textbook-only
changes forces re-embedding ALL arXiv chunks. Define TEXTBOOK_CHUNKER_VERSION = "tv1.0"
in ingest/textbook_chunker.py as a separate constant.

## 2026-05-27 — textbook-ingest-m1 — CHUNK_ID_RE-uses-dollar-not-Z-anchor
`ingest/identifiers.py::CHUNK_ID_RE` is built as `re.compile(rf"^{CHUNK_ID_PATTERN}$")` —
uses `$` (not `\Z`). `_PAPER_ID_FULL_PATTERN` already fixed to `\Z` (F3 closure). The
CHUNK_ID_RE `$` bug is a second F3-class instance: `is_valid_chunk_id("arxiv:2401.00001:abcdef0123456789\n")`
returns True. Any milestone touching `CHUNK_ID_RE` must fix both anchors together.

## 2026-05-27 — textbook-ingest-m1 — three-copy-sync-pattern-for-PAPER_ID_RE
`ingest/identifiers.py:_PAPER_ID_FULL_PATTERN`, `ingest/chunker.py:_PAPER_ID_RE`, and
`tools/validate_eval_fixtures.py:_PAPER_ID_RE` are locked byte-equal by
`tests/test_identifiers.py::TestPaperIdRegex`. Any change to the arXiv alternatives
must propagate to all three. Textbook alternative must be added to all three when
`is_valid_paper_id` is extended (or the equality test must be narrowed — adding to all
three is simpler). The chunker and eval-fixture copies carry only the arXiv branches.

## 2026-05-22 — m10 — ar5iv-html-storage-TWO-paths-search-order
TWO HTML paths: (1) m8 upload → `var/arxmcp/notebooks/<slug>/ar5iv/<flat_paper_id>.html`
(flat, notebook-scoped); (2) ingest pipeline → `var/arxmcp/corpus/parsed/<paper_id>/index.html`
(subdirectory per paper, corpus-global). Preview must check (1) first, then (2).
flat_paper_id = paper_id.replace("/", "_") for both lookups.

## 2026-05-22 — m10 — csp-frame-ancestors-form-action-base-uri-not-default-src-fallback
CSP3: frame-ancestors, form-action, base-uri are NOT fetch directives — they do NOT
fall back to default-src. When omitted from a CSP, frame-ancestors allows any origin
to frame the page, form-action allows form POST to any origin, base-uri is unrestricted.
All three must be set explicitly when writing a tight per-route CSP.

## 2026-05-22 — m10 — m9-scope-invariant-test-blocks-m10-frontend-changes
tests/test_m9_scope_invariants.py greps frontend/ for `iframe|preview` and fails if
found. m10 adds both tokens. Implementer must delete or repurpose this test before
committing the m10 frontend changes.

## 2026-05-22 — m10 — preview-route-must-not-go-under-ui-api-prefix
notebooks_router is mounted at /ui/api (server/main.py:552). The m10 preview route
is at /ui/notebooks/{slug}/papers/{paper_id}/preview (no /api). Must be added to
server/routes/ui.py or a new preview router mounted at /ui (not /ui/api).

## 2026-05-17 — E13_S02 — E13-brief-tool-list-drift-is-systematic
The E13 roadmap's tool list names `paper_diff` + `dependency_graph` (non-existent)
and omits `get_definitions` + `find_lemma_by_name` (real). This drift is present in
every E13 milestone brief. Always reframe to `server/tools.py::ALL_TOOLS` as the
authoritative 7-tool list.

## 2026-05-17 — E13_S02 — E07-fictional-milestones-pattern
E07 roadmap has only S01–S04. Any brief referencing E07_S05 through E07_S13 as
a dependency is citing a fictional milestone. The audit milestone is BOTH enforcement
AND verification. Confirmed for E07_S12 (E13_S01) and E07_S13 (E13_S02).

## 2026-05-17 — E13_S02 — no-delimiter-wrapping-exists-at-v1
As of E13_S02, ZERO handlers in `server/handlers/` wrap retrieved content in
`<retrieved_chunk>` or `<retrieved_equation>` delimiters. This is a full
enforcement gap, not a partial coverage gap. All 7 tools return raw content.

## 2026-05-17 — E13_S01 — doc-placement-correction-pattern
E13 milestone briefs mandate `docs/security/threat-N-audit.md`. CLAUDE.md §1
restricts `docs/` to operator-facing content. Correct destination is always
`.claude/docs/security-threat-N-audit.md`. Established precedent in E13_S01
implementation-summary §Drift item 7.

## 2026-05-18 — E13_S03 — latexml-sandbox-is-aspirational-only
`tools/arxiv_fetch.py::parse_with_latexml` invokes latexmlc via subprocess.run
with timeout=300 (Python-level SIGKILL). NO sandbox-exec/seccomp/landlock wrapper
exists. The code comments explicitly say it is "unsandboxed dev tooling." The
sandbox is documented ONLY in `08-security-observability-ops.md` §Threat 3 and
deferred to production E11 ingestion. E13_S03 is BOTH spec AND validation.

## 2026-05-18 — E13_S03 — parse_status-field-does-not-exist
`parse_status="parse_failed"` is not a field anywhere in ingest/. Parser failures
go to JSONL logs (`ops/parser-failures/bulk.jsonl`) with fields: paper_id,
parsers_tried, failure_reason, timestamp. The `ParseResult` dataclass (tools/
arxiv_fetch.py) has `success: bool`. AC using `parse_status="parse_failed"` must
be reframed to `ParseResult.success == False`.

## 2026-05-18 — E13_S03 — no-docker-compose-exists
No docker-compose.yml exists in the repo (only `infra/observability/phoenix-compose.yml`).
The docker design spec in `08-security-observability-ops.md §Docker deployment` is
aspirational. Any brief AC requiring `docker inspect` verification against a
LaTeXML service must be reframed as deferred to E14.

## 2026-05-18 — E13_S03 — latexmlc-timeout-flag-and-lua
latexmlc has its own `--timeout=secs` (default 600). Pass `--timeout=300` to latexmlc
AND use Python subprocess.run(timeout=305) for defense-in-depth. latexmlc does NOT
support LuaTeX/\directlua — large_alloc via "Lua snippet" is fictional; use deeply
nested macro expansion instead. \write18 is silently ignored by latexmlc (no shell exec).

## 2026-05-18 — E13_S03 — sandbox-exec-deprecated-but-functional
macOS `sandbox-exec` is marked DEPRECATED (man page confirms). It is still functional
on Darwin 25.4.0. The .sb profile syntax is Scheme-like: (version 1), (deny default),
(allow ...). The proper successor requires App Sandbox + code signing — unsuitable for
ad-hoc subprocess wrapping. Use sandbox-exec but document deprecation in the audit doc.

## 2026-05-18 — E13_S04 — e06-s07-s08-e07-s10-all-fictional
E06 has only S01–S06; E07 has only S01–S04. E06_S07, E06_S08, E07_S10 cited as
E13_S04 dependencies do not exist. Same fictional-dependency pattern as E07_S12 /
E07_S13 in E13_S01 / E13_S02. E13_S04 is BOTH spec AND enforcement.

## 2026-05-18 — E13_S04 — no-hourly-rate-limiter-exists
`server/session.py` caps ONLY per-session retrieval rounds (3 search, 4 get_chunk)
per E08_S04 design. There is NO 1000/hour or 60/minute global tool-call rate limiter
anywhere. E13_S04 must implement a new `HourlyRateLimitMiddleware` (pure-ASGI). The
-32005 error code does not exist in the MCP spec or mcp Python SDK; use `isError=True`
with `code="RATE_LIMIT_REACHED"` mirroring the existing RETRIEVAL_CAP_REACHED pattern.

## 2026-05-18 — E13_S04 — enforce-byte-cap-coverage-gap
Only `get_chunk` and `get_definitions` call `enforce_byte_cap`. `search_papers`,
`find_equation`, `find_lemma_by_name`, `get_paper`, `cite_neighbors` do NOT. The 256 KB
byte-cap AC tests should target `get_chunk` (where enforcement actually exists).

## 2026-05-18 — E13_S04 — filters-dict-has-no-count-cap
`search_papers.filters: dict[str, Any] | None` has no item-count limit. 10k-item dict
passes schema validation. Adding a Pydantic Field constraint would re-pin
EXPECTED_TOOL_SCHEMA_SHA256 + bump TOOL_SCHEMA_VERSION (BP1 cache cost). Use handler-body
`raise ValueError` instead (invisible to tool schema, same security outcome).

## 2026-05-18 — E13_S05 — host-and-origin-validation-already-shipped
`HostValidationMiddleware` and `OriginValidationMiddleware` are both SHIPPED (E06_S05).
Host validation already rejects `attacker.localhost` and public IPs via exact frozenset
match in `_validate_host_header`. Bind-host 0.0.0.0 rejection already works in
`config.py::reject_non_loopback`. E13_S05 adds Sec-Fetch-Site enforcement (full gap),
ARXMCP_ALLOWED_ORIGINS (new Config field), and ARXMCP_UNSAFE_NETWORK_BIND (new Config
field requiring field-validator refactor to model-validator).

## 2026-05-18 — E13_S05 — e07-s01-wrong-origin-attribution
E07_S01 is "Phase 1: BM25 over body_tokens" — not Origin validation. Origin
validation shipped in E06_S05. The E13_S05 brief's "E07_S01 (Origin pin)"
dependency is wrong attribution. Real dependency is E06_S05.

## 2026-05-18 — E13_S05 — unsafe-network-bind-needs-model-validator
`Config.reject_non_loopback` is a `@field_validator("bind_host")` — runs before
`unsafe_network_bind` is available. To add the escape-hatch, convert to
`@model_validator(mode="after")` that checks both fields. Tests in
`test_server_startup.py::TestConfigValidation` may assert field-level ValueError;
verify they still pass after the refactor to model-level validation.

## 2026-05-19 — E13_S06 — reranker-already-threat-6-compliant-embedder-incomplete
Reranker (server/retrieval/rerank.py + server/resources.py) already enforces:
SHA pinning (BGE_RERANKER_COMMIT_SHA), use_safetensors=True, trust_remote_code=False
(implicit default; make explicit), and SHA-drift warning at startup. Embedder
(ingest/embedder.py) pins SHA (BGE_M3_COMMIT_SHA) and trust_remote_code=False but
CANNOT enforce use_safetensors=True because the pinned SHA ships .bin-only (documented
gap deferred to future SHA bump). E13_S06 closes embedder gap via shared validator
+ explicit trust_remote_code pass.

## 2026-05-19 — E13_S06 — no-ci-github-workflows-exists
Brief calls for `.github/workflows/sbom.yml` but no .github/ dir exists per CLAUDE.md
§4.1 (no CI blocking merges). Replace with `Makefile sbom` target invoking local
cyclonedx-bom + grype that developers run manually before pushing.

## 2026-05-19 — E13_S06 — no-default-embed-sha-config-constant
Brief says "pinned in `server/config.py` as `DEFAULT_EMBED_SHA` and `DEFAULT_RERANK_SHA`"
but these don't exist. Config has `rerank_model_sha` field (for drift check), but no
module constant. Embedder SHA lives only in ingest/embedder.py::BGE_M3_COMMIT_SHA.
No need to add config constants — module-level ones are already canonical.

## 2026-05-28 — notebook-retrieval-m2 — slug-in-key-via-filter-preservation
DO NOT strip `notebook` from `filters` before calling `derive_tier1_key`. The
`canonical_key_components` helper already length-prefixes `filters_json` — leaving
`notebook` in the dict means the key IS slug-scoped without adding a new key component.
Strip `notebook` ONLY from the predicate-building path (LanceDB `.where()`). Tier-2
`_filter_fingerprint` also uses `filters`, so it's automatically slug-scoped too.

## 2026-05-28 — notebook-retrieval-m2 — notebook-is-routing-key-not-filter-key
`"notebook"` must NOT be added to `SUPPORTED_FILTER_KEYS` (which has two copies:
`server/handlers/search.py:249` and `server/retrieval/bm25.py:117`). It is a routing
key processed before predicate-building. Adding it to `filter_warnings` is also wrong —
it would emit a spurious warning on every notebook-scoped call. Strip silently after
routing; do NOT echo in `filters_applied` or `filter_warnings`.

## 2026-05-28 — notebook-retrieval-m2 — fork-C-and-fork-A-coexist-via-per-call-wins
m1 set `cache_db_path` = per-notebook sibling when `ARXMCP_NOTEBOOK` is set (fork-C).
m2 fork-A uses the shared `cache_db_path` (ARXMCP_NOTEBOOK unset). When BOTH are set
(env + per-call filters), per-call `filters.notebook` wins — the handler opens the
per-call table regardless of the process-level default. These two mechanisms are
compatible because they live at different code layers.

## 2026-05-19 — E13_S07 — e11-s02-100mb-cap-not-shipped
Brief asserts "E11_S02 already enforces the 100 MB content-length cap." FALSE.
E11_S02 implementation summary + code have ZERO 100 MB enforcement. Only per-service
caps exist: OpenAlex 5 MB, INSPIRE 8 MB, ar5iv intra_paper_refs 50 MB. The 100 MB
threshold is documented in `08-security-observability-ops.md` § Threat 7 as a
*mitigation goal*, not an implemented feature. E13_S07 must deliver this cap from
scratch (gap-closure + audit dual role, like E13_S01 for path-traversal).

## 2026-05-19 — E13_S07 — urllib-request-no-shared-client-needed
Brief mandates "single shared `httpx.Client` at module import time." Codebase uses
ZERO httpx imports; all source ingestion uses `urllib.request.urlopen` (ar5iv_fetch,
oai_delta, graph_ingest, inspire_ingest, arxiv_fetch, tools/curate_seed, daily_metrics).
TLS verification is enabled by default in urllib; no escape hatch. No `verify=False`
anywhere in the codebase (grepped entire repo). The brief's `ingest/sources/` directory
does NOT exist (actual sites scattered across ingest/ + tools/). Refactoring urllib
to httpx has negative ROI; audit the status quo instead (already safe-by-default).

## 2026-05-19 — E13_S07 — no-ingest-sources-directory-exists
Brief says "all HTTP clients in `ingest/sources/` must instantiate a single shared
httpx.Client." The directory `ingest/sources/` does NOT exist. Actual HTTP clients:
- ar5iv_fetch.py
- oai_delta.py
- graph_ingest.py
- inspire_ingest.py
Plus tools/ (arxiv_fetch, curate_seed, daily_metrics_report). All use urllib.request.

## 2026-05-19 — E13_S08 — e07-s08-does-not-exist
Brief lists E07_S08 as a dependency ("structured logging scaffolding"). E07 has only
S01–S04. Actual logging state: stdlib logging everywhere, `log_level` config field
shipped, no logging.py in server/observability/ yet. The brief is aspirational about
a non-existent milestone. E13_S08 is pure-new implementation of the filter.

## 2026-05-19 — E13_S08 — docs-placement-security-observability
Brief says `docs/observability/log-redaction.md`. Correct destination per prior E13
milestones is `.claude/docs/security-observability-logging.md` (audit docs live
under .claude/docs/, not docs/). Prior precedent: E13_S01–S07 all use
.claude/docs/security-threat-N-audit.md format.

## 2026-05-19 — E13_S09 — bind-regression-is-audit-not-net-new-test
E13_S05 already shipped `Config.unsafe_network_bind` field + `reject_non_loopback_bind()`.
E13_S09 is purely a REGRESSION TEST + AUDIT, NOT new feature implementation.
Existing coverage: `test_origin_binding.py::TestUnsafeNetworkBindEscapeHatch` (4 tests),
`test_security.py::TestStartupRejectsBadBind` (subprocess path). E13_S09 aggregates these
into a dedicated `test_bind_regression.py` file focused on the TCP-bind layer regression
surface. The brief's ACs are all satisfied by existing tests; the milestone adds test
organization and explicit regression pinning.

## 2026-05-19 — E13_S09 — exception-type-mismatch-brief-vs-code
Brief AC#2 says "raises ConfigError"; code/tests actually raise ValidationError
(pydantic's wrapper on the ValueError raised by the model-validator). This is
NOT a bug — brief wording is imprecise. The test at test_origin_binding.py:341
correctly asserts `pytest.raises(ValidationError, match="must be a loopback")`.
Implementer should NOT change the exception type; it is correct as-is.

## 2026-05-23 — parser-fidelity-eval-m1 — cdm-bbox-detection-is-color-lookup-not-connected-components
CDM algorithm (arXiv:2409.03643) uses colored-token rendering: each LaTeX token
gets a unique RGB color, then bbox = np.where(arr == color). No OpenCV/scikit-image
needed for bbox detection — pure NumPy suffices. scipy.optimize.linear_sum_assignment
(BSD-3-Clause) needed for Hungarian assignment; NOT in pyproject.toml yet.

## 2026-05-23 — parser-fidelity-eval-m1 — opencv-banned-for-cdm-due-to-kmp-landmine
OpenCV adds Intel OpenMP runtime that conflicts with PyTorch's OpenMP under faiss-cpu
on macOS (exact KMP_DUPLICATE_LIB_OK landmine from CLAUDE.md §8). Use NumPy-only
bbox detection + scipy Hungarian. pdftoppm (poppler-utils) for PDF→PNG; lighter than
ImageMagick and avoids ImageMagick CVE surface.

## 2026-05-23 — parser-fidelity-eval-m1 — pdflatex-sandbox-flags
pdflatex --no-shell-escape disables \write18 entirely (Jan 2025 latexref.xyz confirms).
Combine with --interaction=nonstopmode + start_new_session=True + os.killpg pattern
(same as parse_with_latexml in tools/arxiv_fetch.py). 30s timeout is right for
single-equation CDM renders.

## 2026-05-19 — E13_S09 — e07-s09-dependency-is-fictional
E07 has only S01–S04. The brief cites E07_S09 as a dependency, following the
systematic drift pattern from prior E13 milestones. Should cite E13_S05 instead
(HTTP-layer Threat 5 closure; E13_S09 closes TCP-bind layer of same threat).
Implementer should NOT spend effort on nonexistent E07_S09.

## 2026-05-19 — E13_S10 — threat-model-coverage-is-pure-review-audit
E13_S10 is NOT a new-feature milestone. All E13_S01–S09 are complete (phase=complete,
no deferred findings). E13_S10 aggregates them into a single 7-row threat-model
coverage table: Threat#, Mitigation epic, Audit epic (E13_SXX), Test files,
Gap issues. The table documents which test file covers each threat and links any
filed GitHub issues for discovered gaps (byte-cap enforcement partial coverage,
BGE-M3 .bin-only limitation). Doc placement is `.claude/docs/security-threat-model-coverage.md`
(not `docs/security/`). No new tests; no code changes. Pure documentation + issue filing.

## 2026-05-19 — E13_S10 — known-gaps-from-audit-cycle
(1) Byte-cap enforcement: only `get_chunk` + `get_definitions` enforce 256 KB;
5 other tools don't. (2) BGE-M3 .bin-only: current pinned SHA ships .bin format
only; safetensors enforcement waits for future SHA bump. (3) urllib vs httpx:
brief aspired to httpx refactor; implementation uses urllib (safe by default);
no gap. All gaps should be filed as GitHub issues during E13_S10 implementation
+ linked in coverage doc.

## 2026-05-20 — E13_S04b — enforce-byte-cap-all-handlers-canonical-helper
The `server/tools.py::enforce_byte_cap` helper is the canonical, single-source
implementation. It accepts `body_text_path` tuple to locate the body in nested
payloads (e.g., `("chunk", "body_text")` for get_chunk vs top-level for others).
E13_S04b extends it to all 5 remaining tools (search_papers, find_equation,
find_lemma_by_name, get_paper, cite_neighbors). NO extraction needed; use existing
helper. Handler-body calls only — no schema changes (preserves BP1 cache stability).

## 2026-05-20 — E13_S04b — handler-cap-pattern-synthetic-test-fixture
Testing the byte cap requires mocking. Pattern: `unittest.mock.patch` on
`Config.result_byte_cap` to lower it (e.g., 1 KB), then construct a payload that
exceeds it. Avoids large fixture files. The cap check uses: `len(json.dumps(...).encode("utf-8")) * _WIRE_OVERHEAD_FACTOR <= cap`
where _WIRE_OVERHEAD_FACTOR ~= 2. Test should patch both the constant and the
config to force cap firing predictably.

## 2026-05-22 — E13_S07c — ssl-pin-factory-pattern
`ssl.create_default_context(cafile=path)` is the ONLY safe CA-pin form — preserves
check_hostname=True and verify_mode=CERT_REQUIRED, does NOT trigger TestTlsCannotBeDisabled
walk. urlopen takes `context=ssl_ctx` kwarg (cafile/capath on urlopen itself deprecated
since py3.6). Both `ingest/ar5iv_fetch.py::try_cache` and `tools/arxiv_fetch.py::fetch_eprint`
have NO ssl_context injection point today — both need a new optional `ssl_context` param.
Vendor bundle at `infra/ca/arxiv-ca-bundle.pem` (ISRG Root X1/X2 only; stable for years).
FAIL CLOSED when pin=True but bundle missing — never fall back to system trust store silently.

## 2026-05-22 — E13_S07b — redirect-pin-two-error-types
ar5iv_fetch returns miss-result on redirect-off-host; oai_delta raises RuntimeError.
graph_ingest + inspire_ingest should raise RuntimeError (matches their exception-
propagation caller model). Capture `response_url = resp.url` INSIDE the `with urlopen`
block; check AFTER. Use `OPENALEX_BASE + "/"` and `INSPIRE_API_BASE + "/"` as startswith
prefix (mirrors ar5iv trailing-slash pattern to prevent prefix-collision). New tests go
in EXISTING `tests/security/test_source_ingest.py` as a new class — file already cited
in coverage doc so no doc-citation gate update needed.

## 2026-05-22 — E13_S07c — ssl-context-injection-pattern-for-urllib
`urllib.request.urlopen(req, context=ssl_context)` is the correct injection point
for custom SSLContext. `ssl.create_default_context(cafile=path)` creates a pinned-CA
context that preserves `check_hostname=True` + `CERT_REQUIRED`. Add optional
`ssl_context: ssl.SSLContext | None = None` param to fetch functions; callers pass
None (system trust store) or a pre-built context (pinned CA). Module-level singleton
is anti-pattern; explicit parameter threading is correct.

## 2026-05-22 — E13_S07c — config-optional-path-for-optional-feature-pattern
The canonical pattern for "feature enabled by bool + optional path override" in
Config is: `enable_x: bool = False` + `x_path: Path | None = None`. See `enable_lean`
+ `lean_repl_dir` in `server/config.py`. For CA pinning: `pin_arxiv_ca: bool = False`
+ `arxiv_ca_bundle_path: Path | None = None`. Validation goes in `@model_validator(mode="after")`
so both fields are visible. Fail-closed: if pin=True and path resolves to missing file -> raise ValueError.

## 2026-05-22 — E13_S07c — letsencrypt-isrg-root-x1-is-stable-pin
arxiv.org and ar5iv.labs.arxiv.org use Let's Encrypt certs. Root CA is ISRG Root X1
(valid until 2035). Intermediates (E5, R10) rotate ~90 days. Vendor ISRG Root X1
PEM ONLY — not intermediate or leaf — for a rotation-stable bundle. Source:
letsencrypt.org/certs/ (public, non-secret PEM material).

## 2026-05-21 — m6 — bm25-indexer-has-no-root-override
`build_bm25_index(lancedb_path, corpus_version)` writes to the hardcoded
`BM25_INDEX_ROOT = REPO_ROOT/var/arxmcp/index/bm25`. No output-root override
parameter exists. For per-notebook BM25, the per-notebook corpus_version
makes the global path effectively per-notebook (version is unique per notebook).
Brief claims `notebooks/<slug>/index/bm25/vN/` — this is aspirational drift.

## 2026-05-21 — m6 — notebook-scripts-use-urllib-not-httpx
All existing fetch tooling (ar5iv_fetch, oai_delta, graph_ingest, inspire_ingest,
arxiv_fetch, curate_seed) uses urllib.request. No httpx anywhere. Ad-hoc bootstrap
scripts (/tmp/bridgeland_fetch.py etc) also use urllib.request. notebook_fetch.py
must follow suit. timeout=30 for HTTP reads; time.sleep(3.0) for inter-request
politeness (applies to both arxiv.org and ar5iv.labs.arxiv.org per brief AC#2).

## 2026-05-21 — m6 — bulk-ingest-parsed-dir-flag-was-removed
`--parsed-dir` was removed from `ingest.bulk_ingest` CLI (F2 fix; bulk_ingest.py:461).
`notebook_ingest.py` must NOT pass `--parsed-dir`. Chunker always reads from
module-level `ingest.chunker.PARSED_DIR` (var/arxmcp/corpus/parsed/). Variant 1
keeps corpus/parsed/ global; per-notebook scope is only lancedb + bm25.

## 2026-05-21 — m6 — slug-regex-is-canonical-defense
notebook_purge.py + notebook_init.py MUST validate slug against
`^[a-z][a-z0-9-]{2,30}$` BEFORE any path construction. resolve() alone
is insufficient — it resolves existing traversal targets successfully.
Belt: regex gate. Suspenders: (notebooks_base/slug).resolve() containment check.

## 2026-05-22 — m4 — corpus-version-json-paper-count-is-batch-not-cumulative
`corpus-version.json`'s `paper_count` field = len({c.paper_id for c in chunks})
where `chunks` is the LAST batch passed to write_chunks(), NOT the cumulative DB
count. Per-paper bulk_ingest calls write_chunks once per paper, so the field
shows 1. AC thresholds must use `SELECT COUNT(DISTINCT paper_id) FROM chunks`
via lancedb.connect(), not the corpus-version.json marker.

## 2026-05-22 — m4 — both-notebooks-fully-pre-ingested
As of 2026-05-22: bridgeland-stability has 39 unique papers in lancedb (4505
chunks); shimura-varieties has 12 (3625 chunks). ALL 51 paper HTMLs are pre-cached
at var/arxmcp/corpus/parsed/. BM25 v157 (bridgeland) and v49 (shimura) exist but
lack .notebook_slug sentinels (predate m6 F2 fix). Write sentinels manually.

## 2026-05-22 — m4 — validate-eval-fixtures-has-no-notebook-scope
tools/validate_eval_fixtures.py accepts --fixture and --chunks-dir only. It
enforces TARGET_QUERY_COUNT=20 with no per-notebook variant. AC #4 ("extended to
accept per-notebook scope field") requires a NEW tools/validate_notebook_fixtures.py
or explicit extension. Running the existing script against per-notebook queries.json
will fail with "expected 0 or 20 queries; got N".

## 2026-05-21 — m6 — bulk-ingest-uses-cli-not-env
`ingest/bulk_ingest.py` does NOT read ARXMCP_LANCEDB_PATH. It uses
`--lancedb-staging-path` CLI argument (line 445). The brief's env-var
wiring description is wrong. notebook_ingest.py must call
run_bulk_ingest() directly with lancedb_staging_path param or use
subprocess with --lancedb-staging-path flag.

## 2026-05-21 — m6 — old-style-paper-ids-in-bridgeland
bridgeland-stability/papers.txt contains `0705.3794` (old-style, pre-2010).
tools/arxiv_fetch.py::PAPER_ID_RE only matches new-style. Use
ingest.identifiers.is_valid_paper_id for all paper_id validation in
notebook scripts — it handles both old-style and new-style.

## 2026-05-21 — m6 — pdf-deferred-dir-must-survive-init-idempotency
shimura-varieties/pdf-deferred/ exists with manifest.json + 2 PDFs.
notebook_init.py idempotency check (if dir exists: skip) protects it.
notebook_purge.py must warn before rmtree if pdf-deferred/ present.

## 2026-05-21 — m6 — ar5iv-429-is-miss-not-drop
ar5iv_fetch.try_cache returns hit=False with reason="http_429" on 429.
notebook_fetch.py must surface 429s distinctly from true misses — they
are transient (retry after backoff), not permanent drops.

## 2026-05-21 — m1 — cache-already-includes-filters-in-key
server/cache.py + cache_sqlite.py ALREADY include `filters` in the Tier-1
and Tier-2 cache keys via `canonical_key_components`. No cache-layer changes
needed when wiring paper_id filter through search_papers. Brief says "update
cache key" but it is already correct — do NOT modify cache.py.

## 2026-05-21 — m1 — ann-where-no-prefilter
LanceDB ANN + .where() (without prefilter=True) is validated by spike-1.
`prefilter=True` is for full-table-scan calls (get_paper, get_chunk). Do NOT
add prefilter=True to the ANN search in search_papers handler.

## 2026-05-21 — m1 — tests-handlers-dir-does-not-exist
tests/handlers/ does NOT exist in this repo. Handler-specific tests are flat
under tests/ (test_snippet_contract.py, test_tools_all.py, etc). Brief's
tests/handlers/test_search_filter.py → use tests/test_search_filter.py instead.

## 2026-05-21 — proof-verify-handler-wiring-m1 — lancedb-where-predicate-pattern
LanceDB `.where("paper_id IN ('a','b')")` uses single-quoted string literals.
No parameterized query API (documented in ingest/index_definitions.py:404-405).
`_escape_sql = lambda s: s.replace("'","''")` is the project-standard escape.
Pattern in production: `server/graph_queries.py:261-263` and `intra_paper_refs.py:218-226`.

## 2026-05-21 — proof-verify-handler-wiring-m1 — cache-key-already-includes-filters
The 3-tier cache (Tier-1 via `derive_tier1_key`, Tier-2 via `_filter_fingerprint`)
already includes `filters` in its key using `canonical_key_components`. m1 needs
ZERO cache changes — validate this is not re-done by the implementer.

## 2026-05-21 — proof-verify-handler-wiring-m1 — max-filter-items-is-dict-key-count-not-list-length
`MAX_FILTER_ITEMS = 100` at search.py:97 caps the number of KEYS in the filters
dict, not the length of a list-valued item. A `{"paper_id":[10_000 ids]}` passes
the existing guard. A separate `MAX_PAPER_ID_FILTER_ITEMS` list-length cap is needed.

## 2026-05-21 — proof-verify-handler-wiring-m2 — filters-applied-requires-schema-version-bump
Adding `filters_applied` to the search_papers output requires: (1) add to
`server/schemas/search_papers_result.json::properties` (optional, not in `required`);
(2) bump `schema["version"]` and `TOOL_SCHEMA_VERSION` from 8→9 in lockstep;
(3) re-pin EXPECTED_TOOL_SCHEMA_SHA256 + EXPECTED_BP1_SHA256. The TOOL_SCHEMA_VERSION
bump changes `_meta` in ALL_TOOLS → changes `tools/list` bytes → invalidates BP1 hash.

## 2026-05-21 — proof-verify-handler-wiring-m2 — degraded-fields-not-in-schema-pre-existing-gap
`search_papers` emits `degraded`/`degraded_reasons` (lines 469-471 of search.py)
but neither field is in `search_papers_result.json::properties`. The
`additionalProperties: false` schema would reject them. Test passes only because
`r.degraded is None` in fixtures. m2 should fix this companion gap when bumping
the schema version.

## 2026-05-21 — proof-verify-handler-wiring-m2 — restamp-pattern-for-post-cache-injection
The established pattern for injecting request-specific data post-cache is `_restamp_*`
(see `_restamp_degraded` in search.py). For `filters_applied`, introduce a parallel
`_inject_filters_applied(structured, canonical_filters)` helper that adds the field
only when `canonical_filters is not None`. Apply at Tier-1 hit, Tier-2 hit, and miss
paths. Do NOT store `filters_applied` in the cached payload (caller-specific metadata).

## 2026-05-22 — proof-verify-m3 — docs-ops-runbook-pattern-is-established
`docs/ops/` is the established location for operator runbooks in arXMCP.
README.md:63-76 already links 10 runbooks there. New operator-facing runbooks
belong in `docs/ops/`, NOT in `docs/install.md` or a new `docs/*.md` top-level file.
Milestone briefs that suggest `docs/install.md` or `docs/notebooks.md` as a
destination for a deployment-topology runbook should be redirected to `docs/ops/`.

## 2026-05-22 — proof-verify-m7 — SecFetchSite-carveout-via-exempt-prefixes
SecFetchSiteMiddleware has NO path-carve-out mechanism at v1. Canonical pattern:
add `exempt_prefixes: tuple[str,...] = ()` constructor param, check
`any(path == p or path.startswith(p+"/") for p in ...)` at top of __call__.
Mirror BodySizeCapMiddleware's `_BYTE_CAP_EXEMPT_PREFIXES` shape exactly.

## 2026-05-22 — proof-verify-m7 — notebook-sqlite-db-placement
Notebook SQLite DB belongs at `var/arxmcp/notebooks/notebooks.db` (sibling to
per-notebook dirs). Opened independently in the lifespan, attached to
`app.state.notebook_store`. Do NOT fold into `Resources.startup()`.

## 2026-05-22 — proof-verify-m7 — slug-regex-in-tools-not-server
`tools._notebook_common.SLUG_RE` and `validate_slug()` are the canonical slug
validators (m6). REST handlers in `server/routes/notebooks.py` MUST import from
there, not redefine. Import path: `from tools._notebook_common import validate_slug, notebook_dir`.

## 2026-05-22 — proof-verify-handler-wiring-m7 — sec-fetch-site-carve-out-is-real-bug
SecFetchSiteMiddleware rejects ALL non-`none` values including `same-origin`. Once a
browser-served `/ui/` exists, htmx POSTs from `http://127.0.0.1:7733/ui/` to
`/ui/api/...` set `Sec-Fetch-Site: same-origin`. The carve-out is genuine and
necessary. Use path-prefix guard (startswith("/ui/")) mirroring SessionCapMiddleware.
Do NOT use `app.mount()` sub-app (Option B) — it bypasses the global middleware stack.

## 2026-05-22 — proof-verify-handler-wiring-m7 — notebooks-db-must-be-separate-file
Adding notebook tables to `cache_db_path` (retrieval.db) risks triggering
Tier1Store's DROP-AND-RECREATE migration (it checks PRAGMA user_version). Always
use a separate `notebooks.db` sibling file. Add `Config.notebooks_db_path` following
the `cache_db_path` / `theorem_names_db_path` pattern in server/config.py.

## 2026-05-22 — proof-verify-handler-wiring-m7 — sqlite-async-pattern-is-asyncio-to-thread
All SQLite in this codebase uses `asyncio.to_thread` + `asyncio.Lock` (NOT aiosqlite).
See server/cache_sqlite.py. New stores must inherit this exact pattern. SQLite FK
enforcement (PRAGMA foreign_keys=ON) is off by default; any schema with FOREIGN KEY
constraints must enable it explicitly per connection.

## 2026-05-22 — proof-verify-handler-wiring-m8 — missing-deps-jinja2-and-multipart
`jinja2` and `python-multipart` are NOT in pyproject.toml as of m8.
FastAPI's `Jinja2Templates` needs `jinja2>=3.1`; `UploadFile` needs
`python-multipart>=0.0.9`. Any milestone adding an HTML UI or file upload
MUST add both deps explicitly.

## 2026-05-22 — proof-verify-handler-wiring-m8 — body-size-cap-covers-responses-not-requests
`BodySizeCapMiddleware` in `server/main.py` caps RESPONSE bodies (256 KB).
`RequestBodySizeLimitMiddleware` in `server/middleware.py` caps REQUEST bodies (1 MB).
Upload carve-outs only need `RequestBodySizeLimitMiddleware` extension. HTML pages
served as responses risk 413 from `BodySizeCapMiddleware` — add `/ui/` to
`_BYTE_CAP_EXEMPT_PREFIXES` when shipping a Jinja2 HTML surface.

## 2026-05-22 — m8 — htmx-2x-size-is-87kb-not-14kb
htmx 2.0.10 htmx.min.js is ~87 KB on disk (~51 KB gzip). The brief's "14 KB"
is the htmx 1.x era figure. Vendor 87 KB raw file; uvicorn StaticFiles serves
it gzip-compressed. License is Zero-Clause BSD (0BSD), not BSD-2-Clause.

## 2026-05-22 — m8 — ar5iv-url-normalizer-gap-is-deliberate-m7-defer
server/routes/notebooks.py::_ACCEPTED_HOSTS only contains "arxiv.org".
Line 100 explicitly says ar5iv is out of m7 scope. m8 AC#3 requires ar5iv
support. Implementer must add ar5iv.labs.arxiv.org + /html/ prefix to
_arxiv_url_to_paper_id. This is NOT a bug in m7 — it is a planned m8 task.

## 2026-05-22 — m8 — jinja2-python-multipart-are-transitive-via-mcp
jinja2==3.1.6 and python-multipart==0.0.27 are both installed as transitive
deps of mcp>=1.27.1. They are NOT declared in pyproject.toml. m8 must add
explicit declarations: jinja2>=3.1.3 and python-multipart>=0.0.18 (CVE floor).

## 2026-05-22 — proof-verify-handler-wiring-m9 — notebook-ingest-is-sync-requires-subprocess
tools/notebook_ingest.py::run() is SYNCHRONOUS (calls run_bulk_ingest which is a
blocking for-loop). Cannot use asyncio.to_thread for fire-and-forget server tasks
when stderr capture is required. Use asyncio.create_subprocess_exec(stderr=PIPE).
FastAPI BackgroundTasks are not suitable (not cancellable, not tracked in app.state).

## 2026-05-22 — proof-verify-handler-wiring-m9 — additive-migration-vs-drop-recreate
NotebooksStore uses DROP-AND-RECREATE for schema bumps (same as cache_sqlite.py).
Adding a new table (notebook_ingest_runs) MUST use additive migration (CREATE TABLE
IF NOT EXISTS) in a guarded `if current_version < N:` branch. Never replicate the
destructive pattern when live notebook data exists.

## 2026-05-22 — proof-verify-handler-wiring-m9 — asyncio-to-thread-for-cpu-sync-ingest
`run_bulk_ingest` is synchronous + CPU-bound (BGE-M3 embedding). The correct async
shell is `asyncio.create_task(asyncio.to_thread(run, slug))` — NOT
`create_task(coroutine_calling_sync_fn())` which blocks the event loop. htmx 286
status code stops polling on terminal states (htmx-canonical; no JS needed).
Store task references in `app.state` dict to prevent GC; `done_callback` updates DB.

## 2026-05-22 — E14_Tier5plus — metric-name-drift-request-vs-tool-latency
S09 Grafana brief uses `arxmcp_tool_latency_seconds` but actual registered name is
`arxmcp_request_latency_seconds` (server/observability/metrics.py:67). Cache tier
label is `tier` (string "1"/"2"/"3"), not `layer`. Embed singleflight dedup counter
is in server/health.py (not server/observability/metrics.py). Reranker latency has
`{model}` label. All dashboard PromQL must use these actual names.

## 2026-05-22 — E14_Tier5plus — restore-runbook-name-drift
E14_S10 brief references `docs/ops/restore-runbook.md` (from E14_S05). Actual file
is `docs/ops/backup-restore.md`. The brief's file name is documented drift. Link to
backup-restore.md in the runbook index.

## 2026-05-22 — E14_Tier5plus — E08_S07-haiku-summarizer-not-shipped
No E08_S07 milestone exists (milestones only go E08_S01–E08_S05). Haiku summarizer
is explicitly a stub in server/observability/tracing.py:482 (never entered in v1).
S12 ships Voyage path only; leave TODO for Haiku increment referencing E08_S07.

## 2026-05-22 — E14_Tier5plus — voyage-is-stub-always-raises
server/query_encoder.py::_voyage_encode_stub() always raises NotImplementedError
("voyage HTTP client not yet implemented; see E14_S05 D6"). The S12 spend counter
increment fires on the fallback path (after the stub raises). No server/embedder/ or
server/summarizer/ directories exist; S12 code goes in server/query_encoder.py.

## 2026-05-22 — E14_Tier5plus — server-observability-dir-exists-already
`server/observability/` was created by E14_S01 with __init__.py. Any brief
calling it a "NEW directory; create with __init__.py" is wrong — it exists.
The 6 files present: log_filter, logging_setup, metrics, sanitize, tracing, __init__.

## 2026-05-22 — E14_Tier5plus — mcp-session-id-not-emitted-as-response-header
Server ONLY consumes Mcp-Session-Id (stored to ContextVar via TracingContextMiddleware).
It is NEVER emitted in responses. Langfuse doc snippets must note: caller attaches the
session ID they sent (not from a response header). Verified by grep across server/.

## 2026-05-22 — E14_Tier5plus — voyage-stub-raises-not-implemented
_voyage_encode_stub in server/query_encoder.py raises NotImplementedError immediately.
Any S12 spend counter for voyage must be a TODO — no real call site exists yet.

## 2026-05-22 — E14_Tier5plus — docs-ops-restore-runbook-name-mismatch
docs/ops/ has `backup-restore.md`, NOT `restore-runbook.md`. The E14_S05 brief and
E14_S10 brief both reference the wrong filename. Link to backup-restore.md in the index.

## 2026-05-23 — E13_S03b — sandbox-wiring-is-pure-wiring-profiles-already-correct
`infra/latexml/sandbox.sb` and `infra/latexml/docker-compose.latexml.yml` are FULLY
AUTHORED and statically tested. E13_S03b is ONLY wiring: call sandbox-exec (macOS) or
bwrap (Linux) from `tools/arxiv_fetch.py::parse_with_latexml`. Use bubblewrap (bwrap)
for Linux — simpler than raw seccomp/landlock, no C extension dep, distro package.
Graceful degrade: log WARNING + continue with subprocess+timeout-only if neither available.

## 2026-05-23 — E13_S03b — dockerfile-server-wrong-target-for-latexml-docker-layer
`docker/Dockerfile.server` is the MCP server image. LaTeXML runs only during ingest.
Dockerfile hardening target would be `docker/Dockerfile.ingest` (DOES NOT EXIST).
Brief says "Updates to docker/Dockerfile.server" — this is wrong. Document Docker layer
as "applies when operator uses infra/latexml/docker-compose.latexml.yml." Do NOT create
Dockerfile.ingest as out-of-scope for E13_S03b.

## 2026-05-23 — E13_S03b — drift-check-secondary-latexml-site-missing-killpg
`ops/drift_check.py::render_fixture` uses subprocess.run WITHOUT start_new_session=True.
This is a second LaTeXML invocation site not covered by E13_S03's process-group fix.
E13_S03b should apply the sandbox wrapper here too (3-line change) for consistency.

## 2026-05-27 — embedder-truncation-m1 — chunker-version-bump-test-blast-radius
CHUNKER_VERSION bump v1.0→v1.1 requires updating ALL of these simultaneously (one
commit): (1) chunker_types.py constant, (2) all 10 tests/fixtures/chunker/*.expected.json
files, (3) tests/eval/fixtures/queries.json "chunker_version" field, (4) hardcoded
"v1.0" string assertions in test_chunker.py (~4 lines), (5) TestSingleVersionDefinition
in test_chunker_ids.py (scan for "v1.1" not "v1.0"). TestChunkerVersionFreeze SHA in
test_re_embed.py does NOT need re-pinning (only fires if _compute_chunk_id source changes).

## 2026-05-27 — embedder-truncation-m1 — eval-fixture-stub-vacuous-pass
tests/eval/fixtures/queries.json has "queries": [] — zero queries. Any AC that says
"nDCG@5 does not regress" is vacuously true. Record "eval fixture is stub; N/A" in
implementation summary. Do not skip the B-3 AC — just note it passes vacuously.

## 2026-05-27 — embedder-truncation-m1 — lancedb-dataset-count-2026-05-27
Two live LanceDB datasets as of 2026-05-27: notebooks/bridgeland-stability (6804 rows,
corpus-version 369) and notebooks/shimura-varieties (3625 rows, version 49). No
var/arxmcp/index/lancedb exists. demo-nb and csrf-victim notebook dirs exist but have
no lancedb/ subdirectory. Total re-embed scope: ~10,429 rows, ~137 papers.

## 2026-05-27 — embedder-truncation-m1 — re_embed-single-path-no-notebook-enumeration
`ingest/re_embed.py::run_re_embed()` takes ONE `active_lancedb_path` (default: main corpus).
It does NOT enumerate `var/arxmcp/notebooks/*/lancedb/`. Any milestone requiring
"re-embed all datasets" must add a driver loop or CLI flag; the function is not a wildcard tool.
Live dataset counts: bridgeland-stability 6804 rows (v369), shimura-varieties 3625 rows (v49).
Main corpus lancedb has no `chunks` table as of 2026-05-27.

## 2026-05-27 — embedder-truncation-m1 — chunk_id-hash-NOT-version-sensitive
chunk_id hex suffix = sha256(preamble_text + NFC(body_text))[:16]. The CHUNKER_VERSION string
lives on ChunkRecord.chunker_version field, NOT in the hash. Bumping CHUNKER_VERSION does NOT
change the chunk_id hex — only the metadata field. Tests for "version bump invalidates IDs"
should assert `chunk.chunker_version == "v1.1"`, NOT that hex suffixes differ.

## 2026-05-27 — embedder-truncation-m1 — bge-m3-pinned-sha-ships-bin-only-no-safetensors
BGE_M3_COMMIT_SHA = "5617a9f6..." ships `pytorch_model.bin` ONLY (confirmed via
~/.cache/huggingface/.no_exist/5617a9f.../model.safetensors). use_safetensors=True cannot
be enforced at this SHA. Tokenizer config shows model_max_length=8192; config.json shows
max_position_embeddings=8194. Full-attention XLM-RoBERTa — no sparse attention.

## 2026-05-27 — textbook-ingest-m2 — test-column-count-pins-exact-number
`tests/test_store.py::TestSchemaContract::test_column_count_matches_brief` asserts
`len(CHUNKS_SCHEMA_V1) == 14` verbatim. Adding 6 columns bumps to 20.
`test_column_names_in_brief_order` asserts exact ordered list. Both must be updated
lockstep with any CHUNKS_SCHEMA_V1 column addition.

## 2026-05-27 — textbook-ingest-m2 — lancedb-no-auto-null-fill-existing-rows
LanceDB 0.30.2 (pinned in uv.lock): existing rows on disk do NOT auto-gain new
nullable columns when schema gains new fields. Must call `tbl.add_columns(...)` for
the one-time migration when opening a table that lacks the new columns. Guard:
`if "source_kind" not in set(tbl.schema.names): tbl.add_columns(...)`.

## 2026-05-27 — textbook-ingest-m2 — parser_used-not-in-chunks-schema-today
`parser_used` is a field on `PaperOutcome` (bulk_ingest.py) and on the `papers`
metadata table design (05-storage-and-indexing.md), but does NOT currently exist
as a column in CHUNKS_SCHEMA_V1. Adding it in m2 is net-new, not a migration.
Current live values: "ar5iv" | "latexml" | None. m2 adds "mineru+latexml".

## 2026-05-27 — textbook-ingest-m3 — tool-schema-hash-does-not-include-output-json-schemas
`server/schemas/search_papers_result.json` and similar schema files are NOT
embedded in the `tools/list` hash. The hash only covers `ALL_TOOLS` entries
via FastMCP `model_dump`. Edits to output-schema JSON files alone do NOT drift
`EXPECTED_TOOL_SCHEMA_SHA256`. Must edit a `ToolMeta` description or handler
signature to drift the hash.

## 2026-05-27 — textbook-ingest-m3 — tool-schema-and-bp1-co-pin-confirmed-precedent
`853011e` (verification-feedback-m3) confirmed: both `EXPECTED_TOOL_SCHEMA_SHA256`
in `test_server_tool_schema.py` AND `EXPECTED_BP1_SHA256` in `test_prompts.py`
were re-pinned in the SAME commit. BP1 drifts whenever ALL_TOOLS changes. The
brief pattern "bundle into one commit" has working precedent.

## 2026-05-27 — textbook-ingest-m3 — notebooks-store-additive-migration-pattern
`server/notebooks_store.py::SCHEMA_VERSION` currently at 2. New columns require
`ALTER TABLE ... ADD COLUMN` in a `if current_version < N:` block — NOT
DROP-AND-RECREATE (that destroys user data). Each `if` block ends with
`PRAGMA user_version = N`. Notebook data is NOT a cache; loss-on-bump is wrong.

## 2026-05-27 — textbook-ingest-m4 — prefix-caps-cannot-be-kind-conditional
`RequestBodySizeLimitMiddleware.prefix_caps` is path-prefix-only; it has
no access to notebook_kind from the DB. When a milestone needs a cap
conditional on DB state (kind="textbook" → 200 MB, else 10 MB), the pattern
is: raise middleware cap to the higher value (200 MB), then enforce the lower
bound explicitly inside the route body after reading notebook_kind from the
store. Never add a new middleware class for this — the route already has the
notebook row from the 404 check.

## 2026-05-27 — textbook-ingest-m4 — pymupdf-not-in-deps-use-regex-page-count
PyMuPDF (fitz) is NOT a project dependency as of m4 entry. For PDF page-count
probing, use a pure-bytes `/Count\s+(\d+)` regex scan over the last 20% of
the PDF (xref/trailer region). Do not add PyMuPDF in m4; it lands with MinerU
in m5. False-negatives from the heuristic are acceptable (defense-in-depth).

## 2026-05-28 — textbook-ingest-m4 — upload-cap-not-notebook-kind-aware
RequestBodySizeLimitMiddleware prefix_caps cannot inspect notebook_kind (SQLite
read happens in handler, after middleware). For textbook-kind cap raise (10MB →
200MB), set middleware cap to 200MB for the /ui/api/notebooks subtree; the
handler enforces the 10MB arxiv-kind cap via 413 AFTER magic-byte sniff (fast
reject). Non-PDF uploads get 415 at 5 bytes — no DoS via large body buffering.

## 2026-05-28 — textbook-ingest-m4 — pdfid-compressed-stream-limitation
String-grep pdfid (re.findall over raw PDF bytes for /JS /JavaScript /OpenAction
/AA) misses keywords inside FlateDecode compressed object streams. This is a
documented, accepted limitation for m4's defense-in-depth role. PyMuPDF inside
MinerU (layer 2) sees the decompressed stream. Document in pdfid.py docstring.

## 2026-05-28 — textbook-ingest-m4 — tools-security-init-py-required
tools/security/__init__.py must be committed alongside pdfid.py. Missing __init__
causes ModuleNotFoundError on fresh checkout. Pattern applies to any new package
under tools/.

## 2026-05-27 — notebook-preamble-recovery-m1 — all-137-not-65-ar5iv-papers-missing-raw-tex
Milestone brief cited "~65 papers in the live notebook tree." Live measurement: `corpus/parsed/`
has 137 papers, `corpus/raw/` has 0 directories. ALL 137 are missing raw tex. `ingest-recover-preambles`
should target all of `corpus/parsed/`, not notebook-scoped papers only.

## 2026-05-27 — notebook-preamble-recovery-m1 — fetch_eprint-creates-raw-subdir-internally
`tools/arxiv_fetch.fetch_eprint(paper_id, raw_dir)` receives the PARENT dir and appends `paper_id`
internally: `raw_dir = raw_dir / paper_id; raw_dir.mkdir(parents=True, exist_ok=True)`. The returned
`FetchResult.raw_dir` IS the paper-scoped dir. Do NOT pre-create the directory before calling.

## 2026-05-27 — notebook-preamble-recovery-m1 — _notebook_common-has-no-CORPUS_RAW_DIR
`tools/_notebook_common.py` defines `CORPUS_PARSED_DIR`, `CORPUS_CHUNKS_DIR`, `CORPUS_EMBEDDINGS_DIR`
but NO `CORPUS_RAW_DIR`. Any milestone adding raw-tex fetch to the notebook path must add this constant
to `_notebook_common.py` and `__all__`, then monkeypatch it in tests.

## 2026-05-28 — notebook-preamble-recovery-m1 — fetch_eprint-caller-owns-sleep
`tools/arxiv_fetch.fetch_eprint` does NOT sleep internally. Its docstring states:
"Caller is responsible for the politeness sleep BEFORE invoking this." Per-paper cost
for notebook_fetch becomes ~6s (3s ar5iv + 3s e-print) when raw-tex fetch added.
Any new helper wrapping fetch_eprint must call politeness_sleep() explicitly.

## 2026-05-28 — notebook-preamble-recovery-m1 — notebook-tests-in-test-notebook-scripts
There is NO `tests/test_notebook_fetch.py`. All notebook_fetch tests live in
`tests/tools/test_notebook_scripts.py`. New tests for notebook_fetch changes go there.
The fixture pattern monkeypatches `notebook_fetch.try_cache` and `_notebook_common.CORPUS_*`.

## 2026-05-28 — notebook-preamble-recovery-m1 — _notebook_common-missing-CORPUS_RAW_DIR
`tools/_notebook_common.py` defines CORPUS_PARSED_DIR, CORPUS_CHUNKS_DIR, CORPUS_EMBEDDINGS_DIR
but NOT CORPUS_RAW_DIR. Any milestone adding a fetch_raw_tex_if_missing helper must add
CORPUS_RAW_DIR = REPO_ROOT / "var" / "arxmcp" / "corpus" / "raw" to _notebook_common.py
and update the test fixture's monkeypatch to redirect it.

## 2026-05-28 — textbook-ingest-m5 — macOS-RLIMIT_AS-cannot-be-lowered
On Darwin (macOS), `resource.setrlimit(RLIMIT_AS, (any_value, any_value))`
raises `ValueError: current limit exceeds maximum limit` — the hard limit is
RLIM_INFINITY and cannot be reduced from Python. The `hasattr(resource, "setrlimit")`
guard in the spike-2 doc is INSUFFICIENT (passes on macOS but child crashes).
Use `sys.platform == "linux"` guard ONLY. Document gap explicitly on macOS.

## 2026-05-28 — textbook-ingest-m5 — MinerU-3x-spawns-internal-FastAPI-server
MinerU 3.2.0 CLI is NOT a simple subprocess — it spawns an internal FastAPI/uvicorn
server (LocalAPIServer) in a new process group when invoked without `--api-url`.
The grandchild FastAPI server uses its own `start_new_session=True`, placing it in
a DIFFERENT process group than the outer CLI. `os.killpg` on the outer CLI's pgid
does NOT reap the grandchild server. Document as accepted gap; the server is
loopback-only and exits when idle.

## 2026-05-28 — textbook-ingest-m5 — MinerU-3x-output-tree-is-nested-not-flat
MinerU 3.2.0 pipeline backend output tree: `<output_dir>/<stem>/<parse_method>/<stem>.md`
NOT `<output_dir>/<stem>.md`. For `-b pipeline -m auto`: `<output_dir>/<stem>/auto/<stem>.md`.
Always glob for the .md file after process exits; never hardcode a flat path.

## 2026-05-28 — textbook-ingest-m6 — latexmlc-does-not-accept-markdown
Strategy A (wrap markdown as LaTeX -> latexmlc once) is NOT viable for MinerU output.
latexmlc is a LaTeX compiler; it does not understand `## Section`, `**bold**`, or
markdown links. Feeding it MinerU's .md file without a full markdown->LaTeX converter
would fail on every non-LaTeX construct. Strategy C (markdown-it-py prose + latexmlmath
per math block) is the correct path when the input is LaTeX-flavored markdown.

## 2026-05-28 — textbook-ingest-m6 — parse-status-column-default-must-be-skipped
NotebooksStore v3->v4 migration: `parse_status TEXT NOT NULL DEFAULT 'pending'` is WRONG
for the column-level default. Existing rows are ALL arxiv-kind; they should backfill to
'skipped', not 'pending'. Use `DEFAULT 'skipped'` at the column level; set 'pending'
explicitly in the create_notebook write path when notebook_kind='textbook'.

## 2026-05-28 — textbook-ingest-m6 — ingest-tracker-pattern-not-BackgroundTasks
FastAPI BackgroundTasks is request-scoped and unsuitable for 30-min MinerU runs.
The project's established pattern is asyncio.create_task + asyncio.Semaphore(1)
via IngestTaskTracker in server/ingest_tracker.py. Replicate this pattern for
parse tasks (ParseTaskTracker or extend IngestTaskTracker).

## 2026-05-28 — textbook-ingest-m6 — latexmlmath-bare-snippet-no-delimiters-needed
`latexmlmath \frac{a}{b}` works without `$...$` — bare snippet → display="block" MathML.
With `$...$` → display="inline". Output is a MathML fragment, NOT a full document.
~1s Perl startup per call makes per-equation strategy (B/C) infeasible for 500-page books.

## 2026-05-28 — textbook-ingest-m6 — mineru-content-list-has-no-equation-blocks
MinerU 3.2.0 content_list.json contains ONLY {text, page_footnote, page_number} block
types for text-heavy pages. Math is embedded as `$...$` strings within `type:"text"` 
blocks. Strategy B (per-block latexmlmath via content_list) is inoperable. Use Strategy A.

## 2026-05-28 — textbook-ingest-m6 — ingest-tracker-is-canonical-background-task-pattern
IngestTaskTracker (server/ingest_tracker.py) is the authoritative pattern for fire-and-
forget background tasks: asyncio.create_task + global Semaphore(1) + DB row before spawn
+ CancelledError handler in shutdown. Raw FastAPI BackgroundTasks has NO lifespan hook.

## 2026-05-28 — notebook-cutover-m1 — BM25-index-is-global-not-per-notebook
`BM25_INDEX_ROOT = var/arxmcp/index/bm25/` is GLOBAL. Keyed only by `corpus_version`
integer. Per-notebook BM25 DOES NOT EXIST as a separate namespace. After notebook
cutover to a new corpus_version, the cutover tool MUST call
`build_bm25_index(staging_lancedb_path, corpus_version=new_version)` BEFORE the
rename sequence. The server's auto-build in `BM25Phase.startup` only fires for the
shared corpus path at server startup — it will NOT build per-notebook BM25.

## 2026-05-28 — notebook-cutover-m1 — two-rename-window-is-not-atomic
The E11_S05 / notebook-cutover two-rename swap is NOT a single atomic operation.
Step 1: `os.rename(active, rollback)`. Step 2: `os.rename(staging, active)`.
Between them, `lancedb/` does not exist. A crash/SIGKILL in that window leaves the
server unable to start. Mitigation: print recovery instructions BEFORE swapping,
restore in OSError handler (as in ops/cutover.py:558-568).

## 2026-05-28 — notebook-cutover-m1 — per-notebook-lancedb-is-ingest-source-not-query-path
`server/routes/notebooks.py:273` sets `lancedb_path = str(nb_dir / "lancedb")` and
stores it as TEXT in SQLite (metadata only; NOT used for MCP query routing). The MCP
server's `Resources.startup` reads ONLY `config.lancedb_path` (the SHARED corpus at
`var/arxmcp/index/lancedb`). The per-notebook `<slug>/lancedb` is (a) the write target
for `tools/notebook_ingest.py` (initial ingest), and (b) the RE-EMBED SOURCE for
`re_embed_all.py`. Cutover promotes `lancedb-staging → lancedb` so the next re-embed
starts from the improved version. BM25 global path `var/arxmcp/index/bm25/v<N>/` keyed
by per-notebook corpus_version; cutover must call `build_bm25_index` post-swap.

## 2026-05-28 — notebook-retrieval-m1 — shared-corpus-is-empty-server-cannot-start
`var/arxmcp/index/lancedb/` is empty (64 bytes, no corpus-version.json). The server
cannot start with default config.lancedb_path. The notebook LanceDbs (bridgeland v369,
shimura v49) are the ONLY startable corpora today. Any notebook-retrieval design that
requires the server to be running against the shared corpus must first populate it.

## 2026-05-28 — notebook-retrieval-m1 — bm25-is-global-not-per-notebook
BM25_INDEX_ROOT is hardcoded: `var/arxmcp/index/bm25/`. The per-version dir `v<N>/`
is global regardless of which lancedb_path is passed to BM25Phase.startup(). For
notebook corpus_version=369, the artifact at `var/arxmcp/index/bm25/v369/` is
automatically used (already built). No per-notebook BM25 path change needed.

## 2026-05-28 — notebook-retrieval-m1 — filters-is-free-form-dict-no-schema-change
`handle_search_papers` filters arg: `dict[str, Any] | None`. Free-form dict. Adding
"notebook" to SUPPORTED_FILTER_KEYS is handler-body-only — zero tool schema change,
zero EXPECTED_TOOL_SCHEMA_SHA256 re-pin, zero BP1 invalidation. BUT: the Field
description string IS part of the schema hash. Do NOT change filters Field description
or SEARCH_PAPERS tool description in tools.py to avoid re-pin.

## 2026-05-28 — notebook-retrieval-m1 — filters-dict-is-free-form-no-schema-change
`server/handlers/search.py::handle_search_papers` types `filters` as
`dict[str, Any] | None`. FastMCP renders this as `{"type": "object"}` with no
named properties. Adding `notebook` as a recognized key requires NO `inputSchema`
change → no EXPECTED_TOOL_SCHEMA_SHA256 re-pin, no BP1 cache invalidation.
This is the proof for fork-A in notebook-retrieval-m1.

## 2026-05-28 — notebook-retrieval-m1 — cache-key-missing-slug-is-correctness-bug
`derive_tier1_key` in `server/cache_sqlite.py` keys on: query, filters_json, k,
corpus_version, level. NO notebook slug. Two notebooks with the same corpus_version
integer WILL collide in Tier-1. Bridgeland-stability=v369, shimura-varieties=v49.
Any new notebook reaching v369 or v49 silently gets wrong results from cache.
Fix: add notebook_slug as a length-prefixed component + bump SCHEMA_VERSION in
cache_sqlite.py (drops old entries on restart — acceptable cache-cold-start penalty).

## 2026-05-28 — notebook-retrieval-m1 — shared-corpus-empty-server-wont-start
`var/arxmcp/index/lancedb/corpus-version.json` does NOT exist. `Resources.startup`
raises `CorpusNotIngestedError` on absent corpus-version.json. The server cannot
start against the shared corpus today. AC4 ("no regression with shared corpus") is
aspirational, not current-state. Implementer must decide: notebook-only mode vs
deferred AC4.

## 2026-05-28 — notebook-retrieval-m1 — resources-singleton-not-multi-corpus
`server/resources.py::Resources` is a single-corpus dataclass (one chunks_table,
one bm25_phase, one ann_phase). Opening a per-notebook LanceDB requires a separate
dict[slug, NotebookResources] + asyncio.Lock lazy-init, NOT touching the global
Resources singleton. The BGE-M3 embedder module singleton IS shared (server/query_encoder.py).

## 2026-05-28 — textbook-ingest-m7 — _compute_chunk_id-hardcodes-arxiv-prefix
`ingest/chunker.py::_compute_chunk_id(paper_id, preamble_text, body_text)` returns
`f"arxiv:{paper_id}:{sha256(...)[:16]}"` — hardcoded `arxiv:` prefix. A textbook
chunker MUST NOT call this; implement `_compute_textbook_chunk_id(slug, ...)` returning
`f"textbook:{slug}:{sha256(...)[:16]}"` with identical NFC + UTF-8 discipline.

## 2026-05-28 — textbook-ingest-m7 — _resolve_preamble_doc-fails-for-textbook-paper-ids
`ingest/chunker.py::_resolve_preamble_doc(paper_id)` reads
`PREAMBLE_DIR/<paper_id>/preamble.json`. For `paper_id = "textbook:*"` the colon makes
an invalid filesystem path. Use `preamble_text = ""` (empty) in textbook chunker v0 and
add a `# TODO(m8): per-chapter preamble inheritance` comment. Do NOT call this helper.

## 2026-05-28 — textbook-ingest-m7 — ChunkRecord-already-has-all-m2-textbook-fields
All m2 textbook fields (`source_kind`, `license`, `chapter`, `page_start`, `page_end`,
`textbook_slug`, `parser_used`) are in `ingest/chunker_types.py::ChunkRecord` with
defaults (source_kind="arxiv", others=None). `to_dict()` serializes all 7. No gap.

## 2026-05-28 — textbook-ingest-m8 — pdf-path-has-no-preamble-macros-already-expanded
`ingest/textbook_renderer.py` writes a throwaway `main.tex` envelope with only
`\usepackage{amsmath,amssymb}` — no author macros. MinerU expands macros at PDF render
time. `preamble_text=""` and `preamble_ref=None` are the CORRECT PERMANENT values for
`mineru+latexml` chunks, not a TODO. Any future `.tex`-source textbook path would need
its own preamble extraction; do not build it on the PDF path.

## 2026-05-28 — textbook-ingest-m8 — proofnet-cross-reference-needs-no-schema-field
ChunkRecord already has `textbook_slug + chapter + theorem_name + theorem_label` —
enough to cross-reference any chunk to a ProofNet entry by (textbook, theorem-number).
Adding `proofnet_id` as a nullable column has zero data gain (PDFs carry no ProofNet IDs)
and requires schema migration + hash re-pin. Use a documented cross-reference contract,
not a new schema field.

## 2026-05-28 — textbook-ingest-m10 — upload-cap-carve-out-already-built-in-m4
The 200 MB textbook / 10 MB arxiv upload cap was fully implemented in textbook-ingest-m4
(complete). `server/main.py` prefix_caps = {"/ui/api/notebooks": 200MB}; handler checks
`_ARXIV_UPLOAD_MAX_BYTES` for arxiv notebooks. `tests/test_pdf_preflight.py::TestUploadCapPerKind`
and `TestMiddlewareEnvelope` cover all ACs. m10 is a doc-only pass on `.claude/docs/security-pdf-sandbox.md`.

## 2026-05-28 — textbook-ingest-m11 — no-get-chunk-result-schema-file
There is NO `server/schemas/get_chunk_result.json`. Only `search_papers_result.json`
and `lean_verify_result.json` exist. Both echo global `TOOL_SCHEMA_VERSION` in their
`version`/`$id` fields. Any TOOL_SCHEMA_VERSION bump must update both files.

## 2026-05-28 — textbook-ingest-m11 — get-chunk-does-not-read-license-column
`server/handlers/chunk.py` builds the chunk dict (lines 76-87) WITHOUT reading the
`license` column from the Arrow row. Any handler that needs `license` must explicitly
add `row.get("license") or ""` — no helpers exist yet.

## 2026-05-28 — textbook-ingest-m11 — m11-re-pin-scope-confirmed
m11 bumps TOOL_SCHEMA_VERSION 15→16 (result-shape change convention). Re-pins:
EXPECTED_TOOL_SCHEMA_SHA256 (yes), EXPECTED_BP1_SHA256 (NO — GET_CHUNK description
unchanged; BP1 = {name, description} only per test_prompts.py:464).

## 2026-05-28 — notebook-ops-hardening-m2 — fullfsync-is-connection-scoped-not-db-scoped
`PRAGMA fullfsync=ON` does NOT persist to disk. On macOS, a fresh sqlite3 connection to the
same file reads back fullfsync=0. Must be set on every connection in _open_sync. Regression
tests reading fullfsync MUST use the SAME connection (store._conn), not a separate sqlite3.connect().
`synchronous=FULL` (int 2) DOES persist. Confirmed on Darwin 25.4.0 / Python 3.12.

## 2026-05-28 — notebook-ops-hardening-m2 — lancedb-data_storage_version-deprecated-in-0.30
lancedb 0.30.x: `data_storage_version` kwarg on `create_table` is DEPRECATED. Default is "stable".
Modern pin: `lancedb.connect(path, storage_options={"new_table_data_storage_version": "stable"})`.
Current install (0.30.2) already defaults to stable + v2_manifest_paths. Pin explicitly to
survive future default changes.

## 2026-05-28 — corpus-integrity-observability-m2 — DegradedState-reason-enum-zero-out
`refresh_degraded_mode_metric` (server/health.py:638) hardcodes the known reason strings
("corpus_corruption", "hosted_embedder_outage") in its zero-out pass. Any new
`DegradedState.reason` value (e.g. "chunk_count_diverged") MUST be added to that
enumeration; otherwise the gauge for that reason never resets to 0 on startup.

## 2026-05-28 — corpus-integrity-observability-m2 — count_rows-must-use-run_in_executor
`chunks_table.count_rows()` is SYNCHRONOUS I/O in LanceDB. Any call inside an async
function (Resources.startup is async) MUST be wrapped in `await loop.run_in_executor(None,
chunks_table.count_rows)` — same pattern as the LanceDB open in resources.py:355.

## 2026-05-28 — notebook-ops-hardening-m2 — lancedb-data_storage_version-silently-dropped
In lancedb 0.30.2, `data_storage_version` kwarg to `db.create_table()` is SILENTLY DROPPED:
`LanceDBConnection.create_table` accepts it but never forwards it to `LanceTable.create`.
CORRECT approach: `storage_options={"new_table_data_storage_version": "stable"}`.
The deprecated path (LanceTable.create) would translate it, but it is never reached via db.create_table().

## 2026-05-29 — notebook-ops-hardening-m3 — compose-relative-path-depth-matters
`infra/docker-compose.yml` (1 level deep) uses `../var/arxmcp` for bind mounts.
`infra/observability/phoenix-compose.yml` (2 levels deep) uses `../../var/arxmcp`.
Compose v2 resolves paths against the COMPOSE FILE dir, not CWD. Always count
levels from the compose file location, not from the repo root.

## 2026-05-29 — notebook-ops-hardening-m3 — dockerfile-base-image-sha256-not-pinned
docker/Dockerfile.server has TWO `FROM python:3.11-slim` lines (builder + runtime),
NEITHER pinned with @sha256. The AC for m3 requires sha256 pins. The implementer
must `docker pull python:3.11-slim` to obtain the multi-arch manifest digest.
Use `docker buildx imagetools inspect python:3.11-slim` for the manifest digest.

## 2026-05-29 — notebook-ops-hardening-m3 — ARXMCP_CONTACT_EMAIL-not-in-Config
ARXMCP_CONTACT_EMAIL is NOT a Config field. Config uses `extra="forbid"` — setting
it as ARXMCP_CONTACT_EMAIL in a compose environment block would raise ValidationError
at startup. It is only needed by ingest tools, not the MCP server. Never set it
in the server compose environment.

## 2026-05-29 — notebook-ops-hardening-m4 — SecFetchSite-only-exempts-ui-prefix
`SecFetchSiteMiddleware` in `server/middleware.py` exempts ONLY paths matching
`/ui` or `/ui/*` from the `{none}` → `{none, same-origin}` relaxation. Any
htmx badge pointing `hx-get` at a non-`/ui` endpoint (e.g. `/status`) will get
403-rejected for `Sec-Fetch-Site: same-origin`. Always route badge endpoints
to `/ui/status-badge` (or any `/ui/*` path), not to bare API paths.

## 2026-05-29 — notebook-ops-hardening-m4 — htmx-does-not-render-JSON
htmx `hx-get` swaps the raw response body into the DOM as text. If the endpoint
returns `application/health+json`, the badge renders `{"status":"pass",...}` as
raw text — not a styled badge. Health+json endpoints need a companion
`/ui/status-badge` HTML-fragment route for htmx polling.

## 2026-05-29 — notebook-ops-hardening-m4 — health+json-spec-fields
IETF draft-inadarei-api-health-check: top-level `status` MUST be `pass|warn|fail`;
HTTP 2xx for pass/warn, 4xx-5xx for fail. `checks` keys are `{component}:{measurement}`.
`corpus_version`/`notebook_count`/`uptime` belong inside `checks` entries (not ad-hoc

## 2026-05-29 — notebook-surface-expansion-m3 — stale-no-frontend-phrase-lives-in-three-files
"The MCP tool surface is the UI" (stale no-frontend claim) lives in BOTH
`02-architecture-overview.md:150` AND `09-feature-priorities.md:151`, NOT just in
`06-mcp-server-design.md`. A doc-grep test must scan ALL `.claude/notes/*.md` + `CLAUDE.md`
for this phrase; a narrow scan (only the two brief-named files) passes vacuously.
top-level keys). Content-Type: `application/health+json`.

## 2026-05-29 — corpus-integrity-observability-m3 — lancedb-index-names-are-column-plus-idx
lancedb 0.30.2 auto-names indexes `<column_name>_idx` when no `name=` kwarg is passed to
`create_index`. `_create_indices` produces `"embedding_stmt_idx"` + `"embedding_proof_idx"`,
NOT `"hnsw_stmt"` / `"hnsw_proof"` as the docstring claims. Use `tbl.list_indices()` to
discover names — do NOT hardcode. `IndexStatistics.num_unindexed_rows` is the field to sum.
`list_indices()` returns ANN indexes only (scalar indexes excluded from the result).

## 2026-05-29 — notebook-surface-expansion-m4 — mcp-resources-sec-fetch-site-on-mcp-path
`SecFetchSiteMiddleware` exempts only `/ui` prefix (`exempt_prefixes=("/ui",)`).
`/mcp` is NOT exempt → only `Sec-Fetch-Site: none` passes through (CLI/shim, not browsers).
`resources/*` calls live on `/mcp` → same triple-layer protection as tool calls. No new
middleware needed for resources. Browser-originated cross-site XHR to resources → 403.

## 2026-05-29 — notebook-surface-expansion-m4 — lancedb-path-is-info-leak-in-resources-read
`NotebooksStore.list_notebooks()` returns `lancedb_path` = absolute on-disk path.
Exposing this to an agent via `resources/read` leaks host username + project structure.
Recommendation: omit `lancedb_path` from `resources/read` response or replace with
`is_ingested: bool`. This overrides the milestone brief's spec; flag to implementer.

## 2026-05-29 — notebook-surface-expansion-m5 — initialize-instructions-module-separation
MCP `initialize.instructions` constant MUST live in `server/mcp_instructions.py`, NOT
`server/prompts.py`. Reason: prompts.py has AST literal-only checks + BP1 coupling;
mixing instructions there risks accidental orchestrator wiring. Separate module +
separate `EXPECTED_INSTRUCTIONS_SHA256` pin in its own test file is the pattern.

## 2026-05-29 — notebook-surface-expansion-m5 — instructions-is-advisory-not-security
MCP spec 2025-06-18: `instructions?: string` — "MAY be added to the system prompt."
This is CLIENT-OPTIONAL orientation, not a security control. Cannot substitute for
server-side `<retrieved_*>` delimiters (Threat 2). But DO include a pointer to the
`<retrieved_*>` convention in the string — it primes agents before the first tool call.

## 2026-05-30 — verification-feedback-m4 — fastmcp-context-injection-via-functools-wraps
`_wrap_with_observability` uses `@functools.wraps(handler)`. Python 3.12 `inspect.signature`
follows `__wrapped__` by default, so FastMCP's `find_context_parameter` / `func_metadata(skip_names=...)`
correctly detects `ctx: Context` through the wrapper. Adding `ctx: Context | None = None` to a
handler AS THE LAST PARAM works without touching `register_all` or the wrapper. `TOOL_SCHEMA_VERSION`
and both SHA256 hashes are UNCHANGED (Context is in `skip_names`, never enters `inputSchema`).

## 2026-05-31 — notebook-paper-discovery-m1 — restic-backup-covers-whole-db-file
`ops/cron/arxmcp-backup.sh` ALREADY includes `var/arxmcp/cache/notebooks.db` as an explicit
backup path (line 94). Any additive column migration to `notebooks.db` is automatically
covered — no change to the backup script is needed unless a NEW file path is introduced.

## 2026-05-31 — notebook-paper-discovery-m2 — defusedxml-is-project-dep-use-for-external-xml
`defusedxml>=0.7` is already in `pyproject.toml` dependencies (added E10_S03 for MathML parsing).
Any NEW external-origin XML parser (e.g. arXiv Atom feeds) MUST use `defusedxml.ElementTree`,
not stdlib `xml.etree.ElementTree`. The curate_seed.py Atom parser uses stdlib — a known
inconsistency to fix when extracting to a shared library.

## 2026-05-31 — notebook-paper-discovery-m2 — arxiv-api-error-as-200-with-error-entry
arXiv API returns HTTP 200 for malformed queries, with a single entry whose `<id>` contains
`/api/errors#`. Parse-time detection: raise RuntimeError if any entry's id contains that
pattern. DO NOT rely on HTTP status codes for arXiv API error detection.
