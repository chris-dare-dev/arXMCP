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

_None._ Both deltas that had accumulated here after W1 closed — lean_verify`s
`axiom_audit` (issues #205 / #281 / #332) and search_papers` `cache_match`
(issue #204) — were applied together in the **W2 batched re-pin**
(`TOOL_SCHEMA_VERSION` 21 -> 22). Both had merged bump-free and waited here
for a window, which is exactly what this file is for.

That window was **BP1-affecting**: the `LEAN_VERIFY.description` edit changed
`{name, description}`, so `EXPECTED_BP1_SHA256` was hand-edited in
`tests/test_prompts.py` alongside the regenerated
`EXPECTED_TOOL_SCHEMA_SHA256`. #204 contributed to the tool-schema hash only,
through the `_meta.tool_schema_version` echo.

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
