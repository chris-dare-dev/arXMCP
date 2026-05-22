# Critique — proof-verify-handler-wiring-m10 (merged)

**Critics fired:** adversary (1; infra-safety / oss-scout did not fire
— no infra paths in diff, no OSS-scout opt-in).

**Verdict:** SHIP-WITH-FIXES (adversary).

## Findings summary

| ID | Sev | Source | Title | Phase-4 status |
|---|---|---|---|---|
| F1 | HIGH | adversary | `<meta http-equiv="refresh">` is a navigation escape no CSP3 directive blocks | CLOSED — added `_META_REFRESH_RE` regex strip in `server/routes/ui.py` before constructing the preview response. The substituted comment `<!-- meta-refresh stripped (m10 F1) -->` is operator-visible. Regression test: `TestMetaRefreshStripped::test_meta_refresh_stripped_from_served_html` (4 parametrized variants) + `test_legit_meta_tags_are_preserved` (charset / viewport / og:title survive) |
| F2 | HIGH | adversary | Path-traversal test is a false negative; httpx normalizes the URL before send | CLOSED — replaced literal `papers/../etc/preview` with URL-encoded `papers/..%2Fetc%2Fpasswd/preview` so httpx leaves the traversal intact through wire transmission. Now `is_valid_paper_id` actually rejects (asserted `status_code == 422`). Added `test_is_valid_paper_id_rejects_traversal_directly` as a route-independent unit test pinning the validator contract to 5 traversal inputs |
| F3 | MEDIUM | adversary | `test_rejects_malformed_paper_id` accepts overly broad status codes (5xx silently passes) | CLOSED — tightened assertion from `!= 200` to `in (404, 422)`. A future regression that crashes the validator with an unhandled exception would now surface as a test failure instead of silently passing |
| F4 | MEDIUM | adversary | Happy-path CSP assertion only covers new-style paper_id; old-style untested | CLOSED — added exact-bytes CSP assertion to `test_old_style_paper_id_corpus_fallback` AND `test_old_style_paper_id_notebook_scoped`. The math-ph / hep-th category is the very kind of paper this server is built for; the CSP boundary now provably holds for those IDs through both search-order paths |
| F5 | MEDIUM | adversary | Logging the rejected slug/paper_id at WARNING gives an oracle for filesystem-symlink attackers | CLOSED — `logger.warning` no longer includes the slug or paper_id. Log message is now `"preview path-containment rejected (validated inputs)"`. Both inputs are validated upstream so they can't corrupt log files even if logged, but removing them eliminates the side-channel oracle entirely. Inputs are still recoverable from a correlated access-log entry if forensics need them |
| F6 | MEDIUM | adversary | "no preview available" tooltip is a UX cliff with no next-action hint | CLOSED — updated tooltip text to `"upload an ar5iv HTML to enable preview"`. Operator now sees an actionable hint pointing at the upload card on the same page. Test assertion updated to match |
| F7 | MEDIUM | adversary | Missing `Referrer-Policy: no-referrer` on preview response leaks slug to navigated-to attacker site | CLOSED — added `"Referrer-Policy": "no-referrer"` to the preview response headers alongside the CSP. Defense-in-depth pairing with F1's meta-refresh strip (both address navigation-escape information leaks). Regression test: `test_response_includes_referrer_policy_no_referrer` |
| F8 | LOW | adversary | `notebook_dir(slug)` called twice on the preview path (helper + containment guard) — duplicate symlink stat | **DEFERRED** — micro-perf; the duplicate stat is negligible on loopback. The proposed refactor (`_preview_html_path` returns `tuple[Path, Path]`) would touch the helper's signature and 3 call sites. Defer unless rectification touches surrounding code |
| F9 | LOW | adversary | `_paper_row_html` interpolates slug/paper_id without URL-encoding (defensible today; brittle if regex relaxes) | **DEFERRED** — forward-compat gap only. Both inputs are validated upstream against the arXiv-ID + slug regexes, neither of which permits URL-reserved characters. A future regex relaxation that introduced one would surface as a broken-link bug long before becoming a security issue. Defer to a future cleanup pass |

## Rectification artifacts

- `server/routes/ui.py`:
  - Added module-scope `import re` and `_META_REFRESH_RE` pattern.
    **F1 closure.**
  - Handler now applies `_META_REFRESH_RE.sub(...)` to
    `content_bytes` before constructing the Response.
    **F1 closure.**
  - Response headers extended with `"Referrer-Policy": "no-referrer"`.
    **F7 closure.**
  - Path-containment `logger.warning` no longer includes slug or
    paper_id. **F5 closure.**
- `frontend/templates/notebook_detail.html`:
  - Updated `<span class="hint">` tooltip text to actionable
    "upload an ar5iv HTML to enable preview". **F6 closure.**
- `tests/test_preview_route.py`:
  - **F2 closure** — replaced the false-negative
    `test_traversal_attempt_returns_safe_status` with
    `test_traversal_attempt_returns_422_via_validator` using
    URL-encoded traversal (`..%2Fetc%2Fpasswd`).
  - **F2 closure** — added
    `test_is_valid_paper_id_rejects_traversal_directly` (route-
    independent validator probe over 5 traversal inputs).
  - **F3 closure** — tightened
    `test_rejects_malformed_paper_id` assertion from `!= 200` to
    `in (404, 422)` and switched filesystem-leak guards from
    user-input echoing (`/etc/`, `passwd`) to server-side prefixes
    (`/var/arxmcp/`, `notebooks/demo-nb/ar5iv/`).
  - **F4 closure** — added exact-bytes CSP assertion to BOTH
    `test_old_style_paper_id_corpus_fallback` and
    `test_old_style_paper_id_notebook_scoped`.
  - **F1 regression guard** —
    `TestMetaRefreshStripped::test_meta_refresh_stripped_from_served_html`
    (4 parametrized meta-refresh variants) +
    `test_legit_meta_tags_are_preserved` (3 legit meta tags
    survive intact).
  - **F7 regression guard** —
    `test_response_includes_referrer_policy_no_referrer`.
  - **F6 regression guard** — updated
    `test_preview_tooltip_when_html_absent` to assert the new
    tooltip text.

## Final test count

`make test`: **2491 passed** (+7 from m10-impl's 2484; +26 vs m9's
2465). The +7 breakdown: 4 meta-refresh parametrized variants + 1
legit-meta-survives + 1 referrer-policy + 1 validator-direct
traversal probe. 9 skipped (unchanged), 1 xfailed (unchanged). Ruff
clean.

## Deferred findings

- **F8 (LOW)** — duplicate `notebook_dir(slug)` stat on the preview
  path. Micro-perf only; loopback-only deployment makes it negligible.
  The proposed `_preview_html_path -> tuple[Path, Path]` refactor
  would touch the helper signature + 3 call sites. Defer to a future
  cleanup pass.
- **F9 (LOW)** — `_paper_row_html` URL interpolation uses
  `html.escape` but not `urllib.parse.quote`. Defensible today (both
  inputs are validated against arXiv-ID + slug regexes that exclude
  URL-reserved characters). Would only surface as a broken-link bug
  if a future regex relaxation introduced reserved characters. Defer.

## Re-verify gate notes

Both HIGH findings re-verified empirically before fixing:

- **F1** (HIGH): confirmed CSP3 has no directive that blocks
  `<meta http-equiv="refresh">` — the proposed `navigate-to`
  directive never made it to CSP3 baseline. The `<iframe sandbox>`
  attribute in the rejected Option A would have blocked it via
  HTML5 §16.2; the chosen direct-serve route has no equivalent.
  Validated the regex strip against 4 attribute-order/case
  variants — all match correctly; `<meta charset="utf-8">` and
  other legit tags do NOT match.
- **F2** (HIGH): confirmed empirically that
  `httpx.URL("http://test/u/notebooks/demo-nb/papers/../etc/preview").raw_path`
  returns `b'/u/notebooks/demo-nb/etc/preview'` — the literal
  `../` is dropped before the URL hits the test client's transport.
  The fix uses `%2F` encoding which httpx leaves intact through
  wire transmission, so `{paper_id:path}` delivers
  `..%2Fetc%2Fpasswd` to the handler (FastAPI decodes it back to
  `../etc/passwd` post-routing, where `is_valid_paper_id` then
  rejects it).

Zero findings invalidated. Adversary invalidation rate: **0 / 2
(0%)** for HIGH+CRITICAL; well under the 40% threshold.

## Cross-critic agreement

N/A — only one critic fired (adversary). No infra paths in diff so
infra-safety didn't fire; OSS-scout is opt-in only and the user
didn't request it.
