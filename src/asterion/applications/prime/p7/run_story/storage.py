"""Safe immutable publication for generated ARC run-story artifacts."""

from __future__ import annotations

import json
import os
import re
import tempfile
from hashlib import sha256
from pathlib import Path

from .model import RunStoryError, SCHEMA, canonical_json


_SAFE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}\Z")


def safe_id(value: str) -> str:
    if type(value) is not str or _SAFE_ID.fullmatch(value) is None:
        raise RunStoryError("artifact-invalid")
    return value


def digest_bytes(value: bytes) -> str:
    return "sha256:" + sha256(value).hexdigest()


def _ensure_directory(path: Path) -> None:
    missing: list[Path] = []
    cursor = path
    while not cursor.exists():
        missing.append(cursor)
        cursor = cursor.parent
    if cursor.is_symlink() or not cursor.is_dir():
        raise RunStoryError("artifact-invalid")
    for item in reversed(missing):
        item.mkdir(mode=0o750)
    cursor = path
    while True:
        if cursor.is_symlink() or not cursor.is_dir():
            raise RunStoryError("artifact-invalid")
        if cursor == path.anchor or cursor.parent == cursor:
            break
        cursor = cursor.parent
        if cursor.exists() and cursor.parent == cursor:
            break


def _write_file(path: Path, value: bytes) -> None:
    path.parent.mkdir(mode=0o750, parents=True, exist_ok=True)
    if path.parent.is_symlink():
        raise RunStoryError("artifact-invalid")
    descriptor = os.open(
        path,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
        0o640,
    )
    try:
        with os.fdopen(descriptor, "wb", closefd=False) as handle:
            handle.write(value)
            handle.flush()
            os.fsync(handle.fileno())
    finally:
        os.close(descriptor)


def publish_directory(destination: Path, files: dict[str, bytes]) -> Path:
    if destination.is_symlink():
        raise RunStoryError("artifact-conflict")
    _ensure_directory(destination.parent)
    if destination.exists():
        for name, value in files.items():
            path = destination / name
            if path.is_symlink() or not path.is_file() or path.read_bytes() != value:
                raise RunStoryError("artifact-conflict")
        return destination
    stage = Path(tempfile.mkdtemp(prefix=f".{destination.name}-", dir=destination.parent))
    os.chmod(stage, 0o750)
    try:
        for name, value in sorted(files.items()):
            relative = Path(name)
            if relative.is_absolute() or ".." in relative.parts:
                raise RunStoryError("artifact-invalid")
            _write_file(stage / relative, value)
        os.replace(stage, destination)
        descriptor = os.open(destination.parent, os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
    except Exception:
        if stage.exists():
            for path in sorted(stage.rglob("*"), reverse=True):
                if path.is_file():
                    path.unlink()
                elif path.is_dir():
                    path.rmdir()
            stage.rmdir()
        raise
    return destination


def write_atomic_file(path: Path, value: bytes) -> None:
    _ensure_directory(path.parent)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}-", dir=path.parent)
    try:
        os.fchmod(descriptor, 0o640)
        with os.fdopen(descriptor, "wb", closefd=False) as handle:
            handle.write(value)
            handle.flush()
            os.fsync(handle.fileno())
        os.close(descriptor)
        descriptor = -1
        os.replace(temporary, path)
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        if os.path.exists(temporary):
            os.unlink(temporary)


def rebuild_catalog(artifact_root: Path) -> Path:
    games = artifact_root / "games"
    runs: list[dict[str, object]] = []
    if games.exists():
        if games.is_symlink() or not games.is_dir():
            raise RunStoryError("catalog-invalid")
        for manifest_path in games.glob("*/runs/*/artifact.json"):
            if manifest_path.is_symlink():
                raise RunStoryError("catalog-invalid")
            try:
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            except (OSError, UnicodeError, json.JSONDecodeError):
                raise RunStoryError("catalog-invalid") from None
            if (
                not isinstance(manifest, dict)
                or manifest.get("schema") != SCHEMA
                or type(manifest.get("game_id")) is not str
                or type(manifest.get("run_id")) is not str
                or type(manifest.get("bundle_sha256")) is not str
            ):
                raise RunStoryError("catalog-invalid")
            run_root = manifest_path.parent
            analyses = []
            for path in sorted((run_root / "analyses").glob("*/analysis.json")):
                analysis = json.loads(path.read_text(encoding="utf-8"))
                if not isinstance(analysis, dict) or type(analysis.get("analysis_id")) is not str:
                    raise RunStoryError("catalog-invalid")
                analyses.append(
                    {
                        "analysis_id": analysis["analysis_id"],
                        "status": analysis.get("status"),
                    }
                )
            renders = []
            for path in sorted((run_root / "renders" / "web").glob("*/render.json")):
                render = json.loads(path.read_text(encoding="utf-8"))
                if not isinstance(render, dict) or type(render.get("render_id")) is not str:
                    raise RunStoryError("catalog-invalid")
                renders.append(
                    {
                        "render_id": render["render_id"],
                        "path": path.parent.relative_to(artifact_root).as_posix()
                        + "/index.html",
                    }
                )
            runs.append(
                {
                    "analyses": analyses,
                    "bundle_sha256": manifest["bundle_sha256"],
                    "game_id": manifest["game_id"],
                    "path": run_root.relative_to(artifact_root).as_posix(),
                    "run_id": manifest["run_id"],
                    "renders": renders,
                    "verification": manifest["verification"],
                }
            )
    runs.sort(key=lambda item: (str(item["game_id"]), str(item["run_id"])))
    path = artifact_root / "catalog.json"
    write_atomic_file(path, canonical_json({"schema": SCHEMA, "runs": runs}))
    return path


__all__ = (
    "digest_bytes",
    "publish_directory",
    "rebuild_catalog",
    "safe_id",
    "write_atomic_file",
)
