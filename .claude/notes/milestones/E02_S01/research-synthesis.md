# Research Synthesis — E02_S01 Theorem-aware structural chunker

Merged from `research-brief-1.md` (Researcher 1) and `research-brief-2.md` (Researcher 2). Both ran in parallel on 2026-05-07.

## 1. Load-bearing constraints (quoted verbatim)

From `04-parsing-and-chunking.md` § Rule 1:
> "Pair `theorem`, `lemma`, `proposition`, `corollary` environments with their *following* `proof` environment into a single chunk. If the proof is long (>2000 tokens), keep the statement chunk separately *and* prepend it as a header to each proof sub-chunk."

The milestone brief tightens this from 2000-token to 512-token windows with a 64-token statement header — consistent with the H3 dual-column closure.

From `04-parsing-and-chunking.md` § Failure modes:
> "Every failure mode has a log line and a `parser-failures/` artifact."

From `04-parsing-and-chunking.md` § Versioning:
> "Every chunk carries `chunker_version`. When we change chunking strategy: 1. Bump version (`v1.0` → `v1.1`)."

From `05-storage-and-indexing.md` § Embedding strategy (updated 2026-05-06):
> "The dual encoding is now kind-gated: `embedding_stmt` (set for `kind="stmt"` chunks): preamble + statement text, ≤512 tokens. `embedding_proof` (set for `kind="proof"` chunks): preamble + statement header + proof window, ≤512 tokens with 64-token overlap."

From `05-storage-and-indexing.md` § BM25:
> "`body_tokens` is a space-joined token stream produced at chunk-write time by a Python regex pre-tokenizer (E02_S03) that preserves backslash tokens like `\Spec`, `mathrm_Pic`, etc."

From `08-security-observability-ops.md` § BP1:
> "Determinism over cleverness. Every byte the MCP server returns must be reproducible bit-for-bit across calls — this is what enables prompt-cache reuse across agents."

Both researchers cite `04-parsing-and-chunking.md`, `05-storage-and-indexing.md`, `08-security-observability-ops.md` as the load-bearing notes. R2 additionally cites `03-ingestion-pipeline.md` for the parsed-output path; R1 additionally cites `02-architecture-overview.md` (no logic in `ingest/__init__.py`) and notes `09-feature-priorities.md` is SUPERSEDED.

## 2. LaTeXML HTML5 output structure (consensus)

Both researchers verified the same DOM structure by inspecting live ar5iv/arxiv.org HTML5:

- **Theorem environments:** `<div class="ltx_theorem ltx_theorem_<envname>" id="<auto-id-or-label>">`. The `<envname>` suffix matches the `\newtheorem` first-argument key — common values: `theorem`, `lemma`, `lem`, `proposition`, `prop`, `corollary`, `cor`, `definition`, `defn`, `remark`, `rem`, `example`, `exa`. Use a regex match on `ltx_theorem_*` rather than an allowlist (R2's recommendation, more robust).
- **Proof environments:** `<div class="ltx_proof">`. No `id` attribute. No environment-type subclass.
- **Sibling pairing:** Proof divs are **siblings** of theorem divs in the parent section element — NOT children. Pair each `ltx_theorem_*` div with the **next sibling** that has class `ltx_proof`.
- **Theorem display name:** Inside `<h6 class="ltx_title">` (R2) or `<span class="ltx_tag ltx_tag_theorem">` (R1) — both researchers found valid examples in different papers; the implementer should check both. Parenthetical names extractable via regex `\(([^)]+)\)`.
- **Section path:** Walk DOM ancestors via `<section class="ltx_section">`, `<section class="ltx_subsection">`, `<section class="ltx_subsubsection">` (R2: `<section>` not `<div>`). Section titles in `<h2 class="ltx_title">` etc.

## 3. Disagreement: `theorem_label` extraction strategy

**R1 position:** LaTeXML HTML5 does NOT preserve original `\label{}`. The id is auto-generated (e.g. `S2.Thmthm14`). Recommends reading the raw `.tex` source from `var/arxmcp/corpus/raw/<paper_id>/` to extract `\label{}` keys by scanning near each environment.

**R2 position:** "for labeled environments `\label{thm:rr}` LaTeXML maps the key to the element's `id` attribute (verified by inspecting arxiv.org HTML5 output)."

**Resolution (orchestrator pick):** Both are partially correct. LaTeXML emits an auto-generated id (pattern `S<N>.Thm<envname><N>`, e.g. `S2.Thmtheorem2`) when no `\label{}` is present, and incorporates the user's label key into the id (often as a suffix or with prefixing) when one is. The implementer should:

1. Read the `id` attribute from the theorem div.
2. If it matches the regex `^S\d+\.Thm\w+\d+$` (auto-generated pattern), emit `theorem_label: null`.
3. Otherwise, emit the id as-is — it carries the user's label semantics, even if LaTeXML has prefixed it.

This is a heuristic but it's bounded: false negatives (real labels misidentified as auto-generated) only impact E10_S02's dedup quality marginally; false positives (auto-IDs misclassified as labels) would be worse but the auto-pattern is distinctive. **Do NOT attempt a second-pass `.tex` source scan in this milestone** — that's a separate parser dependency the chunker shouldn't take on. If E10_S02 finds the heuristic insufficient, that's the right place to add a `.tex` scan.

## 4. Token budget conflict (R1 flag — pick a position)

R1 flags: the brief says "no single chunk's embedding-input view (preamble + body) exceeds 512 BGE-M3 tokens" but defers `preamble_ref` to E02_S02. E02_S01 cannot fully verify a preamble-inclusive budget if the preamble is null at this milestone.

**Resolution:** E02_S01 enforces 512 tokens on `body_text` alone and reserves headroom that E02_S02 must respect. Specifically:

- Statement chunks: `body_text` ≤ 512 tokens (no headroom needed; preamble is small ≤ ~200 tokens, but enforcing reservation here is brittle since preamble size is paper-dependent).
- Proof window chunks: `body_text` ≤ (512 − 64) = 448 tokens, where 64 is the reserved statement-header allotment per the brief. Window overlap = 64 tokens between consecutive windows.
- Use `len(tokenizer.encode(text, add_special_tokens=False))` for counting (NOT `tokenizer(text)["input_ids"]` which adds CLS/SEP tokens and inflates count by 2).
- The implementer must add a module-level docstring documenting that final preamble-inclusive budget verification is end-to-end with E02_S02.

This trades strict budget enforcement now for forward compatibility with E02_S02. The acceptance criterion "no single chunk's embedding-input view exceeds 512 tokens" remains technically only verifiable end-to-end after E02_S02 lands.

## 5. Implementation patterns to follow (consensus)

- **Per-paper exception isolation:** mirror `tools/arxiv_fetch.py`'s `PER_PAPER_FAILURE_EXCEPTIONS = (RuntimeError, OSError, ValueError, subprocess.TimeoutExpired, tarfile.TarError, gzip.BadGzipFile)`. The chunker's `chunk_paper(paper_id)` must catch broadly, log, and return `[]` on failure rather than raising. Caller-side wrapping in a try/except is the established pattern (commits `c486b26`, `01c6579`).
- **Parser-failure log:** `var/arxmcp/ops/parser-failures/chunk.log` in TSV format `<paper_id>\t<status>\t<elapsed_s>\t<message>` matching `fetch_seed.py`'s `seed.log`.
- **No logic in `ingest/__init__.py`** (per `02-architecture-overview.md`).
- **Determinism (BP1):** chunk output bytes must be reproducible. Sort dict keys when writing JSON. No timestamps, no UUIDs, no hashing-based sort tie-breakers in this milestone (chunk_id hash is deferred to E02_S04 — use the monotonic placeholder `arxiv:<paper_id>:idx<N>`).

## 6. Tooling additions

Both researchers agree:

- Add `beautifulsoup4` to `pyproject.toml` (no C deps; use `html.parser` backend). R2 notes `lxml` would be faster for large HTML but not required.
- Add `transformers` to `pyproject.toml` for `AutoTokenizer.from_pretrained("BAAI/bge-m3")`. This loads tokenizer vocab only (~5 MB on first call, cached to `~/.cache/huggingface/`); it does NOT load the 2 GB model weights. `transformers` pulls `tokenizers` (Rust-backed) and `huggingface-hub` but NOT `torch` (~50–100 MB total).

## 7. Open questions (deduped union)

1. **Token budget without preamble** — resolved above: enforce on body alone with documented limitation.
2. **`theorem_label` extraction** — resolved above: heuristic on auto-id pattern, no `.tex` second-pass.
3. **`kind` values for unmatched environments** — emit `kind` matching the LaTeXML subclass suffix directly (`"lemma"`, `"corollary"`, `"remark"`, `"definition"`, `"example"`) rather than collapsing to `"definition"` or `"section"`. Section chunks (top-level paragraphs not inside any theorem-like env) emit `kind="section"`.
4. **Orphan proof pairing** — pairing scope is the nearest common ancestor section. Orphan proofs (no preceding theorem sibling in the same section) emit as `kind="proof"` with `theorem_label: null` and a warning log.
5. **Proof-chunk `body_text` content** — store the proof window text alone (NOT including the 64-token statement header). The header is reconstructed at embedding time by E03_S01 from the linked `theorem_label` / paper section context. The proof chunk records its parent theorem's `theorem_label` (when extractable) for downstream resolution.
6. **HTML parsing library** — pick `beautifulsoup4` with `html.parser`. Add to `pyproject.toml`.
7. **Proof-pairing adjacency rule** — the immediately next sibling that is `ltx_proof`, ignoring text-only / whitespace siblings. If a non-proof structural sibling intervenes (e.g. another theorem div, a remark), the original theorem is unmatched (no proof chunk), and the intervening element gets its own theorem-or-proof handling.

## 8. External writes the implementation will require

| type | target | why |
|---|---|---|
| filesystem write | `var/arxmcp/corpus/chunks/<paper_id>/<chunk_idx>.json` (50 papers × N chunks) | Primary chunker output. Local disk, gitignored. |
| filesystem write | `var/arxmcp/ops/parser-failures/chunk.log` | Per-paper warning/failure log; TSV format matching `seed.log`. Local disk, gitignored. |
| filesystem write | `pyproject.toml` | Add `beautifulsoup4` and `transformers` dependencies. Local edit, committed. |
| filesystem write | `ingest/chunker.py`, `ingest/chunker_types.py`, `tests/test_chunker.py`, `tests/fixtures/chunker/<paper_id>.html` (fixture papers) | Source code + test fixtures. Local edits, committed. |
| network call (one-time, idempotent) | `https://huggingface.co/BAAI/bge-m3` (tokenizer vocab files, ~5 MB) | `AutoTokenizer.from_pretrained("BAAI/bge-m3")` downloads vocab on first call; cached locally. No API key required. R2 marked this as "None" / not-an-external-write; R1 flagged it. **Position: include as external write — first-run network access is non-trivial in air-gapped environments and the user should be aware.** Cached calls are local and idempotent. |

No git push, PR creation, infra mutation, or authenticated third-party API calls are required.
