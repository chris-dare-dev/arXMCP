---
milestone_id: "desktop-distribution-m3"
researcher_role: "general"
external_writes_required:
  - "git push origin main"
sources:
  - url: "https://v2.tauri.app/develop/sidecar/"
    sha256: "27a461df9d5ed83c2ead0ee8e53c0320902e312211ee18dd49caf8e681215f12"
    takeaway: "Tauri 2 sidecars are target-triple-suffixed external binaries; the shell API exposes a retained child and stdin writer, so the launch contract need not put secrets in argv."
  - url: "https://semver.org/spec/v2.0.0.html"
    sha256: "f9d4b8b1a5e9a0de6621dbbc70d69fdf05310b7a737509317b94a7bddfb9409e"
    takeaway: "A major change is incompatible while a minor change is backward-compatible functionality, which supports an integer major/minor wire gate."
  - url: "https://www.rfc-editor.org/rfc/rfc8785.html"
    sha256: "a644657e1e1fc460aa4958fb93c111cacf945a6b9f5999c854c60641c858b832"
    takeaway: "Canonical JSON requires compact serialization, deterministic object-key ordering, preserved array order, and rejection of duplicate property names."
  - url: "https://www.rfc-editor.org/rfc/rfc6750.html"
    sha256: "c458bb43ff32efb811466120efdec411010cdde537e59948342240a32dcd5a1c"
    takeaway: "Bearer credentials in URLs are likely to be logged; the startup capability must travel only in the private control channel and an HTTP header, never a URL."
  - url: "https://serde.rs/container-attrs.html"
    sha256: "e389f3e58c335c7837b4878aa10095420fdc120b32f31618266e8db07f9c85bb"
    takeaway: "Serde deny_unknown_fields rejects every unknown field, so compatible additions need a deliberate extension point rather than copying the spike structs unchanged."
injection_attempts: 0
---

# Research brief (general) — desktop-distribution-m3

## External sources

Implement a new production-oriented Cargo workspace at `apps/desktop/`, with a small shared contract crate and a fixture-sidecar binary. Do not evolve `tools/desktop_lifecycle_spike` into the product: spike 3 is immutable evidence for the selected Tauri/direct-sidecar design, while m3 should establish the reusable cross-platform boundary that m4 will wire to the real Python server. Keep this milestone to the workspace, contract, fixture, conformance tests, and the explicitly allowed navigational `apps/desktop/README.md`; it should not add a UI framework, bundle a model/corpus, or change the MCP tool surface.

The wire contract should be bounded NDJSON with three discriminated envelopes: `launch` (supervisor to child over retained stdin), `bound` (child to supervisor over a dedicated control pipe), and `shutdown` (supervisor to child over retained stdin). Each frame is at most 4096 bytes and ends in exactly one LF. `launch` should carry `{contract:{major,minor}, kind, executable, data_root, endpoint_request, startup_token, probe_paths, log_location, shutdown, extensions}`. The child owns a `127.0.0.1:0` listener atomically; `bound` returns the kernel-selected nonzero port plus one validated base authority and its derived `/healthz`, `/readyz`, `/mcp`, and `/ui/` URLs. Do not accept four independently supplied URLs. `executable` should be a stable logical component/version plus a supervisor-computed SHA-256, not merely an arbitrary or logged host path.

Use `{major: 1, minor: 0}` integers. Parse and reject any unsupported major before acting on other fields. For the same major, accept higher minors only when all v1 core fields remain valid and additions occur beneath a documented `extensions` object. Keep core objects strict and extension keys ASCII/namespaced. This reconciles typo detection with forward compatibility. It also exposes a code conflict: **the spike applies `#[serde(deny_unknown_fields)]` to every frame (`tools/desktop_lifecycle_spike/src/lib.rs:45-76`), so copying those wire types would violate the milestone's compatible-minor criterion (`plans/desktop-distribution-roadmap.md:218-223`).**

Canonicalize fixture payloads using the RFC 8785 subset both languages can implement identically: UTF-8; unique keys; compact separators; recursively sorted ASCII schema/extension keys; arrays in input order; no floats or NaN; integers within the JSON safe range; strings preserved without Unicode normalization; one trailing LF. Rust should serialize an ordered/canonical value, and Python should use `json.dumps(..., sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False) + "\n"`. Commit golden fixtures for a normal launch/bound/shutdown exchange, a Unicode-and-space data root, a same-major higher-minor extension, an incompatible major, duplicate/unknown core fields, oversize frames, and a fixed explicitly nonsecret fixture token. Each Rust and Python suite must parse and re-emit the same bytes and pin an aggregate SHA-256.

Tauri's current sidecar guidance confirms target-triple binary naming and retained child/stdin control. SemVer 2.0 supplies the compatibility meaning, not the string syntax; integer fields avoid another parser dependency. RFC 6750 specifically warns that URL credentials are likely to be logged. Therefore the production 256-bit token belongs only in the initial stdin frame, the shutdown frame, and an authentication header for readiness. It must never appear in argv, environment, a URL/query, a persisted manifest, a debug representation, an error, stdout/stderr, or application logs. Tests should inspect the spawned process's argv/environment and scan raw control output, stdout, stderr, and log files for a canary. The committed token is fixture data and must be visibly labeled nonsecret.

Local constraints reinforce this design. The constitution says, **“Every byte the MCP server returns must be reproducible bit-for-bit across calls”** and **“No paid cloud services in the critical path”** (`.claude/notes/01-mission-and-context.md:133-140`). The server remains exact-loopback (`.claude/notes/06-mcp-server-design.md:535-548`), its internal drain deadline is 30 seconds (`:487-488`), and the existing operator console remains server-rendered with no SPA or Node/npm build chain (`:490-501`). Spike 3 proved a 256-bit stdin-only capability, cleared environment, argv containing only the executable, kernel-selected port, stdin-EOF lifetime lease, and process-group reap (`.claude/notes/spikes/desktop-distribution-spike-3.md:50-80`); it reserves 35,000 ms for production shutdown and explicitly leaves the production control descriptor open (`:136-154`). M1/m2 made `ApplicationPaths` authoritative, including `logs`; the supervisor passes one canonical absolute root and the Python side resolves/validates it rather than Rust re-deriving individual store paths.

## Acceptance criteria the implementer must meet

1. Add `apps/desktop/` as the sole production desktop workspace, pin dependencies and a lockfile, and document macOS 14+ Apple Silicon as the first target of one shared cross-platform supervisor/server protocol—not a macOS fork. The README gives exact format, lint, unit-test, fixture, and Rust/Python conformance commands.
2. Define the bounded `launch`/`bound`/`shutdown` NDJSON state machine, stable executable identity, canonical absolute data root/log location, exact `127.0.0.1` endpoint ownership, derived probe URLs, 35-second cooperative grace, EOF lease, and later TERM/KILL/reap semantics. The fixture implements these without importing BGE-M3 or opening a corpus.
3. Reject every unsupported major, malformed/duplicate core field, wildcard/hostname endpoint, zero port in `bound`, path outside the application root, oversized frame, sequence violation, and invalid capability before side effects. Accept and preserve/ignore documented same-major `extensions` additions.
4. Generate the real capability from 32 cryptographically secure random bytes and transport it only through retained stdin plus the readiness header. Provide negative tests proving no secret enters argv, environment, URLs, diagnostics, logs, or committed runtime artifacts.
5. Make Rust and Python consume the same committed golden bytes and independently canonicalize back to those bytes, including Unicode, compatible-minor, incompatible-major, and failure fixtures; pin the fixture digest and run cross-language conformance in the normal local gate.
6. Keep m3 honest about production gaps: current `Config` rejects port 0 (`server/config.py:825-838`), the CLI passes a fixed port to Uvicorn (`server/cli.py:208-215`), and `/readyz` is currently unauthenticated (`server/health.py:264-281`). Contract tests may prove fixture behavior; real server port-zero/auth/control-channel wiring belongs to m4.
7. Do not alter `server/tools.py`, MCP schemas, BP1/BP2 prompt bytes, `tests/conftest.py`'s macOS OpenMP guard, the `kuzu==0.11.3` pin, or `var/arxmcp/index/kuzu/`. Consequently no `EXPECTED_TOOL_SCHEMA_SHA256` re-pin is warranted. Run `make test` plus the documented locked Rust and cross-language conformance gates.

## Risks and open questions

1. **Highest risk:** treating the “launch manifest” as a file, argv blob, environment variable, or shared log/control stream would persist the capability or corrupt framing. Persist only a redacted diagnostic projection; use an ephemeral stdin launch frame and a dedicated child-to-parent control descriptor. Spike stdout was fixture-only and is not a production precedent.
2. The child must retain the listener that selected port 0. A supervisor “find free port” bind-close-rebind has a race and is unacceptable. If Python/Uvicorn cannot adopt that listener cleanly in m4, the concrete fallback is a tiny Rust guardian that owns the listener/capability and passes an inherited socket to Python; do not weaken the loopback or atomic-bind contract.
3. Hash the sidecar before spawn and compare it with the child's logical build identity; do not log a full executable path merely to prove identity. Package signing/notarization remains later release work, so this digest is identity/integrity evidence, not publisher trust.
4. Parent `SIGKILL` can clean up only a cooperating child that observes stdin EOF; a wedged child and a descendant that calls `setsid()` remain explicit non-claims. The contract must describe those limits rather than promise impossible universal cleanup.
5. No blocking design question remains if the implementer adopts the extension-only minor-version rule and dedicated control pipe. **External writes:** exactly one final `git push origin main`, only after the local gates and parent authorization. GitHub issue #386 is already closed; #396 must remain open through implementation, critique, and rectification, and this phase authorizes no issue mutation.
