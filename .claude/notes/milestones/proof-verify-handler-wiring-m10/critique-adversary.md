# Critique — proof-verify-handler-wiring-m10

**Critic:** adversary
**Generated:** 2026-05-22T00:00:00Z
**Commit range:** 2780945b364f62193dd9334cc24f30328adac7f5..329c38f57c6b44a6a6f7496b1dceecd666263850
**Verdict:** SHIP-WITH-FIXES

## Executive summary

- SHIP-WITH-FIXES: the validator chain + CSP override mechanism are correctly built, but two real holes remain: `<meta http-equiv="refresh">` is not blocked by any CSP3 directive (navigation escape), and the path-traversal test is silently neutralized by httpx URL normalization (false negative).
- 0 CRITICAL, 2 HIGH, 4 MEDIUM, 2 LOW.
- Highest-risk site: `server/middleware.py:218-225` — the `CONTENT_SECURITY_POLICY_PREVIEW` constant has no defense against `<meta http-equiv="refresh">`, which is the one navigation escape CSP3 does not cover for the direct-serve route shape chosen in synthesis D1.
- The deleted `tests/test_m9_scope_invariants.py` was correctly removed; that guard served its m9-boundary purpose.
- The triple-defense path-validation chain (`validate_slug` → `is_valid_paper_id` → `notebook_dir` → resolved-prefix check) is sound and correctly implemented; the actual byte-comparison `startswith(str(nb_ar5iv) + "/")` works correctly on POSIX.
- The middleware idempotency override (`b"content-security-policy" not in existing`) works as designed: lowercase header name matches Starlette's normalized output (verified empirically).
- CSP byte-stability is preserved (single module-level `bytes` constant; no dynamic interpolation).
- No-fork, local-first, MCP-spec, tier-sequencing all clean (no MCP tool changes, no external network calls in the served path, no infrastructure assumptions).

## Severity calibration

| level | meaning | rectification phase action |
|---|---|---|
| CRITICAL | data loss, security regression, broken core invariant, or shippable-bug-in-production-now | always fix in Phase 4 |
| HIGH | wrong behavior reachable on common path, or load-bearing constraint violated | always fix in Phase 4 |
| MEDIUM | subtle correctness, missing test, latent foot-gun | fix only if cheap (≤ 30 LOC, small test surface) |
| LOW | style, naming, micro-perf | defer (record under `deferred_findings`) |

## Findings

### F1 — `<meta http-equiv="refresh">` is a navigation escape no CSP directive blocks

- **Severity:** HIGH
- **Source:** adversary
- **File:** `server/middleware.py:218-225` (the `CONTENT_SECURITY_POLICY_PREVIEW` constant)
- **What:** The CSP names every CSP3 non-fetch directive (`base-uri`, `form-action`, `frame-ancestors`), but CSP3 deliberately has no directive that blocks `<meta http-equiv="refresh" content="0;url=...">`. The proposed `navigate-to` directive never made it to CSP3. With the direct-serve route shape (synthesis D1), an untrusted ar5iv HTML containing `<meta http-equiv="refresh" content="0;url=https://evil.example.com/phish">` will navigate the new tab to the attacker's origin immediately on load. The user opened "Preview" expecting our content; they now see attacker content in a tab they associate with the local trusted server.
- **Why it matters:** The synthesis D1 reasoning ("`<iframe sandbox>` adds redundant script-disabling on top of `script-src 'none'`") missed that `sandbox="allow-same-origin"` ALSO blocks `<meta refresh>` per HTML5 §16.2 ("the sandboxing flag set"); that was the only mechanism in the rejected Option A that handled this. The direct-serve route now has no defense. Attack vector requires another local process or a misbehaving ar5iv upload — credible in a multi-process workstation threat model.
- **Proposed fix:** Add a pre-serve sanitization pass that strips meta-refresh tags. A single regex over `content_bytes` before constructing the response:
  ```python
  # In server/routes/ui.py, after read_bytes() and before constructing Response:
  _META_REFRESH_RE = re.compile(
      rb"<\s*meta[^>]+http-equiv\s*=\s*['\"]?refresh['\"]?[^>]*>",
      re.IGNORECASE,
  )
  content_bytes = _META_REFRESH_RE.sub(b"<!-- meta-refresh stripped -->", content_bytes)
  ```
  Alternative: revisit synthesis D1 and wrap the served content in an iframe-sandbox page (Option A) — but that's m10+ scope. The regex strip is ≤ 10 LOC.
- **Regression guard:** New test `test_meta_refresh_stripped_from_served_html` — plant `<meta http-equiv="refresh" content="0;url=https://example.com">` in an ar5iv HTML, GET the preview, assert the served body contains the stripped marker and not the original meta tag.

### F2 — Path-traversal test is a false negative; httpx normalizes the URL before send

- **Severity:** HIGH
- **Source:** adversary
- **File:** `tests/test_preview_route.py:307-318` (`test_traversal_attempt_returns_safe_status`)
- **What:** The test sends `client.get("/ui/notebooks/demo-nb/papers/../etc/preview")`. The httpx library normalizes RFC 3986 dot-segments BEFORE wire transmission — verified empirically: `httpx.URL("http://test/u/notebooks/demo-nb/papers/../etc/preview").raw_path` returns `b'/u/notebooks/demo-nb/etc/preview'`. The literal `../` never reaches the server; the server returns 404 because the route doesn't match, NOT because `is_valid_paper_id` rejected the input. The test passes by coincidence on a different code path than the validator chain it claims to verify.
- **Why it matters:** The triple-defense path-validation chain is the SECURITY load-bearing element of m10. The test is the only regression guard that traversal is rejected end-to-end. A future refactor that breaks the validator (e.g., switches to `re.match` without `\Z`) would not surface in this test. The test name + docstring imply coverage that does not exist.
- **Proposed fix:** Replace the literal-traversal path in the test with a URL-encoded form that survives httpx normalization, OR drive the route directly with a raw scope-dict (the canonical pattern used elsewhere in this repo). Concrete fix:
  ```python
  def test_traversal_attempt_returns_safe_status(self, client: TestClient) -> None:
      client.post("/ui/api/notebooks", json={"slug": "demo-nb"})
      # URL-encode the traversal so httpx doesn't normalize it away.
      r = client.get("/ui/notebooks/demo-nb/papers/..%2Fetc%2Fpasswd/preview")
      assert r.status_code == 422, r.text  # is_valid_paper_id rejection
      # The detail field will contain the rejected paper_id repr.
      # That's fine — assert the rejection mechanism, not the body sanitization.
  ```
  Also add a parametrize entry to `test_rejects_malformed_paper_id` for `..%2F..%2Fetc%2Fpasswd` to lock the behavior down.
- **Regression guard:** The fixed assertion above (`r.status_code == 422`) directly probes `is_valid_paper_id` rejection. Add a unit test that calls `is_valid_paper_id("../etc/passwd")` and asserts False — independent of the routing layer.

### F3 — `test_rejects_malformed_paper_id` accepts overly broad status codes (200 is excluded, but 5xx is silently accepted)

- **Severity:** MEDIUM
- **Source:** adversary
- **File:** `tests/test_preview_route.py:276-289` (`TestPreviewPaperIdValidation::test_rejects_malformed_paper_id`)
- **What:** The parametrized test asserts `r.status_code != 200`, which silently accepts 500 (server error), 502/503 (upstream errors), or 504 (timeouts) as "safe outcomes". A regression that causes the validator to crash with an unhandled exception would still pass this test as long as the response isn't 200. Combined with the path-leak assertions (`"/etc/" not in r.text` and `"passwd" not in r.text`), the test gives a false sense of coverage.
- **Why it matters:** The point of this test is to verify validator rejection. Accepting 5xx as "safe" hides crashes that would be real bugs.
- **Proposed fix:** Tighten the assertion to the actual expected behavior: 422 for validator rejection, 404 for FastAPI routing rejection, with no other status accepted. Adjust per-input:
  ```python
  # Allow 422 (validator rejection) or 404 (routing rejection); reject all else.
  assert r.status_code in (404, 422), f"unexpected status {r.status_code}: {r.text}"
  ```
- **Regression guard:** The tightened `assert r.status_code in (404, 422)` is itself the guard.

### F4 — `test_returns_html_with_tight_csp` does not assert the `paper_id` was URL-decoded correctly

- **Severity:** MEDIUM
- **Source:** adversary
- **File:** `tests/test_preview_route.py:138-159` (`TestPreviewHappyPath::test_returns_html_with_tight_csp`)
- **What:** Happy-path test uses the simplest `paper_id` (`2604.26204`) with no special characters. The route accepts `{paper_id:path}` and the validator must run on the URL-decoded form. There is no positive test that asserts the old-style `hep-th/0001234` paper_id ALSO returns the tight CSP correctly through the full route — the closest test (`test_old_style_paper_id_corpus_fallback`) only checks status code and body, not CSP. If a future refactor breaks CSP application for the old-style path (e.g., by gating on `"." in paper_id`), the regression slips through.
- **Why it matters:** Old-style arXiv IDs are the very category of paper this server is built for (`math-ph`, `hep-th`). The CSP boundary must hold for them too.
- **Proposed fix:** Add a single assertion to `test_old_style_paper_id_corpus_fallback` and `test_old_style_paper_id_notebook_scoped`:
  ```python
  assert (
      r.headers["content-security-policy"]
      == CONTENT_SECURITY_POLICY_PREVIEW.decode("ascii")
  )
  ```
- **Regression guard:** The added CSP assertion in the two old-style tests.

### F5 — Logging the rejected slug/paper_id at WARNING leaks attacker-controlled bytes into ops logs

- **Severity:** MEDIUM
- **Source:** adversary
- **File:** `server/routes/ui.py:286-290` (the `logger.warning(...)` inside the path-containment guard)
- **What:** When the resolved-prefix check fails (a real path-containment violation), the code logs `logger.warning("preview path-containment rejected for slug=%r paper_id=%r", slug, paper_id)`. Both inputs are validated by `validate_slug` and `is_valid_paper_id` BEFORE reaching this point — so the slug matches `^[a-z][a-z0-9-]{2,30}$` and the paper_id matches the arXiv-ID regex. Neither can contain newlines or shell metachars that would corrupt log files. **However**: this is the ONLY production path that can be exercised by an attacker who controls the filesystem (the threat model that justifies the belt-and-braces check itself). If the attacker has filesystem control, they may have constructed the symlink to a path that, when logged, helps them confirm whether the symlink redirect was detected — a side-channel oracle.
- **Why it matters:** Low-priority defense-in-depth gap. The validated inputs limit blast radius, but logging defensively-rejected inputs gives a feedback signal back to the attacker via log monitoring.
- **Proposed fix:** Either downgrade to DEBUG (operator opt-in) or remove the inputs from the log message, logging only the bare "path-containment rejected" event:
  ```python
  logger.warning("preview path-containment rejected (validated inputs)")
  ```
  Both inputs are still derivable from a correlated access-log entry if needed for forensics.
- **Regression guard:** Not strictly needed (no behavior change exercised by tests); recommend a brief comment explaining why slug/paper_id are intentionally NOT logged.

### F6 — The `add_paper`-then-`upload` flow can show "no preview available" tooltip even after a paper was added with an in-progress fetch

- **Severity:** MEDIUM
- **Source:** adversary
- **File:** `server/routes/ui.py:172-180` (the `annotated_papers` loop in `ui_notebook_detail`)
- **What:** `has_preview` is computed from filesystem existence at template render time. A paper added via the JSON `POST /ui/api/notebooks/{slug}/papers` (m7 flow, no upload) will have no on-disk HTML and render the "no preview available" tooltip immediately. There is no documented user-facing affordance to fetch/upload the HTML from the browse page; the user must use the upload card (m8). The tooltip text gives no hint at how to GET a preview. This is a UX cliff that the AC text ("missing papers show a 'no preview available' tooltip") technically satisfies but does not navigate.
- **Why it matters:** The browse-table user will see a graveyard of "no preview" tooltips on any seed-corpus-only notebook, with no clear next action. The implementation summary documents this as expected; the test suite does not catch the cliff.
- **Proposed fix:** Update the tooltip text to be actionable: `title="upload an ar5iv HTML to enable preview"`. One template edit:
  ```html
  <span class="hint" title="upload an ar5iv HTML to enable preview">Preview</span>
  ```
  Adjust `TestBrowseTableLinkConditional::test_preview_tooltip_when_html_absent` to assert the new tooltip text.
- **Regression guard:** Update the existing tooltip-text assertion.

### F7 — Missing `Referrer-Policy: no-referrer` on preview response leaks referer to navigated-to attacker site

- **Severity:** MEDIUM
- **Source:** adversary
- **File:** `server/routes/ui.py:305-313` (the `Response(...)` construction)
- **What:** If the served HTML successfully navigates the new tab to an attacker site (via the F1 meta-refresh vector OR via a user click on a `<a href="https://evil/">` in the preview), the browser will send a `Referer:` header containing the preview URL — which includes the notebook slug AND paper_id. This is a small information leak (the slug names the notebook the user was browsing); not catastrophic. Best practice for untrusted-content surfaces is to emit `Referrer-Policy: no-referrer` to suppress this.
- **Why it matters:** Defense-in-depth gap. The slug is user-chosen and may have semantic meaning the user prefers not to leak (e.g., "topic-x-grant-application").
- **Proposed fix:** Add to the preview response headers:
  ```python
  headers={
      "Content-Security-Policy": CONTENT_SECURITY_POLICY_PREVIEW.decode("ascii"),
      "Referrer-Policy": "no-referrer",
  },
  ```
- **Regression guard:** Add an assertion in `test_returns_html_with_tight_csp`: `assert r.headers["referrer-policy"] == "no-referrer"`.

### F8 — `notebook_dir(slug)` is called twice on the preview path (once in helper, once in containment guard) — duplicates the symlink stat without functional benefit

- **Severity:** LOW
- **Source:** adversary
- **File:** `server/routes/ui.py:271` (the `notebook_dir(slug)` call inside the containment-check block)
- **What:** `_preview_html_path()` already calls `notebook_dir(slug)` (line 95). The containment check then calls `notebook_dir(slug)` AGAIN (line 271) to recompute the allowed-prefix base. This duplicates the symlink-existence stat and the `validate_slug` call. The CPU cost is negligible on loopback, but the duplicate slows down the negative path (every Preview link that 404s pays double stat cost). The functional outcome is identical because both calls reach the same resolved directory.
- **Why it matters:** Defensible micro-perf, but more importantly an opportunity to simplify: returning the resolved `nb_dir` from `_preview_html_path` would let the caller use it directly without re-validating.
- **Proposed fix:** Have `_preview_html_path` return `tuple[Path, Path] | None` — the HTML path and the allowed-prefix base. The caller then uses the returned base directly. ~10 LOC of restructuring; defer if not cheap.
- **Regression guard:** Existing search-order tests cover the refactor.

### F9 — `_paper_row_html` interpolates `slug` and `paper_id` into the URL with `html.escape` but no URL-encoding

- **Severity:** LOW
- **Source:** adversary
- **File:** `server/routes/notebooks.py:693-696` (the `preview_url` construction)
- **What:** The upload-fragment helper does:
  ```python
  preview_url = (
      f"/ui/notebooks/{html.escape(slug)}/papers/"
      f"{html.escape(paper_id)}/preview"
  )
  ```
  `html.escape` is the correct defense for HTML-attribute-context interpolation. But the URL itself is not URL-encoded. Both inputs are regex-validated upstream so neither contains `?`, `#`, `%`, or other reserved chars — the result happens to be a valid URL today. If a future regex relaxation (e.g., to support paper title slugs in the URL) introduces a reserved character, this site would silently produce a broken URL. Defense-in-depth would `urllib.parse.quote(slug, safe='')` + `urllib.parse.quote(paper_id, safe='/')` (allow `/` for old-style IDs).
- **Why it matters:** Forward-compatibility / future-regression gap. Not exploitable today.
- **Proposed fix:** Wrap both interpolations in `urllib.parse.quote(...)`. ~5 LOC.
- **Regression guard:** Not required for v2 m10.

## What was done well

- The synthesis A3 catch (CSP3 non-fetch directives don't fall back to `default-src`) is correctly addressed — `base-uri`, `form-action`, `frame-ancestors` are all named explicitly. This is a real and load-bearing security improvement over the roadmap brief.
- The triple-defense path-validation chain is correctly implemented: `validate_slug` → `is_valid_paper_id` → `notebook_dir` (m6 symlink rejection) → resolved-prefix check. Each layer fires before any `read_bytes()` call.
- The CSP override mechanism uses the middleware's existing idempotency check (`b"content-security-policy" not in existing`) — no middleware change needed, verified by `test_csp_overrides_middleware_ui_csp`.
- Module-level `bytes` constant for `CONTENT_SECURITY_POLICY_PREVIEW` preserves byte-stability discipline for future cache-related work.
- Race between `is_file()` and `read_bytes()` is correctly handled with an `OSError` catch that surfaces a generic 404 (no path-leak in the response body).
- Generic 404 responses ("no preview available") don't leak filesystem paths or distinguish between "file missing", "containment failed", and "OS error" — appropriate for a security-sensitive endpoint.
- The `target="_blank" rel="noopener"` on browse-table Preview links correctly prevents `window.opener` access in the new tab.
- The deleted `tests/test_m9_scope_invariants.py` was correctly removed — it was a "do not anticipate m10" guard that has served its boundary purpose.
- HTML magic-byte sniffing in the m8 upload handler (still in force) is a complementary defense that constrains what can land in the served HTML in the first place.
- The implementation honored the synthesis A1 search order (notebook-scoped first, corpus-global fallback) and the deviation from the brief's HTML-path was correctly handled.
- 20 new tests, including positive and negative paths, parametrized malformed-input rejection, and conditional template rendering.

## Recommended rectification order

1. **F2** — fix the false-negative path-traversal test FIRST. This is the single most load-bearing security regression guard; if it doesn't actually exercise the validator, every other defense becomes fragile to refactor.
2. **F1** — strip meta-refresh tags from served HTML (or document the residual risk explicitly in the implementation summary if accepting). Either approach closes the navigation-escape gap.
3. **F3** — tighten the parametrized malformed-input status-code assertion to `in (404, 422)` instead of `!= 200`. Cheap; closes the silent-5xx-acceptance gap.
4. **F4** — add CSP-header assertion to the two old-style-paper-id tests. One line each.
5. **F7** — add `Referrer-Policy: no-referrer` to the preview response headers. Pairs naturally with F1's mitigation since both address the navigation-escape information leak.
6. **F6** — update the tooltip text to be actionable. UX-only, but cheap and aligned with the AC's intent.
7. **F5** — consider downgrading the path-containment warning log; defensive only.
8. **F8**, **F9** — defer unless rectification touches the surrounding code.

## Rectification status (filled by Phase 4)

<!-- Phase 4 appends one bullet per finding; do not pre-populate -->
