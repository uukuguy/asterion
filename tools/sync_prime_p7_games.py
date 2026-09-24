"""Synchronize the public ARC-AGI-3 catalog into an operator-owned root.

This tool deliberately uses only GET endpoints.  It does not import the ARC
SDK because the SDK's normal game creation path can open a scorecard.
"""

from __future__ import annotations

import argparse
import ast
from datetime import datetime
import json
import os
from pathlib import Path
import re
import tempfile
from typing import Any, Callable, Protocol
from urllib.request import Request, urlopen


_GAME_ID = re.compile(r"^[a-z0-9]{4}-[0-9a-f]{8}$")
_CLASS_NAME = re.compile(r"^[A-Z][A-Za-z0-9]*$")
_DEFAULT_BASE_URL = "https://three.arcprize.org"
_TIMEOUT_SECONDS = 10.0


class SyncError(ValueError):
    """A public catalog item cannot safely be synchronized."""


class _Response(Protocol):
    content: bytes

    def json(self) -> object: ...

    def raise_for_status(self) -> None: ...


Get = Callable[..., _Response]


def _expected_class_name(short_id: str) -> str:
    return short_id[0].upper() + short_id[1:]


def _safe_directory(path: Path) -> None:
    """Create a directory only when no component in this owned tree is a link."""
    if path.is_symlink():
        raise SyncError("symlinked destination is not allowed")
    if path.exists():
        if not path.is_dir():
            raise SyncError("destination directory is invalid")
        return
    path.mkdir()
    if path.is_symlink() or not path.is_dir():
        raise SyncError("destination directory is invalid")


def _destination(arc_root: Path, game_id: str) -> tuple[Path, Path, Path]:
    if arc_root.is_symlink():
        raise SyncError("symlinked ARC root is not allowed")
    _safe_directory(arc_root)
    environment_files = arc_root / "environment_files"
    _safe_directory(environment_files)
    short_id, version = game_id.split("-", 1)
    short_root = environment_files / short_id
    _safe_directory(short_root)
    game_root = short_root / version
    _safe_directory(game_root)
    return game_root, game_root / "metadata.json", game_root / f"{short_id}.py"


def _check_file(path: Path) -> None:
    if path.is_symlink():
        raise SyncError("symlinked destination is not allowed")
    if path.exists() and not path.is_file():
        raise SyncError("destination file is invalid")


def _create_atomic(path: Path, contents: bytes) -> None:
    """Publish a complete new file without replacing an existing file."""
    _check_file(path)
    if path.exists():
        raise SyncError("existing game version differs")
    descriptor, temporary_name = tempfile.mkstemp(prefix=".p7-sync-", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(contents)
            handle.flush()
            os.fsync(handle.fileno())
        # link(2) is an atomic create-if-absent operation, unlike replace().
        os.link(temporary, path)
    except FileExistsError as error:
        raise SyncError("existing game version differs") from error
    finally:
        temporary.unlink(missing_ok=True)


def _catalog_ids(value: object) -> tuple[str, ...]:
    if type(value) is not list:
        raise SyncError("official catalog is invalid")
    ids: list[str] = []
    for row in value:
        if type(row) is not dict or type(row.get("game_id")) is not str:
            raise SyncError("official catalog is invalid")
        game_id = row["game_id"]
        if _GAME_ID.fullmatch(game_id) is None:
            raise SyncError("official catalog contains an invalid game ID")
        ids.append(game_id)
    if not ids or len(ids) != len(set(ids)):
        raise SyncError("official catalog has duplicate or missing game IDs")
    return tuple(sorted(ids))


def _metadata(value: object, game_id: str) -> dict[str, Any]:
    if type(value) is not dict or value.get("game_id") != game_id:
        raise SyncError("official metadata identity does not match catalog")
    short_id, version = game_id.split("-", 1)
    class_name = value.get("class_name")
    baseline_actions = value.get("baseline_actions")
    default_fps = value.get("default_fps")
    if (
        type(value.get("title")) is not str
        or ("tags" in value and (
            type(value["tags"]) is not list or any(type(tag) is not str for tag in value["tags"])
        ))
        or (baseline_actions is not None and (
            type(baseline_actions) is not list
            or any(type(action) is not int or isinstance(action, bool) or action < 0 for action in baseline_actions)
        ))
        or (default_fps is not None and (type(default_fps) is not int or isinstance(default_fps, bool) or default_fps < 1))
        or (class_name is not None and (
            type(class_name) is not str
            or _CLASS_NAME.fullmatch(class_name) is None
            or class_name != _expected_class_name(short_id)
        ))
        or ("version" in value and value["version"] != version)
    ):
        raise SyncError("official metadata is invalid")
    return value


def _matches_existing_metadata(existing: object, remote: dict[str, Any], *, destination: Path, class_name: str) -> bool:
    """Accept only the ARC SDK's validated local additions to remote metadata."""
    if type(existing) is not dict or any(existing.get(key) != value for key, value in remote.items()):
        return False
    extras = set(existing) - set(remote)
    if not extras.issubset({"date_downloaded", "local_dir", "class_name"}):
        return False
    if "date_downloaded" in extras:
        try:
            if type(existing["date_downloaded"]) is not str:
                return False
            datetime.fromisoformat(existing["date_downloaded"].replace("Z", "+00:00"))
        except ValueError:
            return False
    if "local_dir" in extras:
        if (
            type(existing["local_dir"]) is not str
            or os.path.abspath(existing["local_dir"]) != os.path.abspath(destination)
        ):
            return False
    return "class_name" not in extras or existing["class_name"] == class_name


def _source(value: bytes, class_name: str) -> bytes:
    try:
        text = value.decode("utf-8")
        tree = ast.parse(text)
    except (UnicodeDecodeError, SyntaxError) as error:
        raise SyncError("official source is not valid Python") from error
    if not any(type(node) is ast.ClassDef and node.name == class_name for node in tree.body):
        raise SyncError("official source does not define the declared class")
    return value


def _default_get(url: str, *, headers: dict[str, str], timeout: float) -> _Response:
    request = Request(url, headers=headers, method="GET")
    with urlopen(request, timeout=timeout) as response:  # noqa: S310 - fixed HTTPS default, operator override
        content = response.read()

    class Response:
        def __init__(self, body: bytes) -> None:
            self.content = body

        def json(self) -> object:
            return json.loads(self.content.decode("utf-8"))

        def raise_for_status(self) -> None:
            return None

    return Response(content)


def sync_games(
    arc_root: Path,
    *,
    api_key: str,
    base_url: str = _DEFAULT_BASE_URL,
    get: Get = _default_get,
) -> tuple[str, ...]:
    """Fetch and safely persist every exact ID in the public official catalog."""
    if not isinstance(api_key, str) or not api_key:
        raise SyncError("ARC API key is unavailable")
    if not isinstance(base_url, str) or not base_url.startswith(("https://", "http://")):
        raise SyncError("ARC base URL is invalid")
    # Fail before contacting the operator service when the root is unsafe.
    if arc_root.is_symlink() or (arc_root / "environment_files").is_symlink():
        raise SyncError("symlinked destination is not allowed")
    base_url = base_url.rstrip("/")
    headers = {"X-API-Key": api_key, "Accept": "application/json"}
    current_game_id: str | None = None
    try:
        catalog = get(f"{base_url}/api/games", headers=headers, timeout=_TIMEOUT_SECONDS)
        catalog.raise_for_status()
        game_ids = _catalog_ids(catalog.json())
        for game_id in game_ids:
            current_game_id = game_id
            metadata_response = get(f"{base_url}/api/games/{game_id}", headers=headers, timeout=_TIMEOUT_SECONDS)
            metadata_response.raise_for_status()
            metadata = _metadata(metadata_response.json(), game_id)
            source_response = get(f"{base_url}/api/games/{game_id}/source", headers=headers, timeout=_TIMEOUT_SECONDS)
            source_response.raise_for_status()
            short_id = game_id.split("-", 1)[0]
            source = _source(source_response.content, _expected_class_name(short_id))
            game_root, metadata_path, source_path = _destination(arc_root, game_id)
            del game_root  # The safe-directory checks above establish both output parents.
            metadata_bytes = (json.dumps(metadata, sort_keys=True, indent=2) + "\n").encode("utf-8")
            _check_file(metadata_path)
            _check_file(source_path)
            if metadata_path.exists() or source_path.exists():
                if source_path.exists() and not metadata_path.exists():
                    raise SyncError("existing game version differs")
                try:
                    same_metadata = _matches_existing_metadata(
                        json.loads(metadata_path.read_text(encoding="utf-8")), metadata,
                        destination=metadata_path.parent, class_name=_expected_class_name(short_id),
                    )
                    same_source = not source_path.exists() or source_path.read_bytes() == source
                except (OSError, UnicodeError, ValueError) as error:
                    raise SyncError("existing game version differs") from error
                if not (same_metadata and same_source):
                    raise SyncError("existing game version differs")
                if not source_path.exists():
                    _create_atomic(source_path, source)
                continue
            _create_atomic(metadata_path, metadata_bytes)
            try:
                _create_atomic(source_path, source)
            except Exception:
                # Preserve the complete metadata as a conservative record; never delete or overwrite it.
                raise
    except SyncError as error:
        if current_game_id is not None:
            raise SyncError(f"official game sync failed: {current_game_id}: {error}") from error
        raise
    except Exception as error:
        if current_game_id is not None:
            raise SyncError(f"official game request failed: {current_game_id}") from error
        raise SyncError("official catalog request failed") from error
    return game_ids


def _read_api_key(env_file: Path) -> str | None:
    try:
        lines = env_file.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError):
        return None
    for line in lines:
        line = line.strip()
        if line.startswith("export "):
            line = line[7:].lstrip()
        if not line.startswith("ARC_API_KEY="):
            continue
        value = line.split("=", 1)[1].strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        return value or None
    return None


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Synchronize public ARC-AGI-3 game sources safely")
    parser.add_argument("--arc-root", type=Path, default=Path.cwd().parent / "external-prime" / "arc-agi-3")
    parser.add_argument("--env-file", type=Path, default=Path.cwd() / ".env")
    parser.add_argument("--base-url", default=_DEFAULT_BASE_URL)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    api_key = _read_api_key(args.env_file)
    if api_key is None:
        print("P7 game sync unavailable")
        return 1
    try:
        game_ids = sync_games(args.arc_root, api_key=api_key, base_url=args.base_url)
    except SyncError:
        print("P7 game sync unavailable")
        return 1
    print(f"P7 games synced: {len(game_ids)}")
    for game_id in game_ids:
        print(game_id)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
