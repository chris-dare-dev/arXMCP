# Critique — notebook-paper-discovery-m2

**Critic:** adversary
**Generated:** 2026-05-31T00:00:00Z
**Commit range:** babe092963453cae92ee1ffd279c7ea7e535ec87..dc33ba1748e0945fba473c99ed16eb5041de529f
**Verdict:** SHIP

## Executive summary

- SHIP: clean library extraction with solid security hardening; 0 CRITICAL / 0 HIGH findings
- 0 CRITICAL, 0 HIGH, 1 MEDIUM, 2 LOW
- Highest-risk line: `tools/_arxiv_api.py:99` — `_keyword_clause` strips+quotes but passes empty phrase if caller sends whitespace-only keyword
- The "no behavior change" claim is imprecise: the trailing `time.sleep(3s)` that pre-m2 `main()` always fired after a single-page fetch is gone; the new code sleeps only *between* pages, so a single-page CLI run no longer sleeps at all
- Pagination loop correctness verified: `max_pages` formula is belt-and-suspenders over the `start < ARXIV_TOTAL_CAP` guard; all tested edge cases (empty page, short page, exact-multiple, multi-page sleep injection) trace correctly
- `defusedxml.ElementTree` is correctly imported and used; the project already depends on `defusedxml>=0.7`; XXE/entity-expansion is blocked at the `fromstring` call
- `test_mcp_resources.py::TestByteStability::test_tools_list_hash_unchanged_with_resources` flakiness is pre-existing order-dependent state pollution: m2 touches only `tools/` and `tests/` — no `server/` change could affect `ALL_TOOLS` or the pinned hash
- No m3/m4 scope leaked: diff is strictly the library extraction + curate_seed rewire

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

### F1 — Whitespace-only keyword produces degenerate abs:"" phrase

- **Severity:** MEDIUM
- **Source:** adversary
- **File:** tools/_arxiv_api.py:99
- **What:** `_keyword_clause` does `value.replace('"', "").strip()` then wraps the result in double-quotes. A caller that passes `abs_keywords="   "` (whitespace-only, e.g. a notebook description that is blank after stripping) gets `abs:""` in the URL — an empty quoted phrase that arXiv treats as either a match-all or an error-entry response (depending on API version). No input validation guard rejects this before the HTTP call.
- **Why it matters:** The m3 notebook-discovery driver will populate `abs_keywords` from notebook metadata (descriptions). A notebook with an empty/blank description field will silently send a degenerate query. If arXiv returns an error-entry feed, `parse_atom_feed` raises `RuntimeError` and propagates to the driver. If it returns a match-all, the caller gets hundreds of unfiltered results. Either outcome is a latent foot-gun; the correct behavior is to skip the clause entirely when the keyword is blank after stripping.
- **Proposed fix:** In `_keyword_clause`, return `None` when `cleaned` is empty, and guard the callers in `build_query_url`:
  ```python
  def _keyword_clause(field: str, value: str) -> str | None:
      cleaned = value.replace('"', "").strip()
      if not cleaned:
          return None
      return f'{field}:"{cleaned}"'
  ```
  Then in `build_query_url`:
  ```python
  clause = _keyword_clause('abs', abs_keywords)
  if clause:
      search_query += f" AND {clause}"
  ```
  Same for `ti_keywords`.
- **Regression guard:** Add `TestBuildQueryURL.test_whitespace_only_keyword_skips_clause`:
  ```python
  def test_whitespace_only_keyword_skips_clause(self) -> None:
      url = build_query_url("math.AG", abs_keywords="   ")
      assert _search_query(url) == "cat:math.AG"
  ```

---

### F2 — Brief's "no behavior change" claim: trailing politeness sleep removed

- **Severity:** LOW
- **Source:** adversary
- **File:** tools/curate_seed.py:108 (post-m2 `main()`; compare pre-m2 line 166)
- **What:** Pre-m2 `main()` always called `time.sleep(POLITENESS_SLEEP_SECONDS)` (3s) after a successful single-page fetch, before returning. The m2 rewire removes this sleep entirely from the CLI path. For `max_results <= 2000` (the default is 200), the new `fetch_candidates` is a single request with zero sleep, so the CLI no longer pauses 3s after running.
- **Why it matters:** The implementation summary claims "for `max_results` ≤ 2000 this is a single request with no sleep — identical to the pre-m2 single-fetch behaviour." This is incorrect: pre-m2 DID sleep after a single-page fetch. The brief says "NO behavior change." The observable change is benign for the one-shot CLI use case (the sleep guarded the *next* manual invocation, not any downstream call within the same run), but the claim is factually wrong and could mislead the m3 author if they assume the library imposes a post-fetch delay.
- **Proposed fix:** Either (a) document the change explicitly in the module docstring ("Note: unlike the pre-m2 `main()`, the library does not sleep after the final page. Callers that need a trailing courtesy sleep must add one."), or (b) accept as-is since the behavior is correct for a library (callers control sleep via the injected `sleep` parameter) and the pre-m2 trailing sleep was a CLI-level concern. Option (b) is recommended; only update the implementation summary's "identical" wording.
- **Regression guard:** No test needed; this is a documented CLI courtesy change, not a functional regression.

---

### F3 — stderr output changed despite "NO behavior change" claim

- **Severity:** LOW
- **Source:** adversary
- **File:** tools/curate_seed.py:100–101
- **What:** Pre-m2 stderr: `"# politeness: 1 request, sleeping 3.0s before any follow-up"`. Post-m2 stderr: `"# politeness: paginating at <= 3.0s/page via tools._arxiv_api"`. The message content changed.
- **Why it matters:** No existing test checks stderr output, so existing tests still pass. The change is purely informational. However, taken together with F2, the implementation summary's blanket "no behavior change" characterization should note these two deviations to prevent m3 from building assumptions on the pre-m2 message.
- **Proposed fix:** Update the implementation summary's "no behavior change" language to "TSV stdout output and existing test assertions pass unchanged; two informational changes: (1) trailing post-fetch sleep removed, (2) stderr politeness message updated." No code change needed.
- **Regression guard:** None required.

## deferred_findings

- **Category injection not validated:** `build_query_url` only checks `if not category` (empty string). A crafted category string like `"math.AG OR abs:password"` would pass the check and get embedded unquoted as `cat:math.AG OR abs:password`. This is LOW severity because (a) category is operator-supplied (structured arXiv code, not user-text), (b) the CLI defaults to `"math.AG"`, and (c) the m3 discovery driver will use hardcoded or validated category values. Not worth a top-level finding but the m3 author should validate category against the known arXiv category codes before passing to `build_query_url`.

## What was done well

- **`defusedxml` used correctly and proactively.** `DET.fromstring` (line 145) blocks XXE and entity-expansion attacks on untrusted Atom responses, closing the FM-1 gap. The import is `defusedxml.ElementTree as DET` — the correct alias, not the stdlib ET fallback.
- **Error-entry detection is correct and tested.** The `_ERROR_ID_MARKER = "/api/errors#"` sentinel at line 66, matched in `parse_atom_feed` at line 151, correctly detects the arXiv HTTP-200 error pattern (FM-6) and raises a named `RuntimeError` with the summary text. The `test_error_entry_raises` test pins this path.
- **Injection containment for keywords is solid.** `_keyword_clause` double-quotes the phrase (neutralising `AND`, `OR`, `NOT`, field prefixes) and strips embedded `"` (preventing phrase-termination). The injection test `test_keyword_injection_is_contained_in_phrase` pins this contract.
- **Pagination loop converges correctly.** All three convergence guards (empty page, short page, `start < ARXIV_TOTAL_CAP`, `pages >= max_pages`) are in place. The `max_pages = ceil(n/page_size) + 1` formula provides a belt-and-suspenders cap without over-fetching. Traced manually: all edge cases (200, 2000, 2001, 5000, 30000) produce the correct call count and result length.
- **Sleep injection is clean.** `fetch_candidates(sleep=time.sleep)` with an injectable `Callable[[float], None]` default (line 212) gives the test suite full control over timing without mocking `time.sleep` globally. The `test_single_page_no_sleep` and `test_multi_page_sleeps_between_pages` tests exercise both branches with zero live network calls.
- **Backward-compatible signature.** `build_query_url(category, start=0, max_results=200, *, abs_keywords=None, ti_keywords=None)` keeps `start`/`max_results` positional so the existing `TestCurateQueryURL` calls (`build_query_url("math.AG", 0, 10)` and `build_query_url("math.AG", start=0, max_results=200)`) work unchanged. `test_no_keywords_matches_legacy_params` pins the byte-identity.
- **`_fetch_url` is correctly privatised for monkeypatching.** By making it a module-level private function and having the tests patch `_arxiv_api._fetch_url`, the test suite avoids the fragile global `urllib.request.urlopen` monkeypatch, following the established `graph_ingest._fetch_openalex_work` pattern.
- **`MAX_RESPONSE_BYTES = 50 MB` read cap applied.** `resp.read(MAX_RESPONSE_BYTES)` at line 202 defends against inflated or malformed Atom responses (FM-5). The cap is documented with its rationale.
- **ruff clean.** All three files pass `ruff check` with no violations. Re-export-only imports (`ARXIV_API_URL`, `ATOM_NS`) in `curate_seed.py` are covered by `__all__` so ruff F401 does not fire.
- **No MCP surface touched.** The diff is confined to `tools/` and `tests/`. `server/tools.py::ALL_TOOLS` is unchanged; `EXPECTED_TOOL_SCHEMA_SHA256` does not need re-pinning. The `test_mcp_resources.py` hash-stability test is unaffected by m2.

## Recommended rectification order

1. **F1 (MEDIUM)** — Add the empty-cleaned-keyword guard in `_keyword_clause` and the corresponding test. This is ~10 LOC + 1 test case and closes the degenerate-query foot-gun before m3 consumes the library.
2. **F2 (LOW)** — Update the implementation summary's "identical" wording. No code change needed.
3. **F3 (LOW)** — Note the stderr change in the implementation summary alongside F2. No code change needed.

## Rectification status (filled by Phase 4)

- F1 (MEDIUM) — fixed in `tools/_arxiv_api.py`: `_keyword_clause` now returns `None`
  when the value is empty after stripping quotes+whitespace, and `build_query_url`
  drops the clause instead of emitting a degenerate `abs:""`/`ti:""` phrase.
  Regression guard:
  `tests/test_arxiv_api.py::TestBuildQueryURL::test_whitespace_only_keyword_skips_clause`.
- F2 (LOW) — addressed via doc precision (no code change; library behavior is correct).
  The implementation-summary's "no behavior change" claim now explicitly scopes to
  TSV stdout + tests, and records the two intentional CLI informational changes
  (trailing post-fetch sleep removed; the library owns inter-page sleep).
- F3 (LOW) — addressed alongside F2: the stderr politeness-message change is noted in
  the implementation summary. No code change.
- Deferred (LOW, m3 concern) — `build_query_url` does not validate `category` beyond
  non-empty. The m3 driver MUST validate `discovery_category` against the four arXiv
  codes (it already does via `_validate_discovery_category`, m1) before passing it.

Re-verify gate: F1 re-verified against `tools/_arxiv_api.py` (the cited
strip-then-quote produced `abs:""` for whitespace-only input, pre-fix). No findings
invalidated. Adversary invalidation rate: 0%.
