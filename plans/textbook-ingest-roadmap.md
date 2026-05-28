# Textbook ingest (PDFs into notebook-scoped corpus) — Roadmap

**Slug:** `textbook-ingest`
**Created:** 2026-05-27T20:34:27Z
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

<!-- populated by REFINE phase; do not edit other phases until this one is complete -->

### How Might We

How might we ingest textbook and lecture-notes-as-PDF sources into arXMCP notebooks for the autoformalizer/sketcher pipeline, **without** breaking the math-fidelity-over-coverage contract (no PyPDF-style equation mangling) and **without** retrofitting non-arxiv chunk identity into the shared arXiv corpus?

### Sharpening questions answered

1. **What problem does this solve that the existing pipeline doesn't?** Today the upload route in [`server/routes/notebooks.py:483`](server/routes/notebooks.py:483) magic-byte-rejects `.pdf`, and the ingest ladder in [`ingest/bulk_ingest.py:41`](ingest/bulk_ingest.py:41) is "ar5iv → LaTeXML → skip+log". The operator's [`var/arxmcp/notebooks/shimura-varieties/pdf-deferred/manifest.json`](var/arxmcp/notebooks/shimura-varieties/pdf-deferred/manifest.json) parks two PDFs (Milne SVI, Caraiani Arizona notes) explicitly because PDF ingest is unsupported. Textbooks are the next demand class.
2. **Why isn't "fetch the .tex source instead" enough?** The T3 sample-of-10 spike at [`.claude/notes/capability-scouts/pdf-ingest-2026/spikes/source-availability.md`](.claude/notes/capability-scouts/pdf-ingest-2026/spikes/source-availability.md) verified **1/10** authors publish `.tex` (Stacks Project). Milne's `svi.pdf` — the named evidence point in the deep dive — has **no** companion `svi.tex`. Source-first is a 10-20% preflight, not a path.
3. **What parser, given the no-PyPDF rule?** [`pdf-capability-deep-dive.md`](.claude/notes/pdf-capability-deep-dive.md) §4 ranked Marker / Nougat / Mathpix / MinerU. Per `pdf-ingest-2026` challenger T2 ruling: **MinerU 2.5 only** (Apache-2.0, no GPL-3 boundary concern, highest reported CDM). Marker is parked (GPL-3 + no-fork-spirit); Mathpix is one-time batch only ([`CAND-8`](.claude/notes/capability-scouts/pdf-ingest-2026/artifacts/final-report.md#rank-1--cand-8-mathpix-as-batch-one-time-exception), separate milestone after this family).
4. **How does math survive?** MinerU emits LaTeX-in-markdown → existing LaTeXML pass → HTML5+MathML → existing chunker. The downstream chunker/embedder/LanceDB chain is reused unmodified. CDM (Character Detection Matching) gate already shipped via [`parser-fidelity-eval-m1`](.claude/notes/milestones/parser-fidelity-eval-m1/state.json) — makes the parser-fidelity claim falsifiable on textbook fixtures before any parser commitment.
5. **What about the chunks-schema collision with arXiv identity?** Per challenger F3 (MAJOR): the `paper_id` regex in [`ingest/identifiers.py`](ingest/identifiers.py) is `\Z`-anchored on arXiv shapes, and `is_valid_paper_id` is a Threat-1 (path-traversal) surface. Adding `textbook:<slug>:<sha>` requires ≥5 new path-traversal regression tests plus a coordinated SHA re-pin commit (`EXPECTED_TOOL_SCHEMA_SHA256` + `EXPECTED_BP1_SHA256`).

### Assumptions

- `[MUST]` **MinerU 2.5 CDM lift on the curated textbook fixture is ≥0.05 over the all-zero baseline**, verified via the eval gate shipped in `parser-fidelity-eval-m1`. If MinerU underperforms here, the whole family stalls and CAND-8 (Mathpix-as-batch) jumps the queue. Spike: textbook-ingest-spike-1.
- `[MUST]` **Subprocess sandbox profile for MinerU under Threat 3** (no network egress, hard CPU/RSS/wall timeout, filesystem whitelist on `var/arxmcp/notebooks/<slug>/`) is sufficient to mitigate PDF-bomb / embedded-JS / polyglot attack surface for operator-supplied PDFs. Sandbox precedent exists at [`.claude/docs/security-cdm-sandbox.md`](.claude/docs/security-cdm-sandbox.md) (Threat-3 peer). Spike: textbook-ingest-spike-2.
- `[MUST]` **Per-notebook isolation is the correct blast radius**: textbook chunks live ONLY in `var/arxmcp/notebooks/<slug>/lancedb/`, never in the shared arXiv corpus. This is the load-bearing claim in challenger F3 + dive Path A — wrong means `search_papers` defaults pollute the arXiv-only query semantics. Spike: textbook-ingest-spike-3.
- `[SHOULD]` **MinerU subprocess wall-clock for a 500-page textbook on M2-Max class CPU is ≤30 min**, otherwise operator UX degrades to background-job territory and we need a job-queue layer (out of scope here). Dive §4 cites 1-3 pages/sec on M2 Max → 500 pages ≈ 3-8 min, with headroom for variance. Fallback: chunk by 100-page slabs and report partial completions.
- `[SHOULD]` **License truncation policy (300 chars + `truncated_for_license: true` flag) is acceptable to operator for non-OA chunks**. Stacks Project (GFDL), arXiv-distributed source (CC-BY / arXiv-license), and self-published lecture notes (no explicit license) are the dominant license tiers per T3 spike. Without an operator policy, the family stalls at the `license` column design.
- `[MIGHT]` **The `notation.yaml` per-textbook macro recovery (CAND-15)** materially improves retrieval over MinerU's recovered preamble. The dive's hypothesis from competitive scout C2 is untested for arXMCP's specific corpus — defer to a v1 follow-up after CDM measurements land on real textbook content.

### Objective

Make textbook and lecture-notes-as-PDF sources first-class citizens of notebook-scoped retrieval — usable by sketchers and autoformalizers — without compromising the math-fidelity contract, the arXiv corpus's chunk identity, or the BP1 prompt-cache discipline.

### Key Results

1. **The two parked PDFs in [`var/arxmcp/notebooks/shimura-varieties/pdf-deferred/`](var/arxmcp/notebooks/shimura-varieties/pdf-deferred/) are ingestible and queryable** via `search_papers` with `filters.source_kind=textbook` against the `shimura-varieties` notebook, by end of family.
2. **CDM ≥0.95 on the 20-page textbook fixture from `parser-fidelity-eval-m1`** measured for at least one textbook in the corpus, with the `parser_used: "mineru+latexml"` tag visible in `get_chunk` envelopes (so consumers can de-prioritize for high-stakes claims).
3. **Zero regressions on the 2129-test green suite** (macOS / Linux) at every milestone boundary; `EXPECTED_TOOL_SCHEMA_SHA256` and `EXPECTED_BP1_SHA256` re-pinned exactly once in a single coordinated rect commit.
4. **`search_papers` with `filters.source_kind={arxiv|textbook}`** ships with backward-compatible default semantics (queries against an arxiv-only notebook return arxiv-only; queries against a textbook-containing notebook return both unless filtered).
5. **Threat-model extension document for PDF inputs** lands at `.claude/docs/security-pdf-sandbox.md` covering polyglot detection, embedded-JS refusal, decompression-bomb caps, and the MinerU subprocess sandbox profile.

### Won't (explicit out-of-scope)

- **PDF figure extraction.** Constitutional non-goal per [`.claude/notes/09-feature-priorities.md`](.claude/notes/09-feature-priorities.md): "Tier 6 if at all." Un-park trigger from [`deferred-work-tracker.md`](.claude/notes/deferred-work-tracker.md) does not auto-apply after this family ships.
- **OCR of scanned (pre-typeset) PDFs.** Constitutional non-goal: "OCR quality on math content is too poor for the math-fidelity contract to survive."
- **A separate `search_textbooks` MCP tool.** Killed per `pdf-ingest-2026` challenger T1 ruling: `source_kind` filter on the existing `search_papers` handler keeps the 7-tool surface byte-stable. Re-litigating would mean two SHA re-pins instead of one.
- **Cross-corpus ingest into the shared arXiv LanceDB.** Per challenger F3 and dive Path A: textbook chunks live ONLY in `var/arxmcp/notebooks/<slug>/lancedb/`. The shared arXiv corpus stays arxiv-only.
- **Mathpix runtime integration.** Hosted-only → disqualified at runtime per local-first constraint. CAND-8 (Mathpix one-time batch) is a separate operator tool, shipped AFTER this family lands its schema + chunker.
- **Full publisher-PDF textbook corpus with parallel MCP tool surface (Path C / CAND-16 / CAND-17).** Parked per dive §5; un-park trigger in `deferred-work-tracker.md`.
- **A new MCP tool for textbook navigation (e.g. `pdf_get_toc`).** Killed per challenger T1 (CAND-9). Chapter walks happen via envelope-on-`get_chunk` when the chunk level is `chapter`.
- **The `notation.yaml` per-textbook macro recovery feature.** Deferred to a v1 follow-up after CDM measurements confirm a lift; ships as `[MIGHT]` (CAND-15), not in this family.
- **`navigation_history` SessionState field (CAND-12).** Deferred — folds into a future polish milestone; not load-bearing for the minimum viable textbook ingest.
- **Late chunking (CAND-4, Jina Sep 2024).** Parked; v1 of the textbook bundle after CDM measurements arrive.

---

## Phase 2 — Decompose

<!-- populated by DECOMPOSE phase -->

### Technique

**Vertical slicing + enabler stories.** Each epic ships one observable slice of the textbook → query path with the minimum scaffolding to demo it end-to-end. Two enablers (schema + parser sandbox) front-load the regrettable-but-load-bearing infrastructure; three value epics deliver the user-visible behavior change (textbook bytes → queryable chunks → cross-corpus search results). The competing technique considered was **Event Storming** (corpus ingestion is a domain-rich event flow), but Event Storming optimizes for *discovering* domain events — the events here are already enumerated in the capability-scout final report. Vertical slicing wins because we have a well-mapped pipeline and need delivery cadence, not discovery.

### Epics

#### textbook-ingest-e1 — Textbook chunk identity is storable and addressable

- **Type:** enabler
- **Specialist suggestion:** `cache-stability-reviewer` + `determinism-reviewer` + `security-reviewer` — see [`.claude/skills/roadmap/references/specialist-contracts.md`](.claude/skills/roadmap/references/specialist-contracts.md). Touches `chunk_id` construction (cache stability), schema versioning (determinism), and the path-traversal regex (security).
- **Outcome:** Chunks tagged `source_kind=textbook` with `textbook:<slug>:<sha>` identity and `page_start`/`page_end`/`chapter`/`license`/`parser_used` columns round-trip cleanly through LanceDB; `is_valid_paper_id` accepts both arXiv shapes and textbook shapes with ≥5 new path-traversal regression tests; `EXPECTED_TOOL_SCHEMA_SHA256` and `EXPECTED_BP1_SHA256` re-pinned in one coordinated commit.
- **Estimated size:** M
- **INVEST check:** I clean (independent of parser choice); N clean; V borderline (enabler — value comes through downstream epics); E clean; S clean (≤ 3 weeks); T clean (schema lints + chunk-id round-trip + path-traversal tests are unambiguous).
- **Dependencies:** none. Ships first.
- **Won't conflict check:** none. Schema bump is allowed by the constitution; bump bumps `corpus_version`.

#### textbook-ingest-e2 — PDFs become HTML5+MathML via sandboxed MinerU

- **Type:** enabler
- **Specialist suggestion:** `security-reviewer` + `latex-parser-reviewer` — subprocess invocation, network egress refusal, and LaTeXML re-invocation all sit in this epic.
- **Outcome:** Operator-uploaded PDF (≤200 MB per textbook notebook) flows through a sandboxed MinerU 2.5 subprocess, then the existing LaTeXML pass, then writes parsed HTML5+MathML to `var/arxmcp/notebooks/<slug>/parsed/<paper-or-textbook-id>/index.html`. CDM ≥0.95 on the `parser-fidelity-eval-m1` fixture on at least one textbook. Polyglot detection + embedded-JS refusal + decompression-bomb caps enforced before MinerU runs.
- **Estimated size:** L
- **INVEST check:** I borderline (consumes e1's schema for `parser_used` tagging — hard dependency); N clean; V clean (operator can demo "PDF → HTML5+MathML on disk"); E clean (CDM is the measurement); S clean (≤ 4 weeks); T clean.
- **Dependencies:** textbook-ingest-e1 (needs `parser_used` column to tag output).
- **Won't conflict check:** none. Honors "no PyPDF as primary parser" — MinerU emits LaTeX, LaTeXML re-renders to MathML.

#### textbook-ingest-e3 — Textbook structure is chunked book/chapter/section

- **Type:** value
- **Specialist suggestion:** `latex-parser-reviewer` + `determinism-reviewer` — chunker boundaries (parser) + deterministic chunk-id derivation under structural-section context.
- **Outcome:** Hierarchical chunker (`ingest/textbook_chunker.py`) emits chunks at `book` / `chapter` / `section` granularity (v0 cut per challenger F2). Theorem / lemma / proof environments inside a section continue to pair as today via the existing chunker primitives. ProofNet metadata schema mapping preserved. Per-chapter preamble inheritance works (textbook-shaped, not paper-shaped).
  - **CLOSED at m7 + m8 (2026-05-28).** m7 shipped the book/chapter/section chunker spine; m8 closed the epic. Two of the named outcomes were DESCOPED by m8 research as written: (1) **per-chapter preamble inheritance is structurally inapplicable** to the shipped PDF→MinerU path (MinerU emits already-expanded math; there is no `.tex` preamble to inherit) — see [`.claude/docs/textbook-preamble-decision.md`](../.claude/docs/textbook-preamble-decision.md); (2) **ProofNet mapping** is delivered as a documented cross-reference contract (existing `theorem_label`/`theorem_name`/`textbook_slug`/`chapter` fields), NOT a schema column — see [`.claude/docs/proofnet-crossref-contract.md`](../.claude/docs/proofnet-crossref-contract.md). A future `.tex`-source textbook ingest path (separate epic) would re-enable real preamble inheritance + reliable ProofNet `theorem_label` joins.
- **Estimated size:** L
- **INVEST check:** I borderline (consumes e1's schema; ideally e2's parsed-HTML output exists — but golden fixtures from a pre-parsed Stacks Project chapter make the chunker testable independently); N clean; V clean (chunk inspection demoable in CLI); E clean (golden-fixture diffs are the measurement); S clean (≤ 5 weeks for v0; v1 exercise + definition chunks deferred); T clean.
- **Dependencies:** textbook-ingest-e1 (schema). e2's parsed-HTML output is the integration target but golden fixtures decouple development.
- **Won't conflict check:** Exercise + definition chunk levels deferred (Won't-list-conformant — those land in a v1 follow-up after CAND-5 `defines` edge ships).

#### textbook-ingest-e4 — Textbook chunks are queryable through `search_papers`

- **Type:** value
- **Specialist suggestion:** `cache-stability-reviewer` + `mcp-protocol-reviewer` — tool-schema extension (BP1 byte-stability) + JSON-Schema-level enum validation.
- **Outcome:** `search_papers` accepts `filters.source_kind={arxiv|textbook}`; queries default to "active notebook regardless of `source_kind`"; the two parked Milne / Caraiani PDFs return in result rows from the `shimura-varieties` notebook with proper `source_kind=textbook` tagging in the envelope. One coordinated `EXPECTED_TOOL_SCHEMA_SHA256` re-pin (bundled with e1's BP1 re-pin per CAND-13 sequencing dependency).
- **Estimated size:** S
- **INVEST check:** I borderline (consumes e1's schema and e2/e3's chunks); N clean; V clean (this IS the demoable user-visible outcome — operator runs `search_papers` against the notebook and sees Milne/Caraiani chunks come back); E clean; S clean (≤ 1 week); T clean (schema-hash test pins the contract).
- **Dependencies:** textbook-ingest-e1, e2, e3 (needs schema + parsed HTML + chunks to query).
- **Won't conflict check:** No new MCP tool — extension only, per Won't-list (T1 ruling).

#### textbook-ingest-e5 — PDF inputs are hardened against the seven threats

- **Type:** enabler
- **Specialist suggestion:** `security-reviewer` — extension of [`.claude/notes/08-security-observability-ops.md`](.claude/notes/08-security-observability-ops.md) and the upload route's threat surface.
- **Outcome:** `.claude/docs/security-pdf-sandbox.md` lands documenting the MinerU subprocess sandbox profile, the pdfid carve-out (`tools/security/pdfid.py` vendored under the no-fork-policy reading), Threat 3.5 (polyglot detection) + Threat 8 (embedded-JS refusal) extensions, and the non-OA license-truncation policy (300 chars + `truncated_for_license: true` flag at the snippet boundary in [`.claude/docs/snippet-contract.md`](.claude/docs/snippet-contract.md)). Upload cap raised from 10 MB → 200 MB ONLY for `kind: "textbook"` notebooks.
- **Estimated size:** M
- **INVEST check:** I borderline (Threat 3.5/8 doc edits can land independently; the cap raise needs e1's `notebook_kind` field); N clean; V borderline (security work is enabler-shaped — value surfaces because PDFs become safe to accept); E clean; S clean (≤ 3 weeks); T clean.
- **Dependencies:** textbook-ingest-e1 (needs `notebook_kind: "textbook"` field for the upload-cap carve-out). Cleanest if e2 has already shipped the sandbox-profile baseline.
- **Won't conflict check:** No conflict — strengthens existing threat model.

---

## Phase 3 — Sequence

<!-- populated by SEQUENCE phase -->

### MoSCoW assignment

- **Must** (≤ 60% of total effort): textbook-ingest-e1, textbook-ingest-e2, textbook-ingest-e4
- **Should**: textbook-ingest-e3, textbook-ingest-e5
- **Could**: (none — Should bucket already absorbs the v0/v1 split per challenger F2)
- **Won't (this cycle)**: the explicit Won't list lives in Phase 1 (figure extraction, OCR, separate `search_textbooks` tool, cross-corpus ingest into shared arXiv corpus, Mathpix runtime, Path C, `pdf_get_toc`, `notation.yaml`, `navigation_history`, late chunking).

`score-moscow.py` summary: must=1.75pm (46.7%), should=2.00pm (53.3%), total=3.75pm. PASS (≤ 60% cap).

### RICE ranking — Musts

| ID | Reach | Impact | Confidence | Effort | Score |
|---|---:|---:|---:|---:|---:|
| textbook-ingest-e4 | 10 | 3.00 | 80% | 0.25 | 96.0 |
| textbook-ingest-e1 | 10 | 3.00 | 80% | 0.50 | 48.0 |
| textbook-ingest-e2 | 10 | 3.00 | 50%* | 1.00 | 15.0 |

`*` Confidence defaulted-low for e2 (MinerU CDM on textbook-shaped layout is unverified for arXMCP's specific trajectory until spike-1 runs). RICE ranking puts e4 first by raw score but **sequencing follows dependency order**: e1 ships before e2 ships before e4, because e4 is a schema-only extension that requires e1's `source_kind` column and e2's chunks to exist.

### Now / Next / Later

- **Now** (fully spec'd, in-flight or next-up): textbook-ingest-e1 (schema migration, decomposed into m1–m3 below)
- **Next** (shaped, awaiting capacity): textbook-ingest-e2 (MinerU parser), textbook-ingest-e4 (search filter), textbook-ingest-e3 (hierarchical chunker)
- **Later** (outcome-only, low-confidence horizon): textbook-ingest-e5 (PDF threat hardening doc + non-OA license-truncation policy — ships after the schema+parser+chunker+search slice has demonstrated demand)

### Spike / discovery lane

- `textbook-ingest-spike-1` — Run MinerU 2.5 against the 20-page textbook fixture from [`parser-fidelity-eval-m1`](.claude/notes/milestones/parser-fidelity-eval-m1/) and report CDM score (≤ 2 days, validates `[MUST]` assumption: *MinerU 2.5 CDM lift ≥0.05 over baseline on textbook fixture*). Output: `.claude/notes/capability-scouts/pdf-ingest-2026/spikes/mineru-cdm-bakeoff.md`. Gate: if CDM < 0.85, escalate to CAND-8 (Mathpix-as-batch) and reorder family.
- `textbook-ingest-spike-2` — Draft `.claude/docs/security-pdf-sandbox.md` covering MinerU subprocess sandbox profile (no network, hard CPU/RSS/wall timeout, filesystem whitelist), polyglot detection, embedded-JS refusal, decompression-bomb caps — modelled on [`.claude/docs/security-cdm-sandbox.md`](.claude/docs/security-cdm-sandbox.md) (Threat-3 peer). (≤ 1.5 days, validates `[MUST]` assumption: *subprocess sandbox is sufficient for operator-supplied PDF attack surface*).
- `textbook-ingest-spike-3` — End-to-end isolation test: write a synthetic textbook chunk into `var/arxmcp/notebooks/<slug>/lancedb/` and verify it does NOT appear in the shared arXiv corpus under `search_papers`, and conversely arXiv chunks do not bleed into the notebook query result. (≤ 1 day, validates `[MUST]` assumption: *per-notebook isolation is the correct blast radius*). Output: `tests/test_textbook_notebook_isolation.py`.

### Milestones — Now lane

<!--
Each Now-lane milestone is its own H3 below. Heading format is
`### <slug>-mN — Title` exactly — milestone-pipeline's init-state.sh
greps for this. Do not change it.
-->

### textbook-ingest-m1 — Textbook chunk-id regex + path-traversal regression suite

**Description.** Extend [`ingest/identifiers.py`](ingest/identifiers.py)'s `is_valid_paper_id` to accept the `textbook:<slug>:<sha>` shape in addition to the existing arXiv shapes (`^\d{4}\.\d{4,5}(v\d+)?$` new-style and `^[a-z\-]+/\d{7}(v\d+)?$` old-style). Both inputs must round-trip via the helper `paper_id_from_chunk_id`. Per challenger F3 (MAJOR): the regex sits on a Threat-1 (path-traversal) surface, so ≥5 new regression tests must cover slash/colon/null-byte/whitespace/`\Z`-anchor-bypass injection attempts against the composed regex. NO schema changes in this milestone — identifiers only.

**Acceptance criteria.**
- Given a valid `textbook:<slug>:<sha>` chunk-id, When `is_valid_paper_id` is called, Then it returns True and `paper_id_from_chunk_id` returns `textbook:<slug>`.
- Given an injection-shaped input from the 5+ Threat-1 fixtures, When the regex matches, Then it does NOT match (verified by negative assertion).
- Given an existing arXiv chunk-id, When `is_valid_paper_id` is called, Then behavior is byte-identical to today (snapshot test).
- [ ] `ruff check .` clean and `make test` green; 2129+ tests passing on macOS / Linux.
- [ ] No changes to chunks schema or LanceDB writer in this milestone (deferred to m2).

**Dependencies.** textbook-ingest-e1; none on prior milestones (first in the family).

**Complexity.** S

**Specialist suggestion.** `security-reviewer` — see [`.claude/skills/roadmap/references/specialist-contracts.md`](.claude/skills/roadmap/references/specialist-contracts.md). Create `.claude/agents/security-reviewer.md` matching this contract before running milestone-pipeline, OR proceed without and rely on milestone-pipeline's default adversary critic.

### textbook-ingest-m2 — Chunks-schema columns + LanceDB migration + corpus_version bump

**Description.** Add six optional columns to the chunks schema in [`ingest/schema.py`](ingest/schema.py): `source_kind` (enum: `arxiv | textbook`, default `arxiv`), `license` (string, default `arxiv-license`), `chapter` (string, nullable), `page_start` (int, nullable), `page_end` (int, nullable), `textbook_slug` (string, nullable), plus extending the existing `parser_used` enum with `mineru+latexml`. Bump `corpus_version` per the determinism contract — downstream caches treat the prior version as stale on read. The LanceDB store ([`ingest/store.py`](ingest/store.py))'s idempotent `merge_insert` must round-trip a textbook-shaped chunk and an arXiv-shaped chunk in the same table without column drift. NO MCP surface changes in this milestone (no envelope edits, no schema-hash re-pin — deferred to m3).

**Acceptance criteria.**
- Given a textbook chunk with `source_kind=textbook`, When written then read, Then all six new columns survive round-trip with correct types.
- Given an existing arXiv chunk, When read after the schema bump, Then all new columns are present with the documented defaults and existing fields are byte-identical.
- Given the chunks table at `corpus_version=N`, When the bump lands, Then the new version is `N+1` and existing tests pinning corpus_version are updated in lockstep.
- [ ] [`.claude/docs/snippet-contract.md`](.claude/docs/snippet-contract.md) updated to document the new columns (snippet-rendering semantics unchanged for textbook chunks — `truncated_for_license` flag NOT enforced yet; that lands with e5).
- [ ] `make test` green; chunker tests + chunk-id round-trip + LanceDB merge-insert tests passing.

**Dependencies.** textbook-ingest-e1, textbook-ingest-m1.

**Complexity.** M

**Specialist suggestion.** `determinism-reviewer` + `cache-stability-reviewer` — see [`.claude/skills/roadmap/references/specialist-contracts.md`](.claude/skills/roadmap/references/specialist-contracts.md).

### textbook-ingest-m3 — Coordinated SHA re-pin + notebook_kind field

**Description.** Single coordinated rect-style commit that re-pins `EXPECTED_TOOL_SCHEMA_SHA256` (in [`tests/test_server_tool_schema.py`](tests/test_server_tool_schema.py)) AND `EXPECTED_BP1_SHA256` (in [`tests/test_prompts.py`](tests/test_prompts.py)) AND adds the `notebook_kind: "textbook"` field to the m6 notebook schema in [`server/routes/notebooks.py`](server/routes/notebooks.py). Hash re-pin is byte-stable: schema description edits, key-ordering, and BP1 prompt-prefix edits all bundle into this one commit so the BP1 prompt cache invalidates ONCE for the full family. Per challenger F3 + the orchestrator-rules doc, this is the BP1 discipline checkpoint.

**Acceptance criteria.**
- Given the new chunks-schema columns from m2, When `tools/list` is hashed, Then the SHA matches the re-pinned `EXPECTED_TOOL_SCHEMA_SHA256` and no subsequent milestone in this family re-pins it.
- Given the new chunks-schema columns from m2, When the BP1 prefix is hashed, Then the SHA matches the re-pinned `EXPECTED_BP1_SHA256`.
- Given a notebook created with `notebook_kind="textbook"`, When persisted, Then the field survives round-trip; arxiv-flavor notebooks default to `notebook_kind="arxiv"`.
- [ ] One single rect commit; pre-commit hooks honored; GPG signing on; co-author trailer present.
- [ ] [`.claude/notes/prompts-bp-discipline.md`](.claude/notes/prompts-bp-discipline.md) updated to note the textbook-family bump.
- [ ] `make test` green; no test segfaults on macOS (`KMP_DUPLICATE_LIB_OK` workaround already in place).

**Dependencies.** textbook-ingest-e1, textbook-ingest-m1, textbook-ingest-m2.

**Complexity.** S

**Specialist suggestion.** `cache-stability-reviewer` — see [`.claude/skills/roadmap/references/specialist-contracts.md`](.claude/skills/roadmap/references/specialist-contracts.md).

### textbook-ingest-m4 — PDF upload pre-flight gate (e2 entry)

**Description.** First milestone of epic **e2** (PDFs become HTML5+MathML via sandboxed MinerU). Lands the defensive perimeter at the m6 notebook-upload route BEFORE MinerU is involved — five independent rejection vectors enforced on every operator-supplied PDF for `notebook_kind="textbook"` notebooks. Per spike-2's design at [`.claude/docs/security-pdf-sandbox.md`](.claude/docs/security-pdf-sandbox.md), the pre-flight gate is the **first defense layer** (subprocess sandbox + per-notebook blast radius are layers 2 + 3 — m5 + already shipped, respectively). m4 closes the upload-side perimeter so a malicious PDF never reaches the MinerU subprocess.

Concrete deliverables:

- **Magic-byte sniff.** First 5 bytes must be `%PDF-` (ISO 32000). Mirrors the existing m6 `_is_html_bytes` helper; lifts the per-route `_MAGIC_SNIFF_BYTES = 16` pattern.
- **Polyglot tail check.** Reject any PDF whose final 1 KB contains a ZIP central-directory marker (`PK\x05\x06`) or HTML closing tag (`</html>`, case-insensitive). Defense against PDF+ZIP / PDF+HTML polyglot attacks.
- **`pdfid` JavaScript-detection vendored helper.** New `tools/security/pdfid.py` (pdf-ingest-2026 CAND-2 — vendored, NOT git-submodule per no-fork policy). String-grep over PDF bytes for `/JS`, `/JavaScript`, `/OpenAction`, `/AA` (additional actions) entries. Defense-in-depth before MinerU's PyMuPDF layer sees the file.
- **Page-count probe.** Lightweight pre-MinerU metadata-only probe (PyMuPDF or a string-grep fallback that walks `/Type /Page` markers). Reject any PDF with >5000 declared pages (Bourbaki tops out around 500; 5000 is a 10× safety margin).
- **Upload cap raise.** From 10 MB (m6 default) to 200 MB **ONLY** for notebooks where `notebook_kind="textbook"`. arXiv-kind notebooks keep the 10 MB cap. Implemented at the m6 upload route's body-size check, gated on the `notebook_kind` SQLite column added in m3.
- **`tools/security/` directory bootstrap.** New `tools/security/README.md` documenting the no-fork vendoring discipline (per CAND-2's challenger F6 note). This is the first vendored security tool; the README establishes the pattern.

**Acceptance criteria.**

- Given a textbook-notebook upload, When the request body's first 5 bytes are not `%PDF-`, Then HTTP 415 returns with a clear "not a PDF" detail BEFORE any disk write occurs.
- Given a PDF whose final 1 KB contains a `PK\x05\x06` marker or `</html>` substring, When the upload reaches the route, Then HTTP 415 returns with a "polyglot detected" detail.
- Given a PDF whose body contains a `/JS` or `/JavaScript` PDF entry, When the upload reaches the route, Then HTTP 415 returns with an "embedded JavaScript detected" detail.
- Given a PDF with >5000 declared pages, When the upload reaches the route, Then HTTP 415 returns with a "page count exceeded" detail.
- Given a textbook-notebook upload of 150 MB, When the request reaches the route, Then it succeeds (vs. the 10 MB cap for arxiv-kind notebooks); 250 MB returns HTTP 413.
- Given an arxiv-kind notebook upload of 50 MB, When the request reaches the route, Then HTTP 413 returns (the 10 MB cap still applies for arxiv-kind).
- [ ] `tools/security/pdfid.py` lands as a small, dependency-free Python module — NOT a git submodule, NOT a vendored copy lifted from upstream's source tree (no-fork policy). Implementation can take ideas from Didier Stevens' `pdfid.py` (well-known public-domain tool) but is written fresh.
- [ ] `tools/security/README.md` documents the vendoring discipline.
- [ ] `make test` green; ≥10 negative-vector tests covering each rejection path.
- [ ] No changes to MinerU integration (deferred to m5).
- [ ] No changes to MCP tool surface or BP1 prefix; `EXPECTED_TOOL_SCHEMA_SHA256` + `EXPECTED_BP1_SHA256` untouched.

**Dependencies.** textbook-ingest-m1, m2, m3 (all shipped). Spikes 2 + 3 inform the design but are not commit-time blockers.

**Complexity.** M

**Specialist suggestion.** `security-reviewer` — see [`.claude/skills/roadmap/references/specialist-contracts.md`](.claude/skills/roadmap/references/specialist-contracts.md). The vendoring discipline + 5-rejection-vector surface area is exactly the area `security-reviewer` is designed to scrutinize.

---

## Phase 4 — Materialize

<!-- populated by MATERIALIZE phase -->

### Validation

- `validate-roadmap.py`: pass
- Must-cap: 46.7% (≤ 60%)
- All Now-lane milestones have AC: yes
- Slug format valid: yes

### GitHub tickets

Not requested (run roadmap with `--github` to bundle epic + story bodies).

### Next step

First Now-lane milestone: `textbook-ingest-m1`. To execute it end-to-end, run:

    /milestone-pipeline textbook-ingest-m1

This skill will not invoke milestone-pipeline. Cache stays warmer if you start the milestone-pipeline session within 5 minutes.

Suggested execution order before kicking off m1:

1. Run the three spikes (textbook-ingest-spike-1/2/3) — they are cheap (≤ 4.5 days total) and resolve the `[MUST]` confidence-low items in Phase 1. spike-1 in particular can re-rank the family if MinerU's CDM is worse than assumed.
2. Then `/milestone-pipeline textbook-ingest-m1` (chunk-id regex + path-traversal regression suite).
3. Then m2 (schema columns + LanceDB migration + corpus_version bump).
4. Then m3 (coordinated SHA re-pin + `notebook_kind` field) — this is the BP1 cache-invalidation checkpoint.

After the Now lane closes, the Next-lane epics (e2 MinerU parser, e4 search filter, e3 hierarchical chunker) get their own Now-lane decomposition via a `/roadmap textbook-ingest` resume run that populates a new milestone block under Phase 3 — OR each epic ships as its own `/milestone-pipeline` invocation if the operator prefers single-milestone execution against this same roadmap doc.

---

<!-- end:roadmap -->
