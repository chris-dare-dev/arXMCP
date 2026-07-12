---
spike_id: "source-truth-spike-1"
date: "2026-07-12"
roadmap_track: "R1-source-truth"
assumption_tested: >-
  must — The arXiv metadata API returns usable license URIs for the corpus's
  ID shapes (new-style, old-style, versioned).
injection_attempts: 0
verdict: "fails-as-scoped"
---

# source-truth-spike-1 — arXiv license-URI coverage via the Atom client

## Question (roadmap acceptance criterion, `.claude/roadmap-briefs/R1-source-truth.md`)

> Given a mixed 30-paper sample (new-style, old-style, versioned ids) drawn from both
> live notebooks, when license URIs are fetched via the `tools/_arxiv_api.py` Atom
> client, then per-ID-shape license-URI coverage and the `license_status=unknown`
> count are recorded, and a projected >20% fail-closed rate on bridgeland-stability
> is flagged to the owner before any backfill.

## Headline result

**0 of 30 sampled papers (0%) carry any license-bearing field in the Atom
`/api/query` response.** This is not a sampling artifact: an exhaustive scan of
every distinct XML tag and every `<link rel=...>` value across the full 45,927-byte
response found **no `arxiv:license` element and no `rel="license"` link anywhere in
the feed**, for any of the 30 entries, across a submission-date range of 1994–2026.
The `license_status=unknown` count is **30/30**. Projected fail-closed rate on
bridgeland-stability: **100%**, far exceeding the brief's 20% owner-escalation
threshold — **flagged below**.

A bounded follow-up probe of arXiv's **OAI-PMH** endpoint (`export.arxiv.org/oai2`,
`GetRecord`/`metadataPrefix=arXiv`) for one of the same 30 papers **does** return a
`<license>` element with a real, dereferenceable URI. So the "must" assumption fails
**as scoped to the Atom client**, but arXiv as a source still carries license data —
just via a different endpoint than `tools/_arxiv_api.py` currently implements. See
Step 3 and Recommendation.

---

## Step 1 — the 30-paper sample

Drawn from `var/arxmcp/notebooks/bridgeland-stability/papers.txt` (bare-ID lines
only, `#`-comment and blank lines skipped) and
`var/arxmcp/notebooks/fourier-duality/papers.txt`. 20 papers from
bridgeland-stability, 10 from fourier-duality.

**Note on the brief's premise:** the brief text estimated bridgeland-stability at
"~200 bare IDs, 33 old-style with `/`". Empirically re-counted via grep against the
live file: **142 bare IDs total (127 new-style + 15 old-style)**. The old-style count
used below (8 drawn from bridgeland-stability, of 15 available) reflects the actual
file content, not the brief's estimate — noted here so the discrepancy doesn't get
silently lost.

| # | Requested ID | Shape | Notebook | Atom-resolved to |
|---|---|---|---|---|
| 1 | `0708.2247` | new-style | bridgeland-stability | `0708.2247v1` |
| 2 | `1203.4613` | new-style | bridgeland-stability | `1203.4613v2` |
| 3 | `1301.6968` | new-style | bridgeland-stability | `1301.6968v4` |
| 4 | `2303.07061` | new-style | bridgeland-stability | `2303.07061v4` |
| 5 | `1905.00748` | new-style | bridgeland-stability | `1905.00748v3` |
| 6 | `2411.18554` | new-style | bridgeland-stability | `2411.18554v2` |
| 7 | `2505.03433` | new-style | bridgeland-stability | `2505.03433v1` |
| 8 | `2305.17213` | new-style | bridgeland-stability | `2305.17213v4` |
| 9 | `2412.08531` | new-style | bridgeland-stability | `2412.08531v1` |
| 10 | `2407.18229` | new-style | bridgeland-stability | `2407.18229v2` |
| 11 | `2203.17148` | new-style | bridgeland-stability | `2203.17148v3` |
| 12 | `2402.07154` | new-style | bridgeland-stability | `2402.07154v3` |
| 13 | `1709.03377` | new-style | fourier-duality | `1709.03377v1` |
| 14 | `1803.01964` | new-style | fourier-duality | `1803.01964v2` |
| 15 | `1409.6128` | new-style | fourier-duality | `1409.6128v3` |
| 16 | `math/0212237` | old-style | bridgeland-stability | `math/0212237v3` |
| 17 | `math/0307164` | old-style | bridgeland-stability | `math/0307164v2` |
| 18 | `alg-geom/9410026` | old-style | bridgeland-stability | `alg-geom/9410026v1` |
| 19 | `alg-geom/9606006` | old-style | bridgeland-stability | `alg-geom/9606006v5` |
| 20 | `hep-th/0002037` | old-style | bridgeland-stability | `hep-th/0002037v4` |
| 21 | `math/0001043` | old-style | bridgeland-stability | `math/0001043v2` |
| 22 | `math/9809114` | old-style | bridgeland-stability | `math/9809114v2` |
| 23 | `hep-th/0212218` | old-style | bridgeland-stability | `hep-th/0212218v3` |
| 24 | `math-ph/0005032` | old-style | fourier-duality | `math-ph/0005032v1` |
| 25 | `math/0311369` | old-style | fourier-duality | `math/0311369v1` |
| 26 | `2006.10956v1` | versioned (new-style+v1) | fourier-duality | `2006.10956v1` |
| 27 | `2309.07644v1` | versioned (new-style+v1) | fourier-duality | `2309.07644v1` |
| 28 | `0911.1734v1` | versioned (new-style+v1) | fourier-duality | `0911.1734v1` |
| 29 | `1911.11718v1` | versioned (new-style+v1) | fourier-duality | `1911.11718v1` |
| 30 | `0903.3845v1` | versioned (new-style+v1) | fourier-duality | `0903.3845v1` |

Shape split: **15 new-style, 10 old-style, 5 versioned**. Notebook split: 20
bridgeland-stability, 10 fourier-duality.

## Step 2 — fetch + raw-feed inspection

Single request via `tools._arxiv_api.build_id_list_url()` + `_fetch_url()`
(politeness contract honored — one batched request, polite User-Agent, no loop):

```
GET https://export.arxiv.org/api/query?id_list=<30 comma-joined ids>&start=0&max_results=30
```

Response: 45,927 bytes, **30/30 entries resolved** (0 arXiv error entries — every
requested id, including all 15 old-style and all 5 versioned ids, resolved cleanly).
Response order does **not** match request order (arXiv's `id_list` API reorders);
matched back to the requested set by normalized id (via
`extract_paper_id_from_abs_url`) — confirmed a clean 1:1 bijection, no drops, no
duplicates, no extras.

Per the brief, `parse_atom_metadata`'s `PaperMetadata` dataclass
(`tools/_arxiv_api.py:254-273`) has no license field, so the raw XML was inspected
directly for every possible license carrier:

- `<arxiv:license>` element (namespace `http://arxiv.org/schemas/atom`) — **absent**
- `<link rel="license" href="...">` — **absent**
- any other `license`/`rights`-named field — **absent**

Exhaustive check: enumerating every distinct XML tag name appearing anywhere in the
45,927-byte response yields exactly 17 tags — `arxiv:comment`, `arxiv:doi`,
`arxiv:journal_ref`, `arxiv:primary_category`, `author`, `category`, `entry`,
`feed`, `id`, `link`, `name`, `opensearch:itemsPerPage`, `opensearch:startIndex`,
`opensearch:totalResults`, `published`, `summary`, `title`, `updated` — no
`arxiv:license` among them. Every `<link rel="...">` value in the feed is either
`alternate` (abs-page) or `related` (PDF) — `license` never appears. `grep -i
"license|rights"` over the raw file: **zero matches**.

### Per-ID-shape license-URI coverage

| Shape | N with license URI | N total | Coverage |
|---|---|---|---|
| new-style | 0 | 15 | 0% |
| old-style | 0 | 10 | 0% |
| versioned | 0 | 5 | 0% |
| **Total** | **0** | **30** | **0%** |

`license_status=unknown` count: **30 / 30**.

## Step 3 — Atom carries nothing, so: OAI-PMH bounded probe

Per the brief's contingency, one bounded request to arXiv's OAI-PMH endpoint for a
paper **already in the 30-sample** (`2006.10956`, requested above as
`2006.10956v1`, versioned/fourier-duality — same underlying paper, so this is a
direct same-paper Atom-vs-OAI-PMH comparison, not a different random probe):

```
GET https://export.arxiv.org/oai2?verb=GetRecord&identifier=oai:arXiv.org:2006.10956&metadataPrefix=arXiv
```

Response (1,834 bytes, saved to `raw_oai.xml`) **does** carry a `<license>` element
inside the `arXiv` metadata block:

```xml
<license>http://arxiv.org/licenses/nonexclusive-distrib/1.0/</license>
```

This is a real, dereferenceable license URI (arXiv's default blanket non-exclusive
distribution license — the same paper carries a `math.GR` `<setSpec>` and full
author/title/abstract/category metadata alongside it). Screened for prompt-injection
content per the untrusted-content policy (both `raw_atom.xml` and `raw_oai.xml`) —
none found; `injection_attempts: 0`.

**Finding: Atom API (`/api/query`, what `tools/_arxiv_api.py` implements today):
no license, 0/30. OAI-PMH (`/oai2`, `GetRecord`/`metadataPrefix=arXiv`, a
different arXiv endpoint not yet implemented in this repo): license present, 1/1
tested.**

**Recommendation for source-truth-e1's license-hydration source:** hydrate
`documents.license URI` (R1 brief KR2) from arXiv's **OAI-PMH** endpoint, not the
existing Atom `id_list` client. This requires a new client (or an additive OAI-PMH
function alongside `build_id_list_url`/`parse_atom_metadata` in
`tools/_arxiv_api.py`, following the same `defusedxml` + polite-User-Agent +
`_fetch_url`-style pattern) — `parse_atom_metadata` itself cannot be patched to
recover a field the Atom feed never sends. Note OAI-PMH is per-record
(`GetRecord`) or per-set/date-range (`ListRecords`) rather than an arbitrary
id-batch endpoint like `id_list`, so the m1 backfill CLI's request shape will need
to loop per-paper (or use `ListRecords` with `resumptionToken` paging) rather than
reusing the single-batched-request pattern this spike used for Atom — a fetch-cost
tradeoff worth surfacing to the owner before m1 implementation, alongside the
license-coverage flag below.

## Projected fail-closed rate on bridgeland-stability — OWNER FLAG

The brief's threshold: *"if >20% of the Bridgeland notebook fails closed, surface
to owner before backfill."*

- Sampled bridgeland-stability subset (20 of the 30 papers: 12 new-style + 8
  old-style): **0/20 (0%) have a license URI via Atom → 20/20 (100%) would fail
  closed** under the R1 KR3 "unknown license fails closed (300-char truncation)"
  policy if license were sourced from the Atom client alone.
- This is not merely a per-paper stochastic result that could vary across the
  notebook's other ~122 unsampled papers: the 0% rate is explained by a
  **schema-level absence** (the Atom response for these 30 entries — spanning
  1994 to 2026 submission dates — never contains an `arxiv:license` element or
  `rel="license"` link at all, confirmed by the exhaustive 17-tag enumeration
  above), not by these particular 30 papers happening to lack a license. The
  projection to the full ~142-paper notebook is therefore a structural claim, not
  just an extrapolated sample statistic — though it has only been verified
  live for a superset drawn from the notebook, not the notebook's every row.

**>>> 100% ≫ 20% — FLAG TO OWNER: if source-truth-e1's license hydration (m1) uses
only the existing Atom client, deploying the R1 KR3 fail-closed policy
(`unknown → 300-char truncation`) would truncate the full body of every chunk in
both live notebooks (bridgeland-stability AND fourier-duality — the fourier-duality
subsample also showed 0/10) on the very next `get_chunk` call after cutover. This
is a full-corpus regression, not a partial degradation, and per the brief's own
documented escape hatch ("the notebook is personal-use, and an operator override
flag scoped per-notebook is the documented escape hatch") that override would need
to be live BEFORE m4's fail-closed cutover ships, not after. <<<**

The OAI-PMH finding (Step 3) means this is very likely avoidable — license URIs
*are* obtainable from arXiv, just from a different endpoint — but m1's
implementation must actually target OAI-PMH, not assume the Atom path suffices,
or this 100% fail-closed outcome ships as written.

## Verdict

**The "must" assumption ("arXiv metadata API returns usable license URIs")
does NOT hold as scoped** — scoped to `tools/_arxiv_api.py`'s Atom client, measured
coverage is 0% across all three ID shapes (new-style, old-style, versioned) in a
30-paper mixed sample from both live notebooks, with a schema-level (not
per-paper-random) explanation.

**What does hold:** arXiv's OAI-PMH endpoint (a different, not-yet-implemented
client) returns a real per-paper license URI — verified live for one sample paper.
The corrected assumption for R1 m1 to build against is: *"arXiv's OAI-PMH endpoint
(GetRecord/ListRecords, metadataPrefix=arXiv) returns usable license URIs for the
corpus's ID shapes"* — which is a **new, narrower spike claim, not yet validated
across old-style or versioned ids** (Step 3 tested exactly one new-style/versioned
paper, per the brief's bound on this contingency step). Before m1 implementation
commits to OAI-PMH as the sole source, a small follow-up check across old-style ids
specifically (pre-2007 papers are the likeliest to have OAI-PMH quirks) is
recommended but was out of scope for this spike.

---

## Appendix

- Raw Atom response: `raw_atom.xml` (45,927 bytes, this directory).
- Raw OAI-PMH response: `raw_oai.xml` (1,834 bytes, this directory).
- Both scanned for prompt-injection content per the untrusted-content policy
  (patterns: instruction-override phrasing, fake system/assistant turns, HTML
  comments, authority claims) — zero matches in either file.
- Total live network requests made by this spike: **2** (one batched 30-id Atom
  request, one single-paper OAI-PMH request) — well within the arXiv politeness
  contract (`tools.arxiv_fetch.POLITENESS_SLEEP_SECONDS`).
- No code edited, no git operations performed, no corpus files modified. Read-only
  spike per the task contract.
