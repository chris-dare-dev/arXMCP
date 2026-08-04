---
milestone_id: "verification-contract-m1"
researcher_role: "general"
external_writes_required:
  - "git push origin main"
sources:
  - url: "https://raw.githubusercontent.com/GasStationManager/SafeVerify/main/README.md"
    sha256: "7a725d6582f792c45fb19038c4666f0111d401ac27e8a28de42d2b7eece6e111"
    takeaway: "SafeVerify is a batch CLI diffing two compiled .olean files (target vs submission) via Environment.replay + a 3-axiom allowlist + kind/type/body equality + partial/unsafe rejection; it explicitly does not pass native_decide proofs and does not check implemented_by/extern/noncomputable metaprogramming markers."
  - url: "https://raw.githubusercontent.com/leanprover-community/repl/master/README.md"
    sha256: "33711c7ba3bf51820978212de61d4b8d8859e8a2e1c41ffc7f45708b56383896"
    takeaway: "The REPL protocol has exactly three interaction modes (cmd, path/file, tactic) plus pickling (pickleTo/unpickleEnvFrom/unpickleProofStateFrom); none is parse-only — every documented mode elaborates."
  - url: "https://arxiv.org/pdf/2606.26442"
    sha256: "82d1b44e8a3d8388a092a07f15941e03bf42bd53c5bdab8b1abd5bd3c52bbb51"
    takeaway: "AXLE's environment field selects a Lean-version+Mathlib-snapshot pair per request behind one endpoint, with per-request sandboxed-process isolation; its verify_proof deliberately trusts the loaded environment's kernel-checked provenance and so is faster but strictly weaker than SafeVerify/Comparator's full environment replay."
  - url: "https://lean-lang.org/doc/reference/latest/ValidatingProofs/"
    sha256: "371db56888a2b2ad3553faeb0939c92ae632a430b9e1f54234402e3ba56e0868"
    takeaway: "Official Lean docs confirm #print axioms is the transitive closure via Lean.collectAxioms; propext/Classical.choice/Quot.sound are named 'standard ... and benign'; sorryAx signals incompleteness; Lean.trustCompiler signals native evaluation was used."
  - url: "https://lean-lang.org/doc/reference/latest/releases/v4.29.0/"
    sha256: "cc86ca6f3338c45328f30ae5fa9f1a9ca8e501e550d25195e5c30bb054baac18"
    takeaway: "Lean 4.29.0 (RFC #12216) replaced the single Lean.trustCompiler axiom with one auto-generated axiom per native_decide/bv_decide computation (names containing '._native.bv_decide.'); the repo's reference toolchain (v4.30.0-rc2) postdates this change."
injection_attempts: 0
---

# Research brief (general) — verification-contract-m1

## A. External-writes enumeration

**`external_writes_required: ["git push origin main"]`** — and nothing else.

Verified against CLAUDE.md §4.1/§4.4 and the milestone-pipeline's own external-write
convention (`.claude/agents/milestone-rectifier.md:151,178,187` names `git push` as the
example and the only enumerated case for milestones like this one). This milestone's
acceptance criteria (roadmap `verification-contract-m1`, `plans/verification-contract/roadmap.yaml:125-129`)
are entirely local: a handler rename, a schema-file edit, a hash re-pin via
`pytest --update-tool-schema-hash`, and a new Markdown ADR committed under `.claude/docs/`.
None of the four acceptance criteria references a package publish, a deploy, a GitHub
issue/PR write, or any network-mutating call. Per CLAUDE.md §4.4, the eventual `git push
origin main` is **per-event user authorization, never implied** by a completed milestone —
this brief records it as the only candidate external write; it does not authorize it.

## B. Design research for the five-operation ADR

### B1. SafeVerify (github.com/GasStationManager/SafeVerify)

**What it checks** (from the README, `List of checks performed by the script`):

1. **Environment-manipulation defense.** Both the target and submission `.olean` files are
   run through `Environment.replay` — "the same check as what `lean4checker` performs,
   re-checking each declaration with the kernel" — before any other check runs, so later
   checks operate on a replayed (re-kernel-verified) environment rather than trusting
   whatever a metaprogram may have installed directly.
2. **Declaration-kind + signature match.** For each target declaration, the submission must
   have a declaration of the **same name, kind (def/theorem/opaque/…), and type**. A kind
   change (`theorem` → `def`) or a type/signature change (weakened or restated theorem) is
   a distinct, named failure mode (`kind mismatch (expected <k1>, got <k2>)` /
   `theorem type mismatch` / `definition type or value mismatch`).
3. **Body-equality with a sorry escape hatch.** A definition's *body* must match the
   target's body **unless the target's own body depends on `sorry`** (a stub the
   submission is meant to fill) — this is the "target replacement" defense: a submission
   cannot silently change what a *finished* target requires.
4. **Axiom allowlist.** Submission declarations must depend only on `propext`,
   `Quot.sound`, `Classical.choice` (via `CollectAxioms.collect`, configurable in-script).
5. **`partial`/`unsafe` rejection.** Any target-or-submission declaration marked `partial`
   or `unsafe` throws — closing the loophole SafeVerify's own docs name explicitly: "the
   use of partial/unsafe functions could allow infinite loops that satisfy the type
   requirement."
6. **`native_decide` is a hard fail, not a policy toggle.** "Currently, proofs containing
   `native_decide` will not pass SafeVerify" — both because of the `ofReduceBool` axiom
   dependency and because native_decide produces no proof term for the kernel to check at
   all. SafeVerify names its own replacement path (`ReplaceNativeDecide`) for proofs that
   need to keep native_decide's speed but still pass strict verification.

**What it explicitly does NOT check** (README, "Things that SafeVerify does not check"):
`implemented_by` / `extern` / `noncomputable` markers (too hard to catch at the `.olean`
level — flagged as a source-level scan the *caller* should add), and filesystem side
effects during compilation ("you may want to do compilation in a sandbox to produce the
olean files, then pass the olean files to SafeVerify"). Declaration shadowing is not named
as a check at all in the README — AXLE's own evaluation (§B3 below) independently surfaced
a *false-disagreement* case from `private`-declaration name-mangling that arises from
comparing whole-environment `.olean` files, not a soundness gap.

**Interface.** CLI-only, operating on **compiled `.olean` files**, not a live REPL
round-trip or a Lean library/tactic: `lake env lean -o submission.olean submission.lean`
to compile, then `lake exe safe_verify [flags] target.olean submission.olean`. Flags:
`--disallow-partial`, `-v/--verbose`, `-s/--save <path>` (JSON output: one row per
declaration with `targetInfo`/`solutionInfo`/`failureMode`). Exit code 0 on all-pass;
non-zero (thrown exception) on any failure.

**Toolchain versions.** No single pinned version on `main`; the repo instead carries
**per-consumer backported branches**: `minif2f-deepseek-check` (Lean 4.9.0),
`minif2f-kimina-check` (Lean 4.15.0), `abc-trinity-check` (Lean 4.20.0),
`seed-prover-check` (Lean 4.14.0). None of these matches the repo's reference toolchain
(`v4.30.0-rc2`, `.claude/docs/lean-sandbox-design.md:63`) — **whether `main` (unbranched)
tracks a current Lean version, or whether a fifth branch is needed, is unconfirmed and
should be spiked in `verification-contract-spike-2`** (the roadmap's own SafeVerify
version-branch probe, `plans/verification-contract/roadmap.yaml:216-228`), not assumed here.

### B2. `#print axioms` semantics (Lean 4, official docs)

Confirmed verbatim from `lean-lang.org/doc/reference/latest/ValidatingProofs/`
("Printing Axioms" section): `#print axioms thmName` "prints the set of axioms used by the
theorem **and the theorems it depends on**" — the transitive closure, computed by
`Lean.collectAxioms` (this is the exact primitive `lean_verify.py`'s `_attach_axiom_audit`
already drives via a `#print axioms` round-trip, `server/handlers/lean_verify.py:1077-1148`).

- **The three allowlisted axioms are official, not an arXMCP-local convention:** "the three
  axioms [`propext`, `Classical.choice`, `Quot.sound`] are standard axioms of Lean's logic,
  and benign" — matching `AXIOM_ALLOWLIST` in `lean_verify.py:397-399` exactly.
- **`sorryAx`**: "If `sorryAx` is reported, then this theorem or one of its dependencies
  uses `sorry` or is otherwise incomplete" — confirms the repo's own docstring
  characterization of `sorryAx` as "the axiom-side cross-check on the proof-closure axis"
  (`lean_verify.py:393-395`).
- **`Lean.trustCompiler`**: "If `Lean.trustCompiler` is reported, then native evaluation is
  used" (i.e. `native_decide`/`decide +native`) — again matching the repo's own comment.
- **Any other axiom** "means that a custom axiom was declared and used, and the theorem is
  only valid relative to the soundness of these axioms" — this is the exact `axiom h :
  False` case the trust-language policy names as the founding defect (§2 of
  `trust-language-policy.md`).

**Dated correction the ADR should carry (verified 2026-08-03, two independent sources):**

1. `Lean.collectAxioms` (hence `#print axioms`) had a **known transitivity bug**
   (`leanprover/lean4#8840`): it did not walk axioms *referenced by other axioms*, so a
   `native_decide` proof's reported axiom set could show `Lean.ofReduceBool` without the
   `Lean.trustCompiler` it indirectly depends on. Fixed by `#8842`, shipped in **Lean
   4.23.0** (2025-09-15 per the release page fetched).
2. **Lean 4.29.0** (RFC #12216, confirmed verbatim in the fetched release notes): "native
   computation (`native_decide`, `bv_decide`) is represented in the logic as one axiom per
   computation... `#print axiom` will no longer show `Lean.trustCompiler`, but rather the
   auto-generated names of these axioms (with, for example, `._native.bv_decide.` in the
   name)." The repo's reference toolchain, `leanprover/lean4:v4.30.0-rc2`
   (`.claude/docs/lean-sandbox-design.md:63`), **postdates** this change.

   This is good news for soundness and a stale-doc risk for prose, in that order: `audit_axioms`
   (and the already-shipped `axiom_audit` axis) is allowlist-based — anything not literally
   `propext`/`Quot.sound`/`Classical.choice` is flagged — so a renamed `._native.bv_decide...`
   axiom is still correctly caught without code changes. But `lean_verify.py`'s own comment
   and the `disallowed_axioms` schema description
   (`server/schemas/lean_verify_result.json:43`) call out `Lean.ofReduceBool` /
   `Lean.trustCompiler` **by literal name** as "notable members" — on the repo's actual
   pinned toolchain that literal name is very unlikely to appear at all going forward
   (native_decide instead surfaces as an unnamed `._native.bv_decide.NNN`-style axiom). The
   ADR should record this as a known documentation-staleness risk for whichever future
   milestone re-touches that prose, not silently repeat the stale claim as current fact.

### B3. AXLE (arXiv:2606.26442, fetched as PDF, 8 pages read)

**Per-request named-environment selection — the actual mechanism (§3.2, verbatim):**
"Each request carries an **`environment` field** that selects a particular LEAN 4 version
paired with a MATHLIB snapshot and any project-specific pre-built dependencies. A single
AXLE deployment serves multiple environments concurrently behind the same endpoint... The
available environments are exposed by the API; by default, the public tier serves a range
of recent LEAN 4–MATHLIB release snapshots, with additional custom environments available
on request." This is a **flat client-supplied string selecting a pre-built, server-known
environment** — not a client-supplied toolchain spec, not a per-request build. It maps
directly onto the roadmap's named environments (`core@<lean-ver>`, `mathlib@<commit>`,
`bridgeland-anchor@<commit>`) and the `arxmcp://lean-env` manifest resource shape (R3
key result 6): one opaque name resolving to a pinned, pre-built, reproducible environment.

**Per-request isolation (§3.3, verbatim):** "Each request runs in its own sandboxed
process. State a request mutates — loaded definitions, set options, registered
attributes, allocated memory — does not persist into any later request, and a crash or
runaway elaboration in one request does not affect concurrent or subsequent requests. The
sandbox additionally blocks network access and prevents the candidate from writing to the
filesystem." This is architecturally a **process-per-request** model, not a warm pool with
shared state — directly relevant to R3-e2's isolation-boundary choice and to why R3
correctly sequences performance/pooling (e6) *after* the trust gate: AXLE gets isolation
"for free" by never sharing process state across requests, at the cost of paying the
Mathlib-import cold-start on every call unless a caller keeps it warm via the paired
`environment` re-use.

**`verify_proof` (§4.1, verbatim four bullets):** rejects any submission declaration that
(a) "contain[s] `sorry`"; (b) "use[s] any axiom outside the small whitelist of known-
consistent axioms shipped in the LEAN standard library (`propext`, `Quot.sound`,
`Classical.choice`)"; (c) "have[s] a type which does not match the formal statement (e.g.,
the candidate proves a weakened or restated version of the theorem)"; (d) "are marked
`unsafe`, and can therefore use kernel-bypassing primitives such as `unsafeCast`." Notably
**AXLE's own bullet list does not separately name `partial`, declaration-kind change, or
native_decide** the way SafeVerify's does — narrower surface, by AXLE's own design choice.

**The load-bearing trust caveat (§4.1, verbatim — the single most important AXLE finding
for this ADR):** "For scalability, `verify_proof` assumes that **every declaration in the
loaded LEAN environment was added through LEAN's normal kernel-checked elaboration path**:
it does **not** re-verify the environment from scratch and hence does **not** defend
against inputs that use LEAN metaprogramming to install unchecked declarations directly
into the environment and make invalid proofs appear valid." AXLE names this explicitly as
the reason it is faster (§5.2: `verify_proof` median 0.97s vs SafeVerify 10.1s vs
Comparator 95.7s on the same 1,000-request corpus) but strictly **weaker** than
SafeVerify/Comparator/lean4checker, which all perform a full `Environment.replay` before
checking anything else.

**What this means for the five-operation split.** `check_declaration` ("isolated
environment compile") is architecturally AXLE's `verify_proof` shape: fast, per-request
isolated, trusts the elaboration path. `strict_replay_proof` ("fresh independent checker;
exact target/signature equality; SafeVerify-pattern" — the roadmap's own phrase) is
architecturally SafeVerify/lean4checker/Comparator's shape: slower, full environment
replay, catches metaprogramming-installed unchecked declarations that `check_declaration`
cannot. **The ADR should name this trade-off explicitly as the reason the contract has
both operations rather than one** — `check_declaration` alone would inherit AXLE's exact
documented gap.

### B4. leanprover-community/repl protocol (README fetched + hashed; repo's own prior
source-level finding for the append-only claim)

**The verified command surface does not match the roadmap brief's naming.** The README
documents exactly three interaction modes and one auxiliary pair:

| Roadmap brief's name | Actual protocol key(s) | Notes |
|---|---|---|
| `cmd` | `cmd` (+ optional `env`) | matches |
| `file` | `path` (+ optional `allTactics`) | brief's "file" is not a literal key |
| `proofStep` | `tactic` (+ `proofState`) | brief's "proofStep" is not a literal key |
| `pickleEnvironment` / `pickleProofSnapshot` | **one** key, `pickleTo`, disambiguated by an `env` **or** `proofState` companion field | not two separate command names |
| `unpickleEnvironment` / `unpickleProofSnapshot` | `unpickleEnvFrom` / `unpickleProofStateFrom` | closest match, but the brief's names still aren't literal |

This repo's handler code already uses the correct literal keys (`cmd`, `env`, `tactic`,
`proofState` — `server/handlers/lean_verify.py:1308,1354-1357`), so no code is at risk; the
mismatch is only in the *roadmap brief's prose*, and the ADR should use the protocol's real
key names rather than propagate the brief's paraphrase.

**Is there a parse-only mode? No — confirmed by omission across the full protocol
surface.** The README documents `cmd` (full elaboration of a command), `path` (file mode —
"a simple wrapper around command mode", so also full elaboration, plus tactic extraction),
and `tactic` (steps an existing proof state — also full elaboration). **No command,
flag, or mode anywhere in the README avoids elaboration.** This directly corroborates the
repo's own pre-existing finding (`trust-language-policy.md:67-68`, independently
re-verified against the pinned `v4.30.0-rc2` REPL source per the R3 brief's F7 note) that
`syntax_only`'s `#check`-wrapping "reduces but does not remove kernel work" — there is no
lighter-weight REPL mode to fall back to. **Concretely: `parse_source` as named in the
roadmap ("parser only") cannot be built as a REPL JSON round-trip at all** — it would need
a separate, direct `Lean.Parser` invocation (a distinct Lean metaprogram, not a `{"cmd":
...}` message to the existing REPL subprocess). The ADR must say this explicitly rather
than imply `parse_source` is "the REPL, but lighter" — it is a structurally different
integration than the other four operations, which likely explains its ordering in R3's
key-result list (behind `check_declaration`'s existing REPL-based transport, not ahead of it).

**Pickling as the m5/m7 mechanism, confirmed:** "As long as the same imports are
available, it should be possible to move such an `.olean` file to another machine and
unpickle into a new REPL session" — and pickling "we don't record full `Environment`s,
only the changes relative to imports... unpickling uses memory mapping... file sizes are
generally small." This directly backs R3-m7's "pickle-migrating the hot named env across a
recycle" line and R3-m5's named-environment manifest concept: a named environment can
plausibly be built once and distributed as a pickled `.olean`, not rebuilt from source per
worker.

**On the append-only-environment-array claim (F7):** this brief did **not** re-fetch the
REPL's Lean source (`REPL/Main.lean`) — the README documents no eviction command, which is
consistent with, but does not independently re-confirm, the repo's existing
source-verified F7 finding (`.claude/roadmap-briefs/R3-verification-contract.md:141`,
census 2026-07-25 against `v4.30.0-rc2`). Treat F7 as already-established by that prior,
stronger (source-level) verification; this brief adds only the protocol-surface
corroboration above.

### B5. Prior art on honest verification-status vocabularies

**Evidence-ledger census (2026-08-03).** Claim under test: "how do comparable systems name
the elaborated/kernel-checked/axiom-clean/replayed distinction, and does `elaborated_no_errors`
read correctly against that convention?"
Census set: AXLE (arXiv:2606.26442, fetched), SafeVerify README (fetched), and
Kimina-Prover-related search results (not independently fetched/hashed — search-snippet
level only).
Queries run: `miniF2F ProofNet Kimina "compiles" vs "verified" theorem proving status
terminology autoformalization` (WebSearch, 2026-08-03).
Verdict: **unconfirmable at full-source depth for Kimina/miniF2F/ProofNet** — the search
surfaced only a snippet-level claim (Kimina distinguishing "type-correct (TC)" vs
"semantically correct (SC)" output) that was not independently fetched and hashed, so it is
reported here as a **weak, unverified lead**, not a citable fact. **Confirmed at
full-source depth for AXLE and SafeVerify:**

- **AXLE's own vocabulary is coarser than arXMCP's target, not finer.** `check` reports
  "errors, warnings, linter messages" (elaboration-level, Table 1) and `verify_proof`
  reports "verification pass/fail, failed declarations" (Table 1) — a binary pass/fail, no
  separate axiom-axis field, no separate "kernel-accepted but axiom-questionable" state.
  AXLE does not name or need an `elaborated_no_errors`-shaped token because it does not
  attempt the trust-language policy's multi-axis split at all; it is not a naming precedent
  to imitate, only a scope contrast.
- **SafeVerify's vocabulary is verdict-shaped, not axis-shaped**, but its **failure-mode
  taxonomy is exactly axis-flavored**: distinct named failures for kind mismatch, type
  mismatch, value mismatch, and "uses disallowed axioms" are already four separate,
  independently-triggerable outcomes — structurally close to arXMCP's axis independence
  requirement (trust-language policy §4), even though SafeVerify itself reports them as one
  overall exception rather than as a Certificate-shaped multi-axis record.
- **`elaborated_no_errors` reads correctly against the one established convention this
  research did verify at source: Lean's own docs (§B2) use "elaboration" and "kernel"
  as the two distinct, named stages** ("Elaboration and Compilation" is chapter 2 of the
  Lean language reference itself, per the fetched TOC), and nowhere in the fetched
  Lean-official or SafeVerify/AXLE material does "elaborated" get used loosely as a
  synonym for "proved" or "verified" — the rename target is not fighting an established
  contrary convention. **No better-established alternative term surfaced** in this
  (admittedly narrow) census; the strongest adjacent term found was Lean's own "Blue
  Double Check Marks" section heading (`ValidatingProofs/`, TOC, not read in full), which
  names a *visual* convention (editor checkmarks), not a wire-vocabulary one, so it is not
  a competing candidate.

Scope note: **narrow and non-exhaustive** — Kimina-Prover, TheoremGraph, and the
miniF2F/ProofNet harnesses were not fetched at source depth for this item; only AXLE,
SafeVerify, and official Lean docs were. A future pass wanting a stronger census on this
specific sub-question should fetch the Kimina-Prover paper (arXiv:2504.11354, found in
search results but not read) directly rather than rely on the search snippet above.

## C. Constraints already read and reflected above

- `.claude/docs/trust-language-policy.md` — read in full; §4's axis table (rows 5–8:
  elaboration / proof closure / axiom audit / checker identity) is the direct spec for
  four of the five roadmap operations (`elaborate_signature`≈axis 5,
  `check_declaration`/`strict_replay_proof`≈axis 6, `audit_axioms`≈axis 7, and axis 8
  — checker identity — has **no operation named for it at all** in the five-op list; see
  Risks §5 below). §6 rule 5 ("no axis defaults to passing") is already the pattern
  `_audit_not_applicable`/`_audit_unknown` implement in `lean_verify.py` today — the ADR
  should describe the five operations using the same never-defaults-to-clean discipline.
- `.claude/docs/evidence-ledger-standard.md` — read in full; applied directly in §B5 above
  (the one item in this brief without full-source verification is explicitly flagged
  `unconfirmable`, not asserted).
- CLAUDE.md §4.7 (no `anthropic` SDK at runtime; `assert` banned via ruff S101) and §4.8
  (server never runs agents; `lean_verify` computes, never persists corpus-visible state)
  — nothing in this milestone's scope (a rename, a schema edit, a hash re-pin, an ADR)
  touches either constraint; flagged here only so the implementer confirms the same before
  merging (the existing handler already has zero `anthropic` imports and zero corpus
  writes — `lean_verify.py` has no `ingest`/`store` import anywhere).
- §1/§4.6 doc placement — the ADR belongs under `.claude/docs/`, following the
  `adr-data-plane-boundary.md` precedent format (Status/Date/Owner/Roadmap
  item/Source brief header block, then `## Context and problem statement` /
  `## Decision N` sections) — that file is the only existing ADR in the repo and is the
  structural template to reuse, not a new format to invent.

## Acceptance criteria the implementer must meet

1. Every code path and test that currently asserts the literal string `"ok"` for
   `lean_verify`'s `status` field must be updated to `"elaborated_no_errors"` — verified
   count: **24** `"ok"` assertions across `tests/test_handlers_lean_verify.py` (the
   `status` enum in `server/schemas/lean_verify_result.json:163` and the three status-
   producing sites in `server/handlers/lean_verify.py` — `_normalize_response:717-724`,
   `_normalize_tactic_step:817-827`, and the sentinel envelopes — must all move together).
2. No response field anywhere in `server/schemas/lean_verify_result.json` may read bare
   `"verified"` (grep-verified: none does today either — the rename must not introduce one).
3. `compilation_success`, `elaborated_no_errors` (renamed `status`), and `axiom_audit` must
   remain **independently derived** per trust-language policy §4 — i.e. the existing
   non-inference discipline in `_normalize_response` / `_attach_axiom_audit` (neither field
   is set from the other) must survive the rename unchanged in behavior.
4. `pytest --update-tool-schema-hash` must be run (bumping `TOOL_SCHEMA_VERSION` from 22
   first, per `tests/test_server_tool_schema.py`'s documented order-of-operations), and
   `EXPECTED_BP1_SHA256` in `tests/test_prompts.py` must be hand-edited afterward — the
   `LEAN_VERIFY.description` literal (`server/tools.py:410-440`) contains the string
   `"ok/error/sorry/incomplete/timeout/unavailable/invalid-input"`, which is BP1-affecting
   and must change alongside the rename.
5. The `server/schemas/lean_verify_result.json` top-level `description` field's running
   changelog (currently ending "...Bumped at the W2 batched re-pin (21 -> 22)...") must
   gain one more entry recording this milestone's version bump and what changed, per the
   file's own established convention.
6. The five-operation ADR must be committed under `.claude/docs/` (not `docs/`, not repo
   root — §1/§4.6), following the `adr-data-plane-boundary.md` structural precedent, and
   must name for each of `parse_source` / `elaborate_signature` / `check_declaration` /
   `audit_axioms` / `strict_replay_proof`: its inputs, its isolation dependency (e2, not
   yet built), its target-binding behavior (e3), and — per this brief's B4 finding — an
   explicit statement that `parse_source` cannot be implemented as a REPL round-trip and
   needs a distinct `Lean.Parser`-based mechanism, not a REPL protocol variant.
7. The ADR must NOT implement any operation (per the roadmap milestone's own acceptance
   criterion 4) — it is a design document only; `lean_verify` itself keeps running exactly
   as it does today except for the rename and schema-shape changes in criteria 1–5.

## Risks and open questions

1. **`parse_source` has no REPL-protocol implementation path.** Confirmed by omission
   across the full leanprover-community/repl README (§B4): `cmd`/`path`/`tactic` all
   elaborate; nothing parses-only. The ADR must name a genuinely different mechanism
   (direct `Lean.Parser` invocation, likely a small Lean metaprogram of its own) for a
   future milestone (m3) rather than imply the REPL subprocess can serve it — silently
   reusing `syntax_only`'s existing `#check`-wrapping approach would repeat exactly the
   "reduces but does not remove kernel work" problem the trust-language policy already
   flagged as unresolved (`trust-language-policy.md:67-68`).
2. **`check_declaration` and `strict_replay_proof` are two different existing trust
   levels, not two implementations of the same check at different speeds.** AXLE's
   `verify_proof` (candidate for `check_declaration`'s shape) explicitly does not re-verify
   the loaded environment and is vulnerable to metaprogramming-installed unchecked
   declarations (§B3, verbatim AXLE quote); SafeVerify/lean4checker/Comparator (candidates
   for `strict_replay_proof`) all perform full `Environment.replay` and catch exactly that
   class. If the ADR describes these as "the same check, twice, for redundancy" rather than
   "two different soundness guarantees," a future implementer could reasonably conclude
   `check_declaration` alone is sufficient and skip building the slower operation — which
   would silently re-open the metaprogramming-tampering gap R3's own brief names as a P0
   concern.
3. **SafeVerify has no version branch matching the repo's pinned toolchain.** The four
   named backport branches (Lean 4.9.0/4.14.0/4.15.0/4.20.0) do not include the repo's
   reference `v4.30.0-rc2` (§B1). `verification-contract-spike-2`
   (`plans/verification-contract/roadmap.yaml:216-228`) already exists to resolve this —
   this ADR milestone should not assume SafeVerify "just works" against the repo's Lean
   version; it should defer that confirmation to the spike explicitly, per the roadmap's
   own sequencing (m3 depends on `spike-2`, not on m1).
4. **The trust-language policy names 8 relevant axes (5–8 map onto Lean-verification
   concerns: elaboration, proof closure, axiom audit, checker identity) but the roadmap's
   five operations only cleanly cover three of those four** (`elaborate_signature`,
   `check_declaration`/`strict_replay_proof`, `audit_axioms`). **No operation is named for
   "checker identity"** (which checker, in which named immutable environment, at what
   policy version) — the roadmap's separate `arxmcp://lean-env` manifest resource (R3 key
   result 6, m5) is presumably meant to close this, but the ADR for the *five operations*
   should say so explicitly (checker identity is a resource, not a sixth operation) rather
   than leave the axis silently unaddressed by anything in this document.
5. **This research found no fetched, hashed source that independently re-confirms F7**
   (the append-only environment-snapshot-array claim). The repo's own prior finding is
   source-level (against `REPL/Main.lean` at `v4.30.0-rc2`, census 2026-07-25) and is
   stronger evidence than anything this brief could add from the public README, which is
   silent on the internal data structure rather than contradicting it. Flagging this so the
   ADR cites the correct (stronger, source-level) evidence rather than a weaker
   documentation-silence inference from this brief.
