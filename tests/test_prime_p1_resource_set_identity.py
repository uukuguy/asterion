"""Tests for the opaque, complete Prime P1 authority resource-set identity."""

from __future__ import annotations

import hashlib
import os
import tempfile
import threading
import unittest
from contextlib import ExitStack
from unittest.mock import patch

from asterion.applications.prime_agent.operator.authority_application_resources import (
    AdmittedPrimeP1ApplicationResources,
)
from asterion.applications.prime_agent.operator.authority_artifact_lock import (
    AdmittedPrimeP1AuthorityArtifacts,
)
from asterion.applications.prime_agent.operator.authority_docker_executable import (
    AdmittedPrimeP1DockerExecutable,
    PrimeP1DockerExecutableError,
    _ExecutableIdentity,
)
from asterion.applications.prime_agent.operator.authority_docker_socket import (
    AdmittedPrimeP1DockerSocket,
    PrimeP1DockerSocketError,
    _Identity,
)
from asterion.applications.prime_agent.operator.authority_evidence import (
    AdmittedPrimeP1EvidenceRoot,
)
from asterion.applications.prime_agent.operator.authority_executable_lock import (
    AdmittedPrimeP1AuthorityExecutable,
    AuthorityExecutableLock,
)
from asterion.applications.prime_agent.operator.image_input_lock import (
    ImagePlatformDescriptor,
)
from asterion.applications.prime_agent.operator.authority_resources import (
    AdmittedProductionAuthorityResources,
    AdmittedStaticAuthorityResources,
    PrimeP1AuthorityResourceError,
)


def _artifacts() -> AdmittedPrimeP1AuthorityArtifacts:
    import asterion.applications.prime_agent.operator.authority_artifact_lock as module

    return AdmittedPrimeP1AuthorityArtifacts(_token=module._TOKEN)


def _application() -> AdmittedPrimeP1ApplicationResources:
    import asterion.applications.prime_agent.operator.authority_application_resources as module

    return AdmittedPrimeP1ApplicationResources(_token=module._TOKEN)


def _static() -> AdmittedStaticAuthorityResources:
    import asterion.applications.prime_agent.operator.authority_resources as module

    return AdmittedStaticAuthorityResources(
        module._StaticAuthorityResourceIdentity("a" * 64),
        object(),
        _token=module._STATIC_AUTHORITY_RESOURCES_TOKEN,
    )


def _evidence() -> AdmittedPrimeP1EvidenceRoot:
    import asterion.applications.prime_agent.operator.authority_evidence as module

    return AdmittedPrimeP1EvidenceRoot(
        os.open("/dev/null", os.O_RDONLY | os.O_CLOEXEC), _token=module._EVIDENCE_TOKEN
    )


def _docker() -> AdmittedPrimeP1DockerExecutable:
    import asterion.applications.prime_agent.operator.authority_docker_executable as module

    return AdmittedPrimeP1DockerExecutable(
        os.open("/dev/null", os.O_RDONLY | os.O_CLOEXEC),
        _ExecutableIdentity(0, 0, 0, 0, 0, 0, 0),
        b"docker",
        _token=module._ADMITTED_DOCKER_EXECUTABLE_TOKEN,
    )


def _socket() -> AdmittedPrimeP1DockerSocket:
    import asterion.applications.prime_agent.operator.authority_docker_socket as module

    identity = _Identity(0, 0, 0, 0, 0)
    return AdmittedPrimeP1DockerSocket(
        os.open("/dev/null", os.O_RDONLY | os.O_CLOEXEC),
        ("docker.sock",),
        (identity,),
        identity,
        _token=module._ADMITTED_DOCKER_SOCKET_TOKEN,
    )


def _authority_executable() -> AdmittedPrimeP1AuthorityExecutable:
    import asterion.applications.prime_agent.operator.authority_executable_lock as module

    return AdmittedPrimeP1AuthorityExecutable(
        AuthorityExecutableLock(
            ImagePlatformDescriptor("linux", "amd64", None), "elf", 1, "d" * 64
        ),
        _token=module._TOKEN,
    )


def _resources() -> AdmittedProductionAuthorityResources:
    import asterion.applications.prime_agent.operator.authority_resources as module

    return AdmittedProductionAuthorityResources(
        _artifacts(), _application(), _static(), _evidence(), _docker(), _socket(),
        _authority_executable(),
        _token=module._PRODUCTION_AUTHORITY_RESOURCES_TOKEN,
    )


def _expected_aggregate_digest(contributions: tuple[bytes, ...]) -> str:
    """Independently encode the fixed resource-set aggregate protocol."""
    digest = hashlib.sha256(b"asterion.prime-p1.resource-set/v1\0")
    for contribution in contributions:
        digest.update(len(contribution).to_bytes(8, "big", signed=False))
        digest.update(contribution)
    return digest.hexdigest()


def _changed_identity_field(identity: object, field: str) -> object:
    """Return an exact identity type with one encoded integer field changed."""
    values = {
        name: getattr(identity, name)
        for name in type(identity).__dataclass_fields__
    }
    values[field] += 1
    return type(identity)(**values)


def _real_resources(directory: str) -> AdmittedProductionAuthorityResources:
    """Build exact admitted child objects whose contributions validate locally."""
    import asterion.applications.prime_agent.operator.authority_application_resources as application_module
    import asterion.applications.prime_agent.operator.authority_artifact_lock as artifact_module
    import asterion.applications.prime_agent.operator.authority_docker_executable as docker_module
    import asterion.applications.prime_agent.operator.authority_docker_socket as socket_module
    import asterion.applications.prime_agent.operator.authority_evidence as evidence_module
    import asterion.applications.prime_agent.operator.authority_executable_lock as executable_module
    import asterion.applications.prime_agent.operator.authority_resources as resources_module
    from asterion.applications.prime_agent.operator.authority_seccomp import (
        AdmittedPrimeP1SeccompResource,
    )

    evidence_fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
    info = os.fstat(evidence_fd)
    executable_fd = os.open("/usr/bin/env", os.O_RDONLY | os.O_CLOEXEC)
    executable_identity = docker_module._identity_for_fd(executable_fd)
    root_fd = os.open("/", os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
    root_identity = socket_module._identity_for_fd(root_fd)
    seccomp = AdmittedPrimeP1SeccompResource(
        (), "", (), object(), "c" * 64, threading.Lock(), [False], [False]
    )
    return AdmittedProductionAuthorityResources(
        AdmittedPrimeP1AuthorityArtifacts(b"a" * 32, _token=artifact_module._TOKEN),
        AdmittedPrimeP1ApplicationResources(b"b" * 32, _token=application_module._TOKEN),
        AdmittedStaticAuthorityResources(
            resources_module._StaticAuthorityResourceIdentity("c" * 64),
            seccomp,
            _token=resources_module._STATIC_AUTHORITY_RESOURCES_TOKEN,
        ),
        AdmittedPrimeP1EvidenceRoot(
            evidence_fd,
            evidence_module._EvidenceIdentity(
                info.st_dev, info.st_ino, info.st_mode, info.st_uid, info.st_gid
            ),
            _token=evidence_module._EVIDENCE_TOKEN,
        ),
        AdmittedPrimeP1DockerExecutable(
            executable_fd,
            executable_identity,
            docker_module._digest_fd(executable_fd, executable_identity),
            _token=docker_module._ADMITTED_DOCKER_EXECUTABLE_TOKEN,
        ),
        AdmittedPrimeP1DockerSocket(
            root_fd,
            ("docker.sock",),
            (root_identity,),
            socket_module._Identity(1, 2, 3, 4, 5),
            "1.41",
            "26.1.4",
            _token=socket_module._ADMITTED_DOCKER_SOCKET_TOKEN,
        ),
        AdmittedPrimeP1AuthorityExecutable(
            AuthorityExecutableLock(
                ImagePlatformDescriptor("linux", "amd64", None), "elf", 1, "d" * 64
            ),
            _token=executable_module._TOKEN,
        ),
        _token=resources_module._PRODUCTION_AUTHORITY_RESOURCES_TOKEN,
    )


class TestPrimeP1ResourceSetIdentity(unittest.TestCase):
    def test_authority_artifact_identity_binds_authority_version(self) -> None:
        import asterion.applications.prime_agent.operator.authority_artifact_lock as module

        artifacts = (module._Artifact("authority_resources.py", "a" * 64),)
        first = module._Descriptor("0.1.0", artifacts)
        second = module._Descriptor("0.1.1", artifacts)

        self.assertNotEqual(
            hashlib.sha256(module._canonical_descriptor_bytes(first)).digest(),
            hashlib.sha256(module._canonical_descriptor_bytes(second)).digest(),
        )

    def test_digest_uses_real_child_contributions_and_rejects_every_closed_child(self) -> None:
        with tempfile.TemporaryDirectory(dir=os.getcwd()) as directory:
            resource = _real_resources(directory)
            try:
                with patch.object(AdmittedPrimeP1DockerSocket, "revalidate_path"):
                    digest = resource._resource_set_sha256()
                    self.assertEqual(digest, resource._resource_set_sha256())
                    for child in (
                        resource._artifacts,
                        resource._application_resources,
                        resource._static_resources,
                        resource._evidence_resource,
                        resource._docker_executable,
                        resource._docker_socket,
                        resource._authority_executable,
                    ):
                        self.assertIsNotNone(child)
                        contribution = child._resource_set_contribution()
                        self.assertTrue(contribution)
            finally:
                resource.close()

            for name in (
                "_artifacts",
                "_application_resources",
                "_static_resources",
                "_evidence_resource",
                "_docker_executable",
                "_docker_socket",
                "_authority_executable",
            ):
                resource = _real_resources(directory)
                try:
                    child = getattr(resource, name)
                    child.close()
                    with patch.object(
                        AdmittedPrimeP1DockerSocket, "revalidate_path"
                    ), self.assertRaises(PrimeP1AuthorityResourceError):
                        resource._resource_set_sha256()
                finally:
                    resource.close()

    def test_digest_matches_independent_ordered_child_contribution_encoding(self) -> None:
        with tempfile.TemporaryDirectory(dir=os.getcwd()) as directory:
            resource = _real_resources(directory)
            try:
                with patch.object(AdmittedPrimeP1DockerSocket, "revalidate_path"):
                    contributions = tuple(
                        child._resource_set_contribution()
                        for child in (
                            resource._artifacts,
                            resource._application_resources,
                            resource._static_resources,
                            resource._evidence_resource,
                            resource._docker_executable,
                            resource._docker_socket,
                            resource._authority_executable,
                        )
                    )
                    expected = _expected_aggregate_digest(contributions)
                    self.assertEqual(expected, resource._resource_set_sha256())
                    swapped = list(contributions)
                    swapped[0], swapped[1] = swapped[1], swapped[0]
                    self.assertNotEqual(expected, _expected_aggregate_digest(tuple(swapped)))
            finally:
                resource.close()

    def test_docker_executable_identity_mutation_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory(dir=os.getcwd()) as directory:
            resource = _real_resources(directory)
            docker = resource._docker_executable
            try:
                with patch.object(AdmittedPrimeP1DockerSocket, "revalidate_path"):
                    baseline = resource._resource_set_sha256()
                    original = docker._identity
                    docker._identity = _changed_identity_field(original, "mtime_ns")
                    try:
                        with self.assertRaises(ValueError):
                            docker._resource_set_contribution()
                        with self.assertRaises(PrimeP1AuthorityResourceError):
                            resource._resource_set_sha256()
                    finally:
                        docker._identity = original
                    self.assertEqual(baseline, resource._resource_set_sha256())
            finally:
                resource.close()

    def test_authority_executable_identity_mutation_is_bound(self) -> None:
        with tempfile.TemporaryDirectory(dir=os.getcwd()) as directory:
            resource = _real_resources(directory)
            executable = resource._authority_executable
            try:
                with patch.object(AdmittedPrimeP1DockerSocket, "revalidate_path"):
                    baseline = resource._resource_set_sha256()
                    original = executable._identity
                    executable._identity = b"e" * 32
                    try:
                        self.assertNotEqual(baseline, resource._resource_set_sha256())
                    finally:
                        executable._identity = original
                    self.assertEqual(baseline, resource._resource_set_sha256())
            finally:
                resource.close()

    def test_docker_socket_identity_parent_and_projection_mutations_are_bound(self) -> None:
        with tempfile.TemporaryDirectory(dir=os.getcwd()) as directory:
            resource = _real_resources(directory)
            docker_socket = resource._docker_socket
            try:
                with patch.object(AdmittedPrimeP1DockerSocket, "revalidate_path"):
                    baseline = resource._resource_set_sha256()
                    original_socket = docker_socket._socket
                    docker_socket._socket = _changed_identity_field(original_socket, "inode")
                    try:
                        self.assertNotEqual(baseline, resource._resource_set_sha256())
                    finally:
                        docker_socket._socket = original_socket

                    self.assertEqual(len(docker_socket._identities), 1)
                    original_chain = docker_socket._identities
                    docker_socket._identities = (
                        _changed_identity_field(original_chain[0], "inode"),
                    )
                    try:
                        with self.assertRaises(ValueError):
                            docker_socket._resource_set_contribution()
                        with self.assertRaises(PrimeP1AuthorityResourceError):
                            resource._resource_set_sha256()
                    finally:
                        docker_socket._identities = original_chain

                    original_version = docker_socket._expected_version
                    docker_socket._expected_version = "26.1.5"
                    try:
                        self.assertNotEqual(baseline, resource._resource_set_sha256())
                    finally:
                        docker_socket._expected_version = original_version
                    self.assertEqual(baseline, resource._resource_set_sha256())
            finally:
                resource.close()

    def test_final_revalidations_run_only_after_real_contributions(self) -> None:
        with tempfile.TemporaryDirectory(dir=os.getcwd()) as directory:
            resource = _real_resources(directory)
            events: list[str] = []
            try:
                children = (
                    resource._artifacts,
                    resource._application_resources,
                    resource._static_resources,
                    resource._evidence_resource,
                    resource._docker_executable,
                    resource._docker_socket,
                    resource._authority_executable,
                )
                originals = tuple(type(child)._resource_set_contribution for child in children)
                labels = (
                    "artifact",
                    "application",
                    "static",
                    "evidence",
                    "docker executable",
                    "docker socket",
                    "authority executable",
                )
                patches = [
                    patch.object(
                        type(child),
                        "_resource_set_contribution",
                        autospec=True,
                        side_effect=lambda child, original=original, label=label: (
                            events.append(label), original(child)
                        )[1],
                    )
                    for child, original, label in zip(children, originals, labels, strict=True)
                ]
                with ExitStack() as stack:
                    for contribution_patch in patches:
                        stack.enter_context(contribution_patch)
                    stack.enter_context(
                        patch.object(
                            AdmittedPrimeP1DockerExecutable,
                            "revalidate_for_spawn",
                            side_effect=lambda: events.append("docker-final"),
                        )
                    )
                    stack.enter_context(
                        patch.object(
                            AdmittedPrimeP1DockerSocket,
                            "revalidate_path",
                            side_effect=lambda: events.append("socket-revalidate"),
                        )
                    )
                    resource._resource_set_sha256()
                self.assertEqual(
                    events,
                    [
                        "artifact",
                        "application",
                        "static",
                        "evidence",
                        "docker executable",
                        "docker socket",
                        "socket-revalidate",
                        "authority executable",
                        "docker-final",
                        "socket-revalidate",
                    ],
                )
            finally:
                resource.close()

    def test_closed_child_and_revalidation_fail_before_digest_without_leaks(self) -> None:
        resource = _resources()
        try:
            resource._artifacts.close()
            with (
                patch.object(AdmittedPrimeP1DockerExecutable, "revalidate_for_spawn"),
                patch.object(AdmittedPrimeP1DockerSocket, "revalidate_path"),
                self.assertRaises(PrimeP1AuthorityResourceError) as raised,
            ):
                resource._resource_set_sha256()
            self.assertNotIn("RESOURCE_SET_SECRET_SENTINEL", str(raised.exception))
            self.assertIsNone(raised.exception.__context__)
        finally:
            resource.close()

        with tempfile.TemporaryDirectory(dir=os.getcwd()) as directory:
            resource = _real_resources(directory)
            try:
                with (
                    patch.object(AdmittedPrimeP1DockerSocket, "revalidate_path"),
                    patch.object(
                        AdmittedPrimeP1DockerExecutable,
                        "revalidate_for_spawn",
                        side_effect=PrimeP1DockerExecutableError("RESOURCE_SET_SECRET_SENTINEL"),
                    ),
                    self.assertRaises(PrimeP1AuthorityResourceError) as raised,
                ):
                    resource._resource_set_sha256()
                self.assertNotIn("RESOURCE_SET_SECRET_SENTINEL", str(raised.exception))
                self.assertIsNone(raised.exception.__context__)
            finally:
                resource.close()

            resource = _real_resources(directory)
            try:
                with (
                    patch.object(
                        AdmittedPrimeP1DockerSocket,
                        "revalidate_path",
                        side_effect=(None, PrimeP1DockerSocketError("RESOURCE_SET_SECRET_SENTINEL")),
                    ),
                    self.assertRaises(PrimeP1AuthorityResourceError) as raised,
                ):
                    resource._resource_set_sha256()
                self.assertNotIn("RESOURCE_SET_SECRET_SENTINEL", str(raised.exception))
                self.assertIsNone(raised.exception.__context__)
            finally:
                resource.close()


if __name__ == "__main__":
    unittest.main()
