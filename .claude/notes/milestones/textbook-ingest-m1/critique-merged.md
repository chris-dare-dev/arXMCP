# Critique — textbook-ingest-m1

**Critic:** adversary
**Generated:** 2026-05-27T00:00:00Z
**Commit range:** `461d2a7..f187af4`
**Verdict:** SHIP-WITH-FIXES

## Executive summary

- Verdict SHIP-WITH-FIXES: the canonical regex widening is correct, robust against every Threat-1 fixture probed (slash, dot-dot, null, whitespace, CR/LF, control chars, URL-encoded, unicode overrides, bare prefix), and the F3 `$`→`\Z` fix on `CHUNK_ID_RE` is a legitimate defense-in-depth win. BUT the implementer widened `is_valid_paper_id` without auditing the seven downstream sites where the validated paper_id flows into filesystem path construction, SQL `WHERE` clauses, and HTML render templates — admitting a `textbook:<slug>` paper_id at sites whose schema/writer support won't ship until m2.
- Finding counts: 0 CRITICAL, 2 HIGH, 3 MEDIUM, 2 LOW.
- Highest-risk site: `server/routes/notebooks.py:619` — `paper_id.replace("/", "_")` was designed for the arXiv character set and does NOT sanitize the colon admitted by the new `textbook:<slug>` shape; the validated paper_id flows into an on-disk filename `f"{flat_paper_id}.html"`.
- Cross-axis pattern: the brief said "identifiers only", but the regex `is_valid_paper_id` is the upstream security gate for ≥9 filesystem-construction and SQL-style callsites (`server/handlers/paper.py:65`, `server/routes/notebooks.py:152/458/554`, `server/handlers/lemma.py:94`, `server/handlers/definitions.py:89`, `ingest/extract_equations.py:369`, `ingest/oai_delta.py:467`, `ingest/bulk_ingest.py:270`). Widening the gate widens the input contract everywhere; the implementer treated this as a local-file edit.
- 17 path-traversal regression tests vs the brief's ≥5 — strong coverage on the regex, but only one of the prompt's explicit non-`\n` whitespace forms (internal space) is tested; trailing-space, leading-whitespace, `\r`, `\t`, bare-prefix `textbook`, `textbook:.`, `textbook:..`, and URL-encoded `textbook:%2e%2e%2f` are all REJECTED by the regex but not explicitly under test.
- Tier-sequencing: `ingest/schema.py`, `ingest/store.py`, `server/tools.py`, `server/prompts.py`, `tests/test_server_tool_schema.py`, and `tests/test_prompts.py` are all UNTOUCHED — m2 and m3 scope is correctly preserved.
- Cache byte-stability: clean. Tool-list hash and BP1 hash both still pinned and passing. `server/schemas/search_papers_result.json` is a result envelope schema, not a tool-list contributor.
- Deviation #5 (schema update) was forced by the existing `test_schema_chunk_id_pattern_matches_canonical` byte-equality lock; this is a defensible scope expansion. The schema pattern uses ECMA-262-valid `(?:v\d+)?` non-capturing groups; confirmed parseable + behavior-equivalent in Python.

## Severity calibration

| level | meaning | rectification phase action |
|---|---|---|
| CRITICAL | data loss, security regression, broken core invariant, or shippable-bug-in-production-now | always fix in Phase 4 |
| HIGH | wrong behavior reachable on common path, or load-bearing constraint violated | always fix in Phase 4 |
| MEDIUM | subtle correctness, missing test, latent foot-gun | fix only if cheap (≤ 30 LOC, small test surface) |
| LOW | style, naming, micro-perf | defer (record under `deferred_findings`) |

## Cross-critic agreement

_None — no file:line region was flagged by ≥ 2 critics._

<!-- end:cross-critic-agreement -->

## Findings

### F1 — Upload sanitizer admits textbook paper_id colon onto filesystem

- **Severity:** HIGH
- **Source:** adversary
- **File:** `server/routes/notebooks.py:619`
- **What:** `flat_paper_id = paper_id.replace("/", "_")` was designed around the arXiv ID character class ("no shell metachars" per the inline comment at line 617). After m1, `is_valid_paper_id("textbook:foo")` returns True, so a client can POST `paper_id=textbook:foo` via the multipart `Form(...)` field. The sanitizer leaves the colon untouched; `f"{flat_paper_id}.html"` produces `textbook:foo.html`. On macOS HFS+/APFS the colon is path-separator-translated by some POSIX file APIs (carriage of the legacy HFS path delimiter), so the resulting filename can render in Finder as `textbook/foo.html` — a confusion vector that bypasses the m6-FM-5 atomic-write invariant (the `os.replace(tmp_path, target_path)` at line 627 sees a different path than the user expects). On Linux the colon is a literal byte; on Windows the filename is rejected entirely.
- **Why it matters:** The m1 brief asserts "identifiers only — no schema or writer changes (deferred to m2)." That contract is violated at this site: by admitting `textbook:<slug>` at the upload gate without expanding the sanitizer, the milestone introduces a new on-disk filename shape that no downstream code expects. The brief's m2-deferral comment about "no chunks schema or LanceDB writer" did not contemplate that the regex itself is the gate for non-schema filesystem writes too.
- **Proposed fix:** Constrain `is_valid_paper_id` to its pre-m1 arXiv-only behavior at the upload + URL-add gates by reading `paper_id.startswith("textbook:")` and rejecting at the route handler (line 458 + line 554 + line 152), OR widen the sanitizer to `paper_id.replace("/", "_").replace(":", "_")` and add a test that POSTs `paper_id=textbook:foo` to `/ui/api/notebooks/{slug}/papers/upload` expecting either a 422 or a sanitized-colon target_path.
- **Regression guard:** New test in `tests/test_routes_notebooks_upload.py` (or `tests/test_routes_notebooks.py`) that POSTs a textbook-shaped paper_id and asserts either 422 OR that the on-disk filename does not contain a literal colon.

### F2 — Filesystem-path sites admit textbook paper_id with no schema/writer ready

- **Severity:** HIGH
- **Source:** adversary
- **File:** `ingest/extract_equations.py:374` (callsite `_parsed_html_path(paper_id)` at line 322)
- **What:** `_parsed_html_path("textbook:foo")` returns `PARSED_DIR / "textbook:foo" / "index.html"`. The `is_valid_paper_id` gate at line 369 now PASSES for textbook paper_ids. There is no LaTeXML-parsed HTML directory under `var/arxmcp/corpus/parsed/textbook:foo/` because m2 (schema) and m3 (BP1 re-pin) haven't shipped. The function exits cleanly (line 376: `logger.warning(...)`, returns 0), but the broader contract — "this function validates ONLY arXiv paper_ids before touching the LanceDB equations table" — is silently relaxed. Similar at `server/handlers/paper.py:65/77` where the validated paper_id flows into a SQL-style WHERE on the `chunks` table (which has no textbook rows yet, so returns empty); at `server/handlers/lemma.py:94`; at `server/handlers/definitions.py:89`; at `ingest/oai_delta.py:467`; at `ingest/bulk_ingest.py:270`.
- **Why it matters:** The implementer's deviation table claims deviations 1–5 but does NOT acknowledge that widening `is_valid_paper_id` is a contract change at every gate that calls it. Even though no security violation lands today (the SQL escape is defensive, the LanceDB returns empty, the directory doesn't exist), the regex is now AHEAD of the rest of the system — m2's writer support and source_kind discriminator are absent. A future bug at any of these sites that assumes "if `is_valid_paper_id` passed, this is an arXiv ID" is now wrong.
- **Proposed fix:** EITHER (a) add a new helper `is_valid_arxiv_paper_id` that retains the pre-m1 two-alternative regex, and use IT at every site that constructs filesystem paths / SQL filters, leaving `is_valid_paper_id` as the broadened gate for textbook-aware sites once m2 ships; OR (b) keep the widened `is_valid_paper_id` but add an early-return / 422 at every callsite that detects `paper_id.startswith("textbook:")` and rejects with "textbook source_kind not supported in m1 — wait for m2 schema migration." Option (a) is cheaper and more defensible.
- **Regression guard:** A test per callsite that passes `textbook:foo` and asserts the expected pre-m2 behavior (currently undefined — that itself is the issue).

### F3 — Threat-1 test surface misses prompt-enumerated injection forms

- **Severity:** MEDIUM
- **Source:** adversary
- **File:** `tests/test_identifiers.py:170-281` (the `TestTextbookIdentifiers.test_textbook_*_rejected` family)
- **What:** The prompt explicitly enumerated injection vectors the regex MUST reject: "trailing whitespace (not just `\n`), leading whitespace, unicode lookalikes (e.g. `textbook:foo<RTL>` — RTL override), bare prefix `textbook` (no slug, no colon), `textbook:.`, `textbook:..`, `textbook:./`, control characters, backslash injection, URL-encoded path traversal `textbook:%2e%2e%2f`". Of these, ONLY internal space (N4) and trailing newline (N5) are explicitly tested. The regex DOES reject every one of these (I verified by running each through `is_valid_paper_id` — all return False), so the runtime is safe. But "the regex coincidentally rejects" is a weaker invariant than "the test suite documents the rejection contract." A future regex refactor (m2's source_kind discriminator? a future tightening for length?) could re-admit one of these silently.
- **Why it matters:** The brief said ≥5 fixtures; the implementer shipped 11 + 6 = 17. But the prompt's reviewer-facing checklist enumerated more specific shapes. Calling this "MEDIUM" not "HIGH" because the regex IS correct today — the gap is documentary, not behavioral.
- **Proposed fix:** Add ~8 more negative-case methods to `TestTextbookIdentifiers`: `test_textbook_trailing_space_rejected`, `test_textbook_trailing_tab_rejected`, `test_textbook_trailing_cr_rejected`, `test_textbook_leading_whitespace_rejected`, `test_textbook_bare_prefix_rejected` (`"textbook"` with no colon), `test_textbook_url_encoded_traversal_rejected` (`"textbook:%2e%2e%2f"`), `test_textbook_rtl_override_rejected` (`"textbook:foo‮"`), `test_textbook_backslash_injection_rejected`. Each is a one-line `assert not is_valid_paper_id(...)`.
- **Regression guard:** The 8 new tests are themselves the guard.

### F4 — Six error messages still hardcode "arXiv id" after widening

- **Severity:** MEDIUM
- **Source:** adversary
- **File:** `server/handlers/paper.py:67`, `server/handlers/lemma.py:96`, `server/routes/notebooks.py:461`, `server/routes/notebooks.py:557`, `ingest/extract_equations.py:371`, `ingest/bulk_ingest.py:272`
- **What:** Each error string is some variant of `f"paper_id {paper_id!r} does not match the arXiv id format"` or `f"paper_id {paper_id!r} is not a valid arXiv id"`. After m1, `is_valid_paper_id` accepts three forms including `textbook:<slug>` — but a malformed input like `textbook:` (empty slug) still produces an error message claiming the regex only checks arXiv shapes. The error message is now lying about what the validator does.
- **Why it matters:** Documentation drift. Confusing for operators and pipeline researchers reading 5xx logs in 2026-06+ once m2 ships writer support and operators start sending textbook-shaped paper_ids.
- **Proposed fix:** Search-and-replace `arXiv id format` → `paper_id format` and `is not a valid arXiv id` → `is not a valid paper_id` across these 6 sites. One-line changes, no test impact.
- **Regression guard:** Not strictly required for a doc fix; existing identifier tests guard the behavior.

### F5 — Eval-fixture validator's PAPER_ID_RE accepts textbook but CHUNK_ID_RE does not

- **Severity:** MEDIUM
- **Source:** adversary
- **File:** `tools/validate_eval_fixtures.py:106-118` (the `_PAPER_ID_RE`) vs `tools/validate_eval_fixtures.py:121-135` (the `_CHUNK_ID_RE`)
- **What:** The validator's `_PAPER_ID_RE` was extended with the textbook alternative for "lockstep" with the canonical (and the byte-equality test). But `_CHUNK_ID_RE` deliberately remains arXiv-only (per the inline comment at line 117 "the validator does not currently accept textbook chunk-ids because no eval fixtures are textbook-shaped"). The two regexes are now asymmetric inside the same file. If a curator accidentally types a `textbook:<slug>` paper_id into an eval fixture, `_PAPER_ID_RE` accepts it but `_CHUNK_ID_RE` rejects every chunk row referencing it — a confusing validation experience.
- **Why it matters:** Internal inconsistency. The implementer's defense — that the lockstep is required by the byte-equality test — is correct, but the resolution is asymmetric: paper_id accepts textbook, chunk_id does not. A defensible choice is to keep both forms consistent in the validator (either both arXiv-only or both extended); the byte-equality test should not drive a half-extension.
- **Proposed fix:** Add a test `tests/test_validate_eval_fixtures.py::test_textbook_paper_id_rejected_for_eval_fixtures` that asserts `_PAPER_ID_RE.match("textbook:foo") is None` after a future validator-level constraint is added (an `is_arxiv_only_paper_id` helper that the validator uses instead of the lockstep regex). OR: accept the asymmetry as deliberate and document it in the validator's module docstring (currently the inline comment is on the wrong regex).
- **Regression guard:** A single new test that documents the intended asymmetry.

### F6 — Snapshot test for arXiv byte-stability is a behavioral check, not a snapshot

- **Severity:** LOW
- **Source:** adversary
- **File:** `tests/test_identifiers.py:141-152` (`test_arxiv_chunk_id_still_valid_after_m1` + `test_paper_id_from_arxiv_chunk_id_unchanged`)
- **What:** The prompt's AC #3 (and the researcher's brief / synthesis) called for a "snapshot test of representative arXiv chunk_ids." What shipped is two methods with 2 + 2 hand-coded assertions each — functionally equivalent for the four cases they cover, but not a parametrized snapshot/golden fixture. If the implementer regresses behavior on a 6-digit pre-2015 ID (`hep-th/0001234`) — a shape the chunker has produced for years — the test would not catch it because it's not in the fixture set.
- **Why it matters:** AC #3 is "byte-identical to today" — strictly, that means a snapshot. A two-case check is weaker.
- **Proposed fix:** Replace the two methods with a single parametrized test fed by a small fixture of representative arXiv IDs (new-style 5-digit, new-style 4-digit, old-style hep-th, old-style math-ph, version suffix) under `@pytest.mark.parametrize`. ~12 LOC.
- **Regression guard:** N/A — the parametrize IS the guard.

### F7 — `from ingest.identifiers import paper_id_from_chunk_id` imported inside test methods

- **Severity:** LOW
- **Source:** adversary
- **File:** `tests/test_identifiers.py:155`, `tests/test_identifiers.py:166`, `tests/test_identifiers.py:282`
- **What:** Three test methods import `paper_id_from_chunk_id` (and `pytest`) at function scope. The top-of-file imports already include `is_valid_paper_id, is_valid_chunk_id`; `paper_id_from_chunk_id` should be there too. Function-scope imports were occasionally used pre-existing for circular-import workarounds; there is no such workaround needed for the `ingest.identifiers` module (it has no dependencies on `server/` or `tests/`).
- **Why it matters:** Style + readability + ruff's `PLC0415` (import outside top-level) would flag this if enabled. `ruff check` passes today because the rule is not enforced.
- **Proposed fix:** Move the two helper imports to the top of `tests/test_identifiers.py` (line 11-ish) alongside the existing `from ingest.identifiers import ...` line. Two-line edit.
- **Regression guard:** N/A — pure refactor.

## What was done well

- Canonical `_PAPER_ID_FULL_PATTERN` and `CHUNK_ID_PATTERN` are docstring-rich, with explicit rationale for the load-bearing `(?:...)` outer wrapper, the positional-capture-group choice (preserves ECMA-262/Python schema lockstep), and the asymmetric textbook-prefix semantics. Future readers can derive the intent without git archaeology.
- The F3 `$`→`\Z` fix was extended to `CHUNK_ID_RE` (closing a second instance of the same bug class) AND to `tools/validate_eval_fixtures._CHUNK_ID_RE` for defense-in-depth. The implementer flagged both as deviations 1 + 2 in the summary — transparent scope expansion.
- The byte-equality lock test (`test_schema_chunk_id_pattern_matches_canonical`) is preserved by carefully matching ECMA-262 non-capturing-group syntax `(?:v\d+)?` in BOTH the canonical and the JSON Schema — the schema pattern parses correctly in Python and accepts/rejects the right inputs.
- 17 negative regression tests for path-traversal (vs the brief's ≥5) covers slash, dotdot, null-byte, internal whitespace, trailing-newline (`\Z` bypass), empty slug, uppercase, length min/max, nested-prefix, chunk-id-form-as-paper-id, and the F3 fix on chunk_ids. Strong baseline.
- Tier-sequencing discipline: `ingest/schema.py`, `ingest/store.py`, `server/tools.py`, `server/prompts.py`, `tests/test_server_tool_schema.py`, and `tests/test_prompts.py` are all untouched. m2 and m3 scope is correctly preserved.
- Cache byte-stability is intact: tool-list hash test (9/9 passing) and BP1 hash test (`test_prompts.py` 33/33 passing) both pinned. The result-schema edit at `server/schemas/search_papers_result.json` is a runtime envelope contract, NOT a `tools/list` contributor — correctly outside the BP1 cache surface.
- Three failing tests (`TestIntegrationRealLatexmlc::*` x2, `TestToolsSmoke::test_cite_neighbors_wired`) are plausibly pre-existing environmental issues (`latexmlc` SIGABRT, Kùzu local-state) — the implementer's `git stash` repro claim is consistent with my own ability to reach `tests/test_identifiers.py` (40/40 pass), `tests/test_server_tool_schema.py` (9/9), and `tests/test_snippet_contract.py::TestRegexSourceOfTruth` (1/1) cleanly.
- The chunker's `_PAPER_ID_RE` lockstep comment correctly notes "the chunker never PRODUCES textbook paper_ids in m1" — forward-compat without scope creep.
- Module docstring in `ingest/identifiers.py:13-25` was updated in lockstep with the regex change — operator-facing contract stays accurate.
- `paper_id_from_chunk_id`'s error path was extended cleanly: the ValueError message now mentions both forms (`arxiv:<paper_id>:<16-hex> or textbook:<slug>:<16-hex>`) — useful for downstream error logs.

## Recommended rectification order

1. **F1** — close the upload-path colon-sanitizer hole. Either reject textbook paper_ids at the three notebook routes (lines 152/458/554 in `server/routes/notebooks.py`) until m2 ships, OR widen the sanitizer to handle colons. This is the only finding with a plausible exploit path today.
2. **F2** — introduce `is_valid_arxiv_paper_id` (or equivalent) and use it at filesystem-construction + SQL-style sites that don't yet have m2 writer support. This decouples "the canonical regex" from "the security gate at each callsite."
3. **F3** — expand the negative-case test family with the 8 missing Threat-1 shapes the prompt enumerated. Cheap, high signal.
4. **F4** — search-and-replace the 6 "arXiv id" error messages for accuracy.
5. **F5** — document the deliberate asymmetry between `_PAPER_ID_RE` and `_CHUNK_ID_RE` in the eval-fixture validator (or fix the asymmetry).
6. **F6** — convert the byte-stability arXiv assertions to a parametrized snapshot.
7. **F7** — move imports to the top of the test file. Deferrable to a future hygiene pass.

## Rectification status

- F1 — fixed in `aec3a12` (server/routes/notebooks.py:619; sanitizer now strips `:` along with `/`). Regression guard: `tests/test_identifiers.py::TestM1RectGatesRejectTextbook::test_upload_sanitizer_neutralizes_colon` + `test_upload_sanitizer_preserves_arxiv_oldstyle`. Primary defense is F2's arXiv-only gate; this is layer 2.
- F2 — fixed in `aec3a12` (added `is_valid_arxiv_paper_id` to `ingest/identifiers.py`; repointed 15 non-test callsites). Regression guards: `TestIsValidArxivPaperId` (5 tests) + `TestM1RectGatesRejectTextbook` (4 tests, including `test_extract_equations_module_uses_arxiv_only_helper` and `test_paper_handler_uses_arxiv_only_helper`).
- F3 — fixed in `aec3a12` (tests/test_identifiers.py). Added 9 new negative-case methods covering the prompt-enumerated injection shapes (trailing space/tab/CR, leading whitespace, bare prefix, dot-slugs, URL-encoded traversal, RTL override, backslash, ASCII control chars). Regression is itself the guard.
- F4 — invalidated by re-verify. After F2 repointed all gates to `is_valid_arxiv_paper_id`, the existing "arXiv id" error messages are accurate. No edits needed; the cited region no longer matches the finding's claim.
- F5 — fixed in `aec3a12` (tools/validate_eval_fixtures.py). Module-level docstring on `_PAPER_ID_RE` documents the intentional asymmetry between paper-id (accepts textbook for lockstep) and chunk-id (rejects textbook) and the trip-wire behavior it produces.
- F6 — deferred (LOW; snapshot-vs-behavioral test shape; pure refactor with no behavior delta; tracked for future hygiene pass).
- F7 — deferred (LOW; function-scope import style; ruff PLC0415 not currently enforced; tracked for future hygiene pass).

**Summary:** 5 fixed (F1, F2, F3, F5 + F4 secondary invalidation), 1 invalidated (F4), 2 deferred (F6, F7). Adversary invalidation rate 1/7 = 14% (well under 40% prompt-broken threshold).
