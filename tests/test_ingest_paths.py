"""Where ingest writes: every path follows ARXMCP_DATA_DIR, and a notebook's
run keeps its sentinel with the notebook."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

import ingest.bulk_ingest as bulk
from ingest import notebooks as _notebook_common
from ingest.bulk_ingest import PaperOutcome
from tools import notebook_ingest

REPO_ROOT = Path(__file__).resolve().parents[1]

_PROBE = """
import importlib, json, pkgutil
from pathlib import Path
import ingest

found = {}
for info in pkgutil.iter_modules(ingest.__path__):
    # The resolver's own globals (the startup directory) are its inputs.
    if info.name == "application_paths":
        continue
    module = importlib.import_module(f"ingest.{info.name}")
    for name, value in vars(module).items():
        if isinstance(value, Path) and not name.startswith("__"):
            found[f"{info.name}.{name}"] = str(value)
print(json.dumps(found))
"""


def _is_source_file(path: Path) -> bool:
    """A path that names code in the checkout (its root, the LaTeXML
    sandbox profile) rather than data, which lives under ``var/``."""
    resolved = path.resolve()
    source = REPO_ROOT.resolve()
    return (
        resolved.exists()
        and resolved.is_relative_to(source)
        and not resolved.is_relative_to(source / "var")
    )


def test_every_ingest_data_path_follows_the_data_dir(tmp_path):
    root = tmp_path / "data"
    env = {k: v for k, v in os.environ.items() if not k.startswith("ARXMCP_")}
    env["ARXMCP_DATA_DIR"] = str(root)

    result = subprocess.run(
        [sys.executable, "-c", _PROBE], cwd=tmp_path,
        env={**env, "PYTHONPATH": str(REPO_ROOT)},
        capture_output=True, text=True, timeout=300, check=False,
    )

    assert result.returncode == 0, result.stderr
    paths = json.loads(result.stdout.strip().splitlines()[-1])
    # The corpus trees, the datasets and the ops files are all there.
    for key in (
        "preamble.RAW_DIR", "preamble.PREAMBLE_DIR", "extract_equations.PARSED_DIR",
        "chunker.CHUNKS_DIR", "embedder.EMBEDDINGS_DIR", "store.DEFAULT_LANCEDB_PATH",
        "oai_delta.DEFAULT_STATE_PATH", "oai_delta.DEFAULT_OPS_DIR",
        "re_embed.DEFAULT_STATE_PATH", "bm25_indexer.BM25_STATS_PATH",
        "intra_paper_refs.DEFAULT_PARSED_DIR", "bulk_ingest.DEFAULT_OPS_DIR",
    ):
        assert key in paths
    outside = {
        key: value for key, value in paths.items()
        if not Path(value).resolve().is_relative_to(root.resolve())
        and not _is_source_file(Path(value))
    }
    assert outside == {}


def test_notebook_ingest_keeps_its_ingest_summary_with_the_notebook(
    tmp_path, monkeypatch
):
    base = tmp_path / "notebooks"
    nb = base / "demo"
    nb.mkdir(parents=True)
    (nb / "papers.txt").write_text("2303.07061\n", encoding="utf-8")
    monkeypatch.setattr(_notebook_common, "NOTEBOOKS_BASE", base)
    monkeypatch.setattr(
        bulk, "ingest_one_paper",
        lambda paper_id, **_kw: PaperOutcome(paper_id, failure_reason="no_parsed_html"),
    )
    shared = bulk.DEFAULT_OPS_DIR / "ingest-summary.json"
    shared_before = shared.read_bytes() if shared.is_file() else None

    assert notebook_ingest.run("demo") == 1

    summary = json.loads((nb / "ops" / "ingest-summary.json").read_text("utf-8"))
    assert summary["papers_processed"] == 1
    assert summary["papers_failed"] == 1
    assert (shared.read_bytes() if shared.is_file() else None) == shared_before


@pytest.fixture(autouse=True)
def _no_contact_email(monkeypatch):
    monkeypatch.delenv("ARXMCP_CONTACT_EMAIL", raising=False)
