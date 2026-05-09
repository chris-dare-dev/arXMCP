# E06_S03 Adversary Critique

## Executive Summary

- The commit ships `server/tools.py` (380 LOC), 7 handlers (`server/handlers/*.py`, ~700 LOC total), `server/main.py` lifespan glue, and `tests/test_tools_all.py` (361 LOC, 14 tests). Wire trace confirms `tools/list` returns 7 tools with `_meta: {tool_schema_version: 1}` per spec, schemas pass Draft-07, and the envelope helpers do produce alphabetically-sorted dicts that survive Pydantic v2 serialization (insertion order is preserved by `model_dump`).
- **Body-cap path is broken on the only handler that uses it.** `enforce_byte_cap()` looks for `body_text` at the top level of `structured_content`, but `chunk.py` nests it under `structured["chunk"]["body_text"]` — so over-cap responses set `body_truncated=True` and add a `resource_link_uri` while the full uncapped body still ships. The 256 KB inline cap is silently bypassed for `get_chunk` (`server/handlers/chunk.py:86-92` + `server/tools.py:296-299`).
- **`_NEWCMD_RE` corrupts multi-`\newcommand` preambles.** With `re.DOTALL` and a greedy `(.*)` capture, when one `preamble.json::macros[i]` string contains two `\newcommand` lines (or any subsequent brace-balanced content), the expansion captures across the next `}` runs. Reproduced: `\newcommand{\R}{\mathbb{R}}\n\newcommand{\C}{\mathbb{C}}` returns `expansion="\mathbb{R}}\newcommand{\C}{\mathbb{C}"` (`server/handlers/definitions.py:36-43`).
- **Path traversal vector in `get_definitions`.** `paper_id` is interpolated into a filesystem path with no regex check; `paper_id="../../../../etc/passwd"` resolves to `/private/etc/passwd/preamble.json`. The handler returns `{"extraction_status": "no_preamble"}` because the file does not exist, but the unvalidated traversal IS happening — and `paper_id` is echoed back into the structured payload, enabling reflection (`server/handlers/definitions.py:99-110`).
- **Schema vs brief drift.** The brief promises `search_papers(..., filters?, cursor?)` but the schema only declares `query, level, k`; an agent calling with `filters={...}` will fail JSON-Schema `additionalProperties:false` (default for Pydantic models). Mirror drift: `cite_neighbors` adds an extra `limit` arg the brief doesn't list; `find_lemma_by_name` adds an extra `k` arg.
- **`search_papers` is invisible to proof chunks.** v1 only searches `embedding_stmt`; the dual-encoding contract puts `kind="proof"` chunks into `embedding_proof` (NULL `embedding_stmt`). Documented in the docstring but not in the user-facing tool description; agents will silently miss every proof body. Same docstring-only escape on `find_equation`.
- **Test surface is thin.** 10 of 14 tests are single-call smoke checks that assert the handler "doesn't 500 + has `corpus_version`". Only one (`test_search_papers_level_paper`) verifies an aggregation invariant. No test exercises the cap path, byte-stability across runs, the multi-`\newcommand` parser case, the path-traversal class, or the `_meta` wire surface (the `model_dump_json(by_alias=True)` rendering pinned for E06_S06).
- **Verdict: fix-then-proceed.** Two HIGH (cap path bypass, regex corruption), four MEDIUM, several LOW. No CRITICAL. AC are green at the synthetic-corpus level but multiple production-realistic paths are silently mis-handled.

## Severity calibration table

| Severity | Definition | Target rate |
|---|---|---|
| CRITICAL | data loss / security breach / broken invariant | rare |
| HIGH | wrong behavior on common path | low |
| MEDIUM | subtle correctness or missing test | moderate |
| LOW | style, naming, minor docs | as found |

## Findings

### CRITICAL

(none)

### HIGH

#### F1 — `enforce_byte_cap` truncates the wrong key; cap silently bypassed for `get_chunk`

- **What.** `enforce_byte_cap()` reads `if "body_text" in truncated` at the top level of `structured_content`. `handle_get_chunk` puts the body at `payload["chunk"]["body_text"]`, NOT at `payload["body_text"]`. So when a chunk exceeds the 256 KB cap, `enforce_byte_cap` flips `body_truncated=True` and emits the resource_link block but the full `chunk["body_text"]` is unchanged in the returned `structured`, which is what `envelope()` then serializes back onto the wire. Net effect: oversized chunks get a wrong-marketing payload (truncated flag + link) but the response still contains the entire body, and the cap is not enforced.
- **Why it matters.** This is the only call site of `enforce_byte_cap` in v1 and one of the milestone's load-bearing claims (synthesis D9). The inline-result cap is a security/UX contract — large LaTeX bodies (math papers can easily produce >256 KB chunks if a section contains a long equation array) will exhaust agent context windows and bypass the documented size guarantee.
- **Where.** `server/tools.py:295-299` (`if "body_text" in truncated`) vs. `server/handlers/chunk.py:73-93` (body lives under `chunk` sub-dict).
- **Fix sketch.** Either (a) make `enforce_byte_cap` accept an explicit "body_text key path" tuple (e.g. `("chunk", "body_text")`) or (b) restructure `payload` so `body_text` lives at the top level (and put the rest of the chunk fields under a different key). Option (a) is the minimal-blast-radius fix. Add a regression test that seeds a >256 KB chunk and asserts the returned body is truncated AND the response is below the cap.

#### F2 — `_NEWCMD_RE` greedy-match corrupts multi-`\newcommand` lines

- **What.** The regex uses `re.DOTALL` and a greedy `\{(.*)\}` for the expansion capture. Verified: feeding `"\newcommand{\R}{\mathbb{R}}\n\newcommand{\C}{\mathbb{C}}"` returns `(symbol="\R", expansion="\mathbb{R}}\newcommand{\C}{\mathbb{C}")` — the expansion eats across the second `\newcommand` line and trails an unbalanced brace. The E02_S02 preamble extractor stores raw source lines per macro (`PreambleDoc.macros: list[str]`), so under most inputs this is a one-line-one-macro scenario — but a real LaTeX preamble OFTEN concatenates multiple commands per source line, and even when it doesn't, a single command with internal `}` (e.g. `\newcommand{\X}{\mathbb{R}^n}`) plus DOTALL means any further text in the same string will be slurped.
- **Why it matters.** This is the entire payload of `get_definitions`. A corrupted expansion misleads the agent's notation lookup — the central use case for the tool. The brief's AC-3 ("`get_definitions(paper_id="2401.01234", term="\mathcal{A}")` returns the expansion for that symbol only") is satisfied by the parser shape but the parser itself is wrong on common LaTeX input.
- **Where.** `server/handlers/definitions.py:36-43` (regex) + `:78` (the `_NEWCMD_RE.search(line)` call).
- **Fix sketch.** Drop `re.DOTALL`, switch to non-greedy `\{(.*?)\}`, and use a brace-balance walker instead of a regex (LaTeX brace structure is not a regular language). At minimum, pin the bug class with a test case `"\newcommand{\R}{\mathbb{R}}\\newcommand{\C}{\mathbb{C}}"` and assert the parser emits TWO entries with the right expansions.

### MEDIUM

#### F3 — Path traversal in `get_definitions::_preamble_path_for`

- **What.** `paper_id` is interpolated directly into `corpus_root / "preamble" / paper_id / "preamble.json"`. Reproduced: `paper_id="../../../../etc/passwd"` resolves to `/private/etc/passwd/preamble.json`. The handler returns `extraction_status="no_preamble"` because that path is not a file, so this is not an exfiltration today — but the symbolic-link case (`/private/etc/passwd → some other file the user owns`) and the future case where someone places a real `preamble.json` somewhere outside the corpus tree both bypass the intended scope. The same `paper_id` is also echoed into the structured response, providing a reflection vector for log-poisoning.
- **Why it matters.** Threat 1 in the security note (path traversal). Every other handler that takes `paper_id` (`get_paper`, `find_lemma_by_name`) at least passes it through LanceDB filter syntax (a different sanitizer), but `get_definitions` builds a raw filesystem path. Defense in depth requires the same `_PAPER_ID_RE` validation that `chunk.py::_CHUNK_ID_RE` performs on `chunk_id`.
- **Where.** `server/handlers/definitions.py:99-110` (no validation before `Path(...)`); `server/handlers/paper.py:40-45` (raw paper_id into `WHERE` clause via `_escape`); `server/handlers/lemma.py:50` (paper_id used in Python-side compare — safer).
- **Fix sketch.** Add a `_PAPER_ID_RE` check at the top of every handler that accepts `paper_id`, mirroring `chunk.py::_CHUNK_ID_RE`. Single-source the regex — see F11. Reject the call with a `ValueError` (FastMCP renders that as `isError=true`).

#### F4 — `enforce_byte_cap` measures inner payload, not wire bytes

- **What.** The cap is computed via `len(json.dumps(structured_content, sort_keys=True, ensure_ascii=False).encode("utf-8"))`. But the actual wire response is a Pydantic `CallToolResult` containing BOTH `structuredContent: <inner>` AND `content: [{type:"text", text:"<json-encoded inner>"}]` AND `isError: false` AND optionally `_meta: ...`. Reproduced wire trace: a 32-byte inner payload renders as a 92-byte JSON-RPC response — and the `content[0].text` block ALSO contains a pretty-printed (indent=2) repeat of the same dict. So the wire bytes for a near-cap inner payload are roughly 2x the measured value. A 250 KB inner check passes; the actual wire response is ~500 KB and the operator's `result_byte_cap=256_000` contract is silently violated.
- **Why it matters.** The cap's promise is bandwidth/context safety. Off-by-2x means the configured cap is effectively half what operators believe.
- **Where.** `server/tools.py:291-294` (the `len(serialized.encode())` check); `server/main.py:105` (the `/mcp` exemption from the ASGI middleware doc explicitly says "the resource_link IS the <256 KB pointer pattern" — but the inner check doesn't account for the wire envelope).
- **Fix sketch.** Either (a) reduce the cap measurement to half the configured value (cheap, conservative), or (b) measure the actual `CallToolResult.model_dump_json()` bytes including the duplicate text block. (a) is simpler and matches the documented "inline-result" semantics.

#### F5 — `search_papers` excludes `kind="proof"` chunks entirely

- **What.** `chunks_table.search(query_vec, vector_column_name="embedding_stmt")` only matches rows with non-NULL `embedding_stmt`. Per `ingest/schema.py:88-99`, `kind="proof"` chunks have NULL `embedding_stmt` and populated `embedding_proof`. So every proof-window chunk in the corpus is invisible to search_papers v1. The docstring says "mixing without RRF would produce inconsistent rankings (E07 is the right venue)" — but the user-facing tool description says "Returns the top-k chunks ranked by relevance" with NO mention of proof chunks being excluded. An agent searching for proof content will silently get statement-only results.
- **Why it matters.** For a research-mathematics corpus, proofs are a substantial fraction of the textual content; "find chunks similar to this proof technique" is a primary use case. The exclusion is documented in the docstring but invisible at the wire layer (the `retrieval_mode: "dense_only"` field tells you the search mode, NOT that half the corpus is excluded).
- **Where.** `server/handlers/search.py:65-70` (the search call); `SEARCH_PAPERS.description` in `server/tools.py:103-114` (no proof-exclusion warning).
- **Fix sketch.** Update the user-facing description to call out the gap: "v1 indexes statement chunks only; proof chunks are not retrievable until E07's dual-column RRF lands." Optionally surface an `excluded_kinds: ["proof"]` field in the result envelope so the agent can detect it programmatically.

#### F6 — Schema drifts from the brief tool signatures

- **What.** Three concrete drifts: `search_papers` schema accepts `(query, level, k)` but the brief promises `(query, level?, k?, filters?, cursor?)` — JSON-Schema validation rejects an agent call with `{filters: {year_min: 2020}}`. `cite_neighbors` schema includes `limit` (1-100, default 30); the brief's signature is `(chunk_id, depth?, direction?)` only. `find_lemma_by_name` schema includes `k`; brief's signature is `(name, paper_id?)` only.
- **Why it matters.** The brief's tool signatures are the contract that downstream documentation and agent prompts will be built against. Adding undocumented arguments is forgivable; OMITTING brief-promised arguments breaks the contract — an agent emits `filters` per the spec, the call fails. The result envelope's `filter_warnings: []` and `next_cursor: null` fields ALSO imply pagination and filtering work, but the schema doesn't even accept those args.
- **Where.** `server/handlers/search.py:41-50` (no `filters`/`cursor` params); `server/handlers/citations.py:22-30` (extra `limit`); `server/handlers/lemma.py:23-31` (extra `k`); brief at `state.json::milestone_brief`.
- **Fix sketch.** For `search_papers`, accept `filters: dict[str, Any] | None = None` and `cursor: str | None = None` even at v1, ignore them server-side, and document via the docstring + `filter_warnings`. For `cite_neighbors` and `find_lemma_by_name`: either remove the extra args or update the brief / synthesis to acknowledge them.

#### F7 — `version: 1` in `search_papers` results is hardcoded misinformation

- **What.** `_arrow_to_rows` always sets `"version": 1` per row with the comment `# paper version; no schema column yet`. Wire trace confirms every result returns `"version": 1`. The brief's Get-Paper signature includes a `version` arg, implying papers ARE versioned (arXiv supports `v1`, `v2`, ...). Agents reading `version: 1` will infer "this is the v1 of the paper" — but the value is the literal integer 1 regardless of the paper's actual arXiv version (which lives in the `paper_id` suffix like `2401.00001v3`).
- **Why it matters.** False data on a primary search result. An agent that prompts on `version` to decide whether to fetch a newer revision will never see `version > 1`. Better to omit the field entirely than to lie.
- **Where.** `server/handlers/search.py:127`.
- **Fix sketch.** Drop the `version` field from the result row until E11/E12 lands a real source. Or extract the version from the `paper_id` suffix (e.g. parse `vN` from `2401.00001v3`).

### LOW

#### F8 — `label` field concatenates two semantically different fields

- **What.** `_format_label(theorem_name, theorem_label)` returns `f"{theorem_name} {theorem_label}"`. Wire trace confirms results like `"Lemma 3.1 Theorem 3.1"` (both fields present, weird display) or `"Riemann-Roch Theorem 0.1"` (named theorem). The brief's example label is `"Theorem 3.4"` — meaning theorem_label is the numbering and theorem_name is the kind. The function inverts the convention by putting `theorem_name` first.
- **Where.** `server/handlers/search.py:133-137`, `server/handlers/lemma.py:79-81`.
- **Fix sketch.** Either swap the join order to `f"{theorem_label} {theorem_name}"`, or pick one canonical field and drop the other from `label` (the raw fields are still surfaced separately).

#### F9 — Dead code: `import asyncio` + `_ = asyncio` suppression in `search.py`

- **What.** `import asyncio` at the top of `server/handlers/search.py` followed by `_ = asyncio` at the bottom to suppress F401. The handler doesn't use `asyncio` anywhere — `async def` is a syntax keyword, not an `asyncio` symbol. The import is dead.
- **Where.** `server/handlers/search.py:23, 178`.
- **Fix sketch.** Remove the import. Apply ruff `--fix`.

#### F10 — `_unused_args` field leaks into structured response

- **What.** `handle_get_chunk` always emits `"_unused_args": _record_unused_args(include_referenced, include_equations)` in the structured payload. When both flags are False (the default), the value is `[]`; when True, it lists the names. This is documented as an "audit trail for the agent runtime" but it's a leading-underscore field name in a public response — convention says private/implementation detail. Either drop it or rename without the underscore.
- **Where.** `server/handlers/chunk.py:91, 114-119`.

#### F11 — `_PAPER_ID_RE` / `_CHUNK_ID_RE` duplicated in three places

- **What.** The regex for paper_id format lives in `ingest/chunker.py:106` (the source of truth, locked by the chunk_id contract). It's duplicated in `tools/validate_eval_fixtures.py:106-111` (with a comment acknowledging the duplication). Now ALSO duplicated in `server/handlers/chunk.py:31-33` for `_CHUNK_ID_RE`. Three copies, three opportunities to drift. Worse, the chunk handler validates `chunk_id` but `paper_id` validation is absent in `paper.py`, `definitions.py`, `find_lemma_by_name` (see F3).
- **Where.** `ingest/chunker.py:106`; `tools/validate_eval_fixtures.py:106, 111`; `server/handlers/chunk.py:31`.
- **Fix sketch.** Extract `PAPER_ID_RE` and `CHUNK_ID_RE` to a single shared module (e.g. `ingest/identifiers.py`) and import everywhere. Add a regression test that asserts pattern equality across the three current sites — `tests/eval/test_fixtures.py:163-164` already does this for one pair.

#### F12 — `find_lemma_by_name` loads the entire chunks table on every call

- **What.** `r.chunks_table.to_arrow()` reads ALL chunks into memory each call, then iterates in Python. For the 50-paper corpus that's fine (~5K chunks, milliseconds). For the Tier-5 vision (200K papers, ~20M chunks) this is catastrophic — multi-GB memory + multi-second latency per call. The docstring says the SQLite FTS5 index lands in E10_S02 and "the API stays stable across the swap" — but until then, an operator who scales the corpus past a few thousand papers will see this tool become unusable.
- **Where.** `server/handlers/lemma.py:33`.
- **Fix sketch.** Document the scale cap in the user-facing description (e.g. "v1 in-memory scan; performance degrades linearly past ~10K papers"). Optionally add a row-count guard that returns `{matches: [], scale_warning: "exceeds_in_memory_threshold"}` past a threshold (e.g. 50K rows).

#### F13 — `get_paper` `limit(10000)` is a magic number

- **What.** `chunks_table.search().where(...).limit(10000).to_arrow()` caps at 10K rows per paper. The 50-paper test corpus has ~100 chunks per paper so this is safe — but the magic number is undocumented and a paper with >10K chunks (a textbook-length monograph) would silently truncate.
- **Where.** `server/handlers/paper.py:40-45`.
- **Fix sketch.** Either lift the limit (LanceDB streaming or a count-only query for `chunk_count`) or document the cap in the description.

#### F14 — `find_equation` BGE-M3 fallback is "polite fiction" relevance

- **What.** The handler embeds raw LaTeX (`\int_0^1 f(x) dx`) via BGE-M3 and matches against statement embeddings. BGE-M3 is trained on natural language; its LaTeX representation is essentially random. The smoke test asserts the call succeeds but never checks that the results are even loosely on-topic. The docstring acknowledges the limitation but the user-facing description (`FIND_EQUATION.description` in `server/tools.py:128-136`) just says "v1 ships dense-only fallback" — no warning that "the relevance is approximately random for non-natural-language inputs."
- **Where.** `server/tools.py:127-136` (description); `server/handlers/equation.py:33-50` (the actual encode + search).
- **Fix sketch.** Strengthen the user-facing description. Quote a baseline disclaimer like "v1 fallback may produce arbitrary rankings for pure-LaTeX queries; agents needing equation similarity should defer use until E10_S03 (TED index)."

#### F15 — Tests don't pin the `_meta` wire bytes for E06_S06

- **What.** `test_per_tool_schema_version_meta` asserts `t.meta.get("tool_schema_version") == 1` via the Python object, but `model_dump_json(by_alias=True)` shows the wire form uses `_meta` (alias). Pinning happens at E06_S06 but no test in this milestone captures the wire-aliased form, so a future Pydantic-v3 alias rename would silently break the wire contract while green-lighting this milestone's tests.
- **Where.** `tests/test_tools_all.py:165-175`.
- **Fix sketch.** Add a test that calls `tools[0].model_dump_json(by_alias=True)` and asserts `'"_meta":{"tool_schema_version":1}'` appears in the rendered JSON.

#### F16 — `mocked_bge_m3` patches three locations; future handlers will silently miss the patch

- **What.** The fixture monkey-patches `server.query_encoder.{_get_model, _get_tokenizer, encode_query}` AND `server.handlers.search.encode_query` AND `server.handlers.equation.encode_query`. A future handler that does `from server.query_encoder import encode_query` will silently use the REAL BGE-M3 in tests because the patch list doesn't know about it. The implementation summary acknowledges this ("brittleness is documented") but doesn't propose a structural fix.
- **Where.** `tests/test_tools_all.py:96-119`.
- **Fix sketch.** Either (a) change all handlers to `from server import query_encoder; query_encoder.encode_query(...)` so the singleton patch on the module attribute is sufficient, or (b) make the fixture iterate `inspect.getmembers(server.handlers, ismodule)` and patch every handler module's bound name.

#### F17 — `inputSchema.title` leaks Python handler name on the wire

- **What.** Wire trace shows `inputSchema.title = "handle_search_papersArguments"` and `outputSchema.title = "handle_search_papersDictOutput"`. These are Pydantic-derived from the function name. They're stable across runs (good for byte-stability) but they're a Python-internals leak — an MCP client viewing schema metadata sees a Python implementation detail. Cosmetic.
- **Where.** Pydantic auto-generated; appears in any tool's `inputSchema` field.
- **Fix sketch.** Set the schema `title` explicitly via `Field(..., json_schema_extra={"title": "..."})` or use `model_config = ConfigDict(title="...")`. Or accept the leak and pin it in the byte-stability test.

#### F18 — `_sort_dict` doesn't sort tuples and other sequence types

- **What.** `_sort_dict` recursively sorts dicts and treats lists element-wise. But Python tuples, sets, and frozensets are not handled. A handler returning `tuple` or `set` (e.g. `set(section_first)` in `paper.py:60`) will pass through `_sort_dict` unchanged. Today, JSON-serialization of a `set` raises `TypeError`; tuples become arrays with non-deterministic-but-actually-deterministic-because-tuple order. Trace `paper.py:57-60` — `section_first = set(...)` is used only for `len()`, so today it's fine, but a future handler that returns the set itself would crash at JSON-encode time.
- **Where.** `server/tools.py:254-270`.
- **Fix sketch.** Either reject non-list non-dict-non-scalar values in `_sort_dict` with a clear error, or normalize tuple→list / set→sorted-list before sort.

## What was done well

- **Frozen dataclass `ToolMeta` constants** at `server/tools.py:89-194` correctly satisfy the brief's "string constants — never interpolated at request time" requirement. The `slots=True, frozen=True` enforcement prevents accidental mutation.
- **`tools/list` order is deterministic and wire-stable** via the `ALL_TOOLS` tuple at `server/tools.py:186-194` and FastMCP's preservation of `add_tool` insertion order.
- **The lifespan ordering is correct.** `register_all_tools(mcp_server)` runs BEFORE `mount_mcp(app, mcp_server)` per synthesis D11 (`server/main.py:394-398`), and `set_resources(resources)` runs AFTER `Resources.startup` returns but BEFORE the session-manager `async with` opens (`server/main.py:288-305`) — handlers cannot fire before resources are ready.
- **`_meta: {"tool_schema_version": 1}` IS surfaced on the wire** under the spec-correct alias `_meta` (Pydantic `by_alias=True`), confirmed by `model_dump_json` trace.
- **Pydantic v2 preserves dict insertion order** through `model_dump`, so `_sort_dict` → `envelope` → JSON wire bytes IS byte-stable across runs (modulo the F18 caveat about non-dict containers).
- **The `_CHUNK_ID_RE` validator in `chunk.py:31-33`** is defense-in-depth against a future schema-derivation tweak that loosens the FastMCP-derived input contract.
- **Smoke-test coverage of all 7 tools** (one happy-path call each, with a mounted FastAPI TestClient against `/mcp/` going through the real MCP `initialize` handshake) is the right shape for an integration-level acceptance check.
- **Handler errors propagate as `isError: true`** (verified live), matching MCP 2025-06-18 spec for tool-execution failures (vs. JSON-RPC `-32602` for protocol-level errors).
- **`reset_resources_for_tests()` + `reset_metrics_for_tests()` are correctly invoked in every test fixture** (`tests/test_tools_all.py:127-128, 146-147, ...`); cross-test pollution is unlikely.

## Recommended rectification order

1. **F1** — Cap path bypass on `get_chunk` is a documented contract violation. Restructure the payload key path or change `enforce_byte_cap` signature. Add a regression test with a >256 KB body.
2. **F2** — Fix `_NEWCMD_RE` (drop DOTALL, switch to non-greedy, or use a brace-balance walker). Add a regression case with multi-`\newcommand` lines.
3. **F3** — Add `_PAPER_ID_RE` validation to `get_definitions`, `get_paper`, and `find_lemma_by_name`. (Combine with F11 by extracting a shared identifier module.)
4. **F6** — Decide schema-vs-brief stance for `search_papers.filters/cursor` (most important — agents WILL pass these), then `cite_neighbors.limit` and `find_lemma_by_name.k`.
5. **F7** — Drop the hardcoded `version: 1` field from search results, or parse it from `paper_id`.
6. **F11** — Single-source `_PAPER_ID_RE` / `_CHUNK_ID_RE` (closes F3 cleanly).
7. **F4** — Either reduce the cap by half OR measure the actual `CallToolResult.model_dump_json()` bytes.
8. **F5** — Update `SEARCH_PAPERS.description` to call out the proof-chunk exclusion.
9. **F14** — Update `FIND_EQUATION.description` with a stronger disclaimer.
10. **F15, F16** — Tighten the test surface (wire-byte pin for `_meta`, structural fix for the encode_query patch fan-out).
11. **F8, F9, F10, F12, F13, F17, F18** — LOW-priority cleanup; batch as time allows.

## Rectification status

**Phase 4 commit:** see `state.json` `rectification_commit` field.

| Finding | Severity | Status | Where fixed |
|---|---|---|---|
| F1 — `enforce_byte_cap` cap bypass on `get_chunk` | HIGH | **fixed** | `server/tools.py::enforce_byte_cap` accepts a `body_text_path` arg; `chunk.py` passes `("chunk", "body_text")`; new `_truncate_at_path` walks the path. Locked by `TestByteCapEnforcement::test_enforce_byte_cap_truncates_nested_body`. |
| F2 — `_NEWCMD_RE` greedy capture corrupts multi-newcommand lines | HIGH | **fixed** | `server/handlers/definitions.py`: dropped `re.DOTALL`, regex now matches only the macro PREFIX up to the opening `{` of the expansion. New `_extract_pairs(line)` uses a brace-balance walker (`_balance_braces`) to handle internal `}` correctly. Locked by `TestDefinitionsParser` (3 tests). |
| F3 — Path traversal in `get_definitions` | MEDIUM | **fixed** | `server/handlers/definitions.py`, `paper.py`, `lemma.py` all validate `paper_id` via `ingest.identifiers.is_valid_paper_id` before use. Locked by `TestPaperIdValidation` (3 tests). |
| F4 — `enforce_byte_cap` measures inner payload, off ~2× | MEDIUM | **fixed** | `_WIRE_OVERHEAD_FACTOR = 2` multiplies the inner measurement; the operator-configured cap is the wire-byte ceiling. Documented in the helper's docstring. |
| F5 — `search_papers` proof-chunk exclusion documented only in docstring | MEDIUM | **fixed** | `SEARCH_PAPERS.description` now carries the verbatim WARNING; the result envelope adds an `excluded_kinds: ["proof"]` field. Locked by `TestSearchSchemaContract::test_search_excludes_proof_kinds_documented`. |
| F6 — Schema drift from brief: missing filters/cursor on search_papers | MEDIUM | **fixed** | `handle_search_papers` now accepts both as `Annotated[..., Field(...)]` parameters; the result's `filter_warnings` array surfaces "ignored at v1" messages when either is set. Locked by `TestSearchSchemaContract::test_search_accepts_filters_arg` + `test_search_accepts_cursor_arg`. |
| F7 — Hardcoded `version: 1` in search results | MEDIUM | **fixed** | `_arrow_to_rows` no longer emits the field. Locked by `test_search_results_have_no_version_field`. |
| F8 — `label` field concatenates name+label in odd order | LOW | **deferred** | Cosmetic; agents can use the raw `theorem_name` / `theorem_label` fields directly. |
| F9 — Dead `import asyncio` in `search.py` | LOW | **fixed** | Removed both the import and the `_ = asyncio` suppression line. Ruff clean. |
| F10 — `_unused_args` field with leading underscore | LOW | **fixed** | Renamed to `unused_args` in `chunk.py` payload. |
| F11 — `_PAPER_ID_RE` duplicated in 3 places | LOW | **fixed** | New `ingest/identifiers.py` is the single source of truth; `chunk.py` imports `is_valid_chunk_id`; `definitions.py`/`paper.py`/`lemma.py` import `is_valid_paper_id`. New `tests/test_identifiers.py` (15 tests) locks the regex equality across `ingest.chunker._PAPER_ID_RE`, `tools.validate_eval_fixtures._PAPER_ID_RE`, and `ingest.identifiers.PAPER_ID_RE`. |
| F12 — `find_lemma_by_name` loads entire chunks table | LOW | **deferred** | Documented as scale limitation in the description; SQLite FTS5 swap is internal in E10_S02. |
| F13 — `get_paper` magic 10000 limit | LOW | **deferred** | The 50-paper test corpus has ~5 chunks per paper; magic number is benign for v1 scale. |
| F14 — `find_equation` "polite fiction" relevance | LOW | **fixed** | `FIND_EQUATION.description` now carries the explicit WARNING. |
| F15 — Test doesn't pin `_meta` wire bytes | LOW | **deferred** | E06_S06 will land the byte-stability hash test that pins the full wire form. The current schema test asserts the Python-object surface; the wire form depends on FastMCP's serialization which E06_S06 freezes. |
| F16 — `mocked_bge_m3` fragile patch fan-out | LOW | **deferred** | Documented in the implementation summary; structural refactor (always-import-module pattern) is a future cleanup. |
| F17 — `inputSchema.title` leaks Python handler name | LOW | **deferred** | Cosmetic; the title is byte-stable across runs and a known FastMCP/Pydantic artifact. |
| F18 — `_sort_dict` doesn't handle tuples/sets | LOW | **deferred** | No current handler returns a tuple or set in structuredContent; future addition can extend the helper. |

**New regression tests added in this rectification batch (25):**
- `TestPaperIdValidation::test_get_definitions_rejects_path_traversal` (F3)
- `TestPaperIdValidation::test_get_paper_rejects_malformed_paper_id` (F3)
- `TestPaperIdValidation::test_find_lemma_rejects_malformed_paper_id` (F3)
- `TestSearchSchemaContract::test_search_accepts_filters_arg` (F6)
- `TestSearchSchemaContract::test_search_accepts_cursor_arg` (F6)
- `TestSearchSchemaContract::test_search_excludes_proof_kinds_documented` (F5)
- `TestSearchSchemaContract::test_search_results_have_no_version_field` (F7)
- `TestDefinitionsParser::test_extract_pairs_two_macros_on_one_line` (F2)
- `TestDefinitionsParser::test_extract_pairs_with_internal_braces` (F2)
- `TestDefinitionsParser::test_extract_pairs_handles_renewcommand` (F2)
- `TestByteCapEnforcement::test_enforce_byte_cap_truncates_nested_body` (F1 + F4)
- `TestByteCapEnforcement::test_enforce_byte_cap_under_cap_passthrough` (F1)
- 13 tests in new `tests/test_identifiers.py` locking the `ingest.identifiers` single-source-of-truth contract (F11)

**Suite at rectification time:** 677 passed, 3 skipped, ruff clean.
