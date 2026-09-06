"""Reproducible, private prerequisites for Prime development commands."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from importlib import resources
import json
import os
from pathlib import Path
import platform as _platform
import shutil
import stat
import subprocess
import tarfile
from typing import Callable, Mapping
from urllib.request import urlopen

from asterion.applications.prime_agent.source_lock import (
    PrimeSourceLock,
    verify_prime_source_lock,
)

_MESSAGE = "Prime development preparation is unavailable"
_SCENARIOS = frozenset({"p1", "p2", "p3", "p4", "p5", "p6", "p7"})


class PrimeDevelopmentPreparationError(ValueError):
    def __init__(self, *_: object) -> None:
        super().__init__(_MESSAGE)


@dataclass(frozen=True)
class PrimeDevelopmentPaths:
    root: Path
    node: Path
    seccomp: Path
    gateway_root: Path
    source_root: Path


def _bytes(name: str) -> bytes:
    return (
        resources.files("asterion.applications.prime_agent.operator.resources")
        .joinpath(name)
        .read_bytes()
    )


def _lock() -> dict[str, object]:
    try:
        value = json.loads(_bytes("prime-development-preparation-lock.json"))
        if (
            type(value) is not dict
            or value.get("format") != "asterion.prime-development-preparation-lock/v1"
        ):
            raise ValueError
        return value
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError):
        raise PrimeDevelopmentPreparationError() from None


def _digest(path: Path) -> str:
    try:
        info = path.lstat()
        if path.is_symlink() or not stat.S_ISREG(info.st_mode):
            raise ValueError
        return sha256(path.read_bytes()).hexdigest()
    except (OSError, ValueError):
        raise PrimeDevelopmentPreparationError() from None


def _root(repo_root: Path) -> Path:
    try:
        root = (
            repo_root.resolve(strict=True) / ".asterion-private" / "prime-development"
        )
        if any(part.is_symlink() for part in (root.parent, root)):
            raise ValueError
        root.mkdir(parents=True, exist_ok=True, mode=0o700)
        if root.is_symlink() or not stat.S_ISDIR(root.lstat().st_mode):
            raise ValueError
        return root
    except (OSError, ValueError):
        raise PrimeDevelopmentPreparationError() from None


def _run(argv: list[str], *, runner: Callable[..., object]) -> object:
    try:
        return runner(
            argv,
            check=True,
            capture_output=True,
            timeout=120,
            env={"PATH": "/usr/bin:/bin"},
        )
    except Exception:
        raise PrimeDevelopmentPreparationError() from None


def _context(repo: Path, arch: str, runner: Callable[..., object]) -> dict[str, object]:
    result = _run(["/usr/bin/docker", "info", "--format", "{{.ID}}"], runner=runner)
    daemon = getattr(result, "stdout", b"")
    if type(daemon) is bytes:
        daemon = daemon.decode("ascii", "ignore").strip()
    if type(daemon) is not str or not daemon:
        raise PrimeDevelopmentPreparationError()
    return {
        "machine": os.environ.get("PRIME_ORB_MACHINE", ""),
        "uid": os.geteuid(),
        "worktree": sha256(str(repo.resolve()).encode()).hexdigest(),
        "platform": "linux/" + arch,
        "daemon": sha256(daemon.encode()).hexdigest(),
    }


def _node(
    root: Path,
    record: dict[str, object],
    *,
    downloader: Callable[..., object],
    runner: Callable[..., object],
) -> Path:
    archive, node = root / "node.tar.xz", root / "node" / "bin" / "node"
    if _digest(archive) != record["archive_sha256"] if archive.exists() else True:
        staged = root / ".node.tar.xz.stage"
        try:
            data = downloader(str(record["url"])).read(128 * 1024 * 1024 + 1)
            if (
                len(data) > 128 * 1024 * 1024
                or sha256(data).hexdigest() != record["archive_sha256"]
            ):
                raise ValueError
            staged.write_bytes(data)
            os.replace(staged, archive)
        except Exception:
            staged.unlink(missing_ok=True)
            raise PrimeDevelopmentPreparationError() from None
        shutil.rmtree(root / "node", ignore_errors=True)
        with tarfile.open(archive) as tar:
            tar.extractall(root / ".node-extract")
        extracted = next(
            (p for p in (root / ".node-extract").iterdir() if p.is_dir()), None
        )
        if extracted is None:
            raise PrimeDevelopmentPreparationError()
        os.replace(extracted, root / "node")
        shutil.rmtree(root / ".node-extract", ignore_errors=True)
    if _digest(node) != record["node_sha256"]:
        raise PrimeDevelopmentPreparationError()
    version = _run([str(node), "--version"], runner=runner)
    if getattr(version, "stdout", b"").decode().strip() != "v22.23.2":
        raise PrimeDevelopmentPreparationError()
    return node


def prepare_prime_development(
    repo_root: Path,
    scenarios: tuple[str, ...],
    *,
    emit: Callable[[str, str], None] | None = None,
    downloader: Callable[..., object] = urlopen,
    runner: Callable[..., object] = subprocess.run,
    platform_machine: Callable[[], str] = _platform.machine,
) -> Mapping[str, PrimeDevelopmentPaths]:
    if (
        type(repo_root) is not Path
        or not scenarios
        or any(type(s) is not str or s not in _SCENARIOS for s in scenarios)
    ):
        raise PrimeDevelopmentPreparationError()
    lock, repo = _lock(), repo_root.resolve()
    arch = {
        "x86_64": "amd64",
        "amd64": "amd64",
        "aarch64": "arm64",
        "arm64": "arm64",
    }.get(platform_machine())
    if arch is None:
        raise PrimeDevelopmentPreparationError()
    root = _root(repo)
    nodes = lock.get("node")
    if type(nodes) is not dict or type(nodes.get(arch)) is not dict:
        raise PrimeDevelopmentPreparationError()
    if emit:
        emit("source", "started")
    node = _node(root, nodes[arch], downloader=downloader, runner=runner)  # type: ignore[arg-type]
    seccomp = root / "prime-development-seccomp.json"
    profile = _bytes("prime-development-seccomp.json")
    sec = lock.get("seccomp")
    if type(sec) is not dict or sha256(profile).hexdigest() != sec.get(
        "canonical_sha256"
    ):
        raise PrimeDevelopmentPreparationError()
    staged = root / ".seccomp.stage"
    staged.write_bytes(profile)
    os.replace(staged, seccomp)
    source = repo / "3th-party" / "prime-agent"
    source_lock = lock.get("source")
    if type(source_lock) is not dict:
        raise PrimeDevelopmentPreparationError()
    verify_prime_source_lock(source, PrimeSourceLock(**source_lock))
    gateway = repo / "packages" / "typescript" / "prime-gateway"
    receipt = {
        "context": _context(repo, arch, runner),
        "lock_sha256": sha256(
            json.dumps(lock, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest(),
        "scenarios": sorted(set(scenarios)),
    }
    staged = root / ".receipt.stage"
    staged.write_bytes(
        json.dumps(receipt, sort_keys=True, separators=(",", ":")).encode()
    )
    os.replace(staged, root / "receipt.json")
    if emit:
        emit("source", "succeeded")
    return {
        s: PrimeDevelopmentPaths(root, node, seccomp, gateway, source)
        for s in scenarios
    }
