# Roadmap

This file is a redirect. The authoritative roadmap moved to
[`.claude/roadmap/README.md`](.claude/roadmap/README.md) on 2026-05-08 (rev
2026-05).

**Why:** the old `ROADMAP.md` used a 15-epic / Tier-0-to-Tier-7 numbering
scheme that didn't match the per-epic spec files. The split between epics
was renumbered in May 2026 to align with the spec files (E01–E14), and
the authoritative index now lives next to those specs.

## Where to go

| What you want | Where to look |
|---|---|
| **Live epic index** (E01–E14, ship status, dependencies) | [`.claude/roadmap/README.md`](.claude/roadmap/README.md) |
| **Per-epic spec** (E01 through E14) | [`.claude/roadmap/E<NN>-<slug>.md`](.claude/roadmap/) |
| **Per-milestone ground truth** (state.json `phase: complete`) | [`.claude/notes/milestones/`](.claude/notes/milestones/) |
| **Tier promotion gates** (what "Tier-N done" means) | [`TIER-GATES.md`](TIER-GATES.md) |
| **Design rationale** (the constitution) | [`.claude/notes/README.md`](.claude/notes/README.md) |
| **Critique-remediation matrix** (H1–H10 + MEDIUM findings) | [`.claude/roadmap/README.md`](.claude/roadmap/README.md) § Critique-remediation matrix |

## Ship status (one-line)

- **E01–E09 shipped** (Tier 0 → Tier 2). 1316 tests passing.
- **E10, E11, E13, E14 pending.** E12 scoped-out (folded into E11).

The historical content of the old `ROADMAP.md` is preserved in git history;
see `git log --oneline ROADMAP.md` for prior revisions.
