# Research Synthesis — textbook-ingest-m4

**Standard mode dispatch (2× Sonnet parallel).** Both briefs converged
on the central approach. This synthesis records the orchestrator's
resolution of one minor divergence and pins the design decisions.

Primary inputs:
- [research-brief-1.md](research-brief-1.md) — in-codebase focus
- [research-brief-2.md](research-brief-2.md) — external + failure-mode focus

---

## Scope (verbatim from roadmap)

Five-vector defensive perimeter at the m6 notebook-upload route for
`notebook_kind="textbook"` notebooks. Per spike-2 design, m4 is the
**first defense layer** (subprocess sandbox + per-notebook blast
radius are layers 2 + 3).

**Acceptance criteria** (6 ACs from the roadmap):

1. Non-`%PDF-` magic bytes → HTTP 415.
2. Polyglot tail (ZIP CD or `</html>` in last 1 KB) → HTTP 415.
3. PDF JS-indicator entry → HTTP 415.
4. >5000 declared pages → HTTP 415.
5. 150 MB upload to textbook notebook succeeds; 250 MB → 413;
   50 MB to arxiv-kind → 413 (10 MB cap retained).
6. `tools/security/pdfid.py` is dependency-free, NOT a copy of
   Didier Stevens' source.

NO MCP surface changes. NO SHA re-pin.

---

## Load-bearing constraints

### The middleware-cap-can't-know-`notebook_kind` problem

Both R1 and R2 independently flagged this. `RequestBodySizeLimitMiddleware`
in `server/middleware.py:129` uses `prefix_caps` keyed by URL prefix —
it has NO awareness of the database row backing the slug. The
current cap is:

```python
prefix_caps={
    "/ui/api/notebooks": 10 * 1024 * 1024,  # 10 MB
}
```

To allow 200 MB textbook uploads, the cap must be raised at the
**middleware** layer (otherwise 10 MB rejection fires before the
handler ever runs). Then the 10 MB enforcement for arxiv-kind
notebooks happens in the **route handler body** after
`await store.get_notebook(slug)` returns `notebook_kind`.

**Acceptable DoS bound:** for a non-PDF body uploaded to ANY
notebook kind, the magic-byte sniff fires at 5 bytes (HTTP 415)
before the 200 MB buffer is exhausted. For a 200 MB body uploaded
to an arxiv-kind notebook, the body IS fully buffered (eager-read
in middleware F1 fix) before the handler's `notebook_kind=="arxiv"`
check fires 413. R2 verdict: **acceptable design** — the only case
where a 200 MB body actually traverses memory is a valid PDF upload
on a textbook notebook, which is intentional.

### Existing upload handler shape (m8 pattern)

`server/routes/notebooks.py` lines 525-690 establish the upload
handler structure m4 inherits:

1. validate slug → 422
2. validate paper_id → 422
3. `await store.get_notebook(slug)` → 404 if None
4. `await file.read()` → 400 / 422
5. `_is_html_bytes(content[:16])` → 422
6. atomic write
7. `store.add_paper(...)` → 200

m4 inserts the PDF preflight **between 3 and 4** (after kind read,
before disk write). The `notebook_kind` value is already in the
result of step 3 per m3 — no extra DB call needed.

### spike-2 prescriptive function shapes

Both R1 and R2 cite `.claude/docs/security-pdf-sandbox.md` as
PRESCRIPTIVE. Function shapes pinned:

```python
def _is_pdf_bytes(head: bytes) -> bool:
    return len(head) >= 5 and head[:5] == b"%PDF-"

def _pdf_polyglot_check(pdf_bytes: bytes) -> None:
    # raises HTTPException(415) on detection
    ...
```

`_is_pdf_bytes` is byte-exact per ISO 32000-1:2008 §7.5.2.

### No PyMuPDF dependency

Both briefs independently confirmed `pyproject.toml` has zero
references to `pymupdf` / `fitz`. PyMuPDF is a MinerU transitive dep
that lands in e2-m5, NOT m4. The page-count probe in m4 is
**pure-bytes regex** (`/Count\s+(\d+)`), no new dep.

### Didier Stevens pdfid — public domain, algorithm only

Public-domain license; no-fork concern is about copying the SOURCE
TEXT, not the ALGORITHM. The pattern is well-documented:
byte-grep for PDF dictionary key names. Implementation in ≤50 LOC,
fresh. Cite the algorithm in the docstring.

---

## Orchestrator design decisions

### D1 — Single `_run_pdf_preflight(content, slug)` orchestrator + per-check helpers

R1's recommendation, adopted. The orchestrator function lives in
`server/routes/notebooks.py` and runs the 5 checks in fast-first
order. Per-check helpers (`_is_pdf_bytes`, `_pdf_polyglot_check`,
`_pdf_declared_page_count`) are private module-level for unit
testability. The JavaScript check delegates to
`tools.security.pdfid.find_javascript`.

### D2 — JS detection token set: 7 tokens (R2's expanded list)

R1 listed 4 tokens (`/JS`, `/JavaScript`, `/OpenAction`, `/AA`); R2
listed 7 (those + `/Launch`, `/SubmitForm`, `/ImportData`).
**Resolved with R2's expanded set.** Rationale: defense-in-depth
errs on the side of more rejections. All three additions are real
auto-execution / data-exfil vectors documented in PDF malware
research. The brief AC says "PDF JS-indicator entry" — the spike-2
doc lists 4, but the milestone is operator-controllable (operator
can downgrade if it false-positives on legitimate textbooks).

The pdfid module exports the canonical token list as a constant so
the m4 docstring + tests can reference it consistently.

### D3 — Upload cap mechanism: raise middleware to 200 MB; handler enforces 10 MB for arxiv-kind

Both briefs converged on this. `server/main.py` `prefix_caps`
raises `/ui/api/notebooks` from `10 * 1024 * 1024` to
`200 * 1024 * 1024`. The route handler explicitly checks
`if notebook["notebook_kind"] != "textbook" and len(content) > 10 * 1024 * 1024`
→ raises `HTTPException(status_code=413)`.

The DoS concern (R2 FM-5) is bounded: non-PDF magic bytes fail at
5-byte read; only a valid-magic-bytes PDF uploaded to an
arxiv-kind notebook reaches the kind-check after full-body buffer.
This is exotic enough to accept as a design tradeoff vs. fork
`RequestBodySizeLimitMiddleware` to be DB-aware (which would be a
much larger change for marginal benefit).

### D4 — Page-count probe: regex max-of-all-`/Count` matches

Both briefs agree. `re.findall(rb"/Count\s+(\d+)", pdf_bytes)` →
`max(matches)`. Reject if max > 5000. Docstring documents the
heuristic limitation (a malformed `/Count` value declared but actual
page tree larger is undetectable without a full parser; MinerU's
PyMuPDF in layer 2 catches the discrepancy).

### D5 — Rejection order (fast-first)

Per R2's recommendation:
1. **Magic-byte sniff** (5 bytes) — `_is_pdf_bytes`
2. **Polyglot tail** (last 1 KB) — `_pdf_polyglot_check`
3. **Arxiv-kind size check** (~zero cost beyond `len()`)
4. **JS detection** (full body regex) — `_pdf_has_javascript`
5. **Page-count probe** (full body regex) — `_pdf_declared_page_count`

Steps 4 + 5 both scan the full body but are cheap regex passes
(~100 ms on a 200 MB PDF). Order is per-check expense, not threat
priority.

### D6 — `tools/security/` directory layout

```
tools/security/
├── __init__.py       # empty (just makes the dir importable)
├── pdfid.py          # find_javascript(bytes) -> list[str]
└── README.md         # vendoring discipline + token list rationale
```

`__init__.py` MUST exist (R2 FM-9 — fresh-checkout import failure
without it). `README.md` documents:
- The no-fork policy (cite CLAUDE.md §4.7).
- The Didier Stevens algorithm credit (public domain, algorithm
  borrowed, source written fresh).
- The 7-token detection list and rationale.
- The compressed-stream-evasion limitation (defense-in-depth
  with MinerU's PyMuPDF in layer 2).

### D7 — HTTP status code convention

Both briefs agree: **413** for size violations (matches
`RequestBodySizeLimitMiddleware` precedent); **415** for content
checks (magic-byte, polyglot, JS, page-count, non-PDF).

### D8 — Test surface

Adapted from R1's enumeration:

- `TestPdfIsPdfBytes` — `_is_pdf_bytes` parametrized (positive +
  negative cases including case-sensitivity per ISO 32000).
- `TestPdfPolyglotCheck` — ZIP CD + HTML closing tag variants in
  tail; ZIP CD outside the last 1 KB (acknowledged-bypass
  documentation test, NOT a passing case).
- `TestPdfFindJavascript` — each of the 7 tokens triggers detection;
  legitimate `/Pages` / `/Kids` keys do NOT false-positive.
- `TestPdfPageCount` — `/Count 100` accepts; `/Count 9999` rejects;
  max-of-multiple-matches.
- `TestRunPdfPreflight` — orchestrator: each check fires in order;
  cheap checks short-circuit expensive ones.
- `TestTextbookUploadCapRaise` — 150 MB textbook upload accepts;
  250 MB textbook upload → 413; 50 MB arxiv upload → 413; 5 MB
  arxiv upload accepts.
- `TestPdfRejectionToHttp` — each rejection vector ends in the
  documented HTTP code.
- `TestPdfPreflightDispatchOrder` — magic-byte sniff fires BEFORE
  any full-body scan (R2 FM-8 regression guard).

**Test fixtures:** synthetic PDF bytes constructed inline (no real
PDF files committed). Each fixture is < 500 bytes — `b"%PDF-1.4\n..."`
+ the minimum object structure to be valid-looking.

### D9 — Out of scope

- Anti-bypass for ZIP-CD-relocated polyglots (R2 FM-1) — documented
  limitation, m5 sandbox is the backstop.
- Anti-bypass for FlateDecode-hidden JS (R2 FM-2) — same.
- PyMuPDF integration (m5's job).
- MCP tool surface changes.
- BP1 / `EXPECTED_TOOL_SCHEMA_SHA256` / `EXPECTED_BP1_SHA256` —
  unchanged.

---

## Files touched in m4

1. `server/routes/notebooks.py` — 5 new private functions:
   `_is_pdf_bytes`, `_pdf_polyglot_check`,
   `_pdf_declared_page_count`, `_pdf_has_javascript` (delegate),
   `_run_pdf_preflight` (orchestrator). Insert call in upload route
   between steps 3 and 4 of the existing flow.
2. `server/main.py` — raise `prefix_caps["/ui/api/notebooks"]`
   from 10 MB to 200 MB.
3. `tools/security/__init__.py` — new, empty.
4. `tools/security/pdfid.py` — new module with
   `find_javascript(pdf_bytes: bytes) -> list[str]` + canonical
   `DANGEROUS_PDF_NAMES = frozenset({"/JS", "/JavaScript", ...})`.
5. `tools/security/README.md` — new, navigational README documenting
   the vendoring discipline.
6. `tests/test_notebook_api.py` — new test classes (per D8).
7. `tests/test_pdfid.py` — new unit tests for the pdfid module.

NO touches to: `server/tools.py`, `server/prompts.py`,
`tests/test_server_tool_schema.py`, `tests/test_prompts.py`,
`ingest/*` (m1+m2 territory), MCP handlers.

---

## Combined failure-mode register

| # | Trigger | Severity | m4 mitigation |
|---|---|---|---|
| FM-1 | ZIP CD relocated via comment padding bypasses tail check | HIGH | Documented limitation; m5 sandbox is backstop |
| FM-2 | JS in FlateDecode stream evades string-grep | HIGH | Documented limitation; MinerU's PyMuPDF in layer 2 |
| FM-3 | Adversarial `/Count` value | MEDIUM | Max-of-all-matches; m5 wall-clock timeout backstop |
| FM-4 | `notebook_kind` race on concurrent delete | LOW | Existing 404 path handles it; documented |
| FM-5 | 200 MB DoS via valid-PDF-bytes uploaded to arxiv-kind | MEDIUM | Documented; magic-byte sniff catches most; m5 sandbox bounds damage |
| FM-6 | Magic-byte sniff runs after full-body read | MEDIUM | Acceptable; middleware eager-buffer is the real cap |
| FM-7 | `pdfid.py` drifts from token list | MEDIUM | Test suite includes per-token synthetic PDFs |
| FM-8 | Rejection order wrong (expensive first) | LOW | Tests assert magic-byte sniff fires first |
| FM-9 | `tools/security/__init__.py` missing | BLOCKING | Explicit ship requirement in commit |

---

## Open questions

**None.** All decisions resolved above.

---

## External writes required

**None.** Purely local — `server/`, `tools/`, `tests/`, `.claude/`.

---

## Orchestrator synthesis note

One divergence resolved (D2 — token set: 4 vs 7); rest of the
briefs converged. Both researchers independently flagged the
middleware-can't-know-`notebook_kind` constraint and proposed the
same resolution (D3 — middleware permissive, handler restrictive).
R2's failure-mode enumeration (9 modes vs R1's none) is the spike's
real value-add — those 9 modes are baked into the test surface (D8)
and the documented-limitation rows in the pdfid README (D6).

Ship as drawn.
