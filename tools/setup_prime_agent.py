"""Verify or install the explicitly selected pinned Prime source checkout."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from importlib import resources
from pathlib import Path
from types import MappingProxyType


LOCK_FORMAT = "asterion.prime-artifact-lock/v1"
MINIMUM_NODE_VERSION = (22, 8, 0)
_COMMIT = re.compile(r"^[0-9a-f]{40}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_VERSION = re.compile(r"^v?(\d+)\.(\d+)\.(\d+)(?:[-+].*)?$")

Runner = Callable[
    [tuple[str, ...], Path, dict[str, str]], subprocess.CompletedProcess[str]
]


class PrimeSetupError(RuntimeError):
    """Raised without provider output or private paths when setup is unsafe."""


@dataclass(frozen=True, repr=False)
class PrimeArtifactLock:
    source_commit: str
    package_name: str
    package_version: str
    daemon_protocol: int
    daemon_schema_revision: int
    daemon_schema_id: str
    files: Mapping[str, str]


@dataclass(frozen=True)
class PrimeSetupReport:
    source_commit: str
    package_version: str
    daemon_protocol: int
    daemon_schema_revision: int
    installed: bool


def _default_runner(
    command: tuple[str, ...], cwd: Path, env: dict[str, str]
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=cwd,
        env=env,
        check=False,
        capture_output=True,
        text=True,
        timeout=900,
    )


def default_lock_path() -> Path:
    repository = (
        Path(__file__).resolve().parents[1]
        / "packages/typescript/prime-gateway/resources/prime-artifact-lock.json"
    )
    if repository.is_file():
        return repository
    packaged = resources.files("asterion").joinpath(
        "control/providers/prime/resources/prime-artifact-lock.json"
    )
    return Path(str(packaged))


def load_prime_artifact_lock(path: Path | None = None) -> PrimeArtifactLock:
    try:
        value = json.loads((path or default_lock_path()).read_text(encoding="utf-8"))
        if not isinstance(value, dict) or set(value) != {
            "format",
            "source_commit",
            "package_name",
            "package_version",
            "daemon_protocol",
            "daemon_schema_revision",
            "daemon_schema_id",
            "files",
        }:
            raise TypeError
        files = value["files"]
        if (
            value["format"] != LOCK_FORMAT
            or not isinstance(value["source_commit"], str)
            or _COMMIT.fullmatch(value["source_commit"]) is None
            or value["package_name"] != "@earendil-works/pi-coding-agent"
            or not isinstance(value["package_version"], str)
            or value["daemon_protocol"] != 7
            or value["daemon_schema_revision"] != 14
            or not isinstance(value["daemon_schema_id"], str)
            or not isinstance(files, dict)
            or not files
        ):
            raise TypeError
        normalized: dict[str, str] = {}
        for relative, digest in files.items():
            candidate = Path(relative)
            if (
                not isinstance(relative, str)
                or candidate.is_absolute()
                or ".." in candidate.parts
                or candidate.as_posix() != relative
                or not isinstance(digest, str)
                or _SHA256.fullmatch(digest) is None
            ):
                raise TypeError
            normalized[relative] = digest
        if tuple(normalized) != tuple(sorted(normalized)):
            raise TypeError
        return PrimeArtifactLock(
            source_commit=value["source_commit"],
            package_name=value["package_name"],
            package_version=value["package_version"],
            daemon_protocol=value["daemon_protocol"],
            daemon_schema_revision=value["daemon_schema_revision"],
            daemon_schema_id=value["daemon_schema_id"],
            files=MappingProxyType(normalized),
        )
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        raise PrimeSetupError("Prime artifact lock is invalid") from None


def verify_prime_source(
    source_root: Path,
    *,
    lock_path: Path | None = None,
    node_executable: str = "node",
    runner: Runner = _default_runner,
) -> PrimeSetupReport:
    lock = load_prime_artifact_lock(lock_path)
    root = _source_root(source_root)
    _verify_files(root, lock)
    git_metadata = root / ".git"
    if git_metadata.is_symlink() or not (
        git_metadata.is_dir() or git_metadata.is_file()
    ):
        raise PrimeSetupError("Prime source checkout is unavailable")
    with tempfile.TemporaryDirectory(prefix="asterion-prime-check-") as temporary:
        environment = _closed_environment(Path(temporary))
        head = _run(runner, ("git", "rev-parse", "HEAD"), root, environment)
        status = _run(
            runner,
            ("git", "status", "--porcelain", "--untracked-files=normal"),
            root,
            environment,
        )
        if (
            head.returncode != 0
            or head.stdout.strip() != lock.source_commit
            or status.returncode != 0
            or status.stdout.strip()
        ):
            raise PrimeSetupError(
                "Prime source checkout is not the pinned clean revision"
            )
        node = _run(runner, (node_executable, "--version"), root, environment)
        if node.returncode != 0 or not _supported_node(node.stdout.strip()):
            raise PrimeSetupError(
                "Prime setup requires compatible Node.js 22.8.0 through 22.x"
            )
    return _report(lock, installed=False)


def setup_prime_source(
    source_root: Path,
    *,
    lock_path: Path | None = None,
    node_executable: str = "node",
    runner: Runner = _default_runner,
) -> PrimeSetupReport:
    report = verify_prime_source(
        source_root,
        lock_path=lock_path,
        node_executable=node_executable,
        runner=runner,
    )
    root = _source_root(source_root)
    with tempfile.TemporaryDirectory(prefix="asterion-prime-npm-") as temporary:
        completed = _run(
            runner,
            ("npm", "ci"),
            root,
            _closed_environment(Path(temporary)),
        )
    if completed.returncode != 0:
        raise PrimeSetupError("Prime dependency installation failed")
    with tempfile.TemporaryDirectory(prefix="asterion-prime-build-") as temporary:
        built = _run(
            runner,
            ("npm", "run", "build"),
            root,
            _closed_environment(Path(temporary)),
        )
    if built.returncode != 0:
        raise PrimeSetupError("Prime source build failed")
    return PrimeSetupReport(
        source_commit=report.source_commit,
        package_version=report.package_version,
        daemon_protocol=report.daemon_protocol,
        daemon_schema_revision=report.daemon_schema_revision,
        installed=True,
    )


def _source_root(value: Path) -> Path:
    try:
        if not isinstance(value, Path) or value.is_symlink():
            raise OSError
        root = value.resolve(strict=True)
        if not root.is_dir():
            raise OSError
        return root
    except (OSError, RuntimeError):
        raise PrimeSetupError("Prime source checkout is unavailable") from None


def _verify_files(root: Path, lock: PrimeArtifactLock) -> None:
    for relative, expected in lock.files.items():
        try:
            path = root / relative
            if path.is_symlink() or not path.is_file():
                raise OSError
            resolved = path.resolve(strict=True)
            resolved.relative_to(root)
            if any(parent.is_symlink() for parent in path.parents if parent != root):
                raise OSError
            digest = hashlib.sha256(resolved.read_bytes()).hexdigest()
            if digest != expected:
                raise OSError
        except (OSError, RuntimeError, ValueError):
            raise PrimeSetupError(
                "Prime source artifact does not match the lock"
            ) from None


def _closed_environment(private_home: Path) -> dict[str, str]:
    environment: dict[str, str] = {
        "HOME": str(private_home),
        "npm_config_audit": "false",
        "npm_config_fund": "false",
        "npm_config_update_notifier": "false",
        "npm_config_userconfig": os.devnull,
    }
    for key in ("PATH", "SystemRoot", "TEMP", "TMP", "TMPDIR"):
        value = os.environ.get(key)
        if value:
            environment[key] = value
    return environment


def _run(
    runner: Runner,
    command: tuple[str, ...],
    cwd: Path,
    environment: dict[str, str],
) -> subprocess.CompletedProcess[str]:
    try:
        return runner(command, cwd, environment)
    except (OSError, subprocess.SubprocessError):
        raise PrimeSetupError("Prime setup command could not run") from None


def _supported_node(value: str) -> bool:
    match = _VERSION.fullmatch(value)
    if match is None:
        return False
    version = tuple(int(part) for part in match.groups())
    return version[0] == 22 and version >= MINIMUM_NODE_VERSION


def _report(lock: PrimeArtifactLock, *, installed: bool) -> PrimeSetupReport:
    return PrimeSetupReport(
        source_commit=lock.source_commit,
        package_version=lock.package_version,
        daemon_protocol=lock.daemon_protocol,
        daemon_schema_revision=lock.daemon_schema_revision,
        installed=installed,
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-root", required=True, type=Path)
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--node-executable", default="node")
    arguments = parser.parse_args(argv)
    try:
        report = (
            verify_prime_source(
                arguments.source_root,
                node_executable=arguments.node_executable,
            )
            if arguments.check
            else setup_prime_source(
                arguments.source_root,
                node_executable=arguments.node_executable,
            )
        )
    except PrimeSetupError as error:
        print(f"Prime setup failed: {error}", file=sys.stderr)
        return 1
    print(
        json.dumps(
            {
                "status": "PASS",
                "source_commit": report.source_commit,
                "package_version": report.package_version,
                "daemon_protocol": report.daemon_protocol,
                "daemon_schema_revision": report.daemon_schema_revision,
                "dependencies_installed": report.installed,
                "provider_operations": 0,
            },
            sort_keys=True,
            separators=(",", ":"),
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
