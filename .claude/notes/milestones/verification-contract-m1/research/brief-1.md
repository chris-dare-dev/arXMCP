---
milestone_id: "verification-contract-m1"
researcher_role: "explore"
injection_attempts: 0
---

# Research brief (explore) — verification-contract-m1

## Affected files / context

### 1. The status surface — `server/handlers/lean_verify.py` (1460 lines total)

**Core status-computation block** (the exact site the roadmap's evidence line names —
verified live, matches `plans/verification-contract/roadmap.yaml:40`'s claim of
`717-733`, superseding the original brief's stale `290-298`):

```
717  has_error = any(m["severity"] == "error" for m in messages)
718  has_sorry = bool(sorry_goals)
719  if has_error:
720      status = "error"
721  elif has_sorry:
722      status = "sorry"
723  else:
724      status = "ok"          # <-- rename target 1/6
725
726  # syntax_only DID NOT run kernel verification ...
730  if mode == "syntax_only" and status == "ok":      # <-- rename target 2/6
731      compilation_success: bool | None = None
732  else:
733      compilation_success = status == "ok"           # <-- rename target 3/6
```

This is the `_normalize_response` cmd-shape branch (full / syntax_only). A **second**,
structurally parallel status computation exists for `tactic_step` mode in
`_normalize_tactic_step` (lines 788-861) — it does **not** use `"ok"` for its own status
enum member (`incomplete` is used there instead), but it DOES set
`status = "ok"` at line 823 for the goals-closed case:

```
817  if has_error:
818      status = "error"
819  elif goals_remaining or sorry_goals:
820      status = "incomplete"
821  elif resp.get("proofStatus") == "Completed":
822      status = "ok"          # <-- rename target 4/6
823  else:
824      status = "incomplete"
```
(Line numbers 817-824 per the live read; the assignment itself is at 823.)

**Every literal `"ok"` occurrence inside this file** (`grep -n '"ok"' server/handlers/lean_verify.py`):

| Line | Context | Action needed |
|---|---|---|
| 363 | comment, prose critique of the old behavior | optional — historical narrative, safe to leave or update |
| 365 | comment, "surface calls a proof of False 'ok'" | optional — same |
| 662 | comment, docstring prose | optional |
| 724 | `status = "ok"` (cmd branch) | **rename to `"elaborated_no_errors"`** |
| 730 | `if mode == "syntax_only" and status == "ok":` | **rename** |
| 733 | `compilation_success = status == "ok"` | **rename** |
| 777 | `if status not in ("ok", "sorry"):` (`_default_audit_for`) | **rename** |
| 800 | docstring comment | optional |
| 823 | `status = "ok"` (tactic_step branch) | **rename** |
| 825 | comment | optional |
| 1447 | `if mode == "full" and payload["status"] in ("ok", "sorry"):` (axiom-audit gate in `handle_lean_verify`) | **rename** |

Six live-code sites (724, 730, 733, 777, 823, 1447) MUST change together — missing any one
either leaves `compilation_success` un-derivable for the new value or skips the axiom-audit
round-trip on a clean elaboration.

**Full enumerated status values the handler can emit** (cross-referenced against
`server/schemas/lean_verify_result.json`'s enum, which is the authority — see §2):
`ok` (rename target) · `error` · `sorry` · `incomplete` (tactic_step only) · `timeout`
(sentinel envelope, `_timeout_envelope`, line 893) · `unavailable` (sentinel envelope,
`_disabled_envelope`, line 871) · `invalid-input` (sentinel envelope,
`_invalid_continuation_envelope`, line 938; also the message-error path returns `"error"`,
not `invalid-input`, at line 973 — see the Shape-1 discriminator at lines 688-702).

**Trust-bearing vs operational split** (this is the exact conflation the milestone fixes):
`status` today mixes an *elaboration+proof-closure* epistemic axis (`ok`/`error`/`sorry`/
`incomplete`) with *operational* lanes (`timeout`/`unavailable`/`invalid-input`) in one
enum — `.claude/docs/trust-language-policy.md` §3's table names this exact overload
(`lean_verify.status` row: "a 5-value epistemic-*and*-operational ladder, mixed"). The
policy does **not** require splitting these into two fields at m1 — §5b explicitly places
`timeout`/`unavailable`/`invalid-input` in a legitimate "operational status" lane that is
allowed to sit beside the epistemic values in one field, AS LONG AS abstention and
operational status are not conflated with each other (they already aren't — `unavailable`/
`timeout`/`invalid-input` never claim a trust verdict). The rename (`ok` →
`elaborated_no_errors`) is the fix the policy actually calls out by name (§2: "R3 renames
`"ok"` → `elaborated_no_errors`").

**`compilation_success` values** — `true` iff `status == "ok"` (soon
`"elaborated_no_errors"`); `false` on error/sorry/timeout/invalid-input; `null` in two
cases: (a) `mode="syntax_only"` with a clean elaborate (line 731), (b) always in
`tactic_step` mode (line 851, hardcoded `None`). This field's semantics are UNCHANGED by
the rename — only the string it compares against changes.

**`axiom_audit` axis (ALREADY SHIPPED)** — lines 359-1148 (not 359-398; that was the
*constants/allowlist* block only). The full mechanism: `AXIOM_ALLOWLIST` (397-399,
`{propext, Quot.sound, Classical.choice}`), the declaration-name parser (445-525), the
Certificate-builder helpers (528-634), `_audit_from_messages` (589-629, the `#print axioms`
reply scorer), and `_attach_axiom_audit` (1077-1148, the second REPL round-trip). This axis
is **out of scope for this milestone** — it already conforms to the trust-language policy's
Certificate shape and is cited BY the policy as the worked example of an independent axis
done right (`.claude/docs/trust-language-policy.md` §2's "Status update (2026-07-31)" note
and §4 row 7). Do not re-touch its logic; only its *place inside the schema* (still present,
unchanged shape) matters for AC #2.

**Stale doc drift already present, worth a drive-by fix while in this file:** the module
docstring at line 9 says `"projects the response into the frozen schema at
server/schemas/lean_verify_result.json (version 12)"` — the live schema is version 22 (see
§2). This has been stale since at least the W1 batched re-pin and is not this milestone's
fault, but touching the file to rename `status` is a natural point to correct it (bump to
whatever version this milestone lands, not "12"). Not an AC; flag as a nice-to-have.

### 2. The frozen-schema blast radius — the highest-risk part of this milestone

**`server/schemas/lean_verify_result.json`** — confirmed live at **version 22**, NOT the
brief's cited "version 12" (that number is only accurate inside the *handler's stale
docstring*, not the schema file itself — the schema's own `"version": 22` field and its
`$id` (`".../lean_verify_result/v22.json"`) are both current and correctly at 22, matching
`TOOL_SCHEMA_VERSION` — see below). Relevant fields for this milestone:
- `properties.status.enum` (line 163): `["ok", "error", "sorry", "incomplete", "timeout",
  "unavailable", "invalid-input"]` → replace `"ok"` with `"elaborated_no_errors"` (position
  in the array does not matter to `jsonschema` but keep it first for readability/parity).
- `properties.status.description` (line 162): prose explicitly says `"'ok' (clean)"` and
  `"status='ok'"` in the axiom-soundness caveat — must be reworded to the new token.
- `properties.compilation_success.description` (line 65): says `"true iff status == 'ok'"`
  — must be reworded.
- Top-level `description` (line 5): the long provenance narrative that records every prior
  bump reason (12→13→…→22) — append this milestone's entry rather than rewriting history,
  matching the file's own established style (each past bump is one clause appended to the
  same string).
- `"version": 22` → bump to the new `TOOL_SCHEMA_VERSION` (23, assuming no other schema
  change lands first — see W1/W2 staging note below).
- `"$id"` (line 3) → `.../v22.json` → `.../v23.json` (not machine-checked for THIS file —
  see the `$id`-suffix test note below — but every prior bump has kept `$id` and `version`
  in lockstep by convention; breaking that silently would be a first).

**`server/schemas/search_papers_result.json`** — the ONLY other file under
`server/schemas/`. Currently ALSO `"version": 22"` and `$id` ending `v22.json`. Its own
content is not touched by this milestone (search_papers is untouched), but it MUST still
bump its `version` field (and, by convention, `$id`) to the new `TOOL_SCHEMA_VERSION` in
lockstep — this exact "bump-even-though-unchanged" pattern is precedented at every prior
`TOOL_SCHEMA_VERSION` rise (its own top-level `description` narrates 8 such no-op bumps,
e.g. "Bumped at verification-feedback-m3 (11 -> 12) to track the lean_verify tool addition;
this search_papers result shape is unchanged"). **This is machine-checked**:
`tests/test_search_filter.py:905-917` (`test_schema_version_matches_after_m2_bump`) asserts
BOTH `schema["version"] == TOOL_SCHEMA_VERSION` AND
`schema["$id"].endswith(f"v{TOOL_SCHEMA_VERSION}.json")` — so for `search_papers_result.json`
specifically, the `$id` bump is not optional, it is asserted. (The equivalent `$id`-suffix
assertion does NOT exist for `lean_verify_result.json` — only
`tests/test_snippet_contract.py:560-566` checks `$id` STARTS WITH the right prefix, not the
version suffix — but bump it anyway for consistency; every prior lean_verify_result.json
edit has.)

**`TOOL_SCHEMA_VERSION`** — defined at `server/tools.py:226`, currently `22`. Read/echoed at:
- `server/tools.py:1133` — `meta = {"tool_schema_version": TOOL_SCHEMA_VERSION}`, attached
  to every registered tool's wire `_meta` inside `register_all` (this is what makes ANY
  `TOOL_SCHEMA_VERSION` bump — even with zero description/inputSchema change — drift
  `EXPECTED_TOOL_SCHEMA_SHA256`, because the `_meta` block is part of the hashed
  `tools/list` bytes).
- `server/tools.py:1142` — startup log line, no test dependency.
- Two purely-historical narrative comments reference an OLD pinned value and are **not**
  live pins needing updates: `server/observability/tracing.py:163-166` and
  `server/observability/spend_constants.py:31-34` both say "keeps TOOL_SCHEMA_VERSION
  pinned at 6" — this describes a design decision made when the constant WAS 6; it is dead
  narrative text, not a test assertion. Do not "fix" these to say 22/23; they document a
  point-in-time rationale (why `_agent_role` is a header, not a schema property), which is
  still true regardless of the constant's current value.
- `server/handlers/search.py:19-23` similarly references a "bundled TOOL_SCHEMA_VERSION
  re-pin later" comment — this is ALSO stale/historical (the referenced delta already
  landed in the agent-platform-m3/W1 batch per `.claude/docs/w1-schema-deltas.md`); not
  part of this milestone's scope, leave alone.

**`tests/test_server_tool_schema.py`** — `EXPECTED_TOOL_SCHEMA_SHA256` (line 94-96) and
`EXPECTED_TOOL_SCHEMA_VERSION_AT_HASH` (line 109, currently `22`). The
`--update-tool-schema-hash` flag is registered by `tests/conftest.py` (confirmed present —
grep hit) and implemented as a `pytest_addoption` + in-`TestPinnedHash.test_live_tools_
match_pinned_hash` rewrite (lines 341-422 of the test file itself, NOT conftest — conftest
only registers the CLI flag). **Behavior**: the flag REFUSES to rewrite the hash unless
`TOOL_SCHEMA_VERSION` has ALREADY been bumped past the pinned `EXPECTED_TOOL_SCHEMA_
VERSION_AT_HASH` value (lines 365-382 — the "decorative-version" guard: hash drift without
a version bump is a hard `pytest.fail`, not a silent pass). Correct order: (1) bump
`server/tools.py::TOOL_SCHEMA_VERSION` to 23 AND edit `LEAN_VERIFY.description` FIRST, (2)
run `pytest tests/test_server_tool_schema.py --update-tool-schema-hash` — it rewrites BOTH
`EXPECTED_TOOL_SCHEMA_SHA256` and `EXPECTED_TOOL_SCHEMA_VERSION_AT_HASH` in place via regex
anchored on `# UPDATE-ANCHOR` / `# VERSION-ANCHOR` sentinels, then deliberately FAILS with a
"commit and rerun" message, (3) re-run plain `pytest tests/test_server_tool_schema.py` to
confirm it now passes. The flag also refuses to run under any CI env var (`_running_in_ci`,
lines 308-322) — irrelevant here (no CI in this repo per CLAUDE.md §4.1) but worth knowing
if this is ever scripted.

**`tests/test_prompts.py`** — `EXPECTED_BP1_SHA256` (line 675-677) is **hand-edited only —
there is no update flag for this constant**, confirmed: no `--update-bp1-hash` or similar
option exists anywhere in `tests/conftest.py` or `tests/test_prompts.py`. The hash is
computed by `_bp1_hash(_build_fanout_request(...))`, which hashes `{"system": SYSTEM_PROMPT,
"tools": [{"name": t.name, "description": t.description} for t in ALL_TOOLS]}` (canonical
JSON, sorted keys) — i.e. BP1 = `SYSTEM_PROMPT` + every tool's `{name, description}` pair,
confirming the roadmap's claim that BP1 covers `{name, description}` pairs is correct
(`_live_tools_payload`, lines 443-464). **A `LEAN_VERIFY.description` edit DOES move this
hash** — every prior `LEAN_VERIFY.description` change (v12, v20, v22 per the inline history
comments at lines 627-674) required a paired `EXPECTED_BP1_SHA256` hand-edit, and this
milestone's edit (renaming `ok` → `elaborated_no_errors` inside the description string at
`server/tools.py:426`) is exactly that shape again. **Procedure**: after bumping
`TOOL_SCHEMA_VERSION` + editing `LEAN_VERIFY.description` + regenerating
`EXPECTED_TOOL_SCHEMA_SHA256`, run `pytest tests/test_prompts.py::TestBP1ByteIdentityAcross
Fanout::test_bp1_hash_pinned` — it FAILS with the actual computed hash printed in the
assertion message (`f"...To intentionally update, edit the EXPECTED_BP1_SHA256 literal in
this file to {actual!r}."` — line 691); paste that value in by hand, plus a new dated
history-comment line following the existing `# v22: ...` pattern (lines 627-674).

**`server/tools.py` — `LEAN_VERIFY` ToolMeta** (lines 410-446). Two literal `"ok"`
occurrences inside the description STRING (not the enum, prose):
- Line 426: `"Returns status (ok/error/sorry/incomplete/timeout/unavailable/invalid-input),"`
- Line 434: `"...they do not check axiom soundness, so a snippet declaring its own axiom
  returns status='ok'."`
Both must become `elaborated_no_errors`. `ALL_TOOLS` (line 452-461) — `LEAN_VERIFY` is the
LAST entry (position matters for hash stability per
`tests/test_handlers_lean_verify.py:180-183`'s explicit "must be appended at the END"
assertion — this milestone does not reorder `ALL_TOOLS`, so that invariant is undisturbed).

**Complete ordered checklist for the re-pin** (a partial application of any ONE of these
without the rest is the documented failure mode — CLAUDE.md §9 "Add a new tool" step 4 and
this file's own module docstrings both warn about this):

1. `server/handlers/lean_verify.py` — 6 code-site renames (§1 table).
2. `server/tools.py:410-446` — `LEAN_VERIFY.description` 2-site rename.
3. `server/tools.py:226` — bump `TOOL_SCHEMA_VERSION` 22 → 23 (+ extend the comment block
   at lines 180-225 with a new `#: 22 -> 23 (verification-contract-m1): ...` entry, matching
   every prior bump's documentation style).
4. `server/schemas/lean_verify_result.json` — enum value, 2 description strings, top-level
   description narrative append, `version` 22→23, `$id` `v22`→`v23`.
5. `server/schemas/search_papers_result.json` — `version` 22→23, `$id` `v22`→`v23`, +1
   narrative-append sentence (content otherwise untouched).
6. `pytest tests/test_server_tool_schema.py --update-tool-schema-hash` — regenerates
   `EXPECTED_TOOL_SCHEMA_SHA256` + `EXPECTED_TOOL_SCHEMA_VERSION_AT_HASH` in
   `tests/test_server_tool_schema.py` (steps 1-5 MUST land first or this computes against
   stale bytes).
7. `tests/test_prompts.py:675-677` — hand-edit `EXPECTED_BP1_SHA256` to the value the
   failing assertion prints; add a `# v23: ...` history comment.
8. `tests/test_handlers_lean_verify.py:224` — hardcoded `assert TOOL_SCHEMA_VERSION == 22`
   → `== 23` (this is the ONE other hand-pinned literal integer in the test suite besides
   the two hash constants above — everything else references the `TOOL_SCHEMA_VERSION`
   symbol dynamically and needs no edit). Extend its docstring history list (lines 193-223)
   with the 22→23 entry.
9. `tests/test_handlers_lean_verify.py` — ~20 literal `assert result["status"] == "ok"` /
   `!= "ok"` sites → `"elaborated_no_errors"` (§3 has the full line list).
10. `docs/api.md:141` — `` `status` (`ok` / `error` / ...) `` → rename the one token (§3).

Steps 6 and 7 are ORDER-DEPENDENT on 1-5 (the hash/BP1 pins must be computed against the
final bytes); steps 1-5, 8, 9, 10 have no strict ordering among themselves.

### 3. Existing test surface — every literal site that breaks on the rename

**`tests/test_handlers_lean_verify.py`** (2791 lines total) — 20 exact-match sites via
`grep -n '"ok"'`:

```
285, 358, 407, 554, 646, 1405, 1467, 1471, 1474 (!= "ok"), 1497, 1643 (comment),
1650 (!= "ok"), 1797, 1814, 1917, 2030, 2077, 2196, 2438, 2471, 2630, 2787
```
(Comment-only lines 594 and 1643/1649 reference `"ok"` in prose and are not asserted
literals — safe to update for accuracy but won't break tests if left. Every other line in
the list above is either `assert result["status"] == "ok"` or the `!=` inverse and MUST be
updated to `"elaborated_no_errors"` or the corresponding test will fail post-rename — the
`!=` ones (1474, 1650) currently assert the OPPOSITE and must ALSO flip their comparison
target string, not their polarity.)

**No other test file in the repo asserts on `lean_verify`'s `status` field with the literal
`"ok"`.** Verified via a repo-wide grep for `"ok"` combined with `status` context — every
other `"ok"` hit found (24 files) is unrelated: `/healthz`/`/readyz` sentinel bodies
(`tests/test_server_startup.py`, `tests/test_security.py`), backup-status vocabulary
(`tests/test_backup_status_vocabulary.py`, `tests/test_server_metrics.py`, `tests/test_
daily_metrics_report.py`), `get_definitions.index_status`
(`tests/test_definitions_index.py`, `tests/test_tools_all.py`), embedder per-paper stats
(`tests/test_embedder.py`, `tests/test_re_embed.py`), WAL checkpoint status
(`tests/test_checkpoint_notebooks_db.py`), notebook detail parse-status mapping
(`tests/test_notebook_detail_status.py`), and — **important, do NOT touch** — the
dispatch-level `REQUEST_COUNTER{status="ok"|"error"}` Prometheus metric
(`server/tools.py:989,1013,1030,1035-1037`; asserted in `tests/test_server_metrics.py`
multiple times). This counter's `status` answers "did the handler dispatch raise an
exception", not lean_verify's trust axis — it is explicitly named as a DIFFERENT,
legitimate `…status` overload in `.claude/docs/trust-language-policy.md` §3's table
(`REQUEST_COUNTER{status}` row: "RPC-dispatch outcome... not a tool-payload field") and
§6 rule 4 ("Transport metrics stay separate"). Renaming `lean_verify`'s internal `status`
value has ZERO effect on this metric's label values — they were never coupled.

**`docs/api.md`** (line 141) and **`docs/usage.md`** (references `lean_verify` at line
189-193 but does not enumerate status values, no `"ok"` literal there) — `docs/api.md:141`
reads `` Returns `status` (`ok` / `error` / `sorry` / `timeout` / `unavailable`), `` — this
line is ALREADY stale independent of this milestone (it's missing `incomplete`,
`invalid-input`, `env`, `continuation_status`, `proof_state_id`, `axiom_audit` — all landed
in lean-verify-continuation-m1 / the W2 axiom-audit window without a docs/api.md update).
This milestone's AC only requires the `"ok"` token itself not survive; a full doc resync is
scope-creep but a one-line minimal fix (rename the token) is trivial and directly required
by AC #1's "no response field anywhere in the schema reads bare 'verified'" spirit (the doc
isn't the schema, but leaving a doc that says `ok` when the wire says `elaborated_no_errors`
would be a self-inflicted new drift the very next session has to re-discover).

**No fixture files** under `tests/fixtures/` reference `lean_verify` output shapes (grepped;
the fixtures directory holds chunker/preamble/eval-report/metrics fixtures unrelated to
this handler).

### 4. Policy requirements — `.claude/docs/trust-language-policy.md` (258 lines, read in full)

Concrete, checkable requirements this redesign must satisfy (§ numbers are the policy's own):
- **§1 (the rule):** no bare "verified"-style status collapsing distinct trust questions.
  Already satisfied structurally — `status`, `compilation_success`, `axiom_audit`,
  `continuation_status` are already four separate fields (this shape landed across m3,
  lean-verify-continuation-m1, and the W2 axiom-audit window; it PRE-DATES this milestone).
  m1's job is the rename, not a re-architecture.
- **§2:** explicitly names the exact fix this milestone performs: `` R3 renames `"ok"` →
  `elaborated_no_errors` (honest to what it measures) ``. The policy's own 2026-07-31
  status-update block (lines 22-44) is EXPLICIT that this specific rename has "**not**
  shipped" as of that date and is deliberately deferred to "R3-m1's batched window" — i.e.
  THIS milestone. Confirms scope precisely.
- **§3 (status overload table):** do not add a fifth bare `status` anywhere (this milestone
  doesn't add one — it renames an existing enum value). `REQUEST_COUNTER{status}` is called
  out by name as the one that must stay untouched (see §3 above in this brief).
- **§4 (multi-axis record):** `meet`/weakest-link combination only WITHIN an axis, never
  across. `axiom_audit`'s own `_worse()` combinator (lean_verify.py:632-634) already follows
  this — not this milestone's concern, just confirm no new code violates it.
- **§5a-c (abstention vs operational vs partial):** `timeout`/`unavailable`/`invalid-input`
  already correctly live in the "operational status" lane (§5b), separate from the
  epistemic `ok→elaborated_no_errors`/`error`/`sorry`/`incomplete` values. No new abstention
  outcome is required by this milestone's ACs — the epistemic-vs-operational split is
  already correct in shape, just needs the token honesty fix.
- **§6 field-naming rules — the 5 rules to check the redesigned schema against for AC #2:**
  (1) no new bare `status` — respected (rename, not addition); (2) abstention/operational/
  partial stay 3 distinct fields — already true; (3) every trust-bearing field carries a
  Certificate (level + evidence) — true for `axiom_audit`, arguably NOT fully true for
  `status` itself (`status` is still a bare token, not Certificate-shaped) — **this is a
  legitimate open question for AC #2**: does "redesign the response schema to conform" mean
  wrapping `status` in a Certificate shape too, or does the policy's own worked example (§2:
  "the honest `elaborated_no_errors` that `lean_verify.status='ok'` should have ALWAYS
  been") sanction `status` staying a bare-but-honestly-named token because it is genuinely
  a single fact (a 5/6-way disjoint ladder) rather than a graded verdict needing evidence?
  The policy text at §2 reads as endorsing the LATTER (rename only, no re-shaping) — but
  this is the one place in the milestone where "redesign per policy" could be read more
  aggressively than the AC's own §3 (BP1 re-pin) implies is in scope. Flag for the
  implementer/critic, do not resolve here.
  (4) transport metrics stay separate — respected; (5) no axis defaults to passing — already
  true for `axiom_audit`'s `_audit_not_applicable`/`_audit_unknown` helpers; `status` itself
  has no "unmeasured" case (every path sets it explicitly), so this rule doesn't add new
  work.
- **§7 (enforcement posture):** "by-reference discipline... not a schema-level gate" — no
  new CI linter or validator is expected from this milestone; the existing
  `Draft7Validator`-based conformance tests (`TestLeanVerifyResultSchema`, lines 1081+, and
  a second conformance block at 2691-2700) are the enforcement, and they validate STRUCTURE
  (does the payload match the schema), not vocabulary honesty — they will pass either way
  as long as the schema and the handler's emitted values stay in lockstep, which is exactly
  what the checklist in §2 above ensures.

**`.claude/docs/w1-schema-deltas.md`** — confirmed: `## Currently staged` section reads
`_None._` (both prior deltas were applied in the W2 batched re-pin, `TOOL_SCHEMA_VERSION`
21→22). This means m1's re-pin is a clean, un-batched, single-purpose bump (22→23) — there
is nothing else waiting in the staging file to fold in. The file's own "How to use this
file" section documents the exact same procedure this brief's checklist (§2 above)
independently re-derives: bump `TOOL_SCHEMA_VERSION`, re-pin
`EXPECTED_TOOL_SCHEMA_SHA256` via the flag, hand-edit `EXPECTED_BP1_SHA256`, bump affected
`server/schemas/*.json` version fields.

### 5. ADR placement + precedent

**One existing ADR**: `.claude/docs/adr-data-plane-boundary.md` (175 lines,
data-plane-governance-m1, Accepted 2026-07-12) — this IS the house format, confirmed by
reading in full. Section skeleton (verified via header grep):

```
# ADR — <topic> (<milestone-id>)
**Status:** ... **Date:** ... **Owner:** ... (per OWNERS.md)
**Roadmap item:** ...  **Source brief:** ...
<intro paragraph — 1-2 sentences on what the ADR does>
## Context and problem statement
## Decision 1 — <title>
## Decision 2 — <title>
... (as many Decision sections as needed)
## Consequences
  - Good: ...
  - Bad / accepted costs: ...
  - Deliberately NOT decided here: ...
  - Known ambient hazards recorded for the next session: ...
## Owner approval record
  - **<date> — Approved (Accepted).** ...
  - Edits requested: none at approval time. / <list>
```

**Placement**: per CLAUDE.md §1/§4.6, agent-internal documents (this is one — an
architecture-decision record for internal contract design, not operator-facing) go under
`.claude/docs/` — matching the existing `adr-data-plane-boundary.md`'s location exactly.
Recommended filename: `.claude/docs/adr-verification-contract-five-operations.md` (mirrors
`adr-data-plane-boundary.md`'s topic-in-filename convention; avoid a generic
`adr-verification-contract.md` since the epic has 6 sub-tracks and only this ADR's *content*
— the five-operation split — needs a stable name a future ADR-2 for isolation (e2) or
caching (e6) could sit beside without colliding).

**AC #4's scope is narrow and explicit**: "defines each operation's inputs, isolation
dependency, and target-binding behavior **without implementing any operation**." This is a
pure-design document — no code changes accompany it. The five operations
(`parse_source`/`elaborate_signature`/`check_declaration`/`audit_axioms`/
`strict_replay_proof`) are already named and roughly scoped in TWO places this ADR should
synthesize rather than duplicate from scratch:
- `.claude/roadmap-briefs/R3-verification-contract.md` (182 lines, read in full) — the
  original seed brief with the fullest prose description of each operation's intent (lines
  22-27) plus the 8 key results, the "wont" list, tiered assumptions, and the F7
  inherited-finding about REPL environment-snapshot growth (lines 133-158) that the ADR's
  "isolation dependency" section should reference for `elaborate_signature`/
  `strict_replay_proof`'s env-reuse behavior.
- `plans/verification-contract/roadmap.yaml` (305 lines, read in full) — the materialized
  roadmap with epic-level `depends_on` edges that directly answer AC #4's "isolation
  dependency" ask: `verification-contract-e3` (the epic that implements the five
  operations) `depends_on: [verification-contract-e1, verification-contract-e2]` — i.e. the
  roadmap ALREADY encodes "the five operations depend on the isolation boundary (e2)" as a
  structural fact; the ADR should state this explicitly rather than leave it implicit in
  YAML `depends_on` edges only a roadmap-reader would find. Same for target-binding: e3's
  own summary text (`plans/verification-contract/roadmap.yaml:78`) already states
  `elaborate_signature`/`strict_replay_proof` "bind to a server-side target reference and
  reject candidates that rename, re-kind, strengthen, or weaken it" — the ADR's job is to
  make this a reviewable, cited DECISION with rationale, not to invent new content.

**Note on Owner-approval convention**: `adr-data-plane-boundary.md`'s "Owner approval
record" section documents an interactive `AskUserQuestion` checkpoint (2026-07-12). CLAUDE.md
§12 says the user "expects autonomous execution (auto-mode) and minimal interruption" and
this milestone has no scheduled interactive checkpoint in its brief. Whether this ADR should
ship as `Status: Accepted` (autonomous, no owner round-trip, matching the milestone's
"auto-mode" framing) or `Status: Proposed` (pending owner review, since it's a genuinely
new architectural commitment spanning 5 future epics) is a real open call — flag for
Phase 2/3, don't resolve here. The 2026-07-12 data-plane ADR's precedent leaned on an
explicit interactive approval; this milestone's brief doesn't mention one.

**Precedent for NOT editing other Accepted docs in place**: `.claude/docs/trust-language-
policy.md`'s own lines 22-44 demonstrate the repo's convention for correcting an "Accepted,
owner-approved policy" — append a dated "Status update" block rather than editing the
original prose. `adr-data-plane-boundary.md:30` and `.claude/roadmap-briefs/R3-
verification-contract.md:10-11,17` still cite the STALE `lean_verify.py:290-298` line
range for the pre-rename status logic. Per the established convention, these should NOT be
hand-edited in place if touched at all — but neither is named in this milestone's ACs or
`state.json`'s `links`, so the recommended action is: leave them untouched (they're
citations of a fact — "the status computation exists and does X" — that remains true in
substance after the rename; only the exact string it produces changes, which those files
don't quote). Not a blocker.

## Acceptance criteria the implementer must meet

1. `status="ok"` → `status="elaborated_no_errors"` at BOTH live call sites in
   `server/handlers/lean_verify.py` (cmd branch line 724, tactic_step branch line 823), plus
   the 4 downstream comparisons that key off the string (lines 730, 733, 777, 1447) — miss
   any one and either `compilation_success` mis-derives or the axiom-audit round-trip stops
   firing on a clean elaboration. No response field must read bare `"verified"` (already
   true; verified via grep, this is a regression guard, not an active fix).
2. The redesigned schema must not collapse elaboration/kernel-check/axiom-audit/replay into
   one token — already true in current shape (4 separate fields:
   `status`/`compilation_success`/`axiom_audit`/`continuation_status`); confirm against
   `.claude/docs/trust-language-policy.md` §6's 5 field-naming rules (see §4 above for the
   one open question on whether `status` itself needs Certificate-wrapping).
3. `pytest --update-tool-schema-hash` (regenerates `EXPECTED_TOOL_SCHEMA_SHA256` +
   `EXPECTED_TOOL_SCHEMA_VERSION_AT_HASH` in `tests/test_server_tool_schema.py`) AND a
   hand-edit of `EXPECTED_BP1_SHA256` in `tests/test_prompts.py` (no update flag exists for
   this one) must both be applied, in that order, AFTER `TOOL_SCHEMA_VERSION` is bumped and
   `LEAN_VERIFY.description` is edited. Both `server/schemas/lean_verify_result.json` and
   `server/schemas/search_papers_result.json` (the ONLY two schema files that exist) must
   have their `version` field bumped in lockstep with `TOOL_SCHEMA_VERSION`, even though
   `search_papers_result.json`'s content is otherwise untouched — this exact pattern is
   precedented ~8 times in that file's own description narrative.
4. The five-operation ADR — new file at `.claude/docs/adr-verification-contract-five-
   operations.md` (or equivalent name), following the house format demonstrated by
   `.claude/docs/adr-data-plane-boundary.md` — must name, for EACH of `parse_source`/
   `elaborate_signature`/`check_declaration`/`audit_axioms`/`strict_replay_proof`: its
   inputs, its isolation dependency (explicit statement that e3 depends on e2's boundary),
   and its target-binding behavior (which operations bind to a server-side target reference
   and what happens on mismatch) — without implementing any of them. No code changes
   accompany this file.

## Risks and open questions

1. **Partial re-pin is the documented failure mode.** Every one of the 10 checklist items
   in §2 must land in the same commit; `tests/test_server_tool_schema.py` and
   `tests/test_prompts.py` cross-check each other's constants (`EXPECTED_TOOL_SCHEMA_
   VERSION_AT_HASH` vs `TOOL_SCHEMA_VERSION`) specifically to catch a partial application,
   so a half-done re-pin will fail loudly rather than silently — but only if the ORDER in
   §2's checklist is respected (steps 6-7 depend on 1-5 already being complete).
2. **AC #2's "redesign" language is broader than what's structurally needed.** The schema
   already has 4 independent trust fields; whether "conform to the policy" requires
   Certificate-wrapping `status` itself (policy §6 rule 3) or whether the policy's own §2
   worked example ("the honest `elaborated_no_errors` that... `status='ok'` should have
   ALWAYS been") sanctions a bare-but-honest token is genuinely ambiguous from the docs
   alone — resolve via a design note in the implementation, not silently.
3. **ADR approval mode is unspecified.** No interactive checkpoint is named in this
   milestone's brief, but the one house-precedent ADR shipped via an explicit owner
   `AskUserQuestion` round-trip. Decide `Accepted` (auto-mode, matches CLAUDE.md §12) vs
   `Proposed` (pending review) explicitly rather than defaulting silently.
4. **The handler's module docstring (`lean_verify.py:9`) already lies about the schema
   version** ("version 12" vs live 22) — pre-existing drift, not this milestone's fault, but
   worth fixing while the file is open for the rename (update to whatever version this
   milestone lands at, 23).
5. **Two stale-but-out-of-scope docs cite the old `290-298` line range**
   (`adr-data-plane-boundary.md:30`, `R3-verification-contract.md:10-11,17`). Per this
   repo's established "append, don't edit Accepted docs" convention (see
   `trust-language-policy.md`'s own correction pattern), leave them — but don't let a
   critic flag their staleness as this milestone's regression; it predates m1 and isn't
   named in its ACs/links.

## Files this milestone will TOUCH (best estimate) + diff-size estimate

**Existing files (9):**
1. `server/handlers/lean_verify.py` — ~6-11 line edits (6 required code sites + up to 5
   optional comment/docstring touch-ups).
2. `server/tools.py` — ~10-15 line edits (TOOL_SCHEMA_VERSION bump + comment-block
   extension + 2-site LEAN_VERIFY.description rename).
3. `server/schemas/lean_verify_result.json` — ~6-10 line edits (enum, 2 field descriptions,
   top-level description append, version, $id).
4. `server/schemas/search_papers_result.json` — ~3 line edits (version, $id, description
   append) — no content change.
5. `tests/test_server_tool_schema.py` — 2 constants regenerated by the update-hash flag
   (mechanical, not hand-authored).
6. `tests/test_prompts.py` — 1 hand-edited hash constant + ~10-15 line comment-history
   addition (matching the existing per-bump documentation style).
7. `tests/test_handlers_lean_verify.py` — ~20 literal-string edits + 1 hardcoded
   version-integer edit (line 224) + ~10-line docstring history addition.
8. `docs/api.md` — 1 line edit.
9. `CLAUDE.md:413` — optional consistency edit (not required by any AC; the "founding case"
   prose there still says `status:"ok"`) — implementer's call, not a blocker either way.

**New file (1):**
10. `.claude/docs/adr-verification-contract-five-operations.md` — new, ~150-250 lines
    (sized off the `adr-data-plane-boundary.md` precedent at 175 lines).

**Total estimate:** ~9 existing files touched (~70-100 LOC changed, dominated by the
mechanical rename + hash regeneration), + 1 new ADR file (~150-250 LOC). Overall
**~250-350 LOC across ~10 files** — a small-to-moderate milestone matching the roadmap's own
`size: S` sizing for the parent epic (`verification-contract-e1`).

**Novel architecture: none.** This is a mechanical rename + a highly precedented
schema/BP1 re-pin dance (the exact same 6-7-step choreography has shipped ~8 times already
per the version-bump histories embedded in the schema files' own descriptions and in
`tests/test_prompts.py`'s comment history) + one new document that follows an existing
1-precedent house format. The only genuinely novel-content piece is the ADR's prose (new
words, not new mechanism) — appropriate for inline Phase 2 implementation rather than
delegation; there is no unresolved design question requiring exploration beyond the two
"risks and open questions" flagged above (AC #2's Certificate-wrapping ambiguity, and the
ADR approval-mode choice), both of which are judgment calls, not research gaps.
