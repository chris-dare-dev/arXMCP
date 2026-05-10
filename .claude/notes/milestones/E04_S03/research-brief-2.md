# E04_S03 Research Brief 2 — corpus_version marker file and cache invalidation contract

## 1. In-Codebase Context

### Where `write_corpus_version_marker` lives in `ingest/store.py`

`ingest/store.py` already has `_append_store_stats(stats: WriteStats)` at line 440 — a
non-atomic append-mode ops log that fires at the end of every successful `write_chunks`
call (line 559). The `WriteStats` dataclass at line 150 already carries
`lancedb_version: int`, the same integer the marker file will record as `version`.

The natural insertion point is immediately AFTER `_append_store_stats(stats)` at the
bottom of `write_chunks`. A new `write_corpus_version_marker(lancedb_path, version, ...)`
should be called there automatically. This makes the marker an automatic postcondition
of every successful `write_chunks` call rather than a separate corpus-driver call.

Calling it inside `write_chunks` produces the correct invariant: if `write_chunks`
returns N, a `corpus-version.json` with `version=N` will exist at `lancedb_path`
before the caller sees N. The only atomicity concern is if `write_chunks` succeeds
but `write_corpus_version_marker` then raises — this must not propagate as a hard
failure; wrap the marker write in a `try/except` that logs ERROR and returns `dataset_version`
unchanged. A missing marker is a softer failure than aborting the whole ingest.

**Recommendation:** `write_chunks` calls `write_corpus_version_marker` automatically.
Do NOT make it an explicit corpus-driver call — that creates a two-step where the driver
could forget the second step, leaving the marker stale.

### `server/corpus.py` existing shape

`server/corpus.py` exports `open_chunks_table(lancedb_path, version)` as its sole public
function. Its docstring already anticipates the marker file at line 108:

> "The server uses this on cold startup before reading the `corpus-version.json` marker
> file (E04_S03); after the marker is read, the server re-opens with the explicit integer."

`read_corpus_version` is a natural sibling of `open_chunks_table` in this module. It
accepts `lancedb_path` (mirrors `open_chunks_table`'s signature), reads
`<lancedb_path>/corpus-version.json`, and returns a typed `CorpusVersionInfo` dataclass.
Both functions are reader-only; neither writes to LanceDB. The module's import graph
stays clean: `server.corpus` imports from `ingest.store` (for `DEFAULT_LANCEDB_PATH`)
and from `ingest.embedder` / `ingest.chunker_types` for the version constants — no
circular dependency.

### Canonical atomic-write pattern

Three existing implementations: `preamble._write_preamble_json`, `embedder._write_embeddings_npz`,
`embedder._write_embeddings_manifest`. The JSON-file form (preamble and manifest) is the
template:

```python
tmp = out_path.with_suffix(
    f"{out_path.suffix}.{os.getpid()}.{uuid.uuid4().hex[:8]}.tmp"
)
payload = json.dumps(doc_dict, ensure_ascii=False, sort_keys=True) + "\n"
try:
    tmp.write_text(payload, encoding="utf-8")
    os.replace(tmp, out_path)
finally:
    with contextlib.suppress(OSError):
        tmp.unlink(missing_ok=True)
```

`write_corpus_version_marker` must use this EXACT pattern. PID+UUID suffix prevents
concurrent ingest runs colliding on a shared `.tmp`. `os.replace` is POSIX-atomic on
same-filesystem (the marker is co-located with the LanceDB dataset, so same fs is
guaranteed).

### `PreambleDoc` dataclass pattern for `CorpusVersionInfo`

`preamble_types.PreambleDoc` defines the three-method contract used by all
downstream readers: `to_dict()` with alphabetical keys, `from_dict(data)` with explicit
type validation (e.g. `if not isinstance(macros_raw, list): raise TypeError`), and no
`__post_init__` logic beyond type checks.

`CorpusVersionInfo` should follow identically:

```python
@dataclass
class CorpusVersionInfo:
    version: int
    chunker_version: str
    embedder_version: str
    created_at: str      # ISO-8601 UTC, debug-only — NOT a cache key
    paper_count: int
    chunk_count: int

    def to_dict(self) -> dict: ...      # alphabetical keys, sort_keys=True
    @classmethod
    def from_dict(cls, data: dict) -> CorpusVersionInfo: ...  # type-validates
```

### BP1 and `created_at`

BP1 is defined in `07-multi-agent-caching.md` line 40–48 as: "Tool definitions are
byte-stable ... Sort properties alphabetically at serialization time." BP1 targets
**prompt-cache keys**: the byte content of system prompt + tool definitions that Anthropic
hashes for cache lookup. The `corpus-version.json` marker file is a **runtime config
artifact read by the MCP server at startup**, NOT a cached artifact included in any
prompt cache prefix. It is explicitly not a "cached artifact" under BP1.

The caching doc's no-timestamps rule at line 56 applies to `structuredContent` payloads
returned by tool calls (the result the model sees): "No timestamps, no random tie-breaks."
The marker file never flows into a tool result payload.

**Decision: keep `created_at`.** It is outside BP1 discipline and provides debugging
value (when did this corpus version land?). It MUST NOT appear in cache key construction
in E08_S03 — only `version: int` is the cache namespace key.

### `EMBEDDER_VERSION` constant in `embedder.py`

Line 117 of `ingest/embedder.py`:
```python
EMBEDDER_VERSION = f"bge-m3@{BGE_M3_COMMIT_SHA[:8]}"
```

Current value: `"bge-m3@5617a9f6"`. This is the SoT. The marker file's `embedder_version`
field must reuse this constant by import, not re-declare it.

### Existing test scan guards

`tests/conftest.py` has a single `autouse` fixture `_patched_store_stats_path` that
redirects `ingest.store.STORE_STATS_PATH` into `tmp_path`. It does NOT patch a corpus-version
path because no corpus-version path exists yet. The new marker write uses
`lancedb_path / "corpus-version.json"` directly (path is a parameter, not a module-level
constant), so tests pass `tmp_path / "lancedb"` explicitly — no conftest fixture needed.

`tests/test_store.py` and `tests/test_mvcc.py` already exercise `write_chunks` against
`tmp_path`-based LanceDB dirs. The new `test_corpus_version.py` should follow the same
fixture pattern.

---

## 2. Prior Decisions and Lessons

### Atomic-write precedent (fully established)

The pattern from `preamble._write_preamble_json` is canonical. Three separate
implementations across the codebase all look identical. No variation; copy verbatim.

### `_validate_paper_id` discipline

`corpus-version.json` takes `lancedb_path`, not `paper_id`. No `_validate_paper_id`
call is needed here. The path is config-derived (same Threat 1 note as `open_chunks_table`).

### `WriteStats.lancedb_version` carries the same integer

`WriteStats.lancedb_version` (line 167 of `store.py`) is already written to
`store-stats.jsonl` per call. The marker file is NOT redundant with this — they serve
different consumers. `store-stats.jsonl` is an append-mode ops audit log. The marker is
the **authoritative server startup config**: "what version should the server pin to RIGHT NOW?"
The marker overwrites on every successful ingest; the JSONL grows.

The marker write must happen AFTER `_append_store_stats`. This preserves the existing
call order and means the JSONL is always at least as fresh as the marker.

### Single-source-of-truth enforcement

**Recommendation: import `CHUNKER_VERSION` and `EMBEDDER_VERSION` directly inside
`write_corpus_version_marker`, do not accept them as parameters.** This enforces SoT
discipline at function-call time: a caller cannot accidentally pass a stale string literal.
The function signature becomes:

```python
def write_corpus_version_marker(
    lancedb_path: str | Path,
    version: int,
    paper_count: int,
    chunk_count: int,
) -> None:
```

`chunker_version` and `embedder_version` are populated by importing `CHUNKER_VERSION`
from `ingest.chunker_types` and `EMBEDDER_VERSION` from `ingest.embedder`.

This matches how `_write_embeddings_manifest` works: it never accepts `chunker_version`
or `embedder_version` as parameters; it reads them from module-level constants (`EXPECTED_CHUNKER_VERSION`
and `EMBEDDER_VERSION`), ensuring the sidecar always reflects the live constants.

### `paper_count` and `chunk_count` — accept as parameters

Querying LanceDB at write time via `count_rows` + a `SELECT DISTINCT paper_id` would add
latency and another LanceDB open after `write_chunks` already closed its connection. The
caller (`write_chunks`) already has both values: `len(chunks)` is `chunk_count`, and
`paper_count` can be derived from `len({c.paper_id for c in chunks})` (or passed down
from the corpus driver). Accept both as parameters. The brief's function signature
already lists `paper_count` and `chunk_count` as parameters — follow it.

### `created_at` timestamp format

Use `datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")`. This produces a
compact Z-suffix form (`"2026-05-08T14:30:00Z"`) without microseconds, consistent with
the ISO-8601 UTC format standard across the codebase. Prefer this over
`datetime.utcnow().replace(microsecond=0).isoformat() + "Z"` (deprecated in Python 3.12).

### `read_corpus_version` — return None on absent

`embedder._read_embeddings_manifest` returns `None` on absent or corrupt. `preamble._read_existing_preamble`
returns `None` on any error. The pattern is universal: absent marker = `None`, not `FileNotFoundError`.
The server startup path must handle `None` gracefully (fall back to `version=None` in
`open_chunks_table`, which opens the live tip).

---

## 3. External Sources

### JSON serialization

`json.dumps(doc_dict, ensure_ascii=False, sort_keys=True) + "\n"` — consistent with
`_write_preamble_json`, `_write_embeddings_manifest`, `_append_store_stats` — all use
this exact call. Alphabetical keys satisfy BP1 for any future context where the file
might flow into a comparison or hash.

### Atomic rename

`os.replace(tmp, dst)` is POSIX-atomic (POSIX rename(2) semantics). The tmp file and
the destination are under `lancedb_path/`, which is the same filesystem. Cross-filesystem
atomicity is not a concern here.

### Timestamp

```python
from datetime import datetime, timezone
datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
```

`datetime.utcnow()` is deprecated since Python 3.12; use `datetime.now(timezone.utc)`.

---

## Open Questions

**1. Where does `write_corpus_version_marker` get called?**
Recommendation: inside `write_chunks`, called automatically after `_append_store_stats`.
The marker write failure must NOT abort `write_chunks` — wrap in `try/except OSError`
that logs ERROR and continues. This keeps the invariant that the marker reflects the
last successful `write_chunks` result without making it a hard precondition.

**2. Should `write_corpus_version_marker` import `EMBEDDER_VERSION` and `CHUNKER_VERSION` directly?**
Yes — import both from their SoT modules (`ingest.embedder.EMBEDDER_VERSION`,
`ingest.chunker_types.CHUNKER_VERSION`). Do NOT accept them as parameters. This is
the same discipline `_write_embeddings_manifest` uses for its version fields, and it
prevents the marker from ever recording a stale string that diverges from the live constants.

**3. The `created_at` field — keep, omit, or make optional?**
Keep it. BP1 applies to prompt-cache prefixes and tool-result payloads, not to a startup
config artifact read before serving begins. The `created_at` field MUST be excluded from
E08_S03 cache key construction (only `version: int` is the cache namespace key per the
caching doc line 126: `key = sha256(... + corpus_version)`).

**4. `paper_count` and `chunk_count` source?**
Accept as parameters. `write_chunks` can derive them cheaply at call time:
`paper_count = len({c.paper_id for c in chunks})`, `chunk_count = len(chunks)`. No
extra LanceDB query.

**5. Should `read_corpus_version` raise on missing file, or return `None`?**
Return `None` — consistent with `_read_embeddings_manifest` and `_read_existing_preamble`.
The server startup path must handle `None` gracefully (open live tip via `version=None`).
Raise `ValueError` only on corrupt JSON that parses but fails schema validation.

**6. Should `CorpusVersionInfo` carry `bge_m3_commit_sha` for security audit?**
No — `embedder_version` already encodes the SHA prefix (`"bge-m3@5617a9f6"`). Full SHA
is available from `ingest.embedder.BGE_M3_COMMIT_SHA` if a security audit needs it. A
separate `bge_m3_commit_sha` field on `CorpusVersionInfo` would either duplicate the
information (redundant with `embedder_version`) or create a new SoT split. Omit.

---

## External Writes the Implementation Will Require

1. **`ingest/store.py` edit** — add `write_corpus_version_marker(lancedb_path, version, paper_count, chunk_count)` as a new module-level function; call it inside `write_chunks` after `_append_store_stats`; add to `__all__`.

2. **`server/corpus.py` edit** — add `CorpusVersionInfo` dataclass (with `to_dict` / `from_dict`), `read_corpus_version(lancedb_path) -> CorpusVersionInfo | None` function, and the cache contract comment explaining that server-side caches MUST include `corpus_version` as a mandatory cache key component and that on version change the server must restart or evict caches keyed on the old version.

3. **`tests/test_corpus_version.py` — new file** covering: (a) `write_corpus_version_marker` writes the expected JSON; (b) `read_corpus_version` returns a `CorpusVersionInfo` with correct fields; (c) two successive `write_chunks` calls (simulated by calling `write_corpus_version_marker` twice) increment `version`; (d) `read_corpus_version` returns `None` on absent file; (e) atomic write: a partially-written tmp file is cleaned up on exception.

4. **The marker file itself** — `<lancedb_path>/corpus-version.json` — written at runtime by `write_corpus_version_marker`, read at server startup by `read_corpus_version`. Not committed to the repo (in `.gitignore` under `var/`).
