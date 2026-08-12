---
milestone_id: "desktop-distribution-m11"
researcher_role: "explore"
injection_attempts: 0
---

# Research brief (explore) — desktop-distribution-m11

## Affected files / context

- `server/application_paths.py` — `ApplicationPaths.resolve` (`:115-183`) is the
  single canonicalizer for the whole tree. `root` param + `ARXMCP_DATA_DIR` env
  already give an "operator-chosen root" input path in `source`/`installed`
  mode (`:126-149`); `_inside`/`_canonical` (`:52-67`) already reject `..` and
  do component-wise-after-resolve containment for every derived path, and
  `_platform_data_root` (`:81-89`) is the existing default. **What does not
  exist**: any caller that offers this as an operator *choice* rather than an
  env var the operator must already know to set, any adoption-detection step,
  any free-space check, and any persistence of the choice across restarts
  (`ARXMCP_DATA_DIR` is not persisted anywhere — it must be re-supplied every
  launch, which is fine for a source checkout's shell profile but wrong for a
  double-clicked `.app` with no env at all).
- `tests/test_application_paths.py` — the m1 traversal suite: 9 tests, covering
  cwd-independence (`:15`), strict alias containment (`:37`), explicit-source
  external alias (`:56`), installed-mode single-root derivation (`:70`,
  `:86`), source-mode alias propagation (`:112`), symlink escape (`:154`),
  symlink loop (`:168`), and read-only-`prepare` propagation (`:176`). None of
  these currently drive an *operator-supplied, not-yet-existing* root through
  adoption/creation — they assert containment given a root, not the UX of
  picking one. AC5 of the brief ("re-run against operator-chosen roots
  including Unicode and whitespace-bearing ones") is asking for new test rows
  on the SAME fixture shape, not a new suite.
- `server/operator_settings.py` — `OperatorSettingsStore` / the sync
  `get_setting`/`set_setting` helpers, backed by `notebooks.db`. **Central
  design problem, confirmed by reading the code, not assumed:**
  `_resolve_db_path` (`:106-111`) falls back to
  `ApplicationPaths.resolve().notebooks_db`, i.e. `<data_root>/cache/notebooks.db`
  (`_LAYOUT` `:29` — `"notebooks_db", "cache/notebooks.db"`). The store's own
  default location is *inside* the data root it would need to name. A
  first-run "which root did the operator pick" fact cannot be read before the
  data root is known, because reading it requires already knowing the data
  root. The docstring's promise of "wizard dismissal-state" as a future key
  (`:9`) is compatible with storing OPERATOR PREFERENCES once a root is
  already selected (e.g. "don't show me the adoption prompt again for this
  root"), but it cannot be the single source of truth for WHICH root that is.
  This is not a documentation gap; it is a real ordering cycle and m11 has to
  resolve it, not paper over it.
- `apps/desktop/crates/supervisor/src/main.rs` — `self_authored_plan`
  (`:512-533`) is the self-authoring arm m10 built and the one the brief's
  "reach the supervisor" question is about. It calls `platform_data_root(lookup)`
  (`:210-233`, the Rust port of `_platform_data_root`) UNCONDITIONALLY —
  confirmed by grep: the only `env::var`/`lookup(` call sites in the file are
  `platform_data_root`'s own `USERPROFILE`/`HOME`/`LOCALAPPDATA`/
  `XDG_DATA_HOME` reads (`:212-230`), the `PLAN_ENV` (`ARXMCP_DESKTOP_LAUNCH_PLAN`)
  gate in `main()` (`:134`), the diagnostic probe's `CHILD_PLAN_PROBE_OUT_ENV`
  (`:495`), and the test barrier env (`:560`). **There is no `ARXMCP_DATA_DIR`
  read anywhere in `main.rs`.** The self-authored plan therefore always sends
  the platform default as `data_root` (`:518`, `wire_path(&data_root)` at
  `:529`) to the child via the `launch` frame
  (`server/desktop_child.py:186,205,379` — `Config(data_dir=Path(frame.data_root))`).
  An operator-chosen root has NO path into a double-clicked `.app` today; the
  only existing override channel (`ARXMCP_DATA_DIR`) is Python-side only and
  is exactly the smoke-test/dev-run knob the self-authored arm exists to NOT
  require (m10's `smoke: false` self-authored plan is deliberately the one
  arm that runs with `ARXMCP_DESKTOP_LAUNCH_PLAN` absent).
- The executable parity matrix m10 pinned (`the_home_lookup_is_lazy_like_pythons`,
  `platform_data_root_reads_the_branch_its_platform_owns`, and the
  cross-language row-for-row env matrix in
  `tests/test_desktop_self_authored_launch.py`) exists specifically to keep
  Rust's `platform_data_root` byte-identical to Python's
  `_platform_data_root` for the DEFAULT case. Any mechanism that lets an
  operator override the root must not perturb that default-path parity — it
  needs to be an override that both languages read and agree on, sitting
  ahead of `platform_data_root` in the resolution order rather than inside
  it, or the parity matrix silently stops meaning what it currently proves.
- **What "already carries arXMCP state" means, concretely, and where each
  marker lives (all data-root-relative, per `_LAYOUT` in
  `application_paths.py:24-33`):**
  - `<root>/cache/notebooks.db` — the `NotebooksStore` SQLite registry
    (`server/notebooks_store.py`), notebook count = `SELECT COUNT(*) FROM
    notebooks`.
  - `<root>/index/lancedb/<notebook>/corpus-version.json` — per-notebook
    corpus epoch marker, read by `server.corpus.read_corpus_version`
    (`server/corpus.py:514`); `server/corpus_manifest.py:317`
    (`_safe_read_corpus_version`) already exists as a never-raising per-slug
    reader that would be the natural detection primitive to call once per
    notebook directory found under `<candidate>/index/lancedb/`.
  - `<root>/index/kuzu/` — the Kùzu citation-graph directory
    (`ingest/kuzudb_schema.py`).
  A detector for "does this candidate root already carry state" is therefore:
  does `<candidate>/cache/notebooks.db` exist and have rows, OR does
  `<candidate>/index/lancedb/*/corpus-version.json` exist for any notebook.
  Nothing in the repo currently runs this check; it would be new code, but
  every primitive it needs (`NotebooksStore.open`, `_safe_read_corpus_version`)
  already exists and is exercised elsewhere, so this is composition, not a
  new subsystem.
- **Free-space check:** `shutil.disk_usage` is already used at
  `server/health.py:499,1196` (readiness/metrics gauges) and referenced at
  `server/config.py:420`. No pre-adoption gate exists yet; the mechanism to
  build one is already in the codebase and battle-tested for the read side,
  just not wired to a refusal-before-adoption path.
- **UI surface:** two candidate hosts, neither built for this today.
  - The loopback Jinja2+htmx console (`server/routes/ui.py`, `GET /ui/`) is
    server-rendered — it cannot run before the server has picked a data root,
    because `server.main.create_app`'s lifespan resolves `ApplicationPaths`
    and constructs `Resources` at startup (`enable_rerank`/`bootstrap_mode`
    docstrings in `server/config.py:190-238` describe startup-time resource
    binding). `bootstrap_mode` (`config.py:218-238`, `onboarding-uplift-m4`)
    already lets the server boot with **no corpus** and short-circuit MCP
    tools to a `no_notebook_selected` envelope — but note this is a DIFFERENT
    problem than m11's: bootstrap_mode assumes the DATA ROOT is already
    known and just empty of notebooks. It does not address "which directory
    is the data root" — that question is settled (via `ARXMCP_DATA_DIR` or
    the platform default) before `Resources.startup` ever runs. So `/ui/`
    is not a viable first-run-data-root host as the server is built today: by
    the time `/ui/` can render anything, the root is already fixed.
  - The Tauri window (`apps/desktop/crates/supervisor`) is the only surface
    that runs BEFORE the server starts, since the supervisor spawns the child
    with the plan (including `data_root`) it authors. This is the only
    plausible host for the actual choice UI: native Tauri window → operator
    picks/confirms a root → supervisor writes the choice to whatever
    mechanism resolves the chicken-and-egg problem above → supervisor
    proceeds to `self_authored_plan` (extended to read that mechanism ahead
    of `platform_data_root`) → child launches against the confirmed root.
    Nothing in `apps/desktop/crates/supervisor` today renders any window
    content beyond what `lifecycle.rs`/`main.rs` already drive for the
    fixture/production child lifecycle; a first-run dialog would be new Tauri
    surface, not a repoint of existing UI.

## Acceptance criteria the implementer must meet

1. First run with no prior state offers the platform default, accepts an
   operator-chosen directory, and every subsequent write lands under the
   chosen root — re-run the m2 write-containment regression against the
   chosen root (`server/application_paths.py` `ApplicationPaths.resolve` +
   `.prepare()`).
2. A root already carrying a notebooks registry or corpus marker is detected
   (see detection primitives above) and adopted, reporting notebook count +
   corpus version before adoption; initialization over existing state
   requires a distinct, explicit operator act.
3. Unwritable / non-existent-and-uncreatable / full-disk roots each produce a
   distinct, actionable message and leave no partial state; a failing root
   never becomes the persisted choice.
4. Free space is measured against a stated requirement before adoption, named
   in the refusal rather than surfacing later as an ingest failure
   (`shutil.disk_usage` is the existing primitive to reuse).
5. `ApplicationPaths.resolve`'s escape/symlink/inconsistent-resolution
   rejection continues to hold for operator-supplied roots — re-run the m1
   traversal suite (`tests/test_application_paths.py`) against operator-chosen
   roots, including Unicode and whitespace-bearing ones.
6. Selection survives restart; a root that has disappeared between launches
   is reported, not silently re-defaulted — this is the acceptance criterion
   that most directly requires solving the chicken-and-egg persistence
   problem above, since "survives restart" for a double-clicked `.app` means
   surviving with NO shell environment carrying `ARXMCP_DATA_DIR` forward.
7. `make test` and `make desktop-conformance` exit 0.

## Risks and open questions

1. **The central design problem (restated as a decision the implementer
   must make, not research further):** the operator's root choice cannot
   live inside `notebooks.db` (it's data-root-relative) and cannot live only
   in an env var (doesn't survive a double-click with no shell). It needs a
   small persistence mechanism that is itself NOT data-root-relative —
   e.g. a fixed-location pointer file at the platform's own stable
   OS-standard location (the same `_platform_data_root()`/`platform_data_root()`
   directory pair, or a sibling of it) whose entire content is the chosen
   root's path, read by BOTH Python (`ApplicationPaths.resolve`, ahead of its
   current env/default resolution) and Rust (`self_authored_plan`, ahead of
   its current `platform_data_root` call) before either language does
   anything else. Whatever shape this takes, it is a NEW artifact this
   milestone introduces, not a repoint of `operator_settings.py` — the brief's
   framing ("selection persists through `OperatorSettingsStore`... no new
   store is introduced") is contradicted by the code as it stands today and
   should be treated as the brief's error, not a constraint to force-fit.
2. **Parity-matrix interaction.** Any override read added ahead of
   `platform_data_root`/`_platform_data_root` in either language changes the
   resolution order both m10 parity tests currently assume is "env vars in,
   platform default out." The override lookup itself will need its own
   cross-language parity test (same shape as the existing HOME/XDG/LOCALAPPDATA
   rows) or the m10 guarantee silently narrows to "only the default path is
   proven to agree."
3. **No first-run UI exists anywhere in the repo today.** The Tauri window is
   the only plausible host (server can't render `/ui/` before its root is
   fixed), but the supervisor crate currently has no window-content-rendering
   surface built out beyond lifecycle plumbing — this is new Tauri-side
   surface area, and the milestone's complexity estimate (M) should be
   checked against that, not just against the Python-side detection/free-space
   logic which is comparatively small composition work.
4. **The inherited AC3 launch-proof obligation (m15's narrowed AC3).**
   m15's gate proves artifact assembly/seal/payload-resolution via
   `--print-child-plan`, explicitly NOT a real boot to a ready server and
   rendered window, because that needs the real frozen child loading BGE-M3 +
   reranker (~4.6 GB, `requires_bundled_model` prerequisites, external HF
   cache). m11 is recorded as the milestone that inherits this because it is
   "the first milestone that needs a launching application for its own
   purpose" (m15 rectify summary, H1 disposition). Assessed honestly: m11's
   OWN acceptance criteria (as given in the roadmap, reproduced above) do not
   require a real end-to-end boot either — they are about root
   selection/detection/persistence, testable with the fixture sidecar or a
   Config-level unit/integration test, not with the real frozen child. If
   m11 is ALSO expected to discharge the full "double-click → ready server →
   rendered window with real models" proof, that is a SEPARATE, `requires_bundled_model`-gated
   gate this milestone would have to add on top of its stated ACs — at real
   cost: it needs the ~4.6 GB HF cache present on the CI/dev box, a
   `requires_desktop_bundle`+`requires_bundled_model` combined marker (neither
   currently combined anywhere in `pyproject.toml`'s registered markers), and
   a new Makefile gate analogous to `desktop-model-check` but driving the
   ASSEMBLED bundle rather than the onedir. This is a real, non-trivial
   addition to scope that the roadmap prose does not currently spell out as
   an acceptance criterion, and the researcher recommends the orchestrator
   confirm with the owner whether m11 is expected to also close it or whether
   it should be named as its own follow-on (the roadmap and m15's rectify
   note disagree on this by omission, not by contradiction).
5. **`ApplicationPaths.resolve`'s relative-path-in-source-mode allowance**
   (`:132-139`, warns and treats a relative `ARXMCP_DATA_DIR` as
   cwd-relative in `source` mode only) is a divergent code path from
   `installed`/`container` mode's absolute-only requirement. Whatever
   first-run UI collects the operator's chosen directory should decide up
   front whether it always resolves to an absolute path before it reaches
   `ApplicationPaths.resolve`, rather than inheriting the source-mode leniency
   into a flow meant for a shipped `.app`.
