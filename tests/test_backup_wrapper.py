"""Tests for the E11_S05 backup wrapper, systemd units, and
restic env template. No live restic — file-content assertions
and shell-wrapper hygiene."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


class TestResticEnvTemplate:
    template = REPO_ROOT / "ops" / "restic-env.sh.template"

    def test_template_exists(self):
        assert self.template.is_file()

    def test_template_declares_required_vars(self):
        text = self.template.read_text(encoding="utf-8")
        assert "RESTIC_REPOSITORY" in text
        assert "RESTIC_PASSWORD_FILE" in text
        # B2 backend env vars must at least be documented.
        assert "B2_ACCOUNT_ID" in text
        assert "B2_ACCOUNT_KEY" in text

    def test_template_guards_empty_repository(self):
        """Sourcing the template with RESTIC_REPOSITORY empty
        must refuse — the operator forgot to fill it in."""
        text = self.template.read_text(encoding="utf-8")
        assert "RESTIC_REPOSITORY is not set" in text

    def test_template_warns_about_password_loss(self):
        """The operator runbook leans on this contract: losing
        the restic password = permanent data loss. Surface
        the warning at the template level too."""
        text = self.template.read_text(encoding="utf-8")
        assert "PERMANENT DATA LOSS" in text or "password" in text.lower()


class TestBackupSystemdUnits:
    service = REPO_ROOT / "ops" / "systemd" / "arxmcp-backup.service"
    timer = REPO_ROOT / "ops" / "systemd" / "arxmcp-backup.timer"

    def test_units_exist(self):
        assert self.service.is_file()
        assert self.timer.is_file()

    def test_service_hardening(self):
        text = self.service.read_text(encoding="utf-8")
        # Mirrors E11_S02 arxmcp-delta.service hardening posture.
        assert "Type=oneshot" in text
        assert "ProtectSystem=strict" in text
        assert "ProtectHome=true" in text
        assert "NoNewPrivileges=true" in text
        assert "PrivateTmp=true" in text

    def test_service_timeout_4_hours(self):
        """135GB backup needs a defense-in-depth timeout above
        E11_S02's 7200s. Synthesis D5: 14400s = 4 hours."""
        text = self.service.read_text(encoding="utf-8")
        assert "TimeoutStartSec=14400" in text

    def test_timer_runs_at_0330(self):
        """Synthesis D5: backup fires 90 min after delta (02:00)."""
        text = self.timer.read_text(encoding="utf-8")
        assert "OnCalendar=*-*-* 03:30:00" in text
        assert "Persistent=true" in text

    def test_documentation_url(self):
        service_text = self.service.read_text(encoding="utf-8")
        timer_text = self.timer.read_text(encoding="utf-8")
        # Documentation= points at the canonical runbook URL,
        # not a /etc/arxmcp/ install-time path (E11_S04 IS3
        # lesson).
        assert "github.com" in service_text or "https://" in service_text
        assert "github.com" in timer_text or "https://" in timer_text


class TestBackupShellWrapper:
    wrapper = REPO_ROOT / "ops" / "cron" / "arxmcp-backup.sh"

    def test_wrapper_exists_and_executable(self):
        assert self.wrapper.is_file()
        assert os.access(self.wrapper, os.X_OK)

    def test_wrapper_set_euo_pipefail(self):
        text = self.wrapper.read_text(encoding="utf-8")
        assert "set -euo pipefail" in text

    def test_wrapper_guards_uv_flock_restic(self):
        """Synthesis D5: command -v guards for all three
        binary dependencies."""
        text = self.wrapper.read_text(encoding="utf-8")
        assert "command -v uv" in text
        assert "command -v flock" in text
        assert "command -v restic" in text

    def test_wrapper_no_hardcoded_user_path(self):
        """E11_S02 IS2 / E11_S04 lesson — no /Users/ paths."""
        text = self.wrapper.read_text(encoding="utf-8")
        assert "/Users/" not in text

    def test_wrapper_uses_flock(self):
        text = self.wrapper.read_text(encoding="utf-8")
        assert ".backup.lock" in text
        assert "flock -n" in text

    def test_wrapper_sources_restic_env(self):
        text = self.wrapper.read_text(encoding="utf-8")
        assert "ops/restic-env.sh" in text

    def test_wrapper_retention_policy(self):
        """Synthesis D5 / brief: 7 daily / 4 weekly / 12 monthly."""
        text = self.wrapper.read_text(encoding="utf-8")
        assert "--keep-daily 7" in text
        assert "--keep-weekly 4" in text
        assert "--keep-monthly 12" in text

    def test_wrapper_writes_sentinel(self):
        text = self.wrapper.read_text(encoding="utf-8")
        assert "backup-status.json" in text

    def test_wrapper_runs_forget_prune(self):
        text = self.wrapper.read_text(encoding="utf-8")
        assert "restic forget --prune" in text


class TestBackupWrapperSyntax:
    """notebook-ops-hardening-m1 regression guard.

    The backup body runs inside ``exec flock ... bash -euo pipefail -c
    '<body>'`` — a single-quoted string. A stray literal apostrophe inside
    the body (e.g. ``restic's``) prematurely closes that quote, so the
    whole script fails to parse and can never run. That bug shipped in
    E11_S05 and went undetected because every other test in this file only
    greps the script TEXT — none of them actually parse it. ``restic`` is
    not installed here, so it was never executed end-to-end either. These
    tests parse the script so the quote-balance class is caught going
    forward (the script is now materially more complex)."""

    wrapper = REPO_ROOT / "ops" / "cron" / "arxmcp-backup.sh"

    def test_wrapper_parses_under_bash_n(self):
        """bash -n must accept the whole script. An odd number of body
        apostrophes (the E11_S05 bug) makes bash report 'unexpected EOF
        while looking for matching'."""
        bash = shutil.which("bash")
        if bash is None:  # pragma: no cover - bash is always present here
            import pytest

            pytest.skip("bash not on PATH")
        result = subprocess.run(
            [bash, "-n", str(self.wrapper)],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, (
            f"arxmcp-backup.sh failed `bash -n`:\n{result.stderr}"
        )

    def test_body_single_quotes_balanced(self):
        """The bash -c '<body>' wrapper requires an EVEN number of
        apostrophes; an odd count means a stray literal apostrophe is
        breaking the body quote (belt-and-suspenders for bash -n)."""
        text = self.wrapper.read_text(encoding="utf-8")
        assert text.count("'") % 2 == 0, (
            "odd apostrophe count — a literal ' is breaking the "
            "single-quoted bash -c body"
        )


class TestNotebookBackupScope:
    """notebook-ops-hardening-m1: notebook data + metadata enter scope."""

    wrapper = REPO_ROOT / "ops" / "cron" / "arxmcp-backup.sh"

    def test_checkpoint_helper_exists(self):
        helper = REPO_ROOT / "ops" / "checkpoint_notebooks_db.py"
        assert helper.is_file()

    def test_manifest_uses_files_from_verbatim(self):
        text = self.wrapper.read_text(encoding="utf-8")
        assert "--files-from-verbatim -" in text
        # The manifest is piped from printf, not passed positionally.
        assert 'printf "%s\\n" "${BACKUP_PATHS[@]}"' in text

    def test_manifest_includes_notebook_paths(self):
        text = self.wrapper.read_text(encoding="utf-8")
        assert "/var/arxmcp/notebooks" in text
        assert "/var/arxmcp/cache/notebooks.db" in text

    def test_manifest_excludes_per_notebook_query_cache(self):
        text = self.wrapper.read_text(encoding="utf-8")
        assert '--exclude "*/cache/retrieval.db"' in text

    def test_wal_checkpoint_runs_before_backup(self):
        """The TRUNCATE checkpoint MUST precede the restic backup so the
        file-level copy of the WAL-mode notebooks.db is self-consistent."""
        text = self.wrapper.read_text(encoding="utf-8")
        ckpt = text.index("checkpoint_notebooks_db.py")
        # Anchor on the actual backup INVOCATION (printf | restic), not the
        # header-comment mention of --files-from-verbatim.
        backup = text.index('printf "%s\\n" "${BACKUP_PATHS[@]}"')
        assert ckpt < backup, (
            "WAL checkpoint must run before the restic backup"
        )

    def test_forget_uses_group_by_host(self):
        text = self.wrapper.read_text(encoding="utf-8")
        assert "--group-by host" in text

    def test_sentinel_paths_list_notebooks(self):
        """Both backup-status.json writes must list the new paths."""
        text = self.wrapper.read_text(encoding="utf-8")
        assert text.count("/var/arxmcp/notebooks\"") >= 2
        assert text.count("/var/arxmcp/cache/notebooks.db\"") >= 2


class TestGitignoreDiscipline:
    """Closes synthesis D12: ops/restic-env.sh (the FILLED
    instance) must be gitignored; only the .template is
    committed."""

    def test_restic_env_sh_is_gitignored(self):
        text = (REPO_ROOT / ".gitignore").read_text(encoding="utf-8")
        assert "ops/restic-env.sh" in text
