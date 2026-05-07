# tools/

One-off developer scripts. Not part of the production ingestion pipeline (that lives in [`ingest/`](../ingest/)).

| Script | Purpose | Lands in |
|---|---|---|
| `fetch_one_paper.py` | Fetch ONE math.AG paper via `/e-print/` and parse with LaTeXML — smoke test for the ingestion path | [E01_S02](../.claude/roadmap/epic-01-vertical-slice.md) |
| `curate_seed.py` | Pull math.AG candidates from the arXiv API and rank by `.tex`/`.sty` simplicity heuristic | [E01_S03](../.claude/roadmap/epic-01-vertical-slice.md) |
| `fetch_seed.py` | Walk `seed-papers.txt`, fetch each paper, run LaTeXML, log outcomes | [E01_S03](../.claude/roadmap/epic-01-vertical-slice.md) |
| `seed-papers.txt` | The 50 hand-curated math.AG arXiv IDs that form the Tier-0 seed corpus | [E01_S03](../.claude/roadmap/epic-01-vertical-slice.md) |

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
