"""Private, reproducible Prime development preparation."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from importlib import resources
import json
import os
from pathlib import Path
import platform as _platform
import stat
import subprocess
import tarfile
import tempfile
from typing import Callable, Mapping
from urllib.request import urlopen

from asterion.applications.prime_agent.source_lock import (
    PrimeSourceLock,
    prime_source_lock_sha256,
    verify_prime_source_lock,
)

_MESSAGE = "Prime development preparation is unavailable"
_SCENARIOS = frozenset({"p1", "p2", "p3", "p4", "p5", "p6", "p7"})
_MAX_ARCHIVE = 128 * 1024 * 1024
_MAX_EXTRACTED = 512 * 1024 * 1024
_MAX_COMMAND_OUTPUT = 4096


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


def _resource(name: str, format_name: str) -> dict[str, object]:
    try:
        value = json.loads(_bytes(name))
        if type(value) is not dict or value.get("format") != format_name:
            raise ValueError
        return value
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError):
        raise PrimeDevelopmentPreparationError() from None


def _lock() -> dict[str, object]:
    return _resource(
        "prime-development-preparation-lock.json",
        "asterion.prime-development-preparation-lock/v1",
    )


def _seccomp_lock() -> dict[str, object]:
    value = _resource(
        "prime-development-seccomp-lock.json",
        "asterion.prime-development-seccomp-lock/v1",
    )
    if (
        set(value)
        != {
            "format",
            "tag",
            "commit",
            "raw_sha256",
            "canonical_sha256",
            "license_sha256",
            "platforms",
            "images",
        }
        or value.get("platforms") != ["linux/amd64", "linux/arm64"]
        or type(value.get("images")) is not dict
        or set(value["images"]) != _SCENARIOS
    ):
        raise PrimeDevelopmentPreparationError()
    return value


def _digest(path: Path) -> str:
    try:
        if path.is_symlink() or not stat.S_ISREG(path.lstat().st_mode):
            raise ValueError
        digest = sha256()
        with path.open("rb") as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(block)
        return digest.hexdigest()
    except (OSError, ValueError):
        raise PrimeDevelopmentPreparationError() from None


def _root(repo_root: Path) -> Path:
    try:
        repo = repo_root.resolve(strict=True)
        if not repo.is_dir():
            raise ValueError
        root = repo / ".asterion-private" / "prime-development"
        root.parent.mkdir(mode=0o700, exist_ok=True)
        root.mkdir(mode=0o700, exist_ok=True)
        if any(item.is_symlink() for item in (root.parent, root)) or not root.is_dir():
            raise ValueError
        return root
    except (OSError, ValueError):
        raise PrimeDevelopmentPreparationError() from None


def _fsync_directory(path: Path) -> None:
    fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _publish_bytes(root: Path, name: str, data: bytes) -> Path:
    staged: Path | None = None
    try:
        fd, value = tempfile.mkstemp(prefix="." + name + ".", suffix=".stage", dir=root)
        staged = Path(value)
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        target = root / name
        os.replace(staged, target)
        _fsync_directory(root)
        return target
    except OSError:
        if staged is not None:
            staged.unlink(missing_ok=True)
        raise PrimeDevelopmentPreparationError() from None


def _remove_tree(path: Path) -> None:
    try:
        try:
            info = path.lstat()
        except FileNotFoundError:
            return
        if path.is_symlink() or not stat.S_ISDIR(info.st_mode):
            raise ValueError
        for child in sorted(path.iterdir(), reverse=True):
            if child.is_symlink():
                raise ValueError
            if child.is_dir():
                _remove_tree(child)
            elif stat.S_ISREG(child.lstat().st_mode):
                child.unlink()
            else:
                raise ValueError
        path.rmdir()
    except (OSError, ValueError):
        raise PrimeDevelopmentPreparationError() from None


def _extract_node(archive: Path, stage: Path) -> Path:
    try:
        with tarfile.open(archive, "r:xz") as tar:
            members = tar.getmembers()
            total = 0
            top: str | None = None
            if not members or len(members) > 4096:
                raise ValueError
            for member in members:
                parts = Path(member.name).parts
                if (
                    Path(member.name).is_absolute()
                    or ".." in parts
                    or len(parts) < 2
                    or member.issym()
                    or member.islnk()
                    or member.isdev()
                    or not (member.isdir() or member.isreg())
                    or member.size < 0
                ):
                    raise ValueError
                top = top or parts[0]
                if parts[0] != top:
                    raise ValueError
                total += member.size
                if total > _MAX_EXTRACTED:
                    raise ValueError
            if top is None or not top.startswith("node-v22.23.2-linux-"):
                raise ValueError
            for member in members:
                out = stage.joinpath(*Path(member.name).parts)
                if member.isdir():
                    out.mkdir(parents=True, exist_ok=False)
                else:
                    out.parent.mkdir(parents=True, exist_ok=True)
                    source = tar.extractfile(member)
                    if source is None:
                        raise ValueError
                    with source, out.open("xb") as output:
                        remaining = member.size
                        while remaining:
                            block = source.read(min(1024 * 1024, remaining))
                            if not block:
                                raise ValueError
                            output.write(block)
                            remaining -= len(block)
            node = stage / top / "bin" / "node"
            if not node.is_file() or node.is_symlink():
                raise ValueError
            return stage / top
    except (OSError, ValueError, tarfile.TarError):
        raise PrimeDevelopmentPreparationError() from None


def _publish_node(root: Path, archive: Path) -> Path:
    stage = Path(tempfile.mkdtemp(prefix=".node.", suffix=".stage", dir=root))
    try:
        extracted = _extract_node(archive, stage)
        target = root / ("node-" + _digest(archive)[:16])
        if target.exists():
            _remove_tree(stage)
            return target / "bin" / "node"
        os.replace(extracted, target)
        _fsync_directory(root)
        _remove_tree(stage)
        return target / "bin" / "node"
    except (OSError, PrimeDevelopmentPreparationError):
        if stage.exists():
            _remove_tree(stage)
        raise PrimeDevelopmentPreparationError() from None


def _run(argv: list[str], *, runner: Callable[..., object]) -> object:
    try:
        result = runner(
            argv,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            timeout=120,
            env={"PATH": "/usr/bin:/bin"},
        )
        output = getattr(result, "stdout", b"")
        if type(output) is not bytes or len(output) > _MAX_COMMAND_OUTPUT:
            raise ValueError
        return result
    except Exception:
        raise PrimeDevelopmentPreparationError() from None


def _arch(machine: str) -> str:
    value = {
        "x86_64": "amd64",
        "amd64": "amd64",
        "aarch64": "arm64",
        "arm64": "arm64",
    }.get(machine)
    if value is None:
        raise PrimeDevelopmentPreparationError()
    return value


def _context(repo: Path, arch: str, runner: Callable[..., object]) -> dict[str, object]:
    daemon = getattr(
        _run(["/usr/bin/docker", "info", "--format", "{{.ID}}"], runner=runner),
        "stdout",
        b"",
    )
    if type(daemon) is bytes:
        daemon = daemon.decode("ascii", "ignore").strip()
    if type(daemon) is not str or not daemon:
        raise PrimeDevelopmentPreparationError()
    return {
        "machine": os.environ.get("PRIME_ORB_MACHINE", ""),
        "uid": os.geteuid(),
        "worktree": str(repo),
        "platform": "linux/" + arch,
        "daemon": sha256(daemon.encode()).hexdigest(),
    }


def _node(
    root: Path,
    record: object,
    *,
    downloader: Callable[..., object],
    runner: Callable[..., object],
) -> Path:
    if (
        type(record) is not dict
        or set(record) != {"url", "archive_sha256", "node_sha256"}
        or not all(type(x) is str for x in record.values())
    ):
        raise PrimeDevelopmentPreparationError()
    archive = root / "node.tar.xz"
    if not archive.exists() or _digest(archive) != record["archive_sha256"]:
        try:
            data = downloader(record["url"], timeout=120).read(_MAX_ARCHIVE + 1)
            if (
                type(data) is not bytes
                or len(data) > _MAX_ARCHIVE
                or sha256(data).hexdigest() != record["archive_sha256"]
            ):
                raise ValueError
        except Exception:
            raise PrimeDevelopmentPreparationError() from None
        archive = _publish_bytes(root, "node.tar.xz", data)
    node = root / ("node-" + _digest(archive)[:16]) / "bin" / "node"
    if not node.exists() or _digest(node) != record["node_sha256"]:
        node = _publish_node(root, archive)
    if (
        _digest(node) != record["node_sha256"]
        or getattr(_run([str(node), "--version"], runner=runner), "stdout", b"")
        .decode("ascii", "ignore")
        .strip()
        != "v22.23.2"
    ):
        raise PrimeDevelopmentPreparationError()
    return node


def _gateway_identity(repo: Path, gateway: object) -> dict[str, str]:
    if type(gateway) is not dict or set(gateway) != {
        "inputs",
        "inputs_sha256",
        "outputs",
        "outputs_sha256",
    }:
        raise PrimeDevelopmentPreparationError()
    root = repo / "packages" / "typescript" / "prime-gateway"
    result = {}
    for kind in ("inputs", "outputs"):
        names = gateway[kind]
        if (
            type(names) is not list
            or names != sorted(set(names))
            or not all(
                type(name) is str
                and not Path(name).is_absolute()
                and ".." not in Path(name).parts
                for name in names
            )
        ):
            raise PrimeDevelopmentPreparationError()
        records = [{"path": name, "sha256": _digest(root / name)} for name in names]
        digest = sha256(
            json.dumps(records, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        if digest != gateway[kind + "_sha256"]:
            raise PrimeDevelopmentPreparationError()
        result[kind] = digest
    return result


def _identities(
    repo: Path,
    root: Path,
    lock: dict[str, object],
    arch: str,
    scenarios: tuple[str, ...],
    *,
    runner: Callable[..., object],
) -> dict[str, str]:
    nodes, source = lock.get("node"), lock.get("source")
    if (
        type(nodes) is not dict
        or type(nodes.get(arch)) is not dict
        or type(source) is not dict
    ):
        raise PrimeDevelopmentPreparationError()
    node = root / ("node-" + nodes[arch]["archive_sha256"][:16]) / "bin" / "node"
    if (
        _digest(node) != nodes[arch].get("node_sha256")
        or getattr(_run([str(node), "--version"], runner=runner), "stdout", b"")
        .decode("ascii", "ignore")
        .strip()
        != "v22.23.2"
    ):
        raise PrimeDevelopmentPreparationError()
    seccomp = root / "prime-development-seccomp.json"
    seccomp_lock = _seccomp_lock()
    if _digest(seccomp) != seccomp_lock["canonical_sha256"]:
        raise PrimeDevelopmentPreparationError()
    try:
        source_lock = PrimeSourceLock(**source)
        verify_prime_source_lock(repo / "3th-party" / "prime-agent", source_lock)
    except Exception:
        raise PrimeDevelopmentPreparationError() from None
    images = seccomp_lock["images"]
    if type(images) is not dict:
        raise PrimeDevelopmentPreparationError()
    result = {
        "node_sha256": _digest(node),
        "seccomp_sha256": _digest(seccomp),
        "source_lock_sha256": prime_source_lock_sha256(source_lock),
        **_gateway_identity(repo, lock.get("gateway")),
    }
    for selected in sorted(set(scenarios)):
        image = images.get(selected)
        if (
            type(image) is not list
            or len(image) != 2
            or not all(type(value) is str for value in image)
        ):
            raise PrimeDevelopmentPreparationError()
        result["image_" + selected] = sha256(
            json.dumps(image, separators=(",", ":")).encode()
        ).hexdigest()
    return result


def _receipt(
    context: dict[str, object],
    lock: dict[str, object],
    scenarios: tuple[str, ...],
    identities: dict[str, str],
) -> dict[str, object]:
    return {
        "format": "asterion.prime-development-receipt/v1",
        "context": context,
        "lock_sha256": sha256(
            json.dumps(lock, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest(),
        "scenarios": sorted(set(scenarios)),
        "identities": identities,
    }


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
    lock, repo, arch = _lock(), repo_root.resolve(), _arch(platform_machine())
    root = _root(repo)
    nodes = lock.get("node")
    if type(nodes) is not dict:
        raise PrimeDevelopmentPreparationError()
    if emit:
        emit("source", "started")
    node = _node(root, nodes.get(arch), downloader=downloader, runner=runner)
    seccomp_lock = _seccomp_lock()
    profile = _bytes("prime-development-seccomp.json")
    if (
        sha256(profile).hexdigest() != seccomp_lock["canonical_sha256"]
        or sha256(_bytes("moby-profiles-LICENSE.txt")).hexdigest()
        != seccomp_lock["license_sha256"]
    ):
        raise PrimeDevelopmentPreparationError()
    _publish_bytes(root, "prime-development-seccomp.json", profile)
    identities = _identities(repo, root, lock, arch, scenarios, runner=runner)
    _publish_bytes(
        root,
        "receipt.json",
        json.dumps(
            _receipt(_context(repo, arch, runner), lock, scenarios, identities),
            sort_keys=True,
            separators=(",", ":"),
        ).encode(),
    )
    if emit:
        emit("source", "succeeded")
    return {
        s: PrimeDevelopmentPaths(
            root,
            node,
            root / "prime-development-seccomp.json",
            repo / "packages" / "typescript" / "prime-gateway",
            repo / "3th-party" / "prime-agent",
        )
        for s in scenarios
    }


def resolve_prepared_prime_development(
    repo_root: Path,
    scenario: str,
    *,
    runner: Callable[..., object] = subprocess.run,
    platform_machine: Callable[[], str] = _platform.machine,
) -> PrimeDevelopmentPaths:
    if (
        type(repo_root) is not Path
        or type(scenario) is not str
        or scenario not in _SCENARIOS
    ):
        raise PrimeDevelopmentPreparationError()
    lock, repo, arch = _lock(), repo_root.resolve(), _arch(platform_machine())
    root = _root(repo)
    try:
        receipt_path = root / "receipt.json"
        if receipt_path.is_symlink() or not stat.S_ISREG(receipt_path.lstat().st_mode):
            raise ValueError
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        scenarios = receipt.get("scenarios") if type(receipt) is dict else None
        if (
            type(scenarios) is not list
            or scenarios != sorted(set(scenarios))
            or any(type(s) is not str or s not in _SCENARIOS for s in scenarios)
        ):
            raise ValueError
        expected = _receipt(
            _context(repo, arch, runner),
            lock,
            tuple(scenarios),
            _identities(repo, root, lock, arch, tuple(scenarios), runner=runner),
        )
        if receipt != expected or scenario not in scenarios:
            raise ValueError
    except (
        OSError,
        UnicodeError,
        json.JSONDecodeError,
        ValueError,
        PrimeDevelopmentPreparationError,
    ):
        raise PrimeDevelopmentPreparationError() from None
    return PrimeDevelopmentPaths(
        root,
        root / ("node-" + lock["node"][arch]["archive_sha256"][:16]) / "bin" / "node",  # type: ignore[index]
        root / "prime-development-seccomp.json",
        repo / "packages" / "typescript" / "prime-gateway",
        repo / "3th-party" / "prime-agent",
    )
