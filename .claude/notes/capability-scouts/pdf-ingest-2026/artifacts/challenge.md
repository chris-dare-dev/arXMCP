# Challenge — pdf-ingest-2026

**Phase 3 of 4 (challenger pass).** Adversarial evaluation of all 17
candidates in `synthesis.md` against the 10-axis CHALLENGER checklist
(cache byte-stability, local-first+Docker, math fidelity, security
threat-model, MCP 2025-06-18 spec compliance, no-fork policy, test
discipline, effort honesty, value vs proof-chain mission, sequencing).

---

## 1. Executive summary

- **0 BLOCKERs, 5 MAJORs, 7 MINORs, 5 NONEs.** No candidate is
  hard-killed; the bundle holds together with discipline, but five
  candidates carry hidden cost the synthesis softened.
- **The biggest risk is scope-creep masquerading as triangulation.**
  CAND-3 (textbook chunker), CAND-11 (schema migration), CAND-15
  (notation.yaml), and CAND-14 (eval fixture) are each "M" or "S"
  in isolation but co-arrive as a single textbook-ingest milestone
  whose true LOC is closer to E14_Tier5plus (~1800 LOC) than the
  ~600 LOC the synthesis implies per item. Phase 4 must price the
  bundle, not the items.
- **CAND-7 (CDM) is correctly sequenced first** — it is the only
  candidate that makes T2 falsifiable. Every parser-choice candidate
  (CAND-1, CAND-8, CAND-17) should be gated on CAND-7 landing first,
  which the synthesis already implies but does not pin.
- **CAND-9 (`pdf_get_toc`) is a MAJOR objection on BP1-discipline
  grounds**; the synthesis's own resolution-candidate (c) is correct
  but the candidate is still listed as live. T1 resolves against
  new tools; my call mirrors the synthesis but firms it up.
- **T3 (Path B) is the cheapest decision in the catalog**: the
  sample-of-10 is 30 minutes of operator work; until it runs,
  CAND-10 is unscored. Pin it as a prerequisite, not a deliverable.

---

## 2. BLOCKER findings

_(none — every candidate survives the 10-axis gauntlet in some
v0 form. The synthesis's parking-lot already absorbed the genuine
hard-constraint violations: ColPali stays parked at CAND-16, Anna's
Archive / NotebookLM-as-substrate are explicitly out of scope.)_

---

## 3. MAJOR findings

### F1 — CAND-9 `pdf_get_toc` violates BP1 discipline for marginal UX

- **Candidate id:** CAND-9
- **Title:** `pdf_get_toc` MCP tool for textbook navigation
- **Severity:** MAJOR
- **Objections:**
  - **Axis 1 (cache byte-stability):** Adding any 8th tool bumps
    `tools/list` payload bytes → forces re-pin of
    `EXPECTED_TOOL_SCHEMA_SHA256` at
    `tests/test_server_tool_schema.py:94`, which in turn invalidates
    every agent's BP1 (1-hour TTL, per
    `.claude/notes/07-multi-agent-caching.md:74-85`) prompt cache
    org-wide on first call. The synthesis flags this; multi-agent
    scout F-G7 already rated it HIGH; the candidate should not
    survive Phase 3 in its current shape.
  - **Axis 9 (value vs proof-chain mission):** The "Lean kernel is
    the better critic" framing
    (`.claude/notes/01-mission-and-context.md`) says invest in
    retrieval, not in agent navigation chrome. TOC navigation is
    chrome.
  - **Axis 5 (MCP spec):** A TOC tool that returns hierarchical
    structure is fine for the 2025-06-18 spec, but the
    competitive-scout precedent (jztan/pdf-mcp 8-tool surface)
    quietly imports a different design philosophy — multi-tool
    granularity over envelope discipline. arXMCP has spent E06_S03,
    E06_S04, E08_S02 hardening the opposite discipline.
- **Suggested scope adjustment:** Kill the standalone tool. Surface
  TOC information as an envelope field on the existing `get_chunk`
  response when `level=chapter` is the result level (CAND-3 already
  introduces the `chapter` level). Agents reach the TOC via
  `search_papers(query="table of contents", filters={"level":
  "chapter", "textbook_slug": "..."}, k=50)` — zero new tools,
  zero BP1 invalidation. This is the synthesis's own
  resolution-candidate (c); I'm firming it from "Phase 3 should
  call" to "Phase 3 calls: drop CAND-9 as a tool."

### F2 — CAND-3 textbook chunker is L in isolation, XL in practice

- **Candidate id:** CAND-3
- **Title:** Textbook-aware hierarchical chunker
- **Severity:** MAJOR
- **Objections:**
  - **Axis 8 (effort honesty):** Synthesis sizes "L". Compare to E10
    indices (~1000 LOC each shipped) — the textbook chunker has
    strictly more discrete responsibilities (TOC discovery
    fallback, per-chapter preamble inheritance, per-section
    preamble inheritance, exercise-as-chunk, definition-as-chunk,
    chunker_version v2.0 stamping, golden-fixture regeneration).
    True floor is ~1500-2000 LOC + ~50 tests.
  - **Axis 3 (math fidelity):** The synthesis assumes the existing
    theorem-aware chunker `ingest/chunker.py` can be paralleled
    cleanly. But adversary F-M6 noted per-chapter preamble breaks
    the "downstream chunker is untouched" promise. The existing
    chunker pipes through `ingest/preamble.py` which is paper-shaped
    (single-block extraction). Textbook chunker needs a redesigned
    preamble cascade (book → chapter → section). That is not a
    parallel module; that is a fork of the preamble subsystem.
  - **Axis 10 (sequencing dependencies):** CAND-3 hard-depends on
    CAND-11 (schema migration adds `chapter`, `section`,
    `exercise_number`, `textbook_slug`, `level` enum values) and
    softly depends on CAND-15 (notation.yaml for macro recovery).
    The synthesis lists these as siblings; they are a logical
    bundle that must ship in a single milestone family or the
    schema lands without consumers.
- **Suggested scope adjustment:** Treat CAND-3 + CAND-11 + CAND-15
  as one milestone family ("textbook-ingest-m1"), priced at the
  E14_Tier5plus precedent (~1800 LOC, 5 logical commits, single
  state.json). v0 cut: book/chapter/section only; defer
  exercise-as-chunk and definition-as-chunk to a v1 follow-up
  (those land cleanest after CAND-5 `defines` edge anyway).
  CAND-4 (late chunking) stays scoped out of the v0 — it is a
  pure quality lever that can be added in v1 once CDM
  measurements (CAND-7) say whether it helps.

### F3 — CAND-11 schema migration understates the snippet-contract surface

- **Candidate id:** CAND-11
- **Title:** Schema migration for textbook chunk identity
- **Severity:** MAJOR
- **Objections:**
  - **Axis 4 (security threat-model):** `ingest/identifiers.py:67`
    `is_valid_paper_id` is intentionally strict
    (E13_S01 path-traversal mitigation, m1-rect-F3 `\Z`-anchor
    hardening). The synthesis says "extends regex to accept
    textbook form" in one line; in reality this is a Threat 1
    surface change — `textbook:<slug>:<sha>` introduces a `:`
    separator and operator-controlled `<slug>` text. The new
    regex must reject `..` in slug, must cap slug length, must
    forbid filesystem-meaningful characters, and must compose
    correctly with `is_valid_chunk_id` at
    `ingest/identifiers.py:77`. This is a security-critical
    regex change with ≥5 new path-traversal regression tests
    required.
  - **Axis 1 (cache byte-stability):** Synthesis correctly flags
    `EXPECTED_TOOL_SCHEMA_SHA256` re-pin if envelopes change. But
    `get_chunk` envelope grows `page_start`, `page_end`, `chapter`,
    `exercise_number`, `textbook_slug`, `license` per F-G5 — that
    is six new optional fields on the most-called tool. Even with
    `null` defaults for arxiv chunks, the JSON-Schema for the
    `get_chunk` response shape changes, which bumps the tool-list
    SHA. The paired `EXPECTED_BP1_SHA256` at
    `tests/test_prompts.py:632` must be re-pinned in lockstep.
  - **Axis 5 (MCP spec):** Tool results are not streamed; growing
    the envelope is spec-compatible, but the snippet-contract
    license truncation (`truncated_for_license: true`) introduces
    new semantic content — agents need to be told what the flag
    means via a tool description update, which is itself a BP1
    invalidation.
- **Suggested scope adjustment:** Keep CAND-11 in the textbook-ingest
  family but explicitly budget: (a) ≥5 new path-traversal regression
  tests against the extended `is_valid_paper_id`, (b) single
  coordinated `EXPECTED_TOOL_SCHEMA_SHA256` + `EXPECTED_BP1_SHA256`
  re-pin commit at the end of the bundle (not piecemeal), (c) a
  CHANGES.md API-version bump entry. Document the license-truncation
  flag in `.claude/docs/snippet-contract.md` before envelope changes
  land.

### F4 — CAND-17 VLM-as-extractor: hosted-Claude branch trips the runtime ban

- **Candidate id:** CAND-17
- **Title:** VLM-as-extractor (hosted Claude OR local Llama-3.2-Vision)
- **Severity:** MAJOR (on the hosted branch); MINOR on the local branch
- **Objections:**
  - **Axis 2 (local-first + Docker):** The hosted-Claude branch
    requires anthropic SDK egress. The synthesis's defense
    ("CLAUDE.md §4.7 ban is at runtime inside `server/`; a
    one-time batch tool in `tools/` is permitted") is technically
    correct but operationally dangerous: every batch tool that's
    "one-time" tends to grow runtime users (CAND-8 Mathpix is the
    same shape and was synthesized correctly; CAND-17 doubles the
    egress surface for the same gain).
  - **Axis 4 (security threat-model):** Hosted vision sends raw
    PDF page bytes to Anthropic. For non-OA textbook content this
    has license implications (CAND-11 F-G5 license column).
    Operator opt-in via env var is the right gate, but the runbook
    needs to be more explicit than CAND-8's analog because vision
    APIs cost ~10× per page vs Mathpix.
  - **Axis 8 (effort honesty):** "S as one-time-batch tool" is
    accurate; "M if integrated as runtime parser candidate" is
    where the synthesis hand-waves — runtime integration means
    feeding into CAND-1's bake-off, which means adding it to
    `ingest/pdf_<parser>.py` driver shape, which means it lives
    in the parser hot path. That is L, not M.
  - **Axis 7 (test discipline):** No path to test the hosted branch
    in CI without burning Anthropic credits. Local branch (Llama-
    3.2-Vision) needs `requires_model` marker — adds yet another
    opt-in env var to the test matrix.
- **Suggested scope adjustment:** Split CAND-17 into two
  candidates. **CAND-17a (local VLM):** keep as a candidate in the
  CAND-1 bake-off; gate on CAND-7 (CDM) demonstrating ≥0.05 lift
  on the textbook fixture. **CAND-17b (hosted Claude vision):**
  drop from this catalog. It is strictly dominated by CAND-8
  Mathpix on the same use case (Mathpix is purpose-built for math,
  cheaper per page, and operator already has the env-var pattern).
  The "VLMs are now capable" argument from adversary F-A5 is
  satisfied by 17a alone.

### F5 — CAND-1 parser bake-off sequencing is right but the schema bump isn't free

- **Candidate id:** CAND-1
- **Title:** Replace Marker with MinerU 2.5 OR Docling
- **Severity:** MAJOR
- **Objections:**
  - **Axis 6 (no-fork policy):** All three candidate parsers are
    subprocess invocations, not imports — compliant. But the
    synthesis's "subprocess invocation pattern mirrors latexmlc"
    elides the sandboxing requirement. Per
    `.claude/notes/08-security-observability-ops.md:35-50` Threat
    3, LaTeXML runs with hard timeout, separate UID, filesystem
    write whitelist, no network. Marker/MinerU/Docling have NOT
    been hardened to that profile; each parser pulls in its own
    Python deps (transformers, torch, custom models) into the
    sandbox. Each new parser is an additional supply-chain
    surface (Threat 6).
  - **Axis 2 (local-first + Docker):** MinerU 2.5 and olmOCR 2
    have GPU dependencies. olmOCR 2 explicitly requires
    "12GB+ VRAM" per the synthesis itself. arXMCP's minimum
    workstation profile per
    `08-security-observability-ops.md:326` is "16 GB RAM, 500 GB
    SSD, no GPU." The recommended profile has GPU but the
    Docker-compose path needs nvidia-runtime configuration that
    breaks on Macs (no CUDA). For an M2 Max workstation this is
    fine (unified memory), but the synthesis claim that
    "downstream chain stays unchanged" hides the per-parser
    install footprint.
  - **Axis 8 (effort honesty):** "M (parser-swap is the easy
    part)" is accurate for ONE parser. The bake-off requires
    installing and sandboxing all three (Marker, MinerU,
    Docling) plus glue code for each parser's output shape.
    That is L, not M, even if the eventual single winner-driver
    is M.
- **Suggested scope adjustment:** Sequence CAND-7 (CDM) FIRST as
  a hard prerequisite. Then run CAND-1's bake-off as a dedicated
  spike milestone (not bundled with the textbook chunker). v0
  bake-off ships MinerU 2.5 only (Apache-2.0, highest reported
  CDM, no GPL-3 concern); Docling and olmOCR 2 stay parked as
  parser-registry alternatives. The bake-off doc lives in
  `.claude/docs/textbook-parser-bakeoff.md` per the synthesis
  sketch. Sandbox profile (Threat 3-equivalent) must ship in the
  same milestone as the parser; no parser lands without its
  sandbox spec.

---

## 4. MINOR findings

### F6 — CAND-2 pdfid carve-out understates the threat-model doc work

- **Candidate id:** CAND-2
- **Title:** Per-notebook PDF upload gate with pdfid pre-scan
- **Severity:** MINOR
- **Objections:**
  - **Axis 4 (security):** Adding a new Threat 3.5 / Threat 8 to
    `.claude/notes/08-security-observability-ops.md` is correctly
    scoped, but raising the upload cap from 10 MB → 200 MB
    expands the resource-exhaustion surface (Threat 4). Per-
    notebook cap must compose with the global byte cap from
    E13_S04. The synthesis says "the carve-out docs are larger
    than the code" — true, but those docs must include the
    Threat-4 composition rule explicitly, not just Threat 3.5
    surface scan.
  - **Axis 6 (no-fork policy):** Vendoring `pdfid.py` (BSD) is
    license-compatible and ~500 LOC — fine. But it is the first
    vendored security tool in the repo, so it sets a precedent.
    Add a `tools/security/README.md` documenting the vendoring
    discipline (commit SHA pin, BSD attribution, no upstream
    patches, quarterly upstream-diff check).
- **Suggested scope adjustment:** Ship as drawn; add the
  Threat-4 composition rule to the docs explicitly; add the
  vendoring discipline README.

### F7 — CAND-5 `defines` edge schema bump under-prices the Kùzu migration cost

- **Candidate id:** CAND-5
- **Title:** Add `defines` / `defined_by` edge to Kùzu graph
- **Severity:** MINOR
- **Objections:**
  - **Axis 10 (sequencing dependencies):** Kùzu archived
    2025-10-10 per CLAUDE.md §8 gotcha 2 — repo pins
    `kuzu==0.11.3` as last stable. Schema v3 migration on an
    archived embedded DB is fine for arXMCP's single-workstation
    lifetime, but any failure-mode in the v3 migration has no
    upstream fix path. Add a v2→v3 migration test that exercises
    the full corpus_version cache invalidation pattern
    (`.claude/notes/07-multi-agent-caching.md:121-167`).
  - **Axis 1 (cache byte-stability):** Synthesis correctly notes
    that adding `defines` / `defined_by` enum values bumps
    `TOOL_SCHEMA_VERSION`. Pair with re-pinning
    `EXPECTED_TOOL_SCHEMA_SHA256` at
    `tests/test_server_tool_schema.py:94` and
    `EXPECTED_BP1_SHA256` at `tests/test_prompts.py:632`. Single
    coordinated commit; document the API-version bump in
    CHANGES.md per CLAUDE.md §4.3.
  - **Axis 9 (value vs mission):** Multi-cited (3 briefs),
    on-mission (definition-chain extension serves the
    autoformalizer use case directly). Genuine high-leverage
    capability; rating is MINOR only because of the
    Kùzu-archived-upstream sequencing concern.
- **Suggested scope adjustment:** Ship as a standalone milestone
  (not bundled with textbook-ingest family). The graph schema
  v3 bump benefits the arxiv corpus today, independent of
  textbook ingest. Add an explicit v2→v3 migration regression
  test under `tests/test_kuzudb_migration.py`. Re-pin the two
  SHAs in one coordinated rect commit.

### F8 — CAND-6 page-range citation is correct but cardinality-shy on the schema

- **Candidate id:** CAND-6
- **Title:** Page-range citation on every textbook chunk
- **Severity:** MINOR
- **Objections:**
  - **Axis 1 (cache byte-stability):** Folded into CAND-11's
    `get_chunk` envelope growth; the synthesis's "no open
    questions" reads as too clean. The envelope-field addition
    must coordinate with the same BP1/BP2 re-pin commit as
    CAND-11.
  - **Axis 3 (math fidelity):** Page-range citation is
    operator-facing verification, not retrieval quality. It's a
    hard requirement (synthesis agrees) but does not improve
    retrieval; pricing should reflect that it is a UX/audit
    feature, not a retrieval-quality lever.
- **Suggested scope adjustment:** Fold into CAND-11's milestone
  family (schema migration sibling). No standalone milestone.

### F9 — CAND-7 CDM eval gate: the 20-page fixture is the slow part

- **Candidate id:** CAND-7
- **Title:** CDM as Tier-1 parser-fidelity gate
- **Severity:** MINOR
- **Objections:**
  - **Axis 8 (effort honesty):** "S (CDM impl ~hundreds of LOC)"
    is reasonable for the algorithm. But CDM needs a
    pdflatex/MathJax render pipeline as a subprocess (the
    "render predicted LaTeX back to an image" step), which
    means another sandboxed subprocess like LaTeXML — Threat 3
    surface again. The 20-page hand-curated fixture
    (`tests/eval/textbook_fixtures/` per CAND-14) is the
    week-of-operator-work hidden in the S size.
  - **Axis 7 (test discipline):** CDM scoring needs
    pdflatex + a CV library (OpenCV or similar) at test time.
    Either gate behind `requires_model` opt-in (won't run in
    default `make test`) or accept the install footprint. The
    M2 Max segfault landmine (CLAUDE.md §8 gotcha 1) is a
    cautionary precedent for adding CV deps.
  - **Axis 10 (sequencing dependencies):** CAND-7 is the
    keystone of T2 and gates CAND-1, CAND-8, CAND-17. The
    synthesis's "ship BEFORE any parser commitment" line at the
    bottom is correct and should be pinned as a hard sequencing
    rule, not advisory.
- **Suggested scope adjustment:** Ship CDM impl as `S` but
  bundle with CAND-14 (eval fixture) as a single milestone
  ("parser-fidelity-eval-m1"), priced M. Mark CDM tests
  `requires_model`-equivalent (new marker:
  `requires_pdflatex`); document in CLAUDE.md §4.5.

### F10 — CAND-8 Mathpix carve-out is sound; threat-model gate must be explicit

- **Candidate id:** CAND-8
- **Title:** Mathpix-as-batch one-time exception
- **Severity:** MINOR
- **Objections:**
  - **Axis 2 (local-first + Docker):** Synthesis's framing
    (one-time prep, analogous to Academic Torrents seed +
    OpenAlex + INSPIRE-HEP) is correct. The
    `ARXMCP_CONTACT_EMAIL` precedent
    (`tools/arxiv_fetch.py`) is the right analog. Adding
    `ARXMCP_MATHPIX_API_KEY` as the opt-in gate is correct.
  - **Axis 4 (security):** Hosted inference = data egress.
    Per-textbook config (`notebook.yaml`) must include explicit
    `license_acknowledged: true` flag from operator confirming
    fair-use; this lives in the same enforcement layer as
    CAND-11's license column.
  - **Axis 9 (value vs mission):** Highest-fidelity math OCR on
    the market; for ≥10 high-value reference textbooks
    (Hartshorne, Griffiths-Harris, Bourbaki, Polchinski) the
    one-time cost is trivial vs the perpetual retrieval-quality
    gain. On-mission per "Lean kernel is the better critic"
    framing — better math fidelity at corpus build time is
    upstream of every downstream LLM call.
- **Suggested scope adjustment:** Ship as drawn. Add the
  `license_acknowledged: true` flag to the per-textbook config
  schema; surface the egress gate in CHANGES.md per the
  Academic Torrents precedent.

### F11 — CAND-12 navigation_history envelope-on-existing-tools is correct

- **Candidate id:** CAND-12
- **Title:** `navigation_history` field on SessionState
- **Severity:** MINOR
- **Objections:**
  - **Axis 1 (cache byte-stability):** Surfacing the field via
    an envelope-on-existing-tools (not via new
    `get_session_history` MCP tool) is correct — bumps
    `EXPECTED_TOOL_SCHEMA_SHA256` but only as part of CAND-11's
    coordinated re-pin commit. Adding the field non-additively
    (always present, even when empty `[]`) is the
    byte-stability-safe pattern.
  - **Axis 5 (MCP spec):** Per-session state belongs on
    `Mcp-Session-Id` (the spec's primary session primitive);
    this is the right placement.
  - **Axis 8 (effort honesty):** "XS, ~50 LOC" is accurate IF
    the envelope-only route. New MCP tool route would be S+.
- **Suggested scope adjustment:** Ship envelope-only. Cap
  `navigation_history` at 2 KB / session with FIFO truncation as
  the synthesis suggests. No standalone milestone; fold into the
  textbook-ingest family as a final wire-up step after CAND-3 +
  CAND-11 land.

### F12 — CAND-13 search_papers cross-corpus filter avoids a new tool — good call

- **Candidate id:** CAND-13
- **Title:** `search_textbooks` vs co-mingling decision
- **Severity:** MINOR
- **Objections:**
  - **Axis 1 (cache byte-stability):** Synthesis recommendation
    (a) — extend `search_papers` with `source_kind` filter — is
    correct. Adding an enum value to the `filters` parameter
    bumps `EXPECTED_TOOL_SCHEMA_SHA256` but does not add a
    tool. This is the right trade.
  - **Axis 9 (value vs mission):** Cross-corpus search lets the
    autoformalizer find a definition in Hartshorne and a
    related lemma in a recent arXiv paper in one call. This is
    the load-bearing UX that justifies textbook ingest at all
    — synthesis is right to flag F-C2 (shipping Marker without
    a handler is shipping into a vacuum).
  - **Axis 10 (sequencing dependencies):** Hard-depends on
    CAND-11 (`source_kind` column must exist before the filter
    works). Same milestone family.
- **Suggested scope adjustment:** Ship as drawn; coordinate
  with CAND-11 schema bump. Per-notebook LanceDB isolation
  needs the handler to be cross-notebook-aware when
  `source_kind` filter is unset — synthesis doesn't address
  this; add an explicit "queries default to the active
  notebook unless `source_kind=any`" rule.

---

## 5. Clean candidates (NONE)

These candidates survive the 10-axis gauntlet without scope objections.

- **CAND-4** — Late chunking. Pure quality lever, opt-in via
  `notebook_kind`, no schema bump, no BP1 invalidation, no new
  tool. Worth doing once CDM (CAND-7) confirms the quality lift on
  textbook content. Defer to v1 of the textbook bundle, not v0.
- **CAND-10** — Source-first `.tex` fetcher (Path B revised). The
  synthesis's "sample-of-10 verification as prerequisite, not
  deliverable" framing is exactly right. The candidate itself
  (a per-author registry feeding an existing `arxiv_fetch.py`-
  shaped tool) is small and local-first; my T3 call below pins
  the sample-of-10 to a half-day prerequisite spike.
- **CAND-14** — Textbook eval fixture. The fixture curation is
  the slow part (hand-labeling 20 pages with ground-truth MathML
  is ~1 day of operator math expertise), but the harness wiring
  is straightforward and bundles cleanly with CAND-7. No
  cache/security/spec objections.
- **CAND-15** — `notebook_kind: "textbook"` + notation.yaml.
  Per-notebook config addition is small. notation.yaml is operator
  curation, not code. Mitigates the F-M4 macro-loss problem
  directly. Folds into the textbook-ingest milestone family.
- **CAND-16** — ColPali / ColQwen2. Correctly parked. Un-park
  trigger documented. No objection.

---

## 6. Cross-cutting tensions resolved

### T1 — New MCP tools vs envelope-only extensions

**Call:** Envelope-only. CAND-9 (`pdf_get_toc`) drops as a
standalone tool. CAND-12 (`navigation_history`) ships
envelope-only. CAND-13 (`search_textbooks`) ships as
`search_papers` extension, not new tool. The
`EXPECTED_TOOL_SCHEMA_SHA256` re-pin happens ONCE in the
textbook-ingest milestone family (covering envelope additions
to `get_chunk` + `search_papers` filter enum + paired
`EXPECTED_BP1_SHA256`). Single coordinated commit; document in
CHANGES.md as an API-version bump per CLAUDE.md §4.3.

Rationale: The 7-tool surface is a hard-earned discipline
(E06_S03 reduced 9 → 7 explicitly). Every new tool costs every
agent's BP1 cache, which is the longest-lived prefix per
`.claude/notes/07-multi-agent-caching.md:74-85`. The competitive
scout's "8-tool precedent" argument loses on arXMCP's measured
cache-discipline ROI.

### T2 — Marker vs MinerU vs Docling for Path A primary parser

**Call:** CAND-7 (CDM) ships FIRST as a hard prerequisite.
CAND-1's bake-off ships as a dedicated spike milestone
immediately after, NOT bundled with the textbook chunker.

Recommendation under the v0 cut: bake-off ships MinerU 2.5
only (Apache-2.0, highest reported CDM, no GPL concern,
2026-stable upstream cadence). Docling stays parked as a
parser-registry alternative pending CDM-measured lift over
MinerU on the textbook fixture. Marker is dropped from the
v0 — GPL-3 boundary concern (adversary F-A1) is real per the
no-fork policy spirit even when subprocess-clean.

Rationale: synthesis's "let the numbers decide" is correct, but
the synthesis under-priced what "running the bake-off" means
(sandboxing 3 parsers + glue for each output shape — see F5).
Picking MinerU-only as the v0 winner reduces bake-off scope
from 3-way to 2-way (MinerU vs status-quo "ar5iv only"
baseline), which is shippable in one milestone. Docling un-park
trigger: CDM gap ≥ 0.05 on the textbook fixture.

### T3 — Path B viability (source-first .tex fetcher)

**Call:** Run the sample-of-10 as a half-day prerequisite spike
BEFORE Phase 4 scopes the milestone. Until the spike runs,
CAND-10 is unscored.

If hit-rate ≥80% on the sample-of-10 (Milne, Caraiani, Vakil,
Stacks Project, Gathmann, Olsson, Conrad, Poonen,
Hartshorne-supplementary, KÉRDÉ Arizona): CAND-10 stands as a
standalone S milestone, ships before CAND-1's parser bake-off
(source-first dominates parser-output for fidelity).

If hit-rate <60%: CAND-10 collapses into a "best-effort source
preflight" sub-feature of CAND-1's parser driver (try source,
fall through to parser on miss).

If hit-rate 60-80%: CAND-10 ships as an opt-in operator tool
(`notebook_fetch.py --prefer-source`) but is not on the
critical path — the parser bake-off (CAND-1) carries the
load-bearing weight.

Rationale: adversary F-B1 (CRITICAL) caught that the dive's
single named-author evidence (Milne) is empirically wrong.
The sample-of-10 is 30 min - 2 hours of operator work and
turns a CRITICAL uncertainty into a falsifiable measurement.
This is the cheapest decision in the catalog by leverage.

---

## 7. Recommended kill list

- **CAND-9** (`pdf_get_toc` as a standalone MCP tool) — kill.
  Replace with envelope-on-`get_chunk` per F1 / T1.
- **CAND-17b** (hosted Claude vision as VLM-as-extractor) — kill.
  Strictly dominated by CAND-8 Mathpix on the same use case per
  F4. CAND-17a (local Llama-3.2-Vision) survives as a candidate
  in the CAND-1 bake-off, gated on CAND-7 CDM measurement.
- **Marker as v0 parser choice** — drop from the bake-off short
  list per T2. GPL-3 subprocess boundary is the right reason
  per F-A1 + arXMCP no-fork-spirit discipline. Park for parser-
  registry diversity only.

No other candidate is killed. CAND-3 + CAND-11 + CAND-15 +
CAND-6 + CAND-12 + CAND-13 form a single textbook-ingest
milestone family. CAND-7 + CAND-14 form the parser-fidelity-eval
prerequisite milestone. CAND-1 (MinerU-only) ships as a
post-CDM spike milestone. CAND-8 ships independently
(operator-tool layer). CAND-5 ships independently (Kùzu graph
schema v3 bump). CAND-10 scopes after T3 sample-of-10 spike.
CAND-4 + CAND-16 + CAND-17a remain parked under the deferred-
work-tracker for v1+ un-park triggers.
