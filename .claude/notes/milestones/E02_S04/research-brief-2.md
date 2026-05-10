# Research Brief 2 — E02_S04: Chunker Version Stamping and Content-Addressable `chunk_id`

**Researcher:** Agent 2 (independent)
**Date:** 2026-05-07

---

## 1. In-Codebase Context

### Current `chunk_id` placeholder format

Every call site in `ingest/chunker.py` that constructs a `ChunkRecord` uses:

```python
chunk_id=f"arxiv:{paper_id}:idx{idx}",
```

where `idx` is a monotonic integer from `counter[0]`. There are three such sites: the orphan-proof path, the statement-chunk path, and the proof-window path inside `_extract_chunks_from_container`, plus the section-prose path inside `_extract_section_chunks`. The file-output loop in `_chunk_paper_impl` then extracts the integer back:

```python
idx_str = chunk.chunk_id.split(":idx")[-1]
out_path = out_dir / f"{idx_str}.json"
```

After E02_S04, this extraction is no longer valid — output filenames must be derived differently (e.g. the 16-char hash suffix, or a sequential index preserved only for naming).

### `chunker_version` placement — the problem

`chunker_version` is currently a **default field on the dataclass**:

```python
# ingest/chunker_types.py, line 74
chunker_version: str = field(default="v1.0")
```

The acceptance criterion requires: "`CHUNKER_VERSION` constant is the only place the version string `"v1.0"` is defined." The dataclass default violates this. The fix is:

1. Add `CHUNKER_VERSION = "v1.0"` as a module-level constant in `ingest/chunker.py`.
2. Change the dataclass default to `field(default=CHUNKER_VERSION)`, importing `CHUNKER_VERSION` from `chunker` into `chunker_types`... **but wait**: `chunker_types.py` is imported by `chunker.py` (`from ingest.chunker_types import ChunkRecord`), so importing back from `chunker` into `chunker_types` creates a circular import.

The clean solution: define `CHUNKER_VERSION = "v1.0"` in `chunker.py` and pass it **explicitly** at every `ChunkRecord(...)` call site, leaving the dataclass default as a sentinel (e.g. `None` or the literal `"v1.0"` but with a `# noqa` comment explaining that the canonical source is `chunker.CHUNKER_VERSION`). Alternatively — and simpler — define `CHUNKER_VERSION` in `chunker_types.py` itself (there is no circular-import risk in that direction), then import it in `chunker.py` and pass it at every construction site. This keeps the single-definition invariant while avoiding circular import.

**Recommended approach:** Define `CHUNKER_VERSION = "v1.0"` in `ingest/chunker_types.py` (alongside the dataclass), change the default to `field(default=CHUNKER_VERSION)`, and import `CHUNKER_VERSION` into `chunker.py` for use in the hash assembly and manifest. This is the zero-circular-import solution.

### Preamble API and the hash input

`ingest/preamble.py` line 424–425:

```python
preamble_text = "\n".join(macros)
preamble_hash = hashlib.sha256(preamble_text.encode("utf-8")).hexdigest()[:16]
```

`PreambleDoc.preamble_text` is already NFC-normalized (the F6 fix from E02_S02 applies `unicodedata.normalize("NFC", tex_source)` before macro extraction). The chunker calls `_resolve_preamble_ref(paper_id)` which returns `doc.preamble_hash` (a 16-char string). It does **not** return `doc.preamble_text`.

For the chunk_id hash, the spec says:
> `sha256(preamble_normalized + body_text)[:16]`

where `preamble_normalized` comes from `preamble.json`. The chunker currently only retains the hash `preamble_ref`, not the full `preamble_text`. To compute the chunk_id, the implementation must fetch `doc.preamble_text` (the full text), not merely `doc.preamble_hash`.

`load_preamble(paper_id)` returns a full `PreambleDoc | None` with the `preamble_text` field available. The chunker should call `load_preamble` (or extract the `preamble_text` from the `doc` already returned by `extract_preamble`) instead of only storing the hash in `preamble_ref`.

### `TOKENIZER_VERSION` relationship

`ingest/tokenizer.py` defines:

```python
TOKENIZER_VERSION = "v1.0"
```

The tokenizer version and chunker version are **independent constants** — `TOKENIZER_VERSION` tracks changes to the BM25 pre-tokenizer regex, while `CHUNKER_VERSION` tracks changes to the structural chunking strategy (theorem/proof detection, windowing, section extraction). They happen to share the value `"v1.0"` at this point, but must remain separate: bumping `CHUNKER_VERSION` invalidates the chunk_id hashes; bumping `TOKENIZER_VERSION` invalidates the `body_tokens` BM25 cache. Both should stay as distinct module-level constants in their respective modules.

### Output file naming after hash migration

The current `_chunk_paper_impl` names output files `{idx_str}.json` by extracting the monotonic index from the placeholder `chunk_id`. After E02_S04, the chunk_id hash is 16 hex chars with no predictable numeric suffix. Output files should be named `{hash_suffix}.json` (i.e. the 16-char hash portion of the `chunk_id`). The manifest file is separate: `chunk_manifest.json` in the same directory.

The `for stale in out_dir.glob("*.json"): stale.unlink()` sweep already clears prior runs before writing — this remains correct and must clear `chunk_manifest.json` too (it matches `*.json`). The manifest should be written **after** all chunk files so the directory is consistent if the process is interrupted.

---

## 2. Prior Decisions and Lessons

### F3 fix (E02_S02): `preamble_ref=None` when extraction fails

`_resolve_preamble_ref` wraps `extract_preamble` in `PER_PAPER_FAILURE_EXCEPTIONS` and returns `None` on failure. When `preamble_ref is None`, chunks are written with `preamble_ref=None` and the embedder logs and continues.

**For chunk_id hashing:** the `preamble_normalized` input when the preamble is absent must be `""` (empty string, not `None`, not `"None"`). Rationale: the hash input must be a valid UTF-8 byte sequence; `"".encode("utf-8")` is `b""` (zero bytes), which is unambiguous and deterministic. Using `None` would require a string coercion and introduces an accidental choice. Using `"None"` would collide with a hypothetical paper whose preamble text is literally the string "None". The decision: **`preamble_normalized = "" if preamble_text is None else preamble_text`**.

This means a paper with a failed preamble and a paper whose preamble extracts to an empty macro list (zero macros → `preamble_text = ""`) produce the same hash prefix. That is correct behavior: both have the same observable preamble contribution.

### F6 fix (E02_S02): NFC normalization already applied

`preamble_text` is already NFC-normalized in `preamble.py`. The `body_text` in `ChunkRecord` comes from `_element_text()`, which normalizes whitespace via `" ".join("".join(parts).split())` but does NOT apply `unicodedata.normalize`. For BP1 determinism, E02_S04 should apply `unicodedata.normalize("NFC", body_text)` before hashing — or document that body_text from the HTML parser is always NFC (which is true for `html.parser` since Python 3.x processes XML/HTML bytes into str, which may carry decomposed forms from source). **The safe and explicit choice is to NFC-normalize both inputs before concatenation.**

### BP1 byte-identical caching contract

From `04-parsing-and-chunking.md` § Rule 6: "Editing a chunk produces a new ID." The hash must be computed over fully deterministic bytes. Two risk vectors:

1. **Dict key ordering in the hash input** — not applicable here since the input is a simple string concatenation: `preamble_text + body_text` (no dict involved).
2. **OS/Python process differences in string representation** — mitigated by explicit UTF-8 encoding: `(preamble_text + body_text).encode("utf-8")`.

### Atomic-write pattern (E02_S02)

`_write_preamble_json` uses `tmp + os.replace + try/finally cleanup` with a PID + UUID suffix on the tmp filename. The manifest write for E02_S04 should follow the same pattern: write to `chunk_manifest.{pid}.{uuid8}.json.tmp`, then `os.replace` to `chunk_manifest.json`.

---

## 3. External Sources: Hash Semantics and Collision Resistance

Python `hashlib.sha256` requires bytes input:

```python
import hashlib
digest = hashlib.sha256((preamble_text + body_text).encode("utf-8")).hexdigest()
chunk_id = f"arxiv:{paper_id}:{digest[:16]}"
```

The `[:16]` slice gives 16 hex characters = 8 bytes = 64 bits of entropy.

**Collision resistance at corpus scale:** The birthday bound gives collision probability ≈ `n²/(2·2^b)` where `n` is the number of items and `b` is the bit width. For 200K papers × ~100 chunks = 20M chunks, `n = 2×10^7`, `2^64 ≈ 1.8×10^19`:

```
P ≈ (2×10^7)² / (2 × 1.8×10^19) = 4×10^14 / 3.6×10^19 ≈ 1.1×10^-5
```

Approximately one-in-90,000 chance of any collision across the entire corpus. This is negligible for a retrieval system where a false chunk_id collision causes a stale-cache miss (not a security failure). The 16-char truncation matches the project's own design: `04-parsing-and-chunking.md` specifies `sha256(canonical_chunk_bytes)[:16]` and the `preamble_hash` in E02_S02 uses the same 16-char prefix.

**Encoding choice:** UTF-8 is canonical; it is the same encoding used for all JSON writes in the project (`ensure_ascii=False`, `encoding="utf-8"`) and for preamble hashing in `preamble.py` line 425.

---

## Open Questions

1. **Output file naming.** After replacing `idx{N}` chunk_ids with hash-based ids, should the per-chunk JSON output files be named `{hash_suffix}.json` (natural) or retain a sequential name `{N}.json` for human readability? The stale-file purge loop already handles both, but the decision affects the file-path extraction that currently splits on `:idx`. **Recommendation:** name files by hash suffix; it aligns the filename with the chunk_id and makes orphaned stale files self-identifying.

2. **Manifest atomicity.** If the process is interrupted after writing chunk JSON files but before writing `chunk_manifest.json`, the directory is in an inconsistent state. The eval harness (E05_S01) uses the manifest to validate. Should the chunker write a `.partial` marker at entry and remove it on clean completion? Or is the atomic-write of the manifest itself sufficient? **Recommendation:** the atomic write (tmp-then-rename) of the manifest is sufficient; a missing manifest indicates an interrupted run, not a corrupt one.

3. **`chunk_manifest.json` included in the `*.json` purge.** The current code does `for stale in out_dir.glob("*.json"): stale.unlink()` before writing new chunks. If `chunk_manifest.json` exists from a prior run, it will be deleted. The new manifest must be written **after** the new chunk files, in the same transaction block. This is the correct order, but it must be explicit in the implementation.

4. **`preamble_text` retrieval in `_resolve_preamble_ref`.** The function currently returns only `doc.preamble_hash`. E02_S04 needs `doc.preamble_text`. Either (a) change the function to return the full `PreambleDoc`, or (b) add a separate `_resolve_preamble_text(paper_id) -> str` helper. Option (b) risks a double `extract_preamble` call if not memoized. **Recommendation:** change `_resolve_preamble_ref` to return `PreambleDoc | None` and update all call sites.

5. **Collision behavior.** If two chunks in the same paper produce the same 16-char hash (a collision), the second will silently overwrite the first in the output directory (same filename). The manifest would list both chunk_ids but the file system would only have one file. Should the implementation detect this and fail loudly? At 64-bit collision resistance this is extremely improbable in practice, but the test should assert no duplicate chunk_ids per paper.

---

## External Writes the Implementation Requires

| Path | Operation | Notes |
|---|---|---|
| `ingest/chunker.py` | Modify | Add `CHUNKER_VERSION = "v1.0"` constant; replace `f"arxiv:{paper_id}:idx{idx}"` at 4 call sites; replace output filename extraction; write manifest |
| `ingest/chunker_types.py` | Modify | Define `CHUNKER_VERSION = "v1.0"` (if placed here); update `field(default=...)` |
| `var/arxmcp/corpus/chunks/<paper_id>/chunk_manifest.json` | Create (per paper) | Atomic write via tmp-then-rename pattern |
| `var/arxmcp/corpus/chunks/<paper_id>/<hash_suffix>.json` | Create (per chunk) | Replaces `<idx>.json` naming |
| `tests/test_chunker_ids.py` | Create | New test file asserting stable chunk_ids and body_text mutation |
