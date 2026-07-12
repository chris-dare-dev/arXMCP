# Session Handoff — 2026-06-11 (bridgeland-stability ingest)

This document captures the complete context of the bridgeland-stability ingest work so a
future session can resume with full understanding. It supersedes all prior HANDOFF.md
content.

> **2026-07-12 addendum (paper-metadata finalize session).** This snapshot was
> written 2026-06-11 but sat uncommitted until the paper-metadata-m2 finalize
> commit landed it. Overtaken since writing: **§13.4 `get_paper` metadata is
> SHIPPED** — paper-metadata-m1 landed the per-notebook store + backfill CLI
> (127/127 bridgeland-stability papers hydrated), and paper-metadata-m2 wired
> the handler (`metadata_status="hydrated"`; title/abstract/authors wrapped in
> `<retrieved_chunk>` delimiters). The rest of the snapshot (notebook state,
> MinerU/textbook recipes, environment notes) remains the newest handoff
> content.

---

## 1. What this work is about

The user (cedare96@gmail.com, a researcher studying Bridgeland stability on algebraic
varieties) is building a **local-first arXMCP research corpus** specifically for
Bridgeland stability / derived categories / Fourier-Mukai transforms. This is distinct
from the main arXMCP codebase work — it is **content ingestion into the running server**,
not code development.

The core problem was: how do you get dense math textbooks (hundreds of pages of LaTeX-heavy
PDFs) and arXiv paper PDFs into the arXMCP corpus so they are searchable via `search_papers`?
The HTML-based pipeline that works for arXiv papers was insufficient for textbooks.

---

## 2. The two notebooks

### `bridgeland-stability` (arxiv-kind, HTML)
- **Location:** `var/arxmcp/notebooks/bridgeland-stability/`
- **Kind:** `arxiv` — papers fetched via ar5iv (HTML5+MathML), chunked by the LaTeXML-aware HTML
  chunker (`ingest/chunker.py`)
- **Current state:** 125 papers / 12,557 chunks in LanceDB (as of 2026-06-11)
- **papers.txt:** 175 lines (includes duplicates/ordering; the LanceDB has 125 unique papers)
- **How to start server against this:** `$env:ARXMCP_NOTEBOOK = "bridgeland-stability"; python -m server.main`
- **BM25 index version:** v1186 (built last time the corpus was written)

The 175 papers include 18 papers added at the end of the prior session from this URL list:
```
https://ar5iv.labs.arxiv.org/html/1412.0612
https://ar5iv.labs.arxiv.org/html/hep-th/0212218
https://ar5iv.labs.arxiv.org/html/2407.20862
https://ar5iv.labs.arxiv.org/html/1106.5217
https://ar5iv.labs.arxiv.org/html/1504.01177
https://ar5iv.labs.arxiv.org/html/1509.04608
https://ar5iv.labs.arxiv.org/html/2006.00756
https://ar5iv.labs.arxiv.org/html/1811.10592
https://ar5iv.labs.arxiv.org/html/1201.4911
https://ar5iv.labs.arxiv.org/html/2007.00044
https://ar5iv.labs.arxiv.org/html/1811.03267
https://ar5iv.labs.arxiv.org/html/1907.12578
https://ar5iv.labs.arxiv.org/html/2112.00923
https://ar5iv.labs.arxiv.org/html/1710.06692
https://ar5iv.labs.arxiv.org/html/2006.08410
https://ar5iv.labs.arxiv.org/html/2307.00815
https://ar5iv.labs.arxiv.org/html/1909.02985
https://ar5iv.labs.arxiv.org/html/1203.0316
```
(One URL `0811.2435` was a dup and skipped automatically.)

### `bridgeland-stability-pdfs` (textbook-kind, PDF)
- **Location:** `var/arxmcp/notebooks/bridgeland-stability-pdfs/`
- **Kind:** `textbook` — papers parsed via MinerU (PDF→markdown) or LaTeXML source render
- **Current state:** 716 chunks in LanceDB (as of 2026-06-11), 20 paper_ids

#### Breakdown by paper_id (chunk counts):
```
hep-th/0403166                          72   (hand-rendered from source .tex)
textbook:derived-categories-p141-160    57   (Huybrechts Fourier-Mukai, pp.141-160)
textbook:derived-categories-p061-080    53   (Huybrechts pp.61-80)
textbook:derived-categories-p161-180    49   (Huybrechts pp.161-180)
textbook:derived-categories-p201-220    49   (Huybrechts pp.201-220)
textbook:derived-categories-p021-040    47   (Huybrechts pp.21-40)
textbook:derived-categories-p041-060    46   (Huybrechts pp.41-60)
textbook:derived-categories-p121-140    45   (Huybrechts pp.121-140)
textbook:derived-categories-p001-020    43   (Huybrechts pp.1-20)
textbook:derived-categories-p081-100    42   (Huybrechts pp.81-100)
textbook:derived-categories-p181-200    41   (Huybrechts pp.181-200)
textbook:derived-categories-p221-241    33   (Huybrechts pp.221-241)
2506.21995                              31   (MinerU markdown-chunked)
textbook:derived-categories-p101-120    31   (Huybrechts pp.101-120)
1611.02087                              21   (MinerU markdown/HTML)
0912.0043                               20   (MinerU)
textbook:dc-lecture-notes               12   (Catuneanu lecture notes)
2602.24016                               9   (MinerU)
1802.01134                               8   (MinerU)
2201.03654                               7   (MinerU)
```

#### What's on disk but NOT in LanceDB:
- `1404.3143` — Kuznetsov "Semiorthogonal decompositions in algebraic geometry". Has:
  - `parsed/1404.3143/1404.3143/auto/1404.3143.md` — clean MinerU markdown (46 chunks available)
  - `parsed/1404.3143/index.html` — LaTeXML HTML (0 chunks via HTML chunker)
  - LanceDB has 0 chunks for this paper_id
  - **STATUS: Can be ingested right now via `--chunker markdown`** (verified: 46 chunks)
  - See ingest command in §5a

---

## 3. The three milestones shipped in this session

All three are fully committed and pushed to `origin/main` (HEAD = `488cdb7`).

### `textbook-md-heading-sectioning-m1` (commits `243019f/3f88625/ba0d6e4`)
**Problem:** MinerU markdown has ATX headings (`##`, `###`) but `_build_latex_wrapper`
in `ingest/textbook_renderer.py` wrapped the markdown verbatim — LaTeXML never saw
`\section{}` commands, so the rendered HTML had no `ltx_section` divs, and the HTML
chunker produced 0 chunks for EVERY real MinerU-parsed PDF.

**Fix:** Added `_convert_markdown_headings_to_latex()` in `textbook_renderer.py`:
- Converts `## heading` → `\subsection{heading}` (math-aware title escaping)
- Added `_HEADING_PROSE_ESCAPE` dict including `"$": "\\$"` (F1: lone `$` in heading
  would open math mode)
- Added `_MATH_SPAN_RE` to detect balanced `$...$` spans and route them out of prose
  escaping

### `textbook-render-robustness-m1` (commits `75dcd19/682aa6f/0932065`)
**Problem 1:** LaTeXML hardcoded 300s timeout killed math-dense PDF renders. The 241-page
Huybrechts book (`2506.21995` segment) took >300s in LaTeXML and lost output.

**Fix:** `ARXMCP_LATEXML_TIMEOUT_S` env var in `tools/arxiv_fetch.py`, default 300s,
range [30, 1800]. The server correctly rejects this var (it's an ingest-tool var, like
`ARXMCP_CONTACT_EMAIL`). A hint is added to `server/main.py::_KNOWN_INGEST_ENV_VARS`.

**Problem 2:** The `_sanitize_math_balance` function in `textbook_renderer.py` tried to
fix unclosed `\begin{array}` by APPENDING `\end{array}` at the end of the body — but
this landed in text mode outside any math environment, re-creating the fatal LaTeXML error.

**Fix:** Rewrote sanitizer as a stack pass that DROPS both orphaned closers AND unclosed
openers; NEVER synthesizes/appends a token.

### `textbook-markdown-chunker-m1` (commits `6048df0/d713763/488cdb7`)
**Problem:** Even with heading sectioning fixed, the HTML path was too coarse (one chunk
per `ltx_section` div). For Huybrechts (241 pages), HTML path gave 39 chunks total and
dropped sections whose LaTeXML render overflowed the 100-error abort.

**Fix:** New module `ingest/textbook_markdown_chunker.py` — chunks MinerU markdown
DIRECTLY (no LaTeXML needed):
- Section hierarchy from ATX headings → `section_path` + `chapter` breadcrumb
- Blank-line paragraph blocks with `$$`-atomicity guard (math spanning blank lines stays in one chunk)
- Token-budget grouping (target 600, max 1500 tokens)
- Oversized blocks split at sentence boundaries, never truncated
- Proof/stmt kind classification → correct `embedding_proof`/`embedding_stmt` routing
- F4 fix: section breadcrumb folded into chunk_id hash so "Proof. Omitted." under two
  different theorems gets distinct IDs (without this, second copy was silently dropped)
- F3 fix: `\$` (escaped dollar) excluded from parity count; `_MAX_MERGE_BLOCKS=50` cap
  prevents runaway merge on stray unbalanced `$`

**Result:** Huybrechts 241 pages → 536 chunks (vs 39 HTML, 2 segments lost).

**New wiring:** `--chunker {html,markdown}` flag added to `tools/notebook_textbook_ingest.py`.
Default is still `html` for backward compatibility.

**Key store.py change:** `"mineru+markdown"` added to `_ALLOWED_PARSER_USED` frozenset in
`ingest/store.py` — WITHOUT THIS, `write_chunks` raises `ValueError` on every markdown chunk.

---

## 4. The Huybrechts book — what it is and how it was ingested

**Book:** Daniel Huybrechts, *Fourier-Mukai Transforms in Algebraic Geometry*, Oxford
University Press. This is the backbone reference for all Bridgeland stability work and the
user described it as "crucial to introductory level understanding" and "the backbone of
most other papers."

**Source PDF:** `var/textbook-staging/H.pdf` (241 pages, obtained from Ludwig-Maximilians
lecture page — GITIGNORED, not committed)

**Segmentation:** poppler `pdfseparate` split into 12 ~20-page PDF segments:
```
var/textbook-staging/H_p001-020.pdf  ... H_p221-241.pdf
```
poppler available at `C:/Users/cedar/AppData/Local/Programs/MiKTeX/miktex/bin/x64/pdfseparate.exe`

**Parse strategy:** MinerU (not LaTeXML) — each segment was parsed via:
```powershell
$env:MINERU_VENV = "C:/Users/cedar/venvs/mineru"
& "$env:MINERU_VENV/Scripts/mineru" parse H_pNNN-NNN.pdf -o parsed_output -m auto
```
MinerU venv: `C:/Users/cedar/venvs/mineru`

The per-segment parsed output goes into:
`var/arxmcp/notebooks/bridgeland-stability-pdfs/parsed/textbook_derived-categories-pNNN-NNN/`

**Segment → paper_id mapping:**
```
H_p001-020.pdf  → textbook:derived-categories-p001-020
H_p021-040.pdf  → textbook:derived-categories-p021-040
... etc.
```

**Ingest command used (for all 12 segments):**
```powershell
uv run python tools/notebook_textbook_ingest.py bridgeland-stability-pdfs `
  --paper-id textbook:derived-categories-p001-020 `
  --paper-id textbook:derived-categories-p021-040 `
  --paper-id textbook:derived-categories-p041-060 `
  --paper-id textbook:derived-categories-p061-080 `
  --paper-id textbook:derived-categories-p081-100 `
  --paper-id textbook:derived-categories-p101-120 `
  --paper-id textbook:derived-categories-p121-140 `
  --paper-id textbook:derived-categories-p141-160 `
  --paper-id textbook:derived-categories-p161-180 `
  --paper-id textbook:derived-categories-p181-200 `
  --paper-id textbook:derived-categories-p201-220 `
  --paper-id textbook:derived-categories-p221-241 `
  --chunker markdown
```
Each segment takes ~1-2 minutes (BGE-M3 embed).

**IMPORTANT LIMITATION:** The 12 segments are INDEPENDENT paper_ids. There is no
cross-segment section continuity — a section that spans page 40 and page 41 is split
across `p021-040` and `p041-060`. Within each segment, section breadcrumbs are correct.
This is accepted for now and documented in the module docstring.

---

## 5. Immediate actionable tasks for the next session

### 5a. Ingest `1404.3143` via markdown chunker (EASY — 2 minutes)

This paper was initially abandoned because the HTML chunker gave 0 chunks. It has been
verified (2026-06-11) that the markdown chunker yields **46 chunks**. The paper is
Kuznetsov's ICM survey "Semiorthogonal decompositions in algebraic geometry" — highly
relevant content.

```powershell
cd "C:/Users/cedar/Documents/Personal Projects/Source Code/arXMCP"
uv run python tools/notebook_textbook_ingest.py bridgeland-stability-pdfs `
  --paper-id 1404.3143 `
  --chunker markdown
```

This will bring LanceDB from 716 → ~762 chunks.

### 5b. Consider re-ingesting low-chunk papers with markdown chunker

Papers with suspiciously few chunks were ingested with the HTML chunker:
- `2201.03654`: 7 chunks (may have very few `ltx_section` divs in HTML)
- `1802.01134`: 8 chunks
- `2602.24016`: 9 chunks

To re-chunk with markdown (adds new chunks alongside old ones — idempotent):
```powershell
uv run python tools/notebook_textbook_ingest.py bridgeland-stability-pdfs `
  --paper-id 2201.03654 --paper-id 1802.01134 --paper-id 2602.24016 `
  --chunker markdown
```

Note: This ADDS new markdown chunks alongside the existing HTML chunks. They coexist
(different chunk_ids, different chunker_version). For a clean slate, the LanceDB table
would need to be dropped and rebuilt — not done here.

### 5c. Add more textbooks or arXiv PDFs

The workflow for any new textbook PDF is:
1. Split into ~20-page segments with `pdfseparate`
2. Parse each segment with MinerU into `var/arxmcp/notebooks/bridgeland-stability-pdfs/parsed/`
3. Ingest with `uv run python tools/notebook_textbook_ingest.py ... --chunker markdown`

### 5d. Verify retrieval quality

Start the server and test that the chunked content is actually retrievable:
```powershell
Remove-Item Env:ARXMCP_CONTACT_EMAIL -ErrorAction SilentlyContinue
$env:ARXMCP_NOTEBOOK = "bridgeland-stability-pdfs"
uv run python -m server.main
```
Then query via `search_papers` with queries like "Fourier-Mukai functor" or
"stability condition" to verify the 716 chunks are searchable.

---

## 6. Architecture decisions made — don't revisit without cause

1. **Two separate notebooks, not one.** `bridgeland-stability` (HTML arXiv papers) and
   `bridgeland-stability-pdfs` (PDF textbooks) are separate slugs. This was intentional
   — different `source_kind`, different chunking pipeline, different retrieval quality.
   They can be queried together by running the server twice with different `ARXMCP_NOTEBOOK`.

2. **Markdown chunker is additive.** The HTML chunker (`chunk_textbook`) is NOT changed.
   The `--chunker markdown` flag opts in. Default remains `html` for backward compatibility.
   This means you can re-chunk any paper with either path without touching the other.

3. **Per-segment paper_ids for books.** Rather than one `textbook:huybrechts` paper_id
   for the whole book, each 20-page segment is a separate paper_id. This was chosen for
   practical reasons (MinerU segment-by-segment parse, memory limits) and is visible in
   the LanceDB `paper_id` column. The alternative (concatenate all segments into one
   markdown then chunk) would give unified section_path breadcrumbs but requires more
   careful stitching. Not worth changing now.

4. **No-LaTeXML path for math-dense books.** The HTML path with LaTeXML is too fragile
   for textbooks: 300s timeout, 100-error abort, flat-doc output for article-class.
   For any new textbook PDF, default to `--chunker markdown` from the start.

5. **`hep-th/0403166` hand-rendered.** This paper's PDF could not be parsed by MinerU
   (too many `^`/`_` in text mode causing LaTeXML abort). The fix was to fetch the
   `.tex` source from arXiv, stub the missing `shadow.sty` package, and run
   `latexmlc --timeout=1800 --path=.` directly. The resulting HTML is at
   `parsed/hep-th_0403166/index.html` and gave 72 chunks.
   
   **Recipe for future hand-renders:**
   ```powershell
   # Fetch source .tex from arXiv
   # Create shadow.sty with: \providecommand{\shabox}[1]{\fbox{#1}}
   # Run in the source dir:
   & "C:/Strawberry/perl/site/bin/latexmlc.BAT" --timeout=1800 --path=. main.tex `
     --dest=index.html --format=html5
   ```

---

## 7. Key files changed in this session

| File | What changed |
|---|---|
| `ingest/textbook_renderer.py` | Added `_convert_markdown_headings_to_latex()`, math-aware escaping, rewritten `_sanitize_math_balance` (stack-based, no synthesis) |
| `ingest/textbook_markdown_chunker.py` | NEW — markdown-native chunker, `chunk_textbook_markdown()` |
| `ingest/store.py` | Added `"mineru+markdown"` to `_ALLOWED_PARSER_USED` |
| `tools/notebook_textbook_ingest.py` | Added `--chunker {html,markdown}` flag |
| `tools/arxiv_fetch.py` | Added `ARXMCP_LATEXML_TIMEOUT_S` configurable timeout |
| `server/main.py` | Added `ARXMCP_LATEXML_TIMEOUT_S` to `_KNOWN_INGEST_ENV_VARS` |
| `tests/test_textbook_markdown_chunker.py` | NEW — 22 tests for the markdown chunker |
| `tests/test_textbook_renderer.py` | Extended with 16 new tests for heading conversion |
| `tests/test_arxiv_fetch.py` | New `TestLatexmlTimeoutConfig` class (7 tests) |
| `tests/test_server_startup.py` | Added `test_latexml_timeout_env_var_rejected` |
| `var/arxmcp/notebooks/bridgeland-stability/papers.txt` | Added 18 new paper IDs (gitignored data) |

---

## 8. How to verify current state from scratch

### Check git state
```powershell
cd "C:/Users/cedar/Documents/Personal Projects/Source Code/arXMCP"
git log --oneline -6
# Should see: 488cdb7, d713763, 6048df0 (markdown chunker milestone)
#             0932065, 682aa6f, 75dcd19 (render robustness milestone)
git status
# Should be clean except: .claude/agent-memory/ modified (normal), var/ untracked (normal)
```

### Check chunk counts
```powershell
uv run python -c "
import lancedb, collections
for slug in ['bridgeland-stability', 'bridgeland-stability-pdfs']:
    db = lancedb.connect(f'var/arxmcp/notebooks/{slug}/lancedb')
    tbl = db.open_table('chunks')
    t = tbl.to_arrow()
    pids = t.column('paper_id').to_pylist()
    c = collections.Counter(pids)
    print(f'{slug}: {len(tbl)} chunks, {len(c)} papers')
"
```
Expected: `bridgeland-stability: 12557 chunks, 125 papers`
Expected: `bridgeland-stability-pdfs: 716 chunks, 20 papers` (762 if 1404.3143 ingested)

### Run test suite
```powershell
uv run python -m pytest --tb=no -p no:warnings -q
```
Pre-existing failures (Windows-only, all documented in CLAUDE.md §3):
- `tests/tools/test_notebook_scripts.py` — POSIX symlink tests (3 failures)
- `tests/tools/test_validate_notebook_fixtures.py::TestHappyPath` — shimura notebook
  fixture missing on this machine (2 failures)
All other tests should pass (2100+ passing).

### Verify markdown chunker works
```powershell
uv run python -c "
from ingest.textbook_markdown_chunker import chunk_textbook_markdown
chunks = chunk_textbook_markdown('bridgeland-stability-pdfs', '1404.3143')
print(f'1404.3143: {len(chunks)} chunks')  # Should be 46
chunks2 = chunk_textbook_markdown('bridgeland-stability-pdfs', 'textbook:derived-categories-p001-020')
print(f'Huybrechts p001-020: {len(chunks2)} chunks')  # Should be 43
"
```

---

## 9. Known issues and pitfalls

### P1: `1404.3143` still has 0 chunks in LanceDB (easy fix)
The markdown chunker was shipped AFTER the paper was declared a "casualty". The markdown
chunker now handles it fine (46 chunks). Run the ingest command in §5a.

### P2: Some arXiv PDFs got very few HTML chunks
Papers `2201.03654` (7), `1802.01134` (8), `2602.24016` (9) were ingested via the HTML
chunker. They may benefit from re-ingesting with `--chunker markdown`. The `write_chunks`
function uses `merge_insert` (idempotent) so old HTML chunks remain alongside new markdown
ones — they coexist and both get searched. For a clean-slate rebuild, drop and recreate
the LanceDB table.

### P3: Huybrechts cross-segment section discontinuity
The 12 segments are independent paper_ids. A chapter spanning pages 38-42 is split across
`p021-040` and `p041-060` with no shared `section_path`. This is accepted — BGE-M3
embeddings are semantic, not structural.

### P4: MinerU grandchild process on Windows
MinerU 3.x spawns an internal FastAPI server as a grandchild. On Windows, `os.killpg`
is not available. If MinerU hangs during a parse, the orphaned process keeps a lock on
`var/arxmcp/notebooks/bridgeland-stability-pdfs/parsed/<id>/` and subsequent runs fail
with permission errors. Workaround:
```powershell
Get-Process | Where-Object { $_.CommandLine -match 'mineru' -or $_.Path -match 'mineru' } | Stop-Process -Force
```

### P5: LaTeXML 600s internal timeout vs ARXMCP_LATEXML_TIMEOUT_S
`ARXMCP_LATEXML_TIMEOUT_S` controls the Python subprocess timeout. But LaTeXML itself
has a hardcoded internal 600s timeout that fires independently. For math-dense segments,
use `--chunker markdown` to bypass LaTeXML entirely.

### P6: GPG signing broken on this workstation
`git config commit.gpgsign=true` is set but no GPG key exists in keyring. All commits
land unsigned. User has explicitly approved. NEVER use `--no-gpg-sign` or `--no-verify`.

### P7: `ARXMCP_CONTACT_EMAIL` must NOT be set when running the server
The server rejects this env var on startup. Unset before starting:
```powershell
Remove-Item Env:ARXMCP_CONTACT_EMAIL -ErrorAction SilentlyContinue
```

### P8: `test_validate_notebook_fixtures` failures are pre-existing Windows failures
Not regressions — the shimura notebook doesn't exist on this machine.

### P9: Use `uv run python -m pytest` not bare `pytest`
The system `pytest` picks up wrong Python. Always prefix with `uv run`.

### P10: RLIMIT_AS warning on Windows is normal
Any process using `ingest/textbook_parser.py` emits:
```
textbook_parser: RLIMIT_AS cap not enforceable on platform 'win32'; the 1800s wall timeout is the only memory backstop.
```
This is a WARN log, not an error. Expected behavior on Windows (CLAUDE.md gotcha #9).

---

## 10. Environment details (Windows workstation)

- **OS:** Windows 11 Home 10.0.26200
- **Python:** 3.12.x via uv, `.venv/` in project root
- **uv:** Available on PATH — `uv run python -m pytest` is the canonical test runner
- **MinerU venv:** `C:/Users/cedar/venvs/mineru`
  - Binary: `C:/Users/cedar/venvs/mineru/Scripts/mineru.exe`
  - Activate: `& "C:/Users/cedar/venvs/mineru/Scripts/Activate.ps1"`
- **LaTeXML (`latexmlc`):** `C:/Strawberry/perl/site/bin/latexmlc.BAT`
  - Has own internal 600s abort timeout
- **poppler (`pdfseparate`):** `C:/Users/cedar/AppData/Local/Programs/MiKTeX/miktex/bin/x64/pdfseparate.exe`
- **GPG:** Configured but no key — commits are unsigned (approved by user)

---

## 11. The ingest pipeline for new PDFs (recipe)

For any new PDF textbook to add to `bridgeland-stability-pdfs`:

### Step 1: Split PDF into ~20-page segments
```powershell
$pdf = "path/to/book.pdf"
$total_pages = 200  # adjust
$seg_size = 20
for ($start = 1; $start -le $total_pages; $start += $seg_size) {
    $end = [Math]::Min($start + $seg_size - 1, $total_pages)
    $label = "p{0:000}-{1:000}" -f $start,$end
    & "C:/Users/cedar/AppData/Local/Programs/MiKTeX/miktex/bin/x64/pdfseparate.exe" `
      -f $start -l $end $pdf "var/textbook-staging/book_$label.pdf"
}
```

### Step 2: Parse each segment with MinerU
```powershell
$slug = "bridgeland-stability-pdfs"
$nb_parsed = "var/arxmcp/notebooks/$slug/parsed"
$book_prefix = "my-book"  # change per book
foreach ($seg in Get-ChildItem "var/textbook-staging/book_p*.pdf") {
    $label = $seg.BaseName -replace 'book_',''  # e.g. "p001-020"
    $paper_id = "textbook:${book_prefix}-${label}"
    $flat_id = $paper_id -replace ':', '_' -replace '/', '_'
    $out_dir = "$nb_parsed/$flat_id"
    New-Item -ItemType Directory -Force $out_dir | Out-Null
    & "C:/Users/cedar/venvs/mineru/Scripts/mineru" parse $seg.FullName -o $out_dir -m auto
}
```

### Step 3: Ingest via markdown chunker
```powershell
# Build paper_id list from what was parsed
$paper_ids = Get-ChildItem "var/arxmcp/notebooks/bridgeland-stability-pdfs/parsed" |
  Where-Object { $_.Name -match "^textbook_my-book" } |
  ForEach-Object { $_.Name -replace '_', ':', 1 }  # first underscore back to colon
  
$args_list = $paper_ids | ForEach-Object { "--paper-id", $_ }
uv run python tools/notebook_textbook_ingest.py bridgeland-stability-pdfs @args_list --chunker markdown
```

---

## 12. Related staging artefacts (gitignored, on disk)

Files in `var/textbook-staging/` (GITIGNORED):
- `H.pdf` — original 241-page Huybrechts PDF
- `H_p001-020.pdf` through `H_p221-241.pdf` — 12 segments (can be regenerated from H.pdf)
- `ingest_book.py` — operator script that drove the Huybrechts ingest
- `segment_parse.py` — single-segment parse driver
- `book_ingest.log` — ingest log (all 12 segments completed)
- `book_parse.log` — MinerU parse log
- `ingest_paper_ids.txt` — the 12 paper_ids

These are staging artefacts. The parsed markdown under `var/arxmcp/notebooks/bridgeland-stability-pdfs/parsed/` is the canonical on-disk state.

---

## 13. What has NOT been done yet

1. **Retrieval quality evaluation.** The eval harness (`make eval`) exists but the
   curated 20-query fixture for Bridgeland stability content hasn't been labeled.
   This is the natural next step after the corpus is complete.

2. **Cross-notebook querying.** No server-level "query both notebooks at once."
   The server is configured to one notebook at a time via `ARXMCP_NOTEBOOK`.

3. **BM25 index for `bridgeland-stability-pdfs`.** Notebook retrieval is currently
   dense-only for textbook notebooks (per `notebook-retrieval-m2 AC2`). BM25 over
   textbook chunks would help with theorem-name lookup but is not yet implemented.

4. **`get_paper` metadata.** `get_paper` MCP tool returns NULL for `authors`, `title`,
   `abstract`, `year`, `categories` — no `papers` metadata table yet (known stub,
   CLAUDE.md §7).

5. **Ingest 1404.3143 into LanceDB.** 46 markdown chunks are ready but not yet embedded
   and written. See §5a.

---

## 14. Commit history for this session's work

```
488cdb7  chore(notes): finalize textbook-markdown-chunker-m1 state -> complete
d713763  rect(ingest): close F1-F5,F7 from textbook-markdown-chunker-m1 critique
6048df0  feat(ingest): markdown-native textbook chunker (textbook-markdown-chunker-m1)
6e9634c  Merge branch 'main' of https://github.com/chris-dare-dev/arXMCP
0932065  chore(notes): finalize textbook-render-robustness-m1 state -> complete
682aa6f  rect(ingest): close F1-F5 from textbook-render-robustness-m1 critique
75dcd19  feat(ingest): configurable latexml timeout + array sanitization (textbook-render-robustness-m1)
ba0d6e4  chore(notes): finalize textbook-md-heading-sectioning-m1 state -> complete
3f88625  rect(ingest): close F1-F4 from textbook-md-heading-sectioning-m1 critique
243019f  feat(ingest): markdown heading -> latex sectioning (textbook-md-heading-sectioning-m1)
```

All 9 commits are unsigned (GPG key missing — approved by user). All pushed to `origin/main`.

---

*Handoff written 2026-06-11. HEAD = `488cdb7`.*
