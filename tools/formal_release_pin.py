"""Pin a topic repo's released formalization. Re-derives from git, not from the bundle.

Lands derived-alg-geo-lean **#174** (epic #135). Offline, read-only over the
topic repo, and it writes exactly one row into ``notebooks.db``'s
``formal_releases`` table (v6). ADR-0004: arXMCP hosts no registry — it holds a
**pin** to a released one and re-serves its records verbatim.

## The weakness this exists to fix

A bundle that crosses the seam validated only for *self-consistency* has no
producer-side gate that survives a file copy. Every one of the design's
sorry-gates was on the producer's side; none of them travelled with the
artifact. Flip ``contains_sorry_ax`` in ``declarations.json``, recompute that
file's sha256 into ``bundle.json``, and the set is internally consistent and
says the opposite of what CI measured.

So the root of trust is the **git tag object**, which the producer's own tag
message names as such:

    The tag object, not the bundle's self-reported hashes, is the root of
    trust across the seam: arXMCP re-derives digests from it.

## What is actually re-derivable, and what is not

This is where the design and the repository disagree today, and the tool says
so rather than papering over it.

**Re-derivable from git, and checked:**

* ``subject[0].digest.gitCommit`` — against ``git rev-parse <tag>^{commit}``.
* ``subject[0].digest.gitTag`` — against the tag name on the tag object.
* ``registry_sha256`` — against ``sha256(git show <tag>:registry/<slug>.json)``.
  The registry IS tracked, and it is the artifact arXMCP re-serves.

**Not re-derivable, because the files are not in git:**
``attest/*`` is gitignored in the topic repo (``/attest/*`` with a single
``!/attest/review.yaml`` re-include), deliberately — CI regenerates those on
every run and a committed copy would be a stale trust record. They exist only
as release assets. So ``predicates[].sha256`` can be checked for *internal*
consistency against the asset bytes and nothing more, and the tamper above is
NOT caught by any git-rooted check.

That is a real gap and it is reported, never hidden: the pin records
``digest_provenance`` as ``git_rooted`` or ``self_attested_only``, and
``self_attested_only`` is never presented as a pass. §4.9 rule 1 — no axis is
inferred from another, and no bare "verified".

**How to close it, at the next tag.** Put the digests in the tag message,
which is the one artifact the tag object actually carries and which no asset
replacement can reach. This tool parses that block already::

    -----BEGIN MFC DIGESTS-----
    attest/bundle.json  <sha256>
    attest/declarations.json  <sha256>
    attest/environment.json  <sha256>
    attest/build.json  <sha256>
    -----END MFC DIGESTS-----

With the block present the tamper test refuses, because the recomputed
``bundle.json`` no longer matches the digest the tag object names. v0.1.0's
message carries prose asserting this property and no block, so pinning it
today reports ``self_attested_only``.

## The withdrawals channel travels forward in time

``withdrawals.yaml`` is fetched from the **newest** tag even when pinned to an
older one — the single channel permitted to do that, and safe for exactly one
reason: it can only REMOVE trust, never grant it. Without it, a v0.1.0 pin
keeps serving a record that v0.2.0 marked ``inadequate`` and nothing tells
anyone.

Usage::

    uv run python -m tools.formal_release_pin \\
        --repo-path ../derived-alg-geo-lean \\
        --tag v0.1.0 \\
        --notebook bridgeland-stability \\
        --assets ./release-assets \\
        --registry registry/bridgeland2007.json

Exit codes:
    0 — pinned
    1 — refused: dirty worktree, unknown tag, digest mismatch, or an artifact
        that does not validate. Nothing is written on any refusal.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sqlite3
import subprocess
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from tools._statement_common import StatementToolError, validate_against

#: Digest provenance, and the two values are NOT a scale with a passing end.
#: `git_rooted` means the tag object names the digests and they match.
#: `self_attested_only` means the artifact set agrees with itself and nothing
#: outside it was consulted, which is the state a file copy survives.
GIT_ROOTED = "git_rooted"
SELF_ATTESTED_ONLY = "self_attested_only"

#: The optional digest block in an annotated tag's message. Whitespace-tolerant
#: on the separator so a hand-written tag is not rejected for two spaces.
_DIGEST_BLOCK_RE = re.compile(
    r"-----BEGIN MFC DIGESTS-----(?P<body>.*?)-----END MFC DIGESTS-----",
    re.DOTALL,
)
_DIGEST_LINE_RE = re.compile(r"^\s*(?P<path>\S+)\s+(?P<sha>[0-9a-f]{64})\s*$")


class PinError(StatementToolError):
    """A refusal. Printed, exit 1, nothing written."""


@dataclass(frozen=True)
class TagObject:
    """What the git tag object itself says."""

    name: str
    object_sha: str
    commit_sha: str
    message: str
    digests: dict[str, str]

    @property
    def is_annotated(self) -> bool:
        """A lightweight tag is a ref, not an object, and carries no message.

        It can still name a commit, so the commit check holds; there is simply
        nothing for a digest block to live in.
        """
        return self.object_sha != self.commit_sha


def _git(repo: Path, *args: str) -> str:
    proc = subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True, text=True, check=False,
    )
    if proc.returncode != 0:
        raise PinError(
            f"git {' '.join(args)} failed in {repo}: "
            f"{proc.stderr.strip() or proc.stdout.strip()}"
        )
    return proc.stdout


def refuse_dirty_worktree(repo: Path) -> None:
    """A dirty tree makes every digest a true statement about a tree nobody can fetch.

    The producer's own `mfc seal` refuses one for the same reason; a consumer
    that did not would accept a pin nobody else can reproduce.
    """
    porcelain = _git(repo, "status", "--porcelain").strip()
    if porcelain:
        lines = porcelain.split("\n")
        shown = "\n".join(f"    {ln}" for ln in lines[:10])
        more = f"\n    … and {len(lines) - 10} more" if len(lines) > 10 else ""
        raise PinError(
            f"{repo} has {len(lines)} uncommitted change(s); refusing to pin.\n"
            f"{shown}{more}\n"
            f"The pin names a commit, and a dirty tree means the files here "
            f"are not that commit. Stash or commit, then re-run."
        )


def read_tag(repo: Path, tag: str) -> TagObject:
    """Resolve ``tag`` to its object, its commit, and any digest block."""
    object_sha = _git(repo, "rev-parse", "--verify", f"refs/tags/{tag}").strip()
    commit_sha = _git(repo, "rev-parse", "--verify", f"{tag}^{{commit}}").strip()
    kind = _git(repo, "cat-file", "-t", object_sha).strip()
    message = _git(repo, "cat-file", "tag", object_sha) if kind == "tag" else ""
    return TagObject(
        name=tag,
        object_sha=object_sha,
        commit_sha=commit_sha,
        message=message,
        digests=parse_digest_block(message),
    )


def parse_digest_block(message: str) -> dict[str, str]:
    """``{path: sha256}`` from a tag message's digest block; ``{}`` when absent.

    Absent is the ordinary case today and is NOT an error — it is the reason
    the pin reads ``self_attested_only``. Silently returning ``{}`` for a
    MALFORMED block would be, so a block containing no parseable line raises.
    """
    match = _DIGEST_BLOCK_RE.search(message)
    if match is None:
        return {}
    digests: dict[str, str] = {}
    for line in match.group("body").split("\n"):
        if not line.strip():
            continue
        entry = _DIGEST_LINE_RE.match(line)
        if entry is None:
            raise PinError(
                f"the tag's MFC DIGESTS block has an unparseable line: "
                f"{line.strip()!r}. Expected `<path>  <64-hex sha256>`. A block "
                f"that cannot be read is not the same as no block, and it must "
                f"not degrade quietly to one."
            )
        digests[entry.group("path")] = entry.group("sha")
    if not digests:
        raise PinError(
            "the tag carries an empty MFC DIGESTS block; that is not a "
            "digest-free tag, it is a broken one"
        )
    return digests


def blob_at(repo: Path, tag: str, path: str) -> bytes | None:
    """The bytes of ``path`` in git at ``tag``, or ``None`` when untracked there."""
    proc = subprocess.run(
        ["git", "-C", str(repo), "show", f"{tag}:{path}"],
        capture_output=True, check=False,
    )
    return proc.stdout if proc.returncode == 0 else None


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def newest_tag(repo: Path) -> str | None:
    """The most recent tag — where withdrawals are read from.

    Creation date, not a version comparator: a comparator has to be taught
    this repo's tag grammar, and getting it wrong would point the revocation
    channel at the WRONG tag, which is the one direction this channel must
    never fail in.

    Ties are broken by refname, descending. Git tag timestamps have
    one-second resolution and two tags cut in the same second sort
    arbitrarily otherwise -- which would make the channel non-deterministic
    exactly when a release is being re-cut, and that is when it matters.
    """
    out = _git(
        repo, "for-each-ref", "--format=%(creatordate:unix) %(refname:short)",
        "refs/tags",
    ).strip()
    rows = []
    for line in out.split("\n"):
        if not line.strip():
            continue
        stamp, _, name = line.partition(" ")
        rows.append((int(stamp), name))
    if not rows:
        return None
    return max(rows)[1]


@dataclass
class Pin:
    """Everything verified, ready to write. Assembled only on a clean run."""

    slug: str
    repo_url: str
    tag: TagObject
    registry_path: str
    registry_bytes: bytes
    registry_doc: dict
    bundle_doc: dict
    digest_provenance: str
    findings: list[str]
    withdrawals_doc: dict | None
    withdrawals_tag: str | None
    asset_dir: str


def verify(
    repo: Path,
    *,
    tag_name: str,
    slug: str,
    registry_path: str,
    assets: Path | None,
    allow_dirty: bool = False,
) -> Pin:
    """Every check, in order. Raises :class:`PinError` on the first refusal."""
    if not (repo / ".git").exists():
        raise PinError(f"{repo} is not a git repository")
    if not allow_dirty:
        refuse_dirty_worktree(repo)

    tag = read_tag(repo, tag_name)

    # --- the registry, which IS in git ------------------------------------
    registry_bytes = blob_at(repo, tag_name, registry_path)
    if registry_bytes is None:
        raise PinError(
            f"{registry_path} is not tracked at {tag_name}. The registry is "
            f"the one contract artifact this tool can root in git, so a pin "
            f"without it has no git-rooted axis at all."
        )
    registry_doc = json.loads(registry_bytes.decode("utf-8"))
    registry_sha256 = sha256_bytes(registry_bytes)

    # --- the bundle, from the assets --------------------------------------
    bundle_doc, bundle_bytes = _load_bundle(repo, tag_name, assets)
    validate_against(bundle_doc, "bundle-1.0")

    subject = (bundle_doc.get("subject") or [{}])[0]
    digest = subject.get("digest") or {}
    if digest.get("gitCommit") != tag.commit_sha:
        raise PinError(
            f"the bundle attests gitCommit {digest.get('gitCommit')!r} and "
            f"{tag_name} points at {tag.commit_sha!r}. These artifacts "
            f"describe a different tree than the one being pinned."
        )
    if digest.get("gitTag") != tag_name:
        raise PinError(
            f"the bundle attests gitTag {digest.get('gitTag')!r}, not "
            f"{tag_name!r}. An artifact set built before its tag existed says "
            f"null here -- a valid artifact and an invalid release."
        )
    if bundle_doc.get("registry_sha256") != registry_sha256:
        raise PinError(
            f"registry_sha256 disagrees. The bundle says "
            f"{bundle_doc.get('registry_sha256')!r}; {registry_path} at "
            f"{tag_name} hashes to {registry_sha256!r}. This is the check the "
            f"whole seam rests on: the bundle describes a registry that is "
            f"not the one in this tag."
        )

    # --- the predicates, rooted in the tag object when it says so ---------
    provenance, findings = _check_predicates(
        repo, tag, bundle_doc, bundle_bytes, assets
    )

    withdrawals_doc, withdrawals_tag = _load_withdrawals(repo, registry_doc)

    return Pin(
        slug=slug,
        repo_url=_remote_url(repo),
        tag=tag,
        registry_path=registry_path,
        registry_bytes=registry_bytes,
        registry_doc=registry_doc,
        bundle_doc=bundle_doc,
        digest_provenance=provenance,
        findings=findings,
        withdrawals_doc=withdrawals_doc,
        withdrawals_tag=withdrawals_tag,
        asset_dir=str(assets) if assets else "",
    )


def _load_bundle(
    repo: Path, tag_name: str, assets: Path | None
) -> tuple[dict, bytes]:
    """``attest/bundle.json`` from the assets, or from git if it is tracked."""
    if assets is not None:
        path = assets / "bundle.json"
        if not path.is_file():
            raise PinError(f"no bundle.json in {assets}")
        raw = path.read_bytes()
    else:
        found = blob_at(repo, tag_name, "attest/bundle.json")
        if found is None:
            raise PinError(
                "attest/bundle.json is neither in --assets nor tracked at "
                f"{tag_name}. The topic repo gitignores attest/* and publishes "
                "it as a release asset; download the assets and pass --assets."
            )
        raw = found
    return json.loads(raw.decode("utf-8")), raw


def _check_predicates(
    repo: Path,
    tag: TagObject,
    bundle_doc: dict,
    bundle_bytes: bytes,
    assets: Path | None,
) -> tuple[str, list[str]]:
    """Decide ``digest_provenance``, and say what could not be checked.

    Three rungs, and only the first is a claim about anything outside the
    artifact set:

    1. the tag object names the digests -> compare against it. ``git_rooted``.
    2. the file is tracked at the tag -> compare against the blob. Also
       ``git_rooted`` for that file.
    3. neither -> compare the asset's bytes against what the bundle says about
       them, which establishes the set is internally consistent and nothing
       more. ``self_attested_only``.
    """
    findings: list[str] = []
    rooted = bool(tag.digests)

    if rooted:
        claimed = tag.digests.get("attest/bundle.json")
        if claimed is None:
            raise PinError(
                "the tag's digest block does not name attest/bundle.json. A "
                "block that omits the bundle roots nothing: every other digest "
                "in the set is read out of the bundle."
            )
        actual = sha256_bytes(bundle_bytes)
        if claimed != actual:
            raise PinError(
                f"attest/bundle.json hashes to {actual} and the tag object "
                f"names {claimed}. The tag object is the root of trust; these "
                f"assets are not the ones this tag was cut over."
            )

    for predicate in bundle_doc.get("predicates") or []:
        name = predicate.get("file", "")
        claimed = predicate.get("sha256", "")
        data = _predicate_bytes(repo, tag, name, assets)
        if data is None:
            findings.append(f"{name}: not present in --assets or in git; unchecked")
            rooted = False
            continue
        actual = sha256_bytes(data)
        if actual != claimed:
            raise PinError(
                f"{name} hashes to {actual}; the bundle claims {claimed}."
            )
        if tag.digests:
            tagged = tag.digests.get(name)
            if tagged is None:
                findings.append(
                    f"{name}: the bundle's digest matches the file, but the "
                    f"tag's digest block does not name it"
                )
                rooted = False
            elif tagged != actual:
                raise PinError(
                    f"{name} hashes to {actual}; the TAG OBJECT names "
                    f"{tagged}. The bundle agreeing with the file means only "
                    f"that both were changed together."
                )
        elif blob_at(repo, tag.name, name) is None:
            rooted = False

    if not rooted:
        findings.append(
            "no git-rooted digest covers the attest artifacts: the topic repo "
            "gitignores attest/* (deliberately -- CI regenerates them and a "
            "committed copy would be a stale trust record) and this tag's "
            "message carries no MFC DIGESTS block. The set is internally "
            "consistent, which a file copy also is. Add the block at the next "
            "tag; this tool reads it."
        )
    return (GIT_ROOTED if rooted else SELF_ATTESTED_ONLY), findings


def _predicate_bytes(
    repo: Path, tag: TagObject, name: str, assets: Path | None
) -> bytes | None:
    if assets is not None:
        candidate = assets / Path(name).name
        if candidate.is_file():
            return candidate.read_bytes()
    return blob_at(repo, tag.name, name)


def _load_withdrawals(repo: Path, registry_doc: dict) -> tuple[dict | None, str | None]:
    """``withdrawals.yaml`` from the NEWEST tag, not the pinned one.

    The single channel permitted to travel forward in time, and safe for
    exactly one reason: a withdrawal can only remove trust, never grant it.
    Reading it from the pinned tag would mean a v0.1.0 pin keeps serving a
    record v0.2.0 marked inadequate, with nothing to say so.
    """
    latest = newest_tag(repo)
    if latest is None:
        return None, None
    raw = blob_at(repo, latest, "attest/withdrawals.yaml")
    if raw is None:
        raw = blob_at(repo, latest, "withdrawals.yaml")
    if raw is None:
        return None, latest
    try:
        import yaml
    except ImportError as exc:  # pragma: no cover - PyYAML is a dep of [contract]
        raise PinError(
            "withdrawals.yaml exists at the newest tag but PyYAML is not "
            "installed, so the revocation channel cannot be read. Refusing to "
            "pin: a pin that silently skips withdrawals is exactly the failure "
            "the channel was added to prevent."
        ) from exc
    document = yaml.safe_load(raw.decode("utf-8")) or {}
    mine = registry_doc.get("registry_id")
    theirs = document.get("registry_id")
    if mine and theirs and mine != theirs:
        raise PinError(
            f"the withdrawals at {latest} are for registry {theirs!r} and this "
            f"registry is {mine!r}. Applying them would remove trust from keys "
            f"they were never about."
        )
    return document, latest


def _remote_url(repo: Path) -> str:
    try:
        return _git(repo, "config", "--get", "remote.origin.url").strip()
    except PinError:
        return str(repo)


def to_row(pin: Pin, *, pinned_at: str | None = None) -> dict[str, str | None]:
    """The ``formal_releases`` row. Small artifacts inline, big ones by path."""
    return {
        "slug": pin.slug,
        "repo": pin.repo_url,
        "tag": pin.tag.name,
        "tag_object_sha": pin.tag.object_sha,
        "commit_sha": pin.tag.commit_sha,
        "registry_id": pin.registry_doc.get("registry_id", ""),
        "registry_sha256": sha256_bytes(pin.registry_bytes),
        "env_digest": pin.bundle_doc.get("env_digest", ""),
        "digest_provenance": pin.digest_provenance,
        "asset_dir": pin.asset_dir,
        "bundle_json": json.dumps(pin.bundle_doc, sort_keys=True),
        # Stored as the BYTES from git, decoded -- not a re-serialization.
        # `registry_sha256` is computed over these bytes and the topic repo
        # compares it against its own `shasum`, so a canonicalizing round-trip
        # here would make the served record disagree with the pin.
        "registry_json": pin.registry_bytes.decode("utf-8"),
        "resolution_json": None,
        "review_json": None,
        "withdrawals_json": (
            json.dumps(pin.withdrawals_doc, sort_keys=True)
            if pin.withdrawals_doc is not None else None
        ),
        "withdrawals_tag": pin.withdrawals_tag,
        "pinned_at": pinned_at or datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }


def write_pin(db_path: Path, row: dict[str, str | None]) -> None:
    """Write the row through the store's own migration ladder.

    :func:`server.notebooks_store.open_sync`, never a raw connection: a writer
    that leaves ``user_version`` at 0 arms the v0->v1 block's unconditional
    ``DROP TABLE``, which is the hazard #174 names in `notebook_restore.py`
    and which a second sync writer would have doubled.
    """
    from server.notebooks_store import open_sync

    conn = open_sync(db_path)
    try:
        columns = ", ".join(row)
        placeholders = ", ".join(f":{k}" for k in row)
        conn.execute("BEGIN IMMEDIATE")
        try:
            conn.execute(
                f"INSERT OR REPLACE INTO formal_releases ({columns}) "
                f"VALUES ({placeholders})",
                row,
            )
            conn.execute("COMMIT")
        except sqlite3.IntegrityError as exc:
            conn.execute("ROLLBACK")
            # `formal_releases.slug` references `notebooks(slug)`, so a pin
            # for a notebook that does not exist is refused by the FK. Said
            # plainly here: the raw message is "FOREIGN KEY constraint
            # failed", which names neither the notebook nor the fix.
            raise PinError(
                f"no notebook {row['slug']!r} on this server, so there is "
                f"nothing for this release to be served under. Create it "
                f"first (make init NOTEBOOK={row['slug']}), then re-pin. "
                f"({exc})"
            ) from exc
        except Exception:
            conn.execute("ROLLBACK")
            raise
    finally:
        conn.close()


def run(
    *,
    repo_path: Path,
    tag: str,
    notebook: str,
    registry: str,
    assets: Path | None,
    db_path: Path | None,
    dry_run: bool,
) -> int:
    from server.operator_settings import DEFAULT_DB_PATH

    pin = verify(
        repo_path, tag_name=tag, slug=notebook,
        registry_path=registry, assets=assets,
    )
    row = to_row(pin)

    for finding in pin.findings:
        print(f"  note: {finding}", file=sys.stderr)
    print(
        f"{pin.tag.name} -> commit {pin.tag.commit_sha[:12]} "
        f"(tag object {pin.tag.object_sha[:12]}), registry "
        f"{row['registry_sha256'][:12]}, {len(pin.registry_doc.get('entries') or {})} "
        f"entries, digest_provenance={pin.digest_provenance}"
    )
    if pin.digest_provenance == SELF_ATTESTED_ONLY:
        print(
            "  digest_provenance is self_attested_only. That is NOT a pass "
            "with a caveat: it means nothing outside the artifact set was "
            "consulted for the attest digests, which is a state a file copy "
            "also reaches. The served record carries it.",
            file=sys.stderr,
        )
    if dry_run:
        print("dry run; nothing written")
        return 0
    write_pin(db_path or DEFAULT_DB_PATH, row)
    print(f"pinned into {db_path or DEFAULT_DB_PATH}")
    return 0


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(__doc__ or "").splitlines()[0],
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--repo-path", type=Path, required=True,
                        help="local clone of the topic repo")
    parser.add_argument("--tag", required=True, help="the release tag to pin")
    parser.add_argument("--notebook", required=True,
                        help="the notebook slug this release is served under")
    parser.add_argument("--registry", required=True,
                        help="repo-relative path to registry/<work-slug>.json")
    parser.add_argument("--assets", type=Path, default=None,
                        help="directory of downloaded release assets "
                             "(attest/* is gitignored in the topic repo)")
    parser.add_argument("--db", type=Path, default=None,
                        help="notebooks.db (default: var/arxmcp/cache/notebooks.db)")
    parser.add_argument("--dry-run", action="store_true",
                        help="verify and report; write nothing")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_arg_parser().parse_args(argv)
    try:
        return run(
            repo_path=args.repo_path, tag=args.tag, notebook=args.notebook,
            registry=args.registry, assets=args.assets, db_path=args.db,
            dry_run=args.dry_run,
        )
    except StatementToolError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
