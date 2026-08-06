# Research synthesis — desktop-distribution-spike-1

## Decision

Use a pinned PyInstaller 6.21 `onedir` build as the primary disposable probe.
Build from an installed arXMCP wheel in a temporary environment, relocate the
result to a read-only path containing spaces and Unicode, and launch it from an
unrelated working directory with no ambient Python or repository path.

Nuitka standalone is the compiled comparator. A pinned
python-build-standalone runtime plus the locked wheel is the fallback if one
bounded PyInstaller hook/spec correction cannot close the bundle. PyInstaller
`onefile`, zipapps, PEX, and ambient virtual environments do not answer the
sidecar question and are rejected for this spike.

## Acceptance criteria

1. Build a clean arm64 `onedir` artifact from a locally built wheel with pinned
   PyInstaller inputs; generated binaries, model caches, downloaded artifacts,
   logs, and generated specs remain outside Git.
2. Copy the artifact to a recursively non-writable Unicode/space-containing
   path and launch by absolute path from an unrelated CWD with an allowlisted
   environment, explicit writable `ARXMCP_DATA_DIR`, and no usable ambient
   Python, Homebrew, checkout, `PYTHONHOME`, `PYTHONPATH`, or `DYLD_*` path.
3. Reach loopback `/healthz` in bootstrap mode and fetch `/ui/`, `app.css`,
   `tokens.css`, and vendored `htmx.min.js` from packaged assets.
4. Exercise representative native imports/operations and the Transformers
   loader offline using a tiny locally generated safetensors model. Import the
   real arXMCP model-loading modules and record their pins. This mandatory gate
   proves loader/extension closure, not BGE-M3 quality or first-run download.
   If the existing pinned BGE-M3 cache is used as an additional probe, keep it
   external and record the known 2.1 GiB `.bin` security exception; never
   bundle or commit it.
5. Record artifact bytes, allocated size, file count, largest files, at least
   five launch-to-health samples, architecture, Mach-O dependencies/RPATHs,
   unresolved or build-host absolute paths, and ad-hoc signature verification.
6. Write an ADR under `.claude/notes/spikes/` comparing PyInstaller `onedir`,
   Nuitka standalone, python-build-standalone, and rejected extraction/ambient
   modes. State host-scoped GO/NO-GO, fallback, support-floor limits, signing
   implications, and every release blocker.
7. Prove Git contains no models, credentials, generated bundle, mutable
   bundle-local state, MCP schema/hash change, or production OpenMP workaround;
   run focused tests and the repository's canonical `make test` gate.

These criteria trace to the live #384 acceptance list and the roadmap spike at
`plans/desktop-distribution-roadmap.md:167`.

## Affected files

- `tools/desktop_sidecar_spike.py` — compact spike-only frozen entry/runtime
  probe and evidence helpers; no production launcher contract.
- `tests/test_desktop_sidecar_spike.py` — deterministic unit coverage for the
  probe's environment, asset, output, and safety contracts. The real bundle
  build remains an explicitly recorded live spike run.
- `.claude/notes/spikes/desktop-distribution-spike-1.md` — ADR and measured
  evidence. Generated artifacts are referenced by hashes/measurements only.
- `.claude/notes/milestones/desktop-distribution-spike-1/implement/synthesis.md`
  — implementation and check-gate record.

No production dependency or committed bundler configuration is expected. If a
reproducible probe cannot fit this bounded surface, stop rather than widening
the spike into m2 packaging work.

## Constraints and known risks

- Bootstrap `/healthz` bypasses BGE-M3 and corpus startup, so UI and offline
  native/model probes are separate mandatory gates.
- The current BGE-M3 revision is a recorded safetensors-policy exception and
  uses a roughly 2.1 GiB `pytorch_model.bin`; it cannot support a claim that the
  production bundle is release-ready.
- This macOS 26 arm64 host proves relocation only here, not the planned macOS
  14 support floor.
- PyInstaller hooks cover several major packages but not every arXMCP native
  dependency. Runtime probes and Mach-O inspection, not hook-name presence,
  decide closure.
- Ad-hoc signing proves structural signability only. Developer ID, hardened
  runtime, notarization, stapling, and Gatekeeper are spike 4.
- Do not ship `KMP_DUPLICATE_LIB_OK=TRUE` as a launcher workaround. A bundled
  FAISS/PyTorch collision is a measured NO-GO or blocker.

## Open questions

1. Can PyInstaller close the native extension tree with at most one bounded
   explicit collection/hook correction?
2. Does the frozen server serve every required UI asset from a read-only
   relocated tree?
3. Do static Mach-O inspection and runtime native/model probes expose any
   non-relocatable dependency?
4. What size and startup measurements result on this host?

## Estimated implementation

Approximately 300–350 changed lines across four implementation/evidence files,
plus live temporary build artifacts. The work is novel packaging architecture,
so Phase 2 uses the delegated path despite the bounded committed diff.

## External writes required

- `git push origin main`

Pinned dependency downloads needed for the temporary build are read-only
network prerequisites, not external mutations. No package publication,
notarization, credential use, or GitHub issue mutation is required by the
implementation phase.
