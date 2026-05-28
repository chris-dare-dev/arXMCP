---
name: uv-lock-transitive-major-version-downgrade
description: Adding a [extras] dep to pyproject.toml can silently force a transitive major-version downgrade of an existing direct dep — check uv.lock diff for version line changes, not just package additions
metadata:
  type: feedback
---

When a milestone adds a new `[project.optional-dependencies].<extra>` entry, the
uv.lock churn is not just "new packages added" — it may force a DOWNGRADE of
an existing direct dep that another lib pins more tightly.

m5 added `mineru[pipeline]>=3.2.0,<4` to `[pdf]` extras. MinerU pins
`transformers<5`, so the entire project's transformers got downgraded
5.8.0 → 4.57.6 in `uv.lock`. The downgrade also removed `typer`, `rich`,
`shellingham`, `markdown-it-py`, `mdurl` (transformers v5 transitive deps
that v4 doesn't pull). The implementation summary did NOT mention this —
operator would discover it via `uv run python -c "import transformers;
print(transformers.__version__)"`.

**Why:** `transformers` is a core dep for the BGE-M3 embedder + reranker.
Major-version downgrades change `from_pretrained` semantics, model loading,
and tokenizer behavior in subtle ways. `requires_model` tests are skipped
by default, so the cold-path BGE code is not exercised on the downgrade.

**How to apply:** When critiquing any milestone that touches
`[project.optional-dependencies]` in pyproject.toml:
1. `git diff <range> -- uv.lock | grep "^[-+]version = "` — check version-line churn.
2. `git diff <range> -- uv.lock | grep "^-name = "` — check for any packages REMOVED.
3. For each removed package, cross-check whether it was a transitive dep of
   a project direct dep — its removal implies that direct dep was downgraded.
4. Flag HIGH if any project direct dep was downgraded across a major version.
5. Look for `requires_model`-style markers that skip the affected code path
   by default — those gaps mean the downgrade is unverified.

Related: [[bp1-description-vs-handler-validator-drift]] is the same shape
(implementation summary claims X but X is not actually tested).
