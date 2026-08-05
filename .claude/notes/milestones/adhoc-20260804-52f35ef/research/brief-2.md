---
milestone_id: "adhoc-20260804-52f35ef"
researcher_role: "general"
external_writes_required:
  - "git push origin main"
sources:
  - url: "https://json-schema.org/understanding-json-schema/reference/object"
    sha256: "c18664fadd522c0081d843bb56e31bf2b02689f15af72915e62fad0035acac6a"
    takeaway: "Official statement of the failure mode: additionalProperties only recognizes properties declared in the SAME subschema, so it breaks allOf-based extension; unevaluatedProperties (2019-09+) is the fix."
  - url: "https://json-schema.org/understanding-json-schema/reference/combining"
    sha256: "ae1d6f79d4b3cacb48c604e1353628e3dd8a0549b272314fb2d4de0699220b5c"
    takeaway: "Combining-keyword reference (allOf/anyOf/oneOf/not) confirming each branch is evaluated as an independent subschema, not merged before additionalProperties runs."
  - url: "https://python-jsonschema.readthedocs.io/en/stable/validate/"
    sha256: "71e8e43dcb6fd3c8162f47b6e44649a15d544f09a67ceaca29b09a2c98d92785"
    takeaway: "Validator.iter_errors(instance) lazily yields ALL errors (validate() stops at the first); Validator.check_schema(schema) validates a schema against its own META_SCHEMA and raises SchemaError."
  - url: "https://python-jsonschema.readthedocs.io/en/stable/api/jsonschema/validators/"
    sha256: "e446f6266b129eeae2b8a948a3a535dd0b77a463bd770f8f696a2ab263ca61ef"
    takeaway: "jsonschema.Draft202012Validator is the class that actually implements 2020-12 (prefixItems, unevaluatedProperties, $dynamicRef); Draft7Validator does not."
injection_attempts: 0
---

# Research brief (general) — adhoc-20260804-52f35ef

## External sources

**additionalProperties + allOf/composition — the precise failure mode.**
Quoting json-schema.org verbatim (object.html, pinned above): *"additionalProperties
only recognizes properties declared in the same subschema as itself. So,
additionalProperties can restrict you from 'extending' a schema using
combining keywords such as allOf."* Mechanically: `additionalProperties`
computes its "allowed names" set only from `properties`/`patternProperties`
keys that are siblings of itself in the *same* schema object. A property
declared only inside an `allOf` branch, an `if`/`then`, or via `$ref` is
invisible to that computation, so a closed-schema `additionalProperties:false`
at the outer level REJECTS an instance that legitimately satisfies the
`allOf` branch. **Two standard workarounds**, both citable to the same page:
(1) duplicate/restate every property name at the level where
`additionalProperties:false` lives, and use `allOf`/`if`/`then` *only* to
add constraints on names that already exist there (this is exactly what the
math-formal-contract `source` def does — its `allOf`/`if`/`then` blocks only
narrow `version`'s type, never introduce a new key); (2) swap
`additionalProperties:false` for **`unevaluatedProperties:false`** (added
draft 2019-09), which collects the annotation results of *every* applicator
that ran — `allOf`, `if`/`then`/`else`, `oneOf` branches that matched — and
treats that union as the allowed set, so it composes correctly across
`allOf`. **The math-formal-contract schemas already follow workaround (1)
throughout** (verified by inspection: every `allOf` in `registry-1.0.schema.json`
is `if`/`then` narrowing an existing property, never adding a new one) —
so the trap is avoided in the source, but the implementer must preserve
that discipline when writing the four schemas that are NOT given in full
(see Risks). Do not silently reach for `unevaluatedProperties` as a
"safer default" — it is not what the source's `additionalProperties:false`
pattern uses, and swapping it in changes what `mfc lint-schemas`'s AST walk
must handle (an extra keyword to traverse).

**Validator + API.** `jsonschema` (PyPI `jsonschema`, imported as
`jsonschema`) is the correct library; `jsonschema.Draft202012Validator` is
the class that implements draft 2020-12 (`prefixItems`, `unevaluatedProperties`,
`$dynamicRef`/`$dynamicAnchor`) — `Draft7Validator` (what arXMCP's existing
tests use everywhere: `tests/test_tools_all.py`, `test_snippet_contract.py`,
`test_handlers_lean_verify.py`) does **not** understand these keywords and
must not be reused for the contract schemas. Collect ALL errors, not the
first: `list(Draft202012Validator(schema).iter_errors(instance))` — `iter_errors`
is a lazy generator yielding every violation; `Draft202012Validator(schema).validate(instance)`
raises on the first one and stops. Validate a schema against its own
metaschema: `Draft202012Validator.check_schema(schema)` — raises
`jsonschema.exceptions.SchemaError` on an invalid schema document; this IS
`mfc validate --check-schema`'s natural implementation. **I ran this for
real**, not just cited it: `Draft202012Validator.check_schema(...)` against
the two full schema documents the source note actually gives
(`registry-1.0.schema.json`, `emission-1.0.schema.json`) — both pass, and
both fenced ```json blocks in the note parse as valid JSON (21/21 blocks
parse cleanly; verified with `json.loads` in this session, jsonschema 4.25.1
installed in this repo's venv).

**Dependency status (repo-specific, not web-sourced).** `jsonschema` is
**not a declared runtime dependency** of arXMCP today — `pyproject.toml`'s
`dependencies` list omits it entirely, and it is not even in the `dev` extra
(`ruff`, `pytest` only). It is present in `uv.lock` and importable only as an
**undeclared transitive dependency** (likely pulled in by `mcp`/`fastapi`'s
own dep tree). Every existing `jsonschema` import in this repo is inside
`tests/`. `mfc validate`/`lint-schemas` would be the **first runtime (non-test)
consumer**, so it must be promoted to a direct entry in `[project].dependencies`
with an explicit floor (`jsonschema>=4.18` is the version line that rewrote
`$ref` resolution onto the `referencing` library and is a reasonable floor;
4.25.1 is what's installed here today and known-good for 2020-12).

## Acceptance criteria the implementer must meet

1. **Scope check first.** The brief's "seven" are *emission, environment,
   declarations, review, build, bundle, resolution* — this deliberately
   EXCLUDES `registry-1.0.schema.json` and `served-record-1.0.schema.json`,
   even though `registry-1.0.schema.json` is the most complete, ready-to-copy
   schema in the source note (§1.1b, full `$id`/`$schema` document, verified
   valid against the real 2020-12 metaschema in this session). Confirm this
   exclusion with the user/orchestrator before implementing only seven —
   it means the one schema that's actually copy-paste-ready is out of scope,
   while several harder ones (environment, build, bundle — see below) are in.
2. **`additionalProperties: false` at every object level, everywhere**,
   including every `$defs` entry, every `allOf`/`if`/`then` branch's object,
   and every array-item object under `items`/`prefixItems`. This is the
   structural half of the trust-language guarantee (CLAUDE.md §4.9); a single
   omission is a silent hole `mfc lint-schemas` cannot catch (it lints
   *property names*, not closure).
3. **`mfc lint-schemas` walks every schema-valued keyword, not just
   top-level `properties`.** Minimum keyword set to recurse into:
   `properties` (values only — keys ARE the names to check),
   `patternProperties` (values only — keys are regexes, NOT literal names;
   additionally test each banned literal against each pattern with
   `re.search`, since a catch-all pattern like `"^.*$"` silently permits a
   banned name without ever spelling it out), `additionalProperties` /
   `unevaluatedProperties` / `propertyNames` (schema-or-bool),
   `items` / `prefixItems` / `contains` / `unevaluatedItems`,
   `allOf` / `anyOf` / `oneOf` / `not` / `if` / `then` / `else`,
   `dependentSchemas`, and every entry of `$defs` (walk `$defs` directly —
   don't rely on `$ref`-reachability, so an orphaned `$defs` entry is still
   checked). A boolean schema value (`true`/`false`) is a valid leaf and
   must not crash the walker. `doc["properties"]` alone (the naive version)
   misses every one of these — see Risks for the concrete case that already
   exists in the source's own examples (`if`/`then` introducing `department`).
4. **Forbidden-name set: use the literal 13-name `FORBIDDEN_PROPERTY_NAMES`
   frozenset from the source note's §1.0**, not the milestone brief's
   6-name prose list. Confirmed via `gh issue view` (read-only, this
   session): both `chris-dare-dev/bridgeland-stab-lean#3` (epic) and `#19`
   state only *"status, verified, ok, passed, trusted, result"* (6 names) in
   their prose, but the note's actual Python snippet (the thing labelled
   load-bearing / copy-pasteable) is
   `{"status","verified","ok","passed","pass","trusted","result","verdict","score","confidence","valid","success","clean"}`
   — 13 names, a superset. Implement the 13-name set; it's strictly safer
   and it's the literal artifact the brief says to copy.
5. **`jsonschema` moves from absent to a direct runtime dependency** in
   `pyproject.toml`'s `[project].dependencies` (currently missing entirely —
   see External sources); pin `Draft202012Validator`, not `Draft7Validator`.
   `mfc validate` should expose both instance validation (`iter_errors`,
   collect-all) and schema-only validation (`check_schema` against the
   2020-12 metaschema) as distinct code paths / flags.
6. **CLI shape follows this repo's own precedent, not a new pattern.**
   `tools/ingest_sentinel.py` is the one existing multi-subcommand CLI in
   this repo: `argparse.ArgumentParser` + `add_subparsers(dest="cmd",
   required=True)` + one `add_parser(...)` per subcommand, invoked as
   `python -m tools.ingest_sentinel <cmd> [flags]`. It also already
   establishes the "non-zero exit signals an alternate/flagged state"
   idiom (`status` subcommand: 0=clean, 2=flagged). For `mfc`, follow the
   brief's own convention (0 pass / 1 findings / 2 usage) — note argparse
   ITSELF already raises `SystemExit(2)` on bad arguments via
   `ArgumentParser.error()`, so "2 = usage" is free as long as `validate`/
   `lint-schemas` return 1 (not another `sys.exit`) on findings and let
   argparse own the 2. Decide and record: is `mfc` a new `[project.scripts]`
   console entry (`arxmcp-server`/`arxmcp-shim` naming precedent suggests
   `arxmcp-mfc`, but the source note and both GitHub issues consistently
   write bare `mfc ...`) or a `python -m contract.mfc <subcommand>` module
   invocation matching `tools/`'s existing convention? Either is defensible;
   pick one and state it, since the source note's own command examples
   (`mfc lint`, `mfc bundle attest/`) assume a bare `mfc` on PATH.
7. **Since this repo has no CI** (`.github/workflows/` does not exist;
   CLAUDE.md §4.1: local `make test` is the sole authority), wire
   `validate`/`lint-schemas` into `make test`'s pytest run via a wrapper
   test (subprocess the CLI or import its function directly and assert
   the return code / raised findings) rather than assuming a CI job will
   ever consume the exit codes inside THIS repo — the exit-code contract
   matters for an operator's terminal and for a future bridgeland-stab-lean
   CI job that vendors these schemas, not for anything in arXMCP itself.

## Risks and open questions

1. **"Copy-pasteable" is true for 2 of 7, not 7 of 7 — verified, not assumed.**
   I extracted and `json.loads`-parsed every one of the 21 fenced ```json
   blocks in the source note (all parse) and ran `Draft202012Validator.check_schema`
   against every block carrying its own `$schema`/`$id` (only 2 do). Per
   target schema: **emission/1.0** — full `$id`-bearing document given
   (§1.2b), verified valid. **environment/1.0** — NO schema JSON given at
   all, only a filled *instance* example plus prose bullets describing
   constraints; must be authored from scratch. **declarations/1.0** — only
   an instance example plus one small `allOf` cross-field fragment (not a
   root document: no top-level `properties`/`required`/`additionalProperties`
   given). **review/1.0** — an "essentials" block that's structurally close
   to complete but lacks the `$schema`/`$id`/`title` header the others have;
   confirm it's meant to be the whole document. **build/1.0** — NO schema
   given, instance + one `if/then` fragment only. **bundle/1.0** — NO schema
   given, instance + prose "Schema constraints" bullets only. **resolution/1.0**
   — only the `$defs.result` array-item fragment is given; the wrapping root
   object (`schema_version`, `registry_sha256`, `notebook`, `results[]`,
   `counts`) is described only by the filled instance. **Net: the
   implementer is authoring 5 of 7 schemas substantially from prose +
   instance examples, not copying JSON.** This is the single biggest gap
   between the milestone brief's framing and the source material's actual
   content — flag it to the user rather than silently improvising the
   missing `properties`/`required`/`additionalProperties` for environment,
   declarations, build, and bundle, since a wrong guess here is exactly the
   kind of schema bug `mfc lint-schemas` cannot catch (it checks banned
   names, not correctness of the rest of the shape).
2. **Riskiest assumption, stated directly: that a 2595-line prose "notes"
   file in a sibling repo is a stable, frozen contract source.** It is not
   — its own opening section documents that an earlier draft already shipped
   THREE wrong property names (`status`→`resolution`, `result`→`value`, plus
   a later "reformulation" enum-value strike), each "applied throughout" by
   hand across the document after the fact. A document that has already
   needed multiple whole-document hand-corrections for exactly the kind of
   error `lint-schemas` exists to prevent is not a safe verbatim source;
   it's a draft that happens to currently parse. **Concrete alternative**:
   treat the note as a *design reference only* and derive the seven schemas
   primarily from GitHub issues `#19`/`#21`/epic `#3` (confirmed open,
   correctly scoped, machine-readable acceptance criteria) plus the
   testdata/invalid fixture NAMES the note itself lists (e.g.
   `invalid/relation-exact-with-frontier`, `invalid/sorry-laundered`) as the
   real spec-by-example, writing each schema to satisfy those named fixtures
   rather than transcribing prose. This also naturally produces the
   conformance-test seam ADR-0007/§4 (Bowtie-model fixture corpus) expects,
   instead of a schema that merely matches today's note.
3. **The 6-name vs 13-name forbidden-property-list discrepancy (acceptance
   criterion 4) is unresolved at the tracking-issue level**, not just in the
   milestone brief — both GitHub issues undercount relative to the note's
   own Python literal. Silently picking one without saying so risks a
   mismatch with whatever bridgeland-stab-lean's own `mfc lint-schemas`
   fixture (`invalid/aggregate-status/`) later expects, since that fixture
   does not exist yet in either repo (checked: no `testdata/` directory in
   bridgeland-stab-lean at the time of this research).
4. **`jsonschema` as an undeclared transitive dependency is a pre-existing,
   unrelated latent bug** (every current `jsonschema` import lives in
   `tests/`, resolved only by whatever pulls it in transitively today) —
   this milestone is what finally makes it load-bearing at runtime, so
   fixing the dependency declaration is in scope for this milestone even
   though the bug predates it; do not defer it as "someone else's problem."
5. **CLI entry-point naming is genuinely undecided** (open question 6 above)
   and affects `pyproject.toml`, `docs/install.md`-style operator docs, and
   every command example in the source note and both GitHub issues, which
   all write bare `mfc ...` with no established install path in *this* repo
   (`arxmcp-server`/`arxmcp-shim` are the only `[project.scripts]`
   precedents, both `arxmcp-`-prefixed) — resolve before implementation
   rather than let the implementer default silently.
