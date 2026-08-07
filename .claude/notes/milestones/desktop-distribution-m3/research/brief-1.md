---
milestone_id: "desktop-distribution-m3"
researcher_role: "explore"
injection_attempts: 0
---

# Research brief (explore) — desktop-distribution-m3

## Affected files / context

### Constraints that must survive

- `.claude/notes/01-mission-and-context.md` makes two rules load-bearing: “Determinism over cleverness. Every byte the MCP server returns must be reproducible bit-for-bit across calls” and “Local-first. No paid cloud services in the critical path. The system must work offline once seeded.” Contract serialization therefore needs one canonical form; the fixture must have no network, corpus, or model dependency.
- `.claude/notes/02-architecture-overview.md` and `.claude/notes/06-mcp-server-design.md` require one long-running Streamable HTTP server on `127.0.0.1`, expose `/healthz` and `/readyz`, and reserve 30 seconds for graceful drain. The desktop protocol must reject `localhost`, wildcard addresses, zero *announced* ports, mismatched URL authorities, and shutdown grace below the spike’s production reservation of 35,000 ms.
- `.claude/notes/07-multi-agent-caching.md` and `.claude/notes/prompts-bp-discipline.md` govern MCP `tools/list` and prompt bytes, not this sidecar contract. M3 should not edit `server/tools.py`, MCP handlers, `TOOL_SCHEMA_VERSION`, `EXPECTED_TOOL_SCHEMA_SHA256`, or BP1/BP2 hashes.
- `.claude/notes/08-security-observability-ops.md` treats local inputs as adversarial. The token must be structurally absent from argv, environment, log records, errors, and the server-to-supervisor response—not merely passed through the current redaction filter, whose INFO+ field list is not a general secret scrubber.
- `CLAUDE.md` permits `apps/desktop/README.md` as a navigational subdirectory README. Any other new Markdown belongs under `.claude/`. Preserve pure ASGI, the no-runtime-`anthropic` rule, the Python production-`assert` ban, `kuzu==0.11.3` at `index/kuzu/`, and `tests/conftest.py`’s macOS `KMP_DUPLICATE_LIB_OK` guard.

### Existing seams to extend

- `server/application_paths.py:24-33,92-194` is the sole data-layout owner. A Python-side contract should accept/emit the already canonical `Config.application_paths.root`, and derive `log_location` beneath `ApplicationPaths.logs`; do not duplicate platform-root logic in Rust or invent `kuzudb/`.
- `server/config.py:563-566` exposes that resolved object. Its port validator at `server/config.py:825-838` currently rejects port `0`, while `server/cli.py:23-29,94-109` intentionally accepts no configuration flags. M3 should define and test the port-zero contract using the fixture; production `Config`/uvicorn binding and endpoint publication are explicitly M4 work. Never add `--startup-token`, `--data-root`, or `--port`.
- `server/cli.py:141-164,208-215` sends operational logging to stderr and starts uvicorn from env-owned config. Use an explicit desktop sidecar mode with **stdin = supervisor control NDJSON, stdout = sidecar control NDJSON only, stderr = structured logs**. The supervisor may persist stderr to the manifest’s canonical log path; it must never persist stdin/control frames.
- `.claude/notes/spikes/desktop-distribution-spike-3.md:29-62` already proves the protocol skeleton: bounded 4,096-byte NDJSON, 256-bit capability, literal `127.0.0.1`, kernel-selected port, authenticated readiness and shutdown, stdin-EOF lifetime lease, and bounded TERM/KILL/reap behavior. Promote the semantics, not the historical `tools/desktop_lifecycle_spike` package. Keep that spike excluded from the Python wheel.
- The production contract should be two typed frames under one v1 protocol: a supervisor-to-sidecar `launch` frame carries `{schema_version, executable identity expectation, canonical data_root, startup_token, log_location, shutdown_semantics}`; a sidecar-to-supervisor `bound` manifest carries `{schema_version, executable identity, dynamic endpoint, health_url, readiness_url, log_location, shutdown_semantics}` and **does not echo the token**. Derive both URLs from the validated `127.0.0.1:<port>` authority rather than trusting three independent inputs.
- Represent compatibility as integer `schema_version: {major, minor}`. Both readers must reject `major != 1`, require all v1 fields and types, accept any `minor` under major 1, and ignore documented unknown fields recursively. Do not use `serde(deny_unknown_fields)` for the promoted v1 reader—the spike currently does, which conflicts with compatible minor additions.
- Canonical fixture bytes should be UTF-8, no BOM, compact JSON, recursively lexicographically sorted keys, one trailing LF, and no timestamps. A fixed fixture token is explicitly test data, never generated or used as a live capability. Production token generation remains 32 cryptographically random bytes and stays memory-only.

### Recommended file/test ownership

- `apps/desktop/Cargo.toml`, `Cargo.lock` — new cross-platform Rust workspace with exact dependency pins and no Node/npm build chain.
- `apps/desktop/crates/desktop-contract/` — Rust frame types, compatibility/loopback/path validators, and canonical JSON serializer.
- `apps/desktop/crates/fixture-sidecar/` — tiny model-free/corpus-free sidecar implementing bind-to-port-zero, control-only stdout, readiness, authenticated shutdown, and stdin-EOF exit.
- `apps/desktop/contract-fixtures/` — one source of golden launch/bound bytes plus compatible-minor and incompatible-major cases consumed verbatim by Rust and Python.
- `apps/desktop/README.md` — supported platform boundary, workspace commands, protocol streams, secret/log policy, and “macOS target, not fork” rationale.
- `server/desktop_contract.py` — Python mirror parser/validator/canonicalizer intended for M4’s server adapter; keep it independent of FastAPI, BGE-M3, LanceDB, and MCP tools.
- `tests/test_desktop_contract.py` — Python reads the exact Rust fixture files, checks byte-for-byte canonical round trips and version behavior, launches the fixture without a corpus/model, and scans argv/environment/stdout/stderr/log artifacts for a runtime canary. Leave historical `tests/test_desktop_lifecycle_spike.py` intact.

## Acceptance criteria the implementer must meet

1. Create `apps/desktop/README.md` with supported OS/architecture boundaries, exact `cargo fmt/test/clippy --locked` development commands, stream ownership, and the roadmap rationale that macOS is the first target of one cross-platform product—not a fork.
2. Implement the v1 `launch`/`bound` contract in Rust and Python: reject incompatible majors, accept same-major higher-minor objects with unknown additions, validate required base fields, canonicalize bytes identically, and cap every NDJSON frame at 4,096 bytes.
3. Keep live startup tokens off argv, environment, stdout, stderr, exceptions, and persisted log/control artifacts. Generate 256 random bits, accept it only over bounded stdin, compare it for readiness/shutdown authentication, and never echo it in `bound`.
4. Provide a fixture sidecar that binds only `127.0.0.1:0`, announces the actual nonzero port, serves health/readiness without importing/loading BGE-M3 or opening a corpus, and exits through authenticated shutdown or stdin EOF.
5. Make golden launch/bound fixtures byte-identical from Rust and Python; include positive v1, same-major future-minor-with-extra-fields, wrong-major rejection, wildcard/mismatched-URL rejection, oversized-frame rejection, and deterministic round-trip cases.
6. Run Rust fmt/test/clippy gates, focused Python contract/lifecycle tests, and repository `make test`; run `make wheel-check` if `server/desktop_contract.py` is added. Assert the MCP schema and prompt-cache pins remain unchanged.

## Risks and open questions

1. **Brief ambiguity—one manifest versus secret safety:** one persisted or server-emitted object containing both the token and bound endpoint would violate the security acceptance criterion. Treat the requested fields as one versioned *protocol* split across `launch` and `bound`; document that interpretation explicitly.
2. **Production integration boundary:** current `Config` rejects port zero, `/readyz` is not capability-authenticated, and the Python server has no stdin control actor. Do not hide these facts in the fixture or widen M3 into server lifecycle integration; M4 owns those changes.
3. **Deferred spike findings:** M1 (universal cleanup epilogue), M2/M10 (same-root recovery/lock reacquisition), M3 (failure janitor), and M8 (ordinary Tauri `ExitRequested`) remain open in `.claude/notes/milestones/desktop-distribution-spike-3/findings.json`. M3 should keep the contract compatible with a single lifecycle owner; M4 must close the real-shell paths before claiming orphan-free production behavior.
4. **Dependency prose conflict:** `desktop-distribution-e2` is listed as an M3 dependency even though E2 is the parent outcome that M3/M4 realize. The completed prerequisites evidenced in-repo are M1 and spike-3; treat E2 as grouping, not a forward gate, and correct the roadmap dependency when its owner permits.
5. **Cross-platform semantics:** do not encode Unix-only `SIGTERM`/`SIGKILL` as the wire contract. Specify graceful deadline, force deadline, parent-lifetime lease, and reap guarantees; map them to process groups on Unix and the eventual Windows job/process primitive in platform adapters.
