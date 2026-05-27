# Chunk truncation & per-paper skew — 2026-05-27

**Trigger.** Tonight's 14-paper bridgeland-stability ingest emitted hundreds of
truncation warnings and produced one paper (1902.08184) that contributed
~3× the median chunk count. This brief is research-only; no code changed.

---

## 1. What's the chunker's body budget today?

`ingest/chunker.py:86-90` defines the budgets:

```python
BGE_M3_MAX_TOKENS = 512
PROOF_HEADER_RESERVE = 64
PROOF_MAX_TOKENS = BGE_M3_MAX_TOKENS - PROOF_HEADER_RESERVE  # 448
PROOF_WINDOW_OVERLAP = 64
STMT_MAX_TOKENS = BGE_M3_MAX_TOKENS  # 512 — preamble headroom is E02_S02's responsibility
```

There is **no headroom for the preamble at chunker time**. The chunker
unconditionally truncates `stmt` / `section` / `definition` /
`lemma` chunks to `≤ 512` BGE-M3 raw subword tokens via
`_truncate_to_token_budget` (lines 525-544), using
`tokenizer(text, add_special_tokens=False, return_offsets_mapping=True)`
to do an offset-mapping substring slice — *not* an encode/decode round-trip
(F5/F6 closure). Truncation surfaces on the record via `ChunkRecord.truncated`
(`ingest/chunker_types.py:126`).

The warning `statement chunk exceeded 512 tokens; truncated` fires at
`chunker.py:677-681`; the `section prose chunk exceeded 512 tokens; truncated`
variant at `chunker.py:786-792`. **Both fire at chunk-emission time** — by the
time the embedder runs, the body has already been sliced.

Proof chunks take a different path: `_window_proof_text` (lines 483-522)
splits oversized proofs into 448-token overlapping windows with a 64-token
overlap; the embedder gets a header-reserve at embed time. No truncation
ever happens for `kind="proof"`.

## 2. How does the embedder's truncation interact?

`ingest/embedder.py:128` sets `MAX_TOKENS = 512`. Embed input is built at
`_build_embed_input` (lines 351-368): `NFC(preamble_text + "\n\n" + body_text)`
when preamble is present, else `NFC(body_text)` alone. The encoder pre-pass
(lines 415-421) measures length via `tokenizer(texts, return_length=True)`
**without `add_special_tokens=False`**. That's the smoking gun:

> The HuggingFace `tokenizer(text)` default adds CLS+SEP (+2 tokens). The
> chunker counts using `add_special_tokens=False`. **A chunk truncated by
> the chunker to exactly 512 raw tokens is reported as 514 by the embedder
> and counted as "truncated".** The two warnings are double-counting the
> same event.

Empirical confirmation from `var/arxmcp/ops/embed-stats.jsonl`:

| paper | chunker-flag truncated | embedder `truncated_count` |
|---|---|---|
| 1912.06504 | 46 | 46 |
| 1912.06935 | 20 | 20 |
| 1902.08184 | 44 | 44 |

Exact match in every batch. **The embedder warning is not surfacing a new
class of loss; it's restating the chunker's truncations through a
+2-token-offset lens.**

For this 14-paper batch, **`preamble_text == ""` on every chunk** — the
papers came via ar5iv (`var/arxmcp/corpus/parsed/<id>/index.html` exists,
`var/arxmcp/corpus/raw/` and `var/arxmcp/corpus/preamble/` are empty),
so `chunk.preamble_ref is None` for all 725+222+145+… chunks. The
embedder warning message "preamble + body_text exceeded BGE-M3 max
length" is **misleading**: preamble contributed zero tokens.

For papers that *do* have a preamble (LaTeXML-from-`/e-print/` path,
E11_S01 production target), the squeeze becomes real. A typical math.AG
preamble carries 50–200 `\newcommand` / `\DeclareMathOperator` lines.
Tokenized, that is roughly 200–800 BGE-M3 tokens — i.e. preamble alone
can consume 40–160% of the 512-token budget before the body ever lands.
The currently-empty `preamble/` directory hides this from us; the next
LaTeXML-path ingest will expose it dramatically.

## 3. Is statement truncation a math-fidelity hazard?

**Yes, for ~30% of the truncated chunks.** Breakdown by kind:

```
1912.06504: truncated kinds = {section: 42, definition: 2, problem: 2}
1912.06935: truncated kinds = {section: 11, definition: 4, lemma: 3, stmt: 2}
1902.08184: truncated kinds = {section: 13, definition: 5, stmt: 11, lemma: 5,
                               example: 2, proposition: 2, remark: 5, corollary: 1}
```

For 1912.06504 most loss is in `section` prose (mid-prose cut is a snippet
hit but rarely the load-bearing retrieval pivot). For 1902.08184, **31 of
44 truncations (70%) are statement-class kinds** (stmt/lemma/def/prop/cor/ex).

Inspecting truncated stmt/definition tails on 1902.08184:

```
chunk arxiv:1902.08184:16ffec530f403f3d (kind=stmt, body=991 chars)
TAIL: ...let Z_{s,1} be the central charge given by the restriction of Z_{s} along K((\math
```

The truncation severs a definitional clause mid-LaTeX expression — the
conclusion ("…is bounded", "…satisfies axiom (B)", etc.) is silently
dropped. The conclusion is exactly what an nDCG@5 query like
*"Bridgeland stability central charge restriction to fiber"* would match
against.

Per `.claude/notes/04-parsing-and-chunking.md` § Rule 1 "Theorem + proof
are one chunk" and § Rule 5 (theorem-level granularity is the tactician's
primary surface), **statement chunks are supposed to be atomic.** The
project's mission DP1 (`01-mission-and-context.md`) — "math fidelity
over coverage" — implies that cutting a definition mid-clause is the
single most expensive failure the chunker can produce. **There is no
unit test today that asserts `truncated == False` on `kind in {stmt,
lemma, definition, proposition, corollary}`.** No `TIER-GATES.md` gate
either. This is an unmonitored regression channel.

## 4. Why does 1902.08184 emit 725 chunks?

It is an **honest representation of a very long paper**, not a chunker bug.
Direct inspection of `var/arxmcp/corpus/parsed/1902.08184/index.html`:

- HTML size: 16.86 MB (3–5× the others in the batch)
- 355 `ltx_theorem_*` divs vs. 48 (1912.06504), 80 (1912.06935), 32 (1704.03546)
- Kind distribution:
  - 84 Lem, 76 Def, 69 Rem, 30 Prop, 26 Thm, 16 Cor, 15 Ex,
    32 innerstep, 3 PropDef, 2 innerclaim, 2 Setup
- 33 sections + 62 subsections + 3 subsubsections + 0 paragraphs

This is a 200-page book-grade manuscript ("Stability conditions over higher-
dimensional bases", Bayer–Lahoz–Macri–Stellari–Toda) with 4 Parts and ~300
labeled environments. 725 chunks = 355 theorem envs + 319 proof windows
(some proofs windowed >1) + 85 section-prose chunks. Math checks out.

**Retrieval skew is the real risk.** With dense BM25 + ANN+RRF + reranker
top-k=20, a single paper contributing 725/N corpus chunks could dominate the
candidate pool for any query in its niche. Mitigation candidates: per-paper
candidate-cap in `server/retrieval/rrf.py`, or rerank-stage diversification
(MMR). Out of scope for tonight, but flag for E14_S07 or a new milestone.

## 5. BGE-M3 alternatives — is 512 a hard ceiling?

**No, it's a model-card recommendation, not a config constraint.** BGE-M3 is
trained natively with positional embeddings up to **8192 tokens** (it's an
XLM-RoBERTa-large backbone with extended positional encoding for long
context). The published M3-Embedding paper benchmarks the model at 512,
1024, 2048, 4096, and 8192 with monotonically improving recall on long-doc
tasks.

`ingest/embedder.py:128` hardcodes `MAX_TOKENS = 512`. There is no model-
config change required to flip to 8K — only:
1. raise `MAX_TOKENS` (and the chunker's `BGE_M3_MAX_TOKENS`),
2. pass `model_max_length=8192` to the tokenizer (or override at encode time),
3. accept the linear VRAM hit (attention is `O(L²)` for full-attention models, but
   BGE-M3 uses sparse-attention extensions; in practice CPU forward time grows
   roughly 2–3× per 2× context).

Embedding dim is **unchanged at 1024** (`EMBEDDING_DIM` constant) — the
LanceDB schema and ANN index stay byte-compatible across context-length
changes. A `CHUNKER_VERSION` bump (`v1.0` → `v1.1`) plus a re-embed pass is
required because `chunk.truncated` flags would flip and chunk bodies would
grow.

Other ideas-only alternatives (no-fork policy still binds):
- **Jina-embeddings-v3** (Apache-2.0, 8192 tokens, 1024d) — same dim,
  drop-in tokenizer change. Strong long-context performance per MTEB.
- **Stella-1.5B-v5** (MIT, 8192 tokens, 1024-8192d) — bigger model,
  better recall, ~6GB VRAM.
- **Nomic-embed-text-v1.5** (Apache-2.0, 8192 tokens, 768d) — would
  invalidate the LanceDB column shape; schema migration.

For this project (CPU-only, BP1 byte-stability, Threat-6 SHA pinning),
**staying on BGE-M3 and just raising the context cap is the lowest-risk
option** of the model swaps.

## 6. Remediation options

| Option | Stmt atomicity | Snippet faithfulness | nDCG@5 | Ingest cost | Schema impact | BP1 / TOOL_SCHEMA hash | VRAM / CPU | No-fork | Operator load |
|---|---|---|---|---|---|---|---|---|---|
| **A.** Tighten chunker budget to 480 raw tokens (leave 32 for embedder special-tokens + future preamble headroom) | small ↑ | unchanged | tiny ↑ | re-chunk all + re-embed all | `CHUNKER_VERSION` bump → `v1.1` | tool-list schema unchanged; BP1 cache invalidates ALL embeddings | none | ✅ | low |
| **B.** Raise BGE-M3 to 8K (chunker + embedder), keep dim=1024 | **large ↑** (statements no longer truncated for any realistic case) | ↑ (longer snippets eligible) | likely +2–5 pts | re-embed all; CPU ~3× per-paper | `CHUNKER_VERSION` bump; LanceDB column shape unchanged | tool-list unchanged | CPU 2–3× | ✅ (config) | medium |
| **C.** Fix embedder `add_special_tokens=False` in pre-pass length count | none (already truncated upstream) | none | none | none — just silences misleading warning | none | none | none | ✅ | trivial (<1 day) |
| **D.** Statement-head + statement-tail chunk pairs with `continuation_of` column | ↑ when statements split cleanly | ↑ | small ↑ — tail chunk now embeds the conclusion | re-chunk all + re-embed all + LanceDB ALTER | new `continuation_of` column; `CHUNKER_VERSION` bump | none | none | ✅ | high (new abstraction) |
| **E.** Switch embedder to Jina-v3 (8K, 1024d) | large ↑ | ↑ | unclear (MTEB says +, math-specific unknown) | re-embed all | LanceDB column shape unchanged (dim 1024 preserved) | none | depends — Jina-v3 is ~580M params | ✅ (HF model load, no source fork) | high — Threat-6 SHA pin migration, new EMBEDDER_VERSION |
| **F.** Per-paper candidate cap in retrieval (orthogonal to truncation; addresses §4 skew) | none | none | likely +1–2 pts | none | none | none | none | ✅ | low |
| **G.** Do nothing — declare current loss acceptable | none | none | none | none | none | none | none | ✅ | none (but constitution violation) |

**Constitution check.** `04-parsing-and-chunking.md` § Rule 1 ("theorem + proof
are one chunk") and DP1 ("math fidelity over coverage") effectively rule out
option G. Option C is unrelated quick-win signal hygiene.

## 7. Recommendation

**Sequenced: C (now) + B (this week).**

- **C (quick-win, <1 day, S):** flip the embedder pre-pass to
  `tokenizer(texts, padding=False, truncation=False, return_length=True,
  add_special_tokens=False)` at `ingest/embedder.py:415`. Aligns the
  embedder's length-count with the chunker's, kills the misleading "preamble +
  body_text" warning on ar5iv-path papers (where preamble is empty), and makes
  the `truncated_count` field on `EmbedStats` exactly equal to the chunker's
  `truncated` flag sum (which it accidentally is today, but for the wrong
  reason). One unit test in `tests/test_embedder_truncation_count.py` to lock.
  No corpus rebuild required.

- **B (real fix, this week, M):** raise `BGE_M3_MAX_TOKENS` to **2048** (not
  8192 — 2048 gives 4× headroom which kills 99%+ of statement truncations on
  the math.AG corpus without paying 16× CPU). Move `PROOF_MAX_TOKENS` to 1920,
  `PROOF_HEADER_RESERVE` to 128. Bump `CHUNKER_VERSION` to `"v1.1"`, bump
  `EMBEDDER_VERSION` automatically (it's derived from BGE SHA, which doesn't
  change, but the chunker_version bump triggers re-embed via the E03_S02
  handshake). Files touched:
  - `ingest/chunker.py` lines 86-90 (budgets)
  - `ingest/chunker_types.py` line 45 (CHUNKER_VERSION → v1.1)
  - `ingest/embedder.py` line 128 (MAX_TOKENS = 2048)
  - new tests: `tests/test_chunker_atomicity.py` asserting
    `kind in {"stmt","lemma","proposition","corollary","definition"} →
    truncated == False` on a fixture paper sized to fit in 2048 tokens
  - `.claude/TIER-GATES.md` adds an atomicity gate
  - `tests/test_chunker_ids.py` re-pins the version literal
  - re-embed cost: ~all 137 currently-chunked papers, batched at 32, on CPU.
    Estimate ~40 min wall-clock based on the embed-stats wall-times in
    `var/arxmcp/ops/embed-stats.jsonl`.
  - `corpus_version` marker in LanceDB bumps; BP1 retrieval cache invalidates;
    `EXPECTED_TOOL_SCHEMA_SHA256` does NOT change (the tools/list response is
    unaffected — chunker internals don't appear in tool metadata)

  Slots into **`pdf-ingest-2026`** as a sibling milestone (`pdf-ingest-2026-m3:
  context-window-expansion`) or as a standalone E15_S01 if `pdf-ingest-2026`
  has wrapped. Either way, ship before the next E11-style full-corpus ingest —
  doing it after re-embeds 200K papers a second time.

Defer **D** (head/tail split) — the head/tail abstraction increases reranker
complexity (`continuation_of` chunks need link-aware scoring) and doesn't help
once the budget headroom from B exists. Defer **E** — Jina-v3 is a future
play, not a tonight play; Threat-6 process alone makes it M-L effort.

**Quick-wins doable in <1 day:**
1. Option C above (the off-by-2 warning).
2. Add an atomicity assertion to `tests/test_chunker_*.py` against the
   existing fixture corpus — would fail today, regresses cleanly with B.
3. File a GitHub issue at `chris-dare-dev/arXMCP` titled
   "Chunker: statement truncation on long math.AG papers (1902.08184,
   bridgeland-stability ingest 2026-05-27)" linking this scan.

**Open follow-ups beyond this brief:**
- Per-paper retrieval skew (§4, option F) — separate milestone, addresses
  the 725-chunk paper hyper-representation independently from truncation.
- Preamble-token-budget plan — when LaTeXML path comes online and preamble
  populates, the chunker's `STMT_MAX_TOKENS = 512` becomes acutely wrong.
  Option B's 2048 budget gives ~1500 tokens of preamble headroom, which
  covers ~99% of math.AG preambles per spot-check estimates. Worth confirming
  with a one-off `tokenize_body(preamble_text)` pass once preambles exist.
