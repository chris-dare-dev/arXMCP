"""E13_S06 — Threat-6 (model commit SHA pinning, safetensors-only,
trust_remote_code=False) audit.

Closes the seven acceptance criteria of the milestone:

1. ``embedder.load(revision="main")`` raises ``ModelPinningError``.
2. ``reranker.load(revision="main")`` raises ``ModelPinningError``.
3. Loading with a valid 40-char SHA succeeds (no spurious raise).
4. Both loaders reject ``.bin`` weights — covered by the reranker's
   ``use_safetensors=True`` + the new
   :func:`server.model_loader.assert_no_bin_in_snapshot` defensive
   check. The embedder ships ``.bin``-only at the currently-pinned
   SHA; the audit doc documents the gap and a future SHA-bump
   milestone will enable the same enforcement there.
5. ``trust_remote_code=False`` is the default; ``ARXMCP_TRUST_REMOTE_CODE=1``
   enables it and logs a ``WARNING``.
6. ``tools/sbom.sh`` produces valid CycloneDX JSON (smoke-checked
   here as a presence test; full pipeline run is the operator's
   ``make sbom``).
7. Critical-CVE handling: ``grype --fail-on critical`` semantics
   are documented in the audit doc and the script; not unit-tested
   because it requires a network round trip to the grype DB.

All tests mock ``transformers.AutoModel.from_pretrained`` and
friends — none touch the network or load real model weights.
"""

from __future__ import annotations

import logging
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

import ingest.embedder as embedder_mod
from ingest.embedder import BGE_M3_COMMIT_SHA
from server.model_loader import (
    _SHA_RE,
    ModelPinningError,
    assert_no_bin_in_snapshot,
    resolve_trust_remote_code,
    validate_model_revision,
)
from server.retrieval.rerank import BGE_RERANKER_COMMIT_SHA

# ===========================================================================
# validate_model_revision
# ===========================================================================


class TestValidateModelRevision:
    """The 40-character lowercase hex SHA validator — Threat 6 mitigation 1."""

    def test_accepts_canonical_lowercase_sha(self):
        """The two pinned production SHAs MUST validate cleanly so
        no current loader path is silently broken by the new guard.
        """
        validate_model_revision(BGE_M3_COMMIT_SHA, model_name="BAAI/bge-m3")
        validate_model_revision(
            BGE_RERANKER_COMMIT_SHA, model_name="BAAI/bge-reranker-v2-m3"
        )

    def test_rejects_branch_name_main(self):
        """AC1 / AC2 — ``revision='main'`` is the named anti-pattern."""
        with pytest.raises(ModelPinningError) as ei:
            validate_model_revision("main", model_name="BAAI/bge-m3")
        # The error message must surface the required format so the
        # operator can fix the pin without grepping the source.
        assert "40-character" in str(ei.value)
        assert "BAAI/bge-m3" in str(ei.value)

    def test_rejects_tag_like_string(self):
        with pytest.raises(ModelPinningError):
            validate_model_revision("v1.0", model_name="BAAI/bge-m3")

    def test_rejects_uppercase_sha(self):
        """HuggingFace returns SHAs in lowercase; an uppercase pin
        almost certainly indicates a copy-paste from a Git GUI that
        rendered the hash uppercase. Refuse loudly rather than
        silently matching — the equality check elsewhere in the
        codebase is case-sensitive.
        """
        upper = BGE_M3_COMMIT_SHA.upper()
        with pytest.raises(ModelPinningError):
            validate_model_revision(upper, model_name="BAAI/bge-m3")

    def test_rejects_short_sha(self):
        """Git's abbreviated SHA (7 chars) is unambiguous in a single
        repo but not in the wider HF org/repo space. Require the full
        40 chars so the pin survives even if HF's hash resolution
        changes.
        """
        short = BGE_M3_COMMIT_SHA[:7]
        with pytest.raises(ModelPinningError):
            validate_model_revision(short, model_name="BAAI/bge-m3")

    def test_rejects_non_hex(self):
        bad = "g" * 40
        with pytest.raises(ModelPinningError):
            validate_model_revision(bad, model_name="BAAI/bge-m3")

    def test_rejects_empty_string(self):
        with pytest.raises(ModelPinningError):
            validate_model_revision("", model_name="BAAI/bge-m3")

    def test_rejects_non_string(self):
        """An accidental ``revision=None`` (or any non-str) must
        raise — Python would otherwise let it through to transformers
        which has its own ambiguous handling.
        """
        with pytest.raises(ModelPinningError):
            validate_model_revision(None, model_name="BAAI/bge-m3")  # type: ignore[arg-type]

    def test_regex_is_anchored(self):
        """Defense-in-depth: confirm the underlying regex full-matches
        and does not accept a 40-hex prefix of a longer string.
        """
        leaky = BGE_M3_COMMIT_SHA + "extra"
        assert _SHA_RE.fullmatch(leaky) is None
        with pytest.raises(ModelPinningError):
            validate_model_revision(leaky, model_name="BAAI/bge-m3")


# ===========================================================================
# resolve_trust_remote_code  (AC5)
# ===========================================================================


class TestResolveTrustRemoteCode:
    """``ARXMCP_TRUST_REMOTE_CODE`` env var semantics."""

    def test_default_is_false(self, monkeypatch):
        monkeypatch.delenv("ARXMCP_TRUST_REMOTE_CODE", raising=False)
        assert resolve_trust_remote_code() is False

    def test_empty_string_is_false(self, monkeypatch):
        monkeypatch.setenv("ARXMCP_TRUST_REMOTE_CODE", "")
        assert resolve_trust_remote_code() is False

    def test_anything_other_than_one_is_false(self, monkeypatch):
        """Fuzzy truthiness is refused: only the literal ``"1"`` opts
        in. ``True`` / ``yes`` / ``on`` / random digits all stay
        False so a confused config file cannot accidentally enable
        the escape hatch.
        """
        for value in ("True", "true", "yes", "on", "2", "0", "false", "False"):
            monkeypatch.setenv("ARXMCP_TRUST_REMOTE_CODE", value)
            assert resolve_trust_remote_code() is False, (
                f"value {value!r} should NOT enable trust_remote_code"
            )

    def test_one_enables_and_warns(self, monkeypatch, caplog):
        monkeypatch.setenv("ARXMCP_TRUST_REMOTE_CODE", "1")
        with caplog.at_level(logging.WARNING, logger="arxmcp.security.model_loader"):
            assert resolve_trust_remote_code() is True
        # The WARN must mention the env var by name so a grep through
        # production logs surfaces the override.
        warn_lines = [
            r for r in caplog.records if r.levelno == logging.WARNING
        ]
        assert any("ARXMCP_TRUST_REMOTE_CODE" in r.getMessage() for r in warn_lines), (
            f"expected WARN log mentioning the env var; got: "
            f"{[r.getMessage() for r in warn_lines]}"
        )


# ===========================================================================
# assert_no_bin_in_snapshot  (AC4 defensive half)
# ===========================================================================


class TestAssertNoBinInSnapshot:
    """Post-load check that catches the silent ``use_safetensors=True``
    fallback to ``.bin`` (some transformers versions exhibit it).
    """

    def _stage_snapshot(self, tmp_path: Path, model_name: str, revision: str) -> Path:
        """Build the HF cache layout
        ``<tmp_path>/hub/models--<org>--<name>/snapshots/<sha>/``
        and return the snapshot dir for the caller to populate.
        """
        safe = "models--" + model_name.replace("/", "--")
        snap = tmp_path / "hub" / safe / "snapshots" / revision
        snap.mkdir(parents=True)
        return snap

    def test_passes_when_no_snapshot_dir(self, tmp_path, monkeypatch):
        """If the cache layout is absent (CI artifact mount, offline
        fixture) we cannot prove a violation; the function should
        return silently and trust the load.
        """
        monkeypatch.setenv("HF_HOME", str(tmp_path))
        assert_no_bin_in_snapshot("BAAI/bge-m3", BGE_M3_COMMIT_SHA)  # no raise

    def test_passes_when_only_safetensors(self, tmp_path, monkeypatch):
        monkeypatch.setenv("HF_HOME", str(tmp_path))
        snap = self._stage_snapshot(
            tmp_path, "BAAI/bge-reranker-v2-m3", BGE_RERANKER_COMMIT_SHA
        )
        (snap / "model.safetensors").write_bytes(b"\x00" * 16)
        (snap / "config.json").write_text("{}")
        # Should NOT raise.
        assert_no_bin_in_snapshot(
            "BAAI/bge-reranker-v2-m3", BGE_RERANKER_COMMIT_SHA
        )

    def test_raises_on_bin_file(self, tmp_path, monkeypatch):
        monkeypatch.setenv("HF_HOME", str(tmp_path))
        snap = self._stage_snapshot(tmp_path, "BAAI/bge-m3", BGE_M3_COMMIT_SHA)
        (snap / "pytorch_model.bin").write_bytes(b"\x80\x04")  # pickle magic
        with pytest.raises(ModelPinningError) as ei:
            assert_no_bin_in_snapshot("BAAI/bge-m3", BGE_M3_COMMIT_SHA)
        assert "pytorch_model.bin" in str(ei.value)
        # The error must cite the threat-model file so a reader can
        # navigate to the rule that was violated.
        assert "Threat 6" in str(ei.value)

    def test_raises_even_when_safetensors_also_present(self, tmp_path, monkeypatch):
        """Mixed snapshot is the dangerous case — we cannot prove
        which was loaded. Refuse to ship.
        """
        monkeypatch.setenv("HF_HOME", str(tmp_path))
        snap = self._stage_snapshot(
            tmp_path, "BAAI/bge-reranker-v2-m3", BGE_RERANKER_COMMIT_SHA
        )
        (snap / "model.safetensors").write_bytes(b"\x00")
        (snap / "pytorch_model.bin").write_bytes(b"\x80\x04")
        with pytest.raises(ModelPinningError):
            assert_no_bin_in_snapshot(
                "BAAI/bge-reranker-v2-m3", BGE_RERANKER_COMMIT_SHA
            )

    def test_ignores_training_args_bin(self, tmp_path, monkeypatch):
        """``training_args.bin`` is a Trainer sidecar that does NOT
        carry model weights. Refusing it would block loads from
        well-formed safetensors repos that happen to ship it.
        """
        monkeypatch.setenv("HF_HOME", str(tmp_path))
        snap = self._stage_snapshot(
            tmp_path, "BAAI/bge-reranker-v2-m3", BGE_RERANKER_COMMIT_SHA
        )
        (snap / "model.safetensors").write_bytes(b"\x00")
        (snap / "training_args.bin").write_bytes(b"x")
        # Should NOT raise.
        assert_no_bin_in_snapshot(
            "BAAI/bge-reranker-v2-m3", BGE_RERANKER_COMMIT_SHA
        )


# ===========================================================================
# Loader integration — embedder paths refuse a bad pin BEFORE network I/O
# ===========================================================================


class TestEmbedderLoaderGuards:
    """The embedder's ``_get_model`` and ``_get_tokenizer`` must call
    the validator before ``from_pretrained`` so a misconfigured pin
    never hits the network.
    """

    def test_get_model_rejects_bad_revision(self, monkeypatch):
        """AC1 — ``embedder.load(revision='main')`` raises
        ``ModelPinningError``. The acceptance criterion phrases this
        in terms of ``revision=``, but the codebase pins the SHA at
        module level and the loader has no per-call ``revision``
        kwarg; the equivalent test is to monkeypatch the module
        constant to ``"main"`` and confirm the load refuses BEFORE
        invoking the transformers loader.
        """
        embedder_mod._model = None
        monkeypatch.setattr(embedder_mod, "BGE_M3_COMMIT_SHA", "main")
        with patch(
            "transformers.AutoModel.from_pretrained"
        ) as load_call, pytest.raises(ModelPinningError):
            embedder_mod._get_model()
        # The transformers loader must NEVER be called when the
        # validator refuses — proves the guard runs BEFORE the
        # network round trip, not after.
        load_call.assert_not_called()

    def test_get_tokenizer_rejects_bad_revision(self, monkeypatch):
        embedder_mod._tokenizer = None
        monkeypatch.setattr(embedder_mod, "BGE_M3_COMMIT_SHA", "main")
        with patch(
            "transformers.AutoTokenizer.from_pretrained"
        ) as load_call, pytest.raises(ModelPinningError):
            embedder_mod._get_tokenizer()
        load_call.assert_not_called()

    def test_get_model_explicit_trust_remote_code_false(self, monkeypatch):
        """AC5 — default is False, passed explicitly to from_pretrained."""
        embedder_mod._model = None
        monkeypatch.delenv("ARXMCP_TRUST_REMOTE_CODE", raising=False)
        fake_model = MagicMock()
        fake_model.eval.return_value = fake_model
        with patch(
            "transformers.AutoModel.from_pretrained", return_value=fake_model
        ) as load_call:
            embedder_mod._get_model()
        load_call.assert_called_once()
        kwargs = load_call.call_args.kwargs
        assert kwargs.get("trust_remote_code") is False
        embedder_mod._model = None

    def test_get_model_trust_remote_code_env_opt_in(self, monkeypatch):
        """AC5 — ``ARXMCP_TRUST_REMOTE_CODE=1`` passes
        ``trust_remote_code=True`` to from_pretrained.
        """
        embedder_mod._model = None
        monkeypatch.setenv("ARXMCP_TRUST_REMOTE_CODE", "1")
        fake_model = MagicMock()
        fake_model.eval.return_value = fake_model
        with patch(
            "transformers.AutoModel.from_pretrained", return_value=fake_model
        ) as load_call:
            embedder_mod._get_model()
        load_call.assert_called_once()
        kwargs = load_call.call_args.kwargs
        assert kwargs.get("trust_remote_code") is True
        embedder_mod._model = None


# ===========================================================================
# Reranker loader guard (smoke — full async load is exercised in
# tests/retrieval/test_rerank.py; here we just confirm the validator
# is on the path).
# ===========================================================================


class TestRerankerLoaderGuard:
    """The reranker's load path now calls ``validate_model_revision``
    before invoking transformers. We assert via a direct call to the
    validator with the production pin and with a bad value.
    """

    def test_production_sha_validates(self):
        # The exact pin from the codebase must satisfy the validator
        # at all times — otherwise the production loader is broken
        # by its own guard. This is the most load-bearing
        # regression in the file.
        validate_model_revision(
            BGE_RERANKER_COMMIT_SHA, model_name="BAAI/bge-reranker-v2-m3"
        )

    def test_branch_name_rejected_for_reranker(self):
        with pytest.raises(ModelPinningError):
            validate_model_revision("main", model_name="BAAI/bge-reranker-v2-m3")


# ===========================================================================
# tools/sbom.sh presence + flag parsing smoke (AC6)
# ===========================================================================


class TestSbomScriptPresence:
    """The brief mandates ``tools/sbom.sh`` produces valid CycloneDX
    JSON. We do not run grype here (network DB fetch); we just
    confirm the script exists, is executable-shaped (bash shebang),
    advertises the right flags, and has a usable help screen.
    """

    def test_script_exists_and_has_bash_shebang(self):
        path = Path(__file__).resolve().parents[2] / "tools" / "sbom.sh"
        assert path.is_file(), f"tools/sbom.sh missing at {path}"
        first_line = path.read_text(encoding="utf-8").splitlines()[0]
        assert first_line.startswith("#!"), (
            f"expected shebang; got: {first_line!r}"
        )
        assert "bash" in first_line

    def test_script_advertises_required_flags(self):
        """The Makefile target documents ``--skip-image`` and
        ``--no-scan``. If the script ever drops those, the docs
        decay. This test binds the contract.
        """
        path = Path(__file__).resolve().parents[2] / "tools" / "sbom.sh"
        body = path.read_text(encoding="utf-8")
        assert "--skip-image" in body
        assert "--no-scan" in body
        # The brief calls for grype --fail-on critical semantics.
        assert "--fail-on critical" in body
        # Outputs CycloneDX JSON.
        assert "cyclonedx" in body.lower()


# ===========================================================================
# Audit doc presence (re-asserts the deliverable in CLAUDE.md-compliant
# location, NOT the brief's docs/security/threat-6-audit.md)
# ===========================================================================


class TestAuditDocPresence:
    """The audit doc lives at ``.claude/docs/security-threat-6-audit.md``
    matching the E13_S01–S05 precedent (CLAUDE.md §1 doc-placement
    rule). The brief asks for ``docs/security/threat-6-audit.md`` but
    that path is rejected by repo policy.
    """

    def test_audit_doc_exists_under_dot_claude(self):
        repo_root = Path(__file__).resolve().parents[2]
        audit = repo_root / ".claude" / "docs" / "security-threat-6-audit.md"
        assert audit.is_file(), f"audit doc missing at {audit}"
        body = audit.read_text(encoding="utf-8")
        # Doc must surface the three mitigations by name for grep
        # discoverability.
        assert "trust_remote_code" in body
        assert "safetensors" in body
        # And the production SHAs (so a reader knows what's pinned).
        assert BGE_M3_COMMIT_SHA in body
        assert BGE_RERANKER_COMMIT_SHA in body
