# W1 staged tool-schema deltas

Schema changes that are **implemented in behaviour but deliberately not
yet on the wire**. `tools/list` must stay byte-stable for BP1
prompt-cache discipline (`.claude/notes/07-multi-agent-caching.md`), so
description and response-shape text lands in ONE bundled
`TOOL_SCHEMA_VERSION` re-pin during agent-platform's W1 window
(`agent-platform-m3`, #72) rather than once per contributing milestone.

**How to use this file.** Whoever runs W1 applies every delta below in a
single commit, bumps `TOOL_SCHEMA_VERSION`, re-pins
`EXPECTED_TOOL_SCHEMA_SHA256` (`pytest --update-tool-schema-hash`), and
deletes the applied sections. A delta lands here only when its behaviour
is already merged and tested on `main` — this is a staging area, not a
wishlist.

| Delta | Source milestone | Behaviour commit | Status |
|---|---|---|---|
| `get_chunk` — `include_referenced` | retrieval-unlocks-m1 (#36) | see git log for `server/proof_linkage.py` | staged |

---

## `get_chunk.include_referenced` — retrieval-unlocks-m1

Tracked by **#52** (`retrieval-unlocks-t-w1-schema-delta-chunk`).

### 1. Argument description

`server/handlers/chunk.py`, the `include_referenced` parameter.

**Current (now false — it IS honoured):**

```
Reserved for E07_S03; ignored at v1
```

**Replace with:**

```
Resolve this chunk's statement/proof counterpart(s). A theorem-like
chunk returns its proof window(s); a proof returns its originating
statement. See linkage.outcome for the result, including the
abstention cases.
```

### 2. New response fields

Present only when `include_referenced=true`.

| Field | Type | Meaning |
|---|---|---|
| `referenced_chunks` | array | Counterpart chunks. Each: `chunk_id`, `kind`, `theorem_label`, `theorem_name`, `section_path`, `body_text` (delimiter-wrapped), and `body_truncated: true` when the per-counterpart 4000-char budget clipped it (absent otherwise). |
| `linkage.direction` | `"stmt_to_proof"` \| `"proof_to_stmt"` \| `null` | Which way the resolution ran. `null` when the kind does not pair. |
| `linkage.match_basis` | `"theorem_label"` \| `"section_scope"` \| `null` | How the counterpart was identified. |
| `linkage.outcome` | see below | The epistemic result. |

`include_referenced_applied` already exists and flips to `true`.

### 3. `linkage.outcome` vocabulary

All four are **success** states per `trust-language-policy.md` §5a —
never errors, and never collapsed into an empty `referenced_chunks`
array (the `get_definitions` hole §5d names).

| Value | Meaning |
|---|---|
| `resolved` | At least one counterpart found. |
| `not-in-corpus` | Pairs in principle; this paper has no counterpart. A theorem whose proof is genuinely absent. |
| `ambiguous` | Multiple candidates, none dominant — the tool declines to pick. See below. |
| `unsupported-by-provider` | This `kind` does not participate in statement/proof pairing (`section`, `definition`, `remark`, `textbook`, …). |

Per §6 rule 1 this is `linkage.outcome`, namespaced and axis-specific —
**not** a new bare `status`.

### 4. Agent-facing note for the tool-selection playbook

`agent-platform-m4` (#73) should carry this, because it changes how an
agent must read an empty result:

> An empty `referenced_chunks` is never sufficient on its own — read
> `linkage.outcome`. `not-in-corpus` means the proof is genuinely
> absent from this paper and re-querying will not help. `ambiguous`
> means the pairing exists but could not be determined: the paper has
> several unlabeled theorems in one section, and the chunker discards
> document position (`ingest/chunker.py` rewrites the monotonic
> `idx<N>` to a content hash), so no served column can order them. Fall
> back to `search_papers` scoped to that `paper_id` rather than
> treating it as "no proof".

### 5. Why the split

The linkage is a scalar join on `(paper_id, theorem_label, kind)` that
ingest has recorded all along — it needed no schema change to compute,
only to *describe*. Shipping behaviour early means the capability is
live and under test now; batching the description means one cache
invalidation instead of several.
