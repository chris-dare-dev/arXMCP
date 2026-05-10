# Research Brief 1 — E09_S01 (Kùzu schema + OpenAlex bulk ingest)

## 1. In-codebase context

Applicable design notes (cite by filename):

- `.claude/notes/05-storage-and-indexing.md` § Citation graph: Kùzu — defines disk path `var/arxmcp/index/kuzu/` (with file `citations.kuzu`), and gives a richer schema than the milestone brief, with five tables (Paper, Author, Theorem, CITES, AUTHORED, PROVES, NAMED_AFTER). **The brief's 2-table schema (`papers`, `cites`) is a deliberate Tier-3 simplification of the design-note schema** — not a contradiction, but the implementer must comment on the divergence in the migration script.
- `.claude/notes/03-ingestion-pipeline.md` § Source 5 (OpenAlex). Quote (load-bearing): *"Polite pool: include `mailto=owner@example.com` query parameter or header to get higher limits."* Note that the canonical pattern in the design note uses **a query parameter OR a header** — the milestone brief says "User-Agent header" only.
- `.claude/notes/08-security-observability-ops.md` § Backup and restore. Quote: *"Kùzu graph: `/var/arxmcp/index/kuzu/`. Re-buildable from OpenAlex + INSPIRE, takes hours."* The path uses `kuzu` (singular) not `kuzudb`. **The milestone brief uses `var/arxmcp/index/kuzudb/`; the design-note convention is `var/arxmcp/index/kuzu/citations.kuzu`. Conflict — flag.**
- `.claude/notes/08-security-observability-ops.md` § Threat 4 (resource exhaustion) — the same JSON-Schema `maximum` discipline applies to graph traversals once `cite_neighbors` lands (E09_S03), but is not load-bearing here.
- `.claude/notes/08-security-observability-ops.md` § Threat 1 (path traversal) — `paper_id` regex `^\d{4}\.\d{4,5}(v\d+)?$` already enforced by `ingest/identifiers.py:PAPER_ID_RE`. Reuse it on every OpenAlex-derived `paper_id` before writing into the Kùzu node.
- `.claude/notes/02-architecture-overview.md` (per E01_S01-S03 synthesis) — *"ingestion service vs MCP read-path server"* separation; `ingest/graph_ingest.py` is the right home, MCP server is not.
- `.claude/roadmap/E04-vector-store.md` E04_S01 — establishes the **stable `paper_id` set** dependency: every Kùzu node MUST exist as a paper_id in the LanceDB `papers`/`chunks` corpus. The 50 seed papers from `tools/seed-papers.txt` are the universe.

Existing conventions to reuse (cite verbatim, do not invent):

- `tools/arxiv_fetch.py:24-26` — `ARXIV_USER_AGENT_TEMPLATE = "arXMCP/0.1 (mailto:{email})"`. **Use the exact same template** for OpenAlex's User-Agent so the contact email is sourced once from `ARXMCP_CONTACT_EMAIL`.
- `tools/arxiv_fetch.py:62-75` — `build_user_agent()` reads `ARXMCP_CONTACT_EMAIL` from env and raises if unset. **Reuse this helper**, do not redefine it inside `ingest/graph_ingest.py`.
- `tools/arxiv_fetch.py:108-116` — `parse_retry_after()` honors `Retry-After` then falls back to a default. Same contract applies to OpenAlex 429/503 responses.
- `ingest/identifiers.py:PAPER_ID_RE` — single source of truth for arxiv ID regex. The new graph code MUST `from ingest.identifiers import is_valid_paper_id` rather than re-deriving.
- `ingest/store.py` — establishes the **idempotent merge_insert pattern** for LanceDB. The Kùzu equivalent is `MERGE` (Cypher) or `CREATE NODE TABLE IF NOT EXISTS` for DDL — both are supported (see §3 below). Same docstring discipline: "Idempotent upsert" prominent in the module docstring.
- `tools/seed-papers.txt` — 50 IDs already on disk. **Note: IDs are post-2604 (e.g. `2605.03890`).** OpenAlex's coverage of post-2026-issued arXiv IDs is the empirical risk, NOT post-2000 coverage as the milestone risk note implies. Flag (§Open questions).
- The committed paper_ids are version-less (e.g. `2605.03890`). The Kùzu primary key MUST use the same version-less form to match LanceDB's `papers.paper_id` column (`05-storage-and-indexing.md` § papers table).

## 2. Prior decisions and lessons

Recent git log (last 30 commits) shows a strict pattern: every milestone is shipped as `feat(<area>): <topic> (E0X_SY)` followed within 1–3 commits by `rect(<area>): close N CRITICAL/HIGH/MEDIUM from E0X_SY critique`. **Critique loops are non-negotiable.** Implementer should expect the same here.

`.claude/notes/HANDOFF.md:567-599` § "Known gotchas / things-that-always-break":

- Quote (§595): *"The `claude/gallant-blackburn-b89422` branch is local only. No `git push` has happened. The user has not authorized one; it's per-event authorization."* — Keeps applying.
- §580: *"Anthropic library is BANNED at runtime."* Not applicable to ingest, but a reminder that the discipline is "no surprise deps."
- §595: macOS `KMP_DUPLICATE_LIB_OK=TRUE` workaround in `tests/conftest.py` for FAISS+PyTorch. Adding `kuzu` to the pytest path may resurface this — verify before declaring done.

Patterns from prior ingest milestones (E01_S02 / E01_S03 — see `.claude/notes/milestones/E01_S01-S03/research-synthesis.md`):

- **Politeness is a contract, not a suggestion.** `tools/arxiv_fetch.py:POLITENESS_SLEEP_SECONDS = 3.0` and the 503 backoff scheme. For OpenAlex (10 rps polite-pool), the equivalent is `time.sleep(0.1)` between requests, plus `Retry-After` honoring on 429.
- **Idempotency via re-read of artifact, not audit trail** (E04_S01 critique closure F4 in `ingest/schema.py:201-269`). The checkpoint file is metadata; the source of truth for "have I processed paper X?" is the Kùzu `MATCH (p:papers {paper_id: $id}) RETURN p`. Don't trust the checkpoint alone.
- **Tarball-style "validate at the schema boundary"**: `ingest/schema.py:EmbedRecord.__post_init__` validates inputs at construct time. Mirror this for OpenAlex JSON: define a frozen dataclass `OpenAlexWork` with `__post_init__` that asserts arxiv_id format, OA work ID format, and that `referenced_works` is `list[str]` of `https://openalex.org/W…` URLs.
- **No live network in CI**: every test mocks transport (`tools/seed-papers.txt` was committed only after the fetch script worked manually). `tests/test_graph_ingest.py` MUST mock `urllib.request.urlopen` or use `responses`/`pytest-httpx`. Do not assume CI has network access.

Conflicts with the milestone brief that **must be resolved by the human**:

1. **Path:** brief says `var/arxmcp/index/kuzudb/`; design notes (`05-storage-and-indexing.md`, `08-security-observability-ops.md`) say `var/arxmcp/index/kuzu/citations.kuzu`. The brief's path is a directory; the design note's path is a file inside a directory. **Recommendation: follow the design notes** — `var/arxmcp/index/kuzu/citations.kuzu` — and treat the milestone brief's `kuzudb/` as drift. Add a note in the schema-migration script docstring.
2. **Polite-pool location of `mailto`:** brief says `User-Agent` header; design note says "query parameter or header"; OpenAlex docs allow either. **Recommendation: use BOTH** — `mailto=` query string param AND `arXMCP/0.1 (mailto:…)` User-Agent. Costs nothing, satisfies both phrasings.
3. **Concept IDs are wrong** (see §3 below). Flag.

## 3. External sources

### Kùzu (CRITICAL FINDING)

**Kùzu was archived on 2025-10-10**: The Register, BigGo News, and the GitHub banner all confirm. Quote (`https://github.com/kuzudb/kuzu`): *"Kuzu is working on something new! We are archiving the KuzuDB project here…"* The final stable release is **v0.11.3 (October 10, 2025)**. PyPI package `kuzu==0.11.3` remains installable. Docs migrated to `https://kuzudb.github.io/docs`.

This is not in the design notes (`05-storage-and-indexing.md` was last touched 2026-05-06 but pre-dates the archival or chose to ignore it). **Flag for human decision.** Two paths:

- **(A, RECOMMENDED) Pin `kuzu==0.11.3` and ship.** The library is MIT, the binary works, prior-version codebases will still install. Note in `pyproject.toml` and module docstrings: "Kuzu archived 2025-10-10; pinned to last stable; future migration to fork (bighorn / Vela-Engineering) tracked in E11."
- **(B) Switch to a fork.** Kineviz `bighorn` and `Vela-Engineering/kuzu` exist. No PyPI presence yet at time of writing. Costs an additional research cycle; not justifiable for E09_S01.

Cypher dialect (verified against `https://kuzudb.github.io/docs`):

- **`CREATE NODE TABLE IF NOT EXISTS Foo (...)`** — supported. This is the idempotent migration primitive. Same for `CREATE REL TABLE IF NOT EXISTS`.
- `CREATE REL TABLE cites (FROM papers TO papers, source STRING, confidence DOUBLE)` — note **no comma between FROM and TO** (Kuzu-specific).
- **`MERGE`** is supported and is the idempotent upsert. `MERGE (p:papers {paper_id: $id}) ON CREATE SET p.title = $title ON MATCH SET p.title = $title` is the per-paper write idiom. Same for relationships: `MATCH (a:papers {paper_id: $a}), (b:papers {paper_id: $b}) MERGE (a)-[r:cites {source: $src}]->(b)`.
- Python API: `db = kuzu.Database(path); conn = kuzu.Connection(db); conn.execute("…", {"id": …})`. `execute()` returns a `QueryResult`. Parameters bound via dict argument.
- Brief schema bug: `confidence FLOAT`. Kùzu's Cypher type is `FLOAT` (32-bit) or `DOUBLE` (64-bit); `FLOAT` works. Brief is fine. `STRING` is fine. `INT32` is fine.

### OpenAlex (TWO CRITICAL FINDINGS)

#### Finding A — concept IDs in the brief are wrong

Verified live against `https://api.openalex.org/concepts/C66938386`: returns concept **"Structural engineering"**, level 1. **Not algebraic geometry.** And `https://api.openalex.org/concepts/C15736585` returns **404**.

Correct IDs (verified live, search results from `/concepts?search=…`):
- **Algebraic geometry: `C68363185`** (level 2, 32,647 works)
- **Number theory: `C169654258`** (level 2, 33,918 works)

#### Finding B — Concepts are deprecated; Topics replace them

Quote, `https://developers.openalex.org/api-entities/concepts`: *"Concepts are **deprecated** and have been replaced by Topics."* Endpoints still function but won't receive updates.

**Recommendation:** for the seed-corpus pass (50 papers fetched directly by `ids.openalex` or `doi`), **don't use concepts at all** — fetch each paper individually by arXiv ID. For the Tier-3 expansion (tens of thousands of papers), use **Topics** filters (the Topics replacement for `concepts.id` is `primary_topic.id` / `topics.id`). Document the brief's old concept IDs as deprecated and substitute the correct `C68363185` / `C169654258` only as a temporary fallback.

#### Other OpenAlex specifics (verified)

- Rate limit, polite pool: per `https://github.com/ourresearch/openalex-docs/blob/main/how-to-use-the-api/rate-limits-and-authentication.md`: *"max 100,000 credits per day for free users, and also max 100 requests per second."* The brief's "10 requests/second" is conservative and safe — keep it. Polite pool entry: query param `?mailto=…` OR `mailto:…` in User-Agent.
- A January 2026 announcement floated requiring API keys post Feb 13 2026, but the canonical docs source (the GitHub repo backing developers.openalex.org) **still has the polite-pool/mailto pattern intact** as of this research turn. **Treat as soft risk; bake the mailto pattern in but leave a TODO for an API-key path.**
- Cursor pagination: initial request `?cursor=*`, response carries `meta.next_cursor`, repeat until `next_cursor=null`. **Per-page max = 100 (default 25).** Cursor pagination has no 10K cap (basic offset paging does). Source: `https://developers.openalex.org/how-to-use-the-api/get-lists-of-entities/paging`.
- `referenced_works` is a **list of OpenAlex Work URL strings**, e.g. `"https://openalex.org/W272048707"` — verified live against `https://api.openalex.org/works/W2058122340`. The implementer must strip the URL prefix to get the bare `W…` ID before joining against the corpus.
- `ids` object on Works has `openalex` (URL), `doi` (URL), `mag`, `pmid`, `pmcid`. `arxiv` is **not always present**; arXiv linkage is via `primary_location.landing_page_url` containing `arxiv.org/abs/<id>` OR via `ids.doi` (arXiv DOIs are `10.48550/arXiv.…`). **Mapping arxiv_id → oa_work_id requires either lookup-by-DOI or a search for the landing page URL.** Brief is silent on this; flag in §Open questions.
- ToS: free, attribution requested but no specific HTTP-header obligation.

## Open questions

1. **Path drift `kuzudb/` vs `kuzu/`** — recommend follow design notes; await human.
2. **Concept IDs in brief are wrong; Concepts are deprecated** — recommend rewrite that section to use Topics for Tier-3 expansion and direct arxiv-ID fetch for the 50-paper seed.
3. **Kùzu archival** — recommend pin `kuzu==0.11.3` and ship; flag fork migration as E11 work.
4. **arxiv_id ↔ oa_work_id mapping for the seed** — for each of the 50 IDs in `tools/seed-papers.txt`, the script must `GET /works/doi:10.48550/arXiv.<id>` (the canonical arXiv-DOI form) and fall back to `/works?filter=primary_location.landing_page_url:https%3A%2F%2Farxiv.org%2Fabs%2F<id>`. Confirm the arXiv DOI prefix is the canonical resolution path before coding.
5. **Papers in seed corpus that aren't in OpenAlex** — write the `papers` node with `oa_work_id=NULL` (use Kùzu nullable column or a sentinel empty string); skip `cites` edges. Acceptance criterion #3 ("for each of 50 seed papers, a node exists") is satisfied; #4 ("edges for OpenAlex-confirmed pairs") is silently a no-op for that paper.
6. **`var/arxmcp/` already gitignored** (line 24 of `.gitignore`: `/var/arxmcp/`). Test fixture for `tests/test_graph_ingest.py` must use `tmp_path` or `var/arxmcp/index/kuzu-test/`; never the production path.
7. **Checkpoint file location** — brief says `var/arxmcp/ops/graph-ingest-checkpoint.json`. Confirm `var/arxmcp/ops/` exists in the bootstrap; per `tools/README.md` (E01_S01) the make-bootstrap target only creates `parser-failures/`. Add an `mkdir -p` step or extend the bootstrap.
8. **Confidence value semantics** — brief says `1.0 for confirmed, lower for inferred`. OpenAlex citations are confirmed by definition (curated). Recommend hard-code `confidence=1.0` for `source="openAlex"` edges; reserve <1.0 for the future intra-paper extraction in E09_S03.
9. **Kùzu Cypher single-writer constraint** — same as LanceDB's E04_S01 single-writer assumption. Document it in the script docstring; do not enforce a flock at this milestone.

## External writes the implementation will require

| type | target | why |
|---|---|---|
| pyproject.toml dep add | local file | pin `kuzu==0.11.3` (last stable, project archived) — local change only |
| HTTP GET (×~50) | `https://api.openalex.org/works/doi:10.48550/arXiv.<paper_id>` | seed-corpus arxiv→OA-work-id resolution; 0.1s sleep, mailto query param + User-Agent |
| HTTP GET (×~50) | `https://api.openalex.org/works/<W…>` (or batched via `?filter=ids.openalex:W1\|W2\|…`) | fetch `referenced_works` per seed paper; same politeness contract |
| filesystem write | `./var/arxmcp/index/kuzu/citations.kuzu` | local Kùzu DB file (gitignored) |
| filesystem write | `./var/arxmcp/ops/graph-ingest-checkpoint.json` | checkpoint state (gitignored) |
| filesystem write | `./var/arxmcp/ops/graph-ingest.log` | structured log (gitignored) |
| git push | `origin main` | NOT required by milestone; per-event authorization only |

**No live OpenAlex calls in CI** — `tests/test_graph_ingest.py` MUST stub the HTTP layer. The 100-ish live GETs above are dev-time only, run by the human against `tools/seed-papers.txt` once the script works on a single paper.
