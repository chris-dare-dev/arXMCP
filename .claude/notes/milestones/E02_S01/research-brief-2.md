# Research Brief: E02_S01 — Theorem-aware structural chunker

## 1. In-codebase context

### Design notes that apply

**`04-parsing-and-chunking.md`** (master spec — highest relevance):
- Rule 1: "Pair `theorem`, `lemma`, `proposition`, `corollary` environments with their *following* `proof` environment into a single chunk. If the proof is long (>2000 tokens), keep the statement chunk separately *and* prepend it as a header to each proof sub-chunk." The milestone brief reduces this to 512 tokens with a 64-token statement header — consistent with the dual-column contract.
- Rule 6 chunk ID format: `arxiv:<paper_id>:<sha256(canonical_chunk_bytes)[:16]>` — E02_S01 defers this to E02_S04; the placeholder `arxiv:<paper_id>:idx<N>` is explicitly scoped here.
- Chunker versioning: "Every chunk carries `chunker_version`. When we change chunking strategy: 1. Bump version (`v1.0` → `v1.1`)."
- Failure table: "Every failure mode has a log line and a `parser-failures/` artifact." The log path from E01 is `var/arxmcp/ops/parser-failures/`.

**`05-storage-and-indexing.md`** (dual-column contract):
- "Updated 2026-05-06 (see E04_S01)… The original `embedding_prose` / `embedding_latex` dual columns are replaced by `embedding_stmt` (nullable; set for `kind="stmt"` chunks) and `embedding_proof` (nullable; set for `kind="proof"` chunks)."
- "Chunks of other kinds (section, definition) receive `embedding_stmt`; `embedding_proof` is NULL for non-proof chunks."
- H3 closure: "Closes H3 (dual 512-tok columns): by emitting separate `stmt` and `proof` chunks each budget-capped at 512 tokens, the chunker enforces that neither embedding input can overflow BGE-M3. This is where the H3 fix originates; E03_S01 and E04_S01 carry it forward."

**`03-ingestion-pipeline.md`** (paths and parser output):
- Parsed output lives at `var/arxmcp/corpus/parsed/<paper_id>/index.html` (single HTML file per paper from `latexmlc --format=html5`).
- Chunks at `var/arxmcp/corpus/chunks/<paper_id>/<chunk_idx>.json`.

**`08-security-observability-ops.md`** (BP1 caching):
- BP1 byte-identical caching requires deterministic chunk content — referenced in E02_S04 and E03_S01 as the reason `body_text` must be stable.

**`E02-chunker.md`** (roadmap spec):
- The embedding input is "preamble + body": "for `kind="stmt"`, the embedding input is `preamble_text + "\n\n" + body_text`". Preamble prepend is E02_S02; E02_S01 writes `preamble_ref: null`.
- `body_tokens` is E02_S03 scope; chunker writes `null`.
- `chunk_id` hash is E02_S04 scope; placeholder format `arxiv:<paper_id>:idx<chunk_idx>`.

**`E03-embedder.md`** (token budget enforcement):
- E03_S01 adds a downstream assertion: "logs a warning and truncates to 512 tokens rather than raising — truncation should be extremely rare if E02_S01 budget enforcement is correct." E02_S01 must enforce the budget so E03_S01 never sees overflow.

### LaTeXML HTML5 output format (from live ar5iv/arxiv.org inspection)

LaTeXML emits theorem-like environments as `<div class="ltx_theorem">` with a subclass encoding the environment type (e.g. `ltx_theorem_theorem`, `ltx_theorem_lemma`, `ltx_theorem_definition`). The class naming pattern is `ltx_theorem_<envname>` where `<envname>` matches the `\newtheorem` argument. Proof environments are `<div class="ltx_proof">`. The theorem header is in `<h6 class="ltx_title">` and contains the display label (e.g. "Theorem 3.1 (Riemann–Roch)."). The `id` attribute uses the pattern `S<section>.Thmtheorem<N>` for theorems; for labeled environments `\label{thm:rr}` LaTeXML maps the key to the element's `id` attribute (verified by inspecting arxiv.org HTML5 output). The `ltx_proof` div has no `id` attribute; it immediately follows its paired theorem div in the tree.

Sibling pairing: the proof div is a **sibling** of the theorem div in the common parent section element — not a child. The correct pairing strategy is to walk siblings and match each `ltx_theorem_*` div with the **next sibling** that has class `ltx_proof`.

### Existing tooling patterns

From `tools/arxiv_fetch.py` and `tools/fetch_seed.py`:
- Per-paper exception isolation uses `PER_PAPER_FAILURE_EXCEPTIONS = (RuntimeError, OSError, ValueError, subprocess.TimeoutExpired, tarfile.TarError, gzip.BadGzipFile)` — the chunker should extend this pattern with `except Exception` caught per paper, logged to `var/arxmcp/ops/parser-failures/`, then `continue`.
- The resilience pattern from `01c6579`: "catch per-paper exceptions in `fetch_one_paper.py` too" — this is the explicit precedent: never let one bad paper abort the batch.
- Parsed HTML is at `var/arxmcp/corpus/parsed/<paper_id>/index.html` (single file, as written by `parse_with_latexml`).
- `ingest/` directory exists with only `__init__.py` — all deliverables are new files.

## 2. Prior decisions and lessons

### Parser failure log convention
`fetch_seed.py` writes `var/arxmcp/ops/parser-failures/seed.log` in TSV format: `<paper_id>\t<status>\t<elapsed_s>\t<message>`. The chunker should log to `var/arxmcp/ops/parser-failures/chunk.log` in the same format.

### Per-paper exception isolation (01c6579)
Commit `01c6579` fixed `fetch_one_paper.py` to catch `PER_PAPER_FAILURE_EXCEPTIONS`. The chunker must do the same — wrap each call to `chunk_paper(paper_id)` in a broad `except` that logs and continues. Never re-raise from the batch loop.

### Token budget: 512 is the design choice, not a model constraint
**FLAG — potential conflict:** BGE-M3 supports up to 8192 tokens. The design note (`05-storage-and-indexing.md`) and the milestone brief both specify 512 tokens as the budget. The H3 critique established 512 as a deliberate design constraint — mean-pooling over a full 8k-token proof degrades embedding quality. The 512 limit is a **design decision** baked into the dual-column architecture, not a model hard limit. Implementer must use `AutoTokenizer` with `max_length=512` for counting purposes only, and enforce the budget at chunk-emit time.

### BeautifulSoup vs lxml
No library is specified for HTML5 parsing. `lxml` is not in `pyproject.toml`. The existing codebase uses `pathlib` and stdlib only. Recommend `beautifulsoup4` with `html.parser` (pure Python, no C dependency) for the initial implementation — but `lxml` is significantly faster for large HTML files. Neither is in `pyproject.toml` yet; the implementer must add one.

### Adjacency pairing: sibling-walk, not subtree descent
LaTeXML places the proof as a sibling of the theorem in the parent section, not nested inside it. The sibling-walk pairing approach (find next `ltx_proof` sibling after each theorem div) is correct. A naive subtree descent would fail to find proofs.

### amsthm environment names vary
Authors redefine theorem environments with `\newtheorem{thm}{Theorem}`, `\newtheorem{prop}{Proposition}`, etc. LaTeXML uses the `\newtheorem` key as the CSS class suffix. The chunker must check for `ltx_theorem_theorem`, `ltx_theorem_thm`, `ltx_theorem_lemma`, `ltx_theorem_lem`, `ltx_theorem_proposition`, `ltx_theorem_prop`, `ltx_theorem_corollary`, `ltx_theorem_cor`, `ltx_theorem_definition`, `ltx_theorem_defn`, `ltx_theorem_remark` — and any other `ltx_theorem_*` pattern. A regex match on `ltx_theorem_` prefix is more robust than an explicit allowlist.

### Theorem name extraction
The display label "Theorem 3.1 (Riemann–Roch)" is inside `<h6 class="ltx_title">`. To extract `theorem_name`, parse the parenthetical substring from this title text using a regex: `\(([^)]+)\)`. The `theorem_label` comes from the `id` attribute of the enclosing `ltx_theorem` div — LaTeXML maps `\label{thm:rr}` to `id="thm:rr"` in the HTML element.

### No `ingest/chunker.py` or `ingest/chunker_types.py` exists yet
Both are new files. The `ingest/` directory has only `__init__.py`.

## 3. External sources

**BGE-M3 tokenizer (verified):**
- Model card: `https://huggingface.co/BAAI/bge-m3`
- Tokenizer type: XLM-RoBERTa, loadable with `AutoTokenizer.from_pretrained("BAAI/bge-m3")`
- `tokenizer = AutoTokenizer.from_pretrained("BAAI/bge-m3")` loads vocab only; the full model is NOT loaded. This is safe and the correct pattern for token counting without the ~2GB model weights.
- `len(tokenizer.encode(text))` returns the token count including special tokens. The chunker should use `tokenizer(text, return_length=True)` or `len(tokenizer(text)["input_ids"])` for budgeting.
- True model max: 8192 tokens. The 512-token budget is a **project design constraint**, not a model limit.
- Dimension: 1024.

**LaTeXML HTML5 output (verified from `https://arxiv.org/html/2307.01156`):**
- Theorem div: `<div id="S2.Thmtheorem2" class="ltx_theorem ltx_theorem_definition">`
- Header: `<h6 class="ltx_title">Definition 2.2.</h6>`
- Proof div: `<div class="ltx_proof"><h6 class="ltx_title">Proof.</h6>...`
- Proof div has NO `id` attribute; theorem div's `id` maps from LaTeX label.
- LaTeXML version pinned: 0.8.8 (from manual at `https://math.nist.gov/~BMiller/LaTeXML/manual/`).

**`beautifulsoup4` (recommended HTML parser):**
- `https://pypi.org/project/beautifulsoup4/` — use `html.parser` backend (no C deps).
- `soup.find_all(class_=re.compile(r"ltx_theorem_"))` for theorem enumeration.

**`transformers` (AutoTokenizer):**
- `https://huggingface.co/docs/transformers/model_doc/auto#transformers.AutoTokenizer`
- `AutoTokenizer.from_pretrained("BAAI/bge-m3")` — loads tokenizer files only, not model weights.

---

## Open questions

1. **Which HTML parsing library?** Neither `beautifulsoup4` nor `lxml` is in `pyproject.toml`. The implementer must choose and add one. Recommend `beautifulsoup4` for zero-C-dependency simplicity; `lxml` if parse speed becomes a bottleneck on the 50-paper run.

2. **Proof pairing scope.** The milestone brief says "immediately following `\begin{proof}`." In ar5iv HTML, "immediately following" means next sibling `ltx_proof` div. But some papers have a corollary or remark between the theorem and its proof. Implementer must decide: first adjacent `ltx_proof`, or next `ltx_proof` within the same section, skipping non-proof intervening siblings?

3. **Section path extraction.** The milestone requires `section_path: ["Introduction", "§2 Main Results"]`. LaTeXML wraps sections in `<section class="ltx_section">` with `<h2 class="ltx_title">` headers. The chunker must walk the DOM ancestors of each theorem div to build this list. No precedent in the codebase — implementer must write this.

4. **Unmatched theorem (no proof) handling.** The brief says emit as `kind="stmt"` only (no proof chunk). Confirm: does `kind="stmt"` apply to unmatched theorems, or should a distinct kind (e.g. `kind="theorem_noproof"`) be used? The design note says "keep the statement chunk separately" but does not specify a separate kind. The milestone schema uses `kind="stmt"` — take this at face value and emit `kind="stmt"` for both matched and unmatched theorem statements.

None of the above are blockers — each has a clear default answer — but the implementer should document the choice in a module-level comment.

---

## External writes the implementation will require

None. All outputs are local file writes under `var/arxmcp/corpus/chunks/` and `ingest/`. No push, PR, infra mutation, or third-party API call is required. The `pyproject.toml` will need `beautifulsoup4` (or `lxml`) added, which is a local file edit.
