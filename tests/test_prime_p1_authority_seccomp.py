"""Focused tests for static Prime P1 seccomp resource admission."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from asterion.applications.prime_agent.operator.authority_config import (
    load_operator_config,
)
from asterion.applications.prime_agent.operator.image_input_lock import (
    ImagePlatformDescriptor,
)
from asterion.applications.prime_agent.operator.seccomp_policy_lock import (
    PromotedSeccompPolicyCatalog,
    SeccompArgumentConstraint,
    SeccompPolicyLock,
    SeccompRuleAtom,
)


_PROFILE = (
    b'{"architectures":["SCMP_ARCH_X86_64"],"defaultAction":"SCMP_ACT_ERRNO",'
    b'"syscalls":[{"action":"SCMP_ACT_ALLOW","args":[],"names":["read"]}]}'
)


def _policy() -> SeccompPolicyLock:
    return SeccompPolicyLock(
        schema_version="asterion.prime-p1-seccomp-policy-lock/v1",
        platform=ImagePlatformDescriptor("linux", "amd64", None),
        libseccomp_architecture="SCMP_ARCH_X86_64",
        image_config_digest="sha256:" + "a" * 64,
        build_input_sha256="b" * 64,
        launcher_sha256="c" * 64,
        workload_sha256="d" * 64,
        starter_sha256="e" * 64,
        oracle_sha256="f" * 64,
        default_action="SCMP_ACT_ERRNO",
        allowed_rule_atoms=(
            SeccompRuleAtom("read", ()),
            SeccompRuleAtom(
                "write", (SeccompArgumentConstraint(0, "SCMP_CMP_EQ", 0, None),)
            ),
        ),
        maximum_profile_sha256="0" * 64,
    )


class TestPrimeP1AuthoritySeccomp(unittest.TestCase):
    def _config(
        self,
        root: Path,
        profile: Path,
        *,
        image_config_digest: str = "sha256:" + "a" * 64,
        profile_bytes: bytes = _PROFILE,
    ) -> object:
        values = {
            "ASTERION_PRIME_P1_DOCKER_EXECUTABLE": "/usr/bin/docker",
            "ASTERION_PRIME_P1_DOCKER_SOCKET": "/var/run/docker.sock",
            "ASTERION_PRIME_P1_SECCOMP_PROFILE": str(profile),
            "ASTERION_PRIME_P1_SECCOMP_PROFILE_SHA256": hashlib.sha256(profile_bytes).hexdigest(),
            "ASTERION_PRIME_P1_IMAGE_CONFIG_DIGEST": image_config_digest,
            "ASTERION_PRIME_P1_IMAGE_PLATFORM_OS": "linux",
            "ASTERION_PRIME_P1_IMAGE_PLATFORM_ARCHITECTURE": "amd64",
            "ASTERION_PRIME_P1_IMAGE_PLATFORM_VARIANT": "none",
            "ASTERION_PRIME_P1_MODEL_ID": "deepseek-chat",
            "ASTERION_PRIME_P1_EVIDENCE_ROOT": "/var/lib/asterion/evidence",
            "ASTERION_PRIME_P1_RECEIPT_KEY_ID": "p1-2026",
            "ASTERION_PRIME_P1_RECEIPT_HMAC_KEY": "b" * 64,
            "DEEPSEEK_API_KEY": "SECCOMP_SECRET_SENTINEL",
        }
        config_path = root / "operator.env"
        config_path.write_text("".join(f"{key}={value}\n" for key, value in values.items()))
        config_path.chmod(0o600)
        return load_operator_config(os.open(config_path, os.O_RDONLY | os.O_CLOEXEC))

    def test_empty_catalog_fails_before_profile_filesystem_access(self) -> None:
        from asterion.applications.prime_agent.operator.authority_seccomp import (
            PrimeP1AuthorityResourceError,
            admit_static_seccomp_resource,
        )

        with tempfile.TemporaryDirectory(dir=Path.cwd()) as temporary:
            root = Path(temporary)
            profile = root / "profile.json"
            profile.write_bytes(_PROFILE)
            profile.chmod(0o600)
            config = self._config(root, profile)
            import asterion.applications.prime_agent.operator.authority_seccomp as module

            with (
                patch.object(module.sys, "platform", "linux"),
                patch.object(module.os, "open", side_effect=AssertionError("filesystem")) as opened,
                self.assertRaises(PrimeP1AuthorityResourceError) as raised,
            ):
                admit_static_seccomp_resource(config)
        opened.assert_not_called()
        self.assertIsNone(raised.exception.__context__)
        self.assertNotIn("SECCOMP_SECRET_SENTINEL", str(raised.exception))

    def test_rejects_config_image_digest_before_profile_filesystem_access(self) -> None:
        from asterion.applications.prime_agent.operator.authority_seccomp import (
            PrimeP1AuthorityResourceError,
            admit_static_seccomp_resource,
        )
        import asterion.applications.prime_agent.operator.authority_seccomp as module
        import asterion.applications.prime_agent.operator.seccomp_policy_lock as catalog_module

        with tempfile.TemporaryDirectory(dir=Path.cwd()) as temporary:
            root = Path(temporary)
            profile = root / "profile.json"
            profile.write_bytes(_PROFILE)
            profile.chmod(0o600)
            config = self._config(root, profile, image_config_digest="sha256:" + "d" * 64)
            with (
                patch.object(module.sys, "platform", "linux"),
                patch.object(
                    catalog_module,
                    "PRIME_P1_PROMOTED_SECCOMP_POLICY_CATALOG",
                    PromotedSeccompPolicyCatalog((_policy(),)),
                ),
                patch.object(module.os, "open", side_effect=AssertionError("filesystem")) as opened,
                self.assertRaises(PrimeP1AuthorityResourceError) as raised,
            ):
                admit_static_seccomp_resource(config)
        opened.assert_not_called()
        self.assertIsNone(raised.exception.__context__)

    def test_admits_exact_canonical_profile_and_revalidates(self) -> None:
        from asterion.applications.prime_agent.operator.authority_seccomp import (
            AdmittedPrimeP1SeccompResource,
            admit_static_seccomp_resource,
            revalidate_static_seccomp_resource,
        )
        import asterion.applications.prime_agent.operator.seccomp_policy_lock as catalog_module
        import asterion.applications.prime_agent.operator.authority_seccomp as module

        with tempfile.TemporaryDirectory(dir=Path.cwd()) as temporary:
            root = Path(temporary)
            profile = root / "profile.json"
            profile.write_bytes(_PROFILE)
            profile.chmod(0o600)
            config = self._config(root, profile)
            with (
                patch.object(module.sys, "platform", "linux"),
                patch.object(
                    catalog_module,
                    "PRIME_P1_PROMOTED_SECCOMP_POLICY_CATALOG",
                    PromotedSeccompPolicyCatalog((_policy(),)),
                ),
            ):
                resource = admit_static_seccomp_resource(config)
                self.assertIsInstance(resource, AdmittedPrimeP1SeccompResource)
                self.assertEqual(resource.sha256, hashlib.sha256(_PROFILE).hexdigest())
                self.assertEqual(repr(resource), "AdmittedPrimeP1SeccompResource(redacted)")
                revalidate_static_seccomp_resource(resource)
                resource.close()

    def test_rejects_noncanonical_or_non_promoted_profile_atoms(self) -> None:
        from asterion.applications.prime_agent.operator.authority_seccomp import (
            PrimeP1AuthorityResourceError,
            admit_static_seccomp_resource,
        )
        import asterion.applications.prime_agent.operator.seccomp_policy_lock as catalog_module
        import asterion.applications.prime_agent.operator.authority_seccomp as module

        invalid = (
            _PROFILE + b" ",
            json.dumps(
                {
                    "architectures": ["SCMP_ARCH_X86_64"],
                    "defaultAction": "SCMP_ACT_ERRNO",
                    "syscalls": [
                        {"action": "SCMP_ACT_ALLOW", "args": [], "names": ["open"]}
                    ],
                }, separators=(",", ":"), sort_keys=True
            ).encode(),
            b'{"architectures":["SCMP_ARCH_X86_64"],"defaultAction":"SCMP_ACT_ERRNO",'
            b'"syscalls":[{"action":"SCMP_ACT_ALLOW","args":[],"names":["read"],"names":["read"]}]}',
        )
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as temporary:
            root = Path(temporary)
            profile = root / "profile.json"
            with (
                patch.object(module.sys, "platform", "linux"),
                patch.object(
                    catalog_module,
                    "PRIME_P1_PROMOTED_SECCOMP_POLICY_CATALOG",
                    PromotedSeccompPolicyCatalog((_policy(),)),
                ),
            ):
                for payload in invalid:
                    with self.subTest(payload=payload[:16]):
                        profile.write_bytes(payload)
                        profile.chmod(0o600)
                        config = self._config(root, profile, profile_bytes=payload)
                        with self.assertRaises(PrimeP1AuthorityResourceError) as raised:
                            admit_static_seccomp_resource(config)
                        self.assertIsNone(raised.exception.__context__)

    def test_revalidation_rejects_changed_bytes_and_closed_resource(self) -> None:
        from asterion.applications.prime_agent.operator.authority_seccomp import (
            PrimeP1AuthorityResourceError,
            admit_static_seccomp_resource,
            revalidate_static_seccomp_resource,
        )
        import asterion.applications.prime_agent.operator.seccomp_policy_lock as catalog_module
        import asterion.applications.prime_agent.operator.authority_seccomp as module

        with tempfile.TemporaryDirectory(dir=Path.cwd()) as temporary:
            root = Path(temporary)
            profile = root / "profile.json"
            profile.write_bytes(_PROFILE)
            profile.chmod(0o600)
            config = self._config(root, profile)
            with (
                patch.object(module.sys, "platform", "linux"),
                patch.object(
                    catalog_module,
                    "PRIME_P1_PROMOTED_SECCOMP_POLICY_CATALOG",
                    PromotedSeccompPolicyCatalog((_policy(),)),
                ),
            ):
                resource = admit_static_seccomp_resource(config)
                profile.write_bytes(_PROFILE + b" ")
                with self.assertRaises(PrimeP1AuthorityResourceError):
                    revalidate_static_seccomp_resource(resource)
                resource.close()
                with self.assertRaises(PrimeP1AuthorityResourceError):
                    revalidate_static_seccomp_resource(resource)

    def test_fifo_is_rejected_without_blocking(self) -> None:
        from asterion.applications.prime_agent.operator.authority_seccomp import (
            PrimeP1AuthorityResourceError,
            admit_static_seccomp_resource,
        )
        import asterion.applications.prime_agent.operator.seccomp_policy_lock as catalog_module
        import asterion.applications.prime_agent.operator.authority_seccomp as module

        with tempfile.TemporaryDirectory(dir=Path.cwd()) as temporary:
            root = Path(temporary)
            profile = root / "profile.fifo"
            os.mkfifo(profile, 0o600)
            config = self._config(root, profile, profile_bytes=b"fifo")
            with (
                patch.object(module.sys, "platform", "linux"),
                patch.object(
                    catalog_module,
                    "PRIME_P1_PROMOTED_SECCOMP_POLICY_CATALOG",
                    PromotedSeccompPolicyCatalog((_policy(),)),
                ),
                self.assertRaises(PrimeP1AuthorityResourceError) as raised,
            ):
                admit_static_seccomp_resource(config)
        self.assertIsNone(raised.exception.__context__)


if __name__ == "__main__":
    unittest.main()
