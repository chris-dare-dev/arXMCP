# Commit format the pipeline emits

Deliberately slim. This documents **only what the milestone-pipeline itself
writes** into a commit — the rect-commit subject and the per-critic
`Reviewed-by:` trailers. Everything else about commit style — allowed types
and scopes, the co-author trailer, signing, hooks — is owned by the **consuming
repo's CLAUDE.md**, which is canonical. The pipeline reads those rules from the
repo; it does not restate or override them here.

There is **no fleet-wide, server-side commit-msg gate**. GitHub does not
enforce a subject-length or type rule on push. Any enforcement is a consuming
repo's own local hook or CLAUDE.md convention — treat every rule below as a
convention the pipeline follows, not a gate a server imposes.

## The rect commit

Phase 4 (rectify) lands a **single** commit that closes the critique findings
it fixed. That commit is never amended onto the Phase 2 implementation commit —
it is a distinct, reviewable rectification.

Subject the pipeline emits:

```
rect(<id>): close <finding-ids>
```

- `<id>` is the milestone / roadmap item id (e.g. `arxmcp-v2-search-m1`).
- `<finding-ids>` is the comma-separated list of findings the commit resolves,
  using the ids from the merged `critique/dedup.md` (e.g. `C1, H1, H2`).

Example:

```
rect(arxmcp-v2-search-m1): close C1, H1, H2
```

`rect(<id>)` is **pipeline-owned**: the milestone-pipeline command (Phase 4b),
`milestone-pipeline-phase-rectify.md`, and `milestone-pipeline-state-schema.md`
all use this exact form, and it is safe because no fleet server-side hook
rejects it.

> Caveat — strict conventional-commit linters. `rect` is not a standard
> conventional-commit type. A consuming repo running a strict local commitlint
> (or a pre-commit conventional-type check) may reject `rect(...)`. For those
> repos, adopt the equivalent standard-type form `fix(<id>-rect): close <ids>`
> instead. Pick **one** convention per repo and use it consistently — never
> ship both in the same repo.

### Subject length

Keep the subject ≤ 50 characters after the `rect(<id>):` prefix, imperative,
no trailing period. This is a **soft house convention**, not a server-enforced
gate. If a consuming repo's CLAUDE.md or local hook sets a different limit,
that wins.

## Reviewed-by trailers

The rect commit carries **one `Reviewed-by:` trailer per critic that ran** in
Phase 3, so the review provenance travels with the commit:

```
Reviewed-by: <critic-agent-name> <noreply@anthropic.com>
```

For example, a run where only the always-on adversary critic fired:

```
Reviewed-by: milestone-adversary-critic <noreply@anthropic.com>
```

A run with an overlay critic and the OSS scout adds a trailer each:

```
Reviewed-by: milestone-adversary-critic <noreply@anthropic.com>
Reviewed-by: milestone-web-perf-critic <noreply@anthropic.com>
Reviewed-by: milestone-oss-scout <noreply@anthropic.com>
```

The `<noreply@anthropic.com>` address is the agent identity; the trailer names
the agent, not a human reviewer.

## What this file does NOT own (defer to the consuming repo)

- **Types and scopes** for ordinary (non-rect) commits — the implementer uses
  the repo's conventional-commit types/scopes from its CLAUDE.md.
- **The co-author trailer** — each repo's CLAUDE.md mandates its own
  `Co-Authored-By:` line; the pipeline appends whatever that repo requires.
- **Signing** — honor the consuming repo's signing configuration. Never
  `--no-verify`, never `--no-gpg-sign`, never a hardcoded gpg program path;
  let git and the repo/environment resolve the signing program. Signing is a
  per-repo requirement, not a fleet-wide mandate. If signing infrastructure is
  unresponsive, abort rather than bypass it.
- **Branch** — never hardcode a branch name. Derive the default branch:

  ```bash
  git symbolic-ref --short refs/remotes/origin/HEAD | sed 's|origin/||'
  ```

  Fall back to the current branch if that fails. Personal repos default to
  `main` (`options-signal-engine` uses `master`); the pipeline never assumes.

## External-write boundary

Committing is local. **Pushing is an external write** and the pipeline never
crosses that boundary on its own — `git push`, publish, and deploy all stop
and ask the user for explicit authorization (Phase 4d). The rect commit is
composed and landed locally; whether it ever reaches a remote is the user's
call.

## Cross-references

- `milestone-pipeline.md` — Phase 4b composes and lands the rect commit.
- `milestone-pipeline-phase-rectify.md` — full rectify protocol.
- `milestone-pipeline-state-schema.md` — records `rectification_commit`.
- `milestone-pipeline-agent-contract.md` — the implementer's own commit rules
  (types/scopes/signing deferred to the repo) mirror the deferral here.
