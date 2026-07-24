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
| `get_chunk` — `include_referenced` | retrieval-unlocks-m1 (#36) | `e5b4905` | staged |
| `search_papers` — `filters.include_kinds` | retrieval-unlocks-m2 (#37) | `11c70ab` | staged |
| `find_equation` — LaTeX on the TED lane | retrieval-unlocks-m4 (#39) | see git log for `_convert_latex_to_mathml` | staged |

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

---

## `search_papers.filters.include_kinds` — retrieval-unlocks-m2

Tracked by **#56** (`retrieval-unlocks-t-w1-schema-delta-search`).

m2's own brief calls this "a versioned, ungated opt-in **contract
event** in the W1 batch" — so the wire-visible half belongs here by the
milestone's own design, not merely by cache convenience.

### 1. `filters` argument description

`server/handlers/search.py`, the `filters` parameter. The current text
enumerates the supported keys; **add** `include_kinds` to that
enumeration with:

```
include_kinds: ['proof'] routes the search onto the proof-body
embedding column instead of the default statement column, making
proof text retrievable. The only supported value is ['proof'] --
every other kind is already served by the default route. Changes
retrieval_mode and excluded_kinds; see those fields.
```

### 2. Response-field semantics change (no new fields)

`retrieval_mode` and `excluded_kinds` already exist, but both were
hardcoded to the statement route's answer. They now vary:

| Route | `retrieval_mode` | `excluded_kinds` |
|---|---|---|
| default | `dense_only` (unchanged) | `["proof"]` (unchanged) |
| `include_kinds: ['proof']` | `dense_only_proof_column` | every non-proof kind |

`excluded_kinds` on the proof route is derived from
`ingest.store.ALLOWED_KINDS` minus `{"proof"}`, so a kind added to the
write-time enum cannot silently go unreported.

**This is the delta most likely to break a naive consumer**: anything
that pattern-matched `retrieval_mode == "dense_only"` to mean "a search
happened", or read `excluded_kinds == ["proof"]` as a constant, now sees
different values. That is the point — the old values were a lie on the
proof route — but it is a genuine contract change and belongs in the
release note for the W1 bump.

### 3. Error behaviour worth documenting

An unsupported `include_kinds` value raises a tool error rather than
falling back to the default route. A caller who asked for proofs and
silently received statements could not tell from the response, so the
failure is loud. Rejected: a bare string (`'proof'` rather than
`['proof']`), an empty list, any non-`proof` kind, wrong case, and
non-string members.

### 4. Agent-facing note for the tool-selection playbook

For `agent-platform-m4` (#73):

> To find how a result is *proved* rather than what is *stated*, pass
> `filters={'include_kinds': ['proof']}`. The two columns are disjoint —
> a default search can never return proof text, and a proof search can
> never return statements — so answering "what does this paper prove,
> and how" takes two calls. `get_chunk(include_referenced=True)` is the
> cheaper move when you already hold one side and want its counterpart.

---

## `find_equation` — LaTeX on the TED lane — retrieval-unlocks-m4

Tracked by **#61** (`retrieval-unlocks-t-w1-schema-delta-eq`).

### 0. FLIP THE DEFAULT — do this in the SAME commit as the description

The route ships **default-OFF** (`Config.eq_latex_route = False`). While
off, the current tool description below is TRUE (LaTeX does fall back to
dense-only), so there is nothing false on the wire yet. The W1 change
must therefore be atomic:

1. Set `Config.eq_latex_route = True` (default-on).
2. Apply the description edit in §1 (which only becomes true once the
   route is on).
3. Bump `TOOL_SCHEMA_VERSION` + re-pin the hashes.

Do NOT edit the description without flipping the default, or vice versa —
either half alone makes the description and the behaviour disagree. This
is the ordering the adversarial critique required (default-OFF keeps the
staged-but-unedited description honest until the atomic flip).

### 1. Tool description — will be false ONCE the route is default-on

`server/tools.py`, the `FIND_EQUATION` ToolMeta. The current text says:

```
LaTeX inputs fall back to dense-only ANN over the chunks table's
statement embeddings (retrieval_mode='dense_only_stmt_fallback')
because there is no query-time LaTeXML pool.
```

True while the route is off; both halves become wrong the moment §0
flips the default. **Replace (in that same commit) with:**

```
LaTeX inputs are converted to Presentation MathML at query time
(latex2mathml) and routed onto the same TED+dense fusion path, so
retrieval_mode reports ted_fused / ted_fused_eq. Because the corpus
trees were built by a different engine (LaTeXML, which expanded
paper-defined macros at ingest), the converted query matches
approximately; query_conversion records that a conversion was applied.
LaTeX that cannot be converted falls back to dense-only over statement
embeddings (retrieval_mode='dense_only_stmt_fallback') with
query_conversion.applied=false. Set ARXMCP_EQ_LATEX_ROUTE=false to
restore the pre-m4 dense-only behaviour for LaTeX.
```

### 2. New response field — `query_conversion`

Present **only** when a LaTeX→MathML conversion was attempted. Absent for
MathML input, when the route is disabled, and when no equations table
exists — absence means "no conversion was involved", which is distinct
from `applied: false` ("we tried and could not").

| Field | Type | Meaning |
|---|---|---|
| `query_conversion.applied` | bool | Whether the converted MathML was used for retrieval. |
| `query_conversion.converter` | string | Exact pin, e.g. `latex2mathml==3.81.0` — the tree shape feeds a distance metric, so the build is provenance. |
| `query_conversion.reason` | string | Only when `applied: false`: `unconvertible-latex` or `converter-output-not-mathml`. |

**No `tools/list` impact** — response shape is not part of the tool
schema hash. Only the description edit above forces the re-pin.

### 3. `retrieval_mode` vocabulary is UNCHANGED

Deliberately no new values. `ted_fused` / `ted_fused_eq` already name the
method that runs, and a failed conversion genuinely is dense-only over
statement embeddings. Retrieval METHOD and query PROVENANCE are two axes
(trust-language-policy §6 rule 1), so the conversion rides its own
namespaced field rather than multiplying the mode enum into
converted/not-converted variants.

One consequence worth the release note: **`dense_only_stmt_fallback` no
longer means "LaTeX is unsupported"** — it now means "this query did not
reach the TED lane", and `query_conversion` says why. A consumer that
treated that token as "LaTeX was ignored" should read the new field.

`malformed_mathml_fallback` keeps its narrow meaning — *caller-supplied*
MathML that failed to parse. A failed LaTeX conversion never emits it.

### 4. Agent-facing note for the tool-selection playbook

For `agent-platform-m4` (#73):

> `find_equation` now accepts LaTeX directly and searches the equation
> index with it — you no longer need to hand-write MathML to get
> structural matching. Check `query_conversion.applied`: when false, the
> results came from statement-embedding similarity rather than equation
> structure, so treat them as weaker. Matching is approximate for
> equations built on paper-defined macros, because the converter does
> not expand `\newcommand` the way the corpus ingest did.
