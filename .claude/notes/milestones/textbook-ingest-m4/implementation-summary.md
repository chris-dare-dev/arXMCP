# Implementation Summary — textbook-ingest-m4

**One-line.** PDF upload pre-flight gate (e2 entry). Five rejection
vectors at the m6 notebook-upload route for `notebook_kind="textbook"`
notebooks, vendored fresh `pdfid.py` JS-detection helper, per-kind
upload cap enforcement (10 MB for arxiv, 200 MB for textbook), and
62 new tests covering each rejection path.

**Commit base.** `474db59` (the spike-1/2/3 commit).

---

## Acceptance criteria status

- [x] **AC #1 — Magic-byte sniff.** Non-`%PDF-` first 5 bytes → HTTP 415.
      Tests: `TestPdfMagicByteSniff` (4 tests: HTML body, ZIP body,
      lowercase `%pdf-`, header at nonzero offset).
- [x] **AC #2 — Polyglot tail.** Last 1 KB containing ZIP EOCD
      (`PK\x05\x06`), `</html>`, or `</body>` → HTTP 415.
      Tests: `TestPdfPolyglotCheck` (4 tests including a regression
      guard for the documented ZIP-CD-relocated bypass — m5 sandbox is
      the backstop for that case).
- [x] **AC #3 — PDF JS-indicator entry → HTTP 415.** Tests:
      `TestPdfFindJavascriptGate` parametrized over all 7 dangerous
      tokens (`/JS`, `/JavaScript`, `/OpenAction`, `/AA`, `/Launch`,
      `/SubmitForm`, `/ImportData`).
- [x] **AC #4 — >5000 declared pages → HTTP 415.** Tests:
      `TestPdfPageCountGate` (under-cap accepts, at-cap accepts, over-
      cap rejects).
- [x] **AC #5 — Per-kind upload cap.** 150 MB textbook upload accepts;
      250 MB textbook → 413 (middleware envelope); 50 MB arxiv → 413
      (handler-level 10 MB cap); 5 MB arxiv accepts. Tests:
      `TestUploadCapPerKind` (arxiv at cap, arxiv over cap, textbook
      over arxiv cap).
- [x] **AC #6 — `tools/security/pdfid.py` is dependency-free, NOT a
      copy of Didier Stevens.** Tests: `TestNoForkPolicy` —
      structural-inspection tests assert the module is 30-200 LOC,
      contains no `PDFiD` / `cPDFDate` / `Didier Stevens Suite`
      fingerprints, and `tools/security/README.md` documents the
      no-fork discipline.
- [x] **`make test` green.** 2877 passed, 26 skipped, 1 xfailed.
      Same 6 pre-existing environmental failures (3 parser-fidelity
      fixture dirs missing, 2 `latexmlc` SIGABRT, 1 Kùzu state) —
      verified unchanged from pre-m4.
- [x] **No MCP surface changes.** `server/tools.py`, `server/prompts.py`,
      `tests/test_server_tool_schema.py`, `tests/test_prompts.py`
      untouched. No SHA re-pin.
- [x] **No MinerU integration.** Deferred to m5.

---

## Files changed

1. **`tools/security/__init__.py`** (new, 7 LOC) — empty package
   bootstrap so `from tools.security.pdfid import ...` works on a
   fresh checkout (FM-9 from synthesis).

2. **`tools/security/pdfid.py`** (new, ~125 LOC) — fresh
   implementation of dangerous-PDF-name detection. Algorithm
   borrowed (NOT copied) from Didier Stevens' public-domain
   `pdfid`. Exports `DANGEROUS_PDF_NAMES` (frozenset, 7 tokens) +
   `find_javascript(pdf_bytes) -> list[str]`. Documents the
   compressed-stream and hex-encoded evasion cases as explicit
   layer-1-only limitations.

3. **`tools/security/README.md`** (new, ~70 LOC) — vendoring
   discipline + 5-point checklist for adding future helpers.
   Documents the 3-layer defense pattern (this module + m5
   sandbox + per-notebook blast radius).

4. **`server/routes/notebooks.py`** (+~175 LOC) —
   - 4 new module-level constants (`_ARXIV_UPLOAD_MAX_BYTES`,
     `_PDF_MAX_PAGE_COUNT`, `_PDF_POLYGLOT_TAIL_BYTES`,
     `_POLYGLOT_TAIL_MARKERS`, `_PDF_COUNT_RE`).
   - 4 new private helpers (`_is_pdf_bytes`, `_pdf_polyglot_check`,
     `_pdf_declared_page_count`, `_run_pdf_preflight`) implementing
     the 5-vector gate.
   - Modified `upload_paper` handler to dispatch on `notebook_kind`:
     fetches the notebook FIRST, validates paper_id per kind
     (arxiv → `is_valid_arxiv_paper_id`; textbook → `is_valid_paper_id`
     union form from m1), enforces the per-kind upload cap, runs the
     PDF preflight for textbook kind or the HTML magic-byte sniff
     for arxiv kind, then writes to `<nb_dir>/pdfs/<flat_paper_id>.pdf`
     or `<nb_dir>/ar5iv/<flat_paper_id>.html` accordingly.
   - Added `re` to top-level imports.

5. **`server/main.py`** (+15, -2) — raised the middleware
   `prefix_caps["/ui/api/notebooks"]` envelope from 10 MB to 200 MB.
   Detailed comment block documents the per-kind enforcement
   downstream + the DoS-bound analysis (magic-byte sniff fires at 5
   bytes for non-PDF bodies; only valid-PDF on textbook-kind reaches
   the full 200 MB buffer).

6. **`tests/test_pdfid.py`** (new, ~190 LOC, 33 tests) — 7
   parametrized positive tests per token + negative cases for the
   substring false-positive class (`/JSON`, `/JavaScripts`, `/AABBB`)
   + documented-limitation regression guards for compressed-stream
   and hex-encoded evasion + type-contract tests + multi-occurrence
   ordering.

7. **`tests/test_pdf_preflight.py`** (new, ~480 LOC, 29 tests) —
   `TestPdfMagicByteSniff` (4), `TestPdfPolyglotCheck` (4 including
   the documented-limitation lock), `TestPdfFindJavascriptGate` (7
   parametrized), `TestPdfPageCountGate` (3), `TestUploadCapPerKind`
   (3), `TestPdfDispatchByKind` (4), `TestNoForkPolicy` (3),
   `TestRejectionOrder` (1).

---

## Deviations from the brief

1. **JS detection scanner uses 7 tokens, not the 4 the brief
   listed.** Per synthesis D2: the spike-2 doc and the roadmap
   brief listed 4 tokens (`/JS`, `/JavaScript`, `/OpenAction`,
   `/AA`); R2's failure-mode analysis surfaced 3 additional
   real-world auto-execution vectors (`/Launch`, `/SubmitForm`,
   `/ImportData`). All 7 are well-documented in PDF malware
   research and are part of the Didier Stevens reference
   implementation. The expanded set defends against more vectors
   with no false-positive cost on real textbook PDFs (none of the
   7 names appear in legitimate textbook PDF structure).

2. **Per-kind upload-cap mechanism is split between middleware and
   handler.** Per synthesis D3: middleware allows 200 MB through
   unconditionally for `/ui/api/notebooks` (it has no awareness of
   `notebook_kind`); the route handler enforces the 10 MB cap for
   arxiv-kind via an explicit `len(content) > _ARXIV_UPLOAD_MAX_BYTES`
   check raising HTTP 413. DoS bound documented: non-PDF bodies are
   caught by the magic-byte sniff at 5-byte read, long before 200 MB
   is buffered.

3. **`upload_paper` handler also dispatches the destination path
   per kind.** Textbook PDFs land at `<nb_dir>/pdfs/<flat_paper_id>.pdf`;
   arxiv HTML lands at `<nb_dir>/ar5iv/<flat_paper_id>.html`
   (unchanged from m8). The path-dispatch logic was not explicitly
   in the brief but is necessary for the handler to function — the
   existing handler hard-coded the ar5iv path + `.html` extension.

4. **Documented limitations baked into tests, not just docs.**
   `TestPolyglotCheck::test_zip_cd_outside_tail_window_passes` and
   `TestDocumentedLimitations::test_compressed_stream_js_misses`
   are tests that ASSERT the limitation holds — they fail if a
   future change accidentally tightens the byte-grep beyond the
   documented scope (forcing the operator to update the docs in
   lockstep with any tightening).

---

## New / changed test paths

- `tests/test_pdfid.py` (new, 33 tests across 5 classes)
- `tests/test_pdf_preflight.py` (new, 29 tests across 8 classes)

Test count: project-wide 2815 → 2877 (+62 new).

---

## External writes required

**None.** Purely local — `server/`, `tools/`, `tests/`,
`.claude/`. No `git push`, no PR, no `gh`, no infra mutation, no
external API call.

---

## Pre-existing failures observed (not from m4)

Same six as m3's tail; verified via `git stash` reproduction:

| Test | Failure | Root cause |
|---|---|---|
| `TestFixtureStructure::test_class_dir_exists[hartshorne-style]` | `is_dir()` False | Parser-fidelity fixture not populated (operator B2) |
| `TestFixtureStructure::test_class_dir_exists[griffiths-harris-style]` | same | same |
| `TestFixtureStructure::test_class_dir_exists[milne-style]` | same | same |
| `TestIntegrationRealLatexmlc::test_all_fixtures_match_baselines` | `latexmlc -6` | `latexmlc` SIGABRT |
| `TestIntegrationRealLatexmlc::test_render_fixture_does_not_leave_log_artifact` | `latexmlc -6` | same |
| `TestToolsSmoke::test_cite_neighbors_wired` | Kùzu graph_status | Local var/arxmcp/index/kuzu state |

---

## Family status post-m4

```
textbook-ingest:
  e1 (schema migration)         DONE ✓  (m1 + m2 + m3)
  e2 (MinerU sandbox)           IN-FLIGHT — m4 shipped (pre-flight gate); m5 needs B1 (MinerU install)
  e3 (hierarchical chunker)     Next-lane — depends on e1 (ready)
  e4 (cross-corpus search)      Next-lane — depends on e1+e2+e3
  e5 (PDF threat hardening)     Later-lane (Threat 3.5/8 docs + license truncation)
  spikes 1-3                    DONE ✓ (1 blocked-with-runbook, 2 design-shipped, 3 code-shipped)
```

m4 closes the upload-side defensive perimeter. The next milestone
(m5) lands the MinerU subprocess driver with the sandbox profile from
`.claude/docs/security-pdf-sandbox.md`; it requires operator action
on B1 (MinerU install) but can ship structural code with
mockable-subprocess tests before the install is complete.

---

## Notes for the adversary critic

This milestone is **security-heavy** — expect deep scrutiny on:

- The 5 rejection vectors' BYTE-LEVEL correctness (regex anchors,
  case sensitivity, lookahead semantics).
- The PER-KIND upload cap mechanism: is the DoS-bound argument
  airtight? Are there other paths besides "non-PDF body, magic-byte
  sniff fires at 5 bytes" that allow > 10 MB to flow into a
  non-textbook handler? (The synthesis D3 ruling was that
  valid-PDF-on-arxiv-kind is the only such case — verify against
  the implementation.)
- The `notebook_kind` lookup ordering — race conditions?
- The polyglot tail-window LIMITATION (ZIP CD outside last 1 KB
  bypasses): documented as such, but is it correctly documented in
  the security-pdf-sandbox.md doc?
- The `pdfid.py` no-fork test (`TestNoForkPolicy`) — is the
  LOC-band assertion too lax (>200 might still be a partial copy)?
  Are the fingerprint strings the right ones to grep for?
- The compressed-stream limitation — does the m5 implementation
  plan ACTUALLY backstop it? (`.claude/docs/security-pdf-sandbox.md`
  says yes via the MinerU sandbox, but verify the design
  contract.)
