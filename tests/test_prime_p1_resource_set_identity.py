"""Tests for the opaque, complete Prime P1 authority resource-set identity."""

from __future__ import annotations

import os
import unittest
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


def _resources() -> AdmittedProductionAuthorityResources:
    import asterion.applications.prime_agent.operator.authority_resources as module

    return AdmittedProductionAuthorityResources(
        _artifacts(), _application(), _static(), _evidence(), _docker(), _socket(),
        _token=module._PRODUCTION_AUTHORITY_RESOURCES_TOKEN,
    )


class TestPrimeP1ResourceSetIdentity(unittest.TestCase):
    def test_digest_is_exact_deterministic_and_binds_every_child(self) -> None:
        resource = _resources()
        children = (
            AdmittedPrimeP1AuthorityArtifacts,
            AdmittedPrimeP1ApplicationResources,
            AdmittedStaticAuthorityResources,
            AdmittedPrimeP1EvidenceRoot,
            AdmittedPrimeP1DockerExecutable,
            AdmittedPrimeP1DockerSocket,
        )
        contributions = (
            b"authority-artifacts\0artifact",
            b"application-resources\0application",
            b"static-image-seccomp\0static",
            b"evidence-root\0evidence",
            b"docker-executable\0executable",
            b"docker-socket\0socket",
        )
        try:
            with (
                patch.object(children[0], "_resource_set_contribution", return_value=contributions[0]),
                patch.object(children[1], "_resource_set_contribution", return_value=contributions[1]),
                patch.object(children[2], "_resource_set_contribution", return_value=contributions[2]),
                patch.object(children[3], "_resource_set_contribution", return_value=contributions[3]),
                patch.object(children[4], "_resource_set_contribution", return_value=contributions[4]),
                patch.object(children[5], "_resource_set_contribution", return_value=contributions[5]),
                patch.object(children[4], "revalidate_for_spawn"),
                patch.object(children[5], "revalidate_path"),
            ):
                digest = resource._resource_set_sha256()
                self.assertEqual(digest, resource._resource_set_sha256())
                self.assertEqual(digest, "ccad79cf72a7ed149c1f923c9e2c400fc30d36cfebca4c6e0d0e1cb9d355d400")
                for position, child in enumerate(children):
                    replacement = contributions[:position] + (contributions[position] + b"changed",) + contributions[position + 1 :]
                    with patch.object(child, "_resource_set_contribution", return_value=replacement[position]):
                        self.assertNotEqual(digest, resource._resource_set_sha256())
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

        resource = _resources()
        try:
            with patch.object(
                AdmittedPrimeP1DockerExecutable,
                "revalidate_for_spawn",
                side_effect=PrimeP1DockerExecutableError("RESOURCE_SET_SECRET_SENTINEL"),
            ), self.assertRaises(PrimeP1AuthorityResourceError) as raised:
                resource._resource_set_sha256()
            self.assertNotIn("RESOURCE_SET_SECRET_SENTINEL", str(raised.exception))
            self.assertIsNone(raised.exception.__context__)
        finally:
            resource.close()

        resource = _resources()
        try:
            with patch.object(
                AdmittedPrimeP1DockerSocket,
                "revalidate_path",
                side_effect=PrimeP1DockerSocketError("RESOURCE_SET_SECRET_SENTINEL"),
            ), self.assertRaises(PrimeP1AuthorityResourceError) as raised:
                resource._resource_set_sha256()
            self.assertNotIn("RESOURCE_SET_SECRET_SENTINEL", str(raised.exception))
            self.assertIsNone(raised.exception.__context__)
        finally:
            resource.close()


if __name__ == "__main__":
    unittest.main()
