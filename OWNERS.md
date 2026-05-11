# Owners

This is a single-user research project. There is one owner.

## Primary owner

**Chris Dare** — `chris.dare@nalej.com`

The owner is the sole maintainer, code reviewer, security contact, and
release manager. All design decisions, milestone schedules, and merges to
`main` flow through this account.

## Working model

- **Single-user, single-workstation.** All work lands on the `main` branch
  directly. No pull requests, no code review handoff, no feature
  branches.
- **Claude agents do most of the implementation work.** Each milestone
  runs through the four-phase
  [`milestone-pipeline`](.claude/skills/milestone-pipeline/SKILL.md)
  skill (Research → Implement → Critique → Rectify), with the owner
  authorizing scope at milestone entry and approving the external-write
  boundary at milestone exit.
- **Push authorization is per-event.** The owner explicitly authorizes
  each `git push`. A push approved for one event does not authorize
  future pushes.

## Contact

- **General contact / questions:** `chris.dare@nalej.com`
- **Security reports:** see [`SECURITY.md`](SECURITY.md). Same email; do
  not file public GitHub issues for unfixed vulnerabilities.

## Code-area ownership

There is one owner; no per-area `CODEOWNERS` matrix is in force today.
If future contributors join, this file will be revised to map subsystems
to maintainers. Until then, the owner is responsible for every directory
in this repo.
