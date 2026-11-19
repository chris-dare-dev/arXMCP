# Owners

This is a single-user research project. There is one owner.

## Primary owner

**Chris Dare** — `cedare96@gmail.com`

The owner is the sole maintainer, code reviewer, security contact, and
release manager. All design decisions, milestone schedules, and merges to
`main` flow through this account.

## Working model

- **Single-user, single-workstation.** Changes land on `main` through pull
  requests the owner reads and merges.
- **Claude agents do most of the implementation work.** The owner sets
  scope in the issue and approves every external write.
- **Push authorization is per-event.** The owner explicitly authorizes
  each `git push`. A push approved for one event does not authorize
  future pushes.

## Contact

- **General contact / questions:** `cedare96@gmail.com`
- **Security reports:** see [`SECURITY.md`](SECURITY.md). Same email; do
  not file public GitHub issues for unfixed vulnerabilities.

## Code-area ownership

There is one owner; no per-area `CODEOWNERS` matrix is in force today.
If future contributors join, this file will be revised to map subsystems
to maintainers. Until then, the owner is responsible for every directory
in this repo.
