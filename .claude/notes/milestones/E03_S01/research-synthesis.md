# E03_S01 Research Synthesis — `ingest/embedder.py` dual-column BGE-M3 encoder

**Sources:** `research-brief-1.md` (Sonnet-A), `research-brief-2.md` (Sonnet-B)
**Status:** convergent — both researchers reached the same recommendations
on every load-bearing decision below.
**Written:** 2026-05-07

---

## Resolved decisions (both briefs agree)

### D1. Break the E04_S01 circular dependency with NPZ-first output

The roadmap's stated dependency `E03_S01 ↔ E04_S01` is mutual, so neither
can literally block on the other. The agreed resolution: E03_S01 ships
**independent** of E04_S01 by writing per-paper embeddings to a parallel
NPZ store at:

```
var/arxmcp/corpus/embeddings/<paper_id>/embeddings.npz
```

containing three NumPy arrays:

- `chunk_ids: array<str>` — chunk_ids in the order their vectors appear
- `embedding_stmt: float32[N_stmt, 1024]` — L2-normalized
- `embedding_proof: float32[N_proof, 1024]` — L2-normalized

When E04_S01 lands, `ingest/store.py` reads these NPZ files alongside
`chunk_manifest.json` to build the LanceDB rows. No LanceDB import in
`ingest/embedder.py`.

The `embed_corpus` signature in the milestone brief (`lancedb_path,
corpus_path, batch_size`) is preserved, but the `lancedb_path` parameter
is treated as advisory until E04_S01 wires the LanceDB write — it is
**only** used to derive the ops-log path.

### D2. Pinned model commit SHA

```python
BGE_M3_COMMIT_SHA = "5617a9f61b028005a4858fdac845db406aefb181"
```

Source: `https://huggingface.co/api/models/BAAI/bge-m3` `sha` field. This
is the HEAD of `BAAI/bge-m3` `main` (last commit message: "Update MIRACL
evaluation results of BGE-M3", 2024-07-03; verified 2026-05-07 by both
researchers). The `embedder_version` formatted string written to ops logs
and (later) to LanceDB is `f"bge-m3@{BGE_M3_COMMIT_SHA[:8]}"` →
`"bge-m3@5617a9f6"`.

### D3. Load form (Threat 6 compliant)

```python
from transformers import AutoModel, AutoTokenizer
import torch
import torch.nn.functional as F

model = AutoModel.from_pretrained(
    "BAAI/bge-m3",
    revision=BGE_M3_COMMIT_SHA,
    trust_remote_code=False,
)
tokenizer = AutoTokenizer.from_pretrained(
    "BAAI/bge-m3",
    revision=BGE_M3_COMMIT_SHA,
)
model.eval()
```

`revision=BGE_M3_COMMIT_SHA` pins to the SHA-verified weights;
`trust_remote_code=False` rejects custom modeling code; safetensors is
preferred via the `safetensors>=0.4` dependency. Loading uses
`AutoModel`, not `FlagEmbedding` — keeping the dependency surface
minimal.

### D4. CLS pooling + explicit L2 normalization

```python
with torch.no_grad():
    encoded = tokenizer(
        texts,
        padding=True,
        truncation=True,
        max_length=512,
        return_tensors="pt",
    )
    output = model(**encoded)
    embeddings = output.last_hidden_state[:, 0, :]   # CLS token
    embeddings = F.normalize(embeddings, p=2, dim=-1)  # MUST call explicitly
```

**Critical:** raw `AutoModel` does **not** auto-normalize — unlike
`BGEM3FlagModel.encode()`. The acceptance criterion "All vectors shape
(1024,) and L2-normalized" is only satisfied by the explicit
`F.normalize` call. `model.eval()` is required to disable XLM-RoBERTa
dropout (BP1 byte-stable across runs).

### D5. Routing table

| `kind` | column written |
|---|---|
| `"proof"` | `embedding_proof` |
| `"stmt"`, `"section"`, `"definition"`, and every other kind the chunker emits (`lemma`, `proposition`, `corollary`, `remark`, `example`, `claim`, `conjecture`, etc.) | `embedding_stmt` |
| (always) | `embedding_eq = NULL` (E10_S03 reserved) |

Implementation: `column = "embedding_proof" if kind == "proof" else "embedding_stmt"`. This routing is future-proof against new kind values
the chunker may emit without an embedder change.

### D6. F3 fallback (preamble missing)

```python
preamble = load_preamble(paper_id)
preamble_text = preamble.preamble_text if preamble is not None else ""
embed_input = preamble_text + "\n\n" + chunk.body_text if preamble_text else chunk.body_text
```

Mirrors the chunker's `_compute_chunk_id` fallback. When `preamble_ref`
is `None` on the chunk, `load_preamble` returns `None` and the embedder
encodes `body_text` alone.

### D7. NFC normalization

`unicodedata.normalize("NFC", embed_input)` before tokenization. The
preamble is already NFC (applied at extraction time), but `body_text` is
stored raw by the chunker (NFC is hash-only). NFC at embed time matches
the tokenizer's discipline (`tokenizer.py` line 128) and protects BP1.

### D8. Token budget: warn + truncate

The chunker caps `body_text` at 512 (stmt) or 448 (proof) BGE-M3 tokens,
but the preamble is uncapped. If `preamble + "\n\n" + body_text` exceeds
512 tokens, log at WARNING and truncate via the tokenizer's
`truncation=True, max_length=512` path. **Never raise.** Track truncation
counts in `EmbedStats.truncated_count` so over-length papers surface in
ops logs.

### D9. Per-paper failure isolation

```python
PER_PAPER_FAILURE_EXCEPTIONS = (OSError, ValueError, FileNotFoundError)
```

Mirrors `chunker.py` and `preamble.py`. Wrap the per-paper loop body;
log the failure to `var/arxmcp/ops/embed-stats.jsonl` with
`status: "fail"`; continue to the next paper. Programmer bugs
(`AttributeError`, `TypeError`, `RuntimeError` from torch internals)
propagate.

### D10. Atomic writes for NPZ

Mirror `_write_preamble_json` in `ingest/preamble.py`:

```python
tmp = out_path.with_suffix(
    f"{out_path.suffix}.{os.getpid()}.{uuid.uuid4().hex[:8]}.tmp"
)
try:
    np.savez(tmp, ...)
    os.replace(tmp, out_path)
finally:
    with contextlib.suppress(OSError):
        tmp.unlink(missing_ok=True)
```

The `embed-stats.jsonl` ops log uses append mode — non-atomic but
acceptable (mirrors `chunk.log` / `preamble.log`).

### D11. CPU thread parallelism

```python
torch.set_num_threads(os.cpu_count() or 4)
```

Default torch CPU thread count can be 1 on some configurations; explicit
setting eliminates the surprise. CPU-only mode by design — never call
`.cuda()` or `.to("cuda")`.

### D12. `pyproject.toml` updates

Add to `dependencies`:

```toml
"torch>=2.0",
"safetensors>=0.4",
"numpy>=1.24",
```

`numpy` is required for the NPZ store; `torch` is required for inference
(currently absent — chunker comment incorrectly says "torch is NOT
required"); `safetensors` enforces Threat 6's "no .bin / pickle weights"
requirement at the dependency level.

The chunker comment about torch must be revised to acknowledge that
embedder.py introduces the dependency.

---

## Open questions (deferred to implementation)

- **CPU-specific torch wheel index:** the standard PyPI `torch` is fine
  for CPU and pulls ~1.5 GB of wheels. A future infra ticket may switch
  to `--extra-index-url https://download.pytorch.org/whl/cpu` to drop
  CUDA wheels. Not a blocker for E03_S01.
- **Tokenizer revision pinning:** `ingest/chunker.py` currently calls
  `AutoTokenizer.from_pretrained("BAAI/bge-m3")` with no `revision=`.
  This is a **pre-existing** Threat 6 violation for the tokenizer. The
  embedder must pin its tokenizer load with `revision=BGE_M3_COMMIT_SHA`;
  fixing the chunker's tokenizer load is out of scope for E03_S01 but
  worth filing as a follow-up.

---

## External writes the implementation will require

| Path | Event | Notes |
|---|---|---|
| `var/arxmcp/corpus/embeddings/<paper_id>/embeddings.npz` | per-paper run | NPZ via tmp + os.replace |
| `var/arxmcp/ops/embed-stats.jsonl` | per `embed_corpus` call | append-mode JSON line |
| `~/.cache/huggingface/hub/` | first model load | one-time ~2.3 GB BGE-M3 safetensors download |
| `pyproject.toml` | implementation | adds `torch>=2.0`, `safetensors>=0.4`, `numpy>=1.24` |

The HF cache write is a network-dependent first run; subsequent runs are
fully offline-capable when `HF_HUB_OFFLINE=1` is set.
