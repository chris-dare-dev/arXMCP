---
milestone_id: "desktop-distribution-m2"
researcher_role: "general"
external_writes_required:
  - "git push origin main"
sources:
  - url: "https://docs.python.org/3.12/library/venv.html"
    sha256: "4a21cfe35163b5f9fcc72bd69c8489884bc8f699dad3ff66029bf4037400b500"
    takeaway: "A venv's installed scripts contain absolute interpreter paths, so the wheel smoke must create and install into the environment at its final arbitrary location rather than claim that a populated venv is relocatable."
  - url: "https://docs.python.org/3.12/library/tempfile.html"
    sha256: "323542212dc35e7e0726eb9709d0059d2c9a1a6356b8f6ff833fc9ea862258c3"
    takeaway: "Python chooses temporary storage from TMPDIR, TEMP, then TMP and may fall back to the current directory; the choice is cached, so launch-time redirection must precede application imports."
injection_attempts: 0
---

# Research brief (general) — desktop-distribution-m2

## External sources

Python 3.12's `venv` documentation is decisive about the meaning of this milestone's relocation smoke: installed scripts use absolute shebangs and virtual environments are inherently non-portable. Build the wheel, create a fresh venv at its final randomly named path, install there, and invoke that environment's absolute `arxmcp-server` entry point from an unrelated working directory. Moving or copying an already-populated venv would test an unsupported property and conflate m2 with the separately completed frozen-sidecar spike.

Python 3.12's `tempfile` documentation establishes a second launch invariant. `TMPDIR`, `TEMP`, and `TMP` influence the selected directory, the current directory can be a last-resort fallback, and selection is cached. The child environment therefore must be complete before its first Python import. In addition to `ARXMCP_DATA_DIR`, redirect `HOME`, `XDG_CACHE_HOME`, `HF_HOME`, `TRANSFORMERS_CACHE`, `MPLCONFIGDIR`, `TMPDIR`/`TEMP`/`TMP`, and Windows `USERPROFILE`/`LOCALAPPDATA`/`APPDATA` beneath the temporary application root; set `PYTHONDONTWRITEBYTECODE=1`. This carries the completed spike-2 finding about library-owned writes into the production check without importing the disposable spike test.

## Repository-grounded recommendation

Extend the existing full wheel gate in `tools/wheel_install_check.py`, specifically `assert_boots`, instead of creating a parallel installer. It already builds a wheel, installs it into an isolated venv, proves `server.__file__` comes from `site-packages`, launches the absolute console script from an unrelated CWD, enables bootstrap mode, and waits for `/healthz == 200`. Add a parent-side filesystem observer and a small installed-runtime path/store probe to that flow. Keep all harness artifacts distinct from application artifacts so the evidence identifies which writes came from the server.

The observer should take manifests of the repository, arbitrary CWD, installed application/`site-packages`, and their relevant parent sandbox after installation but before launch, then compare them after graceful shutdown. Make the application and arbitrary CWD read-only where the platform supports it. Inventory every created or changed path under the application-data root and assert that no watched path outside it changed. A bare `/healthz` check is not sufficient evidence: `Resources.start()` returns early in bootstrap mode before LanceDB, the retrieval cache, model loading, corpus-marker refresh, and metrics refresh. Server startup does open `NotebooksStore`, so it naturally exercises `notebooks.sqlite3` and its schema/settings tables, but cache/log/corpus-marker claims need deterministic representative operations through installed production APIs. Recommended implementation: after the real health boot, run a tiny probe with the installed interpreter that resolves `Config`/`ApplicationPaths`, opens the relevant stores, and performs minimal sentinel writes using production writers. Do not satisfy an “observed write” criterion merely by asserting resolved path strings.

`server/application_paths.py` is the authority, including the strict installed-mode containment of all compatibility aliases. Preserve source-checkout behavior for `make up` and the seven explicit per-store overrides: `ARXMCP_LANCEDB_PATH`, `ARXMCP_KUZU_PATH`, `ARXMCP_CACHE_DB_PATH`, `ARXMCP_BM25_INDEX_ROOT`, `ARXMCP_THEOREM_NAMES_DB_PATH`, `ARXMCP_NOTEBOOKS_DB_PATH`, and `ARXMCP_OPS_DIR`. Installed mode must continue rejecting relative roots and aliases that escape the root; source mode must retain documented legacy compatibility. Add explicit `ARXMCP_DATA_DIR=/app/var/arxmcp` to `infra/docker-compose.yml` and the container runtime environment so Docker no longer relies on `WORKDIR`-relative source detection while preserving its existing mounted-volume behavior.

Three constitutional constraints are load-bearing:

- `.claude/notes/01-mission-and-context.md` says, “Everything runs locally.” The check must require no network after the wheel has been installed and must not turn this milestone into a publisher or updater.
- `.claude/notes/08-security-observability-ops.md` requires “Structured JSON logs to stdout (12-factor).” **BRIEF/CONSTITUTION TENSION:** “log writes beneath the root” cannot mean redirecting normal server logs from stdout into an application file. Keep structured stdout behavior; place the smoke's capture file beneath the temporary root and confine only file-backed operational logs through `ApplicationPaths.logs`.
- `.claude/notes/02-architecture-overview.md` forbids “manual symlink swaps.” The smoke must use normal configuration and atomic production writers, not filesystem aliases that conceal an escaping path.

This milestone does not modify the MCP tool surface, so it must not re-pin `EXPECTED_TOOL_SCHEMA_SHA256`. Preserve the project bans on production `assert`, `BaseHTTPMiddleware`, the runtime `anthropic` SDK, and model-name leakage into `server/`. Preserve the load-bearing `KMP_DUPLICATE_LIB_OK=TRUE` guard in `tests/conftest.py` and the exact `kuzu==0.11.3` pin/path `var/arxmcp/index/kuzu/`.

If enhancing the real full-wheel check becomes too coupled or slow, the acceptable fallback is a dedicated installed-wheel probe module invoked by the existing full check, with the real `/healthz` launch left as a separate phase. The parent process must still own the filesystem manifests and must execute the probe using the installed venv's interpreter; a source-tree pytest subprocess is not equivalent evidence.

## Acceptance criteria the implementer must meet

1. `wheel-check-full` builds and fresh-installs the wheel into a venv created at its final arbitrary path, starts the installed `arxmcp-server` by absolute path from a separate non-repository CWD, uses a temporary absolute `ARXMCP_DATA_DIR`, and observes `/healthz` return 200 in bootstrap mode.
2. The child receives all application, cache, home, profile, and temporary-directory redirects before import; a before/after observer proves the repo, CWD, installed application, and other watched sandbox paths did not change while reporting the complete expected delta beneath the application root.
3. The smoke exercises real installed production writers for notebook/settings state, cache state, a log/capture artifact, and a corpus-marker sentinel; it does not infer write confinement solely from path resolution or bootstrap health.
4. Regression tests fail if installed mode derives writable state from `Path.cwd()`, the checkout, or a relative root, and cover all seven explicit per-store overrides plus installed-mode escape rejection.
5. Docker/Compose explicitly bind `ARXMCP_DATA_DIR` to `/app/var/arxmcp`; their volume semantics, source-checkout `make up`, wheel behavior, and explicit source-mode override compatibility remain unchanged.
6. `make test` exits 0, the opt-in full wheel check exits 0, and no tool-schema hash, Kùzu pin/path, macOS segfault guard, stdout logging contract, or source-checkout compatibility is unintentionally changed.

## Risks and open questions

1. **Vacuous confinement proof:** bootstrap intentionally skips most writable subsystems. Use the installed-runtime production-writer probe recommended above and require an enumerated delta; otherwise m2 could pass while cache or marker writers still escape.
2. **Observer scope:** a portable manifest cannot see every system-wide write. Bound the claim explicitly: redirect every known library-owned root before import, snapshot the complete temporary sandbox plus repo/install/CWD, and fail on unexpected paths. Do not claim OS-global filesystem tracing unless it is actually implemented on every supported platform.
3. **Logging ambiguity:** preserve JSON stdout. Treat the child-output capture as harness evidence under the data root and separately verify the canonical `logs/` path; do not introduce routine file logging merely to manufacture a write.
4. **Test runtime:** keep the installed-wheel boot in the existing opt-in `wheel-check-full` gate while unit-testing the observer, environment builder, and escape cases in `make test`. This preserves ordinary suite speed without weakening the pre-publish proof.
5. **Release closure:** spike 1 proved a frozen-sidecar direction but not model/native closure. That remains a desktop release concern, not a reason to broaden m2 beyond source-wheel path confinement.

## External writes the implementation will require

Only `git push origin main`, after local implementation, critique, rectification, and the required green gates. No package publication, release/tag creation, PR, ticket mutation, deployment, or third-party API write is required.
