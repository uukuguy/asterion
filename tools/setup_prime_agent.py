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
_STATIC_LOCAL_ESM_IMPORT = re.compile(
    r"^import(?:[\s\S]*?\sfrom)?\s*[\"'](\.[^\"']+)[\"']",
    re.MULTILINE,
)
_ENTRY_DYNAMIC_LOCAL_ESM_IMPORT = re.compile(
    r"\bawait\s+import\(\s*[\"'](\.[^\"']+)[\"']"
)
_LINE_DYNAMIC_LOCAL_ESM_IMPORT = re.compile(
    r"^\s*import\(\s*[\"'](\.[^\"']+)[\"']", re.MULTILINE
)
_OFFLINE_BUILD_COMMANDS = (
    ("npm", "--prefix", "packages/tui", "run", "build"),
    (
        "node_modules/.bin/tsgo",
        "-p",
        "packages/ai/tsconfig.build.json",
    ),
    ("npm", "--prefix", "packages/agent", "run", "build"),
    ("npm", "--prefix", "packages/coding-agent", "run", "build"),
)

Runner = Callable[
    [tuple[str, ...], Path, dict[str, str]], subprocess.CompletedProcess[str]
]


class PrimeSetupError(RuntimeError):
    """Raised without provider output or private paths when setup is unsafe."""


@dataclass(frozen=True, repr=False)
class PrimeRlmRuntimeLock:
    entry: str
    binding_chunk: str
    closure: Mapping[str, str]
    derived_closure: Mapping[str, str]
    patch_sha256: str


@dataclass(frozen=True, repr=False)
class PrimeArtifactLock:
    source_commit: str
    package_name: str
    package_version: str
    daemon_protocol: int
    daemon_schema_revision: int
    daemon_schema_id: str
    files: Mapping[str, str]
    rlm_runtime: PrimeRlmRuntimeLock | None


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


def default_rlm_shim_path() -> Path:
    repository = (
        Path(__file__).resolve().parents[1]
        / "packages/typescript/prime-gateway/resources/prime-rlm-host-shim.json"
    )
    if repository.is_file():
        return repository
    packaged = resources.files("asterion").joinpath(
        "control/providers/prime/resources/prime-rlm-host-shim.json"
    )
    return Path(str(packaged))


def _parse_digest_mapping(value: object) -> Mapping[str, str]:
    if not isinstance(value, dict) or not value:
        raise TypeError
    normalized: dict[str, str] = {}
    for relative, digest in value.items():
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
    return MappingProxyType(normalized)


def _parse_rlm_runtime_lock(value: object) -> PrimeRlmRuntimeLock | None:
    if value is None:
        return None
    if not isinstance(value, dict) or set(value) != {
        "entry",
        "binding_chunk",
        "closure",
        "derived_closure",
        "patch_sha256",
    }:
        raise TypeError
    closure = _parse_digest_mapping(value["closure"])
    derived = _parse_digest_mapping(value["derived_closure"])
    entry = value["entry"]
    binding = value["binding_chunk"]
    if (
        not isinstance(entry, str)
        or not isinstance(binding, str)
        or entry not in closure
        or binding not in closure
        or tuple(closure) != tuple(derived)
        or not isinstance(value["patch_sha256"], str)
        or _SHA256.fullmatch(value["patch_sha256"]) is None
    ):
        raise TypeError
    return PrimeRlmRuntimeLock(
        entry=entry,
        binding_chunk=binding,
        closure=closure,
        derived_closure=derived,
        patch_sha256=value["patch_sha256"],
    )


def load_prime_artifact_lock(path: Path | None = None) -> PrimeArtifactLock:
    try:
        value = json.loads((path or default_lock_path()).read_text(encoding="utf-8"))
        if not isinstance(value, dict) or set(value) not in ({
            "format",
            "source_commit",
            "package_name",
            "package_version",
            "daemon_protocol",
            "daemon_schema_revision",
            "daemon_schema_id",
            "files",
        }, {
            "format",
            "source_commit",
            "package_name",
            "package_version",
            "daemon_protocol",
            "daemon_schema_revision",
            "daemon_schema_id",
            "files",
            "rlm_runtime",
        }):
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
        runtime = _parse_rlm_runtime_lock(value.get("rlm_runtime"))
        return PrimeArtifactLock(
            source_commit=value["source_commit"],
            package_name=value["package_name"],
            package_version=value["package_version"],
            daemon_protocol=value["daemon_protocol"],
            daemon_schema_revision=value["daemon_schema_revision"],
            daemon_schema_id=value["daemon_schema_id"],
            files=MappingProxyType(normalized),
            rlm_runtime=runtime,
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
    report = verify_prime_checkout(
        source_root,
        lock_path=lock_path,
        runner=runner,
    )
    root = _source_root(source_root)
    with tempfile.TemporaryDirectory(prefix="asterion-prime-check-") as temporary:
        environment = _closed_environment(Path(temporary))
        node = _run(runner, (node_executable, "--version"), root, environment)
        if node.returncode != 0 or not _supported_node(node.stdout.strip()):
            raise PrimeSetupError(
                "Prime setup requires compatible Node.js 22.8.0 through 22.x"
            )
    return report


def verify_prime_checkout(
    source_root: Path,
    *,
    lock_path: Path | None = None,
    runner: Runner = _default_runner,
) -> PrimeSetupReport:
    """Verify the pinned clean checkout without testing a Node runtime."""

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
        top_level = _run(
            runner, ("git", "rev-parse", "--show-toplevel"), root, environment
        )
        head = _run(runner, ("git", "rev-parse", "HEAD"), root, environment)
        status = _run(
            runner,
            ("git", "status", "--porcelain", "--untracked-files=normal"),
            root,
            environment,
        )
        if (
            not _is_exact_git_root(top_level, root)
            or head.returncode != 0
            or head.stdout.strip() != lock.source_commit
            or status.returncode != 0
            or status.stdout.strip()
        ):
            raise PrimeSetupError(
                "Prime source checkout is not the pinned clean revision"
            )
    return _report(lock, installed=False)


def setup_prime_source(
    source_root: Path,
    *,
    lock_path: Path | None = None,
    rlm_shim_path: Path | None = None,
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
    verify_prime_source(
        root,
        lock_path=lock_path,
        node_executable=node_executable,
        runner=runner,
    )
    with tempfile.TemporaryDirectory(prefix="asterion-prime-build-") as temporary:
        environment = _closed_environment(Path(temporary))
        for command in _OFFLINE_BUILD_COMMANDS:
            built = _run(runner, command, root, environment)
            if built.returncode != 0:
                raise PrimeSetupError("Prime source build failed")
    verify_prime_source(
        root,
        lock_path=lock_path,
        node_executable=node_executable,
        runner=runner,
    )
    lock = load_prime_artifact_lock(lock_path)
    if lock.rlm_runtime is not None:
        derive_prime_rlm_runtime(
            root,
            lock_path=lock_path,
            shim_path=rlm_shim_path,
            runner=runner,
        )
    return PrimeSetupReport(
        source_commit=report.source_commit,
        package_version=report.package_version,
        daemon_protocol=report.daemon_protocol,
        daemon_schema_revision=report.daemon_schema_revision,
        installed=True,
    )


def derive_prime_rlm_runtime(
    source_root: Path,
    *,
    lock_path: Path | None = None,
    shim_path: Path | None = None,
    runner: Runner = _default_runner,
) -> Path:
    """Derive the exact ignored Prime daemon bundle without changing source."""

    lock = load_prime_artifact_lock(lock_path)
    runtime = lock.rlm_runtime
    if runtime is None:
        raise PrimeSetupError("Prime RLM runtime lock is unavailable")
    root = _source_root(source_root)
    verify_prime_checkout(root, lock_path=lock_path, runner=runner)
    shim = _read_regular_file(shim_path or default_rlm_shim_path())
    if hashlib.sha256(shim).hexdigest() != runtime.patch_sha256:
        raise PrimeSetupError("Prime RLM shim is incompatible")
    closure = _resolve_local_esm_closure(root, runtime.entry)
    if tuple(closure) != tuple(runtime.closure):
        raise PrimeSetupError("Prime RLM shim is incompatible")
    digests = _closure_digests(root, closure)
    if digests == dict(runtime.derived_closure):
        return root / runtime.entry
    if digests != dict(runtime.closure):
        raise PrimeSetupError("Prime RLM shim is incompatible")
    target, anchor, replacement = _parse_rlm_shim(shim, runtime)
    original = _read_regular_file_beneath(root, target)
    if original.count(anchor) != 1 or replacement in original:
        raise PrimeSetupError("Prime RLM shim is incompatible")
    _atomic_replace_regular_file(root / target, original.replace(anchor, replacement))
    if _closure_digests(root, closure) != dict(runtime.derived_closure):
        raise PrimeSetupError("Prime RLM shim is incompatible")
    verify_prime_checkout(root, lock_path=lock_path, runner=runner)
    return root / runtime.entry


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


def _read_regular_file(path: Path) -> bytes:
    try:
        if path.is_symlink() or not path.is_file():
            raise OSError
        return path.read_bytes()
    except (OSError, RuntimeError):
        raise PrimeSetupError("Prime RLM shim is incompatible") from None


def _read_regular_file_beneath(root: Path, relative: str) -> bytes:
    try:
        target = root / relative
        if target.is_symlink() or not target.is_file():
            raise OSError
        resolved = target.resolve(strict=True)
        resolved.relative_to(root)
        if any(parent.is_symlink() for parent in target.parents if parent != root):
            raise OSError
        return resolved.read_bytes()
    except (OSError, RuntimeError, ValueError):
        raise PrimeSetupError("Prime RLM shim is incompatible") from None


def _resolve_local_esm_closure(root: Path, entry: str) -> tuple[str, ...]:
    try:
        root = root.resolve(strict=True)
    except (OSError, RuntimeError):
        raise PrimeSetupError("Prime RLM shim is incompatible") from None
    pending = [entry]
    resolved: set[str] = set()
    while pending:
        relative = pending.pop()
        if relative in resolved:
            continue
        contents = _read_regular_file_beneath(root, relative).decode("utf-8")
        resolved.add(relative)
        parent = Path(relative).parent
        imports = _STATIC_LOCAL_ESM_IMPORT.findall(contents)
        if relative == entry:
            imports += _ENTRY_DYNAMIC_LOCAL_ESM_IMPORT.findall(contents)
        else:
            imports += _LINE_DYNAMIC_LOCAL_ESM_IMPORT.findall(contents)
        for imported in imports:
            candidate = Path(imported)
            if candidate.suffix != ".js" or ".." in candidate.parts:
                raise PrimeSetupError("Prime RLM shim is incompatible")
            child = (parent / candidate).as_posix()
            if child.startswith("./"):
                child = child[2:]
            pending.append(child)
    return tuple(sorted(resolved))


def _closure_digests(root: Path, closure: Sequence[str]) -> dict[str, str]:
    return {
        relative: hashlib.sha256(_read_regular_file_beneath(root, relative)).hexdigest()
        for relative in closure
    }


def _parse_rlm_shim(
    bytes_value: bytes, runtime: PrimeRlmRuntimeLock
) -> tuple[str, bytes, bytes]:
    try:
        value = json.loads(bytes_value)
        if not isinstance(value, dict) or set(value) != {
            "format",
            "target",
            "anchor",
            "replacement",
        }:
            raise TypeError
        target = value["target"]
        anchor = value["anchor"]
        replacement = value["replacement"]
        if (
            value["format"] != "asterion.prime-rlm-host-shim/v1"
            or target != runtime.binding_chunk
            or not isinstance(anchor, str)
            or not isinstance(replacement, str)
            or not anchor
            or not replacement
            or anchor == replacement
        ):
            raise TypeError
        return target, anchor.encode("utf-8"), replacement.encode("utf-8")
    except (TypeError, ValueError, json.JSONDecodeError):
        raise PrimeSetupError("Prime RLM shim is incompatible") from None


def _atomic_replace_regular_file(path: Path, value: bytes) -> None:
    try:
        if path.is_symlink() or not path.is_file():
            raise OSError
        with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as temporary:
            temporary.write(value)
            temporary_path = Path(temporary.name)
        try:
            os.replace(temporary_path, path)
        finally:
            temporary_path.unlink(missing_ok=True)
    except (OSError, RuntimeError):
        raise PrimeSetupError("Prime RLM shim is incompatible") from None


def _is_exact_git_root(completed: subprocess.CompletedProcess[str], root: Path) -> bool:
    if completed.returncode != 0:
        return False
    value = completed.stdout.strip()
    candidate = Path(value)
    if not value or not candidate.is_absolute():
        return False
    try:
        return candidate.resolve(strict=True) == root
    except (OSError, RuntimeError):
        return False


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
