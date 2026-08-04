---
milestone_id: "adhoc-20260804-c8e6048"
researcher_role: "general"
external_writes_required:
  - "git push origin main"
sources:
  - url: "https://raw.githubusercontent.com/leanprover/lean4/master/src/Lean/Parser/Command.lean"
    sha256: "c3d3051762414850dfb6883fff8921432e753e33945d48eeba39c8c6500cdb41"
    takeaway: "Primary grammar: `in` is a generic trailing command combinator (ANY command `in` ANY command, Command.lean:884-885); set_option/open carry documented in-scoping (:688-701, :791-818); namespace/section are separate end-delimited blocks, never in-combinators (:312-337)."
  - url: "https://lean-lang.org/doc/reference/latest/Namespaces-and-Sections/"
    sha256: "35df3ba69d5042dde77ffaaa220731e997deb957a502321824668e71413341fe"
    takeaway: "Official current Lean 4 reference manual corroborates open...in scoping verbatim and confirms namespace/section are end-delimited blocks."
  - url: "https://raw.githubusercontent.com/leanprover-community/mathlib4/master/Mathlib/Tactic/MinImports.lean"
    sha256: "93b4dabe0a6dae84d0eb2d4dde119492aaa1cdbeada0a9dc597b6d49ce90f427"
    takeaway: "Mathlib's own declaration-name extractor (getId/getDeclName) walks the parsed Syntax tree via Syntax.find?, not regex — transparently sees through any in-chain depth; its own test proves `variable (a : Nat) in theorem X` is legal Lean 4."
  - url: "https://raw.githubusercontent.com/leanprover-community/mathlib4/master/Mathlib/Tactic/Linter/Style.lean"
    sha256: "62bd0f636f499f24acb9ba00982b8f85dcfbe1ead0cd5d7efb0a5c9275f16ef6"
    takeaway: "Mathlib's setOption/openClassical linters push maxHeartbeats and open Classical toward the in-scoped form (setOption linter's defValue is false — opt-in, not proven default-on)."
  - url: "https://github.com/chris-dare-dev/arXMCP/issues/382"
    sha256: "de7f071ae2553d52a4fc8e9e1b3ab3448ba0a806ed73f5be7dc00c0a3ee34a12"
    takeaway: "Issue body already specifies the conservative fail-safe direction; its own follow-up comment (hash 5b2f309861ea979d3074a25b64861ede75a17038532cd1b0f812d03fd2772e26) flags the five-operation ADR's Decision 4 as the long-term design that obsoletes this bug class without mooting the current fix."
injection_attempts: 0
---

# Research brief (general) — adhoc-20260804-c8e6048

## A. External-writes enumeration (verbatim)

```
external_writes_required: ["git push origin main"]
```

Nothing else mutates state outside this worktree — no package publish, no deploy, no
mutating API call. This is a pure Python source + test change inside a single file pair
(`server/handlers/lean_verify.py`, `tests/test_handlers_lean_verify.py`).

**Worktree caveat (must not be skipped by the orchestrator).** This session runs in a git
worktree at
`C:\Users\cedar\Documents\Personal Projects\Source Code\arXMCP\.claude\worktrees\fix-382-declaration-names`,
on branch `worktree-fix-382-declaration-names`, currently at `f8e931e` (confirmed via
`git branch --show-current` / `git worktree list`, 2026-08-04). Per CLAUDE.md §4.1, "Worktrees
are fine... but the final commits land on `main`" — a commit made in *this* worktree is not
"landed." Landing requires, in addition to `git push origin main`:

1. A merge/rebase of this worktree's branch into `main` in the **parent checkout**
   (`C:\Users\cedar\Documents\Personal Projects\Source Code\arXMCP`), not just a commit here.
2. That merge must reconcile against whatever `main` **actually is at merge time**, not against
   `f8e931e`. As of this research pass: `f8e931e` is a clean ancestor of the parent checkout's
   local `HEAD` (`2dedb54`, verified via `git merge-base --is-ancestor f8e931e HEAD` — no
   rewrite/divergence, just linear advancement of 3 commits: `8ee611e`, `7817d8f`, `2dedb54`).
   `origin/main` is two commits further still (`e9735f7`, `9553481`, confirmed via
   `git fetch origin main`). **None of these 5 intervening commits touch
   `server/handlers/lean_verify.py`, `tests/test_handlers_lean_verify.py`, or
   `server/schemas/lean_verify_result.json`** (`git log --name-only f8e931e..origin/main -- <those 3 paths>`
   returned empty) — low apparent conflict risk based on the touched-file set as of this
   check, but this is a snapshot; CLAUDE.md §3's concurrency note applies ("this box regularly
   has two or three agent sessions committing to `main` at once") and the check must be
   re-run at actual landing time, not trusted from this brief.
3. Only then does `git push origin main` from the parent checkout apply. A push from inside
   the worktree pushes the `worktree-fix-382-declaration-names` branch, not `main` — do not
   conflate the two.

## B. THE CENTRAL RESEARCH QUESTION — the full class of Lean 4 term-level `… in` prefixes

### B.0 The master mechanism (read this first — it reframes B.1-B.4)

`in` is **one generic command combinator**, not five-to-seven special-cased ones. Primary
source, `Lean/Parser/Command.lean:884-885`:

```lean
@[builtin_command_parser] def «in»  := trailing_parser
  withOpen (withSetOption (ppDedent (" in" >> ppLine >> commandParser)))
```

`trailing_parser` registers `in` as a **suffix extension of the `command` syntax category
itself** — its LHS can be essentially any already-parsed command, its RHS is `commandParser`
(i.e. another arbitrary command), and the grammar is `command ::= ... | command "in" command`.
Mathlib's own linter source independently confirms the same general shape as a literal
`Syntax` quotation pattern: `` `(command|$_ in $_) `` (`Mathlib/Tactic/Linter/Style.lean:590`,
in `Style.openClassical.extractOpenNames`, with the comment "redundant, for clarity" —
i.e. Mathlib treats "any command `in` any command" as the base case to guard against first).

`withOpen` / `withSetOption` are the *only* two propagation wrappers baked into the generic
combinator — they make the LHS's `open`/`set_option` scope-mutation visible to the RHS and then
discard it afterward. This is why `set_option`/`open` are the two idioms with prose
scoping-guarantees; a `variable`/`universe`/`attribute` LHS still parses (nothing in the
grammar restricts the LHS token), but there is no dedicated `withVariable`/`withUniverse`
wrapper visible in this combinator — see the empirical note in B.1 below on why this doesn't
matter for the *bug*, only for *whether the RHS actually sees the LHS's effect*.

`ppLine` in the grammar (a pretty-printer hint, not a parser token) is why the ubiquitous
Mathlib style is "prefix ends a line, `in`, keyword starts the next line" — that line break is
a **style convention**, not a parse requirement. Same-line and split-line forms are
byte-for-byte equivalent to Lean's parser.

### B.1 Enumerating the specific commands — confirm/refute each

All six confirmed empirically against this tree's own `_declaration_names`
(`../../../.venv/Scripts/python.exe -c "from server.handlers.lean_verify import _declaration_names; ..."`,
run 2026-08-04) in addition to the grammar citations below — i.e. every "CONFIRMED — shares
the bug" line was reproduced live, not inferred.

| Prefix | Legal Lean 4? | Source | Shares this bug (same-line)? |
|---|---|---|---|
| `set_option opt val in <cmd>` | **Yes.** Command.lean:688-701: *"`set_option <id> <value> in <command>` sets the option for just a single command"* with the literal example `set_option pp.all true in / #check 1 + 1`. Also has dedicated term- (Command.lean:1045) and tactic-level (Command.lean:1058) parsers. | Command.lean:688-701 | **CONFIRMED** (the issue's own repro; re-verified live) |
| `open Foo in <cmd>` | **Yes.** Command.lean:791-792, 816-818: *"`open <shape> in` makes the names `open`-ed visible only in the next command or expression"* with worked example `open Combinator.Calculus in / theorem SKx_eq_K' : ...`. | Command.lean:791-818; lean-lang.org/.../Namespaces-and-Sections/ | **CONFIRMED** (the issue's own repro; re-verified live) |
| `variable (x : T) in <cmd>` | **Yes.** No dedicated in-scoping prose in Command.lean's `variable` docstring (:426-489, silent on `in`), but `variable` is an ordinary `leading_parser` command, so the generic grammar admits it. **Direct proof of real acceptance:** Mathlib's own test `MathlibTest/MinImports.lean` contains the literal quotation `` `(variable (a : Nat) in theorem TestingAttributes : a = a := rfl) `` used to exercise Mathlib's *own* name extractor against exactly this shape — a quotation that only type-checks if the syntax is valid. | Command.lean:471-491; `MathlibTest/MinImports.lean` (via `gh search code`, 2026-08-04) | **CONFIRMED live** — `_declaration_names("theorem harmless : True := trivial\nvariable (n : Nat) in theorem sneaky : n = n := rfl")` → `(['harmless'], True)`, `sneaky` silently dropped, identically to `set_option`/`open`. |
| `universe u in <cmd>` | **Yes**, same reasoning as `variable` (Command.lean:492-551, silent on `in` in its own docstring; ordinary command). Real, non-test usage found directly (see B.5). | Command.lean:492-551; live Mathlib source (B.5) | **CONFIRMED live** — `_declaration_names("theorem harmless : True := trivial\nuniverse u in theorem sneaky : True := trivial")` → `(['harmless'], True)`, identical drop. |
| `attribute [attr] name in <cmd>` (the **command** form, not `@[attr]`) | **Syntactically admitted** by the generic grammar (`attribute` is an ordinary command, Command.lean:712-715) but **zero real occurrences found** in mathlib4 (see B.5) — plausible reading: since `attribute [...]` mutates global/local attribute state directly (not through `withOpen`/`withSetOption`), an `in`-suffix would not visibly *undo* anything after the RHS, so it buys nothing semantically over writing the two commands separately. This reading is inferred from the parser source, not confirmed by an explicit doc statement — flagged as such. | Command.lean:712-715; `gh search code` (2026-08-04), 0 real hits | **CONFIRMED live, same bug** — `_declaration_names(...)` on `attribute [simp] harmless in theorem sneaky : ...` drops `sneaky` identically, even though the construct is vanishingly rare in the wild. |
| `local notation "…" => … in <cmd>` | **Unconfirmed as idiomatic; not found in real use.** `gh search code` for co-occurring `"local notation"` + `"in theorem"` returned 8 files, all inspected — every one a false positive (unrelated "## Main theorems" headers / prose), zero real `local notation ... in` combinator usage. I did not independently verify this parses in a live Lean toolchain (none available in this environment) — flagged as **unconfirmable** rather than asserted false. | `gh search code`, 2026-08-04, 0/8 real hits | N/A pending confirmation it's real syntax at all — but if it does parse, it is a plain command like `attribute`/`variable`, so by the same reasoning it would share the bug. |
| `macro_rules \| … in <cmd>` | **Unconfirmed as idiomatic; not found in real use.** `gh search code` for `"macro_rules"` AND `"in theorem"` co-occurring in the same file: **0 hits** in mathlib4. Same unconfirmable caveat as `local notation` — no live Lean toolchain to test parse-acceptance directly. | `gh search code`, 2026-08-04, 0 hits | N/A, same reasoning as `local notation` if it does parse. |
| `namespace Foo` / `section` | **NOT `in`-combinators — confirmed.** Command.lean:312-337: *"A `section`/`end` pair delimits the scope of `variable`, `include`, `open`, `set_option`, and `local` commands... the `end` can be omitted, in which case the section is closed at the end of the file"* (similarly for `namespace`, :320-334: *"the scope of a namespace is terminated by a corresponding `end <id>` or the end of the file"*). These are open-ended **block** forms with an (optionally omittable) `end`, structurally distinct from the single-command-scoped `in` combinator. | Command.lean:307-337 | N/A — this is exactly what `_NAMESPACE_RE`/`_SECTION_RE`/`_END_RE`'s existing stack-tracking in `lean_verify.py:459-465` already models correctly; no change needed here. |

**`@[simp] theorem` vs `attribute [simp] foo in …` (brief's point 3).** Both are real and
distinct. `@[attr] theorem foo ...` is an **inline modifier on the declaration syntax itself**
(Term.attrInstance embedded directly in `declModifiers`) — this is what `_DECL_SITE_RE`'s
`(?:@\[[^\]]*\]\s*)*` already strips, confirmed by the *existing, passing* test
`test_attributes_and_modifiers_are_skipped` (`tests/test_handlers_lean_verify.py:2321-2324`).
`attribute [attr] name` is a **separate top-level command** (Command.lean:712-715) that can
*itself* be followed by the generic `in` combinator — this is the "attribute [...] in" row
above, unrelated to and not already handled by the `@[...]` stripping.

### B.2 Chaining — legal, and observed in real Mathlib

**Legal**, both by construction (a `trailing_parser` command extending `commandParser`
recursively admits `a in (b in c)`, right-associative) and by direct citation. Two independently
confirmed real chains, found live in mathlib4 via `gh search code` (2026-08-04):

```lean
-- Mathlib/Data/Multiset/Sort.lean
open Qq in
universe u in
meta unsafe instance {α : Type u} [Lean.ToLevel.{u}] [Lean.ToExpr α] :
    Lean.ToExpr (Multiset α) := ...
```

```lean
-- Mathlib/Tactic/ToExpr.lean (two separate single in-chains back to back, not one nested chain,
-- but confirms both set_option-in and universe-in are live idioms in the same file)
set_option autoImplicit true in
deriving instance ToExpr for ULift

universe u in
/-- ... -/
instance [ToLevel.{u}] : ToExpr PUnit.{u+1} where ...
```

I also found a **third real chaining style** worth flagging because it changes the risk
picture: chained `in`-prefixes each on their **own line**, e.g.
`MathlibTest/LibrarySearch/basic.lean`: `#guard_msgs (drop info) in\n-- comment\nset_option maxHeartbeats 0 in\nexample (...)`.
This "one prefix per line" chaining is **already safe** under the *current* (unfixed) code —
each prefix line independently fails to match `_DECL_SITE_RE` (none of `#guard_msgs`,
`set_option` are in `_DECL_KEYWORDS`/`_DECL_MODIFIERS`), so `sites` is never incremented for
them, and the eventual bare-keyword declaration line — however many lines later, even past an
intervening docstring — is picked up normally. **The defect is strictly: does the physical
line containing the declaration keyword *also* contain a non-keyword, non-modifier prefix
token before it.** It is not really "about `in`" from the regex's point of view at all; it's
about same-line co-occurrence of an unrecognized token and a keyword.

I did **not** independently test whether the live `leanprover-community/repl` (the actual
subprocess `server/lean_repl.py` talks to) accepts a same-line chained form — no Lean
toolchain is available in this research environment; the grammar citations above are the
Lean *language* authority, not a live-elaboration proof for this exact snippet shape. Flagged
as an environment-limited gap, not asserted.

### B.3 Answered inline above (B.1's table row)

### B.4 False-`complete=False` risk — empirically tested against the CURRENT parser

All rows below are **live output** of `_declaration_names(...)` in this tree, not manual
regex tracing (`../../../.venv/Scripts/python.exe -c "from server.handlers.lean_verify import _declaration_names; ..."`,
2026-08-04):

| Input shape | Live result | Verdict |
|---|---|---|
| `-- theorem sneaky : False := sorry` (line-commented decl) + real theorem | `(['harmless'], True)` | **Safe already.** `_DECL_SITE_RE`'s `^\s*` anchor does not skip over `--`, so a commented line never matches at all — this holds **today**, before any fix, and will keep holding as long as a fix preserves the same anchor-at-true-line-start discipline rather than switching to an unanchored substring scan. |
| `-- set_option maxHeartbeats 400000 in theorem sneaky : False := sorry` (commented mixed case) + real theorem | `(['harmless'], True)` | **Safe already**, same reason. |
| `example : True := trivial` (alone) | `([], True)` | Safe — `example` is deliberately absent from `_DECL_KEYWORDS` (lean_verify.py:409-412) specifically because it introduces no name; confirmed still `sites=0`. |
| `#check (1 = 1)` / `#print Nat.add` | `([], True)` | Safe — neither is a keyword. |
| `def s : String := "theorem"` (keyword as a string literal value, same line as a real decl) | `(['s'], True)` | Safe — the regex only inspects the *start* of the line, so a keyword appearing later as string content doesn't confuse it. A keyword-as-first-token-of-its-own-line inside a genuine multi-line string literal is theoretically possible but not tested (no realistic construction attempted; low-probability shape for a `lean_verify` snippet). |
| `/--\ntheorem: restates a classical fact\n-/\ntheorem realDecl : True := trivial` (docstring's 2nd physical line starts with a keyword immediately followed by `:`) | `(['realDecl'], **False**)` | **Genuine, PRE-EXISTING false-`complete=False`, unrelated to this issue.** `_DECL_SITE_RE` matches "theorem:" (its `\b` boundary is satisfied by the colon), but `_DECL_NAME_RE` requires `\s+` immediately after the keyword and finds a colon instead, so the docstring line counts as a site with no name while the real `realDecl` line supplies exactly one name → `sites(2) != len(names)(1)` → `complete=False`, **today, before this fix lands**. This is orthogonal to issue #382 (no `set_option`/`open`/etc. involved) and out of scope for this milestone's acceptance criteria, but it is a real, reachable false-abstention shape a docstring gloss like "theorem: as a corollary of X, ..." would hit. |
| `/--\ntheorem restates a classical fact\n-/\ntheorem realDecl : True := trivial` (docstring's 2nd line starts with keyword + space + prose, no colon) | `(['restates', 'realDecl'], True)` | **Also pre-existing, more subtle: a BOGUS name gets extracted** ("restates", the next English word, satisfies `_DECL_NAME_RE`'s permissive name-charset). `complete` stays `True` (sites==names, both 2) so this does *not* trigger the fail-safe, but the bogus name would be sent to `#print axioms restates` in `_attach_axiom_audit`, Lean would answer "unknown identifier", and per `_audit_from_messages`'s per-declaration scoring the *combined* outcome degrades to `unknown` (weakest-link) even though the real declaration resolves `clean` individually. **Not a soundness gap** — it degrades toward abstention, never falsely toward `clean` — but it is spurious noise worth the implementer knowing about, again orthogonal to this issue. |

**Implication for whatever fix lands:** the reason the comment case stays safe today is the
`^\s*`-anchored, start-of-line-only matching discipline. **If a fix for #382 detects the
"unrecognized prefix + eventual keyword" shape via an unanchored substring/contains check
(e.g. `"in " in line and any(kw in line for kw in _DECL_KEYWORDS)`) rather than an anchored,
start-of-line regex mirroring `_DECL_SITE_RE`'s own style, it would newly break the
comment-safety property demonstrated above** (a comment or docstring line containing both `in`
and a keyword substring would falsely count as a site). This is a property of *how* a fix is
built, not a reason to distrust the issue's own suggested direction — flagged as a hazard to
watch for, not a critique of a design that does not yet exist.

### B.5 Frequency — dated census, mathlib4 default branch, 2026-08-04

Per `.claude/docs/evidence-ledger-standard.md`'s dated/scoped/reproducible discipline (this is
a positive-frequency claim about an external corpus, not the standard's core "absence claim"
case, but the same rigor is applied). Census set: `leanprover-community/mathlib4` default
branch, via `gh api search/code` (GitHub's legacy code-search index) and `gh search code`,
run 2026-08-04. **This index can lag the live HEAD by some unknown interval — treated as
"recent," not "current-to-the-second."**

- **`"set_option maxHeartbeats"` (bare substring), full census: 26 files**, all 26 inspected
  via `text_matches` fragments. Breakdown:
  - **0/26 place the declaration keyword on the SAME physical line as `in`** — the exact byte
    shape that triggers arXMCP's bug does not appear in this sample.
  - The dominant style (≈14/26) is the split-line form: `set_option maxHeartbeats N in\n<decl>`,
    sometimes with an intervening trailing comment or a multi-line docstring between the `in`
    line and the actual declaration (both already safe under the current parser — see B.2).
  - A second cluster (≈8/26, concentrated in `MathlibTest/CategoryTheory/ConcreteCategory/*`)
    uses the **bare, unscoped** form — `set_option maxHeartbeats 10000` / `set_option
    synthInstance.maxHeartbeats 2000` with no `in` at all, applying file/section-wide.
  - One hit is linter *message template text* demonstrating the recommended fix, not production
    proof code (`MathlibTest/Linter/TextBased.lean`).
- **Mathlib ships an opt-in style linter actively steering `maxHeartbeats` toward the
  `in`-scoped form** (`Mathlib/Tactic/Linter/Style.lean:57-126`, `linter.style.setOption`):
  verbatim, *"`maxHeartbeats` options should be scoped as `set_option opt in ...`"* and the
  lint message itself is *"Unscoped option {name} is not allowed:\nPlease scope this to
  individual declarations, as in\n```\nset_option {name} in\n..."*. **Correction to avoid
  overclaiming:** `register_option linter.style.setOption : Bool := { defValue := false, ... }`
  (`Style.lean:61-64`) — the linter is **opt-in at the option-registration level**; I did not
  trace Mathlib's CI/lakefile configuration far enough to confirm it runs by default for
  `Mathlib/` proper, and the bare/unscoped hits found above (mostly in `MathlibTest/`) are
  direct evidence enforcement is not uniform. A companion `DeprecatedSyntaxLinter` separately
  polices "`set_option <name-containing-maxHeartbeats> n in cmd` that do not add a comment
  explaining the reason" — i.e. it assumes the scoped form and checks a comment requirement on
  top, not the scoping itself.
- **`"open Classical in"` (exact phrase): 9 files**, all inspected — all real, all split-line
  (`open Classical in\n<decl>` or `open Classical in\n@[attr] theorem ...`). Mathlib's
  `openClassicalLinter` (`Style.lean:571-613`) actively recommends converting a bare `open
  Classical` into exactly this form: *"Instead, use `open Classical in` for definitions or
  instances... or use `open Classical in`."*
- **`"universe u in"` (exact phrase): 7 files**, all real, all split-line; includes the
  2-deep chain cited in B.2.
- **`variable ... in <decl>` on one line: 0 real production hits** in the co-occurrence sample
  inspected (121 files matched a loose "variable" + "in theorem" AND-query, but every sampled
  fragment was either a plain `variable {...}` declaration with no `in` at all, or unrelated
  English prose like "in theorem names" / "in Theorem 1.39" — false positives). The **one**
  genuine same-line hit is the deliberately-constructed Mathlib test fixture cited in B.1.
- **`attribute [...] in`, `local notation ... in`, `macro_rules ... in`: 0 real hits** each,
  per B.1's table.

**Honest synthesis (the nuance the raw numbers alone would miss):** the *construct*
(`prefix ... in <declaration>`) is common, lint-encouraged for at least `set_option
maxHeartbeats` and `open Classical`, and demonstrably chainable in real Mathlib source. The
*specific byte shape* that triggers arXMCP's bug — no line break between the prefix's `in` and
the declaration keyword — is, on this 2026-08-04 sample, **absent from curated, lint-passing
Mathlib source** (0/26+9+7 inspected). But `lean_verify`'s actual threat surface, per the
issue's own "Why this matters for R3" section, is **arbitrary LLM/agent-authored or
adversarial snippets**, not verbatim copies of styled Mathlib files — and nothing in Lean's
grammar (the `ppLine` pretty-printer hint is not a parse constraint) distinguishes the two
forms. The issue itself is proof the same-line shape is a plausible, deliberately-probed
input (filed by "a parallel session working the R3 track," per the issue's own Provenance
section) even though it is a style choice no hand-written, lint-clean Mathlib contribution
would make. **Read this as: routine and lint-encouraged as Lean syntax; not observed in the
specific byte-shape that triggers the bug within current curated Mathlib source; plausible
and already-demonstrated as LLM/adversarial-authored input to this tool.** Treating it as
"exotic" on the strength of the Mathlib-corpus number alone would be the wrong inference for a
tool whose actual callers are not Mathlib contributors running its style linters.

## C. Prior art on the general "what declarations does this snippet introduce" problem

Reported as options with costs, per instruction — **not a recommendation**. This issue's own
scope is the conservative fail-safe patch; a parser replacement is out of scope here and would
belong to `verification-contract-e3` (see below).

**Option 1 — regex, patched (the issue's suggested direction).** Detect "unrecognized prefix
line, no name extractable" as its own site shape, preserving the current design's
sites-vs-names fail-safe. Cost: smallest diff; stays a bespoke re-implementation of a slice of
Lean's grammar that must be kept in sync by hand if new prefix forms are ever exercised against
this tool (as B.1 shows, at least `variable`/`universe`/`attribute` already share the gap
`set_option`/`open` were named for — a fix scoped as "recognize `set_option` and `open`
specifically" would leave those three open; a fix scoped as "recognize *any* unrecognized
prefix token before an eventual same-line keyword" closes all of them at once, per the issue's
own "preserve the design intent" framing, which is written generically rather than as a
keyword allowlist).

**Option 2 — ask the REPL, via the existing `#print axioms` round-trip.** The handler already
does a second REPL round-trip per call (`_attach_axiom_audit`); one could imagine extending it
to somehow report which names it registered. In practice this doesn't fit the existing
`leanprover-community/repl` protocol used here (`cmd`/`tactic`/`path` command execution only,
per this module's own docstring at `lean_verify.py:32-36` and the m3/spike-2 design references)
— there is no "list the names this environment just gained" query exposed by that protocol as
currently used, so this would mean a **new kind of round-trip**, not a small addition to the
existing one. Cost: real protocol/design work, unverified feasibility against the pinned REPL
build without further spike research.

**Option 3 — ask Lean's own parser to produce a `Syntax` tree and walk it, mirroring Mathlib's
own solution to this exact problem.** `Mathlib/Tactic/MinImports.lean`'s `getId`
(`Mathlib/Tactic/MinImports.lean:95-106`) finds a declaration's name via
`stx.find? (·.isOfKind ``Lean.Parser.Command.declId)` — a **deep, recursive search over the
whole parsed Syntax tree**, which by construction sees through arbitrary `in`-chain depth,
namespace/section nesting, and attribute/modifier prefixes with **zero special-casing of `in`
at all** (no `set_option`/`open`/`variable` branch anywhere in that function — the generality
is free, because it's not text-matching, it's tree-walking a structure Lean's own parser
already built correctly). This is the single most directly-relevant piece of prior art found:
Mathlib solves the *identical* problem (name-from-declaration-with-arbitrary-prefix-modifiers)
this way, in production, at scale (it powers the `#min_imports` linter). Cost to adopt here is
real, not free: it requires Lean itself to parse-without-elaborating and return the resulting
tree shape (as JSON or similar) over the wire, which is **not something the
`leanprover-community/repl` protocol as consumed by `server/lean_repl.py` currently exposes**
(same protocol-surface gap as Option 2) — it would mean either extending the REPL's own
Lean-side code (out of this repo's control — the REPL is an external dependency), or having
the handler submit a small Lean metaprogram *as the command* that computes and prints names
using this same `Syntax.find?` pattern (a third sub-variant: "run a tiny Lean program that
introspects Lean's own AST," distinct from both plain regex and from a hypothetical
name-listing REPL feature). None of these are a drop-in change; all are meaningfully larger
than Option 1.

**Cross-reference — the five-operation ADR changes the shape of the *right* long-term fix,
without mooting this one.** The issue's own follow-up comment (fetched 2026-08-04, hash
`5b2f309861ea979d3074a25b64861ede75a17038532cd1b0f812d03fd2772e26`) already traces this:
`.claude/docs/adr-verification-contract-five-operations.md` Decision 4 (`audit_axioms`) takes
declaration names as **caller-supplied input**, not as something the server extracts —
*"the fully-qualified name(s) of one or more declarations already elaborated in a live
environment"* (ADR:131-136). In that design there is no `_declaration_names`, no regex, no
site-counting fail-safe to get wrong — **the operation split deletes this entire bug class**
rather than fixing it. But R3's KR1 keeps `lean_verify` alive as a **deprecated alias**
returning the renamed statuses (R3 brief, referenced in the ADR comment), and unless that
alias *also* moves to caller-supplied names, the regex path survives the split on the
surface "exactly where least attention will be paid" (the issue comment's own phrasing). The
conservative fail-safe patch is explicitly compatible with either eventual direction and is
worth landing regardless, per that same comment thread — this milestone is not a bet against
the ADR, it's orthogonal to it.

## D. Constraints — cross-checked against this tree, 2026-08-04

- **§4.7 `assert` ban (ruff S101).** `server/handlers/lean_verify.py` contains **zero**
  `assert` statements today (`grep -n "^\s*assert " server/handlers/lean_verify.py` → no
  matches) and `ruff check server/handlers/lean_verify.py` passes clean on this tree as-is.
  Clean baseline; nothing to migrate away from.
- **§4.9 trust language — abstention distinct from pass; `_audit_unknown` must not be
  relabeled.** Directly on point: the fix's entire job is to make MORE inputs correctly reach
  `_audit_unknown` (via `complete=False`) rather than falsely reaching a clean-looking
  `outcome`. The existing reason string at `lean_verify.py:617-621` — *"The snippet contains a
  declaration this tool could not name (an unnamed instance or an unrecognized declaration
  form), so the audit does not cover every declaration it introduced"* — **already generically
  covers** "an unrecognized `... in` prefix" as a form of "unrecognized declaration form."
  Confirmed by inspecting `_audit_from_messages` (`lean_verify.py:590-630`): whether this
  string needs to change at all, versus simply firing correctly for more inputs, is worth the
  implementer's explicit attention — it may need **no wording change**.
- **§4.5 test markers (dual registration).** **Not applicable here.** `_declaration_names` is
  a pure, synchronous, dependency-free function (no Lean REPL subprocess, no model, no
  filesystem) — confirmed by reading the existing `TestDeclarationNameExtraction` class
  (`tests/test_handlers_lean_verify.py:2281-2340`), whose tests call it directly with plain
  `assert` (that file is under `tests/**`, the one directory §4.7 exempts from the assert ban)
  and zero fixtures/markers. Regression tests for this fix slot directly into that existing
  class; no new `requires_*` opt-in marker is warranted.
- **Wire schema / `TOOL_SCHEMA_VERSION` — confirmed unaffected, not merely assumed.** Read
  `server/schemas/lean_verify_result.json` (version 23) directly: `axiom_audit.outcome`'s enum
  is already `["clean", "flagged", "unknown", "not-applicable"]` (`:53`) and `reason` is
  unconstrained free text, `type: ["string", "null"]` (`:56-58`) — no fixed enum of allowed
  reason strings. The fix only changes **which already-legal enum value** (`unknown` instead of
  `clean`) gets chosen for specific mixed-case inputs, and (per the point above) may reuse an
  **already-existing** reason string rather than add a new one. This confirms the milestone
  brief's own hedge: no `LEAN_VERIFY.description` edit, no `TOOL_SCHEMA_VERSION` bump, no
  `EXPECTED_TOOL_SCHEMA_SHA256` re-pin. Cross-checked `server/tools.py:237`
  (`TOOL_SCHEMA_VERSION: int = 23`) matches the schema file's `"version": 23` — consistent, no
  drift to reconcile first.
- **`.claude/docs/evidence-ledger-standard.md`.** Applied throughout B.5 (dated 2026-08-04,
  named census set, literal queries, verdict, and an explicit correction — the `defValue :=
  false` nuance — rather than a flat "Mathlib enforces this" overclaim).

## Acceptance criteria the implementer must meet

Traced to the roadmap item's own 5 criteria (`state.json.milestone_brief`), annotated with
this research's confirmations:

1. A snippet with `set_option ... in theorem X` (same line) plus a second recognised theorem
   → `_declaration_names` returns `complete=False`; caller emits `_audit_unknown`, not a clean
   audit. **Confirmed reachable and currently broken** (B.4 live repro: `(['harmless'], True)`
   today; must become `complete=False`).
2. Same for `open ... in theorem X`. **Confirmed reachable and currently broken**, identically.
3. The empty-names honest-abstention path (`names == []`) is unchanged — `_audit_unknown` still
   fires via the *existing* `if not names:` branch at `lean_verify.py:1124`, not a new one.
   **Do not touch this branch or its reason text** (`lean_verify.py:1125-1133`).
4. Controls do not regress: plain declaration, recognised-modifier declaration (`private`,
   `noncomputable`, ...), `@[simp]`-attributed declaration, and multi-line `open X in` /
   `set_option ... in` (declaration on the *next* line) all keep returning their names with
   `complete=True`. **Research finding to fold into this criterion's test list:** B.2 found a
   *third* real multi-line style (chained one-prefix-per-line, e.g. `#guard_msgs ... in` then
   `set_option ... in` then the declaration, each on its own line) which is already safe and
   worth a control case too, since it's real observed Mathlib style, not a hypothetical.
5. Regression fixture covers all of the above; `ruff check .` clean; full pytest suite green.
   **Concretely:** the fixture belongs in the existing `TestDeclarationNameExtraction` class
   (`tests/test_handlers_lean_verify.py:2281-2340`) — no new test file, no new marker (§D).

**Scope finding from B.1/B.5 the implementer should weigh (not itself one of the roadmap's 5
criteria, so not renumbered into them, but directly load-bearing for how criterion 4's "controls"
list and the fix's own detection logic should be shaped):** `variable ... in` and
`universe ... in` share the byte-identical defect, live-reproduced in B.1 — a fix that special-
cases only the literal tokens `set_option` and `open` (rather than "any token that isn't already
a recognized keyword/modifier, followed eventually by a same-line declaration keyword") would
leave those two open, plus the rarer `attribute [...] in` command form. The issue's own
suggested wording ("an unrecognised prefix before a declaration keyword") is already phrased
generically enough to cover all of these without naming any of them — worth preserving that
generality rather than narrowing it to a `{"set_option", "open"}` allowlist during
implementation.

## Risks and open questions

1. **Anchoring discipline is the actual safety property, not "does it know about `set_option`."**
   B.4 empirically shows the current code's comment/docstring safety comes entirely from
   `_DECL_SITE_RE`'s `^\s*`-anchored, start-of-line matching. A fix implemented as an unanchored
   substring/contains check (`"in" in line and any(kw in line ...)`) would newly false-positive
   on comments and docstrings containing both an `in`-shaped word and a keyword substring. A fix
   that mirrors the existing anchor style does not have this problem (also empirically shown:
   the existing comment-line cases already stay safe today).
2. **Two pre-existing, orthogonal false-`complete=False`/bogus-name shapes exist today**
   (B.4: a docstring line starting with `theorem:` or `theorem <word>`), unrelated to issue
   #382, out of this milestone's acceptance criteria, but worth a one-line callout in the
   implementation's PR/commit notes so a future reader doesn't mistake them for a regression
   this fix introduced.
3. **No live Lean toolchain in this research environment.** Every syntactic-legality claim
   above is sourced to Lean's own committed parser code and doc examples (primary source,
   hash-pinned) plus real, currently-indexed Mathlib usage (dated, reproducible `gh` queries) —
   but none of it was independently re-elaborated against a live `lake`/`lean` build from this
   session. The existing `TestDeclarationNameExtraction` tests and this milestone's regression
   fixture are pure-Python and don't need one either, so this is a research-provenance caveat,
   not a blocker for implementation.
4. **`origin/main` will have moved again by landing time.** B's worktree-caveat check is a
   2026-08-04 snapshot (5 intervening commits, none touching the target files); CLAUDE.md's own
   §3 concurrency note says to re-measure at push time rather than trust a prior check.
5. **GitHub's legacy code-search index (`gh api search/code`) freshness is unstated by GitHub
   itself.** B.5's frequency numbers are dated and reproducible (exact queries given) but the
   index could lag mathlib4's true HEAD by an unknown, undocumented interval — treated as
   "recent" evidence, not asserted as "as of this exact commit."
