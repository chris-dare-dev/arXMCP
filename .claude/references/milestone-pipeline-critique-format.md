# Canonical critique format

Every critic writes a markdown file matching this exact shape. The findings
register (`milestone-pipeline-findings.py`) parses the finding header, the
`**Where:**` citation, and the per-finding body fields — deviate and `extract`
fails LOUD (it refuses the whole file and lists every malformed block; it never
silently drops a finding).

**Critique format version:** 1.0

## What changed in v1.0 (authored ids)

Critics now **author their own finding ids** (`C1`, `H2`, ...) in the header,
instead of the register synthesizing them by file order. Authored ids are
stable: inserting a finding no longer renumbers the ones after it, so a
disposition recorded in Phase 4 (`fixed` / `deferred` / `invalidated`) stays
attached to the finding it was about across a re-`extract`. The id-letter must
agree with the severity (`C`↔CRITICAL, `H`↔HIGH, `M`↔MEDIUM, `L`↔LOW); the
parser rejects a mismatch.

**Scope of that stability guarantee: it holds WITHIN one critic file.** Ids are
authored per-file, so two critics both numbering from 1 both emit `C1`/`M1`/`L1`.
Combining them requires renumbering, and renumbering is exactly the thing
authored ids exist to avoid. See "Merging multiple critics" below — that section
is where the guarantee is qualified, and it is not optional reading for any repo
that runs more than one critic.

## File layout

```markdown
# Critique — <id> — <critic-name>

**Critic:** <milestone-adversary-critic | milestone-oss-scout | overlay name>
**Commit range:** <base-sha>..<head-sha>
**Diff stats:** <files-changed> files, <loc-changed> LOC
**Critique format version:** 1.0

## Verdict

One of: SHIP / SHIP-WITH-FIXES / DO-NOT-SHIP

(One paragraph, ≤ 4 sentences, justifying the verdict.)

## Executive summary

- ≤ 8 bullets summarizing the most important findings.
- Each bullet starts with severity in brackets, e.g. `[CRITICAL]`.
- Concrete; no hedging.

## Findings

(Zero or more findings in the per-finding template below, ordered
CRITICAL → HIGH → MEDIUM → LOW. Number within each severity from 1:
C1, C2, ..., H1, H2, ..., M1, ..., L1, ...  Number from 1 EVEN IF other critics
are running — the orchestrator renumbers on merge; see "Merging multiple
critics". Never try to pre-namespace by critic, the parser rejects it.)

## What was done well

(REQUIRED. 5–10 bullets. An empty section reads adversarial-for-its-own-sake
and triggers a re-dispatch.)

Severity counts: C<n> H<n> M<n> L<n>

## Recommended rectification order

(Ordered list of finding ids, e.g. `C1, H1, H3, M1`. Phase 4 follows this
order by default. The dedupe step inserts its "Cross-critic agreement"
section immediately BEFORE this heading — keep the heading verbatim, and
ensure the merged file carries EXACTLY ONE of it.)

## Phase 4 status (filled by orchestrator at rectify time)

- Fixed: <finding ids>
- Deferred: <finding ids>
- Invalidated: <finding ids with reasons>
- Regression tests added: <file paths>
```

## Per-finding template (parser-load-bearing)

```markdown
**C1 — <short title under 70 chars>** (CRITICAL)

**Where:** `path/to/file.ext:123`
**Anchor:** `<first 40 chars of the cited line, verbatim>`
**What:** <One sentence describing what is wrong.>
**Why it matters:** <One sentence on the consequence.>
**Proposed fix:** <One short paragraph; pseudo-code or a one-line patch is fine.>
**Regression-guard:** <CRITICAL + HIGH: the test/assert that catches regression. MEDIUM + LOW: optional.>
**Source critic:** <agent name>
**Source axis:** <axis name, if applicable>
```

Parser contract (enforced by `milestone-pipeline-findings.py extract`):

- **Header**: `**<id> — <title>** (<SEVERITY>)` where the id is
  `<letter><serial>` (letter ∈ C | H | M | L), SEVERITY ∈ CRITICAL | HIGH |
  MEDIUM | LOW, and the letter matches the severity. Em-dash or hyphen
  separator both parse. The whole header is one bold span on its own line
  with the severity in a trailing paren.
- **`**Where:**`** at line start. There are **EXACTLY TWO accepted forms**, and
  the parser (`FILE_LINE_RE` / `NO_FILE_RE` in `milestone-pipeline-findings.py`)
  rejects everything else — a malformed `**Where:**` makes `extract` refuse the
  WHOLE file and blocks the phase. Copy one of these two lines verbatim:

  ```
  **Where:** `path/to/file.ext:123`
  **Where:** no specific file
  ```

  Form A — a real citation — **MUST** be backtick-wrapped, the path **MUST NOT**
  contain a colon (so no `C:/…` absolute Windows paths — use a repo-relative
  path), and the line **MUST** be a single plain integer (for a range, cite the
  first line). Form B — cross-cutting / whole-diff / procedural findings — is the
  **bare literal**, **NOT** backticked; such findings are kept but excluded from
  dedup clustering.

  **Use Form B for any finding that is not anchored to one line of one file** —
  in particular the mandatory diff-size auto-finding. Do not invent a third
  shape for it.

  These three real rejections have each cost a pipeline run; do not repeat them:

  | Written | Why it was rejected |
  |---|---|
  | ``**Where:** `no specific file` `` | Form B backtick-wrapped. `NO_FILE_RE` matches the BARE literal only. |
  | `**Where:** src/foo.py:42` | Form A missing its backticks. |
  | ``**Where:** `abc1234..def5678` — 971 insertions`` | A commit range is neither form. A whole-diff finding is Form B. |
- **Required body fields**: `**What:**`, `**Why it matters:**`,
  `**Proposed fix:**`, `**Regression-guard:**`, `**Source critic:**`. A
  finding missing any of these is a malformed block; `extract` refuses the
  whole file.
- **`**Anchor:**`** and **`**Source axis:**`** are parsed but optional — the
  Anchor is what the Phase-4 re-verification protocol re-locates the finding
  by, so include it for every CRITICAL + HIGH.

Example finding headers that appear inside ``` fenced blocks (like the ones in
this document) are NOT parsed — the parser blanks fenced code before scanning,
so documentation examples never leak into a register.

## Severity counts line

A `Severity counts: C<n> H<n> M<n> L<n>` line (place it just before the
`## Recommended rectification order` heading, or in the header block) records
the author's own tally. If present, it MUST equal the parsed count — a drifted
line means a finding was added or removed without updating it, and `extract`
flags it. The register never trusts this line for the gate; it is an
author-error tripwire, and `summary --counts-for` re-derives counts by parsing.

Write it for YOUR file only. When several critics are merged, each input's line
is dropped and one true total is emitted — a merged file with two of these lines
is a merge bug, not a critic bug.

## Merging multiple critics

Phase 3 dispatches N critics in parallel and each authors its ids from 1 within
its own file. **Two conformant v1.0 files therefore collide by construction**,
and `cat`-ing them produces a file that is malformed three separate ways:

| Naive concatenation produces | What rejects it |
|---|---|
| duplicate ids (`M1` from critic A and critic B) | `dedupe` / `extract` refuse the WHOLE file: `duplicate finding id M1 (first seen at …)` |
| two `Severity counts:` lines | the parser reads the FIRST and warns it drifted against the real total |
| two `## Recommended rectification order` headings | `dedupe` documents inserting its callout "immediately BEFORE this heading" — ambiguous with two |

None of that is a critic error. **Do not re-dispatch a critic over it**, and do
not hand-edit the critic files: they are the durable per-critic evidence. Merge
them instead:

```bash
python3 .claude/scripts/milestone-pipeline-findings.py merge \
  critique/dedup.md critique/adversary.md critique/<overlay>.md critique/oss.md
```

### The rules `merge` implements (and any manual merge MUST follow)

1. **Renumber by continuing the sequence, in critic dispatch order.** Inputs are
   processed in argv order — **adversary first, then overlay critics in
   lexicographic filename order, then oss**. A per-severity counter runs across
   all files: file 1 keeps `C1, C2, M1, M2, M3, L1, L2`, file 2's `M1–M5` become
   `M4–M8` and its `L1–L2` become `L3–L4`. The parser accepts only a bare
   `<letter><serial>` id, so **namespacing by critic (`ADV-M1`, `A.M1`) is not
   available** — renumbering is the only mechanism.
2. **Exactly one `Severity counts:` line**, carrying the true merged total,
   placed just before the single rectification-order heading. Each input's own
   line is dropped.
3. **Exactly one `## Recommended rectification order` heading**, so `dedupe` has
   one unambiguous insertion point. Its id list is the per-critic lists remapped
   through the renumbering and stable-sorted by severity, which keeps each
   critic's intra-severity priority intact.
4. **Per-critic prose is preserved, not collapsed.** `## Verdict` gets one
   `### <critic> — <verdict>` block per critic plus a merged verdict (the most
   severe: `DO-NOT-SHIP` > `SHIP-WITH-FIXES` > `SHIP`); Executive summaries
   become `## Executive summary — <critic>`; "What was done well" becomes
   `### From <critic>` subsections. Sections `merge` does not recognize are
   carried verbatim under `## Carried from <critic> — <heading>` rather than
   dropped.
5. **Finding bodies are verbatim; only the header id is rewritten.** A critic
   that cross-references its own ids in prose ("as established in M2") keeps the
   pre-merge token, which now names a different finding. `merge` warns when it
   detects this; fix those references by hand.
6. **A single input is a verbatim byte-for-byte copy** — no renumbering, no
   header rewriting. Phase 3 can therefore call `merge` unconditionally.

`merge` re-parses its own output through the same fail-loud parser and refuses
to write a file that would not survive `dedupe`.

### Merged ids are NOT the critics' authored ids

Phase 4 dispositions attach to the **merged** ids. `critique/dedup.md` is the
id authority from the moment it is written; `findings.json`, the `rect(<id>):
close <ids>` commit subject, and every `findings.py set` call all speak merged
ids. A `M4` in `arxmcp.md` and a `M4` in `dedup.md` are generally different
findings — always cite the merged file.

The merge is **deterministic**: same inputs in the same order produce a
byte-identical file, so a re-merge followed by a re-`extract` preserves every
disposition. Dispatch order is what makes that true, which is why rule 1 pins it
rather than leaving it to glob order.

**The guarantee breaks if an input file CHANGES between merges.** Add one MEDIUM
to the adversary's file and every later MEDIUM shifts by one; the disposition
recorded against `M4` now describes the finding that is `M5`. `extract` cannot
catch this — it refuses only a *dropped* id, and a shift-by-one drops nothing,
so it exits 0 and the register is silently wrong. Worked example:

```
before:  M1 alpha (open)   M2 beta (deferred: "cosmetic")
after:   M1 alpha (open)   M2 gamma (deferred: "cosmetic")   M3 beta (open)
                              ^ a finding nobody reviewed, carrying beta's disposition
```

So `merge` runs a **rebind guard**: if a findings register already exists and any
disposed (non-`open`) id would land on a different title, it refuses and names
the id. Treat that refusal as it reads — a critic file changed after `extract`,
which is a NEW critique round, not a re-run. `--force` exists for the case where
the register is genuinely disposable, and prints the same list as a warning.

## Dedup semantics

The orchestrator merges all critic files into `critique/dedup.md` with
`findings.py merge` (adversary first, then overlays, then oss — see "Merging
multiple critics" above; a plain `cat` produces a file `dedupe` refuses) and runs
`milestone-pipeline-findings.py dedupe` on it. Findings within ±5 lines of the
same file are clustered into a "Cross-critic agreement" callout — the strongest
fix-first signal, labelled with the cluster's MOST-severe member. The dedupe
step runs through the same fail-loud parser: a malformed or uncited finding
BLOCKS (it never silently vanishes). Idempotent: re-running on a deduped file
is a no-op.

## Severity calibration anchors

- **CRITICAL** — production breaks or a contract violation (external write
  in the diff, one-writer rule violation, production change with zero test
  deltas, unsigned/untrailered commit, CLAUDE.md contradicted).
- **HIGH** — likely-to-cause-incident bug, unmet acceptance criterion,
  security exposure, dependency license/CVE problem, diff > 400 LOC.
- **MEDIUM** — subtle bug, perf regression, or doc drift; fix only if cheap
  (≤ 30 LOC).
- **LOW** — style, naming, micro-optimization; defer by default.

If a finding maps to no clear analog, demote one level. Never invent a
CRITICAL. Zero CRITICALs and two HIGHs is a credible critique — padding
severity erodes signal.

## Worked example

```markdown
**H1 — Acceptance criterion 2 has no covering test** (HIGH)

**Where:** `src/index/store.py:88`
**Anchor:** `def reopen(self, path: Path) -> Index:`
**What:** The "no rebuild on reopen" criterion is implemented but nothing asserts it.
**Why it matters:** A future refactor can silently regress the criterion the milestone exists to deliver.
**Proposed fix:** Add a test that builds the index, reopens the store, and asserts zero rebuild work was scheduled.
**Regression-guard:** tests/test_store_reopen.py::test_reopen_is_norebuild
**Source critic:** milestone-adversary-critic
**Source axis:** Acceptance coverage
```
