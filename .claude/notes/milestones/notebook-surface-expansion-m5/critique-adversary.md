# Critique — notebook-surface-expansion-m5

**Critic:** adversary
**Generated:** 2026-05-29T00:00:00Z
**Commit range:** 96cca0dd0af2a843fcbb008c2b9ddfa83940ff0c..85077ca420bce1ac6699ff030393a1aef178fd5f
**Verdict:** SHIP

## Executive summary

- SHIP — a minimal, well-spiked, single-line wiring of a static MCP `initialize.instructions` hint that leaves both pinned cache hashes byte-identical; all 8 critique axes verified clean with no findings.
- Finding counts: 0 CRITICAL, 0 HIGH, 0 MEDIUM, 0 LOW.
- THE load-bearing axis (cache byte-stability) is independently re-verified GREEN: `tests/test_server_tool_schema.py` + `tests/test_prompts.py` + `tests/test_mcp_instructions.py` = 49 tests pass, no re-pin, no `TOOL_SCHEMA_VERSION` bump.
- Hash-pin (`EXPECTED_INSTRUCTIONS_SHA256`) recomputed independently and MATCHES the pinned literal (`d1cbd98edf8f8e3b0ffbdec861f313d985649efea0558460b3d5771c1969e6ef`); not stale.
- The instructions string is factually honest: all 8 tool names match `server/tools.py::ALL_TOOLS` exactly; resource URIs match `server/mcp_resources.py` (`arxmcp://notebooks` + `arxmcp://notebooks/{slug}`); categories + read-only model are accurate.
- Content-safety verified by direct byte scan beyond the test's substrings — no host paths, IPs, ports, secrets, model names, contact email, or concept IDs; pure ASCII; the string is safe to be public on the unauthenticated loopback handshake.
- The wiring genuinely threads to the real initialize response: `create_initialization_options().instructions == ARXMCP_INSTRUCTIONS` is True (deeper than the test's `mcp.instructions` proxy, which is itself sufficient).
- `!= SYSTEM_PROMPT` test is non-vacuous: SYSTEM_PROMPT is 123 chars (non-empty) and distinct from the 720-char instructions.

## Severity calibration

| level | meaning | rectification phase action |
|---|---|---|
| CRITICAL | data loss, security regression, broken core invariant, or shippable-bug-in-production-now | always fix in Phase 4 |
| HIGH | wrong behavior reachable on common path, or load-bearing constraint violated | always fix in Phase 4 |
| MEDIUM | subtle correctness, missing test, latent foot-gun | fix only if cheap (≤ 30 LOC, small test surface) |
| LOW | style, naming, micro-perf | defer (record under `deferred_findings`) |

## Axis verification (all 8 walked)

- **Axis 1 — Cache byte-stability — CLEAN.** `EXPECTED_TOOL_SCHEMA_SHA256` and `EXPECTED_BP1_SHA256` are NOT touched by the diff (`server/tools.py`, `server/prompts.py`, `tests/test_server_tool_schema.py`, `tests/test_prompts.py` are unchanged — confirmed by `git diff --stat`). `ARXMCP_INSTRUCTIONS` lives in a SEPARATE module `server/mcp_instructions.py`, NOT `server/prompts.py`. Repo grep confirms it is imported ONLY at `server/main.py:653`/`668` (the FastMCP construction), never in `server/orchestrator/` or `server/prompts.py` — so it cannot enter `_build_fanout_request`. No `TOOL_SCHEMA_VERSION` bump. The byte-stability guard test `test_instructions_do_not_drift_tools_hash` (`tests/test_mcp_instructions.py:916`) is genuinely non-vacuous: it builds TWO real servers (`base` without, `treat` with `instructions=`), registers all tools on each, and asserts `base_hash == treat_hash == EXPECTED_TOOL_SCHEMA_SHA256`. Ran the trio: 49 pass.
- **Axis 2 — Math fidelity — CLEAN.** No LaTeX/MathML/PDF/chunker code path touched; the diff is a static string + one-line constructor kwarg.
- **Axis 3 — Security — CLEAN.** The string is server-authored (compiled into source at commit time) — zero injection vector. Direct byte scan of `ARXMCP_INSTRUCTIONS` (not just the test's substrings) found NO `/Users`, `/var`, `/home`, `/tmp`, `0.0.0.0`, `127.0.0.1`, port `7733`, `api_key`/`token`/`secret`/`password`, model names (`claude`/`opus`/`sonnet`/`haiku`), `@`/`.com`, or concept IDs. Appropriately includes the `<retrieved_...>`-is-DATA Threat-2 primer. Safe to treat as public on the unauthenticated loopback `initialize` handshake (per `08-security-observability-ops.md`).
- **Axis 4 — MCP 2025-06-18 spec — CLEAN.** `instructions?: string` is the OPTIONAL `InitializeResult` field; FastMCP threads the constructor kwarg natively into `create_initialization_options().instructions` (verified True). No streaming, no `tools/list` shape change, no method-name change. The string content honestly describes the server (8 tools by name matching `ALL_TOOLS`; `arxmcp://notebooks` + `<slug>` resources matching `mcp_resources.py`; read-only model) — no false claim, correctly says "eight tools" (not the stale "7").
- **Axis 5 — Local-first / Docker — CLEAN.** No S3/ZooKeeper/Kafka/etcd; no new service dependency; no absolute paths; "local-first" claim in the string is accurate.
- **Axis 6 — Tier sequencing — CLEAN.** Consumes only FastMCP 1.27.x (already pinned + shipped) and the m4 resources surface (shipped, commit `96cca0d`). No dependency on a `⏳ PENDING` tier.
- **Axis 7 — No-fork — CLEAN.** No `pyproject.toml`/`requirements*`/`uv.lock` change; no submodule; no `# From https://github.com/...` lift in source. The only `github.com` string is a spec-citation URL inside a research brief.
- **Axis 8 — Test surface — CLEAN.** 8 new tests cover all 3 ACs: hash-pin (intentional-drift), all-8-tool-names-present, length cap (≤ 800), content-safety, `!= SYSTEM_PROMPT`, wiring, and the byte-stability guard. No new MCP tool added, so no `EXPECTED_TOOL_SCHEMA_SHA256` re-pin is owed. `tests/conftest.py` `KMP_DUPLICATE_LIB_OK` is untouched.

## Open-scan verification

- Hash-pin recomputed independently: `sha256(ARXMCP_INSTRUCTIONS) == d1cbd98e…e6ef` — MATCHES the pinned literal at `tests/test_mcp_instructions.py:849`. UPDATE-ANCHOR + intentional-drift docstring correctly mirror `EXPECTED_TOOL_SCHEMA_SHA256`.
- `__all__ = ["ARXMCP_INSTRUCTIONS"]` is correct (the single public symbol).
- No `assert` in production source (`server/mcp_instructions.py`); the `assert`s in `tests/test_mcp_instructions.py` are the pytest idiom, NOT banned-invariant asserts in shippable code.
- No dead code, no bare `except`, no race conditions, no `pass`/`NotImplementedError`/`# TODO` on an exercised path.
- Doc placement clean: the only `.md` edit is `.claude/notes/06-mcp-server-design.md` (additive note, accurate — distinguishes `initialize.instructions` from `SYSTEM_PROMPT`/BP1, states the byte-stability + content-safety posture); all milestone artifacts are under `.claude/`.
- `ruff check .` — All checks passed.
- NOTE (not attributed to m5): `tests/test_tools_all.py::test_cite_neighbors_wired` fails on a stale `var/arxmcp/index/kuzu` directory (2026-05-20, predates this commit); the m5 diff touches no graph/citations code. Correctly excluded.

## Findings

None.

## What was done well

- Placed `ARXMCP_INSTRUCTIONS` in a dedicated `server/mcp_instructions.py` rather than `server/prompts.py`, structurally eliminating the FM-c BP1-drift hazard the research flagged — the boundary between the MCP handshake field and the orchestrator's BP1 prefix is now unambiguous.
- The byte-stability guard test is a real two-server comparison anchored to the pinned baseline hash, not a tautology — it would actually fail if `instructions=` ever leaked into the tool registry.
- Hash-pin mirrors the established `EXPECTED_TOOL_SCHEMA_SHA256` UPDATE-ANCHOR + intentional-drift discipline, and the failure message prints the new value to re-pin — low-friction, correct discipline.
- The instructions string is factually accurate to the live surface: all 8 tool names exactly match `ALL_TOOLS`, the resource URIs match `mcp_resources.py`, and it correctly says "eight tools" (the spike-flagged stale "7-tool" framing was avoided).
- Content-safety was taken seriously: server-authored, ASCII-only, no host paths / IPs / ports / secrets / model names, and it doubles as a Threat-2 `<retrieved_...>`-is-DATA primer for any client that surfaces the hint to its LLM.
- The module docstring is an excellent maintenance artifact — it explains WHY the constant is isolated, what content-safety contract it must honor, and that editing requires a conscious re-pin.
- The `main.py` wiring comment cites spike-1 and the pinning test, so a future reader understands the byte-stability claim without re-deriving it.
- Tests cover beyond the bare AC (tool-name coverage + length cap per research FM-e/FM-f), catching future tool-surface drift and anti-bloat.
- The `!= SYSTEM_PROMPT` test is meaningful: SYSTEM_PROMPT is non-empty (123 chars) and distinct, so the test cannot pass vacuously on two empty strings.
- Scope discipline is exemplary — exactly one constant, one constructor kwarg, one test file, one additive doc note; no scope creep, no dependency churn, no re-pin.

## Recommended rectification order

None — no findings to rectify.

## Rectification status (filled by Phase 4)

Adversary verdict **SHIP** — 0C/0H/0M/0L. No findings → no rectification, no rect
commit (the rect commit in the three-commit pattern is created only when there are
findings to close; m5 ships as feat + chore). Byte-stability gates, the hash-pin
(recomputed-match), MCP-spec honesty, and content-safety were all independently
verified clean by the critic. Proceeding directly to finalize.
