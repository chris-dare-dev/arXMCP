# Implementation Summary — E13_S02

**One-line summary:** Close Threat 2 (prompt injection) with `<retrieved_chunk>` wrapping + escape-on-emit + optional sanitizer.
**Commit range:** d8c9d99..HEAD (pending feat commit SHA)
**Branch:** main
**Date:** 2026-05-17

## What landed

Closes Threat 2 (indirect prompt injection from retrieved chunks)
from `.claude/notes/08-security-observability-ops.md` § Threat 2.

Pre-milestone audit found:
- **Zero** delimiter wrapping in the codebase. `E07_S13` (the
  named prerequisite) is fictional — E07 stopped at S04.
- 4 of 7 tools emit retrieved content at v1 and were wrapped
  (`search_papers`, `get_chunk`, `get_definitions`,
  `find_lemma_by_name`).
- 3 of 7 tools have v1 gaps with no retrieved content emitted
  (`find_equation` no body text, `get_paper.abstract` is NULL,
  `cite_neighbors` is a v1 stub). Each carries a deferred-wrap
  regression test that fails-loudly when the gap closes.

Plus the audit doc, orchestrator system-prompt guide, and 44
regression tests.

## Files changed

| Path | Change | Synthesis ref |
|---|---|---|
| `server/tools.py` | NEW: `wrap_retrieved_text()` helper alongside `envelope()` with escape-on-emit (FM-1 defense) | D1, D2 |
| `server/observability/sanitize.py` | NEW: `sanitize_retrieved_text()` + warn-once on first enabled call. Strips 4 literal injection patterns when `ARXMCP_SANITIZE_RETRIEVED_CONTENT=1` | brief AC2-3 |
| `server/handlers/search.py` | `_snippet()` now sanitizes → truncates → wraps | per-handler wiring |
| `server/handlers/chunk.py` | sanitize raw body_text → enforce_byte_cap → wrap post-truncate | per-handler wiring |
| `server/handlers/definitions.py` | `_load_paper_rows()` wraps `expansion` field at ingress | per-handler wiring |
| `server/handlers/lemma.py` | `_row_to_match()` wraps `display_name`/`theorem_name`; fallback-scan path mirrors the wrap with sort-key fix | per-handler wiring |
| `tests/security/test_delimiters.py` | NEW: 44 tests across 9 test classes — wrap helper, escape-on-emit, sanitizer off/on/strict/warn-once, sanitize→wrap order, search snippet integration, v1 gap regression guards | D3, FM-1 |
| `tests/test_definitions_index.py` | Updated `expansion` assertion to expect wrap | existing test fix |
| `tests/test_snippet_contract.py` | Updated 2 snippet assertions to expect wrap | existing test fix |
| `tests/test_theorem_names.py` | Updated 2 `display_name` assertions to expect wrap | existing test fix |
| `.claude/docs/security-threat-2-audit.md` | NEW operator-internal audit doc | doc-placement reframe |
| `.claude/docs/orchestrator-recommended-system-prompt.md` | NEW orchestrator-side guide for the `<retrieved_chunk>` system-prompt clause | brief AC4 |

## Drift from brief (deliberate; same pattern as E13_S01)

1. **Tool surface corrected.** Brief named `paper_diff` + `dependency_graph`
   (don't exist) and omitted `get_definitions` + `find_lemma_by_name`.
   Adopted the real `server/tools.py::ALL_TOOLS` list.
2. **`E07_S13` is fictional.** Brief asserts it "mandated the delimiters."
   E07 stopped at S04 — same drift as the fictional `E07_S12` from E13_S01.
   This milestone is BOTH coverage audit AND enforcement milestone.
3. **Doc destinations.** Brief said `docs/security/threat-2-audit.md` and
   `docs/orchestrator/recommended-system-prompt.md`. Per CLAUDE.md §1,
   `docs/` is operator-facing-only. Landed at `.claude/docs/security-threat-2-audit.md`
   and `.claude/docs/orchestrator-recommended-system-prompt.md` (matches
   E13_S01 precedent `.claude/docs/security-threat-1-audit.md`).
4. **Escape-on-emit defense added.** Brief did not specify it; researcher-2's
   FM-1 analysis surfaced it as load-bearing. Without escape-on-emit, an
   adversarial `</retrieved_chunk>` literal in paper text would terminate
   the wrapper prematurely and the defense is ceremonial. Added per
   synthesis D2. 4 regression tests under `TestEscapeOnEmit`.
5. **Wrap discipline = shared helper, not per-handler.** Synthesis D1
   chose `wrap_retrieved_text()` in `server/tools.py` (alongside `envelope()`)
   over a per-handler-inline approach. Decisive reason: FM-4 — new handlers
   added in future milestones will automatically discover the helper next
   to `envelope()`. Per-handler wrapping puts the burden on the reviewer
   to remember every site.
6. **Sanitize-then-wrap order canonical.** Synthesis D3. The sanitizer
   strips injection patterns from raw text; the wrapper surrounds the
   cleaned text. Order: `wrap_retrieved_text(sanitize_retrieved_text(raw))`.
7. **Env-var contract — exact-string `"1"` only.** Brief said "controlled
   by `ARXMCP_SANITIZE_RETRIEVED_CONTENT=1`" without specifying truthy
   variants. Sanitizer accepts ONLY `"1"`; `true`/`yes`/`on` are rejected.
   Avoids false-positive activation from casual operator settings.
   Documented in audit doc; tested in `TestSanitizerEnvVarStrict`.
8. **CI hook reframed.** Brief mandated CI; project has no CI per
   CLAUDE.md §4.1. The new tests run as part of `make test`.

## Test count delta

* Pre-milestone (post-E13_S01-d8c9d99): 1909 passed, 9 skipped, 1 xfailed.
* Post-feat: 1953 passed (+44 new in `tests/security/test_delimiters.py`):
  - 6 in `TestWrapHelper` (chunk wrap, equation wrap, empty, None, default kind, unicode)
  - 4 in `TestEscapeOnEmit` (chunk close in body, equation close in body, multiple close tags, non-matching close)
  - 3 in `TestSanitizerOffByDefault` (pass-through, empty/None, unicode)
  - 5 in `TestSanitizerEnabled` (strip system, strip INST, strip im_start, strip ignore, all four at once)
  - 1 more in `TestSanitizerEnabled` (case-sensitive ignore)
  - 11 in `TestSanitizerEnvVarStrict` (10 truthy variants reject + 1 exact "1" accept)
  - 3 in `TestSanitizerWarnOnce` (first call logs, second silent, disabled never logs)
  - 2 in `TestSanitizeThenWrapOrder` (stripped then wrapped, off keeps injection visible)
  - 6 in `TestSearchSnippetWrapping` (short body, truncated body, escape adversarial, empty body, sanitizer off keeps injection, sanitizer on strips)
  - 3 in `TestV1Gaps` (find_equation v1, get_paper v1, cite_neighbors v1 regression guards)
* `ruff check .` — clean.

## Acceptance criteria status

- [x] **AC1 — `pytest tests/security/test_delimiters.py` passes.** 44 tests
  exercise the 4 wrapping handlers + helper + sanitizer.
- [x] **AC2 — Sanitization scrubs the 4 literal patterns when env=1.**
  `TestSanitizerEnabled` covers all four.
- [x] **AC3 — Sanitization off by default; WARN-once when enabled.**
  `TestSanitizerOffByDefault` + `TestSanitizerWarnOnce`.
- [x] **AC4 — `docs/orchestrator/recommended-system-prompt.md` committed.**
  Landed at `.claude/docs/orchestrator-recommended-system-prompt.md`
  (corrected destination per CLAUDE.md §1).
- [x] **AC5 — Escape-on-emit regression guard.** `TestEscapeOnEmit` (4 tests).
- [x] **AC6 — Audit doc.** `.claude/docs/security-threat-2-audit.md` with
  per-tool table.

## What this milestone does NOT cover

- **`find_equation` body wrapping** — deferred to E10_S03 (no body text at v1).
- **`get_paper.abstract` wrapping** — deferred to E11 (NULL at v1 pending metadata backfill).
- **`cite_neighbors.neighbors[].abstract` wrapping** — deferred to E09 wiring
  (v1 stub returns `neighbors: []`).
- **LaTeX-encoded injection** (`\text{<|system|>}`) — out of scope; would
  require model-aware classifier (explicit non-goal per `09-feature-priorities.md`).
- **Unicode confusables / normalization** — out of scope; system-prompt
  clause documents "ASCII delimiters only".
- **Threats 3–9.** Each is its own milestone (E13_S03 through E13_S10).

## External writes the orchestrator must authorize

None — this milestone is purely local. All deliverables are local file
changes and local commits. `git push` to `origin/main` at end is gated by
the standard Phase 4 user-authorization checkpoint (per-event, per
CLAUDE.md §4.4).

## Threat-coverage matrix snapshot

After E13_S02:

| Threat | Status |
|---|---|
| 1. Path traversal via paper_id | ✅ E13_S01 |
| 2. Indirect prompt injection (delimiter coverage) | ✅ E13_S02 |
| 3. LaTeXML sandbox hostile input | ⏳ E13_S03 |
| 4. Resource exhaustion | ⏳ E13_S04 |
| 5. Origin spoofing / DNS rebinding | ⏳ E13_S05 (partial — Origin/Host shipped in E06_S05) |
| 6. Model SHA pinning / safetensors | ⏳ E13_S06 (partial — BGE-M3 SHA pinned) |
| 7. Source ingestion TLS | ⏳ E13_S07 |
| 8. Log redaction | ⏳ E13_S08 |
| 9. Localhost binding regression test | ⏳ E13_S09 |
