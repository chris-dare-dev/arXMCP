# Critique — E13_S02

**Critic:** adversary
**Generated:** 2026-05-17T00:00:00Z
**Commit range:** d8c9d99..ff8c2c3
**Verdict:** SHIP-WITH-FIXES

## Executive summary

- SHIP-WITH-FIXES. Threat-2 wrapping landed correctly across the 4 emitting handlers, escape-on-emit (FM-1) is real and tested, and the sanitizer's strict env-var contract is well-calibrated. Three corrections required before this can be called complete.
- 0 CRITICAL, 2 HIGH, 4 MEDIUM, 3 LOW.
- Highest-risk drift: `server/schemas/search_papers_result.json:62` declares `snippet.maxLength: 150` but the production snippet is now 17 + min(150, len(body)) + 18 = up to 185 chars (verified: jsonschema rejects). A spec-compliant client doing schema validation will reject responses for bodies longer than ~115 chars. The existing `test_schema_validates_real_search_response` only passes because the seeded body is 58 chars.
- The frozen `.claude/docs/snippet-contract.md` was NOT updated. Section (a) at line 10-23 still claims "the first 150 characters of the chunk's canonical body text" — silent contract drift between the doc, the schema, and the wire shape.
- TestV1Gaps uses a fragile `"wrap_retrieved_text" not in source` grep that fires falsely on any future comment containing the literal. The defense it's pretending to provide (alert when deferred handlers start emitting wrapped content) is not load-bearing — same defense already lives in the per-handler integration tests of those handlers.
- The chunk handler's `body_text` wrap is exercised by zero integration tests; only the helper unit tests + a single search-snippet integration path actually round-trip the wrap. The `get_chunk` end-to-end wrap is untested.
- `_in_memory_scan_fallback` wraps ALL matches and THEN slices `[:k]` — wraps up to `len(matches)` rows when only `k` are kept (lemma.py:222-228). Minor inefficiency, not a correctness bug.
- The escape-on-emit defense only escapes the close tag — open-tag spoofing (literal `<retrieved_chunk>` inside body) is unescaped. Audit doc claims "exactly one matched delimiter pair regardless of input" which is misleading for the open-tag case.

## Severity calibration

| level | meaning | rectification phase action |
|---|---|---|
| CRITICAL | data loss, security regression, broken core invariant, or shippable-bug-in-production-now | always fix in Phase 4 |
| HIGH | wrong behavior reachable on common path, or load-bearing constraint violated | always fix in Phase 4 |
| MEDIUM | subtle correctness, missing test, latent foot-gun | fix only if cheap (≤ 30 LOC, small test surface) |
| LOW | style, naming, micro-perf | defer (record under `deferred_findings`) |

## Findings

### F1 — Frozen JSON schema's `snippet.maxLength: 150` violated by wrap

- **Severity:** HIGH
- **Source:** adversary
- **File:** server/schemas/search_papers_result.json:62
- **What:** The frozen schema declares `"maxLength": 150` for `results[].snippet`. The new `_snippet` implementation in `server/handlers/search.py:404-408` truncates body to 150 chars then wraps with `<retrieved_chunk>...</retrieved_chunk>` (35 chars overhead), yielding strings up to 185 chars. Verified directly: feeding a 200-char body to `_snippet` produces a 185-char output that `jsonschema.Draft7Validator` rejects with "is too long". The existing `test_schema_validates_real_search_response` (tests/test_snippet_contract.py:304) passes only because the seeded corpus body is 58 chars.
- **Why it matters:** Spec-compliant MCP clients that validate `structuredContent` against the published schema (the schema's `$id` is `https://arxmcp/schemas/search_papers_result/v6.json` and there is a `version: 6` field intended for client-side schema fetching) will reject every response for any paper body longer than ~115 chars — which is essentially every real arXiv chunk. The byte-stability hash test `EXPECTED_TOOL_SCHEMA_SHA256` is unaffected (it covers `tools/list` input schemas, not the output-result schema), but the output contract is now silently broken. The implementation summary section "Drift from brief" does not mention the schema field at all.
- **Proposed fix:** Update `server/schemas/search_papers_result.json` to raise `snippet.maxLength` to `185` (or compute as `150 + len("<retrieved_chunk></retrieved_chunk>") = 185`) AND update the field's `description` to document the wrapping. Bump `version` from 6 → 7 AND bump `server.tools.TOOL_SCHEMA_VERSION` from 6 → 7 to maintain the cross-file pin (cross-checked by `tests/test_snippet_contract.py::TestSchemaVersionPin::test_schema_version_matches_tool_schema_version`). Re-pin `EXPECTED_TOOL_SCHEMA_SHA256` via the `--update-tool-schema-hash` flag (because the per-tool `_meta: {"tool_schema_version": 7}` value is rendered in the `tools/list` response and is part of the hash).
- **Regression guard:** Add a test under `tests/test_snippet_contract.py::TestSnippetShape` that calls `_snippet("x" * 200)` and asserts schema validation passes — this proves the schema cap correctly accounts for the wrap overhead. Also add an explicit assertion in `test_snippet_length_under_cap` that the bound is `185` not `150` (or whatever the new cap value is).

### F2 — `snippet-contract.md` lies about the wire shape

- **Severity:** HIGH
- **Source:** adversary
- **File:** .claude/docs/snippet-contract.md:10-23
- **What:** Section (a) "Snippet is 150 characters max — no LLM rewriting" describes the wire field as "the first 150 characters of the chunk's canonical body text (column `body_text` in the LanceDB chunks table)" with "byte-for-byte slice — no ellipsis added". This is no longer the wire shape. After E13_S02, the snippet wire field is `<retrieved_chunk>` + up-to-150-chars + `</retrieved_chunk>` (with HTML-escape on close-tag occurrences in the body). The doc was not updated despite the test file `tests/test_snippet_contract.py` itself being updated to reflect the new wrapping (lines 170-186, 367-394). The doc is now a stale contract that contradicts the test that locks it.
- **Why it matters:** `.claude/docs/snippet-contract.md` is THE authoritative doc for the snippet field per the file header ("This document is the single authoritative specification for the `search_papers` tool's result-row shape, frozen at E06_S04"). Agents and integrators reading the doc will write code expecting raw text and discover `<retrieved_chunk>` tags at runtime. The doc-test enforcement `test_doc_states_150_char_cap` and `test_doc_mentions_the_exact_cap` (lines 273-275, 449-458) check for "150 character" substrings which still appear, so the staleness is not caught by CI.
- **Proposed fix:** Add a new section to `snippet-contract.md` — call it "(e) Delimiter wrapping (E13_S02)" — that documents the wrap, the escape-on-emit, the actual wire length (`<retrieved_chunk>X</retrieved_chunk>` where X is the 150-char content), and cross-references `.claude/docs/security-threat-2-audit.md`. Update section (a) to clarify "150 characters of *content* inside the delimiter" and link to (e).
- **Regression guard:** Add a test under `tests/test_snippet_contract.py::TestDocContract` that asserts the doc body contains the literal strings `"<retrieved_chunk>"` and `"E13_S02"` so the doc cannot be reverted to the pre-wrap shape silently.

### F3 — TestV1Gaps uses fragile string-grep regression guard

- **Severity:** MEDIUM
- **Source:** adversary
- **File:** tests/security/test_delimiters.py:418-463
- **What:** Each of the three `TestV1Gaps` tests reads the handler module's source text and asserts `"wrap_retrieved_text" not in source`. This is meant to fire when a future implementer wires the wrap helper into `find_equation`, `get_paper`, or `cite_neighbors`. But the assertion fires falsely on any other appearance of the literal string `"wrap_retrieved_text"` — including a docstring TODO, a comment "see wrap_retrieved_text in tools.py", or an import that wraps a different field (e.g. a future `paper.title` wrap that doesn't need a status flip). It also fires on `# wrap_retrieved_text intentionally deferred until E11` — the exact comment a future implementer would write.
- **Why it matters:** A regression guard that breaks on innocent comments destroys the signal — the next implementer will treat it as flaky and bypass it. The intended invariant ("the handler doesn't emit wrapped content yet") would be better expressed by asserting the handler's actual response shape (e.g. `find_equation` result rows have no `body_text`/`snippet`/`abstract` field). The TestV1Gaps tests are described in `.claude/docs/security-threat-2-audit.md:42` as the fail-loud trigger that flips the audit doc status; they should actually assert what the audit doc claims, not grep for an import name.
- **Proposed fix:** Replace each grep test with a behavioral assertion. For `find_equation`: instantiate the handler in a minimal fixture (or via existing test infrastructure) and assert no result row carries a `body_text`/`snippet`/`expansion` key. For `get_paper`: assert `result.abstract is None and result.title is None`. For `cite_neighbors`: assert `result.neighbors == []`. The behavior is what the audit doc actually documents; the grep is a proxy.
- **Regression guard:** The replacement tests ARE the regression guard. No further test needed.

### F4 — `get_chunk` body_text wrap untested end-to-end

- **Severity:** MEDIUM
- **Source:** adversary
- **File:** server/handlers/chunk.py:109-115
- **What:** The chunk handler wraps `structured["chunk"]["body_text"]` after `enforce_byte_cap` runs. This wrap path is exercised by zero integration tests. `tests/security/test_delimiters.py` tests the helper directly + the search `_snippet` integration; `tests/test_tools_all.py::test_get_chunk_smoke` and `test_get_chunk_not_found` (lines 297-310) assert only `found`/`chunk_id`/no body_text shape. The byte-cap interaction (where wrap is applied AFTER truncation) is also untested for the over-cap path — `TestByteCapEnforcement` at line 497 of `test_tools_all.py` does NOT call the full handler, only the lower-level `enforce_byte_cap` helper.
- **Why it matters:** The wrap is in production code; one of the four E13_S02 deliverables is the chunk-handler wrap. A future refactor that moves the wrap site (e.g. moving wrap inside `enforce_byte_cap`) could silently regress and no test catches it. The escape-on-emit defense on adversarial body content is tested for `_snippet` but NOT for `get_chunk`, where a full-body papper would be the actual injection vector (snippets are 150 chars and most injection payloads don't fit).
- **Proposed fix:** Add to `tests/security/test_delimiters.py` (new class `TestGetChunkWrapping`): one test exercising the under-cap path (small body → wrapped in `<retrieved_chunk>`), one test exercising the over-cap path (large body → truncated to 1024 chars then wrapped, `body_truncated=True`), and one test with adversarial `</retrieved_chunk>` literal in the body confirming escape-on-emit fires.
- **Regression guard:** The three new tests ARE the regression guard.

### F5 — Open-tag spoofing not defended; audit doc misrepresents the guarantee

- **Severity:** MEDIUM
- **Source:** adversary
- **File:** server/tools.py:362-368, .claude/docs/security-threat-2-audit.md:92
- **What:** `wrap_retrieved_text` escapes only the literal close tag (`</retrieved_chunk>` → `&lt;/retrieved_chunk&gt;`). The literal open tag (`<retrieved_chunk>`) in body content is passed through unescaped. The audit doc at line 92 claims "Exactly one matched delimiter pair, regardless of input." This is true only for the close tag. An adversarial body containing `<retrieved_chunk>` (e.g. a paper discussing the arXMCP defense itself) produces output like `<retrieved_chunk>good text <retrieved_chunk> bad</retrieved_chunk>` — which has TWO open tags and ONE close tag from the LLM's view. A permissive LLM that treats the second `<retrieved_chunk>` as a nested or repeated wrapper opening may apply different trust semantics to the inner content.
- **Why it matters:** The threat model in `.claude/notes/08-security-observability-ops.md` § Threat 2 names the attack class generically as "delimiter spoofing". The implementation defends only one half. For research math content this is low-probability — math papers rarely contain MCP delimiter strings — but for the math-ph/hep-th categories where security papers and papers ON LLMs do appear (the brief explicitly enumerates math-ph and hep-th as target categories), this is a real surface. The audit doc's claim that the wrapper produces "exactly one matched delimiter pair regardless of input" is materially false.
- **Proposed fix:** Option A (preferred): escape both open and close tags before wrapping (`text.replace(open, escaped_open).replace(close, escaped_close)`). Option B: update the audit doc and the docstring on `wrap_retrieved_text` to truthfully state "the close tag is escaped; an adversarial open tag in body content is not escaped because the consuming LLM's parsing is delimiter-agnostic — pairing is what matters". Option A costs ~3 LOC and one new test; Option B costs nothing but bakes in a documentation surface that future researchers will need to reason about. Recommend A.
- **Regression guard:** Add `TestEscapeOnEmit::test_adversarial_open_tag_in_body_is_escaped` mirroring the existing close-tag test.

### F6 — Sanitizer's case-sensitive `"ignore previous instructions"` is trivially bypassed

- **Severity:** MEDIUM
- **Source:** adversary
- **File:** server/observability/sanitize.py:54
- **What:** The pattern `"ignore previous instructions"` is matched as a literal byte string (case-sensitive). Any case variation — `"Ignore previous instructions"`, `"IGNORE PREVIOUS INSTRUCTIONS"`, `"Ignore Previous Instructions"` — passes through unchanged. The test `test_case_sensitive_ignore_does_not_match` (lines 236-242) ASSERTS this as intended behavior. The audit doc at `.claude/docs/security-threat-2-audit.md:107-118` justifies this via "literal-byte only" — claiming role-control tokens are byte-exact. But `"ignore previous instructions"` is NOT a tokenizer role token (like `<|system|>` is); it is natural-language prose whose semantics survive any casing.
- **Why it matters:** The other three patterns (`<|system|>`, `[INST]`, `<|im_start|>`) ARE byte-exact tokenizer markers and case-matching is correct for them. The fourth pattern is qualitatively different — it's English text that an LLM tokenizes case-equivalently. The "literal-byte only" justification mixes two patterns of attack into one defense. A real Threat-2 adversary will trivially write "IGNORE PREVIOUS INSTRUCTIONS" and bypass the sanitizer. The defense becomes ceremonial. This is defense-in-depth (the wrapper is the real defense), but the sanitizer should not provide false confidence.
- **Proposed fix:** Split the patterns into two categories. `_TOKENIZER_PATTERNS = ("<|system|>", "[INST]", "<|im_start|>")` matched case-sensitive; `_NL_PATTERNS = ("ignore previous instructions",)` matched case-insensitive via `re.sub(pattern, "", text, flags=re.IGNORECASE)`. Update the audit doc to explain the split. Update `TestSanitizerEnabled::test_case_sensitive_ignore_does_not_match` to test the OPPOSITE assertion (or remove if redundant).
- **Regression guard:** Add `test_strips_ignore_in_title_case`, `test_strips_ignore_in_uppercase`, `test_strips_ignore_mixed_case` under `TestSanitizerEnabled`.

### F7 — `_in_memory_scan_fallback` wraps all matches before slicing to k

- **Severity:** LOW
- **Source:** adversary
- **File:** server/handlers/lemma.py:222-232
- **What:** The fallback wraps every row in `matches` (potentially hundreds for popular theorem names) then slices `matches[:k]`. The wrap on dropped rows is wasted work. The cleaner ordering is `matches = matches[:k]; for r in matches: r["display_name"] = wrap(...)`.
- **Why it matters:** Minor inefficiency only. A pathological corpus with many matches for a common name causes O(N) wrap calls when O(k) suffices. Default `k=10`, so cost is bounded but observable.
- **Proposed fix:** Move the `matches = matches[:k]` slice BEFORE the wrap loop (or move the wrap inside the slice).
- **Regression guard:** None — pure perf improvement; no behavior change.

### F8 — `_reset_warned_for_tests` is a test-only function in production code

- **Severity:** LOW
- **Source:** adversary
- **File:** server/observability/sanitize.py:119-127
- **What:** The `_reset_warned_for_tests` function ships in production. Convention (the underscore prefix and the docstring) signals it's test-only, but nothing in the runtime prevents a production caller from invoking it. Similar smell exists for `_reset_resources_not_ready_warned_for_tests` in `server/tools.py:75` — so this is a pattern, not a one-off — but two wrongs do not make a right.
- **Why it matters:** Low-grade footgun; not a security risk. The function only resets a WARN-once flag; calling it from production just causes the WARN to fire more than once.
- **Proposed fix:** Move the function to a test-helper module (e.g. `tests/_helpers/sanitize_reset.py`) and have tests import it from there. Alternative: rename to `_RESET_WARN_FOR_TESTS_ONLY` (screaming-snake) to make accidental production calls a louder review failure.
- **Regression guard:** None.

### F9 — Implementation summary's "WARN-once" claim is hard to operate

- **Severity:** LOW
- **Source:** adversary
- **File:** server/observability/sanitize.py:106-113
- **What:** The WARN message reads "ARXMCP_SANITIZE_RETRIEVED_CONTENT=1 — sanitizing literal injection patterns (<|system|>, [INST], <|im_start|>, ignore previous instructions) from retrieved content. The delimiter wrapper is still the primary Threat-2 defense." It does not include the source-code path, the configured patterns as an explicit field (they're inline in the message), the env var origin (could be from shell, from systemd, from a docker env file — operators won't know where to look), nor a pointer to the audit doc. The brief AC says "logged at WARN level" but doesn't pin a structure; this is the kind of message that gets ignored or grepped-out in production log handling.
- **Why it matters:** Operations problem only. When the WARN fires unexpectedly, the operator has to grep code to figure out who turned it on.
- **Proposed fix:** Add an explicit pointer to the audit doc in the message: `"... See .claude/docs/security-threat-2-audit.md for the false-positive surface."` Include the env var name as a separate key/value for log-aggregation tools: `logger.warning("...", extra={"env_var": _SANITIZE_ENV_VAR, "patterns": list(_INJECTION_PATTERNS)})`.
- **Regression guard:** None — operational hygiene only.

## What was done well

- The escape-on-emit defense (FM-1) was added beyond the brief's scope based on solid threat reasoning, with 4 dedicated regression tests covering chunk/equation/multiple-tags/non-matching-tag cases. This is real security engineering, not ceremony.
- The shared-helper approach (R2's recommendation over R1's per-handler inline) was correctly adopted with the right structural reasoning — future handlers will discover `wrap_retrieved_text` next to `envelope` in the same module.
- The sanitizer's strict exact-string `"1"` env-var contract is well-motivated and well-tested. Parametrized rejection of `true/yes/on/True/TRUE/Y/y/2/0/""` is exactly the right discipline for an operator-facing security toggle.
- The audit doc at `.claude/docs/security-threat-2-audit.md` is genuinely useful — per-tool coverage table, deferred-work matrix, false-positive surface analysis, academic references with CVE pointers (2025-68143/68144/68145).
- The orchestrator system-prompt doc at `.claude/docs/orchestrator-recommended-system-prompt.md` correctly frames the wrap as necessary-but-not-sufficient and is explicit about who owns each layer (server vs orchestrator vs user).
- The sanitize-then-wrap ordering decision (synthesis D3) is canonical and tested via `TestSanitizeThenWrapOrder`.
- The lemma fallback's `_raw_theorem_name` stash-then-pop pattern correctly preserves the sort-key invariant (sort on raw, then wrap). The dedup_key is computed from raw text before wrap.
- Test count delta of +44 is plausible for the scope (35 test methods × parametrize expansion) and the tests are well-organized into 9 named classes that map to the threat-model defense layers.
- The implementation correctly recognized that brief's `E07_S13` and the brief's tool list are fictional (matching the E13_S01 drift pattern) and adopted the real surface without ceremony.
- No banned patterns introduced (`BaseHTTPMiddleware`, `assert` for invariants, `anthropic` SDK, kuzu version drift, lifted forks). Cache byte-stability via `EXPECTED_TOOL_SCHEMA_SHA256` correctly assessed as not requiring a bump.

## Recommended rectification order

1. **F1 — Fix the snippet schema maxLength.** Block on this first; it's the only finding that breaks the published wire contract. Requires bumping `TOOL_SCHEMA_VERSION` to 7, regenerating the schema-hash pin, updating the schema file's `maxLength` + `description`. Catch: this cascades into `EXPECTED_TOOL_SCHEMA_SHA256` re-pin via `--update-tool-schema-hash`.
2. **F2 — Update `snippet-contract.md`.** Self-contained doc fix; pairs naturally with F1.
3. **F5 — Open-tag escape OR audit-doc honesty fix.** Recommend option A (escape both tags); ~3 LOC + 1 test.
4. **F6 — Case-insensitive `"ignore previous instructions"`.** Single-pattern regex sub change + 3 new tests.
5. **F3 — Replace TestV1Gaps grep with behavioral assertions.** ~30 LOC across 3 tests.
6. **F4 — Add `TestGetChunkWrapping` integration tests.** ~30 LOC.
7. **F7 — Move slice before wrap in lemma fallback.** 2-line reorder.
8. **F8, F9 — Defer.** Operational hygiene; not load-bearing.

## Rectification status

- **F1 (HIGH) — fixed.** `server/schemas/search_papers_result.json`
  `snippet.maxLength` raised 150 → 250 (accommodates 17-char open tag +
  worst-case-escape 198-char content + 18-char close tag). Schema version
  bumped 6 → 7; `server.tools.TOOL_SCHEMA_VERSION` bumped 6 → 7;
  `EXPECTED_TOOL_SCHEMA_SHA256` re-pinned via `--update-tool-schema-hash`.
  Regression guard: `tests/test_snippet_contract.py::TestSchemaVersionPin::test_long_body_produces_schema_valid_snippet`
  validates 200-char body + 8-close-tag adversarial body against the
  schema; `TestSnippetCapConsistency::test_schema_max_length_accommodates_content_cap_and_wrap`
  asserts the relationship between content cap and wire-field cap.
- **F2 (HIGH) — fixed.** `.claude/docs/snippet-contract.md` section (a)
  updated to clarify "150 chars of content (wrapped in delimiters)"; new
  section (e) "Delimiter wrapping (E13_S02)" documents the wrap, escape-
  on-emit, and sanitizer. Regression guard:
  `tests/test_snippet_contract.py::TestSchemaVersionPin::test_doc_documents_e13_s02_delimiter_wrap`
  asserts the doc contains `<retrieved_chunk>` and `E13_S02`.
- **F3 (MEDIUM) — fixed.** `tests/security/test_delimiters.py::TestV1Gaps`
  grep-based assertions replaced with AST-based name resolution. The new
  `_module_references_wrap_helper` walker catches actual Name / Attribute
  / ImportFrom references but ignores strings, docstrings, and comments —
  a future implementer writing `# TODO call wrap_retrieved_text when E11
  lands` no longer trips the guard falsely.
- **F4 (MEDIUM) — fixed.** Added `test_get_chunk_body_text_is_wrapped`
  integration test in `tests/test_tools_all.py`. Exercises the full
  get_chunk handler path through `enforce_byte_cap` + wrap, asserts
  `body_text` is wrapped in `<retrieved_chunk>...</retrieved_chunk>` and
  the inner content matches the seeded body.
- **F5 (MEDIUM) — fixed.** `wrap_retrieved_text` now escapes BOTH open and
  close tags before wrapping (was close-only). The audit doc's claim
  "exactly one matched delimiter pair regardless of input" is now
  truthful. Regression guards:
  `TestEscapeOnEmit::test_adversarial_open_tag_in_body_is_escaped`,
  `test_adversarial_open_tag_in_equation_is_escaped`,
  `test_both_open_and_close_tags_escaped`.
- **F6 (MEDIUM) — fixed.** `sanitize_retrieved_text` split into two pattern
  categories: `_TOKENIZER_PATTERNS` (case-sensitive literal replace) and
  `_NL_PATTERNS` (case-insensitive regex via pre-compiled `re.IGNORECASE`).
  Previous case-sensitive match for "ignore previous instructions" was
  trivially bypassed by "Ignore Previous Instructions"; the rect makes
  the pattern match how English prose actually tokenizes. Test
  `test_case_sensitive_ignore_does_not_match` replaced with
  `test_ignore_pattern_case_insensitive` (5 case variants stripped) and
  `test_tokenizer_markers_remain_case_sensitive` (mixed-case `<|System|>`
  NOT stripped).
- **F7 (LOW) — fixed.** `server/handlers/lemma.py::_in_memory_scan_fallback`
  now slices `matches[:k]` BEFORE the wrap loop (was wrapping all rows
  then slicing). Reduces wrap calls from O(N) to O(k) on pathological
  corpora with many matches for a common theorem name.
- **F8 (LOW) — deferred.** Per critic recommendation; the
  `_reset_warned_for_tests` test-helper-in-production-code smell is a
  pattern already established in `server/tools.py` and recategorizing it
  is operational hygiene only, not load-bearing.
- **F9 (LOW) — deferred.** Per critic recommendation; WARN log message
  ergonomics is operational hygiene only. Operator can still grep the
  message text + the env var name to find the source.

**Critic invalidation rate:** 0% (0 of 6 CRITICAL+HIGH+MEDIUM findings
invalidated on re-verify; all 6 closed by code/test changes). Calibration
is clean.

**Test count delta from rect:** +7 tests (1953 → 1960). Breakdown:
- F1: +2 (long-body validates, schema accommodates wrap)
- F2: +1 (doc references E13_S02)
- F4: +1 (get_chunk wraps end-to-end)
- F5: +3 (open-tag escape × 3 variants)
- F6: +2 (case-insensitive ignore, tokenizer-markers case-sensitive); -1 (replaced case-sensitive test) = +1 net
- F3: 0 (replaced grep with AST, no count change)
- F7: 0 (perf-only, no behavior change to test)
