"""The pinner, and the tamper it is supposed to catch.

derived-alg-geo-lean **#174**. The design weakness this closes: a bundle that
crosses the seam validated only for self-consistency has no producer-side gate
that survives a file copy. Flip `contains_sorry_ax`, recompute that file's
sha256 into `bundle.json`, and the set agrees with itself while saying the
opposite of what CI measured.

So the central test is the tamper test, and it is written twice on purpose:

* with a digest block in the tag message, the pinner REFUSES — the tag object
  is a root the tampering cannot reach;
* without one, it does NOT refuse, and reports `self_attested_only`.

The second is not a weaker version of the first. It is the honest record of
where the topic repo stands today: `attest/*` is gitignored there, so nothing
git-rooted covers those files, and v0.1.0's tag message asserts the property in
prose while carrying no block. A test suite that only exercised the happy path
would let `self_attested_only` read as a pass, which is the failure §4.9 rule 1
exists to prevent.

Real `git`, synthetic repos, no network.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from tools.formal_release_pin import (
    GIT_ROOTED,
    SELF_ATTESTED_ONLY,
    PinError,
    newest_tag,
    parse_digest_block,
    read_tag,
    refuse_dirty_worktree,
    to_row,
    verify,
    write_pin,
)

pytestmark = pytest.mark.skipif(
    shutil.which("git") is None, reason="git is not on PATH"
)

REGISTRY_ID = "a520a8d4f877"
ENV_DIGEST = "45d9e8ca8c1b" + "c" * 52   # 64 hex; the schema checks the shape


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True, text=True, check=True,
    ).stdout


def _registry() -> dict:
    return {
        "schema_version": "registry/1.0",
        "registry_id": REGISTRY_ID,
        "notebook_hint": "bridgeland-stability",
        "entries": {
            f"stmt:{REGISTRY_ID}:bridgeland2007.lem-8.2": {
                "kind": "lemma", "title": "A bound", "informal": "A bound.",
                "source": {"scheme": "arxiv", "id": "math/0212237",
                           "version": "v3", "printed_number": "8.2",
                           "locator": None},
                "quote_mode": "verbatim", "quote": "Lemma 8.2. A bound.",
                "quote_norm": "nfc-ws-collapse/1",
                "quote_sha256": "e" * 64,
                "mint_resolution": None,
                "mint_unresolved_reason": "no resolver run",
                "depends_on": [], "frontier": [],
                "minted_at": "2026-08-05", "minted_by": "fixture",
                "supersedes": None, "superseded_by": None,
            }
        },
    }


def _declarations(*, contains_sorry_ax: bool = False) -> dict:
    return {
        "schema_version": "declarations/1.0",
        "contains_sorry_ax": contains_sorry_ax,
        "constants": [{"name": "Topic.thm"}],
    }


@pytest.fixture
def topic(tmp_path: Path) -> dict:
    """A topic repo with a tag, plus its release assets in a sibling dir.

    Mirrors the real shape: the registry is TRACKED, `attest/*` is gitignored
    and exists only as assets.
    """
    repo = tmp_path / "topic"
    (repo / "registry").mkdir(parents=True)
    _git_init(repo)

    registry_bytes = (json.dumps(_registry(), indent=2) + "\n").encode()
    (repo / "registry" / "bridgeland2007.json").write_bytes(registry_bytes)
    (repo / ".gitignore").write_text("/attest/*\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "the tree this tag names")
    commit = _git(repo, "rev-parse", "HEAD").strip()

    assets = tmp_path / "assets"
    assets.mkdir()
    declarations = (json.dumps(_declarations(), indent=2) + "\n").encode()
    (assets / "declarations.json").write_bytes(declarations)
    bundle = {
        "schema_version": "bundle/1.0",
        "_type": "https://in-toto.io/Statement/v1",
        "subject": [{"name": "Topic",
                     "uri": "https://example.invalid/topic",
                     "digest": {"gitCommit": commit, "gitTag": "v0.1.0"}}],
        "contract_repo": {"url": "https://example.invalid/mfc", "rev": "a" * 40},
        "env_digest": ENV_DIGEST,
        "registry_sha256": _sha(registry_bytes),
        "predicates": [{
            "predicateType": "https://example.invalid/predicate/declarations/v1",
            "file": "attest/declarations.json",
            "sha256": _sha(declarations),
            "produced_by": "fixture",
            "env_digest": ENV_DIGEST,
            "self_attested": True,
        }],
        "unrecognized_predicates": [],
    }
    _write_bundle(assets, bundle)
    return {"repo": repo, "assets": assets, "commit": commit,
            "registry_sha256": _sha(registry_bytes)}


def _git_init(repo: Path) -> None:
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.email", "fixture@example.invalid")
    _git(repo, "config", "user.name", "Fixture")
    _git(repo, "config", "commit.gpgsign", "false")
    _git(repo, "config", "tag.gpgsign", "false")


def _write_bundle(assets: Path, bundle: dict) -> bytes:
    raw = (json.dumps(bundle, indent=2) + "\n").encode()
    (assets / "bundle.json").write_bytes(raw)
    return raw


def _tag(repo: Path, name: str, message: str) -> None:
    _git(repo, "tag", "-a", name, "-m", message)


def _digest_block(assets: Path) -> str:
    lines = [
        f"attest/bundle.json  {_sha((assets / 'bundle.json').read_bytes())}",
        f"attest/declarations.json  "
        f"{_sha((assets / 'declarations.json').read_bytes())}",
    ]
    return ("-----BEGIN MFC DIGESTS-----\n" + "\n".join(lines)
            + "\n-----END MFC DIGESTS-----")


def _notebook_db(tmp_path: Path, slug: str = "bridgeland-stability") -> Path:
    """A notebooks.db with the row `formal_releases.slug` references.

    The FK is the point: a pin for a notebook that does not exist would be a
    record nothing can serve.
    """
    from server.notebooks_store import open_sync

    db = tmp_path / "notebooks.db"
    conn = open_sync(db)
    try:
        conn.execute(
            "INSERT INTO notebooks (slug, display_name, lancedb_path, "
            "created_at) VALUES (?, '', '', '2026-09-03T00:00:00Z')",
            (slug,),
        )
    finally:
        conn.close()
    return db


def _verify(topic, **kw):
    defaults = dict(
        tag_name="v0.1.0", slug="bridgeland-stability",
        registry_path="registry/bridgeland2007.json", assets=topic["assets"],
    )
    defaults.update(kw)
    return verify(topic["repo"], **defaults)


# --- the tamper, both ways -----------------------------------------------------

def test_a_tamper_that_recomputes_the_bundle_is_refused_when_the_tag_names_digests(
    topic,
) -> None:
    """#174's test, and the whole reason this tool re-derives anything.

    `contains_sorry_ax` is flipped AND the file's sha256 is recomputed into
    `bundle.json`, so the artifact set is internally consistent — every check
    a self-validating bundle can perform passes. The tag object is the one
    thing the tamperer cannot reach without pushing a new tag.
    """
    assets = topic["assets"]
    _tag(topic["repo"], "v0.1.0", "release\n\n" + _digest_block(assets))
    assert _verify(topic).digest_provenance == GIT_ROOTED

    tampered = (json.dumps(_declarations(contains_sorry_ax=True), indent=2)
                + "\n").encode()
    (assets / "declarations.json").write_bytes(tampered)
    bundle = json.loads((assets / "bundle.json").read_text())
    bundle["predicates"][0]["sha256"] = _sha(tampered)   # internally consistent
    _write_bundle(assets, bundle)

    # Refused at the bundle, before its predicates are even read: the
    # tamperer had to edit `bundle.json` to keep the set consistent, and the
    # tag object names that file too. Either refusal is the tag object
    # catching what the artifact set alone cannot.
    with pytest.raises(PinError, match="(?i)tag object"):
        _verify(topic)


def test_the_same_tamper_is_NOT_caught_without_a_digest_block(topic) -> None:
    """And the pin says `self_attested_only` rather than pretending.

    This is where the topic repo stands today: `attest/*` is gitignored, so
    the only digests covering those files are the ones inside the file set,
    and a coordinated edit satisfies all of them. v0.1.0's tag message asserts
    that "the tag object ... is the root of trust" in prose and carries no
    block for anything to be rooted in.

    Asserted rather than left implicit because the alternative — a suite that
    exercises only the block-present path — would let `self_attested_only`
    read as a pass everywhere it appears.
    """
    _tag(topic["repo"], "v0.1.0", "release, prose only, no digest block")
    assert _verify(topic).digest_provenance == SELF_ATTESTED_ONLY

    assets = topic["assets"]
    tampered = (json.dumps(_declarations(contains_sorry_ax=True), indent=2)
                + "\n").encode()
    (assets / "declarations.json").write_bytes(tampered)
    bundle = json.loads((assets / "bundle.json").read_text())
    bundle["predicates"][0]["sha256"] = _sha(tampered)
    _write_bundle(assets, bundle)

    pin = _verify(topic)
    assert pin.digest_provenance == SELF_ATTESTED_ONLY
    assert any("no git-rooted digest" in f for f in pin.findings)


def test_an_uncoordinated_tamper_is_caught_either_way(topic) -> None:
    """Flipping the file WITHOUT recomputing the bundle is caught with no tag
    block at all — internal consistency does that much. It is the coordinated
    edit that needs an external root, which is why #174 specified one."""
    _tag(topic["repo"], "v0.1.0", "release, prose only")
    (topic["assets"] / "declarations.json").write_bytes(b'{"tampered": true}\n')
    with pytest.raises(PinError, match="the bundle claims"):
        _verify(topic)


# --- what the git tag object actually pins --------------------------------------

def test_the_pin_names_the_tag_object_not_only_the_commit(topic) -> None:
    """An annotated tag is its own object with its own sha, and that is what a
    re-tag changes. Recording only the commit would make a silently re-cut tag
    invisible."""
    _tag(topic["repo"], "v0.1.0", "release")
    tag = read_tag(topic["repo"], "v0.1.0")
    assert tag.is_annotated
    assert tag.object_sha != tag.commit_sha == topic["commit"]


def test_a_bundle_describing_another_commit_is_refused(topic) -> None:
    _tag(topic["repo"], "v0.1.0", "release")
    bundle = json.loads((topic["assets"] / "bundle.json").read_text())
    bundle["subject"][0]["digest"]["gitCommit"] = "f" * 40
    _write_bundle(topic["assets"], bundle)
    with pytest.raises(PinError, match="describe a different tree"):
        _verify(topic)


def test_a_bundle_built_before_its_tag_is_refused(topic) -> None:
    """`gitTag: null` is what an artifact set produced before the tag existed
    says — a valid artifact and an invalid release."""
    _tag(topic["repo"], "v0.1.0", "release")
    bundle = json.loads((topic["assets"] / "bundle.json").read_text())
    bundle["subject"][0]["digest"]["gitTag"] = None
    _write_bundle(topic["assets"], bundle)
    with pytest.raises(PinError, match="gitTag"):
        _verify(topic)


def test_a_registry_that_moved_since_the_tag_is_refused(topic) -> None:
    """The registry IS tracked, so this axis is git-rooted regardless of the
    tag message — and it is the artifact arXMCP actually re-serves."""
    _tag(topic["repo"], "v0.1.0", "release")
    bundle = json.loads((topic["assets"] / "bundle.json").read_text())
    bundle["registry_sha256"] = "d" * 64
    _write_bundle(topic["assets"], bundle)
    with pytest.raises(PinError, match="registry_sha256 disagrees"):
        _verify(topic)


def test_the_registry_is_read_from_git_not_from_the_worktree(topic) -> None:
    """A pin describes a tag. Reading the file off disk would let an
    uncommitted edit — or a later commit — into a record that claims to be
    v0.1.0."""
    _tag(topic["repo"], "v0.1.0", "release")
    moved = topic["repo"] / "registry" / "bridgeland2007.json"
    moved.write_text('{"schema_version": "registry/1.0"}\n', encoding="utf-8")
    _git(topic["repo"], "add", "-A")
    _git(topic["repo"], "commit", "-q", "-m", "the registry moves on")

    pin = _verify(topic)
    assert to_row(pin)["registry_sha256"] == topic["registry_sha256"]
    assert pin.registry_doc["registry_id"] == REGISTRY_ID


# --- the dirty worktree ---------------------------------------------------------

def test_a_dirty_worktree_is_refused(topic) -> None:
    """The producer's own `mfc seal` refuses one, for the reason the topic
    repo's .gitignore states: the subject attests a gitCommit, and uncommitted
    changes make every digest a true statement about a tree nobody can fetch."""
    _tag(topic["repo"], "v0.1.0", "release")
    (topic["repo"] / "stray.txt").write_text("uncommitted\n", encoding="utf-8")
    with pytest.raises(PinError, match="uncommitted change"):
        refuse_dirty_worktree(topic["repo"])
    with pytest.raises(PinError, match="uncommitted change"):
        _verify(topic)


def test_an_untracked_file_counts_as_dirty(topic) -> None:
    """`git status --porcelain` reports untracked files, and so must this:
    an untracked artifact is exactly how a stray build output gets pinned."""
    _tag(topic["repo"], "v0.1.0", "release")
    (topic["repo"] / "scratch.log").write_text("x\n", encoding="utf-8")
    with pytest.raises(PinError):
        refuse_dirty_worktree(topic["repo"])


# --- the digest block -----------------------------------------------------------

def test_an_absent_digest_block_is_no_digests_not_an_error() -> None:
    """Every tag in the world today is in this state."""
    assert parse_digest_block("just a release message") == {}


def test_a_malformed_digest_block_is_raised_not_degraded_to_absent() -> None:
    """A block that cannot be read is not the same fact as no block, and
    degrading one to the other would turn a typo into a silent downgrade from
    `git_rooted` to `self_attested_only`."""
    with pytest.raises(PinError, match="unparseable"):
        parse_digest_block(
            "-----BEGIN MFC DIGESTS-----\nattest/bundle.json deadbeef\n"
            "-----END MFC DIGESTS-----"
        )


def test_an_empty_digest_block_is_raised(topic) -> None:
    with pytest.raises(PinError, match="empty MFC DIGESTS block"):
        parse_digest_block(
            "-----BEGIN MFC DIGESTS-----\n\n-----END MFC DIGESTS-----")


def test_a_block_that_omits_the_bundle_roots_nothing(topic) -> None:
    """Every other digest in the set is READ OUT OF the bundle, so a block that
    names the leaves and not the root is a root of trust in name only."""
    assets = topic["assets"]
    block = ("-----BEGIN MFC DIGESTS-----\n"
             f"attest/declarations.json  "
             f"{_sha((assets / 'declarations.json').read_bytes())}\n"
             "-----END MFC DIGESTS-----")
    _tag(topic["repo"], "v0.1.0", "release\n\n" + block)
    with pytest.raises(PinError, match="does not name attest/bundle.json"):
        _verify(topic)


def test_a_predicate_the_block_omits_downgrades_rather_than_passing(topic) -> None:
    """Partial rooting is not rooting. The bundle's own digest agreeing with
    the file proves only that both were written together."""
    assets = topic["assets"]
    block = ("-----BEGIN MFC DIGESTS-----\n"
             f"attest/bundle.json  {_sha((assets / 'bundle.json').read_bytes())}\n"
             "-----END MFC DIGESTS-----")
    _tag(topic["repo"], "v0.1.0", "release\n\n" + block)
    pin = _verify(topic)
    assert pin.digest_provenance == SELF_ATTESTED_ONLY
    assert any("does not name it" in f for f in pin.findings)


# --- withdrawals travel forward in time ------------------------------------------

def _add_withdrawals(repo: Path, tag: str, *, registry_id: str = REGISTRY_ID) -> None:
    """Commit a withdrawals file and tag it LATER than everything present.

    `GIT_COMMITTER_DATE` moves the annotated tag's creatordate: git tags have
    one-second resolution, and a test that cut two tags in the same second
    would be asserting against whatever the tiebreak happened to do.
    """
    (repo / "attest").mkdir(exist_ok=True)
    (repo / "attest" / "withdrawals.yaml").write_text(
        f"schema_version: withdrawals/1.0\nregistry_id: {registry_id}\n"
        f"withdrawals:\n"
        f"  - key: stmt:{registry_id}:bridgeland2007.lem-8.2\n"
        f"    withdrawn_at: '2026-09-01'\n"
        f"    reason: the reviewer withdrew it\n",
        encoding="utf-8",
    )
    _git(repo, "add", "-f", "attest/withdrawals.yaml")
    _git(repo, "commit", "-q", "-m", "withdraw one entry")
    subprocess.run(
        ["git", "-C", str(repo), "tag", "-a", tag, "-m", "later release"],
        capture_output=True, text=True, check=True,
        env={**os.environ, "GIT_COMMITTER_DATE": "2030-01-01T00:00:00+0000"},
    )


def test_withdrawals_are_read_from_the_newest_tag_not_the_pinned_one(topic) -> None:
    """The single channel permitted to travel forward in time, and safe for
    exactly one reason: it can only REMOVE trust, never grant it.

    Without this, a v0.1.0 pin keeps serving a record that v0.2.0 marked
    inadequate, and nothing tells anyone.
    """
    pytest.importorskip("yaml")
    _tag(topic["repo"], "v0.1.0", "release")
    _add_withdrawals(topic["repo"], "v0.2.0")

    pin = _verify(topic)
    assert pin.tag.name == "v0.1.0"
    assert pin.withdrawals_tag == "v0.2.0"
    assert pin.withdrawals_doc["withdrawals"][0]["key"].endswith("lem-8.2")


def test_withdrawals_for_another_registry_are_refused(topic) -> None:
    """Applying them would remove trust from keys they were never about, and
    a revocation channel that fires on the wrong keys is worse than none."""
    pytest.importorskip("yaml")
    _tag(topic["repo"], "v0.1.0", "release")
    _add_withdrawals(topic["repo"], "v0.2.0", registry_id="ffffffffffff")
    with pytest.raises(PinError, match="were never about"):
        _verify(topic)


def test_no_withdrawals_file_is_a_legitimate_state(topic) -> None:
    """Most repositories have never withdrawn anything."""
    _tag(topic["repo"], "v0.1.0", "release")
    pin = _verify(topic)
    assert pin.withdrawals_doc is None
    assert pin.withdrawals_tag == "v0.1.0"


def test_the_newest_tag_is_by_creation_date_not_by_name(topic) -> None:
    """A version comparator would have to be taught this repo's tag grammar,
    and getting it wrong points the revocation channel at the WRONG tag — the
    one direction this channel must never fail in."""
    _tag(topic["repo"], "v0.1.0", "release")
    _add_withdrawals(topic["repo"], "v0.10.0")
    assert newest_tag(topic["repo"]) == "v0.10.0"


# --- the row, and the write ------------------------------------------------------

def test_the_stored_registry_is_the_bytes_from_git(topic) -> None:
    """Not a re-serialization. `registry_sha256` is computed over these bytes
    and the topic repo compares it against its own `shasum`, so a
    canonicalizing round-trip would make the served record disagree with the
    pin that vouches for it."""
    _tag(topic["repo"], "v0.1.0", "release")
    row = to_row(_verify(topic))
    assert _sha(row["registry_json"].encode()) == row["registry_sha256"]


def test_the_row_records_which_root_of_trust_the_pin_rests_on(topic) -> None:
    _tag(topic["repo"], "v0.1.0", "release")
    row = to_row(_verify(topic))
    assert row["digest_provenance"] == SELF_ATTESTED_ONLY
    assert row["tag_object_sha"] and row["commit_sha"] == topic["commit"]
    assert row["registry_id"] == REGISTRY_ID
    assert row["env_digest"] == ENV_DIGEST


def test_writing_a_pin_migrates_the_db_rather_than_arming_the_drop(
    topic, tmp_path: Path,
) -> None:
    """The hazard #174 names, asserted on the new writer as well as the old.

    A sync writer that opened a raw connection would leave `user_version` at 0
    with real rows in the file, and the server's v0->v1 block — guarded by
    `current_version < 1` and opening with an unconditional
    `DROP TABLE IF EXISTS notebooks` — would drop them at the next start.
    """
    import sqlite3

    from server.notebooks_store import SCHEMA_VERSION

    _tag(topic["repo"], "v0.1.0", "release")
    db = _notebook_db(tmp_path)
    write_pin(db, to_row(_verify(topic)))

    conn = sqlite3.connect(db)
    try:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
        rows = conn.execute(
            "SELECT slug, tag, digest_provenance FROM formal_releases"
        ).fetchall()
    finally:
        conn.close()
    assert rows == [("bridgeland-stability", "v0.1.0", SELF_ATTESTED_ONLY)]


def test_re_pinning_replaces_rather_than_accumulates(topic, tmp_path: Path) -> None:
    """Two pins for one (slug, repo) would be two answers to "what does this
    notebook serve", and the resource would have to choose — which is the
    operator's decision, expressed by which tag they pinned."""
    import sqlite3

    _tag(topic["repo"], "v0.1.0", "release")
    db = _notebook_db(tmp_path)
    row = to_row(_verify(topic))
    write_pin(db, row)
    write_pin(db, {**row, "tag": "v0.2.0"})

    conn = sqlite3.connect(db)
    try:
        assert conn.execute(
            "SELECT tag FROM formal_releases").fetchall() == [("v0.2.0",)]
    finally:
        conn.close()


def test_nothing_is_written_when_verification_refuses(topic, tmp_path: Path) -> None:
    """A partial pin is worse than no pin: the resource would serve a record
    whose verification never finished."""
    _tag(topic["repo"], "v0.1.0", "release")
    (topic["repo"] / "stray.txt").write_text("dirty\n", encoding="utf-8")
    db = tmp_path / "notebooks.db"
    with pytest.raises(PinError):
        _verify(topic)
    assert not db.exists()
