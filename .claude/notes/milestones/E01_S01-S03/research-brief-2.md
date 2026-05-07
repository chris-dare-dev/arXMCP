# Research Brief 2 — E01_S01-S03
# Combined: repo skeleton + first paper fetch + 50-paper seed corpus

Researcher: agent-2 (parallel run)
Date: 2026-05-06

---

## 1. In-codebase context

### Applicable design notes

The following notes from `.claude/notes/` directly constrain this milestone:

**`02-architecture-overview.md`** — Defines the mono-repo component split:
`server/` (Streamable HTTP MCP server), `ingest/` (separate ingestion process),
`shim/` (stdio proxy), and the two-service Docker shape. Exact quote on separation:
> "The single most important separation here is **ingestion service vs MCP
> read-path server**. They are different processes."

The directory layout in S01 must anticipate this. The five directories named in the
acceptance criteria (`server/`, `ingest/`, `shim/`, `infra/`, `tests/`) map exactly
to these components plus the Docker/Makefile surface. The `tools/` subdirectory
for `fetch_one_paper.py` and `fetch_seed.py` is not named in `02` but is consistent
with "scripts that don't yet have a process home" — appropriate as a temporary
staging location for S02/S03 scripts before `ingest/` is real code.

**`03-ingestion-pipeline.md`** — The canonical on-disk layout is:
```
/var/arxmcp/
  corpus/raw/          # original .tex tarballs
  corpus/parsed/       # LaTeXML HTML5+MathML output
  ops/parser-failures/ # papers that failed all parsers
```
This is the layout S02 and S03 must write to. The `.gitignore` requirement for
`/var/arxmcp/` comes directly from this note.

Rate-limit contract (load-bearing quote):
> "Rate limit: 1 request per 3 seconds per IP, with explicit guidance to back off
> on 503. Hard ceiling."

Politeness header (load-bearing quote):
> "Politeness: include a descriptive User-Agent header (`arXMCP/0.1
> (mailto:owner@example.com)`) and respect 503 backoff."

The note also warns explicitly that for a 500K-paper backfill the `/e-print/`
endpoint is inadequate ("17 days continuous fetching — **Don't try this for the
seed**"), but for 50 papers S03 is in-scope and TOS-clean.

**`04-parsing-and-chunking.md`** — Parser priority order:
1. ar5iv HTML cache (primary) — `https://ar5iv.labs.arxiv.org/html/<arxiv_id>`
2. Local LaTeXML on `/e-print/` source (cache-miss)
3. Nougat on PDF (last resort — largely unmaintained as of late 2024)
4. Skip — log to `ops/parser-failures/`

For S02 and S03, the acceptance criteria specify LaTeXML directly (not via ar5iv),
so the implementer must run LaTeXML locally. The ar5iv path is optional pre-flight
but not required for this milestone. Banned tools (load-bearing quote):
> "Pure pypdf / pymupdf / pdfplumber: mangle math. **Banned from the parser chain.**"

Also: LaTeXML failure modes that must be handled in S03's fetch loop:
> "LaTeXML build error (missing class file) — Log; try Nougat"
> "LaTeXML hang (>5 min) — Subprocess kill; mark as parser-failure"

**`08-security-observability-ops.md`** — Docker deployment shape references two
services that map to `server/` and `ingest/`. The `infra/` directory must anticipate
the docker-compose structure shown in this note. LaTeXML subprocess isolation is
spelled out here (load-bearing for S03):
> "LaTeXML runs in a **subprocess with a hard timeout** (5 minutes)."
> "Subprocess runs as a **separate UID** (Docker user namespace, or rootless
> container with an unprivileged user inside)."
> "**Never** invoke LaTeXML inside the MCP server process itself."

The `restic` backup strategy references `/var/arxmcp/corpus/` and
`/var/arxmcp/index/` — informing layout but out of scope for S01-S03.

### Key constraints from `README.md` (hard stops)
1. No AWS S3 / no requester-pays buckets.
2. No forking existing arXiv-MCP repos.
3. Local-first / Docker-deployable; `var/arxmcp/` is the canonical path.
4. Math fidelity over coverage; PyPDF banned.
5. Politeness non-negotiable (3s/request, `mailto:` User-Agent, 503 backoff).

### Four target arXiv categories (from `01-mission-and-context.md`)
math.AG, math.NT, math-ph, hep-th. The README.md in S01 must list all four.

---

## 2. Prior decisions and lessons

### Git log — state of repo at research time
Five commits: `e9ce36f` (seed design notes), `7e3cd4f` (seed roadmap),
`5688ef9` (milestone-pipeline skill), `662243e` (bridge milestone-pipeline to plans/),
`953709e` (roadmap orchestrator skill). No source code has landed yet. The
repo root contains only `.claude/` and `ROADMAP.md`. This milestone is the
first code-landing event.

### Milestone state machine (`state.json`)
Phase is `research-running`. No prior briefs, no implementation, no critique.
`external_writes_authorized: false`. The pipeline is waiting for this brief and
its peer to drive research-complete.

### `milestone-pipeline` skill
The skill writes state to `.claude/notes/milestones/{ID}/state.json` and expects
research briefs at `.claude/notes/milestones/{ID}/research-brief-N.md`. The
`var/arxmcp/` path used by the corpus is **distinct** from the
`.claude/notes/milestones/` path used by the pipeline state machine —
no overlap or collision.

### `roadmap` skill
Plans are written under `plans/<slug>-roadmap.md`. The roadmap skill does not
interact with the `var/arxmcp/` corpus path; no conflict.

### Lessons implied by roadmap note caveats
`README.md` in `.claude/notes/` explicitly flags:
> "Repo URLs, project names, and protocol behaviors are reliable; **specific version
> numbers, exact pricing, exact rate limits, and current product status** should be
> verified against live docs before being committed to in code."

This applies directly to LaTeXML version pins and arXiv API behavior. Recommendation:
pin LaTeXML at `0.8.8` (confirmed current stable as of 2024-02-26) but include a
comment in the fetch script noting the version source.

### Potential conflict — FLAG
The milestone brief specifies `tools/seed-papers.txt` (flat file at repo root's
`tools/` subdirectory). The S01 acceptance criteria do **not** list `tools/` as a
directory to create. The implementer must create `tools/` in S02, not S01.
This is not a true conflict but an omission in S01's acceptance criteria — the
`tools/` directory should be created as part of S01 or explicitly noted as a
sub-task of S02.

---

## 3. External sources

### arXiv `/e-print/` endpoint contract
- **URL pattern:** `https://arxiv.org/e-print/<paper_id>`
- **Content-type behavior:** For multi-file submissions (most math papers), returns
  `Content-Type: application/x-eprint-tar` with `Content-Encoding: x-gzip` — a
  gzipped tar archive. For single-file submissions, returns a bare gzip file
  (`Content-Type: application/x-eprint`). The fetch script **must** inspect the
  Content-Type header to decide whether to `tar -xz` or plain `gzip -d`.
- **Rate limit:** 1 request per 3 seconds per IP (confirmed via
  `info.arxiv.org/help/api/tou.html`). 503 responses include a flow-control
  directive with a delay value; the script must read and honor the `Retry-After`
  header if present.
- **TOS:** Personal and research use is explicitly permitted. Do not serve downloaded
  content from your own servers. Local indexing is fine.
- **Recommendation:** Use `https://export.arxiv.org/e-print/<paper_id>` (the
  programmatic host) rather than `https://arxiv.org/e-print/<paper_id>`, consistent
  with arXiv's guidance to use `export.arxiv.org` for programmatic access.

### arXiv API — curating 50 math.AG papers
- **Search endpoint:** `http://export.arxiv.org/api/query?search_query=cat:math.AG&start=0&max_results=100&sortBy=submittedDate&sortOrder=descending`
- **Rate limit:** same 3-second politeness rule applies to the API endpoint.
- **Pagination:** `start` (0-based) and `max_results` (max 2000 per request);
  total accessible results capped at 30,000 per query.
- **OAI-PMH set for math.AG:** set spec is `math:math:AG` (confirmed via
  `oaipmh.arxiv.org/oai?verb=ListSets`). Relevant for S03 curation but OAI-PMH
  metadata-only (no .tex source).
- **Recommendation:** Use the arXiv API search endpoint to pull 100+ recent
  math.AG papers sorted by submission date descending; filter post-2015, inspect
  for `\usepackage` exotic chains manually or via heuristic (simple .tex count in
  tarball). Select 50 from that filtered set. This is faster and more targeted than
  OAI-PMH, which returns metadata only.

### LaTeXML 0.8.8 (current stable)
- **Version:** `0.8.8`, released 2024-02-26 (GitHub releases, confirmed).
- **Install:** `apt-get install latexml` (Debian/Ubuntu), `port install LaTeXML +mactex`
  (macOS MacPorts), `cpan LaTeXML` (cross-platform).
- **No official Docker image at `ghcr.io/arxiv/latexml` was found.** The
  `02-architecture-overview.md` reference to this image should be treated as
  aspirational/unverified. Use system Perl install for S02/S03.
- **Recommended invocation for HTML5+MathML:**
  ```
  latexmlc <paper.tex> --dest=<output.html> --format=html5
  ```
  The `--pmml` flag (Presentation MathML) is the default for html5 format.
  `latexmlc` is the combined pipeline (replaces `latexml` + `latexmlpost`).
- **Timeout:** must wrap in subprocess with 5-minute hard kill per
  `08-security-observability-ops.md`.
- **Exit code:** `latexmlc` exits 0 on success, non-zero on fatal parse failure.
  The presence of the output HTML file at `--dest` path is the canonical success
  signal (exit code alone is insufficient — LaTeXML can emit a partial HTML on
  some error conditions; check both exit code AND file size > 0).

### arXiv API for paper curation
The arXiv API (`export.arxiv.org/api/query`) supports `cat:math.AG` search,
returns Atom XML, can be sorted by `submittedDate`. The `arxiv` PyPI package
(`pip install arxiv`) wraps this API cleanly and handles pagination. Recommendation:
use the `arxiv` Python library rather than hand-rolling the Atom XML parser.

### `restic` backup (informational, out of scope for S01-S03)
`restic` (https://restic.net) is a Go binary, supports local/SFTP/B2/S3 backends,
content-deduplication, AES-256 encryption. Relevant only to `var/arxmcp/` layout
decisions (no backup tooling lands in this milestone). The `/var/arxmcp/cache/`
subtree is explicitly **not** backed up per `08-security-observability-ops.md`.

---

## Open questions

**(a) How to pick 50 "clean" math.AG papers.**
Recommendation: scripted from arXiv API, then human-filtered. Concretely:
1. Pull 200 recent math.AG papers (post-2015) via `export.arxiv.org/api/query`.
2. For each candidate, fetch the tarball and count `.sty` files and `.tex` files.
3. Filter to single `.tex` + ≤2 bundled `.sty` files. This heuristic catches
   "clean" papers without exotic class chains.
4. Pick 50 from the filtered set, biased toward post-2018 Annals/Duke-published
   papers (lower chance of unusual macro stacks).
The arXiv API query itself must be done with politeness throttling. Pure manual
curation would work for 50 but adds no reusable tooling; scripted is better because
the same heuristic will be reused in E11.

**(b) Where `var/arxmcp/` should live.**
It must be at the repository root (`./var/arxmcp/`), matching the `.gitignore`
entry `/var/arxmcp/`. This is confirmed by the acceptance criteria: "Tarball is
extracted under `var/arxmcp/corpus/raw/<paper_id>/`" — a relative path from repo
root. The Docker-compose volumes in `08-security-observability-ops.md` use
`/var/arxmcp/` as an absolute path on the host machine; those paths are injected at
runtime, not baked into the repo. The gitignored repo-root `var/` is the local
development path; the absolute `/var/arxmcp/` is the production host path. Both
are valid simultaneously — the Makefile `bootstrap` target should create the local
`var/arxmcp/` tree.

**(c) LaTeXML invocation flags for HTML5+MathML.**
Correct invocation:
```
latexmlc <paper.tex> --dest=<output_dir>/index.html --format=html5
```
Do not add `--javascript=mathjax` for the seed corpus — it pulls external JS and
the output is consumed by the chunker, not a browser. Output directory must exist
before invocation (`latexmlc` does not create it). Working directory during
invocation should be the extracted source directory so `\input{}` relative paths
resolve correctly.

**(d) How to detect "parse success" for the ≥45/50 gate.**
Recommendation: success = exit code 0 AND output file exists AND file size > 1 KB
AND the HTML contains at least one `<math` node. The 1 KB threshold catches empty
or stub HTML. The `<math` check confirms MathML was actually emitted (some
LaTeXML failures emit valid HTML but with plain text where equations should be).
A missing `<math` node on a math paper is a signal of parser degradation, not
success. Log both the exit code and the MathML node count in
`ops/parser-failures/seed.log` for every paper (success and failure), not just
failures — this establishes the baseline for E02.

---

## External writes the implementation will require

| type | target | why |
|---|---|---|
| HTTP GET | `https://export.arxiv.org/api/query?search_query=cat:math.AG&...` | Fetching paper metadata to curate the 50-paper seed list |
| HTTP GET (×50) | `https://export.arxiv.org/e-print/<paper_id>` for each of 50 papers | S03 seed corpus fetch — hits arXiv's network; must be gated on explicit Phase 4 external-write authorization. Each request must be separated by ≥3 seconds. |
| filesystem write | `./var/arxmcp/corpus/raw/<paper_id>/` (×50) | Extracted tarball contents — local disk only |
| filesystem write | `./var/arxmcp/corpus/parsed/<paper_id>/` (×50) | LaTeXML HTML5+MathML output — local disk only |
| filesystem write | `./var/arxmcp/ops/parser-failures/seed.log` | Parser failure log — local disk only |

Note: the 50 `/e-print/` fetches during S03 are the primary external network
dependency. At 3 seconds per request this is ≥150 seconds of wall-clock time,
plus LaTeXML parse time (5–60 seconds per paper). Estimated total wall-clock:
30–90 minutes. This must be gated — Phase 4 (Rectify) or the implementer must
explicitly authorize before executing.
