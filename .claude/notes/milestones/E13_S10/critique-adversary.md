# Critique — E13_S10

**Critic:** adversary
**Generated:** 2026-05-20 (UTC)
**Commit range:** `dc96387ab11f9d2325ce8fb42499faf794953f36..13f465c9a0bda044ecfe8e628080042ffbc5ef21`
**Verdict:** SHIP-WITH-FIXES

## Executive summary

- **Verdict + reason:** SHIP-WITH-FIXES. The coverage audit doc is substantively sound and the 21-test staleness gate is well-designed. One MEDIUM finding: Threat 2's mitigation-epic citation conflates the **delimiter wrapping** (real, E06 + E13_S02) with the **system-prompt instruction** (orchestrator responsibility, outside MCP scope), creating ambiguity about which component is v1-audited. One LOW finding: the gap-list is complete and accurate, but the doc doesn't explicitly clarify the scope boundary between MCP server and orchestrator for Threat 2's system-prompt requirement.
- **Finding counts:** 1 MEDIUM, 1 LOW, 0 HIGH, 0 CRITICAL. Total 2 findings.
- **Highest-risk file:line:** `.claude/docs/security-threat-model-coverage.md:82–84` (Threat 2 mitigation epic citation ambiguity).
- **Cross-axis patterns:** No multi-axis issues. The doc and test are tightly scoped to documentation audit, which limits blast radius. All 9 cited security test files exist and are real. Forward-maintenance contract is enforceable via the threat-count parity test.

## Severity calibration

| level | meaning | rectification phase action |
|---|---|---|
| CRITICAL | data loss, security regression, broken core invariant, or shippable-bug-in-production-now | always fix in Phase 4 |
| HIGH | wrong behavior reachable on common path, or load-bearing constraint violated | always fix in Phase 4 |
| MEDIUM | subtle correctness, missing test, latent foot-gun | fix only if cheap (≤ 30 LOC, small test surface) |
| LOW | style, naming, micro-perf | defer (record under `deferred_findings`) |

## Findings

### F1 — Threat 2 mitigation-epic citation conflates server delimiter wrapping with orchestrator system-prompt instruction

- **Severity:** MEDIUM
- **Source:** adversary
- **File:** `.claude/docs/security-threat-model-coverage.md:82–84`
- **What:** The doc cites "E06 (delimiter wrapping in `server/prompts.py` + handler implementations)" as the mitigation epic for Threat 2. However, the threat-model file (`.claude/notes/08-security-observability-ops.md:26`) explicitly states "The agent's system prompt **(provided by the orchestrator, not the MCP server)** must instruct...". The reference to `server/prompts.py` is misleading because the `SYSTEM_PROMPT` constant in that file is a placeholder (per CLAUDE.md §8 gotcha #6: "SYSTEM_PROMPT in server/prompts.py is still a placeholder. The role prefixes are real; the global system prompt isn't yet authored."). The citation obscures which part of Threat 2's mitigation is actually v1-audited vs. deferred to the orchestrator.
- **Why it matters:** The coverage audit's value is traceability from threat → mitigation → test. A reader seeing "server/prompts.py" might assume the MCP server is responsible for the system-prompt instruction, when actually that responsibility belongs to the consuming orchestrator. This creates confusion about the v1 MCP server's threat-model scope and could mislead a future developer who modifies `server/prompts.py` without realizing the system-prompt instruction is an orchestrator concern.
- **Proposed fix:** In `.claude/docs/security-threat-model-coverage.md`, lines 82–84, revise the "Mitigation epic" cell for Threat 2 from `E06 (delimiter wrapping in server/prompts.py + handler implementations)` to `E06 (delimiter wrapping in handler implementations)` OR add a clarifying note like: `E06 + E13_S02 (delimiter wrapping in handlers; system-prompt instruction is an orchestrator responsibility, not MCP server scope)`. The key change is removing the `server/prompts.py` reference or clarifying it refers only to any role-prefix constants, not the global SYSTEM_PROMPT.
- **Regression guard:** Add a pytest assertion to `tests/security/test_threat_model_coverage.py::TestThreatStructure` that the Threat 2 section does NOT cite `SYSTEM_PROMPT` as a v1 MCP server responsibility, OR add a comment in the Threat 2 section stating "Note: The system-prompt instruction is an orchestrator responsibility (provided outside the MCP server); the MCP server's role in Threat 2 mitigation is delimiter wrapping only." Either approach clarifies the scope boundary.

### F2 — Gap-list omits orchestrator system-prompt instruction as a documented future dependency

- **Severity:** LOW
- **Source:** adversary
- **File:** `.claude/docs/security-threat-model-coverage.md:290–309` (Gap-issue triage section)
- **What:** The gap-list (G1–G6) is accurate and well-prioritized. However, it does not list the orchestrator's system-prompt instruction (Threat 2, mitigation #2 from the threat-model) as a gap. The gap-list surface includes "production sandbox deferred to E11/E14" (G3, documented design deferral) and "sanitizer is opt-in" (G6, design trade-off). By the same logic, the orchestrator's system-prompt instruction could be listed as a gap, with status "Out of scope for v1 MCP server; deferred to orchestrator implementation."
- **Why it matters:** The doc explicitly states its goal is to "confirm every documented mitigation is implemented and covered by an automated test." For Threat 2, three mitigations are documented. Two (delimiter wrapping + sanitizer) are listed in the summary table and gap-list. The third (system-prompt instruction) is mentioned in the threat-model but not traced through in the coverage doc. A reader checking "are all Threat 2 mitigations covered?" might miss this gap. The gap-list should be comprehensive, even if some gaps are marked "out of scope for v1 MCP server."
- **Proposed fix:** Add a row to the gap-issue triage table (lines 290–309) documenting the orchestrator system-prompt instruction: `G7 | Orchestrator system-prompt instruction for <retrieved_chunk> boundary (Threat 2 mitigation #2) | LOW | Out of scope for v1 MCP server (orchestrator responsibility). Tracked for completeness; no action needed in arXMCP v1. | `. Alternatively, add a footnote after the table: "Note: Threat 2's system-prompt instruction mitigation is provided by the consuming orchestrator, not the MCP server, and is therefore not in scope for this v1 audit. See `.claude/notes/08-security-observability-ops.md:26` for the threat-model's explicit boundary statement."
- **Regression guard:** A prose note at the end of the "Gap-issue triage" section stating "Scope: this table lists gaps in the v1 MCP server audit only. Orchestrator-side mitigations (system prompts, input sanitization at the orchestrator boundary) are documented in the threat-model but deferred to orchestrator implementation." This clarifies to future readers that the gap-list is not incomplete, just scoped to MCP server only.

## What was done well

- **Sound structural design:** The pytest gate (`test_threat_model_coverage.py`) is lightweight and correct in scope. It enforces file-existence (catching renames/deletes) and forward-maintenance (threat count parity), which are the two high-leverage staleness risks. The gate does not attempt to verify that each test file's implementation actually exercises the claimed threat — correctly deferring that code-review responsibility to human review.
- **Comprehensive threat mapping:** All 7 documented threats are present in the coverage doc with clear verbatim quotes from the threat-model source. The cross-references back to `.claude/notes/08-security-observability-ops.md` are consistent and traceable.
- **Real-file citations, not fictional epics:** The implementation fixed the common E13 drift where briefs cite fictional milestone IDs (e.g., "E07_S12" when E07 only has S01–S04). The coverage doc uses real file:line citations (`ingest/identifiers.py::is_valid_paper_id`, `server/middleware.py::OriginValidationMiddleware`) and real, completed audit epic IDs. This makes the doc a true audit trail, not a narrative.
- **Gap-list prioritization and honesty:** The 6-gap candidates (G1–G6) are correctly segregated into "real coverage gaps" (byte-cap on 5 tools, redirect-host validation) vs. "documented design deferrals" (LaTeXML production sandbox, BGE-M3 SHA bump pending, CA-pinning stub). The classification is accurate and helps a reader distinguish "we found a bug" from "we deferred this to a future milestone."
- **Observability addendum clarity:** E13_S08 (logging redaction) is correctly captured as a separate row below the 7 threats since it addresses the "Logging" subsection of the threat-model, not a numbered threat. The brief said "7-row table" and the implementation honored that scope while still auditing the logging subsection.
- **Forward-maintenance contract enforcement:** The pytest gate `test_threat_model_source_threat_count_matches` reads the threat-model file and asserts threat-count parity with `EXPECTED_THREAT_NUMBERS`. This is elegant enforcement of "if Threat 8 is added to the source, the coverage doc and test constant must update together." The gate is strict (fails the test) not advisory, which is correct for security audit contracts.
- **Inverse cite test prevents orphan test files:** `test_every_security_test_file_is_cited` asserts that every real `tests/security/test_*.py` file is mentioned in the coverage doc. This prevents the common drift where a new test is added but the audit doc isn't updated. The allow-list for `test_threat_model_coverage.py` itself is correct (documenting the doc, meta-recursive).
- **Doc placement respected CLAUDE.md §1:** Brief specified `docs/security/threat-model-coverage.md`. Implementer correctly placed at `.claude/docs/security-threat-model-coverage.md` per the established precedent (E13_S01–S07 all live under `.claude/docs/`). This avoids mixing agent-internal audit docs with operator-facing content.
- **Phase-4 external-write boundary honored:** Gap-issue filing is correctly deferred to Phase 4 with per-event user authorization. The doc uses `(TODO file issue: ...)` placeholders that will become `[#NNN](URL)` links when the user approves each issue. No gap issues are auto-filed; the user controls the scope.
- **Well-formed gap-row regex is appropriately loose:** The regex for gap-row well-formedness (`\(none\)|—|\(TODO file issue|https://github\.com/.../issues/\d+`) is forgiving on purpose. It allows future developers to use slightly different placeholders (e.g., `(TBD)`) without updating the test, so long as the gap state remains machine-readable.

## Recommended rectification order

1. **F2 (LOW):** Add a clarifying note or gap-list row documenting that the orchestrator system-prompt instruction is out of scope for v1 MCP server audit. This is cheap (< 10 lines) and improves the doc's completeness for readers.
2. **F1 (MEDIUM):** Revise the Threat 2 mitigation-epic citation to either remove the `server/prompts.py` reference or clarify it applies only to delimiter wrapping, not the system-prompt instruction. This is also cheap (1–2 line edit) and removes ambiguity about scope responsibility.

Both fixes are trivial and improve clarity without changing any security posture.

## Rectification status (filled by Phase 4)

<!-- Phase 4 appends one bullet per finding; do not pre-populate -->
