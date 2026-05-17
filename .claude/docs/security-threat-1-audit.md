# Threat-1 audit — paper_id / chunk_id path-traversal coverage

**Milestone:** E13_S01
**Threat:** Path traversal via `paper_id` / `chunk_id`
**Design note:** [`.claude/notes/08-security-observability-ops.md`](../notes/08-security-observability-ops.md) §Threat 1
**Test surface:** [`tests/security/test_path_traversal.py`](../../tests/security/test_path_traversal.py)
**Audit date:** 2026-05-17

---

## Threat statement

Quoted verbatim from
[`.claude/notes/08-security-observability-ops.md`](../notes/08-security-observability-ops.md):

> ### Threat 1: Path traversal via `paper_id`
>
> Tool arguments come from LLM output. An LLM that has been
> prompt-injected by something it read in an arXiv abstract could
> pass `paper_id="../../../etc/passwd"`.
>
> **Mitigation:** strict regex on every arxiv ID input.

## Canonical regex (source of truth)

The regex lives at [`ingest/identifiers.py`](../../ingest/identifiers.py)
(single source of truth — F11 close from E06_S03):

```python
_PAPER_ID_FULL_PATTERN = (
    r"^\d{4}\.\d{4,5}(v\d+)?$"  # new style: 2401.00001 or 2401.00001v3
    r"|"
    r"^[a-z][a-z\-]*/\d{7}(v\d+)?$"  # old style: hep-th/0001234
)

CHUNK_ID_PATTERN = rf"arxiv:({PAPER_ID_PATTERN}):[0-9a-f]{{16}}"
CHUNK_ID_RE = re.compile(rf"^{CHUNK_ID_PATTERN}$")
```

**Drift note.** Both the milestone brief and the design-note
prose carry a slightly incorrect old-style regex
(`^[a-z\-]+/\d{7}(v\d+)?$` — allows leading hyphen). The
canonical pattern (leading lowercase letter required) is in
`ingest/identifiers.py`. The note will be updated in a
follow-up note-grooming pass.

The misleading comment in `identifiers.py` mentions
`math.AG/0001234` as an example but the regex does NOT accept
dots in the archive prefix. The accepted form is `hep-th`-style
(letters + hyphens only). Production traffic uses new-style
(`YYMM.NNNNN`) almost exclusively.

## Tool surface (per `server/tools.py::ALL_TOOLS`)

The v1 surface is the seven tools below. Earlier brief drafts
referenced `paper_diff` and `dependency_graph` — those DO NOT
exist. Any tool added to the surface in the future MUST pass
this audit's test surface before merging.

| # | Tool | Identifier arg | Validation today | Test coverage | Status |
|---|---|---|---|---|---|
| 1 | `search_papers` | `filters` (dict; accepted-but-ignored) | none | — | KNOWN GAP (see §Known gaps) |
| 2 | `get_chunk` | `chunk_id` | in-body `is_valid_chunk_id` (chunk.py:39-43) | 6 cases | ✅ |
| 3 | `find_equation` | (none — `latex_or_mathml` is Threat 3 scope) | n/a | n/a | OUT OF SCOPE |
| 4 | `get_definitions` | `paper_id` | in-body `is_valid_paper_id` (definitions.py:73-78) | 3 cases | ✅ |
| 5 | `find_lemma_by_name` | `paper_id` (optional) | in-body `is_valid_paper_id` (lemma.py:68-71) | 3 cases | ✅ |
| 6 | `get_paper` | `paper_id` | in-body `is_valid_paper_id` (paper.py:37-40) | 3 cases | ✅ |
| 7 | `cite_neighbors` | `chunk_id` | **NEW** in-body `is_valid_chunk_id` (citations.py — added by E13_S01) | 6 cases | ✅ |

**Pre-E13_S01 state:** `cite_neighbors` accepted any `chunk_id`
and echoed it straight into the response envelope without
validation. The handler is a v1 stub but `server/graph_queries.py`
is real and will be wired soon; landing the guard now ensures
the future Kùzu-graph call cannot receive a malformed identifier.

## Adversarial input bank

Three inputs from the milestone brief, parametrized over every
identifier-accepting tool:

| Input | Threat class |
|---|---|
| `"../../../etc/passwd"` | Path traversal |
| `"; cat /etc/shadow #"` | Shell-injection-shaped |
| `"a" * 512` | Overlong (DoS / ReDoS proxy) |

Plus three `chunk_id`-shaped attacks (for `chunk_id` tools only):

| Input | Threat class |
|---|---|
| `"arxiv:../../etc/passwd:aaaaaaaaaaaaaaaa"` | Embedded path-traversal under valid prefix |
| `"arxiv:2401.00001:zzzzzzzzzzzzzzzz"` | Valid prefix, non-hex suffix |
| `"arxiv:2401.00001:" + "a"*15` | Valid prefix, short suffix |

These prove the chunk_id regex tightly composes the embedded
paper_id check + the suffix `[0-9a-f]{16}` lock.

**Total test cases:** 21 (9 paper_id × 3 inputs + 6 chunk_id ×
3 inputs + 6 chunk_id-shaped attacks).

## Accepted AC (synthesis D2; supersedes the brief's "-32602")

The milestone brief mandated `JSON-RPC -32602 Invalid Params`
on every adversarial input. **This is not achievable with the
mcp Python SDK today.** Both `jsonschema.ValidationError`
(low-level server) AND Pydantic `ValidationError` (FastMCP)
surface as `CallToolResult(isError=True)` — never -32602.
JSON-RPC -32602 is reserved for *unknown-tool* requests in the
SDK.

The MCP 2025-06-18 spec is ambiguous on which error encoding
applies to "Invalid arguments" — it lists the case under both
**Protocol Errors** (-32602 bucket) and **Tool Execution
Errors** (`isError:true` bucket). The spec leaves the choice
to the implementation. The strongest spec rule is
*"Servers MUST validate all tool inputs"* — which we do.

**Adopted AC** (verbatim for this audit):

> Every adversarial input produces a `ValueError` from the
> handler's in-body validator BEFORE the handler body reaches
> `chunks_table` / `theorem_names_db` / Kùzu / the filesystem.
> The SDK wraps the `ValueError` into
> `CallToolResult(isError=True)` for callers.

Migration to bespoke `McpError(ErrorData(code=INVALID_PARAMS))`
is a deferred Tier-6+ task — out of E13_S01 budget. See
§Migration plan below.

## Known gaps

### `search_papers.filters` (deferred — E07_S04 dependency)

Today the `filters` arg on `search_papers` is `dict[str, Any]`
and is **accepted but discarded** (the handler records a warning
under `filter_warnings`). A `paper_id`-shaped value inside
`filters` never reaches the filesystem in v1.

When E07_S04 wires real filter execution, the matching audit
extension MUST land in the same PR:

- Validate every nested `paper_id` value through
  `is_valid_paper_id` before any LanceDB query.
- Extend `tests/security/test_path_traversal.py` to cover the
  `search_papers(filters={"paper_id": <bad>})` path.

### `find_equation` — out of Threat-1 scope

The handler takes `latex_or_mathml` (a string that flows through
a separate MathML/LaTeX sanitization path — **Threat 3** in
note 08) and `k`. No paper_id, no chunk_id. The test surface
intentionally omits this handler from Threat-1 cases so a
future contributor doesn't mistakenly add it. **Likewise,
`find_lemma_by_name.name` is free text** (Pydantic
`Field(min_length=1, max_length=200)` only) and routes into the
theorem-names SQLite FTS5 store — argument validation there is
**Threat 2** (prompt-injection delimiter) scope, not Threat 1
(F7 from the E13_S01 critique).

### No JSON-Schema `pattern=` enforcement

Today the regex check is in-body. Adding
`Annotated[str, Field(pattern=PAPER_ID_PATTERN)]` to handler
signatures would:

1. Re-publish the `tools/list` JSON-Schema bytes (every
   `paper_id` arg gets `"pattern": "..."` in the rendered
   schema).
2. Trip `EXPECTED_TOOL_SCHEMA_SHA256` in
   `tests/test_server_tool_schema.py`.
3. Bump `TOOL_SCHEMA_VERSION` per CLAUDE.md §9 step 4.
4. Invalidate the BP1 prompt-cache for every existing agent
   prefix per
   [`.claude/notes/07-multi-agent-caching.md`](../notes/07-multi-agent-caching.md).

The Threat-1 mitigation is already achievable via in-body
validation. The migration's only marginal benefit is publishing
the regex to clients in the schema — desirable but not
load-bearing for the security goal. Deferred.

### No `max_length` Pydantic caps

Brief 2 §6 recommended `max_length=30` (paper_id) and
`max_length=64` (chunk_id) as belt-and-suspenders against
future regex loosening. The cost is the same byte-stability
re-pin as the schema migration above. Deferred to the same
future milestone.

The current regex is anchored (no unbounded backtracking) and
not ReDoS-vulnerable on the 512-char overlong test input — the
match completes in microseconds. The defense-in-depth case is
real but the cost is real too.

### Log redaction of malformed-identifier echo (Threat 8 coupling)

The validator error messages echo the malformed identifier
back via Python `{value!r}` formatting. `repr()` escapes
newlines and control characters but the full 512-character
overlong attack input ends up in the error stream verbatim
(stderr / SDK error wrap / journalctl). This is the inherited
pattern from the four pre-existing handlers' validators
(F8 from the E13_S01 critique).

Threat 8 (log redaction, E13_S08) will truncate / redact this
echo. The audit doc tracks the coupling so the matching change
in this audit's surface lands in the same PR as E13_S08.

## Migration plan (deferred)

A future security milestone (no ID assigned yet) should:

1. Add `max_length=30` (paper_id) and `max_length=64` (chunk_id)
   to every Pydantic Field accepting these identifiers.
2. Add `pattern=PAPER_ID_PATTERN` / `pattern=CHUNK_ID_PATTERN`
   imports from `ingest.identifiers` to the same Fields.
3. Run `pytest --update-tool-schema-hash` to re-pin
   `EXPECTED_TOOL_SCHEMA_SHA256`.
4. Bump `TOOL_SCHEMA_VERSION` from 6 → 7.
5. Document the BP1 cache invalidation in
   [`.claude/notes/07-multi-agent-caching.md`](../notes/07-multi-agent-caching.md).
6. Migrate the in-body raise from `ValueError` to
   `McpError(ErrorData(code=INVALID_PARAMS))` so the wire-level
   code becomes JSON-RPC -32602 (matching the brief's original
   wording).

Until that work lands, the in-body `ValueError` raise is the
security boundary and the SDK's `isError=True` wrap is the
callable contract.

### Follow-up tracking (F6 from the E13_S01 critique)

The four deferrals tracked from this audit:

| Deferral | Tracked at | Status |
|---|---|---|
| `search_papers.filters` paper_id validation | E07_S04 (when real filter execution lands) | filed |
| Pydantic `pattern=` migration | this audit's "Migration plan" above | needs roadmap entry |
| `max_length` caps | this audit's "Migration plan" above | needs roadmap entry |
| `McpError(INVALID_PARAMS)` wire-level wrap | this audit's "Migration plan" above | needs roadmap entry |
| Log-redaction of malformed-identifier echo | E13_S08 | filed |

The three "needs roadmap entry" deferrals are bundled into a
single future security-hardening milestone (tentatively
labelled `E13_SXX_hardening`); the bundle pays the
`EXPECTED_TOOL_SCHEMA_SHA256` re-pin cost once for all three.

## Defense-in-depth posture

Even after the JSON-Schema migration above lands, the in-body
`is_valid_*` calls should **stay**:

1. **Single source of truth.** `ingest/identifiers.py::PAPER_ID_RE`
   is the lock (F11 close from E06_S03). The Pydantic `pattern=`
   would duplicate the regex string into handler signatures;
   drift between the two is exactly the failure mode F11 was
   created to prevent.
2. **Belt-and-suspenders.** A future contributor turning off
   `validate_input` in the low-level server, or a refactor that
   drops the FastMCP Pydantic guard, shouldn't silently unguard
   the handler.
3. **Cost is negligible.** One regex match per request.

## Run the audit locally

```bash
uv run python -m pytest tests/security/ -v
```

The test surface runs as part of `make test`. No CI is wired in
this project (CLAUDE.md §4.1: "All work lands on main directly.
No CI / GitHub Actions blocking merges"); the local test suite
is the authority.

## See also

- [`.claude/notes/08-security-observability-ops.md`](../notes/08-security-observability-ops.md) — full threat model (9 threats)
- [`ingest/identifiers.py`](../../ingest/identifiers.py) — canonical regex
- [`tests/security/test_path_traversal.py`](../../tests/security/test_path_traversal.py) — the 21 test cases
- [`tests/test_identifiers.py`](../../tests/test_identifiers.py) — validator unit tests
