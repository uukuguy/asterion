"""Production-only host authority for the fixed Prime P1 application.

The factory performs static, side-effect-free readiness checks.  It constructs
only the concrete Docker CLI transport and concrete model provider service; it
does not contact either backend.  The resulting capability may authorize one
run and cannot itself turn provider-free traces into successful evidence.
"""

from __future__ import annotations

from collections.abc import Mapping
from contextlib import asynccontextmanager
from dataclasses import dataclass
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import stat
from typing import NoReturn, cast

from dotenv import dotenv_values

from asterion.applications.prime_agent.operator.docker_cli import (
    DockerCliEngineTransport,
    _ProductionAttachRunner,
    _ProductionRunner,
)
from asterion.applications.prime_agent.operator.docker_worker import (
    DockerRestrictedWorkerService,
)
from asterion.applications.prime_agent.operator.model_session_host import (
    _PrimeBoundedModelSessionService,
    _private_config_from_values,
)
from asterion.services.registry import (
    HostServiceFactoryBinding,
    HostServiceFactoryContext,
)


_CAPABILITY_ID = "prime.ipython-production"
_PROVIDER_ID = "prime-agent"
_APPLICATION_ID = "prime.ipython-coding"
_APPLICATION_VERSION = "1.0.0"
_PATH_KEYS = (
    "ASTERION_PRIME_P1_DOCKER_EXECUTABLE",
    "ASTERION_PRIME_P1_DOCKER_SOCKET",
    "ASTERION_PRIME_P1_SECCOMP_PROFILE",
)
_IMAGE_KEY = "ASTERION_PRIME_P1_IMAGE_DIGEST"
_DIGEST = re.compile(r"sha256:[0-9a-f]{64}\Z")
_AUTHORITY_SEAL = object()
_CAPABILITY_SEAL = object()
_SECCOMP_CAP = 64 * 1024
_EXECUTABLE_CAP = 256 * 1024 * 1024


class PrimeP1ProductionHostError(ValueError):
    """Public-safe failure of the selected P1 production host."""

    def __init__(self, *_: object) -> None:
        super().__init__("prime P1 production host is unavailable")


@dataclass(frozen=True, repr=False)
class _ResourceIdentity:
    path: Path
    device: int
    inode: int
    mode: int
    size: int
    sha256: str | None

    def __repr__(self) -> str:
        return "_ResourceIdentity(redacted)"


@dataclass(frozen=True, repr=False)
class _ProductionComponents:
    worker: DockerRestrictedWorkerService
    models: _PrimeBoundedModelSessionService
    resources: tuple[_ResourceIdentity, ...]
    image_digest: str

    def __repr__(self) -> str:
        return "_ProductionComponents(redacted)"


class PrimeP1ProductionRunAuthority:
    """Opaque one-run authority bound to the selected P1 host capability."""

    __slots__ = ("_capability", "_consumed", "_run_id")

    def __init__(
        self,
        capability: object = None,
        run_id: object = None,
        *,
        _seal: object = None,
    ) -> None:
        if (
            _seal is not _AUTHORITY_SEAL
            or type(capability) is not PrimeP1ProductionHostCapability
            or type(run_id) is not str
            or re.fullmatch(r"[a-z][a-z0-9.-]*", run_id) is None
        ):
            _unavailable()
        self._capability = cast(PrimeP1ProductionHostCapability, capability)
        self._run_id = cast(str, run_id)
        self._consumed = False

    def __repr__(self) -> str:
        return "PrimeP1ProductionRunAuthority(redacted)"


class PrimeP1ProductionHostCapability:
    """Selected-host capability which can authorize exactly one P1 run."""

    __slots__ = ("_active", "_authorized", "_components")

    def __init__(self, components: object = None, *, _seal: object = None) -> None:
        if _seal is not _CAPABILITY_SEAL or type(components) is not _ProductionComponents:
            _unavailable()
        self._components = cast(_ProductionComponents, components)
        self._active = True
        self._authorized = False

    def __repr__(self) -> str:
        return "PrimeP1ProductionHostCapability(redacted)"

    def authorize(self, run_id: str) -> PrimeP1ProductionRunAuthority:
        if not self._active or self._authorized:
            _unavailable()
        authority = PrimeP1ProductionRunAuthority(
            self, run_id, _seal=_AUTHORITY_SEAL
        )
        self._authorized = True
        return authority

    def _close(self) -> None:
        self._active = False


def _consume_production_authority(
    authority: object,
) -> tuple[str, _ProductionComponents]:
    if type(authority) is not PrimeP1ProductionRunAuthority:
        _unavailable()
    typed = cast(PrimeP1ProductionRunAuthority, authority)
    capability = typed._capability
    if (
        typed._consumed
        or type(capability) is not PrimeP1ProductionHostCapability
        or not capability._active
        or not capability._authorized
    ):
        _unavailable()
    typed._consumed = True
    _revalidate_resources(capability._components.resources)
    return typed._run_id, capability._components


def create_prime_p1_production_factory(
    *, repo_root: Path, environment: Mapping[str, str] | None = None
) -> HostServiceFactoryBinding:
    """Create the selected-only factory; caller mappings never carry secrets."""
    del environment
    root = Path(repo_root).resolve()

    @asynccontextmanager
    async def factory(context: HostServiceFactoryContext):
        _validate_context(context)
        capability = _build_capability(root / ".env")
        try:
            yield capability
        finally:
            capability._close()

    return HostServiceFactoryBinding(
        capability_id=_CAPABILITY_ID,
        option_names=(),
        factory=factory,
    )


def create_host_service_factory() -> HostServiceFactoryBinding:
    """Installed entry point for the exact selected Prime application."""
    return create_prime_p1_production_factory(repo_root=Path.cwd())


def _validate_context(context: object) -> None:
    if (
        type(context) is not HostServiceFactoryContext
        or context.provider_id != _PROVIDER_ID
        or context.application_id != _APPLICATION_ID
        or context.application_version != _APPLICATION_VERSION
        or context.capability_id != _CAPABILITY_ID
        or dict(context.options)
    ):
        _unavailable()


def _build_capability(env_path: Path) -> PrimeP1ProductionHostCapability:
    try:
        env_identity = _regular_resource(
            env_path, executable=False, digest_limit=_SECCOMP_CAP
        )
        values = dotenv_values(env_path)
        paths = tuple(_absolute_path(values.get(key)) for key in _PATH_KEYS)
        docker_identity = _regular_resource(
            paths[0], executable=True, digest_limit=_EXECUTABLE_CAP
        )
        socket_identity = _socket_resource(paths[1])
        seccomp_identity = _seccomp_resource(paths[2])
        image_digest = values.get(_IMAGE_KEY)
        if type(image_digest) is not str or _DIGEST.fullmatch(image_digest) is None:
            raise ValueError
        model_config = _private_config_from_values(values)
        transport = DockerCliEngineTransport(
            docker_executable=str(paths[0]),
            socket_path=str(paths[1]),
            seccomp_profile=str(paths[2]),
        )
        if (
            type(transport._runner) is not _ProductionRunner  # noqa: SLF001
            or type(transport._attach_runner) is not _ProductionAttachRunner  # noqa: SLF001
        ):
            raise ValueError
        components = _ProductionComponents(
            worker=DockerRestrictedWorkerService(
                image_digest=image_digest, transport=transport
            ),
            models=_PrimeBoundedModelSessionService(model_config),
            resources=(
                env_identity,
                docker_identity,
                socket_identity,
                seccomp_identity,
            ),
            image_digest=image_digest,
        )
        return PrimeP1ProductionHostCapability(
            components, _seal=_CAPABILITY_SEAL
        )
    except BaseException:
        _unavailable()


def _absolute_path(value: object) -> Path:
    if type(value) is not str or not value:
        raise ValueError
    path = Path(value)
    if (
        not path.is_absolute()
        or str(path) != value
        or str(path.resolve(strict=False)) != value
        or any(part in {"", ".", ".."} for part in path.parts[1:])
    ):
        raise ValueError
    _reject_symlink_ancestry(path)
    return path


def _reject_symlink_ancestry(path: Path) -> None:
    current = Path(path.anchor)
    for part in path.parts[1:]:
        current /= part
        details = os.lstat(current)
        if stat.S_ISLNK(details.st_mode):
            raise ValueError


def _regular_resource(
    path: Path, *, executable: bool, digest_limit: int
) -> _ResourceIdentity:
    _reject_symlink_ancestry(path)
    details = os.lstat(path)
    if (
        not stat.S_ISREG(details.st_mode)
        or executable and (details.st_mode & 0o111 == 0 or not os.access(path, os.X_OK))
    ):
        raise ValueError
    if details.st_size <= 0 or details.st_size > digest_limit:
        raise ValueError
    digest = _regular_file_digest(path, details, digest_limit)
    return _ResourceIdentity(
        path,
        details.st_dev,
        details.st_ino,
        details.st_mode,
        details.st_size,
        digest,
    )


def _socket_resource(path: Path) -> _ResourceIdentity:
    _reject_symlink_ancestry(path)
    details = os.lstat(path)
    if not stat.S_ISSOCK(details.st_mode):
        raise ValueError
    return _ResourceIdentity(
        path, details.st_dev, details.st_ino, details.st_mode, details.st_size, None
    )


def _seccomp_resource(path: Path) -> _ResourceIdentity:
    identity = _regular_resource(
        path, executable=False, digest_limit=_SECCOMP_CAP
    )
    value = json.loads(path.read_text(encoding="utf-8"))
    if (
        type(value) is not dict
        or set(value) != {"architectures", "defaultAction", "syscalls"}
        or value["architectures"] != ["SCMP_ARCH_NATIVE"]
        or value["defaultAction"] != "SCMP_ACT_ERRNO"
        or type(value["syscalls"]) is not list
        or not value["syscalls"]
    ):
        raise ValueError
    for rule in value["syscalls"]:
        if (
            type(rule) is not dict
            or set(rule) != {"action", "names"}
            or rule["action"] != "SCMP_ACT_ALLOW"
            or type(rule["names"]) is not list
            or not rule["names"]
            or any(type(name) is not str or not name for name in rule["names"])
            or rule["names"] != sorted(set(rule["names"]))
        ):
            raise ValueError
    return identity


def _revalidate_resources(resources: tuple[_ResourceIdentity, ...]) -> None:
    try:
        for identity in resources:
            details = os.lstat(identity.path)
            if (
                details.st_dev != identity.device
                or details.st_ino != identity.inode
                or details.st_mode != identity.mode
                or details.st_size != identity.size
            ):
                raise ValueError
            if identity.sha256 is not None:
                if (
                    _regular_file_digest(
                        identity.path, details, max(identity.size, 1)
                    )
                    != identity.sha256
                ):
                    raise ValueError
    except BaseException:
        _unavailable()


def _regular_file_digest(path: Path, details: os.stat_result, limit: int) -> str:
    digest = sha256()
    total = 0
    with path.open("rb") as stream:
        opened = os.fstat(stream.fileno())
        if (
            opened.st_dev != details.st_dev
            or opened.st_ino != details.st_ino
            or opened.st_mode != details.st_mode
            or opened.st_size != details.st_size
        ):
            raise ValueError
        while chunk := stream.read(64 * 1024):
            total += len(chunk)
            if total > limit:
                raise ValueError
            digest.update(chunk)
    if total != details.st_size:
        raise ValueError
    return digest.hexdigest()


def _unavailable() -> NoReturn:
    raise PrimeP1ProductionHostError()


__all__ = (
    "PrimeP1ProductionHostCapability",
    "PrimeP1ProductionHostError",
    "PrimeP1ProductionRunAuthority",
    "create_host_service_factory",
    "create_prime_p1_production_factory",
)
