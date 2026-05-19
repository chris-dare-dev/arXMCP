# Milestone Researcher — Project Memory

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
