# Critique — textbook-ingest-m4

**Critic:** adversary
**Generated:** 2026-05-27T00:00:00+00:00
**Commit range:** 474db59..4d99e31
**Verdict:** SHIP-WITH-FIXES

## Executive summary

- SHIP-WITH-FIXES — the 5-vector gate is byte-correct and the no-fork
  discipline is sound, but the per-kind upload cap mechanism documented
  in the synthesis is factually wrong about its DoS bound, and the
  polyglot doc is materially out of date.
- 0 CRITICAL, 2 HIGH, 4 MEDIUM, 2 LOW. Highest-risk finding lives in
  `server/routes/notebooks.py:771-798` (cap-after-read DoS amplifier).
- The synthesis D3 claim that "non-PDF magic bytes fail at 5-byte
  read for any kind" is false: `await file.read()` reads the FULL
  body BEFORE the magic-byte sniff runs.
- `.claude/docs/security-pdf-sandbox.md` was authored against a
  4-byte (`%PDF`) sniff, a 4-token JS list, and `<HTML>` (opening
  uppercase) — m4 ships a 5-byte (`%PDF-`) sniff, 7 tokens, and
  `</html>` / `</body>` (closing, lowercased). Doc not updated in
  lockstep — operator-facing security claims diverge from the code.
- AC #5 acceptance is only PARTIALLY exercised in tests: the >200 MB
  middleware-envelope rejection (the "250 MB textbook → 413" claim in
  the impl summary) is never exercised. The arxiv-cap-bypass-for-
  textbook case is exercised at 10 MB+1 KB rather than the 150 MB
  point in the AC.
- `_POLYGLOT_TAIL_MARKERS` lists `</body>` as a third marker, but no
  test exercises rejection on that marker — the marker is essentially
  dead-code in the test surface.
- pdfid.py JS-token backstop claim ("m5 catches compressed-stream JS")
  is overstated: m5's RLIMIT_AS sandbox bounds resource consumption,
  not malicious JS execution. The real backstop is "PyMuPDF doesn't
  execute JS" per the security-pdf-sandbox.md table.
- "What was done well" section populated with 8 bullets — see below.

## Severity calibration

| level | meaning | rectification phase action |
|---|---|---|
| CRITICAL | data loss, security regression, broken core invariant, or shippable-bug-in-production-now | always fix in Phase 4 |
| HIGH | wrong behavior reachable on common path, or load-bearing constraint violated | always fix in Phase 4 |
| MEDIUM | subtle correctness, missing test, latent foot-gun | fix only if cheap (≤ 30 LOC, small test surface) |
| LOW | style, naming, micro-perf | defer (record under `deferred_findings`) |

## Findings

### F1 — DoS bound argument in synthesis D3 is factually wrong

- **Severity:** HIGH
- **Source:** adversary
- **File:** server/routes/notebooks.py:771-798
- **What:** The synthesis D3 claim — "for a non-PDF body uploaded to
  ANY notebook kind, the magic-byte sniff fires at 5 bytes (HTTP 415)
  before the 200 MB buffer is exhausted" — is contradicted by the
  implementation. Line 771 `content = await file.read()` reads the
  ENTIRE body into memory BEFORE any per-kind check or magic-byte
  sniff runs. For an arxiv-kind notebook receiving a 200 MB body, the
  full 200 MB is buffered TWICE (once in
  `RequestBodySizeLimitMiddleware`'s eager-read `buffered_events`
  list at `server/middleware.py:968-1004`, once in the handler's
  `content` variable) before the 10 MB cap fires at line 788. This is
  a 20× memory-pressure regression vs the pre-m4 path, which rejected
  at the middleware envelope when it was 10 MB.
- **Why it matters:** The DoS-bound argument is load-bearing for the
  synthesis D3 design decision. The fact that it's wrong means the
  cost-benefit analysis that justified raising the middleware envelope
  from 10 MB to 200 MB is built on a false premise. The implementation
  summary at `.claude/notes/milestones/textbook-ingest-m4/
  implementation-summary.md:209-212` repeats the same wrong claim,
  and the route-handler comment at `server/main.py:508-512` enshrines
  it in the production code. In the local-first / loopback-only
  threat model this is a resource-pressure regression rather than a
  remote-exploit vector — but the synthesis explicitly leaned on the
  argument to justify the design tradeoff.
- **Proposed fix:** Move the per-kind cap check to fire on
  `content-length` (when declared) or via a streaming read with
  early-abort. Concretely: add a per-kind cap argument to
  `RequestBodySizeLimitMiddleware.prefix_caps` (a dict keyed by
  `(prefix, notebook_kind)` OR a callable that resolves the cap from
  scope state). Alternative cheaper fix: keep the 200 MB middleware
  envelope but add an explicit content-length check at the TOP of the
  handler (before `file.read()`) that rejects arxiv-kind uploads
  declaring >10 MB. Update the comments in both `server/main.py:508-512`
  and `server/routes/notebooks.py:784-787` to match reality.
- **Regression guard:** Add a test that asserts the handler-level cap
  fires WITHOUT buffering the full body — e.g. send a Content-Length
  declaring 50 MB to an arxiv-kind notebook and verify rejection
  happens before the body is consumed (use a TestClient instrumented
  to detect partial-read behavior, or assert the rejection happens
  fast enough that 50 MB couldn't have been read).

### F2 — Pre-flight gate documentation diverged from implementation

- **Severity:** HIGH
- **Source:** adversary
- **File:** .claude/docs/security-pdf-sandbox.md:36 + 173-199
- **What:** The PDF sandbox security doc states (line 36): "first 4
  bytes must be `%PDF`". The implementation enforces 5 bytes
  (`%PDF-`) per `server/routes/notebooks.py:576`. The doc lists the
  dangerous tokens as 4 (`/JS`, `/JavaScript`, `/OpenAction`, `/AA`)
  at line 213; the implementation has 7 tokens including `/Launch`,
  `/SubmitForm`, `/ImportData`. The doc's polyglot marker tuple
  (line 194) includes `<HTML>` (opening tag, uppercase); the
  implementation uses `</html>` and `</body>` (closing tags,
  lowercased). The doc was authored in the spike commit (474db59)
  and was NOT updated as part of m4.
- **Why it matters:** This is the OPERATOR-FACING security
  documentation. An operator reading it gets wrong byte counts, a
  wrong token list, and wrong marker patterns. If an operator audits
  the security claims (e.g. for compliance, or to vet a textbook
  upload pipeline), the doc and the code disagree — which is the
  textbook m3 finding from this critic's own memory:
  "On any coordinated milestone that edits a description to document
  widened acceptance, verify the matching validator was widened in
  lockstep." Same shape — m4 widened the implementation but the doc
  wasn't moved with it.
- **Proposed fix:** Update `.claude/docs/security-pdf-sandbox.md`
  lines 36 (4 bytes → 5 bytes; `%PDF` → `%PDF-`), 173-200 (replace
  the `_pdf_polyglot_check` stub with the canonical implementation
  shape), 213 (4 tokens → 7 tokens; cite `DANGEROUS_PDF_NAMES`
  frozenset). Add a note that the SHIPPED implementation is the
  source of truth and this doc is a design contract that has been
  realized.
- **Regression guard:** Add a test that greps the doc for `"%PDF-"`
  and `"5 bytes"` and `"7 tokens"` (or the equivalent), asserting
  the operator-facing claims match the implementation. Pattern
  mirrors `tests/test_doc_layout.py`-style structural locks.

### F3 — Missing test for `</body>` polyglot marker

- **Severity:** MEDIUM
- **Source:** adversary
- **File:** tests/test_pdf_preflight.py:192-264 (no test exercises `</body>`)
- **What:** `_POLYGLOT_TAIL_MARKERS` at
  `server/routes/notebooks.py:548-552` declares three markers:
  `b"PK\x05\x06"`, `b"</html>"`, `b"</body>"`. The
  `TestPdfPolyglotCheck` class has tests for `PK\x05\x06`, `</html>`,
  and uppercase `</HTML>`. There is NO test that exercises the
  `</body>` marker (lowercase OR mixed case). The third marker is
  effectively un-load-bearing — if a regression removed it, no test
  would notice.
- **Why it matters:** This is the second-most-common HTML polyglot
  pattern (a PDF that's also a partial HTML file ending in `</body>`
  without the outer `</html>`). The marker was added per the inline
  comment "defense-in-depth for partial-HTML polyglots". If it's
  worth shipping it's worth a test.
- **Proposed fix:** Add `test_pdf_body_polyglot_rejected` to
  `TestPdfPolyglotCheck` mirroring `test_pdf_html_polyglot_rejected`
  but with `tail_marker=b"</body>"`.
- **Regression guard:** The new test IS the regression guard.

### F4 — AC #5 (>200 MB middleware envelope) is not exercised by any test

- **Severity:** MEDIUM
- **Source:** adversary
- **File:** tests/test_pdf_preflight.py:344-399 (`TestUploadCapPerKind`)
- **What:** The AC #5 row in the brief says: "150 MB upload to
  textbook notebook succeeds; 250 MB → 413". The implementation
  summary at lines 30-34 repeats this verbatim. The actual tests use
  `_ARXIV_UPLOAD_MAX_BYTES + 1024` (~10 MB + 1 KB) as the "over
  arxiv cap" body for the textbook-bypass case (line 393), and
  there is NO test that exercises a >200 MB body against either
  notebook kind. The middleware envelope rejection (250 MB → 413) is
  asserted in the AC but only enforced by `RequestBodySizeLimitMiddleware`
  via its `prefix_caps["/ui/api/notebooks"] = 200 MB` setting — a
  regression that lowered or removed that cap would not be caught
  by m4's tests.
- **Why it matters:** Half the AC #5 acceptance contract is
  un-verified. If a future m5+ rectification changes the middleware
  config (e.g. m5 moves the cap to the route handler), the >200 MB
  case silently regresses.
- **Proposed fix:** Add `test_textbook_body_over_envelope_rejected_413`
  to `TestUploadCapPerKind` that asserts a 201 MB body → 413
  (middleware envelope). Adding a third test covering 150 MB
  acceptance is optional given memory cost but would close the AC
  exactly.
- **Regression guard:** The new test IS the regression guard.

### F5 — Backstop claim for compressed-stream evasion is overstated

- **Severity:** MEDIUM
- **Source:** adversary
- **File:** tools/security/pdfid.py:21-25
- **What:** The pdfid.py docstring says: "The textbook-ingest-m5
  MinerU subprocess sandbox is the backstop defense layer for
  compressed-stream / hex-encoded evasion; this module catches the
  common easy cases before MinerU is invoked." The m5 sandbox is the
  RLIMIT_AS + process-group-kill + wall-timeout discipline per
  `.claude/docs/security-pdf-sandbox.md` lines 79-150. That sandbox
  bounds resource consumption — it does NOT prevent
  embedded-JavaScript execution. The actual backstop for
  embedded-JS-in-compressed-stream is "PyMuPDF does not execute
  embedded JavaScript" (per the doc table at line 35). The pdfid.py
  docstring conflates "sandbox" (memory + timeout cap) with
  "non-execution semantics of PyMuPDF" (an unrelated property of the
  parser). An operator reading the docstring would conclude the
  sandbox is what prevents JS-execution risk; in fact PyMuPDF's
  non-evaluation IS the protection, and the sandbox just bounds
  damage if PyMuPDF mis-parses.
- **Why it matters:** Mis-attributed defense layers are the same
  shape as F2 — operator-facing security claim is not grounded in
  the actual mechanism. A future change that swaps PyMuPDF for a
  JS-capable parser (or adds a JS-capable post-processor) would
  silently lose the protection, because the documented backstop
  (sandbox) doesn't actually defend against JS-exec.
- **Proposed fix:** Rewrite `tools/security/pdfid.py:21-25` to
  attribute defense correctly: "Compressed-stream JS evasion is
  bounded by m5's sandbox (memory + timeout caps prevent runaway
  parsing) and by PyMuPDF's documented non-evaluation of embedded
  JavaScript (per `.claude/docs/security-pdf-sandbox.md` Table row 1).
  Hex-encoded name tokens are NOT detected at this layer; the
  same two backstops apply."
- **Regression guard:** Not strictly needed — this is a docstring
  fix. A unit-test-grade lock would assert the docstring contains
  the phrase "PyMuPDF" so a future swap surfaces here.

### F6 — `notebook_kind` lookup ordering moves DB call earlier without test

- **Severity:** MEDIUM
- **Source:** adversary
- **File:** server/routes/notebooks.py:730-761
- **What:** Pre-m4, the upload handler did paper_id-format validation
  BEFORE the SQLite `get_notebook` call. Post-m4, the paper_id
  validation depends on `notebook_kind`, so the DB call happens
  FIRST (line 734) and paper_id validation happens AFTER (lines
  747-761). This shifts a SQLite query earlier in the request flow:
  an attacker who knows valid slug values but supplies a
  syntactically-invalid paper_id (e.g. `paper_id="../../etc/passwd"`)
  now triggers a DB query before the validation rejects them. The
  slug regex (`tools/_notebook_common.validate_slug`) bounds this —
  only well-formed slugs reach the DB — but the new ordering is a
  subtle change in attack-surface ordering that has no test.
- **Why it matters:** Low actual risk (slug regex is the gating
  filter), but the new ordering is undocumented and untested. A
  future change that loosens the slug regex would convert this from
  "harmless" to "DoS amplifier on the SQLite-cache hot path."
- **Proposed fix:** Add a test
  `test_invalid_paper_id_with_valid_slug_does_not_query_db_twice`
  (or similar) that mocks the store's `get_notebook` and asserts
  it's called exactly once for an invalid-paper-id request — this
  locks the call ordering. Cheap (≤ 10 LOC).
- **Regression guard:** The new test.

### F7 — Page-count regex misses `/Count` separated by PDF comment

- **Severity:** LOW
- **Source:** adversary
- **File:** server/routes/notebooks.py:562 + 620-623
- **What:** `_PDF_COUNT_RE = re.compile(rb"/Count\s+(\d+)")` requires
  `\s+` between `/Count` and the integer. PDF syntax allows a `%`
  comment between any two tokens — e.g. `/Count % see footnote\n
  10000` is valid PDF. Python's `\s` matches space/tab/newline but
  NOT `%comment text\n`. So an adversary can hide a `/Count 10000`
  declaration from the regex by injecting a comment between
  `/Count` and the integer.
- **Why it matters:** Low-severity because (a) adversarial-PDF-with-
  embedded-comments is exotic; (b) the m5 wall-clock timeout
  backstops page-count-exhaustion (per docstring at line 562); (c)
  the page-count check is already documented as a "heuristic, not a
  full parser." Worth flagging because if the page-count gate
  becomes load-bearing later (e.g. m5 ships without a wall timeout),
  this evasion would matter.
- **Proposed fix:** Either tighten the regex to accept PDF comments
  (`(?:\s|%[^\n]*\n)+`) or explicitly document the limitation in the
  docstring at line 555-562. Tightening is ~5 LOC; documenting is
  ~3 LOC. Prefer documenting at this milestone — the page-count
  gate's role is bound-not-precise.
- **Regression guard:** A test
  `test_pdf_count_with_intervening_comment_misses` similar to
  `test_compressed_stream_js_misses` that LOCKS the limitation. ~10
  LOC.

### F8 — `_pdf_polyglot_check` defensive `_is_pdf_bytes` re-check raises 415 with confusing detail

- **Severity:** LOW
- **Source:** adversary
- **File:** server/routes/notebooks.py:592-597
- **What:** `_pdf_polyglot_check` includes a defensive `_is_pdf_bytes`
  re-check that raises HTTPException(415, "not a PDF (missing
  %PDF- header)"). This is unreachable in `_run_pdf_preflight` (the
  orchestrator already runs `_is_pdf_bytes` first at line 647) so
  the only way to hit this branch is to call `_pdf_polyglot_check`
  directly. Dead code on the production path; lives only for hand-
  testing. The detail message duplicates the earlier check's
  message with slightly different wording — if both fired (impossible
  today), an operator log would see two near-identical 415 detail
  strings.
- **Why it matters:** Pure defense-in-depth code is fine, but the
  duplicated wording is a future-debugging hazard. If a refactor
  removes the orchestrator-level check, the per-helper check
  surfaces a less-informative error.
- **Proposed fix:** Either remove the defensive re-check (the
  orchestrator is the only caller; keep the contract that callers
  invoke `_is_pdf_bytes` first), or change the detail message to
  signal it's a defensive belt-and-braces ("internal: polyglot check
  invoked without magic-byte sniff"). 2-3 LOC.

## What was done well

- The `pdfid.py` module is a clean fresh implementation — 125 LOC
  with proper docstring + frozenset constant + `__all__`. No
  upstream-source fingerprints. The `TestNoForkPolicy::
  test_pdfid_module_is_small` LOC band [30, 200] is well-calibrated
  for the current implementation (125 mid-band, 60% headroom for
  future helpers).
- The regex alternation order discipline (descending-by-length with
  a comment explaining leftmost-first vs longest-match) is correct
  and well-documented at `tools/security/pdfid.py:67-83`. The negative
  tests (`/JSON`, `/JavaScripts`, `/AABBB`) lock the lookahead
  semantics; the multi-occurrence test locks the ordering contract.
- The synthesis honestly enumerated 9 failure modes and the test
  suite locks ALL of them — including the documented limitations
  (FM-1 ZIP-CD-outside-tail, FM-2 compressed-stream-JS, FM-3
  adversarial-/Count). Documented-limitation tests are an excellent
  pattern because they prevent silent tightening (which would force
  doc updates).
- The rejection-order test (`TestRejectionOrder`) explicitly verifies
  the FM-8 regression guard: an HTML body with `/JS` + `</html>`
  fails at magic-byte, NOT at the more-expensive checks. Locks the
  fast-first dispatch order.
- Cache byte-stability discipline observed: no touches to
  `server/tools.py`, `server/prompts.py`,
  `tests/test_server_tool_schema.py`, `tests/test_prompts.py`, or
  any BP1 surface. Verified clean via `git diff`.
- The no-fork policy is enforced both structurally
  (`TestNoForkPolicy`) AND documentationally
  (`tools/security/README.md` with a 5-point discipline checklist).
  Future helpers under `tools/security/` have a clear template.
- Magic-byte sniff is byte-exact per ISO 32000-1:2008 §7.5.2 — the
  `len(head) >= 5 and head[:5] == b"%PDF-"` form correctly handles
  short reads, header-at-nonzero-offset, lowercase, and nul-padded
  cases. Tests cover all four edge cases.
- The "stale docstring" anti-pattern (this critic's own memory entry)
  was avoided in the route handler: pre-m4 comment at
  `server/routes/notebooks.py:649-655` ("future ``textbook:<slug>``
  shape WILL") was correctly retracted and replaced with present-
  tense wording ("the ``textbook:<slug>`` shape from m1 DOES").

## Recommended rectification order

1. **F2** (security-pdf-sandbox.md doc drift) — small, mechanical
   doc update. Closes operator-facing inconsistency. ~20 LOC.
2. **F1** (DoS-bound argument wrong) — biggest blast radius. Either
   fix the implementation (move per-kind cap upstream) or update
   the synthesis + summary + handler comments to reflect what's
   actually shipped. Recommend the comment-fix path — the actual
   regression is bounded by the loopback-only threat model, and a
   middleware refactor for prefix-keyed-by-kind is a larger change
   than m4's scope.
3. **F4** (missing >200 MB envelope test) — close AC #5 acceptance.
   ~15 LOC.
4. **F3** (missing `</body>` polyglot test) — close the marker
   coverage gap. ~10 LOC.
5. **F5** (pdfid.py backstop claim overstated) — docstring rewrite;
   no behavior change. ~10 LOC.
6. **F6** (DB-call-ordering test) — defensive lock on the new
   ordering. ~15 LOC.
7. **F7** (page-count regex limitation) — document the comment-
   evasion case OR tighten the regex. Documenting preferred for
   m4 scope. ~5 LOC + ~10 LOC test.
8. **F8** (defensive `_is_pdf_bytes` re-check) — small cleanup; can
   be deferred. ~3 LOC.

## Rectification status

<!-- Phase 4 appends one bullet per finding; do not pre-populate -->
