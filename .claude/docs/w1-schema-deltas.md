# W1 staged tool-schema deltas

Schema changes that are **implemented in behaviour but deliberately not
yet on the wire**. `tools/list` must stay byte-stable for BP1
prompt-cache discipline (`.claude/notes/07-multi-agent-caching.md`), so
description and response-shape text lands in ONE bundled
`TOOL_SCHEMA_VERSION` re-pin rather than once per contributing milestone.

**How to use this file.** When a milestone's behaviour has merged but its
tool-description / response-shape / inputSchema change is being held for
a batched re-pin, stage the exact replacement text here. Then a future
schema-bump milestone applies every staged delta in a single commit,
bumps `TOOL_SCHEMA_VERSION`, re-pins `EXPECTED_TOOL_SCHEMA_SHA256`
(`pytest --update-tool-schema-hash`) **and** `EXPECTED_BP1_SHA256`
(hand-edited — no update flag) **and** the version field of any affected
`server/schemas/*.json`, and deletes the applied sections. A delta lands
here only when its behaviour is already merged and tested on `main` —
this is a staging area, not a wishlist.

## Currently staged

### `lean_verify` — the axiom-hygiene axis (issues #205 / #281 / #332)

**Behaviour status:** merged and tested. The handler runs a `#print axioms`
round-trip over the declarations a full-mode snippet introduces and emits an
always-present, Certificate-shaped `axiom_audit` record; the result schema
(`server/schemas/lean_verify_result.json`) carries the new property and the
corrected `status` / `compilation_success` descriptions. `tools/list` is
untouched — `LEAN_VERIFY.description` and its `inputSchema` are byte-identical,
so neither `EXPECTED_TOOL_SCHEMA_SHA256` nor `EXPECTED_BP1_SHA256` moved.

**Why staged rather than shipped.** Issue #205's acceptance is explicit: the
change "MUST ride the next batched `TOOL_SCHEMA_VERSION` re-pin window — do not
mint a separate re-pin." The window it names (W1 / `agent-platform-e2`, issues
#65 / #72 / #87) **already closed** at agent-platform-m3 (20 → 21, #72 and #87
both closed), so there was no open window to ride. Bumping alone was the one
thing the issue forbade, so the behaviour merged and the wire text waits here.

**Carrier candidate — resolved: there is none yet.** A `TOOL_SCHEMA_VERSION`
21 → 22 bump for issue #204 (`search_papers.cache_match`) was in flight in a
concurrent session at the time this was staged, and was noted here as the
natural carrier. It did **not** land: #204 reached the same conclusion this
section did and staged its bump below instead of minting one. Both deltas now
wait on the same window. The numbers in the checklists below assume 22; confirm
the final integer before applying, and note that applying BOTH sections
together is one re-pin, not two.

#### Delta 1 — `server/schemas/lean_verify_result.json`

Set `"version"` to the new `TOOL_SCHEMA_VERSION`, and delete the
"SHAPE CHANGE … WITHOUT a version bump, deliberately" paragraph from the
top-level `description` (it documents precisely this staging gap), replacing it
with a normal history sentence:

> Bumped at &lt;milestone&gt; (21 → 22) together with the always-emitted
> `axiom_audit` record and the corrected `compilation_success` / `status`
> descriptions (issues #205 / #281 / #332) — the axiom-hygiene axis, reported
> independently of `status` per the trust-language policy.

#### Delta 2 — `server/tools.py`, `LEAN_VERIFY.description`

This is a **BP1-affecting** edit (BP1 hashes `{name, description}`), so
applying it re-pins `EXPECTED_BP1_SHA256` **by hand** as well as
`EXPECTED_TOOL_SCHEMA_SHA256` via `pytest --update-tool-schema-hash`.

Replace this run of text:

```
"goals_remaining + sorry_goals, an env token, and "
"continuation_status. A continuation token from before a timeout "
```

with:

```
"goals_remaining + sorry_goals, an env token, "
"continuation_status, and axiom_audit. IMPORTANT: status and "
"compilation_success report elaboration and kernel acceptance ONLY - "
"they do not check axiom soundness, so a snippet declaring its own "
"axiom returns status='ok'. Read axiom_audit (outcome "
"clean/flagged/unknown/not-applicable, plus the per-declaration axiom "
"sets behind it) before treating any result as trustworthy; neither "
"field alone is a trust verdict. A continuation token from before a timeout "
```

Keep the literal-string discipline: no f-strings, no computed content
(`TestToolRegistration::test_lean_verify_in_all_tools` asserts it).

#### Delta 3 — `tests/test_handlers_lean_verify.py`

`TestToolRegistration::test_schema_version_matches_tool_schema_version`
hard-asserts `TOOL_SCHEMA_VERSION == 21`; update it to the new integer and
extend its docstring history, as every prior bump has.

### `search_papers` — the `cache_match` provenance axis (issue #204)

**Behaviour status:** merged and tested. The Tier-2 semantic cache now keys on
`k` (ordinally — an entry answers a request only when it was built at least as
wide) plus `corpus_version` and embedder identity, and a Tier-2 hit reports
whether it matched this query's own embedding or a cosine-≥0.97 neighbour's.
The handler puts that on the wire as an optional `cache_match` object
(`{kind, cosine}`), and `server/schemas/search_papers_result.json` declares the
property — it has to, the envelope is `additionalProperties: false`.
`tools/list` is untouched: `SEARCH_PAPERS.description` and its `inputSchema`
are byte-identical, so neither `EXPECTED_TOOL_SCHEMA_SHA256` nor
`EXPECTED_BP1_SHA256` moved.

**Why staged rather than shipped.** Same reasoning as the `lean_verify`
section above, reached independently: a `TOOL_SCHEMA_VERSION` bump drifts the
`tools/list` bytes through the `_meta.tool_schema_version` echo, this repo
mints that re-pin only in a batched window, and the W1 window closed at
agent-platform-m3. Issue #204's own acceptance criteria say nothing about the
wire version — they are about the cache key — so minting a re-pin for it alone
would have spent the BP1 cache on a bookkeeping integer.

#### Delta 1 — `server/schemas/search_papers_result.json`

Set `"version"` to the new `TOOL_SCHEMA_VERSION` and `"$id"` to the matching
`…/search_papers_result/v<N>.json`. Delete the "SHAPE CHANGE at issue #204 …
WITHOUT a version bump, deliberately" passage from the top-level `description`
(it documents precisely this staging gap) and replace it with a normal history
sentence:

> Bumped at &lt;milestone&gt; (21 → 22) together with the optional
> `cache_match` provenance object (issue #204) — present only on a Tier-2
> semantic-cache hit, naming whether the rows answer this query's own
> embedding or a cosine-≥0.97 neighbour's.

Two tests cross-check this pair, so both move together or both fail:
`tests/test_snippet_contract.py::TestSchemaVersionPin` and
`tests/test_search_filter.py::TestSchemaConformanceForFiltersApplied::test_schema_version_matches_after_m2_bump`
(the latter also asserts the `$id` suffix).

#### Delta 2 — `server/tools.py`, the `TOOL_SCHEMA_VERSION` comment block

Replace the "STILL 21 at issue #204 …, deliberately" paragraph with the normal
`21 -> 22 (<milestone>)` history entry. Nothing else in `server/tools.py`
changes for #204 — the `SEARCH_PAPERS` ToolMeta is untouched, so this stays a
response-shape-only re-pin **from #204's side**. (The `lean_verify` section
above contributes a description edit, which makes the combined bump
BP1-affecting; `EXPECTED_BP1_SHA256` is hand-edited, no update flag.)

There is **no** Delta 3 for #204: no test hard-codes the version integer for
`search_papers`. Both cross-checks above read `TOOL_SCHEMA_VERSION` at runtime.

---

## Previously applied

The three deltas staged for W1 (get_chunk `include_referenced`,
search_papers `filters.include_kinds`, find_equation LaTeX route) were
all applied in the **agent-platform-m3 / W1** batched bump
(`TOOL_SCHEMA_VERSION` 20 → 21), alongside that milestone's own schema
changes (batch `get_chunk`, inert-arg removal, truthful descriptions,
canonical examples, ToolAnnotations, and the search-row title/year join).
The `find_equation` delta was applied together with flipping
`Config.eq_latex_route` to `True`, as the staging note required.
