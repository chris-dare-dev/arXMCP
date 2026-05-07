# Research Brief 1 — E01_S01-S03
# Combined: repo skeleton + first paper fetch + 50-paper seed corpus

---

## 1. In-codebase context

### Applicable design notes

| File | Relevance |
|---|---|
| `03-ingestion-pipeline.md` | Authoritative on `/e-print/` rate limits, politeness contract, and `var/arxmcp/` layout |
| `04-parsing-and-chunking.md` | LaTeXML as primary parser; banned tools; fallback chain |
| `02-architecture-overview.md` | `ingest/` vs `server/` separation; no logic in the skeleton |
| `08-security-observability-ops.md` | Docker two-service target; Threat 3 (LaTeXML sandbox, E02 concern) |
| `09-feature-priorities.md` | Tier 0 checklist; exact scope boundary for S01–S03 |

### Directory layout canon

`03-ingestion-pipeline.md` § "What gets stored on disk" is the canonical layout:

```
/var/arxmcp/
  corpus/
    raw/                   # original .tex tarballs (kept for re-parse)
    parsed/                # LaTeXML HTML5+MathML output (cached)
    chunks/                # canonical chunk JSON
  index/
    lancedb/ …
    kuzu/ …
  cache/
    ar5iv/ …
  ops/
    ingestion.log
    parser-failures/       # papers that failed all parsers
```

The milestone brief's acceptance criteria reference this exactly:
`var/arxmcp/corpus/raw/<paper_id>/`, `var/arxmcp/corpus/parsed/<paper_id>/`,
`var/arxmcp/ops/parser-failures/seed.log`. The `var/` prefix is the
project-root-relative path; the full path in production is `/var/arxmcp/`.
The `.gitignore` must exclude `/var/arxmcp/` (not `var/arxmcp/`) since the
path from repo root is `var/arxmcp/`.

**FLAG — potential ambiguity:** E01_S01 acceptance says `.gitignore` should
exclude `/var/arxmcp/` — the leading `/` makes this an absolute-path ignore
under Git, which ignores only a `var/arxmcp/` at the repo root, not at
`/var/arxmcp/` on the filesystem. This is correct behavior (the corpus lives
at `<repo-root>/var/arxmcp/` during dev) but the implementer should verify
Git treats the pattern as rooted at the repo root, which it does.

### Politeness contract (load-bearing)

`03-ingestion-pipeline.md` § Source 3:

> "Rate limit: 1 request per 3 seconds per IP, with explicit guidance to back
> off on 503. Hard ceiling."

> "Politeness: include a descriptive `User-Agent` header
> (`arXMCP/0.1 (mailto:owner@example.com)`) and respect 503 backoff."

The milestone brief quotes this verbatim. The `fetch_seed.py` loop must
`time.sleep(3)` between every `/e-print/` request, not just between failures.
503 backoff should be exponential starting at 30s (matching `08-security-observability-ops.md`
§ Failure modes: "Pause `/e-print/` fetcher; queue for retry next cycle").

### LaTeXML role in S02/S03

`04-parsing-and-chunking.md` § Parser fallback chain step 2:

> "Local LaTeXML on `/e-print/` source (cache-miss path). …The most complete
> LaTeX→XML/HTML5+MathML converter in existence. Slow (5–60 seconds per paper).
> Coverage on hep-th drops to ~80% because of exotic `.sty` files; for math.AG
> it's closer to 95%."

For 50 math.AG papers the 45/50 acceptance criterion aligns with the ~95%
coverage estimate. At this milestone LaTeXML is run directly against extracted
source — no ar5iv cache (that is an E02 concern), no subprocess sandboxing
(Threat 3 is also E02). The S02/S03 scripts are developer tooling, not
production ingestion path.

### Banned parsers

`04-parsing-and-chunking.md` § Tools we considered and rejected:

> "Pure pypdf / pymupdf / pdfplumber: mangle math. **Banned from the parser
> chain.** Useful only for low-stakes metadata fallback."

The E02_S07 CI guard that enforces this ban does not exist yet at E01, but
the implementation must not introduce any of these imports even as scaffolding.

### Four target categories

`README.md` § "What arXMCP is": math.AG, math.NT, math-ph, hep-th. The seed
corpus is math.AG only (cleanest source; `09-feature-priorities.md` § Tier 0:
"50 papers from one subject (math.AG is cleanest)").

### `tools/` vs `ingest/` location

The epic file `epic-01-vertical-slice.md` S02 acceptance says:
`tools/fetch_one_paper.py` and `tools/seed-papers.txt`. This is a `tools/`
directory at the repo root, distinct from `ingest/` (which houses the
production ingestion process). The `tools/` directory is developer-facing
one-off scripts. This is consistent with `epic-11-ingestion-at-scale.md`
which places the production fetcher at `ingest/sources/eprint.py`.

---

## 2. Prior decisions and lessons

### Git log

Five commits; all are docs and skills setup. Zero source code exists. The
repo root contains only `ROADMAP.md`. There is no `server/`, `ingest/`,
`shim/`, `infra/`, or `tests/` directory yet. S01 creates all of these from
scratch.

### No LESSONS.md or DECISIONS.md

None found. The design notes in `.claude/notes/` are the only prior-decision
record.

### Skills constraint on directory layout

The `milestone-pipeline` skill stores milestone state at
`.claude/notes/milestones/{ID}/state.json`. The `state.json` for this
milestone already exists at
`.claude/notes/milestones/E01_S01-S03/state.json` (phase: `research-running`).
The skill expects research briefs at
`.claude/notes/milestones/{ID}/research-brief-N.md` — exactly where this file
lives. No conflict with the repo skeleton layout.

The `roadmap` skill writes plans to `plans/<slug>-roadmap.md` (see
`skills/roadmap/references/phase-materialize.md`). The arXMCP roadmap lives
at `ROADMAP.md` (repo root), not `plans/`. This discrepancy does not affect
E01_S01-S03 but is noted for future milestone work.

### ar5iv as primary cache — scope boundary

`03-ingestion-pipeline.md` § Source 6 says: "Use ar5iv as a cache, not a
fallback. This saves weeks of CPU time on initial corpus ingestion." But
`09-feature-priorities.md` Tier 0 says only "Manual one-paper ingestion path:
download `/e-print/` source for a hand-picked paper, run LaTeXML locally."
The ar5iv-first path is Tier 1 (E02). At E01_S01-S03, the implementer
**must not** build the ar5iv client — that's E02_S01. The S02/S03 scripts
use `/e-print/` + local LaTeXML only.

### `08-security-observability-ops.md` Threat 3 and sandboxing

LaTeXML sandboxing (subprocess UID, no network, filesystem whitelist) is an
E02_S02 requirement. At E01_S03 the LaTeXML invocation is unsandboxed — this
is acceptable because S02/S03 are developer scripts running on trusted arXiv
source, not production ingestion. The implementer should add a comment
referencing E02_S02 so the debt is visible.

---

## 3. External sources

### arXiv `/e-print/` endpoint contract

- Endpoint: `https://arxiv.org/e-print/<paper_id>` — returns a `.tar.gz`
  (or occasionally a single `.gz` `.tex` file for old papers).
- TOS: `https://info.arxiv.org/help/api/tou.html` — "Limit your requests to
  no more than 1 per 3 seconds." Automated access must include a descriptive
  `User-Agent`.
- Bulk data page: `https://info.arxiv.org/help/bulk_data.html` — explicitly
  states `/e-print/` is not for bulk download; for seed use Academic Torrents
  (E11_S04). For 50 papers, `/e-print/` is within TOS.
- Response: HTTP 200 with `Content-Type: application/x-tar` or
  `application/gzip`. Paper IDs can be new-style (`YYMM.NNNNN`) or old-style
  (`subject/NNNNNNN`). The acceptance criteria for S02 uses only post-2010
  papers so new-style IDs only.
- 503: transient rate-limit or maintenance. Must backoff before retry. 404
  means the paper ID does not exist or has been withdrawn.

### LaTeXML 0.8.x install mechanics

`10-references-and-prior-art.md` lists: `https://github.com/brucemiller/LaTeXML`
and `https://math.nist.gov/~BMiller/LaTeXML/`.

Key install facts (verified against LaTeXML docs, knowledge cutoff Aug 2025):

- **Perl-based.** LaTeXML is a Perl package. It is NOT a Python package.
  Install via CPAN (`cpan LaTeXML`) or system package manager.
- **System packages:** `apt install latexml` on Debian/Ubuntu; `brew install
  latexml` on macOS via Homebrew. These typically ship 0.8.x.
- **Docker image:** `brucemiller/latexml` on Docker Hub. This is the cleanest
  path for reproducible installs and is consistent with the project's
  local-first/Docker-deployable target.
- **Invocation:** `latexml --dest=<output.xml> <input.tex>` then
  `latexmlpost --dest=<output.html> --format=html5 --mathtex <output.xml>`.
  Or the single-pass `latexml --dest=<output.html5> --format=html5 <input.tex>`.
- **Version:** `latexml --version`. The acceptance criteria require 0.8.x or
  newer. Current stable (as of early 2026) is in the 0.8.7+ range.

The implementer must decide between:
1. System install (`brew install latexml` for macOS dev)
2. Docker image (`docker run --rm brucemiller/latexml latexml ...`)

Recommendation: **Docker image** for both S02 and S03. It avoids Perl/CPAN
configuration drift, is consistent with the `infra/` Docker-first target, and
makes the CI/CD path straightforward. The `infra/Dockerfile.ingest` (E02_S02)
will also use it. The dev script can shell out to `docker run --rm
-v <source_dir>:/work -v <output_dir>:/out brucemiller/latexml latexml ...`.

### OAI-PMH as official delta channel

`03-ingestion-pipeline.md` § Source 2: "This is the durable, TOS-clean way
to know what's new. Don't try to scrape the arxiv.org listings page; OAI-PMH
is the supported channel." Endpoint: `http://export.arxiv.org/oai2`. This is
an E11 concern, not E01.

---

## Open questions

The implementer must resolve these before writing code:

1. **Which specific math.AG paper for S02?** The acceptance criteria say "post-2010,
   single .tex file, no exotic .sty chain." A concrete recommendation:
   `2307.01156` (Hironaka, math.AG, 2023, single-file, clean amsthm usage) is
   a reasonable starting point, but the implementer must verify by fetching it
   and checking for `.sty` files in the tarball before committing it to
   `tools/seed-papers.txt`. Alternatively, any Bourbaki-style expository
   paper from math.AG post-2020 will typically be clean.

2. **LaTeXML install path:** Docker image vs system package vs Perl CPAN.
   Recommendation is Docker image (see §3 above). If Docker adds friction
   during interactive dev, `brew install latexml` is acceptable for the
   S02/S03 scripts with a note that the Docker path is canonical for CI/E02.

3. **`tools/` at repo root vs under `ingest/`?** The epic file is explicit:
   `tools/fetch_one_paper.py` and `tools/seed-papers.txt` at repo root.
   This is the correct location. `ingest/` is for the production ingestion
   process (E02+). No ambiguity unless the implementer disagrees with the epic.

4. **`var/arxmcp/` created by the script or pre-existing?** The scripts should
   create `var/arxmcp/corpus/raw/`, `var/arxmcp/corpus/parsed/`, and
   `var/arxmcp/ops/parser-failures/` via `os.makedirs(..., exist_ok=True)` if
   they don't exist. This is consistent with `.gitignore` excluding the whole
   `var/arxmcp/` tree.

5. **`mailto:` value in User-Agent?** The acceptance criteria say
   `arXMCP/0.1 (mailto:...)`. The project owner's email (`chris.dare@nalej.com`
   per user context) is the natural value. It should be configurable via an
   environment variable (`ARXMCP_CONTACT_EMAIL`) so the implementer doesn't
   hard-code a personal email in committed code.

6. **50-paper list: manually curated or OAI-PMH query?** S03 says
   "hand-picked." At this milestone, the correct approach is to manually
   curate from arXiv listings for math.AG (post-2015, searching for papers
   with single-file .tex). An OAI-PMH query to populate the list is premature
   (E11). A static `tools/seed-papers.txt` with 50 IDs is the deliverable.

---

## External writes the implementation will require

| type | target | why |
|---|---|---|
| HTTP GET (×50) | `https://arxiv.org/e-print/<paper_id>` | S03 seed corpus fetch — hits arXiv's network; TOS requires politeness headers and 3s sleep |
| HTTP GET (×1) | `https://arxiv.org/e-print/<paper_id>` | S02 single-paper smoke test |
| git push | `origin main` | Not required by the milestone brief — the milestone brief only says "three logical commits"; push is at the implementer/orchestrator's discretion |

The arXiv `/e-print/` fetches are the only external writes. They are subject
to arXiv TOS. The implementation honors TOS by construction (3s sleep, User-Agent
with `mailto:`). No AWS, no third-party APIs, no infra mutations required.
