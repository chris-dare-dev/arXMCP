---
project: arxmcp
type: roadmap
status: active
authorship: agent-generated
tags:
- project/arxmcp
- type/roadmap
- authorship/agent-generated
---

# search_papers handler wiring for /proof-verify — Roadmap

> [!done] ARCHIVED — track complete, retained for the record
> **Moved** from `plans/proof-verify-handler-wiring-roadmap.md` to `.claude/roadmap/` on 2026-07-29.
> `plans/` is reserved for live `roadmap/1` tracks (`plans/<slug>/roadmap.yaml`);
> `CLAUDE.md` § 1 allows no other Markdown outside `.claude/`. This directory is
> already the home of completed standalone briefs (`notebook-cutover.md`,
> `embedder-truncation.md`, …) and stays inside
> `milestone-pipeline-resolve-brief.py`'s legacy-prose glob, so `/milestone-pipeline`
> still resolves every id below.
>
> **Completed milestones (9)** — `state.json` phase `complete`: `proof-verify-handler-wiring-m1`, `proof-verify-handler-wiring-m10`, `proof-verify-handler-wiring-m2`, `proof-verify-handler-wiring-m3`, `proof-verify-handler-wiring-m4`, `proof-verify-handler-wiring-m6`, `proof-verify-handler-wiring-m7`, `proof-verify-handler-wiring-m8`, `proof-verify-handler-wiring-m9`
> `proof-verify-handler-wiring-m5` has no `state.json` — it ran as a measurement outside the state machine; its own heading records **COMPLETE 2026-05-21, Verdict NO** (hybrid+rerank: zero P@10 lift, −10pp top-1, 122× latency).
> **Last commit touching this track:** `a40807c docs(repo): correct stale stub claims in security audit docs`


**Slug:** `proof-verify-handler-wiring`
**Created:** 2026-05-21T04:00:24Z
**Status:** init

<!--
This roadmap is itself the state. Re-invoking the `roadmap` skill on
this file resumes from the first un-populated phase. Sections below
contain `{{TOKEN}}` placeholders until their phase runs.

Phases:
  1. REFINE     — How-Might-We, sharpening questions, assumptions, OKR, Won't list
  2. DECOMPOSE  — technique, epics, INVEST, specialist suggestions
  3. SEQUENCE   — MoSCoW, RICE, Now/Next/Later, spike lane, Now-lane milestones
  4. MATERIALIZE — validation results, optional GitHub bundle, next-step handoff
-->

---

## Phase 1 — Refine

### How Might We

How might we surface per-notebook scoping and (eventually) two-stage retrieval through the live `search_papers` MCP handler for `/proof-verify` and similar multi-notebook arXMCP consumers, without committing the live handler to operationally heavy or evidence-unsupported retrieval modes?

### Sharpening questions answered

1. **Is a per-call `paper_id` filter at the handler boundary enough for `/proof-verify`'s notebook scoping (R1)?** — Yes. Per `.claude/notes/proof-verify-pivot/synthesis.md` Finding B: dense-only ANN + paper_id filter already returns the right paper at top-1 for every pointed query on the 22-paper math.AG corpus tested in `.claude/notes/spikes/wiring-rerank-lift/`. Client-managed notebook → paper_id mapping at v1; no server-side notebook concept needed.
2. **Do we have evidence that hybrid+rerank lifts intra-notebook precision at the 100-paper target scale?** — No. The 2026-05-20 spike (22-paper corpus) measured P@10 mean = 0.722 across dense_only / hybrid / hybrid+rerank — zero lift — and rerank degraded the hardest adjacent-noise query (Q1) by promoting an off-topic paper into top-3. Caveat: 22 papers is below the scale at which BM25/RRF typically discriminate; the result does NOT cleanly generalize to 100 papers, but it does mean wiring hybrid+rerank as a handler default today is unsupported by evidence.
3. **Is the rerank model's 6.8s/query CPU latency acceptable as default-on?** — No. Per the spike: dense=83ms, hybrid=57ms, hybrid+rerank=6794ms on CPU (80×). Downstream's per-article budget (~30 claims × <1s each) cannot absorb a default-on rerank. Per-query opt-in via a request argument (or env-var-gated default with documented latency) is the right contract.
4. **Can the `search_papers` output payload change (`retrieval_mode` field) without breaking BP1 prompt-cache discipline?** — Yes. Per `tests/test_server_tool_schema.py:94`, only the INPUT tool schema is hashed for BP1 (`EXPECTED_TOOL_SCHEMA_SHA256`). The output payload's `"retrieval_mode": "dense_only"` (line `server/handlers/search.py:268`) is free to change to `"hybrid"` etc. Downstream consumers parsing that string need to know.
5. **Where does the notebook → paper_id mapping live?** — Client-side at v1. Synthesis Finding B + cost analysis: a server-side mapping would require a new MCP tool, session-state tracking, and an authz design — none on the existing roadmap. Client passes the ~100-paper list per call (~1.2 KB payload, well under the E13_S04b 256 KB cap).

### Assumptions

- `[MUST]` Threading the `filters={"paper_id": [...]}` argument into a LanceDB ANN search via `.where("paper_id IN (...)")` composes correctly with HNSW indexing and returns mathematically-sound rankings within the filtered subset. (Will be validated by handler tests + a downstream re-probe; the pattern is shipped in `BM25Phase._apply_supported_filters` at `server/retrieval/bm25.py:670-687` but not yet proven on the ANN call path.)
- `[MUST]` A 100-paper math.AG notebook fixture with chunk-level relevance labels for ~10 pointed sub-questions can be produced within the roadmap horizon. The curation runbook exists at `.claude/docs/eval-curation.md` (E05_S02 deliverable); the data does not. Without it, every hybrid+rerank-vs-dense claim stays unmeasured.
- `[SHOULD]` Per-call paper_id lists of ~100 ids fit comfortably inside the MCP request byte caps. 100 × ~12 bytes ≈ 1.2 KB; cap is 256 KB (E13_S04b).
- `[SHOULD]` No downstream consumer has a load-bearing parser on the output `retrieval_mode` string. (Worth pinging the personal-website session before flipping the value.)
- `[MIGHT]` Rerank latency drops 10× on GPU (still ~0.7s; opt-in only even then).
- `[MIGHT]` Sparse-vector fusion (BGE-M3's multi-vector head) lifts precision on top of hybrid+rerank for technical-term-heavy queries — relevant only if hybrid+rerank itself shows lift at scale.

### Objective

Make arXMCP's live `search_papers` handler the retrieval substrate for `/proof-verify`'s per-notebook claim-verification pipeline, with the retrieval-mode decision (dense-only / hybrid / hybrid+rerank) gated on measured evidence at the target notebook scale rather than on aspiration about what the substrate should do.

### Key Results

1. **R1 wired:** `search_papers(query, filters={"paper_id": [<100 ids>]})` returns results scoped to the supplied paper set; verified by a new handler test fixture AND a downstream re-spike (`arxmcp-triangulation-cutover-spike-5` or equivalent). Target: 2026-06-04 (~2 weeks).
2. **Dense baseline measured:** On the 100-paper math.AG fixture, dense-only paper-level top-1 precision ≥ 0.80 across ≥ 10 hand-labeled pointed sub-questions, with measurements landed in `.claude/docs/retrieval-quality-report.md`.
3. **Hybrid+rerank decision evidence-gated:** A re-spike at 100-paper scale produces a Verdict (YES / NO / UNCERTAIN) on whether hybrid+rerank lifts intra-notebook P@10 by ≥ 0.10 absolute over dense-only. Handler-wiring milestone for hybrid+rerank does NOT begin until this verdict is YES.
4. **Latency budget honored:** Live `search_papers` dense-only p95 ≤ 200 ms at 100-paper notebook scale; hybrid (no rerank) p95 ≤ 500 ms; hybrid+rerank documented as opt-in with measured p95 (no default-on commitment).
5. **No MCP tool input-schema break:** `EXPECTED_TOOL_SCHEMA_SHA256` in `tests/test_server_tool_schema.py` stays pinned through this entire roadmap. Output payload's `retrieval_mode` string is allowed to change with a CHANGES.md entry.

### Won't (explicit out-of-scope)

- Server-side first-class `notebook_id` concept (no schema column, no `set_active_notebook` MCP tool, no session-tracked active-notebook). v1 keeps the notebook as a client-managed paper-id list.
- BGE-M3 model swap (ColBERT, math-domain encoder, etc.).
- Lifting `MAX_SEARCH_PAPERS_CALLS = 3` in `server/session.py:54`. The per-session cap is intentional (E08_S04 Rule 2); downstream's fresh-session-per-query pattern is the intended workaround.
- Multi-tenant auth / per-notebook access control.
- GPU acceleration / Metal-Performance-Shaders for the rerank phase. CPU-acceptable defaults only.
- Sparse-fusion lift measurement (deferred to a follow-up spike only if hybrid+rerank ships and still leaves precision gaps).
- The 100-paper-fixture curation analyst work itself — this roadmap declares the need; the analyst time is a separate deliverable.
- Auto-cutover of `var/arxmcp/index/lancedb-staging` → `var/arxmcp/index/lancedb` for production hygiene. (Real bug per `.claude/notes/proof-verify-pivot/synthesis.md` Finding D-adjacent, but orthogonal to this pivot.)

---

## Phase 2 — Decompose

### Technique

**Vertical slicing + enabler stories**, default per the skill. Each epic is end-to-end consumable (handler change → test → measurement → doc) rather than horizontal-layer (e.g. "wire BM25 phase" / "wire ANN phase" separately). The hybrid pipeline is split horizontally inside e3 only because evidence-gating that epic depends on the 100-paper fixture (an enabler, e2) producing a measurable verdict first.

### Epics

#### proof-verify-handler-wiring-e1 — Notebook scoping live in `search_papers` (operational floor)

- **Type:** value
- **Specialist suggestion:** `mcp-protocol-reviewer` and `cache-stability-reviewer` — see `.claude/skills/roadmap/references/specialist-contracts.md`. The `cache-stability-reviewer` matters because the change touches the retrieval-cache key (filters become part of the cache lookup key today; that wiring needs careful review for correctness when the filter is actually honored).
- **Outcome:** A `/proof-verify` agent can pass `filters={"paper_id": ["2604.26204", "2604.26208", ...]}` to `search_papers` and receive ANN results scoped to that paper set. Verified by a new handler test fixture + a downstream re-spike that returns YES on per-call notebook scoping. **Explicit framing: this is the OPERATIONAL FLOOR — it narrows the haystack from corpus-scale to notebook-scale, but it does NOT itself solve the intra-notebook needle-finding problem (6 relevant of 100 topically-clustered papers). That is e2's question.**
- **Estimated size:** S (~1 week)
- **INVEST check:** I clean (independent of e2/e3), N clean (no prior negotiation needed — filter primitive is shipped at BM25Phase level), V clean (downstream gets immediate value), E clean (~50 LOC handler + ~150 LOC tests), S clean, T clean (paper-level top-K assertion against a known notebook is the test).
- **Dependencies:** none
- **Won't conflict check:** none — this is the v1 client-managed-mapping path explicitly endorsed by REFINE Q5.

#### proof-verify-handler-wiring-e2 — Two-notebook adjacent-noise fixture, 100-paper baseline, and hybrid+rerank re-spike verdict

- **Type:** value (reclassified from enabler — this epic produces THE product-viability answer, not just infrastructure)
- **Specialist suggestion:** `—` (curation-grade math content + standard pytest assertions; no specialist heuristic applies)
- **Outcome:** Two ingested 100-paper notebooks under `var/arxmcp/notebooks/<slug>/` (proposed: `bridgeland-stability` + `shimura-varieties` — disjoint research areas to test both within-notebook precision AND cross-notebook contamination), each with ~10 pointed sub-questions carrying paper-level relevance labels supplied by the user. The rerank-lift spike from `.claude/notes/spikes/wiring-rerank-lift/` is re-run at 100-paper scale; a Verdict (YES = hybrid+rerank lifts intra-notebook precision by ≥ 0.10 P@10; NO = dense+filter is the structural ceiling; UNCERTAIN = need more data) is written to `.claude/notes/spikes/wiring-rerank-lift-100paper/note.md`. The verdict gates e3 — and the entire downstream-product-viability question.
- **Estimated size:** S–M (~1 week with user-curated paper lists; was L when fixture curation was unowned). Effort drops from ~4pm to ~1pm because the analyst component is now contributed by the user.
- **INVEST check:** I clean (independent of e1/e3 implementation, parallelizable), N clean (curation owner identified), V clean (the verdict IS the product-viability signal — not just enabler value), E clean (~50 LOC ingest driver + ~150 LOC re-spike + fixture validation), S clean once curation lands, T clean (paper-level P@K + chunk-leakage measurement against curated ground truth).
- **Dependencies:** **user-curated `var/arxmcp/notebooks/<slug>/papers.txt` and `queries.json` per notebook** (load-bearing precondition; this epic cannot start without them).
- **Won't conflict check:** none — REFINE Won't excluded doing the curation as arXMCP-internal analyst work; user-contributed curation moves it inside scope.

#### proof-verify-handler-wiring-e3 — Hybrid+rerank wiring (CLOSED 2026-05-21, verdict NO)

- **Type:** value
- **Specialist suggestion:** `mcp-protocol-reviewer` and `cache-stability-reviewer` — touches the same handler path as e1 plus the rerank phase's Tier-3 cache.
- **Outcome:** `search_papers` accepts a per-call `rerank: bool = False` argument (or env-var default-on if e2's re-spike shows lift); when true, runs the BM25→ANN+RRF→rerank pipeline that today only runs inside the eval test. The output payload's `retrieval_mode` reflects the actual pipeline used. Downstream can opt in per query.
- **Estimated size:** M (~2 weeks for the lift + tests; assumes the 80-LOC orchestrator from `tests/eval/test_retrieval_quality.py::_run_hybrid_against_corpus` is the reference and the wiring is mechanical)
- **INVEST check:** I borderline (depends on e2's verdict to even start — without 100-paper evidence this epic is structurally an aspiration), N clean (the surgery is well-mapped per `.claude/notes/proof-verify-pivot/synthesis.md` Finding A), V clean (downstream value if e2 verdict is YES; otherwise the epic is correctly NOT done), E clean once started, S clean, T clean (precision@K + latency assertions against the e2 fixture).
- **Dependencies:** e2 (blocks start until 100-paper eval verdict is YES; if NO, this epic is closed without implementation per the REFINE evidence-gating)
- **Won't conflict check:** none

#### proof-verify-handler-wiring-e5 — Notebook directory contract + local-fetch tooling (Variant 1)

- **Type:** enabler
- **Specialist suggestion:** `—`
- **Outcome:** Three CLI scripts under `tools/notebook_*.py` that scaffold the per-notebook directory layout, opportunistically fetch ar5iv HTML for known paper IDs (respecting the existing 3s politeness contract), and run bulk ingest against the per-notebook LanceDB path. The Variant 1 layout — global `var/arxmcp/corpus/{parsed,chunks,embeddings}/` (per-paper, shared across notebooks) + per-notebook `var/arxmcp/notebooks/<slug>/{papers.txt, queries.json, lancedb/, index/bm25/}` — becomes the documented operator pattern. Eliminates the manual `ARXMCP_LANCEDB_PATH=... make ingest ARGS=...` invocation chain that the 2026-05-20 corpus-rebuild work had to construct ad-hoc.
- **Estimated size:** S (~1 day; three small scripts + one doc section)
- **INVEST check:** I clean (no code-path dependency on e1/e2/e3), N clean (Variant 1 endorsed by the user), V clean (operator + future frontend value), E clean, S clean, T clean.
- **Dependencies:** none (parallelizable with e1 and e2)
- **Won't conflict check:** Variant 2 (fully-per-notebook corpus dirs) was considered and rejected in favor of Variant 1. The chunker's module-level `PARSED_DIR` constant stays untouched.

#### proof-verify-handler-wiring-e7 — PDF ingest support (deferred capability)

- **Type:** enabler
- **Specialist suggestion:** `latex-parser-reviewer` (the PDF→text path is structurally a sibling of the LaTeXML→chunks path; the chunker contract must hold for either origin) and `security-reviewer` (PDF parsers have a large attack surface; sandbox + size caps required).
- **Outcome:** arXMCP can ingest PDF references (course notes, lecture notes, non-arXiv published papers) into a notebook on equal footing with ar5iv-rendered HTML. The operator drops a PDF file into a notebook's `pdf-deferred/` directory (today's parking holder, established 2026-05-21 during shimura-varieties bootstrap), runs the (new) `tools/notebook_ingest_pdf.py <slug>`, and the PDF is converted to HTML-equivalent structured text (via Nougat — the E11_S01 synthesis D2 deferral candidate — or an equivalent math-aware PDF parser like MathPix Markdown / Marker / GROBID), then re-uses the existing chunker → embedder → write path. Closes the long-deferred E11_S01 D2 gap.
- **Estimated size:** L (3–6 weeks; PDF→HTML for math content is the actual research-grade work — Nougat is GPU-heavy, MathPix is paid SaaS, alternatives are quality-uneven). Most of the cost is selecting and validating the conversion tool, not wiring it.
- **INVEST check:** I clean (does not affect e1/e2/e3/e6 in-flight work), N borderline (Nougat vs MathPix vs Marker vs GROBID choice is a real architecture decision; needs a sub-spike), V clean (operator + product value — unblocks any non-arXiv reference material), E uncertain (PDF parsing quality on dense math is the unknown), S borderline (could split into "spike: pick PDF tool" + "wire chosen tool" if the choice contests), T borderline (test fixtures need representative deferred PDFs — already have two real ones in `var/arxmcp/notebooks/shimura-varieties/pdf-deferred/`).
- **Dependencies:** e5 (notebook directory contract — uses `pdf-deferred/` subdir convention).
- **Won't conflict check:** REFINE Won't list does NOT exclude PDF support; this epic is additive. Note that the v1 frontend (e6) m8 milestone explicitly handles drag-drop of `.html` files only — extending it to `.pdf` is a separate small follow-up under this epic.
- **Holding area today:** `var/arxmcp/notebooks/<slug>/pdf-deferred/{manifest.json, *.pdf}` — two real deferred PDFs already live there: Milne's "Introduction to Shimura Varieties" course notes, Caraiani's Arizona Winter School notes. These become the e7 fixture when work begins.

#### proof-verify-handler-wiring-e6 — Local notebook-management frontend (htmx + Jinja2 on the daemon)

- **Type:** value (operator-facing, not downstream-facing)
- **Specialist suggestion:** `mcp-protocol-reviewer` (route-prefix carve-out review) and `security-reviewer` (URL paste validation, upload size carve-out — Threat 4 surface).
- **Outcome:** A browser-based UI mounted at `http://127.0.0.1:7733/ui/` that lets the operator create/list/delete notebooks, paste arXiv URLs to add papers, drag-drop ar5iv HTML files onto a notebook, browse the papers already in a notebook, and trigger an ingest run with status polling. Server-rendered htmx — no Node/JS build toolchain — and reuses the existing FastAPI daemon and `Resources` so an "ingest now" button doesn't have to reach into a sibling process. Co-located with the daemon under `/ui/*` with a narrow `SecFetchSiteMiddleware` carve-out for the prefix; the MCP protocol contract at `/mcp` is untouched.
- **Estimated size:** L (3–6 weeks of calendar; the three m7/m8/m9 milestones are M each but sequential)
- **INVEST check:** I borderline (depends on m6 establishing the notebook directory layout AND benefits from m1's filter wiring once the UI grows a query feature in a future epic), N clean (htmx + Jinja2 are zero-build pip-installable), V clean (operator value AND forward-compatible with frontend drag-drop curation), E clean (~600 LOC across templates/static/handlers), S borderline-acceptable (three M milestones; doesn't split further usefully), T clean (per-milestone AC are observable via curl + browser).
- **Dependencies:** m6 (notebook directory contract). Optional consumer of m1 (if the UI later grows query capabilities), but the v1 frontend is curation-only.
- **Won't conflict check:** REFINE Won't list excludes multi-tenant auth and lifting the per-session cap; this epic respects both — the UI is loopback-only by default and does NOT proxy MCP requests (so the 3-call cap is unaffected).

#### proof-verify-handler-wiring-e4 — Operational documentation: per-notebook daemon topology + cap migration story

- **Type:** enabler
- **Specialist suggestion:** `—`
- **Outcome:** A documented operator runbook at `docs/install.md` (or a new `docs/notebooks.md` if it grows) explaining: (a) how to launch one daemon per notebook today via `ARXMCP_LANCEDB_PATH`, (b) when to graduate from per-daemon to per-call `filters` (when e1 ships), (c) the 3-call-per-session cap and fresh-session-per-query pattern. CHANGES.md entry covering the `retrieval_mode` field semantics for any downstream parser.
- **Estimated size:** S (~3 days)
- **INVEST check:** I clean, N clean, V clean (operator-facing), E clean, S clean, T clean (doc-presence test).
- **Dependencies:** e1 must ship for "when to graduate" to be accurate.
- **Won't conflict check:** none

---

## Phase 3 — Sequence

### MoSCoW assignment

- **Must** (27.3% of total effort; measured by `score-moscow.py`): `proof-verify-handler-wiring-e1`, `proof-verify-handler-wiring-e2`, `proof-verify-handler-wiring-e4`, `proof-verify-handler-wiring-e5`
- **Should** (27.3%): `proof-verify-handler-wiring-e6` (frontend)
- **Could** (45.5%): `proof-verify-handler-wiring-e3` (rerank wiring, evidence-gated on e2), `proof-verify-handler-wiring-e7` (PDF ingest support, deferred capability with two real fixtures already on disk)
- **Won't (this cycle)**: — (the REFINE Won't list owns everything explicitly excluded)

**Rationale (revised 2026-05-21).** The original sequencing treated e2 (eval fixture) as Should and e3 (hybrid+rerank wiring) as Could, on the bet that operational unblock (e1) was the load-bearing piece. The user's clarified product framing — "find 6 of 100 topically-clustered papers per pointed sub-question" — makes intra-notebook needle-finding **the product question**, not a quality nice-to-have. Without e2's measurement, we cannot tell downstream whether the entire approach (dense + filter, optionally hybrid+rerank) is structurally sufficient. e2 is therefore promoted to Must. e2's effort estimate also drops from L (3–6 weeks of analyst time) to S/M (~1 week) because the user is contributing the curated paper lists + paper-level relevance labels directly. e3 stays Could because the spike-3 verdict determines whether to ship it at all; pre-committing to Must without the measurement would be the inflate-to-Must anti-pattern.

**e5 (added 2026-05-21):** Notebook directory contract + local-fetch tooling. Promoted to Must because (a) every other Must epic uses the notebook directory structure that e5 defines and scripts; (b) the user explicitly authorized the tooling work; (c) it's tiny (S, ~1 day).

**e6 (added 2026-05-21):** Browser-based notebook-management frontend (htmx + Jinja2 served by the daemon under `/ui/*`). Classified Should — high operator value but not on the product-viability critical path (downstream's `/proof-verify` pipeline does not require a frontend; the m6 CLI tools satisfy curation needs while the frontend lands). Effort L (3 sequential M milestones); Must-classification would push the cap over 60%.

**e7 (added 2026-05-21, late afternoon):** PDF ingest support. Surfaced during the shimura-varieties notebook bootstrap when the user provided two PDF references (Milne's "Introduction to Shimura Varieties" + Caraiani's Arizona Winter School notes) — both non-arXiv, currently parked under `var/arxmcp/notebooks/shimura-varieties/pdf-deferred/`. Classified Could because (a) the v1 product-viability question (e2 verdict) does not depend on PDF support, (b) the conversion-tool choice (Nougat / MathPix / Marker / GROBID) is a real architectural decision that may itself need a sub-spike, (c) Must-classification would consume cap headroom needed for hybrid-rerank wiring if e3's verdict turns YES. The two real PDFs on disk become the e7 fixture when work begins; no curation cost.

### RICE ranking — Musts

| ID | Reach | Impact | Confidence | Effort (pm) | Score |
|---|---:|---:|---:|---:|---:|
| proof-verify-handler-wiring-e5 | 10 | 0.60 | 85% | 0.50 | **10.2** |
| proof-verify-handler-wiring-e2 | 10 | 0.95 | 85% | 1.00 | **8.1** |
| proof-verify-handler-wiring-e1 | 10 | 0.80 | 75% | 1.00 | **6.0** |
| proof-verify-handler-wiring-e4 | 10 | 0.30 | 90% | 0.50 | **5.4** |

_Reach = 10 (every `/proof-verify` claim-verification call hits the substrate covered by these epics; the notebook tooling is the entry point operators and the future frontend use)._
_Confidence: e5 = 85% (small scripts, well-defined contract). e2 = 85% (high once user-curated fixtures land; only residual risk is whether 10 sub-questions per notebook is enough to discriminate). e1 = 75% (BM25Phase filter pattern is shipped; residual risk is LanceDB ANN + scalar predicate composition — see spike-1). e4 = 90% (docs)._
_Tie-break note: e5 tops RICE because of leveraged effort — small change that EVERY downstream Must inherits. e2 ranks #2 because impact dwarfs everything else operationally — a NO verdict on the spike-3 re-run means the entire downstream product approach needs an architectural rethink (sparse fusion, ColBERT, domain-adapted encoder). e1 ships first by topological order (m1 → m4 inheritance) but isn't the top-RICE item._

### Now / Next / Later

- **Now** (fully spec'd, in-flight or next-up): `proof-verify-handler-wiring-e1`, `proof-verify-handler-wiring-e2`, `proof-verify-handler-wiring-e4`, `proof-verify-handler-wiring-e5`
- **Next** (shaped, awaiting capacity): `proof-verify-handler-wiring-e6` (frontend v1, m7→m8→m9 sequential)
- **Later** (outcome-only, low-confidence horizon):
  - `proof-verify-handler-wiring-e3` — **CLOSED 2026-05-21 (verdict NO from m5).** Not implemented. Kept in the doc for traceability + as the reference for any future re-spike (e.g. with sparse fusion, or at 200+ paper scale).
  - `proof-verify-handler-wiring-m10` (frontend v2 paper preview; spec'd in body for forward reference; promotes after e6 v1 ships and operator has a clear use case)

### Spike / discovery lane

- `proof-verify-handler-wiring-spike-1` — Validate that LanceDB ANN search composes correctly with a `.where("paper_id IN (...)")` scalar predicate AND returns mathematically-sound rankings within the filtered subset. The pattern is shipped for BM25 but never used on the ANN call path. (≤ 1 day, validates `[MUST]` assumption #1 from REFINE.)
- `proof-verify-handler-wiring-spike-2` — **OBSOLETE** (was: scope analyst-owned curation commitment). User has agreed to contribute curation directly; this spike is no longer needed. Kept in the lane as a historical record of the dependency.
- `proof-verify-handler-wiring-spike-3` — **THE PRODUCT-VIABILITY GATE.** Re-run the rerank-lift spike (`.claude/notes/spikes/wiring-rerank-lift/`) at 100-paper scale against both user-curated notebooks (bridgeland-stability + shimura-varieties). Measure: paper-level P@K, chunk-level leakage from adjacent papers, score-distribution sharpness (max-vs-rest gap) per pipeline, p95 latency. Verdict format: YES = hybrid+rerank lifts P@K by ≥ 0.10 absolute over dense-only AND produces sharper score distribution → wire e3. NO = dense+filter is the structural ceiling → close e3 and raise the "architecture needs to change" flag with downstream. UNCERTAIN = collect more data before deciding. (≤ 2 days once fixtures land; validates `[MUST]` assumption #2 from REFINE.)

### Milestones — Now lane

### proof-verify-handler-wiring-m1 — Thread `filters={"paper_id":[...]}` through `search_papers` to LanceDB `.where()`

**Description.** Replace the dropped-filter behavior in `server/handlers/search.py:217-225` with a `chunks_table.search(query_vec, ...).where(predicate).limit(...)` call when `filters` contains a non-empty `paper_id` list. Add the predicate validator (paper_id list length, UTF-8 safety, escape rules per LanceDB's SQL-ish predicate syntax). Remove the `filter_warnings` "deferred to E07_S04" message when the filter IS honored. Update the cache key to include the filter set so cached results are scoped correctly. Add tests pinning the behavior against the 22-paper math.AG corpus.

**Acceptance criteria.**
- [ ] Given a daemon serving the 22-paper math.AG corpus, When a client calls `search_papers(query="Bridgeland stability", filters={"paper_id": ["2604.26204", "2604.26208"]}, k=10)`, Then every result row's `paper_id` is in the filter set.
- [ ] Given a daemon serving the 22-paper math.AG corpus, When a client calls `search_papers(query="Bridgeland stability")` (no filter), Then behavior is byte-identical to the pre-milestone dense-only path (no regression).
- [ ] Given a malformed filter (`filters={"paper_id": "not-a-list"}` or `filters={"paper_id": []}`), When the handler processes it, Then a clear error is surfaced via the result envelope (not a 500).
- [ ] `tests/test_server_tool_schema.py::EXPECTED_TOOL_SCHEMA_SHA256` continues to pass — the tool input schema is unchanged.
- [ ] New unit test under `tests/handlers/test_search_filter.py` (or equivalent) covering the three above behaviors.
- [ ] `make test` is green.

**Dependencies.** `proof-verify-handler-wiring-spike-1` validating that LanceDB ANN + scalar predicate compose. e1's parent epic.

**Complexity.** M (1–3 days).

**Specialist suggestion.** `mcp-protocol-reviewer`, `cache-stability-reviewer`.

### proof-verify-handler-wiring-m2 — Output payload semantics + CHANGES.md note

**Description.** Update the `retrieval_mode` field in the `search_papers` output payload to reflect actual pipeline used (`"dense_only"` stays accurate post-m1 — filters don't change the pipeline phase, only the candidate scope). Add an explicit `filters_applied` field in the payload (echo of the honored filter) so downstream can verify scoping. Add a CHANGES.md entry documenting the filter behavior shift and the (unchanged) `retrieval_mode` semantics.

**Acceptance criteria.**
- [ ] When `search_papers` is called with `filters={"paper_id":[...]}`, Then the response payload contains `"filters_applied": {"paper_id": [...]}` echoing the filter.
- [ ] When the same call is made WITHOUT filters, Then `"filters_applied"` is absent or `null`.
- [ ] `CHANGES.md` has a new entry under the current epic-grain header naming the filter behavior change.
- [ ] `tests/test_server_tool_schema.py` continues to pass — output payload is not in the BP1-hashed surface.

**Dependencies.** `proof-verify-handler-wiring-m1`.

**Complexity.** S (≤ 1 day).

**Specialist suggestion.** `mcp-protocol-reviewer`.

### proof-verify-handler-wiring-m3 — Operator runbook: per-notebook daemon vs per-call filters

**Description.** Add a documented section to `docs/install.md` (or new `docs/notebooks.md` if it grows) covering the three operational modes: (1) one daemon per notebook via `ARXMCP_LANCEDB_PATH=<per-notebook-dir>` (today's working pattern), (2) one daemon serving multiple notebooks via per-call `filters={"paper_id":[...]}` (m1's new pattern), (3) the trade-off (per-daemon = isolation + 3-call-cap per notebook session; per-call = single warm process + shared 3-call-cap across all notebooks in one session). Document the `MAX_SEARCH_PAPERS_CALLS = 3` cap and the fresh-session-per-query pattern.

**Acceptance criteria.**
- [ ] Doc section exists and is linked from the root `README.md` or `docs/install.md`.
- [ ] Doc explicitly names the 22-paper math.AG corpus at `var/arxmcp/index/lancedb-staging` as the working example for downstream cross-reference.
- [ ] Doc states the per-call paper_id list size budget (e.g., "~100 paper_ids per call comfortably; tested up to N").
- [ ] Doc cites the `EXPECTED_TOOL_SCHEMA_SHA256` stability commitment.
- [ ] No code changes — pure docs.

**Dependencies.** `proof-verify-handler-wiring-m1`, `proof-verify-handler-wiring-m2`.

**Complexity.** S (≤ 1 day).

**Specialist suggestion.** `—`.

### proof-verify-handler-wiring-m4 — Ingest user-curated notebooks via `tools/notebook_ingest.py`

**Description.** Accept the user-curated `var/arxmcp/notebooks/<slug>/{papers.txt,queries.json}` files (slug ∈ {`bridgeland-stability`, `shimura-varieties`}) and run `tools/notebook_fetch.py <slug>` (from m6) to pre-populate ar5iv HTML, then `tools/notebook_ingest.py <slug>` (also m6) to build the per-notebook LanceDB + BM25 indices. Verify both notebooks are independently queryable via the operational per-daemon workaround OR a single daemon switching via `ARXMCP_LANCEDB_PATH`.

**Acceptance criteria.**
- [ ] Given `var/arxmcp/notebooks/bridgeland-stability/papers.txt` exists, When `tools/notebook_ingest.py bridgeland-stability` runs, Then `var/arxmcp/notebooks/bridgeland-stability/lancedb/chunks.lance/` exists with `corpus-version.json` and `paper_count >= 80` (allowing for ar5iv-miss fail-rate ≤ 20%).
- [ ] Same for `shimura-varieties`.
- [ ] BM25 indices built per notebook at `var/arxmcp/notebooks/<slug>/index/bm25/v<N>/`.
- [ ] Both notebook fixtures pass `tools/validate_eval_fixtures.py` (extended to accept the per-notebook scope field).
- [ ] An operator can launch a daemon against either notebook via `ARXMCP_LANCEDB_PATH=var/arxmcp/notebooks/<slug>/lancedb` and `tools/list` works.

**Dependencies.** m6 (provides `tools/notebook_ingest.py`). User-curated fixtures land. Not blocked by m1/m2/m3 (parallelizable).

**Complexity.** S (~1 day of mostly waiting once fixtures + m6 land).

**Specialist suggestion.** `—`.

### proof-verify-handler-wiring-m6 — Notebook scaffolding scripts and Variant 1 directory contract

**Description.** Ship four small CLI scripts: `tools/notebook_init.py <slug>` scaffolds `var/arxmcp/notebooks/<slug>/{papers.txt,queries.json}` with templates; `tools/notebook_fetch.py <slug>` walks the notebook's `papers.txt`, and for each paper_id whose `var/arxmcp/corpus/parsed/<paper_id>/index.html` is missing, fetches ar5iv HTML (respecting the existing 3s politeness contract) — papers ar5iv lacks are listed for manual drop, not silently failed. `tools/notebook_ingest.py <slug>` is a thin wrapper that runs the existing `bulk_ingest` with `ARXMCP_LANCEDB_PATH=var/arxmcp/notebooks/<slug>/lancedb`, then builds per-notebook BM25 at `var/arxmcp/notebooks/<slug>/index/bm25/v<N>/`. `tools/notebook_purge.py <slug>` is the explicit destructive companion — deletes `var/arxmcp/notebooks/<slug>/` recursively (lancedb, bm25, queries, papers list, ar5iv uploads) AND offers an optional `--purge-corpus-too` flag that ALSO drops per-paper assets under `var/arxmcp/corpus/{parsed,chunks,embeddings}/` for paper_ids unique to this notebook. The script REQUIRES an interactive `yes/typed-slug` confirmation unless `--force` is passed. Variant 1 layout (global `corpus/`, per-notebook `lancedb/` + `bm25/`) is documented in the script docstrings.

**Acceptance criteria.**
- [ ] `tools/notebook_init.py bridgeland-stability` creates `var/arxmcp/notebooks/bridgeland-stability/papers.txt` (commented template) and `queries.json` (skeleton JSON with one example query). Idempotent — re-running on an existing notebook is a no-op (logs `notebook exists; skipping`).
- [ ] `tools/notebook_fetch.py <slug>` produces a summary line: `fetched=N from_cache=M missing=K`, with the missing paper IDs printed for manual drop. Honors the 3s politeness sleep against arxiv.org / ar5iv.labs.arxiv.org.
- [ ] `tools/notebook_ingest.py <slug>` exits 0 when ingest succeeds AND the per-notebook BM25 index is built; exits non-zero otherwise. Logs land in `var/arxmcp/notebooks/<slug>/ops/`.
- [ ] `tools/notebook_purge.py <slug>` removes only the per-notebook directory by default; with `--purge-corpus-too` also removes per-paper assets for paper_ids unique to this notebook (i.e. not referenced by any other notebook). Without `--force` the script blocks on stdin confirmation prompting the operator to type the slug back.
- [ ] All four scripts are runnable from the repo root via `uv run python tools/notebook_<verb>.py <slug>`.
- [ ] New tests under `tests/tools/test_notebook_scripts.py` cover the happy path, the "ar5iv miss with manual drop" path, and the purge confirmation gate (test asserts script aborts on incorrect typed-slug).
- [ ] `make test` green.

**Dependencies.** None (parallelizable with m1–m3; required by m4 — which is rewritten to delegate to `tools/notebook_ingest.py`).

**Complexity.** S (~1 day).

**Specialist suggestion.** `—` (small operator tooling; no protocol surface change).

### proof-verify-handler-wiring-m5 — Spike-3 re-run: hybrid vs dense at 100-paper scale, verdict written (COMPLETE 2026-05-21, Verdict NO)

**Description.** Lift `.claude/notes/spikes/wiring-rerank-lift/poc.py` to accept a per-notebook fixture (paper-id-set scope + queries with paper-level relevance). Run all three pipelines (dense-only, hybrid, hybrid+rerank) against each user-curated notebook from m4. Compute paper-level P@K, chunk-level adjacent-noise leakage, score-distribution sharpness (max-vs-rest gap), and per-pipeline p95 latency. Write the verdict and measurements to `.claude/notes/spikes/wiring-rerank-lift-100paper/`. Update `.claude/notes/proof-verify-pivot/synthesis.md` with measured numbers.

**STATUS:** Executed 2026-05-21 against 51 papers (bridgeland 39 + shimura 12) with 20 hand-labeled queries. Verdict **NO**: hybrid+rerank produces zero P@10 lift, -10pp top-1 regression, 122× latency cost. Closes e3. Full analysis at `.claude/notes/spikes/wiring-rerank-lift-100paper/note.md`.

**Acceptance criteria.**
- [ ] `.claude/notes/spikes/wiring-rerank-lift-100paper/measurements.json` exists with per-query rows for both notebooks across all three pipelines.
- [ ] `.claude/notes/spikes/wiring-rerank-lift-100paper/note.md` contains a single bold Verdict line (YES / NO / UNCERTAIN) with the threshold (≥ 0.10 absolute P@K lift) explicitly applied.
- [ ] `.claude/docs/retrieval-quality-report.md` is updated with measured numbers replacing the PRELIMINARY / PENDING markers (at least for the two user-curated notebooks).
- [ ] `.claude/notes/proof-verify-pivot/synthesis.md` updated: the "rerank lift unmeasured at target scale" caveat is replaced with the measured finding.
- [ ] If Verdict = NO, an explicit "architecture-change candidates" appendix is appended to `note.md` listing the next-step options (sparse fusion, BGE-M3 multi-vector, ColBERT, domain-adapted encoder).

**Dependencies.** m4 (must land first), spike-1 verdict (not strictly required — this spike runs against the eval path, not the live handler).

**Complexity.** M (~2 days).

**Specialist suggestion.** `—`.

### proof-verify-handler-wiring-m7 — Notebook persistence layer + REST CRUD under `/ui/api`

**Description.** Add a `notebooks` SQLite table (sibling to `cache_db_path`) with `(slug, display_name, lancedb_path, created_at)` columns plus a `notebook_papers` junction table. Wire `/ui/api/notebooks` (GET/POST/DELETE) and `/ui/api/notebooks/{slug}/papers` (GET/POST/DELETE) as pure-JSON FastAPI routes, reusing the existing pure-ASGI middleware stack. Carve `/ui/*` out of `SecFetchSiteMiddleware` so same-origin htmx posts pass — without this carve-out, htmx → browser → daemon traffic fails the Sec-Fetch-Site `same-origin` rejection rule. **Deletion semantics (resolved 2026-05-21):** `DELETE /ui/api/notebooks/{slug}` is **metadata-only** — drops the SQLite row and the junction entries; the on-disk LanceDB / BM25 / ar5iv assets under `var/arxmcp/notebooks/{slug}/` are NOT touched. Destructive on-disk wipe is the explicit job of `tools/notebook_purge.py <slug>` (m6). The UI surfaces this in a confirmation tooltip ("Removes notebook from UI; run `tools/notebook_purge.py` to delete on-disk data").

**Acceptance criteria.**
- [ ] `POST /ui/api/notebooks {"slug":"bridgeland"}` creates a row and a `var/arxmcp/notebooks/bridgeland/` directory; idempotent on duplicate slug (HTTP 409).
- [ ] `POST /ui/api/notebooks/bridgeland/papers {"arxiv_url":"https://arxiv.org/abs/2604.26204"}` normalizes the URL, validates against the existing `paper_id` regex from `ingest/identifiers.py`, and writes a junction row.
- [ ] `DELETE /ui/api/notebooks/bridgeland` drops the SQLite row + junction entries but leaves `var/arxmcp/notebooks/bridgeland/` intact on disk. Subsequent `POST` with the same slug succeeds (no leftover state corruption from the on-disk dir).
- [ ] `SecFetchSiteMiddleware` exempts `/ui/*` and is covered by a new test asserting `Sec-Fetch-Site: same-origin` is rejected on `/mcp` but accepted on `/ui/api/notebooks`.
- [ ] `tests/test_server_tool_schema.py::EXPECTED_TOOL_SCHEMA_SHA256` unchanged; no new MCP tools (this is a sibling REST surface, not an MCP surface change).
- [ ] `make test` green.

**Dependencies.** m6 (notebook directory layout); independent of e1 filter wiring (m1).

**Complexity.** M (1–3 days).

**Specialist suggestion.** `mcp-protocol-reviewer` (verify the route prefix carve-out doesn't bleed onto `/mcp`) + `security-reviewer` (paper_id regex enforcement on URL paste).

### proof-verify-handler-wiring-m8 — htmx + Jinja2 UI: notebook CRUD, paper-paste, ar5iv HTML drop, browse

**Description.** Add `frontend/templates/` and `frontend/static/` with a single-page htmx UI: notebook list, create/delete, paper-add by URL paste, drag-drop for ar5iv HTML files (uploaded as `multipart/form-data` to a new `/ui/api/notebooks/{slug}/papers/upload` endpoint), and a paper-browse table fed by the m7 REST routes. No Node toolchain — Jinja2 is rendered server-side, htmx is a single 14 KB JS file vendored into `frontend/static/`.

**Acceptance criteria.**
- [ ] `GET /ui/` returns an HTML page listing notebooks with a create-notebook form and (for each notebook) an "open" link.
- [ ] Dropping an `.html` file onto a notebook card POSTs to `/ui/api/notebooks/{slug}/papers/upload`; the file is stored under `var/arxmcp/notebooks/{slug}/ar5iv/` and a junction row is created.
- [ ] URL paste accepts both `arxiv.org/abs/<id>` and `ar5iv.labs.arxiv.org/html/<id>` forms.
- [ ] `RequestBodySizeLimitMiddleware`'s 1 MB cap is raised for `/ui/api/notebooks/*/papers/upload` only (ar5iv HTML can exceed 1 MB) — separate middleware-prefix carve-out with its own cap (e.g. 10 MB).
- [ ] Vendored htmx + minimal CSS; no internet fetch at runtime.

**Dependencies.** m7.

**Complexity.** M (1–3 days).

**Specialist suggestion.** `mcp-protocol-reviewer` (route surface review) + `security-reviewer` (upload size carve-out is a Threat-4 concern).

### proof-verify-handler-wiring-m9 — Ingest trigger + status polling from the UI

**Description.** Add `POST /ui/api/notebooks/{slug}/ingest` that spawns the existing `tools/notebook_ingest.py` (from m6) as a background `asyncio.create_task`; persist run state in a `notebook_ingest_runs` table. UI polls `/ui/api/notebooks/{slug}/ingest/latest` via htmx `hx-trigger="every 2s"` and shows progress. **Paper-preview feature is explicitly OUT of m9 scope** (deferred to v2 m10 per user decision 2026-05-21) — m9 ships ingest control only; reading a paper happens via the existing MCP `get_chunk` tool or by opening the ar5iv HTML directly from `var/arxmcp/corpus/parsed/<paper_id>/index.html`.

**Acceptance criteria.**
- [ ] Clicking "Ingest now" in the UI starts a background task; the run row stays `running` until the pipeline exits.
- [ ] Failure surfaces the last 1 KB of stderr in the UI without exposing absolute paths beyond `var/arxmcp/`.
- [ ] Only one in-flight ingest per notebook is allowed (concurrent POST returns HTTP 409).
- [ ] No "preview paper" route, link, or iframe in m9. (Out-of-scope assertion verifiable by search: `grep -ri "iframe\|preview" frontend/` returns empty for the v1 ship.)
- [ ] `make test` green; new tests cover the happy path and the 409 collision.

**Dependencies.** m7, m8, and m6 (provides the ingest entry point).

**Complexity.** M (1–3 days).

**Specialist suggestion.** `mcp-protocol-reviewer` + `determinism-reviewer` (background task lifecycle and corpus_version bump on success).

### proof-verify-handler-wiring-m10 — (v2, Later lane) In-UI paper preview via sandboxed iframe

**Description.** Add a "Preview" link next to each paper in the m8 browse table that renders the stored ar5iv HTML (`var/arxmcp/corpus/parsed/<paper_id>/index.html`) in a sandboxed iframe at `/ui/notebooks/{slug}/papers/{paper_id}/preview`. Define a tight CSP that disables scripts in the iframe (ar5iv HTML is static math content; no JS execution needed) and blocks external resource fetches so a malicious paper cannot exfiltrate via a crafted `<img src="https://attacker/...">`. Set `sandbox="allow-same-origin"` on the iframe (no scripts, no top-navigation).

**Acceptance criteria.**
- [ ] `GET /ui/notebooks/{slug}/papers/{paper_id}/preview` returns the stored HTML wrapped in a minimal page with CSP `default-src 'none'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; script-src 'none'`.
- [ ] The "Preview" link is only present in the UI when the on-disk HTML exists; missing papers show a "no preview available" tooltip.
- [ ] A test paper containing `<script>alert(1)</script>` does NOT execute the script when previewed (CSP test).
- [ ] A test paper containing `<img src="https://example.com/track.png">` does NOT make the outbound request (img-src 'self' test).

**Dependencies.** m9 (UI shell + browse table).

**Complexity.** S (~half day for the route + CSP; the testing covers the security boundary).

**Specialist suggestion.** `security-reviewer` (CSP + sandbox boundary review is the load-bearing concern).

---

## Phase 4 — Materialize

### Validation

- `validate-roadmap.py`: PASS — exit 0.
- Must-cap: 37.5% (≤ 60% cap) — measured by `score-moscow.py` after e6 (frontend) classified Should at 3pm.
- All Now-lane, Next-lane, and forward-spec'd Later-lane milestones (m1 through m10) have `- [ ]` AC checkboxes.
- Slug format valid: `proof-verify-handler-wiring` matches `^[a-z][a-z0-9-]{2,30}$` and does NOT collide with the `e\d+` epic-id pattern.
- Now lane has 6 milestones (m1–m6); Next lane has 3 (m7–m9); Later lane has m10 (frontend v2 preview). Intentional — Now's three sub-tracks (m1+m2+m3 operational, m4+m5 product-viability, m6 tooling) are independent; Next is the linear frontend chain; Later is forward-spec'd so the security-reviewer concern for iframe sandboxing is on the record before any v2 work begins.

### GitHub tickets

Not bundled. The `--github` flag was not passed (this repo's CLAUDE.md §4.1 establishes single-user single-workstation `main`-only workflow; no GitHub Issues / PR gating). To bundle later: re-invoke `roadmap proof-verify-handler-wiring --github`.

### Next step

Three parallel tracks are unblocked simultaneously:

```
# Track A — operational unblock (~1-2 weeks)
/spike proof-verify-handler-wiring-spike-1     # ≤ 1 day; cheap sanity check
/milestone-pipeline proof-verify-handler-wiring-m6   # notebook tooling (no deps)
/milestone-pipeline proof-verify-handler-wiring-m1   # filter wiring
/milestone-pipeline proof-verify-handler-wiring-m2   # output payload
/milestone-pipeline proof-verify-handler-wiring-m3   # docs

# Track B — product-viability gate (~1 week once user-curated fixtures land)
# Precondition: var/arxmcp/notebooks/{bridgeland-stability,shimura-varieties}/
#   papers.txt + queries.json (user-curated)
# Precondition: m6 has landed (provides tools/notebook_ingest.py)
/milestone-pipeline proof-verify-handler-wiring-m4   # ingest
/milestone-pipeline proof-verify-handler-wiring-m5   # spike-3 verdict

# Track C — frontend (sequential, starts after m6; ~3-6 weeks total)
/milestone-pipeline proof-verify-handler-wiring-m7   # REST CRUD
/milestone-pipeline proof-verify-handler-wiring-m8   # htmx UI + drag-drop
/milestone-pipeline proof-verify-handler-wiring-m9   # ingest trigger + status
```

**m5 RAN 2026-05-21, Verdict = NO.** e3 closed unimplemented. The dense+filter floor measured at top-1 = 0.85 / R@10 = 0.94 across 20 hand-labeled queries against 51 real papers — sufficient for `/proof-verify`'s `found@K` semantics. Hybrid+rerank produced zero P@10 lift, -10pp top-1 regression, 122× latency cost (CPU). Full analysis: `.claude/notes/spikes/wiring-rerank-lift-100paper/note.md`.

If `/proof-verify` later finds 0.85 top-1 insufficient for some specific subset of claims, the recommended next investigation is a **sparse-vector fusion sub-spike** (BGE-M3 has a sparse head currently unused by arXMCP). Separate ~3-day spike, NOT a roadmap commitment.

### Frontend design decisions (resolved 2026-05-21)

1. **Paper preview: deferred to v2 m10.** v1 frontend (m7+m8+m9) ships ingest control only. m10 is shaped in the Now-lane milestone block above as a Later-lane deliverable behind a security-reviewer specialist; it requires a CSP + iframe-sandbox design study. Reading paper content during v1 happens via the existing MCP `get_chunk` tool or by opening the on-disk ar5iv HTML directly.
2. **Notebook deletion: metadata-only via UI; on-disk wipe via `tools/notebook_purge.py`.** Confirmed. Encoded in m6 (purge script with typed-slug confirmation gate) and m7 (DELETE endpoint metadata-only). The UI surfaces a tooltip on the delete control directing operators to `tools/notebook_purge.py` for the destructive path.
3. **Auth posture: loopback-only, no auth.** Confirmed acceptable per CLAUDE.md single-user doctrine. The daemon binds `127.0.0.1` only (rejected at parse time per `server/config.py::reject_non_loopback` for any other host). The `/ui/*` surface inherits the same posture. **Implication for future multi-user pivot:** would require both (a) a real auth system AND (b) lifting the loopback bind constraint, which is itself a security-reviewed change — not a small retrofit. Documented in m3 (operator runbook) so the constraint is visible at operator-setup time.

---

<!-- end:roadmap -->
