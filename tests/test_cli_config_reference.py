"""``arxmcp-server --list-config`` and the config errors that point at it."""

from __future__ import annotations

import pytest

from arxmcp.server.cli import _format_config_error, config_reference, main
from arxmcp.server.config import CONFIG_REFERENCE_HINT, Config


def _blocks() -> dict[str, list[str]]:
    blocks: dict[str, list[str]] = {}
    for block in config_reference().strip().split("\n\n"):
        head, *body = block.split("\n")
        blocks[head.split()[0]] = body
    return blocks


def test_list_config_prints_every_setting_and_exits_zero(capsys) -> None:
    assert main(["--list-config"]) == 0
    out = capsys.readouterr().out
    for name in Config.model_fields:
        assert f"ARXMCP_{name.upper()}  (" in out


def test_every_setting_carries_a_description() -> None:
    blocks = _blocks()
    assert set(blocks) == {f"ARXMCP_{n.upper()}" for n in Config.model_fields}
    undescribed = sorted(
        env
        for env, body in blocks.items()
        if not body or body == ["    (no description)"]
    )
    assert undescribed == []


def test_listing_shows_scalar_defaults_and_hides_path_spellings() -> None:
    out = config_reference()
    assert "ARXMCP_BIND_PORT  (int; default 7733)" in out
    assert "ARXMCP_ENABLE_RERANK  (bool; default false)" in out
    assert "ARXMCP_NOTEBOOK  (str | None; default unset)" in out
    assert "ARXMCP_LANCEDB_PATH  (Path; default under the data root)" in out
    assert "var/arxmcp" not in out


def test_validation_error_names_the_variable_and_the_listing(monkeypatch) -> None:
    from pydantic import ValidationError

    monkeypatch.setenv("ARXMCP_BIND_PORT", "not-a-port")
    with pytest.raises(ValidationError) as exc_info:
        Config()
    message = _format_config_error(exc_info.value)
    assert message.startswith("ARXMCP_BIND_PORT: ")
    assert message.endswith(CONFIG_REFERENCE_HINT)
    assert "not-a-port" not in message


def test_unknown_variable_error_points_at_the_listing(monkeypatch) -> None:
    from arxmcp.server.main import _scan_unknown_arxmcp_env_vars

    monkeypatch.setenv("ARXMCP_BIND_HOSTT", "127.0.0.1")
    with pytest.raises(ValueError) as exc_info:
        _scan_unknown_arxmcp_env_vars(Config())
    assert str(exc_info.value).endswith(CONFIG_REFERENCE_HINT)
