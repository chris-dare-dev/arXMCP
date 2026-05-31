# arXMCP first-time-user onboarding — current-state critique

**Audit date:** 2026-05-30
**Auditor role:** non-technical user walking from `git clone` to "first paper in"
**Mandate:** unflinching critique, severity-ranked, file:line evidence. No fixes — Agent 2's problem.

This brief is the proposal architect's brief: every blocker named here becomes a "thing the new flow must hide or solve". I quote source verbatim and rank by what actually stops a user, not what theoretically might.

---

## 0. The promised path (per `README.md` quick-start)

```bash
python3 -m venv .venv && source .venv/bin/activate
make bootstrap
export ARXMCP_CONTACT_EMAIL=you@example.com
python tools/fetch_seed.py
make up
# register the shim
```

Six lines. Sounds friendly. Now let's walk it for real.

---

## 1. The detonation chain (what actually happens, in order)

### Step 1: `make bootstrap` — OK in isolation, but leaks expectation

`Makefile:60-63`:

```make
@echo "Bootstrap complete. var/arxmcp/ tree created."
@if [ -z "$$ARXMCP_CONTACT_EMAIL" ]; then \
    echo "WARNING: export ARXMCP_CONTACT_EMAIL=<your-email> before fetching from arXiv."; \
fi
```

Bootstrap nags the user about `ARXMCP_CONTACT_EMAIL` even though the **server** then rejects that exact variable. The Make help text at `Makefile:37-38` repeats the directive ("Before fetching from arXiv, export ARXMCP_CONTACT_EMAIL=<your-email>"). The bootstrap is internally consistent; the rest of the project is not.

### Step 2: `export ARXMCP_CONTACT_EMAIL=...` then `make up` — **HARD FATAL**

Per the live evidence and `server/config.py:79-82`:

```python
model_config = SettingsConfigDict(
    env_prefix="ARXMCP_",
    env_file=None,  # ARXMCP_* env vars only — no .env-file fallback.
    extra="forbid",  # unknown ARXMCP_* vars are configuration errors.
)
```

The server has a strict-typo allow-list. `ARXMCP_CONTACT_EMAIL` migrated to **ingest-only** as of `ingest/inspire_ingest.py:784` and `ingest/graph_ingest.py:775`. The server side has no declaration → `extra="forbid"` raises a Pydantic `ValidationError` at config load.

Cross-references that are now lies:
- `README.md:48`: `export ARXMCP_CONTACT_EMAIL=you@example.com   # arXiv TOS §3 polite pool`
- `CLAUDE.md:515`: same export inside the "Start the MCP server (local dev)" snippet
- `Makefile:37`: bootstrap's parting nag
- `tools/README.md:17`: same export under "Run the ingest pipeline"

The error is a Pydantic dump of every declared `ARXMCP_*` knob — to a non-technical user this is indistinguishable from "the server crashed". The boot dies in <1s. There is no "did you mean to remove this variable?" hint. **Severity: BLOCKER.**

### Step 3: `python tools/fetch_seed.py` — succeeds, but only fetches

`tools/fetch_seed.py` walks `tools/seed-papers.txt`, downloads raw `.tex` and ar5iv HTML into `var/arxmcp/corpus/raw/` and `var/arxmcp/corpus/parsed/`. **It does not chunk, does not embed, does not write LanceDB.** The README's quick-start strongly implies fetch-then-`make up`-and-you're-done. False.

### Step 4: `make up` — **HARD FATAL #2**

Even with the env var problem fixed, the server's `Resources.startup` refuses to boot on a cold-start corpus. `server/resources.py:439-447`:

```python
# 1. Corpus marker — REFUSE TO START on absent (synthesis D5).
corpus_info = read_corpus_version(config.lancedb_path)
if corpus_info is None:
    marker = Path(config.lancedb_path) / "corpus-version.json"
    raise CorpusNotIngestedError(
        f"corpus-version.json not found at {marker}; "
        f"run the ingest pipeline first. The server "
        f"refuses to start on a cold-start corpus state."
    )
```

The user has just fetched 50 papers but no LanceDB exists. The error says "run the ingest pipeline" but **does not name which one**. The user has six options to choose from with no signposting:

- `make ingest` (the docs-canonical answer, but it goes to `ingest.bulk_ingest`)
- `python -m ingest.bulk_ingest` (the real underlying invocation)
- `tools/notebook_init.py`, `tools/notebook_fetch.py`, `tools/notebook_ingest.py` (the per-notebook path; needs a slug the user does not yet have a mental model for)
- `tools/notebook_textbook_ingest.py` (textbook variant; needs MinerU + a separate venv)
- `tools/fetch_seed.py` (already done; doesn't ingest)
- `tools/recover_preambles.py` (recovery, not greenfield)

**Severity: BLOCKER.** Even an operator-grade user will Google the error and end up reading `docs/ops/bulk-ingest-runbook.md`.

### Step 5: choose a fork (A, B, or C) — **OBSCURED CONCEPT**

The user now meets the three-fork mental model. Nowhere in `README.md`, `docs/install.md` §1-§3, or `CLAUDE.md` §6 does a non-technical user get an intro to the question "do I want one daemon per notebook, one daemon with a `filters.notebook` argument, or a single shared corpus?" The only place that explains it is `docs/ops/notebook-modes.md` — a 3rd-tier runbook under the "Operations" header that the quick-start never references.

Evidence the runbook itself confirms the fork concept exists only in source comments + spike docs:

- `docs/install.md:243-244`: "This is the **process-level default** (fork C)" — but the words "fork A" / "fork B" never appear in `install.md`.
- `docs/install.md:249`: "#### Per-call notebook selection (`filters.notebook`)" — this IS fork A, but unlabeled.
- `tools/notebook_ingest.py:23-24`: comments reference "fork-C isolation in :class:`server.config.Config`" — a non-technical user will not read this.
- `CLAUDE.md` has zero mentions of `filters.notebook`, zero mentions of fork A / B / C. The "Browser operator console" sentence at line 263 implies the UI is the answer, but the UI today silently shows zero notebooks if `notebooks.db` is empty (see §3 below).

The runbook table in `notebook-modes.md` is genuinely good, but it's about 9 mouseclicks from the README's quick-start path. **Severity: HIGH.**

### Step 6: the on-disk-vs-registry split — **SILENT LIE**

Live evidence: today's session had four notebook dirs under `var/arxmcp/notebooks/` (`bridgeland-stability`, `csrf-victim`, `demo-nb`, `shimura-varieties`) and an empty `notebooks` table inside `var/arxmcp/cache/notebooks.db`. The UI showed zero notebooks despite 5266 + 10298 chunks of real corpus on disk.

`server/notebooks_store.py:273-300` (`list_notebooks`) reads ONLY from the SQLite registry. There is **no reconciliation pass** that walks `var/arxmcp/notebooks/<slug>/lancedb/corpus-version.json` and back-fills the registry. I searched:

```
grep -rn "reconcile\|sync_existing\|register_existing\|recover_notebook" tools/ server/notebooks_store.py
# → no matches
```

The `tools/notebook_*.py` family has 7 scripts: `init`, `fetch`, `ingest`, `cutover`, `purge`, `restore`, `textbook_ingest`. **None** of them adopts an existing on-disk dir into the registry. `notebook_restore.py:8` only restores from a backup tarball into the registry — not from a "this dir already exists" state.

The UI ends up showing an empty list. The user concludes "the corpus didn't ingest" when in fact the corpus is fine and the registry is the lie.

**Severity: BLOCKER** — UI silently lies about state, and the fix required hand-written SQL today. There is no operator-facing repair path.

### Step 7: stale `chunk_count` in markers — **PERPETUAL DEGRADED BADGE**

Today's `bridgeland-stability/lancedb/corpus-version.json` reported `chunk_count=824` while `chunks_table.count_rows()` returned 5266. The integrity-observability machinery (`server/resources.py:489-507`) computes the live count at startup and reconciles against the marker. A divergence flips the readiness badge to **DEGRADED**.

There is **no operator-facing CLI / Make target / UI button to reconcile the marker**. The fix today was a hand-written Python script using `lancedb` + `pyarrow.compute` to recompute and write back. `Makefile` has 19 targets; none of them is `make reconcile-markers` or equivalent.

The badge label is `("DEGRADED", "warn")` per `server/routes/ui.py:184-207`. It tells the user something is wrong but doesn't tell them how to fix it. **Severity: HIGH.**

### Step 8: `Mcp-Session-Id` and `/mcp` trailing slash — **CLIENT INCOMPATIBILITY**

`server/main.py:109` lists `"/mcp"` among its protected paths. The actual FastMCP mount accepts `/mcp/` (with the trailing slash) and 307-redirects bare `/mcp`. POST with body → 307 redirect → most clients silently drop the body on re-issue → confusing failure mode for someone testing with `curl`. Not mentioned in `docs/install.md` "Troubleshooting" table at `docs/install.md:305-310`. **Severity: MEDIUM** (only affects manual testers; Claude Code's stdio shim hits the right URL automatically).

### Step 9: 503 noise + scrolling readiness probes — **NEW USER PANIC**

While the server warms BGE-M3 (~5-30s on warm HF cache, much longer on first download per `docs/install.md:280-286`), the htmx badge polls `/ui/status-badge` every 10s (`server/routes/ui.py:262`, `frontend/templates/base.html:66`). If the browser is also open to `/ui/`, that's an immediate continuous 503 trickle. The boot log scrolls dozens of `503 GET /readyz` lines from the shim AND the UI poll. The operator semantics (`/healthz` always-200 vs `/readyz` 503-until-warm) are good engineering — but they look like a crash to a non-technical user.

The wait-for-warm guidance at `docs/install.md:285-286` exists ("…before invoking Claude Code") but is buried after Docker discussion. A user who already typed `make up` and sees 100 lines of 503 errors will assume failure. **Severity: MEDIUM.**

---

## 2. The doc-vs-code drift catalog

Stale documentation we discovered, file:line verbatim:

| Doc | Line | Says | Reality |
|---|---|---|---|
| `README.md` | 48 | `export ARXMCP_CONTACT_EMAIL=you@example.com   # arXiv TOS §3 polite pool` | Server rejects the var; only ingest needs it |
| `CLAUDE.md` | 515 | Same export under "Start the MCP server (local dev)" | Wrong sub-section; this is an ingest-only var |
| `Makefile` | 37 | `Before fetching from arXiv, export ARXMCP_CONTACT_EMAIL=<your-email>` | Misleading because users export it once and leave it set; survives into `make up` and detonates |
| `Makefile` | 13-33 | `make help` lists 17 targets including obscure ones like `refresh-arxiv-ca` | No "first-time setup" target. No grouping. The user has no entry-point signal. |
| `docs/install.md` | 308 | "wait for `/readyz` 200, or run the ingest pipeline first" | "The ingest pipeline" — singular. We have six. |
| `docs/install.md` | 234-247 | `ARXMCP_NOTEBOOK=bridgeland-stability make up` | Implies a notebook by that name exists. Today it does on disk but not in the registry. No script bridges this. |
| `CLAUDE.md` | 262-265 | "Browser operator console... notebook management (create / list / ingest / rename / delete / upload)" | Conspicuously absent: "**adopt an existing on-disk notebook**" |

---

## 3. Concept overload — what a non-technical user must learn before they can succeed today

A new user has to internalize ALL of the following before they can put one paper in and ask one question:

1. **"Corpus" is overloaded.** It can mean (a) the global shared LanceDB at `var/arxmcp/index/lancedb/`, (b) a per-notebook LanceDB at `var/arxmcp/notebooks/<slug>/lancedb/`, (c) a staging LanceDB at `var/arxmcp/index/lancedb-staging/`, or (d) a per-notebook staging LanceDB at `var/arxmcp/notebooks/<slug>/lancedb-staging/`. Cutover machinery shuttles between (b) and (d). The user has to know all four exist before reading any runbook.

2. **Fork A / B / C** — which mode of multi-notebook deployment. Today only `docs/ops/notebook-modes.md` introduces this. The README never does.

3. **The notebook concept itself.** Notebooks are an arXMCP construct, not an arXiv one. The slug rules, the `papers.txt` template, the `queries.json` template (`tools/notebook_init.py:30-65`) are all undocumented in `README.md`. The only intro is the per-tool docstring.

4. **`corpus-version.json` marker drift.** That a JSON sidecar file in a LanceDB dir can independently lie about what's in the underlying table is bewildering. There is no published explanation of why this is two sources of truth and not one.

5. **`notebooks.db` SQLite registry vs on-disk dirs.** Two parallel namespaces with no reconciliation. The user has to learn that "create a notebook in the UI" populates both, but a directory created out-of-band populates only the disk side and the UI then lies about it.

6. **Health vs readiness vs degraded.** Three terms, three response codes, badge labels in two CSS variants (`warn` and `down`). The 200-but-DEGRADED case is unintuitive.

7. **The Python interpreter pin.** `Makefile:1-8` defaults `PYTHON=python3` but `MIN_PY_MINOR=11`. Users on macOS with stock Python (3.9) get a `make bootstrap` failure. Recoverable but requires reading the override hint.

8. **`uv run python -m pytest`** vs system pytest (gotcha #8 in `CLAUDE.md`). Same Python-pin landmine.

9. **The shim vs the server.** Two binaries, two roles. The `docs/install.md:1-18` does explain this, but only after the user has parsed "this split is load-bearing" — engineer-grade language.

10. **MinerU in a separate venv.** `docs/install.md:46-62` says to install MinerU in `~/venvs/mineru` and set `ARXMCP_MINERU_BIN`. A user who wants to ingest a PDF textbook has to learn the per-tool venv split.

11. **Badge "DEGRADED" conflation** (already filed as `mcp__ccd_session__spawn_task`; not re-derived here).

---

## 4. Make-target coverage gaps

`make help` (`Makefile:11-38`) lists 17 targets. Notice what is **missing**:

- No `make first-run` / `make setup` / `make hello` — i.e., no "go from a fresh `bootstrap` to a working `make up` with one command".
- No `make reconcile-notebooks` — the on-disk-vs-registry repair.
- No `make reconcile-markers` — the chunk_count drift repair.
- No `make doctor` — a smoke test that walks "is the corpus ingested? is the server up? is the shim registered?" and prints a remediation plan.
- No `make seed` (alias for `python tools/fetch_seed.py`) — the README invokes the script directly, breaking the make-target discoverability story.
- `make ingest` (`Makefile:117-133`) goes to `ingest.bulk_ingest` which itself does NOT operate on the seed-papers fetched by `tools/fetch_seed.py` without a `--paper-ids-file=` argument. The bulk-ingest runbook at `docs/ops/bulk-ingest-runbook.md` is the gap-filler the README should be.

The `make help` output reads like a release-engineer's index of every operator action over the project's life, not a new-user welcome wagon.

---

## 5. The two roles arXMCP is silently serving

**Role A — the operator** (the user CLAUDE.md was written for). Understands fork A/B/C, knows what `corpus-version.json` is, can read `notebooks_store.py` directly, runs `make watchdog` and `make cutover` from memory. CLAUDE.md §3-§4 + the 11 runbooks under `docs/ops/` serve this user well.

**Role B — the end-user / researcher** (Chris's actual stated downstream consumer: the sketcher → autoformalizer → tactician → fixer pipeline). Wants the UI to do everything. Should never type a `make` command. Today the UI assumes a populated `notebooks.db` (which assumes someone ran `tools/notebook_init.py` via CLI or used the "Create" form before the corpus existed). The UI's "Create" form populates the SQLite row but doesn't trigger ingest — that's a follow-up step the user has to know about.

The CLI assumes UI concepts (slugs, the notebook construct). The UI assumes CLI concepts (something has already created and populated the corpus). **Neither persona's flow is end-to-end self-contained today.**

---

## 6. Pain-point summary table

| Severity | Pain | Where | Fix-shape |
|---|---|---|---|
| BLOCKER | `ARXMCP_CONTACT_EMAIL` set → server boot dies in <1s with Pydantic dump | `README.md:48`, `CLAUDE.md:515`, `server/config.py:79-82` | Stale-doc rewrite + Pydantic error hint |
| BLOCKER | `Resources.startup` refuses cold-start with "run the ingest pipeline" but doesn't name which | `server/resources.py:439-447` | Concrete CLI in error + one Make target |
| BLOCKER | UI silently lies — `notebooks` table empty while `var/arxmcp/notebooks/*` has real data | `server/notebooks_store.py:273-300`; no reconcile path in `tools/` | New `make reconcile-notebooks` + UI banner |
| HIGH | No turnkey "first paper in" command — 6 candidate ingest scripts, user picks wrong one | `Makefile:11-38` (no first-run target) | One `make first-run` doing seed→ingest→up |
| HIGH | Fork A / B / C concept hidden in source comments + 3rd-tier runbook | `docs/install.md:243-244`, `docs/ops/notebook-modes.md` | Concept consolidation into README + UI hint |
| HIGH | Stale `chunk_count` in `corpus-version.json` → perpetual DEGRADED badge with no remediation CLI | `server/resources.py:489-507`; no `make reconcile-markers` | New Make target + UI "reconcile" button |
| HIGH | `make ingest` is a CLI dispatch surface, not a greenfield path. Bulk-ingest runbook is the gap-filler the README should be. | `Makefile:117-133`, `docs/ops/bulk-ingest-runbook.md` | New welcome-path doc + Make target |
| MEDIUM | `/mcp` vs `/mcp/` 307 redirect drops POST body for manual curl testers | `server/main.py:109` + FastMCP mount | Troubleshooting table entry |
| MEDIUM | Boot log scrolls 503s from htmx poll + shim probe during warmup, looks crashed | `server/routes/ui.py:262`, `frontend/templates/base.html:66`, `docs/install.md:280-286` | UI "warming up" screen state |
| MEDIUM | Make help lists 17 unsignposted targets; no grouping, no first-time-user signal | `Makefile:11-38` | help-text reorg with a "FIRST TIME?" section |
| MEDIUM | "Corpus" overloaded across four meanings (shared / per-notebook / staging / per-notebook staging) | `docs/install.md` passim; `notebook-modes.md` summary table | concept consolidation + glossary |
| LOW | `notebooks.db` v1→v4 migrations land silently; user can't see schema version | `server/notebooks_store.py:200-251` | Surface in `make status` or `/status` |
| LOW | MinerU separate-venv concept appears only when textbook ingest is attempted | `docs/install.md:46-62` | Defer to textbook flow; not a first-run concern |
| LOW | `ARXMCP_NOTEBOOK` + `ARXMCP_LANCEDB_PATH` mutual exclusion is documented in install but not at error time | `docs/install.md:244-246` | Better error message on conflict |

---

## 7. Bottom line for Agent 2

Today's onboarding has two blocker classes, in this order:

1. **The boot fails twice before the user can type their first MCP query** (env-var rejection + cold-start corpus refusal). Both errors are technically correct; both are catastrophically unfriendly to a non-technical user.
2. **The UI lies about state** because `notebooks.db` and `var/arxmcp/notebooks/<slug>/` are independent sources of truth with no reconciliation. There is no operator-facing tool to repair the inconsistency.

The "concepts a new user must learn before they can succeed" list (§3) is the **what we want to hide** list for the proposal. The 11 items there are 11 things a happy-path flow should never require the user to think about.

If the proposal architect can deliver **one command** that:
- accepts no env vars
- fetches a seed corpus
- ingests it
- starts the server
- registers the notebook in `notebooks.db`
- prints a working URL to the UI
- and a reconcile path for "I deleted/moved/restored my var/ tree"

…then 8 of the 11 concepts disappear from the new user's path. The remaining 3 (notebook concept, shim vs server, health vs readiness) are arXMCP-load-bearing and worth explaining once, gently, in a fresh `docs/quickstart.md` that the README links instead of the current quick-start block.
