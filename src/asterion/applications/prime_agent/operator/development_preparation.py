"""Private, reproducible Prime development preparation."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from importlib import resources
import json
import os
from pathlib import Path
import platform as _platform
import selectors
import stat
import subprocess
import tarfile
import tempfile
import time
from typing import Callable, Mapping
from urllib.request import urlopen

from asterion.applications.prime_agent.source_lock import (
    PrimeSourceLock,
    prime_source_lock_sha256,
    verify_prime_source_lock,
)
from asterion.applications.prime_agent.operator.p7_resource_lock import (
    verify_p7_development_resources,
)
from asterion.applications.prime_agent.operator.p7_runtime_lock import (
    verify_p7_development_runtime,
)
from asterion.applications.prime_agent.operator.p7_development_workload import (
    P7_DEVELOPMENT_ARC_AGI_WHEEL_SHA256,
    P7_DEVELOPMENT_ARCENGINE_WHEEL_SHA256,
)

_MESSAGE = "Prime development preparation is unavailable"
_SCENARIOS = frozenset({"p1", "p2", "p3", "p4", "p5", "p6", "p7"})
_MAX_ARCHIVE = 128 * 1024 * 1024
_MAX_EXTRACTED = 512 * 1024 * 1024
# Official locked Node archives contain 5,866 entries; retain a finite cap above it.
_MAX_NODE_ARCHIVE_MEMBERS = 16_384
_MAX_COMMAND_OUTPUT = 4096
_COMMAND_TIMEOUT = 120
_COMMAND_READ_CHUNK = 1024
_DOWNLOAD_TIMEOUT = 120
_DOWNLOAD_IO_TIMEOUT = 10
_DOWNLOAD_CHUNK = 1024 * 1024
_SECCOMP_LOCK_FORMAT = "asterion.prime-development-seccomp-lock/v1"
_SECCOMP_LOCK_PROVENANCE = {
    "format": _SECCOMP_LOCK_FORMAT,
    "tag": "seccomp/v0.2.3",
    "commit": "836ae4d37ef2ec995c77c99fc55f5b5f3af3a897",
    "raw_sha256": "536529b665dd0972c37bfb569f5d4ac8a53592e7b00752bc39ff063ca9864c74",
    "canonical_sha256": "9da637d2ab0a204fcbd91bd88f1be9e004a3acab61c571a9f5b8870e588a17d2",
    "license_sha256": "cfc7749b96f63bd31c3c42b5c471bf756814053e847c10f3eb003417bc523d30",
    "platforms": ["linux/amd64", "linux/arm64"],
    "images": {
        "p1": [
            "asterion-p1b-development:20260906",
            "sha256:acd139a02dbb80277d0a6c78575f1ddcbdd8042c8a7a82b28416a638cab58657",
        ],
        "p2": [
            "asterion-p2-development:20260906",
            "sha256:7d97b51a21bfffe6caa574063294f72205c60b05d8650fab8c70fdf661921c33",
        ],
        "p3": [
            "asterion-p3-development:20260906",
            "sha256:68ffbf922d6dae7ca7c79294c7dceb680bceda599d3cfd0bc8bb0323a9d5a243",
        ],
        "p4": [
            "asterion-p1b-development:20260906",
            "sha256:acd139a02dbb80277d0a6c78575f1ddcbdd8042c8a7a82b28416a638cab58657",
        ],
        "p5": [
            "asterion-p3-development:20260906",
            "sha256:68ffbf922d6dae7ca7c79294c7dceb680bceda599d3cfd0bc8bb0323a9d5a243",
        ],
        "p6": [
            "asterion-p3-development:20260906",
            "sha256:68ffbf922d6dae7ca7c79294c7dceb680bceda599d3cfd0bc8bb0323a9d5a243",
        ],
        "p7": [
            "asterion-p3-development:20260906",
            "sha256:68ffbf922d6dae7ca7c79294c7dceb680bceda599d3cfd0bc8bb0323a9d5a243",
        ],
    },
}
_LOCKED_IMAGES = {
    "p1": (
        "asterion-p1b-development:20260906",
        "sha256:acd139a02dbb80277d0a6c78575f1ddcbdd8042c8a7a82b28416a638cab58657",
        "image/Dockerfile",
        "src/asterion/applications/prime_agent/operator",
        ("linux/amd64", "linux/arm64"),
    ),
    "p2": (
        "asterion-p2-development:20260906",
        "sha256:7d97b51a21bfffe6caa574063294f72205c60b05d8650fab8c70fdf661921c33",
        "p2_development_image/Dockerfile",
        "src/asterion/applications/prime_agent/operator",
        ("linux/amd64", "linux/arm64"),
    ),
    "p3": (
        "asterion-p3-development:20260906",
        "sha256:68ffbf922d6dae7ca7c79294c7dceb680bceda599d3cfd0bc8bb0323a9d5a243",
        "p3_development_image/Dockerfile",
        "src/asterion/applications/prime_agent/operator",
        ("linux/amd64", "linux/arm64"),
    ),
    "p4": (
        "asterion-p1b-development:20260906",
        "sha256:acd139a02dbb80277d0a6c78575f1ddcbdd8042c8a7a82b28416a638cab58657",
        "image/Dockerfile",
        "src/asterion/applications/prime_agent/operator",
        ("linux/amd64", "linux/arm64"),
    ),
    "p5": (
        "asterion-p3-development:20260906",
        "sha256:68ffbf922d6dae7ca7c79294c7dceb680bceda599d3cfd0bc8bb0323a9d5a243",
        "p3_development_image/Dockerfile",
        "src/asterion/applications/prime_agent/operator",
        ("linux/amd64", "linux/arm64"),
    ),
    "p6": (
        "asterion-p3-development:20260906",
        "sha256:68ffbf922d6dae7ca7c79294c7dceb680bceda599d3cfd0bc8bb0323a9d5a243",
        "p3_development_image/Dockerfile",
        "src/asterion/applications/prime_agent/operator",
        ("linux/amd64", "linux/arm64"),
    ),
    "p7": (
        "asterion-p3-development:20260906",
        "sha256:68ffbf922d6dae7ca7c79294c7dceb680bceda599d3cfd0bc8bb0323a9d5a243",
        "p3_development_image/Dockerfile",
        "src/asterion/applications/prime_agent/operator",
        ("linux/amd64", "linux/arm64"),
    ),
}


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


def _seccomp_lock(raw: bytes | None = None) -> dict[str, object]:
    try:
        value = json.loads(
            _bytes("prime-development-seccomp-lock.json") if raw is None else raw
        )
        if type(value) is not dict or value != _SECCOMP_LOCK_PROVENANCE:
            raise ValueError
    except (UnicodeError, json.JSONDecodeError, ValueError, OSError):
        raise PrimeDevelopmentPreparationError()
    return value


def _validated_seccomp_lock(
    preparation_lock: dict[str, object], arch: str
) -> dict[str, object]:
    binding = preparation_lock.get("seccomp")
    if (
        type(binding) is not dict
        or set(binding) != {"lock_sha256_by_arch"}
        or type(binding.get("lock_sha256_by_arch")) is not dict
        or set(binding["lock_sha256_by_arch"]) != {"amd64", "arm64"}
        or any(
            type(digest) is not str or len(digest) != 64
            for digest in binding["lock_sha256_by_arch"].values()
        )
        or arch not in binding["lock_sha256_by_arch"]
    ):
        raise PrimeDevelopmentPreparationError()
    try:
        raw = _bytes("prime-development-seccomp-lock.json")
    except OSError:
        raise PrimeDevelopmentPreparationError() from None
    if sha256(raw).hexdigest() != binding["lock_sha256_by_arch"][arch]:
        raise PrimeDevelopmentPreparationError()
    return _seccomp_lock(raw)


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


def _extract_node(archive: Path, stage: Path, expected: str, node_sha256: str) -> Path:
    try:
        with tarfile.open(archive, "r:xz") as tar:
            members = tar.getmembers()
            found = []
            names: set[str] = set()
            if not members or len(members) > _MAX_NODE_ARCHIVE_MEMBERS:
                raise ValueError
            for member in members:
                parts = Path(member.name).parts
                if (
                    Path(member.name).is_absolute()
                    or ".." in parts
                    or member.name in names
                ):
                    raise ValueError
                names.add(member.name)
                if member.name == expected:
                    found.append(member)
            if len(found) != 1:
                raise ValueError
            member = found[0]
            if (
                not member.isreg()
                or member.issym()
                or member.islnk()
                or member.isdev()
                or member.size < 0
                or member.size > _MAX_EXTRACTED
            ):
                raise ValueError
            output = stage / "bin" / "node"
            output.parent.mkdir(mode=0o700)
            fd = os.open(
                output, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o555
            )
            try:
                source = tar.extractfile(member)
                if source is None:
                    raise ValueError
                with source, os.fdopen(fd, "wb", closefd=False) as stream:
                    remaining = member.size
                    while remaining:
                        block = source.read(min(1024 * 1024, remaining))
                        if not block:
                            raise ValueError
                        stream.write(block)
                        remaining -= len(block)
                    stream.flush()
                    os.fsync(stream.fileno())
            finally:
                os.close(fd)
            os.chmod(output, 0o555)
            if _digest(output) != node_sha256:
                raise ValueError
            _fsync_directory(output.parent)
            _fsync_directory(stage)
            return stage
    except (OSError, ValueError, tarfile.TarError):
        raise PrimeDevelopmentPreparationError() from None


def _publish_node(
    root: Path,
    archive: Path,
    expected: str | None = None,
    node_sha256: str | None = None,
) -> Path:
    target = root / ("node-" + _digest(archive)[:16])
    if target.exists():
        return target / "bin" / "node"
    if expected is None or node_sha256 is None:
        raise PrimeDevelopmentPreparationError()
    stage = Path(tempfile.mkdtemp(prefix=".node.", suffix=".stage", dir=root))
    try:
        extracted = _extract_node(archive, stage, expected, node_sha256)
        os.replace(extracted, target)
        _fsync_directory(root)
        _remove_tree(stage)
        return target / "bin" / "node"
    except (OSError, PrimeDevelopmentPreparationError):
        if stage.exists():
            _remove_tree(stage)
        raise PrimeDevelopmentPreparationError() from None


def _streaming_run(argv: list[str]) -> subprocess.CompletedProcess[bytes]:
    process: subprocess.Popen[bytes] | None = None
    selector = selectors.DefaultSelector()
    streams: dict[object, bytearray] = {}
    try:
        process = subprocess.Popen(
            argv,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env={"PATH": "/usr/bin:/bin"},
        )
        if process.stdout is None or process.stderr is None:
            raise ValueError
        for stream in (process.stdout, process.stderr):
            os.set_blocking(stream.fileno(), False)
            streams[stream] = bytearray()
            selector.register(stream, selectors.EVENT_READ)
        deadline = time.monotonic() + _COMMAND_TIMEOUT
        while selector.get_map():
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError
            events = selector.select(min(remaining, 0.1))
            for key, _ in events:
                stream = key.fileobj
                chunk = os.read(stream.fileno(), _COMMAND_READ_CHUNK)
                if not chunk:
                    selector.unregister(stream)
                    continue
                streams[stream].extend(chunk)
                if (
                    len(streams[stream]) > _MAX_COMMAND_OUTPUT
                    or sum(len(value) for value in streams.values())
                    > _MAX_COMMAND_OUTPUT
                ):
                    raise ValueError
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError
        returncode = process.wait(timeout=remaining)
        if returncode:
            raise ValueError
        return subprocess.CompletedProcess(
            argv,
            returncode,
            stdout=bytes(streams[process.stdout]),
            stderr=bytes(streams[process.stderr]),
        )
    finally:
        if process is not None and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=1)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=1)
        selector.close()
        for stream in streams:
            stream.close()


def _run(argv: list[str], *, runner: Callable[..., object]) -> object:
    try:
        if runner is subprocess.run:
            return _streaming_run(argv)
        result = runner(
            argv,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=_COMMAND_TIMEOUT,
            env={"PATH": "/usr/bin:/bin"},
        )
        output = getattr(result, "stdout", b"")
        errors = getattr(result, "stderr", b"")
        if (
            type(output) is not bytes
            or type(errors) is not bytes
            or len(output) > _MAX_COMMAND_OUTPUT
            or len(errors) > _MAX_COMMAND_OUTPUT
            or len(output) + len(errors) > _MAX_COMMAND_OUTPUT
        ):
            raise ValueError
        return result
    except Exception:
        raise PrimeDevelopmentPreparationError() from None


def _set_download_timeout(response: object, timeout: float) -> None:
    candidates = [response]
    for attribute in ("fp", "raw", "_sock"):
        candidates.append(getattr(candidates[-1], attribute, None))
    for candidate in candidates:
        settimeout = getattr(candidate, "settimeout", None)
        if callable(settimeout):
            try:
                settimeout(timeout)
            except (OSError, ValueError):
                pass
            return


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
            deadline = time.monotonic() + _DOWNLOAD_TIMEOUT
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError
            response = downloader(
                record["url"], timeout=min(_DOWNLOAD_IO_TIMEOUT, remaining)
            )
            data = bytearray()
            try:
                while True:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise TimeoutError
                    _set_download_timeout(
                        response, min(_DOWNLOAD_IO_TIMEOUT, remaining)
                    )
                    block = response.read(
                        min(_DOWNLOAD_CHUNK, _MAX_ARCHIVE + 1 - len(data))
                    )
                    if time.monotonic() >= deadline:
                        raise TimeoutError
                    if type(block) is not bytes:
                        raise ValueError
                    if not block:
                        break
                    if len(data) + len(block) > _MAX_ARCHIVE:
                        raise ValueError
                    data.extend(block)
            finally:
                close = getattr(response, "close", None)
                if callable(close):
                    close()
            if sha256(data).hexdigest() != record["archive_sha256"]:
                raise ValueError
        except Exception:
            raise PrimeDevelopmentPreparationError() from None
        archive = _publish_bytes(root, "node.tar.xz", bytes(data))
    node = root / ("node-" + _digest(archive)[:16]) / "bin" / "node"
    if not node.exists() or _digest(node) != record["node_sha256"]:
        suffix = {"linux-x64.tar.xz": "x64", "linux-arm64.tar.xz": "arm64"}
        selected = next(
            (value for key, value in suffix.items() if record["url"].endswith(key)),
            None,
        )
        if selected is None:
            raise PrimeDevelopmentPreparationError()
        node = _publish_node(
            root,
            archive,
            "node-v22.23.2-linux-" + selected + "/bin/node",
            record["node_sha256"],
        )
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
    return {
        "inputs": _gateway_aggregate(repo, gateway, "inputs"),
        "outputs": _gateway_aggregate(repo, gateway, "outputs"),
    }


def _gateway_record(gateway: object) -> dict[str, object]:
    if type(gateway) is not dict or set(gateway) != {
        "inputs",
        "inputs_sha256",
        "outputs",
        "outputs_sha256",
    }:
        raise PrimeDevelopmentPreparationError()
    for kind in ("inputs", "outputs"):
        names, digest = gateway[kind], gateway[kind + "_sha256"]
        if (
            type(names) is not list
            or names != sorted(set(names))
            or type(digest) is not str
            or len(digest) != 64
            or any(char not in "0123456789abcdef" for char in digest)
            or not all(
                type(name) is str
                and not Path(name).is_absolute()
                and ".." not in Path(name).parts
                for name in names
            )
        ):
            raise PrimeDevelopmentPreparationError()
    return gateway


def _aggregate(root: Path, names: list[str]) -> str:
    records = [{"path": name, "sha256": _digest(root / name)} for name in names]
    return sha256(
        json.dumps(records, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _gateway_aggregate(repo: Path, gateway: object, kind: str) -> str:
    gateway = _gateway_record(gateway)
    if kind not in {"inputs", "outputs"}:
        raise PrimeDevelopmentPreparationError()
    names = gateway[kind]
    digest = _aggregate(repo / "packages" / "typescript" / "prime-gateway", names)
    if digest != gateway[kind + "_sha256"]:
        raise PrimeDevelopmentPreparationError()
    return digest


def _prepare_gateway(
    repo: Path, gateway: object, *, runner: Callable[..., object]
) -> None:
    """Build only reviewed inputs; a changed input is never a build authority."""
    _gateway_record(gateway)
    _gateway_aggregate(repo, gateway, "inputs")
    try:
        _gateway_aggregate(repo, gateway, "outputs")
        return
    except PrimeDevelopmentPreparationError:
        pass
    _run(
        ["npm", "--prefix", "packages/typescript/prime-gateway", "run", "build"],
        runner=runner,
    )
    _gateway_aggregate(repo, gateway, "outputs")


def _image_record(record: object, scenario: str, platform: str) -> dict[str, object]:
    if (
        type(record) is not dict
        or set(record) != {"tag", "digest", "dockerfile", "context", "platforms"}
        or type(record["tag"]) is not str
        or type(record["digest"]) is not str
        or len(record["digest"]) != 71
        or not record["digest"].startswith("sha256:")
        or any(char not in "0123456789abcdef" for char in record["digest"][7:])
        or any(
            type(record[name]) is not str
            or Path(record[name]).is_absolute()
            or ".." in Path(record[name]).parts
            for name in ("dockerfile", "context")
        )
        or type(record["platforms"]) is not list
        or record["platforms"] != sorted(set(record["platforms"]))
        or platform not in record["platforms"]
    ):
        raise PrimeDevelopmentPreparationError()
    if record != _locked_image_record(scenario):
        raise PrimeDevelopmentPreparationError()
    return record


def _locked_image_record(scenario: str) -> dict[str, object]:
    try:
        tag, digest, dockerfile, context, platforms = _LOCKED_IMAGES[scenario]
    except (KeyError, ValueError):
        raise PrimeDevelopmentPreparationError() from None
    return {
        "tag": tag,
        "digest": digest,
        "dockerfile": dockerfile,
        "context": context,
        "platforms": list(platforms),
    }


def _inspect_image(tag: str, *, runner: Callable[..., object]) -> str | None:
    argv = [
        "/usr/bin/docker",
        "--host",
        "unix:///var/run/docker.sock",
        "image",
        "inspect",
        "--format",
        "{{.Id}}",
        tag,
    ]
    try:
        result = runner(
            argv,
            check=False,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=_COMMAND_TIMEOUT,
            env={"PATH": "/usr/bin:/bin"},
        )
        stdout, stderr = getattr(result, "stdout", b""), getattr(result, "stderr", b"")
        if (
            type(stdout) is not bytes
            or type(stderr) is not bytes
            or len(stdout) + len(stderr) > _MAX_COMMAND_OUTPUT
        ):
            raise ValueError
        if getattr(result, "returncode", 0) != 0:
            return None
        value = stdout.decode("ascii", "strict")
        return value[:-1] if value.endswith("\n") and "\n" not in value[:-1] else None
    except Exception:
        raise PrimeDevelopmentPreparationError() from None


def _prepare_image(
    repo: Path,
    scenario: str,
    record: object,
    platform: str,
    *,
    runner: Callable[..., object],
) -> None:
    image = _image_record(record, scenario, platform)
    tag, digest = image["tag"], image["digest"]
    if _inspect_image(tag, runner=runner) == digest:
        return
    _run(
        [
            "/usr/bin/docker",
            "--host",
            "unix:///var/run/docker.sock",
            "build",
            "--pull=false",
            "--platform",
            platform,
            "--file",
            str(repo / image["dockerfile"]),
            "--tag",
            tag,
            str(repo / image["context"]),
        ],
        runner=runner,
    )
    if _inspect_image(tag, runner=runner) != digest:
        raise PrimeDevelopmentPreparationError()


def _p7_identities(repo: Path, record: object) -> dict[str, str]:
    if (
        type(record) is not dict
        or set(record) != {"external_root", "resource_sha256", "runtime_wheels"}
        or record["external_root"] != "external-prime/arc-agi-3"
        or type(record["resource_sha256"]) is not str
        or type(record["runtime_wheels"]) is not dict
        or set(record["runtime_wheels"]) != {"arc_agi", "arcengine"}
        or any(
            type(value) is not str
            or len(value) != 71
            or not value.startswith("sha256:")
            for value in record["runtime_wheels"].values()
        )
        or record["runtime_wheels"]
        != {
            "arc_agi": P7_DEVELOPMENT_ARC_AGI_WHEEL_SHA256,
            "arcengine": P7_DEVELOPMENT_ARCENGINE_WHEEL_SHA256,
        }
    ):
        raise PrimeDevelopmentPreparationError()
    try:
        external = repo.parent / record["external_root"]
        resources = verify_p7_development_resources(
            external / "environment_files/ls20/9607627b"
        )
        runtime = verify_p7_development_runtime(external)
        if resources.resource_sha256 != record["resource_sha256"]:
            raise ValueError
        return {
            "p7_resource_sha256": resources.resource_sha256,
            "p7_runtime_sha256": runtime.runtime_sha256,
        }
    except Exception:
        raise PrimeDevelopmentPreparationError() from None


def _identities(
    repo: Path,
    root: Path,
    lock: dict[str, object],
    arch: str,
    scenarios: tuple[str, ...],
    seccomp_lock: dict[str, object],
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
    if _digest(seccomp) != seccomp_lock["canonical_sha256"]:
        raise PrimeDevelopmentPreparationError()
    try:
        source_lock = PrimeSourceLock(**source)
        verify_prime_source_lock(repo / "3th-party" / "prime-agent", source_lock)
    except Exception:
        raise PrimeDevelopmentPreparationError() from None
    images = lock.get("images")
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
        image = _image_record(image, selected, "linux/" + arch)
        if _inspect_image(image["tag"], runner=runner) != image["digest"]:
            raise PrimeDevelopmentPreparationError()
        result["image_" + selected] = sha256(
            json.dumps([image["tag"], image["digest"]], separators=(",", ":")).encode()
        ).hexdigest()
    if "p7" in scenarios:
        result.update(_p7_identities(repo, lock.get("p7")))
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


def _invalidate_receipt(root: Path) -> None:
    """A failed final recheck cannot leave a receipt eligible for reuse."""
    try:
        receipt = root / "receipt.json"
        details = receipt.lstat()
        if receipt.is_symlink() or not stat.S_ISREG(details.st_mode):
            return
        receipt.unlink()
        _fsync_directory(root)
    except OSError:
        return


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
        not isinstance(repo_root, Path)
        or not scenarios
        or any(type(s) is not str or s not in _SCENARIOS for s in scenarios)
    ):
        raise PrimeDevelopmentPreparationError()
    lock, repo, arch = _lock(), repo_root.resolve(), _arch(platform_machine())
    seccomp_lock = _validated_seccomp_lock(lock, arch)
    root = _root(repo)
    nodes = lock.get("node")
    if type(nodes) is not dict:
        raise PrimeDevelopmentPreparationError()
    try:
        if emit:
            emit("gateway", "started")
        _prepare_gateway(repo, lock.get("gateway"), runner=runner)
        if emit:
            emit("gateway", "succeeded")
    except PrimeDevelopmentPreparationError:
        if emit:
            emit("gateway", "failed")
        raise
    try:
        if emit:
            emit("image", "started")
        images = lock.get("images")
        if type(images) is not dict:
            raise PrimeDevelopmentPreparationError()
        for scenario in sorted(set(scenarios)):
            _prepare_image(
                repo, scenario, images.get(scenario), "linux/" + arch, runner=runner
            )
        if emit:
            emit("image", "succeeded")
    except PrimeDevelopmentPreparationError:
        if emit:
            emit("image", "failed")
        raise
    try:
        if emit:
            emit("source", "started")
        node = _node(root, nodes.get(arch), downloader=downloader, runner=runner)
        profile = _bytes("prime-development-seccomp.json")
        if (
            sha256(profile).hexdigest() != seccomp_lock["canonical_sha256"]
            or sha256(_bytes("moby-profiles-LICENSE.txt")).hexdigest()
            != seccomp_lock["license_sha256"]
        ):
            raise PrimeDevelopmentPreparationError()
        _publish_bytes(root, "prime-development-seccomp.json", profile)
        identities = _identities(
            repo, root, lock, arch, scenarios, seccomp_lock, runner=runner
        )
    except Exception:
        if emit:
            emit("source", "failed")
        _invalidate_receipt(root)
        raise PrimeDevelopmentPreparationError() from None
    try:
        _publish_bytes(
            root,
            "receipt.json",
            json.dumps(
                _receipt(_context(repo, arch, runner), lock, scenarios, identities),
                sort_keys=True,
                separators=(",", ":"),
            ).encode(),
        )
        # Recheck the receipt and all selected identities before handing it back.
        resolve_prepared_prime_development(
            repo, scenarios[0], runner=runner, platform_machine=platform_machine
        )
    except Exception:
        _invalidate_receipt(root)
        if emit:
            emit("source", "failed")
        raise PrimeDevelopmentPreparationError() from None
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
        not isinstance(repo_root, Path)
        or type(scenario) is not str
        or scenario not in _SCENARIOS
    ):
        raise PrimeDevelopmentPreparationError()
    lock, repo, arch = _lock(), repo_root.resolve(), _arch(platform_machine())
    seccomp_lock = _validated_seccomp_lock(lock, arch)
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
            _identities(
                repo, root, lock, arch, tuple(scenarios), seccomp_lock, runner=runner
            ),
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
