"""Static, non-authoritative Prime P1 image-resource admission tests."""

from __future__ import annotations

from dataclasses import replace
import hashlib
import os
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

from asterion.applications.prime_agent.operator.authority_config import (
    load_operator_config,
)
from asterion.applications.prime_agent.operator.authority_resources import (
    AdmittedProductionAuthorityResources,
    AdmittedStaticAuthorityResources,
    PrimeP1AuthorityResourceError,
    admit_production_authority_resources,
    admit_static_authority_resources,
    admit_static_image_resource,
)
from asterion.applications.prime_agent.operator.authority_evidence import (
    AdmittedPrimeP1EvidenceRoot,
    PrimeP1EvidenceResourceError,
)
from asterion.applications.prime_agent.operator.authority_docker_executable import (
    AdmittedPrimeP1DockerExecutable,
    _ExecutableIdentity,
)
from asterion.applications.prime_agent.operator.image_input_lock import (
    ImageArtifact,
    ImageInputLock,
    ImagePlatformDescriptor,
    validate_image_input_lock,
)
from asterion.applications.prime_agent.operator.seccomp_policy_lock import (
    SeccompPolicyLock,
    SeccompRuleAtom,
)
from asterion.applications.prime_agent.operator.authority_seccomp import (
    AdmittedPrimeP1SeccompResource,
)


_VALUES = {
    "ASTERION_PRIME_P1_DOCKER_EXECUTABLE": "/usr/bin/docker",
    "ASTERION_PRIME_P1_DOCKER_SOCKET": "/var/run/docker.sock",
    "ASTERION_PRIME_P1_DOCKER_SOCKET_OWNER_UID": "0",
    "ASTERION_PRIME_P1_DOCKER_SOCKET_GROUP_GID": "0",
    "ASTERION_PRIME_P1_DOCKER_SOCKET_MODE": "0600",
    "ASTERION_PRIME_P1_DOCKER_SERVER_API_VERSION": "1.41",
    "ASTERION_PRIME_P1_DOCKER_SERVER_VERSION": "26.1.4",
    "ASTERION_PRIME_P1_SECCOMP_PROFILE": "/etc/asterion/seccomp.json",
    "ASTERION_PRIME_P1_SECCOMP_PROFILE_SHA256": "c" * 64,
    "ASTERION_PRIME_P1_IMAGE_CONFIG_DIGEST": "sha256:" + "a" * 64,
    "ASTERION_PRIME_P1_IMAGE_PLATFORM_OS": "linux",
    "ASTERION_PRIME_P1_IMAGE_PLATFORM_ARCHITECTURE": "amd64",
    "ASTERION_PRIME_P1_IMAGE_PLATFORM_VARIANT": "none",
    "ASTERION_PRIME_P1_MODEL_ID": "deepseek-chat",
    "ASTERION_PRIME_P1_EVIDENCE_ROOT": "/var/lib/asterion/evidence",
    "ASTERION_PRIME_P1_RECEIPT_KEY_ID": "p1-2026",
    "ASTERION_PRIME_P1_RECEIPT_HMAC_KEY": "b" * 64,
    "DEEPSEEK_API_KEY": "RESOURCE_SECRET_SENTINEL",
}

_SINGLE_READ_PROFILE = (
    b'{"architectures":["SCMP_ARCH_X86_64"],"defaultAction":"SCMP_ACT_ERRNO",'
    b'"syscalls":[{"action":"SCMP_ACT_ALLOW","args":[],"names":["read"]}]}'
)


class _CountingResource:
    def __init__(self, events: list[str], name: str) -> None:
        self.close_calls = 0
        self._events = events
        self._name = name

    def close(self) -> None:
        self.close_calls += 1
        self._events.append(self._name)


class _StaticResourceSubclass(AdmittedStaticAuthorityResources):
    pass


class _EvidenceResourceSubclass(AdmittedPrimeP1EvidenceRoot):
    pass


class _DockerExecutableSubclass(AdmittedPrimeP1DockerExecutable):
    pass


class _ProductionResourcesSubclass(AdmittedProductionAuthorityResources):
    pass


def _docker() -> AdmittedPrimeP1DockerExecutable:
    import asterion.applications.prime_agent.operator.authority_docker_executable as module

    return AdmittedPrimeP1DockerExecutable(
        os.open("/dev/null", os.O_RDONLY | os.O_CLOEXEC),
        _ExecutableIdentity(0, 0, 0, 0, 0, 0, 0),
        b"docker",
        _token=module._ADMITTED_DOCKER_EXECUTABLE_TOKEN,
    )


def _artifacts(*, config_sha256: str = "a" * 64) -> tuple[ImageArtifact, ...]:
    """Return a complete, canonically ordered static image artifact set."""

    return tuple(
        ImageArtifact(kind, path, 0, sha256)
        for kind, path, sha256 in (
            ("frontend", "build-frontend/launcher.mjs", "1" * 64),
            ("fixture", "fixture/fixture-lock.json", "2" * 64),
            ("node-archive", "node/node-v22.8.0-linux-x64.tar.xz", "3" * 64),
            ("node-modules", "node/node_modules-linux-amd64.tar", "4" * 64),
            ("oci-config", "oci/config.json", config_sha256),
            ("oci-layer", "oci/layer-000.tar", "5" * 64),
            ("oci-manifest", "oci/manifest.json", "6" * 64),
            (
                "python-wheel",
                "python/prime_agent_runtime-0-py3-none-any.whl",
                "7" * 64,
            ),
        )
    )


def _image_lock() -> ImageInputLock:
    lock = ImageInputLock(
        "d" * 40,
        "e" * 64,
        "f" * 64,
        ImagePlatformDescriptor("linux", "amd64", None),
        _artifacts(),
    )
    validate_image_input_lock(lock)
    return lock


def _artifacts_with_two_oci_configs() -> tuple[ImageArtifact, ...]:
    artifacts = _artifacts()
    return artifacts[:5] + (
        ImageArtifact("oci-config", "oci/config/secondary.json", 0, "8" * 64),
    ) + artifacts[5:]


class TestPrimeP1AuthorityResources(unittest.TestCase):
    def _config(self) -> object:
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as temp:
            path = Path(temp) / "operator.env"
            path.write_text("".join(f"{key}={value}\n" for key, value in _VALUES.items()))
            path.chmod(0o600)
            fd = os.open(path, os.O_RDONLY | os.O_CLOEXEC | os.O_NONBLOCK)
            return load_operator_config(fd)

    def test_empty_code_owned_catalog_fails_closed_and_redacted(self) -> None:
        config = self._config()
        with self.assertRaises(PrimeP1AuthorityResourceError) as raised:
            admit_static_image_resource(config)
        self.assertIsNone(raised.exception.__context__)
        self.assertNotIn("RESOURCE_SECRET_SENTINEL", str(raised.exception))
        self.assertNotIn("RESOURCE_SECRET_SENTINEL", repr(raised.exception))

    def test_production_aggregate_requires_exact_docker_executable(self) -> None:
        config = self._config()
        import asterion.applications.prime_agent.operator.authority_resources as module
        import asterion.applications.prime_agent.operator.authority_evidence as evidence_module

        static = AdmittedStaticAuthorityResources(
            object(), _CountingResource([], "nested"),
            _token=module._STATIC_AUTHORITY_RESOURCES_TOKEN,
        )
        evidence = AdmittedPrimeP1EvidenceRoot(
            os.open("/dev/null", os.O_RDONLY | os.O_CLOEXEC),
            _token=evidence_module._EVIDENCE_TOKEN,
        )
        docker_resource = _docker()
        with (
            patch.object(module, "admit_static_authority_resources", return_value=static),
            patch.object(module, "admit_evidence_root", return_value=evidence),
            patch.object(module, "admit_docker_executable", return_value=docker_resource) as docker,
        ):
            resource = admit_production_authority_resources(config)
        docker.assert_called_once_with(config)
        resource.close()

    def test_production_resources_require_static_evidence_and_docker(self) -> None:
        config = self._config()
        events: list[str] = []
        import asterion.applications.prime_agent.operator.authority_resources as module
        import asterion.applications.prime_agent.operator.authority_evidence as evidence_module

        static = AdmittedStaticAuthorityResources(
            object(),
            _CountingResource([], "nested"),
            _token=module._STATIC_AUTHORITY_RESOURCES_TOKEN,
        )
        evidence_fd = os.open("/dev/null", os.O_RDONLY | os.O_CLOEXEC)
        evidence = AdmittedPrimeP1EvidenceRoot(
            evidence_fd, _token=evidence_module._EVIDENCE_TOKEN
        )
        docker = _docker()
        original_static_close = AdmittedStaticAuthorityResources.close
        original_evidence_close = AdmittedPrimeP1EvidenceRoot.close
        original_docker_close = AdmittedPrimeP1DockerExecutable.close

        def close_static(resource: AdmittedStaticAuthorityResources) -> None:
            events.append("static")
            original_static_close(resource)

        def close_evidence(resource: AdmittedPrimeP1EvidenceRoot) -> None:
            events.append("evidence")
            original_evidence_close(resource)

        def close_docker(resource: AdmittedPrimeP1DockerExecutable) -> None:
            events.append("docker")
            original_docker_close(resource)

        with (
            patch.object(
                module, "admit_static_authority_resources", return_value=static
            ) as admit_static,
            patch.object(module, "admit_evidence_root", return_value=evidence) as admit_evidence,
            patch.object(module, "admit_docker_executable", return_value=docker) as admit_docker,
            patch.object(AdmittedStaticAuthorityResources, "close", autospec=True, side_effect=close_static),
            patch.object(AdmittedPrimeP1EvidenceRoot, "close", autospec=True, side_effect=close_evidence),
            patch.object(AdmittedPrimeP1DockerExecutable, "close", autospec=True, side_effect=close_docker),
        ):
            resources = admit_production_authority_resources(config)
            admit_static.assert_called_once_with(config)
            admit_evidence.assert_called_once_with(config)
            admit_docker.assert_called_once_with(config)
            self.assertEqual(repr(resources), "AdmittedProductionAuthorityResources(redacted)")
            with self.assertRaises(TypeError):
                resources.__reduce__()
            threads = [threading.Thread(target=resources.close) for _ in range(2)]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join()
        self.assertEqual(events, ["docker", "evidence", "static"])

    def test_evidence_failure_closes_static_once_in_reverse_acquisition_order(self) -> None:
        config = self._config()
        import asterion.applications.prime_agent.operator.authority_resources as module

        static = AdmittedStaticAuthorityResources(
            object(),
            _CountingResource([], "nested"),
            _token=module._STATIC_AUTHORITY_RESOURCES_TOKEN,
        )
        original_close = AdmittedStaticAuthorityResources.close

        def close(resource: AdmittedStaticAuthorityResources) -> None:
            original_close(resource)

        with (
            patch.object(module, "admit_static_authority_resources", return_value=static),
            patch.object(module, "admit_evidence_root", side_effect=PrimeP1EvidenceResourceError),
            patch.object(module, "admit_docker_executable") as docker,
            patch.object(AdmittedStaticAuthorityResources, "close", autospec=True, side_effect=close) as close_static,
            self.assertRaises(PrimeP1AuthorityResourceError),
        ):
            admit_production_authority_resources(config)
        close_static.assert_called_once_with(static)
        docker.assert_not_called()

    def test_docker_failure_closes_evidence_then_static_once(self) -> None:
        config = self._config()
        events: list[str] = []
        import asterion.applications.prime_agent.operator.authority_resources as module
        import asterion.applications.prime_agent.operator.authority_evidence as evidence_module

        static = AdmittedStaticAuthorityResources(
            object(), _CountingResource([], "nested"),
            _token=module._STATIC_AUTHORITY_RESOURCES_TOKEN,
        )
        evidence = AdmittedPrimeP1EvidenceRoot(
            os.open("/dev/null", os.O_RDONLY | os.O_CLOEXEC),
            _token=evidence_module._EVIDENCE_TOKEN,
        )
        original_static_close = AdmittedStaticAuthorityResources.close
        original_evidence_close = AdmittedPrimeP1EvidenceRoot.close

        def close_static(resource: AdmittedStaticAuthorityResources) -> None:
            events.append("static")
            original_static_close(resource)

        def close_evidence(resource: AdmittedPrimeP1EvidenceRoot) -> None:
            events.append("evidence")
            original_evidence_close(resource)

        with (
            patch.object(module, "admit_static_authority_resources", return_value=static),
            patch.object(module, "admit_evidence_root", return_value=evidence),
            patch.object(module, "admit_docker_executable", side_effect=ValueError),
            patch.object(AdmittedStaticAuthorityResources, "close", autospec=True, side_effect=close_static) as static_close,
            patch.object(AdmittedPrimeP1EvidenceRoot, "close", autospec=True, side_effect=close_evidence) as evidence_close,
            self.assertRaises(PrimeP1AuthorityResourceError) as raised,
        ):
            admit_production_authority_resources(config)
        self.assertIsNone(raised.exception.__context__)
        static_close.assert_called_once_with(static)
        evidence_close.assert_called_once_with(evidence)
        self.assertEqual(events, ["evidence", "static"])

    def test_factory_rejects_lookalike_or_subclass_children_without_ownership_transfer(
        self,
    ) -> None:
        config = self._config()
        import asterion.applications.prime_agent.operator.authority_resources as module
        import asterion.applications.prime_agent.operator.authority_evidence as evidence_module

        for child, factory_name in (
            (_CountingResource([], "static-lookalike"), "admit_static_authority_resources"),
            (
                _StaticResourceSubclass(
                    object(),
                    _CountingResource([], "nested"),
                    _token=module._STATIC_AUTHORITY_RESOURCES_TOKEN,
                ),
                "admit_static_authority_resources",
            ),
            (_CountingResource([], "evidence-lookalike"), "admit_evidence_root"),
            (_CountingResource([], "docker-lookalike"), "admit_docker_executable"),
            (_DockerExecutableSubclass.__new__(_DockerExecutableSubclass), "admit_docker_executable"),
        ):
            with self.subTest(factory_name=factory_name, child_type=type(child)):
                exact_static = AdmittedStaticAuthorityResources(
                    object(),
                    _CountingResource([], "nested"),
                    _token=module._STATIC_AUTHORITY_RESOURCES_TOKEN,
                )
                try:
                    patches = {
                        "admit_static_authority_resources": exact_static,
                        "admit_evidence_root": AdmittedPrimeP1EvidenceRoot(
                            os.open("/dev/null", os.O_RDONLY | os.O_CLOEXEC),
                            _token=evidence_module._EVIDENCE_TOKEN,
                        ),
                        "admit_docker_executable": _docker(),
                    }
                    patches[factory_name] = child
                    with (
                        patch.object(
                            module,
                            "admit_static_authority_resources",
                            return_value=patches["admit_static_authority_resources"],
                        ),
                        patch.object(
                            module,
                            "admit_evidence_root",
                            return_value=patches["admit_evidence_root"],
                        ),
                        patch.object(
                            module,
                            "admit_docker_executable",
                            return_value=patches["admit_docker_executable"],
                        ),
                        self.assertRaises(PrimeP1AuthorityResourceError) as raised,
                    ):
                        admit_production_authority_resources(config)
                    self.assertIsNone(raised.exception.__context__)
                    if isinstance(child, _CountingResource):
                        self.assertEqual(child.close_calls, 0)
                    else:
                        self.assertFalse(hasattr(child, "_fd"))
                finally:
                    exact_static.close()
                    if isinstance(child, _StaticResourceSubclass):
                        child.close()
                    for name, resource in patches.items():
                        if resource is not child and hasattr(resource, "close"):
                            resource.close()

    def test_constructor_rejects_wrong_token_children_and_aggregate_subclass_without_transfer(
        self,
    ) -> None:
        import asterion.applications.prime_agent.operator.authority_resources as module
        import asterion.applications.prime_agent.operator.authority_evidence as evidence_module

        static = AdmittedStaticAuthorityResources(
            object(),
            _CountingResource([], "nested"),
            _token=module._STATIC_AUTHORITY_RESOURCES_TOKEN,
        )
        evidence_fd = os.open("/dev/null", os.O_RDONLY | os.O_CLOEXEC)
        evidence = AdmittedPrimeP1EvidenceRoot(
            evidence_fd, _token=evidence_module._EVIDENCE_TOKEN
        )
        static_subclass = _StaticResourceSubclass(
            object(),
            _CountingResource([], "nested-subclass"),
            _token=module._STATIC_AUTHORITY_RESOURCES_TOKEN,
        )
        evidence_subclass_fd = os.open("/dev/null", os.O_RDONLY | os.O_CLOEXEC)
        evidence_subclass = _EvidenceResourceSubclass(
            evidence_subclass_fd, _token=evidence_module._EVIDENCE_TOKEN
        )
        docker = _docker()
        docker_subclass = _DockerExecutableSubclass.__new__(_DockerExecutableSubclass)
        try:
            cases = (
                (AdmittedProductionAuthorityResources, static, evidence, docker, object()),
                (AdmittedProductionAuthorityResources, object(), evidence, docker, module._PRODUCTION_AUTHORITY_RESOURCES_TOKEN),
                (AdmittedProductionAuthorityResources, static, object(), docker, module._PRODUCTION_AUTHORITY_RESOURCES_TOKEN),
                (AdmittedProductionAuthorityResources, static, evidence, object(), module._PRODUCTION_AUTHORITY_RESOURCES_TOKEN),
                (AdmittedProductionAuthorityResources, static_subclass, evidence, docker, module._PRODUCTION_AUTHORITY_RESOURCES_TOKEN),
                (AdmittedProductionAuthorityResources, static, evidence_subclass, docker, module._PRODUCTION_AUTHORITY_RESOURCES_TOKEN),
                (AdmittedProductionAuthorityResources, static, evidence, docker_subclass, module._PRODUCTION_AUTHORITY_RESOURCES_TOKEN),
                (_ProductionResourcesSubclass, static, evidence, docker, module._PRODUCTION_AUTHORITY_RESOURCES_TOKEN),
            )
            for constructor, static_child, evidence_child, docker_child, token in cases:
                with self.subTest(constructor=constructor, static_type=type(static_child), evidence_type=type(evidence_child), docker_type=type(docker_child)):
                    with self.assertRaises(PrimeP1AuthorityResourceError):
                        constructor(static_child, evidence_child, docker_child, _token=token)
                    self.assertFalse(static._closed)
                    self.assertEqual(evidence._fd, evidence_fd)
                    self.assertFalse(static_subclass._closed)
                    self.assertEqual(evidence_subclass._fd, evidence_subclass_fd)
                    self.assertIsNotNone(docker._fd)
        finally:
            evidence_subclass.close()
            static_subclass.close()
            evidence.close()
            static.close()
            docker.close()

    def test_constructor_failure_closes_acquired_exact_children_in_reverse_order(self) -> None:
        config = self._config()
        events: list[str] = []
        import asterion.applications.prime_agent.operator.authority_resources as module
        import asterion.applications.prime_agent.operator.authority_evidence as evidence_module

        static = AdmittedStaticAuthorityResources(
            object(),
            _CountingResource([], "nested"),
            _token=module._STATIC_AUTHORITY_RESOURCES_TOKEN,
        )
        evidence_fd = os.open("/dev/null", os.O_RDONLY | os.O_CLOEXEC)
        evidence = AdmittedPrimeP1EvidenceRoot(
            evidence_fd, _token=evidence_module._EVIDENCE_TOKEN
        )
        docker = _docker()
        original_static_close = AdmittedStaticAuthorityResources.close
        original_evidence_close = AdmittedPrimeP1EvidenceRoot.close
        original_docker_close = AdmittedPrimeP1DockerExecutable.close

        def close_static(resource: AdmittedStaticAuthorityResources) -> None:
            events.append("static")
            original_static_close(resource)

        def close_evidence(resource: AdmittedPrimeP1EvidenceRoot) -> None:
            events.append("evidence")
            original_evidence_close(resource)

        def close_docker(resource: AdmittedPrimeP1DockerExecutable) -> None:
            events.append("docker")
            original_docker_close(resource)

        with (
            patch.object(module, "admit_static_authority_resources", return_value=static),
            patch.object(module, "admit_evidence_root", return_value=evidence),
            patch.object(module, "admit_docker_executable", return_value=docker),
            patch.object(module, "AdmittedProductionAuthorityResources", side_effect=MemoryError),
            patch.object(AdmittedStaticAuthorityResources, "close", autospec=True, side_effect=close_static),
            patch.object(AdmittedPrimeP1EvidenceRoot, "close", autospec=True, side_effect=close_evidence),
            patch.object(AdmittedPrimeP1DockerExecutable, "close", autospec=True, side_effect=close_docker),
            self.assertRaises(PrimeP1AuthorityResourceError),
        ):
            admit_production_authority_resources(config)
        self.assertEqual(events, ["docker", "evidence", "static"])

    def test_normalizes_none_only_at_resource_admission(self) -> None:
        config = self._config()
        import asterion.applications.prime_agent.operator.authority_resources as module

        with patch.object(
            module,
            "resolve_promoted_image_input_lock",
            side_effect=ValueError("test resolver rejection"),
        ) as resolver:
            with self.assertRaises(PrimeP1AuthorityResourceError):
                admit_static_image_resource(config)
        resolver.assert_called_once_with(ImagePlatformDescriptor("linux", "amd64", None))

    def test_rejects_non_authority_config_before_resolving(self) -> None:
        import asterion.applications.prime_agent.operator.authority_resources as module

        with patch.object(module, "resolve_promoted_image_input_lock") as resolver:
            with self.assertRaises(PrimeP1AuthorityResourceError):
                admit_static_image_resource(object())
        resolver.assert_not_called()

    def test_rejects_resolved_image_lock_with_wrong_oci_config_digest(self) -> None:
        config = self._config()
        wrong = replace(_image_lock(), artifacts=_artifacts(config_sha256="9" * 64))
        import asterion.applications.prime_agent.operator.authority_resources as module

        with patch.object(module, "resolve_promoted_image_input_lock", return_value=wrong):
            with self.assertRaises(PrimeP1AuthorityResourceError):
                admit_static_image_resource(config)

    def test_rejects_image_lock_with_two_oci_config_artifacts(self) -> None:
        config = self._config()
        multiple = replace(_image_lock(), artifacts=_artifacts_with_two_oci_configs())
        validate_image_input_lock(multiple)
        import asterion.applications.prime_agent.operator.authority_resources as module

        with patch.object(
            module, "resolve_promoted_image_input_lock", return_value=multiple
        ):
            with self.assertRaises(PrimeP1AuthorityResourceError):
                admit_static_image_resource(config)

    def test_admits_image_lock_with_matching_oci_config_digest(self) -> None:
        config = self._config()
        resource = _image_lock()
        import asterion.applications.prime_agent.operator.authority_resources as module

        with patch.object(
            module, "resolve_promoted_image_input_lock", return_value=resource
        ):
            self.assertIs(admit_static_image_resource(config), resource)

    def test_empty_image_catalog_precedes_seccomp_admission(self) -> None:
        config = self._config()
        import asterion.applications.prime_agent.operator.authority_resources as module

        with (
            patch.object(module, "admit_static_image_resource", side_effect=ValueError),
            patch.object(module, "admit_static_seccomp_resource") as seccomp,
            self.assertRaises(PrimeP1AuthorityResourceError),
        ):
            admit_static_authority_resources(config)
        seccomp.assert_not_called()

    def test_closes_seccomp_once_when_cross_binding_rejects_it(self) -> None:
        config = self._config()
        image = _image_lock()
        policy = SeccompPolicyLock(
            "asterion.prime-p1-seccomp-policy-lock/v1",
            ImagePlatformDescriptor("linux", "arm64", None),
            "SCMP_ARCH_AARCH64",
            "sha256:" + "a" * 64,
            "1" * 64, "2" * 64, "3" * 64, "4" * 64, "5" * 64,
            "SCMP_ACT_ERRNO", (SeccompRuleAtom("read", ()),),
            hashlib.sha256(_SINGLE_READ_PROFILE).hexdigest(),
        )

        seccomp = AdmittedPrimeP1SeccompResource(
            (), "", (), policy, "c" * 64, threading.Lock(), [False], [False]
        )
        import asterion.applications.prime_agent.operator.authority_resources as module

        with (
            patch.object(module, "admit_static_image_resource", return_value=image),
            patch.object(module, "admit_static_seccomp_resource", return_value=seccomp),
            self.assertRaises(PrimeP1AuthorityResourceError),
        ):
            admit_static_authority_resources(config)
        self.assertTrue(seccomp._closed[0])

    def test_resource_set_is_opaque_and_closes_owned_seccomp_idempotently(self) -> None:
        config = self._config()
        image = _image_lock()
        policy = SeccompPolicyLock(
            "asterion.prime-p1-seccomp-policy-lock/v1", image.platform,
            "SCMP_ARCH_X86_64", "sha256:" + "a" * 64,
            "1" * 64, "2" * 64, "3" * 64, "4" * 64, "5" * 64,
            "SCMP_ACT_ERRNO", (SeccompRuleAtom("read", ()),),
            hashlib.sha256(_SINGLE_READ_PROFILE).hexdigest(),
        )

        seccomp = AdmittedPrimeP1SeccompResource(
            (), "", (), policy, "c" * 64, threading.Lock(), [False], [False]
        )
        import asterion.applications.prime_agent.operator.authority_resources as module

        with (
            patch.object(module, "admit_static_image_resource", return_value=image),
            patch.object(module, "admit_static_seccomp_resource", return_value=seccomp),
        ):
            resources = admit_static_authority_resources(config)
        self.assertNotIn("sha256", repr(resources))
        resources.close()
        resources.close()
        self.assertTrue(seccomp._closed[0])

    def test_identity_is_deterministic_and_domain_binds_each_exact_digest(self) -> None:
        image = _image_lock()
        policy = SeccompPolicyLock(
            "asterion.prime-p1-seccomp-policy-lock/v1", image.platform,
            "SCMP_ARCH_X86_64", "sha256:" + "a" * 64,
            "1" * 64, "2" * 64, "3" * 64, "4" * 64, "5" * 64,
            "SCMP_ACT_ERRNO", (SeccompRuleAtom("read", ()),),
            hashlib.sha256(_SINGLE_READ_PROFILE).hexdigest(),
        )
        import asterion.applications.prime_agent.operator.authority_resources as module

        first = AdmittedPrimeP1SeccompResource(
            (), "", (), policy, "c" * 64, threading.Lock(), [False], [False]
        )
        second = AdmittedPrimeP1SeccompResource(
            (), "", (), policy, "c" * 64, threading.Lock(), [False], [False]
        )
        changed_profile = AdmittedPrimeP1SeccompResource(
            (), "", (), policy, "d" * 64, threading.Lock(), [False], [False]
        )
        self.assertEqual(
            module._static_authority_resource_identity(image, first).digest,
            module._static_authority_resource_identity(image, second).digest,
        )
        self.assertNotEqual(
            module._static_authority_resource_identity(image, first).digest,
            module._static_authority_resource_identity(image, changed_profile).digest,
        )

    def test_identity_matches_independent_literal_domain_and_raw_hashes(self) -> None:
        image = _image_lock()
        policy = SeccompPolicyLock(
            "asterion.prime-p1-seccomp-policy-lock/v1", image.platform,
            "SCMP_ARCH_X86_64", "sha256:" + "a" * 64,
            "1" * 64, "2" * 64, "3" * 64, "4" * 64, "5" * 64,
            "SCMP_ACT_ERRNO", (SeccompRuleAtom("read", ()),),
            hashlib.sha256(_SINGLE_READ_PROFILE).hexdigest(),
        )
        seccomp = AdmittedPrimeP1SeccompResource(
            (), "", (), policy, "c" * 64, threading.Lock(), [False], [False]
        )
        expected = hashlib.sha256(
            b"asterion.prime-p1.static-authority-resources/v1\0"
            + bytes.fromhex(
                "8a0f9cbfb18058e98e4d65cf935b7fcd200809b2482bf0b18c4f9fad10eb9395"
            )
            + bytes.fromhex(
                "50f7d82fdc8c1df9ca05b9c048a61439f7e9470c8d971b6d869955cfe85177f3"
            )
            + bytes.fromhex("c" * 64)
        ).hexdigest()
        import asterion.applications.prime_agent.operator.authority_resources as module

        self.assertEqual(expected, "871375e1568eeefc6d524d5c524fb910a34d05fb26c994e810041411a76c0cb4")
        self.assertEqual(
            module._static_authority_resource_identity(image, seccomp).digest, expected
        )

    def test_identity_changes_when_each_bound_input_hash_changes(self) -> None:
        image = _image_lock()
        policy = SeccompPolicyLock(
            "asterion.prime-p1-seccomp-policy-lock/v1", image.platform,
            "SCMP_ARCH_X86_64", "sha256:" + "a" * 64,
            "1" * 64, "2" * 64, "3" * 64, "4" * 64, "5" * 64,
            "SCMP_ACT_ERRNO", (SeccompRuleAtom("read", ()),),
            hashlib.sha256(_SINGLE_READ_PROFILE).hexdigest(),
        )
        import asterion.applications.prime_agent.operator.authority_resources as module

        def resource(profile_hash: str, lock: SeccompPolicyLock = policy) -> AdmittedPrimeP1SeccompResource:
            return AdmittedPrimeP1SeccompResource(
                (), "", (), lock, profile_hash, threading.Lock(), [False], [False]
            )

        baseline = module._static_authority_resource_identity(image, resource("c" * 64)).digest
        changed_image = replace(image, source_commit="0" * 39 + "1")
        changed_policy = replace(policy, build_input_sha256="7" * 64)
        self.assertNotEqual(
            baseline,
            module._static_authority_resource_identity(changed_image, resource("c" * 64)).digest,
        )
        self.assertNotEqual(
            baseline,
            module._static_authority_resource_identity(image, resource("c" * 64, changed_policy)).digest,
        )
        self.assertNotEqual(
            baseline,
            module._static_authority_resource_identity(image, resource("d" * 64)).digest,
        )

    def test_resource_set_close_calls_owned_child_once(self) -> None:
        config = self._config()
        image = _image_lock()
        policy = SeccompPolicyLock(
            "asterion.prime-p1-seccomp-policy-lock/v1", image.platform,
            "SCMP_ARCH_X86_64", "sha256:" + "a" * 64,
            "1" * 64, "2" * 64, "3" * 64, "4" * 64, "5" * 64,
            "SCMP_ACT_ERRNO", (SeccompRuleAtom("read", ()),),
            hashlib.sha256(_SINGLE_READ_PROFILE).hexdigest(),
        )
        seccomp = AdmittedPrimeP1SeccompResource(
            (), "", (), policy, "c" * 64, threading.Lock(), [False], [False]
        )
        import asterion.applications.prime_agent.operator.authority_resources as module

        with (
            patch.object(module, "admit_static_image_resource", return_value=image),
            patch.object(module, "admit_static_seccomp_resource", return_value=seccomp),
            patch.object(AdmittedPrimeP1SeccompResource, "close", autospec=True) as close,
        ):
            resources = admit_static_authority_resources(config)
            resources.close()
            resources.close()
        close.assert_called_once_with(seccomp)

    def test_constructor_failure_after_seccomp_transfer_closes_child_once(self) -> None:
        config = self._config()
        image = _image_lock()
        policy = SeccompPolicyLock(
            "asterion.prime-p1-seccomp-policy-lock/v1", image.platform,
            "SCMP_ARCH_X86_64", "sha256:" + "a" * 64,
            "1" * 64, "2" * 64, "3" * 64, "4" * 64, "5" * 64,
            "SCMP_ACT_ERRNO", (SeccompRuleAtom("read", ()),),
            hashlib.sha256(_SINGLE_READ_PROFILE).hexdigest(),
        )
        seccomp = AdmittedPrimeP1SeccompResource(
            (), "", (), policy, "c" * 64, threading.Lock(), [False], [False]
        )
        import asterion.applications.prime_agent.operator.authority_resources as module

        with (
            patch.object(module, "admit_static_image_resource", return_value=image),
            patch.object(module, "admit_static_seccomp_resource", return_value=seccomp),
            patch.object(module, "AdmittedStaticAuthorityResources", side_effect=MemoryError),
            patch.object(AdmittedPrimeP1SeccompResource, "close", autospec=True) as close,
            self.assertRaises(PrimeP1AuthorityResourceError),
        ):
            admit_static_authority_resources(config)
        close.assert_called_once_with(seccomp)

    def test_resource_set_rejects_direct_construction_without_private_token(self) -> None:
        policy = SeccompPolicyLock(
            "asterion.prime-p1-seccomp-policy-lock/v1",
            ImagePlatformDescriptor("linux", "amd64", None),
            "SCMP_ARCH_X86_64", "sha256:" + "a" * 64,
            "1" * 64, "2" * 64, "3" * 64, "4" * 64, "5" * 64,
            "SCMP_ACT_ERRNO", (SeccompRuleAtom("read", ()),),
            hashlib.sha256(_SINGLE_READ_PROFILE).hexdigest(),
        )
        seccomp = AdmittedPrimeP1SeccompResource(
            (), "", (), policy, "c" * 64, threading.Lock(), [False], [False]
        )
        with self.assertRaises(PrimeP1AuthorityResourceError):
            AdmittedStaticAuthorityResources(object(), seccomp)


if __name__ == "__main__":
    unittest.main()
