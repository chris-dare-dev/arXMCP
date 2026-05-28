# Critique — textbook-ingest-m10

**Critic:** adversary
**Generated:** 2026-05-28T00:00:00Z
**Commit range:** ca95ccb1878eb348119718a213b76b7cbbe014c2..ce74e618aa423d5bc4555ae6728adf7d381f93e8
**Verdict:** SHIP-WITH-FIXES

## Executive summary

- SHIP-WITH-FIXES: the honest-descope is sound — the 200 MB textbook / 10 MB arxiv carve-out genuinely shipped in m4 and is correctly cited — but the doc-finalization pass left two real inaccuracies inside the very code block the implementer was editing.
- Finding counts: 0 CRITICAL, 0 HIGH, 3 MEDIUM, 2 LOW.
- Highest-risk artifact: `.claude/docs/security-pdf-sandbox.md:262-266` — the page-count snippet still documents a non-existent `_pdf_page_count(pdf_path: Path)` PyMuPDF probe; the real gate is a `/Count` byte-regex (`server/routes/notebooks.py:636`). This is the exact "doc says X, code does Y" drift the milestone's outcome was meant to close.
- The new `TestUploadPathContentLengthGuards` is correctly constructed and genuinely proves the malformed/negative-C-L 400 fires on the upload path under the 200 MB carve-out (verified: 2/2 pass; mirrors the proven `test_security.py` header-override pattern).
- The AC names "missing content-length"; the test + its docstring claim to close "malformed/missing content-length edge cases" but only malformed + negative are asserted. "missing" is a benign pass-through, not a guard — but the asserted-not-tested gap should be corrected (F3).
- Cache byte-stability: CLEAN — no `server/tools.py`, no `ALL_TOOLS`, no schema/BP1 touch (diff is doc + test only). No re-pin needed, correctly.
- No-fork / banned-patterns / local-first / MCP-spec axes: CLEAN or N/A for a doc+test diff (details below).
- Tier sequencing: CLEAN — the m4 attribution in the summary + doc is accurate; m4 really did build `prefix_caps` (200 MB) and `_ARXIV_UPLOAD_MAX_BYTES` (10 MB) with tests, verified against current code.

## Severity calibration

| level | meaning | rectification phase action |
|---|---|---|
| CRITICAL | data loss, security regression, broken core invariant, or shippable-bug-in-production-now | always fix in Phase 4 |
| HIGH | wrong behavior reachable on common path, or load-bearing constraint violated | always fix in Phase 4 |
| MEDIUM | subtle correctness, missing test, latent foot-gun | fix only if cheap (≤ 30 LOC, small test surface) |
| LOW | style, naming, micro-perf | defer (record under `deferred_findings`) |

## Findings

### F1 — Page-count doc snippet still documents a non-existent PyMuPDF probe

- **Severity:** MEDIUM
- **Source:** adversary
- **File:** `.claude/docs/security-pdf-sandbox.md:262-266`
- **What:** The `## Pre-flight gate at the upload route` code block documents `def _pdf_page_count(pdf_path: Path) -> int:` with the body "Uses PyMuPDF's metadata-only mode (does NOT decode page content)." The actual code is `_pdf_declared_page_count(pdf_bytes: bytes) -> int` (`server/routes/notebooks.py:636`) which runs `_PDF_COUNT_RE.findall(pdf_bytes)` over the raw bytes — no PyMuPDF, no Path, no metadata mode. The function name, signature, input type, AND mechanism are all wrong.
- **Why it matters:** The milestone's stated outcome is "finalize `security-pdf-sandbox.md` to match built code." The implementer fixed the JS snippet immediately above (lines 222-243) but left the page-count snippet in the SAME edited code block stale. This contradicts the doc's own "Caps enforced" bullet (line 295: "≤ 5000 declared in any `/Count <int>` PDF token") — the doc is now internally inconsistent. A future implementer reading the snippet would believe page-count uses a PyMuPDF metadata probe and could "fix" the regex toward PyMuPDF, introducing a hard dependency the design deliberately avoids. This is the m4-F2 stale-docstring anti-pattern the doc itself warns about (line 93).
- **Proposed fix:** In `.claude/docs/security-pdf-sandbox.md:262-266` replace the `_pdf_page_count(pdf_path: Path)` snippet with the real signature + mechanism, e.g.:
  ```python
  def _pdf_declared_page_count(pdf_bytes: bytes) -> int:
      """Return the highest /Count integer in the PDF byte stream
      (regex byte-scan via _PDF_COUNT_RE; no PyMuPDF). 0 if absent.
      Adversarial /Count-0-with-huge-Page-Tree slips past; m5's
      wall-clock timeout is the runtime backstop."""
      ...
  ```
- **Regression guard:** Add a doc-consistency assertion in `tests/test_pdf_preflight.py` that the symbol named in the doc snippet exists in `server.routes.notebooks` — e.g. assert `hasattr(notebooks_module, "_pdf_declared_page_count")` AND `not hasattr(notebooks_module, "_pdf_page_count")`. Pins the doc-to-code symbol contract so the next drift trips a test.

### F2 — Threat-table JS row undercounts the detection set (2 of 7 tokens)

- **Severity:** MEDIUM
- **Source:** adversary
- **File:** `.claude/docs/security-pdf-sandbox.md:55`
- **What:** The "Embedded JavaScript in PDF" threat-table row says the pre-flight check "reject[s] any PDF with `/JS` or `/JavaScript` entries." The actual gate (`tools/security/pdfid.py:68-78`, `find_javascript`) detects a 7-token set: `/JS`, `/JavaScript`, `/OpenAction`, `/AA`, `/Launch`, `/SubmitForm`, `/ImportData`. The doc's own "Caps enforced" bullet (lines 291-294) correctly states "a 7-token detection set (NOT 4)" — so the threat table contradicts the same document.
- **Why it matters:** This is the top-of-document threat-surface table — the first artifact an auditor reads. Understating the defense to 2 tokens mis-documents the actual coverage of `/OpenAction` / `/AA` / `/Launch` / `/SubmitForm` / `/ImportData` (auto-open + launch + form-exfil vectors). The milestone explicitly scoped "Finalize the doc to match the now-built hardening," and the brief's verification note (i) calls out the JS-detection accuracy pass specifically. Leaving the headline table at 2 tokens is an under-delivery of the doc-accuracy outcome.
- **Proposed fix:** In `.claude/docs/security-pdf-sandbox.md:55` change "reject any PDF with `/JS` or `/JavaScript` entries" to "reject any PDF containing any of the 7 active-content tokens (`/JS`, `/JavaScript`, `/OpenAction`, `/AA`, `/Launch`, `/SubmitForm`, `/ImportData` — canonical list at `tools/security/pdfid.py::DANGEROUS_PDF_NAMES`)."
- **Regression guard:** Extend the existing `TestPdfFindJavascriptGate` (or add a doc check) asserting the doc threat-table row enumerates the full `DANGEROUS_PDF_NAMES` set, or at minimum assert `len(DANGEROUS_PDF_NAMES) == 7` co-located with a comment pointing at the doc row so a future token addition forces a doc update.

### F3 — "missing content-length" AC case is asserted-as-covered but not tested

- **Severity:** MEDIUM
- **Source:** adversary
- **File:** `tests/test_pdf_preflight.py:683` (docstring) / `tests/test_pdf_preflight.py:714-740` (the two tests)
- **What:** The AC names "malformed/missing content-length edge cases." `TestUploadPathContentLengthGuards`'s docstring claims to close "the AC's 'malformed/missing content-length edge cases the middleware already guards' requirement," but only `test_malformed_content_length_rejected_400` and `test_negative_content_length_rejected_400` exist — no test for the "missing" case. In the middleware (`server/middleware.py:899`), a missing Content-Length means `content_length_b is None`, so the C-L block is skipped and the request falls through to the eager pre-read path (capped at the effective 200 MB). That is benign pass-through behavior, NOT a 400 guard — so "missing" is correctly handled, but the docstring overclaims test coverage of it.
- **Why it matters:** This is the named honest-descope risk: an "already covered" claim that papers over a genuine gap between what the AC enumerates and what the test asserts. The behavior is safe (no security hole), so this is MEDIUM not HIGH — but the docstring asserts a coverage claim the test body does not back, which is exactly the kind of drift this critique exists to catch.
- **Proposed fix:** Either (a) add `test_missing_content_length_passes_to_route` posting to the upload path with NO Content-Length header (chunked/streaming) and assert it reaches the route (e.g. 4xx from form-parsing / handler, NOT a middleware 400), pinning the pass-through contract; OR (b) if no test is added, edit the docstring (`tests/test_pdf_preflight.py:683`) to claim only "malformed/negative content-length" and explicitly note that "missing C-L is a benign pass-through, not a rejection." Option (a) is preferred — it closes the AC literally and is ≤ 15 LOC.
- **Regression guard:** The new `test_missing_content_length_passes_to_route` IS the regression guard — it locks that a missing C-L does not spuriously 400 and does reach the handler under the 200 MB carve-out.

### F4 — Garbled milestone attribution "the m6 m8 upload's"

- **Severity:** LOW
- **Source:** adversary
- **File:** `.claude/docs/security-pdf-sandbox.md:55`
- **What:** The JS threat row reads "Mirrors the m6 m8 upload's magic-byte sniff pattern" — "m6 m8" is two milestone tokens jammed together, ambiguous about which milestone introduced the magic-byte sniff (m8 shipped the ar5iv HTML magic-byte sniff; m4 shipped the PDF preflight).
- **Why it matters:** Minor, but it is in the same threat-table row F2 already flags, so it can be corrected in the same edit. Ambiguous milestone attribution erodes the doc's value as an audit trail.
- **Proposed fix:** In `.claude/docs/security-pdf-sandbox.md:55` change "the m6 m8 upload's magic-byte sniff pattern" to "the m8 ar5iv upload's magic-byte sniff pattern" (or "the m4 PDF preflight's magic-byte sniff").
- **Regression guard:** None required (LOW; prose-only).

### F5 — Decompression-bomb threat row omits the macOS RLIMIT_AS caveat

- **Severity:** LOW
- **Source:** adversary
- **File:** `.claude/docs/security-pdf-sandbox.md:57`
- **What:** The "Decompression bombs in stream filters" threat row states the mitigation as "`subprocess.Popen` hard memory cap via `RLIMIT_AS` (POSIX) ... 4 GB virtual memory ceiling" with no inline note that RLIMIT_AS is non-functional on macOS. The doc DOES cover the Darwin gap exhaustively later (lines 113-120, 360-376, 483-491) and the code is correctly Linux-gated (`ingest/textbook_parser.py:125`), so this is not a correctness miss — but the threat table presents RLIMIT_AS as the unqualified mitigation while the "Caps enforced" + resolved-questions sections qualify it heavily.
- **Why it matters:** The "(POSIX)" parenthetical is slightly misleading — Darwin is POSIX but does NOT enforce RLIMIT_AS (the doc's own resolved-question #4 confirms `ValueError` on Darwin). A reader scanning only the threat table would over-trust the memory cap on macOS dev workflows. LOW because the gap is documented three other places in the same file.
- **Proposed fix:** In `.claude/docs/security-pdf-sandbox.md:57` append "(Linux only — non-functional on macOS, see resolved-question #4; the 30-min wall timeout is the macOS backstop)" to the mitigation cell. Optional given the milestone's narrow doc-fix scope; bundle only if F1/F2 are already being edited.
- **Regression guard:** None required (LOW; prose-only).

## What was done well

- Correct honest-descope: both researchers independently found the carve-out shipped in m4, and the implementer did NOT re-implement it — avoiding the churn of rebuilding working, tested code. The same disciplined posture as m8.
- The m4 attribution is verifiably accurate: `server/main.py:548-549` sets `prefix_caps={"/ui/api/notebooks": 200 * 1024 * 1024}` and `server/routes/notebooks.py:540` defines `_ARXIV_UPLOAD_MAX_BYTES = 10 MB` with the per-kind handler check at line 824 — exactly as the summary claims.
- The JS-snippet doc fix (lines 222-243) is correct and complete: it now matches `find_javascript(pdf_bytes: bytes) -> list[str]` (`tools/security/pdfid.py:102`), documents the `_pdf_find_javascript` import alias and the `_run_pdf_preflight(content)` bytes-not-Path call site, and the truthiness-check usage — all verified against `server/routes/notebooks.py:66,682`.
- The cap-attribution doc fix (threat row line 62) is accurate: two-tier 200 MB envelope + 10 MB arxiv handler cap, with a correct cross-reference to the "Caps enforced" section and the accepted memory-pressure caveat.
- `TestUploadPathContentLengthGuards` is genuinely load-bearing: it mounts the real `RequestBodySizeLimitMiddleware` with the production 200 MB prefix cap, so the 400 demonstrably comes from the middleware (the bare `client` fixture has no middleware) — verified 2/2 passing.
- The new test correctly targets the upload PATH specifically (`/ui/api/notebooks/demo-nb/papers/upload`), and the prefix-match (`startswith("/ui/api/notebooks/")`) genuinely covers it — proving the carve-out path still inherits the smuggling-signal guard.
- Cache discipline respected: no `server/tools.py` / `ALL_TOOLS` / schema / BP1 touch, so the "no re-pin" claim is correct and the byte-stable `tools/list` is untouched.
- Banned-pattern hygiene: no `assert` for invariants in production code (the test-file asserts are pytest-context, allowed); no `BaseHTTPMiddleware`; pure-ASGI preserved; no new `.md` outside `.claude/`; no fork; no `0.0.0.0`; `KMP_DUPLICATE_LIB_OK` untouched.
- The stale future-tense header fix ("e2 will land these" → "shipped in textbook-ingest-m4/m5") with an accurate `requires_mineru` marker pointer is correct — verified the marker exists in `pyproject.toml:214`.
- Tests pass clean (38/38 in `tests/test_pdf_preflight.py`) and `ruff check` is clean on the changed test file.

## Recommended rectification order

1. F1 (page-count doc snippet) — highest leverage: it is the most actively misleading inaccuracy, sits in the code block the implementer already edited, and contradicts the doc's own "Caps enforced" bullet. Fix the snippet + add the symbol-contract regression guard.
2. F3 (missing-C-L AC case) — close the AC literally with a ~15-LOC pass-through test, or correct the overclaiming docstring. Either way removes the asserted-not-tested gap.
3. F2 (threat-table JS undercount) — single-line edit; bundle the F4 "m6 m8" typo into the same line.
4. F4 + F5 (LOW prose fixes) — fold into the F2 edit if already touching that threat-table region; otherwise defer.

## Rectification status

<!-- Phase 4 appends one bullet per finding; do not pre-populate -->
