# Research Brief 2 — E03_S01: `ingest/embedder.py` dual-column BGE-M3 encoder

**Milestone:** E03_S01  
**Researcher:** Sonnet-B (parallel)  
**Date:** 2026-05-07  
**Word count target:** ≤1500  

---

## 1. In-codebase context

### What E04_S01 will provide (and what it won't yet)

E04_S01 (`ingest/store.py` + `ingest/schema.py`) defines the canonical LanceDB
table at `var/arxmcp/index/lancedb/chunks`. Its schema includes
`embedding_stmt`, `embedding_proof`, and `embedding_eq` as nullable
`fixed_size_list<float32>[1024]` columns, and exposes:

```
write_chunks(chunks: list[ChunkRecord], embeddings: EmbedRecord,
             lancedb_path: str) -> int
```

**E04_S01 is listed as a dependency of E03_S01 in the milestone brief, but
E04_S01's own dependency list also includes E03_S01 — a circular dependency.**
The roadmap text states: `E04_S01 dependencies: E02_S04, E03_S01` and
`E03_S01 dependencies: E02_S01, E02_S02, E02_S04, E04_S01`. Neither can be
built first in strict dependency order.

### The existing chunk artifact layout (pre-E04)

`ingest/chunker.py` `_chunk_paper_impl` writes:

- `var/arxmcp/corpus/chunks/<paper_id>/<sha256[:16]>.json` — one per chunk
- `var/arxmcp/corpus/chunks/<paper_id>/chunk_manifest.json` — index of all
  chunk_ids and kinds for the paper

Each JSON is the `ChunkRecord.to_dict()` payload: `body_text`, `body_tokens`,
`chunk_id`, `chunker_version`, `kind`, `paper_id`, `preamble_ref`,
`section_path`, `theorem_label`, `theorem_name`, `truncated`. Note: no
`embedding_*` fields exist on `ChunkRecord` — those are LanceDB-only columns
from E04_S01.

### Preamble access path

`ingest/preamble.py` `load_preamble(paper_id: str) -> PreambleDoc | None`
reads `var/arxmcp/corpus/preamble/<paper_id>/preamble.json`. `PreambleDoc`
carries `preamble_text` (the `"\n".join(macros)` string) and `preamble_hash`
(first 16 hex chars of `SHA-256(preamble_text)`).

The embedder's input for each chunk is:
`preamble_text + "\n\n" + body_text`
where `preamble_text` is fetched via `load_preamble(chunk.paper_id)` and the
`preamble_hash` is compared against `chunk.preamble_ref` to verify consistency.
When `preamble_ref` is `None` (F3 fallback from E02_S02), the embedder must
embed `body_text` alone with no preamble prefix.

### `TOKENIZER_VERSION` precedent for `BGE_M3_COMMIT_SHA`

`ingest/tokenizer.py` defines:
```python
TOKENIZER_VERSION = "v1.0"
```
The parallel constant for the embedder should be:
```python
BGE_M3_COMMIT_SHA = "5617a9f61b028005a4858fdac845db406aefb181"
```
This is the HEAD of `BAAI/bge-m3` main as of 2024-07-03 (confirmed via HF
API: `sha = "5617a9f61b028005a4858fdac845db406aefb181"`). The
`embedder_version` field in stats and the LanceDB `embedder_version` column
should be formed as `f"bge-m3@{BGE_M3_COMMIT_SHA[:8]}"` (e.g.
`"bge-m3@5617a9f6"`), mirroring the `chunker_version = "v1.0"` format.

### `pyproject.toml` dependency gap

`pyproject.toml` currently lists:
```toml
"transformers>=4.40",
```
with the comment: "Loads tokenizer vocab only (~5 MB cached); NOT full model
weights, so torch is NOT required."

This is no longer true once E03_S01 ships. The embedder requires full model
inference. Two additions are needed:

1. `torch` must be added to dependencies — the comment in `pyproject.toml`
   explicitly calls out its absence. Add `"torch>=2.0"` or make it an optional
   dep group `[embed]` with a loud `ImportError` if `torch` is absent at
   embedder import time.
2. The `safetensors` format is required by Threat 6 mitigations — add
   `"safetensors>=0.4"`.

**Recommendation:** add both to the main `dependencies` list (not optional)
because E03_S01 is Tier-0 and CPU-only; the ~2.3 GB weight download happens
once and is cached by HuggingFace. Tests that don't need actual embedding
should mock the model.

---

## 2. Prior decisions and lessons

### E04_S01 dependency — recommendation

**Ship E03_S01 independent of E04_S01** by writing embeddings to a parallel
per-paper NPZ store at `var/arxmcp/corpus/embeddings/<paper_id>/embeddings.npz`
(one NPZ per paper, keys `chunk_ids`, `embedding_stmt`, `embedding_proof`). The
LanceDB integration can be wired in E04_S01 by reading these NPZ files. This
decouples the two milestones, is crash-resumable (skip papers whose NPZ is
already present), and requires zero LanceDB dependency at E03_S01 time.

Alternatively the brief could declare E04_S01 a strict prerequisite and block —
but that produces a deadlock since E04_S01 also lists E03_S01 as a dependency.
The only clean resolution is to ship one of the two first. The NPZ-first
approach is preferred: embeddings are dense arrays best stored as NPZ anyway,
and the LanceDB writer (E04_S01) can read them as its input source.

### F3 fix — preamble_ref=None on extraction failure

When `load_preamble(paper_id)` returns `None` (extraction failed in E02_S02),
the embedder must treat `preamble_text` as `""` and embed `body_text` alone.
This matches the `_compute_chunk_id` fallback in `chunker.py`:
```python
preamble_text = preamble_doc.preamble_text if preamble_doc is not None else ""
```
The embedder must follow the identical pattern.

### F6 — NFC normalization

The chunker stores `body_text` without NFC normalization (by design; the NFC
step is applied only to the `chunk_id` hash input). The embedder must apply
`unicodedata.normalize("NFC", preamble_text + "\n\n" + body_text)` before
encoding, both for cross-host reproducibility and to match the token budget
check convention. The preamble is already NFC (applied at extraction time by
`preamble.py`).

### Threat 6 — model-weights pinning

From `08-security-observability-ops.md` § Threat 6:
> "Pin model commit SHAs in configuration (`BAAI/bge-m3@<sha>`), not just
> names. Use `safetensors` format only; refuse `.bin` / pickle weights. Run
> model loads with `trust_remote_code=False` unless explicitly opted in."

The pinned load call must therefore be:
```python
AutoModel.from_pretrained(
    "BAAI/bge-m3",
    revision=BGE_M3_COMMIT_SHA,
    trust_remote_code=False,
)
```
The tokenizer load in `ingest/chunker.py` currently uses a floating tag
(`AutoTokenizer.from_pretrained("BAAI/bge-m3")` with no revision). That is a
pre-existing violation of Threat 6 for the tokenizer; E03_S01 must not repeat
it.

### Atomic-write pattern (from `preamble.py`)

The per-paper NPZ (or stats JSONL) write should use the same atomic pattern
established in `ingest/preamble.py` `_write_preamble_json`:
```python
tmp = out_path.with_suffix(
    f"{out_path.suffix}.{os.getpid()}.{uuid.uuid4().hex[:8]}.tmp"
)
try:
    # write to tmp
    os.replace(tmp, out_path)
finally:
    with contextlib.suppress(OSError):
        tmp.unlink(missing_ok=True)
```

### `PER_PAPER_FAILURE_EXCEPTIONS` pattern

Embed failures on a single paper (bad preamble JSON, I/O error, token count
overflow) must not abort the batch. Wrap per-paper work in the same
`(OSError, ValueError, FileNotFoundError)` envelope, log to
`var/arxmcp/ops/parser-failures/embed.log` in TSV format (mirroring
`chunk.log` and `preamble.log`), and continue to the next paper.

### Token-budget enforcement at embed time

`ingest/chunker.py` `_truncate_to_token_budget` already caps `body_text` at
512 tokens (stmt) or 448 tokens (proof). The combined embedding input
`preamble_text + "\n\n" + body_text` can therefore still exceed 512 tokens
if the preamble itself is long. The embedder must check the token count of the
full input, warn (do not raise), and truncate to 512 tokens before passing to
the model. Use the same offset-mapping-based slice technique from the chunker
(never an encode/decode round-trip) to avoid mutating the string.

---

## 3. External sources

### BGE-M3 model card findings

- **Output dimension:** 1024 (confirmed via `config.json` `hidden_size: 1024`)
- **Architecture:** XLM-RoBERTa (24 layers, 16 heads, 250K vocab)
- **Max token length:** 8192 (but the project caps at 512 by chunker design)
- **Current HEAD SHA:** `5617a9f61b028005a4858fdac845db406aefb181`
  (as of 2024-07-03; last commit "Update MIRACL evaluation results of BGE-M3")

### Recommended call style: AutoModel, not FlagEmbedding

The brief requires CPU-only inference with no external library beyond
`transformers` + `torch`. Do not add `FlagEmbedding` as a dependency. The
correct call sequence using raw `transformers`:

```python
from transformers import AutoTokenizer, AutoModel
import torch
import torch.nn.functional as F

tokenizer = AutoTokenizer.from_pretrained(
    "BAAI/bge-m3", revision=BGE_M3_COMMIT_SHA
)
model = AutoModel.from_pretrained(
    "BAAI/bge-m3",
    revision=BGE_M3_COMMIT_SHA,
    trust_remote_code=False,
)
model.eval()

with torch.no_grad():
    encoded = tokenizer(
        texts,
        padding=True,
        truncation=True,
        max_length=512,
        return_tensors="pt",
    )
    output = model(**encoded)
    # CLS token pooling (standard for XLM-RoBERTa sentence embeddings)
    embeddings = output.last_hidden_state[:, 0, :]
    # L2 normalization — NOT applied by default in raw AutoModel
    embeddings = F.normalize(embeddings, p=2, dim=-1)
```

**Critical:** unlike `FlagEmbedding`'s `BGEM3FlagModel.encode()` which returns
pre-normalized `dense_vecs`, raw `AutoModel` does NOT apply L2 normalization
by default. The embedder must call `F.normalize(embeddings, p=2, dim=-1)`
explicitly. The acceptance criterion "All vectors shape (1024,) and L2-
normalized" can only be satisfied by explicit normalization in the embedder.

### `torch.no_grad()` and `model.eval()` are required

`model.eval()` disables dropout layers (XLM-RoBERTa has
`attention_probs_dropout_prob: 0.1` and `hidden_dropout_prob: 0.1`). Without
`model.eval()`, the same input will produce different embeddings on each
forward pass, breaking BP1 determinism. `torch.no_grad()` prevents gradient
accumulation (irrelevant for correctness but required for CPU memory
efficiency).

### Column routing

| `kind` value | `embedding_stmt` | `embedding_proof` | `embedding_eq` |
|---|---|---|---|
| `"stmt"` | non-null (1024,) L2-norm | null | null |
| `"proof"` | null | non-null (1024,) L2-norm | null |
| `"section"` | non-null (1024,) L2-norm | null | null |
| `"definition"` | non-null (1024,) L2-norm | null | null |
| any other | non-null in `embedding_stmt` | null | null |

The brief says `kind="section"` or `"definition"` → `embedding_stmt`. For
correctness, treat any `kind` that is not `"proof"` as routing to
`embedding_stmt`. This future-proofs against new kind values (`"lemma"`,
`"remark"`, `"example"`, etc.) that the chunker emits but the milestone brief
does not enumerate.

---

## 4. Open questions

**Primary: the E04_S01 circular dependency.** The brief lists E04_S01 as a
dependency of E03_S01 and vice-versa. The implementer must choose one of:

1. **Recommended:** E03_S01 ships first, writes embeddings to per-paper NPZ
   files. E04_S01 reads the NPZ during `write_chunks`. No LanceDB import in
   `ingest/embedder.py`.
2. **Deferred:** E03_S01 blocks on E04_S01; E04_S01 ships first with null
   embedding columns; E03_S01 back-fills. This is the sequence the E04_S01
   text implies ("E03_S01 writes NULL" for `embedding_eq`). But it requires
   E04_S01 to be partially usable without E03_S01, which contradicts its
   stated dependency on E03_S01.

**Secondary:** the `torch` version pin. `pyproject.toml` currently omits
`torch`. Adding `"torch>=2.0"` to main dependencies will pull in ~1.5 GB of
wheels on a CPU build. The implementer should confirm whether the project wants
a bare `"torch"` (latest) or a CPU-specific extra index URL
(`--extra-index-url https://download.pytorch.org/whl/cpu`).

**Tertiary:** the BGE-M3 commit SHA should be verified at implementation time.
The SHA `5617a9f61b028005a4858fdac845db406aefb181` was current as of 2024-07-03.
The project security manifest (referenced in the brief as the authoritative
source) should record the verified SHA; if that manifest does not yet exist,
E03_S01 must create it.

---

## 5. External writes the implementation will require

| Path | Event | Notes |
|---|---|---|
| `var/arxmcp/corpus/embeddings/<paper_id>/embeddings.npz` | Per-paper embedding run | NPZ with `chunk_ids`, `embedding_stmt`, `embedding_proof` arrays |
| `var/arxmcp/ops/embed-stats.jsonl` | Each `embed_corpus()` call | Appended JSON line with `paper_id`, `chunk_count`, `elapsed_s`, `embedder_version` |
| `var/arxmcp/ops/parser-failures/embed.log` | Per-paper failure | TSV row matching `chunk.log` / `preamble.log` format |
| HuggingFace cache (`~/.cache/huggingface/`) | First model load | ~2.3 GB BGE-M3 safetensors weights; one-time download |
| HuggingFace cache (tokenizer) | First tokenizer load | ~5 MB; already cached if chunker was run first |

The HF model download is the only external (network) write and happens once per
machine. All subsequent runs use the cached weights. The `revision=BGE_M3_COMMIT_SHA`
pin ensures the cached artifact is the exact SHA-verified checkpoint.
