# /explore

Run the WS-E exploration pipeline v0: scan a 3-12-month arXiv window for a
stated topic, cross-reference open-problem sources, and emit an
envelope-wrapped proposed-notebook-manifest for OPERATOR CONFIRMATION.

Usage:
```
/explore "<topic title>" --category <cat> [--months N | --window-from X --window-to Y]
```

**Propose→confirm, strictly (AC-E.1).** This command NEVER ingests, never
creates a notebook, never mutates any store. It ends by presenting the
manifest to the operator. Full protocol, channel notes, snapshot-refresh
procedures, and the third-repo extraction triggers:
[`.claude/exploration/README.md`](../exploration/README.md) — read it first.

## Step 1 — Gather inputs

Ask (or take from flags): topic title/description, arXiv categories
(first = scan category), window (3-12 months), optional anchors (paper ids
already known to matter), optional dedup target (an existing notebook's
`papers.txt`), optional keywords.

If open-problem snapshots under `var/exploration/sources/` are missing or
stale (>30 days by `retrieved_at`), offer to refresh them per the README's
per-source procedures (agent-side fetches; record `retrieved_at`).

## Step 2 — Run the engine

```sh
uv run python -m tools.exploration.propose \
  --topic-title "<title>" --category <cat> --months <N> \
  [--keywords "..."] [--anchors id,id] \
  [--sources-dir var/exploration/sources] \
  [--dedup-papers-file var/arxmcp/notebooks/<slug>/papers.txt] \
  [--email $ARXMCP_CONTACT_EMAIL] \
  --out var/exploration/proposals/<slug>-<date>.json
```

Non-zero exit = the manifest failed WS-E conformance or contract
validation; report the error verbatim, do not "fix" the manifest by hand.

## Step 3 — Present for confirmation

Summarize for the operator: paper count + the per-paper `source_citation`
lines, textbook proposals, window, `graph_status`, open-problem source hit
counts, dedup exclusions. Then STOP and ask which entries to confirm.

Only after explicit confirmation, walk the README's "Operator confirm"
steps (notebook_init → notebook_fetch → notebook_ingest). Never run them
unprompted.
