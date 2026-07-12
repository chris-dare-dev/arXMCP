---
milestone_id: "data-plane-governance-m3"
researcher_role: "explore"
injection_attempts: 0
---
# Research brief (explore) — data-plane-governance-m3

## Affected files / context

### 1. The "bare verified" gap — exact mechanics (THE motivating example)

`server/handlers/lean_verify.py:290-298` (`_normalize_response`):

```python
has_error = any(m["severity"] == "error" for m in messages)
has_sorry = bool(sorry_goals)

if has_error:
    status = "error"
elif has_sorry:
    status = "sorry"
else:
    status = "ok"
```

Confirmed exactly: **`status: "ok"` ⇔ (no error-severity messages) ∧ (no sorry goals).**
Nothing else is checked. The full precedence order actually returned to the wire
(`server/schemas/lean_verify_result.json:89`) is `unavailable > timeout > error > sorry >
ok`, so "ok" is the bottom of a 5-value ladder, not a boolean.

**Would a bare `axiom h : False` pass?** Yes. Declaring an axiom is not a Lean error and
produces no sorry goal, so it elaborates cleanly → `has_error=False`, `has_sorry=False` →
`status="ok"`, and (for `mode="full"`) `compilation_success=True` (lines 300-307). There is
**zero axiom-related code anywhere in `server/`** — confirmed by `grep -ri axiom server/`
returning no matches. `R3-verification-contract.md:12-14` independently verifies the same
conclusion in its own evidence pass ("a bare `axiom h : False` passes silently and poisons
everything after it") — two independent reads converge, which is worth citing verbatim as
corroboration in the policy doc.

**Is `syntax_only` actually syntax-only?** No — it always elaborates. Two branches in
`_build_command` (`lean_verify.py:367-396`):
- Non-declaration input (a term) → wrapped in `#check (...)` — Lean elaborates the term to
  infer its type (full elaboration), just without the kernel's post-elaboration
  decide-instances/reducibility pass.
- Declaration input (`theorem`/`def`/`lemma`/`example`) → **cannot** be `#check`-wrapped, so
  it instead runs under `set_option maxHeartbeats 5000 in <decl>` — this is the full
  declaration elaborator with a heartbeat budget, not a parse-only path. `R3:15-16` names
  this precisely: "reduces but does not remove kernel work." The one honest signal that
  already exists: `compilation_success` is forced to `null` (not `False`) when
  `mode=="syntax_only" and status=="ok"` (lines 300-307) — "even a clean elaboration leaves
  'verification success' undefined" (docstring, lines 300-303). This null is the seed the R3
  brief explicitly builds the renamed-status contract from (`R3:117-118`).

`R3-verification-contract.md` (already drafted, not yet a committed milestone) independently
re-derives both findings from the same source lines and proposes the fix: rename `"ok"` to
`"elaborated_no_errors"` and split into a 5-operation contract (`parse_source` /
`elaborate_signature` / `check_declaration` / `audit_axioms` / `strict_replay_proof`). The
trust-language policy does not need to invent this vocabulary — R3 already drafted it; the
policy's job is to state the *general* multi-axis rule R3's specific rename instantiates.

### 2. MCP-surface trust/status vocabulary — full census

Only 2 of the 8 tools have a frozen `server/schemas/*.json` result-schema doc
(`lean_verify_result.json`, `search_papers_result.json`); the other 6 tools' status-like
fields live only in handler code + `ToolMeta` description prose in `server/tools.py`, with
no schema file cross-checked by a byte-stability test. Full census, one row per field:

| Tool | Field | Values | `file:line` |
|---|---|---|---|
| `search_papers` | `retrieval_mode` | `"dense_only"` (v1; schema names future `hybrid_rrf`/`hybrid_rrf_reranked`) | `server/handlers/search.py:715`; `server/schemas/search_papers_result.json:80-83` |
| `search_papers` | `excluded_kinds` | `["proof"]` (constant at v1) | `server/handlers/search.py:711` |
| `search_papers` | `filter_warnings` | `list[str]`, free-text per ignored filter key | `server/handlers/search.py:679-693,712` |
| `search_papers` | `filters_applied` | `dict`, present iff a `SUPPORTED_FILTER_KEYS` key honored | `server/handlers/search.py:265-311,751` |
| `search_papers` | `degraded` / `degraded_reasons` | `bool` + `list[str]` (e.g. `"hosted_embedder_outage"`) | `server/handlers/search.py:700-719,762-793` |
| `get_chunk` | `found` | `bool` | `server/handlers/chunk.py:63,117` |
| `get_chunk` | `include_equations_applied` / `include_referenced_applied` | `bool`, always `False` at v1 | `server/handlers/chunk.py:64-65,118-119` |
| `get_chunk` | `truncated_for_license` | `bool`, present iff `True` | `server/handlers/chunk.py:94-98,127` |
| `get_chunk` | `unused_args` | `list[str]` (audit trail of ignored flags) | `server/handlers/chunk.py:120,168-173` |
| `find_equation` | `retrieval_mode` | `"ted_fused"` \| `"ted_fused_eq"` \| `"dense_only_stmt_fallback"` \| `"dense_only_fallback"` \| `"malformed_mathml_fallback"` | `server/handlers/equation.py:8,11,18-19,90-91,98,119-127,134-139,148-160,187` |
| `find_equation` | `cosine_score` / `ted_norm` / `score` | `float` (numeric confidence-like) | `server/handlers/equation.py:103-108` |
| `get_definitions` | `index_status` | `"absent"` \| `"ok"` | `server/handlers/definitions.py:128,150,172` |
| `find_lemma_by_name` | `retrieval_mode` | `"fts5_exact"` \| `"fts5_trigram"` \| `"fuzzy_jaccard"` \| `"empty_after_normalization"` \| `"in_memory_scan_fallback"` | `server/handlers/lemma.py:7-13,116-121,126-131,136-141,147-152,262-267` |
| `find_lemma_by_name` | `confidence` (per match) | `float` (store-derived, or hardcoded `1.0` in fallback) | `server/handlers/lemma.py:169,228`; `server/theorem_names_store.py:201` |
| `get_paper` | `metadata_status` | `"hydrated"` \| `"synthesized_from_chunks"` | `server/handlers/paper.py:17,30,136,161,181,186` |
| `get_paper` | `found` | `bool` | `server/handlers/paper.py:135,185` |
| `cite_neighbors` | `graph_status` | `"absent"` \| `"unavailable"` \| `"present"` | `server/handlers/citations.py:108,134,141,148` |
| `cite_neighbors` | `confidence` (per neighbor) | `float` | `server/graph_types.py:40,49`; `server/graph_queries.py:174-189,392-419` |
| `lean_verify` | `status` | `"ok"` \| `"error"` \| `"sorry"` \| `"timeout"` \| `"unavailable"` (precedence-ordered) | `server/handlers/lean_verify.py:290-298,310,328,341,540`; `server/schemas/lean_verify_result.json:88-92` |
| `lean_verify` | `compilation_success` | `bool` \| `null` (null only in `syntax_only` + clean) | `server/handlers/lean_verify.py:300-307,315`; schema `:8-11` |
| `lean_verify` | `lean_status` | `"available"` \| `"disabled"` \| `"timeout"` | `server/handlers/lean_verify.py:316,329,342`; schema `:21-25` |
| `lean_verify` | `mode` (echo) | `"full"` \| `"syntax_only"` | `server/handlers/lean_verify.py:317,428-439`; schema `:55-59` |
| *(all 8 tools)* | `corpus_version` | `int`, echoed by `envelope()` | `server/tools.py:478-501` |
| *(all list tools)* | `body_truncated` | `bool`, present iff cap fired | `server/tools.py:616-665` (`enforce_byte_cap`), `:682-759` (`cap_result_list`) |
| *(dispatch layer, NOT a tool payload field)* | `REQUEST_COUNTER{status}` | `"ok"` \| `"error"` — **RPC-dispatch status, a different namespace than any of the above.** A call that returns `lean_verify status="sorry"` still records `REQUEST_COUNTER{status="ok"}` (business-logic outcome ≠ transport outcome; correct today, but the word "status" is now overloaded 5+ ways across the surface) | `server/tools.py:783,835,859,863,868` |

The word **"status"** alone denotes at least 4 unrelated things today: `lean_verify.status`
(epistemic ladder), `get_definitions.index_status` / `cite_neighbors.graph_status`
(index/graph availability), `get_paper.metadata_status` (enrichment provenance), and
`REQUEST_COUNTER`'s dispatch-level `status` label. The policy should name this overload
explicitly, not just the single-enum-ban case.

### 3. Abstention outcomes already present — mapped to the 4 canonical buckets

Mapping existing "no full answer" signals onto `unknown / ambiguous / not-in-corpus /
unsupported-by-provider` surfaces real gaps, not just a systemization exercise:

| Existing signal | Best-fit bucket | Fit quality |
|---|---|---|
| `get_chunk.found=False` (well-formed id, absent) | not-in-corpus | clean |
| `get_paper.found=False` (unknown paper_id) | not-in-corpus | clean |
| `cite_neighbors.graph_status="absent"` (never ingested) | unsupported-by-provider *or* not-in-corpus | **ambiguous — policy must pick one** |
| `cite_neighbors.graph_status="unavailable"` (corrupt/half-ingested Kùzu DB) | none of the four | **operational failure masquerading as a data-status enum value; not epistemic at all** |
| `lean_verify.lean_status="disabled"` (operator turned it off) | unsupported-by-provider | clean |
| `lean_verify.status="timeout"` | unknown (arguably: "we don't know if it would have closed") | plausible but not obvious |
| `lean_verify.status="unavailable"` (REPL crashed) | unsupported-by-provider | clean |
| `get_definitions.index_status="absent"` | unsupported-by-provider | clean |
| `get_paper.metadata_status="synthesized_from_chunks"` | **fits none cleanly** — the paper IS in-corpus (chunks exist); only the metadata *enrichment* is missing | **named gap — needs its own bucket or an explicit stipulation** |
| `find_lemma_by_name.retrieval_mode="empty_after_normalization"` (degenerate input) | none of the four — this is "invalid/degenerate query," not a corpus-state fact | **named gap — possible missing 5th bucket, or explicitly out of scope** |
| `find_equation`/`find_lemma_by_name` `"*_fallback"` retrieval_mode tags (`dense_only_fallback`, `fuzzy_jaccard`, `in_memory_scan_fallback`, …) | **not abstention at all** — these still return real, ranked results via a lower-precision method | **the policy must decide whether quality-degraded-but-answered results are in scope of "abstention," since today's vocabulary conflates "no answer" with "weaker answer"** |

**A silent (undetectable) gap, not just a mapping-quality issue:** `get_definitions`
(`server/handlers/definitions.py:68-179`) never validates that `paper_id` exists in the
corpus at all — it just queries and returns whatever rows match. An unknown `paper_id` and a
real paper with zero macros/definitions both collapse to the identical response shape
(`{definitions: [], total: 0, index_status: "ok"}`). Unlike the other six tools, there is
currently **no signal to distinguish "not-in-corpus" from "in-corpus-but-empty"** for this
tool at all — worth flagging as a concrete pre-existing hole the abstention-outcome
requirement should close, not just re-describe.

### 4. The rigor.py lattice (stability-mflds, sibling repo) — alignment source material

`C:/Users/cedar/Documents/Personal Projects/Source Code/stability-mflds/bridgeland_stability/rigor.py`
(full file, 58 lines):

```python
class Rigor(IntEnum):          # rigor.py:15-21
    PROVEN = 3        # a cited theorem covers these hypotheses
    CONJECTURAL = 2   # holds modulo a named open conjecture (e.g. threefold BG)
    HEURISTIC = 1     # numerical/empirical (dense compute_walls; doubling cert)
    UNKNOWN = 0        # untagged / no claim

@dataclass(frozen=True)
class Certificate:             # rigor.py:24-31
    rigor: Rigor
    hypotheses: Tuple[str, ...] = ()
    citations: Tuple[str, ...] = ()
    note: str = ""

UNKNOWN_CERTIFICATE = Certificate(Rigor.UNKNOWN, (), (), "")   # rigor.py:35

def meet(*certs) -> Certificate:   # rigor.py:47-57
    # rigor = min(...) ("weakest link"); hypotheses/citations = order-preserving set-union
```

Provenance fields on every verdict: `rigor` (4-level total order), `hypotheses` (tuple of
strings), `citations` (tuple of strings), `note` (free text). `meet()` composes multiple
certificates by taking the minimum rigor and unioning hypotheses/citations — a weakest-link
combinator for chained verdicts.

**Independent-oracle / differential-testing machinery** (two distinct mechanisms, both
worth citing in the alignment doc):
1. `tests/oracle/dlp_reference.py` + `tests/oracle/corpus.py` (E12) — a from-scratch
   transcription of the *published theorem statements* (not derived from the package code),
   asserted to import nothing from `bridgeland_stability`
   (`test_oracle_integrity.py::test_reference_has_no_package_import`) and to use no float
   (`::test_reference_uses_no_float`). Differential-tested against a **frozen 14-row corpus**
   (`test_oracle_integrity.py::FROZEN_STATUS`); a pre-commit hook
   (`.githooks/pre-commit`) refuses any commit touching `tests/oracle/` without a same-commit
   `docs/CORRECTIONS.md` entry, so the corpus can only grow, never quietly relabel a verdict.
   Documented in full at `docs/CORRECTIONS.md:290-409` (§8, defect A4) — this is the case
   R4's brief cites: `Rigor.PROVEN` was returned on **false verdicts in both directions**
   before the oracle caught it (denominator-cutoff truncation bug, `docs/CORRECTIONS.md:357-360`).
2. `bridgeland_stability/oracle/` (`m2.py`) — a *separate*, optional Macaulay2 subprocess
   oracle (E10/G16), lazily imported (never pulled in by `import bridgeland_stability`),
   for sheaf-level bodies (`chi_via_ext`, `ext_dims`, `moduli_nonempty_by_construction`).

**Alignment guidance for the policy doc:** `rigor.py`'s lattice grades *the strength of an
answered verdict* (how proven is this claim); arXMCP's 4 abstention buckets grade *whether a
tool could answer at all*. These are complementary axes, not one ladder — forcing them into
a single merged enum would repeat the exact mistake trust-language policy exists to ban.
`R4-verified-computation.md:31-32` already treats them this way in practice: arXMCP's
planned receipt schema "the `Certificate` passed through verbatim" (opaque passthrough, no
re-derivation, no re-grading) — cite this as the precedent divergence-record entry rather
than inventing a fresh mapping.

### 5. CLAUDE.md §4.9 anchor

Confirmed: §4.8 (`## 4.8 Data-plane boundary — hard constraints (binding)`,
`CLAUDE.md:252`) is the last `§4.x` subsection — §5 (`## 5. Directory layout`) follows
immediately at line 288. No existing `§4.9` anywhere in the file. The ADR itself
(`.claude/docs/adr-data-plane-boundary.md:135-143`, "Decision 5 — CLAUDE.md anchor")
already named `§4.9` as the planned next anchor: *"Milestone m3's trust-language rules land
as §4.9 or extend §4.8."* `.claude/notes/milestones/data-plane-governance-m3/preflight-deviation.md:39`
additionally confirms `git status --porcelain -- CLAUDE.md` was clean at m3's init — no
concurrent session is mid-editing this section.

Last 3 lines of §4.8 (`CLAUDE.md:281-284`), for clean insertion:

```
Non-commercially-licensed external data enters only a candidate layer — never
redistributed, never promoted to served evidence without a recorded
per-source license check (ADR Decision 4; adapter mechanics are the
R7 track's).
```

§4.8's house style (`CLAUDE.md:252-256`): opens with a one-line binding statement ("arXMCP
is a read-only proof-discovery data plane."), immediately links its ADR under
`.claude/docs/` ("Constitution: [`adr-data-plane-boundary.md`](.claude/docs/adr-data-plane-boundary.md)
(data-plane-governance-m1, Accepted 2026-07-12)"), then states an explicit **scope**
sentence before the numbered rules ("Scope: the served process, the `server/` package, and
the shipped distribution."). §4.9 should mirror this: one-line statement, link to
`.claude/docs/trust-language-policy.md` + `.claude/docs/evidence-ledger-standard.md`, then
an explicit scope line (§4.8's scope was process/package; §4.9's natural scope is "the MCP
tool surface" plus a doc-authoring rule for future novelty claims — these are two different
kinds of scope and probably need two scope sentences, not one).

### 6. Novelty-claim census set (R0–R7) — for the evidence-ledger retro pass

Verified exhaustively: close-read of all 8 brief files (R0–R7) **plus** a directory-wide
keyword grep (`no (one|system|library|hosted|code|package)|nobody|not a single|first to|
empty niche|no.{0,15}(ships|serves|serving)`, case-insensitive) across
`.claude/roadmap-briefs/*.md`, cross-checked against each other. Result: **exactly 3**
genuine "no system does X" categorical-novelty claims exist across R0–R7. R0's own body,
R1, R2, R3, and R7 contain **zero** — R0 only *states the evidence-ledger rule*
(`R0:49`, itself the policy text, not a claim instance); the grep's other hits in
R4/R5/R6/R7 (e.g. `R4:57` "no code merge", `R5:76` "nothing serves without its axes",
`R6:87,92` scope-out clauses, `R7:103` "no serving" — a fallback-plan description) are
architectural/scope constraints, not market-novelty assertions, and were excluded.

| Brief | Line | Claim (verbatim, short) | Existing census quality |
|---|---|---|---|
| `R4-verified-computation.md` | 9 | "no one serves Bridgeland-domain computations — Euler pairings, certified wall enumeration, Bogomolov–Gieseker checks, Mukai-lattice classification — as an API" | **Partial** — backed by its own Evidence section (`:123-125`): dated 2026-07-11, names Schmidt `stability_conditions` (Sage, 2023), Naylor `tilt.rs`, QuiverTools; missing only an explicit "queries run" field |
| `R5-formal-target-registry.md` | 9-10 | "The census (2026-07-11, scoped: AXLE, formal-conjectures, SorryDB, Herald, TheoremGraph, LeanArchitect, Matlas) found no system serving new, typechecked formalizations of paper statements pinned to both a corpus revision and a formal environment as a queryable API" | **Partial** — already dated + scoped inline in the claim sentence itself; missing only "queries run" |
| `R6-proof-structure-and-bundles.md` | 15 | "no system tags informal papers by technique at scale" | **None** — no census set, no date, no queries; full retrofit needed |

`.claude/notes/milestones/data-plane-governance-m3/preflight-deviation.md:43-44` records
the implementer's *anticipated* diff surface as `.claude/roadmap-briefs/` edits scoped to
"R0/R3/R5 census + cross-ref edits" — this predates this research and **does not mention
R6**. Since this census finds R6 carries the least-evidenced of the three claims, the
acceptance criteria below flag this explicitly (see Risks #4).

### 7. Doc placement + test surfaces

Both new docs belong under `.claude/docs/` per CLAUDE.md §1/§4.6 — same precedent as
`adr-data-plane-boundary.md` from m1. **No test in `tests/` currently enforces this
placement rule** (verified: a targeted grep for doc-layout/root-markdown-glob enforcement
patterns across `tests/` returned nothing beyond irrelevant false positives in
`test_bm25.py`/`test_query_encoder.py`/`test_store.py`); §1/§4.6 compliance is
convention-only today, same posture m1 operated under.

A second, narrower grep (`trust-language|evidence-ledger|adr-data-plane|§4\.8|§4\.9|"4\.8"`)
across all of `tests/` returned **zero matches** — no test currently pins these doc paths,
the ADR path, or the §4.8/§4.9 section numbers. A broader generic grep for
`CLAUDE\.md|\.claude/docs` matched 24 files, but manual inspection of the two most
plausible candidates found nothing at risk:
- `tests/test_constitution_ui_claims.py` (full file read) — scans CLAUDE.md +
  `.claude/notes/*.md` + README.md, but only for specific phrase presence/absence (the
  stale "MCP tool surface is the UI" claim, the "Browser UI surface" heading) — content
  unrelated to §4.9, not a collision risk, but a directly reusable **pattern** if m3 wants
  its own doc-accuracy guard test later.
- `tests/test_langfuse_doc.py:178-207` — the `anthropic`-import guard test the ADR itself
  names as "the import half" of the §4.7/§4.8 SDK ban; unrelated to m3's doc content.

No test references `data-plane-governance` or `adr-data-plane-boundary` by name anywhere
in `tests/` yet — m3 is greenfield with respect to test-suite entanglement.

## Acceptance criteria the implementer must meet

1. `trust-language-policy.md` must state the exact `lean_verify` `status:"ok"` logic
   (`lean_verify.py:290-298`: no error-severity messages AND no sorry goals) as the
   canonical banned pattern, and must explicitly note that a bare `axiom h : False`
   currently passes silently (zero axiom-audit code exists in `server/` today) — this is
   the concrete case the ban must be legible against. [Roadmap AC1]
2. `trust-language-policy.md`'s multi-axis dimensions must be checked against the actual
   MCP-surface census (§2 table above) — not invented from scratch — and must name the
   "status" word-overload finding (4+ unrelated meanings across the surface today,
   including the RPC-dispatch-level `REQUEST_COUNTER{status}` which is a different
   namespace than any tool-payload field). [Roadmap AC1]
3. The rigor.py alignment mapping must cite `Rigor` (PROVEN>CONJECTURAL>HEURISTIC>UNKNOWN,
   `stability-mflds/bridgeland_stability/rigor.py:15-21`) and `Certificate`
   (rigor+hypotheses+citations+note, `rigor.py:24-31`, `meet()`=weakest-link at
   `rigor.py:47-57`), and must record the explicit divergence that rigor.py grades
   *answer strength* while arXMCP's abstention buckets grade *whether an answer exists at
   all* — complementary axes, not one ladder — per the opaque-passthrough precedent already
   set in `R4-verified-computation.md:31-32` ("the `Certificate` passed through verbatim").
   [Roadmap AC1]
4. The four abstention outcomes must be defined precisely enough to classify every existing
   "no full answer" signal in the §3 mapping table above, and must explicitly resolve (not
   silently skip) its three named gaps: (a) `get_paper.metadata_status=
   "synthesized_from_chunks"` fits none of the four cleanly (paper IS in-corpus; only
   enrichment is missing); (b) degenerate-input signals (`empty_after_normalization`) and
   quality-degraded-but-answered `"*_fallback"` retrieval_mode tags are not refusals at all
   and the policy must state whether they are in scope of "abstention"; (c) `get_definitions`
   cannot today distinguish not-in-corpus from in-corpus-but-empty at all (silent collapse,
   `definitions.py:68-179`) — the policy should require this be closed, not merely describe
   it. [Roadmap AC1]
5. `evidence-ledger-standard.md`'s retro census pass must cover exactly the 3 substantiated
   claims found in §6 (`R4-verified-computation.md:9`, `R5-formal-target-registry.md:9-10`,
   `R6-proof-structure-and-bundles.md:15`) — confirmed exhaustive via both close-read and a
   full-directory keyword grep across all 8 brief files — noting R4/R5 already carry a dated
   + named census set inline and need only "queries run" added, while R6 needs a full
   retrofit (no existing census set/date/queries). [Roadmap AC2]
6. CLAUDE.md's amendment must land as a new `### 4.9` subsection immediately after §4.8
   (confirmed last §4.x subsection, no existing §4.9, ADR Decision 5 already names this
   anchor), mirroring §4.8's house style: one-line binding statement, link to both new
   `.claude/docs/` files, and an explicit scope sentence (§4.8 scoped to
   process/package — §4.9's scope is the MCP tool surface plus a doc-authoring rule for
   future novelty claims; state both). [Roadmap AC3]
7. `R3-verification-contract.md` and `R5-formal-target-registry.md` must each gain an
   explicit cross-reference to `.claude/docs/trust-language-policy.md` at their existing
   tool-surface-gate language — R3's natural anchor is its Key Result 1 (`R3:54-55`, the
   `status:"ok"` → `elaborated_no_errors` rename) and R5's is its "no bare 'verified' label"
   line (`R5:43`) plus its multi-axis-trust-record key result (`R5:65-66`) — both currently
   state the trust-language *intent* in their own words without citing the m3 policy by
   path, since m3 did not exist when R0–R7 were authored (2026-07-11). [Roadmap AC3]

## Risks and open questions

1. **Doc-placement is convention-only, not test-enforced.** No test in `tests/` asserts the
   §1/§4.6 "`.claude/docs/` only" rule; the two new docs landing correctly depends on the
   researcher/implementer following convention, exactly as m1's ADR did — there is no CI
   safety net here.
2. **The four abstention buckets don't obviously cover operational/resource failures or
   degenerate input.** `lean_verify`'s `timeout`/`unavailable`, `cite_neighbors`'
   `graph_status="unavailable"` (corrupt DB), and `find_lemma_by_name`'s
   `empty_after_normalization` are service/input-validity signals, not epistemic
   "abstained on this claim" signals. If m3 doesn't scope the four buckets explicitly
   (epistemic-only vs. also-covers-availability), R3's five-operation redesign — which needs
   to classify axiom-audit failures and isolation-violation kills — will hit the identical
   gap immediately downstream.
3. **Forcing a tight rigor.py "alignment mapping" risks false precision.** stability-mflds'
   CLAUDE.md documents the `Rigor` lattice as grading *its own* verdicts (wall enumeration,
   BG checks) — not arXMCP's retrieval/abstention surface. R4's brief already treats the two
   as adjacent-but-distinct (opaque `Certificate` passthrough, never re-derived). The policy
   doc should follow that precedent rather than inventing a merged lattice that overstates
   how related the two systems' trust concepts really are.
4. **`preflight-deviation.md` (written before this research ran) anticipates a narrower
   roadmap-briefs diff than the census actually supports.** It names "R0/R3/R5 census +
   cross-ref edits" as the m3 diff surface (`preflight-deviation.md:43-44`) but does not
   mention R6 — yet this research's exhaustive §6 census finds R6 carries the
   *least*-evidenced of the three retrofit-needing claims (no existing census set/date at
   all, unlike R4/R5's partial dating). If the implementer follows the preflight note's
   anticipated scope literally rather than this brief's census, R6 will be missed.
5. **Only 2 of 8 tools have a frozen schema doc.** `lean_verify` and `search_papers` have
   `server/schemas/*.json` files cross-checked by a byte-stability test; the other 6 tools'
   status-like fields (`metadata_status`, `index_status`, `graph_status`, `retrieval_mode`
   enums, `confidence`) live only in handler code + `ToolMeta` prose. A "ban" the policy
   states can only be enforced as a doc-review discipline for 6 of 8 tools today, not a
   schema-level gate — the policy should say this rather than imply uniform enforcement
   exists.
