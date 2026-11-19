"""The server is a tool provider: no LLM SDK is imported anywhere in server/.

The model lives in the calling agent. An ``anthropic`` import under server/
would mean the server had started running agents itself.
"""

from __future__ import annotations

import re
from pathlib import Path

SERVER_DIR = Path(__file__).resolve().parents[1] / "server"
_SDK_IMPORT = re.compile(r"^\s*(from|import)\s+anthropic\b", re.MULTILINE)


def test_no_anthropic_import_in_server() -> None:
    offenders = [
        path.relative_to(SERVER_DIR.parent).as_posix()
        for path in sorted(SERVER_DIR.rglob("*.py"))
        if _SDK_IMPORT.search(path.read_text(encoding="utf-8"))
    ]
    assert offenders == [], f"server/ imports the anthropic SDK: {offenders}"
