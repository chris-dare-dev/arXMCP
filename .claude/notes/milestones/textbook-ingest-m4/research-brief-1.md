# Research Brief — textbook-ingest-m4

**Agent:** milestone-researcher (brief-1)
**Generated:** 2026-05-27T00:00:00Z

---

## In-codebase context

### Existing upload route pattern (load-bearing)

`server/routes/notebooks.py` lines 487–518 establish the m8 HTML upload
pattern that m4's PDF gate is a SIBLING of:

```python
_MAGIC_SNIFF_BYTES: int = 16

def _is_html_bytes(head: bytes) -> bool:
    """Return True if ``head`` (first 16 bytes of an upload) looks
    like an HTML document.
    ...
    """
    if not head:
        return False
    s = head.lstrip(b"\xef\xbb\xbf \t\r\n")
    if not s:
        return False
    return s[:2].lower() in (b"<!", b"<h")
```

The upload handler (lines 520–690) structure:
1. validate slug → 422
2. `is_valid_arxiv_paper_id(paper_id)` → 422
3. `await store.get_notebook(slug)` → 404 if None
4. `await file.read()` → 400 on read error; 422 if empty
5. `_is_html_bytes(content[:_MAGIC_SNIFF_BYTES])` → 422 if False
6. atomic write (`tmp_path.write_bytes` + `os.replace`)
7. `store.add_paper(...)` → 200 on duplicate (idempotent)

**m4 must insert the PDF preflight between steps 3 and 4** (after confirming
the notebook exists and reading the kind, but before writing to disk).

### `notebook_kind` flow

`NotebooksStore.get_notebook(slug)` returns `dict[str, str] | None` with
field `"notebook_kind"`. As of textbook-ingest-m3:

```python
async def get_notebook(self, slug: str) -> dict[str, str] | None:
    ...
    return {
        "slug": row[0], "display_name": row[1],
        "lancedb_path": row[2], "created_at": row[3],
        "notebook_kind": row[4],
    }
```

The upload handler ALREADY calls `await store.get_notebook(slug)` for the
404 check (line 572). m4 can read `notebook["notebook_kind"]` from the same
result — no second DB call needed.

### `RequestBodySizeLimitMiddleware` — prefix_caps mechanism

From `server/middleware.py` line 129 and `server/main.py` lines 497–502:

```python
REQUEST_BODY_MAX_BYTES = 1 * 1024 * 1024  # 1 MB default

# In server/main.py:
app.add_middleware(
    RequestBodySizeLimitMiddleware,
    prefix_caps={
        "/ui/api/notebooks": 10 * 1024 * 1024,  # 10 MB for upload
    },
)
```

The `_effective_max_bytes` method selects the cap by prefix-match. To raise
the cap for textbook notebooks to 200 MB, m4 must update this dict. The
key is the prefix `/ui/api/notebooks` — the same prefix already carries the
10 MB carve-out. Since we cannot conditionally apply a cap per
notebook_kind at middleware level (middleware doesn't know the notebook
record), m4 must raise the prefix cap to 200 MB unconditionally for
`/ui/api/notebooks`. The kind check happens inside the upload handler:
the route reads `notebook["notebook_kind"]`, and if it is NOT `"textbook"`,
it applies the old 10 MB limit as an explicit application-level check
rather than relying on the middleware cap alone.

**FLAG: The brief says "Upload cap raise 10 MB → 200 MB ONLY for
notebook_kind='textbook'".** The middleware `prefix_caps` is
path-prefix-only and cannot be kind-conditional. The recommended resolution
(see Recommendations) is: raise middleware cap to 200 MB for the
notebooks prefix (making it the upper envelope), then enforce the 10 MB
limit for non-textbook notebooks inside the route body with an explicit
check on `len(content) > 10_485_760` after reading.

### Prescriptive function shapes from `.claude/docs/security-pdf-sandbox.md`

The spike-2 document is PRESCRIPTIVE for m4. These exact function shapes
are the implementer's contract:

```python
def _is_pdf_bytes(head: bytes) -> bool:
    """Magic-byte sniff. PDF files start with ``%PDF-`` per ISO 32000."""
    return len(head) >= 5 and head[:5] == b"%PDF-"

def _pdf_has_javascript(pdf_path: Path) -> bool:
    """Vendored pdfid (no external dep). Detects /JS, /JavaScript,
    /OpenAction, /AA (additional actions) entries."""
    ...

def _pdf_polyglot_check(pdf_bytes: bytes) -> None:
    """Reject polyglot files. First 4 bytes must be %PDF; final 1 KB
    must not contain a ZIP central-directory marker or HTML closing tag.
    Raises HTTPException(415) on detection."""
    if not _is_pdf_bytes(pdf_bytes[:5]):
        raise HTTPException(status_code=415, detail="not a PDF")
    tail = pdf_bytes[-1024:]
    for marker in (b"PK\x05\x06", b"</html>", b"<HTML>"):
        if marker in tail:
            raise HTTPException(
                status_code=415,
                detail=f"polyglot detected (tail contains {marker!r})",
            )

def _pdf_page_count(pdf_path: Path) -> int:
    """Lightweight pre-MinerU page-count probe."""
    ...
```

The spike doc explicitly states HTTP 415 for magic-byte / polyglot / JS /
page-count failures and HTTP 413 for size overflow.

### Threat coverage (08-security-observability-ops.md)

Threat 7 (§ source ingestion fetches): "Content-length sanity checks (a
single paper > 100 MB source is suspicious)." m4's 200 MB textbook cap
is distinct from Threat 7's arXiv-source cap. The threat note at line 97
covers the arXiv ingest path; m4 covers the operator-upload path.

Threat 3 (LaTeXML on hostile source): m4's pre-flight gate is the first
layer of the three-layer PDF defense stack documented in the spike-2 doc.

### No-fork vendoring precedent

`tools/cdm_eval.py` docstring: "Design-pattern lift from
opendatalab/OmniDocBench (Apache-2.0) per CLAUDE.md §4.7 no-fork rule —
ideas, not code." This is the exact precedent for the pdfid vendoring:
cite the algorithm and the detection rules from Didier Stevens' pdfid, but
write the code fresh.

`tools/README.md` documents the tools/ subdirectory as "one-off developer
scripts" — `tools/security/` is a new subdirectory. Its `README.md` is a
navigational README (allowed under doc-placement rules for subdirs).

### Existing test pattern for magic-byte sniff

`tests/test_upload_handler.py::TestMagicByteSniff` is the direct template.
It tests `_is_html_bytes` directly via import + parametrize, plus an
end-to-end upload test. The m4 equivalent:
- `TestPdfMagicByte` — parametrize `_is_pdf_bytes` + upload rejection
- `TestPdfPolyglot` — tailmarker vectors via `_pdf_polyglot_check`
- `TestPdfJavascript` — `_pdf_has_javascript` unit tests
- `TestPdfPageCount` — page-count probe
- `TestTextbookCapRaise` — verifies 10 MB cap for arXiv notebooks, 200 MB
  for textbook notebooks

---

## Prior decisions and lessons

From `git log --oneline server/routes/notebooks.py`:

- `397a869` `feat(server): BP1 re-pin + notebook_kind field (textbook-ingest-m3)` — notebook_kind field now in the store; m4 can read it from `get_notebook` return.
- `aec3a12` `rect(ingest): close 2 HIGH + 2 MED from textbook-ingest-m1 critique` — F1 HIGH was the `CHUNK_ID_RE` `$` anchor bug.
- `ff88773` `feat(server): htmx UI + ar5iv upload (proof-verify-handler-wiring-m8)` — established the upload handler shape m4 inherits.
- `0026ea4` `rect(server,tests): close F1-F4, F6, F7 from m9 critique`.

**Key lesson from m8:** the HTML magic-byte sniff was placed between the
file.read() call and the disk write. m4's PDF checks must follow the same
position. Reading the full body BEFORE checking magic bytes is correct
because the middleware already caps the upload size (at the new 200 MB
ceiling); there is no need to stream-check.

**Known memory pattern:** the m8 upload handler reads the full file into
`content` with `await file.read()`. For 200 MB textbook PDFs this will
hold 200 MB in memory per request. This is acceptable for the operator-
local single-user context (CLAUDE.md §4.1) but should be noted in tests.

**No existing vendored external module:** no `tools/` Python file imports
from an external library that was "vendored fresh." The pdfid.py file is
genuinely the first vendoring example. The no-fork rule applies: write
fresh, cite the algorithm.

**Codebase memory flags (from MEMORY.md):**
- `CHUNK_ID_RE` uses `$` not `\Z` — not directly relevant to m4.
- Three-copy-sync pattern for `_PAPER_ID_RE` — not relevant to m4 (no
  new identifier regex).

---

## External sources

### Didier Stevens' pdfid — JS detection algorithm

pdfid (public domain) detects JavaScript by scanning PDF byte streams for
the following name objects:

```
/JS          — JavaScript stream directly
/JavaScript  — named JavaScript action
/OpenAction  — action executed when document opens
/AA          — additional actions (per-page triggers)
/Launch      — file/app launch action
/SubmitForm  — form data exfiltration
/ImportData  — data import (indirect vector)
```

The implementation strategy: scan `pdf_bytes` for each token as a raw byte
pattern. PDF name tokens are preceded by `/` and followed by whitespace,
`<`, `>`, `[`, `/`, or end-of-stream. A minimal scanner:

```python
import re

_JS_TOKENS = re.compile(
    rb"/(?:JS|JavaScript|OpenAction|AA|Launch|SubmitForm|ImportData)"
    rb"(?=[\s<>/\[\(]|\Z)"
)

def find_javascript(pdf_bytes: bytes) -> list[str]:
    """Return a list of dangerous PDF name tokens found in pdf_bytes."""
    return [m.group(0).decode("latin-1") for m in _JS_TOKENS.finditer(pdf_bytes)]
```

This is NOT a full PDF parser — it will false-positive on commented-out
tokens (PDF uses `%` for comments, not block comments) and will miss tokens
obfuscated via hex encoding (`/4A53` = `/JS`). For m4's threat model
(defense-in-depth before MinerU), the false-positive rate is acceptable
(reject some benign PDFs) and false-negatives are mitigated by MinerU's own
PyMuPDF layer.

### PyMuPDF (fitz) — NOT a current project dependency

`pyproject.toml` contains no `pymupdf` or `fitz` dependency. Adding it
solely for the page-count probe would introduce a large binary dependency
that MinerU itself will likely require (in m5). **Do not add PyMuPDF in
m4.** Use the pure-bytes fallback instead.

### Pure-bytes page-count probe

PDF page count is declared in the `/Pages` dictionary as `/Count N`. The
cheapest probe: scan the last 20% of the PDF bytes (where the xref table
and trailer live in well-formed PDFs) for the `/Count` token. This is
inherently a heuristic — a malformed PDF can lie or omit the `/Count` key.
The defense goal is rejecting clearly adversarial inputs (e.g., `/Count
9999999`), not parsing all PDFs correctly.

```python
import re

_PAGE_COUNT_RE = re.compile(rb"/Count\s+(\d+)")

def _pdf_declared_page_count(pdf_bytes: bytes) -> int:
    """Return the highest /Count value found in the PDF byte stream,
    or 0 if none is parseable. Heuristic — not a full parser."""
    tail = pdf_bytes[max(0, len(pdf_bytes) - len(pdf_bytes) // 5):]
    matches = _PAGE_COUNT_RE.findall(tail)
    if not matches:
        # fall back to full scan
        matches = _PAGE_COUNT_RE.findall(pdf_bytes)
    if not matches:
        return 0
    return max(int(m) for m in matches)
```

---

## Recommendation

**Implement a single `_run_pdf_preflight(content: bytes, slug: str) -> None`
function** in `server/routes/notebooks.py` that encapsulates all five checks
and raises `HTTPException` on any failure. The upload handler calls it once
after confirming the notebook is a textbook kind, before writing to disk.

This mirrors the m8 pattern (`_is_html_bytes` as a standalone helper) but
bundles the five PDF checks into one call for readability and testability.
The individual check helpers (`_is_pdf_bytes`, `_pdf_polyglot_check`,
`_pdf_has_javascript`, `_pdf_declared_page_count`) are also importable
for unit-testing.

**For `tools/security/pdfid.py`:** implement as a module with the single
importable function `find_javascript(pdf_bytes: bytes) -> list[str]`.
Not a class, not a CLI. The route imports it directly. This is the
simplest shape that satisfies the no-fork policy and the route's usage.

**For the page-count probe:** use the pure-bytes `/Count` regex (no PyMuPDF).
PyMuPDF is not a current dep; adding it in m4 would be premature (m5 is
where MinerU and its PyMuPDF dep land). The regex approach matches the
threat model — adversarial inputs declare an implausible `/Count` that is
easy to detect without parsing.

**For the size-cap conditional:** raise the `prefix_caps` dict in
`server/main.py` from `10 * 1024 * 1024` (10 MB) to `200 * 1024 * 1024`
(200 MB) for the `/ui/api/notebooks` prefix. Inside the upload handler,
after reading the `notebook["notebook_kind"]`:
- if `"textbook"`: pass (200 MB middleware cap is the upper bound)
- if anything else: check `len(content) > 10 * 1024 * 1024` and raise
  `HTTPException(413)` explicitly

This keeps the middleware as the outer envelope without requiring
kind-aware middleware.

**HTTP status codes:** 413 for size violations (consistent with
`RequestBodySizeLimitMiddleware`); 415 Unsupported Media Type for all
five PDF content checks (magic-byte, polyglot, JS, page-count, and
non-PDF uploads to textbook notebooks). This matches the spike-2 doc
prescriptive shapes exactly.

**Insert the `_run_pdf_preflight` call in the upload handler** after
step 3 (notebook kind read) and before step 4 (file.read), except that
the file must be read first to inspect bytes — so the actual call order
is: read content → check kind → if textbook, run preflight → proceed.

**Banned patterns to avoid:**
- No `assert` for the preflight checks — use `if … raise HTTPException`.
- No `BaseHTTPMiddleware` — the size-cap conditional lives in the route
  body, not a new middleware class.
- No `import anthropic` anywhere in this route.
- `tools/security/README.md` is a navigational README for the subdir —
  allowed under doc-placement rules.

---

## Open questions

No open questions — implementation can proceed on the above recommendation.

The one potential ambiguity (middleware cap must be 200 MB unconditionally
to allow textbook uploads, while non-textbook notebooks should still be
capped at 10 MB) is resolved by the route-body kind check described above.
The implementer does not need to re-read middleware internals to implement
this correctly.

---

## External writes the implementation will require

None — this milestone is purely local.
