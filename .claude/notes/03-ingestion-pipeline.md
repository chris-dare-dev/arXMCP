# 03 — Ingestion Pipeline

The corpus must arrive on the user's local disk without paying AWS, without
forking other repos, and without violating arXiv's TOS. Three sources, used in
combination:

## Source 1: Academic Torrents (the seed)

**What:** community-published torrents of arXiv bulk dumps (metadata + source
tarballs). Search Academic Torrents for "arxiv" — there are periodic dumps,
typically months stale at any given time.

**Why this is the only honest answer for the seed:**

- The `arxiv-public-datasets` project (Clement / mattbierbaum) historically
  published periodic dumps; tooling still works but expects S3 — useful for
  **parsing code** to crib, not for fetching.
- Torrents are stale by definition (typically a few months behind), but for a
  **seed** that's fine — the OAI-PMH delta channel keeps it current.
- Filtered to math.AG + math.NT + math-ph + hep-th source: a few hundred GB.
- Filtered PDF: low single-digit TB. We don't need PDF if source is available;
  source is far smaller and far higher fidelity.

**TOS note:** arXiv permits redistribution of content under the original
publication licenses (most papers are arXiv-licensed or CC-BY). Academic Torrents
hosts these legitimately. We are not redistributing — we are downloading for
local indexing. This is fine.

## Source 2: OAI-PMH (the delta channel)

**Endpoint:** `http://export.arxiv.org/oai2`

**Format:** `arXivRaw` — gives metadata including categories, abstract, authors,
version history, license. **Metadata only — no .tex, no PDF.**

**Rate limit:** ~1 request per 4 seconds, with required `from`/`until` windowing
and resumption tokens. Filter at the source via `set=math` or `set=physics:hep-th`
to avoid pulling biology and CS.

**Cadence:** nightly cron. Pull yesterday's deltas, queue the new arxiv IDs for
the source-fetch step.

**This is the durable, TOS-clean way to know what's new.** Don't try to scrape the
arxiv.org listings page; OAI-PMH is the supported channel.

## Source 3: arxiv.org `/e-print/` per-paper fetch (for new papers)

**Endpoint:** `https://arxiv.org/e-print/<paper_id>` returns the .tar.gz of the
.tex source.

**Rate limit:** 1 request per 3 seconds per IP, with explicit guidance to back
off on 503. Hard ceiling.

**Math:** for a 500K-paper backfill at 1-per-3s = 17 days continuous fetching.
**Don't try this for the seed.** Use only for the delta — a few hundred new
papers per day across our four subjects is well within rate limits.

**Politeness:** include a descriptive `User-Agent` header
(`arXMCP/0.1 (mailto:owner@example.com)`) and respect 503 backoff.

## Source 4 (citation enrichment, not corpus): INSPIRE-HEP

**Endpoint:** `https://inspirehep.net/api/literature`

**For:** hep-th + math-ph + general physics. Free, generous limits (~15 rps with
backoff), structured records with references already resolved to other arXiv IDs
and DOIs. **Citation graph backbone for the physics half of the corpus.**

**Don't try to extract `\cite{}` keys from .tex and resolve them yourself —
INSPIRE has already done that work.**

## Source 5 (citation enrichment, not corpus): OpenAlex

**Endpoint:** `https://api.openalex.org` and bulk monthly snapshots
(documented at `https://docs.openalex.org/download-all-data`).

**For:** math.AG + math.NT + general math. Free, fully open, monthly snapshot
dumps, includes citation graph (Work-to-Work edges).

**Polite pool:** include `mailto=owner@example.com` query parameter or header
to get higher limits.

**Bulk dump format:** newline-delimited JSON, gzipped, on a public CDN. Total
size for math is ~tens of GB. Download monthly, diff, apply.

## Source 6 (parser cache, not corpus): ar5iv

**Endpoint:** `https://ar5iv.labs.arxiv.org/html/<arxiv_id>` (and the successor
at `https://arxiv.org/html/<arxiv_id>` which is gradually replacing it).

**What it gives:** pre-rendered LaTeXML output as HTML5 + MathML. Macros expanded.
Cross-references resolved. **This is what we want as the primary parser path** —
ar5iv has already done the LaTeXML CPU work for ~90% of post-2007 arXiv papers.

Run our local LaTeXML only on ar5iv cache misses. Saves weeks of CPU.

## Pipeline shape

```
                                       ┌─── seed (one-time) ───┐
                                       ▼                       │
                          [ Academic Torrents download ]       │
                                       │                       │
                                       ▼                       │
                          [ Extract source tarballs ]           │
                                       │                       │
                                       ▼                       │
       ┌──────────────────────[ Per-paper job queue ]◀─── nightly delta ──┐
       │                               │                                  │
       │          ┌────────────────────┴─────────────────┐                 │
       │          ▼                                      ▼                 │
       │  [ ar5iv HTML fetch ]                  [ /e-print/ source fetch ] │
       │          │                                      │                 │
       │     hit  │  miss                                │                 │
       │          │   └─────────►  [ Local LaTeXML run ] │                 │
       │          ▼                          │           ▼                 │
       │  [ Parsed paper IR (HTML5+MathML) ]◀┘   (fallback: Nougat)        │
       │          │                                                        │
       │          ▼                                                        │
       │   [ Macro normalizer ]                                            │
       │          │                                                        │
       │          ▼                                                        │
       │   [ Chunker (theorem+proof, equations, defs, hierarchical) ]      │
       │          │                                                        │
       │          ▼                                                        │
       │   [ Embedder (self-hosted bge-m3 / e5-mistral) ]                  │
       │          │                                                        │
       │          ▼                                                        │
       │   [ LanceDB write — new version ]                                 │
       │                                                                   │
       │   [ Citation enrichment from INSPIRE / OpenAlex ─────► Kùzu ]     │
       │                                                                   │
       └──────────────────►  [ write new LanceDB dataset version;            │
                              update corpus-version.json (no symlinks) ]   │
                                    (see E04_S02 in roadmap/E04-vector-store.md)
                                                                           │
       [ OAI-PMH harvest ] ──────────────────────────────────────────────► ┘
       (nightly, /set filter, resumption tokens)
```

## Realistic timing

- **Seed (one-time):** torrent download a few hundred GB (a few hours to a day).
- **Initial parse + chunk + embed:** depends on local GPU. With one A6000 / RTX
  4090, ~1–2 days for ~200K papers using bge-m3.
- **Daily delta:** 200–500 new papers per day across our four subjects. Fetch
  + parse + embed = 1–2 hours nightly.
- **Citation graph re-sync:** monthly OpenAlex bulk diff, ~1 hour. INSPIRE
  per-paper enrichment can run continuously at 15 rps.

## What gets stored on disk

```
/var/arxmcp/
  corpus/
    raw/                   # original .tex tarballs (kept for re-parse)
    parsed/                # LaTeXML HTML5+MathML output (cached)
    chunks/                # canonical chunk JSON (content-addressable, sharded by sha256[:2])
  index/
    lancedb/
      chunks/              # single LanceDB dataset; internal versions managed by LanceDB MVCC
      corpus-version.json  # marker file: {"version": N, "chunker_version": ..., "embedder_version": ...}
      bm25/
        v1/                # BM25 index for corpus version 1 (bm25.pkl + chunk_ids.json)
        v2/
    kuzu/
      citations.kuzu       # graph DB file
    # NOTE: No manual version subdirectories (v0001/, v0002/, etc.) and no symlinks.
    # LanceDB MVCC manages corpus versions natively. See E04_S02 in roadmap/E04-vector-store.md.
  cache/
    ar5iv/                 # cached HTML responses, keyed by arxiv_id
    embeddings/            # content-hash → vector cache (sqlite)
  ops/
    ingestion.log
    parser-failures/       # papers that failed all parsers, for human review
```

Estimated total disk for v1 corpus (math.AG, math.NT, math-ph, hep-th):
- Raw .tex tarballs: ~200 GB
- Parsed HTML5+MathML: ~150 GB
- Chunks (JSON): ~30 GB
- LanceDB index (vectors + BM25): ~50–100 GB depending on embedder dim
- Kùzu graph: ~5 GB
- **Total: ~500 GB.** Comfortable on a workstation SSD.

## The %-with-source reality

Roughly 90%+ of post-2007 arXiv submissions ship .tex source. Pre-2007 submissions
often shipped only PostScript or scanned PDF; treat them as a degraded-coverage
zone. For our four subjects:

- **hep-th**: heavy use of physicist-author macros (`\slashed`, custom Feynman
  packages, `\bra`/`\ket`, undefined `\eq{}` shorthands), JHEP/PRL class files
  vendored differently every year. Expect 20–30% of papers to have nontrivial
  `\input` / `\include` chains and bundled `.sty`.
- **math.AG / math.NT**: cleaner. Heavy use of `xy`, `tikz-cd`, `amsthm` with
  redefined theorem environments. Authors who redefine `\to` because they felt
  like it.
- **math-ph**: a hybrid mess.

**Defensible v1 scope:** "1995-onward submissions with usable .tex source." Log
papers that fail all parsers in `ops/parser-failures/` and surface them in a
weekly "degraded coverage" report. Don't silently feed the agent low-confidence
Nougat output for a hep-th paper — the autoformalizer will produce nonsense and
nobody will know why.

## Non-goals for ingestion v1

- Live arXiv listings scraping (use OAI-PMH).
- Pre-2007 PostScript handling (low ROI; mark as degraded coverage).
- PDF figure extraction (separate v2 problem; see
  [09-feature-priorities.md](09-feature-priorities.md)).
- Full-text search of comments threads or blog posts about papers (out of scope).
