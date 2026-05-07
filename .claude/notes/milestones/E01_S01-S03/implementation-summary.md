# Implementation Summary — E01_S01-S03

**One-line:** Stood up the mono-repo skeleton, the shared `/e-print/` + LaTeXML library, the single-paper smoke test, and the 50-paper fetch loop. All offline-testable surface lands with 53 passing unit tests; the actual arXiv fetches are gated on Phase 4 user authorization.

**Commit range:** `953709e..c486b26` (3 commits on `main`).

```
8633cc6 feat(infra): scaffold mono-repo layout for v1 components
8889b61 feat(ingest): /e-print/ + LaTeXML smoke test for one math.AG paper
c486b26 feat(ingest): 50-paper math.AG seed corpus fetch loop
```

## Acceptance criteria status

### E01_S01 — Repo skeleton

| Criterion | Status | Evidence |
|---|---|---|
| `server/`, `ingest/`, `shim/`, `infra/`, `tests/` directories with placeholder markers | met | `git ls-tree HEAD -- server/ ingest/ shim/ infra/ tests/` shows `__init__.py` and/or `README.md` in each |
| Top-level `pyproject.toml` with Python ≥3.11 + ruff + pytest pinned | met | `pyproject.toml` requires-python = ">=3.11"; dev deps ruff>=0.5, pytest>=8.0 |
| `make help` lists `bootstrap`, `test`, `up`, `ingest` | met | `make help` output verified during build |
| `.gitignore` excludes `.venv/`, `__pycache__/`, `/var/arxmcp/` | met | already in pre-existing `.gitignore`; no change required |
| Root `README.md` links to `.claude/notes/README.md` and lists 4 categories | met | linked + lists math.AG, math.NT, math-ph, hep-th |

### E01_S02 — Single-paper smoke test

| Criterion | Status | Evidence |
|---|---|---|
| `tools/fetch_one_paper.py` downloads via `arXMCP/0.1 (mailto:...)` User-Agent | met (code) | `build_user_agent()` formats per-spec; tested in `tests/test_arxiv_fetch.py::TestUserAgent` |
| Tarball extracted under `var/arxmcp/corpus/raw/<paper_id>/` | met (code) | `fetch_eprint()` writes to that path; safe-extract guard against path-traversal |
| LaTeXML 0.8.x runs and emits HTML5+MathML to `var/arxmcp/corpus/parsed/<paper_id>/` | met (code) | `parse_with_latexml()` invokes `latexmlc --format=html5` with cwd at source dir; `--javascript=mathjax` deliberately not added |
| Script exits cleanly on the chosen paper | **deferred to Phase 4** | requires actual network fetch + LaTeXML execution; gated as external write |
| Chosen paper ID committed in `tools/seed-papers.txt` | met | `2307.01156` committed as smoke-test target with explicit "verify before relying" comment |

### E01_S03 — 50-paper seed corpus

| Criterion | Status | Evidence |
|---|---|---|
| `tools/seed-papers.txt` lists 50 arXiv IDs from math.AG | **partially met** | file exists with header + 1 ID; the 50-ID expansion requires running `tools/curate_seed.py` (a Phase 4 external write) followed by human review |
| `tools/fetch_seed.py` walks the list, fetches each, writes raw + parsed to `var/arxmcp/corpus/` | met (code) | `process_paper()` does fetch + parse; tested via `tests/test_fetch_seed.py::TestSeedListReader` for the loop's input layer |
| 3-second sleep between requests + 503 backoff | met (code) | `time.sleep(POLITENESS_SLEEP_SECONDS)` between calls; `fetch_with_backoff` honors Retry-After with 30s floor, 5min cap |
| ≥45/50 successful parses, failures listed in `var/arxmcp/ops/parser-failures/seed.log` | **deferred to Phase 4** | `write_log` covers all 50 outcomes (success + failure) — exit code gates on the threshold; requires actual run to verify |
| Total wall-clock documented | met (code) | `total_elapsed` logged in `seed.log`; expected 30–90 min per research synthesis |

## New / changed test paths

- `tests/test_arxiv_fetch.py` — 37 tests covering User-Agent, paper-id regex, Content-Type dispatch, Retry-After parsing, the four-part parse-success rule (silent-math-loss guard), `find_main_tex` heuristic.
- `tests/test_fetch_seed.py` — 16 tests covering seed-list reader (blanks/comments), outcome log format, query-URL builder, Atom feed parsing, candidate filter.

Total: 53 tests, all green via `ruff check . && python3.13 -m pytest`.

## Commands to verify locally

```sh
# Lint + tests (deterministic, no network):
ruff check .
python3.13 -m pytest

# Make targets exist and `make help` lists bootstrap/test/up/ingest:
make help
```

## External writes the orchestrator must authorize (Phase 4)

| type | target | why | blocking |
|---|---|---|---|
| HTTP GET (×1) | `https://export.arxiv.org/api/query?search_query=cat:math.AG&max_results=200&...` | Run `curate_seed.py` to populate `seed-papers.txt` candidates for human review | yes |
| HTTP GET (×1) | `https://export.arxiv.org/e-print/2307.01156` (or replacement) | E01_S02 smoke test — verify the chosen paper ID actually parses cleanly | yes |
| HTTP GET (×50) | `https://export.arxiv.org/e-print/<paper_id>` for each of 50 papers | E01_S03 main run; ~30–90 minutes wall-clock; honors politeness contract by construction | **yes — biggest one** |
| filesystem write | `./var/arxmcp/corpus/raw/<paper_id>/` (×~50) | extracted source — local disk, gitignored | no |
| filesystem write | `./var/arxmcp/corpus/parsed/<paper_id>/` (×~50) | LaTeXML output — local disk, gitignored | no |
| filesystem write | `./var/arxmcp/ops/parser-failures/seed.log` | outcome log — local disk, gitignored | no |
| git push | `origin main` | NOT required by the milestone brief; orchestrator + user discretion | yes if attempted |

**Note on the seed-papers.txt expansion:** the human-review step between `curate_seed.py` (which proposes candidates) and the final 50-ID list (which gets committed) is the implementer's intentional choice. Auto-populating the file with 50 unverified arXiv IDs from training knowledge would risk fabricated IDs and is worse than gating on a quick human pass through the candidate TSV.

## Deviations from the milestone brief / research synthesis

1. **`tools/__init__.py` was added** to enable `from tools.arxiv_fetch import ...` from both the CLI scripts and the tests. Not in the brief; necessary because the package layout the synthesis assumed wasn't quite right for `tools/` as a real Python package. Cost: one empty file.

2. **`make test` invokes plain `ruff check .` and `pytest`**, not pinned to a specific Python version. The system Python on the dev machine was 3.9.6 (below the 3.11 pin); `python3.13` worked. The Makefile leaves the python binary discovery to the user/dev environment — this is the standard pattern, and the pyproject.toml's `requires-python` will catch a too-old install at `pip install` time. Documented implicitly via the bootstrap target.

3. **`.claude/` excluded from ruff** in `pyproject.toml`. The `.claude/skills/` directory contains pre-existing skill-author Python that fails ruff (datetime.UTC, B007, F541) — those are tooling files committed under earlier commits, not application code. Excluding `.claude/` is the right scope; the synthesis didn't mention this.

4. **No specific 50 paper IDs committed.** The synthesis recommended a scripted prefilter then human pick of 50; I did not commit a hand-rolled list of 50 IDs from training knowledge because the risk of fabricated arXiv IDs (paper IDs that look right but don't resolve) outweighs the convenience. Phase 4 will run `curate_seed.py` and a human review fills `seed-papers.txt`. This is the cost of the safety stance.

## Phase 3 routing hint

The diff touches `.gitignore` (no — already had the entries), `pyproject.toml` (yes), `Makefile` (yes), but **no `infra/` or `Dockerfile` or CI workflow files**. Per `phase-critique.md` the **infra-safety critic should NOT fire** — the conditional regex `^(infra/|\.github/workflows/|Dockerfile|docker-compose(\.[^/]+)?\.ya?ml|Makefile)` matches `Makefile`, so it WILL fire on Makefile. That's appropriate — the bootstrap target creates filesystem dirs and the test target invokes external tools, both worth a quick infra-safety pass.
