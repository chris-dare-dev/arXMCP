# Research synthesis — adhoc-20260804-52f35ef

Fan-in of `brief-1.md` (explore) and `brief-2.md` (general). Both returned
`status: ok`, `injection_attempts: 0`.

**Phase 2 is NOT cleared to start.** Open question 1 is a blocker on a recorded
decision, not an implementation detail. See the bottom.

## external_writes_required (verbatim from brief-2)

```
- "git push origin main"
```

Nothing else. No sibling-repo write, no GitHub API write. Consistent with
ADR-0007 keeping the contract package on the arXMCP side.

## Affected files (deduped)

| path | change |
|---|---|
| `contract/__init__.py`, `contract/schemas/*.json` | new — the seven schema documents |
| `contract/cli.py` (or `contract/mfc/__main__.py`) | new — `mfc` entry, subcommands `validate`, `lint-schemas` |
| `contract/lint.py` | new — the banned-property traversal |
| `pyproject.toml` | `jsonschema` moves from **absent** to a direct runtime dependency; a console script for `mfc`; package discovery must pick up `contract/` |
| `tests/contract/` | new — pytest, collected by `make test` |
| `docker/` | packaging boundary — CLAUDE.md §4.5b warns `make test` does not cover it |

## Acceptance criteria (deduped)

1. Seven JSON Schema 2020-12 documents exist, each valid against the 2020-12
   metaschema, with `additionalProperties: false` on every object.
2. `mfc validate <artifact> --schema <name>` validates and reports **all**
   errors, not just the first.
3. `mfc lint-schemas` fails any schema declaring a banned property name, found
   at **any** depth — `properties`, `patternProperties`, `$defs`,
   `allOf`/`anyOf`/`oneOf` branches, `items`/`prefixItems`,
   `additionalProperties`-as-schema. A shallow `doc["properties"]` walk is a
   defect, not a simplification.
4. Exit codes: 0 pass, 1 findings, 2 usage.
5. A rejection fixture proves the lint fires — a lint with no failing case is
   not evidence.
6. `make test` green (ruff + pytest) before any commit, per §4.5.

## Schema completeness — the brief was wrong

The milestone brief (mine) said the seven schemas were "copy-pasteable from
`2026-08-04-contract-schemas.md`". **Two are.** Established by reading the
source, not its headings:

| schema | state |
|---|---|
| `emission/1.0` | **FULL** — §1.2b, complete document |
| `review/1.0` | **NEAR-FULL** — §1.5, missing only the `$schema`/`$id` wrapper |
| `resolution/1.0` | PARTIAL — `$defs.result` complete; envelope-level properties never spelled out |
| `declarations/1.0` | SKETCH — instance + one `allOf` fragment, no `properties` block |
| `build/1.0` | SKETCH — instance + one `if/then` fragment, no `properties` block |
| `environment/1.0` | SKETCH — instance + prose bullets, **no JSON at all** |
| `bundle/1.0` | SKETCH — instance + prose bullets, **no JSON at all** |

So five of seven must be **authored from filled instances**, which is design
work, not transcription. Re-estimate accordingly.

## Open questions

1. **BLOCKER — ADR-0007's central premise cannot be verified, and the
   artifacts already contradict it.**
   `_pipeline/stage-1-discovery/synthesis/target-architecture.md` is cited by
   ADR-0007, ADR-0001 and `open-questions.md` as the source of a versioned
   bridge-contract system. It **does not exist**: not in arXMCP, not anywhere
   under `~/Personal/SourceCode`, never in arXMCP's git history. Nor do the
   things it allegedly specifies — no artifact-type registry, no
   `GET /bridge/contracts`, no `bridge.*` envelope, in arXMCP or in
   `personal-website` (cited as the vendoring precedent, which has no
   `.claude/references/bridge/`).
   Independently: **none of the seven filled instances nest under a `bridge.*`
   wrapper** — every one has `schema_version` as its flat first key. So the
   design and the envelope it is said to join already disagree.
   Four ADR-0007 conclusions rest on this: schemas live in `arXMCP/contract/`;
   `mfc` is arXMCP-side only (from "§5.4 rule 7"); artifacts join an existing
   envelope; topic repos vendor with a checksum-drift test.
2. **Forbidden-name set disagrees with itself**: 13 names in the design note's
   literal `FORBIDDEN_PROPERTY_NAMES` vs 6 in issues #19/#21. brief-2
   recommends the 13-name superset — strictly safer and it is the literal
   artifact. Needs a decision because it *is* the rule being mechanised.
3. **The schemas note predates and is partly superseded by ADR-0007** (same
   day). Its own "files this deliverable specifies" section and CI examples
   describe the earlier three-repo design (`pipx install
   git+.../math-formal-contract`). Only the JSON Schema bodies survive intact.
4. `jsonschema` is currently absent from `pyproject.toml` entirely; adding a
   runtime dependency touches the packaging boundary §4.5b says `make test`
   does not cover.
5. `additionalProperties: false` composes badly with `allOf`/`$ref` — the
   schemas use both. Standard trap; workarounds identified in brief-2.

## Estimated size

Larger than briefed. Five schemas authored rather than copied, plus CLI, lint
traversal, fixtures and tests. Expect to exceed the 800-LOC Phase 2 abort
threshold; `--allow-large-diff` will likely be needed, or the milestone should
be split (schemas first, CLI second).

## Recommendation

Hold Phase 2. Open question 1 decides **which repo this code belongs in**, and
building `arXMCP/contract/` first and asking later is the expensive order.
