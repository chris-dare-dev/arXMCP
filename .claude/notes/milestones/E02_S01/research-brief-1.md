# Research Brief 1 — E02_S01
# Theorem-aware structural chunker

---

## 1. In-codebase context

### Applicable design notes

| File | Relevance |
|---|---|
| `04-parsing-and-chunking.md` | Master spec: theorem+proof pairing (Rule 1), preamble prepend (Rule 2), chunking rules, failure modes table |
| `05-storage-and-indexing.md` | Schema for `chunks` table; dual-column `embedding_stmt`/`embedding_proof` contract; 512-tok budget; `body_tokens` field |
| `02-architecture-overview.md` | `ingest/` vs `server/` process separation; no logic in `ingest/__init__.py` |
| `08-security-observability-ops.md` | BP1 byte-identical caching requires deterministic chunk content; Threat 3 (LaTeXML subprocess isolation — already handled in E01, not this milestone) |
| `09-feature-priorities.md` | SUPERSEDED 2026-05-06; roadmap authority is now `.claude/roadmap/` |

### Load-bearing constraints (quoted verbatim)

From `04-parsing-and-chunking.md` § Rule 1:

> "Pair `theorem`, `lemma`, `proposition`, `corollary` environments with their *following* `proof` environment into a single chunk. If the proof is long (>2000 tokens), keep the statement chunk separately *and* prepend it as a header to each proof sub-chunk."

From `04-parsing-and-chunking.md` § Failure modes:

> "Every failure mode has a log line and a `parser-failures/` artifact."

From `05-storage-and-indexing.md` § Embedding strategy (updated 2026-05-06):

> "The dual encoding is now kind-gated: `embedding_stmt` (set for `kind="stmt"` chunks): preamble + statement text, ≤512 tokens. `embedding_proof` (set for `kind="proof"` chunks): preamble + statement header + proof window, ≤512 tokens with 64-token overlap."

From `05-storage-and-indexing.md` § BM25 note:

> "`body_tokens` is a space-joined token stream produced at chunk-write time by a Python regex pre-tokenizer (E02_S03) that preserves backslash tokens like `\Spec`, `mathrm_Pic`, etc."

From `08-security-observability-ops.md` § BP1:

> "Determinism over cleverness. Every byte the MCP server returns must be reproducible bit-for-bit across calls — this is what enables prompt-cache reuse across agents."

### LaTeXML HTML5 parse-tree structure (observed from ar5iv live output)

The chunker reads `var/arxmcp/corpus/parsed/<paper_id>/index.html`, produced by `latexmlc --format=html5`. DOM structure confirmed by fetching live ar5iv HTML:

- **Theorem environments** → `<div class="ltx_theorem ltx_theorem_<type>" id="<auto-id>">`. The `<type>` suffix is the LaTeX environment name in lowercase: `theorem`, `lemma`, `proposition`, `corollary`, `definition`, `remark`, `example`, `proof` (note: `proof` is NOT used for the theorem type; proof has its own class). Auto-id format: `S<N>.Thmthm<N>` (e.g. `S2.Thmthm13`).

- **Proof environments** → `<div class="ltx_proof">`, sometimes with `<div class="ltx_proof" id="...">`. Proof divs are **siblings** of theorem divs in the parent section/subsection container — NOT children of the theorem div. There is no explicit structural link in the HTML5 to associate a proof with its theorem.

- **Named theorems** (e.g. `Theorem 1.1 (Riemann–Roch)`) → the parenthetical name appears inside `<span class="ltx_tag ltx_tag_theorem">`. Extractable via `soup.get_text()` on that span.

- **Original `\label{}`** → NOT preserved in LaTeXML HTML5. The auto-generated id replaces the label. To extract the original `\label{key}` from LaTeX source, the chunker must read from `var/arxmcp/corpus/raw/<paper_id>/`. Cross-references inside the HTML use the auto-generated IDs (e.g. `href="#S2.Thmthm14"`), not the original label keys.

- **Section path** → walk ancestors from theorem div: `ltx_document > ltx_section > ltx_subsection > ltx_subsubsection`. Section titles are in `<h2 class="ltx_title ltx_title_section">`, `<h3 class="ltx_title ltx_title_subsection">`, etc.

### Input/output paths (from E01 implementation)

Input: `var/arxmcp/corpus/parsed/<paper_id>/index.html` (confirmed path from `tools/fetch_one_paper.py` and `arxiv_fetch.py`)

Output: `var/arxmcp/corpus/chunks/<paper_id>/<chunk_idx>.json` (new path, not yet created)

### Existing tools the chunker should not duplicate

`tools/arxiv_fetch.py` defines `PER_PAPER_FAILURE_EXCEPTIONS = (RuntimeError, OSError, ValueError, subprocess.TimeoutExpired, tarfile.TarError, gzip.BadGzipFile)`. The chunker exception pattern should mirror this — catch per-paper exceptions, log, continue.

---

## 2. Prior decisions and lessons

### Parser-failure log convention (commit `01c6579`)

The fix in `01c6579` ("catch per-paper exceptions in `fetch_one_paper.py` too") established the pattern: per-paper exceptions must be caught at the paper level and converted to logged outcomes, not propagated to crash the whole run. The chunker must follow this: if BeautifulSoup fails to parse a paper's HTML, log `WARNING: chunker skipped <paper_id>: <reason>` to `var/arxmcp/ops/parser-failures/` and continue to the next paper.

### Per-paper exception isolation (commit `c486b26`, `01c6579`)

`fetch_seed.py` wraps each paper's `process_paper()` call so that `PER_PAPER_FAILURE_EXCEPTIONS` never bubbles up to the main loop. The chunker's `chunk_paper(paper_id)` must be designed so the caller can wrap it in a try/except without fear of the exception type changing. Returning `[]` on failure (with a log line) is cleaner than raising.

### LaTeXML output quality variability (`04-parsing-and-chunking.md` § Failure modes)

> "LaTeXML can emit valid HTML with plain text where equations should be — exit code alone is insufficient."

The chunker should not assume well-formed HTML. Use `html.parser` or `lxml` via BeautifulSoup with error tolerance; do not crash on malformed markup.

### Content-type sniff vs. bytes sniff (commit `0280852`)

The fix "sniff tar-vs-tex from decompressed bytes, not Content-Type" illustrates the project's stance: always use the actual bytes, never trust HTTP metadata. Analogously, the chunker should not trust HTML element ordering heuristics beyond what BeautifulSoup's DOM traversal actually provides.

### BGE-M3 token budget: 512 is a design choice, not the model's hard limit

The BGE-M3 tokenizer's `model_max_length` is 8192 tokens. The 512-token ceiling is an explicit retrieval-quality decision (to avoid mean-pooling flattening over long sequences — this is what "closes H3" means per `E02-chunker.md`). The chunker must enforce this as a hard budget using `len(tokenizer.encode(text)) <= 512`, not by relying on the tokenizer to truncate.

### FLAG — Conflict: Token budget without preamble at E02_S01 time

The milestone brief requires chunks to "not exceed 512 tokens after prepend" but also defers `preamble_ref` to E02_S02 (written as `null` by E02_S01). These are contradictory: E02_S01 cannot enforce the preamble-inclusive budget without knowing the preamble.

**Recommendation:** E02_S01 enforces 512 tokens on `body_text` alone. E02_S02 is responsible for detecting and handling preamble-induced overflow (either truncating `body_text` or splitting the chunk further). The brief's acceptance criterion "no single chunk's embedding-input view exceeds 512 BGE-M3 tokens" is technically only verifiable end-to-end after E02_S02 runs. The implementer should document this explicitly in `ingest/chunker.py`.

### FLAG — Conflict: `theorem_label` from LaTeXML HTML5

The brief requires `theorem_label` containing the original `\label{key}` from LaTeX source. LaTeXML HTML5 does NOT preserve original `\label{}` values in element IDs or attributes — it replaces them with auto-generated IDs (`S2.Thmthm14`). Extracting `theorem_label` requires a secondary parse of the raw `.tex` source from `var/arxmcp/corpus/raw/<paper_id>/`.

This is in tension with the stated input: "walks the LaTeXML HTML5 parse tree." The chunker must also read `.tex` source for label extraction — or accept `null` for `theorem_label` and defer to a more complete label-extraction pass.

**Recommendation:** Read both the HTML5 parse tree AND the `.tex` source. For each theorem div's auto-id (e.g. `S2.Thmthm13`), attempt to match a `\label{}` in the surrounding .tex source context by scanning for `\label{` in the .tex near the environment. This is heuristic and will miss some cases; log misses as warnings, emit `null` for unresolvable labels.

### Proof-to-theorem pairing: sibling scan, not parent-child

Since proof divs are siblings of theorem divs in the DOM (not children), the pairing algorithm must walk all direct children of each section container: for each `ltx_proof` child, assign it to the immediately preceding `ltx_theorem` sibling in the same container. Theorems without a following proof sibling emit as `kind="stmt"` only; orphan proofs emit as `kind="proof"` with a warning log.

---

## 3. External sources

### LaTeXML 0.8.x HTML5 output format

LaTeXML source: `https://github.com/brucemiller/LaTeXML`. The HTML5 output schema is documented in the LaTeXML manual at `https://dlmf.nist.gov/LaTeXML/manual/`. Key confirmed behaviors from live ar5iv HTML inspection:

- CSS class naming: `ltx_theorem` (base) + `ltx_theorem_<envname>` (type), e.g. `ltx_theorem_theorem`, `ltx_theorem_lem`, `ltx_theorem_prop`, `ltx_theorem_defn`, `ltx_theorem_rem`, `ltx_theorem_exa`, `ltx_theorem_cor`.
- Proof class: `ltx_proof` (no secondary class for the environment type; there is only one proof environment in LaTeX).
- Theorem title span: `<span class="ltx_tag ltx_tag_theorem">` contains the display text including any parenthetical name.
- Section elements: `<section class="ltx_section">`, `<section class="ltx_subsection">`, etc. (not div).
- Proof termination (QED): may appear as `<span class="ltx_qed_square">` or similar inside the proof div.

### BGE-M3 tokenizer (HuggingFace `BAAI/bge-m3`)

Model card: `https://huggingface.co/BAAI/bge-m3`. The tokenizer is XLM-RoBERTa based. `AutoTokenizer.from_pretrained("BAAI/bge-m3")` downloads the tokenizer vocabulary without loading the 2GB model weights — this is correct per the brief. The tokenizer's `model_max_length` is 8192; the chunker must use 512 as the explicit budget ceiling and pass `max_length=512, truncation=False` to detect overflows rather than silently truncating.

Loading only the tokenizer: `AutoTokenizer.from_pretrained("BAAI/bge-m3")` without `AutoModel` (no torch weights loaded).

### BeautifulSoup4 and pyproject.toml additions

`beautifulsoup4==4.14.3` is installed locally. Use `html.parser` (stdlib). Primary selectors: `.find_all("div", class_=re.compile("ltx_theorem"))` for theorem envs; `.find_all("div", class_="ltx_proof")` for proofs. Section path from `.find_parents(["section"], class_=re.compile("ltx_(section|subsection|subsubsection)"))`.

`pyproject.toml` currently lists no runtime dependencies. This milestone requires adding `beautifulsoup4` and `transformers` (tokenizer-only; no torch). `transformers` pulls `tokenizers` (Rust-backed) and `huggingface-hub` but NOT `torch` — approximately 50–100 MB, not 2 GB.

---

## Open questions

1. **Token budget without preamble (flagged above):** Should E02_S01 enforce 512 tokens on body alone, or reserve a fixed headroom (e.g. 128 tokens) for preamble? The brief is silent on this; the implementer must choose and document.

2. **`theorem_label` extraction strategy (flagged above):** Should the chunker attempt to extract `\label{}` from the raw .tex source, or emit `null` unconditionally and defer to E10_S02? The brief says "if a theorem has a `\label{}`" — suggesting it expects extraction, but the HTML5 parse tree does not contain this information.

3. **Which theorem `kind` values to emit for unmatched environments:** The brief specifies `"definition"`, `"section"` for unmatched environments but does not enumerate all cases (lemma without proof, corollary, remark, example). Use `ltx_theorem_<type>` suffix as the `kind` value directly (e.g. `"lemma"`, `"corollary"`, `"remark"`) rather than mapping everything to `"definition"` or `"section"`.

4. **Orphan proof pairing (no preceding theorem sibling):** Some proofs appear detached from their statement (e.g. proof in an appendix far from the theorem). The brief says "immediately following" but does not define the containment scope. Recommend: scope pairing to the nearest common ancestor section; log orphans as warnings.

5. **`body_text` content for proof chunks:** Should `body_text` for `kind="proof"` chunks include a copy of the 64-token statement header, or just the proof body window? Per the brief: "preamble prepend + 64-token statement header" is the embedding-input view. The `body_text` field should store only the proof window text; the statement header is reconstructed at embedding time by E03_S01. Confirm this interpretation.

---

## External writes the implementation will require

| type | target | why |
|---|---|---|
| filesystem write | `var/arxmcp/corpus/chunks/<paper_id>/<chunk_idx>.json` (×50 papers × N chunks) | primary chunker output; local disk, gitignored |
| filesystem write | `var/arxmcp/ops/parser-failures/chunk-warnings.log` or similar | per-paper warning log consistent with E01 pattern |
| HuggingFace download (one-time) | `https://huggingface.co/BAAI/bge-m3` (tokenizer vocab only, ~5 MB) | AutoTokenizer.from_pretrained downloads vocab files on first call; cached to `~/.cache/huggingface/` |
