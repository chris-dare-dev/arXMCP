# tools/

One-off developer scripts. Not part of the production ingestion pipeline (that lives in [`ingest/`](../ingest/)).

| Script | Purpose | Lands in |
|---|---|---|
| `fetch_one_paper.py` | Fetch ONE math.AG paper via `/e-print/` and parse with LaTeXML — smoke test for the ingestion path | [E01_S02](../.claude/roadmap/epic-01-vertical-slice.md) |
| `curate_seed.py` | Pull math.AG candidates from the arXiv API and rank by `.tex`/`.sty` simplicity heuristic | [E01_S03](../.claude/roadmap/epic-01-vertical-slice.md) |
| `fetch_seed.py` | Walk `seed-papers.txt`, fetch each paper, run LaTeXML, log outcomes | [E01_S03](../.claude/roadmap/epic-01-vertical-slice.md) |
| `seed-papers.txt` | The 50 hand-curated math.AG arXiv IDs that form the Tier-0 seed corpus | [E01_S03](../.claude/roadmap/epic-01-vertical-slice.md) |
| `soundness_smoke.py` | Live-server soundness smoke: drives `tools/call lean_verify` over the real MCP wire (initialize → initialized → calls) and asserts the D-2 hardening — kernel positive control awards `proven-formal`, the AC-D.1 axiom canary is rejected, the mathlib control records toolchain + mathlib-rev provenance. Exit-coded for scripting | stage2/arx-d2 (WS-D D-2/D-4) |
| `prove_task.py` | D-6 proving-pipeline driver: KAT controls first (AC-D.8; escalation halts, exit 3), then one ProofTask → skeptic lane → prover cycles → faithfulness gate → schema-valid EvidenceBundle (always `publishable: false`). Lean wiring via `ARXMCP_LAKE_PATH` + `ARXMCP_LEAN_REPL_DIR`. Protocol: [`.claude/proving/README.md`](../.claude/proving/README.md) | stage2/arx-d3 (WS-D D-6) |
| `sign_bundle.py` | **Operator-only** D-3 sign-off surface — the ONLY sanctioned caller of `faithfulness.record_human_signoff`. The review is yours; the tool signs the bundle's faithfulness record (refuses failed gates) and emits the publishable `proven-formal` form via `orchestrator.make_publishable_bundle`. Pipeline automation must never invoke it | stage2/arx-d3 (WS-D D-3/D-6) |
| `exploration/` | WS-E exploration pipeline v0 engine — 3-12-month window scan (Atom + cite_neighbors + open-problem sources) emitting an envelope-wrapped proposed-notebook-manifest for operator confirm. Driver: `python -m tools.exploration.propose`; pipeline home: [`.claude/exploration/README.md`](../.claude/exploration/README.md) | stage2/arx-e1 |
| `lean_verify_smoke.py` | Drive ONE mathlib-importing snippet through the `lean_verify` MCP tool against a RUNNING server over the real Streamable-HTTP wire | Stage-2 arx-d1 (WS-D D-1) |

## Usage

Before running any of these, export your contact email (used in the `User-Agent` per arXiv TOS):

```sh
export ARXMCP_CONTACT_EMAIL=you@example.com
```

LaTeXML 0.8.x must be on `PATH`:

```sh
brew install latexml          # macOS via Homebrew
sudo apt install latexml      # Debian / Ubuntu
```

The Docker-image path (`brucemiller/latexml`) is canonical for production ingestion ([E02_S02](../.claude/roadmap/epic-02-parser-foundation.md)) but adds friction for one-off dev scripts. Use system install here.
