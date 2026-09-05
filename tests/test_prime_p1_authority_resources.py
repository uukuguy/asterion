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
    AdmittedStaticAuthorityResources,
    PrimeP1AuthorityResourceError,
    admit_static_authority_resources,
    admit_static_image_resource,
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
