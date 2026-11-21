"""The server starts without ``KMP_DUPLICATE_LIB_OK``, as it does in production.

``tests/conftest.py`` sets the flag for the in-process suite on macOS, where
faiss-cpu and PyTorch each bring an OpenMP runtime. No real server process
has it: not ``make up``, not the container, not the desktop child. So these
tests run in a child process whose environment has it removed, which is the
only way a reintroduced duplicate-OpenMP load can show up as a failure.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[1]
_KMP_KEY = "KMP_DUPLICATE_LIB_OK"

_BOOT = """
import sys
from pathlib import Path

from starlette.testclient import TestClient

from server.config import Config
from server.main import create_app

app = create_app(Config(data_dir=Path(sys.argv[1]), bootstrap_mode=True))
with TestClient(app) as client:
    healthz = client.get("/healthz").status_code
    readyz = client.get("/readyz").status_code
print(f"healthz={healthz} readyz={readyz}")
"""

_FAISS_THEN_TORCH = """
import faiss
import numpy as np
import torch

index = faiss.IndexFlatL2(16)
vectors = np.random.default_rng(0).random((64, 16), dtype=np.float32)
index.add(vectors)
_, neighbours = index.search(vectors[:4], 1)
torch.set_num_threads(4)
product = torch.rand(256, 256) @ torch.rand(256, 256)
print(f"neighbours={neighbours.ravel().tolist()} finite={bool(product.isfinite().all())}")
"""


def _run_without_flag(code: str, *args: str) -> subprocess.CompletedProcess[str]:
    env = {k: v for k, v in os.environ.items() if k != _KMP_KEY}
    env["PYTHONPATH"] = os.pathsep.join(
        p for p in (str(_REPO_ROOT), env.get("PYTHONPATH", "")) if p
    )
    return subprocess.run(  # noqa: S603
        [sys.executable, "-c", code, *args],
        cwd=_REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=180,
        check=False,
    )


def test_server_boots_and_answers_without_the_flag(tmp_path: Path) -> None:
    proc = _run_without_flag(_BOOT, str(tmp_path / "data"))
    assert proc.returncode == 0, proc.stderr[-3000:]
    assert "healthz=200 readyz=200" in proc.stdout, proc.stdout + proc.stderr[-3000:]


@pytest.mark.skipif(
    sys.platform == "darwin",
    reason="a macOS venv carries one OpenMP runtime per wheel, the case "
    "tests/conftest.py sets the flag for; the packaged desktop build is "
    "checked for a single runtime by its own gate",
)
def test_faiss_and_torch_share_a_process_without_the_flag() -> None:
    proc = _run_without_flag(_FAISS_THEN_TORCH)
    assert proc.returncode == 0, proc.stderr[-3000:]
    assert "neighbours=[0, 1, 2, 3] finite=True" in proc.stdout, proc.stdout
