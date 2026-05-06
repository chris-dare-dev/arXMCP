# E15 — Quality of Life (Tier 6) and v2 Deferred Work (Tier 7)

**Epic dependencies:** E10, E12.

**Status:** **Mostly deferred.** This epic exists to track work that is explicitly out of v1 scope but motivates v1 design decisions. Each sub-issue is labelled with its tier and whether it is "candidate" (Tier 6 — may land post-v1 if data justifies) or "deferred / v2" (Tier 7 — out of scope until the autoformalizer integration becomes the primary goal).

**Goal:** keep deferred work visible and traceable so it doesn't accidentally creep into v1, and so it's ready to start when v1 is in steady state.

**Effort:** not budgeted — these are scoped issues that wait for trigger conditions described per item.

**References:** `09-feature-priorities.md` § Tier 6, § Tier 7 (v2), § Decision points to revisit later, § Things to explicitly NOT build in v1; `05-storage-and-indexing.md` § ColBERT for long technical chunks (v1.5 feature), § Equation embeddings (v2 feature).

---

### E15_S01 — Author-disambiguated index via ORCID (Tier 6 candidate)

**Description.** Per `09-feature-priorities.md` Tier 6 — author-disambiguated index. ORCID data already arrives via INSPIRE/OpenAlex enrichment in E09_S05. This issue would expose `find_papers_by_author(orcid)` and disambiguate the `authors` filter in `search_papers`.

**Acceptance criteria.**
- [ ] Tool `find_papers_by_author` accepts an ORCID URL.
- [ ] `search_papers` `filters.authors` accepts ORCID URLs in addition to plain names.
- [ ] Test: an author with multiple identical-name collisions is disambiguated correctly.

**Dependencies.** E09_S05.

**Complexity.** M.

**Labels.** `area:graph`, `area:server`, `kind:feature`, `tier:6`.

---

### E15_S02 — Withdrawal/replacement flag UI surface (Tier 6 candidate)

**Description.** Per `09-feature-priorities.md` Tier 6 — surface `withdrawn=true` flag visibly in tool-result rendering hints. The data is already populated in E11_S10; this issue is about ensuring agents see the flag prominently.

**Acceptance criteria.**
- [ ] Withdrawn papers in `search_papers` results carry an explicit `warning: "withdrawn"` field.
- [ ] `get_paper` for a withdrawn paper has the warning at the top of the response.
- [ ] Documented in `docs/server/withdrawal-handling.md`.

**Dependencies.** E11_S10.

**Complexity.** S.

**Labels.** `area:server`, `tier:6`.

---

### E15_S03 — TikZ-cd diagram extraction for math.AG (Tier 6 candidate)

**Description.** Per `09-feature-priorities.md` Tier 6 — TikZ-cd diagrams (commutative diagrams in math.AG) carry significant semantic content. Extract them as a separate retrievable atom kind.

**Acceptance criteria.**
- [ ] Chunker recognizes `tikzcd` environments and emits `DiagramAtom` records.
- [ ] Each atom has a normalized graph representation (nodes + edges) for graph-similarity retrieval.
- [ ] New `find_diagram` tool (schema TBD).
- [ ] Trigger condition: a documented retrieval-failure case where a tikz-cd-rich paper is missed by chunk retrieval, but a known diagram match exists.

**Dependencies.** E04_S08, E10_S05.

**Complexity.** XL.

**Labels.** `area:parser`, `area:retrieval`, `tier:6`, `kind:research`.

---

### E15_S04 — Proof-skeleton classifier (Tier 6 candidate)

**Description.** Per `09-feature-priorities.md` Tier 6 — small fine-tuned model that tags theorem chunks with proof-skeleton labels (induction, contradiction, spectral sequence, generic functoriality, ...). Trained on Mathlib's tagged proofs as the gold set.

**Acceptance criteria.**
- [ ] Training data: Mathlib tagged proofs (extract from Mathlib source).
- [ ] Model: small classifier (DistilBERT-class) fine-tuned on (theorem-chunk, label) pairs.
- [ ] New chunk field `proof_skeleton: enum`.
- [ ] `search_papers` `filters.proof_skeleton` filter.
- [ ] Trigger condition: tactician sub-agent has demonstrated need for "find me proofs that use induction on the dimension."

**Dependencies.** E10_S03, E04_S08.

**Complexity.** XL.

**Labels.** `area:embedder`, `area:retrieval`, `tier:6`, `kind:research`.

---

### E15_S05 — Multi-paper deduplication (Tier 6 candidate)

**Description.** Per `09-feature-priorities.md` Tier 6 — same paper cross-listed across categories, withdraw-and-resubmit cases, near-duplicate works on different arXiv IDs. Detect via chunk-level overlap and surface as a "see also" hint.

**Acceptance criteria.**
- [ ] Detection: pairwise chunk-similarity scan over papers with overlapping authors and recent dates.
- [ ] Output: a `near_duplicates` field on `papers` table records.
- [ ] Test on the seed corpus that any cross-listings are detected.

**Dependencies.** E12_S04.

**Complexity.** L.

**Labels.** `area:storage`, `tier:6`.

---

### E15_S06 — ColBERT-v2 late-interaction for theorem-level chunks (Tier 6 / v1.5 candidate)

**Description.** Per `05-storage-and-indexing.md` § ColBERT for long technical chunks and `09-feature-priorities.md` § Decision points — ColBERT-v2 late interaction beats single-vector dense on long technical chunks at ~10× storage cost. The schema reserved a column in E05_S01 (`embedding_colbert`). This issue fills it.

**Decision trigger.** Decide after Tier 4 based on retrieval-quality data showing where single-vector dense fails. Don't build until that data exists.

**Acceptance criteria.**
- [ ] Trigger condition met: documented evidence that single-vector retrieval is the bottleneck.
- [ ] ColBERT model loaded; embeddings generated for theorem-level chunks only.
- [ ] Storage budget recalculated; growth ≤10× theorem-chunk storage.
- [ ] Phase-2 retrieval optionally fans out to ColBERT MaxSim and includes its rank list in RRF.
- [ ] A/B comparison vs. single-vector reported.

**Dependencies.** E12_S07.

**Complexity.** XL.

**Labels.** `area:retrieval`, `area:embedder`, `tier:6`, `kind:research`.

---

### E15_S07 — API embedder for query-time encoding (decision-point candidate)

**Description.** Per `09-feature-priorities.md` § Decision points — self-hosted vs API embedder for queries. Decide after Tier 5 based on cost and latency. Self-hosted is the safe default; an API embedder (Voyage) might give marginally better paraphrase handling at known cost.

**Decision trigger.** Tier 5 complete + measured paraphrase failure on the eval harness exceeds an acceptable threshold.

**Acceptance criteria.**
- [ ] Trigger condition documented and met.
- [ ] Optional `ARXMCP_QUERY_EMBED_PROVIDER` env var with `local` (default) or `voyage` choices.
- [ ] When `voyage`, the API key is loaded; spend metric (E14_S12) tracks usage.
- [ ] A/B comparison vs. local embedder reported.
- [ ] Documented in `docs/embedder/query-time-provider.md`.

**Dependencies.** E12_S07, E14_S12.

**Complexity.** M.

**Labels.** `area:embedder`, `tier:6`.

---

### E15_S08 — Trained equation embeddings (v2 / deferred)

**Description.** Per `05-storage-and-indexing.md` § Equation embeddings (v2 feature) — train a small encoder on `(equation, surrounding_sentence)` pairs from our own corpus. Until trained, equations use the same prose embedder over `presentation_latex + context_sentence`. **Deferred:** trigger is measured retrieval failure on `find_equation` after Tier 4.

**Acceptance criteria.**
- [ ] Trigger condition met.
- [ ] Training data extracted from the v1 corpus.
- [ ] Model trained, evaluated, replaces the prose embedder for equations only.
- [ ] Retrieval-quality A/B reported.

**Dependencies.** E12_S04, E10_S05.

**Complexity.** XL.

**Labels.** `area:embedder`, `tier:6`, `kind:research`.

---

### E15_S09 — Lean 4 toolchain integration (Tier 7 / v2 deferred)

**Description.** Per `09-feature-priorities.md` Tier 7 (v2) — LeanDojo bindings to expose Lean's proof state to arXMCP. **DEFERRED.** This is the gateway feature for the autoformalizer integration; out of scope for v1 of arXMCP itself, but the v1 design choices were made with this in mind (deterministic chunk IDs, hierarchical retrieval, definitions table, expand_macro tool).

**Acceptance criteria.**
- [ ] LeanDojo Python client integrated as an optional dependency.
- [ ] `lean_kernel_query` tool — pass-through to Lean's tactic state. Implementation deferred.
- [ ] Documented as the v2 entry-point in `docs/v2/lean-integration.md`.

**Dependencies.** E12_S04 + dedicated v2 design.

**Complexity.** XL.

**Labels.** `area:graph`, `area:server`, `tier:7`, `kind:research`.

---

### E15_S10 — `mathlib_lookup` tool (Tier 7 / v2 deferred)

**Description.** Per `09-feature-priorities.md` Tier 7 — maps arXMCP theorem-name hits to Mathlib lemma names and statements where they exist. **DEFERRED.** Builds on E10_S03 (find_lemma_by_name) but requires a Mathlib import + name-disambiguation layer that's out of v1 scope.

**Acceptance criteria.**
- [ ] Mathlib snapshot ingested into a separate index (or table).
- [ ] `mathlib_lookup({name})` returns matching Mathlib `lemma`/`theorem` declarations.
- [ ] Cross-referenced from `find_lemma_by_name` results when a Mathlib match exists.

**Dependencies.** E10_S03 + Lean toolchain (E15_S09).

**Complexity.** L.

**Labels.** `area:graph`, `area:server`, `tier:7`, `kind:research`.

---

### E15_S11 — Subgoal-decomposition orchestrator agent (Tier 7 / v2 deferred)

**Description.** Per `09-feature-priorities.md` Tier 7 — a sub-agent that takes a Lean `sorry` and uses arXMCP retrieval to find candidate Mathlib lemmas and arXiv proofs of similar facts. **DEFERRED.** This is the DeepSeek-Prover-V2 pattern with arXMCP as the retrieval substrate.

**Acceptance criteria.**
- [ ] Orchestrator agent code lives in a separate repo or component (out of arXMCP server scope).
- [ ] Documented as the canonical v2 consumer; no work in arXMCP itself for this.
- [ ] When this agent exists, its design lives in `docs/v2/subgoal-orchestrator.md`.

**Dependencies.** E15_S09, E15_S10.

**Complexity.** XL.

**Labels.** `tier:7`, `kind:research`.

---

### E15_S12 — Lean kernel as the only critic (Tier 7 / v2 — explicitly NOT an LLM critic)

**Description.** Per `09-feature-priorities.md` Tier 7 AND § Things to explicitly NOT build in v1 — "An LLM 'critic' tool. Lean is the critic. An LLM critic is theater." This issue exists to make the design choice explicit and to reject any future PRs that try to add an LLM-critic tool.

**Acceptance criteria.**
- [ ] `docs/non-goals.md` includes this rule with rationale.
- [ ] PR template warns against adding a `critique`/`adversarial_check`/`llm_critic` tool.
- [ ] CI check / lint that fails the build if a tool with one of those names is registered.

**Dependencies.** none.

**Complexity.** S.

**Labels.** `area:server`, `tier:7`, `kind:infra`.

---

### E15_S13 — Promote `summary` to a standalone tool (decision-point candidate)

**Description.** Per `09-feature-priorities.md` § Decision points — Tier 4 calls a Haiku summarizer for `search_papers` (E08_S07). Promote to a standalone tool only if agents start needing summaries of arbitrary chunk sets.

**Decision trigger.** Documented agent demand: at least 3 distinct sub-agent use cases that need to summarize a custom set of `chunk_id`s.

**Acceptance criteria.**
- [ ] Trigger met.
- [ ] Tool `summarize({chunk_ids, prompt_template?})` shipped.
- [ ] Cached the same way as the inline summary cache (E08_S07).
- [ ] Documented in `docs/server/summarize-tool.md`.

**Dependencies.** E08_S07.

**Complexity.** S.

**Labels.** `area:server`, `area:cache`, `tier:6`.

---
