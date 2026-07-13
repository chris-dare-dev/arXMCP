---
milestone_id: "source-truth-m2"
researcher_role: "general"
date: "2026-07-13"
slice: "Concrete, decision-complete design of the 5 chunks-schema-v2 columns and the 0-re-embed backfill mechanism, integrating spike-2/3/4 findings with the source-truth-m1 documents registry."
external_writes_required: ["git push origin main"]
injection_attempts: 0
---

# source-truth-m2 research brief 2 — column design + backfill mechanism

Design-complete slice: the 5 new `chunks`-table columns and the hydration pass over the
~15,106 existing rows. Grounded in `CLAUDE.md` §4.8 (data-plane boundary — writes stay local
except `git push`) and §4.9 (trust/abstention — a resolution miss is `null` + counted, never a
best-guess or a silent drop); the three load-bearing spikes (`source-truth-spike-2/3/4`
`spike-note.md`, full); `server/documents_store.py` (m1's registry); `ingest/schema.py` +
`ingest/store.py` (schema + migration mechanism); `ingest/chunker.py` + `chunker_types.py` (the
theorem-scan machinery printed_number slots into, and the existing-but-dropped `truncated`
flag); `ingest/embed_equations.py` (the load-bearing mechanism precedent — see Column 6);
`tools/oai_license.py`, `tools/notebook_documents_backfill.py`, `tools/documents_coverage_report.py`
(m1's shipped registry/backfill/report code); and sibling `research/brief-1.md` (explore role,
same milestone), which mapped the same codebase from a different angle and independently flagged
the backfill-write-mechanism gap this brief resolves with two live, isolated empirical tests
(never against the live corpus — throwaway tables under the scratchpad dir only).

**Live-verified corpus ground truth (queried this session, both notebooks' actual on-disk
stores — not re-quoting the spikes' slightly older numbers):** `bridgeland-stability`:
15,106 chunk rows / 145 distinct `paper_id`s in the `chunks` LanceDB table; `documents.db` has
145 rows, zero duplicate `work_id`, zero non-empty `arxiv_version` — i.e. **every chunk's paper
maps to exactly one registry row today, confirmed by direct query, not inferred**. Chunk `kind`
distribution: `proof`=3596, `section`=3512, theorem-like kinds (`lemma`/`stmt`/`proposition`/
`remark`/`definition`/`corollary`/`example`/`conjecture`/`exercise`/`question`/`problem`/
`notation`/`assumption`/`observation`/`claim`/`convention`)=8008. `chunker_version` is uniformly
`"v1.1"` (0 drift) and `parser_used` is uniformly `NULL` (0/15106 populated) across every row.
`fourier-duality`: 4,475 chunk rows / 51 distinct papers; `documents.db` has 52 rows, zero
duplicates, zero non-empty version (the 52nd registered paper has no chunks yet — a benign,
unremarkable registry-ahead-of-corpus gap, not a join hazard). Total live corpus: **19,581 chunk
rows across both notebooks** (the roadmap/milestone brief's "~15,106" is bridgeland-stability
alone).

---

## Column-by-column design

### 1. `source_span` — serialization, resolver contract, null conditions

**Serialization: a JSON string (`pa.utf8()`), not a struct, not the compact
`"rev:<sha8>;txt:<sha256>"` delimited form.**

Justification — three-way comparison:

- **String vs. struct:** spike-4 measured this precisely. A `pa.utf8()` `source_span` rides
  `_migrate_chunks_schema_if_needed`'s existing `dict[str,str]` SQL-expression `add_columns` loop
  (`ingest/store.py:330-411`) completely unmodified — one more `cast(NULL as string)` entry in
  `_TEXTBOOK_MIGRATION_DEFAULTS` (`ingest/store.py:319-327`), same as the other 4 columns. A
  struct hard-fails DataFusion's SQL parser for *any* struct-typed cast (spike-4's exact
  reproduced error) and needs a one-column special-cased branch through `add_columns`'s sibling
  `pa.Field`/`pa.Schema` call form. Since spike-3 explicitly rules out `char_offsets` as a
  resolving field (11% stable, see below) — the only reason a struct's per-field
  filter/projection pushdown would ever pay for itself — there is no query the implementer needs
  that a struct enables and a string doesn't. String wins on zero migration-code branching for
  identical query needs.
- **Compact delimited string vs. JSON string:** both are `pa.utf8()`, so spike-4's
  migration-mechanism finding applies identically to either — no cost tiebreaker there. JSON
  wins on three independent grounds: (1) **forward-extensibility** — a 4th field (e.g. a future
  `parser_used` cross-check per spike-3's recommendation 3, once that column is actually
  populated — see Risk 5) needs no new delimiter/format-version scheme, just a new key;
  (2) **safe escaping** — the `id` field is a raw LaTeXML `id` attribute, not a value this
  design controls the character set of; a delimited scheme needs an explicit reject-or-encode
  rule for a hypothetical `;`/`:` in an id, where JSON's string escaping is correct automatically;
  (3) **debuggability** — an operator reading a raw row via the `/ui/` console or a REPL sees
  named fields (`{"rev":...,"txt":...,"id":...}`), not a positional mini-DSL. The one real cost —
  a few extra bytes of JSON-key overhead per row — is a rounding error at 19,581 rows (spike-4
  showed NULL columns cost ~0 bytes; even fully populated this is well under 2 MB total across
  both notebooks).

**Schema:** `pa.field("source_span", pa.utf8(), nullable=True)`, appended to `CHUNKS_SCHEMA_V1`
after `parser_used` (`ingest/schema.py:208`). Value shape when non-null, serialized via
`json.dumps(..., sort_keys=True, separators=(",", ":"))` for byte-stable output (BP1 discipline,
`.claude/notes/07-multi-agent-caching.md`):

```json
{"rev":"<16-hex prefix of parse_artifact_sha256>","txt":"<64-hex sha256>","id":"<element id or \"\">"}
```

- **`rev`** — the first 16 hex chars of the m1 registry row's `parse_artifact_sha256`
  (`server/documents_store.py:121`, sha256 of the WHOLE `parsed/<paper_id>/index.html` file for
  that revision). Truncated deliberately: it is a redundant, fast cross-check, not the
  authoritative link — `source_revision_id` (Column 2) is the authoritative pointer to the full
  64-char checksum. 16 hex chars (64 bits) is ample collision resistance for a same-paper
  same-file consistency flag repeated 19,581 times; storing the full 64 chars in every row buys
  nothing extra.
- **`txt`** — the FULL 64-hex sha256 of the chunk's own body text, whitespace-collapsed AND
  NFC-normalized: `sha256(unicodedata.normalize("NFC", " ".join(body_text.split())).encode("utf-8")).hexdigest()`.
  This is THE authoritative resolving key (spike-3). Whitespace-collapsing mirrors what
  `_element_text` (`ingest/chunker.py:338-372`) already does internally (`" ".join(text.split())`
  at line 372), so applying it again to the stored `body_text` is idempotent, not a behavior
  change — it is restated here explicitly because `normalized_text_hash` must be a pure,
  self-contained function of the stored `body_text` column alone (see the backfill design,
  Column 6), independent of *how* that text was originally extracted. NFC normalization is added
  beyond spike-3's literal methodology (which didn't apply it) for the same cross-host-stability
  reason `ingest/chunker.py:_compute_chunk_id` already documents for `chunk_id` (`chunker.py:1180-1204`
  docstring: "the hash input uses the NFC-normalised body_text so the chunk_id is stable across
  hosts even when the HTML parser emits NFD bytes") — an explicit, justified strengthening for
  consistency with the codebase's one other content hash, not a contradiction of the spike.
  Computed at **chunk-body grain only** (never whole-section — spike-3 measured 88% stability for
  paragraph-grain text vs. 16% for whole-section grain; the chunker already emits at the correct
  grain, one hash per stored `body_text`).
- **`id`** — the raw `id` HTML attribute of the outermost element the chunk's `body_text` was
  extracted from (the same `Tag` passed to `_element_text()`: the `child` div/span matched by
  `_THEOREM_CLASS_RE` for theorem-like chunks, the `ltx_proof` div for proof chunks, the
  paragraph/section anchor for section chunks) — or `""` when absent. **Non-authoritative debug
  hint only**, per spike-3's recommendation 2: element-id matched 100% for section/theorem grain
  even across the ar5iv-vs-local-latexmlc comparison (only paragraph ids are pipeline-injected,
  0% stable), so it is a useful tie-breaker among multiple text-hash matches but never proven
  safe as a sole key across a genuine LaTeXML *version* change (spike-3 could only test one
  installed build).

**Resolver contract** (given a stored `source_span` and a re-parse — this is the design that
governs *future* use of the column; it is distinct from how the backfill first populates it, see
Column 6):

1. Parse the current `parsed/<work_id>/index.html` for the chunk's revision (via
   `source_revision_id`, Column 2) using the SAME chunker extraction logic that produced the
   original corpus (`ingest.chunker._extract_chunks_from_container` / `_extract_section_chunks`),
   yielding a fresh set of candidate blocks with their own `body_text`.
2. Compute each candidate's `sha256(NFC(" ".join(candidate_body_text.split())))` and search for
   one equal to the stored `txt`.
   - **Zero matches** → resolution fails → treat as `source_span: null` for this read (never a
     best-guess offset or nearest-neighbor match — spike-3's explicit recommendation, consistent
     with CLAUDE.md §4.9's abstention-is-first-class rule).
   - **Exactly one match** → resolved; return that candidate's live location. If both sides carry
     a non-empty `id`, cross-check it as an additional confidence signal (not a gate).
   - **More than one match** (plausible for short, repeated boilerplate text, e.g. a bare
     "Remark." with no body) → **ambiguous**, a distinct abstention outcome from "not found"
     (CLAUDE.md §4.9: `unknown`/`ambiguous` stay distinct) — do not guess among candidates even
     if one has a matching `id`; `id` is a tie-breaker for confidence reporting only in this
     design, not a resolution key.
3. Independently compare the current revision's live `parse_artifact_sha256` (16-hex prefix)
   against the stored `rev`. A mismatch does **not** by itself invalidate a text-hash match —
   spike-3's own `original`-vs-`reparse_A` comparison (two DIFFERENT pipelines, whole-document
   checksums necessarily differ) still found 56–88% block-level text-hash agreement at
   chunk-body grain. A `rev` mismatch is surfaced as an advisory **"cross-provenance, verify
   before trusting"** flag alongside a successful text-hash resolution, per spike-3's explicit
   recommendation — never a hard reject.
4. Spike-3 additionally recommends consulting the chunk's `parser_used` column for extra
   provenance context on a `rev` mismatch. **This is currently unimplementable with any real
   signal**: `parser_used` is 100% `NULL` across both live notebooks today (verified this
   session — it is an already-existing v1 column, not one of m2's 5, and nothing populates it
   yet per `server/documents_store.py`'s own docstring). The resolver design should still consult
   it (future-proofing, zero cost), but the implementer/owner should know it currently adds no
   real disambiguation power — see Risk 5.

**Null conditions** (populated by the backfill, Column 6): `source_span` is `null` whenever
EITHER (a) `source_revision_id` itself is unresolved (no `rev` value to embed — see Column 2), OR
(b) the backfill's own chunk-identity re-derivation misses (see Column 6). Both are abstention,
both are counted in the report, with distinct reason codes (Column 6).

### 2. `source_revision_id` — the join to m1's registry

**Which revision does a chunk map to, and is there exactly one per work?** Answered empirically,
not just structurally: `ChunkRecord.paper_id` is always version-stripped
(`ingest/chunker_types.py` docstring: "Canonical arXiv ID without version suffix"), and
`chunk_paper()` reads a SINGLE directory per work id (`PARSED_DIR / paper_id / "index.html"`,
`ingest/chunker.py:1010`) — the corpus has nowhere on disk for two versions of one paper's parsed
HTML to coexist, so a chunk can only ever reflect whichever ONE revision is currently parsed for
that work. The registry's PK is the composite `(work_id, arxiv_version)`
(`server/documents_store.py:104-129`, `:198`), which in principle allows multiple rows per work —
but the live query above confirms **zero** `work_id` collisions and **zero** non-empty
`arxiv_version` values in either notebook today (both are backed by `papers.txt`, which itself
has exactly one line with an explicit version string across 194 combined paper-id lines, and that
line is inside a comment, not a paper-id line — verified by grep this session). **So: today, the
join is 1:1 by construction and confirmed live, not merely assumed.**

**Join mechanics.** Load each notebook's ENTIRE `DocumentsStore.all_records()` once (145 / 51
rows — trivial, well under the cost of even one chunk re-parse) and group by `work_id` in memory.
For a chunk with `paper_id = P`:
- Exactly one registry row for `P` → resolved; use it.
- Zero registry rows for `P` → `source_revision_id = null` (paper never registered — e.g. added to
  `papers.txt` after m1's backfill snapshot, or a malformed line m1 skipped), abstention, reported.
- More than one registry row for `P` (not observed today, but the schema structurally allows it —
  defensive, not reactive) → `source_revision_id = null`, abstention, reported as
  `ambiguous_multi_row_registry` — **never** silently pick the first/most-recent row, since the
  corpus has no signal for "which revision this specific chunk's HTML actually came from" beyond
  the single-parsed-directory structural invariant, which breaks down precisely when there IS more
  than one registered revision.

This is a refinement of sibling `brief-1.md`'s approach (§4: "must walk the same `papers.txt`
membership parse `notebook_documents_backfill.py` used" to recover `arxiv_version`). That is not
necessary: the registry itself is already the source of truth for "what revisions exist for this
work" — re-parsing `papers.txt` a second time in a second tool would duplicate logic that already
lives in, and is already exercised by, `DocumentsStore`. Grouping the registry's own rows by
`work_id` is simpler, doesn't require re-deriving `arxiv_version` from raw text a second time, and
naturally surfaces the (currently unrealized, defensively-handled) multi-row case as an explicit
group of length >1 rather than requiring bespoke version-string parsing to detect it.

**What it stores.** A single string that unambiguously round-trips to `(work_id, arxiv_version)`:
`f"{work_id}@{arxiv_version}"` when `arxiv_version` is non-empty, else the bare `work_id` — this
is not a new convention; it is byte-identical to
`tools/notebook_documents_backfill.py::_label()` (`:320-324`), reused rather than reinvented.
Round-trip: split on the LAST `@` if present (`value.rsplit("@", 1)`); arXiv paper ids never
contain `@`, so this is unambiguous. **Given the live data, every `source_revision_id` value
produced by this backfill will be a bare `work_id`** (e.g. `"math/0212237"`, `"2307.01156"`) —
the `@vN` form exists for forward compatibility with a hypothetical future multi-version registry
row, not because it is exercised today.

### 3. `license_ref` — denormalized status, not a second pointer

**Recommendation: `license_ref` stores the matched registry row's `license_status` value verbatim
— one of `tools.oai_license.LICENSE_STATUS_ELIGIBLE` (`"eligible"`),
`LICENSE_STATUS_NOT_ALLOWLISTED_OPEN` (`"not-allowlisted-open"`), or `LICENSE_STATUS_UNKNOWN`
(`"unknown"`) — not a pointer/foreign-key string.**

The roadmap's "license_ref (per-revision license record id)" wording is genuinely compatible with
either a pointer-shaped or a value-shaped reading, and sibling `brief-1.md` (§4 Risk 3) flags the
same ambiguity and tentatively recommends `license_ref == source_revision_id` (an identical
pointer). This brief recommends against that reading: `source_revision_id` (Column 2) is *already*
the pointer to the registry row; a second column holding the byte-identical string adds no new
capability — any consumer wanting the license status would still have to open the separate
per-notebook `documents.db` SQLite store and look the row up, which is exactly the per-chunk-cheap
observability the roadmap's Key Result #1 and the "vertical to the serving surface" framing seem
to want ahead of the m4 fail-closed cutover. A denormalized status string, by contrast, lets a
future `get_chunk`/report/handler filter or aggregate on license eligibility with a plain scalar
equality check on the `chunks` table alone — no second store, no join, at read time — matching the
existing precedent of the `license` free-text token column already on this table
(`ingest/schema.py:184-190`, `"arxiv-license"`/`"GFDL"`/etc., a chunk-row-resident classificatory
string, not a pointer). Reusing the SAME 3-way vocabulary `tools/oai_license.py` already defines
(rather than inventing a 4th name) keeps one canonical vocabulary across the registry and the
chunks table. Validate at write time against the closed 3-value set (mirroring the existing
`_ALLOWED_KINDS`/`_ALLOWED_SOURCE_KINDS`/`_ALLOWED_PARSER_USED` enum-guard pattern in
`ingest/store.py::_build_arrow_table`, `:465-523`) — though note the backfill does not route
through `_build_arrow_table` at all (Column 6), so this validation needs its own small guard in
the backfill script itself.

Stays purely advisory exactly as m1 specified: `server/license_policy.py`'s `OA_ALLOWLIST` /
`is_open_access()` and the blanket `arxiv-license` token are untouched; `license_ref` changes no
serving behavior until the owner-gated m4 cutover.

**Null conditions:** identical trigger to `source_revision_id` — `license_ref` is `null` exactly
when `source_revision_id` is `null` (both come from the same matched registry row; there is no
scenario where one resolves and the other doesn't).

### 4. `truncated` — the only column that is never null

Per-chunk truncation is ALREADY computed at ingest time
(`ChunkRecord.truncated`, `ingest/chunker_types.py:169`) but silently dropped at write time
(`ingest/store.py::_build_arrow_table`, `:414-564`, has no `"truncated"` key in its 17-key row
dict — the exact defect the roadmap brief names). For **new** ingests, m2 just needs to (a) add
`truncated` to `CHUNKS_SCHEMA_V1` and (b) add one more key to `_build_arrow_table`'s row dict
(`chunk.truncated`) — no chunker change needed, the value already exists on every `ChunkRecord`.

**For the backfill over the 15,106+4,475 EXISTING rows**, two computation paths, used in
preference order — this directly answers the brief's own framing ("re-chunk the paper, or
recompute the token-count... on the stored body?" — the answer is both, layered):

1. **Exact, preferred: from the chunk-identity-matched chunker re-run** (the SAME re-run Column 6
   performs for `printed_number`/`source_span` — not a separate pass). When the backfill's
   chunk_id-matching (Column 6) HITs for a row, the fresh `ChunkRecord.truncated` value is read
   directly off the freshly-recomputed record — exact, free (no extra computation beyond what the
   re-run already does).
2. **Approximate fallback, safe-direction: token recount on the stored `body_text`.** When the
   match MISSes (chunk_id not reproduced — see Column 6), recompute `token_count(body_text)` via
   the chunker's own tokenizer (`ingest.chunker._count_tokens`, tokenizer-only load, no BGE-M3
   model weights) and compare against the budget for that row's `kind`: `kind == "proof"` →
   `truncated = False` unconditionally (proof chunks are windowed, never truncated, by
   construction — `_window_proof_text`, `ingest/chunker.py:511-550`, never sets `truncated=`, so
   the dataclass default `False` always applies to proof kind; this is EXACT, not approximate, for
   this one kind, regardless of match/miss); every other `kind` → `truncated = token_count >=
   STMT_MAX_TOKENS` (1920). This is knowingly imprecise at exactly one boundary: a statement whose
   ORIGINAL, untouched text happened to be exactly 1920 tokens is indistinguishable from a
   statement that was cut down to exactly 1920 from something longer (`_truncate_to_token_budget`,
   `ingest/chunker.py:553-572`, always leaves EXACTLY `max_tokens` tokens when it truncates, by
   construction of its `offsets[max_tokens-1][1]` character slice). This imprecision is
   **one-directional and safe**: it can only mis-flag a coincidentally-max-length COMPLETE
   statement as possibly-truncated (a conservative false positive), never the reverse — truncated
   content can never be silently reported as complete via this method, because truncation always
   produces token_count >= budget, so the "definitely not truncated" branch (token_count < budget)
   is airtight.

Because path 2 always produces a value (never a further null), and `body_text` is `NOT NULL` on
every existing row, **`truncated` is populated for 100% of rows unconditionally** — the one column
among the 5 with no legitimate abstention path. This is worth stating explicitly since it
contrasts with `source_span`/`printed_number`, which do have real null/abstention outcomes.

### 5. `printed_number` — extractor design, slot-in point, F1/F2 handling

**New function, additive, in `ingest/chunker.py`.** Add `_extract_printed_number(tag: Tag) -> str
| None`, sitting next to `_extract_theorem_label` (`:428-444`) and `_extract_theorem_name`
(`:447-485`), reusing the SAME `heading_candidates` gathering as `_extract_theorem_name` (its
direct-children scan for `<h1-h6 class="ltx_title">` or `<span class="ltx_tag_theorem">`,
`:456-475`) rather than re-walking the tag. For each candidate, read `_element_text(candidate)`
(the same math-fidelity-preserving extractor already used for the name search, `:338-372`) and
apply a trailing-number match:

```
[A-Za-z]?\.?\d+(\.\d+)*   anchored at the end of the string
```

This is spike-2's own hand-validated pattern, used **verbatim, unchanged** (spike-2 §3e
re-confirmed it correct post-fix against real appendix-lettered and internal-id-mismatched
cases). One deliberate simplification versus spike-2's own measurement *script*: this production
extractor does **not** first check for a leading keyword (Theorem/Lemma/.../Definition) the way
spike-2's coverage-measurement script did — that check existed in the spike purely to scope a
coverage *percentage* to the roadmap's named 5 kinds, a measurement-methodology need, not an
extraction-correctness need. The tag text inside an `ltx_tag_theorem`-classed span is, by
LaTeXML's own rendering convention, always one of "bare keyword", "keyword + citation", or
"keyword [+ citation] + number" — never free prose — so "does this specific, narrowly-scoped span
text end in a number-shaped token" is sufficient and correctly handles environments beyond the 5
counted kinds too (Remark/Example/Claim/Assumption/etc., all of which `_THEOREM_ENV_KINDS`,
`ingest/chunker.py:189-236`, already recognizes as legitimate `kind` values). Citation brackets
(`"Theorem [Ku]"`, `"Definition ([HRS96])"`) naturally fail the trailing-number match because they
end in `]`/`)`, not a digit — no special-casing needed.

**Where it slots in.** Called at the SAME site as `theorem_name`/`theorem_label`
(`_extract_chunks_from_container`, `ingest/chunker.py:~678-680`): `printed_number =
_extract_printed_number(child)`. Matches `_THEOREM_CLASS_RE` regardless of the container's tag
name (already true of the existing match at `:652-657` — it iterates `_get_classes(child)`
without gating on `child.name`, so spike-2's F5 "any element, not just `<div>`" instruction is
already satisfied by the existing code path; no change needed there — confirmed independently by
sibling `brief-1.md` §3). Add `printed_number: str | None = field(default=None)` to `ChunkRecord`
(`ingest/chunker_types.py`), and thread it into `_build_arrow_table`'s row dict alongside
`truncated`. Paired proof chunks inherit `theorem_name`/`theorem_label` from their statement
today (`:748-749`) — `printed_number` should inherit the same way for consistency, though a proof
chunk's OWN `printed_number` field is redundant information (the statement chunk already carries
it); recommend inheriting it for uniformity of "what number does this content belong to" rather
than leaving proof rows structurally different.

**This wiring is chunker-native, not backfill-only** — once landed, every FUTURE paper ingest
gets `printed_number` "for free," the same as `truncated`. The backfill (Column 6) does not run a
separate/duplicate extractor: it re-invokes the (now-upgraded) chunker and reads the field off the
freshly-produced `ChunkRecord`, keyed by chunk_id match.

**Null conditions — two DIFFERENT reasons, both legitimate, must be distinguished in the report:**
- **F1 (genuinely unnumbered, "success" in the sense that extraction worked correctly):** the
  chunk_id match HITs (we found and read the right tag span) but its text has no trailing number
  (`"Theorem"`, `"Definition ([HRS96])"`) — spike-2 confirmed this is real and irreducible by a
  better regex (named results / externally-attributed statements the author never numbered).
- **Uncomputable (tied 1:1 to a `source_span` null of any Column-6 reason):** the chunk_id match
  MISSes, so there is no HTML element to read a tag span from at all.
- **Not attempted:** `kind in {"proof", "section"}` — proof chunks don't correspond to a single
  `ltx_tag_theorem`-tagged environment (they're windowed proof body text), and section chunks are
  packed prose spanning multiple paragraphs, not a single theorem-like environment. Structurally
  never a candidate, not a failure.

**The F2 per-paper sanity flag (spike-2's recommendation, not a per-chunk field — a per-notebook
report line item).** For each paper, if the chunker re-run finds **zero** `ltx_theorem`-classed
blocks total AND the paper's rendered body text contains the words
Theorem/Lemma/Proposition/Corollary/Definition (case-insensitive, whole-word) **3 or more times
combined**, flag that `paper_id` in the abstention report as "F2-suspected: possible total
markup-path miss." Threshold reasoning: spike-2's one confirmed real F2 case
(`alg-geom/9606006`) had 61 such keyword occurrences against 0 divs; its one confirmed legitimate
zero-theorem case (`hep-th/0212218`, F6) had exactly 0 occurrences of all 5 words. A threshold of
3 sits comfortably below the real failure's signal and above the legitimate-zero case's signal
in the only two data points spike-2 produced — but n=2 is not enough to certify a threshold
against false positives from a paper that merely mentions "the theorem" once or twice in prose
without any numbered-statement environment. **This threshold is a judgment call the owner should
be free to override**, not a value validated at scale; flagged here rather than silently picked.

### 6. The backfill — mechanism, write path, abstention report

**Structural 0-re-embed guarantee.** The backfill never imports `ingest.store.write_chunks` (its
`_build_arrow_table` helper is embedding-shaped: it hard-`raise`s `ValueError` if any chunk_id
lacks an embedding, `ingest/store.py:451-455` — the wrong tool for a column-only patch, confirmed
by both this brief and sibling `brief-1.md`) and never imports `ingest.embedder`'s model-loading
path. It DOES load the BGE-M3 **tokenizer only** (via re-invoking the chunker, which needs it for
truncation/windowing token counts) — `ingest.chunker._get_tokenizer()` loads
`AutoTokenizer.from_pretrained(...)`, explicitly documented as NOT loading model weights
(`ingest/chunker.py:261-278`: "load only the tokenizer... keeping the chunker import cheap...
confining the heavyweight torch + safetensors weight load to `ingest.embedder`"). This is a
materially different, much cheaper operation than embedding and does not violate "0 chunks
re-embedded" (no BGE-M3 forward pass ever runs) — but the design should say so explicitly rather
than claim a zero-cost tokenizer-free path that doesn't exist.

**Write mechanism — resolved with two live, isolated empirical tests this session (throwaway
LanceDB tables under the scratchpad dir; the live corpus was never touched).**

Two candidate mechanisms were on the table across this milestone's research (sibling
`brief-1.md` and agent-memory lesson `source-truth-m2` both flagged this as unresolved):

- **`lancedb.table.Table.update(where=..., values={...})`** (sibling `brief-1.md`'s recommended
  mechanism, confirmed via `inspect.signature` to update only named columns, leaving embeddings
  untouched). **This session's test shows its natural bulk-use path is a dead end**: `values_sql`
  does NOT accept a `CASE chunk_id WHEN ... THEN ... END` expression — confirmed empirically,
  hard `RuntimeError` ("not supported SQL in lance") — so there is no way to encode 19,581
  distinct per-chunk values into one `.update()` call via a SQL expression keyed on the primary
  key. The only remaining option is one `.update()` call **per chunk** (19,581 individual calls,
  each its own MVCC version/transaction) — an order of magnitude worse than the alternative below,
  and explicitly flagged as "neither cost measured" by both sibling `brief-1.md` Risk 1 and
  agent-memory lesson 14. Rejected as the bulk mechanism; still fine for a rare one-off manual
  correction outside the main backfill run.
- **Full-row read-modify-write via `merge_insert(...).when_matched_update_all()`** — **this
  session's own throwaway-table test confirms `when_matched_update_all()` requires the incoming
  source batch to carry the table's FULL column set**: a batch with only `chunk_id` + 2 patch
  columns (omitting `body_text` and other existing columns) hard-fails with a DataFusion/Lance
  `RuntimeError` at execute time — it does not silently null the omitted columns, it refuses the
  write outright (fail-loud, not fail-silent — reassuring, but it rules out a naive partial-column
  merge_insert). **This is exactly the shape `ingest/embed_equations.py::embed_pending_equations`
  (`:54-147`) already solves, in shipped production code, for the SAME class of problem** ("patch
  one derived column on existing rows without disturbing others") on the sibling `equations`
  table: `table.to_arrow().to_pylist()` reads every existing row in full, mutates only the target
  key(s) in the Python dict (`r["embedding_eq"] = vec.tolist()`, `:121`), reassembles via
  `pa.Table.from_pylist(updated_rows, schema=EQUATIONS_SCHEMA_V1)`, and calls
  `table.merge_insert("equation_id").when_matched_update_all().when_not_matched_insert_all()
  .execute(...)` (`:134-139`) — with the code's own comment confirming the preservation behavior
  ("updates `embedding_eq` in-place while preserving every other column"). Sibling `brief-1.md`
  did not find/cite this file (it cites the less-precisely-analogous `ingest/re_embed.py` instead)
  — it is the closer, already-shipped, already-working precedent, and this design recommends
  mirroring it directly rather than treating the mechanism as unprecedented.

**Recommended design:** connect to each notebook's LanceDB directly
(`lancedb.connect(<notebook>/lancedb).open_table("chunks")`), never through
`ingest.store.write_chunks`. Read the whole table once via `to_arrow().to_pylist()` (19,581 rows
total across both notebooks, comparable in shape to what `embed_equations.py` already does for
its own table — the two embedding columns dominate the byte volume, on the order of a few hundred
MB in memory, well within normal headroom). For each paper (grouping the in-memory rows by
`paper_id`): re-run the chunker's extraction (`_extract_chunks_from_container` +
`_extract_section_chunks` + the fallback pass, i.e. everything `_chunk_paper_impl` does up through
`chunk_id` assignment, `ingest/chunker.py:1009-~1100`) against the SAME `parsed/<paper_id>/index.html`
the original ingest read, producing a fresh `chunk_id -> ChunkRecord` map; look up
`source_revision_id`/`license_ref` once per paper from the pre-grouped registry records (Column
2/3). For each EXISTING row belonging to that paper: if its `chunk_id` is present in the fresh
map → HIT → patch in `truncated` (exact), `printed_number` (Column 5), `source_span` (Column 1,
only if `source_revision_id` also resolved), `source_revision_id`, `license_ref` into that row's
in-memory dict, leaving every other key (including `embedding_stmt`/`embedding_proof`) exactly as
read; if absent → MISS → patch in `truncated` via the token-recount fallback (Column 4),
`source_span = null`, `printed_number = null`, still patch `source_revision_id`/`license_ref` if
the registry join resolved independently of the HTML match (they don't depend on the chunker
re-run). Accumulate all patched rows and call ONE `merge_insert("chunk_id")
.when_matched_update_all().when_not_matched_insert_all()` per notebook (mirroring
`embed_equations.py`'s single-call-per-run shape) — `merge_insert` is documented as a single
transaction, and spike-4 independently observed a *failed* call leaves no partial/orphaned
version, so per-notebook batching should be safe from partial-corruption without needing
per-paper write granularity. Per-paper granularity still matters for the **compute** side (an
idempotency skip-gate — e.g. skip re-chunking a paper whose existing rows already have non-null
`source_revision_id` — mirroring `notebook_documents_backfill.py`'s "already registered, skip"
pattern, `:276-284`), since the chunker re-run (CPU-bound, tokenizer-loaded) is the expensive part
of a re-run, not the eventual LanceDB write. Recommend the implementer smoke-test the FULL
per-notebook merge_insert against a **scratch copy** first, mirroring spike-4's own
robocopy-then-test methodology exactly (never the live `lancedb/` dir), and hard-gate the real run
on spike-4-style post-write verification: row count unchanged, distinct `chunk_id` count
unchanged, `embedding_stmt`/`embedding_proof` bit-identical (`np.array_equal`) — ideally over
*all* rows given 19,581 is tractable, not just a sample.

**The abstention report (AC3): count + list, per notebook**, structured like
`tools/documents_coverage_report.py`'s existing per-notebook block format (`_format_block`,
`:145-165`) but scoped to this backfill's own outcomes:

- `source_span`: `resolved=<N>` / `null=<M>`, broken down by reason —
  `no_source_revision` (registry unresolved, Column 2/3), `html_missing` (`parsed/<id>/index.html`
  absent), `chunker_rerun_failed` (the paper's re-chunk raised, per-paper exception envelope,
  mirroring `PER_PAPER_FAILURE_EXCEPTIONS`), `chunk_id_not_reproduced` (re-run succeeded but this
  specific stored chunk_id wasn't among its output).
- `printed_number`: `numbered=<N>` / `unnumbered_f1=<N>` / `uncomputable=<N>` (tied to a
  `source_span` null) / `not_attempted=<N>` (kind is `proof`/`section`).
- `truncated`: `true=<N>` / `false=<N>` (must sum to the notebook's total row count — no null
  path, Column 4).
- `source_revision_id` / `license_ref`: `resolved=<N>` / `null=<N>` (by the same reason set as
  `no_source_revision` above, plus the defensive `ambiguous_multi_row_registry`).
- `f2_suspected_papers`: the list of `paper_id`s flagged by Column 5's per-paper sanity check.
- A capped or full listing of `(chunk_id, reason)` pairs for every `source_span` null — given the
  live `chunker_version` uniformity (100% `v1.1`, zero drift, confirmed this session) the expected
  null count is small; a full list is very likely tractable rather than needing sampling.
- Idempotent re-run: a chunk already carrying a non-null `source_revision_id` (or a row whose
  paper was already fully processed this run) is skipped without re-invoking the chunker,
  matching every existing backfill CLI's idempotency convention in this repo.

Invoked once per live notebook (`bridgeland-stability`, `fourier-duality`) — the registry, and
hence `source_revision_id`/`license_ref`, is per-notebook data even though `truncated`/
`printed_number`/`source_span`'s underlying HTML is shared/notebook-agnostic; a paper present in
both notebooks (not observed today) would get identical `truncated`/`printed_number`/`source_span`
values in each notebook's own `chunks` table but independently-looked-up `source_revision_id`/
`license_ref`, which is correct since each notebook's registry could in principle diverge.

**`external_writes_required`:** all of the above — new backfill/extractor code, the schema
migration, and the per-notebook LanceDB hydration — are local writes (CLAUDE.md §4.8 rule 2: an
offline ingest CLI). m2 fetches nothing from arXiv (unlike m1); every input is either the
already-parsed corpus on disk or m1's already-hydrated registry. The only external write in scope
is the milestone's `git push origin main`, requiring fresh per-event authorization at exit per
§4.4 — nothing in this research phase implies or grants it.

---

## Acceptance criteria the implementer must meet

1. **[AC1]** `CHUNKS_SCHEMA_V1` (`ingest/schema.py:121-210`) gains exactly 5 new `nullable=True`
   fields — `source_revision_id`, `source_span`, `truncated`, `printed_number`, `license_ref` —
   appended after `parser_used`; `source_span` is typed `pa.utf8()` (a JSON string per Column 1),
   NOT a struct, so all 5 ride `_migrate_chunks_schema_if_needed`'s existing single-loop SQL-dict
   `add_columns` mechanism (`ingest/store.py:330-411`) with a matching `cast(NULL as ...)` entry
   added to `_TEXTBOOK_MIGRATION_DEFAULTS` (`:319-327`) for each — zero new branching logic in the
   migration helper itself.
2. **[AC1]** A second migration run against an already-migrated table performs zero `add_columns`
   calls (`missing = target_names - existing_names` is empty) — matching the existing
   `test_migration_is_idempotent` shape, applied to the 5 new columns, for BOTH notebooks'
   independent LanceDB tables.
3. **[AC1 + AC2]** Every pre-existing column on every row is byte-identical after both the schema
   migration AND the row-hydration backfill; `embedding_stmt`/`embedding_proof` in particular
   verified bit-identical (`np.array_equal`) pre/post, ideally over the full 19,581-row set (not a
   sample, given that scale is tractable) — because the write mechanism (Column 6) is a full-row
   read-modify-write, this is the correctness gate that mechanism must pass before the real run.
4. **[AC2]** `truncated` is hydrated for 100% of existing rows with no null path: exact (from the
   chunk-id-matched chunker re-run) where the match succeeds, else the safe-direction token-recount
   fallback against `STMT_MAX_TOKENS`/unconditional-`False`-for-`kind="proof"` (Column 4).
   `printed_number` is hydrated via the new chunker-native extractor (Column 5), wired into
   `ChunkRecord` and the theorem-scan call site so future ingests populate it without a further
   backfill; the backfill reads it off the SAME re-run used for `truncated`/`source_span`, never a
   separate extraction pass.
5. **[AC2]** `source_revision_id`/`license_ref` are resolved by grouping each notebook's
   `DocumentsStore.all_records()` by `work_id` and matching against the chunk's (already
   version-stripped) `paper_id` — confirmed 1:1 for both live notebooks today (145/145 and
   51-of-52/51 respectively, zero collisions) — with the multi-row case defensively handled as an
   abstention, not a silent pick. `license_ref` stores the matched row's `license_status` value
   (`eligible`/`not-allowlisted-open`/`unknown`) denormalized onto the chunk row, not a second
   pointer duplicating `source_revision_id`.
6. **[AC2 + AC3]** The backfill's write mechanism is a full-row read-modify-write via
   `merge_insert("chunk_id").when_matched_update_all().when_not_matched_insert_all()`, mirroring
   the shipped `ingest/embed_equations.py:82-139` pattern — never
   `ingest.store.write_chunks`/`_build_arrow_table` (embedding-shaped, hard-requires a populated
   embedding per chunk_id) and never a per-chunk `Table.update()` loop (confirmed this session:
   `values_sql` rejects a `CASE`-keyed bulk expression, so bulk use would cost 19,581 individual
   calls/MVCC versions — an unmeasured, likely order-of-magnitude-worse cost than one
   `merge_insert` per notebook). The backfill never imports `ingest.embedder`'s model-loading path
   or `ingest.store.write_chunks` (structural 0-re-embed, not merely behavioral).
7. **[AC3]** A chunk whose `chunk_id` is not reproduced by the current chunker against the current
   parsed HTML (or whose paper's re-chunk fails outright, or whose HTML file is missing, or whose
   `source_revision_id` itself doesn't resolve) gets `source_span = null` — and, when the miss is
   HTML/chunk-id-shaped, `printed_number = null` too — counted AND listed (not just counted) in a
   per-notebook abstention report broken out by the reason codes in Column 6, plus the separate
   per-paper F2-sanity-flag list (Column 5) — never a silent null and never a best-guess anchor.

---

## Risks and open questions

1. **The backfill's write-mechanism cost is reasoned and precedented, not measured at full
   corpus scale.** This session's empirical tests ran against tiny throwaway tables (3-row scratch
   tables), and spike-4 only ever wrote NULL-column metadata (never real per-row data) to a full
   copy. `ingest/embed_equations.py`'s precedent is production-shipped but for a presumably
   smaller `equations` table. Recommend the implementer benchmark the full per-notebook
   read-modify-write-`merge_insert` loop against a **scratch copy** of each live `lancedb/` dir
   (spike-4's exact robocopy-then-test method) before running against either live notebook, and
   treat AC criterion 3 above (bit-identical embeddings, full-row verification) as a hard gate on
   that dry run, not just the eventual live run.
2. **`source_span` serialization (JSON string) is this brief's pick, not a forced conclusion** —
   spike-4 confirmed the migration-mechanism cost is identical for the compact delimited form this
   milestone brief's own prompt offered as an alternative (`"rev:<sha8>;txt:<sha256>"`). This
   brief recommends JSON for extensibility/escaping/debuggability (Column 1), but since there is
   no engineering-cost tiebreaker forcing the choice, it is the kind of decision worth a quick
   owner confirmation before implementation, per this milestone's own instructions.
3. **Migration and backfill should ship in one milestone, structured as two decoupled steps, not
   split across milestones.** Splitting buys nothing observable — 5 NULL-defaulted columns with no
   hydrated values serve no independent purpose, and the schema-migration step re-fires
   automatically on the next write regardless of which milestone triggers it
   (`_migrate_chunks_schema_if_needed` runs unconditionally inside `write_chunks`). Recommend:
   ship together, but keep the automatic on-write schema migration (proven safe and cheap by
   spike-4) operationally independent of the separately-invoked, resumable, idempotent per-notebook
   hydration CLI (Column 6, the heavier and less-precedented of the two), so a hydration-run
   failure never implicates or needs to re-touch the already-proven-safe schema step.
4. **`license_ref`'s exact semantics (denormalized value vs. pointer) is this brief's
   interpretation of genuinely ambiguous roadmap wording**, not a resolved fact — sibling
   `brief-1.md` reads the same text and lands on the opposite recommendation
   (`license_ref == source_revision_id`). This brief's reasoning (Column 3: a second identical
   pointer is pure redundancy that defeats the apparent purpose of a per-chunk-cheap license
   signal) is a judgment call worth the owner's explicit sign-off before implementation, not a
   finding either brief can claim as settled.
5. **`printed_number`/`truncated` are chunker-native and future-proof once wired in; `source_span`/
   `source_revision_id`/`license_ref` are not — no current new-ingest driver consults the
   per-notebook registry.** `ingest/chunker.py::chunk_paper` has zero notebook awareness (it
   resolves papers purely by `paper_id` against the shared, notebook-agnostic
   `var/arxmcp/corpus/parsed/` tree), so a future paper ingested after m2 ships would get
   `truncated`/`printed_number` automatically but `source_span`/`source_revision_id`/`license_ref`
   would stay NULL until another manual backfill run, silently reintroducing the exact gap this
   milestone exists to close. Whether wiring that shut (updating whatever driver calls
   `chunk_paper()` + a write path for a brand-new paper to also consult that notebook's
   `DocumentsStore`) is in m2's scope or a tracked fast-follow is not resolved by the roadmap text
   available to this research phase — recommend the owner confirm explicitly. (A secondary,
   lower-stakes instance of forward-incompleteness: spike-3's `parser_used` cross-check in the
   resolver contract, Column 1, has zero real signal today since that pre-existing column is 100%
   NULL in both live notebooks, confirmed this session — not an m2 defect, since populating it is
   not one of m2's 5 columns, but worth the owner knowing the resolver's cross-provenance flag is
   currently a no-op in practice.)

---

*Corrections/refinements versus sibling `research/brief-1.md` (both source-truth-m2, same phase):*
*the registry join does not require re-walking `papers.txt` (Column 2); the bulk write mechanism*
*is `merge_insert` mirroring `ingest/embed_equations.py`, not a `Table.update()` loop (Column 6,*
*empirically re-tested this session); `license_ref` is recommended as a denormalized value, not a*
*pointer identical to `source_revision_id` (Column 3). All three are flagged above as this brief's*
*reasoned position, not asserted as unilaterally settling brief-1's open questions.*
