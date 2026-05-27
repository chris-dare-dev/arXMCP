# Research Brief — textbook-ingest-m1

**Agent:** milestone-researcher (brief-1, single-mode)
**Generated:** 2026-05-27T21:00:00Z

---

## In-codebase context

### `ingest/identifiers.py` — load-bearing verbatim quotes

```python
_PAPER_ID_FULL_PATTERN = (
    r"^\d{4}\.\d{4,5}(v\d+)?\Z"  # new style
    r"|"
    r"^[a-z][a-z\-]*/\d{7}(v\d+)?\Z"  # old style
)
PAPER_ID_PATTERN = (
    r"\d{4}\.\d{4,5}(v\d+)?|[a-z][a-z\-]*/\d{7}(v\d+)?"
)
CHUNK_ID_PATTERN = rf"arxiv:({PAPER_ID_PATTERN}):[0-9a-f]{{16}}"
CHUNK_ID_RE = re.compile(rf"^{CHUNK_ID_PATTERN}$")
```

The F3 closure comment in the module reads verbatim:
> "F3 closure from proof-verify-handler-wiring-m1 critique: use `\Z` not `$` for
> the end-of-string anchor. Python's default `$` matches both end-of-string AND
> just before a trailing `\n`, so `is_valid_paper_id("2604.26204\n")` returned
> True pre-fix."

`CHUNK_ID_RE` uses `$` (not `\Z`) because it is constructed as `rf"^{CHUNK_ID_PATTERN}$"`.
This is an existing asymmetry: `_PAPER_ID_FULL_PATTERN` uses `\Z`; `CHUNK_ID_RE`
uses `$`. Any textbook chunk-id regex MUST use `\Z` for end-of-string — matching the
already-landed F3 fix.

`paper_id_from_chunk_id` calls `CHUNK_ID_RE.match(chunk_id)` and returns `match.group(1)`,
which is the first capture group of `PAPER_ID_PATTERN`. For textbook chunk-ids, this
group must capture `textbook:<slug>` — so the pattern must be restructured so that
`group(1)` covers the textbook paper_id form as well.

### `ingest/chunker.py` — inline copy of the pattern

`ingest/chunker.py:106–110` carries its own copy of the pattern:
```python
_PAPER_ID_RE = re.compile(
    r"^\d{4}\.\d{4,5}(v\d+)?\Z|^[a-z][a-z\-]*/\d{7}(v\d+)?\Z"
)
```
and `tests/test_identifiers.py:25` asserts:
```python
assert _PAPER_ID_RE.pattern == PAPER_ID_RE.pattern
```
**This test is the byte-equality lock.** Any change to `_PAPER_ID_FULL_PATTERN`
in `identifiers.py` MUST be reflected in `ingest/chunker.py:_PAPER_ID_RE` and in
`tools/validate_eval_fixtures.py:_PAPER_ID_RE` identically, or the test fails.

### `tools/validate_eval_fixtures.py` — third copy

`tools/validate_eval_fixtures.py:106–110` carries an identical third copy with the
same F3-closure comment. Same byte-equality constraint applies.

### Handler boundary — `is_valid_paper_id` call sites

`is_valid_paper_id` is called at 7 call sites:
- `server/handlers/paper.py:65`
- `server/handlers/definitions.py:89`
- `server/handlers/lemma.py:94`
- `server/routes/notebooks.py:152, 458, 554`
- `server/routes/ui.py:200, 270`

All call sites treat a `False` return as an adversarial input rejection (Threat 1).
Extending `is_valid_paper_id` to accept textbook IDs widens the set of inputs that
reach downstream LanceDB queries. That is the correct behavior for m1; downstream
schema enforcement is m2's job.

`is_valid_chunk_id` is called at `server/handlers/chunk.py:45` and
`server/handlers/citations.py:91`. The `CHUNK_ID_RE` currently hardcodes `arxiv:`
as the only valid prefix. Textbook chunk-ids will have prefix `textbook:`.
**The milestone brief says "Both inputs must round-trip via `paper_id_from_chunk_id`"
— this requires extending `CHUNK_ID_PATTERN` / `CHUNK_ID_RE` as well, even though
the brief also says "identifiers only."**

### Threat 1 verbatim from `08-security-observability-ops.md`

> **Threat 1: Path traversal via `paper_id`**
> Tool arguments come from LLM output. An LLM that has been prompt-injected by
> something it read in an arXiv abstract could pass `paper_id="../../../etc/passwd"`.
> **Mitigation:** strict regex on every arxiv ID input: `^\d{4}\.\d{4,5}(v\d+)?$`
> for new-style IDs, `^[a-z\-]+/\d{7}(v\d+)?$` for old-style. Reject at the
> JSON-Schema level so it never reaches handlers.

Note: the doc uses `$`, but the code already closed F3 with `\Z`. The `\Z` fix is
authoritative over this doc.

### `02-architecture-overview.md` chunk_id authority

> "Chunk IDs are content-addressable: `arxiv:<paper_id>:<sha256(canonical_chunk_bytes)[:16]>`."

The `arxiv:` prefix is documented as the canonical form. The textbook extension will
introduce `textbook:` as a second valid prefix. This is a deliberate protocol extension.

### Notebook slug regex from `tools/_notebook_common.py`

```python
SLUG_RE: re.Pattern[str] = re.compile(r"^[a-z][a-z0-9-]{2,30}$")
```

Description: "Lowercase ASCII + digits + hyphens, 3-31 chars, must start with a letter.
Rejects `..`, slashes, shell metacharacters, uppercase, leading hyphen."

---

## Prior decisions and lessons

Git log for `ingest/identifiers.py` and `tests/test_identifiers.py`:
```
5838d4b rect(server): close F1, F2, F3, F4, F5 from m1 critique
7e8ffee rect(tests,docs): close 1 HIGH + 5 MEDIUM + 3 LOW from E13_S01
d10157d feat(server,ingest): cite_neighbors graph query + intra-paper refs (E09_S03)
d253456 rect(server): close 2 HIGH + 5 MEDIUM + 4 LOW from E06_S03 critique
```

The `5838d4b` commit (rect for proof-verify-handler-wiring-m1 F3) landed the `\Z` fix.
Prior to that commit `is_valid_paper_id("2604.26204\n")` returned `True` — the
exact exploit the regression tests must guard.

The `d253456` commit closed F11 from E06_S03 (three call sites with independent regex
definitions; `identifiers.py` became the single source of truth then).

**Key pattern to preserve:** the byte-equality lock test (`test_chunker_pattern_equals_canonical`)
is the canary for the three-copy synchronization. Any change to the arXiv alternatives
in `_PAPER_ID_FULL_PATTERN` must propagate to `chunker.py:_PAPER_ID_RE` and
`validate_eval_fixtures.py:_PAPER_ID_RE` atomically. The textbook alternative is
NEW content that does NOT need to appear in the chunker or eval-fixture copies
(those modules never see textbook paper_ids in this milestone), but the arXiv
alternatives must remain byte-identical.

**Tool-schema re-pinning:** m1 does NOT touch `server/tools.py::ALL_TOOLS` or any
MCP tool definition. `EXPECTED_TOOL_SCHEMA_SHA256` does NOT need re-pinning in this
milestone. The roadmap confirms SHA re-pin is deferred to m3.

---

## External sources

The capability-scout final report (CAND-11 / F3 MAJOR) states verbatim:
> "`is_valid_paper_id` regex change is a Threat-1 surface change (path-traversal
> mitigation). ≥5 new regression tests against `\Z`-anchored arXiv-ID + textbook
> form composition."

MCP spec and Anthropic prompt-caching docs are not relevant to this identifier-only
milestone. No external vendor docs consulted.

---

## Recommendation

**Use a single composed regex in `_PAPER_ID_FULL_PATTERN` with a third alternative,
and update `CHUNK_ID_PATTERN` / `CHUNK_ID_RE` to accept `textbook:` prefix.**

Specifics:

1. **`<slug>` regex:** Use the existing `SLUG_RE` inner pattern `[a-z][a-z0-9-]{2,30}`
   verbatim. This is already the path-traversal-hardened slug contract. It forbids
   colons, slashes, dots, uppercase, null bytes, and whitespace — all injection vectors.
   The `textbook:` prefix already contains one colon as the delimiter; the slug inner
   pattern must not permit colons (it doesn't — `[a-z0-9-]` only). No deviation from
   `SLUG_RE` is needed.

2. **`<sha>` shape:** Use 16 lowercase hex chars (`[0-9a-f]{16}`) — matching the
   existing arXiv chunk-id sha length. Reason: `_compute_chunk_id` already emits
   16-hex for arXiv chunks; textbook chunker (m3) will follow the same derivation.
   Mixing lengths creates a two-regime validation table for no benefit.

3. **Regex structure — single composed regex, NOT a separate function:**
   Extend `_PAPER_ID_FULL_PATTERN` with a third alternative:
   ```python
   _PAPER_ID_FULL_PATTERN = (
       r"^\d{4}\.\d{4,5}(v\d+)?\Z"
       r"|"
       r"^[a-z][a-z\-]*/\d{7}(v\d+)?\Z"
       r"|"
       r"^textbook:[a-z][a-z0-9\-]{2,30}\Z"  # textbook:<slug> form
   )
   ```
   Rationale: the brief says "extend `is_valid_paper_id`"; a single compiled regex
   keeps `PAPER_ID_RE` as the single source of truth without adding a new public
   symbol. The textbook alternative does NOT include the `:<sha>` component — the
   paper_id is `textbook:<slug>`, and the sha is the chunk suffix. This mirrors how
   arXiv paper_ids do not contain the `:<16-hex>` suffix.

4. **`PAPER_ID_PATTERN` (no-anchors inner form):** Add the textbook alternative
   WITHOUT the `\Z` anchor (just as the arXiv alternatives lack `^`/`\Z`):
   ```python
   PAPER_ID_PATTERN = (
       r"\d{4}\.\d{4,5}(v\d+)?"
       r"|[a-z][a-z\-]*/\d{7}(v\d+)?"
       r"|textbook:[a-z][a-z0-9\-]{2,30}"
   )
   ```

5. **`CHUNK_ID_PATTERN` / `CHUNK_ID_RE`:** The current pattern is
   `rf"arxiv:({PAPER_ID_PATTERN}):[0-9a-f]{{16}}"`. With the textbook alternative
   inside `PAPER_ID_PATTERN`, this expands naturally — but the prefix `arxiv:` is
   hardcoded. It must be changed to accept both prefixes:
   ```python
   CHUNK_ID_PATTERN = (
       rf"arxiv:({_ARXIV_PAPER_ID_PATTERN}):[0-9a-f]{{16}}"
       r"|"
       rf"textbook:({_TEXTBOOK_SLUG_PATTERN}):[0-9a-f]{{16}}"
   )
   ```
   Or more cleanly: redefine so that `PAPER_ID_PATTERN` is the full inner form and
   `CHUNK_ID_PATTERN` wraps it as: `rf"(?:arxiv|textbook):({PAPER_ID_INNER}):[0-9a-f]{{16}}"`.
   **WARNING:** this changes `match.group(1)` semantics in `paper_id_from_chunk_id`.
   The simplest safe form that preserves `group(1)` = paper_id is to make the
   whole prefix+paper_id a single captured group:
   ```python
   CHUNK_ID_PATTERN = rf"(arxiv:{_ARXIV_INNER}|textbook:{_TEXTBOOK_INNER}):[0-9a-f]{{16}}"
   CHUNK_ID_RE = re.compile(rf"^\Z" ... )  # full-match
   ```
   The implementer should make `CHUNK_ID_RE` use `\Z` (not `$`) for the end anchor,
   closing the same F3 class of bug that `_PAPER_ID_FULL_PATTERN` already fixed.

6. **`CHUNK_ID_RE` end-anchor fix:** The current `CHUNK_ID_RE = re.compile(rf"^{CHUNK_ID_PATTERN}$")`
   uses `$`, not `\Z`. **Fix this to `\Z` as part of this milestone.** A trailing
   newline in a chunk_id currently passes `is_valid_chunk_id`. This is the same F3
   bug class in a second location.

7. **Three-copy synchronization:** The arXiv alternatives in `chunker.py:_PAPER_ID_RE`
   and `validate_eval_fixtures.py:_PAPER_ID_RE` must remain byte-identical to the arXiv
   portions of `identifiers.py:_PAPER_ID_FULL_PATTERN`. The textbook alternative does
   NOT need to be added to those copies (chunker/eval-fixture never produce textbook IDs
   in m1). The byte-equality test asserts `_PAPER_ID_RE.pattern == PAPER_ID_RE.pattern`;
   if `PAPER_ID_RE` gains a textbook branch, the test will fail unless the chunker and
   eval-fixture copies are updated too — OR the test is narrowed to compare only the
   arXiv subpatterns. **The cleanest fix is to update all three copies to include the
   textbook alternative**, maintaining the invariant. Cost: two-line change in each file.

---

## Threat-1 regression test inputs (exact fixtures)

All of these MUST return `False` from `is_valid_paper_id` and fail `is_valid_chunk_id`:

1. `"textbook:../etc/passwd"` — slash + dotdot in slug (path traversal)
2. `"textbook:foo:bar:baz"` — extra colon; 4 colon-segments instead of 3 in chunk form
3. `"textbook:foo\x00bar"` — null byte in slug
4. `"textbook:foo bar"` — whitespace (space) in slug
5. `"textbook:foo\n"` — trailing newline (`\Z` anchor bypass — the exact F3 landmine)
6. `"textbook::abc123"` — empty slug (violates `[a-z][a-z0-9-]{2,30}` min-length)
7. `"textbook:FOO"` — uppercase slug (policy: REJECT; `SLUG_RE` is lowercase-only)
8. `"textbook:fo"` — slug too short (min 3 chars per `SLUG_RE`: one start letter + 2)
9. `"textbook:a-valid-slug-but-with-UPPERCASE\Z"` — mixed case slug
10. Chunk-id form of #5: `"textbook:foo\n:abcdef0123456789"` — trailing newline before colon

All of these MUST return `True` from `is_valid_paper_id` (positive regression):
- `"textbook:foo-bar"` (3-char min slug: `f` + `oo`)
- `"textbook:shimura-varieties"` (realistic notebook slug)
- `"textbook:lnm-1337"` (alphanumeric slug)

And for `is_valid_chunk_id` + `paper_id_from_chunk_id` round-trip:
- `"textbook:shimura-varieties:abcdef0123456789"` → paper_id = `"textbook:shimura-varieties"`

---

## Failure-mode enumeration

1. **Byte-equality lock test breaks** (`test_chunker_pattern_equals_canonical`).
   Trigger: `PAPER_ID_RE.pattern` changes but `ingest/chunker.py:_PAPER_ID_RE.pattern`
   doesn't. Symptom: test fails with pattern mismatch. Mitigation: update all three
   copies (`chunker.py`, `validate_eval_fixtures.py`, `identifiers.py`) atomically.

2. **`paper_id_from_chunk_id` returns wrong group** for textbook chunk-ids.
   Trigger: `CHUNK_ID_PATTERN` restructured so `group(1)` is the arXiv paper_id only.
   Symptom: `paper_id_from_chunk_id("textbook:foo:abc...")` raises ValueError or
   returns wrong value. Mitigation: verify that `match.group(1)` captures the full
   `textbook:<slug>` prefix in the new regex; add a positive round-trip test.

3. **`server/graph_queries.py` breaks on textbook chunk-ids**.
   Trigger: `paper_id_from_chunk_id` called at `graph_queries.py:370` with a textbook
   chunk_id; Kùzu lookup for `textbook:foo` finds no rows (graph has arXiv nodes only).
   Symptom: silent empty result, not an exception. This is expected v1 behavior (textbook
   chunks are not in the citation graph); document as known gap, not a test failure.

4. **`CHUNK_ID_RE` `$`-vs-`\Z` not fixed, trailing-newline injection persists**.
   Trigger: implementer extends chunk-id pattern but doesn't fix the existing `$` anchor.
   Symptom: `is_valid_chunk_id("arxiv:2401.00001:abcdef0123456789\n")` returns True.
   Mitigation: the brief calls out this bug class explicitly; fix both `_PAPER_ID_FULL_PATTERN`
   (already `\Z`) and `CHUNK_ID_RE` (currently `$`).

5. **`ruff` lint failure from unguarded parenthetical regex string**.
   Trigger: multi-line raw string concatenation for `CHUNK_ID_PATTERN` without proper
   parentheses; `ruff` may flag line-length or string-concatenation issues.
   Mitigation: use `()` grouping for string literals; run `ruff check .` before commit.

6. **Old-style arXiv `hep-th/NNNNNNN` form silently broken by alternation order**.
   Trigger: textbook alternative placed BEFORE old-style arXiv in the alternation;
   `textbook:` partial-matches the start of `^[a-z]` branch. Python regex engine is
   left-to-right; the new branch must not shadow the existing ones for any valid input.
   Mitigation: add the textbook alternative as a third branch AFTER the two arXiv branches;
   validate `hep-th/9876543` still returns True in existing tests.

---

## Open questions

No open questions — implementation can proceed on the above recommendation.

The one non-obvious design call (slug regex) is resolved: reuse `SLUG_RE` inner pattern
`[a-z][a-z0-9-]{2,30}` verbatim. The three-copy sync strategy is resolved: update all
three copies. The `\Z`-vs-`$` fix for `CHUNK_ID_RE` is resolved: fix it. The
`paper_id_from_chunk_id` group-capture structure is resolved: make `group(1)` capture
the full paper_id form (`textbook:<slug>`) for the textbook branch.

---

## External writes the implementation will require

None — this milestone is purely local.

All changes are in `ingest/identifiers.py`, `ingest/chunker.py`,
`tools/validate_eval_fixtures.py`, and `tests/test_identifiers.py`. No git push,
no PR, no ticket, no infra mutation, no external API call.
