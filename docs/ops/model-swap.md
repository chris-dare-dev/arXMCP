# Model swap

Upgrade or change the embedder (BGE-M3) or the reranker
(bge-reranker-v2-m3) to a new commit SHA. Both models are pinned
by commit SHA per Threat 6 (`08-security-observability-ops.md` §
"Supply chain — model integrity"); a swap is therefore a
deliberate, audited change, not a silent dependency bump.

> Indexed from [`docs/ops/README.md`](README.md) #5.
> Related: E13_S06 model SHA-pinning protocol; the
> [`re-embed-runbook.md`](re-embed-runbook.md) handles the re-embed
> sweep AFTER the swap lands.

---

## Symptoms

This is a planned-change runbook, not a fire-fighting one. Triggers:

- Upstream model team publishes a new revision with a known fix
  (e.g., a math-tokenization improvement that helps math.NT recall).
- The current pinned SHA is no longer available on the Hugging Face
  Hub mirror (model lifecycle event).
- An eval regression on the existing model rules out the corpus
  side and points to the model weights themselves.

## Detection

- An ADR (in `.claude/docs/` or a follow-up issue) records the
  rationale for the swap. **No model swap should happen without an
  ADR.**
- The new SHA has been verified against the model card AND a
  safetensors-only download (no pickled `.bin`) per Threat 6.

## Steps

1. **Stage the new model in a scratch path** — do NOT overwrite
   the in-use model directory yet. The current daemon must continue
   serving on the old SHA while you stage.

   ```bash
   export NEW_SHA=<hf-commit-sha>
   export MODEL_DIR=/var/arxmcp/models/staged/bge-m3-$NEW_SHA
   mkdir -p "$MODEL_DIR"

   # Pin to commit SHA, safetensors only (Threat 6)
   huggingface-cli download BAAI/bge-m3 \
     --revision "$NEW_SHA" \
     --local-dir "$MODEL_DIR" \
     --include "*.safetensors" "*.json" "tokenizer*"
   ```

2. **Verify SHA + safetensors-only.** The download must contain
   ZERO `*.bin` / `*.pt` / `*.pickle` files.

   ```bash
   find "$MODEL_DIR" \( -name '*.bin' -o -name '*.pt' -o -name '*.pickle' \)
   # Expected: no output. Any hit blocks the swap.
   ```

3. **Update the SHA pin in `pyproject.toml` / `server/config.py`**
   (the exact location depends on which model — embedder lives in
   `server/query_encoder.py` and `ingest/embedder.py`; reranker in
   `server/retrieval/rerank.py`). Commit the SHA bump as a separate
   commit so the diff makes the audit clean.

4. **Re-embed the corpus.** A model-weight change invalidates every
   embedding vector in LanceDB. Run the
   [`re-embed-runbook.md`](re-embed-runbook.md) before promoting
   the new model to production traffic. The re-embed produces a
   new `corpus_version` per E04_S03.

5. **Run the eval gate.** Before flipping production, run the
   Tier-1 retrieval eval against the new corpus version:

   ```bash
   make eval --ndcg-min=0.80   # E07_S04 Tier-1 → Tier-2 gate
   ```

   If nDCG@5 regresses below the configured floor, do NOT promote;
   fall back to the previous `corpus_version` via
   [corpus-version rollback](corpus-rollback.md).

6. **Promote.** Update the `corpus_version` marker
   (`var/arxmcp/corpus-version.json`) to the new version and
   restart the daemon. The cache invalidates on the version bump
   per E04_S03.

   ```bash
   sudo systemctl restart arxmcp
   ```

## Verification

- `curl http://127.0.0.1:7733/readyz` returns 200 once the new
  model warms.
- `arxmcp_embed_calls_total{model="bge-m3", outcome="ok"}` is
  incrementing (the new model is serving queries).
- The eval gate output is committed at
  `.claude/docs/retrieval-quality-report.md` with the new
  `corpus_version` and SHA.

If anything is off after the swap, the rollback path is
[`corpus-rollback.md`](corpus-rollback.md) — the previous
LanceDB dataset version is still on disk thanks to MVCC.
