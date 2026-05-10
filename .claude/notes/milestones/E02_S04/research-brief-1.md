# Research Brief — E02_S04: Chunker version stamping and content-addressable `chunk_id`

*Researcher 1 of 2 — independent brief*

---

## 1. In-codebase context

### Current `chunk_id` format and where it is set

`ingest/chunker.py` emits chunks with the placeholder:

```python
chunk_id=f"arxiv:{paper_id}:idx{idx}",
```

This appears in three places in `_extract_chunks_from_container` (orphan proof
window, statement chunk, paired proof windows) and once in
`_extract_section_chunks`. The module docstring is explicit:

> "Chunk IDs use the monotonic placeholder `arxiv:<paper_id>:idx<N>` until E02_S04
> lands the content-addressable SHA-256 hash."

There is also a filename derivation tied to the placeholder:

```python
idx_str = chunk.chunk_id.split(":idx")[-1]
out_path = out_dir / f"{idx_str}.json"
```

E02_S04 must replace both the `chunk_id` value and the output filename scheme —
files can no longer be named by monotonic index once IDs become hashes.

### Current `chunker_version` location

`ingest/chunker_types.py` line 74:

```python
chunker_version: str = field(default="v1.0")
```

This is a **dataclass field default**, not a module-level constant. The milestone
brief and acceptance criteria require it to be a `CHUNKER_VERSION` module-level
constant in `ingest/chunker.py` so there is exactly one definition site. The
current placement violates that constraint and must move.

`ingest/chunker_types.py` is the correct place to import the constant from
`chunker.py` — or the constant can live in `chunker_types.py` and be imported by
`chunker.py`. Either is acceptable; the constraint is that `"v1.0"` must not
appear as a string literal in more than one module.

### Preamble API relevant to the hash input

`ingest/preamble.py` → `ingest/preamble_types.py` expose:

- `PreambleDoc.preamble_text`: `"\n".join(self.macros)` — a newline-joined,
  sorted, deduplicated, NFC-normalised, whitespace-collapsed list of macro
  definitions. Already deterministic.
- `PreambleDoc.preamble_hash`: `hashlib.sha256(preamble_text.encode("utf-8")).hexdigest()[:16]`
  — already computed; the chunker stores this as `chunk.preamble_ref`.

The `preamble_text` field (the full text, not the hash) is what goes into the
`chunk_id` hash. The chunker retrieves it through `_resolve_preamble_ref` which
calls `extract_preamble(paper_id)` and returns `doc.preamble_hash`. E02_S04 needs
to instead call `load_preamble(paper_id)` (or reuse the already-extracted doc) to
get `doc.preamble_text`.

**Preferred pattern:** call `extract_preamble` once per paper (already called for
`preamble_ref`), capture the full `PreambleDoc`, extract both `preamble_hash`
(for `preamble_ref`) and `preamble_text` (for the `chunk_id` hash) from the same
call. This avoids a second disk read.

### NFC normalization already applied to preamble

`preamble.py` line 422–423:

```python
tex_source = unicodedata.normalize("NFC", tex_source)
macros = _extract_macros(tex_source)
```

NFC is applied before macro extraction, so `preamble_text` is always NFC. No
additional normalization step is needed in `chunker.py`.

### `body_text` determinism

`body_text` is produced by `_element_text`, which walks the BS4 parse tree and
joins parts with `" ".join("".join(parts).split())`. The final join-split
collapses whitespace canonically. No explicit NFC normalization is applied to
`body_text`. Since the source is an HTML file read with `html_bytes =
parsed_html.read_bytes()` and BeautifulSoup extracts text from it, the bytes are
stable across runs on the same file. However, for absolute BP1 safety the
implementer should apply `unicodedata.normalize("NFC", body_text)` before hashing
(but NOT before storing as `body_text`, to avoid mutating the stored content).
This is the same pattern `tokenize_body` uses in `ingest/tokenizer.py` lines
128–129:

```python
text = unicodedata.normalize("NFC", body_text)
```

Hash over NFC form; store original `body_text` unchanged.

### `TOKENIZER_VERSION` precedent

`ingest/tokenizer.py` line 76:

```python
TOKENIZER_VERSION = "v1.0"
```

This is the exact pattern `CHUNKER_VERSION` must mirror. The comment explains the
rationale: bumping the constant is the signal to downstream re-embedding and cache
invalidation. `TOKENIZER_VERSION` is not currently incorporated into `chunk_id`
(the milestone brief does not ask for it), but it is available as a future hash
input when the BM25 cache key is formalised in E04_S04.

### Downstream consumers using `chunker_version`

`05-storage-and-indexing.md` describes the LanceDB `chunks` table with column
`chunker_version: string`. E04_S02 (LanceDB MVCC writer) reads this field to
detect stale rows. The note (updated 2026-05-06) says:

> "Keep N=7 prior LanceDB dataset versions for rollback."

The writer's staleness logic is: if `chunker_version` on a stored row != the
current `CHUNKER_VERSION` constant, the row is a candidate for replacement during
the next ingest pass. Centralising the constant in `chunker.py` is therefore the
correct contract boundary.

---

## 2. Prior decisions and lessons

### F3 fix (E02_S02) — `preamble_ref=None` on extraction failure

When `extract_preamble` raises a `PER_PAPER_FAILURE_EXCEPTIONS` error,
`_resolve_preamble_ref` returns `None` and the loop:

```python
if preamble_ref is not None:
    for chunk in all_chunks:
        chunk.preamble_ref = preamble_ref
```

leaves `chunk.preamble_ref` as `None`. E02_S04 must handle this case for the
`chunk_id` hash: **when preamble extraction fails, `preamble_normalized` used in
the hash is the empty string `""`**. Rationale: `None` is not hashable as bytes;
`""` is the zero-byte representation of "no preamble content" and is stable across
runs (every run with extraction failure produces the same empty string). Using
`""` means the `chunk_id` depends only on `body_text` for papers without
preambles, which is correct — it remains content-addressable.

This decision must be documented in code with a comment citing the F3 fix from
E02_S02 so future readers understand the choice.

### F6 fix (E02_S02) — NFC normalization on preamble text

Already applied inside `preamble.py` before `preamble_text` is computed. No
additional normalization is needed in the hash input path for the preamble side.

### BP1 byte-identical contract

The `_window_proof_text` docstring is explicit:

> "windows are character-substring slices of `proof_text`, NOT encode/decode
> round-trips. Decoding WordPiece subwords mutates whitespace and breaks the
> determinism contract that E02_S04's content-addressable hashes depend on."

This means `body_text` as stored in `ChunkRecord` is already the canonical
substring to hash — no re-encoding or tokenizer round-trip should be applied
before hashing.

### Atomic-write pattern (E02_S02)

The existing pattern in `preamble.py` (`tmp + os.replace + try/finally`) must be
reused for `chunk_manifest.json`. The manifest is written once per paper after all
chunks are emitted, so atomicity prevents a partial manifest from being consumed
by the eval harness.

---

## 3. External sources

### Python `hashlib.sha256` input semantics

`hashlib.sha256` requires `bytes`, not `str`. The correct call is:

```python
import hashlib
digest = hashlib.sha256(
    (preamble_normalized + body_text).encode("utf-8")
).hexdigest()[:16]
```

UTF-8 encoding is the only choice consistent with the rest of the codebase:
`preamble.py` uses `.encode("utf-8")` for `preamble_hash`, and `json.dumps(...,
ensure_ascii=False)` with `encoding="utf-8"` is used everywhere for file I/O.

### Collision resistance of 16-hex-char prefix

The `[:16]` slice yields 16 hexadecimal characters = 8 bytes = 64 bits of hash
output. For a corpus of 200K papers × ~100 chunks/paper = 20M chunks, the
birthday-bound collision probability is approximately:

```
P ≈ n² / (2 × 2^64) = (2×10^7)² / (2 × 1.8×10^19) ≈ 1.1 × 10^-5
```

This is roughly a one-in-100,000 chance of any collision across the full corpus
— negligible for a research math corpus. The design note in
`04-parsing-and-chunking.md` Rule 6 uses the same `[:16]` prefix without further
justification; this brief provides the quantitative backing.

### Determinism of dict key ordering

The hash input is a concatenated string (`preamble_normalized + body_text`), not
a dict serialization. There is no dict involved, so key-ordering is not a risk
here. The risk note in the milestone brief about "dict key ordering" applies to a
naive design that hashed a JSON representation; the string concatenation design
avoids it entirely.

---

## Open questions

1. **Output filename for chunk JSON files.** Currently `{idx}.json`. After
   E02_S04, the `chunk_id` is a hash-based string containing colons
   (`arxiv:2307.01156:a1b2c3d4e5f60718`). Colons are invalid in filenames on
   Windows and some filesystems. Options:
   - Use only the 16-char hash suffix as the filename: `a1b2c3d4e5f60718.json`.
   - URL-encode colons: `arxiv%3A2307.01156%3Aa1b2c3d4e5f60718.json`.
   - Keep a separate monotonic index for filenames and only use the hash for
     `chunk_id`. This last option is cleanest: filenames are an implementation
     detail, `chunk_id` is the identity.

   Recommended: use `chunk.chunk_id.split(":")[-1]` (the 16-char hash) as the
   filename stem. This is stable, short, and avoids the colon problem.

2. **Hash input for `body_text` NFC normalization.** Should the hash be computed
   over `body_text` as stored or over `NFC(body_text)`? If the HTML parser ever
   emits non-NFC characters in extracted text, two runs on the same paper could
   produce different `body_text` values with the same visual content.
   Recommendation: apply `unicodedata.normalize("NFC", body_text)` inside the
   hash computation only (do not mutate `chunk.body_text`), mirroring
   `tokenize_body`'s pattern.

3. **`chunk_manifest.json` write timing.** The manifest must be written after all
   chunks are emitted (since it lists all `chunk_id`s). It should be written
   inside `_chunk_paper_impl` after the per-chunk JSON loop, using the atomic-write
   pattern. Confirm that the manifest is included in the stale-file cleanup (the
   current `for stale in out_dir.glob("*.json"): stale.unlink()` will catch it
   if it exists from a prior run, since `.json` matches — but verify this is
   intentional).

4. **`CHUNKER_VERSION` import direction.** The constant must be defined in exactly
   one place. Two valid homes: (a) `chunker.py` (it's a chunker property), with
   `chunker_types.py` importing it for use as a field default; (b) `chunker_types.py`
   (it's a field property), with `chunker.py` importing it for use in the hash.
   Option (a) is cleaner since the constant governs chunking strategy, not the
   data schema. But `chunker_types.py` currently imports nothing from `chunker.py`
   and adding such an import would create a circular dependency (chunker.py imports
   ChunkRecord from chunker_types.py). Therefore the constant must live in
   `chunker_types.py` and be imported by `chunker.py`, OR it must live in a new
   `chunker_constants.py` module that both import. Recommended: define it in
   `chunker_types.py` as a module-level constant (not a field default), import it
   in `chunker.py` where needed, and use it as the field default via
   `field(default=CHUNKER_VERSION)`.

5. **Eval harness `chunk_id` reference validation.** The milestone brief mentions
   `tests/eval/fixtures/queries.json` with curated `chunk_id` references. Does
   this file exist yet? If not, the test for manifest validation against it is
   aspirational and the test should be written to handle the file being absent
   gracefully (or the test fixture should be created as part of E02_S04).

---

## External writes the implementation will require

| Path | Description |
|---|---|
| `ingest/chunker.py` | Define `CHUNKER_VERSION = "v1.0"` constant; replace four `chunk_id=f"arxiv:{paper_id}:idx{idx}"` call sites with hash-based ID computation; fix output filename derivation; add `chunk_manifest.json` write after chunk loop |
| `ingest/chunker_types.py` | Either import `CHUNKER_VERSION` from `chunker.py` (circular — avoid) or define the constant here and import in `chunker.py`; remove the `"v1.0"` string literal from the field default |
| `var/arxmcp/corpus/chunks/<paper_id>/chunk_manifest.json` | One file per paper in the seed corpus after a full chunker run |
| `tests/test_chunker_ids.py` | New test file asserting byte-identical `chunk_id` on re-run, different `chunk_id` on body mutation, `chunker_version` on every chunk, single definition of constant |
| `tests/eval/fixtures/queries.json` | May need to be created as a stub if it does not exist yet (eval harness dependency) |
