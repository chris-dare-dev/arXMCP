# MCP tool API

arXMCP exposes **eight** tools over MCP 2025-06-18 Streamable HTTP at
`/mcp/`. This chapter is the human-readable reference; the authoritative,
byte-stable contract is whatever `tools/list` returns at runtime (pinned by
`tests/test_server_tool_schema.py` for prompt-cache stability).

```sh
echo '{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}}' | arxmcp-shim
```

## Conventions

- **Transport.** Single-shot `application/json` JSON-RPC over loopback only.
  No SSE. The `arxmcp-shim` bridges Claude Code's stdio to this endpoint.
- **Result envelopes.** Every tool returns a structured envelope. Recurring
  fields: `retrieval_mode` (which code path served the request),
  `corpus_version` (the corpus the answer came from), and tool-specific
  status fields (`graph_status`, `metadata_status`, `lean_status`, …).
  Tools **degrade rather than 5xx** — a missing index or malformed input
  surfaces as a documented fallback mode, not an error.
- **Size caps.** Responses over 256 KB are returned as a `resource_link`
  with `body_truncated=true`; agents follow the link for the full payload.
- **Validation.** Every `paper_id` / `chunk_id` is regex-validated against
  the arXiv or `textbook:<slug>` form before any I/O
  ([`ingest/identifiers.py`](../ingest/identifiers.py)).
- **Notebook routing.** Most retrieval tools accept
  `filters={"notebook": "<slug>"}` to route a single call to a specific
  notebook's corpus — see the [usage guide](usage.md#serving-many-notebooks).

---

## `search_papers`

Search the corpus for chunks matching a natural-language query; returns the
top-k chunks ranked by relevance.

| Argument | Notes |
|---|---|
| `query` | Natural-language query string. |
| `level` | `theorem` (default, one row per chunk) · `section` (dedup by `(paper_id, section)`) · `paper` (one row per paper). |
| `filters` | `{"paper_id": [...]}` scope to ≤100 papers · `{"source_kind": "arxiv" \| "textbook"}` · `{"notebook": "<slug>"}` route to a notebook corpus. |

Each row carries a 150-char snippet (see
[`.claude/docs/snippet-contract.md`](../.claude/docs/snippet-contract.md)),
a `source_kind` tag, and `chunk_id`. Echoes `filters_applied` /
`filter_warnings`. v1 is **dense-only ANN over BGE-M3 statement
embeddings** (statement chunks only); the BM25 + RRF hybrid path is
roadmapped (E07). `retrieval_mode` and `excluded_kinds` document the active
mode.

`cache_match` appears **only** when the response came from the semantic
(Tier-2) cache, and says which query the rows actually answer:
`kind="exact_query_embedding"` (yours, served from cache) or
`kind="approximate_neighbor"` (a different query within `cosine` of yours —
the value is reported). Its absence means the rows were retrieved for your
query as asked. It is a provenance axis and is independent of `degraded`.

## `get_chunk`

Fetch the full body of one chunk by its content-addressable `chunk_id`
(obtain `chunk_id`s from `search_papers` first). Chunks over the 256 KB
inline cap return a `resource_link` with `body_truncated=true`.

## `find_equation`

Search for equations similar to supplied **LaTeX or MathML**.

- **MathML** input routes through Zhang–Shasha tree-edit-distance fused with
  dense cosine: `score = α·(1 − normalized_ted) + (1 − α)·cosine`, with `α`
  tunable via `ARXMCP_EQ_TED_WEIGHT` (default `0.5`).
- **LaTeX** input falls back to dense-only ANN over statement embeddings
  (`retrieval_mode='dense_only_stmt_fallback'`) — there is no query-time
  LaTeXML pool.
- Malformed MathML degrades to `malformed_mathml_fallback` rather than
  erroring. `retrieval_mode` always names the active path.

## `get_definitions`

Return the per-paper notation/definition table for a `paper_id`. With a
`term`, lookup is: exact `symbol` → exact `symbol_raw` (author's form) →
case-insensitive `symbol_raw` prefix. Without a `term`, returns the full
table sorted by `symbol`, paginated 100/page with an opaque `next_cursor`.
Sourced from preamble `\newcommand` / `\DeclareMathOperator` / `\def` (and
peers) extracted at ingest.

## `find_lemma_by_name`

Find theorems/lemmas/propositions by natural-language name via the SQLite
FTS5 theorem-names index: exact-normalized (`fts5_exact`) → trigram
substring (`fts5_trigram`) → Python trigram-Jaccard typo tolerance
(`fuzzy_jaccard`). Optional `paper_id` restricts to one paper. Each match
carries `dedup_key`, `display_name`, `paper_id`, `chunk_id`, `section_path`,
`confidence`. Falls back to an in-memory scan if the index is absent.

## `get_paper`

Return per-paper metadata. v1 synthesizes from the chunks table
(`paper_id`, `chunker_version`, `embedder_version`, `chunk_count`,
`section_count`). `authors` / `title` / `abstract` / `year` / `categories`
are `null` until a dedicated papers-metadata table lands (E11/E12);
`metadata_status` documents the mode.

## `cite_neighbors`

Traverse the Kùzu citation graph from a `chunk_id`.

| `direction` | Follows |
|---|---|
| `cites` | Outgoing citations (papers the source cites). |
| `cited_by` | Incoming citations (papers that cite the source). |
| `depends_on` | Intra-paper theorem-dependency chain + cross-paper citations. |

`depth` is 1 or 2 hops. Each neighbor carries `paper_id`, a representative
`chunk_id` (null when the paper is in the graph but not the chunked corpus),
`edge_kind`, `hop_distance`, `source`, `confidence`; results are deduped by
`paper_id` and ordered by `(hop_distance, paper_id)`. Returns
`graph_status='absent'` with empty `neighbors` when the graph is not
ingested.

## `lean_verify`

Verify a Lean 4 snippet against a managed local Lean kernel.

| Argument | Notes |
|---|---|
| `snippet` | The Lean 4 source to check. |
| `mode` | `full` — elaboration **and** full kernel verification · `syntax_only` — wraps in `#check(...)` (or `set_option maxHeartbeats 5000 in <decl>` for declarations) for a cheap pre-verify · `tactic_step` — advances an existing proof state one tactic. |
| `imports` | Prepended verbatim as `import X` lines. |
| `env` | Opaque environment continuation token from a prior call; reuses that environment instead of re-importing. |
| `proof_state` | Opaque proof-state token; required with `mode='tactic_step'`. |

Returns `status` (`elaborated_no_errors` / `error` / `sorry` / `incomplete` /
`timeout` / `unavailable` / `invalid-input`),
`compilation_success` (null in `syntax_only` and `tactic_step`), `messages`
(severity + source position), `proof_state` (first unresolved goal),
`goals_remaining`, `sorry_goals`, `axiom_audit`, `env`, `proof_state_id`,
`continuation_status`. **Gated by `ARXMCP_ENABLE_LEAN`** — when disabled returns
`lean_status='disabled'` instead of a 5xx. A 30 s elaboration timeout kills
and respawns the REPL before the next call.

`status` reports elaboration **and** proof closure only — never axiom soundness.
`elaborated_no_errors` (renamed from `ok` at `verification-contract-m1`) means Lean
raised no error-severity diagnostic and no `sorry` remains; a snippet declaring its
own `axiom` lands here. `axiom_audit` reports the transitive axiom closure
independently; `status` and `compilation_success` never speak to it.

---

## See also

- [Usage guide](usage.md) — task-oriented walkthroughs that call these tools.
- [Architecture](architecture.md) — what happens behind each tool.
- [`.claude/docs/proof-chain-workflow.md`](../.claude/docs/proof-chain-workflow.md)
  — the 2-round `cite_neighbors` + bulk `get_chunk` pattern.
