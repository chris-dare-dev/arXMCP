# E03_S01 Research Brief 1 — BGE-M3 Dual-Column Embedder

**Milestone:** E03_S01 — `ingest/embedder.py` dual-column BGE-M3 encoder
**Status:** NEW | **Tier:** 0 | **Effort:** M
**Written:** 2026-05-07

---

## 1. In-Codebase Context

### What E02 already delivers (available NOW)

The chunker pipeline is complete through E02_S04. Each paper produces:

- `var/arxmcp/corpus/chunks/<paper_id>/<hash16>.json` — one file per ChunkRecord,
  JSON-serialized via `ChunkRecord.to_dict()`
- `var/arxmcp/corpus/chunks/<paper_id>/chunk_manifest.json` — index of all
  chunk_ids and kinds for the paper
- `var/arxmcp/corpus/preamble/<paper_id>/preamble.json` — `PreambleDoc` with
  `preamble_text` and `preamble_hash`

The `ChunkRecord` schema (from `ingest/chunker_types.py`) has these load-bearing
fields for E03_S01:

- `chunk_id: str` — `arxiv:<paper_id>:<sha256[:16]>`
- `paper_id: str`
- `kind: str` — one of `"stmt"`, `"proof"`, `"section"`, `"definition"`,
  `"lemma"`, `"proposition"`, `"corollary"`, `"remark"`, etc.
- `body_text: str` — already token-capped: stmts ≤ 512 BGE-M3 tokens,
  proof windows ≤ 448 tokens (via `_truncate_to_token_budget` in `chunker.py`)
- `preamble_ref: str | None` — first 16 hex chars of SHA-256(preamble_text);
  `None` when extraction failed (F3 graceful degradation)
- `truncated: bool` — True when chunker had to slice body_text

**No `embedding_*` fields exist on `ChunkRecord`.** Those are LanceDB columns
defined in E04_S01's `ingest/schema.py` (PyArrow schema). The ChunkRecord is
the input to the embedder; the embedding vectors are output to LanceDB.

### The critical E04_S01 dependency

E04_S01 defines the canonical LanceDB table at
`var/arxmcp/index/lancedb/chunks` with schema:

```
embedding_stmt   fixed_size_list<float32>[1024]  nullable
embedding_proof  fixed_size_list<float32>[1024]  nullable
embedding_eq     fixed_size_list<float32>[1024]  nullable  (NULL until E10_S03)
embedder_version string
preamble_ref     string  nullable
...
```

The table writer is `ingest/store.py` (to be built in E04_S01), exposing
`write_chunks(chunks, embeddings, lancedb_path) -> int`.

**E04_S01 has a circular dependency with E03_S01:** the roadmap file
`E04-vector-store.md` lists E03_S01 as a dependency of E04_S01, AND the
E03_S01 brief says it reads/writes to the LanceDB table from E04_S01.
Neither can literally block on the other.

### RECOMMENDATION: Ship E03_S01 independent of E04_S01 using parallel JSON/NPZ output

E03_S01 should read the existing per-paper chunk JSONs from
`var/arxmcp/corpus/chunks/<paper_id>/` (already produced by E02) and write
embedding vectors to a parallel per-paper store at
`var/arxmcp/corpus/embeddings/<paper_id>/embeddings.npz` (NumPy compressed
array, keyed by `chunk_id`). This:

1. Breaks the circular dependency — E03_S01 ships independent of E04_S01.
2. Lets E04_S01 read both the chunk JSONs AND the pre-computed embeddings
   when building the LanceDB table, with `store.py` assembling the full row.
3. Matches the existing pattern: chunker writes JSON → preamble writes JSON
   → embedder writes NPZ → store reads all three and writes LanceDB.

The `embed_corpus()` function signature stays as specified:
`embed_corpus(lancedb_path: str, corpus_path: str, batch_size: int = 32) -> EmbedStats`
but `lancedb_path` is only used for the stats log path; the actual embedding
vectors go to `var/arxmcp/corpus/embeddings/<paper_id>/embeddings.npz` until
E04_S01 wires the LanceDB write. Alternatively, `embed_corpus` can accept a
`corpus_path` and write NPZ files, with a thin shim for E04_S01 to call later.

**If the implementation team insists on LanceDB from day one**, E04_S01 must
be built first (or simultaneously), and E03_S01 is blocked. The NPZ approach
is strongly preferred to allow independent delivery.

### Tokenizer precedent

`ingest/tokenizer.py` defines:
```python
TOKENIZER_VERSION = "v1.0"
```
`BGE_M3_COMMIT_SHA` in `ingest/embedder.py` should follow the same pattern —
a module-level constant, all-caps, defined at the top of the file. The
`embedder_version` string written to LanceDB (and to `embed-stats.jsonl`)
should be `f"bge-m3@{BGE_M3_COMMIT_SHA[:8]}"` — mirrors the
`corpus-version.json` schema in E04_S03 which uses `"bge-m3@abc1234"`.

### Preamble loading path

`ingest/preamble.py` exposes `load_preamble(paper_id: str) -> PreambleDoc | None`.
This is the correct call for the embedder — it does NOT trigger re-extraction,
just reads the already-written `preamble.json`. The embedder constructs the
embedding input as:

```python
preamble = load_preamble(paper_id)
preamble_text = preamble.preamble_text if preamble is not None else ""
embed_input = preamble_text + "\n\n" + chunk.body_text
```

When `preamble_ref` is None on a chunk (F3 fallback), `load_preamble` will
return None and `preamble_text` falls back to `""` — body_text-only embedding.
This is consistent with how `_compute_chunk_id` in `chunker.py` handles the
same case.

### Token budget: why "warn + truncate" rarely fires

The chunker's `_truncate_to_token_budget` already enforces:
- `kind="stmt"`: body_text ≤ 512 BGE-M3 tokens (STMT_MAX_TOKENS)
- `kind="proof"`: body_text ≤ 448 BGE-M3 tokens (PROOF_MAX_TOKENS)

However, the embedder encodes `preamble_text + "\n\n" + body_text`. The
preamble adds variable token count. The chunker's budget covers body_text
only; the preamble contribution is uncapped upstream. Therefore the embedder's
512-token enforcement is a real safety net for preamble-heavy papers. Warn
(log at WARNING level), then truncate via the same `_truncate_to_token_budget`
call pattern from `chunker.py` — do NOT raise.

### `pyproject.toml` gap: `torch` is missing

`pyproject.toml` currently lists:
```
"transformers>=4.40",
```
The comment explicitly says: "Loads tokenizer vocab only (~5 MB cached); NOT
full model weights, so torch is NOT required."

E03_S01 DOES require `torch` for model inference. The embedder must add
`torch` to `pyproject.toml` dependencies. The correct addition:
```
"torch>=2.0",
```
CPU-only installs can use the standard PyPI `torch` package; no custom index
needed for CPU. The embedder should also add `numpy` if not already present
(for NPZ output and L2-norm calculation, though `torch.nn.functional.normalize`
can replace numpy for the norm step).

---

## 2. Prior Decisions and Lessons

### F3 fix (E02_S02): preamble_ref=None on extraction failure

`ChunkRecord.preamble_ref` is `None` when preamble extraction failed. The
embedder must handle this without crashing: call `load_preamble(paper_id)`,
check for None, fall back to `preamble_text = ""`. This is not an error
condition — it is the documented graceful-degradation path.

### F6 (NFC normalization)

The preamble extractor already applies NFC at extraction time (`preamble.py`
line 421: `tex_source = unicodedata.normalize("NFC", tex_source)`). The stored
`preamble_text` is already NFC. The chunker applies NFC to `body_text` only
for the hash, but stores the raw parser output. The embedder should apply NFC
to `body_text` before concatenating, mirroring `tokenize_body`'s discipline
(`tokenizer.py` line 128: `text = unicodedata.normalize("NFC", body_text)`).
This ensures the embedding input is byte-stable across hosts (BP1).

### Threat 6: model weights pinning (08-security-observability-ops.md)

The security doc states: "Pin model commit SHAs in configuration
(`BAAI/bge-m3@<sha>`), not just names." and "Use `safetensors` format only;
refuse `.bin` / pickle weights." and "Run model loads with
`trust_remote_code=False` unless explicitly opted in."

The locked-load form is therefore:
```python
BGE_M3_COMMIT_SHA = "5617a9f61b028005a4858fdac845db406aefb181"

from transformers import AutoModel, AutoTokenizer
model = AutoModel.from_pretrained(
    "BAAI/bge-m3",
    revision=BGE_M3_COMMIT_SHA,
    trust_remote_code=False,
)
tokenizer = AutoTokenizer.from_pretrained(
    "BAAI/bge-m3",
    revision=BGE_M3_COMMIT_SHA,
)
```
The `revision` parameter is what pins to the SHA — using a floating tag or
omitting `revision` is forbidden by the milestone brief.

### Atomic-write pattern (ingest/preamble.py)

`_write_preamble_json` uses: tmp path = `out_path.with_suffix(f"...{pid}.{uuid}.tmp")`,
`tmp.write_text(...)`, `os.replace(tmp, out_path)`, `try/finally` to
`tmp.unlink(missing_ok=True)`. The embedder's NPZ output and `embed-stats.jsonl`
append should follow the same pattern for the NPZ file; the JSONL append is
inherently non-atomic but acceptable for a stats log (mirrors `chunk.log`).

### PER_PAPER_FAILURE_EXCEPTIONS pattern

Both `chunker.py` and `preamble.py` define:
```python
PER_PAPER_FAILURE_EXCEPTIONS = (OSError, ValueError, FileNotFoundError)
```
The embedder's per-paper loop should catch the same set, log to
`var/arxmcp/ops/embed-stats.jsonl` with `status: "fail"`, and continue —
never abort the corpus-wide batch for a single paper failure. Programmer bugs
(AttributeError, TypeError, RuntimeError from torch internals) propagate.

---

## 3. External Sources

### BGE-M3 commit SHA (current main, fetched 2026-05-07)

```
BGE_M3_COMMIT_SHA = "5617a9f61b028005a4858fdac845db406aefb181"
```
Source: `https://huggingface.co/api/models/BAAI/bge-m3` → `sha` field.
This must be verified at implementation time — the SHA advances when BAAI
pushes updates. The procedure to refresh: `curl -s
https://huggingface.co/api/models/BAAI/bge-m3 | python -c "import sys,json;
print(json.load(sys.stdin)['sha'])"`.

### Loading style: AutoModel, not FlagEmbedding

The model card recommends `FlagEmbedding` for its full multi-vector/sparse
retrieval pipeline. For this project we only need dense embeddings, and
`FlagEmbedding` is an additional heavy dependency not in `pyproject.toml`.
Use `transformers.AutoModel` directly:

```python
import torch
import torch.nn.functional as F
from transformers import AutoModel, AutoTokenizer

model = AutoModel.from_pretrained(
    "BAAI/bge-m3",
    revision=BGE_M3_COMMIT_SHA,
    trust_remote_code=False,
)
model.eval()

with torch.no_grad():
    inputs = tokenizer(
        texts,
        padding=True,
        truncation=True,
        max_length=512,
        return_tensors="pt",
    )
    outputs = model(**inputs)
    # BGE-M3 dense embedding: CLS token of last hidden state
    embeddings = outputs.last_hidden_state[:, 0, :]
    embeddings = F.normalize(embeddings, p=2, dim=1)
```

BGE-M3 uses CLS pooling for dense retrieval. `F.normalize(..., p=2, dim=1)`
produces L2-normalized vectors of shape `(batch_size, 1024)`. The model's
hidden size is 1024 (XLM-RoBERTa-large backbone), matching the LanceDB schema.

`model.eval()` + `torch.no_grad()` are required: `eval()` disables dropout
layers that would produce non-deterministic embeddings; `no_grad()` disables
gradient tracking for inference correctness and memory efficiency on CPU.

### CPU inference

No GPU is required. The standard PyPI `torch` package runs on CPU. Do NOT
call `.cuda()` or `.to("cuda")` — the milestone brief specifies CPU-only mode.
For CPU inference correctness, set:
```python
torch.set_num_threads(os.cpu_count() or 4)
```
This avoids leaving CPU parallelism at the default (can be 1 on some configs).

### L2-normalization

`F.normalize(embeddings, p=2, dim=1)` is equivalent to dividing each vector
by its L2 norm. After normalization, `torch.norm(v, p=2) == 1.0` for every
row. The test suite should assert `abs(np.linalg.norm(vec) - 1.0) < 1e-5`.

### Dependency: `torch` not in pyproject.toml

The chunker explicitly avoids loading torch (comment in `chunker.py`: "NOT
full model weights, so torch is NOT required"). E03_S01 must add `torch>=2.0`
to `pyproject.toml`. The embedder should fail loudly (ImportError with clear
message) if torch is absent at import time — no silent fallback.

---

## 4. Routing Table (kind → column)

Per the milestone brief and E04_S01 schema:

| `kind` value | `embedding_stmt` | `embedding_proof` | `embedding_eq` |
|---|---|---|---|
| `"stmt"` | vector (1024,) | NULL | NULL |
| `"proof"` | NULL | vector (1024,) | NULL |
| `"section"` | vector (1024,) | NULL | NULL |
| `"definition"` | vector (1024,) | NULL | NULL |
| `"lemma"`, `"proposition"`, `"corollary"`, `"remark"`, `"example"`, `"claim"`, `"conjecture"`, `"fact"`, `"hypothesis"`, `"observation"`, `"problem"`, `"question"`, `"exercise"`, `"assumption"`, `"convention"`, `"notation"` | vector (1024,) | NULL | NULL |
| any other kind | vector (1024,) | NULL | NULL |

Rule: `kind == "proof"` → `embedding_proof`; everything else → `embedding_stmt`.
`embedding_eq` is always NULL (E10_S03 reserved).

---

## 5. EmbedStats Dataclass Design

```python
@dataclass
class EmbedStats:
    paper_id: str
    chunks_processed: int
    chunks_skipped: int      # preamble load failed, or other per-chunk error
    elapsed_s: float
    embedder_version: str    # "bge-m3@<sha[:8]>"
    status: str              # "ok" | "fail"
    error: str | None        # populated on status="fail"
```

Written as one JSON line per paper to `var/arxmcp/ops/embed-stats.jsonl`
(append mode). The aggregate `embed_corpus` return is the collection of per-paper
stats.

---

## 6. Open Questions

### PRIMARY: E04_S01 dependency conflict

The milestone brief says `embed_corpus(lancedb_path, ...)` reads/writes
LanceDB. E04_S01 has not been built. **Resolution required before
implementation begins:**

- **Option A (recommended):** E03_S01 writes NPZ files; E04_S01 reads them.
  E03_S01 ships independent of E04_S01. This is the only path that does not
  create a hard sequential block.
- **Option B:** E04_S01 is built first (or simultaneously by a second agent).
  E03_S01 is blocked until `ingest/store.py` and `ingest/schema.py` exist.
- **Option C:** E03_S01 writes a minimal stub `ingest/store.py` that accepts
  embedding vectors and writes LanceDB. This bleeds E04_S01's scope into
  E03_S01 and risks schema drift.

Option A is the recommendation. The `lancedb_path` parameter to `embed_corpus`
can be accepted but ignored (or used only for the ops log path) until E04_S01
wires the write.

### BGE-M3 SHA currency

The SHA `5617a9f61b028005a4858fdac845db406aefb181` was fetched on 2026-05-07.
BAAI may push updates. Implementor must re-verify via the HF API at
implementation time and update the constant. The constant must be recorded in
the project security manifest per Threat 6.

### `torch` version floor

`torch>=2.0` is sufficient for CPU inference with `AutoModel`. If the team
later adds MPS (Apple Silicon GPU) support, `torch>=2.0` remains compatible.
No need to pin a specific minor version at Tier 0.

### `numpy` dependency

NPZ output requires `numpy`. If `numpy` is already transitively installed
(via `transformers` → `torch`), no explicit addition is needed. But it should
be in `pyproject.toml` explicitly if the NPZ approach is adopted.

---

## 7. External Writes the Implementation Will Require

1. **One-time HuggingFace model download (~2.3 GB):** `BAAI/bge-m3` full model
   weights (safetensors format). Cached under `~/.cache/huggingface/hub/` by
   the `transformers` library. This is substantially larger than the tokenizer-
   only download in E02_S03 (~5 MB). Download is triggered on first call to
   `AutoModel.from_pretrained(...)`. Must NOT be triggered at import time;
   model loading must be lazy (match `_get_tokenizer()` pattern in `chunker.py`).

2. **Per-paper embeddings (Option A / NPZ):**
   `var/arxmcp/corpus/embeddings/<paper_id>/embeddings.npz`
   Written atomically via PID+UUID tmp + `os.replace`. Contains two arrays:
   `embedding_stmt` (shape `(N_stmt_chunks, 1024)`) and `embedding_proof`
   (shape `(N_proof_chunks, 1024)`), plus a `chunk_ids` string array for
   alignment.

3. **Ops log:** `var/arxmcp/ops/embed-stats.jsonl` — one JSON line appended
   per paper run. Directory created on first write with `mkdir(parents=True,
   exist_ok=True)`.

4. **pyproject.toml update:** add `"torch>=2.0"` (and `"numpy>=1.24"` if NPZ
   approach adopted).
