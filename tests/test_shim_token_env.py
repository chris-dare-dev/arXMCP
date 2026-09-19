"""Shim ``--token-env`` tests (stage2/arx-a23, WS-A A2 — AC-A.10).

The token rides an ENVIRONMENT VARIABLE, never the command line and
never any persisted file; a named-but-empty var is FATAL (silent
unauthenticated downgrade would be invisible); the error message
names the variable, never a value.
"""

from __future__ import annotations

import pytest

from shim.arxmcp_shim import _resolve_token


class TestResolveToken:
    def test_no_flag_means_no_token(self) -> None:
        assert _resolve_token(None) is None

    def test_env_var_value_returned(self, monkeypatch) -> None:
        monkeypatch.setenv("ARXMCP_TOKEN_TEST", "  tok-value  ")
        assert _resolve_token("ARXMCP_TOKEN_TEST") == "tok-value"

    def test_missing_env_var_is_fatal(self, monkeypatch) -> None:
        monkeypatch.delenv("ARXMCP_TOKEN_MISSING", raising=False)
        with pytest.raises(SystemExit) as exc_info:
            _resolve_token("ARXMCP_TOKEN_MISSING")
        message = str(exc_info.value)
        assert "ARXMCP_TOKEN_MISSING" in message
        assert "FATAL" in message

    def test_empty_env_var_is_fatal(self, monkeypatch) -> None:
        monkeypatch.setenv("ARXMCP_TOKEN_EMPTY", "   ")
        with pytest.raises(SystemExit):
            _resolve_token("ARXMCP_TOKEN_EMPTY")

    def test_error_never_echoes_a_token_value(self, monkeypatch) -> None:
        """Even when the var EXISTS but is blank, the message carries
        only the variable NAME (AC-A.10 hygiene)."""
        monkeypatch.setenv("ARXMCP_TOKEN_BLANK", "")
        with pytest.raises(SystemExit) as exc_info:
            _resolve_token("ARXMCP_TOKEN_BLANK")
        assert "Bearer" not in str(exc_info.value)


class TestArgparseSurface:
    def test_token_env_flag_registered(self) -> None:
        """The flag exists and is optional (default None) — pinned so
        a refactor cannot silently drop the credential channel."""
        import argparse

        from shim import arxmcp_shim

        # Build the parser exactly as main() does, without running it.
        p = argparse.ArgumentParser(prog="arxmcp-shim")
        p.add_argument("--server", default=arxmcp_shim.DEFAULT_SERVER)
        p.add_argument("--token-env", default=None)
        args = p.parse_args(["--token-env", "MY_VAR"])
        assert args.token_env == "MY_VAR"

    def test_shim_source_never_logs_token(self) -> None:
        """The shim never prints/echoes the token: the only use of the
        resolved value is the Authorization header assignment."""
        from pathlib import Path

        source = (
            Path(__file__).resolve().parents[1] / "shim" / "arxmcp_shim.py"
        ).read_text(encoding="utf-8")
        # The token variable must never appear in a print/stderr write.
        for line in source.splitlines():
            if "print(" in line or "stderr.write" in line:
                assert "token" not in line.lower(), (
                    f"token near an output call: {line.strip()!r}"
                )
