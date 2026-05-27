# Preamble extraction without raw .tex — research brief (2026-05-27)

## Observed symptom

Tonight's bridgeland-stability notebook run ingested 14 papers via the
ar5iv-only path (`tools/notebook_fetch.py` → `tools/notebook_ingest.py` →
`ingest/bulk_ingest.py`). Confirmed in
`var/arxmcp/ops/parser-failures/preamble.log`:

```
1912.06504 fail 0.0 raw .tex source not found at .../corpus/raw/1912.06504; run tools/fetch_seed.py first
1912.06935 fail 0.0 raw .tex source not found at .../corpus/raw/1912.06935; run tools/fetch_seed.py first
```

The directory `var/arxmcp/corpus/raw/` contains **zero** paper directories;
`var/arxmcp/corpus/parsed/` contains **137**. Every ar5iv-only paper in the
local corpus has triggered the F3 fallback in
`ingest/chunker.py:899-902` (`preamble_doc = _resolve_preamble_doc(...) → None`),
making this structural rather than a one-off. The log is now 5379 lines long.

## 1. What the preamble actually does downstream

Three distinct consumers reference the per-paper preamble:

1. **`chunk_id` hash input.** `ingest/chunker.py:1016-1040`
   computes `arxiv:<paper_id>:<sha256(preamble_text + NFC(body_text))[:16]>`.
   Empty-preamble fallback is documented in lines 1031-1034: "The hash
   then depends only on `body_text`, which still keeps the chunk_id
   content-addressable and stable across re-runs of the same paper."

2. **The `preamble_ref` LanceDB column.** `ingest/schema.py:126-128`:
   `pa.field("preamble_ref", pa.utf8(), nullable=True)` — explicitly
   nullable. Only metadata; no retrieval handler filters or joins on it
   today.

3. **The embedder input.** `ingest/embedder.py:351-368` (`_build_embed_input`)
   prepends `preamble_text + "\n\n"` to `body_text` before tokenization.
   F3 fallback at line 366: `preamble_text + "\n\n" + body_text if
   preamble_text else body_text` — drops the prefix entirely when
   empty. The "preamble + body_text exceeded BGE-M3 max length"
   warning at lines 1019-1024 confirms the preamble is real text fed
   to BGE-M3, not just a hash component.

4. **`get_definitions` MCP tool.** `ingest/index_definitions.py:266`
   (`load_preamble(paper_id)`) — papers with no `preamble.json` produce
   zero definition rows. `server/handlers/definitions.py:21-23`
   already documents "empty result, not an error" for this case.

## 2. How load-bearing is the preamble for math fidelity?

`.claude/notes/04-parsing-and-chunking.md:83-89` calls preamble
prepending "the single biggest retrieval-quality lever **after macro
expansion**." That qualifier is doing decisive work. The constitution
was authored before E11_S01's ar5iv-first ladder shifted the parser
mix; on the ar5iv path, **macro expansion has already happened**.

Empirical verification on `var/arxmcp/corpus/parsed/1912.06504/index.html`
(2026-05-27 fetch, 6 MB, 2023 `<math>` elements):

- Count of literal `newcommand` / `DeclareMath` / `\def` /
  `\let` strings in the body: **0** (LaTeXML consumed every one).
- 1791 `<math alttext="..."` payloads inspected; all carry
  **fully-expanded** LaTeX:
  `\Omega\colon\Gamma\to\mathbb{Q}`,
  `H^{*}(X,\mathbb{C})`,
  `\Gamma\cong\mathbb{Z}^{\oplus n}`. Never `\AA`, `\Hom`, or any
  author-local macro shorthand.
- 79 `ltx_ERROR undefined` spans, all for `\newaliascnt` /
  `\aliascntresetthe` (preamble-only ceremony, irrelevant for math
  fidelity).

The chunker's `_element_text` in `ingest/chunker.py:314-348` extracts
text by replacing each `<math>` tag with its `alttext` wrapped in
`$...$`. Therefore the `body_text` going to BGE-M3 already contains
expanded LaTeX. The preamble, when present, adds raw `\newcommand{\AA}
{\mathcal{A}}` literals to the front. **These tokens are not what
appears in any chunk body the embedder sees**, so dense retrieval
gains essentially nothing from them. BM25, similarly: `body_tokens`
are tokenized from the chunk body via `ingest/tokenizer.py`, not from
the embed_input string.

So: per-paper preamble was load-bearing for the **local-LaTeXML
fallback path** where author macros remained in `body_text`; on the
**ar5iv-cached path** it is largely cosmetic for retrieval quality.
Where it remains genuinely load-bearing is `get_definitions` — a
notebook agent asking "what does `\AA` mean in this paper?" gets a
useful answer only with `preamble.json`.

## 3. Can `\newcommand`s be recovered from ar5iv HTML?

No, not generally. LaTeXML evaluates `\newcommand` / `\def` /
`\DeclareMathOperator` at parse time and inlines every invocation into
MathML + `alttext`. The HTML contains no `<head>` comment dump of
the source preamble; only **undefined** macros leak through as
`ltx_ERROR undefined` spans (which is the wrong direction — we want
to know what `\AA` expanded to, not which macros LaTeXML failed
to resolve). A heuristic scrape of ar5iv HTML for preamble macros
would be brittle and would not recover the user-defined symbol table
that `get_definitions` exposes.

## 4. Cost of also fetching raw .tex via arXiv `/e-print/`

For 14 papers at `POLITENESS_SLEEP_SECONDS = 3.0`
(`tools/arxiv_fetch.py:35`): **~42 s wall sleep + 14 downloads × few
hundred KB**. A typical arXiv tarball is well below the 100 MB Threat
7 cap (`tools/arxiv_fetch.py:70`). The existing pattern in
`tools/fetch_seed.py` shows the politeness contract is already proven
out: User-Agent template, 503 backoff with retry-after honor,
optional SSL pinning, tar extraction with safe-paths.

**Threat-model impact.** Reading
`.claude/notes/08-security-observability-ops.md:87-98` (Threat 7), the
mitigations are identical to ar5iv:
- TLS verification on by default,
- optional CA pinning via the same `ssl_context` arg,
- 100 MB content-length cap (already enforced in
  `arxiv_fetch.fetch_eprint:268-284`).

`export.arxiv.org` is in the same trust domain as `ar5iv.labs.arxiv.org`
— if either is compromised we have bigger problems. The
`fetch_eprint` path does **not** invoke LaTeXML; it only downloads
and extracts the tarball, then `extract_preamble` operates on the
raw `.tex` string. No subprocess sandbox needed for the preamble
extraction itself — the macro regex scan is pure Python.

## 5. Could the contract be relaxed instead?

Yes — supported by the constitution. `chunk_id` stability is per
corpus-version (LanceDB MVCC; `corpus-version.json`). Empty-preamble
chunks don't collide with prior-version chunks; the chunker's
`_compute_chunk_id` already documents the empty-preamble path as a
first-class fallback. The schema column is already nullable.
`server/handlers/definitions.py:21-23` already returns "empty result,
not an error" for missing preambles.

What the constitution does **not** yet address explicitly: that the
ar5iv path makes the preamble much less retrieval-relevant than note
04 implies. Note 04 was authored against the local-LaTeXML path. The
acceptance criterion implicitly violated today is the spirit of
04:Rule-2 — "Two papers using `X` to mean different things now embed
differently because their preambles differ" is no longer true when
both papers are ar5iv-only and use the same `\AA` shorthand resolved
to the same `\mathcal{A}` in `alttext`. (In practice the new claim
holds anyway: their MathML and `alttext` already differ because the
underlying author intent is different — so retrieval quality is not
actually degraded.)

## Remediation options

| | Math fidelity | Throughput | Threat surface | Schema/corpus_version | BP1 cache | Op load |
|---|---|---|---|---|---|---|
| **A**. Add `/e-print/` raw-tex fetch to `notebook_fetch.py` before ingest | + (recovers `get_definitions` symbol table for ar5iv papers) | -42 s/14 papers; -3 s per future single-paper add | reuses existing `fetch_eprint`; no new code | none (chunk_id flips from empty-preamble to populated-preamble for these papers, but this is per-paper and bounded — same effect as ingesting them later under a different corpus version) | none (no tool schema change) | low — extends an existing tool by one call |
| **B**. Probe ar5iv for raw .tex | n/a — ar5iv does not expose `.tex` source (HTML-only by design) | n/a | n/a | n/a | n/a | rejected |
| **C**. Scrape preamble heuristically from ar5iv HTML | marginal (recovers only undefined-macro names from `ltx_ERROR` spans — the wrong direction) | minor | none | none | none | high (brittle; per-LaTeXML-version drift) |
| **D**. Bless empty-preamble as principled; add `preamble_source` column | 0 (no behavior change) | 0 | none | **adds nullable column → chunker_version bump → full re-embed of every existing paper** | tool schema unchanged, but `chunker_version` ripple affects E03_S02 re-embed driver | medium |
| **E**. Combined: do A now; also add a Tier-2 `preamble_source` provenance column later if/when notebook agents need to distinguish | + | -42 s | reuses existing | none for option A; column add deferred | none for now | low |

A few more observations on each:

- **Option A** is the closest fit to the constitution as written.
  Files touched: `tools/notebook_fetch.py` (one new helper call),
  possibly `tools/_notebook_common.py` for a shared `fetch_raw_tex`
  helper. Tests: extend `tests/test_notebook_fetch.py` with a
  mocked `fetch_eprint` to assert raw .tex is materialized before
  ingest. `ARXMCP_CONTACT_EMAIL` becomes mandatory for notebook ingest
  (it was previously only needed for `fetch_seed.py`); document in
  `tools/notebook_fetch.py` docstring and the `make` target wrapper.
  Failure-mode: an arXiv 503 must not abort the notebook ingest —
  treat raw-tex miss the same way ar5iv treats LaTeXML miss
  (skip-and-log into `preamble.log`, continue with empty preamble).

- **Option D** is tempting but the schema bump is expensive. A new
  `preamble_source` column under E04 MVCC needs a `chunker_version`
  bump (so existing rows get sentinel values on read), which cascades
  through E03_S02's re-embed driver (`ingest/re_embed.py`) — a full
  corpus re-pass. Not warranted for what would be a debug-only column.

- **Option C** was inspected directly: zero `newcommand`/`def` literals
  appear in `var/arxmcp/corpus/parsed/1912.06504/index.html`. The
  `ltx_ERROR undefined` spans surface only the **failures** to resolve,
  not the resolutions themselves. Discarded.

## Recommendation: **Option A**, scoped narrowly

Extend `tools/notebook_fetch.py` so it also fetches raw `.tex` via
`tools.arxiv_fetch.fetch_eprint(...)` for any paper that ar5iv served.
The new step writes to `var/arxmcp/corpus/raw/<paper_id>/` so the
existing `ingest/preamble.py` short-circuits to its happy path
without modification.

**Effort:** S (~½ day).

**Files touched:**
- `tools/notebook_fetch.py` — call `fetch_eprint` after each `try_cache`
  hit; respect the 3 s politeness budget by combining with the
  ar5iv politeness boundary (3 s is per-request to `export.arxiv.org`,
  not to ar5iv).
- `tools/_notebook_common.py` — new `fetch_raw_tex_if_missing(paper_id)`
  helper wrapping `fetch_eprint` with skip-and-log semantics.
- `tools/notebook_fetch.py` docstring — note that
  `ARXMCP_CONTACT_EMAIL` is now required.

**Tests:**
- `tests/test_notebook_fetch.py` — assert raw-tex fetch invoked after
  ar5iv hit, mocked `urllib.request.urlopen`.
- `tests/test_notebook_fetch.py` — assert 503/timeout on `/e-print/`
  does not abort the notebook run (treated as preamble-miss).

**No BP1 schema rehash needed** — the MCP tool surface is unchanged.

**No `corpus_version` ripple needed** — the next `notebook_ingest`
will pick up the now-populated `preamble.json` and re-chunk under a
new chunk_id (because `_compute_chunk_id` is preamble-sensitive),
which is exactly the LanceDB MVCC behavior the chunker already pins.

**Roadmap slotting:** new milestone `notebook-preamble-recovery-m1`
under the `plans/textbook-ingest-roadmap.md` umbrella (notebook ingest
is the same surface area) **or** a one-off `chore(notebook):` triple
without a roadmap entry given the S-effort.

## Acceptance criteria currently violated

- `.claude/notes/04-parsing-and-chunking.md:83-89` Rule 2: "Per-paper
  preamble prepended to every chunk." For 137 ar5iv-only papers in the
  current corpus, the prepended preamble is empty. The note's
  qualifier "after macro expansion" partly excuses this on the ar5iv
  path, but a strict reading is violated.

- `.claude/notes/05-storage-and-indexing.md:37-46`: the design
  contract describes `preamble` as a non-null column. The shipped
  schema relaxed this to nullable; the relaxation is documented in
  schema.py line 127 ("NULL when preamble extraction failed (F3
  fallback)") but not surfaced in note 05.

- `get_definitions` MCP tool returns `{definitions: [], total: 0,
  index_status: "absent"}` for every ar5iv-only paper. This is the
  one **user-facing** consequence of the gap.

## Quick-wins doable in < 1 day

1. Implement Option A (~½ day).
2. Add a `make ingest-recover-preambles` target that walks the current
   `var/arxmcp/corpus/parsed/` directory tree, identifies any paper
   missing a `preamble.json`, and back-fills via `fetch_eprint` +
   `extract_preamble`. One-shot recovery for the 137 already-ingested
   ar5iv papers without re-running ingest.
3. Add a daily-metrics counter: `preamble_missing_papers_total` against
   the parsed-paper count. Surfaces in
   `tools/daily_metrics_report.py` and gives an operator signal that
   would have caught tonight's regression on day one.
4. Update `.claude/notes/04-parsing-and-chunking.md` Rule 2 with a
   one-paragraph addendum noting that on the ar5iv path, MathML
   `alttext` already carries macro-expanded LaTeX, so the
   preamble's retrieval contribution is mostly via `get_definitions`
   rather than via embedder input — this clarifies intent for future
   maintainers.

## Open issues at chris-dare-dev/arXMCP

None of the six existing issues (#1–#6) touch the preamble path.
This gap is unfiled. Filing as `notebook-preamble-recovery` would
be appropriate when the change lands.
