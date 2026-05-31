# README + docs critique (adversarial)

_Review date: 2026-05-31. Scope: root governance docs + `docs/` chapters. Docs only — not code, architecture, or product._

## Executive summary

This docset is **shippable with minor fixes** — every cross-link I sampled resolves on disk, the eight-tool surface in the docs matches `server/tools.py` exactly, and the chapter hierarchy (README → `docs/README.md` → chapters) is clean and non-circular. The biggest win is consistency: terminology (notebook, shim, loopback-only, corpus_version), the 4-part runbook skeleton, and the "tools degrade rather than 5xx" contract are stated the same way everywhere. The biggest weakness is the **`pipx install arxmcp` instruction in two troubleshooting tables**, which directly contradicts the "not yet published to PyPI" statement and would leave a stuck reader running a command that cannot work — plus heavy `install.md` bloat (the textbook/Docker sections read like design notes, not install steps).

## Findings

| ID | Severity | File | Finding | Suggested fix |
|---|---|---|---|---|
| C1 | CRITICAL | `docs/install.md` (L326) | Troubleshooting row for `arxmcp-shim: command not found` says "re-run `pipx install arxmcp`". The package is **not on PyPI** (stated L21–22); this command fails with `No matching distribution`. A reader hitting the most common install failure gets a dead-end instruction. | Replace fix with "re-run the source install (`make bootstrap`) and confirm the venv is activated", matching §1. |
| C2 | CRITICAL | `docs/support.md` (L21) | Same PyPI contradiction, softer: the `command not found` row says "re-run the install from the install guide" — which is fine — but the install guide it points to itself hands the reader the broken `pipx` command (C1). The chain dead-ends. | Fix C1; support.md then resolves correctly. |
| H1 | HIGH | `docs/install.md` | The file is the single biggest bloat point. §"Textbook ingest end-to-end (m6+)", the parse-status JSON schema, the `asyncio.Semaphore(1)` rationale, and the macOS `RLIMIT_AS` essay (L83–128) are reference/design material, not install steps, and they duplicate `docs/usage.md`'s "Textbook (PDF) ingest" section. An installer must scroll past ~45 lines of runtime behavior to reach "Register with Claude Code". | Move parse-status states + sandbox rationale to `usage.md` (or a `.claude/` ref) and leave install.md with the install + register + run path only. |
| H2 | HIGH | `docs/install.md` (L154–171, L330) | The `/mcp` vs `/mcp/` trailing-slash explanation appears **three times** (the callout blockquote, the verbatim-snippet note, and the troubleshooting row), each a dense paragraph. The blockquote at L154–165 is one ~100-word sentence with nested parentheticals — a readability blocker. | State the rule once (POST to `/mcp/`; the shim handles it), keep the troubleshooting row, delete the redundant prose. |
| H3 | HIGH | `docs/install.md` (L5–6, L8) | Internal milestone codes (`E06_S01`, `E06_S02`, `E10_S04`, `textbook-ingest-e2`, "the m5 sandbox driver", "(when E07 lands)") leak into a user-facing install guide. These are meaningless to an external installer and are exactly the "roadmap-flavored" content CLAUDE.md §1 says to keep out of user docs. Other chapters (`api.md`, `architecture.md`) cite E-codes sparingly as "roadmapped (E07)", which is acceptable; install.md over-uses them. | Strip bare epic/milestone codes from install.md prose; keep at most "(roadmapped)". |
| M1 | MEDIUM | `docs/install.md` (L186–248) | The "Run via Docker Compose" section (~60 lines, including a long bind-mount-scope paragraph and a 5-item Notes list) is operations content, not install. It also overlaps the Operations chapter's remit. | Trim to the happy path (build, `--wait`, `curl /readyz`) and link the bind-mount/restart detail to ops. |
| M2 | MEDIUM | `docs/install.md` (L9) vs `docs/usage.md` (L33) | The list of arXiv fetch tools that consume `ARXMCP_CONTACT_EMAIL` is inconsistent across files. install.md L331 lists five (`fetch_seed.py`, `notebook_fetch.py`, `recover_preambles.py`, `inspire_ingest.py`, `graph_ingest.py`); usage.md L34 lists three (drops `notebook_fetch.py`→keeps it, but omits `fetch_seed.py` and `graph_ingest.py`). A reader cross-referencing gets two different answers. | Pick one canonical list and reuse it (or link both to one place). |
| M3 | MEDIUM | `docs/install.md` (L327) vs `docs/support.md` (L22) | The shim-503 fix is duplicated almost verbatim across the install troubleshooting table and the support troubleshooting table; support.md then says "The install guide's troubleshooting table has the full matrix", so the support table is a partial copy of install's. Two overlapping tables risk drift. | Make support.md's table point to install.md rows rather than re-listing them, or vice-versa — don't maintain both. |
| M4 | MEDIUM | `docs/observability/README.md` (L66–73) | "Mount the **three** files" but the bullet list above (L52–56) names only two YAMLs (datasource, dashboard-provider); the third (`grafana-dashboard.json`) is the dashboard itself, introduced earlier. The count is correct but the antecedent is unclear on a skim. | Say "Mount the dashboard JSON and the two provisioning YAMLs". |
| M5 | MEDIUM | `docs/architecture.md` (L20) | The ASCII diagram says "8 MCP tools" while the prose elsewhere spells "eight"; minor but the README/api.md deliberately use the word **eight** for emphasis. Inconsistent number formatting across the docset. | Standardize on the spelled-out "eight" in headline contexts, or accept digits in diagrams consistently. |
| L1 | LOW | `README.md` (L96) | Uses the HTML entity `&amp;` in the visible link text "backup &amp; restore". GitHub renders it, but it is unnecessary in Markdown link text and reads oddly in raw form. | Use a literal `&`. |
| L2 | LOW | `docs/install.md` (L1) | Title "Installing arxmcp for Claude Code" lowercases the product name; every other doc uses "arXMCP". | Capitalize to "Installing arXMCP". |
| L3 | LOW | `CHANGES.md` (L29 ff.) | The `Unreleased` section leads with a milestone-coded entry ("`proof-verify` handler-wiring (m9)") full of internal LOC counts and FM-N references — fine for an epic-grain changelog, but the contrast with the polished release-facing header (L1–24) is jarring for a first-time reader who scrolls in. | Out of scope to rewrite history; consider a one-line "below this point: internal epic history" divider (the file half-does this at the `## Epic status` / `## Releases` footer). |
| L4 | LOW | `docs/usage.md` (L11) vs heading (L84) | TOC entry "Serving many notebooks from one server" links to `#serving-many-notebooks`; the heading is just "Serving many notebooks". The anchor resolves (text differs but slug matches), so it works — but the TOC label and heading wording differ. | Align the TOC label to the heading text. |
| L5 | LOW | `docs/releasing.md` (L57) vs `CHANGES.md` (Epic status) | releasing.md says "E01–E14 shipped"; CHANGES.md says "E01–E11, E13, E14 have shipped (E12 scoped-out)". Both are reconcilable (E12 folded into E11) but a reader sees "E14" vs an explicit gap. | Add "(E12 folded into E11)" to releasing.md's parenthetical for parity. |

## What's good

- **Link integrity is excellent.** Every relative link I sampled — including the tricky `../`-relative ones from `docs/observability/README.md` (`../../infra/...`, `../ops/daily-ops-cadence.md`) and `docs/api.md` (`../ingest/identifiers.py`, `../LICENSE`) — resolves to a real file on disk. No orphan pages; `docs/README.md` is a genuine hub.
- **Doc/reality fidelity holds.** The eight tools in `README.md`, `docs/api.md`, and the `arxmcp-shim` smoke test all match `server/tools.py`'s `ALL_TOOLS` (8 entries) and even the per-tool `retrieval_mode` strings. Stubs/deferrals (E07 hybrid, get_paper nulls, E10/E11 work) are honestly flagged, not oversold.
- **Strong scannability where it counts.** `docs/README.md`, `docs/support.md`, and `docs/ops/README.md` use "read it when you want to…" / "you want to → go to" tables that route readers fast. `api.md` is tight and consistent per tool.
- **Entry point is unambiguous and non-circular.** README → docs hub → chapters, with governance (`CONTRIBUTING`, `SECURITY`, `CHANGES`) cross-linked but never looping back into a README→docs→README trap that adds no value.
- **Security and constraints are stated crisply.** `SECURITY.md`'s in-scope/out-of-scope table and the invariants-with-enforcer table are model examples of "table beats prose".

## Link-check results

Verified to exist on disk **relative to the linking file's directory** (via filesystem check):

- From `README.md`: `LICENSE`, `CONTRIBUTING.md`, `SECURITY.md`, `CHANGES.md`, `CLAUDE.md`, `pyproject.toml`, `docs/install.md`, `docs/usage.md`, `docs/api.md`, `docs/architecture.md`, `docs/evaluation.md`, `docs/support.md`, `docs/ops/README.md`, `docs/observability/README.md`, and all seven `docs/ops/*runbook*.md` quick-links — **all resolve**.
- From `docs/README.md`: `../README.md`, `../.claude/`, `install.md`, `usage.md`, `api.md`, `architecture.md`, `ops/README.md`, `observability/README.md`, `evaluation.md`, `support.md`, `releasing.md`, `../CONTRIBUTING.md`, `../SECURITY.md`, `../CHANGES.md`, `../LICENSE` — **all resolve**.
- From `docs/api.md`: `../ingest/identifiers.py`, `../.claude/docs/snippet-contract.md`, `../.claude/docs/proof-chain-workflow.md`, `usage.md#serving-many-notebooks`, `architecture.md` — **all resolve** (anchor `#serving-many-notebooks` matches heading "Serving many notebooks"; `#lean_verify` matches the `## ` + `lean_verify` ` heading).
- From `docs/architecture.md`: all eight `../.claude/notes/0N-*.md`, `../ingest/schema.py`, `../SECURITY.md`, `observability/README.md`, `ops/README.md` — **all resolve**.
- From `docs/observability/README.md`: `../ops/daily-ops-cadence.md`, `../../infra/observability/grafana-dashboard.json`, `grafana-datasource.yml`, `grafana-dashboard-provider.yml`, `infra/observability/phoenix-compose.yml`, `langfuse-orchestrator.md` — **all resolve**.
- From `docs/evaluation.md`: `../.claude/TIER-GATES.md`, `../.claude/docs/eval-curation.md`, `../.claude/docs/retrieval-quality-report.md`, `../tools/cdm_eval.py`, `../tests/eval/textbook_fixtures/`, `../.claude/notes/01-mission-and-context.md` — **all resolve**.
- From `docs/install.md`: `../.claude/notes/06-mcp-server-design.md`, `../.claude/docs/security-pdf-sandbox.md`, `releasing.md`, `api.md`, `infra/docker-compose.yml` — **all resolve**. Tool scripts named in prose (`tools/notebook_ingest.py`, `tools/notebook_fetch.py`, `tools/recover_preambles.py`) all exist.
- From `docs/support.md`: `install.md#troubleshooting`, `ops/README.md`, `ops/failure-modes.md`, `evaluation.md`, `../SECURITY.md`, `../CONTRIBUTING.md` — **all resolve**; anchor `#troubleshooting` matches install.md's `## Troubleshooting`.
- From `docs/ops/README.md`: `failure-modes.md#disk-full` — **resolves** (heading "Disk full" → slug `disk-full`); all nine runbook + eight related-runbook links resolve.

**Anchor checks:** `install.md#optional-textbook-ingest-dep--mineru` correctly uses the double-hyphen GitHub slug for the em-dash heading "Optional textbook-ingest dep — MinerU" — **valid**. `usage.md#the-operator-console` → "## The operator console" — **valid**.

**No broken links found.** The two CRITICALs (C1/C2) are not broken *links* — they are a broken *instruction* (a shell command that cannot succeed given the project's own stated PyPI status).

---

## Rectification log (2026-05-31)

Applied in the same session, after this critique:

- **C1 / C2 (CRITICAL)** — fixed. The `command not found` troubleshooting row
  now points to the source install (`make bootstrap`); the support.md chain
  resolves through it.
- **H1 (HIGH)** — fixed. The verbose "Textbook ingest end-to-end" block
  (parse-status JSON, states, `Semaphore(1)` rationale, macOS RLIMIT essay)
  was condensed to a one-line pointer to `usage.md#textbook-pdf-ingest` plus a
  short macOS sandbox note. No longer duplicates usage.md.
- **H2 (HIGH)** — fixed. The `/mcp/` trailing-slash rule is now stated once
  (concise blockquote) + the troubleshooting row; the ~100-word sentence is gone.
- **H3 (HIGH)** — fixed. Bare milestone codes (`E06_S01`, `E06_S02`,
  `E11_S01`, `E10_S04`, `textbook-ingest-e2`, "m5 driver", "when E07 lands")
  stripped from install.md prose.
- **M2 (MEDIUM)** — fixed. usage.md's `ARXMCP_CONTACT_EMAIL` tool list aligned
  with install.md's fuller list.
- **M4, M5 (MEDIUM)** — fixed. Grafana "three files" clarified; architecture
  diagram now says "eight MCP tools".
- **L1, L2, L4, L5 (LOW)** — fixed. `&amp;` → `&`; install.md title
  capitalized to "arXMCP"; usage.md TOC label aligned; releasing.md notes
  "(E12 folded into E11)".
- **M1 (MEDIUM, Docker-section trim)** — DEFERRED. The compose section is
  genuine deployment info; trimming it is a judgment call left to the owner.
- **M3 (503-row duplication), L3 (CHANGES internal entries)** — ACCEPTED.
  support.md is intentionally a quick-start subset that points to install.md's
  full matrix; the CHANGES epic history below the release header is legacy and
  out of scope to rewrite.

Doc-pinning tests re-run green after rectification (`test_cutover`,
`test_watchdog_eval`, `test_runbook_index`, `test_constitution_ui_claims`).
