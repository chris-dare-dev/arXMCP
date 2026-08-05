---
milestone_id: "adhoc-20260804-52f35ef"
researcher_role: "explore"
injection_attempts: 0
---
# Research brief (explore) — adhoc-20260804-52f35ef

## Affected files / context

**New package (does not exist yet):** `contract/`, sibling to `server/`,
`ingest/`, `tools/`, `shim/`, `ops/` at repo root. Needs `contract/schemas/`
(seven `*.schema.json` files) and a CLI module (`contract/cli.py` or
`contract/mfc.py`) with `validate` and `lint-schemas` subcommands.

**Packaging (CLAUDE.md §4.5b — not covered by `make test`):**
- `/Users/chris.dare/Personal/SourceCode/arXMCP/pyproject.toml` —
  `[tool.setuptools.packages.find].include` is currently
  `["server*", "ingest*", "tools*", "shim*", "ops*"]`; needs `"contract*"`
  added or the wheel ships no `.py` from it. `[tool.setuptools.package-data]`
  needs a glob for the schema JSON files (mirrors the existing
  `"server.schemas" = ["*.json"]` entry) or they silently drop out of the
  wheel per the §4.5b failure mode. `[project.scripts]` optionally gains
  `mfc = "contract.cli:main"` (mirrors `arxmcp-shim` / `arxmcp-server`) —
  **only if** `mfc` should be an installed console command; see Risk 5.
  **`jsonschema` is not a declared dependency today** — it resolves only as
  a transitive dep of `mcp` (`uv.lock:684-707`, pinned `4.26.0` there). Every
  other dep in this file that arrives transitively is still declared
  explicitly "to match the project's no-implicit-deps discipline" (see the
  `pyyaml`/`jinja2`/`python-multipart` comments in the same file) — `contract/`
  validating against Draft 2020-12 needs `jsonschema.Draft202012Validator`,
  so add `"jsonschema>=4.18"` (or similar) as a direct dependency with the
  same comment convention.
- `/Users/chris.dare/Personal/SourceCode/arXMCP/docker/Dockerfile.server` —
  if `contract*` joins the packages-find include list,
  `tests/test_wheel_packaging.py::TestDockerfileMatchesPackaging::test_builder_stage_copies_every_declared_tree`
  (`tests/test_wheel_packaging.py:353-364`) derives the required `COPY`
  lines from `pyproject.toml` and fails the build check if
  `COPY contract/ ./contract/` is missing from **both** the builder stage
  (existing `COPY server/`, `ingest/`, `tools/`, `shim/`, `ops/` block
  around line 62-81) and the runtime stage (line ~140-160). See Risk 5 for
  whether this is even wanted.
- `/Users/chris.dare/Personal/SourceCode/arXMCP/tests/test_wheel_packaging.py`
  — `TestPackagesDeclared`, `TestPackageDataCoversEveryDataFile`,
  `TestConsoleScripts` (lines 105, 165, 231) all walk the on-disk tree
  against `pyproject.toml` and will need `contract/` accounted for one way
  or another.

**Test discovery:** `pyproject.toml`'s `[tool.pytest.ini_options]` sets
`testpaths = ["tests"]`. `contract/` tests **must live under `tests/`**
(e.g. `tests/test_contract_schemas.py`, `tests/test_mfc_cli.py`, or a
`tests/contract/` subdir) — pytest will not discover anything under
`contract/` itself. `tools/validate_eval_fixtures.py` is the repo's
precedent for "implementation module ships its own CLI + is wrapped by a
`tests/**` pytest module that calls its public function directly."

**Ruff:** `contract/` is not in `extend-exclude` (`[".claude", "var"]`),
so it is linted at `select = ["E", "F", "I", "B", "UP", "SIM", "S101"]`,
`line-length = 100`, `target-version = "py311"`. It gets **no** `S101`
(bare-`assert`) exemption — that's `tests/**`-only — so any invariant check
in `contract/` must be `if … raise RuntimeError(...)`, not `assert`
(CLAUDE.md §4.7).

**CLI style precedents (argparse, this repo's idiom, no click/typer
anywhere):**
- `/Users/chris.dare/Personal/SourceCode/arXMCP/tools/validate_eval_fixtures.py`
  — `REPO_ROOT = Path(__file__).resolve().parent.parent` +
  `sys.path.insert(0, str(REPO_ROOT))` so `python tools/x.py` works without
  install; single `argparse.ArgumentParser`; `FAIL:`-prefixed message to
  stderr + `return 1` on error, `OK:`-prefixed message to stdout + `return 0`
  on success; `if __name__ == "__main__": sys.exit(_main())`.
- `/Users/chris.dare/Personal/SourceCode/arXMCP/tools/ingest_sentinel.py`
  — the repo's only existing **subcommand** CLI:
  `sub = p.add_subparsers(dest="cmd", required=True)`, one
  `sub.add_parser("write", help=...)` per subcommand with its own
  `.add_argument(...)` calls, `if args.cmd == "write": ...`, distinct exit
  codes per outcome (`0` running, `2` paused — not just 0/1).
- `/Users/chris.dare/Personal/SourceCode/arXMCP/server/cli.py` — the
  lazy-import pattern (`main()` imports heavy deps *inside* the function
  body, never at module scope) so `--help`/`--version` stay cheap and
  can't crash on an unrelated config error; `--version` via
  `importlib.metadata.version("arxmcp")` with a graceful
  `PackageNotFoundError` fallback.
- The source doc's own worked CLI shape:
  `mfc validate --schema served-record/1.0 /tmp/records.json`
  (`.claude/notes/2026-08-04-contract-schemas.md:2384`) — i.e. `validate`
  takes `--schema <artifact-name>/<MAJOR.MINOR>` plus a positional file
  path, and resolves that string to the matching
  `contract/schemas/<name>-<major>.<minor>.schema.json`.

**Existing JSON Schema usage (repo-wide grep, confirmed):**
- `jsonschema` **is** resolvable today (transitive via `mcp`) but not a
  declared dependency (see above).
- `/Users/chris.dare/Personal/SourceCode/arXMCP/server/schemas/lean_verify_result.json`
  and `search_papers_result.json` — the two existing hand-written JSON
  Schema files in the repo. **Both are Draft-07**
  (`"$schema": "http://json-schema.org/draft-07/schema#"`), **not**
  2020-12, and deliberately so:
  `/Users/chris.dare/Personal/SourceCode/arXMCP/tests/test_tools_all.py:229-251`
  (`TestSchemaConformance::test_all_input_schemas_are_draft7_compatible`)
  asserts every MCP tool's `inputSchema` is Draft-07-compatible and
  explicitly **fails if `$defs` appears anywhere** ("Draft-2020-12-only;
  Draft-07 expects 'definitions'"). This is a **separate validation
  domain** from the new `contract/` schemas (MCP tool wire schemas vs.
  cross-repo bridge-contract artifacts) — the new work must not be
  conflated with it, and must not be swept into that Draft-07 test.
  `lean_verify_result.json` also currently uses a top-level `status`
  property — CLAUDE.md §4.9 rule 1 records this as a **named, scoped
  deferral** (`verification-contract-e3`), not a precedent to extend; the
  new `contract/` schemas ban `status` outright via `lint-schemas` and are
  not required to (and should not) retrofit the existing tool-result
  schemas.

**CLAUDE.md §4.9 — trust language / evidence ledger (quoted for the
implementer):**

> 1. **No bare "verified".** No tool response carries a single "verified"-style status that
>    collapses distinct trust questions into one token. Trust is a multi-axis record (an ordinal
>    level + attached evidence per axis); **no axis is inferred from another** — fidelity is
>    never inferred from elaboration. New trust-bearing fields are namespaced and axis-specific,
>    never a new bare `status`.
> 2. **Abstention is a first-class, tested success state.** Every tool must be able to return the
>    epistemic outcomes `unknown` / `ambiguous` / `not-in-corpus` / `unsupported-by-provider`...
> 3. **Novelty claims are dated, scoped censuses.**

`lint-schemas` is what the milestone brief calls this policy's first
*machine* enforcement mechanism (as opposed to by-reference review
discipline, which is what §4.9 currently says enforcement is: "by-reference
discipline (no CI linter or schema validator this track)"). Building
`lint-schemas` is therefore also, incidentally, the first concrete
counterexample to that "no CI linter" sentence — worth a one-line note in
the implementation commit, not a §4.9 rewrite (out of this milestone's
scope).

**Source material (read-only sibling repo,
`/Users/chris.dare/Personal/SourceCode/bridgeland-stab-lean/`, NOT
modified):**

`.claude/notes/2026-08-04-contract-schemas.md` (2594 lines) is the cited
copy-paste source. Section map for the seven schemas the brief names
(`emission, environment, declarations, review, build, bundle, resolution`)
— **completeness varies sharply per schema, and this is the single most
important finding of this research pass:**

| Schema | Section | Completeness |
|---|---|---|
| `emission/1.0` | §1.2, lines 553–753 | **FULL.** §1.2b (lines 642–720) is a complete, copy-pasteable `$schema`/`$id`/`type`/`additionalProperties`/`required`/`properties`/`$defs` document. §1.2c (722–752) adds 10 `mfc lint` content rules (`E-01`..`E-10`) — those are semantic rules for a *different*, out-of-scope `mfc lint` subcommand (see Risk 3), not `lint-schemas`. |
| `review/1.0` | §1.5, lines 905–1001 | **NEAR-FULL.** "schema essentials" (960–998) gives a complete `type`/`additionalProperties`/`required`/`properties`/`allOf` body for the reviews array + each review object, including two cross-field `if/then` rules. Missing only the top-level `$schema`/`$id` wrapper — otherwise copy-pasteable. |
| `resolution/1.0` | §1.8, lines 1131–1204 | **PARTIAL.** A filled instance is given, and the per-result-object schema (`$defs.result`, lines 1176–1203) is complete with three `allOf` conditional rules — but the **envelope-level** properties (`schema_version`, `registry_sha256`, `notebook`, `corpus_version`, `corpus_manifest_content_hash`, `resolver_version`, `chunker_version`, `generated_at`, `results`, `counts`) are never spelled out as a schema; must be inferred from the filled instance at lines 1135–1170. |
| `declarations/1.0` | §1.4, lines 829–901 | **SKETCH.** Filled instance + Python recomputation rules (`mfc/bundle.py`, lines 878–889) + **one** small cross-field `allOf` fragment (sorryAx consistency, lines 893–900). No `properties`/`required` block at all — the implementer authors the full schema from the instance. |
| `build/1.0` | §1.6, lines 1004–1059 | **SKETCH.** Filled instance + prose tables (measured Lake/REPL exit-code facts) + one `if/then` fragment (`independent_checkers[].value`/`allow_sorry`, lines 1054–1058). No `properties` block. |
| `environment/1.0` | §1.3, lines 756–826 | **SKETCH.** Full filled instance, but the schema itself is given only as prose "Schema notes" bullets (820–825: patterns, nullability, a `worktree_dirty` CI-mode rule) — no JSON at all for the schema document. |
| `bundle/1.0` | §1.7, lines 1062–1129 | **SKETCH.** Filled instance (in-toto Statement v1 shape) + prose "Schema constraints" bullets (1123–1127) only. No JSON Schema given whatsoever. |

Also present, **out of the milestone's seven**: `registry/1.0` (§1.1, lines
213–551 — lives in `bridgeland-stab-lean/registry/`, not arXMCP) and
`served-record/1.0` (§1.9, line 1210+ — the shape an arXMCP *resource*
composes at serve time, future R5 work, not a file `contract/` validates).

**Two corrections at the head of the source doc, both load-bearing and
easy to miss on a partial read:**
1. (lines 5–6) The brief's own worked examples elsewhere use
   `resolution.json.status` and `build.json.independent_checkers[].result`
   — **both wrong**, both already forbidden by `lint-schemas`. The real
   field names are `resolution` (resolution/1.0) and `value`
   (build/1.0, independent_checkers).
2. (lines 7–17) **`relation_claimed` has FIVE values, not six —
   `reformulation` is struck**, applied "throughout": `exact | equivalent
   | specialization | one_way | no_claim`. This binds the `cite.$defs`
   enum inside `emission/1.0` (line 712). `review/1.0`'s separate
   `relation_confirmed` field keeps **six** (adds `disputed`, review-only,
   not struck) — do not merge the two enums.

**Forbidden-name list — the actual load-bearing constant**
(`.claude/notes/2026-08-04-contract-schemas.md:204-207`):

```python
FORBIDDEN_PROPERTY_NAMES = frozenset({
    "status", "verified", "ok", "passed", "pass", "trusted", "result",
    "verdict", "score", "confidence", "valid", "success", "clean",
})
```

13 names. The milestone brief prose only names 6
(`status/verified/ok/passed/trusted/result`) — see Acceptance Criterion 2.
Line 201: *"enforced by `mfc lint-schemas` walking every `properties` key
of every schema in `schema/`"* — this means walking recursively, including
every nested `$defs` entry's own `properties`, not just the top level.

**ADR context (also read-only, same sibling repo):**
- `.claude/decisions/ADR-0007-contract-package-location.md` — the decision
  the milestone brief cites: schemas + `mfc` live in `arXMCP/contract/`;
  topic repos vendor pinned copies with a checksum-drift test (mirroring
  `EXPECTED_TOOL_SCHEMA_SHA256`); §5.4 rule 7 ("no shared Python package
  imported by both repos") is why `mfc` is arXMCP-side only.
- `.claude/decisions/ADR-0001-the-seam-is-cold.md` — the cold-seam
  rationale; asserts (quoting a document I could not locate — see Risk 1)
  that all cross-repo artifacts "must therefore ride that system's common
  envelope (§5.2) and its artifact-type registry (§5.3)."
- `.claude/open-questions.md` — Q2 (repo location, answered → ADR-0007),
  Q4 (registry size ceiling — the single biggest named risk to the whole
  ecosystem plan, not specific to this milestone), Q5 (`quote_mode`
  default).

## Acceptance criteria the implementer must meet (max 7)

1. `contract/` created at repo root (parallel to `server/`, `ingest/`,
   `tools/`, `shim/`, `ops/`) with `contract/schemas/` holding exactly
   seven files — `emission-1.0.schema.json`, `environment-1.0.schema.json`,
   `declarations-1.0.schema.json`, `review-1.0.schema.json`,
   `build-1.0.schema.json`, `bundle-1.0.schema.json`,
   `resolution-1.0.schema.json` — each declaring
   `"$schema": "https://json-schema.org/draft/2020-12/schema"` and
   `"additionalProperties": false` on **every** object node, top-level and
   every nested `$defs` entry alike.
2. `mfc lint-schemas` recursively walks every `properties` key (top-level
   and nested `$defs`) of every `*.schema.json` under `contract/schemas/`
   and hard-fails (non-zero exit) if any property is named one of the
   **13** names in `FORBIDDEN_PROPERTY_NAMES`
   (`.claude/notes/2026-08-04-contract-schemas.md:204-207` — status,
   verified, ok, passed, pass, trusted, result, verdict, score,
   confidence, valid, success, clean), not just the 6 the milestone-brief
   prose paraphrases. It must also confirm `additionalProperties: false`
   is set on every object schema it walks — the naming ban alone is a
   review habit; pairing it with `additionalProperties:false` is what the
   source doc calls the actual structural guarantee.
3. `mfc validate --schema <name>/<MAJOR.MINOR> <file>` resolves the given
   artifact/version string to
   `contract/schemas/<name>-<MAJOR>.<MINOR>.schema.json`, loads the target
   file, and validates it with `jsonschema.Draft202012Validator` (add
   `jsonschema` as an explicit `pyproject.toml` dependency — currently
   only transitive via `mcp`, `uv.lock` already resolves `4.26.0`).
4. Both subcommands follow this repo's existing CLI idiom: argparse with
   `add_subparsers(dest="cmd", required=True)`
   (`tools/ingest_sentinel.py` pattern), `REPO_ROOT`-relative default
   paths (`tools/validate_eval_fixtures.py` pattern), `0` on success /
   non-zero on failure, `if __name__ == "__main__": sys.exit(main())`.
5. For the five schemas the source doc gives only as a filled instance
   plus prose (`environment`, `declarations`, `build`, `bundle`) or a
   partial fragment (`resolution`'s envelope), the implementer authors the
   missing `type`/`required`/`properties` bodies directly from those
   instances + prose constraints, matching the rigor of the two
   fully-specified schemas (`emission` §1.2b, `review` §1.5) — including
   every documented pattern (`^[0-9a-f]{64}$` for sha256 fields,
   `^[0-9a-f]{40}$` for git revs, the `stmt:` key pattern, etc.) and every
   documented cross-field `allOf`/`if`/`then` rule already given in prose.
6. The `relation_claimed` enum wherever it appears inside `emission/1.0`
   (its `cite.$defs`) has exactly five values —
   `["exact","equivalent","specialization","one_way","no_claim"]` —
   `reformulation` struck per the correction at the top of the source doc.
   `review/1.0`'s distinct `relation_confirmed` enum keeps six values
   (adds `disputed`) and must not be conflated with the first.
7. A decision — stated explicitly in the implementation, not defaulted —
   on whether `contract/` ships in the built wheel / Docker image. If yes:
   `pyproject.toml`'s `packages.find.include` gains `"contract*"`, matching
   `package-data` globs are added for the schema JSON files, and
   `docker/Dockerfile.server` gets `COPY contract/ ./contract/` in both
   the builder and runtime stages (required by
   `tests/test_wheel_packaging.py::TestDockerfileMatchesPackaging`). If
   no: `contract/` stays a repo-local dev/CI tool invoked via
   `python -m contract.cli`, with no `[project.scripts]` entry and no
   Dockerfile change — but then `docs/install.md` (or wherever `mfc` is
   documented) must not promise an installed `mfc` command it doesn't
   ship, the exact issue #206 failure CLAUDE.md already narrates for
   `arxmcp-server`.

## Risks and open questions (max 5)

1. **The cited "bridge envelope" source document does not exist on this
   machine, and the seven schemas as specified may conflict with it.**
   `_pipeline/stage-1-discovery/synthesis/target-architecture.md`, which
   the milestone brief's own STEP 2.3 asks me to read directly, and which
   bridgeland-stab-lean's `ADR-0007`, `ADR-0001`, and `open-questions.md`
   all cite as living "at the Source Code root" (i.e.
   `/Users/chris.dare/Personal/SourceCode/_pipeline/...`), **is not present
   anywhere under `/Users/chris.dare/Personal/SourceCode` or
   `/Users/chris.dare/Personal`** (confirmed by `find`, both narrow and
   broad passes). Everything about its §5.2 "bridge envelope"
   (`bridge.{artifact, version, producer, produced_at, substrate{...}} +
   payload`) and §5.3 "artifact-type registry" is known only second-hand,
   via direct quotes embedded in the three ADR/open-question files. More
   concretely: **none of the seven filled instances in
   `2026-08-04-contract-schemas.md` actually nest under a `bridge.*`
   wrapper** — every one (`emission`, `environment`, `declarations`,
   `review`, `build`, `bundle`, `resolution`) has `schema_version` as its
   literal first top-level key, flat, no envelope. This is an unresolved
   tension between what ADR-0007/ADR-0001 assert ("our artifacts must use
   this envelope") and what the milestone brief's explicit copy-paste
   source actually contains. Recommend building the seven schemas exactly
   as given in `contract-schemas.md` (flat, no `bridge` wrapper) since
   that document is the brief's stated source and the wrapper's
   specification cannot be independently verified — but this should be a
   conscious call by whoever reviews the implementation, not a silent one.
2. **`2026-08-04-contract-schemas.md` predates and is partly superseded by
   `ADR-0007`, dated the same day.** Its own "Files this deliverable
   specifies" section (lines 2578–2584) and its CI-workflow examples
   (`pipx install "git+https://github.com/chris-dare-dev/math-formal-contract@..."`,
   `mfc join --lean ... --registry ...`, Windows-style
   `C:/Users/cedar/...` paths) describe the earlier three-repo design that
   `ADR-0007` explicitly overrides — schemas now live in `arXMCP/contract/`,
   not a separate `math-formal-contract` repo. Only the JSON Schema bodies
   and the `validate`/`lint-schemas` CLI *behavior* from that document are
   in scope here; its deployment-topology and install-command examples
   must not be followed literally.
3. **The milestone's `mfc` is a small slice of a much larger imagined
   tool.** The source doc's `mfc` also has `bundle`, `lint` (content
   linting against ~15+ semantic rules like `E-01`..`E-10`, `V-01`/`V-02`,
   `R-01`), `registry`, `conformance`, `join`, `caveats`, `init`,
   `check-ilean-coverage`, and `check-resolution` subcommands — none of
   which are in this milestone's scope (only `validate` and
   `lint-schemas`). Building any of these beyond what's asked would be
   scope creep; conversely, an implementer skimming the doc could
   plausibly mistake `mfc lint`'s ~15 semantic content rules for what
   `lint-schemas` must do — they are a different subcommand checking a
   different thing (instance content vs. schema-file property names).
4. **Five of seven schemas require real design work, not transcription** —
   `environment`, `declarations`, `build`, `bundle` are sketches (filled
   instance + prose only) and `resolution`'s envelope is unspecified.
   Only `emission` and `review` are close to copy-paste-ready. Budget
   accordingly; a critique pass should specifically check the
   implementer-authored schema bodies against the filled instances and
   prose constraints for gaps, since there's no existing document to diff
   against for these five.
5. **Whether `contract/` ships in the wheel/Docker image is undecided by
   the brief** (see Acceptance Criterion 7) and has real, opposite-direction
   packaging consequences either way — `pyproject.toml` +
   `docker/Dockerfile.server` + `tests/test_wheel_packaging.py` all branch
   on this. Getting it wrong reproduces the exact class of bug issue #206
   fixed (a documented command that doesn't exist, or an image COPY of a
   tool the server never runs).
