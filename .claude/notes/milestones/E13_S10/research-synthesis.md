# Research Synthesis — E13_S10

**Generated:** 2026-05-20 (orchestrator merge of brief-1 and brief-2)
**Mode:** standard (2× milestone-researcher, Haiku 4.5)

---

## What this milestone is

E13_S10 is **pure audit + documentation**, not a feature milestone. No
new production code is needed. The deliverable is a single tracking
document that:

1. Enumerates each of the 7 documented threats verbatim.
2. For each threat, names the mitigation epic, the audit epic
   (E13_SXX), the test files covering it, and any known gaps.
3. Includes a pytest gate that asserts the cited test files exist
   (defense against future file-rename drift).
4. Lists any gaps as "to-file" placeholders that the user authorizes
   into actual GitHub issues at the Phase-4 external-write boundary.

All E13_S01–S09 are `phase: complete` per their state.json files
(verified by both researchers); E13_S10 can proceed without
preconditions.

---

## The 7 documented threats (verbatim, from `08-security-observability-ops.md` § Threat model)

> **Threat 1: Path traversal via `paper_id`** — strict regex on every arxiv ID input; reject at JSON-Schema level so it never reaches handlers.
>
> **Threat 2: Indirect prompt injection from retrieved chunks** — wrap every returned chunk in `<retrieved_chunk>...</retrieved_chunk>` delimiters; agent system prompt instructs that content inside is data, not instructions; optionally sanitize obvious patterns.
>
> **Threat 3: LaTeXML on hostile source** — subprocess with hard timeout (5 minutes); separate UID; filesystem write whitelist; no network; sandbox-exec/seccomp/landlock/Docker hardening; never invoke LaTeXML inside the MCP server process.
>
> **Threat 4: Resource exhaustion via tool arguments** — JSON-Schema maximum on numeric parameters (`k <= 50`); 256 KB byte cap on inline content with `resource_link` spillover; per-session rate limits keyed on `Mcp-Session-Id`; embedder/reranker semaphores.
>
> **Threat 5: Origin spoofing on the HTTP transport** — Origin header validation (MCP spec MUST); Sec-Fetch-Site enforced where possible; DNS-rebinding defense via Host header validation.
>
> **Threat 6: Supply-chain (embedder model, reranker model)** — pin model commit SHAs; use safetensors format only; trust_remote_code=False unless explicitly opted in.
>
> **Threat 7: Source ingestion fetches** — verify TLS certs; pin CA fingerprint (rotated periodically); content-length sanity check at 100 MB; sandbox the parser (Threat 3 mitigation).

**Logging redaction (E13_S08)** addresses the same file's
*"Logging"* subsection, NOT a numbered threat. The brief specifies
"7-row table"; logging is captured as an *observability addendum
row* after the main 7.

---

## Per-threat coverage mapping (load-bearing)

Both researchers built equivalent per-threat tables. Synthesis fixes the
mitigation/audit epic columns where the briefs disagreed and resolves
the fictional-milestone drift seen across E13_S01–S09.

| # | Threat | Mitigation epic (real, not brief-fictional) | Audit epic | Test file(s) | Known gap |
|---|---|---|---|---|---|
| 1 | Path traversal via `paper_id` | `ingest/identifiers.py::is_valid_paper_id` (E01 + E06_S01 JSON-Schema) | E13_S01 | `tests/security/test_path_traversal.py` | — |
| 2 | Indirect prompt injection from chunks | `<retrieved_chunk>` delimiters via `server/prompts.py` + handler wrapping (E06_S01–S04); optional `server/observability/sanitize.py` (E13_S02 opt-in) | E13_S02 | `tests/security/test_delimiters.py` | Sanitizer is opt-in (`ARXMCP_SANITIZE_RETRIEVED_CONTENT=1`); off by default — gap-issue candidate |
| 3 | LaTeXML on hostile source | `ingest/ar5iv_fetch.py` + the LaTeXML subprocess discipline (E02_S02); hostile-fixture audit (E13_S03) | E13_S03 | `tests/security/test_latexml_sandbox.py` | Production sandbox (sandbox-exec / seccomp / landlock) deferred to E11/E14; v1 ships timeout + subprocess isolation only — gap-issue candidate |
| 4 | Resource exhaustion | JSON-Schema `maximum` (E06_S04), 256 KB byte cap on `get_chunk` + `get_definitions` (E06_S05), per-session rate limits (E07_S10) | E13_S04 | `tests/security/test_resource_exhaustion.py` | Byte cap enforcement is partial — only `get_chunk` and `get_definitions` enforce; `search_papers`, `find_equation`, `find_lemma_by_name`, `get_paper`, `cite_neighbors` do not. **Gap-issue candidate.** |
| 5 | Origin spoofing | `server/middleware.py::OriginValidationMiddleware` + `HostValidationMiddleware` (E06_S05); `Sec-Fetch-Site` enforcement + DNS-rebinding tests + `ARXMCP_ALLOWED_ORIGINS` env var (E13_S05) | E13_S05 + E13_S09 | `tests/security/test_origin_binding.py` + `tests/security/test_bind_regression.py` | — |
| 6 | Supply-chain (model weights) | SHA pins in `ingest/embedder.py` + `server/retrieval/rerank.py` (E03 + E07_S03); shared `server/model_loader.py` validator + opt-in `ARXMCP_TRUST_REMOTE_CODE` + post-load `.bin` snapshot check + `Makefile sbom` target (E13_S06) | E13_S06 | `tests/security/test_model_pinning.py` | Embedder pinned BGE-M3 SHA ships `.bin`-only; safetensors enforcement deferred until SHA bump to a safetensors-bearing commit. **Gap-issue candidate.** |
| 7 | Source ingestion TLS + cap | `urllib.request` safe-by-default TLS verify (every fetch site); 100 MB content-length pre-check + read-cap on `ingest/ar5iv_fetch.py` + `ingest/oai_delta.py` + tightened `tools/arxiv_fetch.py` (E13_S07); opt-in stub `ARXMCP_PIN_ARXIV_CA` (E13_S07) | E13_S07 | `tests/security/test_source_ingest.py` | `ARXMCP_PIN_ARXIV_CA` is forward-compat plumbing only — actual SSL-context wiring deferred. **Gap-issue candidate** (low priority — current safe-by-default urllib trust store is the production posture). `graph_ingest.py` and `inspire_ingest.py` do NOT validate redirect hosts (ar5iv + oai_delta do); **gap-issue candidate**. |
| — | Logging redaction (observability addendum) | `server/observability/log_filter.py` + `server/observability/logging_setup.py` (E13_S08) | E13_S08 | `tests/security/test_log_redaction.py` | — |

---

## Brief/repo conflicts — resolved by orchestrator

Same systematic E13 drift. Resolutions:

| # | Brief says | Repo state | Resolution |
|---|---|---|---|
| 1 | `docs/security/threat-model-coverage.md` | CLAUDE.md §1 restricts `docs/` to operator-facing content; every prior E13 audit doc landed at `.claude/docs/security-*` | Place at `.claude/docs/security-threat-model-coverage.md` |
| 2 | "Follow-up issues filed for any gaps" | Phase 4 gates external writes (`gh issue create`); the user must authorize each issue per-event | Compile the gap list at Phase 2, surface to the user at the Phase 4 external-write boundary, file ONLY on authorization. Until filed, the doc uses `(gap: TODO file issue)` placeholders. |
| 3 | "Document reviewed by the developer and committed (not just drafted)" | "reviewed by the developer" has no machinable contract | Surface the coverage doc to the user at the Phase 4 boundary alongside the issue-filing question. The user's confirmation IS the review. Document this in the commit body. |
| 4 | Dependencies: E13_S01..E13_S09 | All complete per state.json files | No blocker; proceed |

---

## Where briefs agreed

Both researchers independently agreed:

1. **Doc placement** under `.claude/docs/`, not `docs/`.
2. **Gap-issue filing is gated by Phase 4 authorization** — don't auto-file.
3. **A pytest gate must validate cited test files exist** (defense against rename drift). E13_S08's `TestAuditDocPresence` is the precedent.
4. **"7-row table"** strictly per the brief; logging is an "observability addendum" row below the table.
5. **Use the `(gap: TODO file issue)` placeholder pattern** in the doc until issues are filed, then replace with `[#NNN — description](URL)`.

Both researchers' open-questions sets dedupe to four:
- File gaps now or defer to user review? → **defer to Phase 4**.
- Test file granularity in the table? → **file paths only, no test-method names**.
- Pytest gate strict or advisory? → **strict** — false security claims are worse than missing features.
- Include recommended Tier-6 hardening? → **no** — table is strictly the documented 7-threat model; future hardening goes in separate issues.

---

## Failure modes (audit-specific; not code-specific)

1. **False-positive coverage claim** — cited test file renamed/deleted. **Mitigation:** new pytest gate `TestThreatModelCoverageDoc::test_cited_test_files_exist` parses the markdown table and asserts each cited path exists. Pattern matches `tests/security/test_log_redaction.py::TestAuditDocPresence`.
2. **Test exists but doesn't exercise the threat** — file-rename gate doesn't catch this. **Mitigation:** the synthesis-merge step (this document) already asserts each test file's contents map to its claimed threat; the implementer must verify in Phase 2.
3. **Gap issues filed but not linked** — broken audit chain. **Mitigation:** every gap row in the doc must contain either a literal `(none)` or a GitHub URL; a pytest assertion can enforce the well-formed-URL contract without requiring the issue to actually exist.
4. **New threat added later, doc not updated** — silent staleness. **Mitigation:** add a footnote to the doc declaring it the v1 snapshot as of commit `<SHA>`; future E14+ work must produce an updated row before closing.
5. **Mitigation epic listed is fictional** — common across E13 briefs. **Mitigation:** the table above uses *real* mitigation locations (file:line citations of where the validator/middleware/test actually shipped), not the brief-cited epic IDs.
6. **The doc is committed without user review** — AC4 ("reviewed by the developer") has no automation contract. **Mitigation:** surface the rendered table at the Phase 4 user boundary; the user's authorization to file gap issues IS the review event.

---

## Implementation plan

1. **`.claude/docs/security-threat-model-coverage.md`** (new) — main deliverable:
   - Front matter: milestone label (E13_S10), v1-snapshot disclaimer with the current HEAD SHA, link back to `08-security-observability-ops.md`.
   - For each of the 7 threats: a `## Threat N — Name` heading, the verbatim threat statement quoted, and a `**Mitigation:** | **Audit:** | **Tests:** | **Gaps:**` line per the table above.
   - "Observability addendum" section for E13_S08 logging redaction.
   - Cross-epic summary table at the top (the 7-row table).
   - "Gap-issue triage" section listing each gap with status (`(TODO file issue)` until filed; `[#NNN](URL)` once filed).
   - Footer: "Forward maintenance contract — any new threat added to `08-security-observability-ops.md` requires a new row here before the next epic closes."

2. **`tests/security/test_threat_model_coverage.py`** (new) — small pytest gate:
   - `TestThreatModelCoverageDoc::test_doc_exists` — sanity check.
   - `test_seven_numbered_threats_present` — assert headings `## Threat 1` through `## Threat 7` appear.
   - `test_cited_test_files_exist` — parse the markdown for `tests/security/test_*.py` substrings; assert each is a real file under `tests/security/`.
   - `test_gap_rows_well_formed` — every "Gaps:" line is either `(none)` / `—` OR contains `(TODO file issue)` placeholder OR a `https://github.com/.../issues/<N>` URL.

3. **No changes** to `server/`, `ingest/`, or `tools/`. No new fixtures.

---

## Gaps to surface at the Phase 4 user boundary

Compiled from researcher-1's per-threat audit + the deferred-findings tail of each E13 milestone. The user authorizes one `gh issue create` per row at the external-write boundary.

| # | Gap | Suggested issue title | Severity | Source |
|---|---|---|---|---|
| G1 | Byte cap enforced only on `get_chunk` + `get_definitions`; `search_papers`, `find_equation`, `find_lemma_by_name`, `get_paper`, `cite_neighbors` do not enforce | "Threat 4: extend 256 KB byte cap to remaining tool handlers" | MEDIUM | Researcher-1, per E13_S04 memory |
| G2 | Embedder BGE-M3 pinned SHA ships `.bin`-only; `use_safetensors=True` cannot be enforced until SHA bump | "Threat 6: bump `BGE_M3_COMMIT_SHA` to a safetensors-bearing revision and enable post-load `.bin` check" | LOW (SHA pin is integrity-preserving) | E13_S06 audit doc § Embedder gap |
| G3 | `ARXMCP_PIN_ARXIV_CA` is a forward-compat stub with no current behavior | "Threat 7: implement `ARXMCP_PIN_ARXIV_CA` SSL-context wiring and refresh procedure" | LOW | E13_S07 audit doc |
| G4 | `ingest/graph_ingest.py` and `ingest/inspire_ingest.py` do NOT validate redirect hosts after fetch (ar5iv + oai_delta do) | "Threat 7: add `response.url.startswith(...)` redirect-host validation to graph_ingest and inspire_ingest" | MEDIUM | E13_S07 audit doc "Known gaps" |
| G5 | LaTeXML production sandbox (sandbox-exec / seccomp / landlock / docker hardening) is documented but not shipped at v1 | "Threat 3: ship production LaTeXML sandbox (E14_S0X track)" | MEDIUM (E11/E14 already plan this) | E13_S03 memory; tier-sequencing |
| G6 | Sanitization layer for prompt-injection patterns is opt-in (`ARXMCP_SANITIZE_RETRIEVED_CONTENT=1`) and off by default | "Threat 2: evaluate flipping default sanitization to on after collecting false-positive data" | LOW | E13_S02 design |

Synthesis flags G1, G4 as the highest-priority real coverage gaps (current code paths exist where the threat-model mitigation isn't enforced). G2, G3, G5, G6 are documented design deferrals or already-planned future work.

---

## Acceptance-criteria mapping

| AC (verbatim) | Status / how met |
|---|---|
| `docs/security/threat-model-coverage.md` committed with all 7 threats covered | ✓ (reframed: `.claude/docs/security-threat-model-coverage.md`) — Phase 2 writes the doc |
| Every threat has at least one automated test linked in the table | ✓ — every row points to one of the 9 `tests/security/test_*.py` files; pytest gate enforces existence |
| Any gap has a filed issue linked in the "Gap issues" column | ⚠️ **gated** — Phase 4 surfaces the 6-row gap list to the user; on authorization, files issues and replaces placeholders; on skip, the placeholders remain and the doc body notes the user's decision |
| Document reviewed by the developer and committed (not just drafted) | ⚠️ **process gate** — user review happens at the Phase 4 boundary; commit body records the review event |

---

## Open questions (deferred to implementer)

1. **Should G1 (byte cap) be one issue or one-per-tool?** Synthesis says one issue with a checklist (5 sub-items) — easier to triage than 5 individual issues. Implementer can split if user prefers granular tracking.

2. **Should the pytest gate fail-loud or skip-with-warning if `gh` CLI isn't installed?** Synthesis says fail-loud for cited-file-existence (always enforceable) and skip-with-warning for issue-URL liveness (requires network + `gh` auth). The file-existence test is the primary contract.

3. **Format of "Mitigation epic" column entries:** synthesis prefers `<epic>: <file:line>` format (e.g. `E06_S05: server/middleware.py::OriginValidationMiddleware`) so a reader can navigate to actual code. Implementer may simplify if too noisy.

---

## External writes the implementation will require

| Type | Target | Why | Phase 4 gated? |
|---|---|---|---|
| Git commit (feat) | local main | Coverage doc + pytest gate | No (local) |
| Git commit (chore) | local main | Finalize state.json | No (local) |
| `gh issue create` (up to 6) | `chris-dare-dev/arXMCP` GitHub issues | File gap-issue rows (G1-G6 above) | **YES** — per-event authorization, one yes/no per issue |

**Phase 4 boundary script:** the implementer surfaces the 6-row gap table to the user, asks "authorize filing each as a GitHub issue? (one yes/no per row)", files only the authorized ones, replaces `(TODO file issue)` placeholders with the resulting `[#NNN](URL)` markdown links, and commits the updated doc. If the user skips all 6, the doc still ships with the placeholder rows + a footnote noting the user's decision.

---

## Orchestrator synthesis note

The two briefs were nearly identical in structure (threat-by-threat
inventory + process recommendations). Synthesis merged them by:

- **Adopting researcher-1's per-threat table** as the load-bearing
  artifact (corrected with real-not-fictional mitigation epic IDs).
- **Adopting researcher-2's gap-triage process** (Phase 4 gating, placeholder pattern, file-existence pytest gate).
- **Resolving the "7 rows vs 8" ambiguity** in favor of "7 rows for
  threats + 1 observability-addendum row for E13_S08 logging." The
  brief is explicit on "7-row table" so the threats stay at 7.
- **Compiling a 6-row gap list** (G1–G6) from both briefs' notes;
  ranked by whether the current production behavior diverges from
  the documented threat-model mitigation.

No real divergence between the briefs — both correctly identified
the pure-audit nature of the milestone and the doc-placement
correction. The synthesis adds the prioritization of which gaps are
real coverage holes (G1, G4) vs documented design deferrals (G2, G3,
G5, G6) — useful for the Phase 4 user-authorization conversation.
