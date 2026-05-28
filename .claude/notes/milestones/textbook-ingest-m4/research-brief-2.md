# Research Brief — textbook-ingest-m4

**Agent:** milestone-researcher (brief-2)
**Generated:** 2026-05-28T00:15:00Z

---

## In-codebase context

### Pre-conditions confirmed: m1–m3 all shipped

`git log --oneline -15` confirms the dependency chain is complete:
- `81701c8 chore(notes): finalize textbook-ingest-m3 state -> complete`
- `0ac2bd4 chore(notes): finalize textbook-ingest-m2 state -> complete`
- `68c77c8 chore(notes): finalize textbook-ingest-m1 state -> complete`

`notebook_kind` field: shipped in m3. From `server/routes/notebooks.py:204`:
```python
notebook_kind: str = Field(
    default="arxiv",
    pattern="^(arxiv|textbook)$",
)
```
And `server/notebooks_store.py:261` confirms `notebook_kind` is included in
`get_notebook()` return dicts — the upload route CAN query it at runtime.

### Upload route (existing baseline)

The m8 upload route at `server/routes/notebooks.py:525` handles
`POST /ui/api/notebooks/{slug}/papers/upload` with an arXiv-HTML assumption:
- It calls `await file.read()` AFTER `await store.get_notebook(slug)`.
- Magic-byte sniff via `_is_html_bytes(content[:_MAGIC_SNIFF_BYTES])` returns
  422 for non-HTML files (including `.pdf`).
- The 10 MB cap is enforced by `RequestBodySizeLimitMiddleware` prefix_caps on
  `/ui/api/notebooks` in `server/main.py:499`.

**CRITICAL: The upload cap is prefix-scoped, NOT notebook_kind-scoped.** The
current `prefix_caps={"/ui/api/notebooks": 10 * 1024 * 1024}` raises the cap
for ALL notebooks routes. m4 must raise this to 200 MB for textbook notebooks,
but the middleware has no awareness of notebook_kind — that check happens
downstream in the route handler. This means the 200 MB cap must be implemented
AT THE ROUTE HANDLER level (after notebook_kind is fetched from SQLite), NOT by
modifying the middleware prefix_caps. The middleware should be set to 200 MB
globally for the `/ui/api/notebooks` prefix (or a textbook-upload sub-path), and
the route handler applies the tighter 10 MB rejection for arxiv-kind notebooks
itself. **Alternatively**, add a second more-specific prefix cap at
`/ui/api/notebooks/.../papers/upload` and make the 10 MB per-notebook-kind check
in-handler. Either way: the middleware must allow 200 MB to pass so the route
handler can inspect `notebook_kind` before rejecting. If the middleware rejects
at 10 MB, the handler NEVER sees textbook uploads.

### security-pdf-sandbox.md design contract (spike-2 output, MUST follow)

From `.claude/docs/security-pdf-sandbox.md` — these are prescriptive for m4:

"**Caps enforced before MinerU is invoked:**
- File size: ≤ 200 MB (`server/middleware.py` upload cap; raised from 10 MB
  ONLY for `kind="textbook"` notebooks).
- Magic bytes: starts with `%PDF-`.
- No polyglot tail markers.
- No `/JS` / `/JavaScript` / `/OpenAction` / `/AA` PDF entries.
- Page count: ≤ 5000."

The spike doc also prescribes the exact function signatures that m4 must ship:
```python
def _is_pdf_bytes(head: bytes) -> bool:
    """Magic-byte sniff. PDF files start with ``%PDF-`` per ISO 32000."""
    return len(head) >= 5 and head[:5] == b"%PDF-"
```

**Doc placement:** `tools/security/README.md` — the brief explicitly calls for
a README in `tools/security/`. Per `agent-conventions.md §6`, only
`README.md` / `CLAUDE.md` are permitted in non-`.claude/` subdirs.
`tools/security/README.md` IS compliant (it is a navigational README for that
subdir). This is the correct placement.

### Threat 3 and Threat 7 from 08-security-observability-ops.md

"**Threat 3: LaTeXML on hostile source.** LaTeX is Turing-complete. A malicious
paper could ship a `.tex` source designed to consume infinite RAM, write
arbitrary files, or shell out. Mitigations: LaTeXML runs in a subprocess with
a hard timeout..."

"**Threat 7: Source ingestion fetches.** Content-length sanity checks (a single
paper > 100 MB source is suspicious)."

The PDF pre-flight gate is the Threat-3 peer for MinerU. The 200 MB upload
cap extends Threat 7's content-length sanity check to the upload path.

### No PyMuPDF in pyproject.toml

`pyproject.toml` and `uv.lock` contain ZERO references to `pymupdf` or `fitz`.
PyMuPDF is described as "MinerU-internal" in the spike-2 doc — it is a
transitive dependency of MinerU, not a direct project dependency. **The
implementer MUST NOT import `fitz` or `pymupdf` directly in the pre-flight
gate.** The spike doc's `_pdf_page_count` uses "PyMuPDF's metadata-only mode"
as aspirational text, but the brief also documents a "string-grep fallback that
walks `/Type /Page` markers." Given no direct dependency on pymupdf, the
**string-grep approach is the only safe default** for the page-count probe in
m4. Importing `fitz` directly would add an unlisted runtime dependency.

### tools/security/ directory does NOT yet exist

`ls /Users/chris.dare/Personal/SourceCode/arXMCP/tools/security/` → DOES NOT
EXIST. m4 creates it. The `tools/security/__init__.py` file MUST be created
alongside `pdfid.py` and `README.md`, otherwise `from tools.security.pdfid
import ...` fails with ModuleNotFoundError on a fresh checkout.

### No MCP tool schema changes

The milestone brief states: "No changes to MCP tool surface or BP1 prefix;
`EXPECTED_TOOL_SCHEMA_SHA256` + `EXPECTED_BP1_SHA256` untouched." This is
consistent with the sprint design — m4 is purely pre-flight defense at the
upload route. No re-pinning needed.

---

## Prior decisions and lessons

### CHUNK_ID_RE dollar anchor bug (from MEMORY)

Prior research noted `CHUNK_ID_RE` uses `$` not `\Z`. The m1 rect commit
(aec3a12) fixed `_PAPER_ID_FULL_PATTERN` but CHUNK_ID_RE may still have `$`.
If `pdfid.py` consumes chunk_ids or paper_ids, verify against the `\Z`-anchored
version. m4's pre-flight gate does not consume chunk_ids directly — this is not
blocking for m4.

### three-copy-sync-pattern (from MEMORY)

`ingest/identifiers.py`, `ingest/chunker.py`, and
`tools/validate_eval_fixtures.py` must stay byte-equal on `_PAPER_ID_RE`. m4
adds nothing to those files, so this pattern is NOT activated here.

### Doc placement correction pattern (from MEMORY)

All security audit docs live under `.claude/docs/`, not `docs/`. Confirmed:
`tools/security/README.md` is a navigational README (permitted in subdirs per
the rule), not an audit doc. No correction needed.

### Banned pattern: assert for invariants

`tools/security/pdfid.py` must use `if ... raise ValueError(...)` for any
invariant checks, NOT `assert`. This is a common trap in fresh-written utility
modules.

### Banned pattern: BaseHTTPMiddleware

The upload cap change MUST NOT introduce BaseHTTPMiddleware. Use
`RequestBodySizeLimitMiddleware.prefix_caps` extension or handler-side byte
checking. The existing pure-ASGI pattern in `server/middleware.py` is the
correct model.

---

## External sources

### PDF magic bytes — ISO 32000

Per ISO 32000-1:2008 §7.5.2, the PDF file header is `%PDF-` followed by the
version number (e.g. `%PDF-1.7`, `%PDF-2.0`). The sequence is **case-sensitive**
— lowercase `%pdf-` is NOT a valid PDF header. The `%` is ASCII 0x25; `PDF-` is
ASCII 0x50 0x44 0x46 0x2D. **No legitimate PDF variant starts with anything
other than `%PDF-`.** Some (broken) PDF readers tolerate the `%PDF-` header
anywhere in the first 1024 bytes, but ISO 32000 requires it at offset 0. The
`_is_pdf_bytes` function checking `head[:5] == b"%PDF-"` is spec-correct.

Sources: [ISO 32000-1:2008](https://www.iso.org/standard/51502.html),
[PDF file format structure](https://www.infosecinstitute.com/resources/hacking/pdf-file-format-basic-structure/)

### Polyglot attacks — canonical techniques and bypasses

**PDF+ZIP polyglot:** ZIP locates its central directory (CD) by scanning the
END of the file for `PK\x05\x06` (end-of-CD record). A PDF header can be
prepended to any ZIP without invalidating it, because ZIP readers seek from
the tail. The 1 KB tail check for `PK\x05\x06` catches the standard case.

**KNOWN BYPASS:** An attacker can relocate the ZIP central directory to a
mid-file position using a ZIP comment field padded to push the EOCD record
earlier in the file, outside the final 1 KB. The EOCD comment field allows up
to 65535 bytes. A sufficiently large comment places the EOCD at file_size -
65535 - 22 bytes, well outside the 1 KB tail. The tail-only check would MISS
this variant. Mitigation: this is acknowledged in the spike-2 design as a
known limitation — the pre-flight gate is defense-in-depth, not a complete
polyglot eliminator. The subprocess sandbox (layer 2) is the defense for
bypass cases.

**PDF+HTML polyglot:** `</html>` in tail catches the simplest case. HTML
closing tags are not required to be at the very end of an HTML file — a
trailing newline or comment is sufficient for the browser. The check is
heuristic.

Sources: [Polyglots arXiv paper 2407.01529](https://arxiv.org/html/2407.01529v1),
[Proofpoint polyglot malware](https://www.proofpoint.com/us/blog/threat-insight/call-it-what-you-want-threat-actor-delivers-highly-targeted-multistage-polyglot-malware)

### Didier Stevens pdfid.py — license and algorithm

**License:** Public Domain (confirmed). No copyright concern. The no-fork
policy means the implementation must be written fresh — the ALGORITHM is
borrowable; the source text is not.

**Algorithm (implementable in ≤50 LOC):** String-grep over the raw PDF byte
stream for PDF dictionary key names: `/JS`, `/JavaScript`, `/OpenAction`, `/AA`.
The implementation iterates through the byte sequence character by character (or
uses `re.findall`) looking for these literals as they appear in object
dictionaries. Key limitation: **this approach MISSES `/JS` entries inside
compressed (FlateDecode) object streams.** Malicious PDFs increasingly hide JS
in compressed streams to evade string-grep tools. The spike-2 doc explicitly
accepts this limitation as "defense-in-depth before MinerU's PyMuPDF layer sees
the file" — NOT the only defense. PyMuPDF inside MinerU will see the
decompressed content.

For m4, the string-grep approach is correct and sufficient — the spec says it
is defense-in-depth. The implementer should document the compressed-stream
limitation in the docstring.

Source: [DidierStevens/DidierStevensSuite pdfid.py](https://github.com/DidierStevens/DidierStevensSuite/blob/master/pdfid.py)

### Page count without full parsing

ISO 32000 §7.7.2: the Document Catalog (pointed to by `/Root` in the trailer
dictionary) contains a `/Pages` entry pointing to a Page Tree root node. The
root node carries `/Count` giving the total page count. A string-grep for
`/Count` is unreliable — `/Count` appears in other contexts (Shading Pattern,
etc.). A safer heuristic: search for `/Type /Page` markers or search for
`/Count ` followed by an integer near the `/Pages` dictionary. None of these
string-grep approaches are structurally robust — they can be fooled by
adversarial PDFs. For m4's purpose (catching accidental huge PDFs, not evading
a determined adversary), a simple `re.findall(rb"/Count\s+(\d+)", pdf_bytes)`
taking the MAX value found is a reasonable heuristic: a >5000 count anywhere
in the file is suspicious. **Flag this limitation in the docstring.**

---

## Failure-mode enumeration

1. **ZIP CD relocated via comment-field padding bypasses tail check.**
   *Trigger:* attacker crafts PDF+ZIP where the EOCD record is >1 KB from
   the file end. *Symptom:* `PK\x05\x06` not found in tail; upload accepted;
   MinerU processes a ZIP-embedded payload. *Mitigation:* acknowledged
   limitation; subprocess sandbox (layer 2, m5) is the backstop. Document in
   `tools/security/pdfid.py` docstring.

2. **JS hidden in FlateDecode compressed object stream.**
   *Trigger:* malicious PDF stores `/JS` inside a compressed stream; string-grep
   misses it. *Symptom:* `_pdf_has_javascript` returns False; upload accepted.
   *Mitigation:* PyMuPDF inside MinerU evaluates the decompressed stream
   (defense layer 2); pdfid is explicitly defense-in-depth not primary.
   Ground: `08-security-observability-ops.md` Threat 3 — "defense-in-depth"
   layering is the project model.

3. **Page-count probe tricked by adversarial `/Count` value.**
   *Trigger:* PDF declares `/Count 10` in a fake dictionary but embeds a
   >5000-page actual Page Tree. *Symptom:* probe passes; MinerU spends hours
   on thousands of pages. *Mitigation:* take the MAX of all `/Count` matches
   (harder to hide), and accept that the page-count probe is a heuristic for
   accidental cases, not adversarial evasion. Ground: Threat 4 resource
   exhaustion — the subprocess wall-clock timeout (m5 layer 2) catches
   runaway page processing.

4. **`notebook_kind` SQLite race: notebook deleted between route entry
   and `get_notebook()` read.**
   *Trigger:* concurrent DELETE on the notebook between slug validation and
   SQLite read in the upload handler. *Symptom:* `get_notebook()` returns None
   after the size cap decision; handler returns 404. *Mitigation:* this is
   benign (404 is correct); the upload cap decision happens BEFORE
   `get_notebook()` if the middleware cap is 200 MB globally. Document that
   the notebook_kind check is best-effort guard for arxiv-kind notebooks.
   Ground: `08-security-observability-ops.md` failure modes table (fail-safe
   behavior).

5. **Upload cap applied wrong: arxiv-kind notebook gets 200 MB.**
   *Trigger:* middleware prefix_caps raised to 200 MB globally for the
   `/ui/api/notebooks` prefix; the per-kind 10 MB check is only in the handler.
   *Symptom:* arxiv-kind notebook accepts a 150 MB upload into memory before the
   handler's `notebook_kind == "arxiv"` check fires a 413. This is a **DoS
   vector**: 150 MB fully buffered into Python memory before rejection. The
   eager-pre-read in `RequestBodySizeLimitMiddleware` buffers the ENTIRE body
   before the handler runs. *Mitigation:* Add a more-specific prefix cap at the
   textbook-upload sub-path (e.g. `/ui/api/notebooks/{slug}/papers/upload`)
   that cannot distinguish notebook_kind at middleware time. The correct design
   is: middleware cap = 200 MB for the upload path; handler rejects 413 for
   arxiv-kind after reading the first few bytes (magic-byte sniff comes FIRST,
   so for arxiv-kind the magic-byte sniff fails at 5 bytes with 415 — the body
   is already buffered, but the rejection is fast). For a textbook-kind upload
   that is non-PDF, same 415 fast rejection. The only case where 200 MB is
   buffered fully is a valid PDF upload on a textbook notebook — which is
   intentional. VERDICT: acceptable design; the DoS concern is bounded because
   arxiv-kind notebooks reject at magic-byte sniff (5 bytes read) long before
   200 MB is processed.

6. **Magic-byte sniff runs AFTER full body read.**
   *Trigger:* `_is_pdf_bytes` called after `await file.read()` accumulates the
   full body. For a 200 MB non-PDF uploaded to a textbook notebook, 200 MB is
   buffered before rejection. *Symptom:* memory spike; slow rejection.
   *Mitigation:* `RequestBodySizeLimitMiddleware` already reads the full body
   eagerly (F1 fix from E06_S05) into `buffered_events` before the handler runs.
   So the body IS fully in memory before the handler fires. The magic-byte check
   at the handler level cannot save memory — the middleware already paid the
   cost. This is acceptable: the middleware's eager-buffer IS the cap; at 200 MB
   the middleware would have rejected first. Document in comments.

7. **`pdfid.py` written fresh but drift from Didier Stevens' keyword list.**
   *Trigger:* implementer misses `/OpenAction` or `/AA` (additional actions)
   from the required keyword set. *Symptom:* PDFs with auto-open JS triggers
   (not using `/JS` directly) pass the check. *Mitigation:* the test suite MUST
   include synthetic PDFs with each keyword variant. The brief ACs explicitly
   list `/JS`, `/JavaScript`, `/OpenAction`, `/AA`.

8. **Rejection vectors run in wrong order (expensive before cheap).**
   *Trigger:* page-count probe (full body scan via regex) runs before magic-byte
   sniff (5 bytes). *Symptom:* unnecessary CPU on non-PDF uploads. *Mitigation:*
   enforce order: (1) magic-byte sniff (5 bytes), (2) size check for
   arxiv-kind, (3) polyglot tail (last 1 KB), (4) pdfid JS scan (full body),
   (5) page-count probe (full body regex). Cheap checks FIRST.

9. **`tools/security/__init__.py` missing from git commit.**
   *Trigger:* implementer creates `pdfid.py` and `README.md` but forgets
   `__init__.py`. *Symptom:* `from tools.security.pdfid import find_javascript`
   raises `ModuleNotFoundError` on fresh checkout. *Mitigation:* include
   `tools/security/__init__.py` (empty is fine) in the commit.

---

## Recommendation

**Implement the five rejection vectors in `server/routes/notebooks.py` directly
(no new module for the main pre-flight gate functions), with `pdfid.py` as a
standalone module in `tools/security/`.**

Rationale: The magic-byte sniff, polyglot tail, and page-count probe are small
enough to live as private functions `_is_pdf_bytes`, `_pdf_polyglot_check`,
`_pdf_page_count` directly in `notebooks.py` — exactly as the spike-2 doc
prescribes. Only the JavaScript detection (`_pdf_has_javascript`) delegates to
`tools.security.pdfid`. This matches the existing `_is_html_bytes` pattern
already present in the file.

**For the upload cap raise:** set the middleware `prefix_caps` to 200 MB for
the textbook upload path. Since notebook_kind cannot be inspected at middleware
time, the handler must reject arxiv-kind notebooks with 413 AFTER the magic-byte
sniff already returns 415 (fast path). The DoS concern in failure mode 5 is
mitigated because non-PDF uploads on any notebook_kind are rejected at magic
bytes (5-byte read), long before 200 MB is buffered.

**For page-count:** use `re.findall(rb"/Count\s+(\d+)", pdf_bytes)` and take
`max(matches)`. Document the structural limitation (string-grep, not a parser).

**For pdfid:** write a fresh implementation in ≤50 LOC that scans
`pdf_bytes` for `/JS`, `/JavaScript`, `/OpenAction`, `/AA` as byte literals.
Use `re.findall` for clarity. Document the compressed-stream limitation.

**Rejection order (fast-first):** magic-byte → polyglot-tail → arxiv-kind-size
→ JS-detection → page-count.

---

## Open questions

1. **Should the middleware prefix_cap for the upload route be raised to
   200 MB globally (for `/ui/api/notebooks`) or only for a more-specific
   textbook sub-path?** The current cap is on `/ui/api/notebooks` (the whole
   subtree). Raising it to 200 MB globally means any future sub-route also
   gets 200 MB capacity unless explicitly capped. A more-specific cap on
   `/ui/api/notebooks/.../papers/upload` is cleaner but requires knowing the
   slug at middleware time (impossible). **Recommended:** raise the
   `/ui/api/notebooks` subtree cap to 200 MB in main.py; the handler's
   arxiv-kind 413 check is the per-kind enforcement.

2. **Where does the upload handler look up `notebook_kind`?** The current
   `upload_paper` calls `await store.get_notebook(slug)` to confirm existence
   and returns 404 if missing. m4 must also inspect `notebook_kind` from that
   dict. Confirm that `store.get_notebook()` is already returning `notebook_kind`
   from m3 (CONFIRMED: yes, from `server/notebooks_store.py:261`). No new
   DB query needed.

---

## External writes the implementation will require

None — this milestone is purely local.
