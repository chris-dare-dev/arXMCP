# E04_S03 Research Synthesis — `corpus_version` marker file + cache contract

**Sources:** `research-brief-1.md` (Sonnet-A), `research-brief-2.md` (Sonnet-B)
**Status:** convergent on every architectural decision. One open question
on the function signature (parameters vs auto-imported constants)
resolved in favor of the brief's literal signature (parameters).
**Written:** 2026-05-08

---

## Resolved decisions

### D1. `write_corpus_version_marker` lives in `ingest/store.py` AND is called automatically by `write_chunks`

`ingest/store.py` already calls `_append_store_stats(stats)` at the
end of every successful `write_chunks` — a precedent for post-write
bookkeeping inside the function. The marker write follows the same
pattern: it is a postcondition of every successful ingest run, not a
separate corpus-driver call.

The call sequence inside `write_chunks`:
1. Build Arrow table, validate inputs.
2. `merge_insert.execute(...)`.
3. `_create_indices(tbl)`.
4. Resolve `dataset_version = tbl.version`.
5. `_append_store_stats(stats)` — ops audit log.
6. `write_corpus_version_marker(...)` — server startup config.
7. `return dataset_version`.

The marker write must NOT propagate exceptions as hard failures —
wrap in `try/except OSError` that logs ERROR and continues. A missing
marker is recoverable (server falls back to live-tip pinning); an
aborted ingest because of a marker write failure is NOT.

`write_corpus_version_marker` is also a public function (in
`__all__`) so tests can call it directly.

### D2. Function signature: parameters per the brief, auto-fed by `write_chunks`

The brief's literal signature:
```python
def write_corpus_version_marker(
    lancedb_path: str | Path,
    version: int,
    chunker_version: str,
    embedder_version: str,
    paper_count: int,
    chunk_count: int,
) -> None: ...
```

Researcher B argued for importing `CHUNKER_VERSION` and
`EMBEDDER_VERSION` directly inside the function (matching
`_write_embeddings_manifest`'s pattern). This would enforce SoT
discipline at function-call time but **trades off testability**: a
test that wants to assert the marker correctly records, say, an
older `chunker_version="v0.9"` (to simulate a version-bump scenario)
would have to monkey-patch module-level constants.

**Resolution: keep the brief's parameter signature.** The
`write_chunks` internal call threads in `CHUNKER_VERSION` and
`EMBEDDER_VERSION` from their SoT modules; tests pass arbitrary
values directly. The single-source-of-truth scan tests (already in
place for `"v1.0"` and the BGE SHA literal) catch any stray
redefinition in `store.py`.

### D3. Atomic write — copy `_write_preamble_json` verbatim

Three existing implementations (`preamble._write_preamble_json`,
`embedder._write_embeddings_npz`, `embedder._write_embeddings_manifest`)
use the same pattern:

```python
tmp = out_path.with_suffix(
    f"{out_path.suffix}.{os.getpid()}.{uuid.uuid4().hex[:8]}.tmp"
)
payload = json.dumps(doc.to_dict(), ensure_ascii=False, sort_keys=True) + "\n"
try:
    tmp.write_text(payload, encoding="utf-8")
    os.replace(tmp, out_path)
finally:
    with contextlib.suppress(OSError):
        tmp.unlink(missing_ok=True)
```

PID + UUID-suffixed tmp prevents concurrent ingest collisions on a
shared `.tmp` path. `os.replace` is POSIX-atomic on the same
filesystem — and the marker is co-located with the LanceDB dataset,
so same-fs is guaranteed.

`store.py` needs to import `os`, `uuid`, and `contextlib` at the
module top (currently absent because the dead `_atomic_write_json`
helper was removed in E04_S01 F11).

### D4. `created_at` is kept (debug-only field outside BP1 scope)

The marker file is a **runtime config artifact** read by the MCP
server at startup, NOT a cached artifact. BP1's "no timestamps"
discipline applies to:
- Tool-result `structuredContent` payloads (the model sees them).
- Prompt-cache prefixes (tool definitions hashed by Anthropic).

The marker file is never sent to the model and never enters the
prompt cache. `created_at` provides debug value (when did this
corpus version land?) and matches the brief's schema verbatim.

The `CorpusVersionInfo.from_dict` reader uses `data.get("created_at")`
(lenient) so a future schema reduction that drops the field doesn't
break readers.

**Cache discipline note (must surface in `server/corpus.py`'s
docstring):** E08_S03 cache keys MUST contain only the `version:
int`, never the `created_at` string. The caching doc's Tier-1 key
formula is `sha256(model_name + model_version + canonical_form
(query) + corpus_version)`.

### D5. `created_at` format

`datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")` produces
the compact Z-suffix form (`"2026-05-08T14:30:00Z"`) without
microseconds, matching the brief's schema example. `datetime.utcnow()`
is deprecated in Python 3.12+; we use the timezone-aware form.

### D6. `read_corpus_version(lancedb_path)` returns `CorpusVersionInfo | None`

Mirrors:
- `embedder._read_embeddings_manifest` → returns `None` on absent /
  corrupt.
- `preamble._read_existing_preamble` → returns `None` on any error.

`read_corpus_version` returns `None` when the marker file is absent.
Corrupt JSON or schema-validation failure raises `ValueError` (a
recoverable corruption signal — caller can decide whether to
re-ingest or rollback). The server startup path handles `None` by
calling `open_chunks_table(path, version=None)` (live-tip fallback).

### D7. `lancedb_path` defaults to `DEFAULT_LANCEDB_PATH` (matches E04_S02 F3)

Both `write_corpus_version_marker` and `read_corpus_version` accept
`lancedb_path: str | Path | None = None`, defaulting to
`DEFAULT_LANCEDB_PATH` from `ingest.store`. Symmetric with
`open_chunks_table` (E04_S02) and `write_chunks` (E04_S01).

### D8. `paper_count` and `chunk_count` are derived inside `write_chunks`

`write_chunks` computes them from the in-memory chunks list:
- `chunk_count = len(chunks)`
- `paper_count = len({c.paper_id for c in chunks})`

No extra LanceDB query. Both fields are passed as parameters to the
internal `write_corpus_version_marker` call.

### D9. `CorpusVersionInfo` dataclass — same shape as `PreambleDoc`

```python
@dataclass
class CorpusVersionInfo:
    version: int
    chunker_version: str
    embedder_version: str
    created_at: str
    paper_count: int
    chunk_count: int

    def to_dict(self) -> dict:
        # alphabetical keys for byte-stability
        return {
            "chunk_count": self.chunk_count,
            "chunker_version": self.chunker_version,
            "created_at": self.created_at,
            "embedder_version": self.embedder_version,
            "paper_count": self.paper_count,
            "version": self.version,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "CorpusVersionInfo":
        return cls(
            version=int(data["version"]),
            chunker_version=str(data["chunker_version"]),
            embedder_version=str(data["embedder_version"]),
            created_at=str(data.get("created_at", "")),
            paper_count=int(data["paper_count"]),
            chunk_count=int(data["chunk_count"]),
        )
```

Lives in `server/corpus.py` (not a separate `_types.py`) — the
server-layer module is small and the type is read-only.

### D10. Cache contract comment in `server/corpus.py`

The cache contract is a multi-paragraph docstring section in
`server/corpus.py`'s module docstring:

> **Cache invalidation contract (E04_S03 → E08_S03).** Server-side
> caches MUST include the `version` integer from
> :class:`CorpusVersionInfo` in their cache keys (NOT
> `chunker_version`, NOT `embedder_version`, NOT `created_at` — only
> `version`). When the server reads a new `corpus-version.json` with
> a higher `version` than its last-seen value, it MUST clear all
> in-process caches keyed on the old version. Sonnet B's E08_S03
> implementation honors this contract.

The contract is also visible in `read_corpus_version`'s docstring
for callers reading top-down.

### D11. Tests live in `tests/test_corpus_version.py`

Coverage map:
- `TestWriteMarker`: marker file written, schema matches, atomic
  (no tmp leak), JSON keys alphabetical (BP1).
- `TestReadMarker`: round-trip via `from_dict`, returns None on
  absent, raises on corrupt JSON.
- `TestVersionIncrements`: two successive `write_chunks` calls
  produce a marker whose `version` field increments.
- `TestSchemaContract`: cache-contract comment present in
  `server/corpus.py`'s module docstring (regression-locked via
  whitespace-collapsed substring match).
- `TestSingleSourceOfTruth`: `CorpusVersionInfo.embedder_version`
  matches `EMBEDDER_VERSION` after a real `write_chunks` run.

The autouse `_patched_store_stats_path` fixture in
`tests/conftest.py` already redirects the stats log; the marker file
lives under `lancedb_path` which each test passes as `tmp_path /
"lancedb"`, so no new fixture is needed.

---

## Open questions resolved

- **Auto-call vs explicit driver call:** auto-call (D1).
- **Function signature:** parameters per brief (D2).
- **`created_at` keep/drop:** keep, lenient `from_dict` (D4).
- **`paper_count` / `chunk_count` source:** derived in `write_chunks`
  from the chunks list (D8).
- **`read_corpus_version` failure mode:** `None` on absent,
  `ValueError` on corrupt (D6).
- **Default path symmetry:** yes, both reader and writer (D7).
- **`bge_m3_commit_sha` full SHA on the marker:** out of scope for
  this milestone — `EMBEDDER_VERSION` already encodes the 8-char
  prefix and is consistent with the LanceDB column. Adding a full-SHA
  field would be a schema change.

---

## External writes the implementation will require

| Path | Event | Notes |
|---|---|---|
| `ingest/store.py` | source edit | `write_corpus_version_marker` function + auto-call from `write_chunks`; adds top-level `os`, `uuid`, `contextlib` imports; updates `__all__` |
| `server/corpus.py` | source edit | `CorpusVersionInfo` dataclass + `read_corpus_version` function + cache-contract paragraph in module docstring; updates `__all__` |
| `tests/test_corpus_version.py` | new file | 5 test classes per D11 |
| `var/arxmcp/index/lancedb/corpus-version.json` | runtime | written by `write_chunks` on every successful ingest; not committed to git |

No `pyproject.toml` change. No new external service. No model
download. No infra mutation.
