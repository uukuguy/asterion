"""Static, authority-only admission of a promoted Prime P1 image input."""

from __future__ import annotations

import hmac
import hashlib
import threading
import asyncio
from dataclasses import dataclass
from typing import SupportsIndex

from .authority_config import PrimeP1OperatorConfig
from .image_input_lock import (
    ImageInputLock,
    ImagePlatformDescriptor,
    image_input_lock_sha256,
    resolve_promoted_image_input_lock,
)
from .authority_seccomp import (
    AdmittedPrimeP1SeccompResource,
    admit_static_seccomp_resource,
)
from .authority_evidence import (
    AdmittedPrimeP1EvidenceRoot,
    admit_evidence_root,
)
from .authority_docker_executable import (
    AdmittedPrimeP1DockerExecutable,
    admit_docker_executable,
)
from .authority_docker_socket import (
    AdmittedPrimeP1DockerSocket,
    admit_docker_socket,
)
from .seccomp_policy_lock import seccomp_policy_lock_sha256


_STATIC_AUTHORITY_RESOURCES_TOKEN = object()
_PRODUCTION_AUTHORITY_RESOURCES_TOKEN = object()
_IDENTITY_DOMAIN = b"asterion.prime-p1.static-authority-resources/v1\0"


class PrimeP1AuthorityResourceError(ValueError):
    """Single public-safe image-resource admission failure category."""

    def __init__(self, *_: object) -> None:
        super().__init__("prime P1 authority resource is unavailable")


@dataclass(frozen=True, repr=False, slots=True)
class _StaticAuthorityResourceIdentity:
    """Private, deterministic binding of the three admitted static inputs."""

    digest: str


class AdmittedStaticAuthorityResources:
    """Opaque owner of static admission resources until the next authority slice."""

    __slots__ = ("_identity", "_lock", "_closed", "_seccomp_resource")

    def __init__(
        self,
        identity: _StaticAuthorityResourceIdentity,
        seccomp_resource: AdmittedPrimeP1SeccompResource,
        *,
        _token: object | None = None,
    ) -> None:
        if _token is not _STATIC_AUTHORITY_RESOURCES_TOKEN:
            raise PrimeP1AuthorityResourceError() from None
        self._identity = identity
        self._seccomp_resource: AdmittedPrimeP1SeccompResource | None = seccomp_resource
        self._lock = threading.Lock()
        self._closed = False

    def __repr__(self) -> str:
        return "AdmittedStaticAuthorityResources(redacted)"

    def __reduce__(self) -> object:
        raise TypeError("prime P1 authority resource is unavailable")

    def __reduce_ex__(self, _: SupportsIndex) -> object:
        raise TypeError("prime P1 authority resource is unavailable")

    def __copy__(self) -> object:
        raise TypeError("prime P1 authority resource is unavailable")

    def __deepcopy__(self, _: object) -> object:
        raise TypeError("prime P1 authority resource is unavailable")

    def close(self) -> None:
        """Release the retained seccomp resource exactly once."""
        with self._lock:
            resource = self._seccomp_resource
            if self._closed:
                return
            self._closed = True
            self._seccomp_resource = None
        if resource is not None:
            try:
                resource.close()
            except BaseException:
                pass


class AdmittedProductionAuthorityResources:
    """Opaque owner of all admitted production resources."""

    __slots__ = (
        "_docker_executable",
        "_docker_socket",
        "_evidence_resource",
        "_lock",
        "_static_resources",
    )

    def __init__(
        self,
        static_resources: AdmittedStaticAuthorityResources,
        evidence_resource: AdmittedPrimeP1EvidenceRoot,
        docker_executable: AdmittedPrimeP1DockerExecutable,
        docker_socket: AdmittedPrimeP1DockerSocket,
        *,
        _token: object | None = None,
    ) -> None:
        if (
            type(self) is not AdmittedProductionAuthorityResources
            or _token is not _PRODUCTION_AUTHORITY_RESOURCES_TOKEN
            or type(static_resources) is not AdmittedStaticAuthorityResources
            or type(evidence_resource) is not AdmittedPrimeP1EvidenceRoot
            or type(docker_executable) is not AdmittedPrimeP1DockerExecutable
            or type(docker_socket) is not AdmittedPrimeP1DockerSocket
        ):
            raise PrimeP1AuthorityResourceError() from None
        self._static_resources: AdmittedStaticAuthorityResources | None = static_resources
        self._evidence_resource: AdmittedPrimeP1EvidenceRoot | None = evidence_resource
        self._docker_executable: AdmittedPrimeP1DockerExecutable | None = docker_executable
        self._docker_socket: AdmittedPrimeP1DockerSocket | None = docker_socket
        self._lock = threading.Lock()

    def __repr__(self) -> str:
        return "AdmittedProductionAuthorityResources(redacted)"

    def __reduce__(self) -> object:
        raise TypeError("prime P1 authority resource is unavailable")

    def __reduce_ex__(self, _: SupportsIndex) -> object:
        raise TypeError("prime P1 authority resource is unavailable")

    def __copy__(self) -> object:
        raise TypeError("prime P1 authority resource is unavailable")

    def __deepcopy__(self, _: object) -> object:
        raise TypeError("prime P1 authority resource is unavailable")

    def close(self) -> None:
        """Release owned children once, in reverse acquisition order."""
        with self._lock:
            socket = self._docker_socket
            docker = self._docker_executable
            evidence = self._evidence_resource
            static = self._static_resources
            self._docker_socket = None
            self._docker_executable = None
            self._evidence_resource = None
            self._static_resources = None
        for resource in (socket, docker, evidence, static):
            if resource is not None:
                try:
                    resource.close()
                except BaseException:
                    pass

    async def _verify_daemon_projection(self, deadline: float) -> None:
        """Delegate the private daemon projection check to the exact socket child."""
        failed = False
        try:
            if type(self) is not AdmittedProductionAuthorityResources:
                raise ValueError
            with self._lock:
                socket = self._docker_socket
            if type(socket) is not AdmittedPrimeP1DockerSocket:
                raise ValueError
            await socket._verify_daemon_projection(deadline)
        except asyncio.CancelledError:
            raise
        except BaseException:
            failed = True
        if failed:
            raise PrimeP1AuthorityResourceError() from None


def _static_authority_resource_identity(
    image: ImageInputLock,
    seccomp: AdmittedPrimeP1SeccompResource,
) -> _StaticAuthorityResourceIdentity:
    """Hash exact admitted lock identities and the observed profile digest."""
    image_hash = image_input_lock_sha256(image)
    policy_hash = seccomp_policy_lock_sha256(seccomp._policy)
    profile_hash = seccomp.sha256
    if (
        type(profile_hash) is not str
        or len(profile_hash) != 64
        or any(character not in "0123456789abcdef" for character in profile_hash)
    ):
        raise ValueError
    digest = hashlib.sha256(
        _IDENTITY_DOMAIN
        + bytes.fromhex(image_hash)
        + bytes.fromhex(policy_hash)
        + bytes.fromhex(profile_hash)
    ).hexdigest()
    return _StaticAuthorityResourceIdentity(digest)


def admit_static_authority_resources(config: object) -> AdmittedStaticAuthorityResources:
    """Admit the exact image/profile pair as one private, retained resource set."""
    seccomp: AdmittedPrimeP1SeccompResource | None = None
    result: AdmittedStaticAuthorityResources | None = None
    try:
        if type(config) is not PrimeP1OperatorConfig:
            raise ValueError
        image = admit_static_image_resource(config)
        seccomp = admit_static_seccomp_resource(config)
        if (
            type(image) is not ImageInputLock
            or type(seccomp) is not AdmittedPrimeP1SeccompResource
            or image.platform != seccomp._policy.platform
            or not hmac.compare_digest(
                config._values["ASTERION_PRIME_P1_IMAGE_CONFIG_DIGEST"],
                seccomp._policy.image_config_digest,
            )
        ):
            raise ValueError
        identity = _static_authority_resource_identity(image, seccomp)
        result = AdmittedStaticAuthorityResources(
            identity, seccomp, _token=_STATIC_AUTHORITY_RESOURCES_TOKEN
        )
        seccomp = None
    except BaseException:
        pass
    finally:
        if seccomp is not None:
            try:
                seccomp.close()
            except BaseException:
                pass
    if result is None:
        raise PrimeP1AuthorityResourceError() from None
    return result


def admit_production_authority_resources(
    config: object,
) -> AdmittedProductionAuthorityResources:
    """Admit and retain static, evidence, and Docker resources as one owner."""
    static: AdmittedStaticAuthorityResources | None = None
    evidence: AdmittedPrimeP1EvidenceRoot | None = None
    docker: AdmittedPrimeP1DockerExecutable | None = None
    socket: AdmittedPrimeP1DockerSocket | None = None
    result: AdmittedProductionAuthorityResources | None = None
    try:
        static_candidate = admit_static_authority_resources(config)
        if type(static_candidate) is not AdmittedStaticAuthorityResources:
            raise ValueError
        static = static_candidate
        evidence_candidate = admit_evidence_root(config)
        if type(evidence_candidate) is not AdmittedPrimeP1EvidenceRoot:
            raise ValueError
        evidence = evidence_candidate
        docker_candidate = admit_docker_executable(config)
        if type(docker_candidate) is not AdmittedPrimeP1DockerExecutable:
            raise ValueError
        docker = docker_candidate
        socket_candidate = admit_docker_socket(config)
        if type(socket_candidate) is not AdmittedPrimeP1DockerSocket:
            raise ValueError
        socket = socket_candidate
        result = AdmittedProductionAuthorityResources(
            static, evidence, docker, socket, _token=_PRODUCTION_AUTHORITY_RESOURCES_TOKEN
        )
        static = None
        evidence = None
        docker = None
        socket = None
    except BaseException:
        pass
    finally:
        for resource in (socket, docker, evidence, static):
            if resource is not None:
                try:
                    resource.close()
                except BaseException:
                    pass
    if result is None:
        raise PrimeP1AuthorityResourceError() from None
    return result


def admit_static_image_resource(config: object) -> ImageInputLock:
    """Resolve only the operator-selected platform from the promoted catalog.

    The config is already a descriptor-only, authority-owned value.  This
    boundary neither discovers host state nor performs Docker, network,
    execution, receipt, or readiness work.
    """
    if type(config) is not PrimeP1OperatorConfig:
        raise PrimeP1AuthorityResourceError() from None
    resource: ImageInputLock | None = None
    try:
        values = config._values
        variant = values["ASTERION_PRIME_P1_IMAGE_PLATFORM_VARIANT"]
        platform = ImagePlatformDescriptor(
            values["ASTERION_PRIME_P1_IMAGE_PLATFORM_OS"],
            values["ASTERION_PRIME_P1_IMAGE_PLATFORM_ARCHITECTURE"],
            None if variant == "none" else variant,
        )
        resource = resolve_promoted_image_input_lock(platform)
        config_artifacts = tuple(
            item for item in resource.artifacts if item.kind == "oci-config"
        )
        if len(config_artifacts) != 1:
            raise ValueError
        expected = values["ASTERION_PRIME_P1_IMAGE_CONFIG_DIGEST"]
        if not hmac.compare_digest(expected, "sha256:" + config_artifacts[0].sha256):
            raise ValueError
    except Exception:
        resource = None
    if resource is None:
        raise PrimeP1AuthorityResourceError() from None
    return resource
