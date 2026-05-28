# Research Brief — textbook-ingest-m11

**Agent:** milestone-researcher (brief-2)
**Generated:** 2026-05-28T18:35:00Z

---

## In-codebase context

### Current get_chunk handler pipeline (verbatim comment trail, `server/handlers/chunk.py`)

```
# E13_S02 (Threat 2) — sanitize body_text BEFORE byte-cap truncation
# so the 256 KB cap measures post-sanitize bytes. Wrapping is
# deferred until AFTER truncation so the delimiter tags are not
# sliced off by the cap path (which truncates ``body_text``
# in-place when the structured payload exceeds the cap).
raw_body = row["body_text"] or ""
sanitized_body = sanitize_retrieved_text(raw_body)
chunk = { "body_text": sanitized_body, ... }
...
structured, content_blocks = enforce_byte_cap(payload, chunk_id=chunk_id, body_text_path=("chunk", "body_text"))
# E13_S02 — wrap AFTER truncation so the delimiter pair is well-formed
structured["chunk"]["body_text"] = wrap_retrieved_text(structured["chunk"]["body_text"], kind="chunk")
```

The current pipeline is: **sanitize → (byte-cap truncation) → delimiter wrap**. m11 inserts license truncation as a new first step: **sanitize → (license truncation) → (byte-cap truncation) → delimiter wrap**. License truncation must operate on the sanitized raw string BEFORE the byte-cap path and BEFORE delimiter wrapping. This is the only ordering that guarantees the 300-char cap cannot be bypassed.

### Confirmed: get_chunk is the ONLY handler returning full body_text

Grepping `body_text` across all `server/handlers/*.py`:

- `chunk.py` — returns `chunk["body_text"]` (full, up to 256 KB cap). **THE target.**
- `search.py` — `_snippet(body_text)` slices to `SNIPPET_MAX_CHARS = 150` chars then wraps. 150 < 300, so search snippets **never** expose >300 chars. The brief is correct that `search_papers` does not need truncation.
- `definitions.py` — returns `expansion` (LaTeX macro bodies from the preamble table, NOT `body_text` from the chunks table). No full chunk body surface.
- `equation.py` — `_dense_only` returns `chunk_id`, `paper_id`, `score` only. No `body_text`.
- `lemma.py` — returns `display_name` (wrapped theorem name) + metadata. In-memory fallback also returns only `theorem_name`, `chunk_id`, etc. — no `body_text`.
- `paper.py` — uses `body_text_path=("paper", "abstract")` for the byte-cap path but `abstract` is NULL until E11 backfills.

**Conclusion:** `get_chunk` is the exclusive body_text leakage surface. The brief's `get_chunk`-only scope is correct.

### License column status

From `ingest/schema.py:165` (verbatim):
```
# ``license`` is free-text — domain is documentary, not
# validated. Default ``"arxiv-license"`` for arXiv chunks;
# textbook chunks carry the textbook's specific license token
# (``"GFDL"`` for Stacks Project, ``"author-distributed"`` for
# lecture notes, etc.). ``truncated_for_license`` snippet
# truncation enforcement lands with textbook-ingest-e5.
```

From `ingest/chunker_types.py:129` (verbatim):
```
Documentary at m2; enforcement of ``truncated_for_license`` flag lands with e5.
```

The `license` column is a nullable `pa.utf8()` column, populated at write time with `"arxiv-license"` by default for arXiv chunks. There is NO `truncated_for_license` schema column — the flag is a RUNTIME response flag only (not persisted). **No schema migration required.**

### TOOL_SCHEMA_VERSION and re-pin scope

`server/tools.py:147`: `TOOL_SCHEMA_VERSION: int = 15`

`tests/test_server_tool_schema.py:95`: `EXPECTED_TOOL_SCHEMA_SHA256 = "b03e965d1f0a90d54dda1cc39d64317e2e3ceaadeb4cdbe96a97219194d7a308"`

`tests/test_prompts.py:649`: `EXPECTED_BP1_SHA256 = "483344e3fcdea1d64de893cc669c9f142fd6f1198d4c8d383cd9c232558959bc"`

The `GET_CHUNK` `ToolMeta.description` (verbatim):
```
"Fetch the full body of one chunk by its content-addressable chunk_id. Use search_papers "
"first to obtain chunk_ids. Large chunks (over the 256 KB inline cap) are returned as a "
"resource_link with body_truncated=True; agents follow the link to fetch the full payload."
```

m11 adds `truncated_for_license` to the RESPONSE envelope only — not to the tool's `name`, `description`, or `inputSchema`. Per the textbook-ingest-m9 lesson (prompts-bp-discipline.md): "BP1 hashes only {name, description} per tool; the Field description (which lives in the inputSchema) and the bumped version are both OUTSIDE the BP1 byte region."

**Key determination:** If the implementer updates `GET_CHUNK.description` to mention `truncated_for_license`, both `EXPECTED_TOOL_SCHEMA_SHA256` AND `EXPECTED_BP1_SHA256` must be re-pinned. If the implementer does NOT update the description (adds the field silently), only `EXPECTED_TOOL_SCHEMA_SHA256` might need re-pinning depending on whether `inputSchema` changed. Adding a response-only field with NO description/inputSchema change: **no re-pin required.** This is the recommended path.

### The `retrieve_single` cache question

The 3-tier retrieval cache (`server/cache.py`) caches QUERY results for `search_papers`. `get_chunk` does NOT use the retrieval cache — it goes directly to LanceDB via `chunks_table.search().where(...)`. Cache-key correctness is therefore NOT an issue for m11. There is no cached `get_chunk` response that could serve stale pre-truncation content.

---

## Security failure-mode analysis

Six failure modes, ordered by severity:

### FM-1 (CRITICAL): License truncation applied after delimiter wrap — >300 chars leaks

**Trigger:** implementer places license truncation AFTER `wrap_retrieved_text(...)` instead of BEFORE it.

**Symptom:** truncation slices off part of the delimiter tag (`...abc</retrieved_c`), producing a malformed injection-defense wrapper AND potentially surfacing more than 300 chars of actual content (the tags add ~35 chars overhead, so a 300-char cap applied to the WRAPPED string gives ~265 chars of content).

**Mitigation:** license truncation MUST operate on `sanitized_body` (the raw string before any wrapping), mirroring the existing `E13_S02` comment at `chunk.py:69-74`. The pipeline order is:
1. `sanitize_retrieved_text(raw_body)` → `sanitized_body`
2. `_apply_license_truncation(sanitized_body, license)` → `body_for_cap`
3. `enforce_byte_cap(payload, ...)` using `body_for_cap`
4. `wrap_retrieved_text(structured["chunk"]["body_text"], kind="chunk")`

### FM-2 (CRITICAL): Non-OA body leaks via resource_link when license truncation is applied AFTER byte-cap

**Trigger:** a non-OA chunk body is >256 KB (unlikely but possible for pathological textbook chunks). If license truncation runs AFTER `enforce_byte_cap`, the byte-cap fires first and sets `body_truncated=True` + `resource_link_uri`. The agent follows the resource link and gets the FULL unrestricted body from the corpus.

**Symptom:** an agent correctly receives `truncated_for_license=True` in the response envelope but can follow `resource_link_uri` to get unrestricted content.

**Mitigation:** license truncation must be innermost (step 2 above). After license truncation, the body is always ≤300 chars, which is far below the 256 KB byte-cap. The byte-cap will never fire on a license-truncated chunk, so `resource_link_uri` is never emitted. The 300-char post-truncation body guarantees this invariant.

**Note:** This is the "headline correctness risk" named in the brief. The ordering fix in FM-1 automatically closes FM-2 as a consequence.

### FM-3 (MEDIUM): UTF-8 multibyte codepoint sliced mid-character at position 300

**Trigger:** a non-OA chunk body contains multi-byte Unicode (e.g. mathematical symbols: `∀`, `∈`, `≤`). Python `str` slicing (`body[:300]`) operates on **Unicode code points**, not bytes. A single `str[300]` slice CANNOT split a codepoint.

**Symptom (if bytes were used instead):** `body_bytes[:300]` could produce a partial UTF-8 sequence, causing JSON serialization failures or mojibake.

**Mitigation:** use Python `str[:300]` (char-level, as the brief specifies), NOT `bytes[:300]`. Python's `str` type is a sequence of Unicode code points; slicing at position 300 is always codepoint-safe. The current `_snippet` function in `search.py:956` uses `sanitized[:SNIPPET_MAX_CHARS]` (str slice) — follow the same pattern. **This is not a risk with correct implementation.**

### FM-4 (HIGH): `license=""` or `license=None` — fail-closed correctness

**Trigger:** a chunk has `license=None` (possible for arXiv chunks ingested before m2 migration if the backfill had gaps) or `license=""` (empty string, possible for textbook chunks with no explicit license field).

**Symptom:** if the allowlist check is `license in OA_ALLOWLIST`, a `None` key raises `TypeError` and the handler crashes. If `license == ""` is treated as OA, non-OA textbook chunks escape truncation.

**Mitigation:** the `is_open_access` helper must explicitly normalize:
```python
def is_open_access(license: str | None) -> bool:
    if not license:  # handles None and ""
        return False  # FAIL CLOSED
    return license in OA_ALLOWLIST
```
The `if not license` guard covers both `None` and `""` before the set-lookup.

### FM-5 (MEDIUM): Delimiter wrap applied to truncated text defeats injection defense

**Trigger (false alarm — confirm):** implementer worries that truncating at 300 chars might leave a partial `</retrieved_chunk>` tag embedded in the content, breaking the wrap.

**Analysis:** The license truncation applies to `sanitized_body` BEFORE any delimiter wrapping occurs. At the point of license truncation, there are NO delimiter tags in the string — they are added AFTER. The `escape-on-emit` mechanism in `wrap_retrieved_text` handles any literal `<retrieved_chunk>` sequences that appear in the original arXiv/textbook content, but those are in the pre-truncation raw text, not in the wrapper tags themselves. A 300-char slice of `sanitized_body` cannot contain a partial tag that was added by a later operation. **This is not a risk if ordering is correct (FM-1 mitigation).**

### FM-6 (LOW): Search snippet `truncated_for_license` flag absent on non-OA rows

**Trigger:** a downstream agent calls `search_papers` on a mixed corpus containing non-OA chunks. It receives a 150-char snippet but no `truncated_for_license` flag on the snippet row.

**Symptom:** the agent does not know from the search row alone that the full body is restricted. It calls `get_chunk` and gets the truncated body + `truncated_for_license=True`. The flag is present on `get_chunk` but absent on `search_papers` result rows.

**Analysis:** the brief explicitly asks "research should decide whether non-OA search rows should ALSO carry the truncated_for_license flag for transparency." The brief recommends omitting it from `search_papers` because 150 < 300 (no truncation occurs there). **Recommendation: do NOT add the flag to `search_papers` rows.** The agent learning from `get_chunk`'s `truncated_for_license=True` is the correct discovery path. Adding it to `search_papers` would change the search result JSON schema, require a `TOOL_SCHEMA_VERSION` bump, and re-pin hashes unnecessarily.

---

## Prior decisions and lessons

- **m9 BP1 lesson (from prompts-bp-discipline.md):** `BP1` hashes only `{name, description}` per tool. A Field-description change (inputSchema) drifts `EXPECTED_TOOL_SCHEMA_SHA256` but NOT `EXPECTED_BP1_SHA256`. A ToolMeta.description change drifts BOTH. Adding a response-only field (no ToolMeta or Field change) drifts NEITHER. This is load-bearing for the re-pin scope decision.

- **`assert` banned for invariants** (CLAUDE.md §4.7): use `if … raise RuntimeError(…)`. The `is_open_access` helper must not use `assert`.

- **`BaseHTTPMiddleware` project-banned** (E06_S01 F1): license truncation lives in the handler body, not middleware. Already correct per the brief's scoping to `get_chunk`.

- **`KMP_DUPLICATE_LIB_OK=TRUE` in `tests/conftest.py`** must not be removed. m11 does not touch `conftest.py`.

- **No prior `is_open_access` helper exists** — grep confirms zero matches for `OA_ALLOWLIST` or `is_open_access` in `server/`. The helper is a net-new addition to `server/handlers/chunk.py` or a shared module (recommendation: `server/license_policy.py` as a standalone module for testability).

- **`TOOL_SCHEMA_VERSION = 15`** at current HEAD. The version comment trail in `server/tools.py:136-147` documents that a description change → bump BOTH version AND `EXPECTED_TOOL_SCHEMA_SHA256`. Adding a response field without touching the description → no bump needed. The brief says "re-pin SHAs only if a tool description/inputSchema actually changes" — this aligns with the m9 lesson.

- **git log:** `a7da3f0` (most recent) closes textbook-ingest-m10 (PDF hardening doc). m10 and m11 are the two-part e5; m11 is the last textbook-ingest milestone. No adjacent state.json to check beyond m10 (complete).

---

## External sources

### OA license semantics

The OA allowlist `{arxiv-license, CC-BY, CC-BY-SA, CC0, public-domain, GFDL}` is grounded in:
- **arxiv-license:** arXiv's standard non-exclusive license for distribution/display of submissions. Full text display is explicitly permitted for non-commercial research use. This is the dominant corpus license.
- **CC-BY, CC-BY-SA:** Creative Commons licenses permitting unrestricted redistribution with attribution (BY) or share-alike (SA). Both are unambiguously open access.
- **CC0, public-domain:** No rights reserved; unrestricted.
- **GFDL:** GNU Free Documentation License — the Stacks Project's license. Redistribution with modification is permitted under GFDL terms. While copyleft, it is open-access for display and copying. The roadmap explicitly tiers it as OA.
- **author-distributed:** No explicit redistribution license. Could be "all rights reserved" with informal distribution. Fail-closed → non-OA truncation is the safe default.
- **no explicit license:** Unknown = non-OA by fail-closed policy.
- **copyrighted:** Explicitly restricted.

The allowlist is conservative and legally defensible: arXiv's terms of use permit display of full texts for research/education; CC/GFDL licenses permit redistribution. Non-listed values are unknown → truncated.

No external doc needed for the MCP spec — the `get_chunk` `structuredContent` envelope shape is already established in the codebase; m11 adds one new field to the envelope without changing the MCP protocol layer.

---

## Recommendation

**Implement license truncation as a single new helper `server/license_policy.py` with an `is_open_access(license: str | None) -> bool` function and an `OA_ALLOWLIST = frozenset({...})` constant. In `server/handlers/chunk.py`, apply license truncation immediately after `sanitize_retrieved_text(raw_body)` and before `enforce_byte_cap`, setting `truncated_for_license=True` in the top-level payload dict when truncation fires. Do NOT modify `GET_CHUNK` ToolMeta description or any `inputSchema` field — this avoids any re-pin of `EXPECTED_TOOL_SCHEMA_SHA256` or `EXPECTED_BP1_SHA256`.**

Reasoning: placing the helper in a separate module makes it independently testable. The ordering (sanitize → license-truncate → byte-cap → wrap) is the only order that prevents the FM-1/FM-2 leakage paths. Keeping the ToolMeta description unchanged avoids a cache-invalidation event for the last textbook-ingest milestone (no reason to invalidate BP1 on a response-envelope-only change).

The implementer should place `license` in the `chunk` dict (alongside existing fields) for observability, and `truncated_for_license` at the top-level payload (parallel to `body_truncated` from the byte-cap path). Both `body_truncated` and `truncated_for_license` can be True simultaneously in pathological cases (a non-OA chunk that is also >256 KB before truncation — but after license truncation at 300 chars, the byte-cap will never fire, so in practice they are mutually exclusive).

---

## Open questions

1. **Should `license` be surfaced in the `chunk` dict of the `get_chunk` response?** The current handler does not include `license` in the chunk fields (line 76-87 of `chunk.py` lists the fields explicitly). Adding it lets agents see the license token directly, which is useful for transparency. Recommendation: YES, add `license` to the `chunk` dict alongside the existing fields. It is a storage-layer field available via `row["license"]` with the same LanceDB lookup.

2. **Should `truncated_for_license` be `false` (explicit) or absent when not truncated?** The brief says "false (or absent per the established absent-not-null pattern)." The byte-cap `body_truncated` is set to `True` only when the cap fires (not set to `False` in the happy path). For consistency, recommend absent (not set) when no truncation occurs. This avoids polluting the response with a `False` flag that adds no information.

No open questions that would block implementation. The two items above are design choices with clear recommendations.

---

## External writes the implementation will require

None — this milestone is purely local. No git push, no PR, no infra mutation, no third-party API call. The implementer commits to `main` directly per §4.1.
