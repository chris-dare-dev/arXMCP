# Research Synthesis — E02_S04 chunk_id + chunker_version

Both researchers fully converged. Resolutions below.

## Architectural decisions (consensus)

**1. `CHUNKER_VERSION` location: `ingest/chunker_types.py`** (not `ingest/chunker.py`).

The brief says "module-level constant in `ingest/chunker.py`" but defining it there creates a circular import: `chunker_types.py` imports nothing from `chunker.py`, but `chunker.py` imports `ChunkRecord` from `chunker_types.py`. Putting the constant in `chunker_types.py` lets the dataclass default reference it as `field(default=CHUNKER_VERSION)` without circularity, and `chunker.py` imports it for use in the manifest. The acceptance criterion ("`CHUNKER_VERSION` constant is the only place `"v1.0"` is defined") is satisfied.

**2. Hash input:**
```python
preamble_text = doc.preamble_text if doc is not None else ""  # F3 fix: handle None
body_text_normalized = unicodedata.normalize("NFC", body_text)
chunk_id = f"arxiv:{paper_id}:{sha256((preamble_text + body_text_normalized).encode('utf-8')).hexdigest()[:16]}"
```

- `preamble_text` is already NFC from `preamble.py`'s F6 fix.
- `body_text` may not be NFC (HTML parser doesn't normalize); apply NFC before hashing only — do NOT mutate the stored `chunk.body_text`.
- Empty string `""` (not `None`, not `"None"`) when preamble extraction failed (F3 fallback).
- 64-bit prefix: ~1-in-90k collision risk across 20M chunks at the project's 200K-paper end state. Documented in module docstring; matches the `[:16]` precedent from `04-parsing-and-chunking.md` Rule 6 and `preamble_hash`.

**3. Output filename: `<hash_suffix>.json`** (the 16-char hash portion of `chunk_id`).

The existing `chunk.chunk_id.split(":idx")[-1]` extraction breaks once chunk_ids are hash-based. New: `chunk.chunk_id.split(":")[-1]` gives the 16-char suffix as the filename stem. Aligns with chunk_id and avoids colon-in-filename portability issues (Windows, some POSIX edge cases).

**4. `_resolve_preamble_ref` change:** return `PreambleDoc | None` instead of just `preamble_hash`. Callers extract both `.preamble_hash` (→ `chunk.preamble_ref`) and `.preamble_text` (→ chunk_id hash input) from the same call. Avoids a second `extract_preamble` call.

**5. `chunk_manifest.json`** written after all chunk JSON files via the atomic `tmp + os.replace + try/finally` pattern from `preamble.py`. Schema:

```json
{
  "paper_id": "2307.01156",
  "chunker_version": "v1.0",
  "chunks": [
    {"chunk_id": "arxiv:2307.01156:a1b2c3d4e5f60718", "kind": "stmt"},
    {"chunk_id": "arxiv:2307.01156:f0e1d2c3b4a59687", "kind": "proof"},
    ...
  ]
}
```

JSON written with `sort_keys=True` and `ensure_ascii=False` (matches preamble.py).

**6. `TOKENIZER_VERSION` and `CHUNKER_VERSION` are independent constants.** Both happen to be `"v1.0"` today. They track different invariants: `CHUNKER_VERSION` invalidates chunk_id hashes (structural chunking change); `TOKENIZER_VERSION` invalidates `body_tokens` BM25 cache (tokenizer regex change). Do NOT consolidate.

## Test surface

`tests/test_chunker_ids.py` (new):

- Same paper, two runs → byte-identical chunk_ids.
- Modified `body_text` (one word change) → different chunk_id.
- Modified preamble (one new macro) → different chunk_id (preamble flows through the hash).
- Missing preamble → empty-string fallback works (chunks emitted with hash, no exception).
- `CHUNKER_VERSION` is the only place `"v1.0"` appears as a string literal in `ingest/`. (Static source check.)
- Per-paper: no duplicate chunk_ids in the manifest (defense against the rare 64-bit collision).
- Manifest exists after a chunker run; lists every emitted chunk.

## Open questions resolved

- Filename: `<hash_suffix>.json`. ✓
- Hash input encoding: UTF-8. ✓
- Empty preamble fallback: `""`. ✓
- NFC on body_text: yes, but only inside the hash computation. ✓
- CHUNKER_VERSION location: `chunker_types.py`. ✓
- TOKENIZER_VERSION relationship: independent. ✓

## External writes

| type | target | why |
|---|---|---|
| filesystem write | `ingest/chunker.py` | hash logic + manifest write + filename change |
| filesystem write | `ingest/chunker_types.py` | `CHUNKER_VERSION` constant; field default uses it |
| filesystem write | `var/arxmcp/corpus/chunks/<paper_id>/<hash_suffix>.json` (×N per paper) | renamed output (gitignored) |
| filesystem write | `var/arxmcp/corpus/chunks/<paper_id>/chunk_manifest.json` | new manifest (gitignored) |
| filesystem write | `tests/test_chunker_ids.py` | new test file (committed) |
| filesystem write | `tests/test_chunker.py` | update existing tests asserting `chunker_version == "v1.0"` to import the constant |

No pushes, no PRs, no infra mutation, no third-party API calls.
