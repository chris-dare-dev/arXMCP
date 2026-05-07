# Research Synthesis — E01_S01-S03

Merged from `research-brief-1.md` and `research-brief-2.md`. Where the briefs agree, quoted once. Where they diverged, both positions are surfaced and one is picked with reasoning.

---

## 1. Applicable design notes (consensus)

The implementer must read these before writing any code. Citations below name the file and the section that constrains this milestone.

| Note | What it dictates for E01_S01-S03 |
|---|---|
| `.claude/notes/02-architecture-overview.md` § Component responsibilities | The directory split (`server/`, `ingest/`, `shim/`, `infra/`, `tests/`) maps directly to the production component split. Quote: *"The single most important separation here is **ingestion service vs MCP read-path server**. They are different processes."* |
| `.claude/notes/03-ingestion-pipeline.md` § Source 3 + § What gets stored on disk | Politeness contract and `/var/arxmcp/` on-disk layout. Both load-bearing for S02/S03. |
| `.claude/notes/04-parsing-and-chunking.md` § Parser fallback chain + § Tools we considered and rejected | LaTeXML is the parser; PyPDF/pymupdf/pdfplumber are **banned** even as scaffolding. |
| `.claude/notes/08-security-observability-ops.md` § Docker deployment + § Threat 3 | Two-service compose target; LaTeXML subprocess sandboxing is **deferred to E02_S02** but the comment trail starts now. |
| `.claude/notes/09-feature-priorities.md` § Tier 0 | Defines the exact scope boundary — Tier-1 work (ar5iv-first, theorem+proof pairing, hybrid retrieval) does **not** belong in this milestone. |

## 2. Load-bearing quotes (verbatim — do not paraphrase in code or comments)

From `03-ingestion-pipeline.md` § Source 3:

> "Rate limit: 1 request per 3 seconds per IP, with explicit guidance to back off on 503. Hard ceiling."

> "Politeness: include a descriptive `User-Agent` header (`arXMCP/0.1 (mailto:owner@example.com)`) and respect 503 backoff."

From `04-parsing-and-chunking.md` § Tools we considered and rejected:

> "Pure pypdf / pymupdf / pdfplumber: mangle math. **Banned from the parser chain.** Useful only for low-stakes metadata fallback."

From `02-architecture-overview.md`:

> "The single most important separation here is **ingestion service vs MCP read-path server**. They are different processes."

From `08-security-observability-ops.md` (LaTeXML hardening — informs E02 not E01, but the comment trail starts here):

> "LaTeXML runs in a **subprocess with a hard timeout** (5 minutes)."
> "Subprocess runs as a **separate UID** (Docker user namespace, or rootless container with an unprivileged user inside)."
> "**Never** invoke LaTeXML inside the MCP server process itself."

## 3. The on-disk layout (consensus)

From `03-ingestion-pipeline.md` § What gets stored on disk:

```
var/arxmcp/                 # at the repo root during dev; /var/arxmcp/ in production Docker
  corpus/
    raw/                    # original .tex tarballs
    parsed/                 # LaTeXML HTML5+MathML output
    chunks/                 # canonical chunk JSON (E01_S04+, not this milestone)
  index/                    # LanceDB + Kùzu (E01_S06+, not this milestone)
  cache/                    # ar5iv (E02+, not this milestone)
  ops/
    ingestion.log
    parser-failures/        # papers that failed all parsers
```

The repo-root `var/arxmcp/` is the dev path. `.gitignore` excludes the whole tree. The Docker production absolute `/var/arxmcp/` is mounted at runtime — that's E14, not this milestone.

## 4. Decisions where the briefs diverged

### D1 — LaTeXML install: Docker image vs system Perl

- **R1** recommended **Docker image** (`brucemiller/latexml` from Docker Hub) for reproducibility and consistency with the eventual `infra/Dockerfile.ingest`.
- **R2** recommended **system install** (`brew install latexml` on macOS, `apt-get install latexml` on Linux) and noted no official `ghcr.io/arxiv/latexml` image was found.

**Decision: system install for the S02/S03 smoke-test scripts; Docker remains canonical for E02_S02 production ingestion.** Reasoning: this milestone delivers developer scripts under `tools/`, not the production parser. A `docker run` wrapper in a smoke-test adds friction (volume mounts, image pull, UID mapping on macOS) without buying anything at scale of 50 papers. The implementer should add a comment in `tools/fetch_seed.py` that says: *"LaTeXML invoked via system install for dev simplicity; production E02_S02 will use the Docker path with subprocess UID isolation per `08-security-observability-ops.md`."* If the implementer's machine doesn't have LaTeXML, the `Makefile bootstrap` target should print a clear `brew install latexml` / `apt install latexml` instruction.

### D2 — arXiv host: `arxiv.org` vs `export.arxiv.org`

- **R1** used `https://arxiv.org/e-print/<paper_id>`.
- **R2** recommended `https://export.arxiv.org/e-print/<paper_id>` (the documented programmatic host) and noted arXiv guidance to use `export.arxiv.org` for programmatic access.

**Decision: use `export.arxiv.org` for both `/e-print/` and `/api/query`.** R2's reasoning is sound: arXiv has documented `export.arxiv.org` as the programmatic hostname; using it is forward-compatible and reduces the chance of being treated as casual web traffic. Update both the S02 single-paper fetch and the S03 loop accordingly.

### D3 — How to curate the 50 math.AG papers

- **R1** recommended **manual curation** from arXiv listings — a static `tools/seed-papers.txt` with 50 IDs.
- **R2** recommended **scripted prefilter** via `export.arxiv.org/api/query?search_query=cat:math.AG&...`, then heuristic filter (single `.tex` + ≤2 bundled `.sty` files), then human selection of final 50. Notes the same approach is reusable in E11.

**Decision: R2's hybrid approach.** Reasoning: writing a 30-line `tools/curate_seed.py` that pulls 200 candidates and prints them ranked by `.tex`/`.sty` count buys reusable tooling for E11 (where 200K-paper ingestion will need similar filtering) and avoids 50 manual web-page visits. **However**, the human is still in the loop for the final 50: the script outputs candidates; the human commits the final list to `tools/seed-papers.txt`. **Crucially, the curation script's HTTP calls also count as `/e-print/`-style external writes** to the arXiv API and must use the same User-Agent + 3s sleep contract.

### D4 — Parse-success detection for the ≥45/50 acceptance gate

- **R1** did not propose a precise rule beyond "LaTeXML build error → log; try Nougat" (from `04-parsing-and-chunking.md`).
- **R2** proposed: `success = exit_code == 0 AND output_file_exists AND file_size > 1 KB AND html.contains("<math")`.

**Decision: R2's rule, with full-corpus logging.** Reasoning: exit code alone is insufficient — LaTeXML emits partial HTML on some failures. The `<math` presence check guards against the failure mode where LaTeXML produces valid HTML but with plain text where equations should be (silent math loss is the worst possible failure for this project). **Log all 50 outcomes** (success and failure) to `var/arxmcp/ops/parser-failures/seed.log` — call it `seed.log` per the brief, but it doubles as the baseline measurement E02 will improve against.

### D5 — `tools/` directory creation timing

- **R1** treated `tools/` as implicitly created during S02.
- **R2** flagged this as an omission in S01's acceptance criteria — `tools/` is not in the list of directories S01 must create, but S02's deliverables live there.

**Decision: S01 explicitly creates `tools/` with a placeholder `README.md`.** Reasoning: the absence is an omission, not a constraint. Adding `tools/` to S01 is one extra `mkdir` and a 5-line README. Treating it as part of S01 keeps the dependency graph cleaner: S02 starts with all directory scaffolding present.

### D6 — `mailto:` value in User-Agent

- **R1** recommended a `ARXMCP_CONTACT_EMAIL` environment variable so a personal email isn't hard-coded in committed code.
- **R2** did not address.

**Decision: R1's env var.** Implementation: the fetch scripts read `os.environ.get("ARXMCP_CONTACT_EMAIL")` and exit with a clear error if unset. The `Makefile bootstrap` target reminds the user to export it. The committed code has the placeholder `arXMCP/0.1 (mailto:${ARXMCP_CONTACT_EMAIL})` but never the literal email.

### D7 — `/e-print/` Content-Type handling

- **R1** did not address.
- **R2** noted: multi-file submissions return `application/x-eprint-tar` (gzipped tar); single-file submissions return bare gzip (`application/x-eprint`). Script must inspect Content-Type before deciding `tar -xz` vs `gunzip`.

**Decision: include R2's caveat in S02's script.** A switch on Content-Type (or alternatively, file-magic detection after download) handles both cases. Without this, single-file submissions silently extract to a non-tar blob.

### D8 — 503 backoff strategy

- **R1** proposed exponential backoff starting at 30s.
- **R2** proposed reading the `Retry-After` header if present.

**Decision: combined.** Honor `Retry-After` (header value in seconds) if the response carries it; otherwise exponential backoff starting at 30s, capped at 5 minutes. Log every 503 to `seed.log` with the chosen sleep interval.

## 5. Open questions for the implementer

1. **Specific math.AG paper for S02 smoke test.** R1 floated `2307.01156` as a candidate but flagged it as needing fetch-time verification. **Resolution: defer to fetch-time.** The implementer fetches a candidate, inspects the tarball (single `.tex`, no exotic `.sty` chain), and only commits the ID once it parses cleanly. The committed `tools/seed-papers.txt` line for S02's paper goes in last (after the script works on it).

2. **`Makefile bootstrap` target scope.** The acceptance criteria require `make help` to list `bootstrap`, `test`, `up`, `ingest`. **Resolution:** at S01 these are placeholder targets — `bootstrap` runs `pip install -e .[dev]` and `mkdir -p var/arxmcp/corpus/{raw,parsed,chunks} var/arxmcp/ops/parser-failures`; the rest are stubs that print "not yet implemented" pointing at their respective epics (E01_S08 for `up`, E11 for `ingest` proper).

3. **`pyproject.toml` shape.** Acceptance says Python ≥3.11 and ruff + pytest pinned. **Resolution:** root `pyproject.toml` with `[project]` table (name, version, requires-python="\>=3.11"), `[project.optional-dependencies]` block with `dev = ["ruff>=0.5", "pytest>=8.0"]`, and a `[tool.ruff]` block with `line-length = 100`. Per-component `pyproject.toml` files are not needed at S01; the roadmap leaves room to split later.

4. **No timestamps in committed text.** Per `02-architecture-overview.md` § Determinism contract: tool results have no timestamps. The `seed.log` written under `var/arxmcp/ops/` is gitignored, so timestamps there are fine — but any committed file (e.g. `tools/seed-papers.txt`, `README.md`) must not include them.

## 6. External writes the implementation will require

This is the deduped union from both briefs. **Phase 4 (Rectify) reads this list and gates execution at the external-write boundary.**

| type | target | why | gate? |
|---|---|---|---|
| HTTP GET (×~200) | `https://export.arxiv.org/api/query?search_query=cat:math.AG&...` | S03 paper curation prefilter (D3); 3s sleep, descriptive User-Agent | yes |
| HTTP GET (×1) | `https://export.arxiv.org/e-print/<paper_id>` | S02 single-paper smoke test fetch | yes |
| HTTP GET (×50) | `https://export.arxiv.org/e-print/<paper_id>` for each of 50 papers | S03 seed-corpus fetch loop. ≥150s of sleeps + 5–60s/paper LaTeXML = ~30–90 minutes wall-clock total | **yes — biggest one** |
| filesystem write | `./var/arxmcp/corpus/raw/<paper_id>/` (×~50) | extracted tarball contents — local disk only | no (local only) |
| filesystem write | `./var/arxmcp/corpus/parsed/<paper_id>/` (×~50) | LaTeXML HTML5+MathML output — local disk only | no (local only) |
| filesystem write | `./var/arxmcp/ops/parser-failures/seed.log` | log of all 50 outcomes | no (local only) |
| git push | `origin main` | NOT required by milestone brief; orchestrator + user discretion | yes if attempted |

**Net network exposure:** ~250 HTTP GETs to `export.arxiv.org` over ~30–90 minutes, all under the politeness contract. No AWS, no third-party APIs, no infra mutations.

## 7. What's explicitly NOT in scope

These are E02+ concerns and **must not** appear in this milestone's commits:

- **ar5iv cache lookup.** `03-ingestion-pipeline.md` § Source 6: *"Use ar5iv as a cache, not a fallback."* That's E02_S01.
- **LaTeXML subprocess UID sandboxing / network restriction.** That's E02_S02 + Threat 3 in `08-security-observability-ops.md`. Add a code comment referencing E02_S02; do not implement.
- **OAI-PMH delta channel.** That's E11.
- **Nougat fallback parser.** That's E02. (Note: `04-parsing-and-chunking.md` says Nougat is *"largely unmaintained as of late 2024"* — even E02 will treat it as last-resort.)
- **Embedding, LanceDB, MCP server, shim.** Those are E01_S04 through E01_S10.
- **Citation graph (Kùzu, INSPIRE, OpenAlex).** That's E09.

## 8. Three-commit shape the implementer should produce

Per the milestone brief's combined exit criteria:

1. `feat(infra): repo skeleton with mono-repo layout` — addresses S01 acceptance criteria. Touches: top-level dirs, `pyproject.toml`, `Makefile`, root `README.md`, `.gitignore`, `tools/README.md`.
2. `feat(ingest): /e-print/ + LaTeXML for one math.AG paper` — addresses S02. Touches: `tools/fetch_one_paper.py`, `tools/seed-papers.txt` (one ID), unit test for the parse-success detector.
3. `feat(ingest): 50-paper math.AG seed corpus` — addresses S03. Touches: `tools/curate_seed.py` (the API-prefilter helper), `tools/fetch_seed.py` (the 50-paper loop with politeness + 503 backoff), `tools/seed-papers.txt` (50 IDs), wall-clock figure documented in `tools/README.md`.

Each commit must run `make test` (which at this milestone is `ruff check . && pytest -q`) cleanly before being authored. Co-author trailer required. GPG signing on. No `--no-verify`.
