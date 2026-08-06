"""Canonical runtime-path contract for source, installed, and container use."""

from __future__ import annotations

import os
import sys
import tempfile
import warnings
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

ApplicationMode = Literal["source", "installed", "container"]
COMPATIBILITY_ALIAS_FIELDS = (
    ("ARXMCP_LANCEDB_PATH", "lancedb"),
    ("ARXMCP_KUZU_PATH", "kuzu"),
    ("ARXMCP_CACHE_DB_PATH", "retrieval_cache_db"),
    ("ARXMCP_BM25_INDEX_ROOT", "bm25"),
    ("ARXMCP_THEOREM_NAMES_DB_PATH", "theorem_names_db"),
    ("ARXMCP_NOTEBOOKS_DB_PATH", "notebooks_db"),
    ("ARXMCP_OPS_DIR", "ops"),
)
_LAYOUT = (
    ("corpus", "corpus"), ("index", "index"),
    ("lancedb", "index/lancedb"), ("kuzu", "index/kuzu"),
    ("bm25", "index/bm25"), ("sqlite", "index/sqlite"),
    ("theorem_names_db", "index/sqlite/theorem_names.db"),
    ("notebooks", "notebooks"), ("cache", "cache"),
    ("retrieval_cache_db", "cache/retrieval.db"),
    ("notebooks_db", "cache/notebooks.db"), ("ops", "ops"),
    ("logs", "logs"), ("backups", "backups"), ("tmp", "tmp"),
)
_STARTUP_CWD = Path.cwd().resolve()


class ApplicationPathError(ValueError):
    """A configured application path is invalid or escapes its root."""


def legacy_source_path(name: str) -> Path:
    """Return the historical checkout-relative spelling for a layout key."""
    suffixes = dict(_LAYOUT)
    if name == "root":
        return Path("var/arxmcp")
    try:
        return Path("var/arxmcp") / suffixes[name]
    except KeyError as exc:
        raise ApplicationPathError(f"unknown application path: {name}") from exc


def _canonical(path: Path, label: str) -> Path:
    try:
        return path.resolve(strict=False)
    except (OSError, RuntimeError) as exc:
        raise ApplicationPathError(f"{label} cannot be resolved: {path}") from exc


def _inside(root: Path, path: Path, label: str) -> Path:
    resolved = _canonical(path, label)
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise ApplicationPathError(
            f"{label} escapes ARXMCP_DATA_DIR: {resolved}"
        ) from exc
    return resolved


def _source_checkout_root() -> Path | None:
    root = Path(__file__).resolve().parents[1]
    source_module_dir = Path(__file__).resolve().parent
    if (
        (root / "pyproject.toml").is_file()
        and (root / "server").resolve() == source_module_dir
    ):
        return root
    return None


def _platform_data_root(env: Mapping[str, str]) -> Path:
    home = Path(env.get("USERPROFILE") or env.get("HOME") or Path.home())
    if sys.platform == "win32":
        base = Path(env.get("LOCALAPPDATA") or home / "AppData" / "Local")
    elif sys.platform == "darwin":
        base = home / "Library" / "Application Support"
    else:
        base = Path(env.get("XDG_DATA_HOME") or home / ".local" / "share")
    return base / "arXMCP"


@dataclass(frozen=True, slots=True)
class ApplicationPaths:
    """One resolved, immutable view of all first-party mutable state."""

    mode: ApplicationMode
    root: Path
    corpus: Path
    index: Path
    lancedb: Path
    kuzu: Path
    bm25: Path
    sqlite: Path
    theorem_names_db: Path
    notebooks: Path
    cache: Path
    retrieval_cache_db: Path
    notebooks_db: Path
    ops: Path
    logs: Path
    backups: Path
    tmp: Path
    legacy_external_aliases: tuple[str, ...] = ()

    @classmethod
    def resolve(
        cls, *, environ: Mapping[str, str] | None = None,
        mode: ApplicationMode | None = None, root: str | Path | None = None,
        aliases: Mapping[str, str | Path] | None = None,
        startup_cwd: Path | None = None, source_root: Path | None = None,
        platform_default: Callable[[], Path] | None = None,
    ) -> ApplicationPaths:
        env = os.environ if environ is None else environ
        detected_source = source_root or _source_checkout_root()
        selected = mode or ("source" if detected_source else "installed")
        raw_root = root if root is not None else env.get("ARXMCP_DATA_DIR")
        cwd = _canonical(startup_cwd or _STARTUP_CWD, "startup cwd")
        if raw_root:
            candidate = Path(raw_root)
            if ".." in candidate.parts:
                raise ApplicationPathError("ARXMCP_DATA_DIR must not contain '..'")
            if not candidate.is_absolute():
                if selected != "source":
                    raise ApplicationPathError("ARXMCP_DATA_DIR must be absolute")
                warnings.warn(
                    "relative ARXMCP_DATA_DIR is source-only and deprecated",
                    DeprecationWarning, stacklevel=2,
                )
                candidate = cwd / candidate
        elif selected == "source" and detected_source is not None:
            candidate = detected_source / "var" / "arxmcp"
        elif selected == "installed":
            candidate = (platform_default or (lambda: _platform_data_root(env)))()
        else:
            raise ApplicationPathError(
                "container mode requires an explicit absolute ARXMCP_DATA_DIR"
            )
        if not candidate.is_absolute():
            raise ApplicationPathError("resolved application root must be absolute")
        canonical_root = _canonical(candidate, "ARXMCP_DATA_DIR")
        supplied = {key: env[key] for key, _ in COMPATIBILITY_ALIAS_FIELDS if env.get(key)}
        supplied.update(aliases or {})
        alias_by_field = {field: key for key, field in COMPATIBILITY_ALIAS_FIELDS}
        values: dict[str, Path] = {}
        legacy: list[str] = []
        for field, suffix in _LAYOUT:
            alias = alias_by_field.get(field)
            raw = supplied.get(alias) if alias else None
            path = canonical_root / suffix
            if raw:
                path = Path(raw)
                if ".." in path.parts:
                    raise ApplicationPathError(f"{alias} must not contain '..'")
                if not path.is_absolute():
                    path = (cwd if selected == "source" else canonical_root) / path
                resolved = _canonical(path, alias or field)
                try:
                    resolved.relative_to(canonical_root)
                except ValueError as exc:
                    if selected != "source":
                        raise ApplicationPathError(
                            f"{alias} escapes ARXMCP_DATA_DIR: {resolved}"
                        ) from exc
                    legacy.append(alias or field)
                values[field] = resolved
            else:
                values[field] = _inside(canonical_root, path, field)
        return cls(
            selected,
            canonical_root,
            **values,
            legacy_external_aliases=tuple(sorted(legacy)),
        )

    def prepare(self) -> None:
        """Create the tree and prove temporary state is writable using EAFP."""
        directories = (self.root, self.corpus, self.index, self.lancedb,
                       self.kuzu, self.bm25, self.sqlite, self.notebooks,
                       self.cache, self.ops, self.logs, self.backups, self.tmp)
        for path in directories:
            path.mkdir(parents=True, exist_ok=True)
        fd, marker = tempfile.mkstemp(prefix=".arxmcp-write-probe-", dir=self.tmp)
        os.close(fd)
        Path(marker).unlink()


__all__ = ["ApplicationMode", "ApplicationPathError", "ApplicationPaths",
           "COMPATIBILITY_ALIAS_FIELDS", "legacy_source_path"]
