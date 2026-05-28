# Milestone Researcher — Project Memory

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
