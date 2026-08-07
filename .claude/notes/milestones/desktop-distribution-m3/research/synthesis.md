# Research synthesis — desktop-distribution-m3

## Decision

Implement one cross-platform desktop/server protocol, not a macOS fork and not
an extension of the throwaway spike package. The protocol is bounded NDJSON:
the supervisor sends `launch` and `shutdown` frames over retained stdin, the
child emits `bound` over stdout as a dedicated control-only stream, and stderr
is reserved for redacted operational logs. A launch capability is ephemeral,
never appears in argv, environment, URLs, bound output, errors, or persisted
artifacts, and is used only by the private control channel and authenticated
probe/shutdown operations.

The v1 contract uses integer `{major, minor}` compatibility. Unknown majors are
rejected before side effects. Same-major additions are accepted only beneath a
documented `extensions` object while required core fields remain strict. Golden
frames use a shared canonical JSON subset: UTF-8, unique recursively sorted
keys, compact separators, input-order arrays, no floats, and exactly one
trailing LF. Every frame is capped at 4,096 bytes.

M3 proves the boundary with a model-free, corpus-free fixture that binds
`127.0.0.1:0` and retains the selected listener. The current Python server's
port-zero adoption, authenticated readiness, control actor, and real Tauri
lifecycle integration remain explicitly in m4.

## Affected files

- `apps/desktop/README.md` — supported boundary, platform policy, stream and
  secret rules, and exact development/conformance commands.
- `apps/desktop/Cargo.toml` and `apps/desktop/Cargo.lock` — pinned, shared Rust
  workspace without a Node/npm build chain.
- `apps/desktop/crates/desktop-contract/Cargo.toml` and `src/lib.rs` — frame
  types, compatibility checks, loopback/path validation, bounded parser, and
  canonical serialization.
- `apps/desktop/crates/fixture-sidecar/Cargo.toml` and `src/main.rs` — tiny
  loopback port-zero fixture with authenticated shutdown and EOF lifetime
  lease; no model or corpus imports.
- `apps/desktop/contract-fixtures/` — byte-stable positive and negative frames
  consumed by both languages, with an aggregate digest.
- `server/desktop_contract.py` — dependency-light Python mirror parser,
  validator, and canonicalizer for later m4 integration.
- `tests/test_desktop_contract.py` — cross-language fixture, version,
  framing, secret-absence, loopback, and sidecar-process coverage.
- `pyproject.toml`, `Makefile`, or packaging checks only if needed to make the
  conformance gate and installed-wheel boundary explicit.
- Existing MCP tool schemas, prompt-cache pins, production CLI/configuration,
  and historical spike sources remain unchanged.

## Acceptance criteria

1. **Roadmap AC1 — desktop boundary documentation.**
   `apps/desktop/README.md` states supported OS/architecture boundaries,
   exact locked Rust/Python commands, protocol stream ownership, the absence of
   a Node build chain, and why macOS is the first target of one cross-platform
   application rather than a fork.
2. **Roadmap AC2 — versioned compatibility.**
   Rust and Python reject unsupported majors, malformed or duplicate core
   fields, sequence violations, oversized frames, non-loopback endpoints, zero
   announced ports, URL-authority mismatches, and paths escaping the canonical
   application root. They accept documented same-major extension additions.
3. **Roadmap AC3 — secret-safe launch.**
   A real capability is 32 cryptographically random bytes and travels only in
   bounded stdin/control frames plus the authenticated readiness header. Tests
   prove a canary is absent from argv, environment, URLs, bound output,
   stdout/stderr diagnostics, exceptions, and persisted logs/artifacts.
4. **Roadmap AC4 — lightweight fixture sidecar.**
   The fixture owns `127.0.0.1:0`, announces the retained nonzero endpoint,
   derives health/readiness URLs from that authority, handles authenticated
   shutdown and stdin EOF, and runs without BGE-M3 or a corpus.
5. **Roadmap AC5 — byte-stable cross-language fixtures.**
   Rust and Python consume the same committed golden launch/bound/shutdown
   bytes and independently re-emit identical canonical payloads. Coverage
   includes compatible minor extensions, incompatible majors, Unicode paths,
   malformed/duplicate fields, wildcard/mismatched URLs, and oversize frames.
6. **Verification rider.**
   Locked Rust format/test/strict-Clippy, focused Python conformance/process
   tests, wheel/package checks when applicable, and `make test` all pass. MCP
   schema and BP1/BP2 hashes remain byte-for-byte unchanged.

## Constraints carried forward

- `server/application_paths.py` remains the sole Python data-layout owner;
  Rust receives one canonical root and never reconstructs internal stores.
- Preserve exact `127.0.0.1` binding, the 35,000 ms production shutdown
  reservation, stdin-EOF lifetime lease, and platform-neutral graceful/force/
  reap semantics proven by spike 3.
- The committed fixture token is conspicuously nonsecret test data. Live token
  generation and process scans must not confuse it with a production secret.
- Do not copy the spike's universal `deny_unknown_fields` behavior: strict v1
  core objects plus a bounded extension namespace supply typo detection and
  compatible minor evolution together.
- Do not claim that M3 closes spike-3's production lifecycle deferrals. M4 owns
  universal cleanup, same-root recovery/contention, failed-case janitor,
  ordinary Tauri exit handling, real server port-zero/auth, and MCP smoke.
- Related issues #293, #343, #347, #373, #374, and #375 are coordination
  context for portable-runtime epic closure, not blockers or silent M3 scope.

## External writes required

```yaml
external_writes_required:
  - "git push origin main"
```

No GitHub mutation is required during implementation. Issue #386 is already
closed; #396 remains open until the pipeline has completed and its user-gated
push has landed.

## Open questions

1. Whether the first workspace should include a zero-UI Tauri shell crate now
   or leave the actual shell to m4. Default: contract + fixture crates only,
   with the README naming the future shell boundary.
2. Whether the Python mirror belongs in the production wheel in M3 or remains
   internal until m4 calls it. Default: include `server.desktop_contract` and
   extend the real wheel contents gate so the future adapter boundary is proven.
3. Whether the fixture exposes authenticated HTTP probes or only validates
   their derived URLs. Default: expose lightweight probes so token handling and
   port ownership are executable, while documenting that production `/readyz`
   authentication is m4 work.

None is blocking; the defaults above preserve the smallest end-to-end contract
slice.

## Size and implementation path

- Estimated implementation: **12–18 files, approximately 1,100–1,700 changed
  source/test/documentation lines plus a generated Cargo lockfile**.
- Architecture: novel cross-language wire boundary and a new Rust workspace.
- Required Phase-2 path: **delegated**.
- The estimate exceeds the pipeline's default 800-LOC review cap. The owner
  explicitly authorized `--allow-large-diff` on 2026-08-07; Phase 2 may proceed
  through the delegated path while retaining small, reviewable commits.
