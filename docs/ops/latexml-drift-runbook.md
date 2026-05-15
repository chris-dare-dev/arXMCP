# LaTeXML drift runbook

**Use when:** the daily `latexml-drift-check.sh` cron job exits
non-zero, writes the sentinel file
`var/arxmcp/ops/drift-detected.flag`, or the
`arxmcp_latexml_drift_detected_total` counter is observed to have
incremented (via `/metrics` once E14 wires production exposure).

**Why drift matters:** a LaTeXML version bump (e.g. `0.8.7` →
`0.8.8`) silently changes the rendered MathML — whitespace,
attribute ordering, or even structural element insertions
(`<mrow>` wrappers, etc.). The equation TED index built by E10_S03
stores per-equation `mathml_tree_json` derived from the *old*
LaTeXML's output. Once the operator's LaTeXML differs, freshly
rendered query MathML will TED-compare against trees built from a
different rendering — silent retrieval degradation, no error.

---

## Recovery procedure

### Step 1 — Confirm the LaTeXML version bump is intentional

```bash
latexmlc --VERSION
# latexmlc (LaTeXML version 0.8.x)
```

If you did NOT intend to upgrade, downgrade
(`brew install latexml@0.8.8` / pin your Docker tag) and re-run
`ops/cron/latexml-drift-check.sh`. The sentinel should clear and
the counter should stop incrementing.

If the upgrade IS intentional, continue.

### Step 2 — Record the new version

```bash
echo "latexml $(latexmlc --VERSION 2>&1 | head -1)" > ops/latexml-version.txt
git add ops/latexml-version.txt
```

This file is the source-of-truth for "which LaTeXML version
the corpus was last re-rendered against." Operators inspecting the
repo can correlate `git log -p ops/latexml-version.txt` against
the fixture commits.

### Step 3 — Re-render every paper's MathML

The corpus's stored MathML is now stale relative to your LaTeXML
binary. Re-render every paper:

```bash
# 3a. Re-extract equation atoms from each paper's LaTeXML HTML.
#     This re-runs the chunker's HTML walk + the equation atom
#     extractor (E10_S03b). The result is fresh `mathml`,
#     `presentation_latex`, `context_sentence` columns on the
#     equations LanceDB table.
for paper_id in $(ls var/arxmcp/corpus/parsed/); do
    python -m ingest.extract_equations "$paper_id"
done

# 3b. Rebuild the tree-JSON column from the new MathML (E10_S03).
#     This re-parses each row's `mathml` into a zss.Node and writes
#     `mathml_tree_json`. Idempotent per row.
python -m ingest.index_equations

# 3c. Re-embed the equation rows whose embedding_eq is now stale.
#     The embedding_eq column was computed over the OLD
#     `presentation_latex + context_sentence` strings; if those
#     changed (typically they don't, but it's possible), re-embed.
#     The embedder skips rows where embedding_eq is already
#     populated — to force re-embed, NULL out the column first:
#     `lancedb.connect(...).open_table("equations").update(
#         where="paper_id IS NOT NULL",
#         values={"embedding_eq": None}
#     )` then run:
python -m ingest.embed_equations
```

**Timing estimates:**

| Corpus size | Step 3a + 3b wall time | Step 3c (BGE-M3 CPU) |
|---|---|---|
| 50-paper seed | ~5 min  (assuming HTML is available) | ~10 s |
| 200K-paper full corpus | ~10 hours | ~10 hours CPU / ~45 min GPU |

The 50-paper seed numbers are the project's v1 reality; the 200K
numbers are Tier-4 planning per the design constitution
(`.claude/notes/05-storage-and-indexing.md`).

### Step 4 — Verify the rebuilt index

```bash
/Users/chris.dare/Library/Python/3.9/bin/uv run python -m pytest tests/test_equation_index.py
```

All tests pass (existing AC coverage from E10_S03 + E10_S03b).

### Step 5 — Regenerate drift-check baselines

After the corpus is rebuilt, the drift-check fixtures themselves
need new baselines pinned to the post-upgrade LaTeXML output —
otherwise the next daily cron will keep alerting:

```bash
python -m ops.drift_check --update-fixtures
git add tests/fixtures/latexml-drift/*.expected.mathml
git commit -m "chore(ops): rebaseline latexml-drift fixtures after $LATEXML_VERSION upgrade"
```

This is analogous to `pytest --update-tool-schema-hash` — a
deliberate operator action that captures the new ground truth.

### Step 6 — Clear the sentinel + restart the server

```bash
rm -f var/arxmcp/ops/drift-detected.flag
# If the MCP server was running, restart it to pick up the new
# equations table state.
make up   # or whatever the operator's deployment harness uses
```

### Step 7 — Confirm the next cron run is clean

Watch for the next daily cron firing (or trigger manually):

```bash
ops/cron/latexml-drift-check.sh
# Expected output:
# ok: 5 fixture(s) match baseline
```

Exit code 0 + no sentinel file = recovery complete.

---

## What this runbook does NOT cover

- **Automatic reindex on drift detection.** v1 is manual on purpose
  — re-rendering the corpus is expensive (~10 hours at Tier-4) and
  should require human confirmation. Auto-reindex is deferred to
  a future ops automation milestone (E14).
- **LaTeXML version pinning in the container image.** Pinning a
  specific LaTeXML version in the project's Docker base is an
  E11 scope concern (production ingest).
- **Detecting drift on tikz-cd output.** `tikz-cd` renders as SVG
  with embedded MathML labels; the v1 drift detector intentionally
  skips it because the SVG output is high-noise. Future ops
  hardening may add tikz-cd as a separate drift class.
- **Cross-process Prometheus exposure of the counter.** At v1 the
  drift signal is the cron's stderr ERROR + sentinel file + exit
  code. Production `/metrics` exposure of
  `arxmcp_latexml_drift_detected_total` is deferred to E14.

---

## See also

- `ops/cron/latexml-drift-check.sh` — the cron entry point.
- `ops/drift_check.py` — the Python module holding all logic.
- `tests/fixtures/latexml-drift/README.md` — fixture management +
  the cron / pytest dual-role.
- `.claude/docs/ops/cron-jobs.md` — internal registry of automated
  jobs (this drift check + any future scheduled tasks).
- `.claude/notes/milestones/E10_S04/research-synthesis.md` —
  design rationale for the extracted-`<math>` diff strategy,
  fixture selection (no `tikz-cd`), and counter exposure
  deferrals.
