# Critique — textbook-ingest-m11

**Critic:** adversary
**Generated:** 2026-05-28T18:39:48Z
**Commit range:** a7da3f06e0e7d0994700fb53e0bec5e25c4f62a1..77a99b506bd5d85a8c6c53cb7228ac66ae403723
**Verdict:** SHIP-WITH-FIXES

## Executive summary

- SHIP-WITH-FIXES: the headline leak-path invariant (FM-1/FM-2) is correctly implemented and tested; remaining findings are doc-precision + test-completeness, none block ship.
- Finding counts: 0 CRITICAL, 0 HIGH, 2 MEDIUM, 2 LOW.
- Highest-risk surface (verified SAFE): `server/handlers/chunk.py:88-92` — license truncation runs on the sanitized INNER body BEFORE `enforce_byte_cap` (line 126) AND before `wrap_retrieved_text` (line 139); a non-OA chunk can never emit a `resource_link` to its full body.
- Scope completeness independently verified: grepped every `server/handlers/*.py` — `get_chunk` is the EXCLUSIVE full-body surface (search snippet 150<300; equation/lemma/paper carry no body; definitions surfaces preamble macro `expansion`, not chunk body). No other non-OA leak path exists.
- Cache re-pin scope is EXACTLY right and empirically confirmed: `TOOL_SCHEMA_VERSION` 15→16, `EXPECTED_TOOL_SCHEMA_SHA256` re-pinned, `EXPECTED_BP1_SHA256` NOT touched. `tests/test_prompts.py` (115 tests) passes with the unchanged BP1 hash → BP1 did not drift. GET_CHUNK ToolMeta description is byte-identical in the diff.
- Fail-closed correctness verified: `is_open_access(None)`, `("")`, unknown, and case-variant (`"cc-by"`) all return False (truncate); no TypeError risk (schema declares `license` as `pa.utf8()`, value is always str|None, `or ""` neutralizes None).
- 549 relevant tests pass (0 fail), ruff clean on all changed files; pyproject/uv.lock untouched (no-fork clean); conftest KMP guard intact.
- The MEDIUM findings are: (F1) the GET_CHUNK ToolMeta description still claims "Fetch the full body" with no mention of non-OA truncation — a description/behavior mismatch the agent only resolves at runtime; (F2) no test pins the exact 301-char truncation boundary or asserts truncated CONTENT identity (only length), so a future off-by-one or wrong-slice-source regression could pass.

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

### F1 — GET_CHUNK description claims "full body"; silent on non-OA truncation

- **Severity:** MEDIUM
- **Source:** adversary
- **File:** server/tools.py:217-223
- **What:** The GET_CHUNK `ToolMeta.description` says "Fetch the **full body** of one chunk by its content-addressable chunk_id" and documents only the 256 KB byte-cap / `resource_link` path. It does not mention that a non-open-access chunk's body is silently capped at 300 chars. For a non-OA chunk the description is now factually wrong about the common-path return value.
- **Why it matters:** The description is the agent-facing contract for the tool. An agent reading it expects the full body and has no a-priori signal that some chunks return only a 300-char excerpt; it discovers the restriction only reactively via the runtime `truncated_for_license` flag + surfaced `chunk.license`. This is a correctness/transparency gap, not a leak. CRUCIALLY: the description is INSIDE the BP1 byte region (`test_prompts.py:464` hashes `{name, description}` per tool), so any edit here drifts `EXPECTED_BP1_SHA256` — the synthesis explicitly forbade mentioning the flag in the description for exactly this reason (research-synthesis.md:59). This is a genuine tension, not an oversight; the implementer made the defensible call to preserve BP1 stability over description completeness. Flagging so Phase 4 makes the trade-off deliberately rather than by omission.
- **Proposed fix:** Preferred (zero BP1 cost): leave the description unchanged and accept the runtime-flag-only discovery model; record under deferred_findings as a documented limitation. The runtime flag + `chunk.license` token already give the agent everything it needs reactively, and `snippet-contract.md §(g)` is the authoritative human-facing contract. If Phase 4 instead decides the description MUST mention truncation, it is a coordinated BP1 re-pin: edit the description (e.g. append "Non-open-access chunks return at most a 300-char excerpt with truncated_for_license=true.") AND re-pin `EXPECTED_BP1_SHA256` in `tests/test_prompts.py` in the SAME commit — do NOT edit one without the other (that is the bp1-description drift class). Note this would also invalidate BP1 prompt-cache across all agent roles on next deploy.
- **Regression guard:** If the description is edited, add an assertion in `tests/test_prompts.py` that the new BP1 hash is pinned AND a `test_server_tool_schema.py` cross-check; if left unchanged, no guard needed (the absence of a description-mentions-truncation test is itself the documented decision).

### F2 — Truncation tests assert length only, never content identity or the 301-char boundary

- **Severity:** MEDIUM
- **Source:** adversary
- **File:** tests/test_handlers_chunk.py:127-130
- **What:** `test_non_oa_body_truncated_to_300_with_flag` (and the other truncation tests) seed a uniform body (`"y"*500`, `"z"*500`, `"m"*1000`) and assert `len(_inner(...)) == 300`. Because the body is a single repeated character, the test cannot distinguish "took the FIRST 300 chars of the sanitized body" from "took the LAST 300", "took a different 300", or "emitted 300 chars of some other string". No test seeds a distinctive prefix to confirm the surfaced excerpt is `sanitized_body[:300]` byte-for-byte, and no test exercises the exact off-by-one boundary (a 301-char body → truncated to 300 + flag; a 300-char body → untruncated, no flag).
- **Why it matters:** The slice source and offset are the load-bearing correctness detail. A future refactor that changed `sanitized_body[:LICENSE_TRUNCATION_CHARS]` to slice the wrong variable, or an off-by-one (`[:299]` / `[:301]`, or flipping the guard to `>=`), would pass every existing test. The current suite proves "300 chars come out" but not "the RIGHT 300 chars" nor "the boundary is exactly 300". By inspection the committed code IS correct (`chunk.py:90-91`: guard is `> 300`, slice is `[:300]` on `sanitized_body`), so this is a missing-test finding, not a live bug.
- **Proposed fix:** In `tests/test_handlers_chunk.py`, (a) add a content-identity assertion: seed `body = ("ABCDEFGHIJ" * 40)` (400 distinct-prefix chars) for a non-OA chunk and assert `_inner(r["chunk"]["body_text"]) == body[:300]` (not just the length). (b) Add a boundary test: a 301-char non-OA body truncates to 300 with the flag; a 300-char non-OA body returns all 300 chars with NO flag (asserts the `>` guard, not `>=`). ~12 LOC, no new fixtures.
- **Regression guard:** The two added assertions above are themselves the regression guard — they fail on any wrong-source slice, off-by-one, or guard-operator flip.

### F3 — Truncating at 300 chars can leave unbalanced LaTeX/MathML (accepted, undocumented in code)

- **Severity:** LOW
- **Source:** adversary
- **File:** server/handlers/chunk.py:90-92
- **What:** `sanitized_body[:300]` can slice mid-`$...$`, mid-`\begin{equation}...\end{equation}`, or mid-`<math>...</math>`, producing a syntactically broken excerpt. This is codepoint-safe (str slicing never splits a UTF-8 char — verified, and noted in the code comment at line 87) but not math-token-safe.
- **Why it matters:** Math fidelity is an arXMCP axis (notes 01/04). For a NON-OA chunk this is the intended, acceptable behavior — the whole point is to withhold the full math, and a 300-char fair-use excerpt is allowed to be incomplete. The `<retrieved_chunk>` wrap escapes any literal delimiter tag in the truncated body (`tools.py:493`), so a mid-LaTeX cut cannot forge a delimiter or break the wrap. No leak, no injection, no crash. Worth a one-line acknowledgement so a future reader does not "fix" it by trying to truncate on a token boundary (which would risk over-surfacing past 300 chars).
- **Proposed fix:** None required for ship. Optionally add one sentence to the `chunk.py:77-87` comment block: "The 300-char excerpt may end mid-LaTeX/MathML; this is intentional for non-OA chunks (a partial excerpt, not a renderable unit) and is harmless because wrap_retrieved_text escapes any sliced delimiter tag." Defer.
- **Regression guard:** N/A (accepted behavior; no test needed).

### F4 — `paper.abstract` is a future non-OA leak vector once E11 backfills metadata

- **Severity:** LOW
- **Source:** adversary
- **File:** server/handlers/paper.py:100
- **What:** `get_paper` returns `abstract: None` at v1, so it surfaces no body today and is correctly excluded from the m11 scope. When E11 backfills the papers metadata table, a non-OA textbook's `abstract` could surface in full (the `enforce_byte_cap` truncation target is `("paper","abstract")` at 1024 chars — well above 300) without any license gate.
- **Why it matters:** Out of scope for m11 (abstract is NULL now, and abstracts are conventionally publishable even for otherwise-restricted works), so this is NOT a defect of this milestone. But m11 is the milestone that establishes the license-truncation policy, and the policy currently lives ONLY in `get_chunk`. A future E11 author backfilling abstracts has no in-code reminder that a second full-text-ish surface now exists. Recording it so the policy's scope assumption ("get_chunk is the only full-body surface") is revisited when that assumption changes.
- **Proposed fix:** No code change for m11. Add one sentence to `snippet-contract.md §(g)`: "Scope note: when E11 backfills get_paper.abstract, re-evaluate whether the license-truncation policy must extend to that surface." This makes the scope assumption explicit and durable. Defer to E11.
- **Regression guard:** N/A (forward-looking; the §(g) note is the guard).

## What was done well

- The load-bearing FM-1/FM-2 ordering invariant is implemented EXACTLY as the synthesis specified: sanitize → license-truncate → byte-cap → wrap (`chunk.py:76, 88-92, 126, 139`). The truncation is on the inner sanitized string before both downstream stages, closing both the resource_link leak (FM-2) and the delimiter-slice (FM-1).
- `test_non_oa_huge_body_never_emits_resource_link` (test:175-184) genuinely SEEDS a 300 KB (>256 KB cap) non-OA body and asserts `resource_link_uri` absent, `body_truncated` falsy, and inner ≤300 — it actually exercises the FM-2 headline risk rather than asserting it trivially.
- `test_oa_huge_body_still_byte_capped` (test:186-194) is the correct negative control: it proves the OA path is UNCHANGED (byte-cap + resource_link still fire for a 300 KB OA body), guarding against an over-broad fix that would have suppressed the cap for everyone.
- Fail-closed is correct and fully tested: None, "", unknown, and case-variant (`"cc-by"`, `"ARXIV-LICENSE"`, `"Gfdl"`) all return False with dedicated tests (`test_license_policy.py:37-56`); the `if not license_token` guard cleanly covers both None and "".
- Re-pin scope is precisely correct and EMPIRICALLY verified: `TOOL_SCHEMA_VERSION` 15→16, `EXPECTED_TOOL_SCHEMA_SHA256` re-pinned, `EXPECTED_TOOL_SCHEMA_VERSION_AT_HASH` 16, both global-echo schema `version`/`$id` fields → 16, and `EXPECTED_BP1_SHA256` untouched. `test_prompts.py` passes with the old BP1 hash → BP1 provably did not drift, exactly as predicted.
- Scope discipline (D2): correctly resisted adding the flag to `search_papers` rows — the 150-char snippet is already below the 300-char cap, so a search-row flag would be informational churn on the final-milestone schema. Independently confirmed by grepping every handler.
- The `truncated_for_license` flag follows the established absent-when-false convention (mirrors `body_truncated` / `filters_applied`), and surfacing the `license` token (D4) gives the agent the WHY without a second round-trip.
- `is_open_access` is a clean pure predicate with no banned `assert` and no spurious `raise` — the docstring even explains WHY there is no invariant guard (`license_policy.py:60-62`). Uses `str` slicing (codepoint-safe), not bytes (FM-3).
- `snippet-contract.md §(g)` is a thorough, accurate human-facing contract: policy, allowlist with per-token rationale, fail-closed default, the present-only-when-true convention, the load-bearing ordering, and the no-new-column note all documented and matching the code.
- No-fork clean (pyproject/uv.lock untouched, no lift markers in the new module), conftest KMP guard intact, ruff clean, and 549 relevant tests pass with zero failures.

## Recommended rectification order

1. F2 (MEDIUM, ~12 LOC, cheap) — add content-identity + 301/300 boundary assertions to `tests/test_handlers_chunk.py`. Highest leverage: hardens the load-bearing slice against future off-by-one/wrong-source regressions with no production-code change and no BP1/cache risk.
2. F1 (MEDIUM) — DECIDE explicitly: either leave the GET_CHUNK description as-is and record the runtime-flag-only discovery model as a documented limitation (preferred, zero BP1 cost), or do a coordinated description-edit + `EXPECTED_BP1_SHA256` re-pin in one commit. Do not split the pair.
3. F4 (LOW, defer) — add the E11 scope-revisit note to `snippet-contract.md §(g)`.
4. F3 (LOW, defer) — optionally append the one-line "intentional partial excerpt" comment in `chunk.py`.

## Rectification status

3 fixed, 1 deferred, 0 invalidated. Re-verify gate: the cited regions
matched the findings' claims against current code (the FM-1/FM-2 invariant
the critic verified safe was left untouched).

- **F2 (MEDIUM)** — FIXED in `tests/test_handlers_chunk.py`: added
  `test_truncation_surfaces_the_first_300_chars_verbatim` (distinct-prefix
  body → asserts inner == `body[:300]`, pinning the slice SOURCE+OFFSET)
  and `test_boundary_301_truncates_300_exactly_keeps_full` (301→truncated
  + flag; 300→untruncated, no flag — pins the strict `>` guard).
- **F1 (MEDIUM)** — DEFERRED (the adversary's preferred path; deliberate
  trade-off). The GET_CHUNK ToolMeta description is left BP1-stable;
  editing it to mention the 300-char non-OA cap would drift
  `EXPECTED_BP1_SHA256` + force a second version cascade (16→17) + a
  one-time prompt-cache invalidation across all agent roles — not cheap
  for a MEDIUM doc-precision gap. The runtime `truncated_for_license`
  flag + surfaced `chunk.license` token + `snippet-contract.md §(g)`
  (which now documents this trade-off explicitly) are the contract; the
  description is accurate for 100% of the arXiv corpus (all OA).
- **F3 (LOW)** — FIXED in `server/handlers/chunk.py`: added the
  "intentional partial excerpt; do NOT truncate on a token boundary"
  comment so a future reader doesn't mis-"fix" the mid-LaTeX cut.
- **F4 (LOW)** — FIXED in `.claude/docs/snippet-contract.md §(g)`: added
  the E11 scope-revisit note (re-evaluate the policy for
  `get_paper.abstract` when E11 backfills it).

Adversary invalidation rate: 0/2 HIGH+CRITICAL (there were none); all 4
findings valid. The headline FM-1/FM-2 leak invariant was verified safe
by the critic — no production-behavior change in this rectification.
