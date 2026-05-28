# ProofNet cross-reference contract (textbook-ingest-m8, OQ-2)

**Decision:** textbook chunks are cross-referenced to ProofNet entries
through the metadata fields the chunker **already** emits — no
`proofnet_id` column is added to `ChunkRecord` or the LanceDB chunks
schema. This satisfies the e3 outcome's *"ProofNet metadata schema
mapping preserved"* as a documented join contract at zero schema cost.

## What ProofNet is

ProofNet (Azerbayev et al., arXiv:2302.12433; HF dataset
`hoskinson-center/proofnet`) is an autoformalization benchmark of 371
undergraduate-mathematics theorems/exercises (185 validation, 186
test) drawn from standard textbooks. The project names it as a target
benchmark in `01-mission-and-context.md` (the sketcher→autoformalizer
pipeline's evaluation surface).

Each ProofNet entry has 5 fields:

| field | type | description |
|---|---|---|
| `id` | string | stable id, pattern `{TextbookName}\|{exercise_N_Ma}` |
| `nl_statement` | string | natural-language statement |
| `nl_proof` | string | natural-language proof (LaTeX) |
| `formal_statement` | string | Lean 3 formal statement |
| `src_header` | string | Lean imports/namespaces header |

Example ids: `Rudin|exercise_1_1a`, `Munkres|exercise_13_1`,
`Axler|exercise_1_3`, `Ireland-Rosen|exercise_1_27`. The `id` decomposes
into `(TextbookName, exercise-number)`.

## The join contract

A textbook chunk maps to a ProofNet entry by:

```
ProofNet.id = "{TextbookName}|{exercise_id}"
            ≈ (chunk.textbook_slug → TextbookName,
               chunk.theorem_label OR chunk.theorem_name → exercise_id)
```

The chunker already emits every field this join needs (no new field):

- **`textbook_slug`** — the notebook slug (e.g. `rudin-principles`);
  maps to ProofNet's `TextbookName` (`Rudin`) via an operator-maintained
  alias table (slugs are arXMCP-internal; ProofNet names are fixed).
- **`theorem_label`** — the LaTeXML `\label{}` key when present
  (e.g. `exercise_1_1a`); the highest-fidelity join key WHEN available.
- **`theorem_name`** — the parenthetical heading name
  (e.g. `Cauchy-Schwarz`); a fallback join key.
- **`chapter`** — disambiguates same-numbered exercises across chapters.
- **`kind="stmt"`** — restricts the join to theorem/exercise statements.

## ⚠️ Fidelity caveat — `theorem_label` is unreliable for PDF textbooks

**This is the load-bearing limitation a downstream ProofNet resolver
MUST account for.** For PDF-sourced textbooks (the m5/m6 path):

- Author `\label{exercise_1_1a}` keys are **not printed in the rendered
  PDF**, so MinerU never sees them.
- LaTeXML, run over MinerU's markdown, emits **auto-generated structural
  ids** (e.g. `S1.Thmtheorem1`), which `_extract_theorem_label`
  correctly classifies as auto-ids → `theorem_label = None`.
- Therefore, for PDF-sourced textbooks, `theorem_label` will USUALLY be
  `None` or an auto-id, NOT `exercise_1_1a`.

**Consequence:** automatic `theorem_label → exercise_id` matching is
best-effort and will frequently miss for the PDF path. A robust resolver
should:
1. Prefer `theorem_label` when it matches the ProofNet exercise-id shape.
2. Fall back to `(textbook_slug, chapter, theorem_name)` fuzzy matching.
3. Accept a manual annotation overlay (operator maps chunk-id →
   ProofNet-id) for the cases automation cannot resolve.

A future **`.tex`-source textbook ingest path** (separate epic; see
`.claude/docs/textbook-preamble-decision.md`) WOULD recover real author
`\label{}` keys, at which point `theorem_label` becomes a reliable join
key and a `proofnet_id` column could be added with real data behind it.
Adding the column now — permanently NULL from the chunker — would be
schema bloat that rotates the retrieval-cache `corpus_version` key for
zero data gain (m8 research-brief-2 FM-5).

## Why no schema column at m8

- `ChunkRecord` (`ingest/chunker_types.py`) already carries the 4 join
  fields. `ingest/schema.py::CHUNKS_SCHEMA_V1` needs no 22nd column.
- A `proofnet_id` column would be NULL for every chunk the chunker
  produces (no auto-population source), and adding it triggers
  `ingest/store.py::_migrate_chunks_schema_if_needed` → a corpus_version
  bump → retrieval-cache invalidation (`07-multi-agent-caching.md`
  Property 2) for no benefit.
- The documented contract above is the minimal artifact that satisfies
  "ProofNet metadata schema mapping preserved."

## Cross-references

- `ingest/chunker_types.py::ChunkRecord` — the join fields.
- `ingest/chunker.py::_extract_theorem_label` / `_extract_theorem_name`
  — how `theorem_label` / `theorem_name` are populated (auto-id → None).
- `.claude/docs/textbook-preamble-decision.md` — the sibling `.tex`-path
  deferral.
- ProofNet: arXiv:2302.12433; `github.com/zhangir-azerbayev/ProofNet`;
  HF `hoskinson-center/proofnet`.
- `.claude/notes/milestones/textbook-ingest-m8/research-synthesis.md` §OQ-2.
